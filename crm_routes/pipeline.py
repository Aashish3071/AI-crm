"""Lead stages (docs/AI_CUSTOMIZATION_PLAN.md, decision D2).

The thirteen system stages keep their names, because call outcomes, quotations, renewals and
reports move leads between them by name; an Owner / Admin can relabel them, reorder them and
hide them from the pickers. A company adds its own stages beside them, each in a category —
being worked (needs a next action), parked (no next action, still open) or finished without
a sale (needs a reason). Workflows test the category, so a company stage behaves like the
system stages of its category everywhere. Only "Policy Sold" is a sale: it is what opens the
customer and the policy.

Renaming a company stage carries its leads, their status history and automation rules along.
A stage still in use can't be deleted or change category; the refusal says how many leads or
rules use it. The order and categories are checked with crm_schema.check_pipeline.
"""
import re
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

import crm_schema
import pipecat_server as core

router = APIRouter()

# The categories a company's own stage may take. A sale stays the system's.
CUSTOM_CATEGORIES = ("working", "parked", "lost")
NAME_MAX = 40
# Names appear in screens, filters and spreadsheet cells; keep them to plain words.
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 &/()+.-]*$")


def _stages(db: Dict[str, Any]) -> List[Dict[str, Any]]:
    return core.normalized_pipeline(((db.get("settings") or {}).get("crm") or {}).get("pipeline"))


def _store(db: Dict[str, Any], stages: List[Dict[str, Any]]) -> None:
    try:
        crm_schema.check_pipeline([{"name": s["name"], "category": s["category"]} for s in stages])
    except crm_schema.SchemaError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.setdefault("settings", {}).setdefault("crm", {})["pipeline"] = [
        {k: s[k] for k in ("name", "category", "label", "hidden") if s.get(k) not in (None, "", False)} for s in stages]
    core._use_pipeline(db)


def _lead_count(db: Dict[str, Any], name: str) -> int:
    return sum(1 for lead in db.get("leads", []) if lead.get("status") == name)


def _rule_count(db: Dict[str, Any], name: str) -> int:
    def uses(rule):
        params = [(rule.get("trigger") or {}).get("params") or {}] + [a.get("params") or {} for a in rule.get("actions") or []]
        return any(p.get("to") == name or p.get("status") == name for p in params)
    return sum(1 for rule in db.get("automationRules", []) if uses(rule))


def _checked_name(db: Dict[str, Any], name: Any, ignore: str = "") -> str:
    name = str(name or "").strip()
    if not name or len(name) > NAME_MAX:
        raise HTTPException(status_code=422, detail=f"A stage needs a name of up to {NAME_MAX} characters")
    if not NAME_RE.match(name):
        raise HTTPException(status_code=422, detail="Use letters, digits, spaces and & / ( ) + . - in a stage name")
    taken = {s["name"].lower() for s in _stages(db) if s["name"] != ignore} | {s.get("label", "").lower() for s in _stages(db)
                                                                              if s["name"] != ignore and s.get("label")}
    if name.lower() in taken or name.lower() in {k.lower() for k in core.LEGACY_STATUSES}:
        raise HTTPException(status_code=422, detail=f"There is already a stage called '{name}'")
    return name


def _view(db: Dict[str, Any]) -> Dict[str, Any]:
    return {"stages": [{**s, "leadCount": _lead_count(db, s["name"])} for s in _stages(db)],
            "categories": [{"category": c, **crm_schema.STAGE_CATEGORIES[c]} for c in crm_schema.STAGE_CATEGORIES],
            "customCategories": list(CUSTOM_CATEGORIES)}


@router.get("/api/pipeline")
def get_pipeline():
    return _view(core.load_db())


@router.post("/api/pipeline/stages")
def add_stage(payload: Dict[str, Any]):
    db = core.load_db()
    name = _checked_name(db, payload.get("name"))
    category = payload.get("category")
    if category not in CUSTOM_CATEGORIES:
        raise HTTPException(status_code=422, detail="A new stage is being worked, parked, or finished without a sale")
    stages = _stages(db)
    after = payload.get("after")
    if after and after not in {s["name"] for s in stages}:
        raise HTTPException(status_code=422, detail=f"There is no stage called '{after}'")
    # By default a stage goes after the last one of its kind, so it lands among its peers.
    at = (next(i for i, s in enumerate(stages) if s["name"] == after) + 1 if after
          else max((i + 1 for i, s in enumerate(stages) if s["category"] == category), default=len(stages)))
    stages.insert(at, {"name": name, "category": category, "system": False})
    _store(db, stages)
    core.audit(db, "Lead Stage Added", "Lead Stage", name, {"category": category, "after": stages[at - 1]["name"] if at else ""})
    core.save_db(db)
    return _view(db)


