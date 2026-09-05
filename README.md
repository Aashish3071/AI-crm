# InsureCRM

InsureCRM is a CRM-first operating system for commercial insurance brokers. It manages an enquiry from lead capture through follow-up, customer conversion, quotation, policy issuance, servicing and renewal. AI voice calling is intentionally outside the current release boundary.

## Current release

The commercial readiness standard is defined in [CRM Blueprint v2](uat/CRM_BLUEPRINT_V2.md), which supersedes [v1](uat/CRM_BLUEPRINT.md) without lowering any criterion in it. v2 adds record-level visibility as a release requirement, an honest-module-boundary standard, and a split dashboard numeric contract; it also records the measured position (43 of 89 acceptance tests passing on 5 September 2026) and the build order derived from it. v1 remains, covering 28 modules, 84 acceptance criteria and seven cross-module journeys. Read the [current assessment](uat/CRM_BLUEPRINT_ASSESSMENT.md) before treating the feature list below as verified commercial capability. The expanded acceptance tests expose failures that earlier smoke tests did not cover. This assessment changes test/documentation files only; it does not silently fix or waive the failures.

Repeat the comparison on disposable data:

```bash
PYTHONWARNINGS=ignore .venv/bin/python3 -m tests.run_blueprint_audit --browser
```

The runner refuses a deployed browser target or configured application database, generates a criterion-by-criterion report and `uat/blueprint-results.json`, and exits nonzero when failures remain. Passing screen navigation is not full module acceptance; provider, production recovery and human accessibility/UAT checks remain separately classified.

Optional real PostgreSQL adapter checks use `CRM_BLUEPRINT_PG_DSN` pointing to a designated disposable database named `blueprint` on localhost. They test competing writes, rollback, company isolation, archive references and scheduler locking; they do not certify combined database/document recovery. Install the declared CRM dependencies before running them. Never supply a live database or real customer records to acceptance tests.

The assessment is snapshot-specific: compare its recorded product hashes with the current files before relying on its results. Product edits after a run require a new assessment.

### Identity truthfulness and dashboard layout — 5 September 2026

Profile was bound to a shared company setting, so every user saw and could edit whichever team member that setting pointed at — signed in as one person, editing another. It now resolves the signed-in session; attempting to act as another user is refused with an explanation rather than ignored. Note authorship derives from the session instead of a caller-supplied label, and the legacy bulk-import path carries the same permission as the current one. All four identity acceptance criteria pass; blueprint acceptance moved from 43 to 47 passing.

Static assets are versioned by modification time and the shell is served no-cache. A hand-typed cache key had not been bumped, so browsers kept old CSS and JavaScript: fixes that were shipped, including the lead-source back button, appeared missing.

The dashboard is two columns rather than one long scroll, tiles align their figure above its label, and the work-trend chart has a 7/14/30-day range control with thirty days of history behind it. Connecting a lead source that already exists is now refused by the server, not only warned about in the browser; a genuine second ad account is added explicitly. Profile lives in Settings, so the sidebar footer is a dropdown containing sign out.

### Dashboard, visibility and cleanup — 5 September 2026

The dashboard was rebuilt around the day's work. Four status tiles lead: overdue, due today, completed today and the next seven days. "My day" lists what actually needs attention, overdue first. The renewal radar, a seven-day scheduled-versus-completed chart, pipeline by stage, the week ahead and the audit activity feed follow. Every panel can be reordered or hidden per user; the arrangement is stored against the signed-in identity and does not affect anyone else.

Three dashboard calculations were wrong and are corrected: "tasks due today" returned every incomplete task regardless of date; open pipeline value included Won and Lost business and parsed premiums by concatenating digits out of a formatted string; and "won this month" counted all time. Task completion time is now recorded, so "completed today" reflects when work finished rather than when it was due.

Record-level visibility is enforced. Administrators and auditors see the whole company book, a manager sees themselves plus their reports, and everyone else sees only records assigned to them — applied to lead lists, single-lead fetches, tasks, deals, policies, renewals, customers, the dashboard and the calendar. Requesting another broker's record by ID returns 404.

