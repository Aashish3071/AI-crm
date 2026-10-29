"""Automation engine (client blueprint, slide 33).

Every rule reads as one sentence: *when* something happens, *if* the record matches,
*then* do these things. This module owns the rules, the matching and every guardrail.
The server registers what each action does (``register_action``) and where each timed
trigger finds its records (``register_time_source``); nothing here touches the CRM's
records directly, which keeps the engine testable and the server free of rule logic.

Guardrails, because an automation that misfires on a 5,000-row import is worse than none:

* **Loops.** A rule never fires again inside the chain it started, and a chain stops
  after ``MAX_DEPTH`` hops.
* **Idempotency.** Each rule fires at most once per record per occurrence
  (``rule:record:occurrence``), so a retried request or a re-run scheduler cannot repeat it.
* **Rate limit.** A rule does at most ``maxPerHour`` runs an hour (default 200).
* **Quiet hours** are enforced by the messaging action, which queues instead of sending.
* **Kill switch.** ``settings.automation.paused`` stops every rule.
* **Contained failure.** One failing action does not stop the others; every run is logged.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MAX_DEPTH = 3
DEFAULT_MAX_PER_HOUR = 200
RUN_LOG_LIMIT = 1000
KEY_RETENTION_DAYS = 120

# ─── Vocabulary ──────────────────────────────────────────────────────────────
TRIGGERS: Dict[str, Dict[str, Any]] = {
    "lead.created": {"label": "A new lead arrives", "record": "lead", "kind": "event"},
    "lead.assigned": {"label": "A lead is assigned to someone", "record": "lead", "kind": "event"},
    "lead.status_changed": {"label": "A lead's status changes", "record": "lead", "kind": "event",
                            "params": [{"name": "to", "label": "to", "type": "status", "optional": True}]},
    "call.logged": {"label": "A call is logged", "record": "lead", "kind": "event",
                    "params": [{"name": "to", "label": "with outcome", "type": "outcome", "optional": True}]},
    "quotation.status_changed": {"label": "A quotation's status changes", "record": "quotation", "kind": "event",
                                 "params": [{"name": "to", "label": "to", "type": "text", "optional": True}]},
    "policy.issued": {"label": "A policy is issued", "record": "policy", "kind": "event"},
    "document.uploaded": {"label": "A document is uploaded", "record": "document", "kind": "event"},
    "task.completed": {"label": "A follow-up is completed", "record": "task", "kind": "event"},
    "policy.expiring": {"label": "A policy is about to expire", "record": "policy", "kind": "time",
                        "params": [{"name": "days", "label": "days before", "type": "int", "default": 30}]},
    "lead.expiring": {"label": "A lead's current policy is about to expire", "record": "lead", "kind": "time",
                      "params": [{"name": "days", "label": "days before", "type": "int", "default": 30}]},
    "task.overdue": {"label": "A follow-up is overdue", "record": "task", "kind": "time",
                     "params": [{"name": "days", "label": "days late", "type": "int", "default": 1}]},
    "lead.no_contact": {"label": "A lead has had no contact", "record": "lead", "kind": "time",
                        "params": [{"name": "days", "label": "days", "type": "int", "default": 3}]},
}

ACTIONS: Dict[str, Dict[str, Any]] = {
    "assign": {"label": "Assign to", "records": ["lead"]},
    "create_task": {"label": "Create a follow-up", "records": ["lead", "policy", "task", "quotation", "document"]},
    "notify": {"label": "Notify", "records": ["lead", "policy", "task", "quotation", "document"]},
    "send_message": {"label": "Message the customer", "records": ["lead", "policy"]},
    "set_status": {"label": "Set lead status", "records": ["lead"]},
    "set_priority": {"label": "Set calling priority", "records": ["lead"]},
    "add_note": {"label": "Add a note", "records": ["lead", "policy"]},
    "create_renewal": {"label": "Create a renewal record", "records": ["policy"]},
}

# What a condition can test, per record type. `numeric` fields compare as numbers.
FIELDS: Dict[str, List[Dict[str, Any]]] = {
    "lead": [
        {"field": "product", "label": "Product"}, {"field": "source", "label": "Lead source"},
        {"field": "city", "label": "City"}, {"field": "leadPriority", "label": "Calling priority"},
        {"field": "status", "label": "Status"}, {"field": "assignedTo", "label": "Telecaller"},
        {"field": "premium", "label": "Premium", "numeric": True},
        {"field": "daysToExpiry", "label": "Days to policy expiry", "numeric": True},
        # Earlier commercial fields; still evaluated so migrated rules keep working.
        {"field": "policyType", "label": "Policy category", "legacy": True},
        {"field": "territory", "label": "Territory", "legacy": True},
        {"field": "organization", "label": "Organization", "legacy": True},
        {"field": "industry", "label": "Industry", "legacy": True},
    ],
    "policy": [
        {"field": "policyType", "label": "Product"}, {"field": "insurer", "label": "Insurer"},
        {"field": "assignedTo", "label": "Telecaller"}, {"field": "premium", "label": "Premium", "numeric": True},
        {"field": "daysToExpiry", "label": "Days to expiry", "numeric": True},
    ],
    "quotation": [
        {"field": "status", "label": "Status"}, {"field": "insurer", "label": "Insurer"},
        {"field": "premium", "label": "Premium", "numeric": True},
    ],
    "task": [
        {"field": "title", "label": "Title"}, {"field": "priority", "label": "Priority"},
        {"field": "activityType", "label": "Activity"}, {"field": "assignedTo", "label": "Telecaller"},
    ],
    "document": [{"field": "category", "label": "Document type"}, {"field": "verification", "label": "Verification"}],
}

OPERATORS = [
    {"op": "contains", "label": "contains"},
    {"op": "is", "label": "is exactly"},
    {"op": "is_not", "label": "is not"},
    {"op": "greater_than", "label": "is more than", "numeric": True},
    {"op": "less_than", "label": "is less than", "numeric": True},
    {"op": "is_empty", "label": "is empty", "noValue": True},
]
# Slide 12. Product-based routing is a condition (product is Car Insurance); availability
# applies to every method — someone marked away is skipped until they are back.
ROUTING_METHODS = [
    {"method": "least_busy", "label": "Whoever has the fewest open leads (workload)"},
    {"method": "rotate", "label": "Rotate evenly between them (round-robin)"},
    {"method": "equal", "label": "Whoever has received the fewest leads this month (equal distribution)"},
    {"method": "performance", "label": "Share by conversion over the last 30 days — better converters get more (performance)"},
    {"method": "priority", "label": "HOT leads to the best converter, others to whoever is least busy (priority)"},
    {"method": "first", "label": "Always the first person listed"},
]
NOTIFY_TARGETS = ["assignee", "manager", "owner"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class ActionBlocked(Exception):
    """An action that deliberately did not run — consent, a closed window, a missing number.
    Recorded as blocked, never as a failure and never silently dropped."""


# ─── Registry filled in by the server ────────────────────────────────────────
_actions: Dict[str, Callable[..., str]] = {}
_time_sources: Dict[str, Callable[..., Iterable[Tuple[Dict[str, Any], str]]]] = {}
_field_reader: Callable[[Dict[str, Any], str], Any] = lambda record, field: record.get(field, "")
_number: Callable[[Any], float] = lambda value: float(value or 0)
# Compares a company-defined (custom) field by its type; see configure().
_typed_matcher: Optional[Callable[[Dict[str, Any], Any, str, Any], bool]] = None


def register_action(action_type: str, executor: Callable[..., str]):
    """executor(db, rule, params, record, ctx) -> short description of what it did."""
    _actions[action_type] = executor


def register_time_source(trigger: str, source: Callable[..., Iterable[Tuple[Dict[str, Any], str]]]):
    """source(db, params, now) -> (record, occurrence) pairs the trigger currently applies to."""
    _time_sources[trigger] = source


def configure(field_reader: Callable[[Dict[str, Any], str], Any], number: Callable[[Any], float],
              typed_matcher: Optional[Callable[[Dict[str, Any], Any, str, Any], bool]] = None):
    """typed_matcher(definition, stored, operator, expected) compares a custom field; a
    condition on one carries a copy of the field's definition."""
    global _field_reader, _number, _typed_matcher
    _field_reader, _number, _typed_matcher = field_reader, number, typed_matcher


