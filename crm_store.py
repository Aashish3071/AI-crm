"""Tenant-aware PostgreSQL persistence adapter.

The current domain service works with collection dictionaries. This adapter maps
those collections to constrained PostgreSQL rows and commits a complete company
revision transactionally. It is a migration bridge: domain-specific tables can be
split out later without changing API handlers.
"""
from __future__ import annotations

import json
import os
import threading
import tempfile
import fcntl
from contextlib import contextmanager
from typing import Any, Dict


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS crm_companies (
    id text PRIMARY KEY,
    revision bigint NOT NULL DEFAULT 0,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS crm_records (
    company_id text NOT NULL REFERENCES crm_companies(id) ON DELETE CASCADE,
    collection text NOT NULL,
    record_id text NOT NULL,
    data jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, collection, record_id),
    CONSTRAINT crm_collection_name CHECK (collection ~ '^[A-Za-z][A-Za-z0-9]*$')
);
CREATE INDEX IF NOT EXISTS crm_records_collection_idx ON crm_records(company_id, collection);
CREATE INDEX IF NOT EXISTS crm_records_data_gin_idx ON crm_records USING gin(data);
CREATE TABLE IF NOT EXISTS crm_links (
    company_id text NOT NULL,
    from_collection text NOT NULL,
    from_id text NOT NULL,
    relationship text NOT NULL,
    to_collection text NOT NULL,
    to_id text NOT NULL,
    PRIMARY KEY (company_id, from_collection, from_id, relationship, to_collection, to_id),
    FOREIGN KEY (company_id, from_collection, from_id)
        REFERENCES crm_records(company_id, collection, record_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (company_id, to_collection, to_id)
        REFERENCES crm_records(company_id, collection, record_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX IF NOT EXISTS crm_links_target_idx ON crm_links(company_id, to_collection, to_id);
"""

DIRECT_RELATIONSHIPS = {
    "leadId": "leads", "sourceLeadId": "leads", "customerId": "customers",
    "convertedCustomerId": "customers", "organizationId": "organizations",
    "policyId": "policies", "newPolicyId": "policies", "convertedPolicyId": "policies",
    "renewalId": "renewals", "quotationId": "quotations", "selectedQuotationId": "quotations",
    "contactId": "contacts", "channelId": "channels", "templateId": "communicationTemplates",
    "dealId": "deals", "calendarEventId": "calendarEvents", "sourceCalendarEventId": "calendarEvents",
    "followUpTaskId": "tasks", "taskId": "tasks",
}

ASSOCIATED_COLLECTIONS = {
    "Lead": "leads", "Customer": "customers", "Policy": "policies", "Renewal": "renewals",
    "Deal": "deals", "Contact": "contacts", "Organization": "organizations", "Service Request": "serviceRequests",
}

_LOCAL_LOCKS: Dict[str, threading.Lock] = {}


def load_json_state(path: str):
    """Never replace an unreadable database with demo data."""
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict):
            raise ValueError("Database must be an object")
        state.setdefault("_revision", 0)
        return state
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise RuntimeError("The CRM database cannot be read; restore a verified backup") from exc


def save_json_state(path: str, state: Dict[str, Any]) -> None:
    """Serialize revision checks across processes, then atomically replace the file."""
    path = os.path.abspath(path)
    with open(path + ".lock", "a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = load_json_state(path)
        revision = current.get("_revision", 0) if current else 0
        if current is not None and state.get("_revision", 0) != revision:
            raise RuntimeError("This company record changed during the operation; reload and retry")
        updated = {**state, "_revision": revision + 1}
        descriptor, temporary = tempfile.mkstemp(prefix="crm_db_", suffix=".json", dir=os.path.dirname(path))
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(updated, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            state["_revision"] = updated["_revision"]
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


@contextmanager
def scheduler_lock(company_id: str):
    """Only one scheduler may dispatch a company's outbox at a time."""
    if not configured():
        lock = _LOCAL_LOCKS.setdefault(company_id, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired: lock.release()
        return
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (f"insurecrm-scheduler:{company_id}",))
            acquired = bool(cursor.fetchone()[0])
        try:
            yield acquired
        finally:
            if acquired:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"insurecrm-scheduler:{company_id}",))


def configured() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL mode requires psycopg[binary]") from exc
    return psycopg.connect(os.environ["DATABASE_URL"])


def ensure_schema() -> None:
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(SCHEMA_SQL)


def load_state(company_id: str, initial: Dict[str, Any]) -> Dict[str, Any]:
    ensure_schema()
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT settings, revision FROM crm_companies WHERE id=%s", (company_id,))
            company = cursor.fetchone()
            if not company:
                # Close this read transaction before opening the transaction that creates
                # the company; this avoids nested connection/DDL locking during bootstrap.
                state = initial
            else:
                cursor.execute("SELECT collection, data FROM crm_records WHERE company_id=%s ORDER BY collection, updated_at", (company_id,))
                state = {"settings": company[0] or {}, "_revision": company[1]}
                for collection, data in cursor.fetchall():
                    state.setdefault(collection, []).append(data)
                return state
    save_state(company_id, state)
    return state


def save_state(company_id: str, state: Dict[str, Any]) -> None:
    ensure_schema()
    settings = state.get("settings", {})
    expected_revision = state.get("_revision")
    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT revision FROM crm_companies WHERE id=%s FOR UPDATE", (company_id,))
            row = cursor.fetchone()
            if row and expected_revision is not None and row[0] != expected_revision:
                raise RuntimeError("This company record changed during the operation; reload and retry")
            if row:
                next_revision = row[0] + 1
                cursor.execute("UPDATE crm_companies SET settings=%s::jsonb, revision=%s, updated_at=now() WHERE id=%s",
                               (json.dumps(settings), next_revision, company_id))
                # Remove links before replacing records: RESTRICT checks cannot be
                # deferred even when the foreign key is declared deferrable.
                cursor.execute("DELETE FROM crm_links WHERE company_id=%s", (company_id,))
                cursor.execute("DELETE FROM crm_records WHERE company_id=%s", (company_id,))
            else:
                next_revision = 1
                cursor.execute("INSERT INTO crm_companies(id, revision, settings) VALUES(%s,%s,%s::jsonb)",
                               (company_id, next_revision, json.dumps(settings)))
            rows = []
            for collection, records in state.items():
                if collection.startswith("_") or collection == "settings" or not isinstance(records, list):
                    continue
                for index, record in enumerate(records):
                    record_id = str(record.get("id") or record.get("archiveId") or f"ROW_{index}")
                    rows.append((company_id, collection, record_id, json.dumps(record)))
            if rows:
                cursor.executemany("INSERT INTO crm_records(company_id,collection,record_id,data) VALUES(%s,%s,%s,%s::jsonb)", rows)
            existing = {(collection, record_id) for _, collection, record_id, _ in rows}
            archived_targets = {("leads", str(item["id"])): ("archivedLeads", str(item["id"]))
                                for item in state.get("archivedLeads", []) if item.get("id")}
            archived_targets.update({(item.get("sourceCollection"), str(item.get("record", {}).get("id"))):
                                     ("archivedRecords", str(item.get("archiveId")))
                                     for item in state.get("archivedRecords", [])})
            links = []
            for _, collection, record_id, raw_record in rows:
                record = json.loads(raw_record)
                for field, target_collection in DIRECT_RELATIONSHIPS.items():
                    target_id = str(record.get(field) or "")
                    if not target_id:
                        continue
                    if (target_collection, target_id) not in existing:
                        target_collection, target_id = archived_targets.get(
                            (target_collection, target_id), (target_collection, target_id))
                    if (target_collection, target_id) not in existing:
                        raise RuntimeError(f"Broken relationship: {collection}/{record_id}.{field} -> {target_collection}/{target_id}")
                    links.append((company_id, collection, record_id, field, target_collection, target_id))
                associated_id = str(record.get("associatedId") or "")
                target_collection = ASSOCIATED_COLLECTIONS.get(str(record.get("associatedType") or ""))
                if (target_collection, associated_id) not in existing:
                    target_collection, associated_id = archived_targets.get(
                        (target_collection, associated_id), (target_collection, associated_id))
                if associated_id and target_collection and (target_collection, associated_id) in existing:
                    links.append((company_id, collection, record_id, "associatedId", target_collection, associated_id))
            if links:
                cursor.executemany("INSERT INTO crm_links(company_id,from_collection,from_id,relationship,to_collection,to_id) "
                                   "VALUES(%s,%s,%s,%s,%s,%s)", links)
    state["_revision"] = next_revision