Sign out is a labelled action beside My profile rather than an unlabelled icon. Activity notes can be archived or deleted from always-visible controls, with a shared confirmation dialog that explains which is reversible. Connecting a lead source that is already connected warns before creating a second one.

The abandoned Frappe/Node prototype was removed (`frappe_extension/`, `server.js`, `frappeClient.js`, `callManager.js`, `voiceAgent.js`, `test_engine.js`, `package.json`, `public/`) after confirming nothing in the running application imported it. Spreadsheet import deduplication was O(rows x leads); an index reduced an 800-row import against 3,000 leads from 4,086 ms to 3.8 ms.

### Workflow cleanup — 5 September 2026

Single and bulk lead edits now share owner/next-action synchronization. Task renames, dates and completion update the canonical lead action by ID. Calendar moves reuse task/appointment validation, including cross-midnight conflicts. Calendar projection lookup uses indexes rather than scanning every task and policy for every lead, and legacy deduplication requires matching activity and date rather than date alone.

Lead merges transfer operational references including appointments and converted customers. Leads linked to different customers cannot be merged implicitly. Archive/restore preserves tasks that were already archived. Notifications follow the work owner and resolve when work completes, is removed or is rescheduled. Task links navigate to the correct module; task/note forms show rejected saves and retain entered information. The Tasks screen includes a visible scheduling button.

Local JSON saves use a cross-process file lock and revision check so stale writes return a conflict instead of silently overwriting another change. Unreadable data is never replaced by seed data. Backup restoration commits against the current revision. PostgreSQL writes remove dependent relationship rows before replacing records and resolve references to archived parents. Production PostgreSQL execution and provider delivery still require deployment tests; the local suites do not certify them.

Lead creation/editing, stage transitions, task and note saves now use the shared authenticated API helper. Previously some used direct requests without the CSRF token, which could fail silently after login. The isolated browser suite now runs with authentication enabled, including lead creation, stage changes, conversion, calendar booking and rejected-save feedback.

The working CRM now includes:

- Dashboard-first startup, global search and guided onboarding.
- Lead capture, spreadsheet import, assignment, list/Kanban views, pagination and personal saved views.
- Required next actions and dates, tasks, calls/meetings/site visits on a timezone-aware calendar, reminders, notifications, snooze and escalation. A booked appointment is shown once while its linked task keeps the work queue synchronized in both directions.
- Editable customer, organization, contact, deal and policy records.
- Customer 360° with contacts, multiple policies, renewals, quotations, tasks, notes, documents, communications and audit history.
- Guided lead conversion into a customer, organization, contacts, won deal and draft policy.
- Backend premium calculations: `tax amount = net premium × tax rate ÷ 100`; `total premium = net premium + tax amount`.
- Policy issuance gated by insurer/dates/final policy number and proposal, KYC, payment and schedule evidence.
- Renewal generation, competing quotation comparison/selection and successor-policy completion.
- Insurance servicing requests for endorsements, claim assistance, certificates, policy copies, cancellation and reinstatement.
- Email and WhatsApp communication history, reusable templates, scheduling, consent/opt-out controls, provider status and delivery-failure notifications.
- Progressive lead-source setup for Meta, Google Ads, LinkedIn, WhatsApp, email, Zapier and signed custom webhooks, including OAuth foundations where the provider supports it.
- Document type/signature validation, malware scanning in production, company-separated object keys, checksums and versions.
- Duplicate detection/merge, archive/restore, field-mapped imports with rejection reports, operations reporting and configurable products/stages/insurers.
- Secure login, CSRF protection, roles, immediate deactivation, company isolation, login throttling and browser security headers.
- PostgreSQL persistence with company keys, optimistic revisions, transactions and constrained cross-record relationship rows.
- PII-redacted, actor/company-labelled and HMAC-chained audit events.
- Separate durable scheduler worker with per-company locking.
- Repeatable Docker deployment with PostgreSQL, private S3-compatible storage, ClamAV, worker, health check and daily database backups.

