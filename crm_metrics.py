"""Performance measures (client blueprint, slides 14, 26, 28–34 and 43).

Every number the dashboards, targets, leaderboard, incentives and reports show is
defined here once, so two screens can never disagree about what "connected calls" or
"conversion" means. Periods are inclusive ranges of dates in the company's time zone;
stored timestamps are UTC and converted before they are bucketed.

| Measure | Definition | Credited to |
| --- | --- | --- |
| newLeads | Leads whose enquiry arrived in the period | The lead's telecaller |
| calls | Calls with a recorded outcome, started in the period | Whoever made the call |
| connected | Of those, calls that reached the customer | Whoever made the call |
| avgCallSeconds | Mean length of connected calls with a known length | Whoever made the call |
| interested | Calls in the period whose outcome was Interested | Whoever made the call |
| quotesSent | Leads that reached Quote Sent in the period | The lead's telecaller at the time |
| policiesSold | Policies whose sale date is in the period | The policy's telecaller |
| premium | Net premium of those policies | The policy's telecaller |
| conversionRate | policiesSold ÷ newLeads, as a percentage | — |
| followUpsDue / followUpsDone / onTimeRate | Follow-ups that fell due in the period (up to now); how many were finished; how many by their due time | The follow-up's owner |
| renewalsClosed / renewalsLost | Renewals completed as renewed, or lost, in the period | The renewal's telecaller |
| documentsCollected | Documents uploaded in the period on the telecaller's leads | The lead's telecaller |
| commission | Commission earned on the policies sold in the period, as fixed at sale | The policy's telecaller |

A measure with nothing to divide by is ``None``, never zero or a placeholder: "no calls
yet" and "0% of calls connected" are different facts.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

MEASURES = ["newLeads", "calls", "connected", "notConnected", "avgCallSeconds", "interested", "quotesSent",
            "policiesSold", "premium", "conversionRate", "followUpsDue", "followUpsDone", "onTimeRate",
            "renewalsClosed", "renewalsLost", "documentsCollected"]


def local_day(stamp: Optional[str], tz) -> str:
    """The company-local date of a stored timestamp. Plain dates pass through unchanged."""
    text = str(stamp or "").strip()
    if not text:
        return ""
    if len(text) == 10:
        return text
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if moment.tzinfo is None:                          # stored without a zone: written as UTC
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).strftime("%Y-%m-%d")


def period_bounds(name: str, today: date, start: Optional[str] = None, end: Optional[str] = None) -> Tuple[str, str]:
    """today · week (Monday to today) · month (1st to today) · custom (start–end)."""
    if name == "custom":
        if not start or not end or start > end:
            raise ValueError("Choose a start date on or before the end date")
        return start, end
    if name == "week":
        return (today - timedelta(days=today.weekday())).isoformat(), today.isoformat()
    if name == "month":
        return today.replace(day=1).isoformat(), today.isoformat()
    return today.isoformat(), today.isoformat()


def _pct(part: float, whole: float) -> Optional[float]:
    return round(part * 100 / whole, 1) if whole else None


def _blank() -> Dict[str, Any]:
    return {"newLeads": 0, "calls": 0, "connected": 0, "notConnected": 0, "talkSeconds": 0, "timedCalls": 0,
            "interested": 0, "quotesSent": 0, "policiesSold": 0, "premium": 0.0, "followUpsDue": 0,
            "followUpsDone": 0, "followUpsOnTime": 0, "renewalsClosed": 0, "renewalsLost": 0, "documentsCollected": 0,
            "commission": 0.0, "productPolicies": {}, "sourcePolicies": {}, "sourcePremium": {}, "productPremium": {}}


def performance(db: Dict[str, Any], start: str, end: str, tz, money: Callable[[Any], float],
                due_moment: Callable[[Dict[str, Any], Any], Optional[datetime]],
                people: Optional[Iterable[str]] = None, now: Optional[datetime] = None) -> Dict[str, Dict[str, Any]]:
    """Measures for each person over [start, end]. Only the named people are returned when given."""
    now = now or datetime.now(tz)
    within = lambda stamp: start <= local_day(stamp, tz) <= end if stamp else False
    rows: Dict[str, Dict[str, Any]] = {}
    row = lambda person: rows.setdefault(person or "Unassigned", _blank())

    leads = {l.get("id"): l for l in db.get("leads", []) if isinstance(l, dict)}
    for lead in leads.values():
        if within(lead.get("leadDate")):
            row(lead.get("assignedTo"))["newLeads"] += 1
        for step in lead.get("statusHistory") or []:
            if step.get("status") == "Quote Sent" and within(step.get("at")):
                row(step.get("owner") or lead.get("assignedTo"))["quotesSent"] += 1

    for call in db.get("callLogs", []):
        if not isinstance(call, dict) or call.get("status") != "Completed" or not within(call.get("startedAt") or call.get("createdAt")):
            continue
        r = row(call.get("assignedTo"))
        r["calls"] += 1
        if call.get("connected"):
            r["connected"] += 1
            if call.get("durationSeconds") is not None:
                r["talkSeconds"] += int(call["durationSeconds"])
                r["timedCalls"] += 1
        else:
            r["notConnected"] += 1
        if call.get("outcome") == "Interested":
            r["interested"] += 1

    for policy in db.get("policies", []):
        if within(policy.get("saleDate")) and policy.get("status") != "Cancelled":
            r = row(policy.get("assignedTo"))
            amount = money(policy.get("netPremium", policy.get("premium", 0)))
            r["policiesSold"] += 1
            r["premium"] += amount
            r["commission"] += money((policy.get("commission") or {}).get("amount", 0))
            product, source = policy.get("policyType") or "", policy.get("leadSource") or ""
            for key, group, value in (("productPolicies", product, 1), ("sourcePolicies", source, 1),
                                      ("productPremium", product, amount), ("sourcePremium", source, amount)):
                r[key][group] = r[key].get(group, 0) + value

    for task in db.get("tasks", []):
        if task.get("status") == "Archived" or not task.get("dueDate") or not (start <= task["dueDate"] <= end):
            continue
        due = due_moment(task, tz)
        if not due or due > now:
            continue                                   # not yet due: neither done nor missed
        r = row(task.get("assignedTo"))
        r["followUpsDue"] += 1
        if task.get("status") == "Completed":
            r["followUpsDone"] += 1
            finished = task.get("completedAt")
            if finished:
                try:
                    if datetime.fromisoformat(finished.replace("Z", "+00:00")) <= due:
                        r["followUpsOnTime"] += 1
                except ValueError:
                    pass

    for renewal in db.get("renewals", []):
        if renewal.get("stage") == "Renewed" and within(renewal.get("completedAt")):
            row(renewal.get("assignedTo"))["renewalsClosed"] += 1
        elif renewal.get("stage") in ("Lost", "Lapsed") and within(renewal.get("updatedAt")):
            row(renewal.get("assignedTo"))["renewalsLost"] += 1

    for document in db.get("documents", []):
        lead = leads.get(document.get("associatedId"))
        if lead and within(document.get("createdAt")):
            row(lead.get("assignedTo"))["documentsCollected"] += 1

    wanted = list(people) if people is not None else list(rows)
    result = {}
    for person in wanted:
        r = rows.get(person) or _blank()
        r["premium"] = round(r["premium"], 2)
        r["commission"] = round(r["commission"], 2)
        r["avgCallSeconds"] = round(r["talkSeconds"] / r["timedCalls"]) if r["timedCalls"] else None
        r["connectRate"] = _pct(r["connected"], r["calls"])
        r["conversionRate"] = _pct(r["policiesSold"], r["newLeads"])
        r["onTimeRate"] = _pct(r["followUpsOnTime"], r["followUpsDue"])
        result[person] = r
    return result


def totals(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The team's figures, recomputed from counts rather than averaging percentages."""
    t = _blank()
    for r in rows.values():
        for key in t:
            if isinstance(t[key], dict):
                for group, value in (r.get(key) or {}).items():
                    t[key][group] = t[key].get(group, 0) + value
            else:
                t[key] += r.get(key, 0) or 0
    t["premium"] = round(t["premium"], 2)
    t["commission"] = round(t["commission"], 2)
    t["avgCallSeconds"] = round(t["talkSeconds"] / t["timedCalls"]) if t["timedCalls"] else None
    t["connectRate"] = _pct(t["connected"], t["calls"])
    t["conversionRate"] = _pct(t["policiesSold"], t["newLeads"])
    t["onTimeRate"] = _pct(t["followUpsOnTime"], t["followUpsDue"])
    return t


