"""Commission (client blueprint, slide 25). Owner only.

Rates by product and insurer, fixed on each sale when it is sold, with corrections and
received-status kept per policy.
"""
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import pipecat_server as core

router = APIRouter()


# What the business earns on each policy, from rates the owner sets. A rate can name a
# product, an insurer, both, or neither; the most specific matching rate applies. The amount
# is fixed when the policy is sold, so changing a rate later does not rewrite past earnings.
COMMISSION_STATES = ["Expected", "Received"]


@router.get("/api/commission/rules")
def get_commission_rules():
    core._require_admin("Commission is visible to the owner only.")
    return {"rules": core._commission_rules(core.load_db())}


@router.put("/api/commission/rules")
def set_commission_rules(payload: Dict[str, Any]):
    core._require_admin("Only the owner can change commission rates.")
    db = core.load_db()
    rules = []
    for item in payload.get("rules") or []:
        clean = {"id": item.get("id") or f"COMR_{uuid.uuid4().hex[:6]}",
                 "product": (item.get("product") or "").strip(), "insurer": (item.get("insurer") or "").strip()}
        for key in ("newRate", "renewalRate"):
            value = item.get(key)
            if value in (None, ""):
                clean[key] = None
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="Commission rates are percentages, such as 12.5")
            if not 0 <= value <= 100:
                raise HTTPException(status_code=422, detail="Commission rates must be between 0 and 100%")
            clean[key] = value
        if clean["newRate"] is None and clean["renewalRate"] is None:
            raise HTTPException(status_code=422, detail="Give each rate line a new-business or renewal rate")
        rules.append(clean)
    keys = [(r["product"].lower(), r["insurer"].lower()) for r in rules]
    if len(keys) != len(set(keys)):
        raise HTTPException(status_code=422, detail="Two lines cover the same product and insurer")
    db.setdefault("settings", {}).setdefault("commission", {})["rules"] = rules
    core.audit(db, "Commission Rates Updated", "Commission", "rates", {"lines": len(rules)})
    core.save_db(db)
    return {"rules": rules}


@router.post("/api/commission/apply-missing")
def apply_missing_commission():
    """Policies sold before any rate existed have no commission; this applies today's rates to them."""
    core._require_admin("Only the owner can change commission.")
    db = core.load_db()
    applied = 0
    for policy in db.get("policies", []):
        if policy.get("saleDate") and (policy.get("commission") or {}).get("rate") is None:
            core._fix_commission(db, policy)
            applied += policy["commission"]["rate"] is not None
    core.audit(db, "Commission Applied", "Commission", "missing", {"policies": applied})
    core.save_db(db)
    return {"applied": applied}


@router.get("/api/commission")
def commission_ledger(month: Optional[str] = None):
    """Slide 25: commission per sale and per telecaller for a month."""
    core._require_admin("Commission is visible to the owner only.")
    db = core.load_db()
    month = core._checked_month(month, db)
    rows = []
    for policy in db.get("policies", []):
        if not (policy.get("saleDate") or "").startswith(month) or policy.get("status") == "Cancelled":
            continue
        c = policy.get("commission") or {}
        rows.append({"policyId": policy["id"], "policyNumber": policy.get("policyNumber") or "Draft",
                     "customerName": policy.get("customerName", ""), "employee": policy.get("assignedTo", ""),
                     "product": policy.get("policyType", ""), "insurer": policy.get("insurer", ""),
                     "premium": core.money_value(policy.get("netPremium", policy.get("premium", 0))), "saleDate": policy.get("saleDate"),
                     "basis": c.get("basis", "new"), "rate": c.get("rate"), "amount": c.get("amount"),
                     "status": c.get("status", "Expected"), "override": c.get("override", False), "note": c.get("note", "")})
    rows.sort(key=lambda r: r["saleDate"], reverse=True)
    people: Dict[str, Dict[str, float]] = {}
    for r in rows:
        p = people.setdefault(r["employee"] or "Unassigned", {"new": 0.0, "renewal": 0.0, "total": 0.0, "policies": 0, "unrated": 0})
        p["policies"] += 1
        if r["amount"] is None:
            p["unrated"] += 1
            continue
        p[r["basis"]] += r["amount"]
        p["total"] += r["amount"]
    return {"month": month, "rows": rows,
            "byEmployee": [{"employee": k, **{m: round(v, 2) if isinstance(v, float) else v for m, v in d.items()}} for k, d in sorted(people.items())],
            "totals": {"expected": round(sum(r["amount"] or 0 for r in rows if r["status"] == "Expected"), 2),
                       "received": round(sum(r["amount"] or 0 for r in rows if r["status"] == "Received"), 2),
                       "unrated": len([r for r in rows if r["amount"] is None])},
            "hasRates": bool(core._commission_rules(db))}


class CommissionUpdate(BaseModel):
    rate: Optional[float] = None
    amount: Optional[float] = None
    status: Optional[str] = None
    receivedOn: Optional[str] = ""
    note: Optional[str] = ""


@router.put("/api/policies/{id}/commission")
def update_policy_commission(id: str, payload: CommissionUpdate):
    """Correct one policy's commission, or record that it has been received."""
    core._require_admin("Only the owner can change commission.")
    db = core.load_db()
    policy = core._find_record(db.get("policies", []), id, "Policy")
    c = policy.setdefault("commission", {"basis": "renewal" if policy.get("previousPolicyId") else "new", "status": "Expected"})
    premium = core.money_value(policy.get("netPremium", policy.get("premium", 0)))
    if payload.rate is not None or payload.amount is not None:
        if not (payload.note or "").strip():
            raise HTTPException(status_code=422, detail="Say why the commission is being changed")
        if payload.rate is not None and not 0 <= payload.rate <= 100:
            raise HTTPException(status_code=422, detail="Commission rates must be between 0 and 100%")
        if payload.amount is not None and payload.amount < 0:
            raise HTTPException(status_code=422, detail="Commission cannot be negative")
        c["rate"] = payload.rate if payload.rate is not None else (round(payload.amount * 100 / premium, 3) if premium else None)
        c["amount"] = round(payload.amount if payload.amount is not None else premium * payload.rate / 100, 2)
        c.update({"override": True, "note": payload.note.strip()})
    if payload.status:
        if payload.status not in COMMISSION_STATES:
            raise HTTPException(status_code=422, detail=f"Status must be one of: {', '.join(COMMISSION_STATES)}")
        c["status"] = payload.status
        c["receivedOn"] = (core._parse_flexible_date(payload.receivedOn) or core._company_today(db)) if payload.status == "Received" else ""
    core.audit(db, "Commission Updated", "Policy", id, {"rate": c.get("rate"), "amount": c.get("amount"), "status": c.get("status")})
    core.save_db(db)
    return policy