SMS has been removed completely from active CRM functionality. The API rejects SMS templates and SMS communication records, the UI offers only Email and WhatsApp, and legacy SMS templates are retired during relationship repair.

## End-to-end workflow

```text
Lead source / direct entry / spreadsheet
                  |
                  v
        Lead + contact + organization
                  |
        next action + task + calendar
                  |
          underwriting / quotation
                  |
                  v
Customer + won deal + draft policy
                  |
      issuance evidence checklist
                  |
                  v
             Issued policy
                  |
       servicing + communication
                  |
        renewal + quote comparison
                  |
                  v
       successor policy / lost / lapsed
```

Stable IDs are the source of truth between modules. Names are labels, not relationships. Deleting a lead removes the connected operational graph—customer, policies, renewals, quotations, tasks, communications, consents, notifications and matching contact/deal records. Its notes remain as archived historical evidence. Organizations are removed only if no surviving record uses them.

Calendar appointments can be linked to leads, customers, policies, renewals, deals, organizations, contacts and service requests. Booking can create both an appointment and a post-meeting follow-up. Editing the appointment or its canonical linked task updates the other record transactionally; completion, archive, lead conversion, reassignment and cascade deletion preserve relationship integrity. Deal close dates, quotation validity, policy renewals, service deadlines and scheduled messages are read-only calendar projections and are not duplicated into appointments.

## Repository layout

| Path | Purpose |
| --- | --- |
| `pipecat_server.py` | FastAPI CRM domain/API service |
| `crm_security.py` | Passwords, sessions, CSRF, roles and company identity context |
| `crm_store.py` | PostgreSQL transactional record/link adapter and scheduler lock |
| `crm_storage.py` | Local-development and S3-compatible document adapter |
| `crm_worker.py` | Durable reminder, escalation and scheduled-message worker |
| `migrations/001_tenant_record_store.sql` | PostgreSQL record, relationship and identity constraints |
| `migrate_to_postgres.py` | Guarded legacy JSON-to-PostgreSQL migration |
| `web/` | Accessible responsive single-page CRM |
| `test_insurance_operations.py` | Lifecycle, recovery, servicing and integration tests |
| `test_security_foundation.py` | Authentication, CSRF, roles, revocation and tenant-isolation tests |
| `uat/` | Anonymized broker acceptance scenarios and sign-off record |
| `Dockerfile`, `docker-compose.yml` | Repeatable production runtime |
| `tests/test_browser_flows.py`, `requirements-test.txt` | Isolated Playwright browser acceptance suite |

The older Node/Frappe/voice files remain outside the CRM production image. They are retained only as source material for a later integration phase and do not run in this release.

## Local development

Prerequisites: Python 3.11+ and a modern browser.

```bash
.venv/bin/pip install -r requirements-crm.txt
.venv/bin/python3 -m uvicorn pipecat_server:app --host 127.0.0.1 --port 8080 --reload
```

Open `http://127.0.0.1:8080/`. On the first authenticated launch, the CRM asks for the company and first administrator. Local JSON storage is supported only for development and migration rehearsals.

To use the existing demonstration workspace without authentication during automated local checks only:

```bash
AUTH_DISABLED=1 .venv/bin/python3 -m uvicorn pipecat_server:app --host 127.0.0.1 --port 8080
```

## Automated verification

```bash
.venv/bin/python3 -m py_compile pipecat_server.py crm_security.py crm_store.py crm_storage.py crm_worker.py migrate_to_postgres.py
.venv/bin/python3 -m unittest -v test_insurance_operations.py test_security_foundation.py tests.test_workflow_integrity
```

The suite covers lead-to-renewal lifecycle calculations, issuance evidence, relationship repair, cascading deletion/note retention, Customer 360°, master editing, lead-source ingestion/deduplication, Email/WhatsApp-only enforcement, WhatsApp delivery-failure callbacks and notification creation, template archive/restore, servicing, canonical calendar/task synchronization, scheduling conflicts and reminders, saved views, pagination, reporting, document versioning, backup/restore, sign-in, CSRF, roles, immediate deactivation and cross-company isolation.

