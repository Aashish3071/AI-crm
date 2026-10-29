"""Calling (client blueprint, slides 15–16).

A telecaller dials from the CRM, sees the customer's record while talking, and records one
of the blueprint's outcomes when the call ends; the outcome takes the next step itself
(a follow-up, a call-back, a retry, a sale). Calls are placed through crm_telephony.
"""
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import crm_automation as automation
import crm_security
import crm_telephony as telephony
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


MAX_CALL_SECONDS = 4 * 3600


@router.get("/api/calls/options")
def call_options():
    db = core.load_db()
    provider = telephony.provider_for(db.get("settings", {}).get("telephony", {}))
    return {"outcomes": [{"value": k, **v} for k, v in core.CALL_OUTCOMES.items()], "closeReasons": core.CLOSE_REASONS,
            "provider": {"key": provider.key, "label": provider.label, "measuresCalls": provider.measures_calls}}


@router.get("/api/calls")
def list_calls(leadId: Optional[str] = None, telecaller: Optional[str] = None, since: Optional[str] = None,
               limit: int = Query(200, ge=1, le=2000)):
    db = core.load_db()
    calls = core.scoped(db.get("callLogs", []), core.visible_owners(db))
    if leadId:
        calls = [c for c in calls if c.get("leadId") == leadId]
    if telecaller:
        calls = [c for c in calls if c.get("assignedTo") == telecaller]
    if since:
        calls = [c for c in calls if (c.get("startedAt") or "") >= since]
    calls = sorted(calls, key=lambda c: c.get("startedAt") or c.get("createdAt") or "", reverse=True)[:limit]
    return [core._call_view(db, c) for c in calls]


class CallStart(BaseModel):
    leadId: str


@router.post("/api/calls/start")
def start_call(payload: CallStart):
    """Click-to-call: open a call record and ask the provider — or the telecaller's phone — to dial."""
    db = core.load_db()
    lead = core.require_visible(core._find_record(db.get("leads", []), payload.leadId, "Lead"), core.visible_owners(db), "Lead")
    session = None if core.AUTH_DISABLED else crm_security.current_user()
    caller = (session or {}).get("name") or lead.get("assignedTo") or current_actor("System")
    settings = db.get("settings", {}).get("telephony", {})
    provider = telephony.provider_for(settings)
    now = datetime.utcnow().isoformat() + "Z"
    call = {"id": f"CALL_{uuid.uuid4().hex[:8]}", "leadId": lead["id"], "customerName": lead.get("name", ""),
            "assignedTo": caller, "direction": "Outbound", "status": "In progress", "fromNumber": settings.get("callerId", ""),
            "toNumber": lead.get("mobile", ""), "startedAt": now, "endedAt": "", "durationSeconds": None,
            "provider": provider.key, "providerCallId": "", "outcome": "", "connected": None, "notes": "",
            "recordingUrl": "", "createdAt": now, "normalized": True}
    try:
        placed = provider.place_call(settings, call["fromNumber"], call["toNumber"], {"name": caller}, call["id"], "")
    except telephony.ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    call["providerCallId"] = placed.get("providerCallId", "")
    db.setdefault("callLogs", []).insert(0, call)
    core.audit(db, "Call Started", "Lead", lead["id"], {"callId": call["id"], "provider": provider.key})
    core.save_db(db)
    return {"call": call, "dial": placed.get("dial", ""), "instructions": placed.get("instructions", ""),
            "lead": core.live_expiry(lead), "documentStatus": core.document_status(db, lead),
            "previousCalls": [core._call_view(db, c) for c in db.get("callLogs", [])
                              if c.get("leadId") == lead["id"] and c["id"] != call["id"]][:5]}


class CallResult(BaseModel):
    outcome: str
    notes: Optional[str] = ""
    followUpDate: Optional[str] = ""
    followUpTime: Optional[str] = ""
    reason: Optional[str] = ""
    currentExpiryDate: Optional[str] = ""
    durationSeconds: Optional[int] = None
    policy: Optional[Dict[str, Any]] = None


class CallLog(CallResult):
    leadId: str


