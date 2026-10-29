"""The calendar: appointments, the combined feed of everything with a date, and rescheduling.
"""
import json
import uuid
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import pipecat_server as core

router = APIRouter()


class CalendarEvent(BaseModel):
    title: str
    date: str
    time: Optional[str] = ""
    durationMinutes: Optional[int] = 30
    type: Optional[str] = "Meeting"
    associatedType: Optional[str] = "Lead"
    associatedId: Optional[str] = ""
    assignedTo: Optional[str] = ""
    notes: Optional[str] = ""
    createTask: Optional[bool] = True
    followUpDate: Optional[str] = ""
    followUpAction: Optional[str] = ""
    timezone: Optional[str] = ""


@router.post("/api/admin/repair-calendar")
def repair_calendar_relations(dryRun: bool = True):
    db = core.load_db(); target = json.loads(json.dumps(db)) if dryRun else db
    counts = core.repair_calendar_model(target)
    if not dryRun:
        core.audit(db, "Calendar Relationships Repaired", "Calendar", "relationship-repair", counts); core.save_db(db)
    return {"dryRun":dryRun, **counts}


@router.get("/api/calendar")
def get_calendar(start: Optional[str] = None, end: Optional[str] = None,
                 assignedTo: Optional[str] = None, types: Optional[str] = None):
    """Everything dated in the CRM, in one feed."""
    db = core.load_db()
    owners = core.visible_owners(db)
    wanted = {t.strip() for t in (types or "").split(",") if t.strip()}
    entries: List[Dict[str, Any]] = []

    def add(entry):
        if owners is not None and entry.get("assignedTo") not in owners:
            return
        if wanted and entry["type"] not in wanted:
            return
        if assignedTo and entry.get("assignedTo") != assignedTo:
            return
        if start and entry["date"] < start:
            return
        if end and entry["date"] > end:
            return
        entries.append(entry)

    for task in db.get("tasks", []):
        if not task.get("dueDate") or task.get("status") == "Archived" or task.get("calendarEventId"):
            continue
        add({"id": task["id"], "type": "Task", "title": task.get("title", ""), "date": task["dueDate"],
             "time": task.get("time", ""), "status": task.get("status", "Pending"),
             "done": task.get("status") == "Completed", "priority": task.get("priority", "Medium"),
             "assignedTo": task.get("assignedTo", ""), "linkType": task.get("associatedType", "Lead"),
             "linkId": task.get("associatedId", ""), "linkLabel": task.get("associatedTitle", ""),
             "source": "Action task"})

    active_tasks = {t.get("id"): t for t in db.get("tasks", []) if t.get("status") != "Archived"}
    task_signatures = {(t.get("associatedId"), t.get("title"), t.get("dueDate"))
                       for t in active_tasks.values() if t.get("associatedType") == "Lead"}
    insured_leads = {p.get("leadId") for p in db.get("policies", [])}
    for lead in db.get("leads", []):
        canonical_task = lead.get("nextActionTaskId") in active_tasks or (
            lead.get("id"), lead.get("nextAction"), lead.get("nextActionDate")) in task_signatures
        if lead.get("nextActionDate") and not canonical_task and not lead.get("nextActionCompleted") and core.is_open_lead(lead):
            add({"id": f"next-{lead['id']}", "type": "Next action", "title": lead.get("nextAction", "Follow up"),
                 "date": lead["nextActionDate"], "time": "", "status": "Scheduled", "done": False,
                 "priority": "High", "assignedTo": lead.get("assignedTo", ""), "linkType": "Lead",
                 "linkId": lead["id"], "linkLabel": f"{lead.get('name')} ({lead.get('organization') or 'Individual'})",
                 "source": "Pipeline next action"})
        policy_owns_expiry = lead.get("convertedPolicyId") or lead.get("id") in insured_leads
        if lead.get("expiryDate") and not policy_owns_expiry:
            add({"id": f"exp-{lead['id']}", "type": "Renewal", "title": f"Policy expires — {lead.get('policyType') or 'cover'}",
                 "date": lead["expiryDate"], "time": "", "status": "Due", "done": False, "priority": "High",
                 "assignedTo": lead.get("assignedTo", ""), "linkType": "Lead", "linkId": lead["id"],
                 "linkLabel": f"{lead.get('name')} ({lead.get('organization') or 'Individual'})",
                 "source": "Policy expiry"})

    for policy in db.get("policies", []):
        if policy.get("expiryDate") and policy.get("status") == "Active":
            add({"id": f"pol-{policy['id']}", "type": "Renewal",
                 "title": f"Policy {policy.get('policyNumber') or ''} expires".strip(),
                 "date": policy["expiryDate"], "time": "", "status": "Due", "done": False, "priority": "High",
                 "assignedTo": policy.get("assignedTo", ""), "linkType": "Policy", "linkId": policy["id"],
                 "linkLabel": policy.get("customerName", ""), "source": "Policy schedule"})

    for renewal in db.get("renewals", []):
        if renewal.get("nextActionDate") and renewal.get("stage") not in ["Renewed", "Lost", "Lapsed"]:
            add({"id": f"ren-{renewal['id']}", "type": "Renewal", "title": renewal.get("nextAction", "Renewal action"),
                 "date": renewal["nextActionDate"], "time": "", "status": renewal.get("stage", ""), "done": False,
                 "priority": "High", "assignedTo": renewal.get("assignedTo", ""), "linkType": "Renewal",
                 "linkId": renewal["id"], "linkLabel": renewal.get("customerName", ""), "source": "Renewal pipeline"})

    for deal in db.get("deals", []):
        if deal.get("expectedCloseDate") and deal.get("status") not in ["Won", "Lost", "Archived"]:
            add({"id":f"deal-{deal['id']}", "type":"Deal", "title":deal.get("dealName", "Deal decision"),
                 "date":deal["expectedCloseDate"], "time":"", "status":deal.get("status", ""), "done":False,
                 "priority":"Medium", "assignedTo":deal.get("assignedTo", ""), "linkType":"Deal", "linkId":deal["id"],
                 "linkLabel":deal.get("organization", ""), "source":"Expected close date"})

    for quote in db.get("quotations", []):
        v_date = quote.get("validityDate") or quote.get("validUntil")
        if v_date:
            add({"id":f"quote-{quote['id']}", "type":"Quotation", "title":f"Quotation expires — {quote.get('insurer','Insurer')}",
                 "date":v_date, "time":"", "status":quote.get("status", "Valid"), "done":False,
                 "priority":"High", "assignedTo":quote.get("assignedTo", ""), "linkType":"Quotation", "linkId":quote.get("id"),
                 "associatedType":"Quotation", "associatedId":quote.get("id"),
                 "linkLabel":quote.get("insurer", ""), "source":"Quotation validity"})

    for request in db.get("serviceRequests", []):
        if request.get("dueDate") and request.get("status") not in ["Completed", "Cancelled", "Archived"]:
            add({"id":f"service-{request['id']}", "type":"Service", "title":request.get("requestType", "Policy service"),
                 "date":request["dueDate"], "time":"", "status":request.get("status", "Open"), "done":False,
                 "priority":request.get("priority", "Medium"), "assignedTo":request.get("assignedTo", ""),
                 "linkType":"Policy", "linkId":request.get("policyId", ""), "linkLabel":request.get("description", ""), "source":"Service deadline"})

    for communication in db.get("communications", []):
        scheduled = str(communication.get("scheduledAt") or "")
        if communication.get("status") == "Scheduled" and len(scheduled) >= 10:
            add({"id":f"message-{communication['id']}", "type":"Message", "title":communication.get("subject") or f"Scheduled {communication.get('channel','message')}",
                 "date":scheduled[:10], "time":scheduled[11:16] if len(scheduled) >= 16 else "", "status":"Scheduled", "done":False,
                 "priority":"Medium", "assignedTo":communication.get("assignedTo", ""), "linkType":communication.get("associatedType", "Lead"),
                 "linkId":communication.get("associatedId", ""), "linkLabel":communication.get("recipient", ""), "source":"Scheduled communication"})

    for event in db.get("calendarEvents", []):
        if event.get("status") in ["Archived", "Cancelled"]: continue
        add({"id": event["id"], "type": "Appointment", "activityType":event.get("type", "Meeting"), "title": event.get("title", ""),
             "date": event.get("date", ""), "time": event.get("time", ""),
             "durationMinutes": event.get("durationMinutes", 30), "status": event.get("status", "Scheduled"),
             "done": event.get("status") == "Completed", "priority": "Medium",
             "assignedTo": event.get("assignedTo", ""), "linkType": event.get("associatedType", "Lead"),
             "linkId": event.get("associatedId", ""), "linkLabel": event.get("associatedTitle", ""),
             "notes": event.get("notes", ""), "taskId": event.get("taskId", ""), "source": "Booked meeting"})

    entries.sort(key=lambda e: (e["date"], e.get("time") or "99:99"))
    counts: Dict[str, int] = {}
    for entry in entries:
        counts[entry["type"]] = counts.get(entry["type"], 0) + 1
    return {"entries": entries, "events": entries, "counts": counts, "total": len(entries)}


