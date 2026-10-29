"""Custom fields on leads, end to end (docs/AI_CUSTOMIZATION_PLAN.md, phase 1).

An owner defines a field; it is checked on every path that writes a lead — the form, an
edit, a spreadsheet import — can be filtered on, tested by an automation rule, and comes
out in the export. Every test signs in as a real user over HTTP.
"""
import csv
import io
import zipfile

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
from test_client_blueprint import ClientBlueprintCase

ENGINE = {"key": "engine_cc", "label": "Engine CC", "type": "number", "min": 50, "section": "Bike details"}
FUEL = {"key": "fuel", "label": "Fuel", "type": "choice", "options": ["Petrol", "Diesel", "EV"]}


class CustomFieldCase(ClientBlueprintCase):
    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Meena Rao", "manager")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.manager = self.sign_in("meena.rao@blueprint.invalid")

    def define(self, field, client=None, status=200):
        res = self.call(client or self.owner, "POST", "/api/schema/fields/lead", json=field)
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def change(self, key, status=200, **changes):
        res = self.call(self.owner, "PUT", f"/api/schema/fields/lead/{key}", json=changes)
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def lead(self, first, custom=None, status=200, **extra):
        body = {"firstName": first, "mobile": f"+91 9{abs(hash(first)) % 10**9:09d}", "assignedTo": "Priya Sharma",
                **({"custom": custom} if custom is not None else {}), **extra}
        res = self.call(self.owner, "POST", "/api/leads", json=body)
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def edit(self, lead_id, custom, status=200):
        res = self.call(self.owner, "PUT", f"/api/leads/{lead_id}", json={"custom": custom})
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def get(self, lead_id):
        return self.call(self.owner, "GET", f"/api/leads/{lead_id}").json()["lead"]


class Definitions(CustomFieldCase):
    def test_owner_defines_everyone_reads(self):
        made = self.define(ENGINE)
        self.assertEqual((made["key"], made["type"], made["min"], made["createdBy"]), ("engine_cc", "number", 50, "Owner One"))
        for client in (self.owner, self.priya, self.manager):
            schema = self.call(client, "GET", "/api/schema").json()
            self.assertEqual([f["key"] for f in schema["objects"]["lead"]], ["engine_cc"])
            self.assertIn("multi_choice", {t["type"] for t in schema["fieldTypes"]})
        self.assertEqual(self.call(self.owner, "GET", "/api/schema").json()["version"], 1)

    def test_only_the_owner_changes_fields(self):
        self.define(ENGINE, client=self.priya, status=403)
        self.define(ENGINE, client=self.manager, status=403)
        self.define(ENGINE)
        res = self.call(self.manager, "PUT", "/api/schema/fields/lead/engine_cc", json={"label": "CC"})
        self.assertEqual(res.status_code, 403)

    def test_bad_definitions_are_refused_with_a_reason(self):
        self.define(ENGINE)
        for bad, reason in (({**ENGINE, "label": "Other"}, "already exists"),
                            ({"key": "mobile", "label": "Phone", "type": "phone"}, "built-in"),
                            ({"key": "x", "label": "X", "type": "formula"}, "not a field type"),
                            ({"key": "fuel", "label": "Fuel", "type": "choice"}, "at least one option")):
            res = self.call(self.owner, "POST", "/api/schema/fields/lead", json=bad)
            self.assertEqual(res.status_code, 422, bad)
            self.assertIn(reason, res.json()["detail"])

    def test_other_record_types_are_not_open_yet(self):
        res = self.call(self.owner, "POST", "/api/schema/fields/policy", json=ENGINE)
        self.assertEqual(res.status_code, 404)

    def test_settings_endpoint_cannot_overwrite_definitions(self):
        self.define(ENGINE)
        res = self.call(self.owner, "PUT", "/api/settings", json={"customFields": {"lead": []}})
        self.assertEqual(res.status_code, 422)
        self.assertEqual(len(self.call(self.owner, "GET", "/api/schema").json()["objects"]["lead"]), 1)

    def test_reorder(self):
        self.define(ENGINE)
        self.define(FUEL)
        res = self.call(self.owner, "PUT", "/api/schema/fields/lead/order", json={"keys": ["fuel", "engine_cc"]})
        self.assertEqual([f["key"] for f in res.json()], ["fuel", "engine_cc"])
        res = self.call(self.owner, "PUT", "/api/schema/fields/lead/order", json={"keys": ["fuel"]})
        self.assertEqual(res.status_code, 422)

    def test_changes_are_audited(self):
        self.define(ENGINE)
        self.change("engine_cc", label="Engine size (cc)")
        with self.company_db() as db:
            logged = [a for a in db["auditLogs"] if a.get("entity") == "Custom Field" or a.get("entityType") == "Custom Field"
                      or "Custom Field" in str(a.get("action"))]
        self.assertEqual(len(logged), 2)


