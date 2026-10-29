"""Lead sources that send leads in: advertising forms, messaging and website webhooks,
their OAuth connections, and the log of every payload received.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel

import crm_schema
import pipecat_server as core
from crm_security import company_context, current_company_id

router = APIRouter()


PROVIDER_SPECS: Dict[str, Dict[str, Any]] = {
    "meta": {
        "label": "Meta Ad Account", "family": "meta", "kind": "Facebook & Instagram lead ads",
        "summary": "One connection covers both Facebook and Instagram. Meta delivers Instagram lead ads through the same Facebook Page, so you only ever connect the page your ad account runs ads from.",
        "credentials": [
            {"key": "verifyToken", "label": "Verification password", "required": True, "generate": True, "advanced": True,
             "help": "A password Meta and this CRM use to confirm each other. We generate one for you to paste into Meta."},
            {"key": "pageId", "label": "Facebook Page ID", "required": False, "advanced": True,
             "help": "The page your ads run from — in Meta Business Suite → Settings → Pages. Recorded for your reference."},
            {"key": "appSecret", "label": "App secret", "required": False, "secret": True, "advanced": True,
             "help": "From your Meta app → Settings → Basic. With it we can prove each enquiry genuinely came from Meta and reject forged ones."},
            {"key": "accessToken", "label": "Page access token", "required": False, "secret": True, "advanced": True,
             "help": "Needed only if Meta sends the enquiry without the form answers attached, so we can fetch them."},
        ],
        "steps": [
            "Create the connection here — we generate your callback URL and verification password.",
            "In Meta Business Suite, open your app in developers.facebook.com and go to Webhooks.",
            "Subscribe to the Page topic, tick the 'leadgen' field, and paste in the callback URL and verification password.",
            "Link the Facebook Page your ad account uses. Instagram lead ads flow through this same page automatically.",
            "Send a test enquiry from the button on this screen, then run Meta's own Lead Ads Testing Tool to confirm end to end.",
        ],
        "defaultMapping": {"full_name": "name", "first_name": "firstName", "last_name": "lastName",
                           "email": "email", "phone_number": "mobile", "company_name": "organization",
                           "city": "territory", "job_title": "designation"},
    },
    "whatsapp": {
        "label": "WhatsApp Business", "family": "meta", "kind": "Messaging",
        "summary": "When someone messages your WhatsApp Business number, the message arrives here as a new enquiry with their name and number, and the conversation is saved to their record.",
        "credentials": [
            {"key": "verifyToken", "label": "Verification password", "required": True, "generate": True, "advanced": True,
             "help": "A password you and Meta both hold, so each side knows the other is genuine. We generate one for you."},
            {"key": "phoneNumberId", "label": "WhatsApp phone number ID", "required": False, "advanced": True, "sending": True,
             "help": "Not your phone number — the ID Meta assigns it, in Meta for Developers → WhatsApp → API Setup. Needed to reply from the CRM."},
            {"key": "wabaId", "label": "WhatsApp Business Account ID", "required": False, "advanced": True, "sending": True,
             "help": "On the same API Setup screen. Needed to register message templates with Meta for approval."},
            {"key": "accessToken", "label": "Permanent access token", "required": False, "secret": True, "advanced": True, "sending": True,
             "help": "From the same screen. Needed to reply from the CRM; not required just to receive messages."},
            {"key": "appSecret", "label": "App secret", "required": False, "secret": True, "advanced": True,
             "help": "From your Meta app → Settings → Basic. Lets us verify each message really came from WhatsApp."},
        ],
        "steps": [
            "Create the connection here to get your callback URL and verification password.",
            "In Meta for Developers → WhatsApp → Configuration, paste both into the Webhook section and save.",
            "Subscribe to the 'messages' field so incoming messages are forwarded.",
            "Message your business number from a personal phone — it should appear on this screen within seconds.",
        ],
        "defaultMapping": {"profile_name": "name", "wa_id": "mobile", "message_text": "companyDescription"},
    },
    "google": {
        "label": "Google Ads", "family": "google", "kind": "Lead form ads",
        "summary": "Enquiries from Google lead form ads arrive the moment someone submits, with the campaign and click ID kept for attribution.",
        "credentials": [
            {"key": "googleKey", "label": "Lead form key", "required": True, "generate": True, "advanced": True,
             "help": "We generate this for you — copy it into Google Ads so it knows the enquiries are yours."},
        ],
        "steps": [
            "Create the connection — we generate your callback URL and lead form key.",
            "In Google Ads, open the campaign's lead form asset → Delivery options.",
            "Paste the callback URL as the webhook URL and the same key phrase as the key.",
            "Click 'Send test data' in Google Ads — the test enquiry appears on this screen.",
        ],
        "defaultMapping": {"FULL_NAME": "name", "FIRST_NAME": "firstName", "LAST_NAME": "lastName",
                           "EMAIL": "email", "PHONE_NUMBER": "mobile", "COMPANY_NAME": "organization",
                           "CITY": "territory", "POSTAL_CODE": "postalCode"},
    },
    "linkedin": {
        "label": "LinkedIn Ads", "family": "linkedin", "kind": "Lead gen forms",
        "summary": "Lead Gen Form submissions from LinkedIn campaigns arrive as enquiries, including job title and company.",
        "summaryNote": "LinkedIn has no built-in webhook, so most brokers connect it through Zapier — pick Zapier below if you don't have a developer app.",
        "credentials": [
            {"key": "organizationId", "label": "LinkedIn organization ID", "required": False, "advanced": True,
             "help": "The number in your Campaign Manager URL when your company page is selected. Recorded for your reference."},
            {"key": "sharedSecret", "label": "Shared password", "required": False, "generate": True, "advanced": True,
             "help": "We generate one. Whatever sends the enquiry includes it, so nobody else can post fake leads."},
        ],
        "steps": [
            "Create the connection here to get your callback URL.",
            "Either register the URL in your LinkedIn developer app as the Lead Sync endpoint,",
            "or — far simpler — use Zapier's 'LinkedIn Lead Gen Forms' trigger and send it to this URL.",
        ],
        "defaultMapping": {"firstName": "firstName", "lastName": "lastName", "emailAddress": "email",
                           "phoneNumber": "mobile", "companyName": "organization", "jobTitle": "designation",
                           "city": "territory"},
    },
    "zapier": {
        "label": "Zapier", "family": "custom", "kind": "Connect 6,000+ other apps",
        "summary": "The catch-all. If a platform isn't listed here — LinkedIn, TikTok, IndiaMART, Justdial, Typeform, Google Sheets, your website forms — Zapier can watch it and pass the enquiry to this CRM with no code.",
        "credentials": [
            {"key": "sharedSecret", "label": "Shared password", "required": False, "generate": True, "advanced": True,
             "help": "We generate one for you. Add it in Zapier so only your Zap can send enquiries here."},
        ],
        "steps": [
            "Create the connection here and copy the callback URL.",
            "In Zapier, make a Zap with your source app as the trigger (LinkedIn Lead Gen Forms, Facebook, a form tool, a spreadsheet — whatever you use).",
            "Add the action 'Webhooks by Zapier → POST' and paste the callback URL.",
            "Set the payload type to JSON and add fields such as name, email, phone and company, plus 'secret' with the password above.",
            "Run Zapier's test — the enquiry appears on this screen, then set the field mapping here if the names differ.",
        ],
        "defaultMapping": {"name": "name", "email": "email", "phone": "mobile", "company": "organization",
                           "message": "companyDescription", "city": "territory"},
    },
    "email": {
        "label": "Email enquiries", "family": "email", "kind": "Inbox",
        "summary": "Enquiries emailed to your business address become leads automatically. We read the sender's name and address, and pick a phone number out of the message body.",
        "credentials": [
            {"key": "inboundAddress", "label": "Your enquiries email address", "required": False,
             "help": "e.g. enquiries@yourbrokerage.in — also used as the From address when you send."},
            {"key": "sharedSecret", "label": "Shared password", "required": False, "generate": True, "advanced": True,
             "help": "We generate one. Your mail forwarding tool includes it so nobody else can post fake enquiries."},
            {"key": "smtpHost", "label": "Outgoing mail server (SMTP)", "required": False, "advanced": True, "sending": True,
             "help": "e.g. smtp.gmail.com or smtp.office365.com. Needed to send email from the CRM."},
            {"key": "smtpPort", "label": "Port", "required": False, "advanced": True, "sending": True,
             "help": "587 for most providers, 465 for SSL. Leave blank for 587."},
            {"key": "smtpUsername", "label": "Mailbox username", "required": False, "advanced": True, "sending": True,
             "help": "Usually the full email address you send from."},
            {"key": "smtpPassword", "label": "Mailbox password", "required": False, "secret": True, "advanced": True, "sending": True,
             "help": "For Gmail and Microsoft 365 this must be an app password, not your normal login password."},
            {"key": "fromAddress", "label": "Send from address", "required": False, "advanced": True, "sending": True,
             "help": "Leave blank to use your enquiries address above."},
        ],
        "steps": [
            "Create the connection here and copy the callback URL.",
            "In a mail parser (Zapier Email Parser, Mailparser or CloudMailin), forward your enquiries inbox to it.",
            "Point the parser at the callback URL, sending JSON with 'from', 'subject' and 'body'.",
            "Include the shared password — as a 'secret' field, an X-Webhook-Secret header, or ?secret= on the URL.",
            "Forward yourself a test enquiry — it should appear on this screen as a new lead.",
        ],
        "defaultMapping": {"from_name": "name", "from_email": "email", "phone": "mobile",
                           "subject": "policyType", "body": "companyDescription"},
    },
    "custom": {
        "label": "Your own website form", "family": "custom", "kind": "Direct webhook",
        "summary": "For a developer wiring your website's quote form straight into the CRM without Zapier in between.",
        "credentials": [{"key": "sharedSecret", "label": "Shared password", "required": False, "generate": True, "advanced": True,
                         "help": "We generate one. Your site sends it with each submission so only your form can create leads."}],
        "steps": [
            "Give your web developer the callback URL and the shared password.",
            "The form should POST flat JSON — for example name, email, phone, company — plus 'secret'.",
            "Submit a test enquiry on your site, then adjust the field mapping here if your field names differ.",
        ],
        "defaultMapping": {"name": "name", "email": "email", "phone": "mobile", "company": "organization",
                           "message": "companyDescription"},
    },
}


# The verify token and shared password are values WE issue for the client to paste into
# their own tool, so they must stay readable. The masked ones come from the provider and
# are never needed again once stored.
COPYABLE_KEYS = {"verifyToken", "sharedSecret", "googleKey"}


def _encrypt_credential(value: str) -> str:
    if not value or str(value).startswith("enc:v1:"): return value
    cipher = core._credential_cipher()
    return f"enc:v1:{cipher.encrypt(str(value).encode()).decode()}" if cipher else value


def _protect_credentials(credentials: Dict[str, str]) -> Dict[str, str]:
    return {key: (_encrypt_credential(value) if key in core.ENCRYPTED_CREDENTIAL_KEYS else value)
            for key, value in credentials.items()}


def _mask(value: str) -> str:
    text = str(value or "")
    return f"{text[:3]}{'•' * max(4, len(text) - 6)}{text[-3:]}" if len(text) > 8 else "•" * len(text)


def _public_channel(channel: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    """Never return raw secrets to the browser; the verify token is shown so it can be pasted."""
    creds = core._usable_credentials(channel)
    safe = {}
    for key, value in creds.items():
        safe[key] = value if key in COPYABLE_KEYS else (_mask(value) if key in core.ENCRYPTED_CREDENTIAL_KEYS else value)
    spec = PROVIDER_SPECS.get(channel.get("provider"), {})
    provider = channel.get("provider")
    can_send = bool(
        (provider == "whatsapp" and creds.get("accessToken") and creds.get("phoneNumberId")) or
        (provider == "email" and creds.get("smtpHost") and creds.get("smtpUsername")))
    company_id = current_company_id()
    webhook_path = f"/api/webhooks/{channel['id']}" if company_id == "default" else f"/api/webhooks/{company_id}/{channel['id']}"
    return {**channel, "credentials": safe,
            "webhookUrl": f"{base_url}{webhook_path}",
            "providerLabel": spec.get("label", provider), "canSend": can_send, "oauthAuthorized": bool(creds.get("accessToken")),
            "summary": spec.get("summary", ""), "steps": spec.get("steps", []),
            "credentialFields": spec.get("credentials", [])}


def _find_lead_by_contact(db: Dict[str, Any], mobile: str = "", email: str = "") -> Optional[Dict[str, Any]]:
    email_key = (email or "").strip().lower()
    for lead in db.get("leads", []):
        if mobile and core._same_phone(lead.get("mobile"), mobile):
            return lead
        if email_key and (lead.get("email") or "").strip().lower() == email_key:
            return lead
    return None


def _flatten_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(_flatten_value(v) for v in value if v not in (None, ""))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return "" if value is None else str(value).strip()


def _extract_meta_lead(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Meta lead ads: entry[].changes[].value carries leadgen_id and (when included) field_data."""
    leads = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            fields = {}
            for item in value.get("field_data", []) or []:
                fields[item.get("name", "")] = _flatten_value(item.get("values"))
            leads.append({"fields": fields, "attribution": {
                "leadId": value.get("leadgen_id", ""), "formId": value.get("form_id", ""),
                "adId": value.get("ad_id", ""), "adsetId": value.get("adgroup_id", ""),
                "campaignId": value.get("campaign_id", ""), "pageId": value.get("page_id", ""),
                "platform": value.get("platform", "")}})
    return leads


