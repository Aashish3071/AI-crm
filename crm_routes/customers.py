"""Customers: converting a lead, the customer list and Customer 360° (client blueprint,
slide 18), and the lead-to-renewal lifecycle view.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

import pipecat_server as core

router = APIRouter()


@router.post("/api/leads/{id}/convert")
def convert_lead(id: str, payload: core.LeadConversionPayload):
    db = core.load_db()
    lead = core.require_visible(core._find_record(db.get("leads", []), id, "Lead"), core.visible_owners(db), "Lead")
    result = core._convert_lead(db, lead, payload)
    core.save_db(db)
    return result


@router.get("/api/customers")
def get_customers(search: Optional[str] = None):
    _db = core.load_db()
    items = core.scoped(_db.get("customers", []), core.visible_owners(_db))
    if search:
        q = search.lower()
        items = [c for c in items if q in c.get("name", "").lower() or q in c.get("organization", "").lower()]
    return items


@router.post("/api/customers")
def create_customer(item: Dict[str, Any]):
    if not str(item.get("name", "")).strip():
        raise HTTPException(status_code=422, detail="Customer name is required")
    db = core.load_db()
    email = str(item.get("email", "")).strip().lower(); mobile = str(item.get("mobile", "")).strip()
    duplicate = next((c for c in db.get("customers", []) if (email and c.get("email", "").lower() == email) or (mobile and core._same_phone(c.get("mobile"), mobile))), None)
    if duplicate:
        raise HTTPException(status_code=409, detail=f"A matching customer already exists: {duplicate.get('name')}")
    customer = {k: item.get(k, "") for k in ["name", "organization", "email", "mobile", "status", "assignedTo", "address", "gstNumber"]}
    customer.update({"id": f"CUS_{uuid.uuid4().hex[:8]}", "status": customer.get("status") or "Active",
                     "createdAt": datetime.utcnow().isoformat() + "Z"})
    organization = next((o for o in db.get("organizations", []) if o.get("name", "").lower() == customer.get("organization", "").lower()), None)
    if organization: customer["organizationId"] = organization["id"]
    db.setdefault("customers", []).insert(0, customer)
    if email or mobile:
        contact = {"id": f"C_{uuid.uuid4().hex[:8]}", "customerId": customer["id"], "name": customer["name"],
                   "email": email, "phone": mobile, "organization": customer.get("organization", ""),
                   "organizationId": customer.get("organizationId", ""), "designation": "Primary Contact",
                   "status": "Active", "isPrimary": True, "createdAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("contacts", []).insert(0, contact)
    core.audit(db, "Customer Created", "Customer", customer["id"], customer)
    core.save_db(db); return customer


@router.get("/api/customers/{id}")
def get_customer(id: str):
    db = core.load_db()
    customer = core.require_visible(core._find_record(db.get("customers", []), id, "Customer"), core.visible_owners(db), "Customer")
    contacts = [c for c in db.get("contacts", []) if c.get("customerId") == id]
    policies = [p for p in db.get("policies", []) if p.get("customerId") == id]
    policy_ids = {p.get("id") for p in policies}
    renewals = [r for r in db.get("renewals", []) if r.get("customerId") == id or r.get("policyId") in policy_ids]
    renewal_ids = {r.get("id") for r in renewals}
    # Slide 18 — one customer, one complete history: every lead that became this customer
    # (a car sale this year and a health enquiry next year are the same person).
    leads = [l for l in db.get("leads", []) if l.get("id") == customer.get("sourceLeadId") or l.get("convertedCustomerId") == id]
    lead_ids = {l.get("id") for l in leads}
    related_ids = {id, customer.get("sourceLeadId", ""), *lead_ids, *policy_ids, *renewal_ids} - {""}
    organization = next((o for o in db.get("organizations", []) if o.get("id") == customer.get("organizationId") or (customer.get("organization") and o.get("name", "").lower() == customer.get("organization", "").lower())), None)
    audits = [a for a in db.get("auditLogs", []) if a.get("entityId") in related_ids]
    srs = [s for s in db.get("serviceRequests", []) if s.get("customerId") == id]
    tasks = [t for t in db.get("tasks", []) if t.get("associatedId") in related_ids and t.get("status") != "Archived"]
    done = lambda t: t.get("status") == "Completed"
    # Insurance history: what they held before coming to us (recorded on the lead), then
    # our own policies that have ended.
    history = [{"source": "Before us", "leadId": l["id"], "product": l.get("product", ""), **(l.get("existingPolicy") or {})}
               for l in leads if any((l.get("existingPolicy") or {}).get(k) for k in ("insurer", "policyNumber", "expiryDate"))]
    history += [{"source": "With us", "policyId": p["id"], "product": p.get("policyType", ""), "insurer": p.get("insurer", ""),
                 "policyNumber": p.get("policyNumber", ""), "expiryDate": p.get("expiryDate", ""), "premium": p.get("netPremium", p.get("premium")),
                 "status": p.get("status", "")} for p in policies if p.get("status") in ("Expired", "Expired/Renewed", "Cancelled", "Lapsed")]
    return {**customer, "organizationRecord": organization, "contacts": contacts, "policies": policies,
            "leads": [{k: l.get(k) for k in ("id", "name", "product", "status", "source", "leadDate", "assignedTo")} for l in leads],
            "calls": sorted((core._call_view(db, c) for c in db.get("callLogs", []) if c.get("leadId") in lead_ids),
                            key=lambda c: c.get("startedAt") or c.get("createdAt") or "", reverse=True),
            "insuranceHistory": history,
            "followUps": {"upcoming": sorted((t for t in tasks if not done(t)), key=lambda t: (t.get("dueDate") or "9999", t.get("dueTime") or "")),
                          "completed": sorted((t for t in tasks if done(t)), key=lambda t: t.get("completedAt") or "", reverse=True)},
            "renewals": renewals, "quotations": [q for q in db.get("quotations", []) if q.get("renewalId") in renewal_ids or q.get("leadId") in lead_ids],
            "deals": [d for d in db.get("deals", []) if d.get("customerId") == id or d.get("leadId") == customer.get("sourceLeadId")],
            "tasks": tasks,
            "notes": [n for n in db.get("notes", []) if n.get("associatedId") in related_ids or n.get("leadId") == customer.get("sourceLeadId")],
            "documents": [d for d in db.get("documents", []) if d.get("associatedId") in related_ids],
            "communications": [c for c in db.get("communications", []) if c.get("associatedId") in related_ids],
            "calendarEvents": [e for e in db.get("calendarEvents", []) if e.get("associatedId") in related_ids or e.get("customerId") == id],
            "serviceRequests": srs,
            "auditHistory": audits}


@router.put("/api/customers/{id}")
def update_customer(id: str, updates: Dict[str, Any]):
    res = core.update_record("customers", id, updates, {"name","organization","email","mobile","status","assignedTo","address","gstNumber",
                                                   "city","preferences"}, "Customer")
    if "name" in updates:
        db = core.load_db()
        new_name = updates["name"]
        for p in db.get("policies", []):
            if p.get("customerId") == id:
                p["customerName"] = new_name
        for c in db.get("contacts", []):
            if c.get("customerId") == id and c.get("isPrimary"):
                c["name"] = new_name
        core.save_db(db)
    return res


@router.delete("/api/customers/{id}")
def delete_customer(id: str):
    db = core.load_db()
    customer = core.require_visible(core._find_record(db.get("customers", []), id, "Customer"), core.visible_owners(db), "Customer")
    db["customers"] = [c for c in db.get("customers", []) if c.get("id") != id]
    for sr in db.get("serviceRequests", []):
        if sr.get("customerId") == id:
            sr["status"] = "Archived"
            sr["archivedAt"] = datetime.utcnow().isoformat() + "Z"
    for end in db.get("endorsements", []):
        if end.get("customerId") == id:
            end["status"] = "Archived"
            end["archivedAt"] = datetime.utcnow().isoformat() + "Z"
    for contact in db.get("contacts", []):
        if contact.get("customerId") == id:
            contact["status"] = "Archived"
    for policy in db.get("policies", []):
        if policy.get("customerId") == id:
            policy["status"] = "Archived"
    core.audit(db, "Customer Deleted With Cascade", "Customer", id, {"name": customer.get("name")})
    core.save_db(db)
    return {"status": "success", "deletedId": id}


@router.get("/api/lifecycle/{lead_id}")
def get_lifecycle(lead_id: str):
    db=core.load_db(); lead=core.require_visible(core._find_record(db.get("leads",[]), lead_id, "Lead"), core.visible_owners(db), "Lead")
    customer=next((c for c in db.get("customers",[]) if c.get("sourceLeadId")==lead_id),None)
    policies=[p for p in db.get("policies",[]) if p.get("leadId")==lead_id or (customer and p.get("customerId")==customer.get("id"))]
    renewals=[r for r in db.get("renewals",[]) if r.get("policyId") in {p.get("id") for p in policies}]
    quotes=[q for q in db.get("quotations",[]) if q.get("renewalId") in {r.get("id") for r in renewals}]
    return {"lead":lead,"customer":customer,"policies":policies,"renewals":renewals,"quotations":quotes,
        "tasks":[t for t in db.get("tasks",[]) if t.get("associatedId")==lead_id],"communications":[c for c in db.get("communications",[]) if c.get("associatedId") in {lead_id, customer.get("id") if customer else ""}]}