class Values(CustomFieldCase):
    def setUp(self):
        super().setUp()
        self.define(ENGINE)
        self.define(FUEL)

    def test_values_are_checked_and_normalised(self):
        lead = self.lead("Arjun", custom={"engine_cc": "1,200", "fuel": "petrol"})
        self.assertEqual(lead["custom"], {"engine_cc": 1200, "fuel": "Petrol"})
        self.assertEqual(self.get(lead["id"])["custom"], {"engine_cc": 1200, "fuel": "Petrol"})

    def test_bad_values_name_the_field(self):
        res = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Bad", "mobile": "+91 90000 11111",
                                                                "custom": {"engine_cc": "big", "fuel": "Coal", "colour": "red"}})
        self.assertEqual(res.status_code, 422)
        detail = res.json()["detail"]
        for part in ("Engine CC must be a number", "'Coal' is not one of the choices", "'colour' is not a field"):
            self.assertIn(part, detail)
        self.assertIn("at least 50", self.call(self.owner, "POST", "/api/leads", json={
            "firstName": "Small", "mobile": "+91 90000 22222", "custom": {"engine_cc": 10}}).json()["detail"])

    def test_edits_merge_and_clear(self):
        lead = self.lead("Kiran", custom={"engine_cc": 150})
        self.assertEqual(self.edit(lead["id"], {"fuel": "EV"})["custom"], {"engine_cc": 150, "fuel": "EV"})
        self.assertEqual(self.edit(lead["id"], {"engine_cc": ""})["custom"], {"fuel": "EV"})
        self.edit(lead["id"], {"fuel": "Coal"}, status=422)
        self.assertEqual(self.get(lead["id"])["custom"], {"fuel": "EV"})

    def test_required_only_for_its_product(self):
        self.change("engine_cc", required=True, products=["Car Insurance"])
        res = self.call(self.owner, "POST", "/api/leads", json={"firstName": "Car", "mobile": "+91 90000 33333",
                                                                "product": "Car Insurance"})
        self.assertEqual(res.status_code, 422)
        self.assertIn("Engine CC is required", res.json()["detail"])
        self.lead("Health", product="Health Insurance")
        car = self.lead("Car2", product="Car Insurance", custom={"engine_cc": 1200})
        # An edit that doesn't touch the field doesn't trip over it.
        self.edit(car["id"], {"fuel": "Petrol"})

    def test_hidden_field_keeps_its_data_but_refuses_writes(self):
        lead = self.lead("Hidden", custom={"engine_cc": 150, "fuel": "EV"})
        self.change("fuel", hidden=True)
        self.assertEqual(self.get(lead["id"])["custom"]["fuel"], "EV")
        res = self.edit(lead["id"], {"fuel": "Petrol"}, status=422)
        self.assertIn("hidden", res["detail"])
        self.change("fuel", hidden=False)
        self.edit(lead["id"], {"fuel": "Petrol"})

    def test_a_telecaller_fills_fields_on_their_own_lead(self):
        res = self.call(self.priya, "POST", "/api/leads", json={"firstName": "Own", "mobile": "+91 90000 44444",
                                                                "custom": {"fuel": "Diesel"}})
        self.assertEqual(res.status_code, 200, res.text)
        res = self.call(self.priya, "PUT", f"/api/leads/{res.json()['id']}", json={"custom": {"engine_cc": 180}})
        self.assertEqual(res.json()["custom"], {"fuel": "Diesel", "engine_cc": 180})


