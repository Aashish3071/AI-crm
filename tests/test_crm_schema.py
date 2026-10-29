"""Custom field types, definitions, values and stage categories (crm_schema.py).

Pure-function tests: no server, no storage. The last class checks that the default
pipeline agrees with the server's fixed status groups, so the move to configurable
stages (decision D2 in docs/AI_CUSTOMIZATION_PLAN.md) starts from today's behaviour.
"""
import unittest

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_automation
import crm_schema as schema
from crm_schema import SchemaError


def field(**overrides):
    return schema.check_field("lead", {"key": "engine_cc", "label": "Engine CC", "type": "number", **overrides})


class FieldDefinitions(unittest.TestCase):
    def test_a_valid_field_is_cleaned(self):
        defn = schema.check_field("lead", {"key": "rider_age", "label": "  Rider age ", "type": "number",
                                           "min": 18, "section": "Bike details", "products": ["Bike Insurance"]})
        self.assertEqual(defn, {"key": "rider_age", "label": "Rider age", "type": "number", "required": False,
                                "hidden": False, "section": "Bike details", "min": 18, "products": ["Bike Insurance"]})

    def test_keys_must_be_simple(self):
        for key in ("", "1st", "Engine", "engine-cc", "engine cc", "x" * 41):
            with self.subTest(key=key), self.assertRaises(SchemaError):
                field(key=key)

    def test_built_in_names_are_reserved_in_any_spelling(self):
        for key in ("mobile", "expiry_date", "assigned_to", "custom"):
            with self.subTest(key=key), self.assertRaisesRegex(SchemaError, "built-in"):
                field(key=key)
        # The same word is free on an object that doesn't have it built in.
        schema.check_field("policy", {"key": "mobile", "label": "Mobile", "type": "phone"})

    def test_duplicate_keys_and_labels_are_refused(self):
        existing = [field()]
        with self.assertRaisesRegex(SchemaError, "already exists"):
            schema.check_field("lead", {"key": "engine_cc", "label": "Other", "type": "text"}, existing)
        with self.assertRaisesRegex(SchemaError, "already labelled"):
            schema.check_field("lead", {"key": "cc", "label": "engine cc", "type": "text"}, existing)

    def test_only_known_types_and_objects(self):
        with self.assertRaises(SchemaError):
            field(type="formula")
        with self.assertRaises(SchemaError):
            schema.check_field("deal", {"key": "x", "label": "X", "type": "text"})

    def test_choice_fields_need_distinct_options(self):
        with self.assertRaisesRegex(SchemaError, "at least one option"):
            field(type="choice")
        with self.assertRaisesRegex(SchemaError, "same name"):
            field(type="choice", options=["Petrol", "petrol"])
        with self.assertRaisesRegex(SchemaError, "Only choice"):
            field(type="text", options=["A"])
        self.assertEqual(field(type="choice", options=[" Petrol ", "CNG"])["options"], ["Petrol", "CNG"])

    def test_lookup_needs_a_target(self):
        with self.assertRaises(SchemaError):
            field(type="lookup")
        self.assertEqual(field(type="lookup", target="customer")["target"], "customer")

    def test_bounds_must_be_ordered(self):
        with self.assertRaisesRegex(SchemaError, "minimum"):
            field(min=10, max=5)

    def test_field_limit(self):
        many = [{"key": f"f{i}", "label": f"F{i}", "type": "text"} for i in range(schema.MAX_FIELDS_PER_OBJECT)]
        with self.assertRaisesRegex(SchemaError, "at most"):
            schema.check_field("lead", {"key": "one_more", "label": "One more", "type": "text"}, many)


