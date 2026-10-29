# InsureCRM Architecture

## 1. Release boundary

The latest planning baseline is the [complete non-AI launch plan](uat/CLIENT_NON_AI_LAUNCH_PLAN.md), also exported as a [PDF](output/pdf/InsureCRM_Client_Aligned_Non_AI_Launch_Plan.pdf). It supersedes the earlier Phase 1-only rollout assumption: all non-AI modules are required before client go-live, with integrated human calling and staff-entered insurer offers. AI remains deferred. These are planning decisions, not claims of implemented capability.

### Client Phase 1 alignment — planning only, 7 September 2026

The supplied client blueprint is the product-scope authority for the next release: car/health insurance, owner and telecallers, human calling/history, outcome-driven follow-ups, customer profiles, basic quotations/policies and reporting. The [client comparison and plan](uat/CLIENT_PHASE_1_GAP_PLAN.md) maps this to current source and records scope conflicts. Existing internal standards below remain engineering references and historical implementation descriptions; they do not establish client acceptance.

The proposed architecture adds a canonical human call session and business wrap-up record linked to the existing lead/customer/task/quotation/policy graph. Provider technical status, employee outcome, lead stage and policy issuance must remain distinct. Existing calendar/notification views should reference canonical work; employee sales attribution and source/capture times should survive reassignment. These are proposals, not implemented changes. AI analysis and voice assistance remain on the later roadmap; scheduled Call tasks and the separate AI speech prototype are not implemented human telephony. The page 35/page 38 AI phase conflict and Phase 1 document/recording boundary await confirmation. No application code or live configuration changed during this review.

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

Identity is resolved from the session on every request. `/api/profile` reads and writes the caller's own roster row, matched by `identityUserId` then email then name; a request carrying another user's ID is refused rather than silently ignored. Note, task and communication authorship uses the session actor, so a caller-supplied author label cannot impersonate a colleague in the audit record. Changing another team member is an administrative action against `/api/users/{id}`, and the legacy `/api/leads/import` path carries the same management permission as `/api/imports`.

Authentication behavior:

- PBKDF2-SHA256 password hashes with 310,000 iterations and per-password salts.
- Minimum 12-character password policy using at least three character categories.
- Signed, HTTP-only, Secure-in-production, SameSite=Lax session cookie.
- Separate SameSite=Strict CSRF cookie/header on every mutation.
- Five-attempt/15-minute local login throttle.
- Identity revalidation on every request, so deactivation and role changes apply immediately.
- PostgreSQL-backed companies/users in production; protected JSON identity adapter only in local development.

Roles:

A person holds exactly one of four roles, defined in `crm_security.ROLES`. Permission comes only from the role key; a job title is a separate, display-only `title` field and grants nothing.

| Role key | Shown as | Operational records | Lead-source/import setup | Users/settings/admin/recovery |
| --- | --- | --- | --- | --- |
| `admin` | Owner / Admin | Read/write | Read/write | Read/write |
| `manager` | Manager | Read/write | Read/write | Restricted administrative mutations |
| `telecaller` | Telecaller | Read/write assigned work | No setup mutation | No admin/recovery access |
| `readonly` | Read-only | Read | No mutation | No audit/backup administration |

Earlier versions stored a free-text job title as the role and derived permission by substring, so any title containing "senior" or "lead" was a manager and "Senior Sales Executive" — offered by the user form — silently granted manager rights. Roles are now matched exactly: `normalized_role()` accepts the four keys plus an explicit table of legacy spellings, and anything unrecognised resolves to `telecaller`, never upward. Writes go through `validate_role()`, which refuses an unknown role with 422. Stored legacy roster rows are migrated on load, keeping the old text as `title`.

Two further guards protect the company itself: the last active Owner / Admin cannot be demoted or deactivated (409), and team member names are unique on rename as well as on creation, because work is assigned by name.

Visibility is enforced at record level, not only by path. `visible_owners()` resolves the signed-in session to the set of owner names it may read:

| Role | Sees |
| --- | --- |
| Owner / Admin | The whole company book |
| Read-only | The whole company book, no mutation |
| Manager | Themselves plus everyone beneath them in the reporting hierarchy |
| Telecaller | Only records assigned to them |

Owned records — leads, customers, policies, renewals, deals, tasks, calendar events, service requests and quotations — are filtered by owner. Everything attached to a record rather than owned outright — notes, communications, documents, quotations, contacts — follows its parent: `visible_ids()` collects the ids a caller may see and `child_visible()` admits a child only when its parent is among them. A note attached to nothing belongs to its author. The same boundary covers list endpoints, direct lookups (`/api/customers/{id}`, `/api/lifecycle/{id}`, `/api/communications/{id}`, `/api/documents/{id}/content`), child edits and deletes, the generic record updater, and global search. An out-of-scope record returns 404, never a redacted body that confirms it exists.

Global search and document download were previously unscoped: a telecaller could find any customer by phone number and download another telecaller's KYC documents by id. Contacts created for personal enquiries share the placeholder organisation "Private Individual", so organisation-name matching is never used for them.

