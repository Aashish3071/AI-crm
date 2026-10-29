"""Automation rules and lead assignment rules (client blueprint, slides 12 and 33).

The rule engine itself is crm_automation; these routes edit, preview and log the rules.
"""
import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import crm_automation as automation
import crm_schema
import crm_security
import pipecat_server as core
from crm_security import current_actor

router = APIRouter()


RULE_FIELDS = [f for f in automation.FIELDS["lead"]]


RULE_OPERATORS = automation.OPERATORS


ROUTING_METHODS = automation.ROUTING_METHODS


WEEKDAYS = automation.WEEKDAYS


class AssignmentRule(BaseModel):
    name: str
    enabled: Optional[bool] = True
    conditions: Optional[List[Dict[str, Any]]] = None      # [{field, operator, value}] — all must match
    assignees: Optional[List[str]] = None                  # team member names
    method: Optional[str] = "least_busy"
    days: Optional[List[str]] = None                       # empty/absent = every day
    createTask: Optional[bool] = False
    taskTitle: Optional[str] = ""
    taskDueInDays: Optional[int] = 1


def _is_assignment_rule(rule: Dict[str, Any]) -> bool:
    return (rule.get("trigger") or {}).get("type") == "lead.created" and any(a["type"] == "assign" for a in rule.get("actions") or [])


def _legacy_view(rule: Dict[str, Any]) -> Dict[str, Any]:
    assign = next(a for a in rule["actions"] if a["type"] == "assign")["params"]
    task = next((a["params"] for a in rule["actions"] if a["type"] == "create_task"), None)
    return {"id": rule["id"], "name": rule.get("name"), "enabled": rule.get("enabled"), "conditions": rule.get("conditions", []),
            "assignees": assign.get("assignees", []), "method": assign.get("method", "least_busy"),
            "days": (rule.get("limits") or {}).get("daysOfWeek", []), "createTask": bool(task),
            "taskTitle": (task or {}).get("title", ""), "taskDueInDays": (task or {}).get("dueInDays", 1),
            "matchCount": rule.get("matchCount", 0), "lastMatchedAt": rule.get("lastMatchedAt", ""),
            "lastAssignedTo": assign.get("lastAssignedTo", ""), "createdAt": rule.get("createdAt", "")}


def _next_order(db: Dict[str, Any]) -> int:
    return max((r.get("order", 0) for r in db.get("automationRules", [])), default=-1) + 1


def _reorder(rules: List[Dict[str, Any]]):
    for i, rule in enumerate(sorted(rules, key=lambda r: r.get("order", 0))):
        rule["order"] = i


# ── Ready-made rules for the client's slide-33 table ──
RECIPES = [
    {"key": "assign-new-leads", "row": "New Lead → Assign employee automatically",
     "name": "Share new leads between telecallers", "needs": "assignees",
     "rule": {"trigger": {"type": "lead.created"}, "actions": [{"type": "assign", "params": {"method": "least_busy"}}]}},
    {"key": "notify-assignment", "row": "New Assignment → Notify employee", "name": "Tell telecallers about their new leads",
     "rule": {"trigger": {"type": "lead.assigned"}, "actions": [{"type": "notify", "params": {
         "to": "assignee", "message": "New lead: {{name}} ({{product}}). Call within the day."}}]}},
    {"key": "call-record", "row": "Call Completed → Save call record",
     "builtIn": "Every call is saved to the customer's history as it is logged — there is nothing to switch on."},
    {"key": "interested-follow-up", "row": "Interested Customer → Create follow-up", "name": "Quote interested customers the same day",
     "rule": {"trigger": {"type": "lead.status_changed", "params": {"to": "Interested"}}, "actions": [{"type": "create_task", "params": {
         "title": "Send quotation to {{name}}", "dueInDays": 0, "priority": "High", "activityType": "Quotation"}}]}},
    {"key": "quote-reminder", "row": "Quote Sent → Schedule reminder", "name": "Chase quotations after two days",
     "rule": {"trigger": {"type": "lead.status_changed", "params": {"to": "Quote Sent"}}, "actions": [{"type": "create_task", "params": {
         "title": "Follow up on the quotation with {{name}}", "dueInDays": 2, "activityType": "Call"}}]}},
    {"key": "sold-renewal", "row": "Policy Sold → Create renewal record", "name": "Open a renewal for every policy sold",
     "rule": {"trigger": {"type": "policy.issued"}, "actions": [{"type": "create_renewal", "params": {}}]}},
    {"key": "renewal-approaching", "row": "Renewal Approaching → Notify employee",
     "builtIn": "Built in: a renewal opens 60 days before expiry, and the telecaller is reminded at 60, 30, 15 and 7 days, "
                "on the due date, and — with their manager — if the policy expires unrenewed."},
    {"key": "missed-follow-up", "row": "Missed Follow-up → Alert employee / owner",
     "builtIn": "Built in: a missed follow-up alerts the telecaller, and one left overdue escalates to their manager."},
    {"key": "target-incentive", "row": "Employee Target Achieved → Update incentive score",
     "builtIn": "Built in: a telecaller's incentive estimate is recalculated from your incentive rules with every sale, "
                "including any bonus for reaching target, and they are notified once when they reach 100% of their monthly target."},
    {"key": "request-documents", "row": "Documents Pending → Ask the customer (slide 19)", "name": "Ask customers for missing documents",
     "rule": {"trigger": {"type": "lead.status_changed", "params": {"to": "Documents Pending"}}, "actions": [{"type": "send_message", "params": {
         "channel": "WhatsApp", "text": "Hello {{firstName}}, to complete your {{product}} we still need: {{missingDocuments}}. "
                                         "You can reply here with a photo or PDF of each. Thank you."}}]}},
]


