"""Company settings.
"""
import json
from typing import Any, Dict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException

import pipecat_server as core

router = APIRouter()


@router.get("/api/settings")
def get_settings():
    db = core.load_db()
    return db.get("settings", {})


@router.put("/api/settings")
def update_settings(updates: Dict[str, Any]):
    db = core.load_db(); before = json.loads(json.dumps(db.get("settings", {})))
    if "customFields" in updates:
        # Field definitions are checked one change at a time; a raw overwrite would skip that.
        raise HTTPException(status_code=422, detail="Custom fields are changed under Settings → Custom fields.")
    timezone_name = (updates.get("crm") or {}).get("companyTimezone") if isinstance(updates.get("crm"), dict) else None
    if timezone_name:
        try: ZoneInfo(str(timezone_name))
        except ZoneInfoNotFoundError: raise HTTPException(status_code=422, detail="Unknown company timezone")
    reminder_minutes = (updates.get("crm") or {}).get("upcomingReminderMinutes") if isinstance(updates.get("crm"), dict) else None
    if reminder_minutes is not None and (not isinstance(reminder_minutes, (int, float)) or reminder_minutes < 15 or reminder_minutes > 10080):
        raise HTTPException(status_code=422, detail="Upcoming reminder must be between 15 minutes and 7 days")
    crm_updates = updates.get("crm") if isinstance(updates.get("crm"), dict) else {}
    if ("leadStages" in crm_updates and list(crm_updates["leadStages"] or []) != list(core.LEAD_STATUSES)) or "pipeline" in crm_updates:
        raise HTTPException(status_code=422, detail="Lead stages are changed under Settings → Lead stages, where each "
                            "change is checked against the call outcomes, follow-ups and reports that depend on it.")
    for key, label in (("insuranceProducts", "product"), ("leadSources", "lead source")):
        if key in crm_updates:
            values = crm_updates[key]
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v.strip() for v in values):
                raise HTTPException(status_code=422, detail=f"Keep at least one {label}; each needs a name.")
            crm_updates[key] = list(dict.fromkeys(v.strip() for v in values))
    for section, values in updates.items():
        if not isinstance(values, dict): continue
        db.setdefault("settings", {}).setdefault(section, {}).update(values)
    core.audit(db, "Settings Updated", "Settings", "global", {"before": before, "after": db.get("settings", {})})
    core.save_db(db); return db["settings"]