# ─── Targets (slide 29) ──────────────────────────────────────────────────────
TARGET_MEASURES = {"policiesSold": "Policies sold", "premium": "Premium (₹)", "calls": "Calls",
                   "renewalsClosed": "Renewals"}


def achievement(actual: Dict[str, Any], target: Dict[str, Any], headline: str) -> Dict[str, Any]:
    """Per-measure progress against target, and the headline figure the dashboards show."""
    parts = {}
    for key in TARGET_MEASURES:
        goal = target.get(key)
        if goal:
            parts[key] = {"target": goal, "actual": actual.get(key, 0), "percent": round((actual.get(key, 0) or 0) * 100 / goal, 1)}
    head = parts.get(headline) or next(iter(parts.values()), None)
    return {"measures": parts, "headline": headline if headline in parts else (next(iter(parts)) if parts else ""),
            "percent": head["percent"] if head else None}


# ─── Recognition (slides 28 and 30) ──────────────────────────────────────────
# Awards need enough to judge by: one sale from one lead is not "highest conversion".
MIN_LEADS_FOR_CONVERSION = 5
MIN_DUE_FOR_DISCIPLINE = 5

AWARDS = [
    ("mostPolicies", "Most policies sold", "policiesSold", None),
    ("highestPremium", "Highest premium", "premium", None),
    ("highestConversion", "Highest conversion", "conversionRate", ("newLeads", MIN_LEADS_FOR_CONVERSION)),
    ("bestFollowUp", "Best follow-up discipline", "onTimeRate", ("followUpsDue", MIN_DUE_FOR_DISCIPLINE)),
    ("bestRenewals", "Best renewal performer", "renewalsClosed", None),
]

