"""The company's own record types (crm_routes/schema.py, crm_routes/records.py; plan phase 4).

A record type hangs from a lead, customer or policy; its records are checked like any custom
field and are visible exactly when their parent is.
"""
import csv
import io
import zipfile

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
from test_client_blueprint import ClientBlueprintCase

INSPECTION = {"label": "Vehicle inspection", "parent": "lead"}
FIELDS = [{"key": "inspected_on", "label": "Inspected on", "type": "date", "required": True},
          {"key": "condition", "label": "Condition", "type": "choice", "options": ["Good", "Fair", "Poor"]}]


class RecordCase(ClientBlueprintCase):
    def setUp(self):
        super().setUp()
        self.add_staff("Priya Sharma", "telecaller")
        self.add_staff("Rohit Verma", "telecaller")
        self.priya = self.sign_in("priya.sharma@blueprint.invalid")
        self.rohit = self.sign_in("rohit.verma@blueprint.invalid")
        made = self.call(self.owner, "POST", "/api/schema/record-types", json=INSPECTION)
        self.assertEqual(made.status_code, 200, made.text)
        self.type = made.json()
        for field in FIELDS:
            res = self.call(self.owner, "POST", f"/api/schema/fields/{self.type['key']}", json=field)
            self.assertEqual(res.status_code, 200, res.text)
        self.lead = self.add_lead(self.owner, "Inspected", owner="Priya Sharma")

    def add(self, client, custom, parent=None, status=200):
        res = self.call(client, "POST", "/api/custom-records",
                        json={"type": self.type["key"], "parentId": parent or self.lead["id"], "custom": custom})
        self.assertEqual(res.status_code, status, res.text)
        return res.json()


class RecordTypes(RecordCase):
    def test_a_record_type_and_its_fields_are_in_the_schema(self):
        self.assertEqual((self.type["key"], self.type["parent"]), ("vehicle_inspection", "lead"))
        schema = self.call(self.priya, "GET", "/api/schema").json()
        self.assertEqual([t["key"] for t in schema["recordTypes"]], ["vehicle_inspection"])
        self.assertEqual([f["key"] for f in schema["objects"]["vehicle_inspection"]], ["inspected_on", "condition"])

    def test_bad_record_types_are_refused(self):
        for body, reason in (({"label": "Vehicle inspection", "parent": "lead"}, "already a record type"),
                             ({"label": "Thing", "parent": "deal"}, "attached to"),
                             ({"label": "Leads", "key": "lead", "parent": "lead"}, "can't be used")):
            res = self.call(self.owner, "POST", "/api/schema/record-types", json=body)
            self.assertEqual(res.status_code, 422, body)
            self.assertIn(reason, res.json()["detail"])
        self.assertEqual(self.call(self.priya, "POST", "/api/schema/record-types", json={"label": "X", "parent": "lead"}).status_code, 403)

    def test_rename_and_hide_but_keep_the_parent(self):
        res = self.call(self.owner, "PUT", "/api/schema/record-types/vehicle_inspection", json={"label": "Car inspection"})
        self.assertEqual(res.json()["label"], "Car inspection")
        self.assertEqual(self.call(self.owner, "PUT", "/api/schema/record-types/vehicle_inspection",
                                   json={"parent": "customer"}).status_code, 422)
        self.call(self.owner, "PUT", "/api/schema/record-types/vehicle_inspection", json={"hidden": True})
        self.assertIn("hidden", self.add(self.priya, {"inspected_on": "2026-11-01"}, status=422)["detail"])

    def test_record_type_fields_have_no_products(self):
        res = self.call(self.owner, "POST", "/api/schema/fields/vehicle_inspection",
                        json={"key": "x", "label": "X", "type": "text", "products": ["Car Insurance"]})
        self.assertEqual(res.status_code, 422)


class Records(RecordCase):
    def test_records_are_checked_like_any_field(self):
        self.assertIn("Inspected on is required", self.add(self.priya, {"condition": "Good"}, status=422)["detail"])
        self.assertIn("not one of the choices", self.add(self.priya, {"inspected_on": "2026-11-01", "condition": "Great"},
                                                         status=422)["detail"])
        record = self.add(self.priya, {"inspected_on": "2026-11-01", "condition": "good"})
        self.assertEqual(record["custom"], {"inspected_on": "2026-11-01", "condition": "Good"})
        res = self.call(self.priya, "PUT", f"/api/custom-records/{record['id']}", json={"custom": {"condition": "Fair"}})
        self.assertEqual(res.json()["custom"], {"inspected_on": "2026-11-01", "condition": "Fair"})

    def test_records_follow_their_parents_visibility(self):
        record = self.add(self.priya, {"inspected_on": "2026-11-01"})
        self.assertEqual(len(self.call(self.priya, "GET", "/api/custom-records", params={"parentId": self.lead["id"]}).json()), 1)
        self.assertEqual(self.call(self.rohit, "GET", "/api/custom-records").json(), [])
        self.add(self.rohit, {"inspected_on": "2026-11-01"}, status=404)
        self.assertEqual(self.call(self.rohit, "PUT", f"/api/custom-records/{record['id']}", json={"custom": {}}).status_code, 404)
        self.assertEqual(self.call(self.rohit, "DELETE", f"/api/custom-records/{record['id']}").status_code, 404)
        self.assertEqual(len(self.call(self.owner, "GET", "/api/custom-records").json()), 1)

    def test_delete_keeps_a_copy_in_the_audit_log(self):
        record = self.add(self.priya, {"inspected_on": "2026-11-01"})
        self.assertEqual(self.call(self.priya, "DELETE", f"/api/custom-records/{record['id']}").status_code, 200)
        self.assertEqual(self.call(self.owner, "GET", "/api/custom-records").json(), [])
        with self.company_db() as db:
            kept = [a for a in db["auditLogs"] if "Custom Record Deleted" in str(a.get("action"))]
        self.assertEqual(len(kept), 1)
        self.assertIn(record["id"], str(kept[0]))

    def test_export_has_a_sheet_per_record_type(self):
        self.add(self.priya, {"inspected_on": "2026-11-01", "condition": "Poor"})
        archive = zipfile.ZipFile(io.BytesIO(self.call(self.owner, "GET", "/api/export").content))
        rows = list(csv.DictReader(io.StringIO(archive.read("vehicle-inspection.csv").decode("utf-8-sig"))))
        self.assertEqual((rows[0]["leadId"], rows[0]["Inspected on"], rows[0]["Condition"]), (self.lead["id"], "2026-11-01", "Poor"))


if __name__ == "__main__":
    import unittest
    unittest.main()