# ── HTTP API ──
def _people(db: Dict[str, Any]) -> List[str]:
    return [u.get("name") for u in db.get("users", []) if u.get("status", "Active") == "Active"]


def _validated(db: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        rule = automation.validate_rule(data, _people(db), core.LEAD_STATUSES, list(core.CALL_OUTCOMES),
                                        extra_fields=core.custom_rule_fields(db))
        for condition in rule["conditions"]:
            if condition.get("definition"):
                crm_schema.check_condition(condition["definition"], condition["operator"], condition["value"])
        return rule
    except (automation.RuleError, crm_schema.SchemaError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/api/automations/options")
def automation_options():
    db = core.load_db()
    custom = [f for f in core.custom_rule_fields(db)["lead"] if not f["hidden"]]
    fields = {**automation.FIELDS, "lead": automation.FIELDS["lead"] + custom}
    return {"triggers": automation.TRIGGERS, "actions": automation.ACTIONS, "fields": fields,
            "operators": automation.OPERATORS, "methods": automation.ROUTING_METHODS,
            "notifyTargets": automation.NOTIFY_TARGETS, "weekdays": automation.WEEKDAYS, "people": _people(db),
            "statuses": list(core.LEAD_STATUSES), "outcomes": list(core.CALL_OUTCOMES), "tokens": core.TEMPLATE_TOKENS + ["customerName", "missingDocuments"],
            "whatsappTemplates": [{"id": t["id"], "name": t.get("name"), "body": t.get("body", "")}
                                  for t in db.get("whatsappTemplates", []) if t.get("status") == "Approved"],
            "maxDepth": automation.MAX_DEPTH, "defaultMaxPerHour": automation.DEFAULT_MAX_PER_HOUR}


@router.get("/api/automations")
def list_automations():
    db = core.load_db()
    rules = sorted(db.get("automationRules", []), key=lambda r: r.get("order", 0))
    used = {r.get("recipe") for r in rules if r.get("recipe")}
    return {"paused": automation.paused(db), "rules": rules,
            "recipes": [{**{k: v for k, v in r.items() if k != "rule"},
                         "ruleId": next((x["id"] for x in rules if x.get("recipe") == r["key"]), ""),
                         "added": r["key"] in used} for r in RECIPES]}


@router.post("/api/automations")
def create_automation(payload: Dict[str, Any]):
    db = core.load_db()
    rule = automation.new_rule(_validated(db, payload), current_actor("System"))
    rule["order"] = _next_order(db)
    db.setdefault("automationRules", []).append(rule)
    core.audit(db, "Automation Created", "Automation", rule["id"], {"name": rule["name"], "enabled": rule["enabled"]})
    core.save_db(db)
    return rule


@router.post("/api/automations/recipes/{key}")
def add_recipe(key: str, payload: Optional[Dict[str, Any]] = None):
    """Turn on one of the slide-33 rules, already written, in one step."""
    db = core.load_db()
    recipe = next((r for r in RECIPES if r["key"] == key), None)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    if "rule" not in recipe:
        raise HTTPException(status_code=409, detail=recipe.get("builtIn") or recipe.get("comingWith"))
    if any(r.get("recipe") == key for r in db.get("automationRules", [])):
        raise HTTPException(status_code=409, detail="This rule is already added — edit it in the list below.")
    data = json.loads(json.dumps(recipe["rule"]))
    if recipe.get("needs") == "assignees":
        chosen = (payload or {}).get("assignees") or [u.get("name") for u in db.get("users", [])
                                                      if u.get("status", "Active") == "Active"
                                                      and crm_security.normalized_role(u.get("role", "")) == "telecaller"]
        if not chosen:
            raise HTTPException(status_code=422, detail="Add a telecaller under Settings → Users first.")
        data["actions"][0]["params"]["assignees"] = chosen
    data.update({"name": recipe["name"], "enabled": (payload or {}).get("enabled", True), "recipe": key})
    rule = automation.new_rule(_validated(db, data), current_actor("System"))
    rule["order"] = _next_order(db)
    db.setdefault("automationRules", []).append(rule)
    core.audit(db, "Automation Created", "Automation", rule["id"], {"name": rule["name"], "recipe": key})
    core.save_db(db)
    return rule


@router.put("/api/automations/pause")
def pause_automations(payload: Dict[str, Any]):
    """The kill switch: stops every rule at once, and starts them again."""
    db = core.load_db()
    state = db.setdefault("settings", {}).setdefault("automation", {})
    state["paused"] = bool(payload.get("paused"))
    state["pausedBy"], state["pausedAt"] = current_actor("System"), datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Automations Paused" if state["paused"] else "Automations Resumed", "Automation", "all", {})
    core.save_db(db)
    return {"paused": state["paused"]}


@router.put("/api/automations/{id}")
def update_automation(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    rule = core._find_record(db.get("automationRules", []), id, "Automation")
    merged = {**rule, **{k: v for k, v in updates.items() if k in {"name", "enabled", "trigger", "conditions", "actions", "limits"}}}
    for action in merged.get("actions") or []:                         # keep rotation state across edits
        if action.get("type") == "assign":
            old = next((a for a in rule.get("actions", []) if a["type"] == "assign"), {})
            action.setdefault("params", {}).setdefault("lastAssignedTo", (old.get("params") or {}).get("lastAssignedTo", ""))
    validated = _validated(db, {**merged, "recipe": rule.get("recipe", "")})
    rule.update({**validated, "updatedAt": datetime.utcnow().isoformat() + "Z"})
    core.audit(db, "Automation Updated", "Automation", id, {k: updates[k] for k in updates if k in {"name", "enabled"}})
    core.save_db(db)
    return rule


@router.post("/api/automations/{id}/move")
def move_automation(id: str, payload: Dict[str, Any]):
    db = core.load_db()
    rules = sorted(db.get("automationRules", []), key=lambda r: r.get("order", 0))
    index = next((i for i, r in enumerate(rules) if r.get("id") == id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    target = max(0, min(len(rules) - 1, index + (-1 if payload.get("direction") == "up" else 1)))
    rules.insert(target, rules.pop(index))
    for i, rule in enumerate(rules):
        rule["order"] = i
    core.save_db(db)
    return rules


@router.delete("/api/automations/{id}")
def delete_automation(id: str):
    db = core.load_db()
    rule = core._find_record(db.get("automationRules", []), id, "Automation")
    db["automationRules"] = [r for r in db.get("automationRules", []) if r.get("id") != id]
    _reorder(db["automationRules"])
    core.audit(db, "Automation Deleted", "Automation", id, {"name": rule.get("name")})
    core.save_db(db)
    return {"status": "deleted", "id": id}


@router.post("/api/automations/preview")
def preview_automation(payload: Dict[str, Any]):
    """Dry run against the most recent matching records. Nothing is changed."""
    db = core.load_db()
    rule = _validated(db, {**payload, "name": payload.get("name") or "Preview"})
    record_type = automation.TRIGGERS[rule["trigger"]["type"]]["record"]
    collection = {"lead": "leads", "policy": "policies", "quotation": "quotations", "task": "tasks", "document": "documents"}[record_type]
    records = sorted(core.scoped(db.get(collection, []), core.visible_owners(db)) if record_type != "document" else db.get(collection, []),
                     key=lambda r: r.get("lastModified") or r.get("updatedAt") or r.get("createdAt") or "", reverse=True)[:20]
    return automation.preview(db, rule, [core.live_expiry(r) for r in records])


@router.get("/api/automations/runs")
def automation_runs(ruleId: Optional[str] = None, limit: int = Query(100, ge=1, le=1000)):
    runs = core.load_db().get("automationRuns", [])
    return [r for r in runs if not ruleId or r.get("ruleId") == ruleId][:limit]


# ── The older assignment-rule API, as a view over automation rules ──
@router.get("/api/assignment-rules/options")
def assignment_rule_options():
    db = core.load_db()
    return {"fields": [f for f in RULE_FIELDS if not f.get("legacy")], "operators": RULE_OPERATORS,
            "methods": ROUTING_METHODS, "days": WEEKDAYS, "people": _people(db)}


@router.get("/api/assignment-rules")
def list_assignment_rules():
    db = core.load_db()
    return [_legacy_view(r) for r in sorted(db.get("automationRules", []), key=lambda r: r.get("order", 0)) if _is_assignment_rule(r)]


def _legacy_to_rule(db: Dict[str, Any], data: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not data.get("assignees"):
        raise HTTPException(status_code=422, detail="Choose at least one person for this rule to assign to")
    if (data.get("method") or "least_busy") not in {m["method"] for m in ROUTING_METHODS}:
        raise HTTPException(status_code=422, detail="Unknown assignment method")
    for condition in data.get("conditions") or []:
        if condition.get("field") not in {f["field"] for f in RULE_FIELDS}:
            raise HTTPException(status_code=422, detail=f"Unknown field: {condition.get('field')}")
        if condition.get("operator") not in {o["op"] for o in RULE_OPERATORS}:
            raise HTTPException(status_code=422, detail=f"Unknown operator: {condition.get('operator')}")
    return core._rule_from_legacy({**(existing or {}), **data}, (existing or {}).get("order", _next_order(db)))


@router.post("/api/assignment-rules")
def create_assignment_rule(payload: AssignmentRule):
    db = core.load_db()
    rule = _legacy_to_rule(db, payload.model_dump())
    rule.update({"id": f"RUL_{uuid.uuid4().hex[:8]}", "createdBy": current_actor("System")})
    db.setdefault("automationRules", []).append(rule)        # order is priority: first match wins
    core.audit(db, "Assignment Rule Created", "Assignment Rule", rule["id"], {"name": rule["name"]})
    core.save_db(db)
    return _legacy_view(rule)


@router.put("/api/assignment-rules/{id}")
def update_assignment_rule(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    rule = core._find_record(db.get("automationRules", []), id, "Assignment rule")
    if not _is_assignment_rule(rule):
        raise HTTPException(status_code=404, detail="Assignment rule not found")
    allowed = {"name", "enabled", "conditions", "assignees", "method", "days", "createTask", "taskTitle", "taskDueInDays"}
    current = _legacy_view(rule)
    replacement = _legacy_to_rule(db, {**current, **{k: v for k, v in updates.items() if k in allowed}}, rule)
    replacement.update({"id": rule["id"], "order": rule.get("order", 0), "createdBy": rule.get("createdBy", "System")})
    rule.clear(); rule.update(replacement)
    core.audit(db, "Assignment Rule Updated", "Assignment Rule", id, {k: v for k, v in updates.items() if k in allowed})
    core.save_db(db)
    return _legacy_view(rule)


@router.post("/api/assignment-rules/{id}/move")
def reorder_assignment_rule(id: str, payload: Dict[str, Any]):
    """Rules are tried top to bottom, so order is the priority."""
    move_automation(id, payload)
    return list_assignment_rules()


@router.delete("/api/assignment-rules/{id}")
def delete_assignment_rule(id: str):
    db = core.load_db()
    rule = core._find_record(db.get("automationRules", []), id, "Assignment rule")
    db["automationRules"] = [r for r in db.get("automationRules", []) if r.get("id") != id]
    _reorder(db["automationRules"])
    core.audit(db, "Assignment Rule Deleted", "Assignment Rule", id, {"name": rule.get("name")})
    core.save_db(db)
    return {"status": "deleted", "id": id}


@router.post("/api/assignment-rules/preview")
def preview_assignment_rule(sample: Dict[str, Any]):
    """Show which rule would fire for an example enquiry, before switching it on."""
    db = json.loads(json.dumps(core.load_db()))                 # a copy: a preview never advances a rotation
    owner, rule = automation.choose_assignee(db, sample, core._pick_assignee)
    if not rule:
        return {"matched": False, "rule": "", "assignee": "",
                "explanation": "No rule matches this enquiry — it would be shared between telecallers as usual."}
    method = next(a for a in rule["actions"] if a["type"] == "assign")["params"].get("method", "least_busy")
    label = next((m["label"] for m in ROUTING_METHODS if m["method"] == method), method)
    return {"matched": True, "rule": rule.get("name", ""), "assignee": owner,
            "explanation": f"“{rule.get('name')}” matches, so it would go to {owner} ({label.lower()})."}
