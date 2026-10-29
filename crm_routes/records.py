"""Records of the company's own types (docs/AI_CUSTOMIZATION_PLAN.md, phase 4).

An Owner / Admin defines a record type — a vehicle inspection, a claim, a family member — that
hangs from a lead, a customer or a policy, and gives it fields (crm_routes/schema.py). Anyone
who may work the parent record adds, edits and deletes its records; they are visible exactly
when the parent is, so a telecaller sees the inspections on their own leads only.

Values are checked by the same helper as every other custom field. Records are stored in
``customRecords`` with ``parentType``/``parentId``; the parent link is deliberately not a
strong relationship, so archiving a lead never fails because it has inspections. Deleting a
record keeps a copy in the audit log.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

import pipecat_server as core
from crm_routes.schema import record_types
from crm_security import current_actor

router = APIRouter()

_PARENT_COLLECTIONS = {"lead": "leads", "customer": "customers", "policy": "policies"}


def _type(db: Dict[str, Any], key: Any, writing: bool = False) -> Dict[str, Any]:
    record_type = next((t for t in record_types(db) if t["key"] == key), None)
    if not record_type:
        raise HTTPException(status_code=404, detail="Record type not found")
    if writing and record_type.get("hidden"):
        raise HTTPException(status_code=422, detail=f"{record_type['label']} is hidden; show it again in Settings to add records")
    return record_type


def _visible_parent(db: Dict[str, Any], parent_type: str, parent_id: Any) -> Dict[str, Any]:
    """The parent record, if the caller may see it; otherwise 404, as for the parent itself."""
    parent = next((r for r in db.get(_PARENT_COLLECTIONS[parent_type], []) if r.get("id") == parent_id), None)
    ids = core.visible_ids(db, core.visible_owners(db))
    if not parent or (ids is not None and parent_id not in ids):
        raise HTTPException(status_code=404, detail=f"{parent_type.capitalize()} not found")
    return parent


def _record(db: Dict[str, Any], id: str) -> Dict[str, Any]:
    record = next((r for r in db.get("customRecords", []) if r.get("id") == id), None)
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")
    _visible_parent(db, record["parentType"], record["parentId"])
    return record


@router.get("/api/custom-records")
def list_records(type: Optional[str] = None, parentId: Optional[str] = None):
    db = core.load_db()
    ids = core.visible_ids(db, core.visible_owners(db))
    records = [r for r in db.get("customRecords", []) if (not type or r.get("type") == type)
               and (not parentId or r.get("parentId") == parentId) and (ids is None or r.get("parentId") in ids)]
    return sorted(records, key=lambda r: r.get("createdAt", ""), reverse=True)


@router.post("/api/custom-records")
def create_record(payload: Dict[str, Any]):
    db = core.load_db()
    record_type = _type(db, payload.get("type"), writing=True)
    _visible_parent(db, record_type["parent"], payload.get("parentId"))
    now = datetime.utcnow().isoformat() + "Z"
    record = {"id": f"REC_{uuid.uuid4().hex[:10]}", "type": record_type["key"], "parentType": record_type["parent"],
              "parentId": payload["parentId"],
              "custom": core.checked_custom_values(db, None, payload.get("custom") or {}, creating=True, obj=record_type["key"]),
              "createdAt": now, "createdBy": current_actor("System"), "updatedAt": now}
    db.setdefault("customRecords", []).insert(0, record)
    core.audit(db, f"{record_type['label']} Added", "Custom Record", record["id"],
               {"type": record_type["key"], "parentId": record["parentId"], "values": record["custom"]})
    core.save_db(db)
    return record


@router.put("/api/custom-records/{id}")
def update_record(id: str, payload: Dict[str, Any]):
    db = core.load_db()
    record = _record(db, id)
    _type(db, record["type"], writing=True)
    before = dict(record.get("custom") or {})
    record["custom"] = core.checked_custom_values(db, record.get("custom"), payload.get("custom") or {}, obj=record["type"])
    record.update({"updatedAt": datetime.utcnow().isoformat() + "Z", "updatedBy": current_actor("System")})
    core.audit(db, "Custom Record Updated", "Custom Record", id, {"before": before, "after": record["custom"]})
    core.save_db(db)
    return record


@router.delete("/api/custom-records/{id}")
def delete_record(id: str):
    db = core.load_db()
    record = _record(db, id)
    db["customRecords"] = [r for r in db.get("customRecords", []) if r.get("id") != id]
    core.audit(db, "Custom Record Deleted", "Custom Record", id, {"record": record})
    core.save_db(db)
    return {"status": "deleted", "id": id}
