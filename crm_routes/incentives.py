"""Incentives, the leaderboard and Employee of the Month (client blueprint, slides 28–30).
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

import crm_metrics as metrics
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


@router.get("/api/incentives")
def get_incentives(month: Optional[str] = None):
    """Each person's incentive for a month under the owner's rules. An approved month is shown
    exactly as approved; the current month is an estimate that moves as sales happen."""
    db = core.load_db()
    month = core._checked_month(month, db)
    people = core._team_people(db, core.visible_owners(db))
    approved = (db.get("incentiveStatements") or {}).get(month)
    if approved:
        return {"month": month, "status": "Approved", "approvedBy": approved["approvedBy"], "approvedAt": approved["approvedAt"],
                "rows": [r for r in approved["rows"] if r["person"] in people], "rules": approved["rules"],
                "kinds": metrics.INCENTIVE_KINDS, "slabMeasures": metrics.SLAB_MEASURES}
    first, last = core._month_range(db, month)
    actual = core._measure(db, first, last, people)
    targets, headline = core._targets_for(db, month), core._headline_measure(db)
    rules = core._incentive_rules(db)
    rows = []
    for person in people:
        pct_ = metrics.achievement(actual[person], targets.get(person, {}), headline)["percent"]
        lines = metrics.incentive_lines(rules, actual[person], pct_)
        rows.append({"person": person, "lines": lines, "total": round(sum(l["amount"] for l in lines), 2),
                     "policiesSold": actual[person]["policiesSold"], "premium": actual[person]["premium"], "targetAchieved": pct_})
    return {"month": month, "through": last, "status": "Estimate", "rows": rows, "rules": rules,
            "kinds": metrics.INCENTIVE_KINDS, "slabMeasures": metrics.SLAB_MEASURES}


@router.put("/api/incentives/plan")
def set_incentive_plan(payload: Dict[str, Any]):
    """The owner's incentive rules, changeable at any time (slide 29)."""
    core._require_admin("Only the owner can change incentives.")
    db = core.load_db()
    rules = []
    for item in payload.get("rules") or []:
        kind = item.get("kind")
        if kind not in metrics.INCENTIVE_KINDS:
            raise HTTPException(status_code=422, detail=f"Each rule must be one of: {', '.join(metrics.INCENTIVE_KINDS.values())}")
        name = str(item.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=422, detail="Give each incentive rule a name")
        if item.get("product") and item.get("source"):
            raise HTTPException(status_code=422, detail="Limit a rule to a product or to a lead source, not both")
        rule = {"id": item.get("id") or f"INC_{uuid.uuid4().hex[:6]}", "name": name, "kind": kind,
                "enabled": bool(item.get("enabled", True)), "product": item.get("product") or "", "source": item.get("source") or ""}
        def number(key, low=0.0, high=None):
            try:
                value = float(item.get(key))
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"“{name}” needs a number for {key}")
            if value < low or (high is not None and value > high):
                raise HTTPException(status_code=422, detail=f"“{name}”: {key} is out of range")
            return value
        if kind == "per_policy":
            rule["amount"] = number("amount")
        elif kind == "premium_percent":
            rule["percent"] = number("percent", 0, 100)
        elif kind == "target_bonus":
            rule["amount"], rule["atPercent"] = number("amount"), number("atPercent", 1, 1000)
        elif kind == "slab":
            if item.get("measure") not in metrics.SLAB_MEASURES:
                raise HTTPException(status_code=422, detail=f"“{name}”: choose what the levels measure")
            slabs = sorted(({"from": float(sl.get("from")), "amount": float(sl.get("amount"))} for sl in item.get("slabs") or []
                            if sl.get("from") not in (None, "") and sl.get("amount") not in (None, "")), key=lambda sl: sl["from"])
            if not slabs or any(sl["from"] < 0 or sl["amount"] < 0 for sl in slabs):
                raise HTTPException(status_code=422, detail=f"“{name}” needs at least one level with a starting point and an amount")
            rule.update({"measure": item["measure"], "slabs": slabs})
        rules.append(rule)
    db["incentivePlan"] = {"rules": rules, "updatedBy": current_actor("System"), "updatedAt": datetime.utcnow().isoformat() + "Z"}
    core.audit(db, "Incentive Plan Updated", "Incentive", "plan", {"rules": len(rules)})
    core.save_db(db)
    return db["incentivePlan"]


