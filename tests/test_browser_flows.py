"""Repeatable browser acceptance checks for the commercial CRM.

The suite starts an isolated JSON-backed preview unless CRM_E2E_BASE_URL points to
an already running disposable environment. It never touches crm_db.json.
"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen
from datetime import date, timedelta

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]


class CommercialCrmBrowserFlows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = None
        cls.server = None
        cls.base_url = os.environ.get("CRM_E2E_BASE_URL", "").rstrip("/")
        if not cls.base_url:
            cls.temporary = tempfile.TemporaryDirectory()
            with socket.socket() as candidate:
                candidate.bind(("127.0.0.1", 0))
                port = candidate.getsockname()[1]
            cls.base_url = f"http://127.0.0.1:{port}"
            environment = os.environ.copy()
            environment.update({
                "AUTH_DISABLED": "0",
                "APP_ENV": "development",
                "DATABASE_URL": "",
                "CRM_DB_FILE": str(Path(cls.temporary.name) / "crm.json"),
                "IDENTITY_STORE_PATH": str(Path(cls.temporary.name) / "identities.json"),
                "DOCUMENT_ROOT": str(Path(cls.temporary.name) / "documents"),
                "BACKUP_ROOT": str(Path(cls.temporary.name) / "backups"),
                "TENANT_ROOT": str(Path(cls.temporary.name) / "tenants"),
                "ENABLE_REMINDER_SCHEDULER": "0",
            })
            cls.server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "pipecat_server:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=ROOT, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if cls.server.poll() is not None:
                    raise RuntimeError("The isolated CRM browser-test server did not start")
                try:
                    with urlopen(f"{cls.base_url}/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.15)
            else:
                raise RuntimeError("Timed out waiting for the isolated CRM browser-test server")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)
        cls.auth_state = None
        if cls.temporary:
            setup = cls.playwright.request.new_context(base_url=cls.base_url)
            response = setup.post("/api/auth/bootstrap", data={"companyName": "Browser Test Broker",
                "name": "Browser Administrator", "email": "browser@test.invalid", "password": "BrowserTestPassword!42"})
            if not response.ok:
                raise RuntimeError("Could not bootstrap isolated authenticated browser workspace")
            cls.auth_state = setup.storage_state()
            setup.dispose()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "browser", None):
            cls.browser.close()
        if getattr(cls, "playwright", None):
            cls.playwright.stop()
        if cls.server:
            cls.server.terminate()
            try:
                cls.server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.server.kill()
        if cls.temporary:
            cls.temporary.cleanup()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1440, "height": 900}, storage_state=self.auth_state)
        self.page.add_init_script("localStorage.setItem('insurecrm_onboarding_dismissed', 'true')")

    def tearDown(self):
        self.page.close()

    def test_dashboard_lead_conversion_and_customer_360(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Car & Health Insurance")).to_be_visible()

        sidebar = page.locator("#app-sidebar")
        sidebar.get_by_role("button", name="Leads", exact=True).click()
        page.get_by_role("button", name="New Lead", exact=True).click()
        lead_dialog = page.get_by_role("dialog", name="Create lead")
        expect(lead_dialog).to_be_visible()

        name = "Browser Acceptance Client"
        page.locator("#lead-name").fill(name)
        page.locator("#lead-product").select_option("Car Insurance")
        page.locator("#lead-mobile").fill("+91 98765 40001")
        page.locator("#lead-email").fill("browser-acceptance@example.invalid")
        page.locator("#lead-premium").fill("125000")
        page.locator("#lead-expiry").fill("2027-09-30")
        page.locator("#lead-next-action").fill("Schedule risk discovery meeting")
        page.locator("#lead-next-action-date").fill("2026-09-10")
        lead_dialog.get_by_role("button", name="Save lead").click()

        row = page.locator("#leads-table-body tr").filter(has_text=name)
        expect(row).to_have_count(1)
        row.get_by_title("View Account 360°").click()
        drawer = page.get_by_role("dialog", name=name)
        expect(drawer).to_be_visible()
        expect(drawer.get_by_text("Schedule risk discovery meeting", exact=True)).to_be_visible()
        drawer.get_by_role("button", name="Close account details").click()

        row.get_by_title("Click to transition stage").click()
        stage = page.locator("#stage-transition-modal")
        stage.locator("#stage-modal-new-stage").select_option("Contacted")
        stage.locator("#stage-modal-action-date").fill("2026-10-10")
        stage.get_by_role("button", name="Save status", exact=True).click()
        expect(stage).to_be_hidden()
        expect(row.get_by_title("Click to transition stage")).to_have_text("Contacted")

        row.get_by_title("Convert to policy").click()
        conversion = page.locator("#insurance-form-modal")
        expect(conversion.get_by_text("Convert lead — confirm customer and draft policy", exact=True)).to_be_visible()
        conversion.locator("[name=insurer]").fill("Acceptance General Insurance")
        conversion.locator("[name=startDate]").fill("2026-10-01")
        conversion.get_by_role("button", name="Save", exact=True).click()
        expect(conversion).to_be_hidden()

        sidebar.get_by_role("button", name="Customers", exact=True).click()
        customer_row = page.locator("#customers-table-body tr").filter(has_text=name)
        expect(customer_row).to_have_count(1)
        customer_row.get_by_role("button", name="360°", exact=True).click()
        customer_view = page.locator("#customer-360")
        expect(customer_view.get_by_role("heading", name=name)).to_be_visible()
        for block in ("Basic details", "Insurance history", "Call history", "Quotations",      # slide 18's eight blocks
                      "Documents", "Policies", "Follow-ups", "Notes"):
            expect(customer_view.locator("h3", has_text=block).first).to_be_visible()

    def test_mobile_navigation_and_lead_dialog_remain_usable(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        page.locator("#app-sidebar").get_by_role("button", name="Leads", exact=True).click()
        page.get_by_role("button", name="New Lead", exact=True).click()
        dialog = page.get_by_role("dialog", name="Create lead")
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role("button", name="Save lead")).to_be_visible()
        expect(dialog.get_by_role("button", name="Close lead form")).to_be_visible()
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), 392)

    def test_calendar_books_linked_meeting_and_follow_up(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        page.locator("#app-sidebar").get_by_role("button", name="Calendar", exact=True).click()
        expect(page.get_by_role("heading", name="Calendar", exact=True)).to_be_visible()
        page.get_by_role("button", name="Book meeting", exact=True).click()
        dialog = page.locator("#insurance-form-modal")
        expect(dialog.get_by_text("Book a meeting", exact=True)).to_be_visible()
        meeting_day = date.today().isoformat()
        follow_up_day = (date.today() + timedelta(days=1)).isoformat()
        dialog.locator("[name=title]").fill("Browser renewal discussion")
        dialog.locator("[name=date]").fill(meeting_day)
        dialog.locator("[name=time]").fill("23:00")
        dialog.locator("[name=associatedId]").select_option(index=1)
        dialog.locator("[name=notes]").fill("Confirm the coverage schedule and decision makers")
        dialog.locator("[name=followUpAction]").fill("Send agreed quotation shortlist")
        dialog.locator("[name=followUpDate]").fill(follow_up_day)
        dialog.get_by_role("button", name="Save", exact=True).click()
        expect(dialog).to_be_hidden()
        expect(page.get_by_text("Browser renewal discussion", exact=True).first).to_be_visible()
        page.evaluate("date => selectCalendarDate(date)", meeting_day)
        expect(page.get_by_role("button", name="Complete", exact=True)).to_be_visible()

    def test_rejected_task_save_keeps_form_and_shows_error(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        page.locator("#app-sidebar").get_by_role("button", name="Follow-ups", exact=True).click()
        page.get_by_role("button", name="Schedule follow-up", exact=True).click()
        dialog = page.get_by_role("dialog", name="Add action task")
        dialog.locator("#task-modal-title").fill("Must not pretend to save")
        dialog.locator("#task-modal-date").fill("2026-10-10")
        dialog.locator("#task-modal-entity").select_option(index=1)
        page.route("**/api/tasks", lambda route: route.fulfill(status=409, content_type="application/json",
            body='{"detail":"This work changed. Reload and retry."}') if route.request.method == "POST" else route.continue_())
        dialog.get_by_role("button", name="Schedule Task", exact=True).click()
        expect(dialog).to_be_visible()
        expect(page.get_by_text("This work changed. Reload and retry.", exact=True)).to_be_visible()

    def test_custom_fields_from_settings_to_the_lead_card(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        csrf = next(c["value"] for c in page.context.cookies() if c["name"] == "crm_csrf")
        for field in ({"key": "engine_cc", "label": "Engine CC", "type": "number", "section": "Bike details"},
                      {"key": "fuel", "label": "Fuel", "type": "choice", "options": ["Petrol", "EV"]}):
            response = page.request.post(f"{self.base_url}/api/schema/fields/lead", data=field, headers={"X-CSRF-Token": csrf})
            self.assertTrue(response.ok, response.text())

        # The owner adds a third field on the settings screen.
        page.locator('button[onclick="openSettingsModal()"]').click()
        page.locator('[data-setting-tab="fields"]').click()
        page.get_by_role("button", name="Add field", exact=True).click()
        page.locator("#cf-label").fill("Chassis number")
        expect(page.locator("#cf-key")).to_have_value("chassis_number")
        page.locator("#setting-pane-content").get_by_role("button", name="Add field", exact=True).click()
        expect(page.locator("#setting-pane-content").get_by_text("Chassis number", exact=True)).to_be_visible()
        page.locator("#settings-modal button", has_text="✕").first.click()

        page.reload(wait_until="networkidle")
        page.locator("#app-sidebar").get_by_role("button", name="Leads", exact=True).click()
        page.get_by_role("button", name="New Lead", exact=True).click()
        dialog = page.get_by_role("dialog", name="Create lead")
        expect(dialog.get_by_text("Bike details", exact=True)).to_be_visible()
        page.locator("#lead-name").fill("Custom Field Rider")
        page.locator("#lead-mobile").fill("+91 98765 40077")
        page.locator("#lead-product").select_option("Car Insurance")
        page.locator("#cf-engine_cc").fill("lots")
        dialog.get_by_role("button", name="Save lead").click()
        expect(page.get_by_text("Engine CC must be a number")).to_be_visible()
        page.locator("#cf-engine_cc").fill("650")
        page.locator("#cf-fuel").select_option("EV")
        page.locator("#cf-chassis_number").fill("MA3FJEB1S00999")
        dialog.get_by_role("button", name="Save lead").click()
        expect(dialog).to_be_hidden()

        row = page.locator("#leads-table-body tr").filter(has_text="Custom Field Rider")
        expect(row).to_have_count(1)
        page.locator("#leads-custom-field").select_option("engine_cc")
        page.locator("#leads-custom-op").select_option("greater_than")
        page.locator("#leads-custom-value").fill("700")
        page.locator("#leads-custom-value").dispatch_event("change")
        expect(row).to_have_count(0)
        page.locator("#leads-custom-value").fill("500")
        page.locator("#leads-custom-value").dispatch_event("change")
        expect(row).to_have_count(1)

        row.get_by_title("View Account 360°").click()
        values = page.get_by_role("dialog", name="Custom Field Rider").get_by_test_id("lead-custom-values")
        for text in ("Engine CC", "650", "EV", "MA3FJEB1S00999"):
            expect(values.get_by_text(text, exact=True)).to_be_visible()

    def test_customer_custom_field_on_the_form_and_customer_360(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        csrf = next(c["value"] for c in page.context.cookies() if c["name"] == "crm_csrf")
        response = page.request.post(f"{self.base_url}/api/schema/fields/customer", headers={"X-CSRF-Token": csrf},
                                     data={"key": "pan", "label": "PAN", "type": "text"})
        self.assertTrue(response.ok, response.text())
        page.reload(wait_until="networkidle")
        page.locator("#app-sidebar").get_by_role("button", name="Customers", exact=True).click()
        page.get_by_role("button", name="New customer", exact=True).click()
        form = page.locator("#insurance-dynamic-form")
        form.locator('[name="name"]').fill("Custom Field Customer")
        form.locator('[name="mobile"]').fill("+91 98765 40088")
        form.locator("#cf-pan").fill("ABCDE1234F")
        form.get_by_role("button", name="Save", exact=True).click()
        row = page.locator("tr").filter(has_text="Custom Field Customer")
        expect(row).to_have_count(1)
        row.get_by_role("button", name="360°", exact=True).click()
        profile = page.locator("#customer-360")
        expect(profile.get_by_text("PAN", exact=True)).to_be_visible()
        expect(profile.get_by_text("ABCDE1234F", exact=True)).to_be_visible()

    def test_lead_stages_added_and_relabelled_in_settings(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        page.locator('button[onclick="openSettingsModal()"]').click()
        page.locator('[data-setting-tab="stages"]').click()
        pane = page.locator("#setting-pane-content")
        pane.locator("#stage-new-name").fill("Site Inspection")
        pane.get_by_role("button", name="Add stage", exact=True).click()
        stage_names = pane.locator("span.font-semibold")
        expect(stage_names.filter(has_text="Site Inspection")).to_have_count(1)
        row = pane.locator("div.border").filter(has_text="Interested").filter(has_text="built in").first
        row.get_by_role("button", name="Label", exact=True).click()
        form = page.locator("#insurance-dynamic-form")
        form.locator('[name="label"]').fill("Hot")
        form.get_by_role("button", name="Save", exact=True).click()
        expect(stage_names.filter(has_text="Hot")).to_have_count(1)
        page.locator("#settings-modal button", has_text="✕").first.click()
        page.locator("#app-sidebar").get_by_role("button", name="Leads", exact=True).click()
        options = page.locator("#leads-status-filter option").all_inner_texts()
        self.assertIn("Hot", options)
        self.assertIn("Site Inspection", options)
        self.assertNotIn("Interested", options)

    def test_customize_with_ai_previews_applies_and_undoes(self):
        page = self.page
        page.goto(f"{self.base_url}/", wait_until="networkidle")
        csrf = next(c["value"] for c in page.context.cookies() if c["name"] == "crm_csrf")
        made = page.request.post(f"{self.base_url}/api/builder/changesets", headers={"X-CSRF-Token": csrf}, data={
            "summary": "Track the referral partner", "operations": [
                {"op": "add_field", "params": {"object": "lead", "label": "Referral partner", "type": "text"}}]})
        self.assertTrue(made.ok, made.text())
        page.on("dialog", lambda dialog: dialog.accept())
        page.locator('button[onclick="openSettingsModal()"]').click()
        page.locator('[data-setting-tab="builder"]').click()
        pane = page.locator("#setting-pane-content")
        expect(pane.get_by_text("Every change can still be made under", exact=False)).to_be_visible()
        card = pane.get_by_test_id("change-set").filter(has_text="Track the referral partner")
        expect(card.get_by_text("Add a short text field “Referral partner” on leads", exact=True)).to_be_visible()
        card.get_by_role("button", name="Apply", exact=True).click()
        expect(card.get_by_text("Applied", exact=False)).to_be_visible()
        schema = page.request.get(f"{self.base_url}/api/schema").json()
        self.assertIn("referral_partner", [f["key"] for f in schema["objects"]["lead"]])
        card.get_by_role("button", name="Undo", exact=True).click()
        expect(card.get_by_text("Undone", exact=False)).to_be_visible()


if __name__ == "__main__":
    unittest.main()
