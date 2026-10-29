"""Documents (client blueprint, slides 19 and 21): upload, verification, download and
each lead's missing-document checklist. Files are scanned and stored through crm_storage.
"""
import base64
import hashlib
import mimetypes
import os
import socket
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

import crm_storage
import pipecat_server as core
from crm_security import current_actor, current_company_id

router = APIRouter()


VERIFICATION_STATES = ["Pending", "Verified", "Rejected"]


ALLOWED_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}


MAX_DOCUMENT_BYTES = 10 * 1024 * 1024


def _document_signature_valid(extension: str, content: bytes) -> bool:
    signatures = {".pdf": (b"%PDF-",), ".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
                  ".docx": (b"PK\x03\x04",), ".xlsx": (b"PK\x03\x04",), ".doc": (b"\xd0\xcf\x11\xe0",), ".xls": (b"\xd0\xcf\x11\xe0",)}
    if extension in signatures: return any(content.startswith(value) for value in signatures[extension])
    return b"\x00" not in content[:4096]


def _scan_document(content: bytes, filename: str) -> None:
    scanner = os.environ.get("DOCUMENT_SCANNER_URL", "")
    clamav_host = os.environ.get("CLAMAV_HOST", "")
    if clamav_host:
        try:
            with socket.create_connection((clamav_host, int(os.environ.get("CLAMAV_PORT", "3310"))), timeout=30) as connection:
                connection.sendall(b"zINSTREAM\0")
                for index in range(0, len(content), 65536):
                    chunk = content[index:index+65536]; connection.sendall(len(chunk).to_bytes(4, "big") + chunk)
                connection.sendall(b"\x00\x00\x00\x00")
                result = connection.recv(4096).decode("utf-8", "replace")
            if " OK" not in result: raise HTTPException(status_code=422, detail="Document failed the malware safety scan")
            return
        except HTTPException: raise
        except Exception: raise HTTPException(status_code=503, detail="Document scanner is unavailable; upload was not stored")
    if not scanner:
        if os.environ.get("APP_ENV", "development").lower() == "production":
            raise HTTPException(status_code=503, detail="Document malware scanning is not configured")
        return
    try:
        response = httpx.post(scanner, content=content, headers={"X-Filename": os.path.basename(filename)}, timeout=30.0)
        if response.status_code >= 400 or not response.json().get("clean"):
            raise HTTPException(status_code=422, detail="Document failed the malware safety scan")
    except HTTPException: raise
    except Exception:
        raise HTTPException(status_code=503, detail="Document scanner is unavailable; upload was not stored")


@router.get("/api/documents")
def get_documents(associatedId: Optional[str] = None):
    db = core.load_db()
    owners = core.visible_owners(db)
    ids = core.visible_ids(db, owners)
    return [x for x in db.get("documents", []) if core.child_visible(x, ids, owners)
            and (not associatedId or x.get("associatedId") == associatedId)]


_DOCUMENT_PARENTS = {"lead": "leads", "customer": "customers", "policy": "policies", "renewal": "renewals",
                     "deal": "deals", "contact": "contacts"}


def _store_document(db: Dict[str, Any], assoc_type: str, assoc_id: str, doc_type: str, filename: str,
                    content: bytes, evidence_key: str = "") -> Dict[str, Any]:
    """The one path every upload takes: parent, access, size, type, contents, virus scan, then storage."""
    if not assoc_id:
        raise HTTPException(status_code=422, detail="associatedId is required")
    collection = _DOCUMENT_PARENTS.get((assoc_type or "").strip().lower().rstrip("s"))
    if not collection:
        raise HTTPException(status_code=422, detail=f"Documents cannot be attached to a {assoc_type}")
    parent = next((r for r in db.get(collection, []) if r.get("id") == assoc_id), None)
    if not parent:
        raise HTTPException(status_code=422, detail=f"Referenced {assoc_type} does not exist")
    owners = core.visible_owners(db)
    if not (core._owned_by(parent, owners) if "assignedTo" in parent else core.child_visible(parent, core.visible_ids(db, owners), owners)):
        raise HTTPException(status_code=404, detail=f"{assoc_type} not found")
    if not content:
        raise HTTPException(status_code=422, detail="Document is empty")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds the 10 MB limit")
    name = os.path.basename(filename or "")
    extension = os.path.splitext(name)[1].lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Include the file name with a supported extension: "
                            + ", ".join(sorted(ALLOWED_DOCUMENT_EXTENSIONS)))
    if not _document_signature_valid(extension, content):
        raise HTTPException(status_code=422, detail="File contents do not match the selected document type")
    _scan_document(content, name)
    category = core._checked_document_type(doc_type)
    document_root = core._company_data_root(core.DOCUMENT_ROOT)
    stored_name = f"{uuid.uuid4().hex}{extension}"
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    crm_storage.put(document_root, current_company_id(), stored_name, content, content_type)
    parent_type = collection[:-1].title() if collection != "policies" else "Policy"
    prior = [x for x in db.get("documents", []) if x.get("associatedId") == assoc_id and x.get("category") == category]
    item = {"id": f"DOC_{uuid.uuid4().hex[:8]}", "associatedId": assoc_id,
            "policyId": assoc_id if collection == "policies" else "", "associatedType": parent_type,
            "category": category, "docType": evidence_key or category, "title": name, "originalName": name,
            "storedName": stored_name, "contentType": content_type, "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(), "version": len(prior) + 1, "status": "Active",
            "verification": "Pending", "uploadedBy": current_actor("System"),
            "createdAt": datetime.utcnow().isoformat() + "Z"}
    db.setdefault("documents", []).insert(0, item)
    core.audit(db, "Document Uploaded", "Document", item["id"],
          {k: item[k] for k in ["associatedId", "category", "originalName", "size", "version"]})
    return item


