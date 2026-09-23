"""Acceptance tests against the client's own blueprint.

Source: Insurance_Telecalling_CRM_Blueprint.pdf. Each test names the slide whose
requirement it proves, so "done" is measured against the client's document rather
than against our internal one. Every test signs in as a real user through the HTTP
boundary; nothing here calls internal functions to fake a result.
"""
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_security
import pipecat_server as server

OWNER_PASSWORD = "OwnerPassword!2026"
STAFF_PASSWORD = "StaffPassword!2026"


def slide(number, requirement):
    """Tag a test with the blueprint slide and requirement it proves."""
    def decorate(fn):
        fn.slide, fn.requirement = number, requirement
        return fn
    return decorate


class ClientBlueprintCase(unittest.TestCase):
    """A fresh company with an owner, signed in, for every test."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.original = {
            "db": server.DB_FILE, "tenant": server.TENANT_ROOT, "docs": server.DOCUMENT_ROOT,
            "backups": server.BACKUP_ROOT, "identity": crm_security.IDENTITY_STORE_PATH,
            "auth": server.AUTH_DISABLED, "session": os.environ.get("SESSION_SECRET"),
        }
        server.DB_FILE = os.path.join(self.temp.name, "default.json")
        server.TENANT_ROOT = os.path.join(self.temp.name, "tenants")
        server.DOCUMENT_ROOT = os.path.join(self.temp.name, "documents")
        server.BACKUP_ROOT = os.path.join(self.temp.name, "backups")
        crm_security.IDENTITY_STORE_PATH = os.path.join(self.temp.name, "identity.json")
        server.AUTH_DISABLED = False
        os.environ["SESSION_SECRET"] = "client-blueprint-test-secret-long-enough"
        server._AUTH_FAILURES.clear()

        self.owner = TestClient(server.app)
        setup = self.owner.post("/api/auth/bootstrap", json={
            "companyName": "Blueprint Telecalling", "name": "Owner One",
            "email": "owner@blueprint.invalid", "password": OWNER_PASSWORD})
        self.assertEqual(setup.status_code, 200, setup.text)
        self.company_id = setup.json()["company"]["id"]

    def tearDown(self):
        server.DB_FILE = self.original["db"]
        server.TENANT_ROOT = self.original["tenant"]
        server.DOCUMENT_ROOT = self.original["docs"]
        server.BACKUP_ROOT = self.original["backups"]
        crm_security.IDENTITY_STORE_PATH = self.original["identity"]
        server.AUTH_DISABLED = self.original["auth"]
        if self.original["session"] is None:
            os.environ.pop("SESSION_SECRET", None)
        else:
            os.environ["SESSION_SECRET"] = self.original["session"]
        self.temp.cleanup()

    # ── helpers ──
    @staticmethod
    def csrf(client):
        return {"X-CSRF-Token": client.cookies.get(crm_security.CSRF_COOKIE)}

    def call(self, client, method, path, **kwargs):
        if method.upper() not in {"GET", "HEAD"}:
            kwargs.setdefault("headers", {}).update(self.csrf(client))
        return client.request(method, path, **kwargs)

    def add_staff(self, name, role, email=None, title=""):
        email = email or f"{name.lower().replace(' ', '.')}@blueprint.invalid"
        res = self.call(self.owner, "POST", "/api/users", json={
            "name": name, "email": email, "role": role, "title": title, "temporaryPassword": STAFF_PASSWORD})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def sign_in(self, email, password=STAFF_PASSWORD):
        client = TestClient(server.app)
        res = client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(res.status_code, 200, res.text)
        return client

    @contextmanager
    def company_db(self):
        """Direct access to this company's records, for fixtures the HTTP API cannot create —
        for example a follow-up finished at a particular moment in the past."""
        token = server.company_context.set(self.company_id)
        try:
            db = server.load_db()
            yield db
            server.save_db(db)
        finally:
            server.company_context.reset(token)

    def add_lead(self, client, first, owner=None, mobile=None):
        body = {"firstName": first, "lastName": "Test", "mobile": mobile or f"+91 90000 {abs(hash(first)) % 100000:05d}"}
        if owner:
            body["assignedTo"] = owner
        res = self.call(client, "POST", "/api/leads", json=body)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()


# ─── Slide 10: user roles and access ─────────────────────────────────────────
class RolesAndAccess(ClientBlueprintCase):

    @slide(10, "A job title grants no privilege; only the four roles do")
    def test_job_title_cannot_escalate_privilege(self):
        staff = self.add_staff("Senior Person", "telecaller", title="Senior Sales Executive")
        self.assertEqual(staff["role"], "telecaller")
        self.assertEqual(staff["title"], "Senior Sales Executive")
        client = self.sign_in("senior.person@blueprint.invalid")
        # Managers may configure assignment rules; a telecaller may not.
        res = self.call(client, "POST", "/api/assignment-rules", json={
            "name": "Try", "conditions": [], "assignees": ["Senior Person"]})
        self.assertEqual(res.status_code, 403)

    @slide(10, "Legacy titles that contain 'lead' or 'senior' are not managers")
    def test_legacy_titles_map_exactly(self):
        for title in ("Senior Sales Executive", "Lead Generation Executive", "Account Manager", "Thread Specialist"):
            self.assertEqual(crm_security.normalized_role(title), "telecaller", title)
        self.assertEqual(crm_security.normalized_role("Administrator"), "admin")
        self.assertEqual(crm_security.normalized_role("Read-only Auditor"), "readonly")

    @slide(10, "An unknown role is refused rather than silently guessed")
    def test_unknown_role_rejected(self):
        res = self.call(self.owner, "POST", "/api/users", json={
            "name": "Mystery", "email": "m@blueprint.invalid", "role": "Supreme Leader",
            "temporaryPassword": STAFF_PASSWORD})
        self.assertEqual(res.status_code, 422)
        self.assertIn("Owner / Admin", res.json()["detail"])

    @slide(42, "The company can never lose its last Owner / Admin")
    def test_last_admin_is_protected(self):
        roster = self.call(self.owner, "GET", "/api/users").json()
        me = next(u for u in roster if crm_security.normalized_role(u["role"]) == "admin")
        demote = self.call(self.owner, "PUT", f"/api/users/{me['id']}", json={"role": "telecaller"})
        self.assertEqual(demote.status_code, 409)
        deactivate = self.call(self.owner, "DELETE", f"/api/users/{me['id']}")
        self.assertEqual(deactivate.status_code, 409)
        # With a second owner in place, the first may step down.
        self.add_staff("Second Owner", "admin")
        self.assertEqual(self.call(self.owner, "PUT", f"/api/users/{me['id']}", json={"role": "manager"}).status_code, 200)

    @slide(10, "Two team members cannot share a name")
    def test_rename_cannot_collide(self):
        self.add_staff("Priya Sharma", "telecaller")
        other = self.add_staff("Rohit Verma", "telecaller")
        res = self.call(self.owner, "PUT", f"/api/users/{other['id']}", json={"name": "priya sharma"})
        self.assertEqual(res.status_code, 409)


# ─── Slide 10: a telecaller sees only assigned work ─────────────────────────
class RecordVisibility(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.mine = self.add_lead(self.owner, "PriyaLead", owner="Priya Sharma", mobile="+91 90000 11111")
        self.theirs = self.add_lead(self.owner, "RohitLead", owner="Rohit Verma", mobile="+91 90000 22222")

    @slide(10, "Global search does not reveal another telecaller's customers")
    def test_search_is_scoped(self):
        found = self.call(self.priya, "GET", "/api/search", params={"q": "90000 22222"}).json()
        self.assertEqual(found, [])
        own = self.call(self.priya, "GET", "/api/search", params={"q": "90000 11111"}).json()
        self.assertIn(self.mine["id"], [r["id"] for r in own])
        # Her lead's own contact card may appear too; nothing tied to Rohit's lead may.
        self.assertTrue(all(r.get("leadId") in ("", self.mine["id"]) or r["id"] == self.mine["id"] for r in own))
        # The owner still searches the whole book.
        self.assertTrue(self.call(self.owner, "GET", "/api/search", params={"q": "90000 22222"}).json())

    @slide(10, "Notes follow the record they belong to")
    def test_notes_are_scoped(self):
        note = self.call(self.owner, "POST", "/api/notes", json={
            "title": "Private", "content": "Rohit's customer only", "associatedType": "Lead",
            "associatedId": self.theirs["id"]})
        self.assertEqual(note.status_code, 200, note.text)
        visible = self.call(self.priya, "GET", "/api/notes").json()
        self.assertNotIn(note.json()["id"], [n["id"] for n in visible])
        edit = self.call(self.priya, "PUT", f"/api/notes/{note.json()['id']}", json={"content": "overwritten"})
        self.assertEqual(edit.status_code, 404)
        self.assertIn(note.json()["id"], [n["id"] for n in self.call(self.rohit, "GET", "/api/notes").json()])

    @slide(21, "Documents cannot be listed or downloaded across telecallers")
    def test_documents_are_scoped(self):
        upload = self.call(self.owner, "POST", "/api/documents", params={
            "associatedId": self.theirs["id"], "associatedType": "Lead", "category": "KYC",
            "filename": "aadhaar.pdf"}, content=b"%PDF-1.4\n%test\n", headers={"Content-Type": "application/pdf"})
        self.assertEqual(upload.status_code, 200, upload.text)
        doc_id = upload.json()["id"]
        self.assertNotIn(doc_id, [d["id"] for d in self.call(self.priya, "GET", "/api/documents").json()])
        self.assertEqual(self.call(self.priya, "GET", f"/api/documents/{doc_id}/content").status_code, 404)
        self.assertEqual(self.call(self.rohit, "GET", f"/api/documents/{doc_id}/content").status_code, 200)

    @slide(10, "A lead's lifecycle cannot be opened by id from outside its owner's book")
    def test_lifecycle_is_scoped(self):
        self.assertEqual(self.call(self.priya, "GET", f"/api/lifecycle/{self.theirs['id']}").status_code, 404)
        self.assertEqual(self.call(self.priya, "GET", f"/api/lifecycle/{self.mine['id']}").status_code, 200)


# ─── Ownership survives renames and reassignment ────────────────────────────
class StableOwnership(ClientBlueprintCase):

    @slide(25, "Every owned record carries a stable owner id for attribution")
    def test_owner_id_is_stamped(self):
        staff = self.add_staff("Priya Sharma", "telecaller")
        lead = self.add_lead(self.owner, "Attrib", owner="Priya Sharma")
        stored = self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]
        self.assertEqual(stored["assignedToId"], staff["id"])

    @slide(25, "Renaming a person keeps their whole book, including records the old fan-out missed")
    def test_rename_heals_every_collection(self):
        staff = self.add_staff("Priya Sharma", "telecaller")
        lead = self.add_lead(self.owner, "Renamed", owner="Priya Sharma")
        quote = self.call(self.owner, "POST", "/api/quotations", json={
            "leadId": lead["id"], "insurer": "Acko", "premium": 12000, "assignedTo": "Priya Sharma"})
        self.assertEqual(quote.status_code, 200, quote.text)
        self.assertEqual(self.call(self.owner, "PUT", f"/api/users/{staff['id']}", json={"name": "Priya S"}).status_code, 200)
        self.assertEqual(self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]["assignedTo"], "Priya S")
        quotes = self.call(self.owner, "GET", "/api/quotations", params={"leadId": lead["id"]}).json()
        self.assertEqual(quotes[0]["assignedTo"], "Priya S")

    @slide(12, "Reassigning a lead is never reverted by ownership reconciliation")
    def test_reassignment_sticks(self):
        self.add_staff("Priya Sharma", "telecaller")
        rohit = self.add_staff("Rohit Verma", "telecaller")
        lead = self.add_lead(self.owner, "Moved", owner="Priya Sharma")
        self.assertEqual(self.call(self.owner, "PUT", f"/api/leads/{lead['id']}", json={"assignedTo": "Rohit Verma"}).status_code, 200)
        stored = self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]
        self.assertEqual((stored["assignedTo"], stored["assignedToId"]), ("Rohit Verma", rohit["id"]))


if __name__ == "__main__":
    unittest.main()


# ─── Slide 11: retail lead capture ───────────────────────────────────────────
class RetailLeadCapture(ClientBlueprintCase):

    def lead_body(self, **extra):
        return {"firstName": "Vikram Mehta", "mobile": "+91 98765 11111", **extra}

    @slide(11, "Nothing is invented: no premium, city, territory or company figures appear unless someone said them")
    def test_no_fabricated_fields(self):
        lead = self.call(self.owner, "POST", "/api/leads", json=self.lead_body()).json()
        self.assertEqual((lead["firstName"], lead["lastName"]), ("Vikram", "Mehta"))
        self.assertEqual(lead["premium"], "")
        self.assertEqual(lead["city"], "")
        for invented in ("territory", "industry", "annualRevenue", "noOfEmployees", "gender"):
            self.assertNotIn(invented, lead, f"{invented} should not be stamped on a personal enquiry")

    @slide(11, "Product is Car or Health Insurance; other lines are refused")
    def test_product_catalogue(self):
        ok = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(product="car insurance"))
        self.assertEqual(ok.json()["product"], "Car Insurance")
        refused = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(product="Marine Cargo", mobile="+91 98765 22222"))
        self.assertEqual(refused.status_code, 422)
        self.assertIn("Health Insurance", refused.json()["detail"])

    @slide(11, "Vehicle details are structured and validated")
    def test_vehicle_details(self):
        lead = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(product="Car Insurance", vehicleDetails={
            "registrationNumber": "mh 12 ab 1234", "make": "Maruti", "model": "Swift", "manufactureYear": 2019,
            "fuelType": "petrol", "ncbPercent": 25})).json()
        self.assertEqual(lead["vehicleDetails"]["registrationNumber"], "MH12AB1234")
        self.assertEqual(lead["vehicleDetails"]["fuelType"], "Petrol")
        bad = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(
            mobile="+91 98765 33333", vehicleDetails={"registrationNumber": "NOT-A-PLATE"}))
        self.assertEqual(bad.status_code, 422)
        self.assertIn("Car details", bad.json()["detail"])
        bad_ncb = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(
            mobile="+91 98765 44444", vehicleDetails={"ncbPercent": 30}))
        self.assertEqual(bad_ncb.status_code, 422)

    @slide(11, "Health needs record who is covered")
    def test_health_details(self):
        lead = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(product="Health Insurance", healthDetails={
            "planType": "family floater", "sumInsured": 1000000,
            "members": [{"relation": "self", "age": 38}, {"relation": "Spouse", "age": 35}]})).json()
        self.assertEqual(lead["healthDetails"]["planType"], "Family Floater")
        self.assertEqual([m["relation"] for m in lead["healthDetails"]["members"]], ["Self", "Spouse"])
        bad = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(
            mobile="+91 98765 55555", healthDetails={"members": [{"relation": "Self", "age": 140}]}))
        self.assertEqual(bad.status_code, 422)

    @slide(11, "Existing policy expiry and the lead's renewal date are one value")
    def test_existing_policy_expiry(self):
        lead = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(
            existingPolicy={"insurer": "ICICI Lombard", "expiryDate": "2026-12-15"})).json()
        self.assertEqual(lead["expiryDate"], "2026-12-15")
        edited = self.call(self.owner, "PUT", f"/api/leads/{lead['id']}", json={"expiryDate": "2027-01-10"}).json()
        self.assertEqual(edited["existingPolicy"]["expiryDate"], "2027-01-10")
        self.assertEqual(edited["existingPolicy"]["insurer"], "ICICI Lombard")

    @slide(32, "Lead source comes from the company's list")
    def test_source_vocabulary(self):
        lead = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(leadSource="meta ads")).json()
        self.assertEqual(lead["source"], "Meta Ads")
        refused = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(leadSource="Billboard", mobile="+91 98765 66666"))
        self.assertEqual(refused.status_code, 422)
        unrecorded = self.call(self.owner, "POST", "/api/leads", json=self.lead_body(mobile="+91 98765 77777")).json()
        self.assertEqual(unrecorded["source"], "Not recorded")

    @slide(43, "Capture date is fixed at creation, so response time can be measured")
    def test_lead_date_is_immutable(self):
        lead = self.call(self.owner, "POST", "/api/leads", json=self.lead_body()).json()
        self.call(self.owner, "PUT", f"/api/leads/{lead['id']}", json={"leadDate": "2020-01-01", "city": "Pune"})
        stored = self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]
        self.assertEqual(stored["leadDate"], lead["leadDate"])
        self.assertEqual(stored["city"], "Pune")


# ─── Slide 11: the thirteen-status lifecycle ─────────────────────────────────
class LeadLifecycle(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.lead = self.add_lead(self.owner, "Lifecycle", mobile="+91 90000 30303")

    def stage(self, status, **extra):
        return self.call(self.owner, "PUT", f"/api/leads/{self.lead['id']}/stage", json={"status": status, **extra})

    @slide(11, "Only the blueprint's thirteen statuses are accepted")
    def test_statuses_are_fixed(self):
        self.assertEqual(self.stage("Qualified", nextAction="Call", nextActionDate="2026-10-10").status_code, 422)
        refused = self.call(self.owner, "PUT", "/api/settings", json={"crm": {"leadStages": ["New", "Qualified"]}})
        self.assertEqual(refused.status_code, 422)

    @slide(16, "Not Interested closes the lead and requires a reason")
    def test_not_interested_needs_reason(self):
        self.assertEqual(self.stage("Not Interested").status_code, 422)
        done = self.stage("Not Interested", lostReason="Renewed with current insurer")
        self.assertEqual(done.status_code, 200, done.text)
        lead = done.json()["lead"]
        self.assertEqual((lead["nextAction"], lead["nextActionDate"]), ("", ""))
        tasks = self.call(self.owner, "GET", "/api/tasks").json()
        self.assertFalse([t for t in tasks if t.get("associatedId") == self.lead["id"] and t["status"] == "Pending"])

    @slide(11, "An open status still needs a next action and date")
    def test_open_status_needs_next_action(self):
        self.assertEqual(self.stage("Interested").status_code, 422)
        self.assertEqual(self.stage("Interested", nextAction="Send quote", nextActionDate="2026-10-10").status_code, 200)

    @slide(22, "A sale records when it happened; later edits do not move it")
    def test_sale_date_is_recorded_once(self):
        sold = self.stage("Policy Sold").json()["lead"]
        self.assertTrue(sold["soldAt"])
        self.call(self.owner, "PUT", f"/api/leads/{self.lead['id']}", json={"city": "Nashik"})
        again = self.call(self.owner, "GET", f"/api/leads/{self.lead['id']}").json()["lead"]
        self.assertEqual(again["soldAt"], sold["soldAt"])

    @slide(11, "Older six-stage values are understood and migrated")
    def test_legacy_status_accepted(self):
        moved = self.stage("Quotation Sent", nextAction="Chase", nextActionDate="2026-10-10").json()["lead"]
        self.assertEqual(moved["status"], "Quote Sent")


# ─── Slide 12: only the owner reassigns ──────────────────────────────────────
class LeadOwnership(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.mine = self.add_lead(self.owner, "Hers", owner="Priya Sharma", mobile="+91 90000 40404")
        self.theirs = self.add_lead(self.owner, "His", owner="Rohit Verma", mobile="+91 90000 50505")

    @slide(12, "A telecaller cannot reassign a lead, even their own")
    def test_telecaller_cannot_reassign(self):
        res = self.call(self.priya, "PUT", f"/api/leads/{self.mine['id']}", json={"assignedTo": "Rohit Verma"})
        self.assertEqual(res.status_code, 403)
        self.assertEqual(self.call(self.owner, "PUT", f"/api/leads/{self.mine['id']}", json={"assignedTo": "Rohit Verma"}).status_code, 200)

    @slide(10, "A telecaller cannot edit or move another telecaller's lead")
    def test_other_leads_are_out_of_reach(self):
        self.assertEqual(self.call(self.priya, "PUT", f"/api/leads/{self.theirs['id']}", json={"city": "Goa"}).status_code, 404)
        self.assertEqual(self.call(self.priya, "PUT", f"/api/leads/{self.theirs['id']}/stage",
                                   json={"status": "Lost", "lostReason": "sabotage"}).status_code, 404)
        self.assertEqual(self.call(self.priya, "PUT", f"/api/leads/{self.mine['id']}", json={"city": "Goa"}).status_code, 200)


class TelecallerCreatedLeads(ClientBlueprintCase):

    @slide(12, "A lead a telecaller creates stays theirs, whatever the routing rules say")
    def test_own_lead_stays_with_creator(self):
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        priya = self.sign_in("priya.sharma@blueprint.invalid")
        lead = self.call(priya, "POST", "/api/leads", json={
            "firstName": "Walk In", "mobile": "+91 90000 60606", "assignedTo": "Rohit Verma"}).json()
        self.assertEqual(lead["assignedTo"], "Priya Sharma")

    @slide(11, "Screens read the lead vocabulary from one place")
    def test_lead_options(self):
        options = self.call(self.owner, "GET", "/api/lead-options").json()
        self.assertEqual(len(options["statuses"]), 13)
        self.assertEqual(options["products"], ["Car Insurance", "Health Insurance"])
        self.assertIn("Policy Sold", options["noNextAction"])


# ─── Slide 17: follow-up management ──────────────────────────────────────────
class FollowUps(ClientBlueprintCase):
    IST = ZoneInfo("Asia/Kolkata")

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")

    def task(self, client, **body):
        res = self.call(client, "POST", "/api/tasks", json={"title": "Call back", **body})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    @slide(13, "A follow-up can carry a time of day, and the lead's next action keeps it")
    def test_follow_up_time(self):
        lead = self.add_lead(self.owner, "Timed", owner="Priya Sharma", mobile="+91 90000 70707")
        moved = self.call(self.owner, "PUT", f"/api/leads/{lead['id']}/stage", json={
            "status": "Interested", "nextAction": "Send quotation", "nextActionDate": "2026-10-10", "nextActionTime": "15:30"})
        self.assertEqual(moved.status_code, 200, moved.text)
        tasks = self.call(self.owner, "GET", "/api/tasks").json()
        current = next(t for t in tasks if t["id"] == moved.json()["lead"]["nextActionTaskId"])
        self.assertEqual((current["dueDate"], current["dueTime"]), ("2026-10-10", "15:30"))
        self.assertEqual(self.call(self.owner, "PUT", f"/api/tasks/{current['id']}", json={"dueTime": "25:00"}).status_code, 422)
        self.call(self.owner, "PUT", f"/api/tasks/{current['id']}", json={"dueTime": "11:00"})
        self.assertEqual(self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]["nextActionTime"], "11:00")

    @slide(10, "A task nobody named is not handed to a demo user")
    def test_task_owner_default(self):
        lead = self.add_lead(self.owner, "Owned", owner="Rohit Verma", mobile="+91 90000 80808")
        linked = self.task(self.owner, dueDate="2026-10-10", associatedType="Lead", associatedId=lead["id"])
        self.assertEqual(linked["assignedTo"], "Rohit Verma")
        own = self.task(self.priya, dueDate="2026-10-10", assignedTo="Rohit Verma")
        self.assertEqual(own["assignedTo"], "Priya Sharma")

    @slide(10, "A telecaller cannot finish, move or delete another telecaller's follow-up")
    def test_task_access(self):
        rohits = self.task(self.owner, dueDate="2026-10-10", assignedTo="Rohit Verma")
        self.assertEqual(self.call(self.priya, "PUT", f"/api/tasks/{rohits['id']}", json={"status": "Completed"}).status_code, 404)
        self.assertEqual(self.call(self.priya, "DELETE", f"/api/tasks/{rohits['id']}").status_code, 404)
        mine = self.task(self.priya, dueDate="2026-10-10")
        self.assertEqual(self.call(self.priya, "PUT", f"/api/tasks/{mine['id']}", json={"assignedTo": "Rohit Verma"}).status_code, 403)
        self.assertEqual(self.call(self.priya, "PUT", f"/api/tasks/{mine['id']}", json={"status": "Completed"}).status_code, 200)

    @slide(17, "On-time rate is never a placeholder: with nothing due, there is no rate")
    def test_on_time_rate_is_not_invented(self):
        metrics = self.call(self.owner, "GET", "/api/follow-ups").json()["metrics"]
        self.assertIsNone(metrics["onTimeRate"])
        self.assertEqual(metrics["onTimeBasis"]["cameDue"], 0)

    @slide(17, "On-time rate is the share of due follow-ups finished by their due time")
    def test_on_time_rate_is_measured(self):
        now = datetime.now(self.IST)
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        on_time = self.task(self.owner, dueDate=yesterday, assignedTo="Priya Sharma")
        late = self.task(self.owner, dueDate=yesterday, assignedTo="Priya Sharma")
        self.task(self.owner, dueDate=yesterday, assignedTo="Priya Sharma")              # still open: missed
        legacy = self.task(self.owner, dueDate=yesterday, assignedTo="Priya Sharma")     # finished, time unknown
        with self.company_db() as db:
            for t in db["tasks"]:
                if t["id"] == on_time["id"]:
                    t.update(status="Completed", completedAt=(now - timedelta(days=1, hours=2)).astimezone(ZoneInfo("UTC")).isoformat())
                if t["id"] == late["id"]:
                    t.update(status="Completed", completedAt=now.astimezone(ZoneInfo("UTC")).isoformat())
                if t["id"] == legacy["id"]:
                    t.update(status="Completed", completedAt="")
        metrics = self.call(self.owner, "GET", "/api/follow-ups").json()["metrics"]
        self.assertEqual(metrics["onTimeBasis"], {"days": 30, "cameDue": 3, "onTime": 1, "unmeasured": 1})
        self.assertEqual(metrics["onTimeRate"], 33)
        self.assertEqual(metrics["overdue"], 1)

    @slide(17, "Each follow-up shows customer, employee, product, last interaction and next action")
    def test_follow_up_record_fields(self):
        lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Anita Desai", "mobile": "+91 90000 90909",
            "product": "Health Insurance", "assignedTo": "Priya Sharma", "nextAction": "Call back",
            "nextActionDate": datetime.now(self.IST).strftime("%Y-%m-%d"), "nextActionTime": "23:59", "notes": "Asked for a family floater"}).json()
        today = self.call(self.priya, "GET", "/api/follow-ups").json()["dueToday"]
        row = next(r for r in today if r["associatedId"] == lead["id"])
        self.assertEqual((row["customerName"], row["assignedTo"], row["product"], row["title"]),
                         ("Anita Desai", "Priya Sharma", "Health Insurance", "Call back"))
        self.assertEqual(row["lastInteraction"]["what"], "Initial enquiry")

    @slide(17, "A passed follow-up alerts the telecaller; left for the escalation period, it alerts their manager")
    def test_missed_then_overdue_alerts(self):
        now = datetime.now(self.IST)
        earlier = now - timedelta(hours=2)
        missed = self.task(self.owner, dueDate=earlier.strftime("%Y-%m-%d"), dueTime=earlier.strftime("%H:%M"),
                           assignedTo="Priya Sharma") if earlier.date() == now.date() else None
        overdue = self.task(self.owner, dueDate=(now - timedelta(days=3)).strftime("%Y-%m-%d"), assignedTo="Priya Sharma")
        server.run_jobs_for_all_companies()
        alerts = self.call(self.owner, "GET", "/api/notifications").json()
        kinds = {(a.get("taskId"), a["type"]) for a in alerts}
        self.assertIn((overdue["id"], "Overdue Follow-up"), kinds)
        self.assertNotIn((overdue["id"], "Missed Follow-up"), kinds, "one alert per state, not both")
        escalation = next(a for a in alerts if a.get("taskId") == overdue["id"])
        self.assertEqual(escalation["escalatedTo"], "Owner One")
        if missed:
            self.assertIn((missed["id"], "Missed Follow-up"), kinds)

    @slide(17, "A HOT lead with a follow-up due today raises a high-value alert, once")
    def test_high_value_alert(self):
        expiring = (datetime.now(self.IST) + timedelta(days=3)).strftime("%Y-%m-%d")
        lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Hot Lead", "mobile": "+91 90000 12121",
            "assignedTo": "Priya Sharma", "expiryDate": expiring}).json()
        self.assertEqual(lead["leadPriority"], "HOT")
        server.run_jobs_for_all_companies()
        server.run_jobs_for_all_companies()
        alerts = [a for a in self.call(self.priya, "GET", "/api/notifications").json() if a["type"] == "High-Value Lead"]
        self.assertEqual([a["associatedId"] for a in alerts], [lead["id"]])

    @slide(33, "The built-in scheduler runs for every company, not just the demo workspace")
    def test_scheduler_reaches_real_companies(self):
        overdue = self.task(self.owner, dueDate="2020-01-01", assignedTo="Priya Sharma")
        server.run_jobs_for_all_companies()
        alerts = self.call(self.owner, "GET", "/api/notifications").json()
        self.assertTrue(any(a.get("taskId") == overdue["id"] for a in alerts))

    @slide(10, "The record picker in every form lists only the caller's own records")
    def test_record_picker_is_scoped(self):
        mine = self.add_lead(self.owner, "PickerMine", owner="Priya Sharma", mobile="+91 90000 13131")
        theirs = self.add_lead(self.owner, "PickerTheirs", owner="Rohit Verma", mobile="+91 90000 14141")
        ids = {e["id"] for e in self.call(self.priya, "GET", "/api/entities").json()}
        self.assertIn(mine["id"], ids)
        self.assertNotIn(theirs["id"], ids)
        self.assertIn(theirs["id"], {e["id"] for e in self.call(self.owner, "GET", "/api/entities").json()})


# ─── Slide 21: documents ─────────────────────────────────────────────────────
import base64 as _b64

PDF = b"%PDF-1.4\n% blueprint test\n"


class Documents(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Car Owner", "mobile": "+91 90000 15151",
            "product": "Car Insurance", "assignedTo": "Priya Sharma"}).json()

    def upload(self, client, category, content=PDF, filename="doc.pdf", lead=None):
        return self.call(client, "POST", "/api/documents", params={"associatedId": (lead or self.lead)["id"],
            "associatedType": "Lead", "category": category, "filename": filename},
            content=content, headers={"Content-Type": "application/pdf"})

    def upload_json(self, client, **body):
        return self.call(client, "POST", "/api/documents", json={"associatedType": "Lead", "associatedId": self.lead["id"], **body})

    @slide(21, "Document types are the client's: RC, driving licence, ID, previous policy, health documents")
    def test_document_types(self):
        self.assertEqual(self.upload(self.priya, "rc").json()["category"], "RC")
        self.assertEqual(self.upload(self.priya, "KYC").json()["category"], "ID Proof")      # older label, mapped
        self.assertEqual(self.upload(self.priya, "Horoscope").status_code, 422)

    @slide(41, "Every upload is checked, whichever way it arrives")
    def test_json_uploads_are_checked(self):
        self.assertEqual(self.upload_json(self.priya, category="RC").status_code, 422)                      # no content
        self.assertEqual(self.upload_json(self.priya, category="RC", content=_b64.b64encode(PDF).decode()).status_code, 422)  # no file name
        disguised = self.upload_json(self.priya, category="RC", filename="rc.pdf",
                                     content=_b64.b64encode(b"<script>alert(1)</script>").decode())
        self.assertEqual(disguised.status_code, 422)
        good = self.upload_json(self.priya, category="RC", filename="rc.pdf", content=_b64.b64encode(PDF).decode())
        self.assertEqual(good.status_code, 200, good.text)
        self.assertEqual(good.json()["contentType"], "application/pdf")

    @slide(21, "A telecaller cannot attach documents to another telecaller's customer")
    def test_upload_respects_visibility(self):
        rohits = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Not Hers", "mobile": "+91 90000 16161",
            "assignedTo": "Rohit Verma"}).json()
        self.assertEqual(self.upload(self.priya, "RC", lead=rohits).status_code, 404)

    @slide(21, "The checklist shows what a car policy still needs, and a rejection counts as missing")
    def test_document_status(self):
        status = self.call(self.priya, "GET", f"/api/leads/{self.lead['id']}/document-status").json()
        self.assertEqual(status["missing"], ["RC", "Previous Policy", "ID Proof"])
        rc = self.upload(self.priya, "RC").json()
        self.upload(self.priya, "Previous Policy")
        pending = self.call(self.priya, "GET", f"/api/leads/{self.lead['id']}").json()["documentStatus"]
        self.assertEqual({r["type"]: r["state"] for r in pending["required"]},
                         {"RC": "pending", "Previous Policy": "pending", "ID Proof": "missing"})
        self.assertEqual(self.call(self.owner, "PUT", f"/api/documents/{rc['id']}/verification",
                                   json={"verification": "Rejected", "note": "Photo is blurred"}).status_code, 200)
        after = self.call(self.priya, "GET", f"/api/leads/{self.lead['id']}/document-status").json()
        self.assertEqual(after["missing"], ["RC", "ID Proof"])

    @slide(21, "Documents are verified by an Owner / Admin or Manager, and a rejection says why")
    def test_verification_rules(self):
        doc = self.upload(self.priya, "RC").json()
        self.assertEqual(self.call(self.priya, "PUT", f"/api/documents/{doc['id']}/verification",
                                   json={"verification": "Verified"}).status_code, 403)
        self.assertEqual(self.call(self.owner, "PUT", f"/api/documents/{doc['id']}/verification",
                                   json={"verification": "Rejected"}).status_code, 422)
        verified = self.call(self.owner, "PUT", f"/api/documents/{doc['id']}/verification", json={"verification": "verified"}).json()
        self.assertEqual((verified["verification"], verified["verifiedBy"]), ("Verified", "Owner One"))

    @slide(19, "A telecaller cannot message another telecaller's customer")
    def test_messaging_is_scoped(self):
        rohits = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Not Hers", "mobile": "+91 90000 17171",
            "assignedTo": "Rohit Verma"}).json()
        self.assertEqual(self.call(self.priya, "GET", f"/api/leads/{rohits['id']}/message-options").status_code, 404)
        self.assertEqual(self.call(self.priya, "POST", f"/api/leads/{rohits['id']}/message",
                                   json={"channel": "WhatsApp", "content": "hi"}).status_code, 404)
        self.assertEqual(self.call(self.priya, "GET", f"/api/leads/{self.lead['id']}/message-options").status_code, 200)

    @slide(22, "A rejected document is not evidence for issuing a policy")
    def test_rejected_document_blocks_issuance(self):
        converted = self.call(self.owner, "POST", f"/api/leads/{self.lead['id']}/convert", json={
            "insurer": "Acko", "startDate": "2026-10-01", "expiryDate": "2027-09-30"})
        self.assertEqual(converted.status_code, 200, converted.text)
        policy = converted.json()["policy"]
        docs = {}
        for key in ("proposalForm", "kyc", "payment", "schedule"):
            res = self.call(self.owner, "POST", "/api/documents", json={"associatedType": "Policy", "associatedId": policy["id"],
                "docType": key, "filename": f"{key}.pdf", "content": _b64.b64encode(PDF).decode()})
            self.assertEqual(res.status_code, 200, res.text)
            docs[key] = res.json()
        self.call(self.owner, "PUT", f"/api/documents/{docs['kyc']['id']}/verification",
                  json={"verification": "Rejected", "note": "Name does not match"})
        checklist = {"proposalForm": True, "kyc": True, "payment": True, "schedule": True}
        blocked = self.call(self.owner, "POST", f"/api/policies/{policy['id']}/issue", json={"policyNumber": "P-1", "documentChecklist": checklist})
        self.assertEqual(blocked.status_code, 422)
        self.assertIn("ID Proof", blocked.json()["detail"])
        replacement = self.call(self.owner, "POST", "/api/documents", json={"associatedType": "Policy", "associatedId": policy["id"],
            "docType": "kyc", "filename": "kyc-2.pdf", "content": _b64.b64encode(PDF).decode()})
        self.assertEqual(replacement.status_code, 200)
        issued = self.call(self.owner, "POST", f"/api/policies/{policy['id']}/issue", json={"policyNumber": "P-1", "documentChecklist": checklist})
        self.assertEqual(issued.status_code, 200, issued.text)


# ─── Slide 33: the automation engine ─────────────────────────────────────────
class Automation(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.add_staff("Meena Rao", "manager")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.manager = self.sign_in("meena.rao@blueprint.invalid")

    def rule(self, **body):
        body.setdefault("name", "Test rule")
        body.setdefault("enabled", True)
        res = self.call(self.owner, "POST", "/api/automations", json=body)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def runs(self, rule_id=None):
        return self.call(self.owner, "GET", "/api/automations/runs", params={"ruleId": rule_id} if rule_id else {}).json()

    def lead(self, first, **extra):
        body = {"firstName": first, "mobile": f"+91 9{abs(hash(first)) % 10**9:09d}", "assignedTo": "Priya Sharma", **extra}
        res = self.call(self.owner, "POST", "/api/leads", json=body)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def stage(self, lead, status, **extra):
        body = {"status": status, "nextAction": "Next", "nextActionDate": "2026-12-01", **extra}
        return self.call(self.owner, "PUT", f"/api/leads/{lead['id']}/stage", json=body)

    @slide(33, "All nine slide-33 rows are offered; the built-in and not-yet-available ones say so")
    def test_recipes(self):
        data = self.call(self.owner, "GET", "/api/automations").json()
        rows = {r["key"]: r for r in data["recipes"]}
        self.assertEqual(len([r for r in data["recipes"] if "→" in r["row"]]), 10)
        self.assertIn("builtIn", rows["missed-follow-up"])
        self.assertEqual(self.call(self.owner, "POST", "/api/automations/recipes/target-incentive").status_code, 409)
        added = self.call(self.owner, "POST", "/api/automations/recipes/interested-follow-up")
        self.assertEqual(added.status_code, 200, added.text)
        self.assertEqual(self.call(self.owner, "POST", "/api/automations/recipes/interested-follow-up").status_code, 409)

    @slide(12, "New leads are shared between telecallers by the assignment recipe")
    def test_assignment_recipe(self):
        self.assertEqual(self.call(self.owner, "POST", "/api/automations/recipes/assign-new-leads").status_code, 200)
        owners = [self.call(self.owner, "POST", "/api/leads", json={"firstName": f"Pool{i}", "mobile": f"+91 90001 0000{i}"}).json()["assignedTo"]
                  for i in range(4)]
        self.assertEqual(sorted(owners), ["Priya Sharma", "Priya Sharma", "Rohit Verma", "Rohit Verma"])
        run = self.runs()[0]
        self.assertEqual(run["actions"][0]["detail"].split(" to ")[0], "Assigned")

    @slide(16, "Interested creates a quotation follow-up the same day")
    def test_interested_follow_up(self):
        self.call(self.owner, "POST", "/api/automations/recipes/interested-follow-up")
        lead = self.lead("Keen")
        self.assertEqual(self.stage(lead, "Interested").status_code, 200)
        tasks = [t for t in self.call(self.owner, "GET", "/api/tasks").json() if t.get("createdByRule")]
        self.assertEqual([t["title"] for t in tasks], ["Send quotation to Keen"])
        self.assertEqual(tasks[0]["assignedTo"], "Priya Sharma")

    @slide(33, "New assignment notifies the telecaller")
    def test_assignment_notifies(self):
        self.call(self.owner, "POST", "/api/automations/recipes/notify-assignment")
        lead = self.lead("Notified")
        mine = [n for n in self.call(self.priya, "GET", "/api/notifications").json() if n["type"] == "Automation"]
        self.assertEqual(len(mine), 1)
        self.assertIn("Notified", mine[0]["message"])
        self.call(self.owner, "PUT", f"/api/leads/{lead['id']}", json={"assignedTo": "Rohit Verma"})
        rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.assertEqual(len([n for n in self.call(rohit, "GET", "/api/notifications").json() if n["type"] == "Automation"]), 1)

    @slide(33, "Two rules that trigger each other stop instead of looping")
    def test_loop_prevention(self):
        a = self.rule(name="A", trigger={"type": "lead.status_changed", "params": {"to": "Interested"}},
                      actions=[{"type": "set_status", "params": {"status": "Quote Sent", "nextAction": "Chase"}}])
        b = self.rule(name="B", trigger={"type": "lead.status_changed", "params": {"to": "Quote Sent"}},
                      actions=[{"type": "set_status", "params": {"status": "Interested", "nextAction": "Quote"}}])
        lead = self.lead("Looper")
        self.assertEqual(self.stage(lead, "Interested").status_code, 200)
        self.assertEqual(len(self.runs(a["id"])), 1)
        self.assertEqual(len(self.runs(b["id"])), 1)
        final = self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]
        self.assertEqual(final["status"], "Interested")

    @slide(33, "A rule fires once per occurrence, however often the record is saved")
    def test_idempotent(self):
        r = self.rule(trigger={"type": "lead.created"}, actions=[{"type": "add_note", "params": {"text": "Welcome {{name}}"}}])
        lead = self.lead("Once")
        for city in ("Pune", "Nashik"):
            self.call(self.owner, "PUT", f"/api/leads/{lead['id']}", json={"city": city})
        self.assertEqual(len(self.runs(r["id"])), 1)

    @slide(33, "A rule stops at its hourly limit and says so")
    def test_rate_limit(self):
        r = self.rule(trigger={"type": "lead.created"}, actions=[{"type": "add_note", "params": {"text": "hi"}}],
                      limits={"maxPerHour": 1})
        self.lead("First")
        self.lead("Second")
        runs = self.runs(r["id"])
        self.assertEqual([x["status"] for x in runs], ["skipped", "done"])
        self.assertIn("Hourly limit", runs[0]["reason"])

    @slide(33, "One switch pauses every automation")
    def test_kill_switch(self):
        r = self.rule(trigger={"type": "lead.created"}, actions=[{"type": "add_note", "params": {"text": "hi"}}])
        self.assertEqual(self.call(self.owner, "PUT", "/api/automations/pause", json={"paused": True}).status_code, 200)
        self.lead("Paused")
        self.assertEqual(self.runs(r["id"]), [])
        self.call(self.owner, "PUT", "/api/automations/pause", json={"paused": False})
        self.lead("Resumed")
        self.assertEqual(len(self.runs(r["id"])), 1)

    @slide(19, "Customer messages wait for quiet hours to end")
    def test_quiet_hours(self):
        self.call(self.owner, "PUT", "/api/settings", json={"automation": {"quietHours": {"start": "00:00", "end": "23:59"}}})
        self.rule(trigger={"type": "lead.created"}, actions=[{"type": "send_message", "params": {"channel": "WhatsApp", "text": "Hello {{firstName}}"}}])
        lead = self.lead("Night Owl")
        messages = self.call(self.owner, "GET", "/api/communications", params={"associatedId": lead["id"]}).json()
        self.assertEqual(messages[0]["status"], "Scheduled")
        self.assertTrue(messages[0]["scheduledAt"])
        self.assertEqual(messages[0]["content"], "Hello Night")

    @slide(19, "A customer who opted out is not messaged; the run records why")
    def test_consent_blocks(self):
        r = self.rule(trigger={"type": "lead.status_changed", "params": {"to": "Interested"}},
                      actions=[{"type": "send_message", "params": {"channel": "WhatsApp", "text": "Offer"}},
                               {"type": "add_note", "params": {"text": "Offer attempted"}}])
        lead = self.lead("Opted Out")
        self.call(self.owner, "POST", "/api/consents", json={"leadId": lead["id"], "channel": "WhatsApp", "status": "Opted Out"})
        self.stage(lead, "Interested")
        run = self.runs(r["id"])[0]
        self.assertEqual([a["result"] for a in run["actions"]], ["blocked", "done"])
        self.assertEqual(run["status"], "partial")
        self.assertIn("opted out", run["actions"][0]["detail"])

    @slide(42, "Only the owner changes automations; a manager can review them")
    def test_permissions(self):
        body = {"name": "x", "trigger": {"type": "lead.created"}, "actions": [{"type": "add_note", "params": {"text": "x"}}]}
        self.assertEqual(self.call(self.priya, "GET", "/api/automations").status_code, 403)
        self.assertEqual(self.call(self.manager, "GET", "/api/automations").status_code, 200)
        self.assertEqual(self.call(self.manager, "POST", "/api/automations", json=body).status_code, 403)

    @slide(33, "A new rule is off until switched on, and is checked before it is saved")
    def test_rule_validation(self):
        created = self.call(self.owner, "POST", "/api/automations", json={"name": "Off", "trigger": {"type": "lead.created"},
                            "actions": [{"type": "add_note", "params": {"text": "x"}}]}).json()
        self.assertFalse(created["enabled"])
        for bad in ({"trigger": {"type": "lead.assigned"}, "actions": [{"type": "assign", "params": {"assignees": ["Priya Sharma"]}}]},
                    {"trigger": {"type": "lead.created"}, "conditions": [{"field": "shoeSize", "operator": "is", "value": "9"}],
                     "actions": [{"type": "add_note", "params": {"text": "x"}}]},
                    {"trigger": {"type": "lead.created"}, "actions": [{"type": "assign", "params": {"assignees": ["Nobody Here"]}}]}):
            self.assertEqual(self.call(self.owner, "POST", "/api/automations", json={"name": "Bad", **bad}).status_code, 422, bad)

    @slide(33, "A preview shows what a rule would act on and changes nothing")
    def test_preview(self):
        self.lead("Car One", product="Car Insurance")
        self.lead("Health One", product="Health Insurance")
        before = len(self.call(self.owner, "GET", "/api/tasks").json())
        result = self.call(self.owner, "POST", "/api/automations/preview", json={
            "trigger": {"type": "lead.created"}, "conditions": [{"field": "product", "operator": "is", "value": "Car Insurance"}],
            "actions": [{"type": "create_task", "params": {"title": "x"}}]}).json()
        self.assertEqual((result["checked"], result["matched"]), (2, 1))
        self.assertEqual(len(self.call(self.owner, "GET", "/api/tasks").json()), before)

    @slide(23, "A timed rule fires once per policy expiry, not on every scheduler run")
    def test_timed_trigger(self):
        soon = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=10)).strftime("%Y-%m-%d")
        r = self.rule(trigger={"type": "lead.expiring", "params": {"days": 30}},
                      actions=[{"type": "notify", "params": {"to": "assignee", "message": "{{name}} expires {{expiryDate}}"}}])
        self.lead("Expiring", expiryDate=soon)
        server.run_jobs_for_all_companies()
        server.run_jobs_for_all_companies()
        self.assertEqual(len(self.runs(r["id"])), 1)
        alerts = [n for n in self.call(self.priya, "GET", "/api/notifications").json() if n["type"] == "Automation"]
        self.assertEqual(alerts[0]["message"], f"Expiring expires {soon}")

    @slide(12, "Assignment rules made before automation keep working, unchanged")
    def test_legacy_assignment_rules_migrate(self):
        with self.company_db() as db:
            db.setdefault("settings", {}).setdefault("automation", {})["assignmentRulesMigrated"] = False
            db["assignmentRules"] = [{"id": "RUL_old", "name": "Health to Rohit", "enabled": True, "method": "first",
                                      "assignees": ["Rohit Verma"],
                                      "conditions": [{"field": "policyType", "operator": "contains", "value": "health"}]}]
        listed = self.call(self.owner, "GET", "/api/assignment-rules").json()
        self.assertEqual([r["id"] for r in listed], ["RUL_old"])
        lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Legacy", "mobile": "+91 90002 00001",
                                                                 "product": "Health Insurance"}).json()
        self.assertEqual(lead["assignedTo"], "Rohit Verma")


# ─── Slides 15–16: calling and call outcomes ─────────────────────────────────
class Calling(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Anita Desai", "mobile": "98200 12345",
            "product": "Car Insurance", "assignedTo": "Priya Sharma", "leadSource": "Meta Ads"}).json()

    def ring(self, lead=None, client=None):
        res = self.call(client or self.priya, "POST", "/api/calls/start", json={"leadId": (lead or self.lead)["id"]})
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def finish(self, started, client=None, **result):
        return self.call(client or self.priya, "POST", f"/api/calls/{started['call']['id']}/complete", json=result)

    def lead_now(self):
        return self.call(self.owner, "GET", f"/api/leads/{self.lead['id']}").json()["lead"]

    @slide(15, "Click-to-call dials the customer and shows their record during the call")
    def test_start_call(self):
        started = self.ring()
        self.assertEqual(started["dial"], "tel:+919820012345")
        self.assertEqual(started["call"]["assignedTo"], "Priya Sharma")
        self.assertEqual(started["lead"]["product"], "Car Insurance")
        self.assertIn("documentStatus", started)

    @slide(10, "A telecaller cannot call from, or read the calls of, another telecaller's lead")
    def test_calls_are_scoped(self):
        rohits = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Not Hers", "mobile": "98200 99999",
            "assignedTo": "Rohit Verma"}).json()
        self.assertEqual(self.call(self.priya, "POST", "/api/calls/start", json={"leadId": rohits["id"]}).status_code, 404)
        rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.finish(self.ring(rohits, rohit), rohit, outcome="Interested")
        self.assertEqual(self.call(self.priya, "GET", "/api/calls").json(), [])
        self.assertEqual(len(self.call(self.owner, "GET", "/api/calls").json()), 1)

    @slide(16, "Interested: status moves on and a quotation follow-up is due today")
    def test_interested(self):
        done = self.finish(self.ring(), outcome="Interested", notes="Wants zero depreciation cover").json()
        self.assertTrue(done["call"]["connected"])
        self.assertEqual(done["call"]["durationSource"], "call screen timer")
        lead = self.lead_now()
        self.assertEqual((lead["status"], lead["nextAction"]), ("Interested", "Send quotation to Anita Desai"))
        self.assertEqual(lead["nextActionDate"], datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d"))
        notes = self.call(self.owner, "GET", "/api/notes").json()
        self.assertTrue(any(n.get("category") == "Call" and "zero depreciation" in n["content"] for n in notes))

    @slide(16, "Call back needs a date, and schedules it with the time")
    def test_call_back(self):
        started = self.ring()
        self.assertEqual(self.finish(started, outcome="Call Back").status_code, 422)
        self.assertEqual(self.finish(started, outcome="Call Back", followUpDate="2026-12-01", followUpTime="16:30").status_code, 200)
        lead = self.lead_now()
        self.assertEqual((lead["status"], lead["nextActionDate"], lead["nextActionTime"]), ("Call Later", "2026-12-01", "16:30"))

    @slide(16, "Not interested needs a reason and closes the lead")
    def test_not_interested(self):
        started = self.ring()
        self.assertEqual(self.finish(started, outcome="Not Interested").status_code, 422)
        self.finish(started, outcome="Not Interested", reason="Premium too high")
        lead = self.lead_now()
        self.assertEqual((lead["status"], lead["lostReason"], lead["nextAction"]), ("Not Interested", "Premium too high", ""))

    @slide(16, "No answer schedules a retry without undoing progress")
    def test_busy(self):
        self.finish(self.ring(), outcome="Busy / Switched Off")
        self.assertEqual(self.lead_now()["status"], "Unreachable")
        self.finish(self.ring(), outcome="Interested")
        done = self.finish(self.ring(), outcome="Busy / Switched Off").json()
        self.assertFalse(done["call"]["connected"])
        lead = self.lead_now()
        self.assertEqual(lead["status"], "Interested")
        self.assertEqual(lead["unansweredCalls"], 2)
        self.assertTrue(lead["nextAction"].startswith("Retry call"))

    @slide(16, "A wrong number is flagged for review")
    def test_wrong_number(self):
        self.finish(self.ring(), outcome="Wrong Number")
        lead = self.lead_now()
        self.assertEqual((lead["status"], lead["flaggedForReview"]), ("Wrong Number", True))
        review = [n for n in self.call(self.owner, "GET", "/api/notifications").json() if n["type"] == "Lead Review"]
        self.assertEqual(review[0]["assignedTo"], "Owner One")

    @slide(16, "Already insured goes on the renewal watchlist with a call booked before expiry")
    def test_already_insured(self):
        started = self.ring()
        self.assertEqual(self.finish(started, outcome="Already Insured").status_code, 422)
        self.finish(started, outcome="Already Insured", currentExpiryDate="2027-03-31")
        lead = self.lead_now()
        self.assertEqual((lead["watchlist"], lead["expiryDate"], lead["nextActionDate"]), ("Already insured", "2027-03-31", "2027-03-01"))

    @slide(16, "Documents pending names what to collect")
    def test_documents_pending(self):
        self.finish(self.ring(), outcome="Documents Pending")
        lead = self.lead_now()
        self.assertEqual(lead["status"], "Documents Pending")
        self.assertEqual(lead["nextAction"], "Collect documents from Anita Desai: RC, Previous Policy, ID Proof")

    @slide(22, "Policy sold creates the policy with sale date, lead source and renewal date")
    def test_policy_sold(self):
        started = self.ring()
        self.assertEqual(self.finish(started, outcome="Policy Sold").status_code, 422)
        self.finish(started, outcome="Policy Sold", policy={"insurer": "Acko", "premium": 14500,
                                                             "startDate": "2026-10-01", "expiryDate": "2027-09-30"})
        lead = self.lead_now()
        self.assertEqual(lead["status"], "Policy Sold")
        self.assertTrue(lead["soldAt"])
        policy = next(p for p in self.call(self.owner, "GET", "/api/policies").json() if p["id"] == lead["convertedPolicyId"])
        self.assertEqual((policy["renewalDate"], policy["leadSource"], policy["policyType"], policy["assignedTo"]),
                         ("2027-09-30", "Meta Ads", "Car Insurance", "Priya Sharma"))
        self.assertTrue(policy["saleDate"])
        orgs = self.call(self.owner, "GET", "/api/organizations").json()
        self.assertFalse(any(o["name"] == "Private Individual" for o in orgs))

    @slide(15, "An outcome is recorded once")
    def test_outcome_once(self):
        started = self.ring()
        self.finish(started, outcome="Interested")
        self.assertEqual(self.finish(started, outcome="Not Interested", reason="x").status_code, 409)

    @slide(15, "A call logged afterwards records no invented length")
    def test_logged_afterwards(self):
        res = self.call(self.priya, "POST", "/api/calls", json={"leadId": self.lead["id"], "outcome": "Call Back",
                                                              "followUpDate": "2026-12-02"}).json()
        self.assertEqual((res["call"]["durationSeconds"], res["call"]["durationSource"]), (None, "not recorded"))
        timed = self.call(self.priya, "POST", "/api/calls", json={"leadId": self.lead["id"], "outcome": "Interested",
                                                                "durationSeconds": 185}).json()
        self.assertEqual((timed["call"]["durationSeconds"], timed["call"]["durationSource"]), (185, "entered by telecaller"))

    @slide(33, "A logged call can trigger an automation, filtered by outcome")
    def test_call_trigger(self):
        rule = self.call(self.owner, "POST", "/api/automations", json={"name": "Hot on interest", "enabled": True,
            "trigger": {"type": "call.logged", "params": {"to": "Interested"}},
            "actions": [{"type": "set_priority", "params": {"priority": "HOT"}}]}).json()
        self.finish(self.ring(), outcome="Busy / Switched Off")
        self.assertNotEqual(self.lead_now()["leadPriority"], "HOT")
        self.finish(self.ring(), outcome="Interested")
        self.assertEqual(self.lead_now()["leadPriority"], "HOT")
        self.assertEqual(len(self.call(self.owner, "GET", "/api/automations/runs", params={"ruleId": rule["id"]}).json()), 1)

    @slide(15, "Older call records stored lengths as text; they are read as seconds")
    def test_legacy_durations(self):
        self.assertEqual([server._parse_duration(v) for v in ("42s", "2m 30s", "1h 2m 3s", 90, "")], [42, 150, 3723, 90, None])


# ─── Slides 14, 26, 29, 34: performance, targets and role dashboards ─────────
class Performance(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.month = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m")

    def lead_for(self, owner, first, **extra):
        return self.call(self.owner, "POST", "/api/leads", json={"firstName": first, "mobile": f"+91 9{abs(hash(first)) % 10**9:09d}",
                                                                 "assignedTo": owner, "product": "Car Insurance", **extra}).json()

    def called(self, client, lead, outcome, seconds, **extra):
        res = self.call(client, "POST", "/api/calls", json={"leadId": lead["id"], "outcome": outcome, "durationSeconds": seconds, **extra})
        self.assertEqual(res.status_code, 200, res.text)

    def work_a_day(self):
        a, b = self.lead_for("Priya Sharma", "Alpha"), self.lead_for("Priya Sharma", "Beta")
        self.called(self.priya, a, "Interested", 200)
        self.called(self.priya, b, "Busy / Switched Off", 20)
        self.called(self.priya, a, "Policy Sold", 100, policy={"insurer": "Acko", "premium": 12000, "expiryDate": "2027-09-30"})
        c = self.lead_for("Rohit Verma", "Gamma")
        self.called(self.rohit, c, "Interested", 60)
        self.call(self.owner, "PUT", f"/api/leads/{c['id']}/stage", json={"status": "Quote Sent", "nextAction": "Chase", "nextActionDate": "2026-12-01"})

    @slide(26, "Each person's calls, connections, quotes, sales, premium and conversion, from one definition")
    def test_measures(self):
        self.work_a_day()
        data = self.call(self.owner, "GET", "/api/performance", params={"period": "today"}).json()
        rows = {r["person"]: r for r in data["rows"]}
        priya, rohit = rows["Priya Sharma"], rows["Rohit Verma"]
        self.assertEqual((priya["newLeads"], priya["calls"], priya["connected"], priya["notConnected"]), (2, 3, 2, 1))
        self.assertEqual((priya["interested"], priya["policiesSold"], priya["premium"]), (1, 1, 12000))
        self.assertEqual(priya["avgCallSeconds"], 150)             # connected calls only: (200 + 100) / 2
        self.assertEqual(priya["conversionRate"], 50.0)
        self.assertEqual((rohit["quotesSent"], rohit["policiesSold"], rohit["conversionRate"]), (1, 0, 0.0))
        self.assertEqual((data["totals"]["calls"], data["totals"]["policiesSold"], data["totals"]["conversionRate"]), (4, 1, 33.3))

    @slide(10, "A telecaller sees only their own performance")
    def test_own_performance_only(self):
        self.work_a_day()
        mine = self.call(self.priya, "GET", "/api/performance", params={"period": "month"}).json()
        self.assertEqual([r["person"] for r in mine["rows"]], ["Priya Sharma"])
        self.assertEqual(self.call(self.priya, "GET", "/api/dashboard/telecaller", params={"person": "Rohit Verma"}).status_code, 404)
        self.assertEqual(self.call(self.priya, "GET", "/api/dashboard/owner").status_code, 403)

    @slide(29, "The owner sets monthly targets and sees achievement against them")
    def test_targets(self):
        self.work_a_day()
        self.assertEqual(self.call(self.priya, "PUT", "/api/targets", json={"month": self.month, "person": "Priya Sharma",
                                                                           "policiesSold": 99}).status_code, 403)
        self.assertEqual(self.call(self.owner, "PUT", "/api/targets", json={"month": self.month, "person": "Priya Sharma",
                                                                           "policiesSold": -1}).status_code, 422)
        data = self.call(self.owner, "PUT", "/api/targets", json={"month": self.month, "person": "Priya Sharma",
                                                                 "policiesSold": 2, "premium": 48000}).json()
        priya = next(r for r in data["rows"] if r["person"] == "Priya Sharma")
        self.assertEqual(priya["achievement"]["percent"], 50.0)                  # 1 of 2 policies (the default headline)
        self.assertEqual(priya["achievement"]["measures"]["premium"]["percent"], 25.0)
        rohit = next(r for r in data["rows"] if r["person"] == "Rohit Verma")
        self.assertIsNone(rohit["achievement"]["percent"])                       # no target set: no figure invented
        nxt = (datetime.strptime(self.month + "-01", "%Y-%m-%d") + timedelta(days=32)).strftime("%Y-%m")
        copied = self.call(self.owner, "POST", "/api/targets/copy", json={"from": self.month, "to": nxt}).json()
        self.assertEqual(copied["copied"], 1)

    @slide(14, "The telecaller dashboard shows their day and their priority leads")
    def test_telecaller_dashboard(self):
        self.work_a_day()
        self.call(self.owner, "PUT", "/api/targets", json={"month": self.month, "person": "Priya Sharma", "policiesSold": 4})
        hot = self.lead_for("Priya Sharma", "Urgent", expiryDate=(datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=3)).strftime("%Y-%m-%d"))
        board = self.call(self.priya, "GET", "/api/dashboard/telecaller").json()
        self.assertEqual(board["person"], "Priya Sharma")
        t = board["tiles"]
        self.assertEqual((t["callsDone"], t["connected"], t["interested"], t["policiesSold"], t["targetAchieved"]), (3, 2, 1, 1, 25.0))
        self.assertEqual(board["priorityLeads"][0]["id"], hot["id"])            # HOT first

    @slide(34, "The owner dashboard shows today, the week, the month and the team")
    def test_owner_dashboard(self):
        self.work_a_day()
        board = self.call(self.owner, "GET", "/api/dashboard/owner").json()
        today = board["bands"]["today"]
        self.assertEqual((today["newLeads"], today["calls"], today["connected"], today["policiesSold"], today["premium"]), (3, 4, 3, 1, 12000))
        self.assertEqual(board["team"]["best"], "Priya Sharma")
        self.assertIn("Priya Sharma", board["control"]["employeesOnline"])
        self.assertEqual(board["control"]["missedCallsToday"], 1)

    @slide(31, "A lead's status history records when it reached each stage")
    def test_status_history(self):
        lead = self.lead_for("Priya Sharma", "Historic")
        self.called(self.priya, lead, "Interested", 30)
        history = self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]["statusHistory"]
        self.assertEqual([h["status"] for h in history], ["New", "Interested"])
        self.assertEqual(history[1]["by"], "Priya Sharma")


# ─── Slides 25 and 28–30: commission, incentives and recognition ────────────
class MoneyAndRecognition(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.add_staff("Meena Rao", "manager")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.manager = self.sign_in("meena.rao@blueprint.invalid")
        self.month = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m")

    def sell(self, client, owner, first, premium, insurer="Acko", product="Car Insurance"):
        lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": first, "mobile": f"+91 9{abs(hash(first)) % 10**9:09d}",
                                                                 "assignedTo": owner, "product": product}).json()
        res = self.call(client, "POST", "/api/calls", json={"leadId": lead["id"], "outcome": "Policy Sold", "durationSeconds": 60,
                                                          "policy": {"insurer": insurer, "premium": premium, "expiryDate": "2027-09-30"}})
        self.assertEqual(res.status_code, 200, res.text)
        return self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]["convertedPolicyId"]

    def policy(self, pid):
        return next(p for p in self.call(self.owner, "GET", "/api/policies").json() if p["id"] == pid)

    def rates(self):
        res = self.call(self.owner, "PUT", "/api/commission/rules", json={"rules": [
            {"product": "Car Insurance", "newRate": 15, "renewalRate": 7.5},
            {"product": "Car Insurance", "insurer": "Acko", "newRate": 18}]})
        self.assertEqual(res.status_code, 200, res.text)

    @slide(25, "Commission uses the most specific rate and is fixed at the moment of sale")
    def test_commission_fixed_at_sale(self):
        self.rates()
        acko, other = self.sell(self.priya, "Priya Sharma", "Acko Buyer", 12000), self.sell(self.priya, "Priya Sharma", "Other Buyer", 10000, "HDFC Ergo")
        self.assertEqual((self.policy(acko)["commission"]["rate"], self.policy(acko)["commission"]["amount"]), (18.0, 2160.0))
        self.assertEqual(self.policy(other)["commission"]["amount"], 1500.0)
        self.call(self.owner, "PUT", "/api/commission/rules", json={"rules": [{"product": "Car Insurance", "newRate": 5}]})
        self.assertEqual(self.policy(acko)["commission"]["amount"], 2160.0)       # a later rate change does not rewrite it
        ledger = self.call(self.owner, "GET", "/api/commission", params={"month": self.month}).json()
        priya = next(r for r in ledger["byEmployee"] if r["employee"] == "Priya Sharma")
        self.assertEqual((priya["total"], priya["policies"]), (3660.0, 2))

    @slide(25, "An override needs a reason; received commission is recorded")
    def test_commission_override_and_receipt(self):
        self.rates()
        pid = self.sell(self.priya, "Priya Sharma", "Override", 12000)
        self.assertEqual(self.call(self.owner, "PUT", f"/api/policies/{pid}/commission", json={"amount": 2000}).status_code, 422)
        changed = self.call(self.owner, "PUT", f"/api/policies/{pid}/commission", json={"amount": 2000, "note": "Insurer paid a flat fee"}).json()
        self.assertEqual((changed["commission"]["amount"], changed["commission"]["override"]), (2000.0, True))
        received = self.call(self.owner, "PUT", f"/api/policies/{pid}/commission", json={"status": "Received", "receivedOn": "2026-10-15"}).json()
        self.assertEqual((received["commission"]["status"], received["commission"]["receivedOn"]), ("Received", "2026-10-15"))

    @slide(10, "Commission is the owner's alone")
    def test_commission_is_owner_only(self):
        for client in (self.priya, self.manager):
            self.assertEqual(self.call(client, "GET", "/api/commission").status_code, 403)
            self.assertEqual(self.call(client, "PUT", "/api/commission/rules", json={"rules": []}).status_code, 403)
        pid = self.sell(self.priya, "Priya Sharma", "Not Hers To Change", 9000)
        self.assertEqual(self.call(self.priya, "PUT", f"/api/policies/{pid}/commission", json={"status": "Received"}).status_code, 403)

    @slide(25, "Policies sold before any rate existed can be given today's rates")
    def test_apply_missing(self):
        pid = self.sell(self.priya, "Priya Sharma", "Early Sale", 10000)
        self.assertIsNone(self.policy(pid)["commission"]["amount"])
        self.rates()
        self.assertEqual(self.call(self.owner, "POST", "/api/commission/apply-missing").json()["applied"], 1)
        self.assertEqual(self.policy(pid)["commission"]["amount"], 1800.0)       # Acko's own 18% rate

    def plan(self):
        res = self.call(self.owner, "PUT", "/api/incentives/plan", json={"rules": [
            {"name": "₹500 a car policy", "kind": "per_policy", "amount": 500, "product": "Car Insurance"},
            {"name": "Target bonus", "kind": "target_bonus", "amount": 2000, "atPercent": 100},
            {"name": "Levels", "kind": "slab", "measure": "policiesSold", "slabs": [{"from": 1, "amount": 100}, {"from": 3, "amount": 400}]}]})
        self.assertEqual(res.status_code, 200, res.text)

    @slide(29, "Incentives follow the owner's rules and targets")
    def test_incentives(self):
        self.plan()
        self.call(self.owner, "PUT", "/api/targets", json={"month": self.month, "person": "Priya Sharma", "policiesSold": 1})
        self.sell(self.priya, "Priya Sharma", "Incentive One", 12000)
        self.sell(self.priya, "Priya Sharma", "Health One", 8000, product="Health Insurance")
        data = self.call(self.owner, "GET", "/api/incentives", params={"month": self.month}).json()
        priya = next(r for r in data["rows"] if r["person"] == "Priya Sharma")
        self.assertEqual([l["amount"] for l in priya["lines"]], [500, 2000, 100])   # one car policy, target met, first level
        self.assertEqual((priya["total"], data["status"]), (2600, "Estimate"))
        mine = self.call(self.priya, "GET", "/api/incentives", params={"month": self.month}).json()
        self.assertEqual([r["person"] for r in mine["rows"]], ["Priya Sharma"])
        self.assertEqual(self.call(self.priya, "PUT", "/api/incentives/plan", json={"rules": []}).status_code, 403)

    @slide(29, "A finished month is approved and then frozen")
    def test_incentive_approval(self):
        self.plan()
        self.assertEqual(self.call(self.owner, "POST", f"/api/incentives/{self.month}/approve").status_code, 409)
        last = (datetime.strptime(self.month + "-01", "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m")
        approved = self.call(self.owner, "POST", f"/api/incentives/{last}/approve").json()
        self.assertEqual(approved["status"], "Approved")
        self.call(self.owner, "PUT", "/api/incentives/plan", json={"rules": []})
        self.assertEqual(len(self.call(self.owner, "GET", "/api/incentives", params={"month": last}).json()["rules"]), 3)
        self.assertEqual(self.call(self.owner, "POST", f"/api/incentives/{last}/approve").status_code, 409)

    @slide(28, "The leaderboard ranks the team, and awards need enough to judge by")
    def test_leaderboard(self):
        self.sell(self.priya, "Priya Sharma", "Board One", 20000)
        self.sell(self.rohit, "Rohit Verma", "Board Two", 9000)
        board = self.call(self.owner, "GET", "/api/leaderboard").json()
        self.assertEqual([r["person"] for r in board["ranking"]][:2], ["Priya Sharma", "Rohit Verma"])
        self.assertEqual(board["awards"]["highestPremium"]["winners"], ["Priya Sharma"])
        self.assertEqual(board["awards"]["highestConversion"]["winners"], [])     # one new lead each is too few
        self.assertEqual(self.call(self.priya, "GET", "/api/leaderboard").status_code, 403)
        self.assertEqual(self.call(self.manager, "GET", "/api/leaderboard").status_code, 200)

    @slide(30, "Employee of the Month is a weighted score; call quality is left out until it can be measured")
    def test_employee_of_month(self):
        self.sell(self.priya, "Priya Sharma", "Star One", 20000)
        self.sell(self.priya, "Priya Sharma", "Star Two", 15000)
        self.sell(self.rohit, "Rohit Verma", "Star Three", 9000)
        eotm = self.call(self.owner, "GET", "/api/leaderboard").json()["employeeOfMonth"]
        self.assertEqual(eotm["winner"], "Priya Sharma")
        self.assertEqual(eotm["leftOut"], ["callQuality"])
        self.assertAlmostEqual(sum(eotm["weightsUsed"].values()), 100, places=0)
        self.assertEqual(self.call(self.owner, "POST", f"/api/recognition/{self.month}/announce", json={"person": "Priya Sharma"}).status_code, 200)
        self.assertEqual(self.call(self.owner, "GET", "/api/leaderboard").json()["employeeOfMonth"]["announced"]["person"], "Priya Sharma")
        self.assertEqual(self.call(self.owner, "PUT", "/api/recognition/weights", json={"weights": {"callQuality": 100}}).status_code, 422)

    @slide(34, "The owner's month shows commission once rates exist")
    def test_owner_dashboard_commission(self):
        self.assertFalse(self.call(self.owner, "GET", "/api/dashboard/owner").json()["commissionAvailable"])
        self.rates()
        self.sell(self.priya, "Priya Sharma", "Dash Sale", 12000)
        board = self.call(self.owner, "GET", "/api/dashboard/owner").json()
        self.assertTrue(board["commissionAvailable"])
        self.assertEqual(board["bands"]["month"]["commission"], 2160.0)
        self.assertFalse(self.call(self.manager, "GET", "/api/dashboard/owner").json()["commissionAvailable"])


# ─── Slides 31–32: sales funnel and lead-source analytics ───────────────────
class Reports(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")

    def lead(self, first, source, **extra):
        return self.call(self.owner, "POST", "/api/leads", json={"firstName": first, "mobile": f"+91 9{abs(hash(first)) % 10**9:09d}",
                                                                 "assignedTo": "Priya Sharma", "product": "Car Insurance",
                                                                 "leadSource": source, **extra}).json()

    def outcome(self, lead, outcome, **extra):
        res = self.call(self.priya, "POST", "/api/calls", json={"leadId": lead["id"], "outcome": outcome, "durationSeconds": 60, **extra})
        self.assertEqual(res.status_code, 200, res.text)

    def build(self):
        a, b, c, d = (self.lead("Meta One", "Meta Ads"), self.lead("Meta Two", "Meta Ads"),
                      self.lead("Referral One", "Referral"), self.lead("Referral Two", "Referral"))
        self.outcome(a, "Interested")
        self.call(self.owner, "PUT", f"/api/leads/{a['id']}/stage", json={"status": "Quote Sent", "nextAction": "Chase", "nextActionDate": "2026-12-01"})
        self.outcome(b, "Busy / Switched Off")
        self.outcome(c, "Policy Sold", policy={"insurer": "Acko", "premium": 15000, "expiryDate": "2027-09-30"})
        self.outcome(d, "Not Interested", reason="Premium too high")

    @slide(31, "The funnel counts how far each lead got — a sale also counts as contacted, interested and quoted")
    def test_funnel(self):
        self.build()
        report = self.call(self.owner, "GET", "/api/reports").json()
        self.assertEqual(report["cohortSize"], 4)
        stages = {s["stage"]: s for s in report["funnel"]}
        self.assertEqual([stages[n]["count"] for n in ("New", "Contacted", "Interested", "Quote Sent", "Policy Sold")], [4, 3, 2, 2, 1])
        self.assertEqual((stages["Contacted"]["ofStart"], stages["Policy Sold"]["ofStart"]), (75.0, 25.0))
        self.assertEqual(report["lostReasons"], [{"reason": "Premium too high", "count": 1}])

    @slide(32, "Each source shows contact, interest, quote and conversion rates and the premium it brought")
    def test_sources(self):
        self.build()
        rows = {r["source"]: r for r in self.call(self.owner, "GET", "/api/reports").json()["sources"]}
        meta, referral = rows["Meta Ads"], rows["Referral"]
        self.assertEqual((meta["leads"], meta["contactRate"], meta["quoteRate"], meta["conversionRate"], meta["premium"]), (2, 50.0, 50.0, 0.0, 0))
        self.assertEqual((referral["conversionRate"], referral["premium"], referral["premiumPerLead"]), (50.0, 15000.0, 7500.0))

    @slide(31, "The funnel filters by telecaller, product, source and dates")
    def test_filters(self):
        self.build()
        only_meta = self.call(self.owner, "GET", "/api/reports", params={"source": "Meta Ads"}).json()
        self.assertEqual(only_meta["cohortSize"], 2)
        health = self.call(self.owner, "GET", "/api/reports", params={"product": "Health Insurance"}).json()
        self.assertEqual(health["cohortSize"], 0)
        future = self.call(self.owner, "GET", "/api/reports", params={"start": "2030-01-01", "end": "2030-01-31"}).json()
        self.assertEqual(future["cohortSize"], 0)
        self.assertEqual(self.call(self.owner, "GET", "/api/reports", params={"start": "2026-10-01", "end": "2026-09-01"}).status_code, 422)

    @slide(10, "Reports are for the owner and managers")
    def test_reports_access(self):
        self.assertEqual(self.call(self.priya, "GET", "/api/reports").status_code, 403)


# ─── Slide 20: quotation management ─────────────────────────────────────────
class Quotations(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Quote Me", "mobile": "+91 90003 00001",
            "product": "Car Insurance", "assignedTo": "Priya Sharma"}).json()

    def quote(self, client=None, **extra):
        res = self.call(client or self.priya, "POST", "/api/quotations", json={"leadId": self.lead["id"], "insurer": "Acko",
                                                                              "premium": 12500, **extra})
        return res

    def move(self, quote, status, **extra):
        return self.call(self.priya, "PUT", f"/api/quotations/{quote['id']}", json={"status": status, **extra})

    def lead_now(self):
        return self.call(self.owner, "GET", f"/api/leads/{self.lead['id']}").json()["lead"]

    @slide(20, "A telecaller can quote their own lead; it carries the product and their name")
    def test_quote_a_lead(self):
        q = self.quote().json()
        self.assertEqual((q["status"], q["product"], q["assignedTo"]), ("Draft", "Car Insurance", "Priya Sharma"))
        rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.assertEqual(self.quote(rohit).status_code, 404)
        self.assertEqual(self.quote(premium=-5).status_code, 422)

    @slide(20, "Quotes follow Draft → Sent → Viewed → Negotiation → Accepted or Rejected")
    def test_lifecycle(self):
        q = self.quote().json()
        self.assertEqual(self.move(q, "Accepted").status_code, 422)                   # a draft isn't accepted unseen
        sent = self.move(q, "Sent").json()
        self.assertTrue(sent["sentAt"])
        for status in ("Viewed", "Negotiation"):
            self.assertEqual(self.move(q, status).status_code, 200)
        self.assertEqual(self.move(q, "Accepted", customerResponse="Happy with zero-dep cover").status_code, 200)
        self.assertEqual(self.call(self.priya, "PUT", f"/api/quotations/{q['id']}", json={"premium": 1}).status_code, 409)
        history = [h["status"] for h in self.call(self.priya, "GET", "/api/quotations", params={"leadId": self.lead["id"]}).json()[0]["statusHistory"]]
        self.assertEqual(history, ["Draft", "Sent", "Viewed", "Negotiation", "Accepted"])

    @slide(20, "Sending a quote moves the lead to Quote Sent with a follow-up; acceptance moves it to documents")
    def test_lead_follows_quote(self):
        q = self.quote(followUpDate="2026-12-05").json()
        self.move(q, "Sent")
        lead = self.lead_now()
        self.assertEqual((lead["status"], lead["nextActionDate"]), ("Quote Sent", "2026-12-05"))
        self.move(q, "Accepted")
        lead = self.lead_now()
        self.assertEqual(lead["status"], "Documents Pending")
        self.assertTrue(lead["nextAction"].startswith("Collect documents"))

    @slide(20, "A quote past its validity date expires")
    def test_expiry(self):
        q = self.quote(status="Sent", validityDate="2020-01-01").json()
        listed = self.call(self.priya, "GET", "/api/quotations", params={"leadId": self.lead["id"]}).json()
        self.assertEqual(listed[0]["status"], "Expired")
        self.assertEqual(self.move(q, "Sent", validityDate="2030-01-01").status_code, 200)   # a revised quote can go again


# ─── Slides 23–24: renewal reminders and the renewal dashboard ──────────────
class Renewals(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")

    def policy(self, name, days, owner="Priya Sharma", premium=10000):
        expiry = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
        with self.company_db() as db:
            db.setdefault("policies", []).append({
                "id": f"POL_{name.replace(' ', '')}", "customerName": name, "policyNumber": f"P-{name[:3].upper()}",
                "policyType": "Car Insurance", "insurer": "Acko", "status": "Active", "issuanceStatus": "Issued",
                "expiryDate": expiry, "netPremium": premium, "assignedTo": owner})
        return expiry

    def run_jobs(self):
        res = self.call(self.owner, "POST", "/api/admin/jobs/run")
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()

    def ladder_alerts(self, client=None):
        return [n for n in self.call(client or self.owner, "GET", "/api/notifications").json() if n.get("type") == "Renewal Reminder"]

    @slide(23, "A renewal opens by itself 60 days before expiry, owned by the policy's telecaller")
    def test_opens_itself(self):
        self.policy("Due Soon", 45)
        self.policy("Far Off", 200)
        self.run_jobs()
        renewals = self.call(self.owner, "GET", "/api/renewals").json()
        self.assertEqual([(r["customerName"], r["assignedTo"]) for r in renewals], [("Due Soon", "Priya Sharma")])
        self.run_jobs()                                                                # never a second one
        self.assertEqual(len(self.call(self.owner, "GET", "/api/renewals").json()), 1)

    @slide(23, "Reminders follow the 60/30/15/7-day ladder, once per stage, and escalate when a policy expires")
    def test_ladder(self):
        self.policy("Thirty", 25)
        self.run_jobs(); self.run_jobs()
        alerts = self.ladder_alerts()
        self.assertEqual([a["title"] for a in alerts], ["Renewal — 30 days"])          # starts where it is, once
        self.assertEqual(alerts[0]["assignedTo"], "Priya Sharma")
        with self.company_db() as db:                                                  # time passes: the policy lapses
            db["renewals"][0]["expiryDate"] = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        self.run_jobs()
        titles = [a["title"] for a in self.ladder_alerts()]
        self.assertIn("Policy expired without renewal", titles)
        listed = self.call(self.owner, "GET", "/api/renewals").json()[0]
        self.assertEqual(listed["ladderStage"], "Expired — not renewed")

    @slide(24, "The renewal dashboard counts due, renewed and lost, and the rate is renewed ÷ due")
    def test_dashboard(self):
        month = datetime.now().strftime("%Y-%m")
        with self.company_db() as db:
            for i, (stage, owner) in enumerate([("Renewed", "Priya Sharma"), ("Lost", "Priya Sharma"),
                                                ("Due Soon", "Rohit Verma"), ("Renewed", "Rohit Verma")]):
                db.setdefault("renewals", []).append({"id": f"REN_T{i}", "policyId": f"POL_T{i}", "customerName": f"C{i}",
                    "expiryDate": f"{month}-15", "assignedTo": owner, "stage": stage, "targetPremium": 5000})
        d = self.call(self.owner, "GET", "/api/renewals/dashboard").json()
        self.assertEqual((d["dueThisMonth"], d["renewed"], d["lost"], d["pending"], d["renewalRate"]), (4, 2, 1, 1, 50.0))
        self.assertEqual({r["person"]: (r["renewed"], r["pending"]) for r in d["byEmployee"]},
                         {"Priya Sharma": (1, 0), "Rohit Verma": (1, 1)})
        mine = self.call(self.priya, "GET", "/api/renewals/dashboard").json()          # a telecaller sees their own book
        self.assertEqual((mine["dueThisMonth"], mine["renewalRate"]), (2, 50.0))
        self.assertEqual(self.call(self.owner, "GET", "/api/renewals/dashboard", params={"month": "2026-13"}).status_code, 422)


# ─── Slide 12: automatic lead assignment methods ─────────────────────────────
class AssignmentMethods(ClientBlueprintCase):

    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.n = 0

    def route(self, method):
        res = self.call(self.owner, "POST", "/api/automations", json={"name": f"Route {method}", "enabled": True,
            "trigger": {"type": "lead.created"},
            "actions": [{"type": "assign", "params": {"assignees": ["Priya Sharma", "Rohit Verma"], "method": method}}]})
        self.assertEqual(res.status_code, 200, res.text)

    def new_lead(self, owner=None, **extra):
        self.n += 1
        body = {"firstName": f"Lead{self.n}", "mobile": f"+91 90002 {self.n:05d}", **extra}
        if owner:
            body["assignedTo"] = owner
        res = self.call(self.owner, "POST", "/api/leads", json=body)
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["assignedTo"]

    @slide(12, "Someone marked away receives no new leads until they are back")
    def test_availability(self):
        self.route("rotate")
        self.assertEqual(self.call(self.priya, "PUT", "/api/availability", json={"available": False, "note": "On leave"}).status_code, 200)
        self.assertEqual([self.new_lead() for _ in range(3)], ["Rohit Verma"] * 3)
        rohit_id = next(u["id"] for u in self.call(self.owner, "GET", "/api/users").json() if u["name"] == "Rohit Verma")
        self.assertEqual(self.call(self.priya, "PUT", "/api/availability", json={"available": False, "userId": rohit_id}).status_code, 403)
        board = self.call(self.owner, "GET", "/api/dashboard/owner").json()
        self.assertEqual([p["person"] for p in board["control"]["away"]], ["Priya Sharma"])
        self.call(self.priya, "PUT", "/api/availability", json={"available": True})
        self.assertEqual(sorted(self.new_lead() for _ in range(2)), ["Priya Sharma", "Rohit Verma"])

    @slide(12, "Equal distribution evens out the month's leads, whatever is still open")
    def test_equal(self):
        self.new_lead("Priya Sharma"); self.new_lead("Priya Sharma")
        self.route("equal")
        self.assertEqual([self.new_lead() for _ in range(3)], ["Rohit Verma", "Rohit Verma", "Priya Sharma"])

    @slide(12, "Performance-based sharing sends more leads to the better converter, but never all of them")
    def test_performance(self):
        for _ in range(5):
            self.new_lead("Priya Sharma"); self.new_lead("Rohit Verma")
        today = datetime.now().strftime("%Y-%m-%d")
        with self.company_db() as db:
            for i, who in enumerate(["Priya Sharma"] * 3 + ["Rohit Verma"]):             # 60% against 20%
                db.setdefault("policies", []).append({"id": f"POL_S{i}", "customerName": f"S{i}", "status": "Active",
                    "policyType": "Car Insurance", "saleDate": today, "netPremium": 9000, "assignedTo": who})
        self.route("performance")
        owners = [self.new_lead() for _ in range(10)]
        self.assertGreater(owners.count("Priya Sharma"), owners.count("Rohit Verma"))
        self.assertGreater(owners.count("Rohit Verma"), 0)

    @slide(12, "Priority-based: a HOT lead goes to the best converter, others to whoever is least busy")
    def test_priority(self):
        self.new_lead("Priya Sharma"); self.new_lead("Priya Sharma")
        today = datetime.now().strftime("%Y-%m-%d")
        with self.company_db() as db:
            db.setdefault("policies", []).append({"id": "POL_P1", "customerName": "P", "status": "Active",
                "policyType": "Car Insurance", "saleDate": today, "netPremium": 9000, "assignedTo": "Priya Sharma"})
        self.route("priority")
        self.assertEqual(self.new_lead(leadPriority="HOT"), "Priya Sharma")
        self.assertEqual(self.new_lead(leadPriority="COLD"), "Rohit Verma")


# ─── Slide 18: Customer 360° profile ─────────────────────────────────────────
class Customer360(ClientBlueprintCase):

    @slide(18, "One customer, one history: calls, quotes, earlier insurance and follow-ups from every lead they came through")
    def test_complete_history(self):
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        priya = self.sign_in("priya.sharma@blueprint.invalid")
        lead = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Asha", "lastName": "Nair", "mobile": "+91 90004 00001",
            "product": "Car Insurance", "assignedTo": "Priya Sharma", "city": "Kochi",
            "existingPolicy": {"insurer": "Tata AIG", "policyNumber": "OLD-1", "expiryDate": "2026-12-31"}}).json()
        started = self.call(priya, "POST", "/api/calls/start", json={"leadId": lead["id"]})
        self.assertEqual(started.status_code, 200, started.text)
        done = self.call(priya, "POST", f"/api/calls/{started.json()['call']['id']}/complete",
                         json={"outcome": "Interested", "notes": "Wants zero-dep", "durationSeconds": 95})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(self.call(priya, "POST", "/api/quotations", json={"leadId": lead["id"], "insurer": "Acko", "premium": 11000}).status_code, 200)
        converted = self.call(priya, "POST", f"/api/leads/{lead['id']}/convert", json={"insurer": "Acko", "premium": 11000,
                                                                                       "startDate": "2027-01-01", "expiryDate": "2027-12-31"})
        self.assertEqual(converted.status_code, 200, converted.text)
        cid = converted.json()["customer"]["id"]
        c = self.call(priya, "GET", f"/api/customers/{cid}").json()
        self.assertEqual(c["city"], "Kochi")
        self.assertEqual([x["outcome"] for x in c["calls"]], ["Interested"])
        self.assertEqual([q["insurer"] for q in c["quotations"]], ["Acko"])
        self.assertEqual([(h["source"], h["insurer"]) for h in c["insuranceHistory"]], [("Before us", "Tata AIG")])
        self.assertEqual(len(c["policies"]), 1)
        self.assertIn("upcoming", c["followUps"])
        self.assertEqual(self.call(priya, "PUT", f"/api/customers/{cid}", json={"preferences": "Malayalam, after 6pm"}).json()["preferences"],
                         "Malayalam, after 6pm")
        rohit = self.sign_in("rohit.verma@blueprint.invalid")
        self.assertEqual(self.call(rohit, "GET", f"/api/customers/{cid}").status_code, 404)


# ─── Slide 33: Employee Target Achieved ─────────────────────────────────────
class TargetAchieved(ClientBlueprintCase):

    @slide(33, "Reaching the monthly target notifies the telecaller once; the automation row says it is built in")
    def test_target_achieved(self):
        self.add_staff("Priya Sharma", "telecaller")
        today = datetime.now(ZoneInfo("Asia/Kolkata"))
        month = today.strftime("%Y-%m")
        self.assertEqual(self.call(self.owner, "PUT", "/api/targets", json={"month": month, "person": "Priya Sharma",
                                                                           "policiesSold": 1}).status_code, 200)
        run = lambda: self.call(self.owner, "POST", "/api/admin/jobs/run")
        alerts = lambda: [n for n in self.call(self.owner, "GET", "/api/notifications").json() if n.get("type") == "Target Achieved"]
        run()
        self.assertEqual(alerts(), [])                                                   # not there yet
        with self.company_db() as db:
            db.setdefault("policies", []).append({"id": "POL_T1", "customerName": "T", "status": "Active",
                "policyType": "Car Insurance", "saleDate": today.strftime("%Y-%m-%d"), "netPremium": 9000, "assignedTo": "Priya Sharma"})
        run(); run()
        self.assertEqual([(a["assignedTo"], a["title"]) for a in alerts()], [("Priya Sharma", "Target achieved — Priya Sharma")])
        recipes = {r["key"]: r for r in self.call(self.owner, "GET", "/api/automations").json()["recipes"]}
        self.assertIn("builtIn", recipes["target-incentive"])