# ─── Rules ───────────────────────────────────────────────────────────────────
class RuleError(ValueError):
    pass


def validate_rule(data: Dict[str, Any], people: Iterable[str], statuses: Iterable[str],
                  outcomes: Iterable[str] = (),
                  extra_fields: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> Dict[str, Any]:
    """Check a rule is complete and every choice in it is one the engine understands.

    ``extra_fields`` adds the company's own fields per record type; each carries its
    ``definition``, which is copied onto the conditions that test it."""
    name = str(data.get("name") or "").strip()
    if not name:
        raise RuleError("Give the rule a name")
    trigger = data.get("trigger") or {}
    kind = trigger.get("type")
    if kind not in TRIGGERS:
        raise RuleError("Choose when the rule runs")
    spec = TRIGGERS[kind]
    params = {}
    for p in spec.get("params", []):
        value = (trigger.get("params") or {}).get(p["name"], p.get("default"))
        if p["type"] == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                raise RuleError(f"{p['label'].capitalize()} must be a whole number")
            if not 0 <= value <= 365:
                raise RuleError(f"{p['label'].capitalize()} must be between 0 and 365")
        elif p["type"] == "status" and value and value not in statuses:
            raise RuleError(f"Status must be one of: {', '.join(statuses)}")
        elif p["type"] == "outcome" and value and value not in outcomes:
            raise RuleError(f"Call outcome must be one of: {', '.join(outcomes)}")
        if value not in (None, ""):
            params[p["name"]] = value
    record = spec["record"]
    known = {f["field"]: f for f in FIELDS.get(record, []) + (extra_fields or {}).get(record, [])}
    conditions = []
    for c in data.get("conditions") or []:
        if c.get("field") not in known:
            raise RuleError(f"'{c.get('field')}' can't be checked on a {record}")
        if c.get("operator", "contains") not in {o["op"] for o in OPERATORS}:
            raise RuleError(f"Unknown comparison '{c.get('operator')}'")
        condition = {"field": c["field"], "operator": c.get("operator", "contains"), "value": c.get("value", "")}
        if known[c["field"]].get("definition"):
            condition["definition"] = known[c["field"]]["definition"]
        conditions.append(condition)
    actions = []
    people = set(people)
    for a in data.get("actions") or []:
        action_type = a.get("type")
        if action_type not in ACTIONS:
            raise RuleError(f"Unknown action '{action_type}'")
        if record not in ACTIONS[action_type]["records"]:
            raise RuleError(f"“{ACTIONS[action_type]['label']}” can't be used when {spec['label'].lower()}")
        p = dict(a.get("params") or {})
        if action_type == "assign":
            if kind != "lead.created":
                raise RuleError("Assigning is done when a new lead arrives")
            assignees = [x for x in p.get("assignees") or [] if x]
            if not assignees:
                raise RuleError("Choose at least one person to assign to")
            unknown = [x for x in assignees if x not in people]
            if unknown:
                raise RuleError(f"Not on the team: {', '.join(unknown)}")
            if p.get("method", "least_busy") not in {m["method"] for m in ROUTING_METHODS}:
                raise RuleError("Unknown way of choosing who gets it")
            p = {"assignees": assignees, "method": p.get("method", "least_busy"), "lastAssignedTo": p.get("lastAssignedTo", "")}
        elif action_type == "create_task":
            if not str(p.get("title") or "").strip():
                raise RuleError("Give the follow-up a title")
            p["dueInDays"] = max(0, min(365, int(p.get("dueInDays") or 0)))
        elif action_type == "notify":
            if p.get("to", "assignee") not in NOTIFY_TARGETS:
                raise RuleError("Notify the telecaller, their manager or the owner")
            if not str(p.get("message") or "").strip():
                raise RuleError("Write the notification")
        elif action_type == "send_message":
            if str(p.get("channel") or "").lower() not in {"whatsapp", "email"}:
                raise RuleError("Messages go by WhatsApp or email")
            if not (p.get("whatsappTemplateId") or str(p.get("text") or "").strip()):
                raise RuleError("Write the message or choose an approved template")
        elif action_type == "set_status":
            if p.get("status") not in statuses:
                raise RuleError(f"Status must be one of: {', '.join(statuses)}")
        elif action_type == "set_priority":
            if str(p.get("priority") or "").upper() not in {"HOT", "WARM", "COLD"}:
                raise RuleError("Priority is HOT, WARM or COLD")
            p["priority"] = p["priority"].upper()
        elif action_type == "add_note" and not str(p.get("text") or "").strip():
            raise RuleError("Write the note")
        actions.append({"type": action_type, "params": p})
    if not actions:
        raise RuleError("Add at least one thing the rule does")
    limits = data.get("limits") or {}
    days = [d for d in limits.get("daysOfWeek") or [] if d in WEEKDAYS]
    try:
        per_hour = int(limits.get("maxPerHour") or DEFAULT_MAX_PER_HOUR)
    except (TypeError, ValueError):
        raise RuleError("Hourly limit must be a whole number")
    return {"name": name, "enabled": bool(data.get("enabled", False)), "trigger": {"type": kind, "params": params},
            "conditions": conditions, "actions": actions,
            "limits": {"daysOfWeek": days, "maxPerHour": max(1, min(5000, per_hour))},
            "recipe": data.get("recipe", "")}


def new_rule(validated: Dict[str, Any], actor: str) -> Dict[str, Any]:
    now = _now_iso()
    return {"id": f"AUTO_{uuid.uuid4().hex[:8]}", **validated, "runCount": 0, "lastRunAt": "",
            "createdBy": actor, "createdAt": now, "updatedAt": now}


# ─── Matching ────────────────────────────────────────────────────────────────
def condition_matches(record: Dict[str, Any], condition: Dict[str, Any]) -> bool:
    field, operator, expected = condition.get("field", ""), condition.get("operator", "contains"), condition.get("value", "")
    actual = _field_reader(record, field)
    if condition.get("definition") and _typed_matcher:
        return _typed_matcher(condition["definition"], actual, operator, expected)
    if operator == "is_empty":
        return actual in (None, "")
    if operator in ("greater_than", "less_than"):
        if actual in (None, ""):
            return False
        try:
            left, right = _number(actual), _number(expected)
        except Exception:
            return False
        return left > right if operator == "greater_than" else left < right
    left, right = str(actual if actual is not None else "").strip().lower(), str(expected).strip().lower()
    if operator == "is":
        return left == right
    if operator == "is_not":
        return left != right
    return right in left


def _trigger_matches(rule: Dict[str, Any], event: str, ctx: Dict[str, Any]) -> bool:
    trigger = rule.get("trigger") or {}
    if trigger.get("type") != event:
        return False
    wanted = (trigger.get("params") or {}).get("to")
    return not wanted or str(ctx.get("to", "")).lower() == str(wanted).lower()


def rule_matches(rule: Dict[str, Any], record: Dict[str, Any]) -> bool:
    return all(condition_matches(record, c) for c in rule.get("conditions") or [])


def _applies_today(rule: Dict[str, Any], now: datetime) -> bool:
    days = (rule.get("limits") or {}).get("daysOfWeek") or []
    return not days or WEEKDAYS[now.weekday()] in days


def paused(db: Dict[str, Any]) -> bool:
    return bool(db.get("settings", {}).get("automation", {}).get("paused"))


# ─── Guardrails ──────────────────────────────────────────────────────────────
def _within_rate(rule: Dict[str, Any], now: datetime) -> bool:
    window = rule.setdefault("window", {})
    hour = now.strftime("%Y-%m-%dT%H")
    if window.get("hour") != hour:
        window.update({"hour": hour, "count": 0})
    return window["count"] < int((rule.get("limits") or {}).get("maxPerHour") or DEFAULT_MAX_PER_HOUR)


def _claim(db: Dict[str, Any], key: str) -> bool:
    """True the first time a rule/record/occurrence is seen; False on every repeat."""
    keys = db.setdefault("automationKeys", {})
    if key in keys:
        return False
    keys[key] = _now_iso()
    return True


def prune_keys(db: Dict[str, Any], now: Optional[datetime] = None):
    cutoff = ((now or datetime.utcnow()) - timedelta(days=KEY_RETENTION_DAYS)).isoformat()
    keys = db.get("automationKeys", {})
    for key in [k for k, at in keys.items() if at < cutoff]:
        keys.pop(key, None)


# ─── Running ─────────────────────────────────────────────────────────────────
def _log(db: Dict[str, Any], entry: Dict[str, Any]):
    runs = db.setdefault("automationRuns", [])
    runs.insert(0, entry)
    del runs[RUN_LOG_LIMIT:]


def _record_label(record: Dict[str, Any]) -> str:
    return str(record.get("name") or record.get("customerName") or record.get("title")
               or record.get("originalName") or record.get("policyNumber") or record.get("id") or "")


def _run_rule(db: Dict[str, Any], rule: Dict[str, Any], event: str, record: Dict[str, Any], occurrence: str,
              ctx: Dict[str, Any], now: datetime, skip: Iterable[str] = (), prefix: Optional[List[Dict]] = None):
    record_id = str(record.get("id") or "")
    if not _claim(db, f"{rule['id']}:{record_id}:{occurrence}"):
        return None
    entry = {"id": f"RUN_{uuid.uuid4().hex[:8]}", "ruleId": rule["id"], "ruleName": rule.get("name", ""),
             "trigger": event, "recordType": TRIGGERS[event]["record"], "recordId": record_id,
             "recordName": _record_label(record), "at": _now_iso(), "actions": list(prefix or []),
             "depth": ctx.get("depth", 0)}
    if not _within_rate(rule, now):
        entry.update(status="skipped", reason=f"Hourly limit of {rule['limits']['maxPerHour']} runs reached")
        _log(db, entry)
        return entry
    rule["window"]["count"] += 1
    child = {**ctx, "depth": ctx.get("depth", 0) + 1, "chain": set(ctx.get("chain", set())) | {rule["id"]}}
    for action in rule.get("actions") or []:
        if action["type"] in skip:
            continue
        executor = _actions.get(action["type"])
        try:
            if not executor:
                raise RuntimeError("This action is not available")
            detail = executor(db, rule, action.get("params") or {}, record, child)
            entry["actions"].append({"type": action["type"], "result": "done", "detail": detail or ""})
        except ActionBlocked as blocked:
            entry["actions"].append({"type": action["type"], "result": "blocked", "detail": str(blocked)})
        except Exception as exc:                       # contained: the other actions still run
            entry["actions"].append({"type": action["type"], "result": "failed", "detail": f"{type(exc).__name__}: {exc}"})
    results = {a["result"] for a in entry["actions"]}
    entry["status"] = ("done" if results <= {"done"} else "failed" if results == {"failed"}
                       else "blocked" if results == {"blocked"} else "partial")
    rule["runCount"] = rule.get("runCount", 0) + 1
    rule["lastRunAt"] = entry["at"]
    _log(db, entry)
    return entry


def fire(db: Dict[str, Any], event: str, record: Dict[str, Any], ctx: Optional[Dict[str, Any]] = None,
         occurrence: str = "", now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Run every enabled rule for this event whose conditions match the record, in order.

    A lead is assigned once: assignment already happened when it was created (see
    choose_assignee), so `assign` actions are skipped here and reported in that rule's log.
    """
    ctx = dict(ctx or {})
    now = now or datetime.utcnow()
    if paused(db) or event not in TRIGGERS:
        return []
    if ctx.get("depth", 0) >= MAX_DEPTH:
        _log(db, {"id": f"RUN_{uuid.uuid4().hex[:8]}", "ruleId": "", "ruleName": "", "trigger": event,
                  "recordType": TRIGGERS[event]["record"], "recordId": str(record.get("id", "")),
                  "recordName": _record_label(record), "at": _now_iso(), "actions": [], "depth": ctx["depth"],
                  "status": "skipped", "reason": f"Stopped: automations may chain at most {MAX_DEPTH} steps"})
        return []
    runs = []
    assignment = ctx.get("assignment") or {}
    for rule in sorted(db.get("automationRules", []), key=lambda r: r.get("order", 0)):
        if not rule.get("enabled") or rule["id"] in ctx.get("chain", set()):
            continue
        if not _trigger_matches(rule, event, ctx) or not _applies_today(rule, now) or not rule_matches(rule, record):
            continue
        prefix = [{"type": "assign", "result": "done", "detail": f"Assigned to {assignment['owner']}"}] \
            if assignment.get("ruleId") == rule["id"] else []
        entry = _run_rule(db, rule, event, record, occurrence or ctx.get("occurrence", event), ctx, now,
                          skip={"assign"}, prefix=prefix)
        if entry:
            runs.append(entry)
    return runs


def choose_assignee(db: Dict[str, Any], lead: Dict[str, Any], pick: Callable[[Dict[str, Any], Dict[str, Any]], str],
                    now: Optional[datetime] = None) -> Tuple[str, Optional[Dict[str, Any]]]:
    """The first enabled new-lead rule with an assign action whose conditions match."""
    now = now or datetime.utcnow()
    if paused(db):
        return "", None
    for rule in sorted(db.get("automationRules", []), key=lambda r: r.get("order", 0)):
        if not rule.get("enabled") or (rule.get("trigger") or {}).get("type") != "lead.created":
            continue
        action = next((a for a in rule.get("actions") or [] if a["type"] == "assign"), None)
        if not action or not _applies_today(rule, now) or not rule_matches(rule, lead):
            continue
        owner = pick(db, action["params"], lead)
        if owner:
            rule["matchCount"] = rule.get("matchCount", 0) + 1
            rule["lastMatchedAt"] = _now_iso()
            return owner, rule
    return "", None


def run_time_triggers(db: Dict[str, Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Called by the scheduler. Each timed rule fires once per record per occurrence."""
    now = now or datetime.utcnow()
    if paused(db):
        return []
    runs = []
    for rule in sorted(db.get("automationRules", []), key=lambda r: r.get("order", 0)):
        trigger = rule.get("trigger") or {}
        source = _time_sources.get(trigger.get("type"))
        if not rule.get("enabled") or not source or not _applies_today(rule, now):
            continue
        for record, occurrence in source(db, trigger.get("params") or {}, now):
            if rule_matches(rule, record):
                entry = _run_rule(db, rule, trigger["type"], record, occurrence, {"depth": 0}, now)
                if entry:
                    runs.append(entry)
    prune_keys(db, now)
    return runs


def preview(db: Dict[str, Any], rule: Dict[str, Any], records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Which of these records the rule would act on. Changes nothing."""
    matched = [r for r in records if rule_matches(rule, r)]
    return {"checked": len(records), "matched": len(matched),
            "examples": [{"id": r.get("id"), "name": _record_label(r)} for r in matched[:10]],
            "actions": [ACTIONS[a["type"]]["label"] for a in rule.get("actions") or []]}


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"
