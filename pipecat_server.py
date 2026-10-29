import os
import hmac
import re
import smtplib
import httpx
from email.message import EmailMessage
import asyncio
import shutil
import hashlib
import json
import uuid
import contextvars
import concurrent.futures
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import uvicorn

if __name__ == "__main__":
    # Serve the importable module, not this __main__ copy: the route modules import
    # pipecat_server, and two copies would hold two separate apps and states.
    uvicorn.run("pipecat_server:app", host="0.0.0.0", port=8080)
    raise SystemExit(0)

# Load .env before any project module reads configuration at import time.
def _load_env_file(path: str = ".env"):
    """Read secrets from a local .env so keys never live in source control."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass

_load_env_file()

from crm_security import (CSRF_COOKIE, SESSION_COOKIE, company_context, current_actor, current_company_id,
                          may_mutate_path, may_read_path, user_context, verify_session)
import crm_security
import crm_store
import crm_automation as automation
import crm_metrics as metrics

app = FastAPI(title="InsureCRM Enterprise Platform")


@app.exception_handler(RuntimeError)
async def runtime_error_response(_request: Request, exc: RuntimeError):
    if "changed during the operation" in str(exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})
    # Configuration and adapter errors should not expose secrets or connection details.
    return JSONResponse(status_code=503, content={"detail": "A required CRM service is unavailable"})


@app.middleware("http")
async def browser_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    if os.environ.get("APP_ENV", "development").lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

os.makedirs("web", exist_ok=True)
app.mount("/static", StaticFiles(directory="web"), name="static")

@app.get("/")
def read_root():
    """Serve the shell with asset versions derived from file modification times.

    The version string used to be typed by hand, so a stylesheet change shipped
    behind a stale cache key and users kept the old CSS. Deriving it means the
    browser refetches exactly when the file actually changes.
    """
    try:
        html = open("web/index.html", encoding="utf-8").read()
        stamp = lambda f: str(int(os.path.getmtime(f))) if os.path.exists(f) else "0"
        html = re.sub(r'(/static/style\.css)\?v=[^"\']*', lambda m: f"{m.group(1)}?v={stamp('web/style.css')}", html)
        html = re.sub(r'(/static/app\.js)\?v=[^"\']*', lambda m: f"{m.group(1)}?v={stamp('web/app.js')}", html)
        # The shell carries the asset version stamps, so it must never be cached itself —
        # a cached shell pins the browser to old CSS/JS no matter what changed on disk.
        return Response(content=html, media_type="text/html",
                        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})
    except OSError:
        return FileResponse("web/index.html")

DB_FILE = os.environ.get("CRM_DB_FILE", "crm_db.json")
DOCUMENT_ROOT = os.environ.get("DOCUMENT_ROOT", "crm_documents")
BACKUP_ROOT = os.environ.get("BACKUP_ROOT", "crm_backups")
TENANT_ROOT = os.environ.get("TENANT_ROOT", "crm_tenants")

AUTH_DISABLED = os.environ.get("AUTH_DISABLED", "0") == "1"
_AUTH_FAILURES: Dict[str, List[float]] = {}

# Blueprint 13-stage telecalling lifecycle + legacy compatibility stages
# ─── Lead lifecycle (client blueprint, slide 11) ───
# The thirteen statuses are fixed by the client's process; the call-outcome engine and
# reports depend on them, so they are not a per-company setting.
LEAD_STATUSES = [
    "New", "Assigned", "Contacted", "Interested", "Quote Sent", "Follow-up",
    "Documents Pending", "Policy Sold", "Not Interested", "Call Later",
    "Wrong Number", "Unreachable", "Lost",
]
STAGES = LEAD_STATUSES
SOLD_STATUSES = {"Policy Sold"}
CLOSED_STATUSES = {"Policy Sold", "Not Interested", "Lost"}       # the enquiry is finished
REASON_REQUIRED = {"Not Interested", "Lost"}
NO_NEXT_ACTION = CLOSED_STATUSES | {"Wrong Number"}               # nothing further to schedule
# Earlier versions used a six-stage commercial pipeline.
LEGACY_STATUSES = {"Won": "Policy Sold", "Quotation Sent": "Quote Sent", "Risk / Underwriting": "Documents Pending"}


def canonical_status(status: Optional[str]) -> str:
    value = (status or "").strip()
    value = LEGACY_STATUSES.get(value, value)
    return next((s for s in LEAD_STATUSES if s.lower() == value.lower()), value)


def is_sold(lead: Dict[str, Any]) -> bool:
    return canonical_status(lead.get("status")) in SOLD_STATUSES


def is_open_lead(lead: Dict[str, Any]) -> bool:
    """Still being worked: not finished and not parked as a wrong number."""
    return canonical_status(lead.get("status")) not in NO_NEXT_ACTION


DEFAULT_PRODUCTS = ["Car Insurance", "Health Insurance"]
_LEGACY_DEFAULT_PRODUCTS = ["Commercial Motor", "Group Health", "Fire & Property", "Cyber Insurance", "Marine Cargo"]

DEFAULT_LEAD_SOURCES = ["Website", "Google Ads", "Meta Ads", "LinkedIn Ads", "WhatsApp", "Referral", "Partner",
                        "Walk-in", "Calling list", "Existing customer", "Spreadsheet import", "Organic", "Other"]
SOURCE_NOT_RECORDED = "Not recorded"

# ─── Documents (client blueprint, slide 21) ───
DOCUMENT_TYPES = ["RC", "Driving Licence", "ID Proof", "Previous Policy", "Health Documents",
                  "Proposal Form", "Payment Proof", "Policy Schedule", "Other"]
# Evidence a policy needs before it is issued, and the document type that provides each.
ISSUANCE_EVIDENCE = {"proposalForm": "Proposal Form", "kyc": "ID Proof", "payment": "Payment Proof",
                     "schedule": "Policy Schedule"}
_LEGACY_DOCUMENT_TYPES = {"kyc": "ID Proof", "id": "ID Proof", "identity document": "ID Proof", "quote": "Other",
                          "claims history": "Other", "rc book": "RC", "registration certificate": "RC",
                          "driving license": "Driving Licence", "dl": "Driving Licence",
                          "previous policy copy": "Previous Policy", "medical reports": "Health Documents",
                          **{k.lower(): v for k, v in ISSUANCE_EVIDENCE.items()}}
DEFAULT_REQUIRED_DOCUMENTS = {"Car Insurance": ["RC", "Previous Policy", "ID Proof"],
                              "Health Insurance": ["ID Proof"]}
_SOURCE_BY_PROVIDER = {"meta": "Meta Ads", "google": "Google Ads", "linkedin": "LinkedIn Ads",
                       "whatsapp": "WhatsApp", "zapier": "Website", "custom": "Website", "email": "Other"}
# Classifies free text already stored by earlier versions. The original wording is kept
# as sourceDetail, so the classification is visible and reversible.
_SOURCE_KEYWORDS = [("spreadsheet", "Spreadsheet import"), ("import", "Spreadsheet import"),
                    ("referral", "Referral"), ("refer", "Referral"), ("partner", "Partner"),
                    ("google", "Google Ads"), ("facebook", "Meta Ads"), ("instagram", "Meta Ads"),
                    ("meta", "Meta Ads"), ("linkedin", "LinkedIn Ads"), ("whatsapp", "WhatsApp"),
                    ("website", "Website"), ("web form", "Website"), ("walk", "Walk-in"),
                    ("cold", "Calling list"), ("calling list", "Calling list"), ("organic", "Organic")]

# ─── Call outcomes (client blueprint, slide 16) ───
# Each outcome decides what happens next, so nothing depends on memory. `needs` lists what
# the telecaller must record for the outcome to make sense.
CALL_OUTCOMES = {
    "Interested": {"connected": True, "needs": [], "label": "Interested / very interested"},
    "Call Back": {"connected": True, "needs": ["followUpDate"], "label": "Asked to call back"},
    "Not Interested": {"connected": True, "needs": ["reason"], "label": "Not interested"},
    "Already Insured": {"connected": True, "needs": ["currentExpiryDate"], "label": "Already insured elsewhere"},
    "Documents Pending": {"connected": True, "needs": [], "label": "Will send documents"},
    "Policy Sold": {"connected": True, "needs": ["policy"], "label": "Bought the policy"},
    "Busy / Switched Off": {"connected": False, "needs": [], "label": "Busy, no answer or switched off"},
    "Wrong Number": {"connected": False, "needs": [], "label": "Wrong number"},
}
_OUTCOME_ALIASES = {"interested / very interested": "Interested", "very interested": "Interested", "busy": "Busy / Switched Off",
                    "switched off": "Busy / Switched Off", "no answer": "Busy / Switched Off", "callback": "Call Back"}


def canonical_outcome(value: Optional[str]) -> str:
    text = (value or "").strip()
    return next((o for o in CALL_OUTCOMES if o.lower() == text.lower()), None) or _OUTCOME_ALIASES.get(text.lower(), text)


def calculate_lead_priority(lead: Dict[str, Any]) -> str:
    """Slide 13: Priority factors — lead freshness, policy expiry date, customer interest."""
    p = str(lead.get("leadPriority") or lead.get("priority") or "").upper()
    if p in ("HOT", "WARM", "COLD"):
        return p
    days = _days_until(lead.get("expiryDate")) if lead.get("expiryDate") else None
    if days is not None and 0 <= days <= 7:
        return "HOT"
    status = lead.get("status", "")
    if status in ("Interested", "Quote Sent", "Quotation Sent"):
        return "HOT"
    if days is not None and 8 <= days <= 30:
        return "WARM"
    if status in ("New", "Assigned", "Contacted", "Follow-up"):
        return "WARM"
    return "COLD"

def get_initial_db() -> Dict[str, Any]:
    now_str = datetime.utcnow().isoformat() + "Z"
    return {
        "users": [
            {"id": "U1", "name": "Sarah Connor", "email": "sarah.connor@insurecrm.in", "role": "telecaller", "title": "Senior Sales Executive", "status": "Active"},
            {"id": "U2", "name": "Aarav Sharma", "email": "aarav.sharma@insurecrm.in", "role": "manager", "title": "Commercial Renewal Lead", "status": "Active"},
            {"id": "U3", "name": "John Parker", "email": "john.parker@insurecrm.in", "role": "telecaller", "title": "Corporate Account Manager", "status": "Active"},
            {"id": "U4", "name": "Administrator", "email": "admin@insurecrm.in", "role": "admin", "title": "System Administrator", "status": "Active"}
        ],
        "leads": [
            {
                "id": "L1",
                "salutation": "Mr",
                "firstName": "Vikram",
                "lastName": "Mehta",
                "name": "Vikram Mehta",
                "organization": "Mehta Logistics Ltd",
                "website": "www.mehtalogistics.in",
                "status": "Contacted",
                "email": "vikram.mehta@mehtalogistics.in",
                "mobile": "+91 98765 43210",
                "gender": "Male",
                "territory": "West India (Mumbai & Pune)",
                "industry": "Logistics & Freight",
                "annualRevenue": "₹ 12,50,00,000",
                "noOfEmployees": "51-200",
                "companyDescription": "Commercial freight carrier with 42 heavy commercial vehicles operating Mumbai-Delhi corridor.",
                "policyType": "Comprehensive Commercial Fleet Motor",
                "policyNumber": "FLEET-8891-MH",
                "premium": "₹ 84,000",
                "expiryDate": "2026-09-12",
                "daysRemaining": 8,
                "nextAction": "Collect Vehicle Fleet RC Books & NCB Proof",
                "nextActionDate": "2026-09-06",
                "nextActionCompleted": False,
                "source": "Website Inbound",
                "assignedTo": "Sarah Connor",
                "lastModified": now_str,
                "lostReason": ""
            },
            {
                "id": "L2",
                "salutation": "Ms",
                "firstName": "Priya",
                "lastName": "Deshmukh",
                "name": "Priya Deshmukh",
                "organization": "Meridian Health Solutions",
                "website": "www.meridianhealth.co.in",
                "status": "Documents Pending",
                "email": "priya.deshmukh@meridianhealth.co.in",
                "mobile": "+91 98123 45678",
                "gender": "Female",
                "territory": "South India (Bengaluru)",
                "industry": "Healthcare & Diagnostics",
                "annualRevenue": "₹ 8,80,00,000",
                "noOfEmployees": "51-200",
                "companyDescription": "Diagnostic labs and day-care network across Karnataka. 180 employees covered.",
                "policyType": "Corporate Group Health Care Shield",
                "policyNumber": "GMC-4402-KA",
                "premium": "₹ 1,45,000",
                "expiryDate": "2026-09-07",
                "daysRemaining": 3,
                "nextAction": "Obtain TPA Cashless Network Addendum from Underwriter",
                "nextActionDate": "2026-09-05",
                "nextActionCompleted": False,
                "source": "Broker Referral",
                "assignedTo": "Aarav Sharma",
                "lastModified": now_str,
                "lostReason": ""
            },
            {
                "id": "L3",
                "salutation": "Mr",
                "firstName": "Lars",
                "lastName": "Nielsen",
                "name": "Lars Nielsen",
                "organization": "Nordic Tech India",
                "website": "www.nordictech.in",
                "status": "Quote Sent",
                "email": "lars@nordictech.in",
                "mobile": "+91 98456 12345",
                "gender": "Male",
                "territory": "North India (Delhi NCR)",
                "industry": "Technology & SaaS",
                "annualRevenue": "₹ 18,20,00,000",
                "noOfEmployees": "51-200",
                "companyDescription": "Enterprise clean energy monitoring software suite.",
                "policyType": "Cyber Security & Professional Indemnity",
                "policyNumber": "CYB-1092-DL",
                "premium": "₹ 95,000",
                "expiryDate": "2026-09-18",
                "daysRemaining": 14,
                "nextAction": "Follow-up on Quotation Review with Board",
                "nextActionDate": "2026-09-10",
                "nextActionCompleted": False,
                "source": "Direct Outreach",
                "assignedTo": "John Parker",
                "lastModified": now_str,
                "lostReason": ""
            },
            {
                "id": "L4",
                "salutation": "Mr",
                "firstName": "Bob",
                "lastName": "Martinez",
                "name": "Bob Martinez",
                "organization": "Globex Industries Ltd",
                "website": "www.globex.co.in",
                "status": "New",
                "email": "bob.martinez@globex.co.in",
                "mobile": "+91 98220 11223",
                "gender": "Male",
                "territory": "West India (Pune)",
                "industry": "Manufacturing & Heavy Engineering",
                "annualRevenue": "₹ 34,50,00,000",
                "noOfEmployees": "201-500",
                "companyDescription": "CNC precision components manufacturer with 2 manufacturing plants in Chakan.",
                "policyType": "Plant & Heavy Machinery Cover",
                "policyNumber": "ENG-3310-MH",
                "premium": "₹ 2,10,000",
                "expiryDate": "2026-09-09",
                "daysRemaining": 5,
                "nextAction": "Initial Discovery Call & Risk Scope Assessment",
                "nextActionDate": "2026-09-04",
                "nextActionCompleted": False,
                "source": "Website Inbound",
                "assignedTo": "Sarah Connor",
                "lastModified": now_str,
                "lostReason": ""
            },
            {
                "id": "L5",
                "salutation": "Ms",
                "firstName": "Grace",
                "lastName": "Park",
                "name": "Grace Park",
                "organization": "NextWave Data Systems",
                "website": "www.nextwave.in",
                "status": "Policy Sold",
                "email": "grace.park@nextwave.in",
                "mobile": "+91 98711 22334",
                "gender": "Female",
                "territory": "South India (Bengaluru)",
                "industry": "Technology & Infrastructure",
                "annualRevenue": "₹ 24,00,00,000",
                "noOfEmployees": "51-200",
                "companyDescription": "AI data center server farm.",
                "policyType": "Industrial All Risk (IAR) & Fire",
                "policyNumber": "IAR-7714-KA",
                "premium": "₹ 1,80,000",
                "expiryDate": "2027-09-01",
                "daysRemaining": 362,
                "nextAction": "Policy Issued — Annual Schedule Filed",
                "nextActionDate": "2027-08-01",
                "nextActionCompleted": True,
                "source": "Industry Conference",
                "assignedTo": "Sarah Connor",
                "lastModified": now_str,
                "lostReason": ""
            },
            {
                "id": "L6",
                "salutation": "Mr",
                "firstName": "Frank",
                "lastName": "Turner",
                "name": "Frank Turner",
                "organization": "Turner Broadcast Studio",
                "website": "www.turnerbc.in",
                "status": "Lost",
                "email": "frank@turnerbc.in",
                "mobile": "+91 98330 44556",
                "gender": "Male",
                "territory": "North India (Delhi)",
                "industry": "Media & Broadcasting",
                "annualRevenue": "₹ 6,20,00,000",
                "noOfEmployees": "11-50",
                "companyDescription": "Regional broadcast channel production facility.",
                "policyType": "Broadcasting Studio Equipment Cover",
                "policyNumber": "MED-0091-DL",
                "premium": "₹ 48,000",
                "expiryDate": "2026-08-20",
                "daysRemaining": -14,
                "nextAction": "Lost to Competitor — Re-engage in 9 months",
                "nextActionDate": "2027-05-01",
                "nextActionCompleted": True,
                "source": "Outreach",
                "assignedTo": "John Parker",
                "lastModified": now_str,
                "lostReason": "Switched to public sector insurer offering 12% lower premium"
            }
        ],
        "deals": [
            {"id": "D1", "organization": "Meridian Health Solutions", "dealName": "Corporate Group Health Cover", "annualRevenue": "₹ 1,45,000", "status": "Proposal/Quotation", "email": "priya.deshmukh@meridianhealth.co.in", "mobile": "+91 98123 45678", "assignedTo": "Aarav Sharma", "lastModified": now_str},
            {"id": "D2", "organization": "Nordic Tech India", "dealName": "Cyber Risk & D&O Package", "annualRevenue": "₹ 95,000", "status": "Negotiation", "email": "lars@nordictech.in", "mobile": "+91 98456 12345", "assignedTo": "John Parker", "lastModified": now_str},
            {"id": "D3", "organization": "Globex Industries Ltd", "dealName": "Chakan Plant Machinery Policy", "annualRevenue": "₹ 2,10,000", "status": "Qualification", "email": "bob.martinez@globex.co.in", "mobile": "+91 98220 11223", "assignedTo": "Sarah Connor", "lastModified": now_str},
            {"id": "D4", "organization": "NextWave Data Systems", "dealName": "Industrial All Risk (IAR)", "annualRevenue": "₹ 1,80,000", "status": "Won", "email": "grace.park@nextwave.in", "mobile": "+91 98711 22334", "assignedTo": "Sarah Connor", "lastModified": now_str}
        ],
        "contacts": [
            {"id": "C1", "name": "Vikram Mehta", "email": "vikram.mehta@mehtalogistics.in", "phone": "+91 98765 43210", "organization": "Mehta Logistics Ltd", "designation": "Managing Director", "status": "Active", "lastModified": now_str},
            {"id": "C2", "name": "Priya Deshmukh", "email": "priya.deshmukh@meridianhealth.co.in", "phone": "+91 98123 45678", "organization": "Meridian Health Solutions", "designation": "HR & Admin Director", "status": "Active", "lastModified": now_str},
            {"id": "C3", "name": "Lars Nielsen", "email": "lars@nordictech.in", "phone": "+91 98456 12345", "organization": "Nordic Tech India", "designation": "Chief Technology Officer", "status": "Active", "lastModified": now_str},
            {"id": "C4", "name": "Bob Martinez", "email": "bob.martinez@globex.co.in", "phone": "+91 98220 11223", "organization": "Globex Industries Ltd", "designation": "Plant Head (Pune)", "status": "Active", "lastModified": now_str},
            {"id": "C5", "name": "Grace Park", "email": "grace.park@nextwave.in", "phone": "+91 98711 22334", "organization": "NextWave Data Systems", "designation": "CFO", "status": "Active", "lastModified": now_str}
        ],
        "organizations": [
            {"id": "O1", "name": "Mehta Logistics Ltd", "website": "www.mehtalogistics.in", "industry": "Logistics & Freight", "annualRevenue": "₹ 12,50,00,000", "territory": "West India (Mumbai & Pune)", "noOfEmployees": "51-200", "lastModified": now_str},
            {"id": "O2", "name": "Meridian Health Solutions", "website": "www.meridianhealth.co.in", "industry": "Healthcare & Diagnostics", "annualRevenue": "₹ 8,80,00,000", "territory": "South India (Bengaluru)", "noOfEmployees": "51-200", "lastModified": now_str},
            {"id": "O3", "name": "Nordic Tech India", "website": "www.nordictech.in", "industry": "Technology & SaaS", "annualRevenue": "₹ 18,20,00,000", "territory": "North India (Delhi NCR)", "noOfEmployees": "51-200", "lastModified": now_str},
            {"id": "O4", "name": "Globex Industries Ltd", "website": "www.globex.co.in", "industry": "Manufacturing & Heavy Engineering", "annualRevenue": "₹ 34,50,00,000", "territory": "West India (Pune)", "noOfEmployees": "201-500", "lastModified": now_str},
            {"id": "O5", "name": "NextWave Data Systems", "website": "www.nextwave.in", "industry": "Technology & Infrastructure", "annualRevenue": "₹ 24,00,00,000", "territory": "South India (Bengaluru)", "noOfEmployees": "51-200", "lastModified": now_str}
        ],
        "notes": [
            {
                "id": "N1",
                "title": "Fleet Renewal Terms & Surveyor Dispatch",
                "associatedType": "Lead",
                "associatedId": "L1",
                "associatedTitle": "Vikram Mehta (Mehta Logistics Ltd)",
                "category": "Underwriting Note",
                "content": "Client operates 42 heavy commercial trucks across Pune-Ahmedabad route. Previous year had zero major total-loss claims. Surveyor verified fleet condition. Requested 35% NCB discount documentation.",
                "author": "Sarah Connor",
                "pinned": True,
                "createdAt": now_str
            },
            {
                "id": "N2",
                "title": "Group Health TPA Cashless Agreement",
                "associatedType": "Lead",
                "associatedId": "L2",
                "associatedTitle": "Priya Deshmukh (Meridian Health)",
                "category": "Risk Assessment",
                "content": "Underwriting review underway with ICICI Lombard. Client insists on MediAssist TPA with cashless coverage across all major hospitals in Bangalore and Mysore.",
                "author": "Aarav Sharma",
                "pinned": True,
                "createdAt": now_str
            },
            {
                "id": "N3",
                "title": "Cyber Security Proposal Terms Presented",
                "associatedType": "Lead",
                "associatedId": "L3",
                "associatedTitle": "Lars Nielsen (Nordic Tech India)",
                "category": "Meeting Minutes",
                "content": "Delivered comparative quotation comparing HDFC Ergo vs Tata AIG. Board reviewing cyber extortion and data recovery sub-limits. Scheduled follow-up for next week.",
                "author": "John Parker",
                "pinned": False,
                "createdAt": now_str
            }
        ],
        "tasks": [
            {
                "id": "T1",
                "title": "Collect Vehicle Fleet RC Books & NCB Proof from Vikram Mehta",
                "associatedType": "Lead",
                "associatedId": "L1",
                "associatedTitle": "Vikram Mehta (Mehta Logistics Ltd)",
                "priority": "High",
                "dueDate": "2026-09-06",
                "status": "Pending",
                "assignedTo": "Sarah Connor"
            },
            {
                "id": "T2",
                "title": "Obtain TPA Cashless Network Addendum from Underwriter for Meridian Health",
                "associatedType": "Lead",
                "associatedId": "L2",
                "associatedTitle": "Priya Deshmukh (Meridian Health)",
                "priority": "High",
                "dueDate": "2026-09-05",
                "status": "Pending",
                "assignedTo": "Aarav Sharma"
            },
            {
                "id": "T3",
                "title": "Follow-up on Quotation Review with Nordic Tech Board",
                "associatedType": "Lead",
                "associatedId": "L3",
                "associatedTitle": "Lars Nielsen (Nordic Tech India)",
                "priority": "Medium",
                "dueDate": "2026-09-10",
                "status": "Pending",
                "assignedTo": "John Parker"
            },
            {
                "id": "T4",
                "title": "Conduct First Discovery Call with Globex Industries",
                "associatedType": "Lead",
                "associatedId": "L4",
                "associatedTitle": "Bob Martinez (Globex Industries Ltd)",
                "priority": "High",
                "dueDate": "2026-09-04",
                "status": "Pending",
                "assignedTo": "Sarah Connor"
            }
        ],
        "settings": {
            "dashboard": {
                "currency": "INR",
                "autoUpdateExpectedDealValue": True
            },
            "userManagement": {
                "autoAssignMethod": "Round-Robin"
            },
            "crm": {
                "leadStages": STAGES,
                "insuranceProducts": list(DEFAULT_PRODUCTS),
                "insurers": [],
                "reminderEscalationDays": 1
            }
        }
    }

def _tenant_db_path(company_id: Optional[str] = None) -> str:
    company_id = company_id or current_company_id()
    if company_id == "default":
        return DB_FILE
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", company_id)
    os.makedirs(TENANT_ROOT, exist_ok=True)
    return os.path.join(TENANT_ROOT, f"{safe_id}.json")


def _ensure_db_shape(db: Dict[str, Any]) -> Dict[str, Any]:
    for collection in ["customers", "policies", "renewals", "quotations", "communications", "communicationTemplates",
                       "consents", "notifications", "auditLogs", "archivedLeads", "archivedRecords", "documents",
                       "backupLogs", "channels", "channelEvents", "imports", "importBatches", "whatsappTemplates",
                       "schedulerJobs", "savedFilters", "serviceRequests", "endorsements", "calendarEvents"]:
        db.setdefault(collection, [])
    db.setdefault("settings", {})
    db["settings"].setdefault("crm", {
        "leadStages": STAGES,
        "insuranceProducts": list(DEFAULT_PRODUCTS),
        "insurers": [],
        "reminderEscalationDays": 1
    })
    db["settings"]["crm"].setdefault("companyTimezone", "Asia/Kolkata")
    db["settings"]["crm"].setdefault("upcomingReminderMinutes", 1440)
    crm = db["settings"]["crm"]
    crm["leadStages"] = list(LEAD_STATUSES)
    if not crm.get("insuranceProducts") or crm.get("insuranceProducts") == _LEGACY_DEFAULT_PRODUCTS:
        crm["insuranceProducts"] = list(DEFAULT_PRODUCTS)
    crm.setdefault("leadSources", list(DEFAULT_LEAD_SOURCES))
    crm.setdefault("requiredDocuments", {k: list(v) for k, v in DEFAULT_REQUIRED_DOCUMENTS.items()})
    _normalize_leads(db, backfill=True)
    _migrate_assignment_rules(db)
    _normalize_calls(db)
    _reconstruct_status_history(db)
    _automation_events(db, backfill=True)
    for user in db.get("users", []):
        role = user.get("role", "")
        if isinstance(user, dict) and role not in crm_security.ROLES:
            # Earlier versions stored a job title as the role. Keep it as display text only.
            if role:
                user.setdefault("title", role)
            user["role"] = crm_security.normalized_role(role)
    return db


def _empty_company_db() -> Dict[str, Any]:
    """A real tenant starts empty; demo records belong only to the local default workspace."""
    return _ensure_db_shape({
        "users": [], "leads": [], "deals": [], "contacts": [], "organizations": [],
        "notes": [], "tasks": [], "calendarEvents": [],
        "settings": {
            "dashboard": {"currency": "INR", "autoUpdateExpectedDealValue": True},
            "userManagement": {"autoAssignMethod": "Round-Robin"},
            "crm": {"leadStages": list(LEAD_STATUSES), "insuranceProducts": list(DEFAULT_PRODUCTS),
                    "leadSources": list(DEFAULT_LEAD_SOURCES), "insurers": [], "reminderEscalationDays": 1},
        },
    })


def load_db() -> Dict[str, Any]:
    initial = get_initial_db() if current_company_id() == "default" else _empty_company_db()
    if crm_store.configured():
        return _ensure_db_shape(crm_store.load_state(current_company_id(), initial))
    db_path = _tenant_db_path()
    existing = crm_store.load_json_state(db_path)
    if existing is not None:
        return _ensure_db_shape(existing)
    db = initial
    save_db(db)
    return db

def save_db(db: Dict[str, Any]):
    _normalize_leads(db)
    _expire_quotes(db)
    _reconcile_ownership(db)
    _apply_commissions(db)
    _fire_automation_events(db)
    _reconcile_work_notifications(db)
    if crm_store.configured():
        crm_store.save_state(current_company_id(), db)
        return
    crm_store.save_json_state(_tenant_db_path(), db)


def _reconcile_work_notifications(db: Dict[str, Any]):
    tasks = {item.get("id"): item for item in db.get("tasks", [])}
    events = {item.get("id"): item for item in db.get("calendarEvents", [])}
    for notification in db.get("notifications", []):
        field = "calendarEventId" if notification.get("calendarEventId") else "taskId"
        record_id = notification.get(field)
        if not record_id:
            continue
        record = (events if field == "calendarEventId" else tasks).get(record_id)
        if record:
            notification["assignedTo"] = record.get("assignedTo", "")
        stale_schedule = False
        if record and notification.get("dedupeKey"):
            schedule = f":{record.get('date')}:{record.get('time', '')}" if field == "calendarEventId" else f":{_schedule_suffix(record)}"
            stale_schedule = not notification["dedupeKey"].endswith(schedule)
        if not record or stale_schedule or record.get("status") in {"Completed", "Archived", "Cancelled"}:
            notification.update({"read": True, "resolved": True})
            if not record:
                notification["archivedRelatedId"] = notification.pop(field)

def update_record(collection: str, record_id: str, updates: Dict[str, Any], allowed: set, label: str):
    db = load_db(); item = _find_record(db.get(collection, []), record_id, label); before = dict(item)
    if "assignedTo" in item:
        require_visible(item, visible_owners(db), label)
    changes = {k: v for k, v in updates.items() if k in allowed}; item.update(changes); item["lastModified"] = datetime.utcnow().isoformat()+"Z"
    audit(db, f"{label} Updated", label, record_id, {"before": {k:before.get(k) for k in changes}, "after":changes})
    save_db(db); return item

# ─── Roles and ownership ───
# Collections that are historical snapshots: their owner is what it was at the time.
_OWNERSHIP_HISTORY = {"users", "auditLogs", "archivedLeads", "archivedRecords"}


def _reconcile_ownership(db: Dict[str, Any]):
    """Keep a stable owner id beside every owner name.

    Names are what people read and what visibility compares, so they stay. The id is
    what survives a rename and what performance and commission attribute to. A name
    that resolves to a current team member always wins, so a reassignment is never
    undone; a name that is a person's former name is healed to their current one.
    """
    users = [u for u in db.get("users", []) if isinstance(u, dict) and u.get("id")]
    by_id = {u["id"]: u for u in users}
    by_name: Dict[str, Dict[str, Any]] = {}
    for user in users:
        by_name.setdefault((user.get("name") or "").strip().lower(), user)
    for collection, records in db.items():
        if collection in _OWNERSHIP_HISTORY or not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or ("assignedTo" not in record and "assignedToId" not in record):
                continue
            name = (record.get("assignedTo") or "").strip().lower()
            owner = by_name.get(name) if name else None
            previous = by_id.get(record.get("assignedToId"))
            if owner:
                record["assignedToId"] = owner["id"]
            elif previous and name in {n.lower() for n in previous.get("previousNames", [])}:
                record["assignedTo"] = previous.get("name", "")
            else:
                record.pop("assignedToId", None)


# ─── Retail lead model: car and health insurance ───
FUEL_TYPES = ["Petrol", "Diesel", "CNG", "LPG", "Electric", "Hybrid"]
NCB_LEVELS = [0, 20, 25, 35, 45, 50]
HEALTH_PLAN_TYPES = ["Individual", "Family Floater"]
MEMBER_RELATIONS = ["Self", "Spouse", "Son", "Daughter", "Father", "Mother", "Other"]
GENDERS = ["Male", "Female", "Other"]
# State code, RTO number, series, number — or the Bharat series (22BH1234AA).
_REGISTRATION = re.compile(r"^(?:[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{1,4}|\d{2}BH\d{4}[A-Z]{1,2})$")


def _one_of(value, allowed, label):
    if value in (None, ""):
        return value
    match = next((a for a in allowed if str(a).lower() == str(value).strip().lower()), None)
    if match is None:
        raise ValueError(f"{label} must be one of: {', '.join(map(str, allowed))}")
    return match


class _Details(BaseModel):
    """Every field is optional: a telecaller records what the customer says, when they say it."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VehicleDetails(_Details):
    registrationNumber: Optional[str] = ""
    make: Optional[str] = ""
    model: Optional[str] = ""
    variant: Optional[str] = ""
    manufactureYear: Optional[int] = None
    fuelType: Optional[str] = ""
    idv: Optional[float] = Field(default=None, ge=0)
    ncbPercent: Optional[int] = None
    previousClaims: Optional[bool] = None

    @field_validator("registrationNumber")
    @classmethod
    def _registration(cls, v):
        v = re.sub(r"[\s.-]", "", v or "").upper()
        if v and not _REGISTRATION.match(v):
            raise ValueError("should look like MH12AB1234, or 22BH1234AA for Bharat series")
        return v

    @field_validator("manufactureYear")
    @classmethod
    def _year(cls, v):
        latest = datetime.now().year + 1
        if v is not None and not 1980 <= v <= latest:
            raise ValueError(f"must be between 1980 and {latest}")
        return v

    @field_validator("fuelType")
    @classmethod
    def _fuel(cls, v):
        return _one_of(v, FUEL_TYPES, "Fuel type")

    @field_validator("ncbPercent")
    @classmethod
    def _ncb(cls, v):
        return _one_of(v, NCB_LEVELS, "No-claim bonus")