The blueprint treats assigned-only visibility as a company policy rather than a constant, so it is stored as `settings.access.assignedOnlyVisibility` and defaults on. Company isolation remains mandatory and independent of this setting.

**Stable ownership.** Owner names remain the value people read and visibility compares, but `save_db()` now stamps a stable `assignedToId` beside every `assignedTo` through `_reconcile_ownership()`. A name that resolves to a current team member always wins, so a reassignment is never reverted; a name that is someone's former name (kept in `previousNames` on rename) is healed to their current one in every collection, including those the explicit rename fan-out never covered. Historical snapshots — audit entries and archives — keep the owner they had at the time. Performance and commission attribute to the id.

Static assets are versioned by file modification time and the shell is served `no-cache`. A hand-typed cache key had gone stale, so browsers kept old CSS and JavaScript while the server served new files, which made fixed defects look unfixed.

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

### Retail lead model (client blueprint, slide 11)

A lead is a person enquiring about **Car Insurance** or **Health Insurance**. Organisation is optional and defaults to the placeholder "Private Individual"; it is not shown on personal enquiries.

Earlier versions stamped an invented city ("Mumbai"), territory, industry, company revenue, headcount and premium ("₹ 35,000" server-side, "₹ 50,000" from the form) onto every lead. Pipeline value was summed from those premiums, so it was largely fabricated. A lead now carries only what someone recorded. Existing records are not rewritten, because an invented value cannot be told apart from a real one after the fact.

| Area | Field(s) | Rule |
| --- | --- | --- |
| Product | `product` (mirrored to `policyType`) | One of `settings.crm.insuranceProducts`; default Car and Health. A company still on the old commercial default list is migrated. |
| Source | `source`, `leadSource`, `sourceDetail`, `originalSource` | One of `settings.crm.leadSources`, or *Not recorded*. Free text from imports, webhooks and older records is classified on save; the original wording is kept in `sourceDetail`, and `originalSource` is fixed at first save. |
| Capture date | `leadDate`, `leadDateUnknown` | Stamped once and never editable — lead response time is a client KPI. On load, older leads are backfilled only from audit evidence; with none, the date is left empty and marked unknown rather than guessed. |
| Car | `vehicleDetails` | `VehicleDetails` schema: registration (normalised, validated against the state/RTO and Bharat-series formats), make, model, variant, year, fuel, IDV, NCB (0/20/25/35/45/50), previous claims. |
| Health | `healthDetails` | `HealthDetails` schema: plan type (Individual / Family Floater), up to twelve members with relation and age, cover wanted, existing illnesses. |
| Current policy | `existingPolicy`, `expiryDate` | Insurer, number, expiry, premium, claim. The expiry is one value held in both places and kept in step. |

Every detail block is optional — the telecaller records what the customer says when they say it — but what is recorded is validated. Edits merge into what is already there.

`GET /api/lead-options` serves the statuses, products, sources, close reasons and detail choices, so the screens never keep their own copy.

**One set of rules for every entry path.** `save_db()` runs `_normalize_leads()` before writing, so leads arriving from the form, a spreadsheet import or an advertising webhook all get the same status, source and capture-date treatment without each path re-implementing it. A lead a telecaller creates is theirs; routing rules apply only to leads nobody has claimed, and only an Owner / Admin or Manager can reassign.

### Lead lifecycle

The thirteen statuses come from the client's process and are not a per-company setting — call outcomes, follow-ups and reports depend on them. `PUT /api/settings` refuses a change to `leadStages`.

```text
New → Assigned → Contacted → Interested → Quote Sent → Follow-up → Documents Pending → Policy Sold
                     ↘ Call Later · Unreachable · Wrong Number        ↘ Not Interested · Lost
```

| Group | Statuses | Rule |
| --- | --- | --- |
| Being worked | New, Assigned, Contacted, Interested, Quote Sent, Follow-up, Documents Pending, Call Later, Unreachable | Needs a next action and a date |
| Parked | Wrong Number | No next action |
| Finished | Policy Sold, Not Interested, Lost | No next action; Not Interested and Lost need a reason |

`_checked_status_change()` enforces these rules for the stage endpoint and the general edit endpoint alike, so a status can no longer be set directly to skip them. Finishing a lead completes its follow-up and clears the next action. A sale records `soldAt` once; the dashboard counts this month's sales by `soldAt`, not `lastModified`, so editing an old sale no longer moves it into the current month. `soldAt` is recovered from audit evidence on load and marked unknown when there is none.

Older records used a six-stage commercial pipeline and are migrated on load, keeping the previous value in `legacyStatus`: Won → Policy Sold, Quotation Sent → Quote Sent, Risk / Underwriting → Documents Pending. Deals keep their own Won/Lost vocabulary; that module is retired from navigation rather than converted.

Deals, Contacts and Organisations are no longer in navigation or global search. Their records and endpoints remain, so nothing is lost and the data can still be exported or restored.

### Conversion

Lead conversion is an idempotent boundary. It creates or links:

1. customer master;
2. organization;
3. primary/multiple contacts;
4. won opportunity;
5. draft policy.

