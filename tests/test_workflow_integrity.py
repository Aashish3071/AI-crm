"""Regression checks for shared workflow invariants using disposable data."""
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

import crm_test_isolation  # noqa: F401  (must precede app imports; keeps tests off live data)
import crm_store
import pipecat_server as server
import test_insurance_operations


class WorkflowIntegrityTests(unittest.TestCase):
    setUp = test_insurance_operations.InsuranceOperationsTests.setUp
    tearDown = test_insurance_operations.InsuranceOperationsTests.tearDown

    def lead(self, name="Sync"):
        response = self.client.post("/api/leads", json={"firstName": name, "lastName": "Test",
            "organization": name + " Co", "mobile": "+919999111222", "nextAction": "Call client",
            "nextActionDate": "2026-10-10", "assignedTo": "Sarah Connor"})
        self.assertEqual(response.status_code, 200)
        return response.json()

    def meeting(self, lead, day, time="10:00", owner="Sarah Connor", duration=30):
        return self.client.post("/api/calendar/events", json={"title": "Review", "date": day,
            "time": time, "durationMinutes": duration, "assignedTo": owner,
            "associatedType": "Lead", "associatedId": lead["id"]})

    def test_canonical_task_rename_date_and_completion_update_lead(self):
        lead = self.lead()
        response = self.client.put(f"/api/tasks/{lead['nextActionTaskId']}", json={
            "title": "Send revised quotation", "dueDate": "2026-10-11", "status": "Completed"})
        self.assertEqual(response.status_code, 200)
        updated = self.client.get(f"/api/leads/{lead['id']}").json()["lead"]
        self.assertEqual(updated["nextAction"], "Send revised quotation")
        self.assertEqual(updated["nextActionDate"], "2026-10-11")
        self.assertTrue(updated["nextActionCompleted"])

    def test_task_and_calendar_moves_cannot_bypass_conflicts(self):
        lead = self.lead()
        first = self.meeting(lead, "2026-10-11").json()
        self.assertEqual(self.meeting(lead, "2026-10-12").status_code, 200)
        for endpoint, data in [
            (f"/api/tasks/{first['taskId']}", {"dueDate": "2026-10-12"}),
            ("/api/calendar/reschedule", {"id": first["taskId"], "date": "2026-10-12"}),
        ]:
            response = self.client.post(endpoint, json=data) if endpoint.endswith("reschedule") else self.client.put(endpoint, json=data)
            self.assertEqual(response.status_code, 409)
        stored = next(item for item in server.load_db()["calendarEvents"] if item["id"] == first["id"])
        self.assertEqual(stored["date"], "2026-10-11")

    def test_conflicts_across_midnight_and_invalid_duration(self):
        lead = self.lead()
        first = self.meeting(lead, "2026-10-11", "23:45", duration=60).json()
        self.assertEqual(self.meeting(lead, "2026-10-12", "00:15").status_code, 409)
        self.assertEqual(self.meeting(lead, "2026-10-12", "00:45").status_code, 200)
        self.assertEqual(self.client.put(f"/api/calendar/events/{first['id']}", json={"durationMinutes": "bad"}).status_code, 422)

    def test_bulk_assignment_moves_appointment_and_notification_together(self):
        lead = self.lead()
        event = self.meeting(lead, "2026-10-11").json()
        db = server.load_db()
        db.setdefault("notifications", []).append({"id": "NTF_TEST", "calendarEventId": event["id"], "read": False})
        server.save_db(db)
        self.assertEqual(self.client.post("/api/leads/bulk-update", json={"ids": [lead["id"]],
            "updates": {"assignedTo": "John Parker"}}).status_code, 200)
        db = server.load_db()
        self.assertEqual(next(e for e in db["calendarEvents"] if e["id"] == event["id"])["assignedTo"], "John Parker")
        self.assertEqual(next(n for n in db["notifications"] if n["id"] == "NTF_TEST")["assignedTo"], "John Parker")
        self.client.put(f"/api/tasks/{event['taskId']}", json={"status": "Completed"})
        self.assertTrue(next(n for n in server.load_db()["notifications"] if n["id"] == "NTF_TEST")["resolved"])

    def test_merge_relinks_appointments_and_converted_customer(self):
        target, duplicate = self.lead("Target"), self.lead("Duplicate")
        event = self.meeting(duplicate, "2026-10-11").json()
        conversion = self.client.post(f"/api/leads/{duplicate['id']}/convert", json={}).json()
        self.assertEqual(self.client.post(f"/api/leads/{target['id']}/merge/{duplicate['id']}").status_code, 200)
        db = server.load_db()
        self.assertEqual(next(e for e in db["calendarEvents"] if e["id"] == event["id"])["associatedId"], target["id"])
        self.assertEqual(next(c for c in db["customers"] if c["id"] == conversion["customer"]["id"])["sourceLeadId"], target["id"])

    def test_concurrent_writers_reject_stale_snapshot_without_lost_update(self):
        server.load_db()
        barrier = threading.Barrier(2)
        def write(value):
            state = crm_store.load_json_state(self.db_path)
            state["settings"]["writer"] = value
            barrier.wait(timeout=5)
            try:
                crm_store.save_json_state(self.db_path, state)
                return value
            except RuntimeError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ["first", "second"]))
        winners = [item for item in results if item]
        self.assertEqual(len(winners), 1)
        self.assertEqual(server.load_db()["settings"]["writer"], winners[0])

    def test_corrupt_database_is_not_overwritten_with_demo_records(self):
        with open(self.db_path, "w", encoding="utf-8") as handle:
            handle.write('{"broken":')
        with self.assertRaises(RuntimeError):
            server.load_db()
        with open(self.db_path, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), '{"broken":')

    def test_archive_restore_does_not_reopen_previously_archived_tasks(self):
        lead = self.lead()
        task = self.client.post("/api/tasks", json={"title": "Retired action", "dueDate": "2026-10-10",
            "associatedType": "Lead", "associatedId": lead["id"]}).json()
        self.client.put(f"/api/tasks/{task['id']}", json={"status": "Archived"})
        self.assertEqual(self.client.post(f"/api/leads/{lead['id']}/archive").status_code, 200)
        self.assertEqual(self.client.post(f"/api/archived-leads/{lead['id']}/restore").status_code, 200)
        tasks = {item["id"]: item for item in self.client.get("/api/tasks").json()}
        self.assertEqual(tasks[task["id"]]["status"], "Archived")
        self.assertEqual(tasks[lead["nextActionTaskId"]]["status"], "Pending")

    def test_legacy_same_day_task_is_not_mistaken_for_next_action(self):
        lead = self.lead()
        db = server.load_db()
        stored = next(item for item in db["leads"] if item["id"] == lead["id"])
        stored.pop("nextActionTaskId")
        task = next(item for item in db["tasks"] if item["id"] == lead["nextActionTaskId"])
        task["title"] = "A different piece of work"
        server.repair_calendar_model(db)
        self.assertFalse(stored.get("nextActionTaskId"))
        server.save_db(db)
        feed = self.client.get("/api/calendar").json()["entries"]
        self.assertTrue(any(item["id"] == "next-" + lead["id"] for item in feed))