class FieldChanges(unittest.TestCase):
    def test_key_is_permanent_and_label_is_not(self):
        before = field()
        self.assertEqual(schema.check_field_change("lead", before, {"label": "Engine size"}, [before])["label"],
                         "Engine size")
        with self.assertRaisesRegex(SchemaError, "key can't be changed"):
            schema.check_field_change("lead", before, {"key": "engine"}, [before])

    def test_only_compatible_type_changes(self):
        text = schema.check_field("lead", {"key": "remarks", "label": "Remarks", "type": "text"})
        self.assertEqual(schema.check_field_change("lead", text, {"type": "long_text"})["type"], "long_text")
        with self.assertRaisesRegex(SchemaError, "add a new field"):
            schema.check_field_change("lead", text, {"type": "number"})
        link = field(type="lookup", target="customer")
        with self.assertRaises(SchemaError):
            schema.check_field_change("lead", link, {"target": "policy"})

    def test_removed_options_are_reported(self):
        before = field(type="choice", options=["Petrol", "Diesel", "CNG"])
        self.assertEqual(schema.removed_options(before, {"options": ["petrol", "EV"]}), ["Diesel", "CNG"])


class Values(unittest.TestCase):
    def read(self, value, **defn):
        return schema.read_value({"key": "k", "label": "K", **defn}, value)

    def test_empty_clears(self):
        for value in (None, "", "  ", []):
            self.assertIsNone(self.read(value, type="number"))

    def test_numbers_and_amounts(self):
        self.assertEqual(self.read("1,200", type="number"), 1200)
        self.assertEqual(self.read("12.5", type="number"), 12.5)
        self.assertEqual(self.read("₹ 12,500.505", type="currency"), 12500.5)
        self.assertEqual(self.read("Rs. 1,25,000", type="currency"), 125000.0)
        for bad in ("abc", True, "NaN", "inf"):
            with self.subTest(bad=bad), self.assertRaises(SchemaError):
                self.read(bad, type="number")
        with self.assertRaisesRegex(SchemaError, "negative"):
            self.read(-1, type="currency")
        with self.assertRaisesRegex(SchemaError, "at least 18"):
            self.read(17, type="number", min=18)

    def test_dates(self):
        self.assertEqual(self.read("2026-11-01", type="date"), "2026-11-01")
        self.assertEqual(self.read("2026-11-01T10:30:00Z", type="datetime"), "2026-11-01T10:30:00+00:00")
        for bad in ("01/11/2026", "2026-02-30"):
            with self.subTest(bad=bad), self.assertRaises(SchemaError):
                self.read(bad, type="date")

    def test_yes_no(self):
        self.assertIs(self.read("Yes", type="boolean"), True)
        self.assertIs(self.read(0, type="boolean"), False)
        with self.assertRaises(SchemaError):
            self.read("maybe", type="boolean")

    def test_choices_keep_the_defined_spelling(self):
        options = ["Petrol", "Diesel", "CNG"]
        self.assertEqual(self.read("petrol", type="choice", options=options), "Petrol")
        self.assertEqual(self.read("cng, Petrol, cng", type="multi_choice", options=options), ["CNG", "Petrol"])
        self.assertEqual(self.read("Petrol; CNG", type="multi_choice", options=options), ["Petrol", "CNG"])
        with self.assertRaisesRegex(SchemaError, "not one of"):
            self.read("EV", type="choice", options=options)

    def test_phone_and_email(self):
        self.assertEqual(self.read("+91 98765-43210", type="phone"), "+919876543210")
        self.assertEqual(self.read("(022) 2345 6789", type="phone"), "02223456789")
        for bad in ("12345", "98765abc10", "91+9876543210"):
            with self.subTest(bad=bad), self.assertRaises(SchemaError):
                self.read(bad, type="phone")
        self.assertEqual(self.read(" Priya@Example.in ", type="email"), "priya@example.in")
        with self.assertRaises(SchemaError):
            self.read("priya@", type="email")

    def test_record_ids(self):
        self.assertEqual(self.read("C_1a2b", type="lookup", target="customer"), "C_1a2b")
        with self.assertRaises(SchemaError):
            self.read("../etc/passwd", type="file")


