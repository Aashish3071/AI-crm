"""Messages to customers: templates, consent, email and WhatsApp sending, WhatsApp
template registration with Meta, and the per-lead message composer.
"""
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


class CommunicationModel(BaseModel):
    associatedType: Optional[str] = "Lead"
    associatedId: str
    recipient: str
    channel: str
    templateId: Optional[str] = ""
    subject: Optional[str] = ""
    content: str
    direction: Optional[str] = "Outbound"
    scheduledAt: Optional[str] = ""
    author: Optional[str] = None
    createdBy: Optional[str] = None


class TemplateModel(BaseModel):
    name: str
    channel: str
    subject: Optional[str] = ""
    content: str
    status: Optional[str] = "Active"


class ConsentModel(BaseModel):
    contactId: Optional[str] = ""
    leadId: Optional[str] = ""
    channel: str
    status: str
    source: Optional[str] = "Manual"
    notes: Optional[str] = ""


@router.get("/api/communication-templates")
def get_communication_templates(channel: Optional[str] = None, includeArchived: bool = False):
    templates = core.load_db().get("communicationTemplates", [])
    return [t for t in templates
            if str(t.get("channel", "")).lower() != "sms"
            if (includeArchived or t.get("status") != "Archived")
            and (not channel or t.get("channel") == channel)]


@router.post("/api/communication-templates")
def create_communication_template(payload: TemplateModel):
    if payload.channel.lower() not in {"email", "whatsapp"}:
        raise HTTPException(status_code=422, detail="Templates are supported for Email and WhatsApp only")
    db = core.load_db()
    item = payload.model_dump()
    item.update({"id": f"TPL_{uuid.uuid4().hex[:8]}", "createdAt": datetime.utcnow().isoformat() + "Z"})
    db.setdefault("communicationTemplates", []).insert(0, item)
    core.audit(db, "Communication Template Created", "Communication Template", item["id"], item)
    core.save_db(db)
    return item


@router.put("/api/communication-templates/{id}")
def update_communication_template(id: str, updates: Dict[str, Any]):
    if "channel" in updates and str(updates["channel"]).lower() not in {"email", "whatsapp"}:
        raise HTTPException(status_code=422, detail="Templates are supported for Email and WhatsApp only")
    return core.update_record("communicationTemplates", id, updates, {"name", "channel", "subject", "content", "status"}, "Communication Template")


@router.post("/api/communication-templates/{id}/restore")
def restore_communication_template(id: str):
    db = core.load_db(); item = core._find_record(db.get("communicationTemplates", []), id, "Communication template")
    item["status"] = "Active"; item.pop("archivedAt", None)
    item["updatedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Communication Template Restored", "Communication Template", id, {"name": item.get("name")})
    core.save_db(db); return item


@router.delete("/api/communication-templates/{id}")
def delete_communication_template(id: str, permanent: bool = False):
    db = core.load_db(); templates = db.get("communicationTemplates", [])
    item = core._find_record(templates, id, "Communication template")
    if permanent:
        if item.get("status") != "Archived":
            raise HTTPException(status_code=409, detail="Archive the template before permanently deleting it")
        templates.remove(item)
        core.audit(db, "Communication Template Permanently Deleted", "Communication Template", id,
              {"name": item.get("name"), "channel": item.get("channel")})
        core.save_db(db); return {"status": "deleted", "id": id}
    item["status"] = "Archived"; item["archivedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Communication Template Archived", "Communication Template", id, {"name": item.get("name")})
    core.save_db(db); return item


@router.get("/api/consents")
def get_consents(leadId: Optional[str] = None):
    items = core.load_db().get("consents", [])
    return [c for c in items if not leadId or c.get("leadId") == leadId]


@router.post("/api/consents")
def record_consent(payload: ConsentModel):
    db = core.load_db()
    if payload.status not in ["Opted In", "Opted Out", "Unknown"]:
        raise HTTPException(status_code=422, detail="Invalid consent status")
    now_str = datetime.utcnow().isoformat() + "Z"
    existing = next((c for c in db.get("consents", []) if c.get("leadId") == payload.leadId and c.get("contactId") == payload.contactId and c.get("channel") == payload.channel), None)
    if existing:
        before = dict(existing)
        existing.update(payload.model_dump())
        existing["updatedAt"] = now_str
        item = existing
    else:
        item = payload.model_dump()
        item.update({"id": f"CON_{uuid.uuid4().hex[:8]}", "createdAt": now_str, "updatedAt": now_str})
        db.setdefault("consents", []).insert(0, item)
        before = {}
    core.audit(db, "Consent Recorded", "Consent", item["id"], {"before": before, "after": item})
    core.save_db(db)
    return item


