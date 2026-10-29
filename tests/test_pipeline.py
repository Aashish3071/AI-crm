"""Company lead stages (docs/AI_CUSTOMIZATION_PLAN.md, decision D2; crm_routes/pipeline.py).

A company adds its own stages beside the thirteen system ones. Each behaves like the system
stages of its category everywhere a workflow asks — next actions, reasons, closing work,
open-lead counts, the funnel — and system stages can be relabelled or hidden but never lose
their names. Every test signs in as a real user over HTTP.
"""
import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import pipecat_server as server
from test_client_blueprint import ClientBlueprintCase


class PipelineCase(ClientBlueprintCase):
    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Meena Rao", "manager")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.manager = self.sign_in("meena.rao@blueprint.invalid")

    def add_stage(self, name, category, status=200, client=None, **extra):
        res = self.call(client or self.owner, "POST", "/api/pipeline/stages", json={"name": name, "category": category, **extra})
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def change(self, stage, status=200, **changes):
        res = self.call(self.owner, "PUT", f"/api/pipeline/stages/{stage}", json=changes)
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def names(self):
        return [s["name"] for s in self.call(self.owner, "GET", "/api/pipeline").json()["stages"]]

    def new_lead(self, first="Stage Test"):
        return self.add_lead(self.owner, first, owner="Priya Sharma")

    def move(self, lead, status, **extra):
        return self.call(self.owner, "PUT", f"/api/leads/{lead['id']}/stage", json={"status": status, **extra})

    def get(self, lead):
        return self.call(self.owner, "GET", f"/api/leads/{lead['id']}").json()["lead"]


class Stages(PipelineCase):
    def test_the_default_is_the_thirteen_system_stages(self):
        stages = self.call(self.priya, "GET", "/api/pipeline").json()["stages"]
        self.assertEqual(len(stages), 13)
        self.assertTrue(all(s["system"] for s in stages))
        self.assertEqual(self.call(self.owner, "GET", "/api/lead-options").json()["statuses"][0], "New")

    def test_only_the_owner_changes_stages(self):
        self.add_stage("Site Inspection", "working", status=403, client=self.priya)
        self.add_stage("Site Inspection", "working", status=403, client=self.manager)
        res = self.call(self.manager, "PUT", "/api/pipeline/stages/Interested", json={"label": "Hot"})
        self.assertEqual(res.status_code, 403)

    def test_new_stages_land_among_their_kind(self):
        self.add_stage("Site Inspection", "working")
        self.add_stage("On Hold", "parked")
        self.add_stage("Bought Elsewhere", "lost")
        names = self.names()
        self.assertEqual(names.index("Site Inspection"), names.index("Unreachable") + 1)
        self.assertEqual(names.index("On Hold"), names.index("Wrong Number") + 1)
        self.assertEqual(names[-1], "Bought Elsewhere")
        self.add_stage("Survey", "working", after="Interested")
        self.assertEqual(self.names()[self.names().index("Interested") + 1], "Survey")
        options = self.call(self.owner, "GET", "/api/lead-options").json()
        self.assertIn("Site Inspection", options["statuses"])
        self.assertIn("On Hold", options["noNextAction"])
        self.assertIn("Bought Elsewhere", options["reasonRequired"])
        self.assertIn("Bought Elsewhere", options["closedStatuses"])

    def test_bad_stages_are_refused(self):
        for name, category, reason in (("Interested", "working", "already a stage"), ("won", "working", "already a stage"),
                                       ("Big Sale", "won", "finished without a sale"), ("", "working", "needs a name")):
            res = self.call(self.owner, "POST", "/api/pipeline/stages", json={"name": name, "category": category})
            self.assertEqual(res.status_code, 422, name)
            self.assertIn(reason, res.json()["detail"])

    def test_another_company_keeps_its_own_stages(self):
        self.add_stage("Site Inspection", "working")
        token = server.company_context.set("CO_another_company")
        try:
            server.load_db()
            self.assertNotIn("Site Inspection", list(server.LEAD_STATUSES))
            self.assertNotIn("Site Inspection", server.NO_NEXT_ACTION | server.CLOSED_STATUSES)
        finally:
            server.company_context.reset(token)
        self.assertIn("Site Inspection", self.call(self.owner, "GET", "/api/lead-options").json()["statuses"])

    def test_settings_cannot_overwrite_stages(self):
        res = self.call(self.owner, "PUT", "/api/settings", json={"crm": {"pipeline": [{"name": "New", "category": "working"}]}})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(len(self.names()), 13)


