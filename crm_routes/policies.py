"""Policies: creation, issuance with evidence, edits, service requests and endorsements.
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


class PolicyModel(BaseModel):
    leadId: Optional[str] = ""
    customerId: Optional[str] = ""
    organizationId: Optional[str] = ""
    customerName: str
    organization: Optional[str] = ""
    policyType: str
    policyNumber: Optional[str] = ""
    insurer: Optional[str] = ""
    sumInsured: Optional[float] = None
    premium: Optional[float] = 0
    taxRate: Optional[float] = 18
    startDate: Optional[str] = ""
    expiryDate: str
    status: Optional[str] = "Draft"
    issuanceStatus: Optional[str] = "Pending Documents"
    assignedTo: Optional[str] = None


@router.post("/api/policies/{id}/issue")
def issue_policy(id: str, payload: Dict[str, Any]):
    db = core.load_db(); policy = core._find_record(db.get("policies", []), id, "Policy")
    checklist = payload.get("documentChecklist") or payload.get("checklist") or {}
    policy_number = payload.get("policyNumber") or policy.get("policyNumber") or f"POL-{uuid.uuid4().hex[:8].upper()}"
    insurer = payload.get("insurer") or policy.get("insurer") or "New India Assurance"
    start_date = payload.get("startDate") or policy.get("startDate") or datetime.utcnow().strftime("%Y-%m-%d")
    expiry_date = payload.get("expiryDate") or policy.get("expiryDate") or (datetime.utcnow() + timedelta(days=365)).strftime("%Y-%m-%d")
    required_documents = {"proposalForm", "kyc", "payment", "schedule"}
    if not required_documents.issubset(checklist) or not all(checklist.get(key) is True for key in required_documents):
        raise HTTPException(status_code=422, detail="Complete every required document checklist item before issuance")
    policy_docs = [d for d in db.get("documents", []) if (d.get("associatedId") == id or d.get("policyId") == id)
                   and d.get("status") != "Archived" and d.get("verification") != "Rejected"]
    if not policy_docs:
        raise HTTPException(status_code=422, detail="Uploaded document evidence files in storage are required for all checklist items before issuance")
    for req in required_documents:
        # Evidence is matched by what the document is, not by words in its file name.
        wanted = core.ISSUANCE_EVIDENCE[req]
        if not any(d.get("docType") == req or core._checked_document_type_quiet(d.get("category")) == wanted for d in policy_docs):
            raise HTTPException(status_code=422, detail=f"Upload the {wanted} before issuing this policy")
    policy.update({"policyNumber": policy_number, "insurer": insurer, "startDate": start_date, "expiryDate": expiry_date,
                   "documentChecklist": checklist, "status": "Active", "issuanceStatus": "Issued", "issuedAt": datetime.utcnow().isoformat() + "Z", "updatedAt": datetime.utcnow().isoformat() + "Z"})
    core.audit(db, "Policy Issued", "Policy", id, {"policyNumber": policy_number}, payload.get("actor", current_actor()))
    core.save_db(db); return policy


@router.get("/api/policies")
def get_policies(leadId: Optional[str] = None, status: Optional[str] = None):
    _db = core.load_db()
    policies = core.scoped(core.live_expiry_inplace(_db.get("policies", [])), core.visible_owners(_db))
    if leadId:
        policies = [p for p in policies if p.get("leadId") == leadId]
    if status:
        policies = [p for p in policies if p.get("status") == status]
    return policies


@router.post("/api/policies")
def create_policy(payload: PolicyModel):
    db = core.load_db()
    item = payload.model_dump()
    item["assignedTo"] = payload.assignedTo or current_actor("")
    if not payload.customerId:
        raise HTTPException(status_code=422, detail="Select a customer before creating a policy")
    customer = core._find_record(db.get("customers", []), payload.customerId, "Customer")
    configured_products = db.get("settings", {}).get("crm", {}).get("insuranceProducts", [])
    if configured_products and payload.policyType not in configured_products:
        raise HTTPException(status_code=422, detail=f"Policy type '{payload.policyType}' is not among configured insurance products")
    if payload.premium is not None and payload.premium < 0:
        raise HTTPException(status_code=422, detail="Premium cannot be negative")
    if payload.sumInsured is not None and payload.sumInsured <= 0:
        raise HTTPException(status_code=422, detail="Sum insured must be greater than zero")
    if payload.startDate and payload.expiryDate and payload.startDate > payload.expiryDate:
        raise HTTPException(status_code=422, detail="Policy startDate cannot be after expiryDate")
    item.update({"customerName": customer.get("name", payload.customerName), "organization": customer.get("organization", payload.organization),
                 "organizationId": customer.get("organizationId", payload.organizationId)})
    item.update(core.policy_financials(payload.premium, payload.taxRate))
    item.update({"id": f"POL_{uuid.uuid4().hex[:8]}", "daysRemaining": core._days_until(payload.expiryDate), "createdAt": datetime.utcnow().isoformat() + "Z", "updatedAt": datetime.utcnow().isoformat() + "Z"})
    db.setdefault("policies", []).insert(0, item)
    core.audit(db, "Policy Created", "Policy", item["id"], item)
    core.save_db(db)
    return item


@router.post("/api/policies/migrate-leads")
def migrate_lead_policies():
    """One-time compatibility bridge for policy fields stored on legacy lead records."""
    db = core.load_db()
    existing_leads = {p.get("leadId") for p in db.get("policies", [])}
    created = []
    for lead in db.get("leads", []):
        if lead.get("id") in existing_leads or not lead.get("policyType"):
            continue
        premium_digits = "".join(c for c in str(lead.get("premium", "0")) if c.isdigit())
        item = {"id": f"POL_{uuid.uuid4().hex[:8]}", "leadId": lead.get("id"), "organizationId": "",
                "customerName": lead.get("name", ""), "organization": lead.get("organization", ""),
                "policyType": lead.get("product") or lead.get("policyType", ""), "policyNumber": lead.get("policyNumber", ""),
                "insurer": lead.get("insurer", ""), "sumInsured": 0, "premium": float(premium_digits or 0), "startDate": "",
                "expiryDate": lead.get("expiryDate", ""), "status": "Active", "issuanceStatus": "Issued",
                "assignedTo": lead.get("assignedTo", ""), "createdAt": datetime.utcnow().isoformat() + "Z",
                "updatedAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("policies", []).append(item)
        created.append(item)
    core.audit(db, "Policies Migrated From Leads", "Policy", "bulk", {"createdCount": len(created), "policyIds": [p["id"] for p in created]})
    core.save_db(db)
    return {"createdCount": len(created), "policies": created}


@router.put("/api/policies/{id}")
def update_policy(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    policy = core._find_record(db.get("policies", []), id, "Policy")
    allowed = {"policyNumber", "insurer", "sumInsured", "premium", "taxRate", "startDate", "expiryDate", "status", "assignedTo", "policyType"}
    if updates.get("status") in ("Active", "Issued"):
        raise HTTPException(status_code=422, detail="Direct activation via PUT is forbidden. Use POST /api/policies/{id}/issue")
    if updates.get("status") not in {None, "Draft", "Data Review", "Active", "Cancelled", "Expired/Renewed"}:
        raise HTTPException(status_code=422, detail="Unsupported policy status")
    if "premium" in updates and updates["premium"] is not None and updates["premium"] < 0:
        raise HTTPException(status_code=422, detail="Premium cannot be negative")
    if "sumInsured" in updates and updates["sumInsured"] is not None and updates["sumInsured"] <= 0:
        raise HTTPException(status_code=422, detail="Sum insured must be greater than zero")
    s_date = updates.get("startDate", policy.get("startDate"))
    e_date = updates.get("expiryDate", policy.get("expiryDate"))
    if s_date and e_date and s_date > e_date:
        raise HTTPException(status_code=422, detail="Policy startDate cannot be after expiryDate")
    if "policyType" in updates:
        configured_products = db.get("settings", {}).get("crm", {}).get("insuranceProducts", [])
        if configured_products and updates["policyType"] not in configured_products:
            raise HTTPException(status_code=422, detail=f"Policy type '{updates['policyType']}' is not among configured insurance products")
    policy.update({k: v for k, v in updates.items() if k in allowed})
    if "premium" in updates or "taxRate" in updates: policy.update(core.policy_financials(policy.get("premium"), updates.get("taxRate", policy.get("taxRate", 18))))
    policy["daysRemaining"] = core._days_until(policy.get("expiryDate", ""))
    policy["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Policy Updated", "Policy", id, {k: updates[k] for k in updates if k in allowed})
    core.save_db(db)
    return policy


class ServiceRequestModel(BaseModel):
    customerId: str
    policyId: Optional[str] = ""
    requestType: str
    description: str
    priority: Optional[str] = "Medium"
    dueDate: Optional[str] = ""
    assignedTo: Optional[str] = ""


@router.get("/api/service-requests")
def get_service_requests(customerId: Optional[str] = None, policyId: Optional[str] = None, status: Optional[str] = None):
    items = core.load_db().get("serviceRequests", [])
    return [item for item in items if (not customerId or item.get("customerId") == customerId)
            and (not policyId or item.get("policyId") == policyId) and (not status or item.get("status") == status)]


@router.post("/api/service-requests")
def create_service_request(payload: ServiceRequestModel):
    allowed_types = {"Endorsement", "Claim Assistance", "Certificate", "Policy Document", "Cancellation", "Reinstatement", "Other"}
    if payload.requestType not in allowed_types: raise HTTPException(status_code=422, detail="Unsupported service request type")
    db = core.load_db(); customer = core._find_record(db.get("customers", []), payload.customerId, "Customer")
    policy = None
    if payload.policyId:
        policy = core._find_record(db.get("policies", []), payload.policyId, "Policy")
        if policy.get("customerId") != customer.get("id"): raise HTTPException(status_code=422, detail="Policy does not belong to this customer")
    item = payload.model_dump(); item.update({"id": f"SR_{uuid.uuid4().hex[:8]}", "status": "Open",
        "customerName": customer.get("name"), "policyNumber": policy.get("policyNumber") if policy else "", "createdAt": datetime.utcnow().isoformat()+"Z"})
    db.setdefault("serviceRequests", []).insert(0,item)
    if payload.requestType == "Endorsement":
        db.setdefault("endorsements", []).insert(0,{"id":f"END_{uuid.uuid4().hex[:8]}","serviceRequestId":item["id"],
            "customerId":payload.customerId,"policyId":payload.policyId or "","description":payload.description,"status":"Requested",
            "createdAt":datetime.utcnow().isoformat()+"Z"})
    core.audit(db,"Service Request Created","Service Request",item["id"],item); core.save_db(db); return item


@router.put("/api/service-requests/{id}")
def update_service_request(id: str, updates: Dict[str, Any]):
    db = core.load_db(); item = core._find_record(db.get("serviceRequests", []), id, "Service request")
    allowed = {"status", "priority", "dueDate", "assignedTo", "description", "outcome", "resolution"}
    changes = {k: v for k, v in updates.items() if k in allowed}
    if changes.get("status") not in {None, "Open", "In Progress", "Waiting on Client", "Waiting on Insurer", "Completed", "Cancelled"}:
        raise HTTPException(status_code=422, detail="Unsupported service status")
    if changes.get("status") in ("Completed", "Resolved"):
        outcome = (updates.get("outcome") or updates.get("resolution") or item.get("outcome") or item.get("resolution") or "").strip()
        if not outcome and item.get("requestType") == "Endorsement":
            outcome = "Endorsement processed and completed"
        if not outcome:
            raise HTTPException(status_code=422, detail="Resolution outcome is mandatory when completing a service request")
        item["outcome"] = outcome
        item["resolvedAt"] = datetime.utcnow().isoformat() + "Z"
        for end in db.get("endorsements", []):
            if end.get("serviceRequestId") == id or (item.get("policyId") and end.get("policyId") == item["policyId"]):
                end["status"] = "Completed"
                end["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    before = {k: item.get(k) for k in changes}; item.update(changes); item["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Service Request Updated", "Service Request", id, {"before": before, "after": changes}); core.save_db(db); return item


@router.get("/api/endorsements")
def get_endorsements(policyId: Optional[str] = None):
    return [item for item in core.load_db().get("endorsements",[]) if not policyId or item.get("policyId")==policyId]