@router.get("/api/communications")
def get_communications(associatedId: Optional[str] = None):
    db = core.load_db()
    owners = core.visible_owners(db)
    ids = core.visible_ids(db, owners)
    return [c for c in db.get("communications", []) if core.child_visible(c, ids, owners)
            and (not associatedId or c.get("associatedId") == associatedId)]


@router.post("/api/communications")
def create_communication(payload: CommunicationModel):
    db = core.load_db()
    if payload.channel.lower() not in {"email", "whatsapp"}:
        raise HTTPException(status_code=422, detail="Communications are supported for Email and WhatsApp only")
    if payload.templateId:
        templates = db.get("communicationTemplates", []) + db.get("templates", []) + db.get("whatsappTemplates", [])
        if not any(t.get("id") == payload.templateId for t in templates):
            raise HTTPException(status_code=422, detail="Template referenced by templateId does not exist")
    # A message belongs to a record; the sender must be able to see that record.
    owners = core.visible_owners(db)
    if owners is not None and not core.child_visible({"associatedId": payload.associatedId}, core.visible_ids(db, owners), owners):
        raise HTTPException(status_code=404, detail="Record not found")
    if payload.direction == "Outbound" and not core._consent_allows(db, payload.associatedId, payload.channel, payload.recipient):
        raise HTTPException(status_code=409, detail=f"Recipient has opted out of {payload.channel}")
    now_str = datetime.utcnow().isoformat() + "Z"
    actor = current_actor("System")
    item = payload.model_dump()
    item.update({"id": f"COM_{uuid.uuid4().hex[:8]}", "status": "Scheduled" if payload.scheduledAt else "Queued",
                 "author": actor, "createdBy": actor,
                 "providerMessageId": "", "deliveryEvents": [{"status": "Queued", "at": now_str}], "createdAt": now_str})
    db.setdefault("communications", []).insert(0, item)
    core.audit(db, "Communication Created", "Communication", item["id"], {"channel": item.get("channel"), "recipient": item.get("recipient")})
    core.save_db(db)
    return item


@router.get("/api/communications/{id}")
def get_communication(id: str):
    db = core.load_db()
    return core.require_child_visible(db, core._find_record(db.get("communications", []), id, "Communication"), "Communication")


@router.post("/api/communications/{id}/send")
def send_communication(id: str):
    db = core.load_db()
    item = core.require_child_visible(db, core._find_record(db.get("communications", []), id, "Communication"), "Communication")
    if item.get("status") in ("Sent", "Delivered", "Read"):
        return item
    if item.get("direction") == "Outbound" and not core._consent_allows(db, item.get("associatedId", ""), item.get("channel", ""), item.get("recipient", "")):
        raise HTTPException(status_code=409, detail=f"Recipient has opted out of {item.get('channel')}")
    res = core._dispatch(db, item)
    if isinstance(res, dict):
        if res.get("status"):
            item["status"] = res["status"]
        if res.get("providerMessageId"):
            item["providerMessageId"] = res["providerMessageId"]
    core.audit(db, "Communication Sent", "Communication", id,
          {"status": item.get("status", "Sent"), "channel": item.get("channel"), "providerMessageId": item.get("providerMessageId", "")})
    core.save_db(db)
    return item


WHATSAPP_CATEGORIES = ["UTILITY", "MARKETING", "AUTHENTICATION"]


META_TEMPLATE_STATUSES = {"APPROVED": "Approved", "PENDING": "Pending review", "REJECTED": "Rejected",
                          "PAUSED": "Paused by Meta", "DISABLED": "Disabled by Meta"}


