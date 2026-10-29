"""Data export and backups (client blueprint, slides 41–42). Owner only.
"""
import csv
import io
import json
import os
import tempfile
import zipfile
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

import crm_schema
import crm_storage
import pipecat_server as core
from crm_security import current_company_id

router = APIRouter()


# The business owns its data and must be able to take all of it away without a developer:
# one ZIP with a spreadsheet per kind of record, a complete JSON copy, and optionally every
# uploaded document. Owner / Admin only; every export is recorded in the audit log.
EXPORT_SHEETS = [
    ("leads", "leads", "Every enquiry, open and closed, with its status, source and details"),
    ("customers", "customers", "People who bought, with contact details and preferences"),
    ("policies", "policies", "Policies sold, with insurer, premium, dates and commission"),
    ("renewals", "renewals", "Renewal records and their outcomes"),
    ("callLogs", "calls", "Every call: telecaller, outcome, duration and notes"),
    ("quotations", "quotations", "Quotations and their status history"),
    ("tasks", "follow-ups", "Follow-ups and other tasks, open and completed"),
    ("notes", "notes", "Notes written on records"),
    ("documents", "documents", "The list of uploaded documents (the files themselves are in documents/ when included)"),
    ("communications", "messages", "WhatsApp and email messages sent and received"),
    ("calendarEvents", "calendar", "Meetings and calls booked in the calendar"),
    ("users", "team", "Team members and roles (no passwords — sign-in details are stored separately)"),
    ("incentiveStatements", "incentive-statements", "Approved monthly incentive statements"),
    ("auditLogs", "audit-log", "Who did what and when"),
]


_SKIP_EXPORT_FIELDS = {"automationState", "automationKeys"}


def _cell(value: Any) -> Any:
    """A spreadsheet-safe cell: nested values as JSON, and text that a spreadsheet would run as a
    formula (a value typed into a public web form can start with = + - @) kept as text."""
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def _csv_bytes(records: List[Dict[str, Any]]) -> bytes:
    columns: List[str] = []
    for record in records:
        for key in record:
            if key not in columns and key not in _SKIP_EXPORT_FIELDS and not key.startswith("_"):
                columns.append(key)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    for record in records:
        writer.writerow([_cell(record.get(c, "")) for c in columns])
    return out.getvalue().encode("utf-8-sig")          # the BOM makes Excel read ₹ and Indian names correctly


def _lead_rows(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Leads with one column per custom field, titled with its label, instead of one JSON cell.
    Hidden fields are included: an export is the company's whole record."""
    defs = core.custom_field_defs(db, "lead")
    rows = []
    for lead in db.get("leads") or []:
        if not isinstance(lead, dict):
            continue
        row = {k: v for k, v in lead.items() if k != "custom"}
        for d in defs:
            column = d["label"] if d["label"] not in row else f"{d['label']} (custom)"
            row[column] = crm_schema.display_value(d, (lead.get("custom") or {}).get(d["key"]))
        rows.append(row)
    return rows


def _target_rows(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"month": month, "person": person, **measures}
            for month, people in sorted((db.get("targets") or {}).items()) for person, measures in sorted(people.items())]


