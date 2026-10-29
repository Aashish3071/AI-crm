"""Reports (client blueprint, slides 31–32): the sales funnel, lead sources and the
operations summary, for owners and managers.
"""
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException

import crm_metrics as metrics
import pipecat_server as core

router = APIRouter()


@router.get("/api/reports")
def get_reports(start: Optional[str] = None, end: Optional[str] = None, person: str = "", product: str = "", source: str = ""):
    """One cohort — the leads that arrived in the period — seen as a funnel, by source and by why
    leads were lost, so the three views always describe the same leads."""
    db = core.load_db()
    tz = core._calendar_timezone(db)
    today = core._company_date(db)
    first = start or today.replace(day=1).isoformat()
    last = end or today.isoformat()
    if not core._parse_flexible_date(first) or not core._parse_flexible_date(last) or first > last:
        raise HTTPException(status_code=422, detail="Choose a start date on or before the end date")
    owners = core.visible_owners(db)
    people = core._team_people(db, owners)
    if person and person not in people:
        raise HTTPException(status_code=404, detail="That person isn't on your team")
    visible = core.scoped(db.get("leads", []), owners)
    leads = metrics.cohort(visible, first, last, tz, person, product, source)
    undated = len([l for l in visible if not l.get("leadDate")])
    lost: Dict[str, int] = {}
    for lead in leads:
        if core.canonical_status(lead.get("status")) in core.REASON_REQUIRED:
            reason = lead.get("lostReason") or "Not recorded"
            lost[reason] = lost.get(reason, 0) + 1
    return {"period": {"start": first, "end": last}, "filters": {"person": person, "product": product, "source": source},
            "cohortSize": len(leads), "undatedLeads": undated,
            "funnel": metrics.funnel(leads, core.custom_stage_ranks()),
            "sources": metrics.by_source(leads, db.get("policies", []), core.money_value, core.custom_stage_ranks()),
            "lostReasons": sorted(({"reason": k, "count": v} for k, v in lost.items()), key=lambda r: r["count"], reverse=True),
            "options": {"people": people, "products": core._products(db),
                        "sources": sorted({l.get("source") or "Not recorded" for l in visible})}}


@router.get("/api/reports/operations")
def operations_report(start: Optional[str] = None, end: Optional[str] = None):
    db = core.load_db(); leads = db.get("leads", []); tasks = db.get("tasks", []); today = datetime.now().strftime("%Y-%m-%d")
    if start or end:
        def in_period(lead):
            d = (lead.get("createdAt") or lead.get("lastModified") or "")[:10]
            if start and d and d < start: return False
            if end and d and d > end: return False
            if not d and (start or end): return False
            return True
        leads = [l for l in leads if in_period(l)]
    stage_counts: Dict[str, int] = {}; lost_reasons: Dict[str, int] = {}; employee: Dict[str, Dict[str, int]] = {}
    by_source: Dict[str, int] = {}; by_product: Dict[str, int] = {}; premium_by_insurer: Dict[str, float] = {}
    for lead in leads:
        stage = core.canonical_status(lead.get("status")) or "Unknown"; stage_counts[stage] = stage_counts.get(stage, 0) + 1
        source = lead.get("source") or "Not recorded"; by_source[source] = by_source.get(source, 0) + 1
        product = lead.get("policyType") or "Not recorded"; by_product[product] = by_product.get(product, 0) + 1
        owner = lead.get("assignedTo", "Unassigned"); employee.setdefault(owner, {"leads":0,"won":0,"openTasks":0})["leads"] += 1
        if stage in core.SOLD_STATUSES: employee[owner]["won"] += 1
        if stage in core.REASON_REQUIRED: lost_reasons[lead.get("lostReason") or "Not recorded"] = lost_reasons.get(lead.get("lostReason") or "Not recorded", 0) + 1
    for task in tasks:
        if task.get("status") not in ["Completed", "Archived"]: employee.setdefault(task.get("assignedTo","Unassigned"), {"leads":0,"won":0,"openTasks":0})["openTasks"] += 1
    for policy in db.get("policies", []):
        insurer = policy.get("insurer") or "Not recorded"
        premium_by_insurer[insurer] = round(premium_by_insurer.get(insurer, 0) + core.money_value(policy.get("netPremium", policy.get("premium", 0))), 2)
    sold = sum(stage_counts.get(s, 0) for s in core.SOLD_STATUSES)
    closed = sum(stage_counts.get(s, 0) for s in core.CLOSED_STATUSES)
    conversion_rate = round(sold*100/len(leads), 1) if leads else 0
    return {"leadCount":len(leads), "conversionRate": conversion_rate, "winRate": round(sold*100/closed,1) if closed else 0, "byStage":stage_counts,
            "overdueTasks":len([t for t in tasks if t.get("status") not in ["Completed","Archived"] and t.get("dueDate") and t["dueDate"] < today]),
            "lostReasons":lost_reasons, "employeeActivity":employee, "byLeadSource": by_source,
            "byProduct": by_product, "premiumByInsurer": premium_by_insurer, "renewal":core.renewal_report()}
