"""Quotations (client blueprint, slide 20), on leads and on renewals.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import crm_metrics as metrics
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


class QuotationModel(BaseModel):
    renewalId: Optional[str] = None
    leadId: Optional[str] = None
    dealId: Optional[str] = None
    insurer: str
    premium: float
    product: Optional[str] = ""
    sumInsured: Optional[float] = 0
    coverageSummary: Optional[str] = ""
    deductible: Optional[float] = 0
    validityDate: Optional[str] = ""
    followUpDate: Optional[str] = ""
    status: Optional[str] = "Draft"
    assignedTo: Optional[str] = ""


def _quote_moves_lead(db: Dict[str, Any], quote: Dict[str, Any], status: str):
    """Sending a quote puts the lead at Quote Sent with a follow-up; acceptance moves it on
    to collecting documents. A lead already further along is not moved back."""
    lead = next((l for l in db.get("leads", []) if l.get("id") == quote.get("leadId")), None)
    if not lead or not core.is_open_lead(lead):
        return
    rank = metrics.furthest_stage({"status": core.canonical_status(lead.get("status"))})
    if status == "Sent" and rank <= metrics.FUNNEL.index("Quote Sent"):
        due = core._parse_flexible_date(quote.get("followUpDate") or "") or core._company_today(db, 2)
        core._set_lead_next(db, lead, "Quote Sent", f"Follow up on the {quote.get('insurer')} quotation with {lead.get('name')}", due)
    elif status == "Accepted" and rank < metrics.FUNNEL.index("Documents Pending"):
        missing = core.document_status(db, lead)["missing"]
        core._set_lead_next(db, lead, "Documents Pending", f"Collect documents from {lead.get('name')}"
                       + (f": {', '.join(missing)}" if missing else ""), core._company_today(db, 1))


@router.get("/api/quotations")
def get_quotations(renewalId: Optional[str] = None, leadId: Optional[str] = None, dealId: Optional[str] = None):
    db = core.load_db()
    core._expire_quotes(db)
    owners = core.visible_owners(db)
    ids = core.visible_ids(db, owners)
    quotes = [q for q in db.get("quotations", []) if core.child_visible(q, ids, owners)]
    if renewalId:
        quotes = [q for q in quotes if q.get("renewalId") == renewalId]
    if leadId:
        quotes = [q for q in quotes if q.get("leadId") == leadId]
    if dealId:
        quotes = [q for q in quotes if q.get("dealId") == dealId]
    return quotes


@router.post("/api/quotations")
def create_quotation(payload: QuotationModel):
    db = core.load_db()
    if not (payload.renewalId or payload.leadId or payload.dealId):
        raise HTTPException(status_code=422, detail="Quotation must link to at least one parent entity: renewalId, dealId, or leadId")
    owners = core.visible_owners(db)
    if payload.renewalId:
        parent = core.require_visible(core._find_record(db.get("renewals", []), payload.renewalId, "Renewal"), owners, "Renewal")
    elif payload.leadId:
        parent = core.require_visible(core._find_record(db.get("leads", []), payload.leadId, "Lead"), owners, "Lead")
    else:
        parent = core.require_visible(core._find_record(db.get("deals", []), payload.dealId, "Deal"), owners, "Deal")
    if payload.premium < 0 or (payload.sumInsured or 0) < 0:
        raise HTTPException(status_code=422, detail="Premium and cover cannot be negative")
    status = core.canonical_quote_status(payload.status)
    if status not in {"Draft", "Sent"}:
        raise HTTPException(status_code=422, detail="A new quotation starts as Draft or Sent")
    for field in ("validityDate", "followUpDate"):
        value = getattr(payload, field)
        if value and not core._parse_flexible_date(value):
            raise HTTPException(status_code=422, detail=f"{field} is not a valid date")
    item = payload.model_dump()
    now = datetime.utcnow().isoformat() + "Z"
    item.update({"id": f"QUO_{uuid.uuid4().hex[:8]}", "createdAt": now, "status": status,
                 "product": payload.product or parent.get("product") or parent.get("policyType", ""),
                 "assignedTo": payload.assignedTo or parent.get("assignedTo") or current_actor(""),
                 "validityDate": core._parse_flexible_date(payload.validityDate) if payload.validityDate else "",
                 "followUpDate": core._parse_flexible_date(payload.followUpDate) if payload.followUpDate else "",
                 "sentAt": now if status == "Sent" else "", "customerResponse": "",
                 "statusHistory": [{"status": status, "at": now, "by": current_actor("System")}]})
    if status == "Sent":
        _quote_moves_lead(db, item, "Sent")
    db.setdefault("quotations", []).insert(0, item)
    core.audit(db, "Quotation Created", "Quotation", item["id"], item)
    core.save_db(db)
    return item


@router.put("/api/quotations/{id}")
def update_quotation(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    quote = core.require_child_visible(db, core._find_record(db.get("quotations", []), id, "Quotation"), "Quotation")
    allowed = {"insurer", "premium", "sumInsured", "coverageSummary", "deductible", "validityDate", "status",
               "customerResponse", "followUpDate", "product"}
    changes={k:v for k,v in updates.items() if k in allowed}; before={k:quote.get(k) for k in changes}
    current = core.canonical_quote_status(quote.get("status"))
    if current == "Accepted" and set(changes) - {"customerResponse"}:
        raise HTTPException(status_code=409, detail="An accepted quotation is kept as it was accepted; add a new one to change it")
    if "status" in changes:
        wanted = core.canonical_quote_status(changes["status"])
        if wanted not in core.QUOTE_STATUSES:
            raise HTTPException(status_code=422, detail=f"Status must be one of: {', '.join(core.QUOTE_STATUSES)}")
        if wanted != current and wanted not in core.QUOTE_TRANSITIONS.get(current, set()):
            raise HTTPException(status_code=422, detail=f"A {current.lower()} quotation cannot become {wanted.lower()}")
        changes["status"] = wanted
        if wanted != current:
            now = datetime.utcnow().isoformat() + "Z"
            quote.setdefault("statusHistory", []).append({"status": wanted, "at": now, "by": current_actor("System")})
            if wanted == "Sent":
                quote["sentAt"] = now
            _quote_moves_lead(db, {**quote, **changes}, wanted)
    for field in ("premium", "sumInsured"):
        if field in changes and (changes[field] is None or float(changes[field]) < 0):
            raise HTTPException(status_code=422, detail="Premium and cover cannot be negative")
    quote.setdefault("versions", []).append({"version":len(quote.get("versions",[]))+1,"snapshot":before,"changedAt":datetime.utcnow().isoformat()+"Z","actor":current_actor()})
    quote.update(changes); quote["updatedAt"]=datetime.utcnow().isoformat()+"Z"
    core.audit(db, "Quotation Updated", "Quotation", id, {"before":before,"after":changes})
    core.save_db(db)
    return quote