@router.get("/api/export")
def export_data(includeFiles: bool = False):
    core._require_admin("Only the Owner / Admin can export the company's data.")
    db = core.load_db()
    now = datetime.now(core._calendar_timezone(db))
    sheets = [(label, _lead_rows(db) if key == "leads" else db.get(key) or [], about) for key, label, about in EXPORT_SHEETS]
    sheets.append(("targets", _target_rows(db), "Monthly targets by person"))
    counts = {label: len(rows) for label, rows, _ in sheets}
    missing_files = 0
    handle = tempfile.NamedTemporaryFile(prefix="crm-export-", suffix=".zip", delete=False)
    handle.close()
    with zipfile.ZipFile(handle.name, "w", zipfile.ZIP_DEFLATED) as archive:
        for label, rows, _ in sheets:
            archive.writestr(f"{label}.csv", _csv_bytes([r for r in rows if isinstance(r, dict)]))
        archive.writestr("crm-data.json", json.dumps({k: v for k, v in db.items() if not k.startswith("_")},
                                                     ensure_ascii=False, indent=1))
        if includeFiles:
            root = os.path.abspath(core._company_data_root(core.DOCUMENT_ROOT))
            used: set = set()
            for item in db.get("documents", []):
                if item.get("status") == "Archived" or not item.get("storedName"):
                    continue
                try:
                    local = crm_storage.local_path(root, item["storedName"])
                    content = open(local, "rb").read() if local else crm_storage.get(root, current_company_id(), item["storedName"])
                except Exception:
                    missing_files += 1
                    continue
                name = f"documents/{item['id']}-{os.path.basename(item.get('originalName') or item['storedName'])}"
                if name not in used:
                    used.add(name)
                    archive.writestr(name, content)
        lines = [f"InsureCRM data export — {now.strftime('%d %B %Y, %H:%M')} ({core._calendar_timezone(db)})", "",
                 "Each .csv file opens in Excel or Google Sheets. One row per record; values that hold several",
                 "pieces of information (vehicle details, status history) are written as JSON text.",
                 "Text beginning with = + - or @ is prefixed with an apostrophe so a spreadsheet shows it rather than running it.", ""]
        lines += [f"  {label}.csv — {counts[label]} row{'' if counts[label] == 1 else 's'}. {about}" for label, _, about in sheets]
        lines += ["", "  crm-data.json — everything above in one file, for moving to another system or restoring.",
                  "  documents/ — " + ("the uploaded files, named by document id." if includeFiles else "not included in this export."),
                  "", "Sign-in passwords are never exported."]
        if missing_files:
            lines.append(f"{missing_files} document file(s) could not be read and are listed in documents.csv only.")
        archive.writestr("README.txt", "\n".join(lines))
    core.audit(db, "Data Exported", "Company", current_company_id(), {"includeFiles": includeFiles, "rows": counts,
                                                                   "missingFiles": missing_files})
    core.save_db(db)
    filename = f"insurecrm-export-{now.strftime('%Y-%m-%d-%H%M')}.zip"
    return FileResponse(handle.name, filename=filename, media_type="application/zip",
                        background=BackgroundTask(os.unlink, handle.name))


@router.get("/api/backups")
def list_backups():
    backup_root = core._company_data_root(core.BACKUP_ROOT)
    if not os.path.isdir(backup_root): return []
    return [{"name":name,"size":os.path.getsize(os.path.join(backup_root,name))} for name in sorted(os.listdir(backup_root), reverse=True) if name.endswith(".json")]


@router.post("/api/backups")
def create_backup():
    item = core._create_backup(); db = core.load_db(); db.setdefault("backupLogs", []).insert(0,item); core.audit(db,"Backup Created","Backup",item["name"],item); core.save_db(db); return item


@router.post("/api/backups/{name}/restore")
def restore_backup(name: str):
    if name != os.path.basename(name) or not name.endswith(".json"): raise HTTPException(status_code=422, detail="Invalid backup name")
    path = os.path.join(core._company_data_root(core.BACKUP_ROOT), name)
    if not os.path.exists(path): raise HTTPException(status_code=404, detail="Backup not found")
    with open(path, "r", encoding="utf-8") as handle: restored_db = json.load(handle)
    safety = core._create_backup("Pre-restore safety copy")
    restored_db = core._ensure_db_shape(restored_db)
    restored_db["_revision"] = core.load_db().get("_revision", 0)
    core.audit(restored_db, "Backup Restored", "Backup", name, {"safetyBackup": safety["name"]})
    core.save_db(restored_db)
    return {"restored":name,"safetyBackup":safety["name"]}
