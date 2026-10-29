"""Customize with AI (crm_builder.py, crm_routes/builder.py; plan phase 3).

Change sets are written by hand here, or by a stand-in for the model: what is under test is
the catalogue, the checks, the preview, apply and undo — the part that decides what can change.
"""
import json

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_ai
import crm_builder
from test_ai_advisor import FREE_MODEL, FakeProvider, ai_env
from test_client_blueprint import ClientBlueprintCase

BIKE = [
    {"op": "add_product", "params": {"name": "Bike Insurance"}},
    {"op": "add_field", "params": {"object": "lead", "label": "Engine CC", "type": "number", "section": "Bike details",
                                   "products": ["Bike Insurance"]}},
    {"op": "add_stage", "params": {"name": "Inspection", "category": "working", "after": "Interested"}},
    {"op": "add_automation", "params": {
        "name": "Big bikes are hot", "trigger": {"type": "lead.created"},
        "conditions": [{"field": "custom.engine_cc", "operator": "greater_than", "value": "500"}],
        "actions": [{"type": "set_priority", "params": {"priority": "HOT"}}]}},
]


class BuilderCase(ClientBlueprintCase):
    def setUp(self):
        super().setUp()
        crm_ai.reset_for_tests()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Meena Rao", "manager")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.manager = self.sign_in("meena.rao@blueprint.invalid")

    def propose(self, operations, status=200):
        res = self.call(self.owner, "POST", "/api/builder/changesets", json={"operations": operations})
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def act(self, change_set, action, status=200):
        res = self.call(self.owner, "POST", f"/api/builder/changesets/{change_set['id']}/{action}")
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def fields(self):
        return [f["key"] for f in self.call(self.owner, "GET", "/api/schema").json()["objects"]["lead"]]

    def stages(self):
        return [s["name"] for s in self.call(self.owner, "GET", "/api/pipeline").json()["stages"]]

    def products(self):
        return self.call(self.owner, "GET", "/api/lead-options").json()["products"]

    def rules(self):
        return self.call(self.owner, "GET", "/api/automations").json()["rules"]


class ChangeSets(BuilderCase):
    def test_a_change_set_is_previewed_then_applied_then_undone(self):
        proposal = self.propose(BIKE)
        self.assertTrue(proposal["ready"])
        self.assertEqual([r["ok"] for r in proposal["results"]], [True] * 4)
        self.assertIn("Engine CC", proposal["results"][1]["description"])
        self.assertIn("switched off", proposal["results"][3]["description"])
        self.assertEqual((self.fields(), len(self.stages())), ([], 13))          # nothing changes before applying

        self.act(proposal, "apply")
        self.assertEqual(self.fields(), ["engine_cc"])
        self.assertEqual(self.stages()[self.stages().index("Interested") + 1], "Inspection")
        self.assertIn("Bike Insurance", self.products())
        rule = self.rules()[0]
        self.assertEqual((rule["name"], rule["enabled"]), ("Big bikes are hot", False))

        self.act(proposal, "undo")
        self.assertEqual((self.fields(), len(self.stages()), self.rules()), ([], 13, []))
        self.assertNotIn("Bike Insurance", self.products())

    def test_each_operation_is_checked_and_explained(self):
        proposal = self.propose([
            {"op": "add_field", "params": {"object": "lead", "label": "Mobile", "key": "mobile", "type": "phone"}},
            {"op": "delete_field", "params": {"object": "lead", "key": "x"}},
            {"op": "add_stage", "params": {"name": "Big Win", "category": "won"}},
            {"op": "add_product", "params": {"name": "Car Insurance"}},
        ])
        self.assertFalse(proposal["ready"])
        errors = [r.get("error", "") for r in proposal["results"]]
        self.assertIn("built-in", errors[0])
        self.assertIn("not something the builder can do", errors[1])
        self.assertIn("without a sale", errors[2])
        self.assertIn("already a product", errors[3])
        self.act(proposal, "apply", status=409)

    def test_it_can_adjust_but_never_destroy(self):
        self.act(self.propose([{"op": "add_field", "params": {"object": "lead", "label": "Fuel", "type": "choice",
                                                               "options": ["Petrol", "EV"]}}]), "apply")
        refused = self.propose([{"op": "change_field", "params": {"object": "lead", "key": "fuel", "changes": {"type": "text"}}},
                                {"op": "change_field", "params": {"object": "lead", "key": "fuel", "changes": {"options": ["EV"]}}}])
        self.assertTrue(all("change" in r["error"] and "in Settings" in r["error"] for r in refused["results"]))
        allowed = self.propose([{"op": "add_choice", "params": {"object": "lead", "key": "fuel", "options": ["CNG"]}},
                                {"op": "change_field", "params": {"object": "lead", "key": "fuel", "changes": {"required": True}}}])
        self.assertTrue(allowed["ready"], allowed["results"])
        self.act(allowed, "apply")
        fuel = self.call(self.owner, "GET", "/api/schema").json()["objects"]["lead"][0]
        self.assertEqual((fuel["options"], fuel["required"]), (["Petrol", "EV", "CNG"], True))

    def test_later_operations_see_earlier_ones(self):
        proposal = self.propose([{"op": "add_automation", "params": {
            "name": "Needs field", "trigger": {"type": "lead.created"},
            "conditions": [{"field": "custom.engine_cc", "operator": "greater_than", "value": "500"}],
            "actions": [{"type": "set_priority", "params": {"priority": "HOT"}}]}}])
        self.assertIn("can't be checked", proposal["results"][0]["error"])
        self.assertTrue(self.propose(BIKE)["ready"])                         # field added first, then tested

    def test_apply_rechecks_against_the_crm_as_it_is_now(self):
        proposal = self.propose([BIKE[1]])
        self.call(self.owner, "POST", "/api/schema/fields/lead", json={"key": "engine_cc", "label": "Engine CC", "type": "number"})
        self.assertIn("no longer applies", self.act(proposal, "apply", status=409)["detail"])

    def test_only_the_owner_customizes(self):
        for client in (self.priya, self.manager):
            self.assertEqual(self.call(client, "GET", "/api/builder").status_code, 403)
            self.assertEqual(self.call(client, "POST", "/api/builder/changesets", json={"operations": BIKE}).status_code, 403)


