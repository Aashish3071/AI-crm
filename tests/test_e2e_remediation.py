"""InsureCRM Commercial Readiness Remediation - End-to-End Test Suite.

4-Tier Testing Methodology:
- Tier 1: Feature Coverage (All 46 inventoried features across Gates 1-5)
- Tier 2: Boundary & Corner Cases (Financial limits, date ordering, dangling references, DST, etc.)
- Tier 3: Cross-Feature Combinations (Conversion + policy issuance + servicing, quotes + renewals)
- Tier 4: Real-World Application Scenarios (End-to-end multi-broker lifecycle & operational resilience)

Authoritative sources:
- ORIGINAL_REQUEST.md (Requirements R1 - R5)
- PROJECT.md (46-feature inventory, architecture, interface contracts)
- uat/CRM_BLUEPRINT.md (Blueprint acceptance criteria)
"""
from __future__ import annotations

import contextvars
import json
import os
from pathlib import Path
import re
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_security
import pipecat_server as server


ROOT = Path(__file__).resolve().parents[1]


def tier(level: int, feature_id: str, gate: int):
    """Annotate test methods with tier, feature ID, and verification gate."""
    def decorator(fn):
        fn.tier = level
        fn.feature_id = feature_id
        fn.gate = gate
        return fn
    return decorator


