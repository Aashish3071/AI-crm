"""Executable commercial expectations. Failures are defects, not expectedFailure.

Only disposable stores and synthetic identities are used. Never invoke this suite
against the running CRM. Run through tests.run_blueprint_audit for the evidence file.
"""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pipecat_server as server
import crm_security
import test_insurance_operations
import test_security_foundation

REQUEST_EVIDENCE = []


def criterion(*ids, complete=False):
    def decorate(function):
        function.criteria = ids
        function.complete_criterion = complete
        return function
    return decorate


class BlueprintAcceptance(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"DATABASE_URL": "", "OBJECT_STORAGE_BUCKET": "",
            "APP_ENV": "development", "CLAMAV_HOST": "", "DOCUMENT_SCANNER_URL": ""})
        self.environment.start()
        test_insurance_operations.InsuranceOperationsTests.setUp(self)
        state = server._empty_company_db()
        state["users"] = server.get_initial_db()["users"]
        server.save_db(state)
        original_request = self.client.request
        def tracked(method, url, **kwargs):
            result = original_request(method, url, **kwargs)
            REQUEST_EVIDENCE.append({"test": self.id(), "method": method.upper(),
                "path": str(url).split("?")[0], "status": result.status_code})
            return result
        self.client.request = tracked

    def tearDown(self):
        test_insurance_operations.InsuranceOperationsTests.tearDown(self)
        self.environment.stop()

    def ok(self, method, url, **kwargs):
        response = getattr(self.client, method)(url, **kwargs)
        self.assertLess(response.status_code, 300, f"Setup/action {method} {url}: {response.status_code} {response.text[:200]}")
        return response.json()

    def lead(self, **changes):
        return self.ok("post", "/api/leads", json={"firstName": "Blueprint", "lastName": "Client",
            "organization": "Blueprint Co", "email": "client@example.invalid", "mobile": "+919999123456",
            "premium": "1000.50", "nextAction": "Call prospect", "nextActionDate": "2026-10-10", **changes})

    def customer(self, **changes):
        return self.ok("post", "/api/customers", json={"name": "Blueprint Customer", **changes})

    def policy(self, customer=None, **changes):
        customer = customer or self.customer()
        return self.ok("post", "/api/policies", json={"customerId": customer["id"], "customerName": customer["name"],
            "policyType": "Property", "premium": 1000.50, "insurer": "Test Insurer", "startDate": "2026-01-01",
            "expiryDate": "2026-12-31", **changes})

    def renewal(self, policy=None):
        return self.ok("post", "/api/renewals", json={"policyId": (policy or self.policy())["id"]})

    def quote(self, renewal=None, **changes):
        return self.ok("post", "/api/quotations", json={"renewalId": (renewal or self.renewal())["id"],
            "insurer": "Test Insurer", "premium": 1050.50, "validityDate": "2027-01-01", **changes})

    def import_batch(self):
        analyzed = self.ok("post", "/api/imports/analyze?filename=blueprint.csv",
            content=b"Name,Phone,Email\nImport Client,9999123401,import@example.invalid\n,9999123402,missing-name@example.invalid\n")
        return analyzed["importId"]

    def commit(self, batch):
        return self.ok("post", f"/api/imports/{batch}/commit", json={"mapping": {"0": "name", "1": "mobile", "2": "email"}})

    @criterion("M01.2", complete=True)
    def test_dashboard_today_filters_dates_and_archives(self):
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        for title, due, status in [("today", today, "Pending"), ("tomorrow", today + timedelta(days=1), "Pending"),
                                   ("archived", today, "Archived"), ("done", today, "Completed")]:
            task = self.ok("post", "/api/tasks", json={"title": title, "dueDate": str(due)})
            self.ok("put", f"/api/tasks/{task['id']}", json={"status": status})
        titles = {item["title"] for item in self.ok("get", "/api/dashboard")["tasksDueToday"]}
        self.assertEqual(titles, {"today"}, "Dashboard due-today must exclude tomorrow, completed and archived tasks")

    @criterion("M01.3")
    def test_dashboard_preserves_decimal_premium(self):
        self.lead(premium="1000.50")
        value = self.ok("get", "/api/dashboard")["pipelineValue"]
        self.assertAlmostEqual(server.money_value(value), 1000.50, places=2,
            msg="Pipeline premium must not turn 1000.50 into 100050")

    @criterion("M03.2")
    def test_webhook_ingestion_has_canonical_task_reference(self):
        channel = self.ok("post", "/api/channels", json={"name": "Blueprint Ingress", "provider": "custom"})
        self.ok("post", f"/api/channels/{channel['id']}/test", json={"name": "Source Client", "phone": "9999888777"})
        leads = self.ok("get", "/api/leads")
        self.assertTrue(leads, "Ingestion must produce a lead")
        task_ids = {t["id"] for t in self.ok("get", "/api/tasks")}
        self.assertIn(leads[0].get("nextActionTaskId"), task_ids, "Source lead lacks canonical nextActionTaskId")

    @criterion("M04.1")
    def test_import_mapping_and_error_download(self):
        batch = self.import_batch()
        self.commit(batch)
        saved = self.ok("get", f"/api/imports/{batch}")
        self.assertEqual(saved["importedCount"], 1)
        self.assertEqual(self.client.get(f"/api/imports/{batch}/rejected.csv").status_code, 200)

    @criterion("M04.2", complete=True)
    def test_imported_lead_links_canonical_task(self):
        self.commit(self.import_batch())
        lead = self.ok("get", "/api/leads")[0]
        self.assertIn(lead.get("nextActionTaskId"), {t["id"] for t in self.ok("get", "/api/tasks")},
            "Imported lead lacks canonical task reference")

    @criterion("M04.3")
    def test_import_retry_and_rollback_preserves_edited_lead(self):
        batch = self.import_batch(); self.commit(batch)
        self.assertEqual(self.client.post(f"/api/imports/{batch}/commit", json={"mapping": {"0": "name"}}).status_code, 409)
        lead = self.ok("get", "/api/leads")[0]
        self.ok("put", f"/api/leads/{lead['id']}", json={"name": "Human-corrected customer"})
        response = self.client.post(f"/api/imports/{batch}/rollback")
        self.assertIn(response.status_code, {200, 409})
        self.assertEqual(self.client.get(f"/api/leads/{lead['id']}").status_code, 200,
            "Import rollback must not discard subsequently edited leads")

    @criterion("M05.1")
    def test_rule_preview_does_not_consume_rotation(self):
        self.ok("get", "/api/assignment-rules/options")
        before = self.ok("get", "/api/assignment-rules")
        self.ok("post", "/api/assignment-rules/preview", json={"policyType": "Property"})
        self.assertEqual(before, self.ok("get", "/api/assignment-rules"))

    @criterion("M05.3")
    def test_direct_entry_uses_enabled_routing(self):
        state = server.load_db()
        state.setdefault("settings", {})["assignmentRules"] = []
        server.save_db(state)
        with patch.object(server, "apply_assignment_rules", return_value="John Parker") as routing:
            lead = self.lead(assignedTo="")
        self.assertTrue(routing.called, "Direct entry bypassed shared assignment-rule engine")
        self.assertEqual(lead["assignedTo"], "John Parker")

    @criterion("M06.3")
    def test_lead_invalid_stage_and_loss_reason(self):
        lead = self.lead()
        for stage in ("Invented", "Lost"):
            response = self.client.put(f"/api/leads/{lead['id']}/stage", json={"status": stage,
                "nextAction": "Follow up", "nextActionDate": "2026-10-10"})
            self.assertEqual(response.status_code, 422)

    @criterion("M07.1")
    def test_independent_deal_creation_exists(self):
        customer = self.customer()
        response = self.client.post("/api/deals", json={"dealName": "New opportunity", "customerId": customer["id"],
            "organization": "Blueprint Co", "status": "Open", "annualRevenue": "5000"})
        self.assertIn(response.status_code, {200, 201}, "Pipeline has no supported independent deal-creation endpoint")

    @criterion("M07.2", complete=True)
    def test_conversion_updates_existing_deal(self):
        lead = self.lead()
        state = server.load_db()
        state["deals"].append({"id": "D_BP", "leadId": lead["id"], "organization": "Blueprint Co", "status": "Open"})
        server.save_db(state)
        result = self.ok("post", f"/api/leads/{lead['id']}/convert", json={})
        deal = next(d for d in self.ok("get", "/api/deals") if d["id"] == "D_BP")
        self.assertEqual(deal["status"], "Won", "Existing deal did not advance on conversion")
        self.assertEqual(deal.get("customerId"), result["customer"]["id"])

    @criterion("M07.3")
    def test_deal_close_is_projected_to_calendar(self):
        lead = self.lead(); self.ok("post", f"/api/leads/{lead['id']}/convert", json={})
        deal = self.ok("get", "/api/deals")[0]
        self.ok("put", f"/api/deals/{deal['id']}", json={"status": "Open", "expectedCloseDate": "2026-10-11"})
        entries = self.ok("get", "/api/calendar")["entries"]
        self.assertEqual(len([e for e in entries if e.get("linkType") == "Deal" and e.get("linkId") == deal["id"]]), 1)

    @criterion("M08.1")
    def test_conversion_retry_does_not_duplicate(self):
        lead = self.lead()
        result = self.ok("post", f"/api/leads/{lead['id']}/convert", json={})
        self.assertEqual(result["policy"]["customerId"], result["customer"]["id"])
        self.assertEqual(result["policy"]["status"], "Draft")
        self.assertEqual(self.client.post(f"/api/leads/{lead['id']}/convert", json={}).status_code, 409)
        self.assertEqual(len(self.ok("get", "/api/policies")), 1)

    @criterion("M08.2")
    def test_conversion_new_organization_has_stable_relationship(self):
        lead = self.lead()
        result = self.ok("post", f"/api/leads/{lead['id']}/convert", json={"organization": "Different Legal Entity"})
        organizations = {o["id"]: o for o in self.ok("get", "/api/organizations")}
        self.assertIn(result["policy"].get("organizationId"), organizations,
            "Conversion accepted a new organization label without its master record")

    @criterion("M09.1", "M11.1")
    def test_multiple_contacts_and_policies_in_customer_360(self):
        customer = self.customer()
        for name in ("Finance", "Operations"):
            contact = self.ok("post", "/api/contacts", json={"name": name, "customerId": customer["id"]})
            self.ok("put", f"/api/contacts/{contact['id']}", json={"designation": "Decision Maker"})
        self.policy(customer); self.policy(customer)
        view = self.ok("get", f"/api/customers/{customer['id']}")
        self.assertEqual(len(view["contacts"]), 2)
        self.assertEqual(len(view["policies"]), 2)

    @criterion("M09.2")
    def test_customer_rename_updates_policy_label(self):
        customer = self.customer(); policy = self.policy(customer)
        self.ok("put", f"/api/customers/{customer['id']}", json={"name": "Renamed Customer"})
        stored = next(p for p in self.ok("get", "/api/policies") if p["id"] == policy["id"])
        self.assertEqual(stored["customerName"], "Renamed Customer", "Active policy still displays old customer name")

    @criterion("M10.1")
    def test_organization_create_edit_audit(self):
        org = self.ok("post", "/api/organizations", json={"name": "Org One"})
        self.ok("put", f"/api/organizations/{org['id']}", json={"name": "Org Two"})
        self.assertEqual(self.ok("get", "/api/organizations")[0]["name"], "Org Two")
        self.assertGreaterEqual(len(self.ok("get", f"/api/audit-logs?entityId={org['id']}")), 2)

    @criterion("M10.2")
    def test_organization_rename_updates_customer_label(self):
        org = self.ok("post", "/api/organizations", json={"name": "Original Org"})
        customer = self.customer(organization="Original Org")
        self.assertEqual(customer["organizationId"], org["id"])
        self.ok("put", f"/api/organizations/{org['id']}", json={"name": "Renamed Org"})
        self.assertEqual(self.ok("get", "/api/customers")[0]["organization"], "Renamed Org")

    @criterion("M10.3", "M11.3")
    def test_contact_rejects_nonexistent_parent(self):
        response = self.client.post("/api/contacts", json={"name": "Orphan", "customerId": "CUS_MISSING", "organizationId": "ORG_MISSING"})
        self.assertIn(response.status_code, {404, 422}, "Contact accepted dangling parent IDs")

    @criterion("M11.2", complete=True)
    def test_secondary_contact_survives_lead_edit(self):
        lead = self.lead()
        second = self.ok("post", "/api/contacts", json={"name": "Secondary Contact", "leadId": lead["id"], "email": "secondary@example.invalid"})
        self.ok("put", f"/api/leads/{lead['id']}", json={"name": "Primary Renamed"})
        stored = next(c for c in self.ok("get", "/api/contacts") if c["id"] == second["id"])
        self.assertEqual(stored["name"], "Secondary Contact")

    @criterion("M12.1")
    def test_task_validation(self):
        for payload in ({"title": "", "dueDate": "2026-10-10"}, {"title": "Call", "dueDate": "bad-date"}):
            self.assertEqual(self.client.post("/api/tasks", json=payload).status_code, 422)

    @criterion("M13.3")
    def test_calendar_rejects_dst_nonexistent_time(self):
        self.ok("put", "/api/settings", json={"crm": {"companyTimezone": "America/New_York"}})
        response = self.client.post("/api/calendar/events", json={"title": "DST gap", "date": "2027-03-14", "time": "02:30"})
        self.assertIn(response.status_code, {409, 422}, "02:30 does not exist on the spring DST transition day")

    @criterion("M14.2")
    def test_completed_renewal_resolves_renewal_alert(self):
        renewal = self.renewal()
        self.ok("put", f"/api/renewals/{renewal['id']}", json={"nextActionDate": "2020-01-01"})
        self.ok("post", "/api/notifications/run-escalations")
        self.ok("put", f"/api/renewals/{renewal['id']}", json={"stage": "Lost", "outcomeReason": "Client declined"})
        alerts = self.ok("get", "/api/notifications?unreadOnly=true")
        self.assertFalse(any(n.get("associatedId") == renewal["id"] for n in alerts), "Closed renewal retains an unread overdue alert")

    @criterion("M15.2")
    def test_note_edit_is_supported(self):
        lead = self.lead()
        note = self.ok("post", "/api/notes", json={"title": "Meeting", "content": "Initial meeting", "associatedId": lead["id"]})
        response = self.client.put(f"/api/notes/{note['id']}", json={"content": "Corrected meeting outcome"})
        self.assertEqual(response.status_code, 200, "No supported note-edit operation")

    @criterion("M16.1")
    def test_quote_from_another_renewal_cannot_be_selected(self):
        first, second = self.renewal(), self.renewal()
        quote = self.quote(second)
        response = self.client.put(f"/api/renewals/{first['id']}", json={"selectedQuotationId": quote["id"]})
        self.assertIn(response.status_code, {404, 422}, "Renewal accepted another renewal's quote")

    @criterion("M16.1")
    def test_expired_quote_cannot_be_selected(self):
        renewal = self.renewal(); quote = self.quote(renewal, validityDate="2020-01-01")
        response = self.client.put(f"/api/renewals/{renewal['id']}", json={"selectedQuotationId": quote["id"]})
        self.assertIn(response.status_code, {409, 422}, "Expired quote was selectable")

    @criterion("M16.2", complete=True)
    def test_quote_validity_appears_in_calendar(self):
        quote = self.quote()
        entries = self.ok("get", "/api/calendar")["entries"]
        self.assertTrue(any(e.get("date") == quote["validityDate"] and e.get("type") == "Quotation" for e in entries),
            "Quote validity field is not projected into Calendar")

    @criterion("M16.3")
    def test_new_business_quote_without_renewal(self):
        lead = self.lead()
        response = self.client.post("/api/quotations", json={"leadId": lead["id"], "insurer": "Test", "premium": 1000})
        self.assertIn(response.status_code, {200, 201}, "Quotation model requires an existing renewal; new business is unsupported")

    @criterion("M17.1")
    def test_policy_financial_calculation(self):
        policy = self.policy()
        self.assertEqual(policy["taxAmount"], 180.09)
        self.assertEqual(policy["totalPremium"], 1180.59)

    @criterion("M17.1")
    def test_negative_policy_premium_rejected(self):
        policy = self.policy()
        self.assertEqual(self.client.put(f"/api/policies/{policy['id']}", json={"premium": -100}).status_code, 422,
            "Negative premium accepted")

    @criterion("M17.1")
    def test_reversed_policy_term_rejected(self):
        policy = self.policy()
        self.assertEqual(self.client.put(f"/api/policies/{policy['id']}", json={"startDate": "2027-01-01", "expiryDate": "2026-01-01"}).status_code, 422,
            "Policy expiry before inception accepted")

    @criterion("M17.2")
    def test_policy_activation_cannot_bypass_issuance(self):
        policy = self.policy(insurer="", startDate="")
        response = self.client.put(f"/api/policies/{policy['id']}", json={"status": "Active"})
        self.assertEqual(response.status_code, 422, "Ordinary policy update bypassed issuance validation")

    @criterion("M17.2")
    def test_issuance_checkboxes_are_not_document_evidence(self):
        policy = self.policy()
        response = self.client.post(f"/api/policies/{policy['id']}/issue", json={"policyNumber": "BP-001",
            "documentChecklist": dict.fromkeys(["proposalForm", "kyc", "payment", "schedule"], True)})
        self.assertEqual(response.status_code, 422, "Policy issued without any stored supporting documents")

    @criterion("M18.1")
    def test_renewal_generation_excludes_drafts(self):
        soon = str(datetime.now().date() + timedelta(days=10))
        policy = self.policy(status="Draft", expiryDate=soon)
        generated = self.ok("post", "/api/renewals/generate?days=60")
        self.assertFalse(any(r["policyId"] == policy["id"] for r in generated["renewals"]), "Draft policy entered renewal pipeline")

    @criterion("M18.2")
    def test_renewal_completion_retry_is_idempotent(self):
        renewal = self.renewal(); quote = self.quote(renewal)
        self.ok("put", f"/api/renewals/{renewal['id']}", json={"selectedQuotationId": quote["id"]})
        payload = {"policyNumber": "BP-NEXT", "startDate": "2027-01-01", "expiryDate": "2027-12-31",
            "documentChecklist": dict.fromkeys(["proposalForm", "kyc", "payment", "schedule"], True)}
        self.ok("post", f"/api/renewals/{renewal['id']}/complete", json=payload)
        self.client.post(f"/api/renewals/{renewal['id']}/complete", json=payload)
        self.assertEqual(len(self.ok("get", "/api/policies")), 2, "Repeated completion created multiple successor policies")

    @criterion("M19.1", complete=True)
    def test_service_rejects_other_customers_policy(self):
        customer = self.customer(); policy = self.policy()
        response = self.client.post("/api/service-requests", json={"customerId": customer["id"], "policyId": policy["id"],
            "requestType": "Endorsement", "description": "Add location"})
        self.assertEqual(response.status_code, 422)

    @criterion("M19.2")
    def test_endorsement_tracks_service_completion(self):
        policy = self.policy()
        service = self.ok("post", "/api/service-requests", json={"customerId": policy["customerId"], "policyId": policy["id"],
            "requestType": "Endorsement", "description": "Add location", "dueDate": "2026-10-11"})
        self.ok("put", f"/api/service-requests/{service['id']}", json={"status": "Completed"})
        endorsement = self.ok("get", f"/api/endorsements?policyId={policy['id']}")[0]
        self.assertIn(endorsement["status"], {"Completed", "Issued"}, "Completed service left endorsement Requested")

    @criterion("M19.3")
    def test_service_completion_requires_outcome(self):
        policy = self.policy()
        service = self.ok("post", "/api/service-requests", json={"customerId": policy["customerId"], "policyId": policy["id"],
            "requestType": "Cancellation", "description": "Cancellation requested"})
        self.assertEqual(self.client.put(f"/api/service-requests/{service['id']}", json={"status": "Completed"}).status_code, 422)

    @criterion("M20.1")
    def test_unconfigured_sender_does_not_claim_delivery(self):
        lead = self.lead()
        message = self.ok("post", "/api/communications", json={"associatedId": lead["id"], "recipient": "client@example.invalid",
            "channel": "Email", "content": "Test only"})
        sent = self.ok("post", f"/api/communications/{message['id']}/send")
        self.assertNotIn(sent["status"], {"Sent", "Delivered", "Read"})

    @criterion("M20.2")
    def test_out_of_order_delivery_does_not_regress_read(self):
        lead = self.lead()
        message = self.ok("post", "/api/communications", json={"associatedId": lead["id"], "recipient": "client@example.invalid", "channel": "Email", "content": "Test"})
        self.ok("post", f"/api/communications/{message['id']}/delivery-event", json={"status": "Read"})
        updated = self.ok("post", f"/api/communications/{message['id']}/delivery-event", json={"status": "Delivered"})
        self.assertEqual(updated["status"], "Read", "Older delivered callback regressed the message status")

    @criterion("M21.2")
    def test_lead_opt_out_survives_customer_conversion(self):
        lead = self.lead()
        self.ok("post", "/api/consents", json={"leadId": lead["id"], "channel": "Email", "status": "Opted Out"})
        converted = self.ok("post", f"/api/leads/{lead['id']}/convert", json={})
        response = self.client.post("/api/communications", json={"associatedType": "Customer", "associatedId": converted["customer"]["id"],
            "recipient": "client@example.invalid", "channel": "Email", "content": "Must be blocked"})
        self.assertEqual(response.status_code, 409, "Customer-linked communication bypassed lead opt-out")

    @criterion("M21.3")
    def test_missing_template_reference_rejected(self):
        lead = self.lead()
        response = self.client.post("/api/communications", json={"associatedId": lead["id"], "recipient": "client@example.invalid",
            "channel": "Email", "templateId": "TPL_MISSING", "content": "Hello {{unknown}}"})
        self.assertIn(response.status_code, {404, 422}, "Invalid template reference accepted")

    @criterion("M22.2")
    def test_document_rejects_missing_parent_before_storage(self):
        response = self.client.post("/api/documents?associatedType=Customer&associatedId=CUS_MISSING&filename=scope.txt", content=b"Synthetic text")
        self.assertIn(response.status_code, {404, 422}, "Document upload accepted a nonexistent parent")

    @criterion("M23.1")
    def test_search_and_lead_pagination(self):
        lead = self.lead()
        matches = self.ok("get", "/api/search?q=Blueprint")
        self.assertTrue(any(r["id"] == lead["id"] and r["type"] == "Lead" for r in matches))
        page = self.ok("get", "/api/leads?paginated=true&page=2&pageSize=1")
        self.assertEqual(page["items"], [])
        self.assertEqual(page["total"], 1)

    @criterion("M23.3")
    def test_global_search_finds_task_work(self):
        task = self.ok("post", "/api/tasks", json={"title": "DistinctiveTaskNeedle", "dueDate": "2026-10-10"})
        self.assertTrue(any(r["id"] == task["id"] for r in self.ok("get", "/api/search?q=DistinctiveTaskNeedle")),
            "Global search cannot find action tasks")

    @criterion("M24.1")
    def test_conversion_metric_uses_all_eligible_leads(self):
        first = self.lead(firstName="Converted")
        self.lead(firstName="Open", mobile="+919988112233")
        self.ok("post", f"/api/leads/{first['id']}/convert", json={})
        report = self.ok("get", "/api/reports/operations")
        self.assertEqual(report["conversionRate"], 50, "Labelled conversion metric uses closed-only win-rate denominator")

    @criterion("M24.2")
    def test_report_excludes_archived_work(self):
        task = self.ok("post", "/api/tasks", json={"title": "Old work", "dueDate": "2020-01-01"})
        self.ok("put", f"/api/tasks/{task['id']}", json={"status": "Archived"})
        self.assertEqual(self.ok("get", "/api/reports/operations")["overdueTasks"], 0)

    @criterion("M24.3")
    def test_report_period_filters_population(self):
        self.lead()
        report = self.ok("get", "/api/reports/operations?start=2000-01-01&end=2000-01-02")
        self.assertEqual(report["leadCount"], 0, "Report ignored requested historical period")

    @criterion("M25.1")
    def test_settings_timezone_validation(self):
        self.assertEqual(self.client.put("/api/settings", json={"crm": {"companyTimezone": "Invalid/Zone"}}).status_code, 422)
        self.ok("put", "/api/settings", json={"crm": {"companyTimezone": "Asia/Kolkata"}})
        self.assertEqual(self.ok("get", "/api/settings")["crm"]["companyTimezone"], "Asia/Kolkata")

    @criterion("M25.2")
    def test_configured_stage_is_used_by_transition_engine(self):
        response = self.client.put("/api/settings", json={"crm": {"leadStages": ["New", "Qualified", "Won", "Lost"]}})
        if response.status_code == 422:
            return
        self.assertEqual(response.status_code, 200)
        lead = self.lead()
        response = self.client.put(f"/api/leads/{lead['id']}/stage", json={"status": "Qualified", "nextAction": "Quote", "nextActionDate": "2026-10-10"})
        self.assertEqual(response.status_code, 200, "Settings accepted a stage the transition engine rejects")

    @criterion("M26.3")
    def test_lead_delete_removes_dependent_service_graph(self):
        lead = self.lead(); converted = self.ok("post", f"/api/leads/{lead['id']}/convert", json={})
        service = self.ok("post", "/api/service-requests", json={"customerId": converted["customer"]["id"], "policyId": converted["policy"]["id"],
            "requestType": "Endorsement", "description": "Synthetic service"})
        self.ok("delete", f"/api/leads/{lead['id']}")
        self.assertFalse(any(s["id"] == service["id"] for s in self.ok("get", "/api/service-requests")), "Cascade left servicing records pointing at deleted policy/customer")

    @criterion("M27.2")
    def test_legacy_policy_migration_is_audited(self):
        self.lead(policyType="Property")
        before = len(self.ok("get", "/api/audit-logs"))
        self.ok("post", "/api/policies/migrate-leads")
        self.assertGreater(len(self.ok("get", "/api/audit-logs")), before, "Policy migration mutates without an audit event")

    @criterion("M02.3")
    def test_reporting_hierarchy_rejects_cycles(self):
        self.assertEqual(self.client.put("/api/users/U1/manager", json={"reportsTo": "U1"}).status_code, 422)
        self.ok("put", "/api/users/U1/manager", json={"reportsTo": "U2"})
        self.assertEqual(self.client.put("/api/users/U2/manager", json={"reportsTo": "U1"}).status_code, 422)

    @criterion("M08.3", complete=True)
    def test_conversion_keeps_appointments_and_followups_in_360(self):
        lead = self.lead()
        event = self.ok("post", "/api/calendar/events", json={"title": "Account meeting", "date": "2026-10-10", "time": "09:00",
            "associatedType": "Lead", "associatedId": lead["id"], "followUpDate": "2026-10-11", "followUpAction": "Send recap"})
        converted = self.ok("post", f"/api/leads/{lead['id']}/convert", json={})
        view = self.ok("get", f"/api/customers/{converted['customer']['id']}")
        self.assertIn(event["id"], {e["id"] for e in view["calendarEvents"]})
        self.assertIn(event["followUpTaskId"], {t["id"] for t in view["tasks"]})

    @criterion("M09.3")
    def test_customer_360_includes_servicing(self):
        policy = self.policy()
        service = self.ok("post", "/api/service-requests", json={"customerId": policy["customerId"], "policyId": policy["id"],
            "requestType": "Certificate", "description": "Certificate request"})
        view = self.ok("get", f"/api/customers/{policy['customerId']}")
        self.assertIn(service["id"], {s["id"] for s in view.get("serviceRequests", [])}, "Customer 360 omits servicing records")

    @criterion("M14.3")
    def test_overdue_escalation_reaches_configured_manager(self):
        self.ok("put", "/api/users/U1/manager", json={"reportsTo": "U4"})
        task = self.ok("post", "/api/tasks", json={"title": "Escalate this work", "dueDate": "2020-01-01", "assignedTo": "Sarah Connor"})
        self.ok("post", "/api/admin/jobs/run")
        alerts = self.ok("get", "/api/notifications")
        self.assertTrue(any(n.get("taskId") == task["id"] and
            (n.get("assignedTo") == "Administrator" or n.get("escalatedTo") in {"Administrator", "U4"}) for n in alerts),
            "Escalation has no configured-manager recipient")

    @criterion("M25.3")
    def test_configured_product_choices_are_enforced(self):
        self.ok("put", "/api/settings", json={"crm": {"insuranceProducts": ["Property"], "insurers": ["Test Insurer"]}})
        customer = self.customer()
        response = self.client.post("/api/policies", json={"customerId": customer["id"], "customerName": customer["name"],
            "policyType": "Unconfigured Product", "expiryDate": "2027-01-01", "premium": 100})
        self.assertEqual(response.status_code, 422, "Configured product choices do not constrain policy entry")

    @criterion("M20.2")
    def test_sent_message_retry_does_not_dispatch_twice(self):
        lead = self.lead()
        message = self.ok("post", "/api/communications", json={"associatedId": lead["id"], "recipient": "client@example.invalid",
            "channel": "Email", "content": "Synthetic message"})
        def simulated_dispatch(_state, item):
            item.update({"status": "Sent", "providerMessageId": "provider-synthetic"})
            return item
        with patch.object(server, "_dispatch", side_effect=simulated_dispatch) as dispatch:
            self.ok("post", f"/api/communications/{message['id']}/send")
            self.client.post(f"/api/communications/{message['id']}/send")
        self.assertEqual(dispatch.call_count, 1, "Retry dispatched an already sent message twice")

    @criterion("M05.1")
    def test_assignment_rule_crud_and_preview(self):
        rule = self.ok("post", "/api/assignment-rules", json={"name": "Property Routing", "method": "rotate",
            "assignees": ["Sarah Connor", "John Parker"], "conditions": [{"field": "policyType", "operator": "is", "value": "Property"}]})
        self.ok("put", f"/api/assignment-rules/{rule['id']}", json={"name": "Renamed Routing"})
        self.ok("post", f"/api/assignment-rules/{rule['id']}/move", json={"direction": "up"})
        before = self.ok("get", "/api/assignment-rules")
        self.ok("post", "/api/assignment-rules/preview", json={"policyType": "Property"})
        self.assertEqual(before, self.ok("get", "/api/assignment-rules"))
        self.ok("delete", f"/api/assignment-rules/{rule['id']}")
        self.assertFalse(self.ok("get", "/api/assignment-rules"))

    @criterion("M26.2")
    def test_policy_archive_restore_retains_identity(self):
        policy = self.policy()
        archived = self.ok("post", f"/api/records/policies/{policy['id']}/archive")
        self.assertFalse(self.ok("get", "/api/policies"))
        self.assertTrue(self.ok("get", "/api/archived-records"))
        restored = self.ok("post", f"/api/archived-records/{archived['archiveId']}/restore")
        self.assertEqual(restored["id"], policy["id"])
        self.assertFalse(self.ok("get", "/api/archived-records"))

    @criterion("M12.1", "M14.1")
    def test_deleting_appointment_task_archives_calendar_and_resolves_alert(self):
        event = self.ok("post", "/api/calendar/events", json={"title": "Old meeting", "date": "2020-01-01", "time": "09:00"})
        self.ok("post", "/api/notifications/run-escalations")
        self.ok("delete", f"/api/tasks/{event['taskId']}")
        self.assertFalse(any(e["id"] == event["id"] for e in self.ok("get", "/api/calendar")["entries"]))
        self.assertFalse(any(n.get("calendarEventId") == event["id"] for n in self.ok("get", "/api/notifications?unreadOnly=true")))

    @criterion("M22.1")
    def test_document_list_preview_archive_and_invalid_type(self):
        lead = self.lead()
        doc = self.ok("post", f"/api/documents?associatedId={lead['id']}&filename=evidence.txt", content=b"Synthetic evidence")
        self.assertIn(doc["id"], {d["id"] for d in self.ok("get", "/api/documents")})
        self.assertEqual(self.client.get(f"/api/documents/{doc['id']}/content?preview=true").content, b"Synthetic evidence")
        self.assertEqual(self.ok("delete", f"/api/documents/{doc['id']}")["status"], "Archived")
        bad = self.client.post(f"/api/documents?associatedId={lead['id']}&filename=evidence.pdf", content=b"Not a PDF")
        self.assertEqual(bad.status_code, 422)

    @criterion("M21.1", "M21.3")
    def test_template_edit_and_whatsapp_local_lifecycle(self):
        template = self.ok("post", "/api/communication-templates", json={"name": "Email draft", "channel": "Email", "content": "Hello"})
        edited = self.ok("put", f"/api/communication-templates/{template['id']}", json={"content": "Updated wording"})
        self.assertEqual(edited["content"], "Updated wording")
        wa = self.ok("post", "/api/whatsapp-templates", json={"name": "Blueprint reminder", "body": "Hello {{name}}", "submit": False})
        self.assertIn(wa["id"], {t["id"] for t in self.ok("get", "/api/whatsapp-templates")})
        self.assertEqual(self.client.post(f"/api/whatsapp-templates/{wa['id']}/submit").status_code, 422)
        self.assertEqual(self.client.post("/api/whatsapp-templates/sync").status_code, 422)
        self.ok("delete", f"/api/whatsapp-templates/{wa['id']}")

    @criterion("M20.1")
    def test_record_message_options_and_unconfigured_send(self):
        lead = self.lead()
        self.ok("get", f"/api/leads/{lead['id']}/message-options")
        sent = self.ok("post", f"/api/leads/{lead['id']}/message", json={"channel": "Email", "content": "Synthetic note"})
        self.assertNotIn(sent["status"], {"Sent", "Delivered"})
        self.assertEqual(self.client.post(f"/api/leads/{lead['id']}/message", json={"channel": "SMS", "content": "Not allowed"}).status_code, 422)

    @criterion("M03.1")
    def test_source_update_sample_disconnect_and_invalid_oauth(self):
        channel = self.ok("post", "/api/channels", json={"name": "Source", "provider": "custom"})
        self.ok("put", f"/api/channels/{channel['id']}", json={"name": "Renamed Source"})
        self.ok("get", f"/api/channels/{channel['id']}/sample-payload")
        self.assertTrue(self.ok("get", "/api/channels"))
        self.assertEqual(self.client.get(f"/api/channels/{channel['id']}/oauth/start").status_code, 422)
        self.assertIn(self.client.get("/api/integrations/oauth/callback?state=bad&code=bad").status_code, {400, 403, 422})
        self.ok("delete", f"/api/channels/{channel['id']}")

    @criterion("M16.2")
    def test_quote_edit_uses_same_validity_field(self):
        quote = self.quote()
        changed = self.ok("put", f"/api/quotations/{quote['id']}", json={"validityDate": "2027-02-01", "premium": 1200})
        self.assertEqual(changed["validityDate"], "2027-02-01")
        self.assertTrue(changed["versions"])
        self.assertEqual(self.ok("get", "/api/quotations")[0]["premium"], 1200)

    @criterion("M15.1")
    def test_explicit_note_delete_and_list(self):
        note = self.ok("post", "/api/notes", json={"title": "Transient note", "content": "Synthetic"})
        self.assertEqual(len(self.ok("get", "/api/notes")), 1)
        self.ok("delete", f"/api/notes/{note['id']}")
        self.assertFalse(self.ok("get", "/api/notes"))


