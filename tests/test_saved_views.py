"""Shared saved lead views (docs/AI_CUSTOMIZATION_PLAN.md, phase 2).

An Owner / Admin or Manager can share a saved view with whole roles. It is only a filter:
whoever applies it still sees just the records their role and team allow.
"""
import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
from test_client_blueprint import ClientBlueprintCase

VIEW = {"name": "Big bikes", "module": "leads",
        "criteria": {"customField": "engine_cc", "customOp": "greater_than", "customValue": "500"}}


class SharedViews(ClientBlueprintCase):
    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Meena Rao", "manager")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.manager = self.sign_in("meena.rao@blueprint.invalid")

    def views(self, client):
        return {v["name"]: v for v in self.call(client, "GET", "/api/saved-filters", params={"module": "leads"}).json()}

    def test_owner_shares_a_view_with_telecallers(self):
        made = self.call(self.owner, "POST", "/api/saved-filters", json={**VIEW, "sharedWith": ["telecaller"]})
        self.assertEqual(made.status_code, 200, made.text)
        self.assertEqual(made.json()["sharedWith"], ["telecaller"])
        self.assertEqual(self.views(self.priya)["Big bikes"]["ownedByMe"], False)
        self.assertEqual(self.views(self.priya)["Big bikes"]["criteria"]["customField"], "engine_cc")
        self.assertNotIn("Big bikes", self.views(self.manager))
        self.assertTrue(self.views(self.owner)["Big bikes"]["ownedByMe"])

    def test_only_its_owner_deletes_a_shared_view(self):
        view = self.call(self.owner, "POST", "/api/saved-filters", json={**VIEW, "sharedWith": ["telecaller"]}).json()
        self.assertEqual(self.call(self.priya, "DELETE", f"/api/saved-filters/{view['id']}").status_code, 403)
        self.assertEqual(self.call(self.owner, "DELETE", f"/api/saved-filters/{view['id']}").status_code, 200)
        self.assertNotIn("Big bikes", self.views(self.priya))

    def test_telecallers_keep_their_views_to_themselves(self):
        res = self.call(self.priya, "POST", "/api/saved-filters", json={**VIEW, "sharedWith": ["telecaller"]})
        self.assertEqual(res.status_code, 403)
        self.call(self.priya, "POST", "/api/saved-filters", json={**VIEW, "name": "Mine"})
        self.assertNotIn("Mine", self.views(self.owner))

    def test_a_manager_shares_and_roles_are_checked(self):
        self.assertEqual(self.call(self.manager, "POST", "/api/saved-filters",
                                   json={**VIEW, "sharedWith": ["telecaller"]}).status_code, 200)
        self.assertEqual(self.call(self.owner, "POST", "/api/saved-filters",
                                   json={**VIEW, "sharedWith": ["everyone"]}).status_code, 422)