class Behaviour(PipelineCase):
    def test_a_worked_stage_needs_a_next_action(self):
        self.add_stage("Site Inspection", "working")
        lead = self.new_lead()
        self.assertEqual(self.move(lead, "Site Inspection").status_code, 422)
        res = self.move(lead, "Site Inspection", nextAction="Inspect the car", nextActionDate="2026-12-01")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.get(lead)["nextAction"], "Inspect the car")

    def test_a_parked_stage_takes_no_next_action_and_is_not_open_work(self):
        self.add_stage("On Hold", "parked")
        lead = self.new_lead()
        self.assertEqual(self.move(lead, "On Hold").status_code, 200)
        now = self.get(lead)
        self.assertEqual((now["status"], now["nextAction"]), ("On Hold", ""))
        users = {u["name"]: u for u in self.call(self.owner, "GET", "/api/users").json()}
        self.assertEqual(users["Priya Sharma"].get("openLeads", 0), 0)

    def test_a_lost_stage_needs_a_reason_and_closes_the_work(self):
        self.add_stage("Bought Elsewhere", "lost")
        lead = self.new_lead()
        self.assertEqual(self.move(lead, "Bought Elsewhere").status_code, 422)
        self.assertEqual(self.move(lead, "Bought Elsewhere", lostReason="Cheaper online").status_code, 200)
        tasks = [t for t in self.call(self.owner, "GET", "/api/tasks").json() if t.get("associatedId") == lead["id"]]
        self.assertTrue(tasks and all(t["status"] == "Completed" for t in tasks), tasks)
        report = self.call(self.owner, "GET", "/api/reports").json()
        self.assertIn("Cheaper online", {r["reason"] for r in report["lostReasons"]})

    def test_the_funnel_counts_a_company_stage_as_the_step_before_it(self):
        self.add_stage("Negotiating", "working", after="Quote Sent")
        lead = self.new_lead()
        self.move(lead, "Negotiating", nextAction="Call back", nextActionDate="2026-12-01")
        funnel = {s["stage"]: s["count"] for s in self.call(self.owner, "GET", "/api/reports").json()["funnel"]}
        self.assertEqual((funnel["Quote Sent"], funnel["Follow-up"]), (1, 0))

    def test_automations_can_watch_a_company_stage(self):
        self.add_stage("Site Inspection", "working")
        rule = self.call(self.owner, "POST", "/api/automations", json={
            "name": "Hot on inspection", "enabled": True,
            "trigger": {"type": "lead.status_changed", "params": {"to": "Site Inspection"}},
            "actions": [{"type": "set_priority", "params": {"priority": "HOT"}}]})
        self.assertEqual(rule.status_code, 200, rule.text)
        lead = self.new_lead()
        self.move(lead, "Site Inspection", nextAction="Inspect", nextActionDate="2026-12-01")
        self.assertEqual(self.get(lead)["leadPriority"], "HOT")


class Changes(PipelineCase):
    def test_system_stages_take_a_label_but_keep_their_name(self):
        self.change("Interested", label="Hot")
        options = self.call(self.owner, "GET", "/api/lead-options").json()
        self.assertEqual(options["stageLabels"], {"Interested": "Hot"})
        lead = self.new_lead()
        self.move(lead, "Interested", nextAction="Quote", nextActionDate="2026-12-01")
        self.assertEqual(self.get(lead)["status"], "Interested")
        self.assertIn("label instead", self.change("Interested", status=422, name="Hot lead")["detail"])
        self.assertIn("already a stage", self.change("Contacted", status=422, label="Hot")["detail"])

    def test_hidden_stages_leave_the_pickers_but_still_work(self):
        self.change("Documents Pending", hidden=True)
        options = self.call(self.owner, "GET", "/api/lead-options").json()
        self.assertNotIn("Documents Pending", options["pickableStatuses"])
        self.assertIn("Documents Pending", options["statuses"])
        lead = self.new_lead()
        self.assertEqual(self.move(lead, "Documents Pending", nextAction="Chase", nextActionDate="2026-12-01").status_code, 200)

    def test_renaming_carries_leads_and_rules_along(self):
        self.add_stage("Site Visit", "working")
        lead = self.new_lead()
        self.move(lead, "Site Visit", nextAction="Visit", nextActionDate="2026-12-01")
        self.call(self.owner, "POST", "/api/automations", json={
            "name": "Watch visits", "enabled": True, "trigger": {"type": "lead.status_changed", "params": {"to": "Site Visit"}},
            "actions": [{"type": "add_note", "params": {"text": "Visit booked"}}]})
        self.change("Site Visit", name="Site Inspection")
        self.assertEqual(self.get(lead)["status"], "Site Inspection")
        rules = self.call(self.owner, "GET", "/api/automations").json()["rules"]
        self.assertEqual(rules[0]["trigger"]["params"]["to"], "Site Inspection")

    def test_a_stage_in_use_keeps_its_meaning_and_place(self):
        self.add_stage("On Hold", "parked")
        lead = self.new_lead()
        self.move(lead, "On Hold")
        self.assertIn("1 lead is in On Hold", self.change("On Hold", status=409, category="working")["detail"])
        res = self.call(self.owner, "DELETE", "/api/pipeline/stages/On Hold")
        self.assertEqual(res.status_code, 409)
        self.assertIn("1 lead use On Hold", res.json()["detail"])
        self.move(lead, "Contacted", nextAction="Call", nextActionDate="2026-12-01")
        self.assertEqual(self.call(self.owner, "DELETE", "/api/pipeline/stages/On Hold").status_code, 200)
        self.assertNotIn("On Hold", self.names())
        self.assertEqual(self.call(self.owner, "DELETE", "/api/pipeline/stages/Lost").status_code, 422)

    def test_order_must_start_with_work(self):
        names = self.names()
        res = self.call(self.owner, "PUT", "/api/pipeline/order", json={"names": [names[-1]] + names[:-1]})
        self.assertEqual(res.status_code, 422)
        self.assertIn("first stage", res.json()["detail"])
        reordered = [names[0], names[2], names[1]] + names[3:]
        res = self.call(self.owner, "PUT", "/api/pipeline/order", json={"names": reordered})
        self.assertEqual([s["name"] for s in res.json()["stages"]], reordered)
        self.assertEqual(self.call(self.owner, "GET", "/api/lead-options").json()["statuses"], reordered)


if __name__ == "__main__":
    import unittest
    unittest.main()
