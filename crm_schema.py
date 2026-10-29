"""Company configuration: custom fields and stage categories (docs/AI_CUSTOMIZATION_PLAN.md).

A company shapes its CRM with data, not code. This module owns the rules for that data:
which field types exist, what a valid field definition is, how a value typed into a form,
a spreadsheet or a webhook is checked and normalised, and how a company's own lead stages
map onto the categories the workflows depend on. Pure functions, no I/O — the server
stores the configuration and calls these on save, so every entry path gets the same rules.

Custom values live under ``record["custom"][key]``, apart from system fields, so a company
field can never overwrite one the calls, renewals or commission code relies on.

| Type | Stored as | Accepts |
| --- | --- | --- |
| text | str (≤ 500) | any text |
| long_text | str (≤ 5,000) | any text |
| number | int or float | 12, 12.5, "1,200" |
| currency | float, 2 decimals | 12500, "₹ 12,500.50" |
| date | "YYYY-MM-DD" | ISO date |
| datetime | ISO 8601 text | ISO date-time |
| boolean | bool | true/false, yes/no, 1/0 |
| choice | one option, as defined | an option, any letter case |
| multi_choice | list of options | a list, or "a, b" / "a; b" from a spreadsheet |
| phone | "+digits" or "digits" (7–15 digits) | spaces, dashes, brackets ignored |
| email | lower-case address | name@domain.tld |
| lookup | record id | the id of a record of the field's target type |
| file | document id | the id of an uploaded document |

An empty value ("", None, []) clears the field. Nothing is ever invented: a value that
can't be read is an error, never a guess.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

OBJECTS = ("lead", "customer", "policy")
# Objects whose custom fields the CRM reads and writes so far (plan, phase 1). The others follow.
ENABLED_OBJECTS = ("lead", "customer", "policy")
# A company's own record types (e.g. a vehicle inspection attached to a lead) have keys like
# these, and never one of the CRM's own record or collection names.
RECORD_TYPE_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
RESERVED_RECORD_TYPES = frozenset(OBJECTS) | {"renewal", "quotation", "task", "note", "deal", "contact", "organization",
                                              "document", "user", "call", "communication", "calendar", "record", "custom"}
RECORD_PARENTS = ("lead", "customer", "policy")
# What every record of a company record type carries besides its fields.
RECORD_SYSTEM_FIELDS = frozenset({"id", "type", "parentType", "parentId", "custom", "createdAt", "createdBy",
                                  "updatedAt", "updatedBy"})

# Records whose product decides which product-limited fields apply. Customers have no product.
PRODUCT_FIELD = {"lead": "product", "policy": "policyType"}
LOOKUP_TARGETS = ("lead", "customer", "policy", "renewal", "quotation", "task")

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RECORD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")

MAX_FIELDS_PER_OBJECT = 100
# Roles that write records (crm_security.ROLES); a field can be limited to some of them.
EDITING_ROLES = ("admin", "manager", "telecaller")
MAX_OPTIONS = 100
LABEL_MAX = 60
OPTION_MAX = 80
HELP_MAX = 200

# Field names the CRM's own code reads. A custom key may not resemble one ("expiry_date"
# and "expiryDate" would be indistinguishable in a rule or a report column).
SYSTEM_FIELDS: Dict[str, frozenset] = {
    "lead": frozenset({
        "id", "name", "salutation", "firstName", "lastName", "email", "mobile", "phone", "city",
        "organization", "organizationId", "product", "policyType", "premium", "expiryDate",
        "nextAction", "nextActionDate", "nextActionTime", "nextActionTaskId", "status", "statusHistory",
        "assignedTo", "assignedToId", "leadPriority", "leadSource", "source", "sourceDetail",
        "originalSource", "notes", "vehicleDetails", "healthDetails", "existingPolicy", "leadDate",
        "soldAt", "closeReason", "convertedCustomerId", "convertedPolicyId", "custom", "customFields",
        "createdAt", "lastModified"}),
    "customer": frozenset({
        "id", "name", "email", "mobile", "phone", "city", "preferences", "organization",
        "organizationId", "sourceLeadId", "status", "assignedTo", "assignedToId", "custom",
        "createdAt", "lastModified"}),
    "policy": frozenset({
        "id", "leadId", "customerId", "organizationId", "customerName", "organization", "policyType",
        "product", "policyNumber", "insurer", "sumInsured", "premium", "taxRate", "startDate",
        "expiryDate", "status", "issuanceStatus", "assignedTo", "assignedToId", "soldAt",
        "commission", "custom", "createdAt", "lastModified"}),
}


class SchemaError(ValueError):
    """A definition or value that breaks the rules. The message is shown to the person."""


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip()) or (isinstance(value, (list, tuple)) and not value)


# ─── Value readers, one per type ─────────────────────────────────────────────
def _text(limit: int) -> Callable[[Dict[str, Any], Any], str]:
    def read(defn: Dict[str, Any], value: Any) -> str:
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise SchemaError("must be text")
        text = str(value).strip()
        if len(text) > limit:
            raise SchemaError(f"must be at most {limit:,} characters")
        return text
    return read


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise SchemaError("must be a number")
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
    elif isinstance(value, str):
        cleaned = re.sub(r"[\s,₹]", "", value).removeprefix("Rs.").removeprefix("INR")
        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            raise SchemaError("must be a number")
    else:
        raise SchemaError("must be a number")
    if not number.is_finite():
        raise SchemaError("must be a number")
    return number


def _bounded(defn: Dict[str, Any], number: Decimal) -> Decimal:
    if defn.get("min") is not None and number < Decimal(str(defn["min"])):
        raise SchemaError(f"must be at least {defn['min']}")
    if defn.get("max") is not None and number > Decimal(str(defn["max"])):
        raise SchemaError(f"must be at most {defn['max']}")
    return number


def _number(defn: Dict[str, Any], value: Any):
    number = _bounded(defn, _decimal(value))
    return int(number) if number == number.to_integral_value() else float(number)


def _currency(defn: Dict[str, Any], value: Any) -> float:
    number = _bounded(defn, _decimal(value))
    if defn.get("min") is None and number < 0:
        raise SchemaError("can't be negative")
    return float(number.quantize(Decimal("0.01")))


def _date(defn: Dict[str, Any], value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise SchemaError("must be a date (YYYY-MM-DD)")


def _datetime(defn: Dict[str, Any], value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).isoformat()
    except ValueError:
        raise SchemaError("must be a date and time")


_TRUE = {"true", "yes", "y", "1"}
_FALSE = {"false", "no", "n", "0"}


def _boolean(defn: Dict[str, Any], value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise SchemaError("must be yes or no")


def _option(defn: Dict[str, Any], value: Any) -> str:
    wanted = str(value).strip().lower()
    match = next((o for o in defn.get("options") or [] if o.lower() == wanted), None)
    if match is None:
        raise SchemaError(f"'{value}' is not one of the choices")
    return match


def _choice(defn: Dict[str, Any], value: Any) -> str:
    if isinstance(value, (list, dict, bool)):
        raise SchemaError("must be one of the choices")
    return _option(defn, value)


def _multi_choice(defn: Dict[str, Any], value: Any) -> List[str]:
    # "a, b" from a form or spreadsheet; "a; b" is how the export writes them, so it reads back.
    items = re.split(r"[,;]", value) if isinstance(value, str) else value
    if not isinstance(items, (list, tuple)):
        raise SchemaError("must be a list of choices")
    chosen = [_option(defn, item) for item in items if not _empty(item)]
    return list(dict.fromkeys(chosen))


def _phone(defn: Dict[str, Any], value: Any) -> str:
    text = str(value).strip()
    if isinstance(value, bool) or re.search(r"[^\d\s()+.-]", text) or text.count("+") > (1 if text.startswith("+") else 0):
        raise SchemaError("must be a phone number")
    digits = re.sub(r"\D", "", text)
    if not 7 <= len(digits) <= 15:
        raise SchemaError("must be a phone number of 7 to 15 digits")
    return ("+" if text.startswith("+") else "") + digits


def _email(defn: Dict[str, Any], value: Any) -> str:
    text = str(value).strip().lower()
    if not EMAIL_RE.match(text):
        raise SchemaError("must be an email address")
    return text


def _record_id(defn: Dict[str, Any], value: Any) -> str:
    text = str(value).strip()
    if isinstance(value, bool) or not RECORD_ID_RE.match(text):
        raise SchemaError("must be the id of a record")
    return text


_TEXT_OPS = ["contains", "is", "is_not", "is_empty"]
_NUMBER_OPS = ["is", "is_not", "greater_than", "less_than", "is_empty"]
_EXACT_OPS = ["is", "is_not", "is_empty"]

# The closed list. `operators` uses crm_automation.OPERATORS names, so a custom field can be
# tested by a rule or a filter with no translation.
FIELD_TYPES: Dict[str, Dict[str, Any]] = {
    "text":         {"label": "Short text", "read": _text(500), "operators": _TEXT_OPS},
    "long_text":    {"label": "Long text", "read": _text(5000), "operators": ["contains", "is_empty"]},
    "number":       {"label": "Number", "read": _number, "operators": _NUMBER_OPS},
    "currency":     {"label": "Amount (₹)", "read": _currency, "operators": _NUMBER_OPS},
    "date":         {"label": "Date", "read": _date, "operators": _NUMBER_OPS},
    "datetime":     {"label": "Date and time", "read": _datetime, "operators": _NUMBER_OPS},
    "boolean":      {"label": "Yes / no", "read": _boolean, "operators": _EXACT_OPS},
    "choice":       {"label": "Pick one", "read": _choice, "operators": _EXACT_OPS},
    "multi_choice": {"label": "Pick several", "read": _multi_choice, "operators": ["contains", "is_empty"]},
    "phone":        {"label": "Phone", "read": _phone, "operators": _TEXT_OPS},
    "email":        {"label": "Email", "read": _email, "operators": _TEXT_OPS},
    "lookup":       {"label": "Link to a record", "read": _record_id, "operators": _EXACT_OPS},
    "file":         {"label": "Document", "read": _record_id, "operators": ["is_empty"]},
}

# A type change keeps stored values readable only in these directions.
COMPATIBLE_TYPE_CHANGES = {("text", "long_text"), ("long_text", "text"), ("choice", "multi_choice")}


def type_catalogue() -> List[Dict[str, Any]]:
    """What the settings screen and the AI builder may offer."""
    return [{"type": key, "label": spec["label"], "operators": list(spec["operators"])}
            for key, spec in FIELD_TYPES.items()]


# ─── Field definitions ───────────────────────────────────────────────────────
def check_field(obj: str, defn: Dict[str, Any], existing: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Validate a field definition against the object's other fields; return it cleaned.
    ``obj`` is a built-in record type or the key of one of the company's own."""
    if obj not in OBJECTS and (not RECORD_TYPE_KEY_RE.match(obj) or obj in RESERVED_RECORD_TYPES):
        raise SchemaError(f"Fields can't be added to '{obj}'")
    if not isinstance(defn, dict):
        raise SchemaError("A field definition must be an object")
    others = list(existing)
    if len(others) >= MAX_FIELDS_PER_OBJECT:
        raise SchemaError(f"A {obj} can have at most {MAX_FIELDS_PER_OBJECT} custom fields")

    key = str(defn.get("key") or "").strip()
    if not KEY_RE.match(key):
        raise SchemaError("A field key starts with a letter and uses only lower-case letters, digits and _ (up to 40)")
    if _squash(key) in {_squash(name) for name in SYSTEM_FIELDS.get(obj, RECORD_SYSTEM_FIELDS)}:
        raise SchemaError(f"'{key}' is a built-in {obj} field")
    if any(_squash(f.get("key", "")) == _squash(key) for f in others):
        raise SchemaError(f"A {obj} field called '{key}' already exists")

    label = str(defn.get("label") or "").strip()
    if not label or len(label) > LABEL_MAX:
        raise SchemaError(f"A field needs a label of up to {LABEL_MAX} characters")
    if any(str(f.get("label", "")).strip().lower() == label.lower() for f in others):
        raise SchemaError(f"Another {obj} field is already labelled '{label}'")

    field_type = defn.get("type")
    if field_type not in FIELD_TYPES:
        raise SchemaError(f"'{field_type}' is not a field type")

    clean: Dict[str, Any] = {"key": key, "label": label, "type": field_type,
                             "required": bool(defn.get("required", False)), "hidden": bool(defn.get("hidden", False))}
    for attr, limit in (("section", LABEL_MAX), ("help", HELP_MAX)):
        text = str(defn.get(attr) or "").strip()
        if len(text) > limit:
            raise SchemaError(f"The {attr} must be at most {limit} characters")
        if text:
            clean[attr] = text

    if field_type in ("choice", "multi_choice"):
        options = defn.get("options")
        if not isinstance(options, list) or not options:
            raise SchemaError("A choice field needs at least one option")
        if len(options) > MAX_OPTIONS:
            raise SchemaError(f"A choice field can have at most {MAX_OPTIONS} options")
        cleaned = [str(o).strip() for o in options if isinstance(o, (str, int, float)) and not isinstance(o, bool)]
        if len(cleaned) != len(options) or any(not o or len(o) > OPTION_MAX for o in cleaned):
            raise SchemaError(f"Each option needs a name of up to {OPTION_MAX} characters")
        if len({o.lower() for o in cleaned}) != len(cleaned):
            raise SchemaError("Two options have the same name")
        clean["options"] = cleaned
    elif defn.get("options"):
        raise SchemaError("Only choice fields have options")

    if field_type == "lookup":
        if defn.get("target") not in LOOKUP_TARGETS:
            raise SchemaError("A link field must say which kind of record it links to")
        clean["target"] = defn["target"]

    if field_type in ("number", "currency"):
        for bound in ("min", "max"):
            if defn.get(bound) is not None:
                clean[bound] = _number({}, defn[bound])
        if clean.get("min") is not None and clean.get("max") is not None and clean["min"] > clean["max"]:
            raise SchemaError("The minimum is above the maximum")

    editable = defn.get("editableBy")
    if editable:
        if not isinstance(editable, list) or any(role not in EDITING_ROLES for role in editable):
            raise SchemaError(f"Who can change a field is any of: {', '.join(EDITING_ROLES)}")
        clean["editableBy"] = [role for role in EDITING_ROLES if role in editable]

    products = defn.get("products")
    if products and obj not in PRODUCT_FIELD:
        raise SchemaError(f"A {obj} has no product, so its fields can't be limited to products")
    if products:
        if not isinstance(products, list) or not all(isinstance(p, str) and p.strip() for p in products):
            raise SchemaError("Products must be a list of product names")
        clean["products"] = list(dict.fromkeys(p.strip() for p in products))
    return clean


