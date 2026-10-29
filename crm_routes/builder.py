"""Customize with AI (docs/AI_CUSTOMIZATION_PLAN.md, phase 3). Owner / Admin only.

The owner describes a change; the model (through crm_ai) proposes a change set from
crm_builder's catalogue; every operation is checked and described in plain words; nothing
changes until the owner applies it. A change set can also be written by hand, which is how
it works with no AI configured and how the catalogue is tested.

Applying re-checks the change set against the configuration as it is now and writes it in one
save. Undo restores the configuration from before, and removes the rules it added, but only
for the most recent change set, only if nothing has changed since, and only if no lead has
started using what it added — otherwise hiding is the safe way back.

The model sees the configuration and the catalogue, never a customer record.
"""
import copy
import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

import crm_ai
import crm_automation as automation
import crm_builder
import crm_schema
import crm_security
import pipecat_server as core
from crm_routes import pipeline as pipeline_routes
from crm_security import current_actor

router = APIRouter()

REQUEST_MAX = 2000
KEEP_CHANGE_SETS = 100
_RECORDS = {"lead": "leads", "customer": "customers", "policy": "policies"}


def _company() -> str:
    return crm_security.current_company_id()


def _config(db: Dict[str, Any]) -> Dict[str, Any]:
    stages = core.normalized_pipeline(((db.get("settings") or {}).get("crm") or {}).get("pipeline"))
    return crm_builder.config_from(db.get("settings") or {}, stages)


