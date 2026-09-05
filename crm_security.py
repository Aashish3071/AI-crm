"""Authentication and tenant context for InsureCRM.

The local identity file is a development adapter. Production deployments use the
same API contract but must point ``IDENTITY_STORE_PATH`` at a protected volume and
set ``SESSION_SECRET`` through the platform secret manager. CRM business records
are isolated by the company id placed in ``company_context``.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
import uuid
from typing import Any, Dict, Optional


company_context: contextvars.ContextVar[str] = contextvars.ContextVar("crm_company_id", default="default")
user_context: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("crm_user", default=None)

IDENTITY_STORE_PATH = os.environ.get("IDENTITY_STORE_PATH", "crm_identity.json")
SESSION_COOKIE = "crm_session"
CSRF_COOKIE = "crm_csrf"
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "28800"))


IDENTITY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS crm_auth_companies (
    id text PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL CHECK (status IN ('Active', 'Inactive')),
    created_at bigint NOT NULL
);
CREATE TABLE IF NOT EXISTS crm_auth_users (
    id text PRIMARY KEY,
    company_id text NOT NULL REFERENCES crm_auth_companies(id) ON DELETE CASCADE,
    name text NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    status text NOT NULL CHECK (status IN ('Active', 'Inactive')),
    password_hash text NOT NULL,
    created_at bigint NOT NULL,
    password_changed_at bigint NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS crm_auth_users_email_idx ON crm_auth_users(lower(email));
CREATE INDEX IF NOT EXISTS crm_auth_users_company_idx ON crm_auth_users(company_id, status);
"""


def _postgres_configured() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL authentication requires psycopg[binary]") from exc
    return psycopg.connect(os.environ["DATABASE_URL"])


def _ensure_identity_schema(connection=None) -> None:
    if connection is not None:
        with connection.cursor() as cursor:
            cursor.execute(IDENTITY_SCHEMA_SQL)
        return
    with _connect() as owned:
        with owned.cursor() as cursor:
            cursor.execute(IDENTITY_SCHEMA_SQL)