@router.post("/api/calendar/events")
def create_calendar_event(payload: CalendarEvent):
    """Book a meeting. It also lands in the task queue so it can't be missed there."""
    db = core.load_db()
    event_date = core._parse_flexible_date(payload.date)
    if not event_date:
        raise HTTPException(status_code=422, detail="A valid date is required")
    duration = int(payload.durationMinutes or 30)
    now_str = datetime.utcnow().isoformat() + "Z"
    related, label = core._calendar_entity(db, payload.associatedType or "Lead", payload.associatedId or "")
    owner = payload.assignedTo or core.get_next_round_robin_user(db)
    item = {"id": f"EVT_{uuid.uuid4().hex[:8]}", "title": payload.title.strip(),
            "date": event_date, "time": payload.time or "",
            "durationMinutes": duration, "type": payload.type or "Meeting", "category":"Appointment",
            "associatedType": payload.associatedType or "Lead", "associatedId": payload.associatedId or "",
            "associatedTitle": label, "assignedTo": owner, "notes": payload.notes or "",
            "status": "Scheduled", "taskId": "", "followUpTaskId":"", "createdAt": now_str,
            "timezone": payload.timezone or str(core._calendar_timezone(db)), "relationshipStatus":"Linked" if related else "Unlinked"}
    core._validate_appointment(db, item)

    if payload.createTask:
        task = {"id": f"T_{uuid.uuid4().hex[:8]}", "title": item["title"], "associatedType": item["associatedType"],
                "associatedId": item["associatedId"], "associatedTitle": label, "priority": "Medium",
                "dueDate": item["date"], "status": "Pending", "assignedTo": owner,
                "activityType": item["type"], "calendarEventId": item["id"]}
        db.setdefault("tasks", []).insert(0, task)
        item["taskId"] = task["id"]

    follow_up_date = core._parse_flexible_date(payload.followUpDate) if payload.followUpDate else ""
    if payload.followUpDate and not follow_up_date:
        raise HTTPException(status_code=422, detail="Follow-up date is invalid")
    if follow_up_date and follow_up_date < event_date:
        raise HTTPException(status_code=422, detail="Follow-up date cannot be before the appointment")
    if follow_up_date:
        follow_up = {"id":f"T_{uuid.uuid4().hex[:8]}", "title":payload.followUpAction.strip() or f"Follow up after {item['title']}",
                     "associatedType":item["associatedType"], "associatedId":item["associatedId"], "associatedTitle":label,
                     "priority":"High", "dueDate":follow_up_date, "status":"Pending", "assignedTo":owner,
                     "activityType":"Follow-up", "sourceCalendarEventId":item["id"]}
        db.setdefault("tasks", []).insert(0, follow_up); item["followUpTaskId"] = follow_up["id"]

    db.setdefault("calendarEvents", []).insert(0, item)
    core.audit(db, "Calendar Event Created", "Calendar", item["id"],
          {"title": item["title"], "date": item["date"], "linkedTask": item["taskId"]})
    core.save_db(db)
    return item


