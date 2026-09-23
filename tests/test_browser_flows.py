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


if __name__ == "__main__":
    unittest.main()
