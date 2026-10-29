"""Notes, attached to any record.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


@router.get("/api/notes")
def get_notes(associatedId: Optional[str] = None, includeArchived: bool = False):
    db = core.load_db()
    owners = core.visible_owners(db)
    ids = core.visible_ids(db, owners)
    notes = [n for n in db.get("notes", []) if core.child_visible(n, ids, owners)]
    if not includeArchived:
        notes = [n for n in notes if not n.get("archived")]
    if associatedId:
        notes = [n for n in notes if n.get("associatedId") == associatedId or n.get("leadId") == associatedId]
    return notes


class NoteModel(BaseModel):
    title: str
    associatedType: Optional[str] = "Lead"
    associatedId: Optional[str] = ""
    associatedTitle: Optional[str] = ""
    category: Optional[str] = "Underwriting Note"
    content: str
    author: Optional[str] = None                 # ignored: the author is whoever is signed in
    pinned: Optional[bool] = False
    leadId: Optional[str] = None


@router.post("/api/notes")
def create_note(n: NoteModel):
    db = core.load_db()
    new_id = f"N{len(db.get('notes', [])) + 1}_{uuid.uuid4().hex[:4]}"
    assoc_id = n.associatedId or n.leadId or ""
    assoc_type = n.associatedType or ("Lead" if n.leadId else "General")
    item = {
        "id": new_id,
        "title": n.title or n.content[:24],
        "associatedType": assoc_type,
        "associatedId": assoc_id,
        "leadId": assoc_id if assoc_type == "Lead" else "",
        "associatedTitle": n.associatedTitle or "General Note",
        "category": n.category or "Underwriting Note",
        "content": n.content,
        "author": current_actor("System"),
        "pinned": n.pinned or False,
        "createdAt": datetime.utcnow().isoformat() + "Z"
    }
    db.setdefault("notes", []).insert(0, item)
    core.audit(db, "Note Created", "Note", item["id"], {"associatedId":item.get("associatedId"), "title":item.get("title")}, item.get("author","System"))
    core.save_db(db)
    return item


@router.put("/api/notes/{id}")
def update_note(id: str, payload: Dict[str, Any]):
    db = core.load_db()
    note = core.require_child_visible(db, core._find_record(db.get("notes", []), id, "Note"), "Note")
    before = dict(note)
    allowed = {"title", "content", "category", "pinned"}
    changes = {k: v for k, v in payload.items() if k in allowed and v is not None}
    actor = current_actor("System")
    note.update(changes)
    note["lastEditedBy"] = actor
    note["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Note Updated", "Note", id, {"before": {k: before.get(k) for k in changes}, "after": changes, "lastEditedBy": actor}, actor)
    core.save_db(db)
    return note


@router.post("/api/notes/{id}/archive")
def archive_note(id: str):
    """Archiving keeps the note as evidence; deleting removes it. Both are audited."""
    db = core.load_db()
    note = core.require_child_visible(db, core._find_record(db.get("notes", []), id, "Note"), "Note")
    note["archived"] = True
    note["archivedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Note Archived", "Note", id, {"title": note.get("title")})
    core.save_db(db)
    return note


@router.post("/api/notes/{id}/restore")
def restore_note(id: str):
    db = core.load_db()
    note = core.require_child_visible(db, core._find_record(db.get("notes", []), id, "Note"), "Note")
    note.pop("archived", None)
    note.pop("archivedAt", None)
    core.audit(db, "Note Restored", "Note", id, {"title": note.get("title")})
    core.save_db(db)
    return note


@router.delete("/api/notes/{id}")
def delete_note(id: str):
    db = core.load_db()
    item = core.require_child_visible(db, core._find_record(db.get("notes", []), id, "Note"), "Note")
    db["notes"] = [n for n in db.get("notes", []) if n["id"] != id]
    core.audit(db, "Note Deleted", "Note", id, {"snapshot":item})
    core.save_db(db)
    return {"status": "success"}
