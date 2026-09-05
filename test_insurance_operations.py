"""Focused smoke tests for the Phase 3/4 insurance operations API."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

import pipecat_server as server


class InsuranceOperationsTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(self.db_path)
        self.original_db_path = server.DB_FILE
        self.original_document_root = server.DOCUMENT_ROOT
        self.original_backup_root = server.BACKUP_ROOT
        self.original_auth_disabled = server.AUTH_DISABLED
        server.DB_FILE = self.db_path
        server.AUTH_DISABLED = True
        self.temp_root = tempfile.TemporaryDirectory()
        server.DOCUMENT_ROOT = os.path.join(self.temp_root.name, "documents")
        server.BACKUP_ROOT = os.path.join(self.temp_root.name, "backups")
        self.client = TestClient(server.app)

    def tearDown(self):
        server.DB_FILE = self.original_db_path
        server.DOCUMENT_ROOT = self.original_document_root
        server.BACKUP_ROOT = self.original_backup_root
        server.AUTH_DISABLED = self.original_auth_disabled
        self.temp_root.cleanup()
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_policy_renewal_and_quotation_flow(self):
        migrated = self.client.post("/api/policies/migrate-leads")
        self.assertEqual(migrated.status_code, 200)
        self.assertGreater(migrated.json()["createdCount"], 0)

        generated = self.client.post("/api/renewals/generate?days=365")
        self.assertEqual(generated.status_code, 200)
        renewal = generated.json()["renewals"][0]

        quote = self.client.post("/api/quotations", json={
            "renewalId": renewal["id"], "insurer": "Test Insurer", "premium": 50000
        })
        self.assertEqual(quote.status_code, 200)

        invalid_loss = self.client.put(f"/api/renewals/{renewal['id']}", json={"stage": "Lost"})
        self.assertEqual(invalid_loss.status_code, 422)

    def test_opt_out_blocks_delivery(self):
        self.client.post("/api/consents", json={
            "leadId": "L1", "channel": "WhatsApp", "status": "Opted Out"
        })
        message = self.client.post("/api/communications", json={
            "associatedId": "L1", "recipient": "+910000000000",
            "channel": "WhatsApp", "content": "Renewal reminder"
        })
        self.assertEqual(message.status_code, 409)

    def test_whatsapp_delivery_failure_updates_timeline_and_notifies_owner(self):
        channel = self.client.post("/api/channels", json={
            "provider": "whatsapp", "name": "Broker WhatsApp"
        }).json()
        db = server.load_db()
        db.setdefault("communications", []).insert(0, {
            "id": "COM_WA_STATUS", "associatedType": "Lead", "associatedId": "L1",
            "recipient": "+919999000000", "channel": "WhatsApp", "content": "Renewal reminder",
            "direction": "Outbound", "status": "Sent", "providerMessageId": "wamid.delivery-test",
            "deliveryEvents": [{"status": "Sent", "at": "2026-09-04T10:00:00Z"}],
            "createdAt": "2026-09-04T10:00:00Z"
        })
        server.save_db(db)

        callback = self.client.post(f"/api/webhooks/{channel['id']}", json={
            "object": "whatsapp_business_account",
            "entry": [{"changes": [{"field": "messages", "value": {"statuses": [{
                "id": "wamid.delivery-test", "status": "failed", "timestamp": "1788516060",
                "errors": [{"title": "Recipient unavailable"}]
            }]}}]}]
        })
        self.assertEqual(callback.status_code, 200)
        communication = next(item for item in self.client.get("/api/communications").json()
                             if item["id"] == "COM_WA_STATUS")
        self.assertEqual(communication["status"], "Failed")
        self.assertEqual(communication["deliveryEvents"][-1]["details"], "Recipient unavailable")
        notifications = self.client.get("/api/notifications").json()
        self.assertTrue(any(item.get("communicationId") == "COM_WA_STATUS" for item in notifications))

    def test_calendar_canonical_projection_and_two_way_sync(self):
        lead = self.client.post("/api/leads", json={"firstName":"Calendar", "lastName":"Client",
            "mobile":"+919999300001", "organization":"Calendar Works", "expiryDate":"2027-09-30",
            "nextAction":"Discovery meeting", "nextActionDate":"2026-09-10", "assignedTo":"Sarah Connor"}).json()
        feed = self.client.get("/api/calendar?start=2026-09-01&end=2027-10-01").json()["entries"]
        lead_work = [item for item in feed if item.get("linkId") == lead["id"] and item.get("title") == "Discovery meeting"]
        self.assertEqual(len(lead_work), 1)
        self.assertEqual(lead_work[0]["type"], "Task")

        event = self.client.post("/api/calendar/events", json={"title":"Risk review", "date":"2026-09-12",
            "time":"10:00", "durationMinutes":60, "type":"Meeting", "associatedType":"Lead",
            "associatedId":lead["id"], "assignedTo":"Sarah Connor", "notes":"Review asset schedule",
            "followUpDate":"2026-09-14", "followUpAction":"Send quotation options"}).json()
        feed = self.client.get("/api/calendar?start=2026-09-01&end=2026-09-30").json()["entries"]
        self.assertEqual(len([item for item in feed if item.get("id") == event["id"]]), 1)
        self.assertFalse(any(item.get("id") == event["taskId"] for item in feed))
        self.assertTrue(any(item.get("id") == event["followUpTaskId"] for item in feed))

        moved = self.client.put(f"/api/tasks/{event['taskId']}", json={"dueDate":"2026-09-13", "assignedTo":"John Parker"})
        self.assertEqual(moved.status_code, 200)
        updated_event = next(item for item in server.load_db()["calendarEvents"] if item["id"] == event["id"])
        self.assertEqual(updated_event["date"], "2026-09-13")
        self.assertEqual(updated_event["assignedTo"], "John Parker")

        self.client.put(f"/api/calendar/events/{event['id']}", json={"date":"2026-09-15", "status":"Completed"})
        linked_task = next(item for item in self.client.get("/api/tasks").json() if item["id"] == event["taskId"])
        self.assertEqual(linked_task["dueDate"], "2026-09-15")
        self.assertEqual(linked_task["status"], "Completed")

    def test_calendar_conflicts_reminders_archive_and_repair(self):
        customer = self.client.post("/api/customers", json={"name":"Timed Customer", "mobile":"+919999300002",
            "assignedTo":"Sarah Connor"}).json()
        first = self.client.post("/api/calendar/events", json={"title":"Coverage meeting", "date":"2026-09-18",
            "time":"11:00", "durationMinutes":60, "associatedType":"Customer", "associatedId":customer["id"],
            "assignedTo":"Sarah Connor"})
        self.assertEqual(first.status_code, 200)
        conflict = self.client.post("/api/calendar/events", json={"title":"Clashing call", "date":"2026-09-18",
            "time":"11:30", "durationMinutes":30, "type":"Call", "associatedType":"Customer",
            "associatedId":customer["id"], "assignedTo":"Sarah Connor"})
        self.assertEqual(conflict.status_code, 409)

        soon = datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(minutes=30)
        upcoming = self.client.post("/api/calendar/events", json={"title":"Upcoming review", "date":soon.strftime("%Y-%m-%d"),
            "time":soon.strftime("%H:%M"), "associatedType":"Customer", "associatedId":customer["id"],
            "assignedTo":"John Parker"}).json()
        notifications = self.client.post("/api/notifications/run-escalations").json()["notifications"]
        self.assertTrue(any(item.get("calendarEventId") == upcoming["id"] for item in notifications))

        db = server.load_db(); db["calendarEvents"][0].pop("category", None)
        db["tasks"] = [task for task in db["tasks"] if task.get("id") != db["calendarEvents"][0].get("taskId")]
        server.save_db(db)
        repaired = self.client.post("/api/admin/repair-calendar?dryRun=false").json()
        self.assertIn("eventTypesNormalized", repaired)
        deleted = self.client.delete(f"/api/calendar/events/{upcoming['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(any(item.get("id") == upcoming["id"] for item in self.client.get("/api/calendar").json()["entries"]))

    def test_end_to_end_lead_to_renewed_policy(self):
        lead = self.client.post("/api/leads", json={"firstName":"Flow","lastName":"Test","mobile":"+910001112223",
            "organization":"Flow Industries","policyType":"Commercial Motor","premium":"100000","expiryDate":"2026-10-01"}).json()
        converted = self.client.post(f"/api/leads/{lead['id']}/convert", json={"insurer":"Alpha Insurance","premium":100000,
            "startDate":"2025-10-02","expiryDate":"2026-10-01"})
        self.assertEqual(converted.status_code, 200)
        policy = converted.json()["policy"]
        self.assertEqual(policy["taxAmount"], 18000)
        renewal = self.client.post("/api/renewals", json={"policyId":policy["id"], "targetPremium":110000}).json()
        quote = self.client.post("/api/quotations", json={"renewalId":renewal["id"],"insurer":"Beta Insurance","premium":108000,"sumInsured":500000}).json()
        self.client.put(f"/api/renewals/{renewal['id']}", json={"selectedQuotationId":quote["id"],"stage":"Quotation Sent"})
        completed = self.client.post(f"/api/renewals/{renewal['id']}/complete", json={"policyNumber":"NEW-100","startDate":"2026-10-02","expiryDate":"2027-10-01",
            "documentChecklist":{"proposalForm":True,"kyc":True,"payment":True,"schedule":True}})
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["newPolicy"]["totalPremium"], 127440)
        lifecycle = self.client.get(f"/api/lifecycle/{lead['id']}").json()
        self.assertEqual(len(lifecycle["policies"]), 2)

    def test_lead_delete_cascades_but_archives_notes(self):
        lead = self.client.post("/api/leads", json={"firstName":"Delete","lastName":"Test","mobile":"+919999000001",
            "email":"delete@test.invalid","organization":"Delete Test Org","notes":"Historical note"}).json()
        appointment = self.client.post("/api/calendar/events", json={"title":"Deletion-safe meeting", "date":"2026-09-20",
            "time":"10:00", "associatedType":"Lead", "associatedId":lead["id"]}).json()
        self.client.post(f"/api/leads/{lead['id']}/convert", json={})
        deleted = self.client.delete(f"/api/leads/{lead['id']}")
        self.assertEqual(deleted.status_code, 200)
        self.assertGreaterEqual(deleted.json()["affected"]["notesArchived"], 1)
        self.assertEqual(self.client.get(f"/api/leads/{lead['id']}").status_code, 404)
        notes = self.client.get("/api/notes").json()
        archived = [n for n in notes if n.get("archivedLeadId") == lead["id"]]
        self.assertTrue(archived and all(n["archived"] for n in archived))
        archived_event = next(event for event in server.load_db()["calendarEvents"] if event["id"] == appointment["id"])
        self.assertEqual(archived_event["status"], "Archived")
        self.assertFalse(archived_event.get("taskId"))

    def test_lead_edit_and_bulk_work_management_sync(self):
        lead = self.client.post("/api/leads", json={"firstName":"Work","lastName":"User","mobile":"+919999000002",
            "email":"work@test.invalid","organization":"Work Org","nextAction":"Initial call","nextActionDate":"2026-09-10"}).json()
        edited = self.client.put(f"/api/leads/{lead['id']}", json={"name":"Work User Edited","mobile":"+919999000003","expiryDate":"2027-01-01","assignedTo":"Aarav Sharma"})
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.json()["assignedTo"], "Aarav Sharma")
        contacts = self.client.get("/api/contacts").json()
        self.assertTrue(any(c.get("leadId") == lead["id"] and c.get("phone") == "+919999000003" for c in contacts))
        bulk = self.client.post("/api/leads/bulk-update", json={"ids":[lead["id"]],"updates":{"nextAction":"Customer meeting","nextActionDate":"2026-09-12","priority":"High"}})
        self.assertEqual(bulk.json()["updatedCount"], 1)
        tasks = self.client.get("/api/tasks").json()
        self.assertTrue(any(t.get("associatedId") == lead["id"] and t.get("title") == "Customer meeting" for t in tasks))

    def test_master_record_editing_customer_360_and_audit(self):
        lead = self.client.post("/api/leads", json={"firstName":"Master","lastName":"Record","mobile":"+919900000001","organization":"Master Org"}).json()
        conversion = self.client.post(f"/api/leads/{lead['id']}/convert", json={"customerName":"Master Customer","organization":"Master Org","expiryDate":"2027-01-01"}).json()
        customer = conversion["customer"]
        edited = self.client.put(f"/api/customers/{customer['id']}", json={"email":"customer@example.com","assignedTo":"John Parker"})
        self.assertEqual(edited.status_code, 200)
        view = self.client.get(f"/api/customers/{customer['id']}").json()
        self.assertEqual(view["email"], "customer@example.com")
        self.assertTrue(any(c.get("customerId") == customer["id"] for c in view["contacts"]))
        self.assertTrue(self.client.get(f"/api/audit-logs?entityId={customer['id']}").json())

    def test_document_versioning_backup_and_health(self):
        first = self.client.post("/api/documents?associatedId=L1&category=KYC&filename=kyc.pdf", content=b"%PDF-first", headers={"Content-Type":"application/pdf"})
        second = self.client.post("/api/documents?associatedId=L1&category=KYC&filename=kyc.pdf", content=b"%PDF-second", headers={"Content-Type":"application/pdf"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.json()["version"], 2)
        self.assertEqual(self.client.get(f"/api/documents/{first.json()['id']}/content").content, b"%PDF-first")
        backup = self.client.post("/api/backups")
        self.assertEqual(backup.status_code, 200)
        self.assertTrue(self.client.get("/api/backups").json())
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")

    def test_archive_restore_duplicate_merge_and_report(self):
        one = self.client.post("/api/leads", json={"firstName":"Duplicate","lastName":"One","mobile":"+919900000002"}).json()
        two = self.client.post("/api/leads", json={"firstName":"Duplicate","lastName":"Two","mobile":"+919900000002"}).json()
        groups = self.client.get("/api/data-quality/lead-duplicates").json()
        self.assertTrue(any(len(group["records"]) >= 2 for group in groups))
        merged = self.client.post(f"/api/leads/{one['id']}/merge/{two['id']}")
        self.assertEqual(merged.status_code, 200)
        archived = self.client.post(f"/api/leads/{one['id']}/archive")
        self.assertEqual(archived.status_code, 200)
        self.assertEqual(self.client.post(f"/api/archived-leads/{one['id']}/restore").status_code, 200)
        report = self.client.get("/api/reports/operations").json()
        self.assertIn("employeeActivity", report)

    def test_policy_document_checklist_and_notification_workflow(self):
        lead = self.client.post("/api/leads", json={"firstName":"Issue","lastName":"Flow","mobile":"+919900000003","expiryDate":"2027-01-01"}).json()
        policy = self.client.post(f"/api/leads/{lead['id']}/convert", json={"insurer":"Alpha","startDate":"2026-01-01","expiryDate":"2027-01-01"}).json()["policy"]
        incomplete = self.client.post(f"/api/policies/{policy['id']}/issue", json={"policyNumber":"P-1","documentChecklist":{"proposalForm":True,"kyc":True,"payment":False,"schedule":True}})
        self.assertEqual(incomplete.status_code, 422)
        issued = self.client.post(f"/api/policies/{policy['id']}/issue", json={"policyNumber":"P-1","documentChecklist":{"proposalForm":True,"kyc":True,"payment":True,"schedule":True}})
        self.assertEqual(issued.json()["issuanceStatus"], "Issued")
        notification = self.client.post("/api/notifications/run-escalations").json()
        if notification["notifications"]:
            item = notification["notifications"][0]
            updated = self.client.put(f"/api/notifications/{item['id']}", json={"read":True,"assignedTo":"John Parker","snoozedUntil":"2026-10-01"})
            self.assertTrue(updated.json()["read"])

    def test_lead_source_connect_test_ingest_and_deduplicate(self):
        providers = self.client.get("/api/channel-providers").json()
        self.assertTrue(any(item["provider"] == "google" for item in providers))
        created = self.client.post("/api/channels", json={
            "provider":"google", "name":"Google Motor Leads",
            "defaults":{"policyType":"Commercial Motor"}
        })
        self.assertEqual(created.status_code, 200)
        channel = created.json()
        self.assertTrue(channel["credentials"]["googleKey"])
        self.assertNotIn("•", channel["credentials"]["googleKey"])

        first = self.client.post(f"/api/channels/{channel['id']}/test")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["events"][0]["status"], "Lead created")
        lead_id = first.json()["events"][0]["leadId"]
        lead = self.client.get(f"/api/leads/{lead_id}").json()["lead"]
        self.assertEqual(lead["sourceChannelId"], channel["id"])
        self.assertEqual(lead["policyType"], "Commercial Motor")
        self.assertTrue(any(t.get("associatedId") == lead_id for t in self.client.get("/api/tasks").json()))

        repeated = self.client.post(f"/api/channels/{channel['id']}/test")
        self.assertEqual(repeated.json()["events"][0]["status"], "Duplicate")
        events = self.client.get(f"/api/channel-events?channelId={channel['id']}").json()
        self.assertEqual(len(events), 2)

    def test_message_template_archive_restore_and_permanent_delete(self):
        created = self.client.post("/api/communication-templates", json={
            "name": "Test renewal reminder", "channel": "Email",
            "subject": "Renewal due", "content": "Your policy is due for renewal."
        }).json()
        template_id = created["id"]
        self.assertTrue(any(t["id"] == template_id for t in self.client.get("/api/communication-templates").json()))

        self.assertEqual(self.client.delete(f"/api/communication-templates/{template_id}").status_code, 200)
        self.assertFalse(any(t["id"] == template_id for t in self.client.get("/api/communication-templates").json()))
        archived = self.client.get("/api/communication-templates?includeArchived=true").json()
        self.assertEqual(next(t for t in archived if t["id"] == template_id)["status"], "Archived")

        restored = self.client.post(f"/api/communication-templates/{template_id}/restore")
        self.assertEqual(restored.json()["status"], "Active")
        self.assertTrue(any(t["id"] == template_id for t in self.client.get("/api/communication-templates").json()))

        self.client.delete(f"/api/communication-templates/{template_id}")
        deleted = self.client.delete(f"/api/communication-templates/{template_id}?permanent=true")
        self.assertEqual(deleted.json()["status"], "deleted")
        self.assertFalse(any(t["id"] == template_id for t in self.client.get("/api/communication-templates?includeArchived=true").json()))

    def test_sms_is_removed_saved_filters_paginate_and_reports_segment(self):
        sms_template = self.client.post("/api/communication-templates", json={
            "name":"Unsupported", "channel":"SMS", "content":"Do not send"
        })
        self.assertEqual(sms_template.status_code, 422)
        sms_message = self.client.post("/api/communications", json={
            "associatedId":"L1", "recipient":"+910000000000", "channel":"SMS", "content":"Do not send"
        })
        self.assertEqual(sms_message.status_code, 422)

        saved = self.client.post("/api/saved-filters", json={
            "name":"My overdue work", "module":"leads", "criteria":{"quickFilter":"overdue"}
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get("/api/saved-filters?module=leads").json()[0]["name"], "My overdue work")
        page = self.client.get("/api/leads?paginated=true&page=1&pageSize=2").json()
        self.assertEqual(len(page["items"]), 2)
        self.assertGreaterEqual(page["totalPages"], 2)
        report = self.client.get("/api/reports/operations").json()
        self.assertIn("byLeadSource", report)
        self.assertIn("premiumByInsurer", report)

    def test_relational_repair_service_request_and_scheduler(self):
        db = server.load_db()
        db["policies"] = [{"id":"P_ORPHAN", "leadId":"L1", "customerId":"", "customerName":"Vikram Mehta",
                           "organization":"Mehta Logistics Ltd", "policyType":"Motor", "policyNumber":"LEGACY-1",
                           "issuanceStatus":"Issued", "status":"Active", "insurer":"", "startDate":"", "expiryDate":"2027-01-01"}]
        server.save_db(db)
        repaired = self.client.post("/api/admin/repair-relations?dryRun=false")
        self.assertEqual(repaired.status_code, 200)
        self.assertEqual(repaired.json()["after"]["policiesWithoutCustomer"], 0)
        policy = self.client.get("/api/policies").json()[0]
        self.assertEqual(policy["issuanceStatus"], "Needs Review")

        request = self.client.post("/api/service-requests", json={
            "customerId":policy["customerId"], "policyId":policy["id"], "requestType":"Endorsement",
            "description":"Correct the insured address using the verified registered office.", "dueDate":"2026-09-05"
        })
        self.assertEqual(request.status_code, 200)
        self.assertTrue(self.client.get(f"/api/endorsements?policyId={policy['id']}").json())

        communication = self.client.post("/api/communications", json={
            "associatedId":"L1", "recipient":"client@example.invalid", "channel":"Email", "content":"Follow-up",
            "scheduledAt":"2020-01-01T00:00:00Z"
        }).json()
        jobs = self.client.post("/api/admin/jobs/run")
        self.assertEqual(jobs.status_code, 200)
        sent = next(item for item in self.client.get("/api/communications").json() if item["id"] == communication["id"])
        self.assertEqual(sent["status"], "Not sent — no sender connected")

    def test_restore_replaces_changed_data_and_keeps_safety_copy(self):
        backup = self.client.post("/api/backups").json()
        self.client.post("/api/leads", json={"firstName":"Temporary", "mobile":"+919812345678"})
        self.assertTrue(any(item["name"] == "Temporary" for item in self.client.get("/api/leads").json()))
        restored = self.client.post(f"/api/backups/{backup['name']}/restore")
        self.assertEqual(restored.status_code, 200)
        self.assertFalse(any(item["name"] == "Temporary" for item in self.client.get("/api/leads").json()))
        self.assertTrue(restored.json()["safetyBackup"])

    def test_audit_chain_and_scheduler_concurrency_guard(self):
        self.client.post("/api/leads", json={"firstName":"Audit", "mobile":"+919812345679"})
        integrity = self.client.get("/api/admin/audit-integrity").json()
        self.assertTrue(integrity["valid"])
        self.assertGreater(integrity["signedEvents"], 0)
        with server.crm_store.scheduler_lock("default") as acquired:
            self.assertTrue(acquired)
            skipped = self.client.post("/api/admin/jobs/run").json()
            self.assertEqual(skipped["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