@router.post("/api/incentives/{month}/approve")
def approve_incentives(month: str):
    """Freeze a finished month for payroll. Later sales or rule changes do not alter it."""
    core._require_admin("Only the owner can approve incentives.")
    db = core.load_db()
    month = core._checked_month(month, db)
    if month >= core._company_date(db).strftime("%Y-%m"):
        raise HTTPException(status_code=409, detail="A month can be approved once it has ended")
    if (db.get("incentiveStatements") or {}).get(month):
        raise HTTPException(status_code=409, detail="This month is already approved")
    statement = get_incentives(month)
    db.setdefault("incentiveStatements", {})[month] = {"rows": statement["rows"], "rules": statement["rules"],
                                                        "approvedBy": current_actor("System"), "approvedAt": datetime.utcnow().isoformat() + "Z"}
    core.audit(db, "Incentives Approved", "Incentive", month, {"total": round(sum(r["total"] for r in statement["rows"]), 2)})
    core.save_db(db)
    return get_incentives(month)


def _recognition_weights(db: Dict[str, Any]) -> Dict[str, float]:
    return (db.get("settings", {}).get("recognition", {}) or {}).get("weights") or dict(metrics.DEFAULT_WEIGHTS)


@router.get("/api/leaderboard")
def leaderboard(period: str = "month", start: Optional[str] = None, end: Optional[str] = None):
    db = core.load_db()
    try:
        first, last = metrics.period_bounds(period, core._company_date(db), start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    people = core._team_people(db, core.visible_owners(db))
    rows = core._measure(db, first, last, people)
    ranking = sorted(({"person": p, **{k: rows[p][k] for k in ("calls", "connected", "connectRate", "quotesSent", "policiesSold",
                                                               "premium", "conversionRate", "onTimeRate", "renewalsClosed")}}
                      for p in people), key=lambda r: (r["premium"], r["policiesSold"]), reverse=True)
    weights = _recognition_weights(db)
    month = first[:7]
    return {"period": {"name": period, "start": first, "end": last}, "ranking": ranking, "awards": metrics.awards(rows),
            "employeeOfMonth": {**metrics.scores(rows, weights), "weights": weights, "labels": metrics.WEIGHT_LABELS,
                                "announced": (db.get("recognition") or {}).get(month)},
            "minimums": {"newLeadsForConversion": metrics.MIN_LEADS_FOR_CONVERSION, "dueForDiscipline": metrics.MIN_DUE_FOR_DISCIPLINE}}


@router.put("/api/recognition/weights")
def set_recognition_weights(payload: Dict[str, Any]):
    core._require_admin("Only the owner can change how Employee of the Month is scored.")
    db = core.load_db()
    weights = {}
    for key, value in (payload.get("weights") or {}).items():
        if key not in metrics.WEIGHT_LABELS:
            raise HTTPException(status_code=422, detail=f"Unknown measure: {key}")
        try:
            value = float(value or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="Weights are numbers")
        if value < 0:
            raise HTTPException(status_code=422, detail="Weights cannot be negative")
        weights[key] = value
    if not any(v for k, v in weights.items() if k in metrics.AVAILABLE_FOR_SCORING):
        raise HTTPException(status_code=422, detail="Give weight to at least one measure the CRM can score")
    db.setdefault("settings", {}).setdefault("recognition", {})["weights"] = weights
    core.save_db(db)
    return {"weights": weights}


@router.post("/api/recognition/{month}/announce")
def announce_employee_of_month(month: str, payload: Dict[str, Any]):
    core._require_admin("Only the owner can announce Employee of the Month.")
    db = core.load_db()
    month = core._checked_month(month, db)
    person = payload.get("person", "")
    if person not in core._team_people(db, None):
        raise HTTPException(status_code=404, detail="That person isn't on the team")
    db.setdefault("recognition", {})[month] = {"person": person, "note": (payload.get("note") or "").strip(),
                                               "announcedBy": current_actor("System"), "announcedAt": datetime.utcnow().isoformat() + "Z"}
    core.audit(db, "Employee Of The Month Announced", "Recognition", month, {"person": person})
    core.save_db(db)
    return db["recognition"][month]