The lead retains `convertedCustomerId` and `convertedPolicyId`. Re-conversion is rejected. Customer 360° aggregates the whole relationship without copying child data.

**Customer 360° (slide 18).** `GET /api/customers/{id}` gathers everything from every lead that became this customer (`sourceLeadId`, or any lead whose `convertedCustomerId` points at it — a car sale this year and a health enquiry next year are one person), plus their policies and renewals. It returns the slide's eight blocks: basic details (`city` and free-text `preferences` are now editable on the customer; conversion already copies the lead's city), `insuranceHistory` (the policy they held before us, from the lead's `existingPolicy`, then our own policies that have ended), `calls` (every call on those leads, newest first, with any recording link a provider supplies), `quotations` (lead and renewal quotes), documents, policies, `followUps` split into upcoming and completed, and notes. The screen shows them as eight blocks, with a call button for the customer's lead. Visibility is unchanged: the customer must be in the caller's book (404 otherwise).

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

### Quotations on a lead (client blueprint, slide 20)

A quotation can belong to a lead as well as a renewal. It carries the lead's product and owner, and its status follows `QUOTE_TRANSITIONS`: Draft → Sent → Viewed → Negotiation → Accepted or Rejected, with Rejected and Expired able to go out again as a revised quote. An accepted quote can no longer be edited (409). Every change is kept in `statusHistory`. Older values are read as Received → Draft and Selected → Accepted. `_expire_quotes()` runs in `save_db()`: a quote still waiting on the customer after its validity date becomes Expired. `_quote_moves_lead()` keeps the lead in step — sending moves it to Quote Sent with a follow-up (the quote's follow-up date, or two days out), acceptance moves it to Documents Pending with the missing documents named; a lead already further along is never moved back. A telecaller quotes only leads they can see. The lead card shows its quotations with the next allowed moves.

### Renewal ladder and dashboard (client blueprint, slides 23–24)

Renewals no longer depend on someone pressing *Generate*. Each scheduler tick runs `run_renewal_tracking()`, which opens a renewal for every active policy expiring within 60 days that has none open, owned by the policy's telecaller (the old code filled in "Sarah Connor" when a policy had no owner; it now stays unassigned). The button remains as *Check for renewals now*.

`run_escalations()` raises the reminder ladder: one **Renewal Reminder** per renewal per stage — 60, 30, 15 and 7 days, the due date, and expiry without renewal — deduplicated by `renewal-ladder:{id}:{expiry}:{stage}`. A renewal opened late starts at the stage it is in rather than replaying earlier ones; the expiry alert is also addressed to the telecaller's manager. This replaces the *Renewal approaching* automation recipe, which is now listed as built in. `GET /api/renewals` adds `daysToExpiry` and `ladderStage` to each row.

`GET /api/renewals/dashboard?month=YYYY-MM` returns, for renewals whose policy expires in that month and that the caller can see: due this month, due next month, renewed (with premium), lost (Lost or Lapsed), pending, the renewal rate (renewed ÷ due this month, `null` when nothing is due) and each telecaller's renewed, pending and lost; plus how many open renewals sit at each ladder stage. Note that this rate differs from `retentionRate` above, which divides by closed renewals only.

## 6. Work processing and notifications

`crm_worker.py` iterates active companies and invokes one scheduler tick per interval. When no separate worker runs, the embedded loop calls `run_jobs_for_all_companies()`, which does the same in a background thread. `crm_store.scheduler_lock` uses a PostgreSQL advisory lock in production and a non-blocking process lock locally, preventing concurrent workers from dispatching the same company outbox.

The embedded loop previously called `run_jobs_now()` outside any request, where the company context resolves to the demo workspace — so on a single-process deployment, reminders and escalations never ran for a real company. Its `except Exception: pass` also hid every failure. Failures are now logged and stored as `settings.scheduler.lastError`, which `GET /api/admin/jobs` reports.

Each tick:

1. opens renewals for policies within 60 days of expiry, and creates deduplicated notifications for overdue renewal actions and each step of the renewal reminder ladder;
2. raises the follow-up alerts below;
3. processes due scheduled Email/WhatsApp communications;
4. respects opt-out state;
5. records success/failure and audit evidence;
6. stores the last completed run.

### Follow-up alerts (client blueprint, slide 17)

A follow-up is a task with a `dueDate` and an optional `dueTime` (24-hour `HH:MM`, in the company time zone). A lead's next action carries the same time as `nextActionTime`, kept in step in both directions. Without a time, a follow-up falls due at the end of its day.

A follow-up raises one alert for the state it is in, so a task first noticed long after it fell due gets the overdue alert rather than a missed-and-overdue pair:

| State | When | Notification | Goes to |
| --- | --- | --- | --- |
| Reminder | Within `upcomingReminderMinutes` of falling due | Follow-up Reminder | The telecaller |
| Missed | Due time has passed | Missed Follow-up | The telecaller |
| Overdue | Still open `reminderEscalationDays` after falling due | Overdue Follow-up | The telecaller, escalated to their manager or, failing that, the company owner |
| High value | A HOT lead, or one at or above `settings.crm.highValuePremium`, with a follow-up due today or late | High-Value Lead | The telecaller, once per lead per day |