class HealthMember(_Details):
    relation: str
    age: int = Field(ge=0, le=110)
    gender: Optional[str] = ""

    @field_validator("relation")
    @classmethod
    def _relation(cls, v):
        return _one_of(v, MEMBER_RELATIONS, "Relation")

    @field_validator("gender")
    @classmethod
    def _gender(cls, v):
        return _one_of(v, GENDERS, "Gender")


class HealthDetails(_Details):
    planType: Optional[str] = ""
    members: List[HealthMember] = Field(default_factory=list, max_length=12)
    sumInsured: Optional[float] = Field(default=None, ge=0)
    preExistingConditions: Optional[str] = ""

    @field_validator("planType")
    @classmethod
    def _plan(cls, v):
        return _one_of(v, HEALTH_PLAN_TYPES, "Plan type")


class ExistingPolicy(_Details):
    insurer: Optional[str] = ""
    policyNumber: Optional[str] = ""
    expiryDate: Optional[str] = ""
    premium: Optional[float] = Field(default=None, ge=0)
    hadClaim: Optional[bool] = None

    @field_validator("expiryDate")
    @classmethod
    def _expiry(cls, v):
        if not v:
            return ""
        parsed = _parse_flexible_date(v)
        if not parsed:
            raise ValueError("is not a valid date")
        return parsed


_DETAIL_MODELS = {"vehicleDetails": (VehicleDetails, "Car details"),
                  "healthDetails": (HealthDetails, "Health details"),
                  "existingPolicy": (ExistingPolicy, "Existing policy")}