@router.post("/api/documents")
async def upload_document(request: Request, associatedId: Optional[str] = None, associatedType: str = "Lead",
                          category: str = "Other", filename: str = "document"):
    """Accepts a raw file body with query parameters, or JSON with base64 content.

    Both used to be separate code paths, and the JSON one skipped every check: any bytes
    were stored as a PDF, and a request with no content stored the words "document content"
    as the file. Both now go through _store_document().
    """
    db = core.load_db()
    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid JSON body")
        try:
            content = base64.b64decode(str(body.get("content") or ""), validate=True)
        except Exception:
            raise HTTPException(status_code=422, detail="content must be the file encoded as base64")
        requested = body.get("docType") or body.get("category") or category
        evidence = requested if requested in core.ISSUANCE_EVIDENCE else ""
        item = _store_document(db, body.get("associatedType") or associatedType, body.get("associatedId") or associatedId,
                               requested, body.get("filename") or body.get("originalName") or body.get("title") or "",
                               content, evidence)
    else:
        item = _store_document(db, associatedType, associatedId or "", category, filename, await request.body(),
                               category if category in core.ISSUANCE_EVIDENCE else "")
    core.save_db(db)
    return item


class DocumentVerification(BaseModel):
    verification: str
    note: Optional[str] = ""


@router.put("/api/documents/{id}/verification")
def verify_document(id: str, payload: DocumentVerification):
    """Slide 21: documents are checked against requirements by someone other than the uploader."""
    core._require_manager("Only an Owner / Admin or a Manager can verify documents.")
    db = core.load_db()
    item = core.require_child_visible(db, core._find_record(db.get("documents", []), id, "Document"), "Document")
    state = next((v for v in VERIFICATION_STATES if v.lower() == payload.verification.strip().lower()), None)
    if not state:
        raise HTTPException(status_code=422, detail=f"Verification must be one of: {', '.join(VERIFICATION_STATES)}")
    if state == "Rejected" and not (payload.note or "").strip():
        raise HTTPException(status_code=422, detail="Say why the document was rejected, so the customer can be asked for the right one.")
    item.update({"verification": state, "verificationNote": (payload.note or "").strip(),
                 "verifiedBy": current_actor("System"), "verifiedAt": datetime.utcnow().isoformat() + "Z"})
    core.audit(db, "Document Verified" if state == "Verified" else f"Document {state}", "Document", id,
          {"category": item.get("category"), "verification": state})
    core.save_db(db)
    return item


@router.get("/api/leads/{id}/document-status")
def get_lead_document_status(id: str):
    db = core.load_db()
    lead = core.require_visible(core._find_record(db.get("leads", []), id, "Lead"), core.visible_owners(db), "Lead")
    return core.document_status(db, lead)


@router.get("/api/documents/{id}/content")
def download_document(id: str, preview: bool = False):
    db = core.load_db()
    item = core.require_child_visible(db, core._find_record(db.get("documents", []), id, "Document"), "Document")
    root = os.path.abspath(core._company_data_root(core.DOCUMENT_ROOT)); path = os.path.abspath(os.path.join(root, item["storedName"]))
    if os.path.commonpath([root, path]) != root: raise HTTPException(status_code=404, detail="Document file not found")
    local = crm_storage.local_path(root, item["storedName"])
    disposition = "inline" if preview and item.get("contentType") in {"application/pdf","image/png","image/jpeg"} else "attachment"
    if local:
        if not os.path.exists(local): raise HTTPException(status_code=404, detail="Document file not found")
        return FileResponse(local, filename=item["originalName"], media_type=item.get("contentType"), content_disposition_type=disposition)
    try: content = crm_storage.get(root, current_company_id(), item["storedName"])
    except Exception: raise HTTPException(status_code=404, detail="Document file not found")
    return Response(content=content, media_type=item.get("contentType"), headers={"Content-Disposition":f'{disposition}; filename="{os.path.basename(item["originalName"])}"'})


@router.delete("/api/documents/{id}")
def archive_document(id: str):
    db = core.load_db(); item = core.require_child_visible(db, core._find_record(db.get("documents", []), id, "Document"), "Document"); item.update({"status":"Archived", "archivedAt":datetime.utcnow().isoformat()+"Z"})
    core.audit(db, "Document Archived", "Document", id, {"originalName":item.get("originalName")}); core.save_db(db); return item
