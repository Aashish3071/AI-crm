# InsureCRM Architecture

## 1. Release boundary

### Target architecture versus demonstrated behavior

[CRM Blueprint v1](uat/CRM_BLUEPRINT.md) is the normative workflow standard. [Blueprint Assessment](uat/CRM_BLUEPRINT_ASSESSMENT.md) is the evidence-backed comparison against this implementation. Architectural descriptions in this file describe implemented mechanisms and intent; they are not a declaration that every boundary behaves correctly. In particular, the blueprint tests separately challenge identity/profile scope, import/routing parity, conversion links, quote ownership, issuance bypass, renewal retry, consent continuity, service completion and metric definitions.

`tests/test_blueprint_acceptance.py` adds positive and negative API checks tied to criterion IDs. `tests/test_blueprint_browser.py` checks authenticated navigation breadth and customer-task navigation. `tests/run_blueprint_audit.py` runs them alongside the existing suites, records failures without expected-failure suppression, enumerates all application routes, and produces source-hashed evidence. Route observation is measured separately from acceptance; unobserved endpoints and externally blocked checks remain explicit.

The browser assessment also checks all eleven settings sections and selected-section highlighting. `tests/test_blueprint_postgres.py` optionally exercises the real PostgreSQL adapter against an explicitly designated disposable local database, including optimistic concurrency, atomic rollback, company-separated identifiers, archived relationship targets and scheduler advisory locks. This is adapter evidence, not an end-to-end PostgreSQL deployment or recovery certification. The report counts each test once even if both setup and cleanup fail.

This release is the commercial-insurance CRM. AI voice calling is deferred and its legacy files are excluded from the CRM container. SMS is removed. Supported outbound channels are Email and WhatsApp.

The architecture favors a single connected operating workflow over independent record screens:

```text
Ingress -> Lead -> Daily work -> Conversion -> Policy -> Service -> Renewal
   |         |         |             |           |          |
 attribution|     tasks/calendar   Customer360   docs    quotations
 deduplicate|         alerts        contacts      audit   successor policy
```

## 2. Runtime topology

```text
Browser
  |
  | HTTPS session cookie + CSRF token
  v
FastAPI web service -----------------------> S3-compatible private document bucket
  |                                            ^
  | PostgreSQL transactions                   | encrypted objects + company key prefix
  v                                            |
PostgreSQL <---------------- Durable worker ---+
  |                           |
  |                           +--> Email SMTP / WhatsApp Cloud API
  |
  +--> company records, relationship links, identities and audit events

Upload path: Browser -> FastAPI validation -> ClamAV -> object storage -> metadata transaction
Backup path: PostgreSQL -> daily custom-format dump -> retained backup volume -> off-host copy by operator
```

Production uses `docker-compose.yml` to start `web`, `worker`, `postgres`, `minio`, `minio-bootstrap`, `clamav` and `backup`. The browser/API service does not run an embedded scheduler in production.

## 3. Trust and tenancy

Every authenticated request resolves a signed session to an active identity and places its `companyId` in request context. Business reads/writes, documents, backups, webhooks and worker runs derive their company scope from that context; callers cannot submit a company identifier to override it.

Authentication behavior:

- PBKDF2-SHA256 password hashes with 310,000 iterations and per-password salts.
- Minimum 12-character password policy using at least three character categories.
- Signed, HTTP-only, Secure-in-production, SameSite=Lax session cookie.
- Separate SameSite=Strict CSRF cookie/header on every mutation.
- Five-attempt/15-minute local login throttle.
- Identity revalidation on every request, so deactivation and role changes apply immediately.
- PostgreSQL-backed companies/users in production; protected JSON identity adapter only in local development.

Roles:

| Role | Operational records | Lead-source/import setup | Users/settings/admin/recovery |
| --- | --- | --- | --- |
| Administrator | Read/write | Read/write | Read/write |
| Manager | Read/write | Read/write | Restricted administrative mutations |
| Broker | Read/write assigned operational work | No setup mutation | No admin/recovery access |
| Read-only/Auditor | Read | No mutation | No audit/backup administration |

Visibility is enforced at record level, not only by path. `visible_owners()` resolves the signed-in session to the set of owner names it may read:

| Role | Sees |
| --- | --- |
| Administrator | The whole company book |
| Read-only/Auditor | The whole company book, no mutation |
| Manager | Themselves plus everyone beneath them in the reporting hierarchy |
| Broker | Only records assigned to them |