def _meta_template_name(name: str) -> str:
    """Meta only accepts lowercase letters, digits and underscores."""
    slug = re.sub(r"[^a-z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    return slug[:512] or f"template_{uuid.uuid4().hex[:6]}"


def _to_positional(body: str) -> Dict[str, Any]:
    """Turn 'Hello {{name}}, your {{policyType}}…' into Meta's 'Hello {{1}}, your {{2}}…'."""
    variables: List[str] = []
    def swap(match):
        token = match.group(1).strip()
        if token not in variables:
            variables.append(token)
        return "{{" + str(variables.index(token) + 1) + "}}"
    positional = re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", swap, body or "")
    return {"text": positional, "variables": variables}


# Filled into a template's preview only — never sent to a customer.
SAMPLE_VALUES = {"name": "Rahul Mehta", "organization": "",
                 "policyType": "Car Insurance", "policyNumber": "CAR-2291-MH",
                 "premium": "12,500", "expiryDate": "12 October 2026", "daysRemaining": "15",
                 "nextAction": "Collect RC and previous policy", "nextActionDate": "30 September 2026",
                 "assignedTo": "Your telecaller"}


def _whatsapp_channel(db: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((c for c in db.get("channels", []) if c.get("provider") == "whatsapp"), None)


def _meta_template_request(channel: Dict[str, Any], method: str, path: str,
                           payload: Optional[Dict[str, Any]] = None,
                           params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    creds = core._usable_credentials(channel)
    waba_id, token = creds.get("wabaId"), creds.get("accessToken")
    if not waba_id or not token:
        return {"ok": False, "offline": True,
                "error": "Add your WhatsApp Business Account ID and access token in Sending setup to submit templates to Meta."}
    url = f"{core.GRAPH_API_BASE}/{core.WHATSAPP_API_VERSION}/{waba_id}/{path}".rstrip("/")
    try:
        response = httpx.request(method, url, timeout=25.0,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                                 json=payload, params=params)
        data = response.json() if response.content else {}
        if response.status_code >= 400:
            return {"ok": False, "error": ((data.get("error") or {}).get("message")
                                           or f"Meta returned HTTP {response.status_code}")}
        return {"ok": True, "data": data}
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach Meta: {exc}"}


class WhatsAppTemplate(BaseModel):
    name: str
    category: Optional[str] = "UTILITY"
    language: Optional[str] = "en_US"
    body: str
    footer: Optional[str] = ""
    submit: Optional[bool] = True


@router.get("/api/whatsapp-templates")
def list_whatsapp_templates():
    return core.load_db().get("whatsappTemplates", [])


@router.post("/api/whatsapp-templates")
def create_whatsapp_template(payload: WhatsAppTemplate):
    """Write a template locally, then submit it to Meta for approval."""
    db = core.load_db()
    category = (payload.category or "UTILITY").upper()
    if category not in WHATSAPP_CATEGORIES:
        raise HTTPException(status_code=422, detail=f"Category must be one of {', '.join(WHATSAPP_CATEGORIES)}")
    if not payload.body.strip():
        raise HTTPException(status_code=422, detail="The message body cannot be empty")
    if len(payload.body) > 1024:
        raise HTTPException(status_code=422, detail="Meta limits the body to 1024 characters")

    meta_name = _meta_template_name(payload.name)
    if any(t.get("metaName") == meta_name for t in db.get("whatsappTemplates", [])):
        raise HTTPException(status_code=409, detail="A template with this name already exists")

    converted = _to_positional(payload.body)
    unknown = [v for v in converted["variables"] if v not in core.TEMPLATE_TOKENS]
    if unknown:
        raise HTTPException(status_code=422,
                            detail=f"Unknown placeholder(s): {', '.join('{{' + u + '}}' for u in unknown)}")

    now_str = datetime.utcnow().isoformat() + "Z"
    item = {"id": f"WAT_{uuid.uuid4().hex[:8]}", "name": payload.name.strip(), "metaName": meta_name,
            "category": category, "language": payload.language or "en_US", "body": payload.body,
            "positionalBody": converted["text"], "variables": converted["variables"],
            "footer": (payload.footer or "").strip(), "status": "Draft", "metaId": "",
            "rejectedReason": "", "createdAt": now_str, "updatedAt": now_str}

    if payload.submit:
        channel = _whatsapp_channel(db)
        if not channel:
            item["statusNote"] = "Saved as a draft — connect WhatsApp in Lead Sources to submit it to Meta."
        else:
            components: List[Dict[str, Any]] = [{"type": "BODY", "text": converted["text"]}]
            if converted["variables"]:
                components[0]["example"] = {"body_text": [[SAMPLE_VALUES.get(v, v) for v in converted["variables"]]]}
            if item["footer"]:
                components.append({"type": "FOOTER", "text": item["footer"]})
            result = _meta_template_request(channel, "POST", "message_templates", payload={
                "name": meta_name, "language": item["language"], "category": category, "components": components})
            if result.get("ok"):
                data = result["data"]
                item.update({"metaId": data.get("id", ""),
                             "status": META_TEMPLATE_STATUSES.get(str(data.get("status", "PENDING")).upper(), "Pending review"),
                             "submittedAt": now_str})
            else:
                item.update({"status": "Draft", "statusNote": result.get("error", "")})

    db.setdefault("whatsappTemplates", []).insert(0, item)
    core.audit(db, "WhatsApp Template Created", "WhatsApp Template", item["id"],
          {"name": item["name"], "metaName": meta_name, "status": item["status"]})
    core.save_db(db)
    return item


@router.post("/api/whatsapp-templates/{id}/submit")
def submit_whatsapp_template(id: str):
    """Send (or resend) a draft to Meta — used after fixing a rejection."""
    db = core.load_db()
    item = core._find_record(db.get("whatsappTemplates", []), id, "WhatsApp template")
    if item.get("status") in ["Pending review", "Approved"]:
        raise HTTPException(status_code=409, detail=f"This template is already {item['status'].lower()}")
    channel = _whatsapp_channel(db)
    if not channel:
        raise HTTPException(status_code=422, detail="Connect WhatsApp in Lead Sources before submitting templates")

    components: List[Dict[str, Any]] = [{"type": "BODY", "text": item["positionalBody"]}]
    if item.get("variables"):
        components[0]["example"] = {"body_text": [[SAMPLE_VALUES.get(v, v) for v in item["variables"]]]}
    if item.get("footer"):
        components.append({"type": "FOOTER", "text": item["footer"]})

    result = _meta_template_request(channel, "POST", "message_templates", payload={
        "name": item["metaName"], "language": item["language"], "category": item["category"], "components": components})
    now_str = datetime.utcnow().isoformat() + "Z"
    if not result.get("ok"):
        item.update({"statusNote": result.get("error", ""), "updatedAt": now_str})
        core.save_db(db)
        raise HTTPException(status_code=502, detail=result.get("error", "Meta rejected the submission"))
    data = result["data"]
    item.update({"metaId": data.get("id", ""), "rejectedReason": "", "statusNote": "",
                 "status": META_TEMPLATE_STATUSES.get(str(data.get("status", "PENDING")).upper(), "Pending review"),
                 "submittedAt": now_str, "updatedAt": now_str})
    core.audit(db, "WhatsApp Template Submitted", "WhatsApp Template", id, {"metaName": item["metaName"]})
    core.save_db(db)
    return item


@router.post("/api/whatsapp-templates/sync")
def sync_whatsapp_templates():
    """Pull current approval status for every template from Meta."""
    db = core.load_db()
    channel = _whatsapp_channel(db)
    if not channel:
        raise HTTPException(status_code=422, detail="Connect WhatsApp in Lead Sources first")
    result = _meta_template_request(channel, "GET", "message_templates",
                                    params={"fields": "name,status,category,language,components,rejected_reason",
                                            "limit": 200})
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("error", "Could not read templates from Meta"))

    remote = {f"{t.get('name')}::{t.get('language')}": t for t in result["data"].get("data", [])}
    updated, imported = 0, 0
    now_str = datetime.utcnow().isoformat() + "Z"
    for item in db.get("whatsappTemplates", []):
        match = remote.pop(f"{item.get('metaName')}::{item.get('language')}", None)
        if not match:
            continue
        item.update({"status": META_TEMPLATE_STATUSES.get(str(match.get("status", "")).upper(), item["status"]),
                     "rejectedReason": match.get("rejected_reason", "") or "", "updatedAt": now_str})
        updated += 1
    # Templates approved directly in Meta's console should appear here too.
    for key, match in remote.items():
        body = next((c.get("text", "") for c in match.get("components", []) if c.get("type") == "BODY"), "")
        db.setdefault("whatsappTemplates", []).append({
            "id": f"WAT_{uuid.uuid4().hex[:8]}", "name": match.get("name", ""), "metaName": match.get("name", ""),
            "category": match.get("category", "UTILITY"), "language": match.get("language", "en_US"),
            "body": body, "positionalBody": body, "variables": [],
            "footer": "", "status": META_TEMPLATE_STATUSES.get(str(match.get("status", "")).upper(), "Pending review"),
            "metaId": match.get("id", ""), "rejectedReason": match.get("rejected_reason", "") or "",
            "importedFromMeta": True, "createdAt": now_str, "updatedAt": now_str})
        imported += 1
    core.audit(db, "WhatsApp Templates Synced", "WhatsApp Template", "all", {"updated": updated, "imported": imported})
    core.save_db(db)
    return {"updatedCount": updated, "importedCount": imported,
            "templates": db.get("whatsappTemplates", [])}


@router.delete("/api/whatsapp-templates/{id}")
def delete_whatsapp_template(id: str):
    db = core.load_db()
    item = core._find_record(db.get("whatsappTemplates", []), id, "WhatsApp template")
    channel = _whatsapp_channel(db)
    if channel and item.get("metaId"):
        _meta_template_request(channel, "DELETE", "message_templates", params={"name": item["metaName"]})
    db["whatsappTemplates"] = [t for t in db.get("whatsappTemplates", []) if t.get("id") != id]
    core.audit(db, "WhatsApp Template Deleted", "WhatsApp Template", id, {"name": item.get("name")})
    core.save_db(db)
    return {"status": "deleted", "id": id}


class LeadMessage(BaseModel):
    channel: str                                  # "WhatsApp" or "Email"
    content: Optional[str] = ""
    subject: Optional[str] = ""
    templateId: Optional[str] = ""
    whatsappTemplateId: Optional[str] = ""        # an approved Meta template, for outside the 24h window
    send: Optional[bool] = True


@router.post("/api/leads/{id}/message")
def message_lead(id: str, payload: LeadMessage):
    """Compose and send a message to a client from their record."""
    db = core.load_db()
    lead = core.require_visible(core._find_record(db.get("leads", []), id, "Lead"), core.visible_owners(db), "Lead")
    item = core._compose_lead_message(db, lead, payload.channel, payload.content or "", payload.subject or "",
                                 payload.whatsappTemplateId or "", payload.templateId or "", send=payload.send)
    channel_type, recipient = item["channel"], item["recipient"]
    core.save_db(db)
    return item


@router.get("/api/leads/{id}/message-options")
def lead_message_options(id: str):
    """What can actually be sent to this client right now, and why not if it can't."""
    db = core.load_db()
    lead = core.require_visible(core._find_record(db.get("leads", []), id, "Lead"), core.visible_owners(db), "Lead")
    templates = [t for t in db.get("communicationTemplates", []) if t.get("status") != "Archived"]
    options = []
    for channel_type, address, label in [("WhatsApp", lead.get("mobile", ""), "mobile number"),
                                         ("Email", lead.get("email", ""), "email address")]:
        sender = core._sending_channel(db, channel_type)
        blocked = not core._consent_allows(db, id, channel_type)
        reason = ""
        if blocked:
            reason = f"{lead.get('name')} has opted out of {channel_type}"
        elif not address:
            reason = f"No {label} on this record"
        elif not sender:
            reason = f"{channel_type} sending is not connected yet — messages are recorded but not delivered"
        options.append({"channel": channel_type, "recipient": address, "canSend": bool(address) and not blocked,
                        "live": bool(sender), "senderName": (sender or {}).get("name", ""), "reason": reason})
    in_window = core._within_service_window(lead)
    approved = [t for t in db.get("whatsappTemplates", []) if t.get("status") == "Approved"]
    return {"leadId": id, "options": options, "tokens": core.TEMPLATE_TOKENS,
            "whatsapp": {
                "inServiceWindow": in_window,
                "lastInboundAt": lead.get("lastWhatsAppInboundAt", ""),
                "requiresApprovedTemplate": not in_window,
                "note": ("They messaged in the last 24 hours, so you can write freely."
                         if in_window else
                         "Outside WhatsApp's 24-hour reply window, so Meta only allows a template it has approved."),
                "approvedTemplates": [{"id": t["id"], "name": t["name"], "body": t["body"],
                                       "language": t.get("language", "en_US"),
                                       "variables": t.get("variables", [])} for t in approved]},
            "templates": [{"id": t["id"], "name": t["name"], "channel": t["channel"],
                           "subject": t.get("subject", ""), "content": t.get("content", "")} for t in templates]}


@router.post("/api/communications/{id}/delivery-event")
def record_delivery_event(id: str, event: Dict[str, Any]):
    db = core.load_db()
    item = core._find_record(db.get("communications", []), id, "Communication")
    status = event.get("status")
    if status not in ["Delivered", "Read", "Failed", "Bounced"]:
        raise HTTPException(status_code=422, detail="Unsupported delivery status")
    delivery_event = {"status": status, "at": event.get("at") or datetime.utcnow().isoformat() + "Z", "details": event.get("details", "")}
    item.setdefault("deliveryEvents", []).append(delivery_event)
    status_ranks = {"Pending": 0, "Queued": 1, "Sent": 2, "Delivered": 3, "Read": 4, "Replied": 5}
    current_status = item.get("status", "Pending")
    current_rank = status_ranks.get(current_status, 0)
    new_rank = status_ranks.get(status, 0)
    if new_rank >= current_rank or status in ("Failed", "Bounced"):
        item["status"] = status
    core.audit(db, "Communication Delivery Updated", "Communication", id, delivery_event)
    core.save_db(db)
    return item
