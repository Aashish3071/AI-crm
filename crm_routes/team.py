"""The team: users, the signed-in person's profile, the sales hierarchy and availability.
"""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import crm_security
import pipecat_server as core
from crm_security import create_identity_user, current_actor, current_company_id, update_identity_user

router = APIRouter()


def _checked_role(role: str) -> str:
    try:
        return crm_security.validate_role(role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _guard_unique_name(db: Dict[str, Any], name: str, excluding_id: Optional[str]):
    wanted = (name or "").strip().lower()
    if any(u.get("id") != excluding_id and (u.get("name") or "").strip().lower() == wanted for u in db.get("users", [])):
        raise HTTPException(status_code=409, detail="A team member with this name already exists. "
                            "Names must be unique so that work and commission reach the right person.")


def _guard_last_admin(db: Dict[str, Any], user: Dict[str, Any], new_role: Optional[str] = None,
                      new_status: Optional[str] = None):
    """Refuse any change that would leave the company without an active Owner / Admin."""
    if crm_security.normalized_role(user.get("role", "")) != "admin" or user.get("status", "Active") != "Active":
        return
    loses_admin = new_role is not None and crm_security.normalized_role(new_role) != "admin"
    loses_access = new_status is not None and new_status != "Active"
    if not (loses_admin or loses_access):
        return
    others = [u for u in db.get("users", []) if u.get("id") != user.get("id") and u.get("status", "Active") == "Active"
              and crm_security.normalized_role(u.get("role", "")) == "admin"]
    if not others:
        raise HTTPException(status_code=409, detail="This is the only active Owner / Admin. Make another team member "
                            "an Owner / Admin first, or nobody could manage users, settings or backups.")


def _remember_previous_name(user: Dict[str, Any], new_name: Optional[str]):
    old = user.get("name")
    if new_name and old and new_name != old:
        names = user.setdefault("previousNames", [])
        if old not in names:
            names.append(old)


def _self_record(db: Dict[str, Any]) -> Dict[str, Any]:
    """The roster record belonging to the signed-in session — never a shared setting.

    Reading a company-wide "currentUserId" meant every user saw and edited whichever
    profile that setting pointed at, which is impersonation inside an audited system.
    """
    users = db.get("users", [])
    session = crm_security.current_user()
    if not session:
        if core.AUTH_DISABLED and users:
            return users[0]
        raise HTTPException(status_code=401, detail="Sign in to continue")

    identity_id = session.get("sub")
    email = (session.get("email") or "").strip().lower()
    name = (session.get("name") or "").strip().lower()
    user = next((u for u in users if u.get("identityUserId") == identity_id), None)
    if not user and email:
        user = next((u for u in users if (u.get("email") or "").strip().lower() == email), None)
    if not user and name:
        user = next((u for u in users if (u.get("name") or "").strip().lower() == name), None)
    if not user:
        # A signed-in identity with no roster row yet: create one bound to this identity
        # rather than silently showing somebody else's profile.
        user = {"id": f"U_{uuid.uuid4().hex[:8]}", "identityUserId": identity_id,
                "name": session.get("name", ""), "email": session.get("email", ""),
                "role": crm_security.normalized_role(session.get("role", "")), "status": "Active",
                "createdAt": datetime.utcnow().isoformat() + "Z"}
        db.setdefault("users", []).append(user)
        core.save_db(db)
    elif not user.get("identityUserId") and identity_id:
        user["identityUserId"] = identity_id
        core.save_db(db)
    return user


@router.get("/api/profile")
def get_profile():
    """The signed-in user's own profile, resolved from the session."""
    db = core.load_db()
    users = db.get("users", [])
    user = _self_record(db)
    manager = next((u for u in users if u.get("id") == user.get("reportsTo")), None)
    reports = [u for u in users if u.get("reportsTo") == user.get("id")]
    leads = db.get("leads", [])
    return {**user,
            "managerName": (manager or {}).get("name", ""),
            "directReports": [{"id": r["id"], "name": r["name"], "role": r.get("role", "")} for r in reports],
            "stats": {
                "openLeads": len([l for l in leads if l.get("assignedTo") == user.get("name") and core.is_open_lead(l)]),
                "wonLeads": len([l for l in leads if l.get("assignedTo") == user.get("name") and core.is_sold(l)]),
                "openTasks": len([t for t in db.get("tasks", []) if t.get("assignedTo") == user.get("name") and t.get("status") not in ["Completed", "Archived"]])}}


class ProfileUpdate(BaseModel):
    currentUserId: Optional[str] = None
    userId: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[str] = None
    title: Optional[str] = None
    territory: Optional[str] = None


@router.put("/api/profile")
def update_profile(payload: ProfileUpdate):
    db = core.load_db()
    user = _self_record(db)
    target_id = payload.currentUserId or payload.userId or payload.id
    if target_id and target_id != user.get("id") and target_id != user.get("identityUserId"):
        raise HTTPException(status_code=403,
                            detail="A profile edit applies to your own account. To change another team member, use Settings → Users.")
    session = crm_security.current_user()
    caller_role = crm_security.normalized_role(session.get("role", "") if session else user.get("role", ""))
    if payload.role and payload.role != user.get("role") and caller_role != "admin":
        raise HTTPException(status_code=403, detail="Role modifications require administrator privileges")
    old_name = user.get("name")
    changes = {k: v for k, v in payload.model_dump().items() if v is not None and k not in {"currentUserId", "userId", "id"}}
    if "role" in changes and caller_role != "admin":
        changes.pop("role", None)
    if "role" in changes:
        changes["role"] = _checked_role(changes["role"])
        _guard_last_admin(db, user, new_role=changes["role"])
    if changes.get("name"):
        _guard_unique_name(db, changes["name"], user.get("id"))
    _remember_previous_name(user, changes.get("name"))
    user.update(changes)
    if changes.get("name") and changes["name"] != old_name:
        for collection in ["leads", "tasks", "deals", "policies", "renewals", "customers", "notifications", "calendarEvents"]:
            for record in db.get(collection, []):
                if record.get("assignedTo") == old_name:
                    record["assignedTo"] = changes["name"]
    core.audit(db, "Profile Updated", "User", user["id"], changes)
    core.save_db(db)
    return get_profile()


@router.get("/api/users/hierarchy")
def get_sales_hierarchy():
    """The reporting tree, with each person's book rolled up through their reports."""
    db = core.load_db()
    users = [u for u in db.get("users", []) if u.get("status", "Active") == "Active"]
    leads = db.get("leads", [])

    def own_counts(name: str) -> Dict[str, Any]:
        mine = [l for l in leads if l.get("assignedTo") == name]
        return {"leads": len(mine),
                "open": len([l for l in mine if core.is_open_lead(l)]),
                "won": len([l for l in mine if core.is_sold(l)])}

    def build(parent_id: Optional[str], seen: set) -> List[Dict[str, Any]]:
        nodes = []
        for user in users:
            if user.get("reportsTo") != parent_id and not (parent_id is None and not user.get("reportsTo")):
                continue
            if user["id"] in seen:                       # defensive: never loop on a bad cycle
                continue
            children = build(user["id"], seen | {user["id"]})
            own = own_counts(user.get("name", ""))
            team = dict(own)
            for child in children:
                for key in team:
                    team[key] += child["team"][key]
            nodes.append({"id": user["id"], "name": user.get("name", ""), "role": user.get("role", ""),
                          "email": user.get("email", ""), "own": own, "team": team, "reports": children})
        return nodes

    tree = build(None, set())
    placed = set()
    def collect(nodes):
        for n in nodes:
            placed.add(n["id"]); collect(n["reports"])
    collect(tree)
    orphans = [{"id": u["id"], "name": u.get("name", ""), "role": u.get("role", ""), "email": u.get("email", ""),
                "own": own_counts(u.get("name", "")), "team": own_counts(u.get("name", "")), "reports": []}
               for u in users if u["id"] not in placed]
    return {"tree": tree + orphans, "userCount": len(users)}


@router.put("/api/users/{id}/manager")
def set_user_manager(id: str, payload: Dict[str, Any]):
    """Place someone under a manager, refusing anything that would create a loop."""
    db = core.load_db()
    user = core._find_record(db.get("users", []), id, "User")
    manager_id = (payload or {}).get("reportsTo") or ""
    if manager_id:
        if manager_id == id:
            raise HTTPException(status_code=422, detail="Someone cannot report to themselves")
        core._find_record(db.get("users", []), manager_id, "Manager")
        by_id = {u["id"]: u for u in db.get("users", [])}
        walker, hops = manager_id, 0
        while walker and hops < 50:
            if walker == id:
                raise HTTPException(status_code=422, detail="That would create a reporting loop")
            walker = by_id.get(walker, {}).get("reportsTo")
            hops += 1
    user["reportsTo"] = manager_id
    core.audit(db, "Reporting Line Changed", "User", id, {"reportsTo": manager_id})
    core.save_db(db)
    return user


class UserModel(BaseModel):
    name: str
    email: Optional[str] = ""
    role: Optional[str] = "telecaller"
    title: Optional[str] = ""
    status: Optional[str] = "Active"
    temporaryPassword: Optional[str] = ""


@router.get("/api/users")
def get_users(activeOnly: bool = False):
    users = core.load_db().get("users", [])
    return [u for u in users if not activeOnly or u.get("status") == "Active"]


@router.post("/api/users")
def create_user(payload: UserModel):
    db = core.load_db()
    if any(u.get("name", "").strip().lower() == payload.name.strip().lower() for u in db.get("users", [])):
        raise HTTPException(status_code=409, detail="A team member with this name already exists")
    item = payload.model_dump(exclude={"temporaryPassword"})
    item["role"] = _checked_role(payload.role or "telecaller")
    if not core.AUTH_DISABLED and not payload.temporaryPassword:
        raise HTTPException(status_code=422, detail="A temporary password is required for a new login")
    if payload.temporaryPassword:
        try: identity = create_identity_user(current_company_id(), payload.name, payload.email or "", item["role"], payload.temporaryPassword)
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc))
        item["identityUserId"] = identity["id"]
    item.update({"id": f"U_{uuid.uuid4().hex[:8]}", "createdAt": datetime.utcnow().isoformat() + "Z"})
    db.setdefault("users", []).append(item)
    core.audit(db, "User Created", "User", item["id"], {"name": item["name"], "role": item.get("role")})
    core.save_db(db)
    return item