def _checked_details(field: str, value: Any, current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate a details block, merging a partial edit into what is already recorded."""
    model, label = _DETAIL_MODELS[field]
    if value in (None, ""):
        return current or {}
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail=f"{label} must be a set of named fields")
    try:
        return model.model_validate({**(current or {}), **value}).model_dump(exclude_none=True)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = " ".join(str(part) for part in error["loc"] if not isinstance(part, int)) or "value"
        message = str(error["msg"]).removeprefix("Value error, ")
        raise HTTPException(status_code=422, detail=f"{label}: {where} {message}")


def _products(db: Dict[str, Any]) -> List[str]:
    return db.get("settings", {}).get("crm", {}).get("insuranceProducts") or list(DEFAULT_PRODUCTS)


def _lead_sources(db: Dict[str, Any]) -> List[str]:
    return db.get("settings", {}).get("crm", {}).get("leadSources") or list(DEFAULT_LEAD_SOURCES)


def _checked_product(db: Dict[str, Any], product: Optional[str]) -> str:
    value = (product or "").strip()
    if not value:
        return ""
    match = next((p for p in _products(db) if p.lower() == value.lower()), None)
    if not match:
        raise HTTPException(status_code=422, detail=f"Product must be one of: {', '.join(_products(db))}")
    return match


def _checked_source(db: Dict[str, Any], source: Optional[str]) -> str:
    value = (source or "").strip()
    if not value or value.lower() == SOURCE_NOT_RECORDED.lower():
        return SOURCE_NOT_RECORDED
    match = next((x for x in _lead_sources(db) if x.lower() == value.lower()), None)
    if not match:
        raise HTTPException(status_code=422, detail=f"Lead source must be one of: {', '.join(_lead_sources(db))}")
    return match


def _classify_source(db: Dict[str, Any], lead: Dict[str, Any]) -> str:
    raw = str(lead.get("source") or lead.get("leadSource") or "").strip()
    exact = next((x for x in _lead_sources(db) + [SOURCE_NOT_RECORDED] if x.lower() == raw.lower()), None)
    if exact:
        return exact
    channel = next((c for c in db.get("channels", []) if c.get("id") == lead.get("sourceChannelId")), None)
    if channel and channel.get("provider") in _SOURCE_BY_PROVIDER:
        return _SOURCE_BY_PROVIDER[channel["provider"]]
    low = raw.lower()
    if low in {"", "direct entry", "manual", "gateway"}:
        return SOURCE_NOT_RECORDED
    return next((source for keyword, source in _SOURCE_KEYWORDS if keyword in low), "Other")


def _checked_status_change(lead: Dict[str, Any], new_status: str, reason: str = "",
                           next_action: Optional[str] = None, next_date: Optional[str] = None) -> str:
    """The rules every status change obeys, whichever endpoint makes it."""
    status = canonical_status(new_status)
    if status not in LEAD_STATUSES:
        raise HTTPException(status_code=422, detail=f"Status must be one of: {', '.join(LEAD_STATUSES)}")
    if status in REASON_REQUIRED and not (reason or lead.get("lostReason") or "").strip():
        raise HTTPException(status_code=422, detail=f"Record a reason when a lead is marked {status}.")
    if status not in NO_NEXT_ACTION:
        action = lead.get("nextAction") if next_action is None else next_action
        due = lead.get("nextActionDate") if next_date is None else next_date
        if not str(action or "").strip() or not _parse_flexible_date(str(due or "")):
            raise HTTPException(status_code=422, detail="While a lead is still being worked it needs a next action and a date.")
    return status


def _close_lead_work(db: Dict[str, Any], lead: Dict[str, Any]):
    """A finished lead has nothing left to do: settle its follow-up and clear the next action."""
    task = next((t for t in db.get("tasks", []) if t.get("id") == lead.get("nextActionTaskId")), None)
    if task and task.get("status") not in ("Completed", "Archived"):
        task["status"] = "Completed"
        task["completedAt"] = datetime.utcnow().isoformat() + "Z"
    lead.update({"nextAction": "", "nextActionDate": "", "nextActionTime": "", "nextActionCompleted": True})


_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _checked_time(value: Optional[str]) -> str:
    """Optional 24-hour HH:MM. "Call within the day" needs a time, not just a date."""
    text = (value or "").strip()
    if text and not _CLOCK.match(text):
        raise HTTPException(status_code=422, detail="Time must be HH:MM in 24-hour format, for example 14:30")
    return text


def _schedule_suffix(task: Dict[str, Any]) -> str:
    """The part of a reminder's key that changes when the follow-up is rescheduled."""
    return f"{task.get('dueDate', '')}" + (f"T{task['dueTime']}" if task.get("dueTime") else "")


def _due_moment(task: Dict[str, Any], tz) -> Optional[datetime]:
    """When a follow-up falls due: its time if it has one, otherwise the end of its day."""
    try:
        day = datetime.strptime(task.get("dueDate") or "", "%Y-%m-%d")
    except ValueError:
        return None
    if task.get("dueTime") and _CLOCK.match(task["dueTime"]):
        hour, minute = map(int, task["dueTime"].split(":"))
        return day.replace(hour=hour, minute=minute, tzinfo=tz)
    return day.replace(hour=23, minute=59, second=59, tzinfo=tz)


def _normalize_leads(db: Dict[str, Any], backfill: bool = False):
    """One set of rules for every lead, however it arrived — form, import or ad webhook.

    Status is one of the thirteen; source is one of the company's sources, with any other
    wording kept as sourceDetail; the capture date is stamped once and never edited; and a
    sale records when it happened. On load, missing dates are recovered from the audit
    ledger and left empty when there is no evidence — never invented.
    """
    evidence: Dict[str, Dict[str, str]] = {}
    if backfill:
        for entry in db.get("auditLogs", []):
            lead_id, when = entry.get("entityId"), entry.get("createdAt")
            if not lead_id or not when:
                continue
            if entry.get("action") == "Lead Created":
                evidence.setdefault(lead_id, {}).setdefault("created", when)
            details = entry.get("details") or {}
            sold = entry.get("action") == "Lead Converted" or (
                entry.get("action") == "Lead Stage Changed" and canonical_status(details.get("to")) in SOLD_STATUSES)
            if sold:
                evidence.setdefault(lead_id, {})["sold"] = when
    now = datetime.utcnow().isoformat() + "Z"
    for lead in db.get("leads", []):
        if not isinstance(lead, dict):
            continue
        status = canonical_status(lead.get("status") or "New")
        if status != lead.get("status"):
            lead.setdefault("legacyStatus", lead.get("status"))
            lead["status"] = status

        raw = str(lead.get("source") or lead.get("leadSource") or "").strip()
        source = _classify_source(db, lead)
        if raw and raw.lower() != source.lower():
            lead.setdefault("sourceDetail", raw)
        lead["source"] = lead["leadSource"] = source
        lead.setdefault("originalSource", lead.get("sourceDetail") or source)

        known = evidence.get(lead.get("id"), {})
        if "leadDate" not in lead or (backfill and not lead.get("leadDate") and not lead.get("leadDateUnknown")):
            found = lead.get("createdAt") or known.get("created")
            if backfill and not found:
                lead["leadDate"], lead["leadDateUnknown"] = "", True
            else:
                lead["leadDate"] = found or now
        if status in SOLD_STATUSES:
            if backfill and not lead.get("soldAt") and not lead.get("soldAtUnknown"):
                if known.get("sold"):
                    lead["soldAt"] = known["sold"]
                else:
                    lead["soldAt"], lead["soldAtUnknown"] = "", True
            elif "soldAt" not in lead:
                lead["soldAt"] = now
        else:
            # Reopened: the sale date belongs to a sale that no longer stands.
            lead.pop("soldAt", None)
            lead.pop("soldAtUnknown", None)

def get_next_round_robin_user(db: Dict[str, Any]) -> str:
    users = [u["name"] for u in db.get("users", [])
             if crm_security.normalized_role(u.get("role", "")) not in {"admin", "readonly"}
             and u.get("status", "Active") == "Active" and u.get("available", True)]
    if not users:
        # Never invent an owner who isn't on the team: fall back to whoever actually holds leads.
        owners = sorted({l.get("assignedTo") for l in db.get("leads", []) if l.get("assignedTo")})
        return owners[0] if owners else "Unassigned"
    leads = db.get("leads", [])
    counts = {u: 0 for u in users}
    for l in leads:
        owner = l.get("assignedTo")
        if owner in counts:
            counts[owner] += 1
    return min(counts, key=counts.get)

def money_value(value: Any) -> float:
    if isinstance(value, (int, float)): return round(float(value), 2)
    cleaned = "".join(c for c in str(value or "0") if c.isdigit() or c in ".-")
    try: return round(float(cleaned or 0), 2)
    except ValueError: return 0.0

def policy_financials(premium: Any, tax_rate: Any = 18) -> Dict[str, float]:
    base = money_value(premium); rate = money_value(tax_rate)
    tax = round(base * rate / 100, 2)
    return {"netPremium": base, "taxRate": rate, "taxAmount": tax, "totalPremium": round(base + tax, 2)}


LABEL_SOURCES = [("leads", "name"), ("customers", "name"), ("policies", "customerName"),
                 ("renewals", "customerName"), ("organizations", "name"), ("contacts", "name"),
                 ("tasks", "title"), ("notes", "title"), ("users", "name")]

def _build_label_index(db: Dict[str, Any], wanted: set) -> Dict[str, str]:
    """One pass over the collections for all the ids we need, rather than a full scan each."""
    labels: Dict[str, str] = {}
    wanted = {w for w in wanted if w}
    if not wanted:
        return labels
    for collection, field in LABEL_SOURCES:
        for record in db.get(collection, []):
            if not isinstance(record, dict):
                continue
            record_id = record.get("id")
            if record_id in wanted and record_id not in labels and record.get(field):
                labels[record_id] = record[field]
                if len(labels) == len(wanted):
                    return labels          # stop the moment everything is resolved
    return labels

def _entity_label(db: Dict[str, Any], entity_id: str) -> str:
    """Resolve a record id to the name a broker would recognise."""
    return _build_label_index(db, {entity_id}).get(entity_id, entity_id)


def audit(db: Dict[str, Any], action: str, entity_type: str, entity_id: str, details: Dict[str, Any], actor: str = "System"):
    sensitive = {"password", "passwordHash", "smtpPassword", "accessToken", "appSecret", "sharedSecret",
                 "email", "mobile", "phone", "address", "rawPayload"}
    def safe(value, key=""):
        if key in sensitive or "secret" in key.lower() or "token" in key.lower() or "password" in key.lower():
            return "[redacted]"
        if isinstance(value, dict): return {k: safe(v, k) for k, v in value.items()}
        if isinstance(value, list): return [safe(v) for v in value]
        return value
    logs = db.setdefault("auditLogs", [])
    event = {"id": f"AUD_{uuid.uuid4().hex[:8]}", "action": action, "entityType": entity_type,
             "entityId": entity_id, "details": safe(details), "actor": current_actor(actor),
             "companyId": current_company_id(), "createdAt": datetime.utcnow().isoformat() + "Z",
             "previousHash": next((item.get("eventHash", "") for item in logs if item.get("eventHash")), "")}
    key = os.environ.get("AUDIT_SIGNING_KEY", "")
    if not key:
        if os.environ.get("APP_ENV", "development").lower() == "production":
            raise RuntimeError("AUDIT_SIGNING_KEY is required in production")
        key = "insurecrm-development-audit-key"
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    event["eventHash"] = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    logs.insert(0, event)


PUBLIC_API_PATHS = {"/api/health", "/api/auth/status", "/api/auth/bootstrap", "/api/auth/login"}


# When each person last used the CRM, for "employees online" (slide 47). Held in memory:
# it describes this server's recent traffic, and starts empty after a restart.
_LAST_SEEN: Dict[tuple, datetime] = {}


@app.middleware("http")
async def authenticated_company_scope(request: Request, call_next):
    path = request.url.path
    if AUTH_DISABLED or not path.startswith("/api/") or path in PUBLIC_API_PATHS or path.startswith("/api/webhooks/"):
        company_token = company_context.set("default")
        user_token = user_context.set(None)
        try:
            return await call_next(request)
        finally:
            company_context.reset(company_token); user_context.reset(user_token)

    session = verify_session(request.cookies.get(SESSION_COOKIE, ""))
    if not session:
        return JSONResponse(status_code=401, content={"detail": "Sign in to continue"})
    if request.method in {"GET", "HEAD"} and not may_read_path(session.get("role", ""), path):
        return JSONResponse(status_code=403, content={"detail": "Your role does not permit access to this information"})
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
        if not csrf_cookie or not hmac.compare_digest(csrf_cookie, request.headers.get("x-csrf-token", "")):
            return JSONResponse(status_code=403, content={"detail": "Security token expired; refresh and sign in again"})
        if not may_mutate_path(session.get("role", ""), path):
            return JSONResponse(status_code=403, content={"detail": "Your role does not permit this action"})
    company_token = company_context.set(session.get("companyId") or "default")
    user_token = user_context.set(session)
    request.state.user = session
    _LAST_SEEN[(session.get("companyId") or "default", session.get("name", ""))] = datetime.utcnow()
    try:
        return await call_next(request)
    finally:
        company_context.reset(company_token); user_context.reset(user_token)


# ─── Performance, targets and role dashboards (slides 14, 26, 29, 34, 47) ───


def _team_people(db: Dict[str, Any], owners: Optional[set]) -> List[str]:
    """The people whose performance is measured — telecallers and managers — that the caller may see."""
    people = [u.get("name") for u in db.get("users", []) if u.get("status", "Active") == "Active"
              and crm_security.normalized_role(u.get("role", "")) in {"telecaller", "manager"}]
    return [p for p in people if owners is None or p in owners]


def _company_date(db: Dict[str, Any]) -> date:
    return datetime.now(_calendar_timezone(db)).date()


def _measure(db: Dict[str, Any], start: str, end: str, people: List[str]) -> Dict[str, Dict[str, Any]]:
    return metrics.performance(db, start, end, _calendar_timezone(db), money_value, _due_moment, people)


def _targets_for(db: Dict[str, Any], month: str) -> Dict[str, Dict[str, Any]]:
    return (db.get("targets") or {}).get(month, {})


def _headline_measure(db: Dict[str, Any]) -> str:
    return (db.get("settings", {}).get("targets", {}) or {}).get("headline") or "policiesSold"


def _checked_month(month: Optional[str], db: Dict[str, Any]) -> str:
    value = month or _company_date(db).strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise HTTPException(status_code=422, detail="Month must look like 2026-09")
    return value


def _month_range(db: Dict[str, Any], month: str) -> tuple:
    first = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return first.isoformat(), min(last, _company_date(db)).isoformat() if first <= _company_date(db) else last.isoformat()


# ─── Commission (slide 25) ───


def _require_admin(message: str):
    if AUTH_DISABLED:
        return
    session = crm_security.current_user()
    if session and crm_security.normalized_role(session.get("role", "")) != "admin":
        raise HTTPException(status_code=403, detail=message)


def _commission_rules(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (db.get("settings", {}).get("commission", {}) or {}).get("rules", [])


def _commission_rate(db: Dict[str, Any], policy: Dict[str, Any]) -> tuple:
    """(rate %, basis, rule) for a policy, or (None, basis, None) when no rate applies."""
    basis = "renewal" if policy.get("previousPolicyId") else "new"
    product, insurer = (policy.get("policyType") or "").lower(), (policy.get("insurer") or "").lower()
    best, best_score = None, -1
    for rule in _commission_rules(db):
        rule_product, rule_insurer = (rule.get("product") or "").lower(), (rule.get("insurer") or "").lower()
        if (rule_product and rule_product != product) or (rule_insurer and rule_insurer != insurer):
            continue
        score = (2 if rule_product else 0) + (1 if rule_insurer else 0)
        if score > best_score:
            best, best_score = rule, score
    if not best:
        return None, basis, None
    rate = best.get("renewalRate") if basis == "renewal" else best.get("newRate")
    return (float(rate) if rate is not None else None), basis, best


def _fix_commission(db: Dict[str, Any], policy: Dict[str, Any]):
    rate, basis, rule = _commission_rate(db, policy)
    premium = money_value(policy.get("netPremium", policy.get("premium", 0)))
    policy["commission"] = {"rate": rate, "amount": round(premium * rate / 100, 2) if rate is not None else None,
                            "basis": basis, "ruleId": (rule or {}).get("id", ""), "status": "Expected",
                            "fixedAt": datetime.utcnow().isoformat() + "Z", "override": False}


def _apply_commissions(db: Dict[str, Any]):
    """On save: a sold policy gets its commission fixed. If its premium changes before the
    commission is received, the amount follows the premium at the same rate."""
    for policy in db.get("policies", []):
        if not isinstance(policy, dict) or not policy.get("saleDate"):
            continue
        commission = policy.get("commission")
        if not commission:
            _fix_commission(db, policy)
        elif commission.get("rate") is not None and not commission.get("override") and commission.get("status") == "Expected":
            premium = money_value(policy.get("netPremium", policy.get("premium", 0)))
            commission["amount"] = round(premium * commission["rate"] / 100, 2)


# ─── Incentives (slide 29) ───
def _incentive_rules(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (db.get("incentivePlan") or {}).get("rules", [])


# ─── Calling (client blueprint, slides 15–16) ───


def _parse_duration(value: Any) -> Optional[int]:
    """Seconds from 150, "150", "42s" or "2m 30s" — older call records stored text."""
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value or "").strip().lower()
    if text.isdigit():
        return int(text)
    parts = re.findall(r"(\d+)\s*([hms])", text)
    return sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in parts) if parts else None


def _normalize_calls(db: Dict[str, Any]):
    """Older call records: seconds as a number, an owner, and an outcome name we recognise."""
    leads = {l.get("id"): l for l in db.get("leads", [])}
    for call in db.get("callLogs", []):
        if not isinstance(call, dict) or call.get("normalized"):
            continue
        if "durationSeconds" not in call:
            call["durationSeconds"] = _parse_duration(call.get("duration"))
        call.setdefault("assignedTo", call.get("telecaller") or (leads.get(call.get("leadId")) or {}).get("assignedTo", ""))
        call.setdefault("startedAt", call.get("createdAt", ""))
        if call.get("outcome"):
            call["outcome"] = canonical_outcome(call["outcome"])
        call.setdefault("connected", CALL_OUTCOMES.get(call.get("outcome"), {}).get("connected",
                                                                                   call.get("status") == "Completed"))
        call.setdefault("durationSource", "recorded earlier")
        call["normalized"] = True


def _call_view(db: Dict[str, Any], call: Dict[str, Any]) -> Dict[str, Any]:
    lead = next((l for l in db.get("leads", []) if l.get("id") == call.get("leadId")), {})
    return {**call, "customerName": call.get("customerName") or lead.get("name", ""), "product": lead.get("product", "")}


def _set_lead_next(db: Dict[str, Any], lead: Dict[str, Any], status: str, action: str = "", due: str = "",
                   due_time: str = "", reason: str = ""):
    """Move a lead on after a call: close the old follow-up and schedule the next, or finish it."""
    lead["status"] = status
    if reason:
        lead["lostReason"] = reason
    lead["lastModified"] = datetime.utcnow().isoformat() + "Z"
    if status in NO_NEXT_ACTION:
        _close_lead_work(db, lead)
        return
    previous = next((t for t in db.get("tasks", []) if t.get("id") == lead.get("nextActionTaskId")), None)
    if previous and previous.get("status") not in ("Completed", "Archived"):
        previous.update({"status": "Completed", "completedAt": datetime.utcnow().isoformat() + "Z"})
    task = {"id": f"T_{uuid.uuid4().hex[:8]}", "title": action, "associatedType": "Lead", "associatedId": lead["id"],
            "associatedTitle": lead.get("name", ""), "priority": "High" if status in {"Interested", "Quote Sent", "Documents Pending"} else "Medium",
            "dueDate": due, "dueTime": due_time, "status": "Pending", "assignedTo": lead.get("assignedTo", ""),
            "activityType": "Call" if "call" in action.lower() else "Follow-up"}
    db.setdefault("tasks", []).insert(0, task)
    lead.update({"nextAction": action, "nextActionDate": due, "nextActionTime": due_time,
                 "nextActionCompleted": False, "nextActionTaskId": task["id"]})


# ─── Slide 17: Follow-up Management API ───
def _last_interactions(db: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """The most recent contact with each record: a call, a message, a note or a status change."""
    latest: Dict[str, Dict[str, str]] = {}

    def seen(record_id, when, what):
        if record_id and when and when > latest.get(record_id, {}).get("at", ""):
            latest[record_id] = {"at": when, "what": what}

    for call in db.get("callLogs", []):
        seen(call.get("leadId"), call.get("createdAt"), f"Call — {call.get('outcome') or call.get('status') or 'logged'}")
    for message in db.get("communications", []):
        seen(message.get("associatedId"), message.get("sentAt") or message.get("createdAt"),
             f"{message.get('channel', 'Message')} {str(message.get('direction', '')).lower()}".strip())
    for note in db.get("notes", []):
        if not note.get("archived"):
            seen(note.get("associatedId"), note.get("createdAt"), note.get("title") or "Note")
    return latest


# ─── Leads CRUD & Stage Transition Engine ───


def _require_manager(message: str):
    """Owner / Admin and Managers only. Local development without sign-in is unrestricted."""
    if AUTH_DISABLED:
        return
    session = crm_security.current_user()
    if session and crm_security.normalized_role(session.get("role", "")) not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail=message)


# Suggestions only — a reason is free text, these are the ones telecallers use most.
CLOSE_REASONS = ["Premium too high", "Renewed with current insurer", "Bought from another agent",
                 "Not planning to insure now", "Vehicle sold", "Already covered by employer", "Stopped responding"]


def _sync_lead_work(db: Dict[str, Any], lead: Dict[str, Any], changes: Dict[str, Any]):
    """Apply the same owner and next-action rules to single and bulk edits."""
    lead_id = lead["id"]
    if "assignedTo" in changes:
        for record in db.get("tasks", []) + db.get("deals", []):
            linked = (record.get("associatedType") == "Lead" and record.get("associatedId") == lead_id) or record.get("leadId") == lead_id
            if linked and record.get("status") not in {"Completed", "Archived", "Cancelled"}:
                record["assignedTo"] = lead.get("assignedTo")
        for event in db.get("calendarEvents", []):
            if event.get("associatedType") == "Lead" and event.get("associatedId") == lead_id and event.get("status") == "Scheduled":
                event["assignedTo"] = lead.get("assignedTo")
                _validate_appointment(db, event)
    if not {"nextAction", "nextActionDate", "nextActionTime", "priority"}.intersection(changes):
        return
    task = next((t for t in db.get("tasks", []) if t.get("id") == lead.get("nextActionTaskId")), None)
    if "nextAction" in changes or "nextActionDate" in changes:
        due = _parse_flexible_date(lead.get("nextActionDate", ""))
        if not due or not str(lead.get("nextAction") or "").strip():
            raise HTTPException(status_code=422, detail="A next action and valid date are required")
        lead["nextActionDate"] = due
        if not task:
            task = {"id": f"T_{uuid.uuid4().hex[:8]}", "associatedType": "Lead", "associatedId": lead_id,
                    "associatedTitle": lead.get("name", ""), "activityType": "Follow-up"}
            db.setdefault("tasks", []).insert(0, task)
            lead["nextActionTaskId"] = task["id"]
        task.update({"title": lead["nextAction"], "dueDate": due, "dueTime": lead.get("nextActionTime", ""),
                     "assignedTo": lead.get("assignedTo"), "status": "Pending"})
        lead["nextActionCompleted"] = False
        _sync_calendar_event_from_task(db, task)
    if task and "nextActionTime" in changes and not {"nextAction", "nextActionDate"}.intersection(changes):
        task["dueTime"] = lead.get("nextActionTime", "")
    if task:
        task["priority"] = lead.get("priority", "Medium")


@app.put("/api/leads/{id}")
def update_lead(id: str, updates: Dict[str, Any]):
    db = load_db()
    lead = next((l for l in db.get("leads", []) if l["id"] == id), None)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    require_visible(lead, visible_owners(db), "Lead")
    before = dict(lead)
    allowed = {"firstName", "lastName", "name", "organization", "email", "mobile", "policyType", "premium",
               "expiryDate", "assignedTo", "nextAction", "nextActionDate", "nextActionTime", "priority", "source", "product", "city",
               "leadPriority", "leadSource", "vehicleDetails", "healthDetails", "existingPolicy", "status", "lostReason"}
    changes = {k: v for k, v in updates.items() if k in allowed}

    if "assignedTo" in changes and changes["assignedTo"] != lead.get("assignedTo"):
        _require_manager("Only an Owner / Admin or a Manager can reassign a lead.")
    if "product" in changes:
        changes["product"] = _checked_product(db, changes["product"])
        changes["policyType"] = changes["product"]
    if "source" in changes or "leadSource" in changes:
        chosen = _checked_source(db, changes.pop("leadSource", None) or changes.pop("source", None))
        changes["source"] = changes["leadSource"] = chosen
    for field in _DETAIL_MODELS:
        if field in changes:
            changes[field] = _checked_details(field, changes[field], lead.get(field))
    if "nextActionTime" in changes:
        changes["nextActionTime"] = _checked_time(changes["nextActionTime"])
    if changes.get("expiryDate"):
        parsed = _parse_flexible_date(changes["expiryDate"])
        if not parsed:
            raise HTTPException(status_code=422, detail="Policy expiry is not a valid date")
        changes["expiryDate"] = parsed
        changes["existingPolicy"] = {**changes.get("existingPolicy", lead.get("existingPolicy") or {}), "expiryDate": parsed}
    elif changes.get("existingPolicy", {}).get("expiryDate"):
        changes["expiryDate"] = changes["existingPolicy"]["expiryDate"]

    new_status = None
    if "status" in changes and canonical_status(changes["status"]) != canonical_status(lead.get("status")):
        new_status = _checked_status_change(lead, changes["status"], changes.get("lostReason", ""),
                                            changes.get("nextAction"), changes.get("nextActionDate"))
        changes["status"] = new_status
    else:
        changes.pop("status", None)
    finished = canonical_status(new_status or lead.get("status")) in NO_NEXT_ACTION
    if finished:
        # A finished lead keeps no next action; an edit form resending blank ones is not an error.
        changes.pop("nextAction", None)
        changes.pop("nextActionDate", None)
        changes.pop("nextActionTime", None)

    lead.update(changes)
    if "leadPriority" in changes:
        p_val = str(changes["leadPriority"]).upper()
        lead["priority"] = p_val.capitalize() if p_val in ("HOT", "WARM", "COLD") else lead.get("priority", "Medium")
    if "name" in changes:
        parts = changes["name"].strip().split(" ", 1)
        lead["firstName"] = parts[0]
        lead["lastName"] = parts[1] if len(parts) > 1 else ""
    lead["lastModified"] = datetime.utcnow().isoformat() + "Z"
    if "expiryDate" in changes:
        lead["daysRemaining"] = _days_until(lead.get("expiryDate", ""))
    for contact in db.get("contacts", []):
        linked = contact.get("leadId") == id
        matches_original = bool(before.get("mobile") or before.get("email")) and contact.get("phone") == before.get("mobile") and contact.get("email") == before.get("email")
        if (linked and (contact.get("isPrimary") or matches_original)) or (not contact.get("leadId") and matches_original):
            contact.update({"leadId": id, "name": lead.get("name"), "email": lead.get("email"), "phone": lead.get("mobile"), "organization": lead.get("organization"), "lastModified": lead["lastModified"]})
    if new_status in NO_NEXT_ACTION:
        _close_lead_work(db, lead)
    _sync_lead_work(db, lead, changes)
    audit(db, "Lead Updated", "Lead", id, {"before": {k: before.get(k) for k in changes}, "after": changes})
    save_db(db)
    return lead


class DealModel(BaseModel):
    title: Optional[str] = ""
    dealName: Optional[str] = ""
    customerId: Optional[str] = ""
    leadId: Optional[str] = ""
    organizationId: Optional[str] = ""
    organization: Optional[str] = ""
    stage: Optional[str] = "Open"
    status: Optional[str] = "Open"
    estimatedPremium: Optional[float] = 0
    annualRevenue: Optional[Any] = 0
    assignedTo: Optional[str] = None
    expectedCloseDate: Optional[str] = ""
    probability: Optional[float] = 50.0
    commissionRate: Optional[float] = 10.0

# ─── Deals CRUD ───

class DealModel(BaseModel):
    title: Optional[str] = ""
    dealName: Optional[str] = ""
    customerId: Optional[str] = ""
    leadId: Optional[str] = ""
    organizationId: Optional[str] = ""
    organization: Optional[str] = ""
    stage: Optional[str] = "Open"
    status: Optional[str] = "Open"
    estimatedPremium: Optional[float] = 0
    annualRevenue: Optional[Any] = 0
    assignedTo: Optional[str] = None
    expectedCloseDate: Optional[str] = ""
    probability: Optional[float] = 50.0
    commissionRate: Optional[float] = 10.0


# ─── Polymorphic Notes CRUD ───


def _sync_lead_next_action(db: Dict[str, Any], task: Dict[str, Any]):
    """Keep a lead's next action in step with the task that represents it.

    The stage modal provisions a task per next action, so ticking that task off is how a
    broker actually finishes the action. Without this the lead stays flagged overdue forever.
    """
    lead_id = task.get("associatedId")
    if not lead_id or task.get("associatedType") != "Lead":
        return
    lead = next((l for l in db.get("leads", []) if l.get("id") == lead_id), None)
    if not lead:
        return
    if lead.get("nextActionTaskId"):
        if lead["nextActionTaskId"] != task.get("id"):
            return
    elif lead.get("nextAction") != task.get("title"):
        return
    lead["nextActionTaskId"] = task["id"]
    lead["nextAction"] = task.get("title", "")
    lead["nextActionDate"] = task.get("dueDate", "")
    lead["nextActionTime"] = task.get("dueTime", "")
    lead["nextActionCompleted"] = task.get("status") == "Completed"
    lead["lastModified"] = datetime.utcnow().isoformat() + "Z"

def _sync_calendar_event_from_task(db: Dict[str, Any], task: Dict[str, Any]):
    """Mirror task edits into the appointment that owns the task."""
    event_id = task.get("calendarEventId")
    if not event_id:
        return
    event = next((item for item in db.get("calendarEvents", []) if item.get("id") == event_id), None)
    if not event:
        task.pop("calendarEventId", None)
        return
    candidate = {**event, "title": task.get("title"), "date": task.get("dueDate"),
                 "assignedTo": task.get("assignedTo"),
                 "status": "Completed" if task.get("status") == "Completed" else
                           "Archived" if task.get("status") == "Archived" else "Scheduled"}
    _validate_appointment(db, candidate)
    event.update({"title": task.get("title", event.get("title", "")),
                  "date": task.get("dueDate", event.get("date", "")),
                  "assignedTo": task.get("assignedTo", event.get("assignedTo", ""))})
    if task.get("status") == "Completed": event["status"] = "Completed"
    elif task.get("status") == "Archived": event["status"] = "Archived"
    elif event.get("status") in ["Completed", "Archived"]: event["status"] = "Scheduled"
    event["updatedAt"] = datetime.utcnow().isoformat() + "Z"

# ─── Polymorphic Tasks CRUD ───


@app.put("/api/tasks/{id}")
def update_task(id: str, updates: Dict[str, Any]):
    db = load_db()
    for task in db.get("tasks", []):
        if task["id"] == id:
            require_visible(task, visible_owners(db), "Task")
            before = dict(task)
            allowed = {"title", "priority", "dueDate", "dueTime", "status", "assignedTo", "activityType"}
            changes = {k: v for k, v in updates.items() if k in allowed}
            if "dueTime" in changes:
                changes["dueTime"] = _checked_time(changes["dueTime"])
            if "assignedTo" in changes and changes["assignedTo"] != task.get("assignedTo"):
                _require_manager("Only an Owner / Admin or a Manager can hand a task to someone else.")
            if "dueDate" in changes:
                changes["dueDate"] = _parse_flexible_date(changes["dueDate"])
                if not changes["dueDate"]:
                    raise HTTPException(status_code=422, detail="A valid due date is required")
            # Record when work actually finished; "completed today" cannot be derived
            # from the due date, which is when it was meant to happen.
            if changes.get("status") == "Completed" and task.get("status") != "Completed":
                changes["completedAt"] = datetime.utcnow().isoformat() + "Z"
            elif "status" in changes and changes["status"] != "Completed":
                changes["completedAt"] = ""
            if "title" in changes and (not isinstance(changes["title"], str) or not changes["title"].strip()):
                raise HTTPException(status_code=422, detail="A task title is required")
            if "status" in changes and changes["status"] not in {"Pending", "In Progress", "Completed", "Archived"}:
                raise HTTPException(status_code=422, detail="Invalid task status")
            task.update(changes)
            _sync_lead_next_action(db, task)
            _sync_calendar_event_from_task(db, task)
            audit(db, "Task Updated", "Task", id, {"before":{k:before.get(k) for k in changes}, "after":changes})
            save_db(db)
            return task
    raise HTTPException(status_code=404, detail="Task not found")


# ─── Core Insurance Operations ───
class LeadConversionPayload(BaseModel):
    customerName: Optional[str] = ""
    organization: Optional[str] = ""
    policyType: Optional[str] = ""
    insurer: Optional[str] = ""
    sumInsured: Optional[float] = 0
    premium: Optional[float] = 0
    startDate: Optional[str] = ""
    expiryDate: Optional[str] = ""
    assignedTo: Optional[str] = ""


# ─── Quotation lifecycle (client blueprint, slide 20) ───
QUOTE_STATUSES = ["Draft", "Sent", "Viewed", "Negotiation", "Accepted", "Rejected", "Expired"]
QUOTE_TRANSITIONS = {
    "Draft": {"Sent", "Rejected"},
    "Sent": {"Viewed", "Negotiation", "Accepted", "Rejected", "Expired"},
    "Viewed": {"Negotiation", "Accepted", "Rejected", "Expired"},
    "Negotiation": {"Sent", "Accepted", "Rejected", "Expired"},
    "Rejected": {"Sent"}, "Expired": {"Sent"},        # a revised quote can go out again
    "Accepted": set(),
}
_OPEN_QUOTE = {"Sent", "Viewed", "Negotiation"}
# Earlier screens stored "Received" (from the insurer, not yet sent) and "Selected".
_LEGACY_QUOTE_STATUSES = {"received": "Draft", "selected": "Accepted"}


def canonical_quote_status(value: Optional[str]) -> str:
    text = (value or "Draft").strip()
    return next((q for q in QUOTE_STATUSES if q.lower() == text.lower()), None) or _LEGACY_QUOTE_STATUSES.get(text.lower(), text)


def _expire_quotes(db: Dict[str, Any]):
    """A quote still waiting on the customer after its validity date has expired."""
    today = _company_today(db)
    for quote in db.get("quotations", []):
        quote["status"] = canonical_quote_status(quote.get("status"))
        if quote["status"] in _OPEN_QUOTE and quote.get("validityDate") and quote["validityDate"] < today:
            quote["status"] = "Expired"
            quote.setdefault("statusHistory", []).append({"status": "Expired", "at": datetime.utcnow().isoformat() + "Z",
                                                          "by": "Validity date passed"})


def _find_record(items: List[Dict[str, Any]], record_id: str, label: str):
    record = next((item for item in items if item.get("id") == record_id), None)
    if not record:
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return record

def _days_until(date_value: str) -> Optional[int]:
    try:
        return (datetime.strptime(date_value, "%Y-%m-%d").date() - datetime.now().date()).days
    except (TypeError, ValueError):
        return None

def live_expiry_inplace(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Same derivation as live_expiry_all, without copying every record.

    load_db() hands back a freshly parsed structure each call, so the records are ours to
    write to. Copying 3,000 dicts per request cost ~9ms for no benefit.
    """
    for record in records:
        record["daysRemaining"] = _days_until(record.get("expiryDate", ""))
    return records

def live_expiry(record: Dict[str, Any]) -> Dict[str, Any]:
    """Derive daysRemaining from expiryDate at read time.

    A stored countdown silently drifts one day out of date every day, which quietly
    hides expiring policies from the renewal radar. Every read path goes through here
    so the radar always reflects today.
    """
    return {**record, "daysRemaining": _days_until(record.get("expiryDate", ""))}

def live_expiry_all(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [live_expiry(r) for r in records]

def _expiring_within(record: Dict[str, Any], days: int) -> bool:
    """True when the record expires today or within `days`. Records with no expiry date never qualify."""
    remaining = record.get("daysRemaining")
    if remaining is None:
        remaining = _days_until(record.get("expiryDate", ""))
    return remaining is not None and 0 <= remaining <= days

def _convert_lead(db: Dict[str, Any], lead: Dict[str, Any], payload: "LeadConversionPayload") -> Dict[str, Any]:
    """A sale: the lead becomes a customer with a draft policy that records when it was sold,
    where the lead came from and when it renews (slide 22)."""
    id = lead["id"]
    if lead.get("convertedPolicyId"):
        raise HTTPException(status_code=409, detail="Lead has already been converted")
    for field, value in (("premium", payload.premium), ("sumInsured", payload.sumInsured)):
        if value is not None and value < 0:
            raise HTTPException(status_code=422, detail=f"{field} cannot be negative")
    start_date = _parse_flexible_date(payload.startDate) if payload.startDate else ""
    expiry_date = _parse_flexible_date(payload.expiryDate) if payload.expiryDate else lead.get("expiryDate", "")
    if (payload.startDate and not start_date) or (payload.expiryDate and not expiry_date):
        raise HTTPException(status_code=422, detail="Policy dates must be valid dates")
    if start_date and expiry_date and start_date > expiry_date:
        raise HTTPException(status_code=422, detail="Policy startDate cannot be after expiryDate")
    owner = payload.assignedTo or lead.get("assignedTo") or current_actor("")
    now = datetime.utcnow().isoformat() + "Z"
    customer = next((c for c in db.get("customers", []) if c.get("sourceLeadId") == id), None)
    if not customer:
        customer = {"id": f"CUS_{uuid.uuid4().hex[:8]}", "sourceLeadId": id, "name": lead.get("name", ""),
                    "organization": lead.get("organization", ""), "email": lead.get("email", ""), "mobile": lead.get("mobile", ""),
                    "city": lead.get("city", ""), "assignedTo": owner, "status": "Active", "createdAt": now}
        db.setdefault("customers", []).insert(0, customer)
    org_name = (payload.organization or customer.get("organization") or lead.get("organization", "")).strip()
    customer.update({"name": payload.customerName or customer.get("name") or lead.get("name", ""), "organization": org_name})
    organization_id = ""
    # A personal enquiry has no organisation; the "Private Individual" placeholder is not one.
    if org_name and org_name.lower() not in _SHARED_ORGANIZATIONS:
        organization = next((o for o in db.get("organizations", []) if o.get("name", "").strip().lower() == org_name.lower()), None)
        if not organization:
            organization = {"id": f"ORG_{uuid.uuid4().hex[:8]}", "name": org_name, "status": "Active",
                            "createdAt": now, "lastModified": now}
            db.setdefault("organizations", []).insert(0, organization)
            audit(db, "Organization Created", "Organization", organization["id"], organization)
        organization_id = organization["id"]
        customer["organizationId"] = organization_id
    for contact in db.get("contacts", []):
        if contact.get("leadId") == id:
            contact["customerId"] = customer["id"]
    # Deals belong to the earlier commercial workflow: an existing one is closed as won, none is created.
    deal_ids = []
    for d in [d for d in db.get("deals", []) if d.get("leadId") == id]:
        d.update({"stage": "Won", "status": "Won", "customerId": customer["id"], "lastModified": now, "updatedAt": now})
        if not d.get("organization") and customer.get("organization"):
            d["organization"] = customer.get("organization")
        if not d.get("organizationId") and organization_id:
            d["organizationId"] = organization_id
        deal_ids.append(d["id"])
    policy_id = f"POL_{uuid.uuid4().hex[:8]}"
    policy = {
        "id": policy_id, "leadId": id, "customerId": customer["id"], "organizationId": organization_id,
        "customerName": customer.get("name", ""), "organization": customer.get("organization", ""),
        "policyType": payload.policyType or lead.get("product") or lead.get("policyType", ""),
        "policyNumber": "", "insurer": payload.insurer or "", "sumInsured": payload.sumInsured or 0,
        "premium": payload.premium or 0, "startDate": start_date, "expiryDate": expiry_date,
        "renewalDate": expiry_date, "saleDate": _company_today(db), "leadSource": lead.get("source", ""),
        "status": "Draft", "issuanceStatus": "Pending Documents", "assignedTo": owner, "createdAt": now, "updatedAt": now}
    policy.update(policy_financials(policy.get("premium"), 18))
    policy["daysRemaining"] = _days_until(policy.get("expiryDate", ""))
    db.setdefault("policies", []).insert(0, policy)
    lead.update({"status": "Policy Sold", "convertedCustomerId": customer["id"], "convertedPolicyId": policy_id, "lastModified": now})
    _close_lead_work(db, lead)
    for event in db.get("calendarEvents", []):
        if event.get("associatedType") == "Lead" and event.get("associatedId") == id:
            event["customerId"] = customer["id"]
            event["convertedPolicyId"] = policy_id
    for task in db.get("tasks", []):
        if task.get("associatedType") == "Lead" and task.get("associatedId") == id:
            task["customerId"] = customer["id"]
    audit(db, "Lead Converted", "Lead", id, {"customerId": customer["id"], "organizationId": organization_id,
                                             "dealIds": deal_ids, "policyId": policy_id})
    return {"status": "success", "lead": lead, "customer": customer, "policy": policy}


def relational_integrity(db: Dict[str, Any]) -> Dict[str, Any]:
    ids = lambda collection: {item.get("id") for item in db.get(collection, [])}
    customers, policies, leads, organizations = ids("customers"), ids("policies"), ids("leads"), ids("organizations")
    has_valid_parent = lambda record: ((record.get("customerId") in customers) or (record.get("leadId") in leads)
                                       or (record.get("organizationId") in organizations))
    return {
        "policiesWithoutCustomer": sum(not p.get("customerId") or p.get("customerId") not in customers for p in db.get("policies", [])),
        "issuedPoliciesMissingInsurer": sum(p.get("issuanceStatus") == "Issued" and not p.get("insurer") for p in db.get("policies", [])),
        "issuedPoliciesMissingStartDate": sum(p.get("issuanceStatus") == "Issued" and not p.get("startDate") for p in db.get("policies", [])),
        "renewalsWithoutPolicy": sum(r.get("policyId") not in policies for r in db.get("renewals", [])),
        "contactsWithoutParent": sum(not has_valid_parent(c) for c in db.get("contacts", [])),
        "dealsWithoutParent": sum(not has_valid_parent(d) for d in db.get("deals", [])),
        "prospectContactsAwaitingConversion": sum(not c.get("customerId") and c.get("leadId") in leads for c in db.get("contacts", [])),
    }


def repair_relational_model(db: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill durable IDs without inventing underwriting facts.

    Legacy lead-policy rows that claim to be issued without insurer/start dates are
    deliberately quarantined as Needs Review. A migration must never turn missing
    insurance evidence into a valid policy silently.
    """
    before = relational_integrity(db)
    counts = {"customersCreated": 0, "organizationsLinked": 0, "contactsLinked": 0,
              "dealsLinked": 0, "policiesLinked": 0, "renewalsLinked": 0, "policiesQuarantined": 0,
              "smsTemplatesRetired": 0}
    leads = {lead.get("id"): lead for lead in db.get("leads", [])}
    organizations_by_name = {o.get("name", "").strip().lower(): o for o in db.get("organizations", []) if o.get("name")}
    customers_by_lead = {c.get("sourceLeadId"): c for c in db.get("customers", []) if c.get("sourceLeadId")}

    def organization_for(name: str) -> Optional[Dict[str, Any]]:
        key = (name or "").strip().lower()
        if not key or key == "private individual": return None
        organization = organizations_by_name.get(key)
        if not organization:
            organization = {"id": f"O_{uuid.uuid4().hex[:8]}", "name": name.strip(), "status": "Active",
                            "createdAt": datetime.utcnow().isoformat() + "Z", "migrationSource": "relationship-repair"}
            db.setdefault("organizations", []).append(organization); organizations_by_name[key] = organization
        return organization

    def customer_for(lead: Dict[str, Any]) -> Dict[str, Any]:
        customer = customers_by_lead.get(lead.get("id"))
        if customer: return customer
        customer = {"id": f"CUS_{uuid.uuid4().hex[:8]}", "sourceLeadId": lead.get("id"), "name": lead.get("name", ""),
                    "organization": lead.get("organization", ""), "email": lead.get("email", ""), "mobile": lead.get("mobile", ""),
                    "status": "Active", "assignedTo": lead.get("assignedTo", ""), "createdAt": datetime.utcnow().isoformat() + "Z",
                    "migrationSource": "legacy-policy-owner"}
        db.setdefault("customers", []).append(customer); customers_by_lead[lead.get("id")] = customer
        counts["customersCreated"] += 1
        return customer

    def related_lead(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if record.get("leadId") in leads: return leads[record["leadId"]]
        email = str(record.get("email", "")).strip().lower()
        phone = record.get("phone") or record.get("mobile") or ""
        exact = [lead for lead in leads.values() if (email and str(lead.get("email", "")).strip().lower() == email)
                 or (phone and _same_phone(phone, lead.get("mobile", "")))]
        if len(exact) == 1: return exact[0]
        organization = str(record.get("organization", "")).strip().lower()
        by_org = [lead for lead in leads.values() if organization and str(lead.get("organization", "")).strip().lower() == organization]
        return by_org[0] if len(by_org) == 1 else None

    for policy in db.get("policies", []):
        lead = leads.get(policy.get("leadId"))
        customer = customers_by_lead.get(policy.get("leadId")) if lead else None
        if lead and not customer:
            customer = customer_for(lead)
        if customer and policy.get("customerId") != customer["id"]:
            policy["customerId"] = customer["id"]; counts["policiesLinked"] += 1
        name = policy.get("organization") or (lead or {}).get("organization", "")
        organization = organization_for(name)
        if organization and policy.get("organizationId") != organization["id"]:
            policy["organizationId"] = organization["id"]; counts["organizationsLinked"] += 1
        if customer and organization:
            customer["organizationId"] = organization["id"]
        if policy.get("issuanceStatus") == "Issued" and (not policy.get("insurer") or not policy.get("startDate") or not policy.get("policyNumber")):
            policy.update({"issuanceStatus": "Needs Review", "status": "Data Review", "migrationIssue": "Missing issuance evidence"})
            counts["policiesQuarantined"] += 1

    for contact in db.get("contacts", []):
        lead = related_lead(contact)
        if lead and not contact.get("leadId"): contact["leadId"] = lead["id"]
        customer = customers_by_lead.get((lead or {}).get("id"))
        if customer and contact.get("customerId") != customer["id"]:
            contact["customerId"] = customer["id"]; counts["contactsLinked"] += 1
        organization = organization_for(contact.get("organization") or (lead or {}).get("organization", ""))
        if organization: contact["organizationId"] = organization["id"]

    for deal in db.get("deals", []):
        lead = related_lead(deal)
        if lead and not deal.get("leadId"): deal["leadId"] = lead["id"]
        customer = customers_by_lead.get((lead or {}).get("id"))
        if customer and deal.get("customerId") != customer["id"]:
            deal["customerId"] = customer["id"]; counts["dealsLinked"] += 1
        organization = organization_for(deal.get("organization") or (lead or {}).get("organization", ""))
        if organization: deal["organizationId"] = organization["id"]

    policy_index = {p.get("id"): p for p in db.get("policies", [])}
    for renewal in db.get("renewals", []):
        policy = policy_index.get(renewal.get("policyId"))
        if policy and renewal.get("customerId") != policy.get("customerId"):
            renewal["customerId"] = policy.get("customerId"); renewal["organizationId"] = policy.get("organizationId", "")
            counts["renewalsLinked"] += 1

    for template in db.get("communicationTemplates", []):
        if str(template.get("channel", "")).lower() == "sms" and template.get("status") != "Retired — SMS removed":
            template.update({"status": "Retired — SMS removed", "retiredAt": datetime.utcnow().isoformat() + "Z"})
            counts["smsTemplatesRetired"] += 1

    after = relational_integrity(db)
    audit(db, "Relational Data Repaired", "System", "relationship-repair", {"before": before, "after": after, "changes": counts})
    return {"before": before, "after": after, "changes": counts}


# ─── Renewals (client blueprint, slides 23–24) ───
RENEWAL_WINDOW_DAYS = 60
RENEWAL_LADDER = [60, 30, 15, 7, 0]          # reminder stages, in days before expiry
_CLOSED_RENEWAL = {"Renewed", "Lost", "Lapsed"}


def renewal_stage(days: Optional[int], stage: str = "") -> str:
    """Where a renewal sits on the slide-23 ladder."""
    if stage in _CLOSED_RENEWAL:
        return "Renewed" if stage == "Renewed" else "Lost"
    if days is None:
        return ""
    if days < 0:
        return "Expired — not renewed"
    if days == 0:
        return "Renewal due today"
    reached = [t for t in RENEWAL_LADDER if t and days <= t]
    return f"{min(reached)} days" if reached else ""


def _open_due_renewals(db: Dict[str, Any], days: int = RENEWAL_WINDOW_DAYS, policies: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Open a renewal for every active policy expiring within `days` that has none open."""
    open_for = {r.get("policyId") for r in db.get("renewals", []) if r.get("stage") not in _CLOSED_RENEWAL}
    created = []
    for policy in policies if policies is not None else db.get("policies", []):
        if policy.get("status") in ("Draft", "Cancelled", "Expired/Renewed") or policy.get("id") in open_for:
            continue
        remaining = _days_until(policy.get("expiryDate", ""))
        if remaining is None or remaining < 0 or remaining > days:
            continue
        now = datetime.utcnow().isoformat() + "Z"
        item = {"id": f"REN_{uuid.uuid4().hex[:8]}", "policyId": policy["id"], "customerName": policy.get("customerName"),
                "customerId": policy.get("customerId", ""), "organization": policy.get("organization"),
                "policyNumber": policy.get("policyNumber"), "product": policy.get("policyType", ""), "insurer": policy.get("insurer", ""),
                "expiryDate": policy.get("expiryDate"), "assignedTo": policy.get("assignedTo") or "",
                "stage": "Due Soon", "previousPremium": money_value(policy.get("netPremium", policy.get("premium", 0))),
                "targetPremium": money_value(policy.get("netPremium", policy.get("premium", 0))),
                "nextAction": "Contact customer for renewal", "nextActionDate": _company_today(db), "outcomeReason": "",
                "createdAt": now, "updatedAt": now}
        db.setdefault("renewals", []).insert(0, item)
        audit(db, "Renewal Generated", "Renewal", item["id"], {"policyId": policy["id"], "days": remaining})
        created.append(item)
    return created


def run_renewal_tracking() -> int:
    """Scheduler: renewals open themselves 60 days before expiry — nobody has to remember to."""
    db = load_db()
    created = _open_due_renewals(db)
    if created:
        save_db(db)
    return len(created)


@app.get("/api/renewals/report")
def renewal_report():
    db = load_db()
    renewals = db.get("renewals", [])
    stages = {}
    for renewal in renewals:
        stages[renewal.get("stage", "Unknown")] = stages.get(renewal.get("stage", "Unknown"), 0) + 1
    closed = [r for r in renewals if r.get("stage") in ["Renewed", "Lost", "Lapsed"]]
    renewed = [r for r in closed if r.get("stage") == "Renewed"]
    return {"total": len(renewals), "byStage": stages, "closed": len(closed), "renewed": len(renewed),
            "retentionRate": round((len(renewed) / len(closed)) * 100, 1) if closed else 0,
            "premiumRetained": sum(float(r.get("targetPremium") or 0) for r in renewed)}

# ─── Communication, Consent & Delivery Tracking ───


def _consent_allows(db: Dict[str, Any], lead_id: str, channel: str, recipient: str = "") -> bool:
    consents = db.get("consents", [])
    matching = [c for c in consents if (c.get("leadId") == lead_id or c.get("associatedId") == lead_id or c.get("customerId") == lead_id) and c.get("channel", "").lower() == channel.lower()]
    if matching and any(m.get("status") == "Opted Out" for m in matching):
        return False
    cust = next((c for c in db.get("customers", []) if c.get("id") == lead_id), None)
    if cust:
        src_lead_id = cust.get("sourceLeadId")
        if src_lead_id:
            lead_matching = [c for c in consents if c.get("leadId") == src_lead_id and c.get("channel", "").lower() == channel.lower()]
            if lead_matching and any(m.get("status") == "Opted Out" for m in lead_matching):
                return False
        if cust.get("email"):
            em_match = [c for c in consents if c.get("email", "").lower() == cust["email"].lower() and c.get("channel", "").lower() == channel.lower()]
            if em_match and any(m.get("status") == "Opted Out" for m in em_match):
                return False
    if recipient:
        rec_match = [c for c in consents if (c.get("recipient", "").lower() == recipient.lower() or c.get("email", "").lower() == recipient.lower() or c.get("phone") == recipient) and c.get("channel", "").lower() == channel.lower()]
        if rec_match and any(m.get("status") == "Opted Out" for m in rec_match):
            return False
        lead_by_rec = next((l for l in db.get("leads", []) if l.get("email", "").lower() == recipient.lower() or l.get("mobile") == recipient), None)
        if lead_by_rec:
            l_match = [c for c in consents if c.get("leadId") == lead_by_rec["id"] and c.get("channel", "").lower() == channel.lower()]
            if l_match and any(m.get("status") == "Opted Out" for m in l_match):
                return False
    return True


# ─── Outbound sending: WhatsApp & email ─────────────────────────────
# Each channel type has one dispatcher. When the client hasn't supplied credentials yet
# the message is still recorded against the client's timeline, clearly marked as not sent,
# so nobody mistakes a simulation for a delivered message.

WHATSAPP_API_VERSION = "v21.0"
# Overridable so the integration can be pointed at a sandbox or a stand-in during testing.
GRAPH_API_BASE = os.environ.get("GRAPH_API_BASE", "https://graph.facebook.com").rstrip("/")

def _sending_channel(db: Dict[str, Any], channel_type: str) -> Optional[Dict[str, Any]]:
    """The connected source able to send on this channel, if sending is configured."""
    wanted = "whatsapp" if channel_type.lower() == "whatsapp" else "email"
    for channel in db.get("channels", []):
        if channel.get("status") != "Connected":
            continue
        provider = channel.get("provider")
        creds = _usable_credentials(channel)
        if wanted == "whatsapp" and provider == "whatsapp" and creds.get("accessToken") and creds.get("phoneNumberId"):
            return channel
        if wanted == "email" and provider == "email" and creds.get("smtpHost") and creds.get("smtpUsername"):
            return channel
    return None

def _send_whatsapp(channel: Dict[str, Any], to: str, text: str,
                   template: Optional[Dict[str, Any]] = None, values: Optional[List[str]] = None) -> Dict[str, Any]:
    """WhatsApp Business Cloud API.

    Free-form text only reaches people who messaged within the last 24 hours. Outside that
    window Meta requires a template it has already approved, sent with positional values.
    """
    creds = _usable_credentials(channel)
    digits = "".join(ch for ch in str(to) if ch.isdigit())
    url = f"{GRAPH_API_BASE}/{WHATSAPP_API_VERSION}/{creds['phoneNumberId']}/messages"
    if template:
        body = {"messaging_product": "whatsapp", "to": digits, "type": "template",
                "template": {"name": template["metaName"], "language": {"code": template.get("language", "en_US")},
                             "components": [{"type": "body",
                                             "parameters": [{"type": "text", "text": v} for v in (values or [])]}]
                             if values else []}}
    else:
        body = {"messaging_product": "whatsapp", "to": digits,
                "type": "text", "text": {"preview_url": False, "body": text}}
    try:
        response = httpx.post(url, timeout=20.0,
                              headers={"Authorization": f"Bearer {creds['accessToken']}",
                                       "Content-Type": "application/json"},
                              json=body)
        if response.status_code >= 400:
            detail = ""
            try:
                detail = (response.json().get("error") or {}).get("message", "")
            except Exception:
                detail = response.text[:200]
            return {"ok": False, "error": detail or f"WhatsApp returned HTTP {response.status_code}"}
        data = response.json()
        message_id = (data.get("messages") or [{}])[0].get("id", "")
        return {"ok": True, "providerMessageId": message_id}
    except Exception as exc:
        return {"ok": False, "error": f"Could not reach WhatsApp: {exc}"}

def _send_email_sync(channel: Dict[str, Any], to: str, subject: str, body: str) -> Dict[str, Any]:
    creds = _usable_credentials(channel)
    sender = creds.get("fromAddress") or creds.get("inboundAddress") or creds.get("smtpUsername")
    message = EmailMessage()
    message["Subject"] = subject or "Message from your insurance broker"
    message["From"] = sender
    message["To"] = to
    message.set_content(body)
    port = int(creds.get("smtpPort") or 587)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(creds["smtpHost"], port, timeout=20)
        else:
            server = smtplib.SMTP(creds["smtpHost"], port, timeout=20)
        with server:
            server.ehlo()
            # Only negotiate TLS when the server actually offers it — internal relays often don't.
            if port != 465 and server.has_extn("starttls"):
                server.starttls()
                server.ehlo()
            # Authenticate only where the server asks for it; an internal relay may not.
            if creds.get("smtpPassword") and server.has_extn("auth"):
                server.login(creds["smtpUsername"], creds["smtpPassword"])
            server.send_message(message)
        return {"ok": True, "providerMessageId": message.get("Message-ID") or f"SMTP_{uuid.uuid4().hex[:10]}"}
    except Exception as exc:
        return {"ok": False, "error": f"Email could not be sent: {exc}"}

def _send_email(channel: Dict[str, Any], to: str, subject: str, body: str) -> Dict[str, Any]:
    try:
        # loop.run_in_executor / run_in_threadpool: offload blocking SMTP I/O safely
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_send_email_sync, channel, to, subject, body)
            return future.result(timeout=25)
    except Exception:
        pass
    return _send_email_sync(channel, to, subject, body)

def _dispatch(db: Dict[str, Any], item: Dict[str, Any],
              template: Optional[Dict[str, Any]] = None,
              template_values: Optional[List[str]] = None) -> Dict[str, Any]:
    channel_type = (item.get("channel") or "").lower()
    channel = _sending_channel(db, channel_type)
    now_str = datetime.utcnow().isoformat() + "Z"
    if template is None and item.get("whatsappTemplateId"):
        # A queued template message must still go as its template: outside WhatsApp's
        # 24-hour window, free text is rejected.
        template = next((t for t in db.get("whatsappTemplates", []) if t.get("id") == item["whatsappTemplateId"]), None)
        template_values = item.get("templateValues") or []

    if not channel:
        item.update({"status": "Not sent — no sender connected", "sentAt": "",
                     "providerMessageId": f"SIM_{uuid.uuid4().hex[:10]}"})
        item.setdefault("deliveryEvents", []).append(
            {"status": "Not sent — no sender connected", "at": now_str,
             "details": f"Connect {channel_type or 'a channel'} in Lead Sources and add sending credentials."})
        return item

    if channel_type == "whatsapp":
        result = _send_whatsapp(channel, item.get("recipient", ""), item.get("content", ""),
                                template=template, values=template_values)
    else:
        result = _send_email(channel, item.get("recipient", ""), item.get("subject", ""), item.get("content", ""))

    if result.get("ok"):
        item.update({"status": "Sent", "sentAt": now_str,
                     "providerMessageId": result.get("providerMessageId", ""), "sentVia": channel.get("name")})
        item.setdefault("deliveryEvents", []).append({"status": "Sent", "at": now_str, "details": channel.get("name", "")})
    else:
        item.update({"status": "Failed", "sentAt": "", "error": result.get("error", "")})
        item.setdefault("deliveryEvents", []).append({"status": "Failed", "at": now_str, "details": result.get("error", "")})
    return item


# ─── WhatsApp template registration with Meta ───────────────────────
# Meta must approve any message sent outside the 24-hour reply window. Templates are
# written here with readable {{name}} placeholders, converted to the positional {{1}}
# form Meta requires, submitted for approval, and their status polled back.

WHATSAPP_LANGUAGES = ["en_US", "en_GB", "en", "hi", "mr", "gu", "ta", "te", "kn", "bn", "pa"]


def _within_service_window(lead: Dict[str, Any]) -> bool:
    """True while Meta still allows a free-form reply — 24h from the client's last message."""
    last = lead.get("lastWhatsAppInboundAt")
    if not last:
        return False
    try:
        moment = datetime.strptime(str(last).replace("Z", "").split(".")[0], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return False
    return (datetime.utcnow() - moment).total_seconds() < 24 * 3600

TEMPLATE_TOKENS = ["name", "firstName", "product", "city", "premium", "expiryDate", "daysRemaining",
                   "nextAction", "nextActionDate", "policyNumber", "assignedTo"]
# Still filled so templates written for the earlier commercial model keep working; no longer offered.
_LEGACY_TEMPLATE_TOKENS = ["organization", "policyType"]

def _render_template(text: str, lead: Dict[str, Any]) -> str:
    """Fill {{name}}-style placeholders from the client's record."""
    rendered = text or ""
    for token in TEMPLATE_TOKENS + _LEGACY_TEMPLATE_TOKENS:
        value = lead.get(token)
        rendered = rendered.replace("{{" + token + "}}", "" if value is None else str(value))
    return rendered


def _quiet_hours(db: Dict[str, Any]) -> tuple:
    hours = db.get("settings", {}).get("automation", {}).get("quietHours") or {}
    return hours.get("start", "21:00"), hours.get("end", "09:00")


def _next_sending_time(db: Dict[str, Any]) -> str:
    """Empty when a message may go now; otherwise, in UTC, when quiet hours end."""
    start, end = _quiet_hours(db)
    tz = _calendar_timezone(db)
    now = datetime.now(tz)
    clock = now.strftime("%H:%M")
    quiet = (start <= clock or clock < end) if start > end else (start <= clock < end)
    if not quiet:
        return ""
    hour, minute = map(int, end.split(":"))
    resume = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if resume <= now:
        resume += timedelta(days=1)
    return resume.astimezone(ZoneInfo("UTC")).replace(tzinfo=None).isoformat() + "Z"


def _compose_lead_message(db: Dict[str, Any], lead: Dict[str, Any], channel_type: str, content: str, subject: str,
                          whatsapp_template_id: str, template_id: str, send: bool = True,
                          respect_quiet_hours: bool = False, author: Optional[str] = None,
                          extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The rules every message to a customer obeys, whether a person or an automation sends it:
    consent, a number or address to send to, WhatsApp's 24-hour window and approved templates.
    An automation also respects quiet hours, queueing the message for the morning instead."""
    lead_id = lead["id"]
    channel_type = (channel_type or "").strip()
    if channel_type.lower() not in ["whatsapp", "email"]:
        raise HTTPException(status_code=422, detail="Messages can be sent by WhatsApp or Email")
    channel_type = "WhatsApp" if channel_type.lower() == "whatsapp" else "Email"
    if not _consent_allows(db, lead_id, channel_type):
        raise HTTPException(status_code=409, detail=f"{lead.get('name')} has opted out of {channel_type}")

    recipient = lead.get("mobile", "") if channel_type == "WhatsApp" else lead.get("email", "")
    if not recipient:
        raise HTTPException(status_code=422,
                            detail=f"No {'mobile number' if channel_type == 'WhatsApp' else 'email address'} on this record")

    live = {**live_expiry(lead), **(extra or {})}
    now_str = datetime.utcnow().isoformat() + "Z"
    wa_template = None
    template_values: List[str] = []
    content = content or ""

    if channel_type == "WhatsApp":
        sender = _sending_channel(db, "whatsapp")
        in_window = _within_service_window(lead)
        if whatsapp_template_id:
            wa_template = _find_record(db.get("whatsappTemplates", []), whatsapp_template_id, "WhatsApp template")
            if wa_template.get("status") != "Approved":
                raise HTTPException(status_code=409,
                                    detail=f"“{wa_template['name']}” is {wa_template['status'].lower()} — only approved templates can be sent")
            template_values = [_render_template("{{" + v + "}}", live) for v in wa_template.get("variables", [])]
            content = _render_template(wa_template.get("body", ""), live)
        elif sender and not in_window:
            # Meta will reject free-form text here, so refuse before spending the send.
            approved = [t for t in db.get("whatsappTemplates", []) if t.get("status") == "Approved"]
            raise HTTPException(status_code=409, detail=(
                f"{lead.get('name')} hasn't messaged in the last 24 hours, so WhatsApp only allows an approved template. "
                + (f"Choose one of your {len(approved)} approved template(s)." if approved
                   else "Create and get a template approved under Message Templates first.")))
    if not content.strip():
        raise HTTPException(status_code=422, detail="The message is empty")

    actor = author or current_actor("System")
    item = {"id": f"COM_{uuid.uuid4().hex[:8]}", "associatedType": "Lead", "associatedId": lead_id,
            "recipient": recipient, "channel": channel_type, "templateId": template_id or "",
            "whatsappTemplateId": whatsapp_template_id or "", "templateValues": template_values,
            "whatsappTemplateName": (wa_template or {}).get("name", ""),
            "subject": _render_template(subject or "", live),
            "content": _render_template(content, live), "direction": "Outbound",
            "status": "Queued", "providerMessageId": "", "deliveryEvents": [{"status": "Queued", "at": now_str}],
            "author": actor, "createdBy": actor, "createdAt": now_str}
    db.setdefault("communications", []).insert(0, item)

    later = _next_sending_time(db) if respect_quiet_hours else ""
    if later:
        item.update({"status": "Scheduled", "scheduledAt": later})
        item["deliveryEvents"].append({"status": "Scheduled", "at": now_str, "details": "Held until quiet hours end"})
    elif send:
        _dispatch(db, item, template=wa_template, template_values=template_values)

    db.setdefault("notes", []).insert(0, {
        "id": f"N_{uuid.uuid4().hex[:8]}", "title": f"{channel_type} message — {item['status']}",
        "associatedType": "Lead", "associatedId": lead_id, "associatedTitle": lead.get("name"),
        "category": "General Memo", "content": item["content"], "author": actor, "pinned": False, "createdAt": now_str})
    audit(db, "Message Sent To Client", "Lead", lead_id,
          {"channel": channel_type, "status": item["status"], "recipient": recipient})
    return item


def _manager_of(db: Dict[str, Any], person: Optional[str]) -> str:
    """Who an overdue follow-up escalates to: the person's manager, else the company owner."""
    user = next((u for u in db.get("users", []) if person and person in (u.get("name"), u.get("id"))), None)
    manager_ref = (user or {}).get("reportsTo")
    if manager_ref:
        manager = next((m for m in db.get("users", []) if manager_ref in (m.get("id"), m.get("name"))), None)
        return (manager or {}).get("name") or manager_ref
    owner = next((u for u in db.get("users", []) if crm_security.normalized_role(u.get("role", "")) == "admin"
                  and u.get("status", "Active") == "Active"), None)
    return (owner or {}).get("name") or "Administrator"


@app.post("/api/notifications/run-escalations")
def run_escalations():
    db = load_db()
    timezone = _calendar_timezone(db)
    now_local = datetime.now(timezone)
    today = now_local.strftime("%Y-%m-%d")
    upcoming_minutes = int(db.get("settings", {}).get("crm", {}).get("upcomingReminderMinutes") or 1440)
    existing_keys = {n.get("dedupeKey") for n in db.get("notifications", [])}
    created = []
    for renewal in db.get("renewals", []):
        if renewal.get("stage") in ["Renewed", "Lost", "Lapsed"] or not renewal.get("nextActionDate") or renewal.get("nextActionDate") >= today:
            continue
        key = f"renewal-overdue:{renewal['id']}:{renewal.get('nextActionDate')}"
        if key in existing_keys:
            continue
        item = {"id": f"NTF_{uuid.uuid4().hex[:8]}", "type": "Renewal Escalation", "severity": "High", "title": "Overdue renewal action",
                "message": f"{renewal.get('customerName')} — {renewal.get('nextAction')}", "associatedId": renewal["id"],
                "assignedTo": renewal.get("assignedTo"), "dedupeKey": key, "read": False, "createdAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("notifications", []).insert(0, item)
        created.append(item)
    # Slide 23: the renewal reminder ladder — one alert per renewal per stage (60, 30, 15 and
    # 7 days, the due date, and expiry without renewal), never repeated. A renewal opened
    # late starts at the stage it is already in rather than replaying the earlier ones.
    for renewal in db.get("renewals", []):
        if renewal.get("stage") in _CLOSED_RENEWAL:
            continue
        label = renewal_stage(_days_until(renewal.get("expiryDate") or ""), renewal.get("stage", ""))
        if not label:
            continue
        key = f"renewal-ladder:{renewal['id']}:{renewal.get('expiryDate')}:{label}"
        if key in existing_keys:
            continue
        expired = label.startswith("Expired")
        item = {"id": f"NTF_{uuid.uuid4().hex[:8]}", "type": "Renewal Reminder",
                "severity": "High" if expired or label in ("7 days", "Renewal due today") else "Medium",
                "title": f"Renewal — {label}" if not expired else "Policy expired without renewal",
                "message": f"{renewal.get('customerName')} — {renewal.get('product') or 'policy'} {renewal.get('policyNumber') or ''} expires {renewal.get('expiryDate')}".replace("  ", " "),
                "associatedId": renewal["id"], "assignedTo": renewal.get("assignedTo"),
                "escalatedTo": _manager_of(db, renewal.get("assignedTo")) if expired else None,
                "dedupeKey": key, "read": False, "createdAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("notifications", []).insert(0, item); created.append(item); existing_keys.add(key)
    # Slide 33, "Employee Target Achieved": the incentive estimate already follows every sale
    # (including any bonus for reaching target); this tells the person — once a month — that
    # they have reached 100% of their headline target. The owner sees it in the inbox too.
    month = today[:7]
    targets = _targets_for(db, month)
    if targets:
        first, last = _month_range(db, month)
        people = [p for p in _team_people(db, None) if targets.get(p)]
        rows = _measure(db, first, last, people)
        headline = _headline_measure(db)
        for person in people:
            percent = metrics.achievement(rows[person], targets[person], headline)["percent"]
            key = f"target-achieved:{person}:{month}"
            if percent is None or percent < 100 or key in existing_keys:
                continue
            label = metrics.TARGET_MEASURES.get(headline, headline)
            item = {"id": f"NTF_{uuid.uuid4().hex[:8]}", "type": "Target Achieved", "severity": "Medium",
                    "title": f"Target achieved — {person}",
                    "message": f"{person} has reached {percent:g}% of this month's {label.lower()} target. The incentive estimate is updated.",
                    "associatedId": "", "assignedTo": person, "escalatedTo": _manager_of(db, person) or None,
                    "dedupeKey": key, "read": False, "createdAt": datetime.utcnow().isoformat() + "Z"}
            db.setdefault("notifications", []).insert(0, item); created.append(item); existing_keys.add(key)
    # Slide 17: a follow-up raises one alert for the state it is in — a reminder before it
    # is due, a missed alert to the telecaller once it passes, and an overdue alert escalated
    # to their manager once it has been left for the escalation period.
    escalation_days = int(db.get("settings", {}).get("crm", {}).get("reminderEscalationDays") or 1)
    window_end = now_local + timedelta(minutes=upcoming_minutes)
    for task in db.get("tasks", []):
        if task.get("status") in ["Completed", "Archived"] or not task.get("dueDate") or task.get("calendarEventId"):
            continue
        due = _due_moment(task, timezone)
        if not due:
            continue
        if due >= now_local:
            timed = bool(task.get("dueTime"))
            if (timed and due > window_end) or (not timed and task["dueDate"] > window_end.strftime("%Y-%m-%d")):
                continue
            state = "upcoming"
        else:
            state = "overdue" if now_local - due >= timedelta(days=escalation_days) else "missed"
        key = f"task-{state}:{task['id']}:{_schedule_suffix(task)}"
        if key in existing_keys:
            continue
        escalated_to = _manager_of(db, task.get("assignedTo")) if state == "overdue" else None
        when = f"{task['dueDate']}{' ' + task['dueTime'] if task.get('dueTime') else ''}"
        kind, severity, title = {
            "upcoming": ("Follow-up Reminder", "Medium", f"Follow-up due {when}"),
            "missed": ("Missed Follow-up", "High", f"Missed follow-up — was due {when}"),
            "overdue": ("Overdue Follow-up", "High", f"Overdue follow-up — escalated to {escalated_to}"),
        }[state]
        item = {"id": f"NTF_{uuid.uuid4().hex[:8]}", "type": kind, "severity": severity, "title": title,
                "message": f"{task.get('associatedTitle', 'Customer')} — {task.get('title')}",
                "associatedId": task.get("associatedId"), "taskId": task["id"], "assignedTo": task.get("assignedTo"),
                "escalatedTo": escalated_to, "dedupeKey": key, "read": False,
                "createdAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("notifications", []).insert(0, item); created.append(item); existing_keys.add(key)

    # High-value leads: a HOT lead, or one worth more than the owner's threshold, whose
    # follow-up is due today or already late. One alert per lead per day.
    threshold = money_value(db.get("settings", {}).get("crm", {}).get("highValuePremium") or 0)
    tasks_by_id = {t.get("id"): t for t in db.get("tasks", [])}
    for lead in db.get("leads", []):
        if not is_open_lead(lead):
            continue
        task = tasks_by_id.get(lead.get("nextActionTaskId"))
        if not task or task.get("status") in ["Completed", "Archived"] or not task.get("dueDate") or task["dueDate"] > today:
            continue
        hot = (lead.get("leadPriority") or calculate_lead_priority(lead)) == "HOT"
        valuable = bool(threshold) and money_value(lead.get("premium")) >= threshold
        if not (hot or valuable):
            continue
        key = f"high-value:{lead['id']}:{today}:{_schedule_suffix(task)}"
        if key in existing_keys:
            continue
        why = "HOT lead" if hot else f"premium {lead.get('premium')}"
        item = {"id": f"NTF_{uuid.uuid4().hex[:8]}", "type": "High-Value Lead", "severity": "High",
                "title": f"High-value lead needs a call — {why}",
                "message": f"{lead.get('name')} ({lead.get('product') or 'product not set'}) — {task.get('title')} due {task['dueDate']}",
                "associatedId": lead["id"], "taskId": task["id"], "assignedTo": lead.get("assignedTo"),
                "dedupeKey": key, "read": False, "createdAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("notifications", []).insert(0, item); created.append(item); existing_keys.add(key)
    for event in db.get("calendarEvents", []):
        if event.get("status") in ["Completed", "Cancelled", "Archived"] or not event.get("date"):
            continue
        try:
            starts = datetime.fromisoformat(f"{event['date']}T{event.get('time') or '09:00'}:00").replace(tzinfo=timezone)
        except ValueError:
            continue
        minutes_until = (starts - now_local).total_seconds() / 60
        if minutes_until < -int(event.get("durationMinutes") or 30): state = "overdue"
        elif 0 <= minutes_until <= upcoming_minutes: state = "upcoming"
        else: continue
        key = f"calendar-{state}:{event['id']}:{event.get('date')}:{event.get('time','')}"
        if key in existing_keys: continue
        item = {"id":f"NTF_{uuid.uuid4().hex[:8]}", "type":"Calendar Escalation" if state == "overdue" else "Upcoming Appointment",
                "severity":"High" if state == "overdue" else "Medium",
                "title":"Missed calendar activity" if state == "overdue" else "Upcoming calendar activity",
                "message":f"{event.get('associatedTitle') or 'Calendar'} — {event.get('title')}",
                "associatedId":event.get("associatedId"), "calendarEventId":event["id"], "assignedTo":event.get("assignedTo"),
                "dedupeKey":key, "read":False, "createdAt":datetime.utcnow().isoformat()+"Z"}
        db.setdefault("notifications", []).insert(0,item); created.append(item); existing_keys.add(key)
    save_db(db)
    return {"createdCount": len(created), "notifications": created}


def process_scheduled_communications() -> Dict[str, int]:
    db = load_db(); now = datetime.utcnow().isoformat() + "Z"; sent = failed = 0
    for item in db.get("communications", []):
        if item.get("status") != "Scheduled" or not item.get("scheduledAt") or item.get("scheduledAt") > now:
            continue
        if not _consent_allows(db, item.get("associatedId", ""), item.get("channel", "")):
            item["status"] = "Cancelled — opted out"; failed += 1
        else:
            _dispatch(db, item)
            if item.get("status") == "Sent": sent += 1
            else: failed += 1
        audit(db, "Scheduled Communication Processed", "Communication", item["id"], {"status": item.get("status")})
    if sent or failed: save_db(db)
    return {"sent": sent, "failed": failed}


def run_scheduler_tick() -> Dict[str, Any]:
    return {"renewalsOpened": run_renewal_tracking(), "escalations": run_escalations(), "automations": run_time_automations(),
            "communications": process_scheduled_communications(),
            "companyId": current_company_id(), "completedAt": datetime.utcnow().isoformat() + "Z"}


@app.post("/api/admin/jobs/run")
def run_jobs_now():
    with crm_store.scheduler_lock(current_company_id()) as acquired:
        if not acquired:
            return {"status":"skipped", "reason":"Another scheduler owns this company", "companyId":current_company_id()}
        result = run_scheduler_tick(); db = load_db(); db.setdefault("settings", {}).setdefault("scheduler", {})["lastRun"] = result["completedAt"]
        audit(db, "Scheduler Run Completed", "System", "scheduler", result); save_db(db); return result


# ─── Communication Gateway: advertising & messaging lead sources ────
# Each connected channel exposes a webhook the provider posts to. Payloads differ per
# provider, so each has an extractor that flattens it to {field: value} pairs; a per-channel
# mapping then decides which CRM field each one fills. The raw payload is always retained,
# so a mapping fixed later can be replayed against events already received.


SECRET_KEYS = {"appSecret", "accessToken", "smtpPassword"}
ENCRYPTED_CREDENTIAL_KEYS = SECRET_KEYS | {"sharedSecret", "verifyToken", "googleKey", "refreshToken"}

def _credential_cipher():
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "")
    if not key:
        if os.environ.get("APP_ENV", "development").lower() == "production":
            raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is required in production")
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode("ascii"))
    except ImportError as exc:
        raise RuntimeError("Install cryptography to protect provider credentials") from exc
    except Exception as exc:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY must be a valid Fernet key") from exc


def _decrypt_credential(value: str) -> str:
    if not str(value or "").startswith("enc:v1:"): return value
    cipher = _credential_cipher()
    if not cipher: raise RuntimeError("Encrypted credentials require CREDENTIAL_ENCRYPTION_KEY")
    return cipher.decrypt(str(value)[7:].encode()).decode()


def _usable_credentials(channel: Dict[str, Any]) -> Dict[str, str]:
    return {key: (_decrypt_credential(value) if key in ENCRYPTED_CREDENTIAL_KEYS else value)
            for key, value in (channel.get("credentials") or {}).items()}


def _phone_key(value: Any) -> str:
    """Compare phone numbers by their last 10 digits.

    The same client's number arrives formatted differently everywhere — '+91 98765 43210'
    from a spreadsheet, '919876543210' from WhatsApp, '098765 43210' from a web form.
    Matching on the raw string creates a duplicate record for a client you already have.
    """
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits

def _same_phone(a: Any, b: Any) -> bool:
    key_a, key_b = _phone_key(a), _phone_key(b)
    return bool(key_a) and key_a == key_b


# ─── Spreadsheet Import: analyse → map → commit ─────────────────────
# A broker's book arrives as whatever columns their old spreadsheet happened to use.
# Rather than demand a fixed column order, the file is parsed, columns are matched to
# CRM fields, and anything left over is kept on the lead as a custom field so that an
# import never silently discards a column the client cared about.

IMPORT_FIELDS = [
    {"field": "name", "label": "Client name", "required": True,
     "aliases": ["name", "client", "client name", "customer", "customer name", "contact", "contact name", "full name", "lead name", "insured", "insured name", "party"]},
    {"field": "organization", "label": "Organization", "required": False,
     "aliases": ["organization", "organisation", "company", "company name", "firm", "business", "account", "corporate", "entity"]},
    {"field": "mobile", "label": "Mobile", "required": False,
     "aliases": ["mobile", "mobile no", "mobile number", "phone", "phone no", "phone number", "contact number", "contact no", "cell", "cellphone", "telephone", "whatsapp"]},
    {"field": "email", "label": "Email", "required": False,
     "aliases": ["email", "e-mail", "email id", "email address", "mail", "mail id"]},
    {"field": "policyType", "label": "Policy category", "required": False,
     "aliases": ["policy type", "policy category", "product", "product type", "cover", "coverage", "insurance type", "lob", "line of business", "class"]},
    {"field": "policyNumber", "label": "Policy number", "required": False,
     "aliases": ["policy number", "policy no", "policy #", "policy", "certificate", "certificate no", "cover note"]},
    {"field": "premium", "label": "Premium", "required": False,
     "aliases": ["premium", "annual premium", "gross premium", "net premium", "amount", "value", "premium amount", "sum"]},
    {"field": "expiryDate", "label": "Renewal / expiry date", "required": False,
     "aliases": ["expiry", "expiry date", "expiration", "expiration date", "renewal", "renewal date", "renewal due", "end date", "valid till", "valid upto", "due date", "policy end"]},
    {"field": "startDate", "label": "Policy start date", "required": False,
     "aliases": ["start date", "inception", "inception date", "policy start", "effective date", "valid from"]},
    {"field": "sumInsured", "label": "Sum insured", "required": False,
     "aliases": ["sum insured", "sum assured", "si", "coverage amount", "insured value", "idv"]},
    {"field": "insurer", "label": "Insurer", "required": False,
     "aliases": ["insurer", "insurance company", "underwriter", "carrier", "company insurer"]},
    {"field": "status", "label": "Pipeline stage", "required": False,
     "aliases": ["status", "stage", "pipeline", "lead status", "pipeline stage"]},
    {"field": "assignedTo", "label": "Owner / broker", "required": False,
     "aliases": ["owner", "assigned", "assigned to", "broker", "agent", "executive", "rm", "relationship manager", "handler", "servicing agent"]},
    {"field": "territory", "label": "Territory", "required": False,
     "aliases": ["territory", "region", "zone", "location", "city", "branch", "state"]},
    {"field": "industry", "label": "Industry", "required": False,
     "aliases": ["industry", "sector", "trade", "occupation", "nature of business"]},
    {"field": "companyDescription", "label": "Notes", "required": False,
     "aliases": ["notes", "note", "remarks", "comment", "comments", "description", "details"]},
]

IMPORT_FIELD_LOOKUP = {f["field"]: f for f in IMPORT_FIELDS}
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d",
                "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%b-%y", "%m/%d/%y", "%d/%m/%y"]


def _parse_flexible_date(value: Any) -> Optional[str]:
    """Accept the date formats a real spreadsheet actually contains; return ISO or None."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    text = text.split(" 00:00:00")[0].strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ─── Who may see which records ──────────────────────────────────────
# Roles already decide who may change things. This decides who may SEE things.
# Administrators see the whole book. Managers see themselves plus everyone reporting to
# them. Everyone else sees only what is assigned to them. The blueprint treats
# assigned-only visibility as a company policy, so it is a setting rather than a constant.

def _visibility_policy(db: Dict[str, Any]) -> bool:
    access = (db.get("settings", {}) or {}).get("access", {}) or {}
    return bool(access.get("assignedOnlyVisibility", True))

def _team_of(db: Dict[str, Any], user_name: str) -> set:
    """A manager's own name plus everyone beneath them in the reporting tree."""
    users = db.get("users", [])
    by_manager: Dict[str, List[Dict[str, Any]]] = {}
    for user in users:
        by_manager.setdefault(user.get("reportsTo") or "", []).append(user)
    start = next((u for u in users if u.get("name") == user_name), None)
    if not start:
        return {user_name}
    names, queue, guard = {user_name}, [start.get("id")], 0
    while queue and guard < 500:
        guard += 1
        current = queue.pop()
        for report in by_manager.get(current, []):
            if report.get("name") not in names:
                names.add(report.get("name"))
                queue.append(report.get("id"))
    return names

def visible_owners(db: Dict[str, Any]) -> Optional[set]:
    """None means 'everything'. Otherwise the set of owner names this user may see."""
    if AUTH_DISABLED:
        return None
    session = crm_security.current_user()
    if not session:
        return None
    role = crm_security.normalized_role(session.get("role", ""))
    if role in {"admin", "readonly"}:          # auditors read the book without changing it
        return None
    if not _visibility_policy(db):
        return None
    name = session.get("name", "")
    return _team_of(db, name) if role == "manager" else {name}

def _owned_by(record: Dict[str, Any], owners: Optional[set]) -> bool:
    if owners is None:
        return True
    return record.get("assignedTo") in owners

def scoped(records: List[Dict[str, Any]], owners: Optional[set]) -> List[Dict[str, Any]]:
    if owners is None:
        return records
    return [r for r in records if isinstance(r, dict) and _owned_by(r, owners)]

def require_visible(record: Dict[str, Any], owners: Optional[set], label: str = "Record"):
    """Direct record access must respect the same boundary as the lists."""
    if not _owned_by(record, owners):
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return record


# Records that carry an owner of their own. Anything else — a note, a message, a
# document, a quotation — is visible exactly when the record it belongs to is.
_OWNED_COLLECTIONS = ("leads", "customers", "policies", "renewals", "deals", "tasks", "calendarEvents",
                      "serviceRequests", "quotations")
_PARENT_KEYS = ("associatedId", "leadId", "customerId", "policyId", "renewalId", "dealId")


def visible_ids(db: Dict[str, Any], owners: Optional[set]) -> Optional[set]:
    """Ids of every owned record this user may see. None means the whole book."""
    if owners is None:
        return None
    return {r["id"] for c in _OWNED_COLLECTIONS for r in db.get(c, [])
            if isinstance(r, dict) and r.get("id") and _owned_by(r, owners)}


def child_visible(record: Dict[str, Any], ids: Optional[set], owners: Optional[set]) -> bool:
    if ids is None:
        return True
    if record.get("assignedTo") and _owned_by(record, owners):
        return True
    if any(record.get(key) and record.get(key) in ids for key in _PARENT_KEYS):
        return True
    # A note or message attached to nothing belongs to whoever wrote it.
    parentless = not any(record.get(key) for key in _PARENT_KEYS)
    return parentless and (record.get("author") or record.get("createdBy")) in owners


def require_child_visible(db: Dict[str, Any], record: Dict[str, Any], label: str):
    owners = visible_owners(db)
    if not child_visible(record, visible_ids(db, owners), owners):
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return record


def _visible_org_names(db: Dict[str, Any], owners: Optional[set]) -> Optional[set]:
    if owners is None:
        return None
    return {(r.get("organization") or "").strip().lower() for c in ("leads", "customers", "deals")
            for r in db.get(c, []) if _owned_by(r, owners) and r.get("organization")}


# Placeholder organisations shared by every personal enquiry. Matching on them would
# make every telecaller's contacts visible to every other telecaller.
_SHARED_ORGANIZATIONS = {"", "private individual", "individual", "n/a", "na", "none"}


def contact_visible(contact: Dict[str, Any], ids: Optional[set], orgs: Optional[set]) -> bool:
    if ids is None:
        return True
    if contact.get("leadId") or contact.get("customerId"):
        return contact.get("leadId") in ids or contact.get("customerId") in ids
    org = (contact.get("organization") or "").strip().lower()
    return org not in _SHARED_ORGANIZATIONS and org in orgs

# ─── Automation (client blueprint, slide 33) ────────────────────────
# The engine, its guardrails and its vocabulary live in crm_automation.py. This section
# connects it to the CRM: what each action does, where each timed trigger looks and how
# changes are noticed. Its HTTP API is crm_routes/automation.py. Assignment rules are
# automation rules whose trigger is "a new lead arrives" and whose action is "assign";
# the older /api/assignment-rules endpoints remain as a view over them.


def _automation_field(record: Dict[str, Any], field: str) -> Any:
    if field == "daysToExpiry":
        return _days_until(record.get("expiryDate") or "") if record.get("expiryDate") else ""
    if field == "premium":
        raw = record.get("premium")
        return money_value(raw) if raw not in (None, "") else ""
    if field == "product":
        return record.get("product") or record.get("policyType") or ""
    return record.get(field, "")


automation.configure(_automation_field, money_value)


def _condition_matches(lead: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    return automation.condition_matches(lead, condition)


def _available_people(db: Dict[str, Any]) -> set:
    """Active people not marked away (slide 12, employee availability)."""
    return {u.get("name") for u in db.get("users", []) if u.get("status", "Active") == "Active" and u.get("available", True)}


def _pick_assignee(db: Dict[str, Any], params: Dict[str, Any], lead: Optional[Dict[str, Any]] = None) -> str:
    """Choose among the rule's people who are active and available; never a deactivated or
    away person. With nobody available the rule does not match, and the next one is tried."""
    available = _available_people(db)
    people = [n for n in (params.get("assignees") or []) if n in available]
    if not people:
        return ""
    method = params.get("method", "least_busy")
    if method == "first":
        return people[0]
    if method == "rotate":
        last = params.get("lastAssignedTo", "")
        order = params.get("assignees") or people
        start = order.index(last) + 1 if last in order else 0
        chosen = next(n for n in order[start:] + order[:start] if n in people)   # skip whoever is away
        params["lastAssignedTo"] = chosen
        return chosen
    open_count = lambda n: len([l for l in db.get("leads", []) if is_open_lead(l) and l.get("assignedTo") == n])
    hot = bool(lead) and ((lead.get("leadPriority") or calculate_lead_priority(lead)).upper() == "HOT")
    if method == "least_busy" or (method == "priority" and not hot):
        return min(people, key=open_count)
    tz = _calendar_timezone(db)
    month = _company_date(db).strftime("%Y-%m")
    received = lambda n: len([l for l in db.get("leads", []) if l.get("assignedTo") == n
                              and metrics.local_day(l.get("leadDate"), tz).startswith(month)])
    if method == "equal":
        return min(people, key=lambda n: (received(n), open_count(n)))
    today = _company_date(db)
    rows = _measure(db, (today - timedelta(days=30)).isoformat(), today.isoformat(), people)
    conversion = lambda n: rows[n]["conversionRate"] or 0
    if method == "priority":                          # a HOT lead
        return max(people, key=lambda n: (conversion(n), -open_count(n)))
    # performance: leads shared in proportion to conversion. Everyone keeps a share (10 points
    # on top of their rate), so a newcomer with no sales yet still receives leads.
    return min(people, key=lambda n: ((received(n) + 1) / (conversion(n) + 10), open_count(n)))


last_rule_match_var: contextvars.ContextVar = contextvars.ContextVar("last_rule_match_var", default={"name": ""})
advisor_error_var: contextvars.ContextVar = contextvars.ContextVar("advisor_error_var", default=None)
_last_rule_match: Dict[str, str] = {"name": ""}


def apply_assignment_rules(db: Dict[str, Any], lead: Dict[str, Any]) -> str:
    """Decide the owner for a new lead from the first matching new-lead rule that assigns.

    The rule's other actions run once the lead is saved, with every other matching rule.
    The matched rule name is parked in _last_rule_match so the caller can stamp it.
    """
    _last_rule_match["name"] = ""
    last_rule_match_var.set({"name": ""})
    owner, rule = automation.choose_assignee(db, lead, _pick_assignee)
    if not rule:
        return ""
    lead["assignedByRule"] = rule.get("name", "")
    _last_rule_match["name"] = rule.get("name", "")
    last_rule_match_var.set({"name": rule.get("name", "")})
    return owner


def _rule_from_legacy(item: Dict[str, Any], order: int) -> Dict[str, Any]:
    """An assignment rule in the older shape, expressed as an automation rule."""
    actions = [{"type": "assign", "params": {"assignees": list(item.get("assignees") or []),
                                             "method": item.get("method") or "least_busy",
                                             "lastAssignedTo": item.get("lastAssignedTo", "")}}]
    if item.get("createTask"):
        actions.append({"type": "create_task", "params": {"title": item.get("taskTitle") or "Follow up on new enquiry",
                                                          "dueInDays": int(item.get("taskDueInDays") or 1), "priority": "High"}})
    now = datetime.utcnow().isoformat() + "Z"
    return {"id": item.get("id") or f"AUTO_{uuid.uuid4().hex[:8]}", "name": item.get("name", "Assignment rule"),
            "enabled": item.get("enabled", True), "order": order, "trigger": {"type": "lead.created", "params": {}},
            "conditions": list(item.get("conditions") or []), "actions": actions,
            "limits": {"daysOfWeek": list(item.get("days") or []), "maxPerHour": automation.DEFAULT_MAX_PER_HOUR},
            "recipe": item.get("recipe", ""), "runCount": item.get("matchCount", 0), "lastRunAt": item.get("lastMatchedAt", ""),
            "matchCount": item.get("matchCount", 0), "lastMatchedAt": item.get("lastMatchedAt", ""),
            "createdBy": item.get("createdBy", "System"), "createdAt": item.get("createdAt") or now, "updatedAt": now}


def _migrate_assignment_rules(db: Dict[str, Any]):
    """Once per company: older assignment rules become automation rules, unchanged in effect.
    The originals are kept under assignmentRulesMigrated."""
    state = db.setdefault("settings", {}).setdefault("automation", {})
    db.setdefault("automationRules", [])
    if state.get("assignmentRulesMigrated") or not db.get("assignmentRules"):
        state["assignmentRulesMigrated"] = True
        return
    start = len(db["automationRules"])
    for i, item in enumerate(db["assignmentRules"]):
        db["automationRules"].append(_rule_from_legacy(item, start + i))
    db["assignmentRulesMigrated"] = db.pop("assignmentRules")
    state["assignmentRulesMigrated"] = True


# ── Noticing changes ──
def _record_status(lead: Dict[str, Any], status: str, when: Optional[str] = None, by: Optional[str] = None):
    """Keep a lead's status history, so reports can say when it reached each stage (slide 31)."""
    history = lead.setdefault("statusHistory", [])
    if history and history[-1].get("status") == status:
        return
    history.append({"status": status, "at": when or datetime.utcnow().isoformat() + "Z",
                    "by": by or current_actor("System"), "owner": lead.get("assignedTo", "")})


def _reconstruct_status_history(db: Dict[str, Any]):
    """For leads saved before history was kept: rebuild it from the audit ledger's stage changes.
    Entries are marked reconstructed; a lead with no recorded changes gets only its current status."""
    changes: Dict[str, List[Dict[str, Any]]] = {}
    for entry in db.get("auditLogs", []):
        if entry.get("action") == "Lead Stage Changed" and entry.get("entityId"):
            details = entry.get("details") or {}
            changes.setdefault(entry["entityId"], []).append({"at": entry.get("createdAt", ""), "by": entry.get("actor", ""),
                                                              "from": canonical_status(details.get("from")),
                                                              "to": canonical_status(details.get("to"))})
    for lead in db.get("leads", []):
        if not isinstance(lead, dict) or "statusHistory" in lead:
            continue
        steps = sorted(changes.get(lead.get("id"), []), key=lambda c: c["at"])
        start = steps[0]["from"] if steps else canonical_status(lead.get("status"))
        history = [{"status": start, "at": lead.get("leadDate") or "", "by": "", "owner": lead.get("assignedTo", ""),
                    "reconstructed": True}]
        for step in steps:
            if step["to"] and step["to"] != history[-1]["status"]:
                history.append({"status": step["to"], "at": step["at"], "by": step["by"],
                                "owner": lead.get("assignedTo", ""), "reconstructed": True})
        if history[-1]["status"] != canonical_status(lead.get("status")):
            history.append({"status": canonical_status(lead.get("status")), "at": "", "by": "",
                            "owner": lead.get("assignedTo", ""), "reconstructed": True})
        lead["statusHistory"] = history


def _automation_events(db: Dict[str, Any], backfill: bool = False) -> List[tuple]:
    """Compare each record with what automation last saw and return the events to fire.

    Detecting at save time means every way a record changes — the lead form, an import,
    an advertising webhook, a bulk edit — triggers automations the same way. On load,
    existing records are marked without firing, so switching this on replays nothing.
    """
    events = []
    rules_by_name = {r.get("name"): r for r in db.get("automationRules", [])}
    for lead in db.get("leads", []):
        if not isinstance(lead, dict):
            continue
        owner, status = lead.get("assignedTo") or "", canonical_status(lead.get("status"))
        seen = lead.get("automationState")
        if seen is None:
            lead["automationState"] = {"owner": owner, "status": status, "seq": 0}
            if not backfill:
                _record_status(lead, status, lead.get("leadDate") or None)
                assigning = rules_by_name.get(lead.get("assignedByRule")) if lead.get("assignedByRule") else None
                ctx = {"occurrence": "created"}
                if assigning:
                    ctx["assignment"] = {"ruleId": assigning["id"], "owner": owner}
                events.append(("lead.created", lead, ctx))
                if owner and owner != "Unassigned":
                    events.append(("lead.assigned", lead, {"occurrence": f"assigned:{owner}:0"}))
            continue
        if owner != seen.get("owner"):
            seen["seq"] = seen.get("seq", 0) + 1
            seen["owner"] = owner
            if owner and owner != "Unassigned" and not backfill:
                events.append(("lead.assigned", lead, {"occurrence": f"assigned:{owner}:{seen['seq']}"}))
        if status != seen.get("status"):
            seen["seq"] = seen.get("seq", 0) + 1
            previous, seen["status"] = seen.get("status"), status
            if not backfill:
                _record_status(lead, status)
                events.append(("lead.status_changed", lead, {"to": status, "from": previous,
                                                             "occurrence": f"status:{status}:{seen['seq']}"}))
    for quote in db.get("quotations", []):
        seen = quote.setdefault("automationState", {"status": quote.get("status", "")}) if backfill else quote.get("automationState")
        if seen is None:
            quote["automationState"] = {"status": quote.get("status", "")}
        elif quote.get("status", "") != seen.get("status"):
            seen["status"] = quote.get("status", "")
            if not backfill:
                events.append(("quotation.status_changed", quote, {"to": seen["status"], "occurrence": f"status:{seen['status']}:{quote.get('updatedAt', '')}"}))
    for policy in db.get("policies", []):
        issued = policy.get("issuanceStatus") == "Issued"
        seen = policy.get("automationState")
        if seen is None or backfill:
            policy["automationState"] = {"issued": issued if seen is None else seen.get("issued", issued)}
            if seen is not None or backfill:
                policy["automationState"]["issued"] = issued
            continue
        if issued and not seen.get("issued"):
            seen["issued"] = True
            events.append(("policy.issued", policy, {"occurrence": f"issued:{policy.get('issuedAt', '')}"}))
    for document in db.get("documents", []):
        if document.get("automationState") is None:
            document["automationState"] = {"seen": True}
            if not backfill:
                events.append(("document.uploaded", document, {"occurrence": "uploaded"}))
    for task in db.get("tasks", []):
        done = task.get("status") == "Completed"
        seen = task.get("automationState")
        if seen is None or backfill:
            task["automationState"] = {"done": done}
            continue
        if done and not seen.get("done"):
            events.append(("task.completed", task, {"occurrence": f"done:{task.get('completedAt', '')}"}))
        seen["done"] = done
    return events


def _fire_automation_events(db: Dict[str, Any]):
    for event, record, ctx in _automation_events(db):
        automation.fire(db, event, record, ctx)


# ── What each action does ──
def _lead_for(db: Dict[str, Any], record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The lead a record belongs to: itself, or the lead behind a policy, quote, task or document."""
    if "firstName" in record and "mobile" in record:
        return record
    lead_id = record.get("leadId") or (record.get("associatedId") if record.get("associatedType") == "Lead" else "")
    if not lead_id and record.get("customerId"):
        customer = next((c for c in db.get("customers", []) if c.get("id") == record["customerId"]), None)
        lead_id = (customer or {}).get("sourceLeadId", "")
    if not lead_id and record.get("associatedType") == "Policy":
        policy = next((p for p in db.get("policies", []) if p.get("id") == record.get("associatedId")), None)
        return _lead_for(db, policy) if policy else None
    return next((l for l in db.get("leads", []) if l.get("id") == lead_id), None) if lead_id else None


def _automation_context(db: Dict[str, Any], record: Dict[str, Any]) -> Dict[str, Any]:
    """What {{placeholders}} in an automation's text are filled from."""
    lead = _lead_for(db, record) or {}
    merged = {**live_expiry(lead), **record} if lead is not record else live_expiry(record)
    merged.setdefault("firstName", (merged.get("name") or merged.get("customerName") or "").split(" ")[0])
    merged.setdefault("customerName", merged.get("name", ""))
    if lead:
        merged["missingDocuments"] = ", ".join(document_status(db, lead)["missing"]) or "nothing further"
    return merged


def _company_today(db: Dict[str, Any], offset_days: int = 0) -> str:
    return (datetime.now(_calendar_timezone(db)) + timedelta(days=offset_days)).strftime("%Y-%m-%d")


def _auto_create_task(db, rule, params, record, ctx):
    lead = _lead_for(db, record)
    target = lead or record
    owner = record.get("assignedTo") or (lead or {}).get("assignedTo") or ""
    title = _render_template(params.get("title", ""), _automation_context(db, record))
    task = {"id": f"T_{uuid.uuid4().hex[:8]}", "title": title,
            "associatedType": "Lead" if lead else record.get("associatedType", "Lead"),
            "associatedId": target.get("id", ""), "associatedTitle": target.get("name") or target.get("customerName", ""),
            "priority": params.get("priority") or "Medium", "dueDate": _company_today(db, int(params.get("dueInDays") or 0)),
            "dueTime": params.get("dueTime", ""), "status": "Pending", "assignedTo": owner,
            "activityType": params.get("activityType") or "Follow-up", "createdByRule": rule.get("name", ""),
            "author": f"Automation: {rule.get('name', '')}"}
    db.setdefault("tasks", []).insert(0, task)
    return f"Follow-up “{title}” due {task['dueDate']} for {owner or 'nobody'}"


def _auto_notify(db, rule, params, record, ctx):
    lead = _lead_for(db, record)
    assignee = record.get("assignedTo") or (lead or {}).get("assignedTo") or ""
    target = {"assignee": assignee, "manager": _manager_of(db, assignee),
              "owner": _manager_of(db, None)}[params.get("to", "assignee")]
    if not target:
        raise automation.ActionBlocked("Nobody to notify: the record has no telecaller")
    message = _render_template(params.get("message", ""), _automation_context(db, record))
    db.setdefault("notifications", []).insert(0, {
        "id": f"NTF_{uuid.uuid4().hex[:8]}", "type": "Automation", "severity": params.get("severity") or "Medium",
        "title": rule.get("name", "Automation"), "message": message,
        "associatedId": (lead or record).get("id", ""), "assignedTo": target,
        "dedupeKey": f"automation:{rule['id']}:{record.get('id', '')}:{uuid.uuid4().hex[:6]}",
        "read": False, "createdAt": datetime.utcnow().isoformat() + "Z"})
    return f"Notified {target}"


def _auto_send_message(db, rule, params, record, ctx):
    lead = _lead_for(db, record)
    if not lead:
        raise automation.ActionBlocked("No customer record to message")
    try:
        item = _compose_lead_message(db, lead, params.get("channel", "WhatsApp"), params.get("text", ""),
                                     params.get("subject", ""), params.get("whatsappTemplateId", ""), "",
                                     send=True, respect_quiet_hours=True, author=f"Automation: {rule.get('name', '')}",
                                     extra=_automation_context(db, record))
    except HTTPException as refused:
        raise automation.ActionBlocked(str(refused.detail))
    return f"{item['channel']} to {item['recipient']} — {item['status']}"


def _auto_set_status(db, rule, params, record, ctx):
    lead = _lead_for(db, record)
    if not lead:
        raise automation.ActionBlocked("No lead to update")
    status = canonical_status(params.get("status"))
    if canonical_status(lead.get("status")) == status:
        raise automation.ActionBlocked(f"Already {status}")
    next_action = params.get("nextAction") or ""
    due = _company_today(db, int(params.get("dueInDays") or 0))
    try:
        _checked_status_change(lead, status, params.get("reason", ""), next_action if status not in NO_NEXT_ACTION else None,
                               due if status not in NO_NEXT_ACTION else None)
    except HTTPException as refused:
        raise automation.ActionBlocked(str(refused.detail))
    previous = canonical_status(lead.get("status"))
    lead["status"] = status
    if params.get("reason"):
        lead["lostReason"] = params["reason"]
    if status in NO_NEXT_ACTION:
        _close_lead_work(db, lead)
    else:
        old = next((t for t in db.get("tasks", []) if t.get("id") == lead.get("nextActionTaskId")), None)
        if old and old.get("status") not in ("Completed", "Archived"):
            old.update({"status": "Completed", "completedAt": datetime.utcnow().isoformat() + "Z"})
        task = {"id": f"T_{uuid.uuid4().hex[:8]}", "title": next_action, "associatedType": "Lead",
                "associatedId": lead["id"], "associatedTitle": lead.get("name", ""), "priority": "Medium",
                "dueDate": due, "status": "Pending", "assignedTo": lead.get("assignedTo", ""), "activityType": "Follow-up",
                "createdByRule": rule.get("name", "")}
        db.setdefault("tasks", []).insert(0, task)
        lead.update({"nextAction": next_action, "nextActionDate": due, "nextActionTime": "",
                     "nextActionCompleted": False, "nextActionTaskId": task["id"]})
    lead["lastModified"] = datetime.utcnow().isoformat() + "Z"
    seen = lead.setdefault("automationState", {"owner": lead.get("assignedTo", ""), "status": previous, "seq": 0})
    seen["seq"] = seen.get("seq", 0) + 1
    seen["status"] = status
    _record_status(lead, status, by=f"Automation: {rule.get('name', '')}")
    automation.fire(db, "lead.status_changed", lead, {**ctx, "to": status, "from": previous,
                                                      "occurrence": f"status:{status}:{seen['seq']}"})
    return f"{previous} → {status}"


def _auto_set_priority(db, rule, params, record, ctx):
    lead = _lead_for(db, record)
    if not lead:
        raise automation.ActionBlocked("No lead to update")
    lead["leadPriority"] = params["priority"]
    lead["priority"] = params["priority"].capitalize()
    return f"Priority {params['priority']}"


def _auto_add_note(db, rule, params, record, ctx):
    target = _lead_for(db, record) or record
    text = _render_template(params.get("text", ""), _automation_context(db, record))
    db.setdefault("notes", []).insert(0, {
        "id": f"N_{uuid.uuid4().hex[:8]}", "title": rule.get("name", "Automation"), "associatedType": "Lead" if target.get("mobile") else "Policy",
        "associatedId": target.get("id", ""), "associatedTitle": target.get("name") or target.get("customerName", ""),
        "category": "Automation", "content": text, "author": f"Automation: {rule.get('name', '')}", "pinned": False,
        "createdAt": datetime.utcnow().isoformat() + "Z"})
    return "Note added"


def _auto_create_renewal(db, rule, params, record, ctx):
    if not record.get("expiryDate"):
        raise automation.ActionBlocked("The policy has no expiry date")
    if any(r.get("policyId") == record.get("id") and r.get("stage") not in ["Renewed", "Lost", "Lapsed"] for r in db.get("renewals", [])):
        raise automation.ActionBlocked("This policy already has an open renewal")
    now = datetime.utcnow().isoformat() + "Z"
    item = {"id": f"REN_{uuid.uuid4().hex[:8]}", "policyId": record["id"], "assignedTo": record.get("assignedTo", ""),
            "stage": "Upcoming", "targetPremium": money_value(record.get("premium") or 0), "nextAction": "Contact customer about renewal",
            "nextActionDate": "", "customerName": record.get("customerName"), "organization": record.get("organization"),
            "policyNumber": record.get("policyNumber"), "expiryDate": record.get("expiryDate"), "outcomeReason": "",
            "createdByRule": rule.get("name", ""), "createdAt": now, "updatedAt": now}
    db.setdefault("renewals", []).insert(0, item)
    return f"Renewal created for expiry {record.get('expiryDate')}"


def _auto_assign(db, rule, params, record, ctx):
    raise automation.ActionBlocked("Leads are assigned when they arrive")


for _type, _executor in {"assign": _auto_assign, "create_task": _auto_create_task, "notify": _auto_notify,
                         "send_message": _auto_send_message, "set_status": _auto_set_status,
                         "set_priority": _auto_set_priority, "add_note": _auto_add_note,
                         "create_renewal": _auto_create_renewal}.items():
    automation.register_action(_type, _executor)


# ── Where timed triggers look ──
def _expiring(records, params):
    horizon = int(params.get("days") or 30)
    for record in records:
        days = _days_until(record.get("expiryDate") or "") if record.get("expiryDate") else None
        if days is not None and 0 <= days <= horizon:
            yield record, f"expiry:{record['expiryDate']}"


automation.register_time_source("policy.expiring", lambda db, params, now: _expiring(
    [p for p in db.get("policies", []) if p.get("status") not in ("Cancelled", "Expired/Renewed", "Draft")], params))
automation.register_time_source("lead.expiring", lambda db, params, now: _expiring(
    [l for l in db.get("leads", []) if is_open_lead(l)], params))


def _overdue_tasks(db, params, now):
    tz = _calendar_timezone(db)
    late_by = timedelta(days=int(params.get("days") or 1))
    local_now = datetime.now(tz)
    for task in db.get("tasks", []):
        due = _due_moment(task, tz) if task.get("status") not in ("Completed", "Archived") else None
        if due and local_now - due >= late_by:
            yield task, f"overdue:{_schedule_suffix(task)}"


def _quiet_leads(db, params, now):
    """Open leads with no call, message or note for the given number of days."""
    cutoff = (datetime.utcnow() - timedelta(days=int(params.get("days") or 3))).isoformat()
    last = _last_interactions(db)
    for lead in db.get("leads", []):
        if not is_open_lead(lead):
            continue
        latest = (last.get(lead.get("id")) or {}).get("at") or lead.get("leadDate") or ""
        if latest and latest < cutoff:
            yield lead, f"quiet-since:{latest}"


automation.register_time_source("task.overdue", _overdue_tasks)
automation.register_time_source("lead.no_contact", _quiet_leads)


def run_time_automations() -> int:
    db = load_db()
    runs = automation.run_time_triggers(db)
    save_db(db)
    return len(runs)


# ─── Calendar ───────────────────────────────────────────────────────
# The calendar is a read across the CRM rather than a separate diary: tasks, scheduled
# next actions, policy renewals and booked meetings all appear on the same grid, so a
# broker's day is in one place and nothing is tracked in two systems.


CALENDAR_ENTITY_COLLECTIONS = {"Lead":"leads", "Customer":"customers", "Policy":"policies",
                               "Renewal":"renewals", "Deal":"deals", "Organization":"organizations",
                               "Contact":"contacts", "Service Request":"serviceRequests"}
APPOINTMENT_TYPES = {"Meeting", "Call", "Site visit", "Survey", "Renewal review"}

def _calendar_timezone(db: Dict[str, Any]) -> ZoneInfo:
    name = str(db.get("settings", {}).get("crm", {}).get("companyTimezone") or "Asia/Kolkata")
    try: return ZoneInfo(name)
    except ZoneInfoNotFoundError: raise HTTPException(status_code=422, detail="The configured company timezone is invalid")

def _calendar_entity(db: Dict[str, Any], entity_type: str, entity_id: str) -> tuple[Optional[Dict[str, Any]], str]:
    if not entity_id:
        return None, ""
    collection = CALENDAR_ENTITY_COLLECTIONS.get(entity_type)
    if not collection:
        raise HTTPException(status_code=422, detail="Unsupported calendar relationship type")
    record = _find_record(db.get(collection, []), entity_id, entity_type)
    label = (record.get("name") or record.get("customerName") or record.get("dealName") or
             record.get("title") or record.get("policyNumber") or record.get("requestType") or entity_id)
    organization = record.get("organization")
    return record, f"{label} ({organization})" if organization and organization not in str(label) else str(label)

def _valid_clock(value: str) -> bool:
    return not value or bool(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value))

def _calendar_conflict(db: Dict[str, Any], owner: str, event_date: str, event_time: str,
                       duration: int, exclude_id: str = "") -> Optional[Dict[str, Any]]:
    if not owner or not event_time:
        return None
    start = datetime.fromisoformat(f"{event_date}T{event_time}")
    end = start + timedelta(minutes=duration)
    for event in db.get("calendarEvents", []):
        if event.get("id") == exclude_id or event.get("status") in ["Completed", "Cancelled", "Archived"]:
            continue
        if event.get("assignedTo") != owner or not event.get("time"):
            continue
        try:
            other_start = datetime.fromisoformat(f"{event['date']}T{event['time']}")
            other_end = other_start + timedelta(minutes=int(event.get("durationMinutes") or 30))
        except (ValueError, TypeError, KeyError):
            continue  # Malformed legacy events remain available for relationship review.
        if start < other_end and other_start < end:
            return event
    return None


def _validate_appointment(db: Dict[str, Any], item: Dict[str, Any]):
    """One validation path for booking, task edits, reassignment and calendar moves."""
    if not isinstance(item.get("title"), str) or not item["title"].strip():
        raise HTTPException(status_code=422, detail="A title is required")
    if not _parse_flexible_date(item.get("date", "")) or not _valid_clock(str(item.get("time", ""))):
        raise HTTPException(status_code=422, detail="A valid date and 24-hour HH:MM time are required")
    try:
        duration = int(item.get("durationMinutes", 30))
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Duration must be a number of minutes")
    if not 5 <= duration <= 1440:
        raise HTTPException(status_code=422, detail="Duration must be between 5 and 1440 minutes")
    if item.get("type", "Meeting") not in APPOINTMENT_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported appointment type")
    if item.get("status", "Scheduled") not in {"Scheduled", "Completed", "Cancelled", "Archived"}:
        raise HTTPException(status_code=422, detail="Invalid appointment status")
    if item.get("status", "Scheduled") == "Scheduled":
        tz_str = item.get("timezone") or str(_calendar_timezone(db))
        if tz_str and item.get("date") and item.get("time"):
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(tz_str)
                dt_raw = datetime.strptime(f"{item['date']} {item['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=tz)
                back_dt = dt_raw.astimezone(zoneinfo.ZoneInfo("UTC")).astimezone(tz)
                if back_dt.strftime("%Y-%m-%d %H:%M") != f"{item['date']} {item['time']}":
                    raise HTTPException(status_code=409, detail="Scheduled appointment falls within nonexistent daylight saving transition gap")
            except HTTPException:
                raise
            except Exception:
                pass
        conflict = _calendar_conflict(db, item.get("assignedTo", ""), item["date"], item.get("time", ""), duration, item.get("id", ""))
        if conflict:
            raise HTTPException(status_code=409, detail=f"Calendar conflict with '{conflict.get('title')}'")

def repair_calendar_model(db: Dict[str, Any]) -> Dict[str, int]:
    """Backfill canonical task/event links without deleting calendar history."""
    counts = {"leadTasksLinked":0, "eventTasksLinked":0, "eventTasksCreated":0,
              "eventTypesNormalized":0, "orphansFlagged":0}
    tasks = {task.get("id"):task for task in db.get("tasks", [])}
    for lead in db.get("leads", []):
        if lead.get("nextActionTaskId") in tasks:
            continue
        matches = [task for task in tasks.values() if task.get("associatedType") == "Lead" and task.get("associatedId") == lead.get("id")
                   and task.get("status") not in ["Completed", "Archived"] and
                   task.get("title") == lead.get("nextAction") and task.get("dueDate") == lead.get("nextActionDate")]
        if len(matches) == 1:
            lead["nextActionTaskId"] = matches[0]["id"]; counts["leadTasksLinked"] += 1
    for event in db.get("calendarEvents", []):
        if event.get("type") in APPOINTMENT_TYPES and event.get("category") != "Appointment":
            event["category"] = "Appointment"; counts["eventTypesNormalized"] += 1
        task = tasks.get(event.get("taskId"))
        if not task and event.get("status", "Scheduled") not in ["Completed", "Cancelled", "Archived"]:
            task = {"id":f"T_{uuid.uuid4().hex[:8]}", "title":event.get("title", "Calendar appointment"),
                    "associatedType":event.get("associatedType", "Lead"), "associatedId":event.get("associatedId", ""),
                    "associatedTitle":event.get("associatedTitle", ""), "priority":"Medium", "dueDate":event.get("date", ""),
                    "status":"Pending", "assignedTo":event.get("assignedTo", ""), "activityType":event.get("type", "Meeting"),
                    "calendarEventId":event.get("id")}
            db.setdefault("tasks", []).insert(0, task); tasks[task["id"]] = task; event["taskId"] = task["id"]
            counts["eventTasksCreated"] += 1
        if task and task.get("calendarEventId") != event.get("id"):
            task["calendarEventId"] = event["id"]; counts["eventTasksLinked"] += 1
        if event.get("associatedId"):
            collection = CALENDAR_ENTITY_COLLECTIONS.get(event.get("associatedType", "Lead"))
            if not collection or not any(r.get("id") == event.get("associatedId") for r in db.get(collection, [])):
                event["relationshipStatus"] = "Needs Review"; counts["orphansFlagged"] += 1
    db.setdefault("settings", {}).setdefault("migrations", {})["calendarRelationshipVersion"] = 2
    return counts


def _lead_label(db: Dict[str, Any], lead_id: str) -> str:
    lead = next((l for l in db.get("leads", []) if l.get("id") == lead_id), None)
    return f"{lead.get('name')} ({lead.get('organization') or 'Individual'})" if lead else ""


# ─── Documents, reporting, data quality and recovery ───


def _company_data_root(base: str) -> str:
    company_id = current_company_id()
    if company_id == "default": return base
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", company_id)
    return os.path.join(base, safe_id)


def _checked_document_type(value: Optional[str]) -> str:
    """The client's document types. Older labels such as "KYC" are understood and mapped."""
    text = (value or "").strip()
    if not text:
        return "Other"
    match = next((t for t in DOCUMENT_TYPES if t.lower() == text.lower()), None) or _LEGACY_DOCUMENT_TYPES.get(text.lower())
    if not match:
        raise HTTPException(status_code=422, detail=f"Document type must be one of: {', '.join(DOCUMENT_TYPES)}")
    return match


def document_status(db: Dict[str, Any], lead: Dict[str, Any]) -> Dict[str, Any]:
    """What the customer still has to send for their product, counting documents held against
    the lead and, once converted, against their customer record and policy."""
    required = (db.get("settings", {}).get("crm", {}).get("requiredDocuments") or DEFAULT_REQUIRED_DOCUMENTS)
    product = lead.get("product") or lead.get("policyType") or ""
    wanted = next((docs for name, docs in required.items() if name.lower() == product.lower()), [])
    holders = {lead.get("id"), lead.get("convertedCustomerId"), lead.get("convertedPolicyId")} - {None, ""}
    held = [d for d in db.get("documents", []) if d.get("associatedId") in holders and d.get("status") == "Active"]
    items = []
    for doc_type in wanted:
        matches = sorted((d for d in held if _checked_document_type_quiet(d.get("category")) == doc_type),
                         key=lambda d: d.get("createdAt", ""), reverse=True)
        latest = matches[0] if matches else None
        state = "missing" if not latest else (latest.get("verification") or "Pending").lower()
        items.append({"type": doc_type, "state": state, "documentId": (latest or {}).get("id", ""),
                      "note": (latest or {}).get("verificationNote", "")})
    outstanding = [i["type"] for i in items if i["state"] in ("missing", "rejected")]
    return {"product": product, "required": items, "missing": outstanding,
            "complete": bool(items) and not outstanding}


def _checked_document_type_quiet(value: Optional[str]) -> str:
    try:
        return _checked_document_type(value)
    except HTTPException:
        return "Other"


def _create_backup(reason: str = "Manual"):
    backup_root = _company_data_root(BACKUP_ROOT)
    os.makedirs(backup_root, exist_ok=True); stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S%fZ"); name = f"crm-{stamp}.json"; path = os.path.join(backup_root, name)
    current_state = load_db()
    if crm_store.configured():
        with open(path, "w", encoding="utf-8") as handle: json.dump(current_state, handle, ensure_ascii=False, indent=2)
    else:
        shutil.copy2(_tenant_db_path(), path)
    with open(path, "rb") as handle: checksum = hashlib.sha256(handle.read()).hexdigest()
    return {"name":name,"size":os.path.getsize(path),"checksum":checksum,"reason":reason,"createdAt":datetime.utcnow().isoformat()+"Z"}

# ─── Data export (client blueprint, slides 41–42) ───


_reminder_scheduler_task = None


def run_jobs_for_all_companies():
    """Run due work for every company, as the separate worker process does.

    The embedded loop used to call run_jobs_now() outside any request, which resolves to the
    demo workspace, so reminders and escalations never ran for a real company. Failures were
    swallowed silently; they are now logged and recorded where Settings can show them.
    """
    for company_id in crm_security.company_ids():
        token = company_context.set(company_id)
        try:
            run_jobs_now()
        except Exception as exc:
            print(f"scheduler company={company_id} failed: {exc!r}", flush=True)
            try:
                db = load_db()
                db.setdefault("settings", {}).setdefault("scheduler", {}).update(
                    {"lastError": f"{type(exc).__name__}: {exc}", "lastErrorAt": datetime.utcnow().isoformat() + "Z"})
                save_db(db)
            except Exception as inner:
                print(f"scheduler company={company_id} could not record its failure: {inner!r}", flush=True)
        finally:
            company_context.reset(token)


@app.on_event("startup")
async def start_reminder_scheduler():
    global _reminder_scheduler_task
    if os.environ.get("ENABLE_REMINDER_SCHEDULER", "1") != "1" or _reminder_scheduler_task:
        return
    async def loop():
        while True:
            await asyncio.sleep(300)
            await asyncio.to_thread(run_jobs_for_all_companies)
    _reminder_scheduler_task = asyncio.create_task(loop())

@app.on_event("shutdown")
async def stop_reminder_scheduler():
    global _reminder_scheduler_task
    if _reminder_scheduler_task:
        _reminder_scheduler_task.cancel(); _reminder_scheduler_task = None

# ─── Areas moved to their own modules (docs/AI_CUSTOMIZATION_PLAN.md, phase 0) ───
# Imported last: each module reaches this one's helpers at call time.
from crm_routes import backups as _backups_routes  # noqa: E402
from crm_routes import admin as _admin_routes  # noqa: E402
from crm_routes import deals_and_contacts as _deals_and_contacts_routes  # noqa: E402
from crm_routes import tasks as _tasks_routes  # noqa: E402
from crm_routes import notes as _notes_routes  # noqa: E402
from crm_routes import leads as _leads_routes  # noqa: E402
from crm_routes import settings as _settings_routes  # noqa: E402
from crm_routes import team as _team_routes  # noqa: E402
from crm_routes import automation as _automation_routes  # noqa: E402
from crm_routes import calendar as _calendar_routes  # noqa: E402
from crm_routes import quotations as _quotations_routes  # noqa: E402
from crm_routes import renewals as _renewals_routes  # noqa: E402
from crm_routes import policies as _policies_routes  # noqa: E402
from crm_routes import customers as _customers_routes  # noqa: E402
from crm_routes import channels as _channels_routes  # noqa: E402
from crm_routes import imports as _imports_routes  # noqa: E402
from crm_routes import notifications as _notifications_routes  # noqa: E402
from crm_routes import messaging as _messaging_routes  # noqa: E402
from crm_routes import documents as _documents_routes  # noqa: E402
from crm_routes import follow_ups as _follow_ups_routes  # noqa: E402
from crm_routes import incentives as _incentives_routes  # noqa: E402
from crm_routes import commission as _commission_routes  # noqa: E402
from crm_routes import reports as _reports_routes  # noqa: E402
from crm_routes import dashboards as _dashboards_routes  # noqa: E402
from crm_routes import search as _search_routes  # noqa: E402
from crm_routes import auth as _auth_routes  # noqa: E402
from crm_routes import calls as _calls_routes  # noqa: E402
from crm_routes import advisor as _advisor_routes  # noqa: E402

app.include_router(_advisor_routes.router)
app.include_router(_calls_routes.router)
app.include_router(_auth_routes.router)
app.include_router(_search_routes.router)
app.include_router(_dashboards_routes.router)
app.include_router(_reports_routes.router)
app.include_router(_commission_routes.router)
app.include_router(_incentives_routes.router)
app.include_router(_follow_ups_routes.router)
app.include_router(_documents_routes.router)
app.include_router(_messaging_routes.router)
app.include_router(_notifications_routes.router)
app.include_router(_imports_routes.router)
app.include_router(_channels_routes.router)
app.include_router(_customers_routes.router)
app.include_router(_policies_routes.router)
app.include_router(_renewals_routes.router)
app.include_router(_quotations_routes.router)
app.include_router(_calendar_routes.router)
app.include_router(_automation_routes.router)
app.include_router(_team_routes.router)
app.include_router(_settings_routes.router)
app.include_router(_leads_routes.router)
app.include_router(_notes_routes.router)
app.include_router(_tasks_routes.router)
app.include_router(_deals_and_contacts_routes.router)
app.include_router(_admin_routes.router)
app.include_router(_backups_routes.router)