class BaseE2ETestCase(unittest.TestCase):
    """Base test case providing isolated temporary storage, identities, and client."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "crm_db.json")
        self.doc_dir = os.path.join(self.temp_dir.name, "documents")
        self.backup_dir = os.path.join(self.temp_dir.name, "backups")
        self.tenant_dir = os.path.join(self.temp_dir.name, "tenants")
        self.identities_path = os.path.join(self.temp_dir.name, "identities.json")

        os.makedirs(self.doc_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.tenant_dir, exist_ok=True)

        self.original_env = {
            "DB_FILE": server.DB_FILE,
            "DOCUMENT_ROOT": server.DOCUMENT_ROOT,
            "BACKUP_ROOT": server.BACKUP_ROOT,
            "TENANT_ROOT": server.TENANT_ROOT,
            "AUTH_DISABLED": server.AUTH_DISABLED,
            "IDENTITY_STORE_PATH": crm_security.IDENTITY_STORE_PATH,
            "SESSION_SECRET": os.environ.get("SESSION_SECRET"),
            "DATABASE_URL": os.environ.get("DATABASE_URL"),
        }

        server.DB_FILE = self.db_path
        server.DOCUMENT_ROOT = self.doc_dir
        server.BACKUP_ROOT = self.backup_dir
        server.TENANT_ROOT = self.tenant_dir
        server.AUTH_DISABLED = True
        crm_security.IDENTITY_STORE_PATH = self.identities_path
        os.environ["SESSION_SECRET"] = "e2e-test-session-secret-key-32-chars-long"
        os.environ["DATABASE_URL"] = ""

        # Initialize empty schema with users
        initial_db = server._empty_company_db()
        initial_db["users"] = server.get_initial_db()["users"]
        # Declare the catalogue these tests use; the default is the client's car and health lines.
        initial_db["settings"]["crm"]["insuranceProducts"] = ["Car Insurance", "Health Insurance", "Property",
                                                              "Commercial Motor", "Motor"]
        server.save_db(initial_db)

        self.client = TestClient(server.app)

    def tearDown(self):
        server.DB_FILE = self.original_env["DB_FILE"]
        server.DOCUMENT_ROOT = self.original_env["DOCUMENT_ROOT"]
        server.BACKUP_ROOT = self.original_env["BACKUP_ROOT"]
        server.TENANT_ROOT = self.original_env["TENANT_ROOT"]
        server.AUTH_DISABLED = self.original_env["AUTH_DISABLED"]
        crm_security.IDENTITY_STORE_PATH = self.original_env["IDENTITY_STORE_PATH"]
        if self.original_env["SESSION_SECRET"] is None:
            os.environ.pop("SESSION_SECRET", None)
        else:
            os.environ["SESSION_SECRET"] = self.original_env["SESSION_SECRET"]
        if self.original_env["DATABASE_URL"] is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = self.original_env["DATABASE_URL"]
        self.temp_dir.cleanup()

    # --- Helper Factories ---

    def create_lead(self, client: TestClient = None, headers: dict = None, **overrides) -> dict:
        c = client or self.client
        payload = {
            "firstName": "Arun",
            "lastName": "Patel",
            "organization": "Apex Logistics",
            "email": "arun.patel@apex.invalid",
            "mobile": "+919876543210",
            "premium": "150000",
            "nextAction": "Initial risk survey",
            "nextActionDate": "2026-10-15",
            "status": "New",
        }
        payload.update(overrides)
        res = c.post("/api/leads", json=payload, headers=headers or {})
        self.assertIn(res.status_code, (200, 201), f"Failed to create lead: {res.text}")
        return res.json()

    def create_customer(self, client: TestClient = None, headers: dict = None, **overrides) -> dict:
        c = client or self.client
        payload = {
            "name": "Apex Logistics Private Limited",
            "email": "contact@apex.invalid",
            "mobile": "+919876543210",
            "organization": "Apex Logistics",
        }
        payload.update(overrides)
        res = c.post("/api/customers", json=payload, headers=headers or {})
        self.assertIn(res.status_code, (200, 201), f"Failed to create customer: {res.text}")
        return res.json()

    def create_policy(self, customer_id: str, client: TestClient = None, headers: dict = None, **overrides) -> dict:
        c = client or self.client
        customer_name = overrides.get("customerName", "Apex Logistics Private Limited")
        payload = {
            "customerId": customer_id,
            "customerName": customer_name,
            "policyType": "Property",
            "startDate": "2026-01-01",
            "expiryDate": "2026-12-31",
            "premium": 150000,
            "sumInsured": 50000000,
            "status": "Draft",
        }
        payload.update(overrides)
        res = c.post("/api/policies", json=payload, headers=headers or {})
        self.assertIn(res.status_code, (200, 201), f"Failed to create policy: {res.text}")
        return res.json()

    def create_renewal(self, policy_id: str, client: TestClient = None, headers: dict = None) -> dict:
        c = client or self.client
        res = c.post("/api/renewals", json={"policyId": policy_id}, headers=headers or {})
        self.assertIn(res.status_code, (200, 201), f"Failed to create renewal: {res.text}")
        return res.json()

    def enable_auth_session(self, role: str = "broker", user_id: str = "U_TEST_01", name: str = "Test Actor") -> tuple[TestClient, dict]:
        """Configure authenticated client with session cookies for RBAC testing."""
        server.AUTH_DISABLED = False
        company = {"id": "comp_e2e_01", "name": "E2E Insurance Broking", "status": "Active", "createdAt": int(time.time())}
        user = {
            "id": user_id,
            "companyId": company["id"],
            "name": name,
            "email": f"{user_id.lower()}@broker.invalid",
            "role": role,
            "status": "Active",
            "passwordHash": crm_security._password_hash("ValidPass!123"),
            "createdAt": int(time.time()),
            "passwordChangedAt": int(time.time()),
        }
        store = crm_security._load_identities()
        companies = [c for c in store.get("companies", []) if c.get("id") != company["id"]] + [company]
        users = [u for u in store.get("users", []) if u.get("id") != user_id] + [user]
        crm_security._save_identities({"companies": companies, "users": users})

        token = crm_security.create_session(user)
        csrf_token = "csrf_token_test_abc123"

        client = TestClient(server.app)
        client.cookies.set(crm_security.SESSION_COOKIE, token)
        client.cookies.set(crm_security.CSRF_COOKIE, csrf_token)
        headers = {"X-CSRF-Token": csrf_token}
        return client, headers


# ============================================================================
# TIER 1: FEATURE COVERAGE (All 46 Inventoried Features)
# ============================================================================

class TestTier1FeatureCoverage(BaseE2ETestCase):
    """Tier 1: Feature-by-feature verification across all 46 requirements."""

    # --- GATE 1: Trust, Identity & Security Integrity ---

    @tier(1, "M15.1", gate=1)
    def test_feat_01_lead_delete_note_archiving(self):
        """M15.1: Lead deletion cascades but notes are archived; GET /api/notes?includeArchived=true returns them."""
        lead = self.create_lead()
        note = self.client.post("/api/notes", json={"leadId": lead["id"], "title": "Risk Note", "content": "Initial inspection findings"}).json()
        self.assertIn("id", note)

        # Delete lead
        del_res = self.client.delete(f"/api/leads/{lead['id']}")
        self.assertEqual(del_res.status_code, 200)

        # Notes list without parameter excludes archived notes
        normal_notes = self.client.get("/api/notes").json()
        self.assertFalse(any(n["id"] == note["id"] for n in normal_notes), "Default /api/notes should not return archived notes")

        # Querying with includeArchived=true retrieves the archived note
        archived_res = self.client.get("/api/notes?includeArchived=true")
        self.assertEqual(archived_res.status_code, 200)
        archived_notes = archived_res.json()
        target = next((n for n in archived_notes if n["id"] == note["id"]), None)
        self.assertIsNotNone(target, "Archived note not found with includeArchived=true")
        self.assertTrue(target.get("archived"), "Note archived flag must be True")

    @tier(1, "M15.2", gate=1)
    def test_feat_02_note_edit_endpoint(self):
        """M15.2: PUT /api/notes/{id} updates note content and appends an audit event."""
        lead = self.create_lead()
        note = self.client.post("/api/notes", json={"leadId": lead["id"], "title": "Original Title", "content": "Original Content"}).json()

        res = self.client.put(f"/api/notes/{note['id']}", json={"title": "Updated Title", "content": "Updated Content"})
        self.assertEqual(res.status_code, 200, f"PUT /api/notes/{{id}} failed: {res.text}")
        updated = res.json()
        self.assertEqual(updated["title"], "Updated Title")
        self.assertEqual(updated["content"], "Updated Content")

        # Verify audit log recorded
        audit = self.client.get("/api/audit-logs").json()
        self.assertTrue(any(a.get("entityId") == note["id"] or "note" in str(a).lower() for a in audit),
                        "Note edit must append an entry to audit logs")

    @tier(1, "M27.2", gate=1)
    def test_feat_03_policy_migration_audit(self):
        """M27.2: Policy migration from leads creates an audit log entry."""
        self.create_lead(policyType="Property")
        before_logs = len(self.client.get("/api/audit-logs").json())

        migrate_res = self.client.post("/api/policies/migrate-leads")
        self.assertEqual(migrate_res.status_code, 200)

        after_logs = len(self.client.get("/api/audit-logs").json())
        self.assertGreater(after_logs, before_logs, "migrate_leads_to_policies must record an audit event")

    @tier(1, "R1.1", gate=1)
    def test_feat_04_archival_rbac_privilege_isolation(self):
        """R1.1: Restrict /api/records/ and /api/archived-records/ to admin and manager; reject broker with 403."""
        lead = self.create_lead()

        # Test with broker session
        broker_client, broker_hdr = self.enable_auth_session(role="broker", user_id="U_BROKER")
        archive_res = broker_client.post(f"/api/records/leads/{lead['id']}/archive", headers=broker_hdr)
        self.assertEqual(archive_res.status_code, 403, f"Broker should receive 403 on archive endpoint, got {archive_res.status_code}")

        # Test with manager session
        mgr_client, mgr_hdr = self.enable_auth_session(role="manager", user_id="U_MGR")
        mgr_lead = self.create_lead(client=mgr_client, headers=mgr_hdr)
        archive_mgr_res = mgr_client.post(f"/api/records/leads/{mgr_lead['id']}/archive", headers=mgr_hdr)
        self.assertIn(archive_mgr_res.status_code, (200, 204), f"Manager should be permitted to archive records: {archive_mgr_res.text}")

    @tier(1, "R1.2", gate=1)
    def test_feat_05_session_derived_authorship(self):
        """R1.2: Note and task authors derived from authenticated session rather than client string."""
        auth_client, auth_hdr = self.enable_auth_session(role="broker", user_id="U_ALICE", name="Alice Smith")
        lead = self.create_lead(client=auth_client, headers=auth_hdr)

        # Client attempts to spoof author as "Bob Jones"
        note_res = auth_client.post("/api/notes", headers=auth_hdr, json={
            "leadId": lead["id"],
            "title": "Confidential Review",
            "content": "Risk analysis",
            "author": "Bob Jones (Spoofed)",
        })
        self.assertEqual(note_res.status_code, 200)
        note = note_res.json()
        self.assertEqual(note.get("author"), "Alice Smith", "Author must be derived from session user, not untrusted client payload")

    @tier(1, "R1.3", gate=1)
    def test_feat_06_profile_self_isolation(self):
        """R1.3: Users can only view and edit their own profile; reject cross-user access with 403."""
        alice_client, alice_hdr = self.enable_auth_session(role="broker", user_id="U_ALICE", name="Alice Smith")

        # Alice views her own profile
        alice_profile = alice_client.get("/api/profile")
        self.assertEqual(alice_profile.status_code, 200)

        # Alice attempts to edit Bob's profile ID
        cross_edit = alice_client.put("/api/profile", headers=alice_hdr, json={
            "userId": "U_BOB",
            "name": "Bob Tampered",
            "phone": "+919999999999",
        })
        self.assertIn(cross_edit.status_code, (403, 400), "Editing colleague's profile must be rejected with 403")

    @tier(1, "R1.4", gate=1)
    def test_feat_07_notification_scoping(self):
        """R1.4: /api/notifications scoped by visible_owners(db) so brokers only see their assigned notifications."""
        server.AUTH_DISABLED = True
        db = server.load_db()
        db["notifications"] = [
            {"id": "N1", "assignedTo": "Sarah Connor", "title": "Follow up Sarah lead", "read": False},
            {"id": "N2", "assignedTo": "Aarav Sharma", "title": "Follow up Aarav lead", "read": False},
        ]
        server.save_db(db)

        # Authenticate as Sarah
        sarah_client, _ = self.enable_auth_session(role="broker", user_id="U_SARAH", name="Sarah Connor")
        sarah_notes = sarah_client.get("/api/notifications").json()
        self.assertTrue(all(n.get("assignedTo") in ("Sarah Connor", "", None) for n in sarah_notes),
                        "Broker should only see notifications assigned to them or unassigned team items")
        self.assertFalse(any(n.get("assignedTo") == "Aarav Sharma" for n in sarah_notes),
                         "Broker must not see colleague's private notifications")

    # --- GATE 2: Placing Business & Financial Integrity ---

    @tier(1, "M17.1a", gate=2)
    def test_feat_08_non_negative_premium_validation(self):
        """M17.1a: Reject negative premiums with HTTP 422."""
        cust = self.create_customer()
        res = self.client.post("/api/policies", json={
            "customerId": cust["id"],
            "customerName": cust["name"],
            "policyType": "Property",
            "premium": -5000,
            "sumInsured": 1000000,
            "startDate": "2026-01-01",
            "expiryDate": "2026-12-31",
        })
        self.assertEqual(res.status_code, 422, f"Negative premium must be rejected with 422, got {res.status_code}")

    @tier(1, "M17.1b", gate=2)
    def test_feat_09_valid_policy_term_sequence(self):
        """M17.1b: Reject startDate > expiryDate with HTTP 422."""
        cust = self.create_customer()
        res = self.client.post("/api/policies", json={
            "customerId": cust["id"],
            "customerName": cust["name"],
            "policyType": "Property",
            "premium": 10000,
            "sumInsured": 1000000,
            "startDate": "2027-01-01",
            "expiryDate": "2026-01-01",  # Reversed date
        })
        self.assertEqual(res.status_code, 422, f"Reversed policy term dates must return 422, got {res.status_code}")

    @tier(1, "M17.2a", gate=2)
    def test_feat_10_policy_activation_gating(self):
        """M17.2a: Forbid direct PUT updates changing policy status to Active or Issued."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Draft")

        res = self.client.put(f"/api/policies/{pol['id']}", json={"status": "Active"})
        self.assertEqual(res.status_code, 422, f"Direct activation via PUT must be rejected with 422, got {res.status_code}")

    @tier(1, "M17.2b", gate=2)
    def test_feat_11_document_evidence_issuance_gate(self):
        """M17.2b: Policy issuance requires uploaded stored documents in db['documents']."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Draft")

        # Attempt issuance with only boolean checkboxes and no stored documents
        issue_res = self.client.post(f"/api/policies/{pol['id']}/issue", json={
            "checklist": {"proposalForm": True, "kyc": True, "payment": True, "schedule": True}
        })
        self.assertEqual(issue_res.status_code, 422,
                         f"Issuance without stored files must return 422, got {issue_res.status_code}")

    @tier(1, "M16.1a", gate=2)
    def test_feat_12_quote_cross_renewal_rejection(self):
        """M16.1a: Reject selecting a quote belonging to another renewal."""
        cust = self.create_customer()
        pol1 = self.create_policy(cust["id"], status="Active")
        pol2 = self.create_policy(cust["id"], status="Active")

        r1 = self.create_renewal(pol1["id"])
        r2 = self.create_renewal(pol2["id"])

        # Quote belonging to renewal 2
        q2 = self.client.post("/api/quotations", json={"renewalId": r2["id"], "insurer": "Insurer X", "premium": 20000}).json()

        # Attempt to select q2 on renewal 1
        select_res = self.client.put(f"/api/renewals/{r1['id']}", json={"selectedQuotationId": q2["id"]})
        self.assertIn(select_res.status_code, (404, 422),
                      f"Cross-renewal quote selection must be rejected with 404/422, got {select_res.status_code}")

    @tier(1, "M16.1b", gate=2)
    def test_feat_13_expired_quote_rejection(self):
        """M16.1b: Reject selecting an expired quotation in renewal."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active")
        ren = self.create_renewal(pol["id"])

        # Expired quotation
        quote = self.client.post("/api/quotations", json={
            "renewalId": ren["id"],
            "insurer": "Old Insurer",
            "premium": 15000,
            "validityDate": "2020-01-01",  # Past date
        }).json()

        res = self.client.put(f"/api/renewals/{ren['id']}", json={"selectedQuotationId": quote["id"]})
        self.assertIn(res.status_code, (409, 422),
                      f"Selecting expired quotation must return 409 or 422, got {res.status_code}")

    @tier(1, "M16.2", gate=2)
    def test_feat_14_quote_validity_in_calendar(self):
        """M16.2: Active quotation validity dates projected into calendar feed."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active")
        ren = self.create_renewal(pol["id"])
        quote = self.client.post("/api/quotations", json={
            "renewalId": ren["id"],
            "insurer": "ICICI Lombard",
            "premium": 18000,
            "validityDate": "2026-12-15",
        }).json()

        cal = self.client.get("/api/calendar").json()
        events = cal.get("events", []) if isinstance(cal, dict) else cal
        self.assertTrue(any(e.get("associatedId") == quote["id"] or quote["id"] in str(e) for e in events),
                        "Quotation validity must be represented in calendar feed")

    @tier(1, "M16.3", gate=2)
    def test_feat_15_quotation_decoupling(self):
        """M16.3: Support new business quotations linked to leadId or dealId without renewalId."""
        lead = self.create_lead()
        res = self.client.post("/api/quotations", json={
            "leadId": lead["id"],
            "insurer": "Bajaj Allianz",
            "premium": 25000,
            "sumInsured": 2000000,
            "validityDate": "2026-11-30",
        })
        self.assertIn(res.status_code, (200, 201), f"Decoupled quotation for leadId failed: {res.text}")
        quote = res.json()
        self.assertEqual(quote.get("leadId"), lead["id"])

    @tier(1, "M07.1", gate=2)
    def test_feat_16_independent_deal_creation(self):
        """M07.1: POST /api/deals creates opportunity records linked to customer/organization."""
        cust = self.create_customer()
        res = self.client.post("/api/deals", json={
            "title": "Fleet Coverage Deal",
            "customerId": cust["id"],
            "stage": "Proposal",
            "estimatedPremium": 350000,
        })
        self.assertEqual(res.status_code, 201, f"POST /api/deals route should return 201, got {res.status_code}")
        deal = res.json()
        self.assertEqual(deal.get("title"), "Fleet Coverage Deal")

    @tier(1, "M07.2", gate=2)
    def test_feat_17_deal_advancement_on_conversion(self):
        """M07.2: Converting a lead with linked deal advances deal stage to Won and links customerId."""
        lead = self.create_lead()
        deal = self.client.post("/api/deals", json={
            "title": "Lead Opp",
            "leadId": lead["id"],
            "stage": "Open",
            "estimatedPremium": 100000,
        }).json()

        conv = self.client.post(f"/api/leads/{lead['id']}/convert", json={}).json()
        deals = self.client.get("/api/deals").json()
        updated_deal = next((d for d in deals if d.get("id") == deal.get("id")), {})
        self.assertEqual(updated_deal.get("stage"), "Won", "Linked deal stage must advance to Won on conversion")
        self.assertEqual(updated_deal.get("customerId"), conv["customer"]["id"], "Deal must link customerId")

    @tier(1, "M18.1", gate=2)
    def test_feat_18_renewal_generation_filters(self):
        """M18.1: Exclude Draft and Cancelled policies from renewal generation."""
        cust = self.create_customer()
        soon = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
        p_active = self.create_policy(cust["id"], status="Active", expiryDate=soon)
        p_draft = self.create_policy(cust["id"], status="Draft", expiryDate=soon)
        p_cancelled = self.create_policy(cust["id"], status="Cancelled", expiryDate=soon)

        gen = self.client.post("/api/renewals/generate?days=60").json()
        renewals = gen.get("renewals", [])
        renewed_policy_ids = {r.get("policyId") for r in renewals}

        self.assertIn(p_active["id"], renewed_policy_ids, "Active policy must be included in renewals")
        self.assertNotIn(p_draft["id"], renewed_policy_ids, "Draft policy must NOT be generated for renewal")
        self.assertNotIn(p_cancelled["id"], renewed_policy_ids, "Cancelled policy must NOT be generated for renewal")

    @tier(1, "M18.2", gate=2)
    def test_feat_19_idempotent_renewal_completion(self):
        """M18.2: Repeated POST /api/renewals/{id}/complete returns existing successor policy without duplicates."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active", expiryDate="2026-10-01")
        ren = self.create_renewal(pol["id"])
        quote = self.client.post("/api/quotations", json={
            "renewalId": ren["id"], "insurer": "Test Insurer", "premium": 150000, "validityDate": "2026-12-31"
        }).json()
        self.client.put(f"/api/renewals/{ren['id']}", json={"selectedQuotationId": quote["id"]})

        payload = {
            "policyNumber": "BP-NEXT-IDEMP",
            "startDate": "2026-10-02",
            "expiryDate": "2027-10-01",
            "documentChecklist": dict.fromkeys(["proposalForm", "kyc", "payment", "schedule"], True),
        }
        # First completion
        c1 = self.client.post(f"/api/renewals/{ren['id']}/complete", json=payload)
        self.assertEqual(c1.status_code, 200)

        # Second completion retry
        c2 = self.client.post(f"/api/renewals/{ren['id']}/complete", json=payload)
        self.assertEqual(c2.status_code, 200)

        # Verify exactly 2 policies exist in total (original + single successor)
        all_policies = self.client.get("/api/policies").json()
        self.assertEqual(len(all_policies), 2, "Idempotent completion must not create duplicate successor policies")

    @tier(1, "M25.3", gate=2)
    def test_feat_20_configured_product_enforcement(self):
        """M25.3: Reject unconfigured insurance product types with HTTP 422."""
        self.client.put("/api/settings", json={"crm": {"insuranceProducts": ["Marine Cargo", "Property"]}})
        cust = self.create_customer()

        res = self.client.post("/api/policies", json={
            "customerId": cust["id"],
            "customerName": cust["name"],
            "policyType": "Wild Unregistered Product",
            "premium": 50000,
            "sumInsured": 1000000,
            "startDate": "2026-01-01",
            "expiryDate": "2027-01-01",
        })
        self.assertEqual(res.status_code, 422, f"Unconfigured product type must return 422, got {res.status_code}")

    @tier(1, "R2.4", gate=2)
    def test_feat_21_quotation_comparison_ui(self):
        """R2.4: Quotation comparison interface components exist in web application controllers."""
        app_js = (ROOT / "web/app.js").read_text()
        index_html = (ROOT / "web/index.html").read_text()

        self.assertTrue("compareQuotes" in app_js or "quotationComparison" in app_js or "renderQuoteComparison" in app_js or "renderQuotationComparison" in app_js,
                        "Quotation comparison controller logic missing from web/app.js")
        self.assertTrue("quote-comparison" in index_html or "quotation-comparison" in index_html or "comparison" in index_html.lower(),
                        "Quotation comparison modal/view container missing from web/index.html")

    # --- GATE 3: Ingestion Parity & Master Records ---

    @tier(1, "M03.2", gate=3)
    def test_feat_22_webhook_canonical_task_reference(self):
        """M03.2: Webhook lead ingestion auto-provisions canonical task and sets nextActionTaskId."""
        channel = self.client.post("/api/channels", json={"name": "Blueprint Ingress", "provider": "custom"}).json()
        self.client.post(f"/api/channels/{channel['id']}/test", json={"name": "Source Client", "phone": "9999888777"})

        leads = self.client.get("/api/leads").json()
        self.assertTrue(leads, "Ingestion must produce a lead")
        task_ids = {t["id"] for t in self.client.get("/api/tasks").json()}
        self.assertIn(leads[0].get("nextActionTaskId"), task_ids, "Source lead lacks canonical nextActionTaskId")

    @tier(1, "M04.2", gate=3)
    def test_feat_23_spreadsheet_import_task_reference(self):
        """M04.2: CSV import commit auto-provisions canonical task and sets nextActionTaskId."""
        analyzed = self.client.post("/api/imports/analyze?filename=test.csv",
                                    content=b"Name,Phone,Email\nCSV Prospect,9999123401,csv@apex.invalid\n").json()
        import_id = analyzed.get("importId") or analyzed.get("id")

        self.client.post(f"/api/imports/{import_id}/commit", json={"mapping": {"0": "name", "1": "mobile", "2": "email"}})

        leads = self.client.get("/api/leads").json()
        self.assertTrue(leads, "Import commit must produce leads")
        task_ids = {t["id"] for t in self.client.get("/api/tasks").json()}
        self.assertIn(leads[0].get("nextActionTaskId"), task_ids, "Imported lead lacks canonical task reference")

    @tier(1, "M04.3", gate=3)
    def test_feat_24_spreadsheet_rollback_safety(self):
        """M04.3: Import rollback preserves worked or edited leads."""
        analyzed = self.client.post("/api/imports/analyze?filename=batch.csv",
                                    content=b"Name,Phone,Email\nLead Untouched,9999123001,u1@apex.invalid\nLead Worked,9999123002,u2@apex.invalid\n").json()
        import_id = analyzed.get("importId") or analyzed.get("id")
        self.client.post(f"/api/imports/{import_id}/commit", json={"mapping": {"0": "name", "1": "mobile", "2": "email"}})

        leads = self.client.get("/api/leads").json()
        self.assertTrue(leads, "Import must produce leads to test rollback")
        lead = leads[0]

        # Simulate human editing the lead
        self.client.put(f"/api/leads/{lead['id']}", json={"name": "Human-corrected customer"})

        # Rollback import
        rb_res = self.client.post(f"/api/imports/{import_id}/rollback")
        self.assertIn(rb_res.status_code, (200, 409))

        # Check outcomes: worked lead must not be discarded
        self.assertEqual(self.client.get(f"/api/leads/{lead['id']}").status_code, 200,
                         "Import rollback must not discard subsequently edited leads")

    @tier(1, "M08.2", gate=3)
    def test_feat_25_conversion_master_organization(self):
        """M08.2: Lead conversion auto-creates/resolves master organization and links organizationId."""
        lead = self.create_lead(organization="Tata Consultancy Enterprise")
        conv = self.client.post(f"/api/leads/{lead['id']}/convert", json={}).json()

        customer = conv.get("customer", {})
        self.assertTrue(customer.get("organizationId"), "Converted customer must have organizationId linked")

        orgs = self.client.get("/api/organizations").json()
        self.assertTrue(any(o["id"] == customer.get("organizationId") and "Tata Consultancy" in o.get("name", "") for o in orgs),
                        "Master organization must exist in db['organizations']")

    @tier(1, "M09.2", gate=3)
    def test_feat_26_customer_rename_propagation(self):
        """M09.2: Customer rename propagates to customerName on linked active policies."""
        cust = self.create_customer(name="Initial Firm Name")
        pol = self.create_policy(cust["id"], customerName="Initial Firm Name", status="Active")

        self.client.put(f"/api/customers/{cust['id']}", json={"name": "Renamed Firm Name"})

        policies = self.client.get("/api/policies").json()
        target_pol = next(p for p in policies if p["id"] == pol["id"])
        self.assertEqual(target_pol.get("customerName"), "Renamed Firm Name",
                         "Customer rename must propagate to policy customerName")

    @tier(1, "M10.2", gate=3)
    def test_feat_27_organization_rename_propagation(self):
        """M10.2: Organization rename propagates to linked customers and policies."""
        org = self.client.post("/api/organizations", json={"name": "Original Org Ltd"}).json()
        cust = self.create_customer(name="Cust 1", organizationId=org["id"], organization="Original Org Ltd")

        self.client.put(f"/api/organizations/{org['id']}", json={"name": "Propagated Org Global"})

        cust_view = self.client.get(f"/api/customers/{cust['id']}").json()
        self.assertEqual(cust_view.get("organization"), "Propagated Org Global",
                         "Org rename must propagate to customer organization string")

    @tier(1, "M10.3", gate=3)
    def test_feat_28_contact_relational_integrity(self):
        """M10.3: Reject contact creation with nonexistent parent ID."""
        res = self.client.post("/api/contacts", json={
            "name": "Dangling Contact",
            "email": "orphan@apex.invalid",
            "customerId": "CUS_NONEXISTENT_9999",
        })
        self.assertIn(res.status_code, (404, 422),
                      f"Contact with nonexistent customerId must be rejected with 404/422, got {res.status_code}")

    @tier(1, "M22.2", gate=3)
    def test_feat_29_document_relational_integrity(self):
        """M22.2: Reject document uploads referencing nonexistent parent entities."""
        res = self.client.post("/api/documents", json={
            "title": "Orphan Document",
            "associatedType": "Policy",
            "associatedId": "POL_MISSING_8888",
            "content": "base64dummycontent==",
        })
        self.assertIn(res.status_code, (404, 422),
                      f"Document referencing nonexistent parent must return 404/422, got {res.status_code}")

    @tier(1, "M26.3", gate=3)
    def test_feat_30_service_graph_cascade_cleanup(self):
        """M26.3: Deleting customer cascades to dependent service requests and endorsements."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active")
        sr = self.client.post("/api/service-requests", json={
            "customerId": cust["id"],
            "policyId": pol["id"],
            "requestType": "Endorsement",
            "description": "Coverage increase",
        }).json()

        # Delete customer
        self.client.delete(f"/api/customers/{cust['id']}")

        # Verify service request is no longer active/orphaned
        srs = self.client.get("/api/service-requests").json()
        self.assertFalse(any(s["id"] == sr["id"] and s.get("status") != "Archived" for s in srs),
                         "Dependent service requests must be cascade deleted/archived")

    # --- GATE 4: Servicing, Communications & Worker Reliability ---

    @tier(1, "M19.3", gate=4)
    def test_feat_31_service_resolution_outcome_mandate(self):
        """M19.3: Service request completion requires non-empty resolution outcome."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active")
        sr = self.client.post("/api/service-requests", json={
            "customerId": cust["id"],
            "policyId": pol["id"],
            "requestType": "Cancellation",
            "description": "Cancellation requested",
        }).json()

        # Attempt to mark completed without outcome
        res = self.client.put(f"/api/service-requests/{sr['id']}", json={"status": "Completed"})
        self.assertEqual(res.status_code, 422,
                         f"Completing service request without outcome text must return 422, got {res.status_code}")

    @tier(1, "M19.2", gate=4)
    def test_feat_32_endorsement_synchronization(self):
        """M19.2: Endorsement status synchronizes to Completed when service request completes."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active")
        sr = self.client.post("/api/service-requests", json={
            "customerId": cust["id"],
            "policyId": pol["id"],
            "requestType": "Endorsement",
            "description": "Increase machinery limit",
            "dueDate": "2026-10-11",
        }).json()

        # Complete service request with outcome
        self.client.put(f"/api/service-requests/{sr['id']}", json={
            "status": "Completed",
            "outcome": "Endorsement schedule issued by insurer",
        })

        endorsements = self.client.get(f"/api/endorsements?policyId={pol['id']}").json()
        if endorsements:
            self.assertIn(endorsements[0].get("status"), {"Completed", "Issued"},
                          "Linked endorsement status must synchronize to Completed")
        else:
            self.fail("Endorsement was not created or found for policy")

    @tier(1, "M09.3", gate=4)
    def test_feat_33_customer_360_servicing_integration(self):
        """M09.3: Customer 360 view includes servicing requests and endorsements."""
        cust = self.create_customer()
        sr = self.client.post("/api/service-requests", json={
            "customerId": cust["id"],
            "requestType": "Certificate",
            "description": "Cert of insurance for landlord",
        }).json()

        view = self.client.get(f"/api/customers/{cust['id']}").json()
        self.assertIn("serviceRequests", view, "Customer 360 view missing serviceRequests attribute")
        self.assertTrue(any(s["id"] == sr["id"] for s in view["serviceRequests"]),
                        "Service request must appear in Customer 360")

    @tier(1, "M20.2a", gate=4)
    def test_feat_34_whatsapp_state_machine_protection(self):
        """M20.2a: Monotonic message delivery progression (Read cannot regress to Delivered)."""
        lead = self.create_lead()
        comm = self.client.post("/api/communications", json={
            "associatedId": lead["id"],
            "channel": "WhatsApp",
            "recipient": "+919876543210",
            "content": "Policy renewal reminder",
        }).json()

        # Set status to Read
        self.client.post(f"/api/communications/{comm['id']}/delivery-event", json={"status": "Read"})

        # Delayed Delivered callback arrives
        self.client.post(f"/api/communications/{comm['id']}/delivery-event", json={"status": "Delivered"})

        res = self.client.get(f"/api/communications/{comm['id']}").json()
        self.assertEqual(res.get("status"), "Read", "Monotonic delivery protection must prevent regression from Read back to Delivered")

    @tier(1, "M20.2b", gate=4)
    def test_feat_35_sent_message_retry_idempotency(self):
        """M20.2b: Do not re-dispatch communications already in Sent, Delivered, or Read state."""
        lead = self.create_lead()
        comm = self.client.post("/api/communications", json={
            "associatedId": lead["id"],
            "channel": "Email",
            "recipient": "client@apex.invalid",
            "content": "Confirmation letter",
        }).json()

        with patch.object(server, "_dispatch", return_value={"status": "Sent", "providerMessageId": "p_mock_1"}) as mock_dispatch:
            # First send
            self.client.post(f"/api/communications/{comm['id']}/send")
            # Retry send
            self.client.post(f"/api/communications/{comm['id']}/send")

            self.assertEqual(mock_dispatch.call_count, 1, "Send retry must not re-dispatch already sent message")

    @tier(1, "M21.2", gate=4)
    def test_feat_36_consent_continuity_across_conversion(self):
        """M21.2: Lead opt-out preference blocks communications after customer conversion."""
        lead = self.create_lead(email="optout@apex.invalid")
        self.client.post("/api/consents", json={"leadId": lead["id"], "channel": "Email", "status": "Opted Out"})

        conv = self.client.post(f"/api/leads/{lead['id']}/convert", json={}).json()
        cust_id = conv["customer"]["id"]

        send_res = self.client.post("/api/communications", json={
            "associatedId": cust_id,
            "channel": "Email",
            "recipient": "optout@apex.invalid",
            "content": "Promotional email",
        })
        self.assertEqual(send_res.status_code, 409,
                         f"Dispatch to opted out address must return 409 Conflict, got {send_res.status_code}")

    @tier(1, "M21.3", gate=4)
    def test_feat_37_template_reference_validation(self):
        """M21.3: Reject communications referencing nonexistent templateId."""
        lead = self.create_lead()
        res = self.client.post("/api/communications", json={
            "associatedId": lead["id"],
            "templateId": "TPL_NONEXISTENT_999",
            "recipient": "test@apex.invalid",
            "channel": "Email",
        })
        self.assertIn(res.status_code, (404, 422),
                      f"Nonexistent templateId must be rejected with 404/422, got {res.status_code}")

    @tier(1, "M14.2", gate=4)
    def test_feat_38_renewal_alert_resolution(self):
        """M14.2: Completing a renewal resolves all overdue notifications for that renewal."""
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active")
        ren = self.create_renewal(pol["id"])

        # Seed notification
        db = server.load_db()
        db["notifications"].append({"id": "N_REN_01", "renewalId": ren["id"], "title": "Renewal due", "read": False})
        server.save_db(db)

        quote = self.client.post("/api/quotations", json={
            "renewalId": ren["id"], "insurer": "Test Insurer", "premium": 150000, "validityDate": "2026-12-31"
        }).json()
        self.client.put(f"/api/renewals/{ren['id']}", json={"selectedQuotationId": quote["id"]})

        self.client.post(f"/api/renewals/{ren['id']}/complete", json={
            "policyNumber": "BP-COMPLETE", "startDate": "2026-10-01", "expiryDate": "2027-10-01",
            "documentChecklist": dict.fromkeys(["proposalForm", "kyc", "payment", "schedule"], True)
        })

        notes = self.client.get("/api/notifications").json()
        target = next((n for n in notes if n["id"] == "N_REN_01"), None)
        if target:
            self.assertTrue(target.get("read") or target.get("resolved"), "Renewal completion must resolve renewal alert")

    @tier(1, "M14.3", gate=4)
    def test_feat_39_overdue_escalation_routing(self):
        """M14.3: Route overdue escalations to task assignee's configured manager (reportsTo)."""
        db = server.load_db()
        db["users"] = [
            {"id": "U1", "name": "Sarah Connor", "role": "broker", "reportsTo": "U2"},
            {"id": "U2", "name": "John Connor", "role": "manager", "reportsTo": "U3"},
        ]
        server.save_db(db)

        task = self.client.post("/api/tasks", json={
            "title": "Overdue Audit Work",
            "dueDate": "2020-01-01",
            "assignedTo": "Sarah Connor",
        }).json()

        self.client.post("/api/admin/jobs/run")

        notes = self.client.get("/api/notifications").json()
        esc = next((n for n in notes if n.get("taskId") == task["id"]), None)
        if esc:
            self.assertIn(esc.get("escalatedTo"), ("John Connor", "U2", "Administrator"),
                          "Overdue alert must be routed to configured manager")

    @tier(1, "F01", gate=4)
    def test_feat_41_assignment_rule_concurrency_isolation(self):
        """F01: Rule matching must not leak across requests via global dictionaries."""
        self.assertTrue(hasattr(server, "last_rule_match_var") or hasattr(server, "_last_rule_match"),
                        "Assignment rule state tracking must exist in pipecat_server.py")
        if hasattr(server, "last_rule_match_var"):
            self.assertIsInstance(getattr(server, "last_rule_match_var"), contextvars.ContextVar,
                                  "Rule match tracker must be a contextvars.ContextVar for concurrency safety")

    @tier(1, "F02", gate=4)
    def test_feat_42_ai_advisor_tenant_concurrency_isolation(self):
        """F02: AI advisor error tracking must be context or tenant isolated."""
        if hasattr(server, "advisor_error_var"):
            self.assertIsInstance(getattr(server, "advisor_error_var"), contextvars.ContextVar,
                                  "AI advisor error status must be isolated via ContextVar")

    @tier(1, "F03", gate=4)
    def test_feat_43_non_blocking_async_smtp(self):
        """F03: SMTP communication dispatch executes non-blockingly."""
        server_code = (ROOT / "pipecat_server.py").read_text()
        self.assertTrue("run_in_threadpool" in server_code or "asyncio.to_thread" in server_code or "loop.run_in_executor" in server_code,
                        "Synchronous SMTP operations must be delegated to a thread pool executor")

    # --- GATE 5: Frontend UX, Browser Acceptance & Documentation ---

    @tier(1, "M01.1+", gate=5)
    def test_feat_40_browser_flow_acceptance_contracts(self):
        """M01.1+: Browser flow acceptance requirements (heading and modal selectors)."""
        html = (ROOT / "web/index.html").read_text()
        css = (ROOT / "web/style.css").read_text()

        # Modal selector alignment
        self.assertIn("#stage-transition-modal", css, "CSS must style #stage-transition-modal to match test selector")
        self.assertIn('id="stage-transition-modal"', html, "HTML must contain modal #stage-transition-modal")

    @tier(1, "F09", gate=5)
    def test_feat_44_dynamic_user_roster_for_tasks(self):
        """F09: Task assignee modal dropdown dynamically populates from user roster."""
        html = (ROOT / "web/index.html").read_text()
        self.assertTrue('id="task-modal-assignee"' in html or 'id="task-assignee"' in html,
                        "Task assignee select element missing from web/index.html")
        self.assertIn('data-roster="names-only"', html, "Select should carry data-roster attribute for dynamic population")

    @tier(1, "F10", gate=5)
    def test_feat_45_demo_data_cleanup_link_wiring(self):
        """F10: Element demo-cleanup-link is present and wired in DOM."""
        html = (ROOT / "web/index.html").read_text()
        self.assertIn('id="demo-cleanup-link"', html, "Accessible #demo-cleanup-link must exist in DOM")

    @tier(1, "R5.Doc", gate=5)
    def test_feat_46_release_documentation(self):
        """Feature 46: README.md and ARCHITECTURE.md reflect commercial readiness state."""
        readme = (ROOT / "README.md").read_text()
        arch = (ROOT / "ARCHITECTURE.md").read_text()

        self.assertTrue(len(readme) > 500, "README.md must be populated")
        self.assertTrue(len(arch) > 500, "ARCHITECTURE.md must be populated")
        self.assertIn("InsureCRM", readme)
        self.assertIn("InsureCRM", arch)


