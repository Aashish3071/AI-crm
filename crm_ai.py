"""The one door to a language model (docs/AI_CUSTOMIZATION_PLAN.md, decision D3).

Every AI feature — the reporting advisor today, the customization builder later — asks
through ``complete()``, so the provider, the model, the usage cap and error reporting are
decided once. The provider is OpenRouter's OpenAI-compatible chat API; during testing the
company runs on OpenRouter's free models, which are rate-limited and may be retired, so:

* **The model is configuration.** ``AI_MODEL`` (or the older ``ADVISOR_MODEL``) names it,
  e.g. a model id ending in ``:free``. With no key or no model the CRM says so and the
  features fall back to their built-in behaviour; nothing silently picks a paid model.
* **A daily cap per company** (``AI_DAILY_LIMIT``, default 50 requests) stops one company
  using up a shared key. Counted in this process and reset at midnight UTC.
* **Failures are explained, not swallowed.** The last reason is kept per company, so one
  company's rejected request never shows up as another's.

Never send customer data the caller isn't allowed to see: the caller scopes what it passes.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_DAILY_LIMIT = 50
TIMEOUT_SECONDS = 45.0

_lock = threading.Lock()
_usage: Dict[Tuple[str, str], int] = {}          # (company, UTC day) -> requests sent
_last_error: Dict[str, str] = {}                 # company -> why the last request didn't answer


def api_key() -> str:
    return os.environ.get("OPENROUTER_API_KEY", "").strip()


def model() -> str:
    return (os.environ.get("AI_MODEL") or os.environ.get("ADVISOR_MODEL") or "").strip()


def daily_limit() -> int:
    try:
        return max(0, int(os.environ.get("AI_DAILY_LIMIT", DEFAULT_DAILY_LIMIT)))
    except ValueError:
        return DEFAULT_DAILY_LIMIT


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def used_today(company_id: str) -> int:
    with _lock:
        return _usage.get((company_id, _today()), 0)


def not_configured_reason() -> str:
    if not api_key():
        return "AI is switched off: no OPENROUTER_API_KEY is set."
    if not model():
        return "AI is switched off: no AI_MODEL is set. Set it to an OpenRouter model id, such as one ending in ':free'."
    return ""


def status(company_id: str) -> Dict[str, object]:
    configured = not not_configured_reason()
    reason = not_configured_reason() or last_error(company_id)
    return {"modelConfigured": configured, "model": model() if configured else "",
            "mode": "model" if configured and not reason else "built-in", "lastError": reason,
            "usedToday": used_today(company_id), "dailyLimit": daily_limit()}


def last_error(company_id: str) -> str:
    with _lock:
        return _last_error.get(company_id, "")


def _fail(company_id: str, reason: str) -> None:
    with _lock:
        _last_error[company_id] = reason


def _take_allowance(company_id: str) -> bool:
    """Count one request against today's cap; False when the cap is used up."""
    key = (company_id, _today())
    with _lock:
        for stale in [k for k in _usage if k[1] != key[1]]:
            del _usage[stale]
        if _usage.get(key, 0) >= daily_limit():
            return False
        _usage[key] = _usage.get(key, 0) + 1
        return True


def _error_detail(response: httpx.Response) -> str:
    try:
        return str(((response.json().get("error") or {}).get("message") or ""))[:200]
    except Exception:
        return response.text[:200]


async def complete(company_id: str, messages: List[Dict[str, str]], *, title: str,
                   max_tokens: int = 700, temperature: float = 0) -> Optional[str]:
    """Ask the model; return its text, or None with the reason kept for ``status()``."""
    reason = not_configured_reason()
    if reason:
        _fail(company_id, reason)
        return None
    if not _take_allowance(company_id):
        _fail(company_id, f"Today's AI limit for this company ({daily_limit()} requests) is used up; "
                          "AI features are off until midnight UTC.")
        return None
    base_url = (os.environ.get("AI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json",
                         "X-Title": title},
                json={"model": model(), "temperature": temperature, "max_tokens": max_tokens,
                      "messages": messages})
    except Exception as exc:
        _fail(company_id, f"Could not reach the AI provider: {exc}")
        return None
    if response.status_code == 429:
        # Free models are shared and throttled; this is expected, not a fault.
        _fail(company_id, "The AI provider is rate-limiting requests (free models are shared). "
                          f"Try again in a minute. {_error_detail(response)}".strip())
        return None
    if response.status_code >= 400:
        _fail(company_id, f"The AI provider rejected the request (HTTP {response.status_code}): "
                          f"{_error_detail(response)}")
        return None
    try:
        data = response.json()
        answer = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    except Exception:
        answer = ""
    if not answer:
        _fail(company_id, "The AI model returned an empty answer.")
        return None
    _fail(company_id, "")
    return answer


def reset_for_tests() -> None:
    with _lock:
        _usage.clear()
        _last_error.clear()