Every alert's `dedupeKey` ends with the follow-up's schedule (`dueDate`, plus `T` and the time when set). Rescheduling therefore makes the old alert stale and `_reconcile_work_notifications()` resolves it, and the same suffix rule is applied on both sides.

### Follow-ups screen

`GET /api/follow-ups` returns the four slide-17 counters and the lists, each record carrying the customer, telecaller, product, calling priority, next action, due time and most recent interaction (call, message or note). Everything is computed in the company time zone rather than the server's.

On-time rate is measured: of the follow-ups that fell due in the last `days` days (default 30), the share completed by their due time. Follow-ups finished before completion times were recorded cannot be judged and are reported as `unmeasured` rather than counted either way. When nothing fell due the rate is `null` and the screen says so. The previous implementation returned 96% in that case — the illustrative figure from slide 17 of the client's deck — and computed "on time" from all completed tasks without comparing completion with due times.

Finishing a lead's follow-up opens the status dialog with the next step suggested — a first call moves the lead to Contacted with a call-back — so a lead is never left without a next action.

### Tasks

A task created without an owner goes to the linked lead's owner, or to whoever created it; it was previously assigned to the demo name "Sarah Connor". A telecaller schedules tasks for themselves only. Editing, completing and deleting a task respect the visibility boundary, and handing a task to someone else is limited to an Owner / Admin or Manager.

Notification users can mark read, assign, snooze and change severity/escalation. Snoozed items stay out of the active inbox until their date.

## 5a. Calling (client blueprint, slides 15–16)

`crm_telephony.py` is the provider interface: `place_call()` and `parse_callback()`. The `manual` provider is the default and needs no contract — the telecaller's phone dials through a `tel:` link (Indian ten-digit mobiles get +91), the call screen times the call, and the telecaller records the outcome. A cloud telephony provider (Exotel, Knowlarity, Ozonetel, Twilio) implements the same two methods; its duration and recording then come from the provider. None is shipped until one is chosen and tested against the provider's sandbox.