@router.put("/api/users/{id}")
def update_user(id: str, updates: Dict[str, Any]):
    db = core.load_db()
    user = core._find_record(db.get("users", []), id, "User")
    old_name = user.get("name")
    allowed = {"name", "email", "role", "title", "status"}
    changes = {k: v for k, v in updates.items() if k in allowed}
    if "role" in changes:
        changes["role"] = _checked_role(changes["role"])
    if changes.get("name"):
        _guard_unique_name(db, changes["name"], user.get("id"))
    _guard_last_admin(db, user, new_role=changes.get("role"), new_status=changes.get("status"))
    _remember_previous_name(user, changes.get("name"))
    user.update(changes)
    if user.get("identityUserId"):
        try: update_identity_user(user["identityUserId"], current_company_id(), {**changes, "password": updates.get("password", "")})
        except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc))
    # Renaming a broker must carry their whole book with them, or their leads and tasks
    # end up owned by a name that no longer exists.
    if changes.get("name") and changes["name"] != old_name:
        for collection in ["leads", "tasks", "deals", "policies", "renewals", "customers", "notifications", "calendarEvents"]:
            for record in db.get(collection, []):
                if record.get("assignedTo") == old_name:
                    record["assignedTo"] = changes["name"]
    core.audit(db, "User Updated", "User", id, changes)
    core.save_db(db)
    return user


