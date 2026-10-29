"""Tasks, attached to any record.
"""
import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import crm_security
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


@router.get("/api/tasks")
def get_tasks():
    db = core.load_db()
    return core.scoped(db.get("tasks", []), core.visible_owners(db))


class TaskModel(BaseModel):
    title: str
    associatedType: Optional[str] = "Lead"
    associatedId: Optional[str] = ""
    associatedTitle: Optional[str] = ""
    priority: Optional[str] = "Medium"
    dueDate: str
    dueTime: Optional[str] = ""
    assignedTo: Optional[str] = None
    activityType: Optional[str] = "Follow-up"
    author: Optional[str] = None
    createdBy: Optional[str] = None


@router.post("/api/tasks")
def create_task(t: TaskModel):
    db = core.load_db()
    due_date = core._parse_flexible_date(t.dueDate)
    if not due_date or not t.title.strip():
        raise HTTPException(status_code=422, detail="A task title and valid due date are required")
    _, label = core._calendar_entity(db, t.associatedType or "Lead", t.associatedId or "")
    new_id = f"T{len(db.get('tasks', [])) + 1}_{uuid.uuid4().hex[:4]}"
    actor = current_actor("System")
    session = None if core.AUTH_DISABLED else crm_security.current_user()
    if session and crm_security.normalized_role(session.get("role", "")) == "telecaller":
        owner = session.get("name", "")          # a telecaller schedules their own work
    else:
        linked = next((l for l in db.get("leads", []) if l.get("id") == t.associatedId), None)
        owner = t.assignedTo or (linked or {}).get("assignedTo") or actor
    item = {
        "id": new_id,
        "title": t.title,
        "associatedType": t.associatedType or "Lead",
        "associatedId": t.associatedId or "",
        "associatedTitle": label or "General Task",
        "priority": t.priority or "Medium",
        "dueDate": due_date,
        "dueTime": core._checked_time(t.dueTime),
        "status": "Pending",
        "assignedTo": owner,
        "activityType": t.activityType or "Follow-up",
        "author": actor,
        "createdBy": actor,
    }
    db.setdefault("tasks", []).insert(0, item)
    core.audit(db, "Task Created", "Task", item["id"], item)
    core.save_db(db)
    return item


@router.delete("/api/tasks/{id}")
def delete_task(id: str):
    db = core.load_db()
    item = core.require_visible(core._find_record(db.get("tasks", []), id, "Task"), core.visible_owners(db), "Task")
    db["tasks"] = [t for t in db.get("tasks", []) if t["id"] != id]
    for lead in db.get("leads", []):
        if lead.get("nextActionTaskId") == id:
            lead.update({"nextActionTaskId": "", "nextAction": "", "nextActionDate": "", "nextActionCompleted": False})
    if item.get("calendarEventId"):
        event = next((e for e in db.get("calendarEvents", []) if e.get("id") == item["calendarEventId"]), None)
        if event:
            event.update({"status":"Archived", "archivedAt":datetime.utcnow().isoformat()+"Z",
                          "archivedReason":"Linked task deleted", "taskId":""})
    if item.get("sourceCalendarEventId"):
        event = next((e for e in db.get("calendarEvents", []) if e.get("id") == item["sourceCalendarEventId"]), None)
        if event and event.get("followUpTaskId") == id:
            event["followUpTaskId"] = ""
    core.audit(db, "Task Deleted", "Task", id, {"snapshot":item})
    core.save_db(db)
    return {"status": "success"}