The boundary is applied to lead lists and single-lead fetches, tasks, deals, policies, renewals, customers, the dashboard and the calendar, so a scoped user cannot reach another broker's record by requesting its ID; the response is 404, not a redacted record. The blueprint treats assigned-only visibility as a company policy rather than a constant, so it is stored as `settings.access.assignedOnlyVisibility` and defaults on. Company isolation remains mandatory and independent of this setting.

## 4. Persistence and relationships

`crm_store.py` is the PostgreSQL adapter. Each domain record is stored as JSONB but receives a relational identity `(company_id, collection, record_id)`. `crm_links` materializes and constrains strong relationships on both ends. A company revision is locked and incremented for every commit; a stale write returns a conflict rather than overwriting a concurrent update.

Strong link fields include:

| Field | Target |
| --- | --- |
| `leadId`, `sourceLeadId` | Lead |
| `customerId`, `convertedCustomerId` | Customer |
| `organizationId` | Organization |
| `policyId`, `newPolicyId`, `convertedPolicyId` | Policy |
| `renewalId` | Renewal |
| `quotationId`, `selectedQuotationId` | Quotation |
| `contactId` | Contact |
| `channelId` | Lead/communication channel |
| `templateId` | Communication template |
| `dealId` | Deal |

Polymorphic `associatedId` links are constrained when the named target is live. Historical notes may intentionally refer to an archived/deleted lead, so archive evidence does not become an invalid foreign key.

State mutations are committed as one company transaction. The adapter rebuilds constrained link rows inside that transaction. Missing strong targets fail the commit. The local JSON adapter uses atomic file replacement only and remains a development/migration adapter.

### Legacy relationship repair

`repair_relational_model` matches legacy contacts and deals by explicit ID, normalized email/phone and unambiguous organization. It creates/link customer masters for policy owners, links renewals to the same customer/organization and retires legacy SMS templates. It never invents underwriting facts: a row marked Issued without policy number, insurer, start date or expiry evidence becomes `Needs Review`/`Data Review`.

The guarded migration utility:

- supports dry run;
- creates a migration-source backup;
- refuses unresolved relationship errors;
- refuses to overwrite a non-empty tenant without explicit `--replace`;
- verifies the target after commit.

## 4a. Dashboard composition

The dashboard owns no records. Every number is a filtered view of the records that own the work, recomputed per request and scoped to the caller's visibility.

- `todayCounts` splits active tasks into overdue, due today, completed today and the next seven days. "Due today" means the due date equals today; it previously returned every incomplete task regardless of date.
- Completion time is recorded on the task as `completedAt`, because "completed today" cannot be derived from a due date, which states when work was meant to happen.
- Open pipeline value sums premiums of leads that are not Won or Lost, using decimal parsing rather than digit concatenation of a formatted string. Won value is reported separately. `wonThisMonth` counts the stated period only.
- `workTrend` returns seven daily pairs of scheduled versus completed tasks.

Panel selection and order are per user, stored under `settings.dashboardLayouts` keyed by identity ID, so one broker's arrangement never changes another's. Chart colours come from a validated categorical palette (blue/orange, CVD ΔE 24.7 light and 26.8 dark); reserved status colours mark overdue, due, and completed states and are never reused as series colours.

## 5. Domain lifecycle

### Shared workflow invariants

`_sync_lead_work` owns next-action and owner propagation for both single and bulk edits. `_sync_lead_next_action` uses `nextActionTaskId`, so renaming a task does not disconnect it from its lead. `_validate_appointment` is shared by booking, appointment edits, linked task edits and reassignment. Calendar rescheduling delegates to the same domain handlers instead of maintaining a separate mutation path. Time conflicts compare complete dates and times, including intervals crossing midnight.

Before persistence, `_reconcile_work_notifications` updates ownership and resolves notifications whose source is completed, removed or rescheduled. Notification history remains available. Lead merge relinks polymorphic and direct lead references throughout operational collections, preserves historical audit records and blocks automatic merging across distinct converted customers. Archive-driven task changes carry provenance so restoring a lead does not reopen independently archived work.

Local persistence uses `crm_store.load_json_state` / `save_json_state`: an advisory file lock covers the revision check and atomic, flushed file replacement. Competing stale snapshots fail with HTTP 409. Corrupt JSON raises a service error and is never silently overwritten. This protects local development data; it is not a replacement for the PostgreSQL production adapter. Backup restore uses the current database revision, not the snapshot revision.