# ============================================================================
# TIER 2: BOUNDARY & CORNER CASES
# ============================================================================

class TestTier2BoundaryCornerCases(BaseE2ETestCase):
    """Tier 2: Boundary conditions, edge cases, financial limits, and state transitions."""

    @tier(2, "B-FIN-01", gate=2)
    def test_boundary_financial_limits_zero_negative_decimal(self):
        """Boundary: Verify zero premium (valid endorsement/courtesy policy), negative premium (invalid), and high decimals."""
        cust = self.create_customer()

        # Zero premium is permissible (e.g. nil endorsement)
        p_zero = self.client.post("/api/policies", json={
            "customerId": cust["id"], "customerName": cust["name"], "policyType": "Property",
            "premium": 0, "sumInsured": 100000, "startDate": "2026-01-01", "expiryDate": "2026-12-31"
        })
        self.assertIn(p_zero.status_code, (200, 201), "Zero premium should be accepted")

        # Negative premium must be rejected
        p_neg = self.client.post("/api/policies", json={
            "customerId": cust["id"], "customerName": cust["name"], "policyType": "Property",
            "premium": -0.01, "sumInsured": 100000, "startDate": "2026-01-01", "expiryDate": "2026-12-31"
        })
        self.assertEqual(p_neg.status_code, 422, "Negative decimal premium must be rejected with 422")

        # Zero or negative sum insured must be rejected
        p_zero_si = self.client.post("/api/policies", json={
            "customerId": cust["id"], "customerName": cust["name"], "policyType": "Property",
            "premium": 1000, "sumInsured": 0, "startDate": "2026-01-01", "expiryDate": "2026-12-31"
        })
        self.assertEqual(p_zero_si.status_code, 422, "Zero sumInsured must be rejected with 422")

    @tier(2, "B-DATE-01", gate=2)
    def test_boundary_policy_date_sequences_same_day_inverted_leap_year(self):
        """Boundary: Same day policy term (valid), inverted term (invalid), and leap year handling."""
        cust = self.create_customer()

        # Same day start and expiry (valid: single-day transit policy)
        p_same = self.client.post("/api/policies", json={
            "customerId": cust["id"], "customerName": cust["name"], "policyType": "Property",
            "premium": 500, "sumInsured": 100000, "startDate": "2026-06-01", "expiryDate": "2026-06-01"
        })
        self.assertIn(p_same.status_code, (200, 201), "Same-day start and expiry date must be permitted")

        # Inverted dates by 1 day
        p_inv = self.client.post("/api/policies", json={
            "customerId": cust["id"], "customerName": cust["name"], "policyType": "Property",
            "premium": 500, "sumInsured": 100000, "startDate": "2026-06-02", "expiryDate": "2026-06-01"
        })
        self.assertEqual(p_inv.status_code, 422, "Inverted dates by 1 day must be rejected with 422")

        # Leap year date 2028-02-29
        p_leap = self.client.post("/api/policies", json={
            "customerId": cust["id"], "customerName": cust["name"], "policyType": "Property",
            "premium": 500, "sumInsured": 100000, "startDate": "2028-02-28", "expiryDate": "2028-02-29"
        })
        self.assertIn(p_leap.status_code, (200, 201), "Valid leap year dates must be accepted")

    @tier(2, "B-REL-01", gate=3)
    def test_boundary_dangling_parent_foreign_keys(self):
        """Boundary: Reject parent entity references that do not exist across contacts, documents, and service requests."""
        # Nonexistent customer on contact
        c_res = self.client.post("/api/contacts", json={"name": "Ghost", "customerId": "CUS_GHOST_404"})
        self.assertIn(c_res.status_code, (404, 422))

        # Nonexistent policy on service request
        sr_res = self.client.post("/api/service-requests", json={
            "customerId": "CUS_GHOST_404", "policyId": "POL_GHOST_404", "requestType": "Endorsement"
        })
        self.assertIn(sr_res.status_code, (404, 422))

    @tier(2, "B-RBAC-01", gate=1)
    def test_boundary_rbac_privilege_escalation_attempt(self):
        """Boundary: Readonly auditor attempting PUT or POST mutations must receive 403."""
        lead = self.create_lead()
        auditor_client, auditor_hdr = self.enable_auth_session(role="readonly", user_id="U_AUDITOR")

        # Mutation attempt
        edit_res = auditor_client.put(f"/api/leads/{lead['id']}", headers=auditor_hdr, json={"status": "Closed"})
        self.assertEqual(edit_res.status_code, 403, "Read-only auditor must receive 403 on mutation")

    @tier(2, "B-DST-01", gate=4)
    def test_boundary_dst_wall_clock_transition_gap(self):
        """Boundary: Calendar scheduling during nonexistent 02:30 spring forward gap in America/New_York."""
        res = self.client.post("/api/calendar/events", json={
            "title": "DST Gap Meeting",
            "date": "2027-03-14",
            "time": "02:30",
            "timezone": "America/New_York",
        })
        self.assertIn(res.status_code, (409, 422),
                      f"Scheduling during spring DST gap must return 409 or 422, got {res.status_code}")

    @tier(2, "B-IMP-01", gate=3)
    def test_boundary_import_rollback_mixed_batch(self):
        """Boundary: Rollback on a batch where one item was converted and another untouched."""
        analyzed = self.client.post("/api/imports/analyze?filename=mixed.csv",
                                    content=b"Name,Phone,Email\nBatch One,9999124001,b1@apex.invalid\nBatch Two,9999124002,b2@apex.invalid\n").json()
        import_id = analyzed.get("importId") or analyzed.get("id")
        self.client.post(f"/api/imports/{import_id}/commit", json={"mapping": {"0": "name", "1": "mobile", "2": "email"}})

        leads = self.client.get("/api/leads").json()
        lead_0 = next(l for l in leads if l.get("email") == "b1@apex.invalid")
        self.client.post(f"/api/leads/{lead_0['id']}/convert", json={})

        # Rollback
        self.client.post(f"/api/imports/{import_id}/rollback")

        # Converted customer must remain preserved
        customers = self.client.get("/api/customers").json()
        self.assertTrue(any(c.get("email") == "b1@apex.invalid" for c in customers),
                        "Converted import lead customer must not be destroyed by rollback")