# Slide 30's example weights. Call quality needs call reviews, which do not exist yet, so it
# is left out and the other weights are scaled up to fill its share.
DEFAULT_WEIGHTS = {"policiesSold": 40, "conversionRate": 25, "premium": 15, "onTimeRate": 10, "callQuality": 10}
AVAILABLE_FOR_SCORING = {"policiesSold", "conversionRate", "premium", "onTimeRate", "renewalsClosed"}
WEIGHT_LABELS = {"policiesSold": "Policies sold", "conversionRate": "Conversion", "premium": "Premium",
                 "onTimeRate": "Follow-ups on time", "renewalsClosed": "Renewals", "callQuality": "Call quality"}


def awards(rows: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """The named awards. Nobody wins a category with nothing in it, and ties are shared."""
    result = {}
    for key, label, measure, minimum in AWARDS:
        eligible = {p: r for p, r in rows.items() if r.get(measure) not in (None, 0)
                    and (minimum is None or (r.get(minimum[0]) or 0) >= minimum[1])}
        if not eligible:
            result[key] = {"label": label, "winners": [], "value": None,
                           "note": f"Needs at least {minimum[1]} {'new leads' if minimum[0] == 'newLeads' else 'follow-ups due'}" if minimum else "Nobody yet"}
            continue
        best = max(r[measure] for r in eligible.values())
        result[key] = {"label": label, "winners": sorted(p for p, r in eligible.items() if r[measure] == best), "value": best}
    return result


def scores(rows: Dict[str, Dict[str, Any]], weights: Dict[str, float]) -> Dict[str, Any]:
    """Slide 30: a weighted score out of 100. Each measure is scaled against the best in the
    team, so the leader on a measure earns its full weight."""
    usable = {k: float(v) for k, v in weights.items() if k in AVAILABLE_FOR_SCORING and float(v or 0) > 0}
    left_out = sorted(k for k, v in weights.items() if k not in AVAILABLE_FOR_SCORING and float(v or 0) > 0)
    total = sum(usable.values())
    scale = {k: v * 100 / total for k, v in usable.items()} if total else {}
    tops = {k: max((r.get(k) or 0) for r in rows.values()) if rows else 0 for k in scale}
    table = []
    for person, r in rows.items():
        parts = {k: round(((r.get(k) or 0) / tops[k] * w) if tops[k] else 0, 1) for k, w in scale.items()}
        table.append({"person": person, "score": round(sum(parts.values()), 1), "parts": parts})
    table.sort(key=lambda x: x["score"], reverse=True)
    leader = table[0] if table and table[0]["score"] > 0 else None
    return {"ranking": table, "weightsUsed": {k: round(v, 1) for k, v in scale.items()}, "leftOut": left_out,
            "winner": leader["person"] if leader and (len(table) == 1 or table[1]["score"] < leader["score"]) else "",
            "tied": [t["person"] for t in table if leader and t["score"] == leader["score"]] if leader else []}


# ─── Incentives (slide 29) ───────────────────────────────────────────────────
INCENTIVE_KINDS = {
    "per_policy": "A fixed amount for each policy sold",
    "premium_percent": "A percentage of the premium sold",
    "target_bonus": "A bonus when a target is reached",
    "slab": "An amount for reaching a level",
}
SLAB_MEASURES = {"policiesSold": "Policies sold", "premium": "Premium", "renewalsClosed": "Renewals",
                 "conversionRate": "Conversion %"}


def incentive_lines(rules: List[Dict[str, Any]], r: Dict[str, Any], achievement_pct: Optional[float]) -> List[Dict[str, Any]]:
    """What one person earns this month under each enabled rule."""
    lines = []
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        kind, product, source = rule.get("kind"), rule.get("product") or "", rule.get("source") or ""
        if product and source:
            continue                                   # validated away; never guessed
        count = (r["productPolicies"].get(product, 0) if product else r["sourcePolicies"].get(source, 0) if source else r["policiesSold"])
        premium = (r["productPremium"].get(product, 0) if product else r["sourcePremium"].get(source, 0) if source else r["premium"])
        amount, basis = 0.0, ""
        if kind == "per_policy":
            amount, basis = count * float(rule.get("amount") or 0), f"{count} × ₹{float(rule.get('amount') or 0):,.0f}"
        elif kind == "premium_percent":
            amount, basis = premium * float(rule.get("percent") or 0) / 100, f"{float(rule.get('percent') or 0):g}% of ₹{premium:,.0f}"
        elif kind == "target_bonus":
            needed = float(rule.get("atPercent") or 100)
            if achievement_pct is not None and achievement_pct >= needed:
                amount = float(rule.get("amount") or 0)
            basis = f"target {achievement_pct:g}% of {needed:g}% needed" if achievement_pct is not None else "no target set this month"
        elif kind == "slab":
            measure = rule.get("measure", "policiesSold")
            value = r.get(measure) or 0
            reached = [s for s in sorted(rule.get("slabs") or [], key=lambda s: float(s.get("from") or 0)) if value >= float(s.get("from") or 0)]
            amount = float(reached[-1]["amount"]) if reached else 0
            basis = f"{SLAB_MEASURES.get(measure, measure)} {value:g}" + (f", level from {float(reached[-1]['from']):g}" if reached else ", below the first level")
        lines.append({"ruleId": rule.get("id"), "rule": rule.get("name", ""), "basis": basis, "amount": round(amount, 2)})
    return lines


# ─── Sales funnel and lead sources (slides 31 and 32) ────────────────────────
# A cohort report: the leads that arrived in a period, and how far each one got. A lead has
# "reached" a stage if it was ever there or further on, so a sale also counts as contacted,
# interested and quoted. Statuses off the main path count as the furthest point they imply.
FUNNEL = ["New", "Contacted", "Interested", "Quote Sent", "Follow-up", "Documents Pending", "Policy Sold"]
_FUNNEL_RANK = {"New": 0, "Assigned": 0, "Unreachable": 0, "Wrong Number": 0,
                "Contacted": 1, "Call Later": 1, "Not Interested": 1, "Lost": 1,
                "Interested": 2, "Quote Sent": 3, "Follow-up": 4, "Documents Pending": 5, "Policy Sold": 6}


def furthest_stage(lead: Dict[str, Any], ranks: Optional[Dict[str, int]] = None) -> int:
    """``ranks`` places a company's own stages; each counts as the main-path stage before it."""
    statuses = [step.get("status") for step in lead.get("statusHistory") or []] + [lead.get("status")]
    return max((_FUNNEL_RANK.get(s, (ranks or {}).get(s, 0)) for s in statuses if s), default=0)


def cohort(leads: Iterable[Dict[str, Any]], start: str, end: str, tz, person: str = "", product: str = "",
           source: str = "") -> List[Dict[str, Any]]:
    """Leads whose enquiry arrived in [start, end], optionally for one telecaller, product or source.
    Leads with no recorded arrival date cannot be placed in a period and are left out."""
    chosen = []
    for lead in leads:
        day = local_day(lead.get("leadDate"), tz)
        if not day or not start <= day <= end:
            continue
        if person and lead.get("assignedTo") != person:
            continue
        if product and (lead.get("product") or lead.get("policyType") or "") != product:
            continue
        if source and (lead.get("source") or "") != source:
            continue
        chosen.append(lead)
    return chosen


def funnel(leads: List[Dict[str, Any]], ranks: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    reached = [furthest_stage(l, ranks) for l in leads]
    stages, previous = [], None
    for rank, name in enumerate(FUNNEL):
        count = sum(1 for r in reached if r >= rank)
        stages.append({"stage": name, "count": count, "ofStart": _pct(count, len(leads)),
                       "ofPrevious": _pct(count, previous) if previous is not None else None})
        previous = count
    return stages


def by_source(leads: List[Dict[str, Any]], policies: Iterable[Dict[str, Any]], money: Callable[[Any], float],
              ranks: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Slide 32: which source produces the best customers, not just the most leads."""
    premium_by_lead: Dict[str, float] = {}
    for policy in policies:
        if policy.get("leadId") and policy.get("status") != "Cancelled":
            premium_by_lead[policy["leadId"]] = premium_by_lead.get(policy["leadId"], 0) + money(policy.get("netPremium", policy.get("premium", 0)))
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for lead in leads:
        groups.setdefault(lead.get("source") or "Not recorded", []).append(lead)
    rows = []
    for source, members in groups.items():
        reached = [furthest_stage(l, ranks) for l in members]
        sold = sum(1 for r in reached if r >= 6)
        premium = round(sum(premium_by_lead.get(l.get("id"), 0) for l in members), 2)
        rows.append({"source": source, "leads": len(members),
                     "contactRate": _pct(sum(1 for r in reached if r >= 1), len(members)),
                     "interestedRate": _pct(sum(1 for r in reached if r >= 2), len(members)),
                     "quoteRate": _pct(sum(1 for r in reached if r >= 3), len(members)),
                     "conversionRate": _pct(sold, len(members)), "policies": sold, "premium": premium,
                     "premiumPerLead": round(premium / len(members), 2) if members else None})
    return sorted(rows, key=lambda r: (r["premium"], r["leads"]), reverse=True)


def breakdown(leads: List[Dict[str, Any]], key: str, field_type: str, options: List[str],
              sold: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
    """Leads by the value of one of the company's own fields (a choice, several choices or
    yes/no): how many, how many were sold, and conversion. A lead with several choices counts
    under each; one with no value is "Not recorded"."""
    values = ["Yes", "No"] if field_type == "boolean" else list(options)
    groups: Dict[str, List[Dict[str, Any]]] = {v: [] for v in values + ["Not recorded"]}
    for lead in leads:
        raw = (lead.get("custom") or {}).get(key)
        if raw is None or raw == [] or raw == "":
            chosen = ["Not recorded"]
        elif field_type == "boolean":
            chosen = ["Yes" if raw else "No"]
        else:
            chosen = [v for v in (raw if isinstance(raw, list) else [raw]) if v in groups] or ["Not recorded"]
        for value in chosen:
            groups[value].append(lead)
    return [{"value": value, "leads": len(members), "sold": sum(1 for l in members if sold(l)),
             "conversionRate": _pct(sum(1 for l in members if sold(l)), len(members))}
            for value, members in groups.items() if members or value != "Not recorded"]