def _extract_whatsapp(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    leads = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            profiles = {c.get("wa_id"): (c.get("profile", {}) or {}).get("name", "")
                        for c in value.get("contacts", []) or []}
            for message in value.get("messages", []) or []:
                sender = message.get("from", "")
                text = (message.get("text", {}) or {}).get("body", "") if message.get("type") == "text" else f"[{message.get('type', 'message')}]"
                leads.append({"fields": {"wa_id": sender, "profile_name": profiles.get(sender, ""),
                                         "message_text": text},
                              "attribution": {"leadId": message.get("id", ""),
                                              "platform": "whatsapp",
                                              "phoneNumberId": (value.get("metadata", {}) or {}).get("phone_number_id", "")},
                              "inboundMessage": text})
    return leads


def _apply_whatsapp_delivery_events(db: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Apply Meta delivery/read/failure callbacks to the outbound communication timeline."""
    applied = []
    status_names = {"sent":"Sent", "delivered":"Delivered", "read":"Read", "failed":"Failed"}
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            for status in (change.get("value", {}) or {}).get("statuses", []) or []:
                provider_id = status.get("id", "")
                communication = next((item for item in db.get("communications", [])
                                      if provider_id and item.get("providerMessageId") == provider_id), None)
                if not communication: continue
                label = status_names.get(str(status.get("status", "")).lower(), str(status.get("status", "")).title())
                errors = status.get("errors") or []
                details = "; ".join(str(error.get("title") or error.get("message") or error.get("code")) for error in errors)
                try: event_at = datetime.fromtimestamp(int(status.get("timestamp"))).isoformat()+"Z"
                except (TypeError, ValueError, OSError): event_at = datetime.utcnow().isoformat()+"Z"
                event = {"status":label, "at":event_at, "details":details}
                communication.setdefault("deliveryEvents", []).append(event); communication["status"] = label
                if label == "Failed":
                    key = f"communication-failed:{communication['id']}:{provider_id}"
                    if not any(item.get("dedupeKey") == key for item in db.get("notifications", [])):
                        db.setdefault("notifications", []).insert(0, {"id":f"NTF_{uuid.uuid4().hex[:8]}", "type":"Delivery Failure",
                            "severity":"High", "title":"WhatsApp message failed", "message":details or "Provider rejected the message",
                            "associatedId":communication.get("associatedId"), "communicationId":communication["id"],
                            "assignedTo":"", "dedupeKey":key, "read":False, "createdAt":datetime.utcnow().isoformat()+"Z"})
                applied.append({"providerMessageId":provider_id, "status":label, "communicationId":communication["id"]})
    return applied


def _extract_google(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    fields = {}
    for item in payload.get("user_column_data", []) or []:
        fields[item.get("column_id", "")] = _flatten_value(item.get("string_value"))
    return [{"fields": fields, "attribution": {
        "leadId": payload.get("lead_id", ""), "formId": payload.get("form_id", ""),
        "campaignId": payload.get("campaign_id", ""), "adGroupId": payload.get("adgroup_id", ""),
        "gclid": payload.get("gcl_id", ""), "platform": "google_ads",
        "isTest": payload.get("is_test", False)}}]


def _extract_linkedin(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    leads = []
    for response in payload.get("formResponses", [payload]):
        fields = {}
        for answer in response.get("answers", []) or []:
            fields[answer.get("questionId") or answer.get("name", "")] = _flatten_value(answer.get("answer") or answer.get("value"))
        for key in ["firstName", "lastName", "emailAddress", "phoneNumber", "companyName", "jobTitle", "city"]:
            if response.get(key):
                fields[key] = _flatten_value(response.get(key))
        leads.append({"fields": fields, "attribution": {
            "leadId": str(response.get("leadId") or response.get("id") or ""),
            "formId": str(response.get("formId") or ""), "campaignId": str(response.get("campaignId") or ""),
            "platform": "linkedin"}})
    return leads


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{8,15}\d)")


def _extract_email(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Inbound enquiry email: use explicit fields when the parser supplies them, else read the body."""
    body = payload.get("body") or payload.get("text") or payload.get("plain") or ""
    sender = payload.get("from") or payload.get("sender") or ""
    from_email = payload.get("from_email") or ""
    from_name = payload.get("from_name") or ""
    if sender and not from_email:
        match = EMAIL_RE.search(sender)
        from_email = match.group(0) if match else ""
        from_name = sender.split("<")[0].strip().strip('"') or from_name
    phone = payload.get("phone") or ""
    if not phone:
        match = PHONE_RE.search(body)
        phone = match.group(0).strip() if match else ""
    if not from_email:
        match = EMAIL_RE.search(body)
        from_email = match.group(0) if match else ""
    return [{"fields": {"from_name": from_name or (from_email.split("@")[0] if from_email else ""),
                        "from_email": from_email, "phone": phone,
                        "subject": payload.get("subject", ""), "body": body},
             "attribution": {"platform": "email", "leadId": payload.get("message_id", "")},
             "inboundMessage": body}]


def _extract_custom(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = payload.get("leads") if isinstance(payload.get("leads"), list) else [payload]
    return [{"fields": {k: _flatten_value(v) for k, v in row.items() if not isinstance(v, (dict, list))},
             "attribution": {"platform": "custom"}} for row in rows if isinstance(row, dict)]


EXTRACTORS = {"meta": _extract_meta_lead, "whatsapp": _extract_whatsapp, "google": _extract_google,
              "linkedin": _extract_linkedin, "email": _extract_email, "custom": _extract_custom,
              "zapier": _extract_custom,
              # Older connections made before Facebook and Instagram were merged into one Meta source.
              "meta_facebook": _extract_meta_lead, "meta_instagram": _extract_meta_lead}


class ChannelModel(BaseModel):
    provider: str
    allowDuplicate: Optional[bool] = False
    name: Optional[str] = ""
    credentials: Optional[Dict[str, str]] = None
    fieldMapping: Optional[Dict[str, str]] = None
    defaults: Optional[Dict[str, str]] = None
    status: Optional[str] = "Connected"


@router.get("/api/channel-providers")
def list_channel_providers():
    return [{"provider": key, "label": spec["label"], "kind": spec["kind"], "family": spec["family"],
             "credentials": spec["credentials"], "defaultMapping": spec["defaultMapping"],
             "summary": spec.get("summary", ""), "summaryNote": spec.get("summaryNote", ""),
             "steps": spec.get("steps", [])}
            for key, spec in PROVIDER_SPECS.items()]


@router.get("/api/channels")
def list_channels(request: Request):
    base = str(request.base_url).rstrip("/")
    return [_public_channel(c, base) for c in core.load_db().get("channels", [])]


@router.post("/api/channels")
def create_channel(payload: ChannelModel, request: Request):
    if payload.provider not in PROVIDER_SPECS:
        raise HTTPException(status_code=422, detail="Unknown lead source")
    spec = PROVIDER_SPECS[payload.provider]
    # A second connection for the same provider means two callback URLs to maintain and
    # enquiries split across both. Almost always an accident, so it must be deliberate.
    existing = next((c for c in core.load_db().get("channels", []) if c.get("provider") == payload.provider), None)
    if existing and not payload.allowDuplicate:
        raise HTTPException(status_code=409, detail=(
            f"{spec['label']} is already connected as “{existing.get('name')}”. "
            "Finish setting that one up, or choose to add a second deliberately if you run separate ad accounts."))
    creds = dict(payload.credentials or {})
    for field in spec["credentials"]:
        if field.get("generate") and not creds.get(field["key"]):
            creds[field["key"]] = uuid.uuid4().hex           # a verify token the client pastes into the provider
        if field.get("required") and not creds.get(field["key"]):
            raise HTTPException(status_code=422, detail=f"{field['label']} is required to connect {spec['label']}")
    db = core.load_db()
    channel = {
        "id": f"CH_{uuid.uuid4().hex[:8]}", "provider": payload.provider,
        "name": payload.name or spec["label"], "status": payload.status or "Connected",
        "credentials": _protect_credentials(creds), "fieldMapping": payload.fieldMapping or dict(spec["defaultMapping"]),
        "defaults": payload.defaults or {}, "stats": {"received": 0, "created": 0, "duplicates": 0, "failed": 0},
        "lastEventAt": "", "createdAt": datetime.utcnow().isoformat() + "Z"
    }
    db.setdefault("channels", []).insert(0, channel)
    core.audit(db, "Lead Source Connected", "Channel", channel["id"], {"provider": payload.provider, "name": channel["name"]})
    core.save_db(db)
    return _public_channel(channel, str(request.base_url).rstrip("/"))


OAUTH_PROVIDERS = {
    "meta": {"authorize": "https://www.facebook.com/v21.0/dialog/oauth", "token": "https://graph.facebook.com/v21.0/oauth/access_token",
             "clientIdEnv": "META_CLIENT_ID", "clientSecretEnv": "META_CLIENT_SECRET", "scope": "leads_retrieval,pages_manage_metadata,pages_show_list"},
    "google": {"authorize": "https://accounts.google.com/o/oauth2/v2/auth", "token": "https://oauth2.googleapis.com/token",
               "clientIdEnv": "GOOGLE_CLIENT_ID", "clientSecretEnv": "GOOGLE_CLIENT_SECRET", "scope": "https://www.googleapis.com/auth/adwords"},
    "linkedin": {"authorize": "https://www.linkedin.com/oauth/v2/authorization", "token": "https://www.linkedin.com/oauth/v2/accessToken",
                 "clientIdEnv": "LINKEDIN_CLIENT_ID", "clientSecretEnv": "LINKEDIN_CLIENT_SECRET", "scope": "r_ads r_ads_leadgen_automation"},
}


def _oauth_secret() -> bytes:
    value = os.environ.get("OAUTH_STATE_SECRET") or os.environ.get("SESSION_SECRET")
    if not value and os.environ.get("APP_ENV", "development").lower() == "production":
        raise HTTPException(status_code=503, detail="OAuth state signing is not configured")
    return (value or "insurecrm-development-oauth-state").encode()


def _oauth_state(channel: Dict[str, Any]) -> str:
    data = {"companyId": current_company_id(), "channelId": channel["id"], "provider": channel["provider"],
            "expires": int(datetime.utcnow().timestamp()) + 600, "nonce": uuid.uuid4().hex}
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_oauth_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def _read_oauth_state(value: str) -> Dict[str, Any]:
    try:
        body, signature = value.split(".", 1)
        expected = hmac.new(_oauth_secret(), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected): raise ValueError()
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(data.get("expires", 0)) < int(datetime.utcnow().timestamp()): raise ValueError()
        return data
    except Exception:
        raise HTTPException(status_code=400, detail="The provider authorization request expired; start again")


@router.get("/api/channels/{id}/oauth/start")
def start_channel_oauth(id: str, request: Request):
    db = core.load_db(); channel = core._find_record(db.get("channels", []), id, "Lead source")
    spec = OAUTH_PROVIDERS.get(channel.get("provider"))
    if not spec: raise HTTPException(status_code=422, detail="This source uses a signed webhook instead of account authorization")
    client_id = os.environ.get(spec["clientIdEnv"], "")
    if not client_id: raise HTTPException(status_code=503, detail=f"{spec['clientIdEnv']} is not configured on the server")
    redirect_uri = str(request.base_url).rstrip("/") + "/api/integrations/oauth/callback"
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": spec["scope"], "state": _oauth_state(channel)}
    if channel.get("provider") == "google": params.update({"access_type": "offline", "prompt": "consent"})
    return {"authorizationUrl": f"{spec['authorize']}?{urlencode(params)}", "expiresIn": 600}


@router.get("/api/integrations/oauth/callback")
def finish_channel_oauth(request: Request, code: str = "", state: str = "", error: str = ""):
    if error: return RedirectResponse(url=f"/?integration=failed&reason={error}")
    saved = _read_oauth_state(state)
    if saved.get("companyId") != current_company_id(): raise HTTPException(status_code=403, detail="Authorization belongs to another company")
    db = core.load_db(); channel = core._find_record(db.get("channels", []), saved["channelId"], "Lead source")
    spec = OAUTH_PROVIDERS.get(saved["provider"]); redirect_uri = str(request.base_url).rstrip("/") + "/api/integrations/oauth/callback"
    client_id, client_secret = os.environ.get(spec["clientIdEnv"], ""), os.environ.get(spec["clientSecretEnv"], "")
    if not code or not client_id or not client_secret: raise HTTPException(status_code=503, detail="Provider authorization is not fully configured")
    response = httpx.post(spec["token"], data={"client_id": client_id, "client_secret": client_secret, "redirect_uri": redirect_uri,
                                                   "grant_type": "authorization_code", "code": code}, timeout=25.0)
    if response.status_code >= 400: return RedirectResponse(url="/?integration=failed")
    tokens = response.json(); credentials = core._usable_credentials(channel)
    credentials["accessToken"] = tokens.get("access_token", "")
    if tokens.get("refresh_token"): credentials["refreshToken"] = tokens["refresh_token"]
    if channel.get("provider") == "meta" and os.environ.get("META_CLIENT_SECRET"): credentials["appSecret"] = os.environ["META_CLIENT_SECRET"]
    channel["credentials"] = _protect_credentials(credentials); channel["status"] = "Authorized"
    channel["authorizedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Lead Source Authorized", "Channel", channel["id"], {"provider": channel.get("provider")}); core.save_db(db)
    return RedirectResponse(url="/?integration=connected")


@router.put("/api/channels/{id}")
def update_channel(id: str, updates: Dict[str, Any], request: Request):
    db = core.load_db()
    channel = core._find_record(db.get("channels", []), id, "Lead source")
    for key in ["name", "status", "fieldMapping", "defaults"]:
        if key in updates:
            channel[key] = updates[key]
    if isinstance(updates.get("credentials"), dict):
        # A masked value means "unchanged" — never overwrite a stored secret with its own mask.
        for key, value in updates["credentials"].items():
            if value and "•" not in str(value):
                channel.setdefault("credentials", {})[key] = _encrypt_credential(value) if key in core.ENCRYPTED_CREDENTIAL_KEYS else value
    core.audit(db, "Lead Source Updated", "Channel", id, {k: v for k, v in updates.items() if k != "credentials"})
    core.save_db(db)
    return _public_channel(channel, str(request.base_url).rstrip("/"))


@router.delete("/api/channels/{id}")
def disconnect_channel(id: str):
    db = core.load_db()
    channel = core._find_record(db.get("channels", []), id, "Lead source")
    db["channels"] = [c for c in db.get("channels", []) if c.get("id") != id]
    core.audit(db, "Lead Source Disconnected", "Channel", id, {"name": channel.get("name")})
    core.save_db(db)
    return {"status": "disconnected", "id": id}


def _verify_signature(channel: Dict[str, Any], raw_body: bytes, signature_header: str) -> bool:
    """Meta signs payloads with HMAC-SHA256 of the raw body using the app secret."""
    secret = core._usable_credentials(channel).get("appSecret") or os.environ.get("META_CLIENT_SECRET", "")
    if not secret:
        return os.environ.get("APP_ENV", "development").lower() != "production"
    if not signature_header:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _apply_channel_mapping(channel: Dict[str, Any], extracted: Dict[str, Any]) -> Dict[str, Any]:
    mapping = channel.get("fieldMapping") or {}
    values: Dict[str, str] = {}
    unmapped: Dict[str, str] = {}
    for key, value in (extracted.get("fields") or {}).items():
        if not value:
            continue
        target = mapping.get(key)
        if target and target != "__skip__":
            values[target] = value
        else:
            unmapped[key] = value                    # kept on the lead, never discarded
    if not values.get("name"):
        joined = " ".join(x for x in [values.pop("firstName", ""), values.pop("lastName", "")] if x).strip()
        if joined:
            values["name"] = joined
    values.pop("firstName", None); values.pop("lastName", None)
    return {"values": values, "unmapped": unmapped}


def _split_custom(db: Dict[str, Any], values: Dict[str, str], unmapped: Dict[str, str]) -> Tuple[Dict[str, Any], List[str]]:
    """Values mapped to custom.<key>, checked. A web form can send anything, and losing an
    enquiry is worse than an untyped detail, so a value that can't be read is kept with the
    unmapped fields, under the field's label, and reported instead of failing the lead."""
    defs = {d["key"]: d for d in core.custom_field_defs(db) if not d.get("hidden")}
    custom: Dict[str, Any] = {}
    problems: List[str] = []
    for target in [k for k in values if k.startswith("custom.")]:
        raw_value, key = values.pop(target), target[len("custom."):]
        defn = defs.get(key)
        try:
            if defn is None:
                raise crm_schema.SchemaError(f"'{key}' is not a field")
            cleaned = crm_schema.read_value(defn, raw_value)
            if cleaned is not None:
                custom[key] = cleaned
        except crm_schema.SchemaError as exc:
            unmapped[defn["label"] if defn else key] = raw_value
            problems.append(f"{defn['label']} {exc}" if defn else str(exc))
    return custom, problems


def _ingest_channel_lead(db: Dict[str, Any], channel: Dict[str, Any], extracted: Dict[str, Any],
                         raw: Dict[str, Any]) -> Dict[str, Any]:
    """Turn one extracted payload into a CRM lead, recording the event either way."""
    now_str = datetime.utcnow().isoformat() + "Z"
    mapped = _apply_channel_mapping(channel, extracted)
    values, unmapped = mapped["values"], mapped["unmapped"]
    custom, custom_problems = _split_custom(db, values, unmapped)
    defaults = channel.get("defaults") or {}
    attribution = extracted.get("attribution") or {}

    event = {"id": f"EVT_{uuid.uuid4().hex[:8]}", "channelId": channel["id"], "channelName": channel.get("name"),
             "provider": channel.get("provider"), "receivedAt": now_str, "attribution": attribution,
             "payload": raw, "mappedValues": values, "unmappedFields": unmapped, "status": "Received", "leadId": ""}

    name = (values.get("name") or "").strip()
    mobile = (values.get("mobile") or "").strip()
    email = (values.get("email") or "").strip()
    if not name and not mobile and not email:
        event.update({"status": "Failed", "message": "Payload had no name, phone or email to identify the enquiry"})
        channel.setdefault("stats", {})["failed"] = channel.get("stats", {}).get("failed", 0) + 1
        return event

    if custom_problems:
        event["customFieldProblems"] = custom_problems
    existing = _find_lead_by_contact(db, mobile, email)
    if existing:
        existing.setdefault("customFields", {}).update(unmapped)
        if custom:
            # A repeat enquiry fills gaps; it doesn't overwrite what a telecaller recorded.
            existing["custom"] = {**custom, **(existing.get("custom") or {})}
        existing["lastModified"] = now_str
        # Their message reopens WhatsApp's 24-hour window for free-form replies.
        if channel.get("provider") == "whatsapp" and extracted.get("inboundMessage"):
            existing["lastWhatsAppInboundAt"] = now_str
        db.setdefault("notes", []).insert(0, {
            "id": f"N_{uuid.uuid4().hex[:8]}", "title": f"New enquiry via {channel.get('name')}",
            "associatedType": "Lead", "associatedId": existing["id"],
            "associatedTitle": f"{existing.get('name')} ({existing.get('organization')})",
            "category": "General Memo",
            "content": extracted.get("inboundMessage") or f"Repeat enquiry received from {channel.get('name')}. Campaign: {attribution.get('campaignId') or 'n/a'}.",
            "author": channel.get("name", "Gateway"), "pinned": False, "createdAt": now_str})
        event.update({"status": "Duplicate", "leadId": existing["id"],
                      "message": f"Matched existing lead {existing.get('name')} — logged to their timeline"})
        channel.setdefault("stats", {})["duplicates"] = channel.get("stats", {}).get("duplicates", 0) + 1
        return event

    lead_id = f"L_{uuid.uuid4().hex[:8]}"
    parts = name.split(" ") if name else [mobile or email]
    lead = {
        "id": lead_id, "salutation": "", "firstName": parts[0], "lastName": " ".join(parts[1:]),
        "name": name or mobile or email, "organization": values.get("organization", ""), "website": "",
        "status": defaults.get("status") or "New", "email": email, "mobile": mobile, "gender": "",
        "territory": values.get("territory") or defaults.get("territory", ""), "industry": defaults.get("industry", ""),
        "annualRevenue": "", "noOfEmployees": "",
        "companyDescription": values.get("companyDescription", ""),
        "policyType": values.get("policyType") or defaults.get("policyType", ""),
        "policyNumber": "", "premium": values.get("premium", ""), "expiryDate": "", "daysRemaining": None,
        "nextAction": defaults.get("nextAction") or "Call back the new enquiry",
        "nextActionDate": datetime.now().strftime("%Y-%m-%d"), "nextActionCompleted": False,
        "source": channel.get("name", "Gateway"), "sourceChannelId": channel["id"],
        "attribution": attribution, "customFields": unmapped,
        "assignedTo": defaults.get("assignedTo") or core.apply_assignment_rules(db, {
            "id": lead_id, "name": name or mobile or email,
            "policyType": values.get("policyType") or defaults.get("policyType", ""),
            "source": channel.get("name", ""), "organization": values.get("organization", ""),
            "premium": values.get("premium", ""), "status": defaults.get("status") or "New",
            "territory": values.get("territory") or defaults.get("territory", ""), "industry": ""}) or core.get_next_round_robin_user(db),
        "lastModified": now_str, "lostReason": ""
    }
    if custom:
        lead["custom"] = custom
    lead["assignedByRule"] = core._last_rule_match["name"]
    if channel.get("provider") == "whatsapp" and extracted.get("inboundMessage"):
        lead["lastWhatsAppInboundAt"] = now_str
    db.setdefault("leads", []).insert(0, lead)

    if mobile and not any(core._same_phone(c.get("phone"), mobile) for c in db.get("contacts", [])):
        db.setdefault("contacts", []).insert(0, {
            "id": f"C_{uuid.uuid4().hex[:8]}", "leadId": lead_id, "name": lead["name"], "email": email,
            "phone": mobile, "organization": lead["organization"], "designation": values.get("designation", "Primary Contact"),
            "status": "Active", "lastModified": now_str})

    task_id = f"T_{uuid.uuid4().hex[:8]}"
    lead["nextActionTaskId"] = task_id
    db.setdefault("tasks", []).insert(0, {
        "id": task_id, "title": lead["nextAction"], "associatedType": "Lead",
        "associatedId": lead_id, "associatedTitle": f"{lead['name']} ({lead['organization'] or 'Individual'})",
        "priority": "High", "dueDate": lead["nextActionDate"], "status": "Pending",
        "assignedTo": lead["assignedTo"], "activityType": "Follow-up"})

    if extracted.get("inboundMessage"):
        db.setdefault("communications", []).insert(0, {
            "id": f"COM_{uuid.uuid4().hex[:8]}", "associatedType": "Lead", "associatedId": lead_id,
            "recipient": mobile or email, "channel": PROVIDER_SPECS.get(channel.get("provider"), {}).get("kind", "Message"),
            "content": extracted["inboundMessage"], "direction": "Inbound", "status": "Received",
            "deliveryEvents": [{"status": "Received", "at": now_str}], "createdAt": now_str})

    # An ad-form submission is an explicit request to be contacted: record it as consent.
    db.setdefault("consents", []).insert(0, {
        "id": f"CON_{uuid.uuid4().hex[:8]}", "leadId": lead_id, "contactId": "",
        "channel": "WhatsApp" if channel.get("provider") == "whatsapp" else "Phone",
        "status": "Opted In", "source": f"{channel.get('name')} enquiry", "notes": "Captured with the inbound enquiry",
        "createdAt": now_str, "updatedAt": now_str})

    event.update({"status": "Lead created", "leadId": lead_id})
    channel.setdefault("stats", {})["created"] = channel.get("stats", {}).get("created", 0) + 1
    return event


def _handle_channel_payload(channel_id: str, payload: Dict[str, Any], raw_body: bytes,
                            signature: str = "", query: Optional[Dict[str, Any]] = None,
                            header_secret: str = "") -> Dict[str, Any]:
    db = core.load_db()
    channel = next((c for c in db.get("channels", []) if c.get("id") == channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail="Unknown lead source")
    if channel.get("status") == "Paused":
        raise HTTPException(status_code=409, detail="This lead source is paused")

    provider = channel.get("provider")
    if PROVIDER_SPECS.get(provider, {}).get("family") == "meta" and not _verify_signature(channel, raw_body, signature):
        raise HTTPException(status_code=401, detail="Payload signature did not match the app secret")
    if provider == "google":
        expected = core._usable_credentials(channel).get("googleKey")
        if expected and payload.get("google_key") != expected:
            raise HTTPException(status_code=401, detail="google_key did not match")
    if provider in ["linkedin", "email", "custom", "zapier"]:
        secret = core._usable_credentials(channel).get("sharedSecret")
        # Accept the password wherever the sending tool can put it: JSON body, query
        # string or header — mail parsers and no-code tools each allow different ones.
        if secret and secret not in [(query or {}).get("secret"), payload.get("secret"), header_secret]:
            raise HTTPException(status_code=401, detail="Shared password did not match. Check the value configured in the sending tool.")

    delivery_updates = _apply_whatsapp_delivery_events(db, payload) if provider == "whatsapp" else []
    extracted_list = EXTRACTORS[provider](payload)
    if not extracted_list:
        events = [{"id": f"EVT_{uuid.uuid4().hex[:8]}", "channelId": channel_id, "channelName": channel.get("name"),
                   "provider": provider, "receivedAt": datetime.utcnow().isoformat() + "Z", "payload": payload,
                   "status": "Delivery updated" if delivery_updates else "Ignored",
                   "message": f"Updated {len(delivery_updates)} communication delivery record(s)" if delivery_updates else "Payload contained no lead data",
                   "attribution": {}, "mappedValues": {}, "unmappedFields": {}, "leadId": ""}]
    else:
        events = [_ingest_channel_lead(db, channel, extracted, payload) for extracted in extracted_list]

    channel.setdefault("stats", {})["received"] = channel.get("stats", {}).get("received", 0) + len(events)
    channel["lastEventAt"] = datetime.utcnow().isoformat() + "Z"
    db.setdefault("channelEvents", [])
    for event in events:
        db["channelEvents"].insert(0, event)
    db["channelEvents"] = db["channelEvents"][:500]
    core.audit(db, "Channel Event Received", "Channel", channel_id,
          {"provider": provider, "events": len(events), "deliveryUpdates":len(delivery_updates), "outcomes": [e["status"] for e in events]})
    core.save_db(db)
    return {"received": len(events), "events": [{k: e[k] for k in ["id", "status", "leadId"] if k in e} for e in events]}


def _verify_channel_webhook(channel_id: str, request: Request):
    """Meta's subscription handshake: echo hub.challenge when the verify token matches."""
    params = dict(request.query_params)
    db = core.load_db()
    channel = next((c for c in db.get("channels", []) if c.get("id") == channel_id), None)
    if not channel:
        raise HTTPException(status_code=404, detail="Unknown lead source")
    expected = core._usable_credentials(channel).get("verifyToken")
    if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == expected:
        channel["status"] = "Connected"
        channel["verifiedAt"] = datetime.utcnow().isoformat() + "Z"
        core.audit(db, "Lead Source Verified", "Channel", channel_id, {"provider": channel.get("provider")})
        core.save_db(db)
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verify token did not match")


WEBHOOK_RATE_LIMIT = int(os.environ.get("WEBHOOK_RATE_LIMIT", "120"))   # posts per minute per source


_webhook_hits: Dict[str, List[float]] = {}


def _rate_limit(channel_id: str):
    """Callback URLs are public by necessity; cap how fast one can be driven."""
    import time as _time
    now = _time.time()
    hits = [t for t in _webhook_hits.get(channel_id, []) if now - t < 60]
    if len(hits) >= WEBHOOK_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests to this lead source. Try again shortly.")
    hits.append(now)
    _webhook_hits[channel_id] = hits


async def _receive_channel_webhook(channel_id: str, request: Request):
    _rate_limit(channel_id)
    raw_body = await request.body()
    try:
        payload = json.loads(raw_body or b"{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="Webhook body was not valid JSON")
    return _handle_channel_payload(channel_id, payload, raw_body,
                                   request.headers.get("x-hub-signature-256", ""), dict(request.query_params),
                                   request.headers.get("x-webhook-secret", ""))


@router.get("/api/webhooks/{company_id}/{channel_id}")
def verify_company_channel_webhook(company_id: str, channel_id: str, request: Request):
    if not re.fullmatch(r"CO_[A-Za-z0-9_-]+", company_id): raise HTTPException(status_code=404, detail="Unknown company")
    token = company_context.set(company_id)
    try: return _verify_channel_webhook(channel_id, request)
    finally: company_context.reset(token)


@router.post("/api/webhooks/{company_id}/{channel_id}")
async def receive_company_channel_webhook(company_id: str, channel_id: str, request: Request):
    if not re.fullmatch(r"CO_[A-Za-z0-9_-]+", company_id): raise HTTPException(status_code=404, detail="Unknown company")
    token = company_context.set(company_id)
    try: return await _receive_channel_webhook(channel_id, request)
    finally: company_context.reset(token)


@router.get("/api/webhooks/{channel_id}")
def verify_channel_webhook(channel_id: str, request: Request):
    return _verify_channel_webhook(channel_id, request)


@router.post("/api/webhooks/{channel_id}")
async def receive_channel_webhook(channel_id: str, request: Request):
    return await _receive_channel_webhook(channel_id, request)


SAMPLE_PAYLOADS = {
    "meta": {"object": "page", "entry": [{"changes": [{"field": "leadgen", "value": {
        "leadgen_id": "SAMPLE-LEAD-1", "form_id": "FORM-88", "ad_id": "AD-12", "campaign_id": "CAMP-7",
        "page_id": "PAGE-1", "platform": "facebook", "field_data": [
            {"name": "full_name", "values": ["Anita Desai"]}, {"name": "email", "values": ["anita.desai@example.in"]},
            {"name": "phone_number", "values": ["+91 90000 41001"]}, {"name": "company_name", "values": ["Desai Warehousing"]},
            {"name": "city", "values": ["Pune"]}, {"name": "cover_required", "values": ["Fire & Property"]}]}}]}]},
    "zapier": {"name": "Priya Sharma", "email": "priya@sharmalogistics.in", "phone": "+91 90000 41008",
               "company": "Sharma Logistics", "message": "Sent through a Zap from a LinkedIn lead form",
               "city": "Mumbai"},
    "whatsapp": {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": {
        "metadata": {"phone_number_id": "PN-1"}, "contacts": [{"wa_id": "919000041003", "profile": {"name": "Farah Khan"}}],
        "messages": [{"id": "wamid.SAMPLE", "from": "919000041003", "type": "text",
                      "text": {"body": "Hi, I need a quote for my 12-truck fleet."}}]}}]}]},
    "google": {"lead_id": "SAMPLE-G-1", "form_id": "GFORM-5", "campaign_id": "GCAMP-9", "is_test": True,
               "gcl_id": "GCLID-XYZ", "user_column_data": [
                   {"column_id": "FULL_NAME", "string_value": "Sanjay Verma"},
                   {"column_id": "EMAIL", "string_value": "sanjay@vermasteel.in"},
                   {"column_id": "PHONE_NUMBER", "string_value": "+91 90000 41004"},
                   {"column_id": "COMPANY_NAME", "string_value": "Verma Steel Works"}]},
    "linkedin": {"formResponses": [{"leadId": "SAMPLE-LI-1", "formId": "LIFORM-2", "campaignId": "LICAMP-4",
                                    "firstName": "Meera", "lastName": "Nair", "emailAddress": "meera.nair@nairgroup.in",
                                    "phoneNumber": "+91 90000 41005", "companyName": "Nair Group",
                                    "jobTitle": "Finance Director", "city": "Kochi"}]},
    "email": {"from": "Deepak Rao <deepak@raoenterprises.in>", "subject": "Group health cover enquiry",
              "body": "Hello, we need group health cover for 80 employees. Please call me on +91 90000 41006.",
              "message_id": "SAMPLE-EMAIL-1"},
    "custom": {"name": "Website Visitor", "email": "visitor@example.in", "phone": "+91 90000 41007",
               "company": "Web Enquiry Ltd", "message": "Requested a fleet quote from the pricing page"},
}


