"""Global search and entity lookup, limited to the records the caller may see.
"""
from typing import Any, Dict

from fastapi import APIRouter, Query

import pipecat_server as core

router = APIRouter()


@router.get("/api/entities")
def get_entities():
    """Records a task, note or appointment can be attached to — only the caller's own.

    This list feeds the pickers in every form, so it was sending the whole company's
    customers and phone numbers to every telecaller's browser.
    """
    db = core.load_db()
    owners = core.visible_owners(db)
    ids = core.visible_ids(db, owners)
    mine = lambda r: owners is None or core._owned_by(r, owners) or core.child_visible(r, ids, owners)
    entities = []
    for l in db.get("leads", []):
        if mine(l):
            entities.append({"id": l["id"], "title": l["name"], "type": "Lead",
                             "subtitle": " • ".join(x for x in (l.get("product") or l.get("policyType"), l.get("mobile")) if x)})
    for c in db.get("customers", []):
        if mine(c):
            entities.append({"id": c["id"], "title": c.get("name"), "type": "Customer",
                             "subtitle": c.get("mobile") or c.get("email", "")})
    for p in db.get("policies", []):
        if mine(p):
            entities.append({"id": p["id"], "title": f"{p.get('policyNumber') or 'Draft policy'} — {p.get('customerName')}",
                             "type": "Policy", "subtitle": p.get("policyType", "")})
    for r in db.get("renewals", []):
        if mine(r):
            entities.append({"id": r["id"], "title": f"Renewal — {r.get('customerName')}", "type": "Renewal",
                             "subtitle": r.get("policyNumber", "")})
    for s in db.get("serviceRequests", []):
        if mine(s):
            entities.append({"id": s["id"], "title": f"{s.get('requestType')} — {s.get('customerName')}",
                             "type": "Service Request", "subtitle": s.get("policyNumber", "")})
    return entities


@router.get("/api/search")
def global_search(q: str = Query(..., min_length=2), limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
    db = core.load_db(); needle = q.strip().lower(); results = []
    specs = [
        # Deals, contacts and organisations are no longer part of the telecalling workflow.
        ("leads", "Lead", "leads", ["name", "organization", "email", "mobile", "policyNumber", "city"]),
        ("customers", "Customer", "customers", ["name", "organization", "email", "mobile"]),
        ("policies", "Policy", "policies", ["policyNumber", "customerName", "organization", "policyType", "insurer"]),
        ("renewals", "Renewal", "renewals", ["policyNumber", "customerName", "organization"]),
        ("tasks", "Task", "tasks", ["title", "description", "assignedTo", "associatedTitle"]),
        ("serviceRequests", "Service Request", "customers", ["description", "requestType", "customerName", "policyNumber"]),
    ]
    owners = core.visible_owners(db)
    ids, orgs = core.visible_ids(db, owners), core._visible_org_names(db, owners)

    def allowed(collection: str, item: Dict[str, Any]) -> bool:
        if owners is None:
            return True
        if collection == "contacts":
            return core.contact_visible(item, ids, orgs)
        if collection == "organizations":
            name = (item.get("name") or "").strip().lower()
            return name not in core._SHARED_ORGANIZATIONS and name in orgs
        return core._owned_by(item, owners) if "assignedTo" in item else core.child_visible(item, ids, owners)

    for collection, label, view, fields in specs:
        for item in db.get(collection, []):
            if not allowed(collection, item): continue
            matching = next((str(item.get(field, "")) for field in fields if needle in str(item.get(field, "")).lower()), "")
            if not matching: continue
            title = item.get("title") or item.get("name") or item.get("customerName") or item.get("policyNumber") or item.get("dealName") or item.get("id")
            subtitle = item.get("associatedTitle") or item.get("description") or item.get("organization") or item.get("policyType") or item.get("email") or matching
            results.append({"id": item.get("id"), "type": label, "view": view, "title": title, "subtitle": subtitle,
                            "customerId": item.get("customerId", ""), "leadId": item.get("leadId", "")})
    return results[offset:offset + limit]