def _rule_checker(db: Dict[str, Any]):
    """Checks an add_automation against the change set's configuration so far."""
    people = [u.get("name") for u in db.get("users", []) if u.get("status", "Active") == "Active"]

    def check(config: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            rule = automation.validate_rule(data, people, [s["name"] for s in config["pipeline"]], list(core.CALL_OUTCOMES),
                                            extra_fields=core.custom_rule_fields(db, config["customFields"]["lead"]))
            for condition in rule["conditions"]:
                if condition.get("definition"):
                    crm_schema.check_condition(condition["definition"], condition["operator"], condition["value"])
        except (automation.RuleError, crm_schema.SchemaError) as exc:
            raise crm_builder.BuilderError(str(exc))
        return rule
    return check


def _vocabulary(db: Dict[str, Any]) -> Dict[str, Any]:
    return {"triggers": {k: {"label": v["label"], "params": [p["name"] for p in v.get("params", [])]}
                         for k, v in automation.TRIGGERS.items()},
            "actions": {k: v["label"] for k, v in automation.ACTIONS.items()},
            "leadFields": [f["field"] for f in automation.FIELDS["lead"] if not f.get("legacy")]
                          + [f["field"] for f in core.custom_rule_fields(db)["lead"]],
            "operators": [o["op"] for o in automation.OPERATORS],
            "callOutcomes": list(core.CALL_OUTCOMES)}


def _store_change_set(db: Dict[str, Any], change_set: Dict[str, Any]) -> Dict[str, Any]:
    sets = db.setdefault("builderChangeSets", [])
    sets.insert(0, change_set)
    del sets[KEEP_CHANGE_SETS:]
    core.audit(db, "Customization Proposed", "Change Set", change_set["id"],
               {"source": change_set["source"], "request": change_set.get("request", ""), "operations": len(change_set["operations"])})
    core.save_db(db)
    return change_set


def _new_change_set(db: Dict[str, Any], operations: Any, source: str, request: str = "", summary: str = "",
                    questions: List[str] = ()) -> Dict[str, Any]:
    if operations:
        try:
            _, results = crm_builder.check(_config(db), operations, _rule_checker(db))
        except crm_builder.BuilderError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
    else:
        results = []
    return {"id": f"CHG_{uuid.uuid4().hex[:10]}", "source": source, "request": request,
            "summary": summary, "questions": list(questions), "operations": operations or [], "results": results,
            "ready": bool(results) and all(r["ok"] for r in results), "status": "proposed",
            "proposedBy": current_actor("System"), "createdAt": datetime.utcnow().isoformat() + "Z"}


def _find(db: Dict[str, Any], id: str) -> Dict[str, Any]:
    return core._find_record(db.get("builderChangeSets", []), id, "Change set")


@router.get("/api/builder")
def builder_overview():
    db = core.load_db()
    return {"ai": crm_ai.status(_company()), "operations": crm_builder.CATALOGUE,
            "changeSets": db.get("builderChangeSets", [])[:20]}


@router.post("/api/builder/propose")
async def propose(payload: Dict[str, Any]):
    request = str(payload.get("request") or "").strip()
    if not request:
        raise HTTPException(status_code=422, detail="Describe the change you want")
    if len(request) > REQUEST_MAX:
        raise HTTPException(status_code=422, detail=f"Keep the request under {REQUEST_MAX} characters")
    reason = crm_ai.not_configured_reason()
    if reason:
        raise HTTPException(status_code=503, detail=f"{reason} You can still make every change under Settings.")
    db = core.load_db()
    answer = await crm_ai.complete(_company(), [
        {"role": "system", "content": crm_builder.prompt(_config(db), _vocabulary(db))},
        {"role": "user", "content": "===== THE OWNER'S REQUEST =====\n" + request + "\n===== END OF REQUEST ====="}],
        title="InsureCRM Builder", max_tokens=1500)
    if answer is None:
        raise HTTPException(status_code=502, detail=crm_ai.last_error(_company()) or "The AI model didn't answer")
    try:
        reply = crm_builder.parse_reply(answer)
    except crm_builder.BuilderError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    db = core.load_db()
    return _store_change_set(db, _new_change_set(db, reply["operations"], "ai", request, reply["summary"], reply["questions"]))


@router.post("/api/builder/changesets")
def create_change_set(payload: Dict[str, Any]):
    """A change set written by hand: the same checks, preview and undo, with no AI involved."""
    db = core.load_db()
    if not payload.get("operations"):
        raise HTTPException(status_code=422, detail="The change set has no operations")
    return _store_change_set(db, _new_change_set(db, payload["operations"], "manual", "", str(payload.get("summary") or "")))


def _write_config(db: Dict[str, Any], config: Dict[str, Any]) -> None:
    settings = db.setdefault("settings", {})
    settings["customFields"] = copy.deepcopy(config["customFields"])
    settings["customFieldsVersion"] = int(settings.get("customFieldsVersion") or 0) + 1
    crm = settings.setdefault("crm", {})
    crm["insuranceProducts"], crm["leadSources"] = list(config["products"]), list(config["leadSources"])
    pipeline_routes._store(db, config["pipeline"])
    for field in config["customFields"]["lead"]:
        core.refresh_rule_definitions(db, "lead", field)


@router.post("/api/builder/changesets/{id}/apply")
def apply_change_set(id: str):
    db = core.load_db()
    change_set = _find(db, id)
    if change_set["status"] != "proposed":
        raise HTTPException(status_code=409, detail=f"This change set is already {change_set['status']}")
    before = _config(db)
    try:
        after, results = crm_builder.check(before, change_set["operations"], _rule_checker(db))
    except crm_builder.BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not all(r["ok"] for r in results):
        change_set.update({"results": results, "ready": False})
        core.save_db(db)
        raise HTTPException(status_code=409, detail="The CRM changed since this was proposed, and some of it no longer "
                            "applies: " + "; ".join(r["error"] for r in results if not r["ok"]))
    _write_config(db, after)
    actor = current_actor("System")
    added_rules = []
    for validated in after["automations"]:
        rule = automation.new_rule(validated, f"{actor} (Customize with AI)" if change_set["source"] == "ai" else actor)
        rule["order"] = max((r.get("order", 0) for r in db.get("automationRules", [])), default=-1) + 1
        db.setdefault("automationRules", []).append(rule)
        added_rules.append({"id": rule["id"], "updatedAt": rule["updatedAt"]})
    change_set.update({"status": "applied", "results": results, "appliedBy": actor,
                       "appliedAt": datetime.utcnow().isoformat() + "Z", "before": before,
                       "afterFingerprint": crm_builder.fingerprint(_config(db)), "addedRules": added_rules})
    core.audit(db, "Customization Applied", "Change Set", id, {"operations": [r["description"] for r in results]})
    core.save_db(db)
    return change_set


def _in_use(db: Dict[str, Any], change_set: Dict[str, Any]) -> List[str]:
    """What the change set added that records have started using since."""
    before = change_set["before"]
    uses = []
    for obj, collection in _RECORDS.items():
        old = {f["key"] for f in before["customFields"].get(obj, [])}
        for field in core.custom_field_defs(db, obj):
            if field["key"] not in old:
                count = sum(1 for r in db.get(collection, []) if (r.get("custom") or {}).get(field["key"]) is not None)
                if count:
                    uses.append(f"{count} {obj}{'s' if count != 1 else ''} have values in {field['label']}")
    old_stages = {s["name"] for s in before["pipeline"]}
    for stage in core.normalized_pipeline(((db.get("settings") or {}).get("crm") or {}).get("pipeline")):
        if stage["name"] not in old_stages:
            count = sum(1 for lead in db.get("leads", []) if lead.get("status") == stage["name"])
            if count:
                uses.append(f"{count} lead{'s are' if count != 1 else ' is'} in {stage['name']}")
    return uses


@router.post("/api/builder/changesets/{id}/undo")
def undo_change_set(id: str):
    db = core.load_db()
    change_set = _find(db, id)
    if change_set["status"] != "applied":
        raise HTTPException(status_code=409, detail="Only an applied change set can be undone")
    latest = next((c for c in db.get("builderChangeSets", []) if c["status"] == "applied"), None)
    if latest is not change_set:
        raise HTTPException(status_code=409, detail="Undo the most recent change set first")
    rules = {r["id"]: r for r in db.get("automationRules", [])}
    if crm_builder.fingerprint(_config(db)) != change_set["afterFingerprint"] or any(
            rules.get(r["id"], {}).get("updatedAt") != r["updatedAt"] for r in change_set["addedRules"]):
        raise HTTPException(status_code=409, detail="Settings have changed since this was applied, so undoing it "
                            "could undo someone else's work. Change it back under Settings instead.")
    uses = _in_use(db, change_set)
    if uses:
        raise HTTPException(status_code=409, detail="; ".join(uses) + ". Hide what you no longer want instead.")
    _write_config(db, change_set["before"])
    added = {r["id"] for r in change_set["addedRules"]}
    db["automationRules"] = [r for r in db.get("automationRules", []) if r.get("id") not in added]
    change_set.update({"status": "undone", "undoneBy": current_actor("System"), "undoneAt": datetime.utcnow().isoformat() + "Z"})
    core.audit(db, "Customization Undone", "Change Set", id, {"operations": len(change_set["operations"])})
    core.save_db(db)
    return change_set


# ─── Setup templates (plan, phase 4) ─────────────────────────────────────────
@router.get("/api/builder/template")
def download_template():
    """The company's setup as a file: fields, stages, products, sources and rules — no records,
    no people. Rules that assign leads to named people stay behind."""
    db = core.load_db()
    template = crm_builder.export_template(_config(db), db.get("automationRules", []))
    core.audit(db, "Setup Exported", "Change Set", "template", {"fields": sum(len(v) for v in template["customFields"].values())})
    core.save_db(db)
    return template


@router.post("/api/builder/template")
def import_template(payload: Dict[str, Any]):
    """Start from another company's setup: what it has and this company lacks becomes a change
    set, previewed and applied like any other."""
    db = core.load_db()
    try:
        operations = crm_builder.template_operations(_config(db), payload.get("template"),
                                                     [r.get("name", "") for r in db.get("automationRules", [])])
    except crm_builder.BuilderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not operations:
        raise HTTPException(status_code=409, detail="This company already has everything in that setup")
    change_set = _new_change_set(db, operations, "template", "", "Start from a setup file")
    return _store_change_set(db, change_set)