PostgreSQL saves explicitly remove old relationship rows before replacing record rows because target foreign keys use RESTRICT. Parent references can target their retained archive records. Runtime PostgreSQL concurrency/recovery and external provider delivery are deployment verification requirements, not covered by the JSON-backed acceptance suite.

### Lead and daily work

Lead creation synchronizes the prospect organization/contact and creates one canonical first task. Stage transitions require a next action/date and add both a timeline note and canonical actionable task. Calendar appointments support meetings, calls, site visits, surveys and renewal reviews linked by stable ID to any operational master. Each appointment may own one work-queue task and one post-appointment follow-up task; updates to either side are saved in the same company transaction.

The calendar feed is a projection, not a second source of truth. It combines appointments with task due dates, deal close dates, quotation validity, policy renewal dates, service deadlines and scheduled communications. An appointment-backed task is suppressed from the feed so one activity appears once. The relationship repair migration links legacy next actions/tasks and meeting/tasks, creates only missing canonical work items, and flags unresolved relationships for review without deleting history.

Appointment times are interpreted using the company IANA timezone. Owner overlaps return a conflict response before save. The durable worker emits deduplicated upcoming and overdue appointment/task notifications using the configured reminder window. Conversion carries appointment relationships to the customer and policy; reassignment moves future linked work; archive and cascade deletion archive calendar history and remove dangling task links.

Lead stage values are:

```text
New -> Contacted -> Risk / Underwriting -> Quotation Sent -> Won
                                                        \-> Lost (reason required)
```

### Conversion

Lead conversion is an idempotent boundary. It creates or links:

1. customer master;
2. organization;
3. primary/multiple contacts;
4. won opportunity;
5. draft policy.

The lead retains `convertedCustomerId` and `convertedPolicyId`. Re-conversion is rejected. Customer 360° aggregates the whole relationship without copying child data.

### Policy issuance

A draft policy cannot become Issued through a generic edit. The dedicated issuance command requires insurer, start/expiry dates, a final insurer policy number and all four evidence flags: proposal form, KYC, payment and schedule. Policy numbers are never generated for raw leads.

Backend financial formulas are authoritative:

```text
netPremium   = normalized input premium
taxAmount    = round(netPremium * taxRate / 100, 2)
totalPremium = round(netPremium + taxAmount, 2)
daysRemaining = expiryDate - currentDate
```

### Servicing

Service requests belong to both a customer and one of that customer's policies. Supported types are Endorsement, Claim Assistance, Certificate, Policy Document, Cancellation, Reinstatement and Other. Endorsement requests create a linked endorsement work record. Every status/owner/due-date change is audited.

### Renewal and quotations

Renewals link the expiring policy, customer and organization. Competing quotations record insurer, premium, sum insured, coverage summary, deductible and validity. Quote edits retain versions; selection retains approval history. Renewal completion requires a selected quote and the issuance checklist, expires the old policy and creates an issued successor with `previousPolicyId`.

Closed renewal outcomes are Renewed, Lost or Lapsed. Retention is calculated as:

```text
retentionRate = renewed closed renewals / all closed renewals * 100
```

## 6. Work processing and notifications

`crm_worker.py` iterates active companies and invokes one scheduler tick per interval. `crm_store.scheduler_lock` uses a PostgreSQL advisory lock in production and a non-blocking process lock locally, preventing concurrent workers from dispatching the same company outbox.

Each tick:

1. creates deduplicated notifications for overdue renewal actions;
2. creates deduplicated notifications for overdue client tasks;
3. processes due scheduled Email/WhatsApp communications;
4. respects opt-out state;
5. records success/failure and audit evidence;
6. stores the last completed run.

Notification users can mark read, assign, snooze and change severity/escalation. Snoozed items stay out of the active inbox until their date.

## 7. Communications and lead sources

### Outbound

- Email uses configured SMTP with STARTTLS when offered or SMTP-over-TLS on port 465.
- WhatsApp uses the Meta Cloud API. Outside the 24-hour service window, the UI/API requires an approved WhatsApp template.
- Provider credentials are encrypted with Fernet before persistence. Provider-owned access tokens, refresh tokens, app secrets and SMTP passwords are masked in API responses.
- WhatsApp sent/delivered/read/failed webhooks update the communication timeline. Failures generate deduplicated notifications.
- If no sender is configured, the record explicitly says `Not sent — no sender connected`; it is never presented as delivered.
- SMS is rejected at both template and communication API boundaries.

