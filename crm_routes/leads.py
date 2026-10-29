"""Leads (client blueprint, slide 11): the list, a lead's card, creation, edits, stage
changes, archive and restore, duplicates and merging, and saved list views.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import crm_schema
import crm_security
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


@router.get("/api/leads")
def get_leads(status: Optional[str] = None, search: Optional[str] = None, assignedTo: Optional[str] = None,
              priority: Optional[str] = None, product: Optional[str] = None,
              filter: Optional[str] = None, page: int = Query(1, ge=1), pageSize: int = Query(50, ge=1, le=200),
              paginated: bool = False, customField: Optional[str] = None, customOp: str = "is",
              customValue: Optional[str] = None):
    db = core.load_db()
    custom_defs = core.custom_field_defs(db)
    custom_filter = None
    if customField:
        custom_filter = next((d for d in custom_defs if d["key"] == customField), None)
        if not custom_filter:
            raise HTTPException(status_code=422, detail=f"'{customField}' is not a field")
        try:
            crm_schema.check_condition(custom_filter, customOp, customValue)
        except crm_schema.SchemaError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    leads = core.scoped(core.live_expiry_inplace(db.get("leads", [])), core.visible_owners(db))
    for l in leads:
        if not l.get("leadPriority"):
            l["leadPriority"] = core.calculate_lead_priority(l)
    if status:
        leads = [l for l in leads if l.get("status") == status]
    if assignedTo:
        leads = [l for l in leads if l.get("assignedTo") == assignedTo]
    if priority:
        p_up = priority.upper()
        leads = [l for l in leads if (l.get("leadPriority") or "").upper() == p_up or (l.get("priority") or "").upper() == p_up]
    if product:
        p_prod = product.lower()
        leads = [l for l in leads if (l.get("product") or l.get("policyType") or "").lower() == p_prod]
    if filter == "expiring_soon":
        leads = [l for l in leads if core._expiring_within(l, 15)]
    elif filter == "due_today":
        today_str = datetime.now().strftime("%Y-%m-%d")
        leads = [l for l in leads if l.get("nextActionDate") == today_str]
    elif filter == "overdue":
        today_str = datetime.now().strftime("%Y-%m-%d")
        leads = [l for l in leads if l.get("nextActionDate") and l.get("nextActionDate") < today_str and not l.get("nextActionCompleted")]
    elif filter == "hot":
        leads = [l for l in leads if l.get("leadPriority") == "HOT"]
    elif filter == "warm":
        leads = [l for l in leads if l.get("leadPriority") == "WARM"]
    elif filter == "cold":
        leads = [l for l in leads if l.get("leadPriority") == "COLD"]
        
    if custom_filter:
        leads = [l for l in leads if crm_schema.matches(custom_filter, (l.get("custom") or {}).get(customField),
                                                         customOp, customValue)]
    if search:
        s = search.lower()
        searchable = [d for d in custom_defs if d["type"] in ("text", "long_text", "phone", "email")]
        leads = [l for l in leads if (
            s in l.get("name", "").lower() or 
            s in l.get("email", "").lower() or 
            s in l.get("organization", "").lower() or
            s in l.get("mobile", "").lower() or
            s in l.get("policyType", "").lower() or
            s in (l.get("product") or "").lower() or
            s in (l.get("city") or "").lower() or
            any(s in str((l.get("custom") or {}).get(d["key"]) or "").lower() for d in searchable)
        )]
    if not paginated:
        return leads
    start = (page - 1) * pageSize
    return {"items": leads[start:start + pageSize], "page": page, "pageSize": pageSize,
            "total": len(leads), "totalPages": max(1, (len(leads) + pageSize - 1) // pageSize)}


@router.get("/api/leads/{id}")
def get_single_lead(id: str):
    db = core.load_db()
    lead = next((l for l in db.get("leads", []) if l["id"] == id), None)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    core.require_visible(lead, core.visible_owners(db), "Lead")
    notes = [n for n in db.get("notes", []) if n.get("associatedId") == id or n.get("leadId") == id]
    tasks = [t for t in db.get("tasks", []) if t.get("associatedId") == id]
    return {"lead": core.live_expiry(lead), "notes": notes, "tasks": tasks, "documentStatus": core.document_status(db, lead)}


class StageTransitionPayload(BaseModel):
    status: str
    nextAction: Optional[str] = ""
    nextActionDate: Optional[str] = ""
    nextActionTime: Optional[str] = ""
    stageNote: Optional[str] = ""
    lostReason: Optional[str] = ""
    author: Optional[str] = None      # ignored: the audit records whoever is signed in


@router.put("/api/leads/{id}/stage")
def transition_lead_stage(id: str, payload: StageTransitionPayload):
    db = core.load_db()
    lead = next((l for l in db.get("leads", []) if l["id"] == id), None)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    core.require_visible(lead, core.visible_owners(db), "Lead")

    old_stage = core.canonical_status(lead.get("status", "New"))
    new_stage = core._checked_status_change(lead, payload.status, payload.lostReason or "",
                                       payload.nextAction or "", payload.nextActionDate or "")
    finished = new_stage in core.NO_NEXT_ACTION
    due = "" if finished else core._parse_flexible_date(payload.nextActionDate or "")
    due_time = "" if finished else core._checked_time(payload.nextActionTime)
    now_str = datetime.utcnow().isoformat() + "Z"

    lead["status"] = new_stage
    lead["nextAction"] = "" if finished else payload.nextAction
    lead["nextActionDate"] = due
    lead["nextActionTime"] = due_time
    lead["nextActionCompleted"] = finished
    lead["lastModified"] = now_str
    if payload.lostReason:
        lead["lostReason"] = payload.lostReason

    next_step = "No further action." if finished else f"Next: '{payload.nextAction}' due {due}."
    db.setdefault("notes", []).insert(0, {
        "id": f"N{len(db.get('notes', [])) + 1}_{uuid.uuid4().hex[:4]}",
        "title": f"Status: {old_stage} → {new_stage}",
        "associatedType": "Lead", "associatedId": id, "associatedTitle": lead.get("name"),
        "category": "Stage Progression",
        "content": (payload.stageNote or "").strip() or f"Status changed from '{old_stage}' to '{new_stage}'. {next_step}"
                   + (f" Reason: {payload.lostReason}." if payload.lostReason else ""),
        "author": current_actor("System"), "pinned": False, "createdAt": now_str})

    # Close the previous canonical follow-up before provisioning the next one.
    previous_task = next((t for t in db.get("tasks", []) if t.get("id") == lead.get("nextActionTaskId")), None)
    if previous_task and previous_task.get("status") not in ["Completed", "Archived"]:
        previous_task["status"] = "Completed"
        previous_task["completedAt"] = now_str

    if not finished:
        next_task = {
            "id": f"T{len(db.get('tasks', [])) + 1}_{uuid.uuid4().hex[:4]}",
            "title": payload.nextAction, "associatedType": "Lead", "associatedId": id,
            "associatedTitle": lead.get("name"),
            "priority": "High" if new_stage in {"Interested", "Quote Sent", "Documents Pending"} else "Medium",
            "dueDate": due, "dueTime": due_time, "status": "Pending", "assignedTo": lead.get("assignedTo", ""),
            "activityType": "Follow-up"}
        db.setdefault("tasks", []).insert(0, next_task)
        lead["nextActionTaskId"] = next_task["id"]

    core.audit(db, "Lead Stage Changed", "Lead", id, {"from": old_stage, "to": new_stage,
                                                 "nextAction": lead["nextAction"], "dueDate": due})

    core.save_db(db)
    return {"status": "success", "lead": lead}


class LeadModel(BaseModel):
    salutation: Optional[str] = ""
    firstName: str
    lastName: Optional[str] = ""
    email: Optional[str] = ""
    mobile: str
    city: Optional[str] = ""
    organization: Optional[str] = ""
    product: Optional[str] = None
    policyType: Optional[str] = None          # earlier name for product, still accepted
    premium: Optional[Any] = ""
    expiryDate: Optional[str] = ""
    nextAction: Optional[str] = "First call"
    nextActionDate: Optional[str] = ""
    nextActionTime: Optional[str] = ""
    status: Optional[str] = "New"
    assignedTo: Optional[str] = None
    leadPriority: Optional[str] = None
    leadSource: Optional[str] = None
    source: Optional[str] = None
    notes: Optional[str] = ""
    vehicleDetails: Optional[Dict[str, Any]] = None
    healthDetails: Optional[Dict[str, Any]] = None
    existingPolicy: Optional[Dict[str, Any]] = None
    custom: Optional[Dict[str, Any]] = None       # the company's own fields, by key (crm_routes/schema.py)


@router.get("/api/lead-options")
def get_lead_options():
    """The lead vocabulary in one place, so screens never keep a copy that drifts."""
    db = core.load_db()
    pipeline = core.company_pipeline()
    return {"statuses": list(core.LEAD_STATUSES), "closedStatuses": sorted(core.CLOSED_STATUSES),
            # How each stage reads on screen, and which ones are offered when choosing a stage.
            "stageLabels": {s["name"]: s["label"] for s in pipeline if s.get("label")},
            "pickableStatuses": [s["name"] for s in pipeline if not s.get("hidden")],
            "noNextAction": sorted(core.NO_NEXT_ACTION), "reasonRequired": sorted(core.REASON_REQUIRED),
            "products": core._products(db), "sources": core._lead_sources(db), "closeReasons": core.CLOSE_REASONS,
            "fuelTypes": core.FUEL_TYPES, "ncbLevels": core.NCB_LEVELS, "healthPlanTypes": core.HEALTH_PLAN_TYPES,
            "memberRelations": core.MEMBER_RELATIONS, "documentTypes": core.DOCUMENT_TYPES, "quoteStatuses": core.QUOTE_STATUSES,
            "quoteTransitions": {k: sorted(v) for k, v in core.QUOTE_TRANSITIONS.items()},
            "requiredDocuments": db.get("settings", {}).get("crm", {}).get("requiredDocuments") or core.DEFAULT_REQUIRED_DOCUMENTS}


@router.post("/api/leads")
def create_lead(item: LeadModel):
    db = core.load_db()
    first, last = item.firstName.strip(), (item.lastName or "").strip()
    if not last and " " in first:
        first, last = first.split(" ", 1)            # the form sends the full name in one box
    full_name = f"{first} {last}".strip()
    mobile = (item.mobile or "").strip()
    if not full_name or not mobile:
        raise HTTPException(status_code=422, detail="A customer name and mobile number are required")

    product = core._checked_product(db, item.product) if item.product else (item.policyType or "").strip()
    source = core._checked_source(db, item.leadSource or item.source)
    details = {field: core._checked_details(field, getattr(item, field)) for field in core._DETAIL_MODELS}
    existing = details["existingPolicy"]
    expiry = ""
    if item.expiryDate:
        expiry = core._parse_flexible_date(item.expiryDate)
        if not expiry:
            raise HTTPException(status_code=422, detail="Policy expiry is not a valid date")
    expiry = expiry or existing.get("expiryDate", "")
    if expiry and not existing.get("expiryDate"):
        existing["expiryDate"] = expiry              # one expiry, recorded in both places
    next_action = (item.nextAction or "First call").strip()
    next_date = item.nextActionDate or datetime.now().strftime("%Y-%m-%d")
    status = core._checked_status_change({}, item.status or "New", "", next_action, next_date)
    if status not in core.NO_NEXT_ACTION:
        next_date = core._parse_flexible_date(next_date)

    new_id = f"L{len(db.get('leads', [])) + 1}_{uuid.uuid4().hex[:4]}"
    now_str = datetime.utcnow().isoformat() + "Z"
    org_name = (item.organization or "").strip() or "Private Individual"
    priority = (item.leadPriority or "").upper() or core.calculate_lead_priority({"expiryDate": expiry, "status": status})
    session = None if core.AUTH_DISABLED else crm_security.current_user()
    if session and crm_security.normalized_role(session.get("role", "")) == "telecaller":
        # A telecaller's own enquiry stays with them; handing work to someone else is a manager's call.
        owner = session.get("name", "")
    elif item.assignedTo and item.assignedTo != "Auto":
        owner = item.assignedTo
    else:
        # An admin's assignment rules decide first; round-robin is the fallback.
        owner = core.apply_assignment_rules(db, {"id": new_id, "name": full_name, "policyType": product,
                                            "product": product, "source": source, "organization": org_name,
                                            "premium": str(item.premium or ""), "status": status,
                                            "city": item.city or "", "leadPriority": priority}) or core.get_next_round_robin_user(db)

    # Only what someone actually said. Earlier versions stamped an invented city, territory,
    # industry, company revenue, headcount and premium onto every lead, which inflated
    # pipeline value and made reports describe customers nobody had spoken to.
    new_lead = {
        "id": new_id,
        "salutation": item.salutation or "",
        "firstName": first,
        "lastName": last,
        "name": full_name,
        "organization": org_name,
        "status": status,
        "email": (item.email or "").strip(),
        "mobile": mobile,
        "city": (item.city or "").strip(),
        "product": product,
        "policyType": product,
        # A policy number is evidence from the insurer and is assigned only at issuance.
        "policyNumber": "",
        "premium": str(item.premium).strip() if item.premium not in (None, "") else "",
        "expiryDate": expiry,
        "daysRemaining": core._days_until(expiry) if expiry else None,
        "nextAction": "" if status in core.NO_NEXT_ACTION else next_action,
        "nextActionDate": "" if status in core.NO_NEXT_ACTION else next_date,
        "nextActionTime": "" if status in core.NO_NEXT_ACTION else core._checked_time(item.nextActionTime),
        "nextActionCompleted": status in core.NO_NEXT_ACTION,
        "source": source,
        "leadSource": source,
        "originalSource": source,
        "leadPriority": priority,
        "priority": priority.capitalize() if priority in ("HOT", "WARM", "COLD") else "Medium",
        "leadDate": now_str,
        "vehicleDetails": details["vehicleDetails"],
        "healthDetails": details["healthDetails"],
        "existingPolicy": existing,
        "assignedTo": owner,
        "lastModified": now_str,
        "lostReason": "",
        "assignedByRule": core._last_rule_match["name"],
    }
    custom = core.checked_custom_values(db, None, item.custom, creating=True, product=product)
    if custom:
        new_lead["custom"] = custom
    db.setdefault("leads", []).insert(0, new_lead)

    if org_name != "Private Individual" and not any(o.get("name", "").lower() == org_name.lower()
                                                      for o in db.get("organizations", [])):
        db.setdefault("organizations", []).insert(0, {
            "id": f"O{len(db.get('organizations', [])) + 1}_{uuid.uuid4().hex[:4]}",
            "name": org_name, "website": "", "lastModified": now_str})

    if not any(c.get("phone") == mobile for c in db.get("contacts", [])):
        db.setdefault("contacts", []).insert(0, {
            "id": f"C{len(db.get('contacts', [])) + 1}_{uuid.uuid4().hex[:4]}",
            "leadId": new_id, "name": full_name, "email": new_lead["email"], "phone": mobile,
            "organization": org_name, "designation": "Primary Contact", "status": "Active",
            "lastModified": now_str})

    if item.notes:
        db.setdefault("notes", []).insert(0, {
            "id": f"N{len(db.get('notes', [])) + 1}_{uuid.uuid4().hex[:4]}",
            "title": "Initial enquiry", "associatedType": "Lead", "associatedId": new_id,
            "associatedTitle": full_name, "category": "General", "content": item.notes,
            "author": current_actor("System"), "pinned": False, "createdAt": now_str})

    if status not in core.NO_NEXT_ACTION:
        initial_task = {
            "id": f"T{len(db.get('tasks', [])) + 1}_{uuid.uuid4().hex[:4]}",
            "title": next_action, "associatedType": "Lead", "associatedId": new_id,
            "associatedTitle": full_name, "priority": new_lead["priority"] if new_lead["priority"] != "Cold" else "Medium",
            "dueDate": next_date, "dueTime": new_lead["nextActionTime"], "status": "Pending", "assignedTo": owner,
            "activityType": "Call"}
        db.setdefault("tasks", []).insert(0, initial_task)
        new_lead["nextActionTaskId"] = initial_task["id"]

    core.audit(db, "Lead Created", "Lead", new_id, {"source": source, "product": product, "assignedTo": owner})
    core.save_db(db)
    return new_lead


class BulkLeadUpdate(BaseModel):
    ids: List[str]
    updates: Dict[str, Any]


@router.post("/api/leads/bulk-update")
def bulk_update_leads(payload: BulkLeadUpdate):
    allowed = {"assignedTo", "priority", "nextAction", "nextActionDate"}
    updates = {k: v for k, v in payload.updates.items() if k in allowed}
    if not payload.ids or not updates: raise HTTPException(status_code=422, detail="Lead IDs and supported updates are required")
    db = core.load_db(); changed = []
    for lead in db.get("leads", []):
        if lead.get("id") not in payload.ids: continue
        before = {k: lead.get(k) for k in updates}; lead.update(updates); lead["lastModified"] = datetime.utcnow().isoformat()+"Z"; changed.append(lead["id"])
        core._sync_lead_work(db, lead, updates)
        core.audit(db,"Lead Bulk Updated","Lead",lead["id"],{"before":before,"after":updates})
    core.save_db(db); return {"updatedCount":len(changed),"ids":changed}


@router.delete("/api/leads/{id}")
def delete_lead(id: str):
    db = core.load_db()
    lead = next((l for l in db.get("leads", []) if l.get("id") == id), None)
    if not lead: raise HTTPException(status_code=404, detail="Lead not found")
    customer_ids = {c.get("id") for c in db.get("customers", []) if c.get("sourceLeadId") == id}
    policy_ids = {p.get("id") for p in db.get("policies", []) if p.get("leadId") == id or p.get("customerId") in customer_ids}
    renewal_ids = {r.get("id") for r in db.get("renewals", []) if r.get("policyId") in policy_ids}
    associated_ids = {id, *customer_ids, *policy_ids, *renewal_ids}
    counts = {}
    def remove(collection, predicate):
        before = len(db.get(collection, [])); db[collection] = [x for x in db.get(collection, []) if not predicate(x)]; counts[collection] = before-len(db[collection])
    remove("leads", lambda x: x.get("id") == id)
    remove("customers", lambda x: x.get("id") in customer_ids)
    remove("policies", lambda x: x.get("id") in policy_ids)
    remove("renewals", lambda x: x.get("id") in renewal_ids)
    remove("quotations", lambda x: x.get("renewalId") in renewal_ids)
    remove("tasks", lambda x: x.get("associatedId") in associated_ids)
    remove("communications", lambda x: x.get("associatedId") in associated_ids)
    remove("consents", lambda x: x.get("leadId") == id or x.get("customerId") in customer_ids)
    remove("notifications", lambda x: x.get("associatedId") in associated_ids)
    remove("serviceRequests", lambda x: x.get("customerId") in customer_ids or x.get("policyId") in policy_ids or x.get("associatedId") in associated_ids)
    remove("endorsements", lambda x: x.get("customerId") in customer_ids or x.get("policyId") in policy_ids or x.get("associatedId") in associated_ids)
    remove("documents", lambda x: x.get("associatedId") in associated_ids or x.get("policyId") in policy_ids or x.get("customerId") in customer_ids)
    remove("deals", lambda x: x.get("leadId") == id or (x.get("organization") == lead.get("organization") and (x.get("email") == lead.get("email") or x.get("mobile") == lead.get("mobile"))))
    remove("contacts", lambda x: x.get("customerId") in customer_ids or x.get("leadId") == id or (x.get("phone") == lead.get("mobile") and x.get("email") == lead.get("email")))
    org_used = any(x.get("organization") == lead.get("organization") for x in db.get("leads", []) + db.get("customers", []) + db.get("policies", []))
    if not org_used: remove("organizations", lambda x: x.get("name") == lead.get("organization"))
    else: counts["organizations"] = 0
    archived = 0
    for note in db.get("notes", []):
        if note.get("associatedId") in associated_ids or note.get("leadId") == id:
            note.update({"archived": True, "archivedReason": "Related lead deleted", "archivedLeadId": id, "associatedType": "Archived Lead"}); archived += 1
    counts["notesArchived"] = archived
    calendar_archived = 0
    for event in db.get("calendarEvents", []):
        if event.get("associatedId") in associated_ids or event.get("customerId") in customer_ids or event.get("convertedPolicyId") in policy_ids:
            # Related tasks were removed above; do not leave archived events with
            # dangling strong links when this transaction is persisted in PostgreSQL.
            if event.get("taskId") and not any(t.get("id") == event.get("taskId") for t in db.get("tasks", [])):
                event["taskId"] = ""
            if event.get("followUpTaskId") and not any(t.get("id") == event.get("followUpTaskId") for t in db.get("tasks", [])):
                event["followUpTaskId"] = ""
            event.update({"status":"Archived", "archivedAt":datetime.utcnow().isoformat()+"Z",
                          "archivedReason":"Related lead deleted",
                          "associatedTitle":event.get("associatedTitle") or lead.get("name", "Deleted lead")})
            for field in ("customerId", "convertedPolicyId"):
                if event.get(field):
                    event["archived" + field[0].upper() + field[1:]] = event.pop(field)
            calendar_archived += 1
    counts["calendarEventsArchived"] = calendar_archived
    core.audit(db, "Lead Deleted With Cascade", "Lead", id, {"leadSnapshot": lead, "affected": counts})
    core.save_db(db)
    return {"status": "success", "deletedId": id, "affected": counts}


@router.get("/api/archived-leads")
def get_archived_leads():
    return core.load_db().get("archivedLeads", [])


@router.post("/api/leads/{id}/archive")
def archive_lead(id: str):
    db=core.load_db(); lead=core._find_record(db.get("leads",[]),id,"Lead"); db["leads"]=[x for x in db.get("leads",[]) if x.get("id")!=id]
    lead.update({"archived":True,"archivedAt":datetime.utcnow().isoformat()+"Z"}); db.setdefault("archivedLeads",[]).insert(0,lead)
    for task in db.get("tasks",[]):
        if task.get("associatedType") == "Lead" and task.get("associatedId") == id and task.get("status") not in {"Completed", "Archived"}:
            task.update({"statusBeforeLeadArchive": task.get("status", "Pending"), "status": "Archived", "archivedByLeadId": id})
    for event in db.get("calendarEvents",[]):
        if event.get("associatedType")=="Lead" and event.get("associatedId")==id and event.get("status") not in ["Completed","Cancelled", "Archived"]:
            event.update({"status":"Archived","archivedAt":datetime.utcnow().isoformat()+"Z","archivedReason":"Related lead archived"})
    core.audit(db,"Lead Archived","Lead",id,{"name":lead.get("name")}); core.save_db(db); return lead


@router.post("/api/archived-leads/{id}/restore")
def restore_lead(id: str):
    db=core.load_db(); lead=core._find_record(db.get("archivedLeads",[]),id,"Archived lead"); db["archivedLeads"]=[x for x in db.get("archivedLeads",[]) if x.get("id")!=id]
    if lead.get("mergedIntoLeadId"):
        raise HTTPException(status_code=409, detail="A merged lead cannot be restored independently of its merged relationships")
    lead.pop("archived",None); lead["restoredAt"]=datetime.utcnow().isoformat()+"Z"; db.setdefault("leads",[]).insert(0,lead)
    for task in db.get("tasks",[]):
        if task.get("archivedByLeadId") == id and task.get("status") == "Archived":
            task["status"] = task.pop("statusBeforeLeadArchive", "Pending")
            task.pop("archivedByLeadId", None)
    for event in db.get("calendarEvents",[]):
        if event.get("associatedType")=="Lead" and event.get("associatedId")==id and event.get("archivedReason")=="Related lead archived":
            event["status"]="Scheduled"; event.pop("archivedReason",None); event.pop("archivedAt",None)
    core.audit(db,"Lead Restored","Lead",id,{"name":lead.get("name")}); core.save_db(db); return lead


@router.get("/api/data-quality/lead-duplicates")
def duplicate_candidates():
    db = core.load_db(); groups: Dict[str, List[Dict[str, Any]]] = {}
    for lead in db.get("leads", []):
        keys = [f"mobile:{lead.get('mobile','').strip().lower()}", f"email:{lead.get('email','').strip().lower()}"]
        for key in keys:
            if not key.endswith(":"): groups.setdefault(key, []).append(lead)
    return [{"matchKey":key, "records":items} for key, items in groups.items() if len(items) > 1]


@router.post("/api/leads/{target_id}/merge/{duplicate_id}")
def merge_leads(target_id: str, duplicate_id: str):
    if target_id == duplicate_id: raise HTTPException(status_code=422, detail="Choose two different leads")
    db = core.load_db(); target = core._find_record(db.get("leads", []), target_id, "Target lead"); duplicate = core._find_record(db.get("leads", []), duplicate_id, "Duplicate lead")
    if duplicate.get("convertedCustomerId") and target.get("convertedCustomerId") and duplicate["convertedCustomerId"] != target["convertedCustomerId"]:
        raise HTTPException(status_code=409, detail="These leads belong to different customers; reconcile the customer records before merging")
    for collection, records in db.items():
        if not isinstance(records, list) or collection in {"auditLogs", "archivedLeads", "archivedRecords"}:
            continue
        for index, item in enumerate(records):
            # Some collections (callQueue) hold bare lead ids rather than records.
            if isinstance(item, str):
                if item == duplicate_id:
                    records[index] = target_id
                continue
            if not isinstance(item, dict):
                continue
            if item.get("associatedType", "Lead") == "Lead" and item.get("associatedId") == duplicate_id:
                item.update({"associatedId": target_id, "associatedTitle": target.get("name", "")})
            for field in ("leadId", "sourceLeadId"):
                if item.get(field) == duplicate_id:
                    item[field] = target_id
    for key, value in duplicate.items():
        if not target.get(key) and value: target[key] = value
    if duplicate.get("custom"):
        # Field by field, like the rest: the target's own values win, the duplicate fills gaps.
        target["custom"] = {**duplicate["custom"], **(target.get("custom") or {})}
    duplicate["mergedIntoLeadId"] = target_id
    db["leads"] = [x for x in db.get("leads", []) if x.get("id") != duplicate_id]
    duplicate.update({"archived":True, "archivedReason":f"Merged into {target_id}", "archivedAt":datetime.utcnow().isoformat()+"Z"}); db.setdefault("archivedLeads", []).insert(0, duplicate)
    core.audit(db, "Leads Merged", "Lead", target_id, {"mergedLeadId": duplicate_id}); core.save_db(db); return {"target":target,"archivedDuplicate":duplicate}


ALLOWED_FILTER_MODULES = {"leads", "customers", "policies", "renewals", "deals", "tasks"}


@router.get("/api/saved-filters")
def get_saved_filters(module: Optional[str] = None):
    user = crm_security.current_user() or {}
    items = [item for item in core.load_db().get("savedFilters", []) if item.get("ownerId") in {user.get("sub"), user.get("id"), "local"}]
    return [item for item in items if not module or item.get("module") == module]


@router.post("/api/saved-filters")
def create_saved_filter(payload: Dict[str, Any]):
    module = str(payload.get("module", "")); name = str(payload.get("name", "")).strip(); criteria = payload.get("criteria")
    if module not in ALLOWED_FILTER_MODULES or not name or not isinstance(criteria, dict):
        raise HTTPException(status_code=422, detail="Filter name, supported module and criteria are required")
    user = crm_security.current_user() or {}
    db = core.load_db(); item = {"id": f"FLT_{uuid.uuid4().hex[:8]}", "name": name, "module": module,
                            "criteria": criteria, "ownerId": user.get("sub") or user.get("id") or "local",
                            "createdAt": datetime.utcnow().isoformat() + "Z"}
    db.setdefault("savedFilters", []).insert(0, item); core.audit(db, "Saved Filter Created", "Saved Filter", item["id"], {"name": name, "module": module}); core.save_db(db)
    return item


@router.delete("/api/saved-filters/{id}")
def delete_saved_filter(id: str):
    db = core.load_db(); user = crm_security.current_user() or {}; owner = user.get("sub") or user.get("id") or "local"
    item = core._find_record(db.get("savedFilters", []), id, "Saved filter")
    if item.get("ownerId") != owner: raise HTTPException(status_code=403, detail="This saved view belongs to another user")
    db["savedFilters"] = [value for value in db.get("savedFilters", []) if value.get("id") != id]
    core.audit(db, "Saved Filter Deleted", "Saved Filter", id, {"name": item.get("name")}); core.save_db(db); return {"status": "deleted"}
