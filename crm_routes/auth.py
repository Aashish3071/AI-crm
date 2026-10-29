"""Signing in: first-company setup, login, the current user and logout.

Sessions, passwords and CSRF live in crm_security; these routes only expose them.
"""
import os
import shutil
import uuid
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import crm_security
import crm_store
import pipecat_server as core
from crm_security import (authenticate,
    bootstrap_company,
    company_context,
    create_session,
    CSRF_COOKIE,
    identity_status,
    SESSION_COOKIE)

router = APIRouter()


class AuthSetupModel(BaseModel):
    companyName: str
    name: str
    email: str
    password: str


class LoginModel(BaseModel):
    email: str
    password: str


def _set_auth_cookies(response: JSONResponse, user: Dict[str, Any]) -> JSONResponse:
    secure = os.environ.get("APP_ENV", "development").lower() == "production"
    csrf = uuid.uuid4().hex
    # Lax permits the signed OAuth callback to carry the login cookie after the
    # user returns from Meta/Google/LinkedIn. Mutations still require the separate
    # SameSite=Strict CSRF cookie and matching header.
    response.set_cookie(SESSION_COOKIE, create_session(user), httponly=True, secure=secure, samesite="lax",
                        max_age=crm_security.SESSION_TTL_SECONDS, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=secure, samesite="strict",
                        max_age=crm_security.SESSION_TTL_SECONDS, path="/")
    return response


@router.get("/api/auth/status")
def auth_status():
    return {**identity_status(), "authenticationRequired": not core.AUTH_DISABLED}


@router.post("/api/auth/bootstrap")
def auth_bootstrap(payload: AuthSetupModel):
    if not payload.companyName.strip() or not payload.name.strip() or not payload.email.strip():
        raise HTTPException(status_code=422, detail="Company, administrator name and email are required")
    try:
        result = bootstrap_company(payload.companyName, payload.name, payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=409 if "already" in str(exc).lower() else 422, detail=str(exc))
    # Preserve the current prototype data as the first company's migration source.
    if not crm_store.configured() and os.path.exists(core.DB_FILE):
        destination = core._tenant_db_path(result["company"]["id"])
        if not os.path.exists(destination):
            shutil.copy2(core.DB_FILE, destination)
    company_token = company_context.set(result["company"]["id"])
    try:
        db = core.load_db()
        if not any(u.get("identityUserId") == result["user"]["id"] for u in db.get("users", [])):
            db.setdefault("users", []).append({"id": f"U_{uuid.uuid4().hex[:8]}", "identityUserId": result["user"]["id"],
                "name": result["user"]["name"], "email": result["user"]["email"], "role": "admin", "title": "Owner", "status": "Active"})
            core.save_db(db)
    finally: company_context.reset(company_token)
    return _set_auth_cookies(JSONResponse(content=result), result["user"])


@router.post("/api/auth/login")
def auth_login(payload: LoginModel, request: Request):
    now = datetime.now().timestamp(); key = f"{request.client.host if request.client else 'unknown'}:{payload.email.strip().lower()}"
    attempts = [stamp for stamp in core._AUTH_FAILURES.get(key, []) if now - stamp < 900]
    if len(attempts) >= 5:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts; wait 15 minutes and try again")
    user = authenticate(payload.email, payload.password)
    if not user:
        attempts.append(now); core._AUTH_FAILURES[key] = attempts
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    core._AUTH_FAILURES.pop(key, None)
    return _set_auth_cookies(JSONResponse(content={"user": user}), user)


@router.get("/api/auth/me")
def auth_me(request: Request):
    # With sign-in disabled for local development there is no signed-in user to return.
    return {"user": getattr(request.state, "user", None)}


@router.post("/api/auth/logout")
def auth_logout():
    response = JSONResponse(content={"status": "signed out"})
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return response