class Changes(CustomFieldCase):
    def setUp(self):
        super().setUp()
        self.define(FUEL)

    def test_an_option_in_use_cannot_be_removed(self):
        self.lead("Diesel driver", custom={"fuel": "Diesel"})
        res = self.change("fuel", status=409, options=["Petrol", "EV"])
        self.assertIn("1 lead use Diesel", res["detail"])
        self.change("fuel", options=["Petrol", "Diesel", "EV", "CNG"])
        self.change("fuel", options=["Petrol", "Diesel", "EV"])         # CNG unused: fine

    def test_pick_one_becomes_pick_several_keeping_values(self):
        lead = self.lead("Hybrid", custom={"fuel": "Petrol"})
        self.change("fuel", type="multi_choice")
        self.assertEqual(self.get(lead["id"])["custom"]["fuel"], ["Petrol"])
        self.assertEqual(self.edit(lead["id"], {"fuel": "petrol, ev"})["custom"]["fuel"], ["Petrol", "EV"])

    def test_incompatible_type_change_is_refused(self):
        res = self.change("fuel", status=422, type="number")
        self.assertIn("add a new field", res["detail"])

    def test_long_text_that_would_not_fit_blocks_shortening(self):
        self.define({"key": "remarks", "label": "Remarks", "type": "long_text"})
        self.lead("Talkative", custom={"remarks": "x" * 600})
        res = self.change("remarks", status=409, type="text")
        self.assertIn("more than 500 characters", res["detail"])


class ListFilterAndSearch(CustomFieldCase):
    def setUp(self):
        super().setUp()
        self.define(ENGINE)
        self.define({"key": "chassis", "label": "Chassis number", "type": "text"})
        self.small = self.lead("Small bike", custom={"engine_cc": 110, "chassis": "MA3FJEB1S00123456"})
        self.big = self.lead("Big bike", custom={"engine_cc": 650})
        self.none = self.lead("No bike")

    def names(self, client=None, **params):
        res = self.call(client or self.owner, "GET", "/api/leads", params=params)
        self.assertEqual(res.status_code, 200, res.text)
        return {l["firstName"] for l in res.json()}

    def test_filter_compares_by_type(self):
        self.assertEqual(self.names(customField="engine_cc", customOp="greater_than", customValue="500"), {"Big"})
        self.assertEqual(self.names(customField="engine_cc", customOp="less_than", customValue="1,000"), {"Small", "Big"})
        self.assertEqual(self.names(customField="engine_cc", customOp="is_empty"), {"No"})

    def test_filter_mistakes_are_explained(self):
        for params, reason in (({"customField": "colour"}, "not a field"),
                               ({"customField": "engine_cc", "customOp": "contains", "customValue": "1"}, "can't be compared"),
                               ({"customField": "engine_cc", "customOp": "greater_than", "customValue": "lots"}, "must be a number")):
            res = self.call(self.owner, "GET", "/api/leads", params=params)
            self.assertEqual(res.status_code, 422, params)
            self.assertIn(reason, res.json()["detail"])

    def test_search_finds_custom_text(self):
        self.assertEqual(self.names(search="ma3fjeb1s"), {"Small"})

    def test_filter_stays_inside_the_callers_book(self):
        self.add_staff("Rohit Verma", "telecaller")
        self.lead("Rohit bike", custom={"engine_cc": 900}, assignedTo="Rohit Verma")
        self.assertEqual(self.names(self.priya, customField="engine_cc", customOp="greater_than", customValue="500"), {"Big"})


class Automation(CustomFieldCase):
    def setUp(self):
        super().setUp()
        self.define(ENGINE)
        self.define({**FUEL, "type": "multi_choice"})

    def rule(self, conditions, status=200):
        res = self.call(self.owner, "POST", "/api/automations", json={
            "name": "Big bikes are hot", "enabled": True, "trigger": {"type": "lead.created"},
            "conditions": conditions, "actions": [{"type": "set_priority", "params": {"priority": "HOT"}}]})
        self.assertEqual(res.status_code, status, res.text)
        return res.json()

    def test_custom_fields_are_offered_to_rules(self):
        fields = self.call(self.owner, "GET", "/api/automations/options").json()["fields"]["lead"]
        engine = next(f for f in fields if f["field"] == "custom.engine_cc")
        self.assertEqual((engine["label"], engine["numeric"]), ("Engine CC", True))
        self.assertNotIn("contains", engine["operators"])

    def test_rule_compares_a_number_as_a_number(self):
        self.rule([{"field": "custom.engine_cc", "operator": "greater_than", "value": "500"}])
        self.assertEqual(self.get(self.lead("Royal", custom={"engine_cc": 650})["id"])["leadPriority"], "HOT")
        self.assertNotEqual(self.get(self.lead("Scooty", custom={"engine_cc": 110})["id"])["leadPriority"], "HOT")
        self.assertNotEqual(self.get(self.lead("Unknown")["id"])["leadPriority"], "HOT")

    def test_rule_on_pick_several(self):
        self.rule([{"field": "custom.fuel", "operator": "contains", "value": "ev"}])
        self.assertEqual(self.get(self.lead("Green", custom={"fuel": ["Petrol", "EV"]})["id"])["leadPriority"], "HOT")
        self.assertNotEqual(self.get(self.lead("Petrolhead", custom={"fuel": ["Petrol"]})["id"])["leadPriority"], "HOT")

    def test_rules_with_impossible_conditions_are_refused(self):
        for condition, reason in (({"field": "custom.engine_cc", "operator": "greater_than", "value": "big"}, "must be a number"),
                                  ({"field": "custom.engine_cc", "operator": "contains", "value": "5"}, "can't be compared"),
                                  ({"field": "custom.fuel", "operator": "contains", "value": "Coal"}, "not one of the choices"),
                                  ({"field": "custom.colour", "operator": "is", "value": "red"}, "can't be checked")):
            self.assertIn(reason, self.rule([condition], status=422)["detail"])

    def test_rule_follows_a_change_to_the_field(self):
        rule = self.rule([{"field": "custom.engine_cc", "operator": "greater_than", "value": "500"}])
        self.change("engine_cc", label="Engine size")
        with self.company_db() as db:
            stored = next(r for r in db["automationRules"] if r["id"] == rule["id"])
        self.assertEqual(stored["conditions"][0]["definition"]["label"], "Engine size")