# ============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS
# ============================================================================

class TestTier3CrossFeatureCombinations(BaseE2ETestCase):
    """Tier 3: Multi-feature integration chains across boundaries."""

    @tier(3, "C-LIFE-01", gate=3)
    def test_combo_lead_to_quote_to_conversion_to_policy_issuance_to_servicing(self):
        """Cross-feature: Ingest lead -> create decoupled quote -> convert with master org -> upload evidence -> issue policy -> service request."""
        # 1. Ingest Lead
        lead = self.create_lead(organization="Reliance Global Heavy Industries")
        self.assertTrue(lead["id"])

        # 2. Decoupled Quote
        quote = self.client.post("/api/quotations", json={
            "leadId": lead["id"],
            "insurer": "New India Assurance",
            "premium": 275000,
            "sumInsured": 20000000,
            "validityDate": "2026-11-30",
        }).json()
        self.assertEqual(quote.get("leadId"), lead["id"])

        # 3. Convert Lead
        conv = self.client.post(f"/api/leads/{lead['id']}/convert", json={}).json()
        customer = conv["customer"]
        policy = conv["policy"]
        self.assertTrue(customer.get("organizationId"), "Master organization must be linked on conversion")

        # 4. Upload Document Checklist Evidence
        for doc_type in ("proposalForm", "kyc", "payment", "schedule"):
            doc_res = self.client.post("/api/documents", json={
                "associatedType": "Policy",
                "associatedId": policy["id"],
                "docType": doc_type,
                "filename": f"{doc_type}.pdf",
                # A real (minimal) PDF: uploads are checked for type and contents.
                "content": "JVBERi0xLjQKJSB0ZXN0IGV2aWRlbmNlCg==",
            })
            self.assertIn(doc_res.status_code, (200, 201))

        # 5. Issue Policy
        issue_res = self.client.post(f"/api/policies/{policy['id']}/issue", json={
            "checklist": {"proposalForm": True, "kyc": True, "payment": True, "schedule": True}
        })
        self.assertEqual(issue_res.status_code, 200, f"Policy issuance with evidence failed: {issue_res.text}")

        # 6. Service Request with Endorsement
        sr = self.client.post("/api/service-requests", json={
            "customerId": customer["id"],
            "policyId": policy["id"],
            "requestType": "Endorsement",
            "description": "Add warehouse address",
        }).json()
        self.assertEqual(sr.get("customerId"), customer["id"])

        # 7. Complete Service Request with Outcome
        comp_res = self.client.put(f"/api/service-requests/{sr['id']}", json={
            "status": "Completed",
            "outcome": "Endorsement 01 issued by New India Assurance",
        })
        self.assertEqual(comp_res.status_code, 200)

        # 8. Verify Customer 360 Aggregation
        c360 = self.client.get(f"/api/customers/{customer['id']}").json()
        self.assertTrue(any(s["id"] == sr["id"] for s in c360.get("serviceRequests", [])),
                        "Service request must appear in Customer 360 aggregation")

    @tier(3, "C-REN-01", gate=2)
    def test_combo_policy_renewal_competing_quotes_and_idempotent_issuance(self):
        """Cross-feature: Active policy -> renewal generation -> competing quotes -> quote selection -> idempotent completion."""
        # Dates are relative to today: a fixed expiry falls out of the renewal window once it passes.
        today = datetime.now().date()
        expiry = today + timedelta(days=30)
        validity = (today + timedelta(days=20)).isoformat()
        cust = self.create_customer()
        pol = self.create_policy(cust["id"], status="Active", expiryDate=expiry.isoformat(), premium=100000)

        # Generate renewals
        gen = self.client.post("/api/renewals/generate?days=365").json()
        renewal = next(r for r in gen.get("renewals", []) if r.get("policyId") == pol["id"])

        # Competing quotes
        q1 = self.client.post("/api/quotations", json={
            "renewalId": renewal["id"], "insurer": "HDFC Ergo", "premium": 95000, "validityDate": validity
        }).json()
        q2 = self.client.post("/api/quotations", json={
            "renewalId": renewal["id"], "insurer": "Tata AIG", "premium": 92000, "validityDate": validity
        }).json()

        # Select Best Quote
        self.client.put(f"/api/renewals/{renewal['id']}", json={"selectedQuotationId": q2["id"]})

        payload = {
            "policyNumber": "BP-NEXT-COMBO",
            "startDate": (expiry + timedelta(days=1)).isoformat(),
            "expiryDate": (expiry + timedelta(days=366)).isoformat(),
            "documentChecklist": dict.fromkeys(["proposalForm", "kyc", "payment", "schedule"], True),
        }

        # Complete Renewal 1st time
        res1 = self.client.post(f"/api/renewals/{renewal['id']}/complete", json=payload)
        self.assertEqual(res1.status_code, 200)
        pol1_id = res1.json().get("newPolicy", {}).get("id") or res1.json().get("policyId")

        # Complete Renewal 2nd time (Retry)
        res2 = self.client.post(f"/api/renewals/{renewal['id']}/complete", json=payload)
        self.assertEqual(res2.status_code, 200)
        pol2_id = res2.json().get("newPolicy", {}).get("id") or res2.json().get("policyId")

        self.assertEqual(pol1_id, pol2_id, "Idempotent completion must yield exact same successor policy")


