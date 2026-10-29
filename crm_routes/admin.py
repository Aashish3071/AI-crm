"""Administration: data integrity reports and repairs, the audit log, archived records,
demo data clean-up and the health check.
"""
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

import crm_store
import pipecat_server as core

router = APIRouter()


def verify_audit_chain(db: Dict[str, Any]) -> Dict[str, Any]:
    key = os.environ.get("AUDIT_SIGNING_KEY", "") or "insurecrm-development-audit-key"
    signed = [event for event in reversed(db.get("auditLogs", [])) if event.get("eventHash")]
    previous = ""; invalid = []
    for event in signed:
        expected_event = {key_name:value for key_name,value in event.items() if key_name != "eventHash"}
        canonical = json.dumps(expected_event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        expected = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        if event.get("previousHash", "") != previous or not hmac.compare_digest(expected, event.get("eventHash", "")):
            invalid.append(event.get("id"))
        previous = event.get("eventHash", "")
    return {"valid": not invalid, "signedEvents": len(signed), "legacyUnsignedEvents": len(db.get("auditLogs", [])) - len(signed),
            "invalidEventIds": invalid}


@router.get("/api/admin/integrity")
def get_integrity_report():
    return core.relational_integrity(core.load_db())


@router.get("/api/admin/audit-integrity")
def get_audit_integrity():
    return verify_audit_chain(core.load_db())


@router.post("/api/admin/repair-relations")
def repair_relations(dryRun: bool = True):
    db = core.load_db()
    if dryRun:
        clone = json.loads(json.dumps(db))
        return {**core.repair_relational_model(clone), "dryRun": True}
    backup = core._create_backup("Pre relationship-repair") if not crm_store.configured() else None
    result = core.repair_relational_model(db)
    core.save_db(db)
    return {**result, "dryRun": False, "backup": backup}


@router.get("/api/audit-logs")
def get_audit_logs(entityId: Optional[str] = None):
    items = core.load_db().get("auditLogs", [])
    return [a for a in items if not entityId or a.get("entityId") == entityId]


DEMO_SEED_IDS = {
    "leads": {"L1", "L2", "L3", "L4", "L5", "L6"},
    "deals": {"D1", "D2", "D3", "D4"},
    "contacts": {"C1", "C2", "C3", "C4", "C5"},
    "organizations": {"O1", "O2", "O3", "O4", "O5"},
    "notes": {"N1", "N2", "N3"},
    "tasks": {"T1", "T2", "T3", "T4"},
    "users": {"U1", "U2", "U3", "U4"},
}


DEMO_COLLECTIONS = ["leads", "deals", "contacts", "organizations", "notes", "tasks",
                    "customers", "policies", "renewals", "quotations", "communications",
                    "consents", "notifications", "documents", "callQueue", "callLogs"]


def _is_demo(collection: str, record: Any) -> bool:
    # Some collections (callQueue) hold bare ids rather than records.
    if isinstance(record, str):
        return record in DEMO_SEED_IDS.get("leads", set())
    if not isinstance(record, dict):
        return False
    if record.get("isDemo") is True:
        return True
    return record.get("id") in DEMO_SEED_IDS.get(collection, set())


def _demo_summary(db: Dict[str, Any]) -> Dict[str, Any]:
    counts, total = {}, 0
    for collection in DEMO_COLLECTIONS:
        found = [r for r in db.get(collection, []) if _is_demo(collection, r)]
        if found:
            counts[collection] = len(found)
            total += len(found)
    demo_leads = [l for l in db.get("leads", []) if _is_demo("leads", l)]
    return {"total": total, "byCollection": counts,
            "sampleNames": [l.get("name", "") for l in demo_leads[:6]],
            "realLeadCount": len([l for l in db.get("leads", []) if not _is_demo("leads", l)])}


@router.get("/api/demo-data")
def preview_demo_data():
    """What a cleanup would remove — shown before anything is deleted."""
    return _demo_summary(core.load_db())


@router.post("/api/demo-data/purge")
def purge_demo_data(payload: Optional[Dict[str, Any]] = None):
    db = core.load_db()
    summary = _demo_summary(db)
    if not summary["total"]:
        raise HTTPException(status_code=404, detail="There is no demo data left to remove.")

    safety = core._create_backup("Pre demo-data cleanup")     # always recoverable
    removed_lead_ids = {l["id"] for l in db.get("leads", []) if _is_demo("leads", l)}
    removed: Dict[str, int] = {}
    for collection in DEMO_COLLECTIONS:
        keep, dropped = [], 0
        for record in db.get(collection, []):
            # Child records attached to a demo lead go with it. Some collections hold bare ids.
            attached_to_demo = (record in removed_lead_ids) if isinstance(record, str) else (
                record.get("associatedId") in removed_lead_ids or record.get("leadId") in removed_lead_ids)
            if _is_demo(collection, record) or attached_to_demo:
                dropped += 1
            else:
                keep.append(record)
        if dropped:
            db[collection] = keep
            removed[collection] = dropped

    if (payload or {}).get("includeUsers"):
        seeded = [u for u in db.get("users", []) if u.get("id") in DEMO_SEED_IDS["users"]]
        owners = {l.get("assignedTo") for l in db.get("leads", [])}
        # Never remove someone who still owns live work.
        drop = [u for u in seeded if u.get("name") not in owners]
        if drop:
            db["users"] = [u for u in db.get("users", []) if u not in drop]
            removed["users"] = len(drop)

    core.audit(db, "Demo Data Cleared", "System", "demo", {"removed": removed, "safetyBackup": safety["name"]})
    core.save_db(db)
    return {"removed": removed, "removedTotal": sum(removed.values()), "safetyBackup": safety["name"],
            "remainingLeads": len(db.get("leads", []))}


ARCHIVABLE_COLLECTIONS = {"leads":"Lead", "policies":"Policy", "renewals":"Renewal", "deals":"Deal", "contacts":"Contact", "organizations":"Organization"}


@router.post("/api/records/{collection}/{id}/archive")
def archive_operational_record(collection: str, id: str):
    if collection not in ARCHIVABLE_COLLECTIONS: raise HTTPException(status_code=422, detail="Unsupported record type")
    db=core.load_db(); item=core._find_record(db.get(collection,[]),id,ARCHIVABLE_COLLECTIONS[collection]); db[collection]=[x for x in db.get(collection,[]) if x.get("id")!=id]
    archived={"archiveId":f"ARC_{uuid.uuid4().hex[:8]}","sourceCollection":collection,"record":item,"archivedAt":datetime.utcnow().isoformat()+"Z"}; db.setdefault("archivedRecords",[]).insert(0,archived)
    core.audit(db,f"{ARCHIVABLE_COLLECTIONS[collection]} Archived",ARCHIVABLE_COLLECTIONS[collection],id,{"archiveId":archived["archiveId"]}); core.save_db(db); return archived


@router.post("/api/archived-records/{archive_id}/restore")
def restore_operational_record(archive_id: str):
    # Archive entries are keyed by archiveId, not id — looking them up by id made every
    # archived policy/renewal/deal impossible to restore.
    db=core.load_db()
    archived=next((x for x in db.get("archivedRecords",[]) if x.get("archiveId")==archive_id), None)
    if not archived: raise HTTPException(status_code=404, detail="Archived record not found")
    collection=archived.get("sourceCollection")
    if collection not in ARCHIVABLE_COLLECTIONS: raise HTTPException(status_code=422, detail="Unsupported archived record")
    record=archived["record"]
    if any(x.get("id")==record.get("id") for x in db.get(collection,[])): raise HTTPException(status_code=409, detail="A live record with this ID already exists")
    db.setdefault(collection,[]).insert(0,record); db["archivedRecords"]=[x for x in db.get("archivedRecords",[]) if x.get("archiveId")!=archive_id]
    core.audit(db,f"{ARCHIVABLE_COLLECTIONS[collection]} Restored",ARCHIVABLE_COLLECTIONS[collection],record["id"],{"archiveId":archive_id}); core.save_db(db); return record


@router.get("/api/archived-records")
def get_archived_records(): return core.load_db().get("archivedRecords",[])


@router.get("/api/health")
def health():
    db = core.load_db(); return {"status":"ok","database":"postgresql" if crm_store.configured() else "json",
                            "records":{key:len(value) for key,value in db.items() if isinstance(value,list)},
                            "scheduler":"worker" if os.environ.get("SCHEDULER_PROCESS") == "1" else ("embedded" if os.environ.get("ENABLE_REMINDER_SCHEDULER","1") == "1" else "disabled")}
