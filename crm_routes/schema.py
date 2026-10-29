"""Custom fields (docs/AI_CUSTOMIZATION_PLAN.md, phase 1).

An Owner / Admin adds, edits, orders and hides the fields a lead carries; everyone reads
the definitions, because every form and card is drawn from them. There is no delete: a
field that is no longer wanted is hidden, and its values stay on the records. A change that
would make stored values unreadable — removing an option still in use, shortening text
that is already longer — is refused with the number of leads it would affect.

The rules for definitions and values are crm_schema's. Each change is audited with its
before and after, and bumps ``settings.customFieldsVersion``.
"""
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

import crm_schema
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


def _checked_object(obj: str) -> None:
    if obj not in crm_schema.ENABLED_OBJECTS:
        raise HTTPException(status_code=404, detail=f"Custom fields aren't available on {obj} records yet")


def _store(db: Dict[str, Any], obj: str, fields: List[Dict[str, Any]]) -> None:
    settings = db.setdefault("settings", {})
    settings.setdefault("customFields", {})[obj] = fields
    settings["customFieldsVersion"] = int(settings.get("customFieldsVersion") or 0) + 1


def _records(db: Dict[str, Any], obj: str) -> List[Dict[str, Any]]:
    return db.get({"lead": "leads", "customer": "customers", "policy": "policies"}[obj], [])


def _count(records: List[Dict[str, Any]], key: str, test) -> int:
    return sum(1 for r in records if (r.get("custom") or {}).get(key) is not None and test((r["custom"])[key]))


@router.get("/api/schema")
def get_schema():
    db = core.load_db()
    return {"fieldTypes": crm_schema.type_catalogue(), "lookupTargets": list(crm_schema.LOOKUP_TARGETS),
            "objects": {obj: core.custom_field_defs(db, obj) for obj in crm_schema.ENABLED_OBJECTS},
            "version": int((db.get("settings") or {}).get("customFieldsVersion") or 0)}


@router.post("/api/schema/fields/{obj}")
def add_field(obj: str, definition: Dict[str, Any]):
    _checked_object(obj)
    db = core.load_db()
    fields = core.custom_field_defs(db, obj)
    try:
        field = crm_schema.check_field(obj, definition, fields)
    except crm_schema.SchemaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    field.update({"createdAt": datetime.utcnow().isoformat() + "Z", "createdBy": current_actor("System")})
    _store(db, obj, fields + [field])
    core.audit(db, "Custom Field Added", "Custom Field", f"{obj}.{field['key']}", {"after": field})
    core.save_db(db)
    return field


# Declared before /{key} so "order" is never read as a field key.
@router.put("/api/schema/fields/{obj}/order")
def reorder_fields(obj: str, payload: Dict[str, Any]):
    _checked_object(obj)
    db = core.load_db()
    fields = core.custom_field_defs(db, obj)
    keys = payload.get("keys")
    if not isinstance(keys, list) or sorted(keys) != sorted(f["key"] for f in fields):
        raise HTTPException(status_code=422, detail="Send every field's key exactly once, in the new order")
    by_key = {f["key"]: f for f in fields}
    _store(db, obj, [by_key[k] for k in keys])
    core.audit(db, "Custom Fields Reordered", "Custom Field", obj,
               {"before": [f["key"] for f in fields], "after": keys})
    core.save_db(db)
    return core.custom_field_defs(db, obj)


@router.put("/api/schema/fields/{obj}/{key}")
def update_field(obj: str, key: str, changes: Dict[str, Any]):
    _checked_object(obj)
    db = core.load_db()
    fields = core.custom_field_defs(db, obj)
    before = next((f for f in fields if f["key"] == key), None)
    if not before:
        raise HTTPException(status_code=404, detail="Field not found")
    try:
        after = crm_schema.check_field_change(obj, before, changes, fields)
    except crm_schema.SchemaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    records = _records(db, obj)
    removed = {o.lower() for o in crm_schema.removed_options(before, after)}
    if removed:
        in_use = _count(records, key, lambda v: any(str(x).lower() in removed for x in (v if isinstance(v, list) else [v])))
        if in_use:
            raise HTTPException(status_code=409, detail=(
                f"{in_use} {obj}{'s' if in_use != 1 else ''} use {', '.join(sorted(crm_schema.removed_options(before, after)))}. "
                "Change those first, or hide the field instead."))
    if before["type"] == "long_text" and after["type"] == "text":
        too_long = _count(records, key, lambda v: len(str(v)) > 500)
        if too_long:
            raise HTTPException(status_code=409, detail=(
                f"{too_long} {obj}{'s' if too_long != 1 else ''} hold more than 500 characters in {before['label']}; "
                "short text can't hold them."))
    if before["type"] == "choice" and after["type"] == "multi_choice":
        for record in records:
            value = (record.get("custom") or {}).get(key)
            if isinstance(value, str):
                record["custom"][key] = [value]

    after.update({k: before[k] for k in ("createdAt", "createdBy") if k in before})
    after["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    _store(db, obj, [after if f["key"] == key else f for f in fields])
    core.refresh_rule_definitions(db, obj, after)
    core.audit(db, "Custom Field Changed", "Custom Field", f"{obj}.{key}", {"before": before, "after": after})
    core.save_db(db)
    return after