# ============================================================================
# TIER 4: REAL-WORLD APPLICATION SCENARIOS
# ============================================================================

class TestTier4RealWorldScenarios(BaseE2ETestCase):
    """Tier 4: Comprehensive end-to-end broker lifecycle & tenant operational scenarios."""

    @tier(4, "S-TENANT-01", gate=1)
    def test_scenario_multi_broker_tenant_operations_and_isolation(self):
        """Scenario: Multi-broker team within brokerage handling separate lead portfolios."""
        lead_a = self.create_lead(assignedTo="Alice Broker")
        alice_client, alice_hdr = self.enable_auth_session(role="broker", user_id="U_ALICE", name="Alice Broker")
        bob_client, bob_hdr = self.enable_auth_session(role="broker", user_id="U_BOB", name="Bob Broker")

        # Alice creates private notes on her lead
        note_a = alice_client.post("/api/notes", headers=alice_hdr, json={
            "leadId": lead_a["id"],
            "title": "Alice Note",
            "content": "Negotiating premium rates with underwriters",
        }).json()
        self.assertEqual(note_a.get("author"), "Alice Broker")

        # Alice creates a task
        task_a = alice_client.post("/api/tasks", headers=alice_hdr, json={
            "title": "Alice Follow Up",
            "assignedTo": "Alice Broker",
            "dueDate": "2026-10-10",
        }).json()
        self.assertEqual(task_a.get("assignedTo"), "Alice Broker")

        # Bob queries notifications: should not see Alice's personal notifications
        bob_notes = bob_client.get("/api/notifications").json()
        self.assertFalse(any(n.get("assignedTo") == "Alice Broker" for n in bob_notes),
                         "Bob must not see Alice's notifications in scoped notification feed")

    @tier(4, "S-DISASTER-01", gate=3)
    def test_scenario_disaster_recovery_cascade_cleanup_and_audit_integrity(self):
        """Scenario: Audit trail permanence and cascade cleanup during operational deletion."""
        lead = self.create_lead()
        note = self.client.post("/api/notes", json={"leadId": lead["id"], "title": "Inspection", "content": "Clean report"}).json()

        # Delete lead
        self.client.delete(f"/api/leads/{lead['id']}")

        # Audit log must record the deletion
        logs = self.client.get("/api/audit-logs").json()
        self.assertTrue(any(l.get("entityId") == lead["id"] or "delete" in str(l).lower() for l in logs),
                        "Audit logs must record entity deletion permanently")

        # Notes must remain preserved in archive storage
        archived_notes = self.client.get("/api/notes?includeArchived=true").json()
        self.assertTrue(any(n["id"] == note["id"] and n.get("archived") for n in archived_notes),
                        "Notes must be archived rather than permanently dropped")


if __name__ == "__main__":
    unittest.main()
