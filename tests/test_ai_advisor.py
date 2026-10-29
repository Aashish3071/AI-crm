"""The AI provider adapter (crm_ai.py) and the reporting advisor's record visibility.

The model is never reached: OpenRouter is replaced by an in-process transport, so these
tests cover configuration, the daily cap, error reporting and what the advisor sends.
"""
import asyncio
import json
import os
import unittest
from unittest.mock import patch

import httpx

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_ai
from test_client_blueprint import ClientBlueprintCase

AI_ENV = ("OPENROUTER_API_KEY", "AI_MODEL", "ADVISOR_MODEL", "AI_DAILY_LIMIT", "AI_BASE_URL")
FREE_MODEL = "example/test-model:free"


def ai_env(**values):
    """Exactly these AI settings, whatever the developer's own .env holds."""
    clean = {k: v for k, v in os.environ.items() if k not in AI_ENV}
    return patch.dict(os.environ, {**clean, **values}, clear=True)


class FakeProvider:
    """Stands in for OpenRouter and records what it was sent."""

    def __init__(self, status=200, content="Answer from the model"):
        self.status, self.content, self.requests = status, content, []
        self._client = httpx.AsyncClient

    def handler(self, request):
        self.requests.append({"url": str(request.url), "body": json.loads(request.content),
                              "auth": request.headers.get("authorization")})
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "provider says no"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": self.content}}]})

    def __enter__(self):
        transport = httpx.MockTransport(self.handler)
        self._patch = patch.object(crm_ai.httpx, "AsyncClient",
                                   lambda **kw: self._client(transport=transport, **kw))
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def ask(company="C1"):
    return asyncio.run(crm_ai.complete(company, [{"role": "user", "content": "hi"}], title="Test"))


class Adapter(unittest.TestCase):
    def setUp(self):
        crm_ai.reset_for_tests()

    def test_no_key_uses_built_in_answers(self):
        with ai_env(AI_MODEL=FREE_MODEL), FakeProvider() as provider:
            self.assertIsNone(ask())
            self.assertEqual(provider.requests, [])
            status = crm_ai.status("C1")
        self.assertEqual(status["mode"], "built-in")
        self.assertIn("OPENROUTER_API_KEY", status["lastError"])

    def test_no_model_never_falls_back_to_a_paid_default(self):
        with ai_env(OPENROUTER_API_KEY="k"), FakeProvider() as provider:
            self.assertIsNone(ask())
            self.assertEqual(provider.requests, [])
            self.assertIn("AI_MODEL", crm_ai.status("C1")["lastError"])
            self.assertFalse(crm_ai.status("C1")["modelConfigured"])

    def test_answers_from_the_configured_model(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider() as provider:
            self.assertEqual(ask(), "Answer from the model")
            status = crm_ai.status("C1")
        sent = provider.requests[0]
        self.assertEqual(sent["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(sent["body"]["model"], FREE_MODEL)
        self.assertEqual(sent["auth"], "Bearer k")
        self.assertEqual((status["mode"], status["model"], status["usedToday"]), ("model", FREE_MODEL, 1))

    def test_older_advisor_model_setting_still_works(self):
        with ai_env(OPENROUTER_API_KEY="k", ADVISOR_MODEL="older/model"), FakeProvider() as provider:
            ask()
        self.assertEqual(provider.requests[0]["body"]["model"], "older/model")

    def test_free_tier_rate_limit_is_explained(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(status=429):
            self.assertIsNone(ask())
            self.assertIn("rate-limiting", crm_ai.last_error("C1"))

    def test_rejection_is_explained(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(status=401):
            self.assertIsNone(ask())
            self.assertIn("HTTP 401", crm_ai.last_error("C1"))
            self.assertIn("provider says no", crm_ai.last_error("C1"))

    def test_empty_answer_is_a_failure(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(content="  "):
            self.assertIsNone(ask())
            self.assertIn("empty", crm_ai.last_error("C1"))

    def test_daily_cap_is_per_company(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL, AI_DAILY_LIMIT="2"), FakeProvider() as provider:
            self.assertIsNotNone(ask("C1"))
            self.assertIsNotNone(ask("C1"))
            self.assertIsNone(ask("C1"))
            self.assertIn("limit", crm_ai.last_error("C1"))
            self.assertIsNotNone(ask("C2"))
        self.assertEqual(len(provider.requests), 3)

    def test_one_companys_error_is_not_anothers(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL):
            with FakeProvider(status=500):
                ask("C1")
            with FakeProvider():
                ask("C2")
            self.assertIn("HTTP 500", crm_ai.status("C1")["lastError"])
            self.assertEqual(crm_ai.status("C2")["lastError"], "")
            with FakeProvider():
                ask("C1")
            self.assertEqual(crm_ai.status("C1")["mode"], "model")


class AdvisorVisibility(ClientBlueprintCase):
    """The advisor answers from the asker's own book, as every other screen does."""

    def setUp(self):
        super().setUp()
        crm_ai.reset_for_tests()
        self.add_staff("Asha Rao", "telecaller")
        self.add_staff("Ravi Iyer", "telecaller")
        self.add_lead(self.owner, "Aarti", owner="Asha Rao")
        self.add_lead(self.owner, "Bhavesh", owner="Ravi Iyer")
        self.asha = self.sign_in("asha.rao@blueprint.invalid")

    def sent_data(self, client):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider() as provider:
            res = self.call(client, "POST", "/api/ai-advisor", json={"query": "Which leads do I have?"})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(res.json()["source"], "model")
        return provider.requests[0]["body"]["messages"][1]["content"]

    def test_telecaller_sends_only_their_own_records(self):
        data = self.sent_data(self.asha)
        self.assertIn("Aarti", data)
        self.assertNotIn("Bhavesh", data)
        self.assertNotIn("Ravi Iyer", data)

    def test_owner_sends_the_whole_book(self):
        data = self.sent_data(self.owner)
        self.assertIn("Aarti", data)
        self.assertIn("Bhavesh", data)

    def test_built_in_answers_are_scoped_too(self):
        with ai_env():
            res = self.call(self.asha, "POST", "/api/ai-advisor", json={"query": "pipeline breakdown"})
        body = res.json()
        self.assertEqual(body["source"], "built-in")
        self.assertIn("Pipeline (1 accounts)", body["answer"])
        self.assertIn("OPENROUTER_API_KEY", body["notice"])

    def test_status_reports_mode_and_usage(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL, AI_DAILY_LIMIT="5"):
            status = self.asha.get("/api/ai-advisor/status").json()
        self.assertEqual((status["modelConfigured"], status["dailyLimit"], status["usedToday"]), (True, 5, 0))


if __name__ == "__main__":
    unittest.main()