The repeatable browser suite uses its own temporary database, creates and converts a lead through the visible interface, opens Customer 360°, books a linked meeting with a follow-up, and checks the mobile lead dialog:

```bash
.venv/bin/pip install -r requirements-test.txt
.venv/bin/python3 -m playwright install chromium
.venv/bin/python3 -m unittest -v tests/test_browser_flows.py
```

Set `CRM_E2E_BASE_URL` only when intentionally testing a disposable deployed environment. Without it, the suite starts and stops an isolated local CRM automatically.

## Production deployment

1. Copy `.env.example` to `.env` and replace every placeholder. Use a secret manager in the hosted environment; do not commit `.env`.
2. Set a real HTTPS `PUBLIC_BASE_URL`, provider OAuth application IDs/secrets, a Fernet `CREDENTIAL_ENCRYPTION_KEY`, independent `SESSION_SECRET`, `OAUTH_STATE_SECRET` and `AUDIT_SIGNING_KEY`.
3. Validate and start the stack:

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

The stack runs:

- `web`: stateless CRM API/UI; embedded scheduling is disabled.
- `worker`: one durable scheduler loop across active companies.
- `postgres`: authoritative CRM and authentication database.
- `minio` plus `minio-bootstrap`: private company-separated document storage and bucket creation.
- `clamav`: fail-closed malware scanning before uploads are stored.
- `backup`: daily PostgreSQL custom-format dumps with configurable local retention.

Terminate HTTPS at a trusted reverse proxy/load balancer. Encrypt database/backup volumes at the infrastructure layer, ship backups off-host, restrict MinIO/PostgreSQL to the private network, centralize logs/alerts and monitor `/api/health`. The included local backup volume is not an off-site disaster-recovery strategy.

## Existing-record migration

The current legacy file was repaired on 4 September 2026 after a safety copy. The repair linked policies, renewals, contacts and deals through stable IDs and changed 18 unsupported “Issued” rows to `Needs Review` because insurer/start-date evidence was absent.

For a PostgreSQL environment, first create the company administrator in the CRM, obtain its `companyId` from `/api/auth/me`, then rehearse and run:

```bash
DATABASE_URL=postgresql://... .venv/bin/python3 migrate_to_postgres.py --source crm_db.json --company-id CO_xxx --dry-run
DATABASE_URL=postgresql://... .venv/bin/python3 migrate_to_postgres.py --source crm_db.json --company-id CO_xxx
```

The migration repairs relationships, refuses unresolved hard errors, refuses a non-empty target unless `--replace` is explicitly supplied, preserves the source and writes a migration-source backup.

## Recovery

- The in-app admin backup creates a tenant-level logical JSON snapshot and takes another safety snapshot before restore.
- The production backup service creates a PostgreSQL custom-format dump every 24 hours.
- Restore a PostgreSQL dump only in a maintenance window, preferably into a new database first:

```bash
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" /path/to/insurecrm-TIMESTAMP.dump
```

After restore, run the relationship and audit-integrity endpoints, sign in as each role, process one scheduler tick in a sandbox and verify document access before reopening the service.

## Broker UAT and go-live gate

[Broker acceptance scenarios](uat/BROKER_ACCEPTANCE.md) and the [anonymized workflow manifest](uat/anonymized_broker_workflows.json) are included. Automated tests do not replace broker sign-off. Before importing live data, a broker must run all six scenarios with copied/anonymized real workflows, record results, close critical defects and repeat the migration/recovery rehearsal.

Provider setup also requires external credentials, verified domains/numbers and provider approval. Production email/WhatsApp delivery cannot be declared complete until those accounts are connected and sandbox-to-production acceptance evidence is recorded.

See [ARCHITECTURE.md](ARCHITECTURE.md) for trust boundaries, relationships and module responsibilities.