class BlueprintIdentityAcceptance(unittest.TestCase):
    setUp = test_security_foundation.SecurityFoundationTests.setUp
    tearDown = test_security_foundation.SecurityFoundationTests.tearDown

    def accounts(self):
        setup = self.client.post("/api/auth/bootstrap", json={"companyName": "Blueprint Auth", "name": "Real Administrator",
            "email": "admin@blueprint.invalid", "password": "StrongPassword!42"})
        self.assertEqual(setup.status_code, 200)
        headers = {"X-CSRF-Token": self.client.cookies.get(crm_security.CSRF_COOKIE)}
        created = self.client.post("/api/users", headers=headers, json={"name": "Actual Broker", "email": "broker@blueprint.invalid",
            "role": "Broker", "temporaryPassword": "BrokerPassword!42"})
        self.assertEqual(created.status_code, 200)
        from fastapi.testclient import TestClient
        broker = TestClient(server.app)
        self.assertEqual(broker.post("/api/auth/login", json={"email": "broker@blueprint.invalid", "password": "BrokerPassword!42"}).status_code, 200)
        return broker, headers

    @criterion("M02.2")
    def test_profile_is_signed_in_identity(self):
        broker, _ = self.accounts()
        profile = broker.get("/api/profile").json()
        self.assertEqual(profile.get("email"), "broker@blueprint.invalid", "Profile endpoint returned another company team member")

    @criterion("M27.3")
    def test_broker_cannot_switch_edit_another_profile(self):
        broker, _ = self.accounts()
        headers = {"X-CSRF-Token": broker.cookies.get(crm_security.CSRF_COOKIE)}
        users = self.client.get("/api/users").json()
        other = next(u for u in users if u.get("email") != "broker@blueprint.invalid")
        switched = broker.put("/api/profile", headers=headers, json={"currentUserId": other["id"]})
        if switched.status_code in {403, 422}:
            return
        changed = broker.put("/api/profile", headers=headers, json={"name": "Unauthorized Rename"})
        self.assertIn(changed.status_code, {403, 422}, "Broker can switch shared profile and rename another team member")

    @criterion("M15.3")
    def test_note_author_cannot_be_impersonated(self):
        broker, _ = self.accounts()
        note = broker.post("/api/notes", headers={"X-CSRF-Token": broker.cookies.get(crm_security.CSRF_COOKIE)},
            json={"title": "Meeting", "content": "Synthetic note", "author": "Someone Else"})
        self.assertEqual(note.status_code, 200)
        self.assertEqual(note.json()["author"], "Actual Broker", "Note author trusts submitted label instead of session actor")

    @criterion("M23.2", complete=True)
    def test_private_saved_view_is_not_visible_or_deletable_by_peer(self):
        broker, admin_headers = self.accounts()
        created = self.client.post("/api/saved-filters", headers=admin_headers,
            json={"name": "Admin Private", "module": "leads", "criteria": {"status": "New"}})
        self.assertEqual(created.status_code, 200)
        saved_id = created.json()["id"]
        self.assertFalse(any(f["id"] == saved_id for f in broker.get("/api/saved-filters").json()))
        response = broker.delete(f"/api/saved-filters/{saved_id}", headers={"X-CSRF-Token": broker.cookies.get(crm_security.CSRF_COOKIE)})
        self.assertEqual(response.status_code, 403)

    @criterion("M27.3")
    def test_broker_cannot_bypass_import_permission_on_legacy_endpoint(self):
        broker, _ = self.accounts()
        response = broker.post("/api/leads/import", headers={"X-CSRF-Token": broker.cookies.get(crm_security.CSRF_COOKIE)},
            json={"leads": [{"name": "Legacy import probe", "mobile": "9999111222"}]})
        self.assertEqual(response.status_code, 403, "Broker bypassed manager-only import via legacy endpoint")

    @criterion("M02.1")
    def test_logout_clears_current_browser_access(self):
        broker, _ = self.accounts()
        self.assertEqual(broker.get("/api/auth/me").status_code, 200)
        response = broker.post("/api/auth/logout", headers={"X-CSRF-Token": broker.cookies.get(crm_security.CSRF_COOKIE)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(broker.get("/api/leads").status_code, 401)


class BlueprintExternalAcceptance(unittest.TestCase):
    @criterion("M03.3")
    def test_real_lead_source_oauth_lifecycle(self):
        self.skipTest("No authorized provider sandbox/asset and callback subscription supplied for this audit")

    @criterion("M20.3")
    def test_real_email_whatsapp_delivery_and_reply(self):
        self.skipTest("No authorized sandbox recipient/provider environment; no external messages sent")

    @criterion("M22.3")
    def test_deployed_private_storage_scan_and_restore(self):
        self.skipTest("Requires disposable production-equivalent object storage and malware scanner")

    @criterion("M28.2")
    def test_postgres_migration_and_combined_recovery(self):
        self.skipTest("Requires designated disposable PostgreSQL/object-store environment and measured restore drill")


def _read_contract(endpoint, criteria_ids):
    @criterion(*criteria_ids)
    def test(self):
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200, endpoint)
        if endpoint != "/":
            self.assertIsInstance(response.json(), (dict, list))
    return test


for _endpoint, _criteria in {
    "/": ("M01.1",), "/api/entities": ("M23.1",), "/api/auth/status": ("M02.1",),
    "/api/admin/integrity": ("M27.1",), "/api/admin/jobs": ("M14.3",),
    "/api/archived-leads": ("M26.2",), "/api/renewals": ("M18.1",),
    "/api/renewals/report": ("M24.3",), "/api/consents": ("M21.2",),
    "/api/imports": ("M04.1",), "/api/demo-data": ("M26.2",),
    "/api/users/hierarchy": ("M02.3",),
}.items():
    setattr(BlueprintAcceptance, "test_read_contract_" + _endpoint.strip("/").replace("/", "_").replace("-", "_"), _read_contract(_endpoint, _criteria))
