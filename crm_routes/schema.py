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


def record_types(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The company's own record types (settings.customObjects)."""
    return [dict(t) for t in (db.get("settings") or {}).get("customObjects") or []]


def _checked_object(db: Dict[str, Any], obj: str) -> None:
    if obj not in crm_schema.ENABLED_OBJECTS and obj not in {t["key"] for t in record_types(db)}:
        raise HTTPException(status_code=404, detail=f"There are no {obj} records to add fields to")


def _store(db: Dict[str, Any], obj: str, fields: List[Dict[str, Any]]) -> None:
    settings = db.setdefault("settings", {})
    settings.setdefault("customFields", {})[obj] = fields
    settings["customFieldsVersion"] = int(settings.get("customFieldsVersion") or 0) + 1


def _records(db: Dict[str, Any], obj: str) -> List[Dict[str, Any]]:
    collection = {"lead": "leads", "customer": "customers", "policy": "policies"}.get(obj)
    if collection:
        return db.get(collection, [])
    return [r for r in db.get("customRecords", []) if r.get("type") == obj]


def _count(records: List[Dict[str, Any]], key: str, test) -> int:
    return sum(1 for r in records if (r.get("custom") or {}).get(key) is not None and test((r["custom"])[key]))


@router.get("/api/schema")
def get_schema():
    db = core.load_db()
    types = record_types(db)
    return {"fieldTypes": crm_schema.type_catalogue(), "lookupTargets": list(crm_schema.LOOKUP_TARGETS),
            "objects": {obj: core.custom_field_defs(db, obj) for obj in [*crm_schema.ENABLED_OBJECTS, *(t["key"] for t in types)]},
            "recordTypes": types, "recordParents": list(crm_schema.RECORD_PARENTS),
            "version": int((db.get("settings") or {}).get("customFieldsVersion") or 0)}


# ── The company's own record types ──
@router.post("/api/schema/record-types")
def add_record_type(definition: Dict[str, Any]):
    db = core.load_db()
    try:
        record_type = crm_schema.check_record_type(definition, record_types(db))
    except crm_schema.SchemaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    record_type.update({"createdAt": datetime.utcnow().isoformat() + "Z", "createdBy": current_actor("System")})
    settings = db.setdefault("settings", {})
    settings["customObjects"] = record_types(db) + [record_type]
    settings["customFieldsVersion"] = int(settings.get("customFieldsVersion") or 0) + 1
    core.audit(db, "Record Type Added", "Record Type", record_type["key"], {"after": record_type})
    core.save_db(db)
    return record_type


@router.put("/api/schema/record-types/{key}")
def update_record_type(key: str, changes: Dict[str, Any]):
    """A record type can be renamed or hidden; its key and what it is attached to stay."""
    db = core.load_db()
    types = record_types(db)
    before = next((t for t in types if t["key"] == key), None)
    if not before:
        raise HTTPException(status_code=404, detail="Record type not found")
    if changes.get("parent", before["parent"]) != before["parent"] or changes.get("key", key) != key:
        raise HTTPException(status_code=422, detail="A record type keeps its key and what it is attached to")
    try:
        after = crm_schema.check_record_type({**before, **{k: changes[k] for k in ("label", "hidden") if k in changes}},
                                             [t for t in types if t["key"] != key])
    except crm_schema.SchemaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    after.update({k: before[k] for k in ("createdAt", "createdBy") if k in before})
    db["settings"]["customObjects"] = [after if t["key"] == key else t for t in types]
    core.audit(db, "Record Type Changed", "Record Type", key, {"before": before, "after": after})
    core.save_db(db)
    return after


@router.post("/api/schema/fields/{obj}")
def add_field(obj: str, definition: Dict[str, Any]):
    db = core.load_db()
    _checked_object(db, obj)
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
    db = core.load_db()
    _checked_object(db, obj)
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
    db = core.load_db()
    _checked_object(db, obj)
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