@router.get("/api/channels/{id}/sample-payload")
def channel_sample_payload(id: str):
    channel = core._find_record(core.load_db().get("channels", []), id, "Lead source")
    return SAMPLE_PAYLOADS.get(channel.get("provider"), {})


@router.post("/api/channels/{id}/test")
def send_test_event(id: str, payload: Optional[Dict[str, Any]] = None):
    """Fire a realistic provider payload through the live path so mapping can be checked before going live."""
    db = core.load_db()
    channel = core._find_record(db.get("channels", []), id, "Lead source")
    body = payload or SAMPLE_PAYLOADS.get(channel.get("provider"), {})
    credentials = core._usable_credentials(channel)
    if channel.get("provider") == "google" and credentials.get("googleKey"):
        body = {**body, "google_key": credentials["googleKey"]}
    if credentials.get("sharedSecret"):
        body = {**body, "secret": credentials["sharedSecret"]}
    raw = json.dumps(body).encode()
    signature = ""
    if credentials.get("appSecret"):
        signature = "sha256=" + hmac.new(credentials["appSecret"].encode(), raw, hashlib.sha256).hexdigest()
    return _handle_channel_payload(id, body, raw, signature,
                                   header_secret=credentials.get("sharedSecret", ""))


@router.get("/api/channel-events")
def list_channel_events(channelId: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    events = core.load_db().get("channelEvents", [])
    if channelId:
        events = [e for e in events if e.get("channelId") == channelId]
    if status:
        events = [e for e in events if e.get("status") == status]
    return events[:limit]


@router.post("/api/channel-events/{id}/reprocess")
def reprocess_channel_event(id: str):
    """Replay a stored payload after fixing the mapping — this is why raw payloads are kept."""
    db = core.load_db()
    event = core._find_record(db.get("channelEvents", []), id, "Channel event")
    if event.get("status") == "Lead created":
        raise HTTPException(status_code=409, detail="This event already created a lead")
    channel_id = event.get("channelId")
    payload = event.get("payload") or {}
    # A replay is internal: the payload was already authenticated when it first arrived,
    # so re-present the channel's own credentials rather than rejecting it.
    channel = next((c for c in db.get("channels", []) if c.get("id") == channel_id), None)
    result = _handle_channel_payload(channel_id, payload, json.dumps(payload).encode(),
                                     signature=_signature_for(channel_id, payload),
                                     header_secret=((channel or {}).get("credentials") or {}).get("sharedSecret", ""))
    db = core.load_db()
    stored = next((e for e in db.get("channelEvents", []) if e.get("id") == id), None)
    if stored:
        stored["status"] = "Reprocessed"
        stored["reprocessedAt"] = datetime.utcnow().isoformat() + "Z"
        core.save_db(db)
    return result


def _signature_for(channel_id: str, payload: Dict[str, Any]) -> str:
    channel = next((c for c in core.load_db().get("channels", []) if c.get("id") == channel_id), None)
    secret = ((channel or {}).get("credentials") or {}).get("appSecret")
    if not secret:
        return ""
    return "sha256=" + hmac.new(secret.encode(), json.dumps(payload).encode(), hashlib.sha256).hexdigest()
