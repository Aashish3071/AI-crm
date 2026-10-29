"""In-app notifications and the scheduler's job status.
"""
import os
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter

import pipecat_server as core

router = APIRouter()


@router.get("/api/notifications")
def get_notifications(unreadOnly: bool = False):
    db = core.load_db()
    items = db.get("notifications", [])
    owners = core.visible_owners(db)
    if owners is not None:
        items = [n for n in items if n.get("assignedTo") in owners or n.get("escalatedTo") in owners]
    today = datetime.now(core._calendar_timezone(db)).strftime("%Y-%m-%d")
    return [n for n in items if (not n.get("snoozedUntil") or n.get("snoozedUntil") <= today)
            and (not unreadOnly or not n.get("read"))]


@router.get("/api/admin/jobs")
def scheduler_status():
    scheduler = core.load_db().get("settings", {}).get("scheduler", {})
    return {"workerMode": "separate-process" if os.environ.get("SCHEDULER_PROCESS") == "1" else "embedded-development",
            "lastRun": scheduler.get("lastRun", ""), "lastError": scheduler.get("lastError", ""),
            "lastErrorAt": scheduler.get("lastErrorAt", "")}


@router.put("/api/notifications/{id}")
def update_notification(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    item = core._find_record(db.get("notifications", []), id, "Notification")
    allowed = {"read", "assignedTo", "snoozedUntil", "severity", "escalationLevel"}
    changes = {k: v for k, v in updates.items() if k in allowed}
    before = {k: item.get(k) for k in changes}; item.update(changes); item["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Notification Updated", "Notification", id, {"before": before, "after": changes})
    core.save_db(db)
    return item