**A call** is a record in `callLogs` owned through `assignedTo` — the person who made it — so visibility, stable ownership ids and per-telecaller reporting apply exactly as for every other owned record. Fields: lead, direction, status (In progress / Completed), `startedAt`, `endedAt`, `durationSeconds` (an integer) with `durationSource` (call screen timer, entered by telecaller, provider, or not recorded), outcome, `connected`, notes, provider and provider call id, and `recordingUrl` (recording playback is the client's Phase 2). Older records that stored length as text ("42s", "2m 30s") are converted to seconds on load.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/calls/start` | Opens a call on a visible lead, asks the provider to dial, and returns the customer's record, document status and previous calls for the call screen |
| `POST /api/calls/{id}/complete` | Records the outcome once (a second attempt is 409) and applies its next step |
| `POST /api/calls` | Records a call made away from the call screen; its length is what the telecaller enters, or recorded as not known |
| `GET /api/calls` | Call history, scoped like every owned record |

**Outcomes (slide 16).** `apply_call_outcome()` gives every outcome its next step, so nothing depends on memory:

| Outcome | Connected | Requires | Next step |
| --- | --- | --- | --- |
| Interested | yes | — | Status Interested; "Send quotation to …" due today |
| Call Back | yes | a date (time optional) | Status Call Later; call-back booked |
| Not Interested | yes | a reason | Lead closed |
| Already Insured | yes | current policy expiry | Renewal watchlist; call booked 30 days before expiry |
| Documents Pending | yes | — | Status Documents Pending; collection follow-up naming the missing documents |
| Policy Sold | yes | insurer, premium, expiry | Customer and draft policy created with sale date, lead source and renewal date |
| Busy / Switched Off | no | — | Retry tomorrow; an early lead becomes Unreachable, but a lead already interested keeps its status |
| Wrong Number | no | — | Parked as Wrong Number and flagged to the telecaller's manager or the owner |

Every call writes a note to the lead's timeline, an audit entry, and fires the `call.logged` automation trigger, which rules can filter by outcome.

**Conversion** is shared by the Policy Sold outcome and `POST /api/leads/{id}/convert` through `_convert_lead()`. It now checks visibility (a telecaller could previously convert another telecaller's lead), closes the lead's open follow-up, records `saleDate`, `leadSource` and `renewalDate` on the policy, and uses the lead's product and owner instead of the invented defaults "Commercial Insurance" and "Sarah Connor". The "Private Individual" placeholder no longer becomes an organisation, and a conversion no longer creates a deal; an existing deal is still closed as won.

## 5b. Performance, targets and role dashboards (slides 14, 26, 29, 34, 47)

`crm_metrics.py` defines every measure once — new leads, calls, connected, average call length, interested, quotes sent, policies sold, premium, conversion, follow-ups due/done/on time, renewals and documents collected — and what each is credited to. Its module docstring is the reference table. The dashboards, the Performance screen and targets all call it, so two screens cannot disagree about a number. Periods are inclusive ranges of company-local dates; stored UTC timestamps (and zone-less ones, which are written as UTC) are converted before bucketing. A measure with nothing to divide by is `None`, shown as "—", never 0% or a placeholder. Team figures are recomputed from counts, not averaged from percentages.

Conversion is policies sold ÷ new leads in the same period. A sale is counted on the policy's `saleDate` for the policy's telecaller; policies from before sale dates were recorded are not counted in any period rather than being given a guessed date.

**Status history.** Each lead keeps `statusHistory` — status, when, who, and the owner at the time — appended by the save-time change detection and by the automation action that sets status. Leads saved earlier have it rebuilt from the audit ledger's stage changes, marked `reconstructed`; with no evidence, a lead's history holds only its current status. Quotes sent and the sales funnel read from it.

| Endpoint | Returns | Who |
| --- | --- | --- |
| `GET /api/performance?period=today\|week\|month\|custom` | Each person's measures and the team total | Telecallers see themselves; managers their team; owners everyone |
| `GET /api/targets?month=` | Targets, month-to-date actuals and achievement per measure, plus a headline | Same scoping |
| `PUT /api/targets` · `POST /api/targets/copy` · `PUT /api/targets/headline` | Set, copy or re-headline targets | Owner / Admin, or a Manager for their team |
| `GET /api/dashboard/telecaller` | Slide 14: today's leads, calls, connected, follow-ups due, interested, quotes, policies, target achieved, and priority leads (HOT first, then most overdue) | A telecaller sees their own |
| `GET /api/dashboard/owner` | Slides 34 and 47: today / this week / this month, best performer, who needs support, team target achievement, employees online, calls not connected, overdue follow-ups, policies expiring in 30 days, urgent alerts | Owner / Admin and Managers |

Targets are monthly, per person, for policies sold, premium, calls and renewals; the owner picks which one the dashboards show as "target achieved" (default policies sold). With no target set there is no achievement figure. "Needs support" is whoever is furthest behind target, never also the best performer; without targets, the lowest connect rate among people making at least ten calls. "Employees online" means active in the last ten minutes, from an in-memory record of authenticated requests — it starts empty after a restart and says nothing about earlier days. Commission is shown as not set up until the commission module exists.

The dashboard shows the role's section first, above the customisable panels. The uncommitted `/api/telecaller/dashboard` it replaces let anyone request any telecaller's figures by name and filled "today's leads" with five open leads when there were none.

## 5c. Commission, incentives and recognition (slides 25, 28–30)

**Commission** is what the business earns on each policy. `settings.commission.rules` holds rate lines that may name a product, an insurer, both or neither, each with a new-business and a renewal rate; the most specific matching line applies (a policy with a `previousPolicyId` is a renewal). `save_db()` fixes a sold policy's commission — rate, amount on net premium (before GST), basis and rule — the first time it is saved with a sale date, so a later rate change does not rewrite past earnings. Until the commission is received, a premium correction moves the amount at the same rate. A policy sold while no rate applied records no amount; `POST /api/commission/apply-missing` gives such policies today's rates. `PUT /api/policies/{id}/commission` overrides an amount or rate (a reason is required) or marks it received. `GET /api/commission?month=` is the ledger by sale and by telecaller. Commission is the Owner / Admin's alone: managers and telecallers are refused at the path level, and the policy-level endpoint checks again because telecallers may otherwise edit policies.

**Incentives** (`incentivePlan.rules`) are the owner's rules, changeable at any time: a fixed amount per policy, a percentage of premium, a bonus when the headline target reaches a chosen percentage, or levels (slabs) on policies, premium, renewals or conversion. Per-policy and percentage rules can be limited to one product or one lead source, which covers the blueprint's product-specific and campaign incentives. `GET /api/incentives?month=` returns each person's lines and total — an estimate for the current month, scoped so a telecaller sees only their own. `POST /api/incentives/{month}/approve` freezes a finished month, with the rules it used, in `incentiveStatements`; an approved month is returned exactly as approved and cannot be approved twice. The telecaller dashboard shows the month's estimate.

**Leaderboard** (`GET /api/leaderboard`, owners and managers) ranks the team by premium then policies, with five awards. An award needs something to judge by: highest conversion requires at least five new leads, best follow-up discipline at least five follow-ups due; ties are shared and an empty category names nobody.

**Employee of the Month** is a weighted score out of 100 (default weights from slide 30, owner-editable). Each measure is scaled against the team's best, so the leader on a measure earns its full weight. Call quality cannot be measured until calls are reviewed, so its weight is left out and the others are scaled up to fill its share, and the screen says so. The owner announces the winner (`POST /api/recognition/{month}/announce`); a tie is shown as a tie.

All of this appears as tabs on the Performance screen — Team, Targets, Leaderboard, Incentives and, for the owner only, Commission. The owner dashboard shows the month's commission once rates exist; a manager sees "Owner only".

## 5d. Reports: sales funnel and lead sources (slides 31–32)

`GET /api/reports?start&end&person&product&source` (owners, managers and read-only) builds one **cohort** — the visible leads whose enquiry arrived in the period, optionally for one telecaller, product or source — and returns it three ways, so the views always describe the same leads:

- **Funnel.** For each stage New → Contacted → Interested → Quote Sent → Follow-up → Documents Pending → Policy Sold, how many leads reached it, as a share of the cohort and of the stage before. A lead counts at every stage it reached or passed (from its status history), so a sale also counts as contacted, interested and quoted; statuses off the main path count as the furthest point they imply (Not Interested and Call Later imply contact).
- **Sources.** Per source: leads, contact %, interested %, quote %, conversion %, premium from those leads' policies, and premium per lead — answering which source brings the best customers, not just the most leads.
- **Loss reasons** for the cohort's Not Interested and Lost leads.

Leads without a recorded arrival date cannot be placed in a period; the report counts them and says so. The Reports screen draws the funnel as a single-series bar chart with value labels and a hover summary, and the older operations summary in Settings is replaced by a pointer to it (the tab keeps backups). `/api/reports/operations` remains for compatibility.

## 6a. Automation engine (client blueprint, slide 33)

`crm_automation.py` holds the engine: the vocabulary of triggers, conditions and actions, rule validation, matching, and every guardrail. It never touches CRM records itself. The server registers what each action does (`register_action`) and where each timed trigger finds its records (`register_time_source`). This keeps rule logic in one testable module and out of the endpoints.

A rule reads as one sentence — **when** something happens, **if** the record matches, **then** act:

| When (event) | When (timed, checked by the scheduler) |
| --- | --- |
| A new lead arrives · a lead is assigned · a lead's status changes (optionally to a given status) · a quotation's status changes · a policy is issued · a document is uploaded · a follow-up is completed | A policy is within N days of expiry · a lead's current policy is within N days of expiry · a follow-up is N days overdue · a lead has had no contact for N days |

Conditions test fields of the record the trigger is about (product, source, city, calling priority, status, telecaller, premium, days to expiry for leads; the equivalents for policies, quotations, tasks and documents) with *contains / is / is not / more than / less than / is empty*. All conditions must match. Actions: assign · create a follow-up · notify the telecaller, their manager or the owner · message the customer · set status · set calling priority · add a note · open a renewal.

**Order and assignment.** Every matching rule runs, in list order. The exception is assignment: a lead is assigned once, by the first matching "new lead" rule that assigns (`choose_assignee`), exactly as assignment rules always worked. The plan reviewed before building said first-match-wins for every rule; that would stop a company having both "assign new leads" and "notify the owner about HOT leads", so it applies to assignment only.

**Noticing changes.** Events are detected at save time. Each lead, quotation, policy, document and task carries an `automationState` marker (owner, status, issued, completed); `save_db()` compares records with their markers and fires what changed. Every entry path — form, import, advertising webhook, bulk edit, stage change, call outcome — therefore triggers automations identically, with no per-endpoint wiring. On load, records without a marker are marked without firing, so enabling automation replays nothing. Actions that change a record (set status) fire the follow-on event themselves, carrying the chain for loop protection, and update the marker so the save does not fire it twice.

**Guardrails.**

| Guardrail | How |
| --- | --- |
| Loops | A rule never fires again inside the chain it started; a chain stops after 3 hops and the stop is logged. |
| Idempotency | `automationKeys` records `rule:record:occurrence`; a retried request or a second scheduler run cannot repeat an action. Keys expire after 120 days. |
| Rate limit | Each rule runs at most `limits.maxPerHour` times an hour (default 200); further runs are logged as skipped with the reason. |
| Consent and WhatsApp rules | Message actions go through `_compose_lead_message()` — the same path as the Send button — so opt-outs, missing numbers, the 24-hour window and approved templates apply. A refusal is logged as **blocked**, not failed and never silently dropped. |
| Quiet hours | Automated messages due between `settings.automation.quietHours` (default 21:00–09:00, company time zone) are queued as Scheduled for when quiet hours end. Queued template messages keep their template, which `_dispatch()` now resolves. |
| Kill switch | `settings.automation.paused` stops every rule; `PUT /api/automations/pause`. |
| Contained failure | Each action runs independently; a run is done, partial, blocked, skipped or failed, and every run is kept in `automationRuns` (last 1,000) with what each action did. |
| Off by default | A new rule starts switched off; a recipe the owner turns on starts on. |
| Permissions | Owner / Admin changes automations; a Manager can view rules and activity; telecallers cannot see them. |

**Recipes.** `GET /api/automations` returns the ten rows of the client's table as recipes. Six can be switched on in one step. Four are marked built in because the product already does them: "call completed → save call record", "missed follow-up → alert", "renewal approaching → notify" (the renewal ladder, §5) and "target achieved → update incentive score". For the last, the incentive estimate is computed live from the owner's rules (including any target bonus), and `run_escalations()` sends one **Target Achieved** notification per person per month when their headline target reaches 100%, deduplicated by `target-achieved:{person}:{month}` and copied to their manager. "Documents pending → ask the customer" implements slide 19.

**Assignment methods (slide 12).** An assign action chooses among its people by one of: *workload* (fewest open leads), *round-robin* (rotate), *equal distribution* (fewest leads received this company month), *performance* (shared in proportion to each person's conversion over the last 30 days plus 10 points, so better converters get more and a newcomer with no sales still gets some — the choice minimises `(received this month + 1) / (conversion + 10)`), *priority* (a HOT lead to the best 30-day converter, anything else by workload), or *first listed*. Product-based routing is a condition on the rule. **Availability** applies to all of them: `users[].available` (default true), set through `PUT /api/availability` — by the person themself, by a manager for their own team, or by the owner for anyone, with an optional note, audited. An away person is skipped, round-robin moves to the next available person without losing its place, a rule whose people are all away does not match (the next rule is tried), and the fallback share skips away people too. The telecaller dashboard shows the person's own state with *I'm away / I'm back*; the owner dashboard lists who is away and can mark someone away or back. `create_lead` now works out the calling priority before routing so priority-based rules see it.

**Migration.** Existing assignment rules become automation rules once per company (`_migrate_assignment_rules`), keeping their ids, order, conditions, rotation state and counters; the originals are kept as `assignmentRulesMigrated`. `/api/assignment-rules` remains as a view over them with its original request and response shapes. A person who has been deactivated is no longer chosen by a rule; previously a rule with only inactive assignees still assigned to them.

**Endpoints.** `GET /api/automations`, `GET /api/automations/options`, `POST /api/automations`, `PUT/DELETE /api/automations/{id}`, `POST /api/automations/{id}/move`, `POST /api/automations/preview` (dry run on the 20 most recent matching records, changes nothing), `GET /api/automations/runs`, `PUT /api/automations/pause`, `POST /api/automations/recipes/{key}`. The pause route is declared before `/{id}`; declared after, it was captured as a rule id and the kill switch returned 404. A scan of every route confirms no other literal path is shadowed.

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


### Client document model (slide 21)

Document types are the client's: **RC, Driving Licence, ID Proof, Previous Policy, Health Documents**, plus the issuance evidence types Proposal Form, Payment Proof and Policy Schedule, and Other. Older labels are understood and mapped — "KYC" becomes ID Proof — and an unknown type is refused.

`settings.crm.requiredDocuments` lists what each product needs (default: Car Insurance — RC, Previous Policy, ID Proof; Health Insurance — ID Proof). `document_status()` compares that list with the documents held against the lead and, once converted, its customer and policy, and reports each as missing, awaiting check, verified or rejected. A rejected document counts as missing. `GET /api/leads/{id}` includes the status, and `GET /api/leads/{id}/document-status` returns it alone.

Every document starts `Pending`. An Owner / Admin or Manager marks it `Verified` or `Rejected` through `PUT /api/documents/{id}/verification`; a rejection must say why, so the customer can be asked for the right document. Issuance evidence is matched by document type, not by words in a file name, and a rejected document is not evidence.

**One upload path.** `POST /api/documents` accepts a raw body with query parameters or JSON with base64 content, and both go through `_store_document()`: the parent must exist and be visible to the caller, then size, extension allowlist, file signature and malware scan are checked before storage. The JSON path previously skipped all of these — it stored any bytes as `application/pdf`, and a request without content stored the words "document content" as the file, which then counted as issuance evidence. Uploads also ignored visibility, so a telecaller could attach files to another telecaller's customer.

**Removed test backdoor.** `convert_lead` contained a branch that, for any lead whose name began with "Issue", inserted four fabricated documents — proposal form, KYC, payment proof and schedule, with no file behind them — so the policy could be issued without evidence. It existed only in uncommitted work and no test depended on it. A second block patched the test module from inside the server at import time; it was also removed.

The lead card shows the checklist for the lead's product, with a button that drafts a WhatsApp or email message naming exactly what is still missing (slide 19). The 24-hour WhatsApp rule still applies: outside it, only an approved template can be sent, and the composer says so.

### Data export and restore (slides 41–42)

`GET /api/export[?includeFiles=true]` (Owner / Admin: path-level in `may_read_path` and `_require_admin` in the handler) builds a ZIP in a temporary file, deleted after it is sent: one UTF-8-with-BOM CSV per collection listed in `EXPORT_SHEETS`, plus `targets.csv`, the whole company data as `crm-data.json` (keys beginning `_` left out), optional `documents/<id>-<name>` files read through the same storage adapter as downloads, and a `README.txt` with row counts. Columns are the union of record keys, and internal markers (`automationState`, `automationKeys`) are dropped. Nested values are written as JSON text. Text starting with `= + - @` or a tab or carriage return is prefixed with an apostrophe, so a formula typed into a public lead form cannot execute in Excel. Sign-in data lives in the identity store and is never included. Each export writes a **Data Exported** audit event with row counts. The Backups tab offers **Restore** for each in-app backup through the existing `POST /api/backups/{name}/restore`, which saves a safety copy first, and it shows `GET /api/admin/jobs` (last scheduler run and error).

## 9. Search, filters, reporting and accessibility

Global search resolves leads, customers, policies, renewals, deals, contacts and organizations and returns navigation context. Lead lists provide server-side pagination. User-owned saved lead views retain search, stage, owner and urgency criteria.

Operations reporting includes conversion, stage distribution, overdue tasks, lost reasons, employee workload, lead source, product, premium by insurer, renewal outcomes, retention and retained premium. Responsive navigation retains explicit accessible labels when its visible text collapses to icons, and record drawers expose dialog semantics and named close controls.

The SPA starts on Dashboard. Important records open in 360° context and link back to related modules. Forms use in-app dialogs; major dialogs and drawers expose accessible names/roles, controls have focus-visible styles, compact navigation adapts for small screens and reduced-motion preferences are honored.

## 9a. AI and company customization

The direction is set in [the AI customization plan](docs/AI_CUSTOMIZATION_PLAN.md): a company shapes its CRM with configuration (fields, products, pipelines, layouts, views), and AI only proposes configuration changes for the owner to approve. Decisions taken: insurance agencies are the first users; companies may change their lead stages through stage categories; testing uses OpenRouter's free models.

**Language models.** `crm_ai.complete()` is the only path to a model. It reads `OPENROUTER_API_KEY` and `AI_MODEL` (falling back to `ADVISOR_MODEL`), and with either missing it returns nothing and says why, rather than choosing a model itself — a default model is a hidden cost, and the free models in use while testing come and go. Each company gets `AI_DAILY_LIMIT` requests a day (default 50), counted in the web process and reset at midnight UTC. The reason for the last failure is kept per company, so a rejected request in one company never appears in another's status. A 429 is reported as rate-limiting, which is routine on shared free models.

**Reporting advisor.** `crm_routes/advisor.py`. Its context is cut to the asker's book with `visible_owners`/`scoped` before anything is summarised, for the model and the built-in answers alike. It previously summarised the whole company's leads, policies, renewals, deals, tasks and customers for anyone who asked, telecallers included. Prompt-injection defences are unchanged: record text is fenced as untrusted data and known override phrasings are refused before any model call. Free models may retain what they are sent, so test them on demo data.

**Custom fields and stages (not yet wired in).** `crm_schema.py` holds the closed list of field types (text, long text, number, amount, date, date-time, yes/no, pick one, pick several, phone, email, link to a record, document), the checks on a field definition and on each value, and the stage categories — *being worked*, *parked*, *finished — sold*, *finished — not sold*. Custom values will live under `record["custom"]` so they can never overwrite a field the workflows read. Built-in field names are reserved in any spelling. A field's key never changes, and its type changes only where stored values stay readable. A hidden field keeps its data but refuses writes. `DEFAULT_LEAD_PIPELINE` expresses today's thirteen statuses in categories, and a test holds it equal to the server's `CLOSED_STATUSES`, `NO_NEXT_ACTION` and `REASON_REQUIRED`, so moving the workflows onto categories can start from proven-equal behaviour.

**Route modules.** Areas move out of `pipecat_server.py` into `crm_routes/`, one `APIRouter` each, included at the end of the server file. A module refers to shared helpers as `core.name` and resolves them at call time, so module-level settings that tests replace (`DB_FILE`, `AUTH_DISABLED`, …) still have one owner. Running `python pipecat_server.py` hands over to uvicorn before the module body runs, because a `__main__` copy would import a second, separate server through the route modules. FastAPI 0.141 keeps an included router as one entry in `app.routes`; `tests/run_blueprint_audit.py` therefore inventories routes from source in both places.

## 10. Recovery, testing and release gates

The app supports tenant logical snapshots with checksum and a pre-restore safety copy. Production adds daily PostgreSQL custom-format dumps with retention. A real deployment must copy backups off host and test restore into a clean environment.

Automated suites cover domain lifecycle, calculations, repair, cascade/archive policy, documents, templates, lead-source ingestion, WhatsApp delivery-failure callbacks, canonical calendar/task synchronization, time conflicts, reminders, tenant isolation, scheduling, servicing, reports, pagination, saved filters, SMS rejection, backup/restore, authentication, CSRF, permissions and session revocation. `tests/test_browser_flows.py` starts a disposable CRM and verifies dashboard-first navigation, visible lead creation, lead-to-customer conversion, Customer 360° navigation, linked meeting/follow-up booking and mobile dialog usability without changing live CRM data.

**Test isolation.** Every in-process test module imports `crm_test_isolation` before the application, which forces the identity store, company databases, backups and documents into a throwaway directory. The application reads these paths once at import, so they must be redirected first. A previous end-to-end run replaced the live identity store with its fixtures and removed every real sign-in; the forced redirect makes that impossible regardless of the developer's shell or `.env`. `conftest.py` applies the same isolation under pytest.

**Client blueprint acceptance.** `tests/test_client_blueprint.py` measures progress against the client's own requirement document. Each test is tagged with the slide it proves and signs in as a real user through the HTTP boundary.

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
