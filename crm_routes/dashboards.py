"""Dashboards, performance and targets (client blueprint, slides 14, 26, 29, 34, 47).

What a telecaller or owner sees first, the team performance table and monthly targets.
Every figure comes from crm_metrics, so these screens always agree with each other.
"""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import crm_metrics as metrics
import crm_security
import pipecat_server as core
from crm_security import current_company_id

router = APIRouter()


def _relative_time(iso_stamp: str) -> str:
    try:
        moment = datetime.strptime(iso_stamp.replace("Z", ""), "%Y-%m-%dT%H:%M:%S.%f")
    except (TypeError, ValueError):
        try:
            moment = datetime.strptime(iso_stamp.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")
        except (TypeError, ValueError):
            return ""
    seconds = (datetime.utcnow() - moment).total_seconds()
    if seconds < 60: return "just now"
    if seconds < 3600: return f"{int(seconds // 60)}m ago"
    if seconds < 86400: return f"{int(seconds // 3600)}h ago"
    if seconds < 172800: return "yesterday"
    return f"{int(seconds // 86400)}d ago"


def _recent_activity(db: Dict[str, Any], limit: int = 6) -> List[Dict[str, Any]]:
    """Real activity from the audit ledger, so the dashboard reflects what actually happened."""
    entries = db.get("auditLogs", [])[:limit]
    labels = core._build_label_index(db, {e.get("entityId", "") for e in entries})   # one pass for the whole feed
    feed = []
    for entry in entries:
        details = entry.get("details") or {}
        subject = details.get("name") or details.get("title") or labels.get(entry.get("entityId", ""), entry.get("entityId", ""))
        description = f"{entry.get('action', 'Updated')} — {subject}" if subject else entry.get("action", "Updated")
        if entry.get("action") == "Lead Stage Changed" and details.get("from"):
            description = f"{subject}: {details.get('from')} → {details.get('to')}"
        feed.append({"id": entry.get("id"), "description": description,
                     "actor": entry.get("actor", "System"), "time": _relative_time(entry.get("createdAt", ""))})
    return feed


ONLINE_MINUTES = 10


@router.get("/api/dashboard")
def get_dashboard():
    db = core.load_db()
    owners = core.visible_owners(db)
    leads = core.scoped(core.live_expiry_inplace(db.get("leads", [])), owners)
    deals = core.scoped(db.get("deals", []), owners)
    tasks = core.scoped(db.get("tasks", []), owners)

    today = datetime.now().date()
    today_str = today.strftime("%Y-%m-%d")
    month_start = today.replace(day=1).strftime("%Y-%m-%d")
    week_ahead = (today + timedelta(days=7)).strftime("%Y-%m-%d")

    def task_date(task):
        return task.get("dueDate") or ""

    active_tasks = [t for t in tasks if t.get("status") not in ["Completed", "Archived"]]
    # M01.2: "due today" means today — not every open task, which is what it used to return.
    due_today = [t for t in active_tasks if task_date(t) == today_str]
    overdue = [t for t in active_tasks if task_date(t) and task_date(t) < today_str]
    upcoming = [t for t in active_tasks if today_str < task_date(t) <= week_ahead]
    completed_today = [t for t in tasks if t.get("status") == "Completed"
                       and (t.get("completedAt", "")[:10] or task_date(t)) == today_str]

    total_leads = len(leads)
    open_leads = [l for l in leads if core.is_open_lead(l)]
    open_deals = [d for d in deals if d.get("status") not in ["Won", "Lost"]]

    # M01.3: open pipeline excludes closed business, and keeps decimals rather than
    # concatenating digits out of a formatted string.
    pipeline_value = round(sum(core.money_value(l.get("premium")) for l in open_leads), 2)
    won_value = round(sum(core.money_value(l.get("premium")) for l in leads if core.is_sold(l)), 2)

    # A date-labelled KPI uses its stated period.
    # The sale date, not the last edit: editing an old sale must not move it into this month.
    won_this_month = [l for l in leads if core.is_sold(l) and (l.get("soldAt") or "")[:10] >= month_start]

    stage_counts = {stg: 0 for stg in core.STAGES}
    for l in leads:
        stage_counts[l.get("status", "New")] = stage_counts.get(l.get("status", "New"), 0) + 1

    renewals = sorted([l for l in leads if core._expiring_within(l, 15)],
                      key=lambda l: l.get("daysRemaining", 999))

    # 30 days of history; the dashboard slices the range the user picked (7/14/30).
    trend = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        key = day.strftime("%Y-%m-%d")
        trend.append({
            "date": key,
            "label": day.strftime("%a"),
            "due": len([t for t in tasks if task_date(t) == key]),
            "completed": len([t for t in tasks if t.get("status") == "Completed"
                              and (t.get("completedAt", "")[:10] or task_date(t)) == key]),
        })

    return {
        "today": today_str,
        "todayCounts": {"overdue": len(overdue), "dueToday": len(due_today),
                        "completedToday": len(completed_today), "next7Days": len(upcoming)},
        "myDay": sorted(overdue + due_today, key=lambda t: (task_date(t), t.get("priority") != "High"))[:12],
        "upcomingTasks": sorted(upcoming, key=task_date)[:8],
        "completedTodayList": completed_today[:8],
        "workTrend": trend,
        "totalLeads": total_leads,
        "openLeads": len(open_leads),
        "openDeals": len(open_deals),
        "wonThisMonth": len(won_this_month),
        "pipelineValue": f"₹ {pipeline_value:,.2f}".replace(".00", ""),
        "pipelineValueRaw": pipeline_value,
        "wonValueRaw": won_value,
        "pipelineByStage": stage_counts,
        "tasksDueToday": due_today,
        "renewalsDueThisWeek": renewals,
        "recentActivity": _recent_activity(db)
    }


# Every figure comes from crm_metrics, which defines each measure once.
def _is_owner() -> bool:
    """Commission is the owner's figure: shown only to an Owner / Admin (or local mode)."""
    if core.AUTH_DISABLED:
        return True
    session = crm_security.current_user()
    return bool(session) and crm_security.normalized_role(session.get("role", "")) == "admin"


@router.get("/api/performance")
def get_performance(period: str = "month", start: Optional[str] = None, end: Optional[str] = None):
    """Slide 26: each person's figures for today, this week, this month or a chosen range."""
    db = core.load_db()
    try:
        first, last = metrics.period_bounds(period, core._company_date(db), start, end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    people = core._team_people(db, core.visible_owners(db))
    rows = core._measure(db, first, last, people)
    return {"period": {"name": period, "start": first, "end": last}, "timezone": str(core._calendar_timezone(db)),
            "rows": [{"person": p, **rows[p]} for p in people], "totals": metrics.totals(rows),
            "definitions": metrics.__doc__}


@router.get("/api/targets")
def get_targets(month: Optional[str] = None):
    """Slide 29: each person's monthly targets and how far they have got."""
    db = core.load_db()
    month = core._checked_month(month, db)
    first, last = core._month_range(db, month)
    people = core._team_people(db, core.visible_owners(db))
    actual = core._measure(db, first, last, people)
    targets, headline = core._targets_for(db, month), core._headline_measure(db)
    rows = [{"person": p, "targets": targets.get(p, {}), "actual": {k: actual[p].get(k, 0) for k in metrics.TARGET_MEASURES},
             "achievement": metrics.achievement(actual[p], targets.get(p, {}), headline)} for p in people]
    team_target = {k: sum((targets.get(p, {}).get(k) or 0) for p in people) for k in metrics.TARGET_MEASURES}
    team_actual = metrics.totals(actual)
    return {"month": month, "through": last, "headline": headline, "measures": metrics.TARGET_MEASURES, "rows": rows,
            "team": {"targets": team_target, "actual": {k: team_actual.get(k, 0) for k in metrics.TARGET_MEASURES},
                     "achievement": metrics.achievement(team_actual, team_target, headline)}}


class TargetUpdate(BaseModel):
    month: str
    person: str
    policiesSold: Optional[float] = None
    premium: Optional[float] = None
    calls: Optional[float] = None
    renewalsClosed: Optional[float] = None


@router.put("/api/targets")
def set_target(payload: TargetUpdate):
    """The owner sets targets; a manager may set them for their own team."""
    core._require_manager("Only an Owner / Admin or a Manager can set targets.")
    db = core.load_db()
    month = core._checked_month(payload.month, db)
    if payload.person not in core._team_people(db, core.visible_owners(db)):
        raise HTTPException(status_code=404, detail="That person isn't on your team")
    values = {}
    for key in metrics.TARGET_MEASURES:
        value = getattr(payload, key)
        if value is None:
            continue
        if value < 0:
            raise HTTPException(status_code=422, detail="Targets cannot be negative")
        values[key] = round(value, 2) if key == "premium" else int(value)
    person_targets = db.setdefault("targets", {}).setdefault(month, {}).setdefault(payload.person, {})
    person_targets.update({k: v for k, v in values.items() if v})
    for key in [k for k, v in values.items() if not v]:
        person_targets.pop(key, None)
    core.audit(db, "Target Set", "Target", f"{month}:{payload.person}", {"month": month, "person": payload.person, **values})
    core.save_db(db)
    return get_targets(month)


@router.post("/api/targets/copy")
def copy_targets(payload: Dict[str, Any]):
    """Start a month from last month's targets, without overwriting any already set."""
    core._require_manager("Only an Owner / Admin or a Manager can set targets.")
    db = core.load_db()
    source, destination = core._checked_month(payload.get("from"), db), core._checked_month(payload.get("to"), db)
    people = set(core._team_people(db, core.visible_owners(db)))
    copied = 0
    for person, values in core._targets_for(db, source).items():
        if person in people and person not in core._targets_for(db, destination):
            db.setdefault("targets", {}).setdefault(destination, {})[person] = dict(values)
            copied += 1
    core.audit(db, "Targets Copied", "Target", destination, {"from": source, "to": destination, "people": copied})
    core.save_db(db)
    return {**get_targets(destination), "copied": copied}


@router.put("/api/targets/headline")
def set_target_headline(payload: Dict[str, Any]):
    """Which target the dashboards show as "target achieved"."""
    core._require_manager("Only an Owner / Admin or a Manager can change this.")
    if payload.get("headline") not in metrics.TARGET_MEASURES:
        raise HTTPException(status_code=422, detail=f"Choose one of: {', '.join(metrics.TARGET_MEASURES.values())}")
    db = core.load_db()
    db.setdefault("settings", {}).setdefault("targets", {})["headline"] = payload["headline"]
    core.save_db(db)
    return {"headline": payload["headline"]}


def _priority_leads(db: Dict[str, Any], leads: List[Dict[str, Any]], limit: int = 15) -> List[Dict[str, Any]]:
    """Who to call next: HOT first, then whatever is most overdue, then soonest due."""
    order = {"HOT": 0, "WARM": 1, "COLD": 2}
    open_leads = [core.live_expiry(l) for l in leads if core.is_open_lead(l)]
    open_leads.sort(key=lambda l: (order.get((l.get("leadPriority") or "").upper(), 3),
                                   l.get("nextActionDate") or "9999", l.get("nextActionTime") or "99:99"))
    return [{k: l.get(k) for k in ("id", "name", "product", "status", "leadPriority", "nextAction", "nextActionDate",
                                   "nextActionTime", "mobile", "city")} for l in open_leads[:limit]]


@router.get("/api/dashboard/telecaller")
def telecaller_dashboard(person: Optional[str] = None):
    """Slide 14: one telecaller's day. A telecaller sees their own; a manager or owner may pick one."""
    db = core.load_db()
    owners = core.visible_owners(db)
    session = None if core.AUTH_DISABLED else crm_security.current_user()
    me = (session or {}).get("name") or ""
    who = person or me
    if not who:
        people = core._team_people(db, owners)
        who = people[0] if people else ""
    if owners is not None and who not in owners:
        raise HTTPException(status_code=404, detail="That person isn't on your team")
    today = core._company_date(db).isoformat()
    todays = core._measure(db, today, today, [who])[who]
    month = today[:7]
    first, last = core._month_range(db, month)
    month_actual = core._measure(db, first, last, [who])[who]
    target = metrics.achievement(month_actual, core._targets_for(db, month).get(who, {}), core._headline_measure(db))
    mine = [l for l in db.get("leads", []) if l.get("assignedTo") == who]
    working_today = [l for l in mine if core.is_open_lead(l) and (
        (l.get("nextActionDate") and l["nextActionDate"] <= today and not l.get("nextActionCompleted"))
        or metrics.local_day(l.get("leadDate"), core._calendar_timezone(db)) == today)]
    tz = core._calendar_timezone(db)
    now = datetime.now(tz)
    due = [t for t in db.get("tasks", []) if t.get("assignedTo") == who and t.get("status") not in ("Completed", "Archived")
           and t.get("dueDate") and t["dueDate"] <= today]
    incentive = metrics.incentive_lines(core._incentive_rules(db), month_actual, target["percent"])
    user = next((u for u in db.get("users", []) if u.get("name") == who), {})
    return {"person": who, "date": today,
            "availability": {"available": user.get("available", True), "note": user.get("availabilityNote", ""), "userId": user.get("id", "")},
            "incentive": {"estimate": round(sum(l["amount"] for l in incentive), 2), "lines": incentive,
                          "hasPlan": bool(core._incentive_rules(db))},
            "tiles": {"todaysLeads": len(working_today), "callsDone": todays["calls"], "connected": todays["connected"],
                      "followUpsDue": len(due), "overdue": len([t for t in due if (core._due_moment(t, tz) or now) < now]),
                      "interested": todays["interested"], "quotesSent": todays["quotesSent"],
                      "policiesSold": todays["policiesSold"], "targetAchieved": target["percent"]},
            "target": target, "month": {k: month_actual.get(k) for k in ("calls", "connected", "policiesSold", "premium")},
            "priorityLeads": _priority_leads(db, mine)}


@router.get("/api/dashboard/owner")
def owner_dashboard():
    """Slides 34 and 47: the business at a glance — today, this week, this month, and the team."""
    core._require_manager("The owner's dashboard is for an Owner / Admin or a Manager.")
    db = core.load_db()
    owners = core.visible_owners(db)
    people = core._team_people(db, owners)
    today = core._company_date(db)
    bands = {}
    for name in ("today", "week", "month"):
        first, last = metrics.period_bounds(name, today)
        bands[name] = {"start": first, "end": last, **metrics.totals(core._measure(db, first, last, people))}
    month = today.strftime("%Y-%m")
    first, last = core._month_range(db, month)
    month_rows = core._measure(db, first, last, people)
    targets, headline = core._targets_for(db, month), core._headline_measure(db)
    standing = [{"person": p, "achievement": metrics.achievement(month_rows[p], targets.get(p, {}), headline)["percent"],
                 **{k: month_rows[p][k] for k in ("policiesSold", "premium", "calls", "connectRate")}} for p in people]
    ranked = sorted(standing, key=lambda r: (r["premium"], r["policiesSold"]), reverse=True)
    best = ranked[0]["person"] if ranked and (ranked[0]["premium"] or ranked[0]["policiesSold"]) else ""
    # Needs support: furthest behind target; without targets, the lowest connect rate among those making calls.
    # Never the best performer as well: with one person measured there is no one to compare.
    with_target = [r for r in standing if r["achievement"] is not None and r["person"] != best]
    if with_target:
        weakest = min(with_target, key=lambda r: r["achievement"])
        support = weakest["person"] if weakest["achievement"] < 100 else ""
    else:
        callers = [r for r in standing if r["calls"] >= 10 and r["connectRate"] is not None and r["person"] != best]
        support = min(callers, key=lambda r: r["connectRate"])["person"] if callers else ""
    team_target = {k: sum((targets.get(p, {}).get(k) or 0) for p in people) for k in metrics.TARGET_MEASURES}
    team = metrics.achievement(metrics.totals(month_rows), team_target, headline)
    cutoff = datetime.utcnow() - timedelta(minutes=ONLINE_MINUTES)
    company = current_company_id()
    online = sorted(p for p in people if core._LAST_SEEN.get((company, p)) and core._LAST_SEEN[(company, p)] >= cutoff)
    scoped_policies = core.scoped(db.get("policies", []), owners)
    renewal_window = [p for p in scoped_policies if p.get("status") not in ("Cancelled", "Expired/Renewed")
                      and p.get("expiryDate") and 0 <= (core._days_until(p["expiryDate"]) or -1) <= 30]
    # Follow-ups as the Follow-ups screen counts them: open and due today or earlier.
    tz = core._calendar_timezone(db)
    now_local = datetime.now(tz)
    open_due = [t for t in core.scoped(db.get("tasks", []), owners) if t.get("status") not in ("Completed", "Archived")
                and t.get("dueDate") and t["dueDate"] <= today.isoformat()]
    overdue = [t for t in open_due if (core._due_moment(t, tz) or now_local) < now_local]
    bands["today"]["followUpsOpen"] = len(open_due)
    alerts = [n for n in db.get("notifications", []) if not n.get("read") and n.get("severity") == "High"
              and (owners is None or n.get("assignedTo") in owners or n.get("escalatedTo") in owners)]
    return {"bands": bands, "team": {"best": best, "needsSupport": support, "targetAchieved": team["percent"],
                                     "headline": headline, "standing": ranked},
            "control": {"employeesOnline": online, "teamSize": len(people),
                        "away": [{"person": u.get("name"), "userId": u.get("id"), "note": u.get("availabilityNote", "")}
                                 for u in db.get("users", []) if u.get("name") in people and not u.get("available", True)],
                        "availablePeople": [{"person": u.get("name"), "userId": u.get("id")} for u in db.get("users", [])
                                            if u.get("name") in people and u.get("available", True)], "missedCallsToday": bands["today"]["notConnected"],
                        "overdueFollowUps": len(overdue),
                        "renewalOpportunities": len(renewal_window), "importantAlerts": len(alerts)},
            "commissionAvailable": bool(core._commission_rules(db)) and _is_owner(),}


DASHBOARD_PANELS = [
    {"id": "today", "label": "Today at a glance", "description": "Overdue, due today, finished today and the week ahead."},
    {"id": "myDay", "label": "My day", "description": "The tasks actually needing attention now."},
    {"id": "renewals", "label": "Renewal radar", "description": "Policies expiring within 15 days."},
    {"id": "trend", "label": "Work trend", "description": "Scheduled versus completed over the last 7 days."},
    {"id": "pipeline", "label": "Pipeline by stage", "description": "Where the open book sits."},
    {"id": "upcoming", "label": "Coming up", "description": "Scheduled for the next 7 days."},
    {"id": "activity", "label": "Recent activity", "description": "What the team changed, from the audit ledger."},
]


DEFAULT_PANEL_ORDER = ["today", "myDay", "renewals", "trend", "pipeline", "upcoming", "activity"]


def _panel_key() -> str:
    session = crm_security.current_user() or {}
    return session.get("sub") or "default"


@router.get("/api/dashboard/layout")
def get_dashboard_layout():
    """Each person arranges their own dashboard; the catalogue is shared."""
    db = core.load_db()
    saved = ((db.get("settings", {}) or {}).get("dashboardLayouts", {}) or {}).get(_panel_key())
    order = [p for p in (saved or {}).get("order", DEFAULT_PANEL_ORDER) if p in {x["id"] for x in DASHBOARD_PANELS}]
    for panel in DEFAULT_PANEL_ORDER:
        if panel not in order:
            order.append(panel)
    hidden = [h for h in (saved or {}).get("hidden", []) if h in order]
    return {"panels": DASHBOARD_PANELS, "order": order, "hidden": hidden}


@router.put("/api/dashboard/layout")
def save_dashboard_layout(payload: Dict[str, Any]):
    db = core.load_db()
    valid = {p["id"] for p in DASHBOARD_PANELS}
    order = [p for p in payload.get("order", DEFAULT_PANEL_ORDER) if p in valid]
    hidden = [h for h in payload.get("hidden", []) if h in valid]
    db.setdefault("settings", {}).setdefault("dashboardLayouts", {})[_panel_key()] = {
        "order": order or DEFAULT_PANEL_ORDER, "hidden": hidden}
    core.save_db(db)
    return get_dashboard_layout()
