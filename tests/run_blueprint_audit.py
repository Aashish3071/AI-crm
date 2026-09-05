"""Run the blueprint comparison and generate a reproducible evidence register.

Exit 1 means demonstrated product failures; exit 2 means incomplete execution.
Never point this runner at a deployed/live CRM. All mutations use temporary stores.
"""
import argparse
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import re
import sys
import time
import unittest
from unittest.mock import patch

from starlette.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]

BASELINE_MAPPING = {
    "test_dashboard_lead_conversion_and_customer_360": ["M01.1", "M06.1", "M08.1", "M09.1"],
    "test_mobile_navigation_and_lead_dialog_remain_usable": ["M01.1", "M28.3"],
    "test_calendar_books_linked_meeting_and_follow_up": ["M13.1"],
    "test_rejected_task_save_keeps_form_and_shows_error": ["M12.2"],
    "test_auth_csrf_roles_and_company_isolation": ["M02.1", "M02.3"],
    "test_lead_source_connect_test_ingest_and_deduplicate": ["M03.1"],
    "test_lead_edit_and_bulk_work_management_sync": ["M05.2", "M06.2"],
    "test_canonical_task_rename_date_and_completion_update_lead": ["M06.2", "M12.1"],
    "test_calendar_canonical_projection_and_two_way_sync": ["M13.1", "M08.3"],
    "test_calendar_conflicts_reminders_archive_and_repair": ["M13.2", "M14.1"],
    "test_task_and_calendar_moves_cannot_bypass_conflicts": ["M13.2", "M06.2"],
    "test_conflicts_across_midnight_and_invalid_duration": ["M13.2"],
    "test_bulk_assignment_moves_appointment_and_notification_together": ["M05.2", "M14.1"],
    "test_merge_relinks_appointments_and_converted_customer": ["M26.1"],
    "test_archive_restore_does_not_reopen_previously_archived_tasks": ["M26.2"],
    "test_legacy_same_day_task_is_not_mistaken_for_next_action": ["M13.1"],
    "test_lead_delete_cascades_but_archives_notes": ["M15.1", "M26.2"],
    "test_master_record_editing_customer_360_and_audit": ["M09.1", "M10.1", "M11.1", "M27.1"],
    "test_policy_renewal_and_quotation_flow": ["M18.1", "M18.3"],
    "test_end_to_end_lead_to_renewed_policy": ["M08.1", "M17.3", "M18.2", "M18.3"],
    "test_policy_document_checklist_and_notification_workflow": ["M17.2", "M17.3", "M14.1"],
    "test_relational_repair_service_request_and_scheduler": ["M19.1", "M19.2", "M14.3"],
    "test_opt_out_blocks_delivery": ["M21.2"],
    "test_whatsapp_delivery_failure_updates_timeline_and_notifies_owner": ["M20.2", "M14.1"],
    "test_message_template_archive_restore_and_permanent_delete": ["M21.1"],
    "test_sms_is_removed_saved_filters_paginate_and_reports_segment": ["M20.1", "M23.1", "M23.2", "M24.2"],
    "test_document_versioning_backup_and_health": ["M22.1", "M28.1"],
    "test_restore_replaces_changed_data_and_keeps_safety_copy": ["M28.1"],
    "test_audit_chain_and_scheduler_concurrency_guard": ["M27.1", "M14.3"],
    "test_concurrent_writers_reject_stale_snapshot_without_lost_update": ["M28.1"],
    "test_corrupt_database_is_not_overwritten_with_demo_records": ["M28.1"],
    "test_archive_restore_duplicate_merge_and_report": ["M26.1", "M26.2"],
}

JOURNEYS = {
    "J01": ["M03.1", "M03.2", "M05.3", "M06.1", "M07.2", "M08.2", "M16.3", "M17.2"],
    "J02": ["M16.1", "M18.1", "M18.2", "M18.3", "M24.3"],
    "J03": ["M09.1", "M09.3", "M19.1", "M19.2", "M19.3", "M22.1"],
    "J04": ["M05.2", "M12.1", "M13.2", "M14.1", "M14.2", "M14.3"],
    "J05": ["M04.1", "M04.2", "M04.3", "M26.1", "M26.2", "M26.3", "M27.2", "M28.1"],
    "J06": ["M02.1", "M02.2", "M02.3", "M23.2", "M27.3"],
    "J07": ["M08.1", "M18.2", "M20.2", "M22.2", "M28.1", "M28.2"],
}


class EvidenceResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.cases = []
        self.current = None
        self.started = 0
        self.subtest_failures = []

    def startTest(self, test):
        super().startTest(test)
        self.current = test.id()
        self.started = time.monotonic()
        self.subtest_failures = []

    def record(self, test, status, message=""):
        method_name = getattr(test, "_testMethodName", "")
        method = getattr(test, method_name, None)
        criteria = list(getattr(method, "criteria", BASELINE_MAPPING.get(method_name, [])))
        try:
            source = str(Path(inspect.getsourcefile(method)).relative_to(ROOT))
            line = inspect.getsourcelines(method)[1]
        except (TypeError, ValueError):
            source, line = "", 0
        # A setup failure and cleanup failure are two errors in one test case,
        # not two executed tests. Retain both diagnostics without inflating counts.
        existing = next((case for case in self.cases if case["test"] == test.id()), None)
        if existing:
            existing["message"] = "\n".join(filter(None, [existing["message"], message]))
            priority = {"PASS": 0, "BLOCKED": 1, "FAIL": 2, "ERROR": 3}
            if priority[status] > priority[existing["status"]]:
                existing["status"] = status
            return
        self.cases.append({"test": test.id(), "status": status, "criteria": criteria,
            "completeCriterion": getattr(method, "complete_criterion", False),
            "message": message, "source": source, "line": line,
            "seconds": round(time.monotonic() - self.started, 3)})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "PASS")

    def addFailure(self, test, error):
        super().addFailure(test, error)
        self.record(test, "FAIL", str(error[1]))

    def addError(self, test, error):
        super().addError(test, error)
        self.record(test, "ERROR", f"{error[0].__name__}: {error[1]}")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "BLOCKED", reason)

    def addSubTest(self, test, subtest, error):
        super().addSubTest(test, subtest, error)
        if error:
            self.subtest_failures.append(f"{subtest}: {error[1]}")

    def stopTest(self, test):
        if self.subtest_failures:
            self.record(test, "FAIL", "\n".join(self.subtest_failures))
        super().stopTest(test)