class CleanCustom(unittest.TestCase):
    defs = [
        {"key": "engine_cc", "label": "Engine CC", "type": "number", "required": True, "products": ["Bike Insurance"]},
        {"key": "fuel", "label": "Fuel", "type": "choice", "options": ["Petrol", "EV"]},
        {"key": "old_code", "label": "Old code", "type": "text", "hidden": True},
    ]

    def test_values_merge_into_existing(self):
        custom, errors = schema.clean_custom(self.defs, {"fuel": "ev"}, existing={"engine_cc": 150, "old_code": "A1"})
        self.assertEqual(errors, {})
        self.assertEqual(custom, {"engine_cc": 150, "fuel": "EV", "old_code": "A1"})

    def test_clearing_a_value_removes_it(self):
        custom, errors = schema.clean_custom(self.defs, {"fuel": ""}, existing={"fuel": "EV"})
        self.assertEqual((custom, errors), ({}, {}))

    def test_errors_are_per_field_and_readable(self):
        _, errors = schema.clean_custom(self.defs, {"fuel": "Diesel", "colour": "red", "old_code": "B"})
        self.assertEqual(set(errors), {"fuel", "colour", "old_code"})
        self.assertIn("Fuel", errors["fuel"])
        self.assertIn("hidden", errors["old_code"])

    def test_required_only_for_the_fields_product(self):
        _, errors = schema.clean_custom(self.defs, {}, creating=True, product="Bike Insurance")
        self.assertEqual(errors, {"engine_cc": "Engine CC is required"})
        _, errors = schema.clean_custom(self.defs, {}, creating=True, product="Car Insurance")
        self.assertEqual(errors, {})
        # An edit that doesn't touch a required field doesn't fail on it.
        _, errors = schema.clean_custom(self.defs, {"fuel": "EV"}, product="Bike Insurance")
        self.assertEqual(errors, {})
        _, errors = schema.clean_custom(self.defs, {"engine_cc": ""}, existing={"engine_cc": 150},
                                        product="Bike Insurance")
        self.assertEqual(set(errors), {"engine_cc"})

    def test_not_an_object(self):
        _, errors = schema.clean_custom(self.defs, ["fuel"])
        self.assertEqual(set(errors), {"custom"})


class TypeCatalogue(unittest.TestCase):
    def test_operators_are_the_automation_engines(self):
        known = {o["op"] for o in crm_automation.OPERATORS}
        for entry in schema.type_catalogue():
            with self.subTest(type=entry["type"]):
                self.assertTrue(set(entry["operators"]) <= known)


class StageCategories(unittest.TestCase):
    def test_default_pipeline_matches_todays_status_rules(self):
        import pipecat_server as server
        pipeline = schema.check_pipeline(schema.DEFAULT_LEAD_PIPELINE)
        self.assertEqual([s["name"] for s in pipeline], server.LEAD_STATUSES)
        self.assertEqual(schema.stages_in(pipeline, finished=True), server.CLOSED_STATUSES)
        self.assertEqual(schema.stages_in(pipeline, next_action=False), server.NO_NEXT_ACTION)
        self.assertEqual(schema.stages_in(pipeline, reason=True), server.REASON_REQUIRED)
        self.assertEqual(schema.stages_in(pipeline, category="won"), server.SOLD_STATUSES)

    def test_a_company_pipeline(self):
        pipeline = schema.check_pipeline([{"name": "New", "category": "working"},
                                          {"name": "Inspection", "category": "working"},
                                          {"name": "Sold", "category": "won"}, {"name": "Dropped", "category": "lost"}])
        self.assertEqual(schema.stages_in(pipeline, reason=True), {"Dropped"})

    def test_pipeline_rules(self):
        cases = {
            "at least one stage": [],
            "category": [{"name": "New", "category": "hot"}],
            "first stage": [{"name": "Sold", "category": "won"}, {"name": "New", "category": "working"},
                            {"name": "Lost", "category": "lost"}],
            "not sold": [{"name": "New", "category": "working"}, {"name": "Sold", "category": "won"}],
            "Two stages": [{"name": "New", "category": "working"}, {"name": "new", "category": "working"}],
        }
        for message, stages in cases.items():
            with self.subTest(message), self.assertRaisesRegex(SchemaError, message):
                schema.check_pipeline(stages)


if __name__ == "__main__":
    unittest.main()