def check_record_type(definition: Any, existing: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """A company record type: a key, a label and the record it hangs from."""
    if not isinstance(definition, dict):
        raise SchemaError("A record type needs a name and what it is attached to")
    label = str(definition.get("label") or "").strip()
    if not label or len(label) > LABEL_MAX:
        raise SchemaError(f"A record type needs a name of up to {LABEL_MAX} characters")
    key = str(definition.get("key") or re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")[:30]).strip()
    if not RECORD_TYPE_KEY_RE.match(key) or key in RESERVED_RECORD_TYPES:
        raise SchemaError(f"'{key}' can't be used as a record type's key")
    others = list(existing)
    if any(t["key"] == key for t in others) or any(t["label"].lower() == label.lower() for t in others):
        raise SchemaError(f"There is already a record type called '{label}'")
    if definition.get("parent") not in RECORD_PARENTS:
        raise SchemaError(f"A record type is attached to a {', a '.join(RECORD_PARENTS)}")
    return {"key": key, "label": label, "parent": definition["parent"], "hidden": bool(definition.get("hidden", False))}


def check_field_change(obj: str, before: Dict[str, Any], after: Dict[str, Any],
                       existing: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """Validate an edit to an existing field. The key never changes, because stored values
    are filed under it; the type changes only where every stored value stays readable."""
    if after.get("key", before["key"]) != before["key"]:
        raise SchemaError("A field's key can't be changed; change its label instead")
    merged = {**before, **after, "key": before["key"]}
    if merged["type"] != before["type"] and (before["type"], merged["type"]) not in COMPATIBLE_TYPE_CHANGES:
        raise SchemaError(f"A {FIELD_TYPES[before['type']]['label'].lower()} field can't become "
                          f"{FIELD_TYPES.get(merged['type'], {}).get('label', merged['type']).lower()}; add a new field instead")
    if before["type"] == "lookup" and merged.get("target") != before.get("target"):
        raise SchemaError("A link field can't be pointed at a different kind of record")
    return check_field(obj, merged, [f for f in existing if f.get("key") != before["key"]])


def removed_options(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    """Options an edit takes away. The server counts records still using them before saving."""
    kept = {o.lower() for o in after.get("options") or []}
    return [o for o in before.get("options") or [] if o.lower() not in kept]


def applies_to(defn: Dict[str, Any], product: Optional[str]) -> bool:
    """A field limited to some products is shown and required only on records of those products."""
    products = defn.get("products")
    return not products or (product or "").strip().lower() in {p.lower() for p in products}


# ─── Values ──────────────────────────────────────────────────────────────────
def read_value(defn: Dict[str, Any], value: Any) -> Any:
    """Check and normalise one value. Empty means cleared and returns None."""
    if _empty(value):
        return None
    return FIELD_TYPES[defn["type"]]["read"](defn, value)


def clean_custom(defs: Iterable[Dict[str, Any]], values: Optional[Dict[str, Any]],
                 existing: Optional[Dict[str, Any]] = None, creating: bool = False,
                 product: Optional[str] = None, role: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Merge submitted custom values into a record's existing ones.

    Returns ``(custom, errors)``. ``errors`` maps a field key to a message; when it is not
    empty nothing should be saved. Values of fields since hidden or removed are kept as they
    were — data is never dropped because a field was tidied away — but can't be written.
    ``role`` is the writer's; a field limited to other roles refuses a *change* from them
    (a form sending back the value already there is not one).
    """
    by_key = {d["key"]: d for d in defs}
    merged = dict(existing or {})
    errors: Dict[str, str] = {}
    if values is not None and not isinstance(values, dict):
        return merged, {"custom": "Custom values must be an object"}
    for key, value in (values or {}).items():
        defn = by_key.get(key)
        if defn is None:
            errors[key] = f"'{key}' is not a field"
            continue
        if defn.get("hidden"):
            errors[key] = f"{defn['label']} is hidden and can't be changed"
            continue
        try:
            cleaned = read_value(defn, value)
        except SchemaError as exc:
            errors[key] = f"{defn['label']} {exc}"
            continue
        if role and defn.get("editableBy") and role not in defn["editableBy"] and cleaned != merged.get(key):
            who = " and ".join({"admin": "the Owner / Admin", "manager": "Managers", "telecaller": "Telecallers"}[r]
                               for r in defn["editableBy"])
            errors[key] = f"{defn['label']} can only be changed by {who}"
            continue
        if cleaned is None:
            merged.pop(key, None)
        else:
            merged[key] = cleaned
    for defn in by_key.values():
        if not defn.get("required") or defn.get("hidden") or not applies_to(defn, product):
            continue
        touched = defn["key"] in (values or {})
        if (creating or touched) and _empty(merged.get(defn["key"])) and defn["key"] not in errors:
            errors[defn["key"]] = f"{defn['label']} is required"
    return merged, errors


# ─── Comparing values (list filters and automation conditions) ───────────────
def _comparable(defn: Dict[str, Any], value: Any):
    """A value in a form that orders correctly for its type, or None if it can't be read."""
    try:
        cleaned = read_value(defn, value)
    except SchemaError:
        return None
    if cleaned is None:
        return None
    if defn["type"] in ("number", "currency"):
        return Decimal(str(cleaned))
    if defn["type"] == "datetime":
        moment = datetime.fromisoformat(cleaned)
        return moment.replace(tzinfo=None) if moment.tzinfo is None else moment.astimezone().replace(tzinfo=None)
    if isinstance(cleaned, str):
        return cleaned.lower()
    return cleaned


def check_condition(defn: Dict[str, Any], operator: str, value: Any) -> None:
    """A filter or rule must use an operator the field's type offers, and a value it can read."""
    if operator not in FIELD_TYPES[defn["type"]]["operators"]:
        raise SchemaError(f"{defn['label']} can't be compared with '{operator}'")
    if operator == "is_empty" or (operator == "contains" and defn["type"] in ("text", "long_text", "phone", "email")):
        return
    # A multi-choice field is compared with one of its options; bounds limit values, not comparisons.
    probe = {**defn, "type": "choice" if defn["type"] == "multi_choice" else defn["type"], "min": None, "max": None}
    try:
        cleaned = read_value(probe, value)
    except SchemaError as exc:
        raise SchemaError(f"{defn['label']} {exc}")
    if cleaned is None:
        raise SchemaError(f"Give a value to compare {defn['label']} with")


def matches(defn: Dict[str, Any], stored: Any, operator: str, expected: Any) -> bool:
    """Does a stored custom value satisfy ``operator expected``? Typed: numbers compare as
    numbers, dates as dates, a multi-choice field "contains" one of its options."""
    if operator == "is_empty":
        return _empty(stored)
    if _empty(stored) or operator not in FIELD_TYPES[defn["type"]]["operators"]:
        return False
    kind = defn["type"]
    if kind == "multi_choice":
        wanted = str(expected).strip().lower()
        return any(str(item).lower() == wanted for item in stored)
    if kind in ("text", "long_text", "email") or (kind == "phone" and operator == "contains"):
        left, right = str(stored).strip().lower(), str(expected).strip().lower()
        if kind == "phone":
            left, right = re.sub(r"\D", "", left), re.sub(r"\D", "", right)
        return {"contains": right in left, "is": left == right, "is_not": left != right}[operator]
    probe = {**defn, "min": None, "max": None}
    left, right = _comparable(probe, stored), _comparable(probe, expected)
    if left is None or right is None:
        return False
    try:
        return {"is": left == right, "is_not": left != right,
                "greater_than": left > right, "less_than": left < right}[operator]
    except TypeError:
        return False


def display_value(defn: Dict[str, Any], stored: Any) -> Any:
    """How a value reads in a spreadsheet column or on a card."""
    if _empty(stored):
        return ""
    if defn["type"] == "boolean":
        return "Yes" if stored else "No"
    if defn["type"] == "multi_choice":
        return "; ".join(str(item) for item in stored)
    return stored


# ─── Stage categories (decision D2) ──────────────────────────────────────────
# Workflows test a stage's category, never its name, so a company can rename or add stages.
STAGE_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "working": {"label": "Being worked", "finished": False, "nextAction": True, "reason": False},
    "parked":  {"label": "Parked", "finished": False, "nextAction": False, "reason": False},
    "won":     {"label": "Finished — sold", "finished": True, "nextAction": False, "reason": False},
    "lost":    {"label": "Finished — not sold", "finished": True, "nextAction": False, "reason": True},
}

# Today's thirteen statuses, expressed as a pipeline. Must agree with the server's
# CLOSED_STATUSES, NO_NEXT_ACTION and REASON_REQUIRED (tests/test_crm_schema.py checks it).
DEFAULT_LEAD_PIPELINE: List[Dict[str, str]] = [
    {"name": "New", "category": "working"}, {"name": "Assigned", "category": "working"},
    {"name": "Contacted", "category": "working"}, {"name": "Interested", "category": "working"},
    {"name": "Quote Sent", "category": "working"}, {"name": "Follow-up", "category": "working"},
    {"name": "Documents Pending", "category": "working"}, {"name": "Policy Sold", "category": "won"},
    {"name": "Not Interested", "category": "lost"}, {"name": "Call Later", "category": "working"},
    {"name": "Wrong Number", "category": "parked"}, {"name": "Unreachable", "category": "working"},
    {"name": "Lost", "category": "lost"},
]

MAX_STAGES = 30


def check_pipeline(stages: Any) -> List[Dict[str, str]]:
    """A pipeline needs a first stage that is being worked, a way to win and a way to lose."""
    if not isinstance(stages, list) or not stages:
        raise SchemaError("A pipeline needs at least one stage")
    if len(stages) > MAX_STAGES:
        raise SchemaError(f"A pipeline can have at most {MAX_STAGES} stages")
    clean: List[Dict[str, str]] = []
    for stage in stages:
        name = str((stage or {}).get("name") or "").strip() if isinstance(stage, dict) else ""
        category = stage.get("category") if isinstance(stage, dict) else None
        if not name or len(name) > LABEL_MAX:
            raise SchemaError(f"Each stage needs a name of up to {LABEL_MAX} characters")
        if category not in STAGE_CATEGORIES:
            raise SchemaError(f"Stage '{name}' needs a category: {', '.join(STAGE_CATEGORIES)}")
        if any(s["name"].lower() == name.lower() for s in clean):
            raise SchemaError(f"Two stages are called '{name}'")
        clean.append({"name": name, "category": category})
    if clean[0]["category"] != "working":
        raise SchemaError("The first stage must be one that is being worked")
    for needed in ("won", "lost"):
        if not any(s["category"] == needed for s in clean):
            raise SchemaError(f"A pipeline needs at least one '{STAGE_CATEGORIES[needed]['label']}' stage")
    return clean


def stages_in(pipeline: Iterable[Dict[str, str]], *, finished: Optional[bool] = None,
              next_action: Optional[bool] = None, reason: Optional[bool] = None,
              category: Optional[str] = None) -> set:
    """Stage names matching a category property, e.g. every stage that needs a reason."""
    names = set()
    for stage in pipeline:
        spec = STAGE_CATEGORIES[stage["category"]]
        if ((category is None or stage["category"] == category)
                and (finished is None or spec["finished"] == finished)
                and (next_action is None or spec["nextAction"] == next_action)
                and (reason is None or spec["reason"] == reason)):
            names.add(stage["name"])
    return names