def inventory_routes():
    source = (ROOT / "pipecat_server.py").read_text()
    routes = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and isinstance(dec.func.value, ast.Name):
                if dec.func.value.id == "app" and dec.func.attr in {"get", "post", "put", "delete", "patch"}:
                    routes.append({"method": dec.func.attr.upper(), "path": ast.literal_eval(dec.args[0]),
                                   "handler": node.name, "line": node.lineno})
    return routes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="Also run disposable authenticated Playwright suites")
    args = parser.parse_args()
    if os.environ.get("CRM_E2E_BASE_URL"):
        raise SystemExit("Refusing deployed target: unset CRM_E2E_BASE_URL for this audit")
    if os.environ.get("DATABASE_URL"):
        raise SystemExit("Refusing configured database: this audit requires isolated local storage")
    blueprint = (ROOT / "uat/CRM_BLUEPRINT.md").read_text()
    criteria = {cid: {"id": cid, "requirement": text, "status": "NOT VERIFIED", "evidence": []}
                for cid, text in re.findall(r"^- (M\d{2}\.\d): (.+)$", blueprint, re.M)}
    modules = dict(re.findall(r"^### (M\d{2}) — (.+)$", blueprint, re.M))
    if len(criteria) != 84 or len(modules) != 28:
        raise SystemExit("Blueprint register mismatch; review criterion enumeration before running")
    suites = ["test_insurance_operations", "test_security_foundation", "tests.test_workflow_integrity", "tests.test_blueprint_acceptance"]
    if os.environ.get("CRM_BLUEPRINT_PG_DSN"):
        suites.append("tests.test_blueprint_postgres")
    if args.browser:
        suites += ["tests.test_browser_flows", "tests.test_blueprint_browser"]
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)) for name in suites)
    result = EvidenceResult()
    requests = []
    original_request = TestClient.request
    def tracked(client, method, url, **kwargs):
        response = original_request(client, method, url, **kwargs)
        requests.append({"test": result.current, "method": method.upper(), "path": str(url).split("?")[0], "status": response.status_code})
        return response
    with patch.object(TestClient, "request", tracked):
        suite.run(result)
    for case in result.cases:
        for cid in case["criteria"]:
            if cid not in criteria:
                raise RuntimeError(f"Test references unknown criterion {cid}")
            criteria[cid]["evidence"].append(case)
    for row in criteria.values():
        evidence = row["evidence"]
        statuses = {e["status"] for e in evidence}
        if "FAIL" in statuses:
            row["status"] = "FAIL"
        elif "ERROR" in statuses:
            row["status"] = "NOT VERIFIED"
        elif any(e["status"] == "PASS" and e["completeCriterion"] for e in evidence):
            row["status"] = "PASS"
        elif "PASS" in statuses:
            row["status"] = "PARTIAL"
        elif "BLOCKED" in statuses:
            row["status"] = "BLOCKED"
    startup_tests = {"test_dashboard_lead_conversion_and_customer_360", "test_mobile_navigation_and_lead_dialog_remain_usable"}
    if startup_tests.issubset({e["test"].split(".")[-1] for e in criteria["M01.1"]["evidence"] if e["status"] == "PASS"}):
        criteria["M01.1"]["status"] = "PASS"
    routes = inventory_routes()
    for route in routes:
        regex = "^" + re.sub(r"\{[^}]+\}", "[^/]+", route["path"]) + "$"
        hits = [r for r in requests if r["method"] == route["method"] and re.match(regex, r["path"])]
        route["observedStatusCodes"] = sorted({r["status"] for r in hits})
        route["observedRequests"] = len(hits)
        route["tests"] = sorted({r["test"] for r in hits if r["test"]})
    journeys = []
    for jid, required in JOURNEYS.items():
        failures = [cid for cid in required if criteria[cid]["status"] == "FAIL"]
        journeys.append({"id": jid, "status": "FAIL" if failures else "PARTIAL", "requirements": required,
                         "failedRequirements": failures, "note": "Derived from component evidence; not proof of one uninterrupted production journey"})
    product_files = ["pipecat_server.py", "crm_store.py", "crm_security.py", "crm_storage.py", "crm_worker.py", "web/app.js", "web/index.html"]
    output = {"generatedAt": datetime.now(timezone.utc).isoformat(), "blueprint": "uat/CRM_BLUEPRINT.md",
        "blueprintSha256": hashlib.sha256(blueprint.encode()).hexdigest(),
        "productSha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in product_files},
        "environment": "Disposable JSON companies; authenticated API security/browser suites; no provider sends" +
            ("; real disposable PostgreSQL adapter checks" if os.environ.get("CRM_BLUEPRINT_PG_DSN") else ""),
        "testCounts": dict(Counter(c["status"] for c in result.cases)),
        "criterionCounts": dict(Counter(c["status"] for c in criteria.values())),
        "modules": modules, "criteria": list(criteria.values()), "journeys": journeys,
        "tests": result.cases, "routes": routes,
        "routeEvidenceNote": "Observed TestClient method/path requests only. Browser requests are not counted. A route hit is not full functional coverage.",
        "browserIncluded": args.browser}
    (ROOT / "uat/blueprint-results.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    lines = ["# Blueprint Assessment", "", f"Generated: {output['generatedAt']}", "",
        "Decision: the current CRM does not yet meet the commercial blueprint. This report records demonstrated gaps without modifying the product to conceal them.", "",
        f"Test cases: {output['testCounts']}. Criterion register: {output['criterionCounts']}.", "",
        "Read the [target blueprint](CRM_BLUEPRINT.md) first. [Machine-readable evidence](blueprint-results.json) contains source hashes, individual results and the endpoint observation inventory.", "",
        "Passing scenarios demonstrate only their assertions. PARTIAL is not a release pass. FAIL means a reproducible violation. BLOCKED names an unavailable external prerequisite. NOT VERIFIED means missing/errored execution. Every one of the 84 criteria is listed below.", "",
        "## Highest-priority remediation", "",
        "1. Access and identity: bind Profile to the session; prevent editing another user's profile; derive note authorship from the authenticated actor.",
        "2. Policy and renewal integrity: reject invalid terms/amounts, enforce actual issuance evidence, validate quote ownership/validity and make renewal completion idempotent.",
        "3. Relationship continuity: unify source/import next-action creation, synchronize conversion/master changes, protect edited imports and complete the deletion/service graph.",
        "4. Work and communication: finish service/renewal alerts, manager escalation, quote calendar validity, consent continuity and safe send/callback retries.",
        "5. Operator experience: deal/note editing gaps, task search, truthful dashboard calculations, report periods and configuration-driven validation.",
        "6. Production proof: complete authorized provider sandboxes, PostgreSQL/object storage/scanner testing, worker crash/retry, accessibility/load and broker UAT.", "",
        "## Journey verdicts", ""]
    for journey in journeys:
        lines.append(f"- {journey['id']}: **{journey['status']}**. Failed component criteria: {', '.join(journey['failedRequirements']) or 'none demonstrated'}. This is a component-derived verdict, not a completed production journey.")
    lines += ["", "## Criterion-by-criterion register", ""]
    for module, title in modules.items():
        lines += [f"### {module} — {title}", ""]
        for row in criteria.values():
            if not row["id"].startswith(module + "."):
                continue
            lines += [f"- **{row['id']} — {row['status']}**: {row['requirement']}"]
            if not row["evidence"]:
                lines += ["  - Evidence: no sufficient automated test executed for this criterion; manual/source inspection does not establish a pass."]
            for case in row["evidence"]:
                label = case["test"].split(".")[-1]
                message = re.sub(r"\s+", " ", case["message"])[:450]
                link = f"[test](../{case['source']}#L{case['line']})" if case["source"] else "test runner"
                lines.append(f"  - {case['status']}: `{label}` ({link}). {message}")
        lines.append("")
    untouched = [r for r in routes if not r["observedRequests"]]
    lines += ["## Endpoint observation scope", "",
        f"Registered routes: {len(routes)}; observed by API tests: {len(routes)-len(untouched)}; unobserved by API tests: {len(untouched)}.", "",
        output["routeEvidenceNote"], "", "Unobserved routes remain explicitly unverified at the request level; some may be visited in browser tests. AI advisor routes are outside the CRM acceptance boundary.", ""]
    lines += [f"- `{r['method']} {r['path']}` — `{r['handler']}`, pipecat_server.py:{r['line']}" for r in untouched]
    lines += ["", "## Repeat the comparison", "", "```bash", "PYTHONWARNINGS=ignore .venv/bin/python3 -m tests.run_blueprint_audit --browser", "```", "",
        "The runner refuses a deployed browser target or configured database. It writes only the evidence files and disposable test data. Exit 1 is intentional when blueprint defects remain; no expected-failure decorators hide them. Product files are unchanged by this assessment.", "",
        "External and manual acceptance remains necessary. A full keyboard/screen-reader audit, realistic load run, provider round trip and combined database/document recovery were not executed here. Existing green smoke tests must not be interpreted as proof that these checks passed.", "",
        "Optional PostgreSQL adapter tests run when CRM_BLUEPRINT_PG_DSN names a designated disposable localhost database named blueprint. These cover adapter transactions/rollback, competing writers, company isolation, archived targets and scheduler locks; they do not certify the full deployment or combined recovery."]
    (ROOT / "uat/CRM_BLUEPRINT_ASSESSMENT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"tests": output["testCounts"], "criteria": output["criterionCounts"],
        "routesObserved": len(routes)-len(untouched), "routesTotal": len(routes), "report": "uat/CRM_BLUEPRINT_ASSESSMENT.md"}))
    return 1 if any(c["status"] == "FAIL" for c in result.cases) else 2 if any(c["status"] in {"ERROR", "BLOCKED"} for c in result.cases) else 0


if __name__ == "__main__":
    sys.exit(main())