# Declared before /stages/{name} so it is never read as a stage name.
@router.put("/api/pipeline/order")
def reorder_stages(payload: Dict[str, Any]):
    db = core.load_db()
    stages = _stages(db)
    names = payload.get("names")
    if not isinstance(names, list) or sorted(names) != sorted(s["name"] for s in stages):
        raise HTTPException(status_code=422, detail="Send every stage's name exactly once, in the new order")
    by_name = {s["name"]: s for s in stages}
    _store(db, [by_name[n] for n in names])
    core.audit(db, "Lead Stages Reordered", "Lead Stage", "pipeline",
               {"before": [s["name"] for s in stages], "after": names})
    core.save_db(db)
    return _view(db)


@router.put("/api/pipeline/stages/{name}")
def update_stage(name: str, changes: Dict[str, Any]):
    db = core.load_db()
    stages = _stages(db)
    stage = next((s for s in stages if s["name"] == name), None)
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    before = dict(stage)
    if "label" in changes:
        label = str(changes.get("label") or "").strip()
        stage["label"] = _checked_name(db, label, ignore=name) if label and label != name else ""
    if "hidden" in changes:
        stage["hidden"] = bool(changes["hidden"])
    if stage.get("system") and ({"name", "category"} & set(changes)):
        if changes.get("name", name) != name or changes.get("category", stage["category"]) != stage["category"]:
            raise HTTPException(status_code=422, detail="A system stage keeps its name and kind; give it a label instead")
    new_category = changes.get("category", stage["category"])
    if not stage.get("system") and new_category != stage["category"]:
        if new_category not in CUSTOM_CATEGORIES:
            raise HTTPException(status_code=422, detail="A stage is being worked, parked, or finished without a sale")
        in_use = _lead_count(db, name)
        if in_use:
            raise HTTPException(status_code=409, detail=(
                f"{in_use} lead{'s are' if in_use != 1 else ' is'} in {name}; changing what it means would change "
                "what they need. Move them first, or add a new stage."))
        stage["category"] = new_category
    new_name = changes.get("name", name)
    if not stage.get("system") and new_name != name:
        new_name = _checked_name(db, new_name, ignore=name)
        stage["name"] = new_name
        now = datetime.utcnow().isoformat() + "Z"
        for lead in db.get("leads", []):
            if lead.get("status") == name:
                lead["status"], lead["lastModified"] = new_name, now
            for step in lead.get("statusHistory") or []:
                if step.get("status") == name:
                    step["status"] = new_name
        for rule in db.get("automationRules", []):
            for params in [(rule.get("trigger") or {}).get("params") or {}] + [a.get("params") or {} for a in rule.get("actions") or []]:
                for key in ("to", "status"):
                    if params.get(key) == name:
                        params[key] = new_name
    _store(db, stages)
    core.audit(db, "Lead Stage Changed", "Lead Stage", stage["name"], {"before": before, "after": stage})
    core.save_db(db)
    return _view(db)


@router.delete("/api/pipeline/stages/{name}")
def delete_stage(name: str):
    db = core.load_db()
    stages = _stages(db)
    stage = next((s for s in stages if s["name"] == name), None)
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    if stage.get("system"):
        raise HTTPException(status_code=422, detail="System stages can be hidden, not deleted")
    leads, rules = _lead_count(db, name), _rule_count(db, name)
    if leads or rules:
        uses = " and ".join(part for part in (f"{leads} lead{'s' if leads != 1 else ''}" if leads else "",
                                              f"{rules} automation rule{'s' if rules != 1 else ''}" if rules else "") if part)
        raise HTTPException(status_code=409, detail=f"{uses} use {name}. Move them first, or hide the stage instead.")
    _store(db, [s for s in stages if s["name"] != name])
    core.audit(db, "Lead Stage Deleted", "Lead Stage", name, {"before": stage})
    core.save_db(db)
    return _view(db)