### Inbound and advertising sources

Callbacks are tenant-specific. Meta-family payloads use HMAC app-secret verification in production; Google uses its generated lead key; LinkedIn, email, Zapier and custom sources use generated shared secrets. Rate limits apply to public callbacks. Raw fields and attribution are retained for replay/mapping, while normalized email/phone prevents duplicate lead creation.

OAuth authorization state is signed, company-bound, nonce-bearing and expires after ten minutes. Server-side provider application credentials are required before the one-click Meta/Google/LinkedIn authorization action is enabled. Provider approval/subscription remains an external activation step.

## 8. Documents, personal data and audit

Document controls:

- 10 MB limit and extension allow-list;
- content signature check for common binary formats;
- fail-closed ClamAV or configured scanning service in production;
- generated storage names and sanitized download names;
- company-prefixed object keys;
- private bucket with server-side encryption;
- SHA-256 checksum, category, version and archive metadata;
- authenticated/authorized download and inline preview.

Audit controls:

- every supported create/edit/delete/archive/restore/assignment/transition/import/recovery operation calls the audit service;
- password/token/secret, email, phone, address and raw payload values are redacted from details;
- actor, company and UTC time are recorded;
- every new event includes the previous event hash and an HMAC `eventHash`;
- `/api/admin/audit-integrity` verifies the signed chain and separately reports pre-chain legacy events.

Database, object and backup volume encryption and key rotation are infrastructure responsibilities. Never store encryption/signing keys in source control.

## 9. Search, filters, reporting and accessibility

Global search resolves leads, customers, policies, renewals, deals, contacts and organizations and returns navigation context. Lead lists provide server-side pagination. User-owned saved lead views retain search, stage, owner and urgency criteria.

Operations reporting includes conversion, stage distribution, overdue tasks, lost reasons, employee workload, lead source, product, premium by insurer, renewal outcomes, retention and retained premium. Responsive navigation retains explicit accessible labels when its visible text collapses to icons, and record drawers expose dialog semantics and named close controls.

The SPA starts on Dashboard. Important records open in 360° context and link back to related modules. Forms use in-app dialogs; major dialogs and drawers expose accessible names/roles, controls have focus-visible styles, compact navigation adapts for small screens and reduced-motion preferences are honored.

## 10. Recovery, testing and release gates

The app supports tenant logical snapshots with checksum and a pre-restore safety copy. Production adds daily PostgreSQL custom-format dumps with retention. A real deployment must copy backups off host and test restore into a clean environment.

Automated suites cover domain lifecycle, calculations, repair, cascade/archive policy, documents, templates, lead-source ingestion, WhatsApp delivery-failure callbacks, canonical calendar/task synchronization, time conflicts, reminders, tenant isolation, scheduling, servicing, reports, pagination, saved filters, SMS rejection, backup/restore, authentication, CSRF, permissions and session revocation. `tests/test_browser_flows.py` starts a disposable CRM and verifies dashboard-first navigation, visible lead creation, lead-to-customer conversion, Customer 360° navigation, linked meeting/follow-up booking and mobile dialog usability without changing live CRM data.

The workflow regression suite in `tests/test_workflow_integrity.py` additionally checks concurrent competing saves, corrupt-store preservation, task/lead updates, conflict bypass attempts, overnight overlaps, merge links, ownership/notification propagation and archive restoration. The browser suite exercises rejected task saves to ensure errors are visible and forms stay open.

Browser acceptance bootstraps an isolated company with authentication enabled. Lead creation, editing and stage transitions use `apiJson` alongside task/note writes, ensuring the CSRF header and visible server-error handling are consistent. Earlier browser coverage with `AUTH_DISABLED=1` did not exercise this boundary.

Commercial release still requires environment-specific evidence:

- successful Docker image build and migration against the chosen PostgreSQL service;
- HTTPS/domain, email and WhatsApp production credentials/approvals;
- centralized logs, metrics, alerts and off-site backup policy;
- vulnerability/dependency scan and infrastructure penetration review;
- load/concurrency test at the client's expected volume;
- recovery-time/recovery-point acceptance;
- broker UAT sign-off with copied/anonymized real workflows in `uat/BROKER_ACCEPTANCE.md`.

These are deployment and human-acceptance gates, not code features that can be truthfully marked complete in a local prototype.