class ImportExportMerge(CustomFieldCase):
    def setUp(self):
        super().setUp()
        self.define(ENGINE)
        self.define({**FUEL, "type": "multi_choice"})

    def import_csv(self, text, mapping=None):
        analyzed = self.call(self.owner, "POST", "/api/imports/analyze?filename=bikes.csv", content=text.encode("utf-8"))
        self.assertEqual(analyzed.status_code, 200, analyzed.text)
        data = analyzed.json()
        mapping = mapping or {str(c["index"]): c["suggestedField"] or "__skip__" for c in data["columns"]}
        res = self.call(self.owner, "POST", f"/api/imports/{data['importId']}/commit", json={"mapping": mapping})
        self.assertEqual(res.status_code, 200, res.text)
        return data, res.json()

    def test_import_maps_and_checks_custom_columns(self):
        data, result = self.import_csv("Name,Mobile,Engine CC,Fuel\nAsha,+91 90000 55555,350,petrol; ev\n"
                                       "Bad Row,+91 90000 66666,huge,petrol\n")
        self.assertIn({"field": "custom.engine_cc", "label": "Engine CC", "required": False, "custom": True},
                      data["availableFields"])
        self.assertEqual([c["suggestedField"] for c in data["columns"]][2:], ["custom.engine_cc", "custom.fuel"])
        self.assertEqual(result["importedCount"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("Engine CC must be a number", result["errors"][0]["message"])
        lead = self.get(result["createdLeadIds"][0])
        self.assertEqual(lead["custom"], {"engine_cc": 350, "fuel": ["Petrol", "EV"]})

    def test_import_refuses_an_unknown_custom_target(self):
        analyzed = self.call(self.owner, "POST", "/api/imports/analyze?filename=x.csv",
                             content=b"Name,Mobile,Colour\nA,+91 90000 77777,red\n").json()
        res = self.call(self.owner, "POST", f"/api/imports/{analyzed['importId']}/commit",
                        json={"mapping": {"0": "name", "1": "mobile", "2": "custom.colour"}})
        self.assertEqual(res.status_code, 422)

    def test_export_has_a_column_per_field(self):
        self.lead("Exported", custom={"engine_cc": 220, "fuel": ["Petrol", "EV"]})
        archive = zipfile.ZipFile(io.BytesIO(self.call(self.owner, "GET", "/api/export").content))
        rows = list(csv.DictReader(io.StringIO(archive.read("leads.csv").decode("utf-8-sig"))))
        row = next(r for r in rows if r["firstName"] == "Exported")
        self.assertEqual((row["Engine CC"], row["Fuel"]), ("220", "Petrol; EV"))
        self.assertNotIn("custom", rows[0])

    def test_merge_keeps_both_leads_values(self):
        keep = self.lead("Keep", custom={"engine_cc": 150}, mobile="+91 90000 88888")
        dupe = self.lead("Dupe", custom={"engine_cc": 999, "fuel": ["EV"]}, mobile="+91 90000 88889")
        res = self.call(self.owner, "POST", f"/api/leads/{keep['id']}/merge/{dupe['id']}")
        self.assertEqual(res.status_code, 200, res.text)
        self.assertEqual(self.get(keep["id"])["custom"], {"engine_cc": 150, "fuel": ["EV"]})


if __name__ == "__main__":
    import unittest
    unittest.main()