class AvailabilityModel(BaseModel):
    available: bool
    userId: Optional[str] = None      # someone else's — managers for their team, the owner for anyone
    note: Optional[str] = ""


@router.put("/api/availability")
def set_availability(payload: AvailabilityModel):
    """Slide 12: someone away (leave, training, a full day of renewals) receives no new leads
    until they are back. Everyone can set their own; managers set their team's."""
    db = core.load_db()
    me = current_actor("")
    target = (core._find_record(db.get("users", []), payload.userId, "User") if payload.userId
              else next((u for u in db.get("users", []) if u.get("name") == me), None))
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.get("name") != me:
        owners = core.visible_owners(db)
        core._require_manager("You can only change your own availability")
        if owners is not None and target.get("name") not in owners:
            raise HTTPException(status_code=403, detail="You can only change your own availability")
    target["available"] = payload.available
    target["availabilityNote"] = "" if payload.available else (payload.note or "").strip()[:120]
    target["availabilityChangedAt"] = datetime.utcnow().isoformat() + "Z"
    core.audit(db, "Availability Changed", "User", target.get("id", ""), {"name": target.get("name"), "available": payload.available,
                                                                     "note": target["availabilityNote"]})
    core.save_db(db)
    return {"name": target.get("name"), "available": target["available"], "note": target["availabilityNote"]}


@router.delete("/api/users/{id}")
def deactivate_user(id: str):
    """Deactivate rather than delete: their name still appears on historical records."""
    db = core.load_db()
    user = core._find_record(db.get("users", []), id, "User")
    _guard_last_admin(db, user, new_status="Inactive")
    open_work = len([l for l in db.get("leads", []) if l.get("assignedTo") == user.get("name") and core.is_open_lead(l)])
    user["status"] = "Inactive"
    user["deactivatedAt"] = datetime.utcnow().isoformat() + "Z"
    if user.get("identityUserId"): update_identity_user(user["identityUserId"], current_company_id(), {"status":"Inactive"})
    core.audit(db, "User Deactivated", "User", id, {"name": user.get("name"), "openLeads": open_work})
    core.save_db(db)
    return {**user, "openLeadsToReassign": open_work}