def _secret() -> bytes:
    configured = os.environ.get("SESSION_SECRET", "")
    if configured:
        return configured.encode("utf-8")
    if os.environ.get("APP_ENV", "development").lower() == "production":
        raise RuntimeError("SESSION_SECRET is required in production")
    # Stable local-only key so browser sessions survive a development restart.
    return hashlib.sha256((os.path.abspath(IDENTITY_STORE_PATH) + ":insurecrm-dev").encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _load_identities() -> Dict[str, Any]:
    if _postgres_configured():
        with _connect() as connection:
            _ensure_identity_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, name, status, created_at FROM crm_auth_companies ORDER BY created_at")
                companies = [{"id": row[0], "name": row[1], "status": row[2], "createdAt": row[3]}
                             for row in cursor.fetchall()]
                cursor.execute("SELECT id, company_id, name, email, role, status, password_hash, created_at, password_changed_at "
                               "FROM crm_auth_users ORDER BY created_at")
                users = [{"id": row[0], "companyId": row[1], "name": row[2], "email": row[3],
                          "role": row[4], "status": row[5], "passwordHash": row[6],
                          "createdAt": row[7], "passwordChangedAt": row[8]} for row in cursor.fetchall()]
                return {"companies": companies, "users": users}
    if not os.path.exists(IDENTITY_STORE_PATH):
        return {"companies": [], "users": []}
    try:
        with open(IDENTITY_STORE_PATH, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        value.setdefault("companies", [])
        value.setdefault("users", [])
        return value
    except (OSError, json.JSONDecodeError):
        return {"companies": [], "users": []}


def _save_identities(data: Dict[str, Any]) -> None:
    if _postgres_configured():
        with _connect() as connection:
            _ensure_identity_schema(connection)
            with connection.cursor() as cursor:
                cursor.execute("LOCK TABLE crm_auth_companies, crm_auth_users IN EXCLUSIVE MODE")
                cursor.execute("DELETE FROM crm_auth_users")
                cursor.execute("DELETE FROM crm_auth_companies")
                for company in data.get("companies", []):
                    cursor.execute("INSERT INTO crm_auth_companies(id,name,status,created_at) VALUES(%s,%s,%s,%s)",
                                   (company["id"], company["name"], company.get("status", "Active"), company.get("createdAt", int(time.time()))))
                for user in data.get("users", []):
                    cursor.execute("INSERT INTO crm_auth_users(id,company_id,name,email,role,status,password_hash,created_at,password_changed_at) "
                                   "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                   (user["id"], user["companyId"], user["name"], user["email"], user["role"],
                                    user.get("status", "Active"), user["passwordHash"], user.get("createdAt", int(time.time())),
                                    user.get("passwordChangedAt", int(time.time()))))
        return
    directory = os.path.dirname(os.path.abspath(IDENTITY_STORE_PATH))
    os.makedirs(directory, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix="crm_identity_", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
        os.chmod(temporary, 0o600)
        os.replace(temporary, IDENTITY_STORE_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _password_hash(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${_b64(salt)}${_b64(derived)}"


def _password_valid(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(rounds))
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


def password_policy(password: str) -> Optional[str]:
    if len(password) < 12:
        return "Password must contain at least 12 characters"
    categories = [any(c.islower() for c in password), any(c.isupper() for c in password),
                  any(c.isdigit() for c in password), any(not c.isalnum() for c in password)]
    if sum(categories) < 3:
        return "Password must use at least three of: uppercase, lowercase, number and symbol"
    return None


def identity_status() -> Dict[str, Any]:
    store = _load_identities()
    return {"setupRequired": not bool(store["users"]), "companyCount": len(store["companies"])}


def company_ids() -> list[str]:
    values = [c.get("id") for c in _load_identities().get("companies", []) if c.get("status") == "Active" and c.get("id")]
    return values or ["default"]


def bootstrap_company(company_name: str, admin_name: str, email: str, password: str) -> Dict[str, Any]:
    store = _load_identities()
    if store["users"]:
        raise ValueError("Initial setup has already been completed")
    error = password_policy(password)
    if error:
        raise ValueError(error)
    company_id = f"CO_{uuid.uuid4().hex[:12]}"
    user_id = f"USR_{uuid.uuid4().hex[:12]}"
    company = {"id": company_id, "name": company_name.strip(), "status": "Active", "createdAt": int(time.time())}
    user = {"id": user_id, "companyId": company_id, "name": admin_name.strip(), "email": email.strip().lower(),
            "role": "Administrator", "status": "Active", "passwordHash": _password_hash(password),
            "createdAt": int(time.time()), "passwordChangedAt": int(time.time())}
    store["companies"].append(company)
    store["users"].append(user)
    _save_identities(store)
    return {"company": company, "user": public_user(user)}


def authenticate(email: str, password: str) -> Optional[Dict[str, Any]]:
    candidate = email.strip().lower()
    store = _load_identities()
    user = next((u for u in store["users"] if u.get("email") == candidate and u.get("status") == "Active"), None)
    if not user or not _password_valid(password, user.get("passwordHash", "")):
        return None
    company = next((c for c in store["companies"] if c.get("id") == user.get("companyId") and c.get("status") == "Active"), None)
    if not company:
        return None
    return {**public_user(user), "companyName": company.get("name", "")}


def public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {k: user.get(k) for k in ["id", "companyId", "name", "email", "role", "status"]}


def create_identity_user(company_id: str, name: str, email: str, role: str, password: str) -> Dict[str, Any]:
    error = password_policy(password)
    if error:
        raise ValueError(error)
    store = _load_identities()
    normalized = email.strip().lower()
    if any(u.get("email") == normalized for u in store["users"]):
        raise ValueError("A login with this email already exists")
    if not any(c.get("id") == company_id and c.get("status") == "Active" for c in store["companies"]):
        raise ValueError("Company was not found")
    user = {"id": f"USR_{uuid.uuid4().hex[:12]}", "companyId": company_id, "name": name.strip(),
            "email": normalized, "role": role, "status": "Active", "passwordHash": _password_hash(password),
            "createdAt": int(time.time()), "passwordChangedAt": int(time.time())}
    store["users"].append(user)
    _save_identities(store)
    return public_user(user)


def update_identity_user(user_id: str, company_id: str, changes: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    store = _load_identities()
    user = next((u for u in store["users"] if u.get("id") == user_id and u.get("companyId") == company_id), None)
    if not user:
        return None
    for key in ["name", "role", "status"]:
        if key in changes:
            user[key] = changes[key]
    if changes.get("password"):
        error = password_policy(changes["password"])
        if error:
            raise ValueError(error)
        user["passwordHash"] = _password_hash(changes["password"])
        user["passwordChangedAt"] = int(time.time())
    _save_identities(store)
    return public_user(user)


def create_session(user: Dict[str, Any]) -> str:
    now = int(time.time())
    payload = {"sub": user["id"], "companyId": user["companyId"], "name": user["name"],
               "email": user["email"], "role": user["role"], "iat": now, "exp": now + SESSION_TTL_SECONDS,
               "nonce": secrets.token_hex(8)}
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_session(token: str) -> Optional[Dict[str, Any]]:
    try:
        encoded, signature = token.split(".", 1)
        expected = _b64(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            return None
        payload = json.loads(_unb64(encoded))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        # Re-read the account on every request so deactivation and role changes revoke
        # privileges immediately instead of waiting for an old cookie to expire.
        store = _load_identities()
        user = next((item for item in store.get("users", []) if item.get("id") == payload.get("sub")
                     and item.get("companyId") == payload.get("companyId") and item.get("status") == "Active"), None)
        company = next((item for item in store.get("companies", []) if item.get("id") == payload.get("companyId")
                        and item.get("status") == "Active"), None)
        if not user or not company:
            return None
        return {**payload, "name": user.get("name"), "email": user.get("email"), "role": user.get("role"),
                "companyName": company.get("name")}
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def current_company_id() -> str:
    return company_context.get() or "default"


def current_user() -> Optional[Dict[str, Any]]:
    return user_context.get()


def current_actor(fallback: str = "System") -> str:
    user = current_user()
    return user.get("name", fallback) if user else fallback


def normalized_role(role: str) -> str:
    value = (role or "").lower()
    if "admin" in value:
        return "admin"
    if "manager" in value or "lead" in value or "senior" in value:
        return "manager"
    if "read" in value or "viewer" in value or "auditor" in value:
        return "readonly"
    return "broker"


def may_mutate_path(role: str, path: str) -> bool:
    level = normalized_role(role)
    if level == "readonly":
        return False
    admin_only = ("/api/users", "/api/settings", "/api/backups", "/api/admin")
    if path.startswith(admin_only):
        return level == "admin"
    # /api/leads/import is the legacy bulk path; it must carry the same permission as /api/imports.
    management_only = ("/api/channels", "/api/imports", "/api/leads/import", "/api/assignment-rules")
    if path.startswith(management_only):
        return level in {"admin", "manager"}
    return level in {"admin", "manager", "broker"}


def may_read_path(role: str, path: str) -> bool:
    level = normalized_role(role)
    if path.startswith(("/api/backups", "/api/admin")):
        return level == "admin"
    if path.startswith("/api/audit-logs"):
        return level in {"admin", "manager"}
    if path.startswith("/api/channel-events"):
        return level in {"admin", "manager"}
    return level in {"admin", "manager", "broker", "readonly"}