def apply_call_outcome(db: Dict[str, Any], lead: Dict[str, Any], call: Dict[str, Any], result: CallResult) -> str:
    """Slide 16: every outcome triggers its next step. Returns a sentence saying what happened."""
    outcome = core.canonical_outcome(result.outcome)
    spec = core.CALL_OUTCOMES.get(outcome)
    if not spec:
        raise HTTPException(status_code=422, detail=f"Outcome must be one of: {', '.join(core.CALL_OUTCOMES)}")
    today, tomorrow = core._company_today(db), core._company_today(db, 1)
    early = core.canonical_status(lead.get("status")) in {"New", "Assigned", "Unreachable"}
    status = core.canonical_status(lead.get("status"))
    name = lead.get("name", "")

    if outcome == "Interested":
        core._set_lead_next(db, lead, "Interested", f"Send quotation to {name}", today)
        return "Interested — quotation follow-up due today."
    if outcome == "Call Back":
        due = core._parse_flexible_date(result.followUpDate or "")
        if not due:
            raise HTTPException(status_code=422, detail="Choose when to call back.")
        when = core._checked_time(result.followUpTime)
        core._set_lead_next(db, lead, "Call Later", f"Call back {name}", due, when)
        return f"Call back scheduled for {due}{' ' + when if when else ''}."
    if outcome == "Not Interested":
        if not (result.reason or "").strip():
            raise HTTPException(status_code=422, detail="Record why the customer is not interested.")
        core._set_lead_next(db, lead, "Not Interested", reason=result.reason.strip())
        return "Closed as not interested."
    if outcome == "Busy / Switched Off":
        # A missed call does not undo progress: an interested customer who didn't pick up is still interested.
        attempts = lead["unansweredCalls"] = int(lead.get("unansweredCalls") or 0) + 1
        core._set_lead_next(db, lead, "Unreachable" if early else status, f"Retry call to {name}", tomorrow,
                       core._checked_time(result.followUpTime))
        return f"No answer (attempt {attempts}) — retry tomorrow."
    if outcome == "Wrong Number":
        core._set_lead_next(db, lead, "Wrong Number")
        lead["flaggedForReview"] = True
        reviewer = core._manager_of(db, lead.get("assignedTo"))
        db.setdefault("notifications", []).insert(0, {
            "id": f"NTF_{uuid.uuid4().hex[:8]}", "type": "Lead Review", "severity": "Medium",
            "title": f"Wrong number flagged — {name}", "message": f"{call.get('assignedTo')} reached a wrong number on {lead.get('mobile')}. Check the number or close the lead.",
            "associatedId": lead["id"], "assignedTo": reviewer, "dedupeKey": f"wrong-number:{lead['id']}:{call['id']}",
            "read": False, "createdAt": datetime.utcnow().isoformat() + "Z"})
        return f"Flagged for {reviewer} to review."
    if outcome == "Already Insured":
        expiry = core._parse_flexible_date(result.currentExpiryDate or "")
        if not expiry:
            raise HTTPException(status_code=422, detail="Record when their current policy expires, so we call before it renews.")
        lead["expiryDate"] = expiry
        lead["existingPolicy"] = {**(lead.get("existingPolicy") or {}), "expiryDate": expiry}
        lead["daysRemaining"] = core._days_until(expiry)
        lead["watchlist"] = "Already insured"
        call_on = max(today, (datetime.strptime(expiry, "%Y-%m-%d") - timedelta(days=30)).strftime("%Y-%m-%d"))
        core._set_lead_next(db, lead, "Call Later", f"Renewal call to {name} before their policy expires", call_on)
        return f"On the renewal watchlist — call again on {call_on}."
    if outcome == "Documents Pending":
        missing = core.document_status(db, lead)["missing"]
        core._set_lead_next(db, lead, "Documents Pending", f"Collect documents from {name}" + (f": {', '.join(missing)}" if missing else ""), tomorrow)
        return "Documents pending — collection follow-up tomorrow."
    if outcome == "Policy Sold":
        if lead.get("convertedPolicyId"):
            core._set_lead_next(db, lead, "Policy Sold")
            return "Marked sold; the policy was already recorded."
        details = core.LeadConversionPayload(**{k: v for k, v in (result.policy or {}).items() if k in core.LeadConversionPayload.model_fields})
        if not details.insurer or not details.premium or not details.expiryDate:
            raise HTTPException(status_code=422, detail="Record the insurer, premium and policy expiry to log a sale.")
        converted = core._convert_lead(db, lead, details)
        core._close_lead_work(db, lead)
        return f"Sold — draft policy created, renewal date {converted['policy'].get('renewalDate') or 'not set'}."
    raise HTTPException(status_code=422, detail="Unknown outcome")