@router.put("/api/calendar/events/{id}")
def update_calendar_event(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    item = core._find_record(db.get("calendarEvents", []), id, "Calendar event")
    allowed = {"title", "date", "time", "durationMinutes", "type", "assignedTo", "notes", "status"}
    changes = {k: v for k, v in updates.items() if k in allowed}
    if "date" in changes:
        parsed = core._parse_flexible_date(changes["date"])
        if not parsed:
            raise HTTPException(status_code=422, detail="A valid date is required")
        changes["date"] = parsed
    if "time" in changes and not core._valid_clock(str(changes["time"])):
        raise HTTPException(status_code=422, detail="Time must use 24-hour HH:MM format")
    core._validate_appointment(db, {**item, **changes})
    item.update(changes)
    # Keep the linked task in step — moving a meeting moves its task.
    task = next((t for t in db.get("tasks", []) if t.get("id") == item.get("taskId")), None)
    if task:
        if "date" in changes: task["dueDate"] = changes["date"]
        if "title" in changes: task["title"] = changes["title"]
        if "assignedTo" in changes: task["assignedTo"] = changes["assignedTo"]
        if "type" in changes: task["activityType"] = changes["type"]
        if "status" in changes:
            task["status"] = "Completed" if changes["status"] == "Completed" else ("Archived" if changes["status"] in ["Archived","Cancelled"] else "Pending")
        core._sync_lead_next_action(db, task)
    core.audit(db, "Calendar Event Updated", "Calendar", id, changes)
    core.save_db(db)
    return item


@router.delete("/api/calendar/events/{id}")
def delete_calendar_event(id: str):
    db = core.load_db()
    item = core._find_record(db.get("calendarEvents", []), id, "Calendar event")
    item.update({"status":"Archived", "archivedAt":datetime.utcnow().isoformat()+"Z", "archivedReason":"Calendar event deleted"})
    for task in db.get("tasks", []):
        if task.get("id") == item.get("taskId"): task["status"] = "Archived"
    core.audit(db, "Calendar Event Deleted", "Calendar", id, {"title": item.get("title")})
    core.save_db(db)
    return {"status": "deleted", "id": id}


@router.post("/api/calendar/reschedule")
def reschedule_calendar_entry(payload: Dict[str, Any]):
    """Move any dated thing — a task, a next action or a meeting — from the calendar."""
    entry_id, new_date = payload.get("id", ""), core._parse_flexible_date(payload.get("date", ""))
    if not new_date:
        raise HTTPException(status_code=422, detail="A valid date is required")
    db = core.load_db()

    if entry_id.startswith("next-"):
        return core.update_lead(entry_id[5:], {"nextActionDate": new_date})
    elif entry_id.startswith("ren-"):
        renewal = core._find_record(db.get("renewals", []), entry_id[4:], "Renewal")
        renewal["nextActionDate"] = new_date
        core.audit(db, "Renewal Action Rescheduled", "Renewal", renewal["id"], {"nextActionDate": new_date})
    elif entry_id.startswith("EVT_"):
        return update_calendar_event(entry_id, {"date": new_date})
    elif entry_id.startswith("exp-") or entry_id.startswith("pol-"):
        raise HTTPException(status_code=422, detail="A policy expiry date is set by the policy, not the calendar")
    else:
        return core.update_task(entry_id, {"dueDate": new_date})
    core.save_db(db)
    return {"id": entry_id, "date": new_date}
