"""Follow-ups (client blueprint, slide 17): the day's call-backs and chases, by due time.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query

import pipecat_server as core

router = APIRouter()


def _completed_moment(task: Dict[str, Any]) -> Optional[datetime]:
    stamp = (task.get("completedAt") or "").replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None


@router.get("/api/follow-ups")
def get_follow_ups(assignedTo: Optional[str] = None, days: int = Query(30, ge=1, le=365)):
    """Slide 17. Counters and the follow-up list, in the company's time zone.

    On-time rate is measured, not asserted: of the follow-ups that fell due in the last
    `days` days, the share finished by their due time. When nothing fell due it is null —
    the screen says so — rather than a placeholder figure.
    """
    db = core.load_db()
    tz = core._calendar_timezone(db)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")
    tasks = [t for t in core.scoped(db.get("tasks", []), core.visible_owners(db))
             if t.get("status") != "Archived" and t.get("dueDate") and core._due_moment(t, tz)]
    if assignedTo:
        tasks = [t for t in tasks if t.get("assignedTo") == assignedTo]
    leads = {l.get("id"): l for l in db.get("leads", [])}
    last = core._last_interactions(db)

    def view(task):
        lead = leads.get(task.get("associatedId")) if task.get("associatedType", "Lead") == "Lead" else None
        return {**{k: task.get(k) for k in ("id", "title", "dueDate", "dueTime", "status", "priority", "assignedTo",
                                           "associatedId", "associatedType", "activityType")},
                "customerName": (lead or {}).get("name") or task.get("associatedTitle", ""),
                "product": (lead or {}).get("product") or (lead or {}).get("policyType", ""),
                "leadPriority": (lead or {}).get("leadPriority", ""),
                "leadStatus": (lead or {}).get("status", ""),
                "mobile": (lead or {}).get("mobile", ""),
                "lastInteraction": last.get(task.get("associatedId")),
                "dueAt": core._due_moment(task, tz).isoformat()}

    open_tasks = [t for t in tasks if t.get("status") != "Completed"]
    overdue = sorted((t for t in open_tasks if core._due_moment(t, tz) < now), key=lambda t: core._due_moment(t, tz))
    due_today = sorted((t for t in open_tasks if t["dueDate"] == today and core._due_moment(t, tz) >= now),
                       key=lambda t: core._due_moment(t, tz))
    upcoming = sorted((t for t in open_tasks if t["dueDate"] > today), key=lambda t: core._due_moment(t, tz))
    done_today = sorted((t for t in tasks if t.get("status") == "Completed" and _completed_moment(t)
                         and _completed_moment(t).astimezone(tz).strftime("%Y-%m-%d") == today),
                        key=lambda t: _completed_moment(t), reverse=True)

    since = now - timedelta(days=days)
    came_due = [t for t in tasks if since <= core._due_moment(t, tz) <= now]
    measurable = [t for t in came_due if t.get("status") != "Completed" or _completed_moment(t)]
    on_time = [t for t in measurable if t.get("status") == "Completed" and _completed_moment(t) <= core._due_moment(t, tz)]
    return {
        "metrics": {"dueToday": len(due_today), "overdue": len(overdue), "upcoming": len(upcoming),
                    "onTimeRate": round(len(on_time) * 100 / len(measurable)) if measurable else None,
                    "onTimeBasis": {"days": days, "cameDue": len(measurable), "onTime": len(on_time),
                                    # Finished before completion times were recorded: cannot be judged either way.
                                    "unmeasured": len(came_due) - len(measurable)}},
        "overdue": [view(t) for t in overdue],
        "dueToday": [view(t) for t in due_today],
        "upcoming": [view(t) for t in upcoming[:100]],
        "doneToday": [{**view(t), "completedAt": t.get("completedAt")} for t in done_today],
        "timezone": str(tz),
    }
