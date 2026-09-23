"""Telephony (client blueprint, slide 15).

One interface for placing calls and reading their results, so a provider can be added
without touching the calling screens or the outcome rules.

* ``manual`` works with no contract: the telecaller's own phone dials through a ``tel:``
  link, the CRM times the call on screen and records the outcome.
* A cloud telephony provider (Exotel, Knowlarity, Ozonetel, Twilio…) implements
  ``place_call`` and ``parse_callback``; its duration and recording then come from the
  provider rather than the screen timer. None is included until one is chosen and tested
  against the provider's own sandbox — an adapter that has never placed a real call is
  not shipped as if it worked.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional


class ProviderError(RuntimeError):
    pass


class Provider:
    key = ""
    label = ""
    # Whether the provider reports duration and recordings itself. When it does not, the
    # CRM measures duration as the time the call screen was open.
    measures_calls = False

    def place_call(self, settings: Dict[str, Any], from_number: str, to_number: str, agent: Dict[str, Any],
                   call_id: str, callback_url: str) -> Dict[str, Any]:
        raise NotImplementedError

    def parse_callback(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Normalise a provider's status callback to
        {providerCallId, status, answered, durationSeconds, recordingUrl, endedAt}."""
        raise NotImplementedError


class ManualProvider(Provider):
    key = "manual"
    label = "Telecaller's own phone"

    def place_call(self, settings, from_number, to_number, agent, call_id, callback_url):
        digits = dial_string(to_number)
        if not digits:
            raise ProviderError("This lead has no phone number to call")
        return {"providerCallId": "", "status": "Dialling", "dial": f"tel:{digits}",
                "instructions": "Your phone will dial the customer. Come back here to record how the call went."}

    def parse_callback(self, payload):
        raise ProviderError("The manual provider does not send callbacks")


PROVIDERS: Dict[str, Provider] = {"manual": ManualProvider()}


def provider_for(settings: Dict[str, Any]) -> Provider:
    return PROVIDERS.get((settings or {}).get("provider") or "manual", PROVIDERS["manual"])


def dial_string(number: Optional[str]) -> str:
    """A number a phone can dial: digits, with a leading + kept. Indian ten-digit mobiles
    get the +91 country code."""
    raw = str(number or "").strip()
    plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if not plus and len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if not plus and len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return f"+{digits}" if plus else digits