class Undo(BuilderCase):
    def test_undo_is_refused_once_leads_use_what_it_added(self):
        applied = self.act(self.propose(BIKE), "apply")
        self.call(self.owner, "POST", "/api/leads", json={"firstName": "Rider", "mobile": "+91 90000 10101",
                                                          "product": "Bike Insurance", "custom": {"engine_cc": 650}})
        res = self.act(applied, "undo", status=409)
        self.assertIn("1 lead have values in Engine CC", res["detail"])
        self.assertIn("Hide", res["detail"])

    def test_undo_is_refused_after_other_changes(self):
        applied = self.act(self.propose([BIKE[0]]), "apply")
        self.call(self.owner, "POST", "/api/schema/fields/lead", json={"key": "chassis", "label": "Chassis", "type": "text"})
        self.assertIn("changed since", self.act(applied, "undo", status=409)["detail"])

    def test_only_the_latest_change_set_is_undone(self):
        first = self.act(self.propose([BIKE[0]]), "apply")
        second = self.act(self.propose([{"op": "add_lead_source", "params": {"name": "Dealer referral"}}]), "apply")
        self.assertIn("most recent", self.act(first, "undo", status=409)["detail"])
        self.act(second, "undo")
        self.act(first, "undo")
        self.assertNotIn("Bike Insurance", self.products())


class WithTheModel(BuilderCase):
    def test_without_a_model_the_owner_is_pointed_to_settings(self):
        with ai_env():
            res = self.call(self.owner, "POST", "/api/builder/propose", json={"request": "Add bike insurance"})
        self.assertEqual(res.status_code, 503)
        self.assertIn("under Settings", res.json()["detail"])

    def test_the_model_proposes_and_sees_no_customer(self):
        self.call(self.owner, "POST", "/api/leads", json={"firstName": "Secret", "lastName": "Customer", "mobile": "+91 90000 20202"})
        reply = json.dumps({"summary": "Adds bike insurance with an engine size field.", "operations": BIKE[:2],
                            "questions": []})
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(content=f"Here you go:\n```json\n{reply}\n```") as provider:
            res = self.call(self.owner, "POST", "/api/builder/propose", json={"request": "Add bike insurance, with engine CC"})
        self.assertEqual(res.status_code, 200, res.text)
        proposal = res.json()
        self.assertEqual((proposal["source"], proposal["ready"], proposal["summary"]),
                         ("ai", True, "Adds bike insurance with an engine size field."))
        sent = json.dumps(provider.requests[0]["body"]["messages"])
        self.assertNotIn("Secret", sent)
        self.assertIn("add_field", sent)
        self.assertEqual(self.fields(), [])                                   # proposed, not applied

    def test_a_model_overstepping_the_catalogue_is_stopped(self):
        reply = json.dumps({"summary": "x", "operations": [{"op": "run_sql", "params": {"sql": "DROP TABLE leads"}}]})
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(content=reply):
            proposal = self.call(self.owner, "POST", "/api/builder/propose", json={"request": "anything"}).json()
        self.assertFalse(proposal["ready"])
        self.assertIn("not something the builder can do", proposal["results"][0]["error"])

    def test_a_question_back_is_kept_with_no_operations(self):
        reply = json.dumps({"summary": "", "operations": [], "questions": ["Which products should the field apply to?"]})
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(content=reply):
            proposal = self.call(self.owner, "POST", "/api/builder/propose", json={"request": "add a field"}).json()
        self.assertEqual((proposal["questions"], proposal["ready"]), (["Which products should the field apply to?"], False))

    def test_unreadable_model_output_is_reported(self):
        with ai_env(OPENROUTER_API_KEY="k", AI_MODEL=FREE_MODEL), FakeProvider(content="I think you should add a field."):
            res = self.call(self.owner, "POST", "/api/builder/propose", json={"request": "add a field"})
        self.assertEqual(res.status_code, 502)
        self.assertIn("wasn't a change set", res.json()["detail"])


class Evaluations(BuilderCase):
    """The evaluation set's expected change sets must stay valid as the catalogue changes."""

    def test_every_expected_change_set_is_valid_on_a_new_company(self):
        with open("tests/builder_evals.json", encoding="utf-8") as handle:
            cases = json.load(handle)
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case["request"]):
                proposal = self.propose(case["expected"]) if case["expected"] else None
                if proposal:
                    self.assertTrue(proposal["ready"], proposal["results"])
                for op in case.get("mustNotUse", []):
                    self.assertNotIn(op, crm_builder.OPERATIONS)
