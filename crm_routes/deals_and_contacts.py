"""Deals, contacts and organisations.

These modules are retired from navigation and search; their records and endpoints remain
so nothing is lost and the data can still be exported or restored.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


@router.get("/api/deals")
def get_deals(status: Optional[str] = None, stage: Optional[str] = None,
              customerId: Optional[str] = None, leadId: Optional[str] = None,
              search: Optional[str] = None):
    db = core.load_db()
    deals = core.scoped(db.get("deals", []), core.visible_owners(db))
    if status:
        deals = [d for d in deals if d.get("status") == status or d.get("stage") == status]
    if stage:
        deals = [d for d in deals if d.get("stage") == stage or d.get("status") == stage]
    if customerId:
        deals = [d for d in deals if d.get("customerId") == customerId]
    if leadId:
        deals = [d for d in deals if d.get("leadId") == leadId]
    if search:
        s = search.lower()
        deals = [d for d in deals if (
            s in d.get("organization", "").lower() or 
            s in d.get("dealName", "").lower() or
            s in d.get("title", "").lower() or
            s in d.get("email", "").lower()
        )]
    for d in deals:
        if not d.get("title") and d.get("dealName"):
            d["title"] = d["dealName"]
        if not d.get("dealName") and d.get("title"):
            d["dealName"] = d["title"]
        if not d.get("stage") and d.get("status"):
            d["stage"] = d["status"]
        if not d.get("status") and d.get("stage"):
            d["status"] = d["stage"]
    return deals


@router.post("/api/deals", status_code=201)
def create_deal(payload: core.DealModel):
    db = core.load_db()
    deal_title = payload.title or payload.dealName or "Commercial Insurance Opportunity"
    deal_stage = payload.stage or payload.status or "Open"
    item = payload.model_dump()
    deal_id = f"D_{uuid.uuid4().hex[:8]}"
    item.update({
        "id": deal_id,
        "title": deal_title,
        "dealName": deal_title,
        "stage": deal_stage,
        "status": deal_stage,
        "estimatedPremium": payload.estimatedPremium or (float(payload.annualRevenue) if str(payload.annualRevenue or "").replace(".", "", 1).isdigit() else 0),
        "annualRevenue": payload.annualRevenue or (f"₹ {payload.estimatedPremium:,.0f}" if payload.estimatedPremium else ""),
        "assignedTo": payload.assignedTo or current_actor(""),
        "createdAt": datetime.utcnow().isoformat() + "Z",
        "lastModified": datetime.utcnow().isoformat() + "Z",
        "updatedAt": datetime.utcnow().isoformat() + "Z"
    })
    if payload.customerId:
        customer = next((c for c in db.get("customers", []) if c.get("id") == payload.customerId), None)
        if customer:
            item.setdefault("organization", customer.get("organization", ""))
            item.setdefault("organizationId", customer.get("organizationId", ""))
    db.setdefault("deals", []).insert(0, item)
    core.audit(db, "Deal Created", "Deal", deal_id, item)
    core.save_db(db)
    return item


@router.put("/api/deals/{id}")
def update_deal(id: str, updates: Dict[str, Any]):
    return core.update_record("deals", id, updates, {"organization","organizationId","dealName","title","stage","annualRevenue","estimatedPremium","customerId","leadId","status","email","mobile","assignedTo","expectedCloseDate","probability","commissionRate","selectedQuotationId"}, "Deal")


@router.get("/api/contacts")
def get_contacts(search: Optional[str] = None):
    db = core.load_db()
    owners = core.visible_owners(db)
    ids, orgs = core.visible_ids(db, owners), core._visible_org_names(db, owners)
    contacts = [c for c in db.get("contacts", []) if core.contact_visible(c, ids, orgs)]
    if search:
        s = search.lower()
        contacts = [c for c in contacts if (
            s in c.get("name", "").lower() or 
            s in c.get("email", "").lower() or 
            s in c.get("organization", "").lower()
        )]
    return contacts


@router.put("/api/contacts/{id}")
def update_contact(id: str, updates: Dict[str, Any]):
    return core.update_record("contacts", id, updates, {"name","email","phone","organization","designation","status","isPrimary","isDecisionMaker"}, "Contact")


@router.get("/api/organizations")
def get_organizations(search: Optional[str] = None):
    db = core.load_db()
    names = core._visible_org_names(db, core.visible_owners(db))
    orgs = [o for o in db.get("organizations", []) if names is None or (o.get("name") or "").strip().lower() in names]
    if search:
        s = search.lower()
        orgs = [o for o in orgs if (
            s in o.get("name", "").lower() or 
            s in o.get("industry", "").lower()
        )]
    return orgs


@router.put("/api/organizations/{id}")
def update_organization(id: str, updates: Dict[str, Any]):
    res = core.update_record("organizations", id, updates, {"name","website","industry","annualRevenue","territory","noOfEmployees","address","gstNumber","assignedTo","status"}, "Organization")
    if "name" in updates:
        db = core.load_db()
        new_name = updates["name"]
        for c in db.get("customers", []):
            if c.get("organizationId") == id:
                c["organization"] = new_name
        for p in db.get("policies", []):
            if p.get("organizationId") == id:
                p["organization"] = new_name
        core.save_db(db)
    return res


ORGANIZATION_FIELDS = {"name", "website", "industry", "annualRevenue", "territory",
                       "noOfEmployees", "address", "gstNumber", "assignedTo", "status"}


CONTACT_FIELDS = {"name", "email", "phone", "organization", "designation", "status",
                  "leadId", "customerId", "isPrimary", "isDecisionMaker"}


@router.post("/api/organizations")
def create_organization(item: Dict[str, Any]):
    if not item.get("name"): raise HTTPException(status_code=422, detail="Organization name is required")
    # Only accept known fields, so a caller can't stash arbitrary data on a record.
    clean = {k: v for k, v in item.items() if k in ORGANIZATION_FIELDS}
    db = core.load_db(); clean.update({"id": f"O_{uuid.uuid4().hex[:8]}", "createdAt": datetime.utcnow().isoformat() + "Z"})
    db.setdefault("organizations", []).insert(0, clean); core.audit(db,"Organization Created","Organization",clean["id"],clean); core.save_db(db); return clean


@router.post("/api/contacts")
def create_contact(item: Dict[str, Any]):
    if not item.get("name"): raise HTTPException(status_code=422, detail="Contact name is required")
    db = core.load_db()
    if item.get("customerId"):
        if not any(c.get("id") == item["customerId"] for c in db.get("customers", [])):
            raise HTTPException(status_code=422, detail="Referenced customer does not exist")
    if item.get("organizationId"):
        if not any(o.get("id") == item["organizationId"] for o in db.get("organizations", [])):
            raise HTTPException(status_code=422, detail="Referenced organization does not exist")
    if item.get("leadId"):
        if not any(l.get("id") == item["leadId"] for l in db.get("leads", [])):
            raise HTTPException(status_code=422, detail="Referenced lead does not exist")
    clean = {k: v for k, v in item.items() if k in CONTACT_FIELDS}
    clean.update({"id": f"C_{uuid.uuid4().hex[:8]}", "createdAt": datetime.utcnow().isoformat() + "Z"})
    db.setdefault("contacts", []).insert(0, clean); core.audit(db,"Contact Created","Contact",clean["id"],clean); core.save_db(db); return clean
