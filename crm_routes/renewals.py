"""Renewals (client blueprint, slides 23–24): the renewal records, their dashboard and report,
and completing a renewal into its successor policy.
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


class RenewalModel(BaseModel):
    policyId: str
    assignedTo: Optional[str] = None
    stage: Optional[str] = "Upcoming"
    targetPremium: Optional[float] = 0
    nextAction: Optional[str] = "Contact customer"
    nextActionDate: Optional[str] = ""


@router.get("/api/renewals")
def get_renewals(stage: Optional[str] = None):
    _db = core.load_db()
    renewals = core.scoped(_db.get("renewals", []), core.visible_owners(_db))
    for r in renewals:
        r["daysToExpiry"] = core._days_until(r.get("expiryDate") or "")
        r["ladderStage"] = core.renewal_stage(r["daysToExpiry"], r.get("stage", ""))
    return [r for r in renewals if not stage or r.get("stage") == stage]


@router.post("/api/renewals")
def create_renewal(payload: RenewalModel):
    db = core.load_db()
    policy = core._find_record(db.get("policies", []), payload.policyId, "Policy")
    if any(r.get("policyId") == payload.policyId and r.get("stage") not in ["Renewed", "Lost", "Lapsed"] for r in db.get("renewals", [])):
        raise HTTPException(status_code=409, detail="An active renewal already exists for this policy")
    item = payload.model_dump()
    item["assignedTo"] = payload.assignedTo or policy.get("assignedTo") or current_actor("")
    item.update({"id": f"REN_{uuid.uuid4().hex[:8]}", "customerName": policy.get("customerName"), "organization": policy.get("organization"),
                 "policyNumber": policy.get("policyNumber"), "expiryDate": policy.get("expiryDate"), "outcomeReason": "",
                 "createdAt": datetime.utcnow().isoformat() + "Z", "updatedAt": datetime.utcnow().isoformat() + "Z"})
    db.setdefault("renewals", []).insert(0, item)
    core.audit(db, "Renewal Created", "Renewal", item["id"], item)
    core.save_db(db)
    return item


@router.put("/api/renewals/{id}")
def update_renewal(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    renewal = core._find_record(db.get("renewals", []), id, "Renewal")
    allowed = {"assignedTo", "stage", "targetPremium", "nextAction", "nextActionDate", "selectedQuotationId", "outcomeReason"}
    sanitized = {k: v for k, v in updates.items() if k in allowed}
    transition_map = {"Upcoming":{"Due Soon","Contacted","Quotation Requested","Quotation Sent","Negotiation","Lost","Lapsed"}, "Due Soon":{"Contacted","Quotation Requested","Quotation Sent","Negotiation","Lost","Lapsed"},
                      "Contacted":{"Quotation Requested","Quotation Sent","Negotiation","Lost","Lapsed"},
                      "Quotation Requested":{"Quotation Sent","Negotiation","Lost","Lapsed"},
                      "Quotation Sent":{"Negotiation","Lost","Lapsed"}, "Negotiation":{"Quotation Sent","Lost","Lapsed"},
                      "Lost":set(), "Lapsed":set(), "Renewed":set()}
    requested_stage = sanitized.get("stage")
    if requested_stage == "Renewed": raise HTTPException(status_code=422, detail="Use Complete renewal to create the successor policy")
    if requested_stage and requested_stage != renewal.get("stage") and requested_stage not in transition_map.get(renewal.get("stage"), set()):
        raise HTTPException(status_code=422, detail=f"Renewal cannot move from {renewal.get('stage')} to {requested_stage}")
    if sanitized.get("stage") in ["Lost", "Lapsed"] and not sanitized.get("outcomeReason"):
        raise HTTPException(status_code=422, detail="An outcome reason is required for lost or lapsed renewals")
    if sanitized.get("selectedQuotationId"):
        quote_id = sanitized["selectedQuotationId"]
        quote = next((q for q in db.get("quotations", []) if q.get("id") == quote_id), None)
        if not quote:
            raise HTTPException(status_code=404, detail="Selected quotation not found")
        if quote.get("renewalId") != id:
            raise HTTPException(status_code=422, detail="Quotation does not belong to this renewal")
        if quote.get("validityDate"):
            today_str = datetime.now().strftime("%Y-%m-%d")
            if quote["validityDate"] < today_str:
                raise HTTPException(status_code=422, detail="Selected quotation has expired")
    renewal.update(sanitized)
    if sanitized.get("stage") in ("Lost", "Lapsed", "Renewed"):
        for n in db.get("notifications", []):
            if n.get("associatedId") == id:
                n["read"] = True
                n["resolvedAt"] = datetime.utcnow().isoformat() + "Z"
    if sanitized.get("selectedQuotationId"):
        renewal.setdefault("approvalHistory", []).append({"quotationId":sanitized["selectedQuotationId"], "action":"Selected", "actor":updates.get("actor","System"), "at":datetime.utcnow().isoformat()+"Z"})
    renewal["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Renewal Updated", "Renewal", id, sanitized)
    core.save_db(db)
    return renewal


@router.post("/api/renewals/{id}/complete")
def complete_renewal(id: str, payload: Dict[str, Any]):
    db = core.load_db(); renewal = core._find_record(db.get("renewals", []), id, "Renewal")
    if renewal.get("stage") == "Renewed" and (renewal.get("newPolicyId") or renewal.get("successorPolicyId")):
        succ_id = renewal.get("newPolicyId") or renewal.get("successorPolicyId")
        succ_policy = next((p for p in db.get("policies", []) if p.get("id") == succ_id), None)
        if succ_policy:
            old_pol = next((p for p in db.get("policies", []) if p.get("id") == renewal.get("policyId")), {})
            return {"success": True, "policyId": succ_id, "renewal": renewal, "previousPolicy": old_pol, "newPolicy": succ_policy}

    old_policy = core._find_record(db.get("policies", []), renewal.get("policyId"), "Policy")
    quote = core._find_record(db.get("quotations", []), renewal.get("selectedQuotationId", ""), "Selected quotation")
    required = [payload.get("policyNumber"), payload.get("startDate"), payload.get("expiryDate")]
    if not all(required): raise HTTPException(status_code=422, detail="New policy number, start date and expiry date are required")
    checklist = payload.get("documentChecklist", {})
    required_documents = {"proposalForm", "kyc", "payment", "schedule"}
    if not required_documents.issubset(checklist) or not all(checklist.get(key) is True for key in required_documents):
        raise HTTPException(status_code=422, detail="Complete every renewal issuance checklist item")
    new_policy = {**old_policy, "id": f"POL_{uuid.uuid4().hex[:8]}", "previousPolicyId": old_policy["id"], "policyNumber": payload["policyNumber"],
        "insurer": quote.get("insurer"), "premium": quote.get("premium"), "sumInsured": quote.get("sumInsured"), "startDate": payload["startDate"],
        "expiryDate": payload["expiryDate"], "status": "Active", "issuanceStatus": "Issued", "documentChecklist": checklist,
        "createdAt": datetime.utcnow().isoformat()+"Z", "updatedAt": datetime.utcnow().isoformat()+"Z"}
    new_policy.update(core.policy_financials(quote.get("premium"), old_policy.get("taxRate", 18))); new_policy["daysRemaining"] = core._days_until(new_policy["expiryDate"])
    old_policy.update({"status":"Expired/Renewed", "renewedToPolicyId":new_policy["id"]})
    renewal.update({"stage":"Renewed", "newPolicyId":new_policy["id"], "successorPolicyId":new_policy["id"], "completedAt":datetime.utcnow().isoformat()+"Z"})
    db.setdefault("policies", []).insert(0, new_policy)

    for note in db.get("notifications", []):
        if note.get("renewalId") == id or note.get("associatedId") == id:
            note["read"] = True
            note["resolved"] = True
            note["resolvedAt"] = datetime.utcnow().isoformat() + "Z"

    core.audit(db, "Renewal Completed", "Renewal", id, {"oldPolicyId":old_policy["id"], "newPolicyId":new_policy["id"], "quotationId":quote["id"]}, payload.get("actor","System"))
    core.save_db(db); return {"success": True, "policyId": new_policy["id"], "renewal":renewal, "previousPolicy":old_policy, "newPolicy":new_policy}


@router.post("/api/renewals/generate")
def generate_renewals(days: int = Query(60, ge=1, le=365)):
    db = core.load_db()
    created = core._open_due_renewals(db, days, core.scoped(db.get("policies", []), core.visible_owners(db)))
    core.save_db(db)
    return {"createdCount": len(created), "renewals": created}


@router.get("/api/renewals/dashboard")
def renewal_dashboard(month: Optional[str] = None):
    """Slide 24: renewals due this month and next, renewed, lost, the renewal rate and each
    telecaller's renewed and pending. The rate is renewed ÷ due this month."""
    db = core.load_db()
    month = core._checked_month(month, db)
    first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    following = (first.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
    renewals = core.scoped(db.get("renewals", []), core.visible_owners(db))
    due = [r for r in renewals if (r.get("expiryDate") or "").startswith(month)]
    renewed = [r for r in due if r.get("stage") == "Renewed"]
    lost = [r for r in due if r.get("stage") in ("Lost", "Lapsed")]
    people: Dict[str, Dict[str, int]] = {}
    for r in due:
        row = people.setdefault(r.get("assignedTo") or "Unassigned", {"renewed": 0, "lost": 0, "pending": 0})
        row["renewed" if r.get("stage") == "Renewed" else "lost" if r.get("stage") in ("Lost", "Lapsed") else "pending"] += 1
    ladder: Dict[str, int] = {}
    for r in renewals:
        if r.get("stage") not in core._CLOSED_RENEWAL:
            label = core.renewal_stage(core._days_until(r.get("expiryDate") or ""), r.get("stage", ""))
            if label:
                ladder[label] = ladder.get(label, 0) + 1
    return {"month": month, "dueThisMonth": len(due),
            "dueNextMonth": len([r for r in renewals if (r.get("expiryDate") or "").startswith(following)]),
            "renewed": len(renewed), "lost": len(lost), "pending": len(due) - len(renewed) - len(lost),
            "renewalRate": round(len(renewed) * 100 / len(due), 1) if due else None,
            "premiumRenewed": round(sum(core.money_value(r.get("targetPremium") or 0) for r in renewed), 2),
            "byEmployee": [{"person": k, **v} for k, v in sorted(people.items())],
            "ladder": [{"stage": label, "count": ladder.get(label, 0)} for label in
                       ["60 days", "30 days", "15 days", "7 days", "Renewal due today", "Expired — not renewed"]]}
