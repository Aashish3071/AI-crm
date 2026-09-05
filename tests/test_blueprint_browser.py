"""Authenticated navigation breadth, separate from complete feature acceptance."""
import unittest
from playwright.sync_api import expect
import tests.test_browser_flows as flows
from tests.test_blueprint_acceptance import criterion


class BlueprintBrowserAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        flows.CommercialCrmBrowserFlows.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        flows.CommercialCrmBrowserFlows.tearDownClass.__func__(cls)

    setUp = flows.CommercialCrmBrowserFlows.setUp
    tearDown = flows.CommercialCrmBrowserFlows.tearDown

    @criterion("M28.3")
    def test_every_main_navigation_module_loads(self):
        errors, requests = [], []
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        self.page.on("response", lambda response: requests.append(f"{response.status} {response.url}")
                     if "/api/" in response.url and response.status >= 400 else None)
        self.page.goto(self.base_url, wait_until="networkidle")
        selectors = self.page.locator("#app-sidebar .nav-btn[data-view]").evaluate_all(
            "buttons => buttons.map(button => button.getAttribute('data-view'))")
        self.assertGreaterEqual(len(selectors), 12)
        for view in selectors:
            with self.subTest(module=view):
                self.page.locator(f'#app-sidebar [data-view="{view}"]').click()
                self.page.wait_for_load_state("networkidle")
                self.assertEqual(self.page.evaluate("currentView"), view)
                self.assertFalse(errors, f"JavaScript failures while opening {view}: {errors}")
                self.assertFalse(requests, f"API failures while opening {view}: {requests}")

    @criterion("M12.3", complete=True)
    def test_customer_task_navigates_to_customer(self):
        self.page.goto(self.base_url, wait_until="networkidle")
        # Seed synthetic work through the same authenticated API used by the UI.
        ids = self.page.evaluate("""async () => {
            const customer = await apiJson('/api/customers', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({name:'Task Navigation Customer'})});
            const task = await apiJson('/api/tasks', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({title:'Review navigation customer', associatedType:'Customer', associatedId:customer.id, dueDate:'2026-10-10'})});
            return {customer:customer.id, task:task.id};
        }""")
        self.assertTrue(ids["task"])
        self.page.locator('#app-sidebar [data-view="tasks"]').click()
        self.page.get_by_role("button", name="Task Navigation Customer", exact=False).click()
        expect(self.page.locator("#customer-360").get_by_role("heading", name="Task Navigation Customer", exact=True)).to_be_visible()