def _finish_call(db: Dict[str, Any], call: Dict[str, Any], result: CallResult):
    lead = core.require_visible(core._find_record(db.get("leads", []), call["leadId"], "Lead"), core.visible_owners(db), "Lead")
    now = datetime.utcnow()
    outcome = core.canonical_outcome(result.outcome)
    if result.durationSeconds is not None:
        if not 0 <= result.durationSeconds <= MAX_CALL_SECONDS:
            raise HTTPException(status_code=422, detail="Call length must be between 0 seconds and 4 hours")
        call["durationSeconds"], call["durationSource"] = result.durationSeconds, "entered by telecaller"
    elif call.get("loggedAfterwards"):
        call["durationSeconds"], call["durationSource"] = None, "not recorded"
    elif call.get("startedAt"):
        started = datetime.fromisoformat(call["startedAt"].replace("Z", ""))
        call["durationSeconds"] = min(MAX_CALL_SECONDS, max(0, int((now - started).total_seconds())))
        call["durationSource"] = "call screen timer"
    summary = apply_call_outcome(db, lead, call, result)
    call.update({"outcome": outcome, "connected": core.CALL_OUTCOMES[outcome]["connected"], "status": "Completed",
                 "endedAt": now.isoformat() + "Z", "notes": (result.notes or "").strip(), "result": summary})
    note = f"{core.CALL_OUTCOMES[outcome]['label']}. {summary}" + (f"\n\n{call['notes']}" if call["notes"] else "")
    db.setdefault("notes", []).insert(0, {
        "id": f"N_{uuid.uuid4().hex[:8]}", "title": f"Call — {outcome}", "associatedType": "Lead", "associatedId": lead["id"],
        "associatedTitle": lead.get("name", ""), "category": "Call", "content": note, "callId": call["id"],
        "author": call.get("assignedTo") or current_actor("System"), "pinned": False, "createdAt": now.isoformat() + "Z"})
    core.audit(db, "Call Logged", "Lead", lead["id"], {"callId": call["id"], "outcome": outcome, "durationSeconds": call.get("durationSeconds")})
    automation.fire(db, "call.logged", lead, {"to": outcome, "occurrence": f"call:{call['id']}"})
    return {"call": core._call_view(db, call), "lead": core.live_expiry(lead), "summary": summary}


@router.post("/api/calls/{id}/complete")
def complete_call(id: str, result: CallResult):
    db = core.load_db()
    call = core.require_visible(core._find_record(db.get("callLogs", []), id, "Call"), core.visible_owners(db), "Call")
    if call.get("status") == "Completed":
        raise HTTPException(status_code=409, detail="This call's outcome is already recorded")
    response = _finish_call(db, call, result)
    core.save_db(db)
    return response


@router.post("/api/calls")
def log_call(payload: CallLog):
    """Record a call made outside the call screen, with its length entered by hand."""
    db = core.load_db()
    lead = core.require_visible(core._find_record(db.get("leads", []), payload.leadId, "Lead"), core.visible_owners(db), "Lead")
    session = None if core.AUTH_DISABLED else crm_security.current_user()
    now = datetime.utcnow().isoformat() + "Z"
    call = {"id": f"CALL_{uuid.uuid4().hex[:8]}", "leadId": lead["id"], "customerName": lead.get("name", ""),
            "assignedTo": (session or {}).get("name") or lead.get("assignedTo", ""), "direction": "Outbound",
            "status": "In progress", "toNumber": lead.get("mobile", ""), "startedAt": now, "provider": "manual",
            "createdAt": now, "normalized": True, "loggedAfterwards": True}
    db.setdefault("callLogs", []).insert(0, call)
    response = _finish_call(db, call, CallResult(**payload.model_dump(exclude={"leadId"})))
    core.save_db(db)
    return response
