"""Real PostgreSQL adapter checks; only a designated disposable local database."""
import copy
import os
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from unittest.mock import patch

import crm_store
from tests.test_blueprint_acceptance import criterion


class BlueprintPostgresAcceptance(unittest.TestCase):
    def setUp(self):
        dsn = os.environ.get("CRM_BLUEPRINT_PG_DSN", "")
        if not dsn:
            self.skipTest("CRM_BLUEPRINT_PG_DSN was not supplied for a designated disposable local database")
        parsed = urlparse(dsn)
        if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.path != "/blueprint":
            self.fail("Refusing PostgreSQL target outside the disposable localhost blueprint database")
        self.environment = patch.dict(os.environ, {"DATABASE_URL": dsn})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.companies = []
        self.addCleanup(self.cleanup_companies)
        self.company = self.new_company()

    def new_company(self):
        company = "BP_TEST_" + uuid.uuid4().hex
        self.companies.append(company)
        crm_store.save_state(company, {"settings": {}, "customers": [{"id": "CUS_BP", "name": "Synthetic Customer"}],
            "policies": [{"id": "POL_BP", "customerId": "CUS_BP", "premium": 1000}]})
        return company

    def cleanup_companies(self):
        with crm_store._connect() as connection:
            with connection.cursor() as cursor:
                for company in self.companies:
                    cursor.execute("DELETE FROM crm_links WHERE company_id=%s", (company,))
                    cursor.execute("DELETE FROM crm_records WHERE company_id=%s", (company,))
                    cursor.execute("DELETE FROM crm_companies WHERE id=%s", (company,))

    @criterion("M28.2")
    def test_postgres_roundtrip_stale_revision_and_rollback(self):
        state = crm_store.load_state(self.company, {})
        stale = copy.deepcopy(state)
        state["policies"][0]["premium"] = 1200
        crm_store.save_state(self.company, state)
        with self.assertRaisesRegex(RuntimeError, "changed during"):
            crm_store.save_state(self.company, stale)
        loaded = crm_store.load_state(self.company, {})
        self.assertEqual(loaded["policies"][0]["premium"], 1200)
        loaded["policies"][0]["customerId"] = "MISSING"
        with self.assertRaisesRegex(RuntimeError, "Broken relationship"):
            crm_store.save_state(self.company, loaded)
        self.assertEqual(crm_store.load_state(self.company, {})["policies"][0]["customerId"], "CUS_BP")

    @criterion("M28.2")
    def test_postgres_competing_writers_have_one_winner(self):
        first = crm_store.load_state(self.company, {})
        second = copy.deepcopy(first)
        barrier = threading.Barrier(2)
        def save(args):
            state, amount = args
            state["policies"][0]["premium"] = amount
            barrier.wait(timeout=5)
            try:
                crm_store.save_state(self.company, state)
                return amount
            except RuntimeError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, [(first, 1200), (second, 1400)]))
        winners = [amount for amount in outcomes if amount]
        self.assertEqual(len(winners), 1)
        self.assertEqual(crm_store.load_state(self.company, {})["policies"][0]["premium"], winners[0])

    @criterion("M28.2", "M26.2")
    def test_postgres_archive_reference_and_restore(self):
        state = crm_store.load_state(self.company, {})
        customer = state["customers"].pop()
        state["archivedRecords"] = [{"archiveId": "ARC_BP", "sourceCollection": "customers", "record": customer}]
        crm_store.save_state(self.company, state)
        loaded = crm_store.load_state(self.company, {})
        self.assertEqual(loaded["policies"][0]["customerId"], "CUS_BP")
        loaded["customers"] = [customer]
        loaded["archivedRecords"] = []
        crm_store.save_state(self.company, loaded)
        self.assertEqual(crm_store.load_state(self.company, {})["customers"][0]["name"], "Synthetic Customer")

    @criterion("M02.1", "M28.2")
    def test_postgres_same_record_ids_remain_company_isolated(self):
        other = self.new_company()
        state = crm_store.load_state(other, {})
        state["customers"][0]["name"] = "Other Company"
        crm_store.save_state(other, state)
        self.assertEqual(crm_store.load_state(self.company, {})["customers"][0]["name"], "Synthetic Customer")

    @criterion("M14.3", "M28.2")
    def test_postgres_scheduler_lock_excludes_second_worker(self):
        with crm_store.scheduler_lock(self.company) as first:
            self.assertTrue(first)
            with crm_store.scheduler_lock(self.company) as second:
                self.assertFalse(second)
        with crm_store.scheduler_lock(self.company) as after_release:
            self.assertTrue(after_release)
