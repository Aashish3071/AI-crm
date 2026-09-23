"""Security and tenant-isolation acceptance tests for the CRM HTTP boundary."""
import os
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_security
import pipecat_server as server


class SecurityFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = {
            "db": server.DB_FILE, "tenant": server.TENANT_ROOT, "identity": crm_security.IDENTITY_STORE_PATH,
            "auth": server.AUTH_DISABLED, "session": os.environ.get("SESSION_SECRET"),
        }
        server.DB_FILE = os.path.join(self.temp.name, "legacy.json")
        server.TENANT_ROOT = os.path.join(self.temp.name, "tenants")
        crm_security.IDENTITY_STORE_PATH = os.path.join(self.temp.name, "identities.json")
        server.AUTH_DISABLED = False
        os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-and-isolated"
        server._AUTH_FAILURES.clear()
        self.client = TestClient(server.app)

    def tearDown(self):
        server.DB_FILE = self.original["db"]
        server.TENANT_ROOT = self.original["tenant"]
        crm_security.IDENTITY_STORE_PATH = self.original["identity"]
        server.AUTH_DISABLED = self.original["auth"]
        if self.original["session"] is None: os.environ.pop("SESSION_SECRET", None)
        else: os.environ["SESSION_SECRET"] = self.original["session"]
        self.temp.cleanup()

    def _csrf(self, client):
        return {"X-CSRF-Token": client.cookies.get(crm_security.CSRF_COOKIE)}

    def test_auth_csrf_roles_and_company_isolation(self):
        self.assertEqual(self.client.get("/api/leads").status_code, 401)
        weak = self.client.post("/api/auth/bootstrap", json={
            "companyName":"Broker One", "name":"Admin One", "email":"admin@one.invalid", "password":"weak"
        })
        self.assertEqual(weak.status_code, 422)
        setup = self.client.post("/api/auth/bootstrap", json={
            "companyName":"Broker One", "name":"Admin One", "email":"admin@one.invalid", "password":"StrongPassword!42"
        })
        self.assertEqual(setup.status_code, 200)
        self.assertEqual(setup.headers["x-frame-options"], "DENY")
        self.assertEqual(setup.headers["x-content-type-options"], "nosniff")
        company_one = setup.json()["company"]["id"]
        self.assertEqual(self.client.post("/api/leads", json={"firstName":"No CSRF", "mobile":"1"}).status_code, 403)
        created = self.client.post("/api/leads", headers=self._csrf(self.client), json={
            "firstName":"Tenant", "lastName":"One", "mobile":"+919000000001"
        })
        self.assertEqual(created.status_code, 200)
        appointment = self.client.post("/api/calendar/events", headers=self._csrf(self.client), json={
            "title":"Tenant-private meeting", "date":"2026-09-10", "time":"10:00",
            "associatedType":"Lead", "associatedId":created.json()["id"]
        })
        self.assertEqual(appointment.status_code, 200)

        readonly = self.client.post("/api/users", headers=self._csrf(self.client), json={
            "name":"Auditor", "email":"audit@one.invalid", "role":"Read-only Auditor",
            "temporaryPassword":"AuditPassword!42"
        })
        self.assertEqual(readonly.status_code, 200)
        auditor = TestClient(server.app)
        self.assertEqual(auditor.post("/api/auth/login", json={"email":"audit@one.invalid", "password":"AuditPassword!42"}).status_code, 200)
        self.assertEqual(auditor.get("/api/leads").status_code, 200)
        self.assertEqual(auditor.post("/api/tasks", headers=self._csrf(auditor), json={"title":"Forbidden", "dueDate":"2026-09-05"}).status_code, 403)
        self.assertEqual(auditor.get("/api/backups").status_code, 403)

        store = crm_security._load_identities()
        company_two = {"id":"CO_SECOND", "name":"Broker Two", "status":"Active", "createdAt":int(time.time())}
        user_two = {"id":"USR_SECOND", "companyId":"CO_SECOND", "name":"Admin Two", "email":"admin@two.invalid",
                    "role":"Administrator", "status":"Active", "passwordHash":crm_security._password_hash("SecondPassword!42"),
                    "createdAt":int(time.time()), "passwordChangedAt":int(time.time())}
        store["companies"].append(company_two); store["users"].append(user_two); crm_security._save_identities(store)
        second = TestClient(server.app)
        self.assertEqual(second.post("/api/auth/login", json={"email":"admin@two.invalid", "password":"SecondPassword!42"}).status_code, 200)
        self.assertEqual(second.get("/api/leads").json(), [])
        self.assertEqual(second.get("/api/calendar").json()["entries"], [])
        self.assertEqual(len(self.client.get("/api/leads").json()), 1)
        self.assertTrue(any(item["title"] == "Tenant-private meeting" for item in self.client.get("/api/calendar").json()["entries"]))
        self.assertNotEqual(company_one, company_two["id"])

        # Deactivation takes effect immediately even if an older signed cookie exists.
        user_id = readonly.json()["id"]
        self.client.delete(f"/api/users/{user_id}", headers=self._csrf(self.client))
        self.assertEqual(auditor.get("/api/leads").status_code, 401)


if __name__ == "__main__":
    unittest.main()
