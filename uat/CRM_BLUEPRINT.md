# Commercial Insurance CRM Blueprint v1

Baseline date: 5 September 2026. Owner: product owner and broker UAT lead.

This is the target behavior, not a description of what the current code already does. Assessment results belong in `CRM_BLUEPRINT_ASSESSMENT.md`. Changing an implementation must not silently weaken this standard. The scope is an insurance broker's CRM: acquiring customers, organizing daily work, placing insurance, servicing policies and retaining customers. AI voice calling is deferred; SMS is excluded. Email and WhatsApp are included. Insurer underwriting decisions, claims adjudication and full accounting are outside this release.

## People and daily user journeys

- Administrator: set up the company, users, roles, products, stages, timezone, providers and recovery; monitor integration failures and audit changes.
- Broker: open Dashboard, see today's work, accept an assigned enquiry, qualify it, contact the prospect, schedule the next action, obtain quotes and convert the opportunity.
- Account manager: open Customer 360°, manage contacts and policies, record requests, collect documents, coordinate insurer responses and complete servicing.
- Renewal broker: work a dated renewal queue, obtain comparable quotes, record customer approval, issue the successor policy or record a reason for loss/lapse.
- Team manager: review team workload, overdue actions and failed communications; reassign work and escalate unresolved exceptions.
- Auditor: inspect permitted evidence without changing business data. Administrative recovery and credentials remain restricted.

Company isolation is mandatory. The default blueprint assumes a shared company book for operational users, with role-restricted configuration and recovery. Assigned-only visibility is a separate configurable company policy, not an assumption that the current broker role already enforces it.

## Connected lifecycle

1. Connect a source or import a file; validate, identify duplicates, retain attribution and assign ownership.
2. Create a lead with an actionable next step; show it in Tasks, Calendar and the correct owner's work queue.
3. Qualify the opportunity; record conversations and risk needs; create or link a deal and quotations.
4. Confirm conversion: customer, organization, contacts, existing deal and policy draft. Commit the relationships together.
5. Collect evidence and complete issuance. Customer 360° shows the issued policy and its financial values.
6. Service the customer through linked requests, notes, communications, documents and scheduled work.
7. Generate one renewal per eligible policy term; compare quotes, record approval and create exactly one successor.
8. Report outcomes from the same records; archive and restore without breaking the retained graph.

The calendar reads dated work from the records that own it. A dashboard number is a filtered view of those same records. A notification points to the work; it is not a second task. A sent message is an immutable delivery attempt; a template is reusable content, not a sent message.

## Record ownership and synchronization contract

- Company owns configuration, users, integrations, data and access boundaries.
- Lead owns acquisition source, qualification and its canonical next-action reference. Customer owns the enduring account profile. Conversion retains source attribution and history.
- Organization owns legal/company identity; contacts own individual names, addresses and communication preferences. A customer may have multiple contacts and policies. Renaming a master does not change its ID or overwrite secondary contacts.
- Deal owns the sales opportunity, stage, expected close and commercial amount. Policy owns cover, insurer, term, issuance state and financial amounts. A deal win is not proof of policy issuance.
- Quotation owns a versioned insurer offer, exclusions, excess, cover, validity, currency and premium components. Selection belongs to one opportunity/renewal and records the chosen version and actor.
- Renewal owns the workflow for one expiring policy term. Its successor references its predecessor and the accepted quote. Retrying completion must not create another policy.
- Task owns a dated action. Appointment owns time, duration, participants/context and meeting outcome; its work-queue projection must not duplicate it in Calendar.
- Service request owns a customer/policy request and its completion evidence. Endorsement status and policy changes follow the insurer's confirmed outcome, not an arbitrary checkbox.
- Document owns versioned metadata and a private stored object. Audit owns immutable historical evidence. Neither should be rewritten to make a report look consistent.

For every mutation: validate role and company, validate fields and related IDs, apply transition rules, commit related records atomically, record actor/time/change, refresh affected views, then enqueue side effects. Failed validation or stale revisions must leave the business graph unchanged. Provider calls need durable attempts, retry rules and deduplication across worker crashes.

## Module standards and acceptance criteria

Each numbered criterion is a release requirement. User flows below explain how the criteria fit daily work. The assessment must account for every ID, with an explicit evidence level.

### M01 — Dashboard and onboarding

Use case: decide what to do next without searching through modules. Flow: sign in → Dashboard → today's action/renewal/exception → related record → complete work → counts refresh. Dashboard owns no copied operational records.

- M01.1: startup opens Dashboard and primary navigation remains usable at a narrow mobile viewport.
- M01.2: “Tasks due today” contains only today's active tasks, excluding future, completed and archived work.
- M01.3: pipeline premium preserves decimal amounts and excludes closed opportunities from open-pipeline value; date-labelled KPIs use their stated period.

Onboarding explains each module, has dismiss/reopen controls and does not obscure the main action. Keyboard and screen-reader assessment remains a release check under M28.

### M02 — Login, users, profile and hierarchy

Use case: put work in the hands of identifiable authorized people. Flow: administrator creates user → user signs in → sees permitted company data → performs work → logs out; manager configures reporting hierarchy.

- M02.1: unauthenticated access and missing-CSRF mutations fail; tenant and read-only boundaries hold, including direct record requests.
- M02.2: profile editing changes the signed-in user's identity/profile, not another team member selected by a shared company setting.
- M02.3: deactivation revokes access immediately and a user cannot become their own manager or form a reporting cycle.

Password recovery, invitation delivery, session expiry and multi-device revocation need production-equivalent acceptance; a bootstrap account alone is not a complete onboarding process.

### M03 — Lead Sources

Use case: enquiries arrive automatically with clear provenance. Flow: choose provider → authorize account → select asset/form → test → enable → inspect/retry failed events. Source owns credentials and source-event IDs; Lead owns accepted enquiry data.

- M03.1: a valid signed synthetic webhook creates one attributed lead; replay does not create duplicates and invalid signatures fail.
- M03.2: an ingested lead has a linked canonical first task and contact/organization relationships, matching direct-entry behavior.
- M03.3: a real provider sandbox completes authorization, asset selection, subscription, delivery, token renewal and disconnect without manual database edits.

### M04 — Spreadsheet import

Use case: bring the existing book into CRM reliably. Flow: upload → map → preview validation → choose duplicate policy → commit → download errors → inspect imported records or safely roll back.

- M04.1: mapped import accepts valid rows, reports invalid rows and preserves a retrievable import result/error file.
- M04.2: imported leads receive the same canonical next-action/task relationship as directly entered leads.
- M04.3: retrying a committed batch does not duplicate records; rollback preserves records subsequently edited/converted or reports a conflict.

### M05 — Assignment rules

Use case: distribute enquiries and manage workload. Flow: manager defines criteria and order → previews → enables → source/import uses the rule → team sees ownership. Preview must not consume rotation.

- M05.1: preview does not alter rotation state; supported rule creation, editing and ordering are retrievable.
- M05.2: bulk lead reassignment propagates to open tasks, appointments and notification ownership with conflict protection.
- M05.3: direct-entry, imported and webhook leads apply the same enabled routing rules when no explicit owner is supplied.

### M06 — Leads and Accounts

Use case: qualify and progress an enquiry. Flow: add/select → edit profile/owner/date → record stage outcome and next action → schedule work → convert or close lost.

- M06.1: authenticated browser creation and stage change persist; conversion can be reached from the lead row.
- M06.2: canonical task rename/date/completion updates the lead; failed conflicting changes roll back.
- M06.3: invalid stages and Lost without a reason are rejected; only configured valid stages are accepted.

### M07 — Pipeline Deals

Use case: track sales value separately from a person's enquiry. Flow: create/link opportunity → edit amount/owner/expected close → qualify → win/loss → navigate customer/policy. Conversion must reuse a matching deal.

- M07.1: an independent deal can be created, edited and linked to its customer or lead through supported API/UI paths.
- M07.2: converting a lead with an existing deal sets that deal to Won and links the converted customer, without creating a second deal.
- M07.3: expected close date appears once in Calendar and opens the deal context.

### M08 — Guided conversion

Use case: turn a qualified prospect into a durable customer relationship. Flow: review existing matches → confirm customer/org/contacts/deal/draft policy → submit → open Customer 360°.

- M08.1: conversion creates a customer and linked draft policy, keeps source history, and rejects/reuses a repeated conversion without duplicating records.
- M08.2: choosing a different organization during conversion produces a valid organization ID and consistent customer/contact/policy relationships.
- M08.3: already scheduled lead appointments and follow-ups remain visible under the converted customer.

### M09 — Customers and Customer 360°

Use case: maintain an account across multiple enquiries and policy terms. Flow: search customer → edit profile → inspect contacts/policies/history → schedule or service → follow related record.

- M09.1: multiple policies and contacts belong to one customer and are included in its 360° response.
- M09.2: profile edits show consistently in linked active policy/customer labels without changing IDs or historical snapshots.
- M09.3: 360° includes related appointments, tasks, notes, communications, documents and servicing, including policy-linked items.

### M10 — Organizations

Use case: maintain one legal/business identity used by customers and prospects. Flow: create → link → edit legal/contact data → inspect related accounts.

- M10.1: organization creation and editing persist and are audited.
- M10.2: renaming an organization updates active display labels through stable IDs across customers, contacts and policies.
- M10.3: invalid relationship IDs are rejected rather than saved as disconnected masters.

### M11 — Contacts

Use case: work with multiple decision makers and servicing contacts. Flow: add contact to account → mark primary/role → edit contact → use it for communication.

- M11.1: multiple contacts can be created and edited without overwriting each other.
- M11.2: editing a lead's primary contact details preserves a secondary contact's name and details.
- M11.3: nonexistent customer/organization references cannot be saved to contacts.

### M12 — Action Tasks

Use case: make every promise actionable. Flow: schedule → assign/date → see task in work queue and Calendar → move/complete → update lead/appointment and resolve alerts.

- M12.1: task creation rejects invalid dates and missing titles; edits synchronize canonical related work.
- M12.2: rejected browser saves show the server error and preserve the open form; archived tasks are excluded from active lists.
- M12.3: a task linked to a customer opens customer context rather than a lead drawer.

### M13 — Calendar

Use case: plan calls/meetings, record purpose and create the follow-up. Flow: book from record → assign time/duration → detect conflicts → attend/complete → do linked follow-up.

- M13.1: appointment and linked task appear once in Calendar; edits synchronize both ways; booking/follow-up works in the authenticated browser.
- M13.2: conflict checks apply through task edits and Calendar moves, including cross-midnight appointments.
- M13.3: timezone validation rejects invalid zones; DST nonexistent/ambiguous local times require explicit handling rather than silent reinterpretation.

### M14 — Notifications, reminders and escalation

Use case: upcoming and overdue work reaches the responsible user. Flow: worker finds eligible work → one alert → inbox → open/snooze/reassign/resolve; overdue work escalates by policy.

- M14.1: upcoming work creates a deduplicated notification; completed/deleted work resolves alerts and reassignment updates the owner.
- M14.2: renewal/service/task/appointment reassignment and completion consistently update their own related alerts.
- M14.3: a restarted durable worker processes due work once across concurrent workers; escalation reaches the configured manager after the configured delay.

### M15 — Activity Notes

Use case: retain the context behind decisions. Flow: open record → write note → read in record history/Notes → correct with audit → archive with lead deletion.

- M15.1: notes persist with their relationship and remain archived when their lead is deleted.
- M15.2: a user can correct a note through a supported edit operation with an audit record.
- M15.3: note authorship uses the authenticated actor, not a caller-supplied impersonation label.

### M16 — Quotations and comparison

Use case: choose suitable cover, not merely the lowest premium. Flow: obtain offers → compare cover/exclusions/excess/taxes/validity → record customer selection and quote version → issue.

- M16.1: quote selection rejects an offer belonging to another renewal/opportunity and rejects an expired offer.
- M16.2: quotation validity uses one field contract across create/edit and Calendar projection.
- M16.3: new-business quotes can attach to an open deal before any existing policy renewal; selected terms/version remain traceable in issuance.

### M17 — Policies and issuance

Use case: register insurance that was actually placed. Flow: draft → collect insurer/payment/documents → validate term and amounts → issue → view in Customer 360°.

- M17.1: backend calculates decimal premium and tax consistently; negative values and invalid/reversed term dates are rejected.
- M17.2: issuance requires insurer, number, term and real linked checklist evidence; another update endpoint cannot bypass issuance gates.
- M17.3: new policies belong to a valid customer; policy modifications are audited and visible in customer history.

Tax default is a configurable business input, not legal tax advice. Formulas: net premium = sum of premium components minus allowed discounts; tax = round(net × rate / 100, 2); total = net + tax + explicit fees. Use decimal arithmetic, explicit currency and server-side validation.

### M18 — Renewals

Use case: retain coverage before expiry. Flow: eligible issued policy enters queue → contact → quotes → selection → successor issuance or reasoned loss/lapse.

- M18.1: generation excludes drafts/cancelled policies and does not create two active renewals for the same policy term.
- M18.2: completing the same renewal twice creates at most one successor policy, preserving predecessor links and customer continuity.
- M18.3: loss/lapse requires a reason and completion requires a selected quote plus valid issuance evidence.

### M19 — Servicing and endorsements

Use case: resolve customer needs after sale. Flow: customer/policy → request → owner/deadline → customer/insurer coordination → evidence → complete/cancel.

- M19.1: a service request cannot use a policy belonging to a different customer.
- M19.2: endorsement completion synchronizes its servicing workflow; linked service work is visible in 360°/Calendar and alerts.
- M19.3: completing a service request requires an outcome/evidence appropriate to the request rather than losing unresolved work.

Claims here means claim assistance tracking, not insurer claims adjudication or settlement calculation.

### M20 — Communications: Email and WhatsApp

Use case: communicate and preserve delivery history. Flow: select record/recipient → compose/template → consent check → queue/send → delivery/failure → follow-up.

- M20.1: missing provider configuration does not claim successful delivery; SMS is rejected.
- M20.2: delivered/read states do not regress from older callbacks; a replay cannot duplicate a delivery event or resend an already sent message.
- M20.3: real sandbox Email and WhatsApp delivery, inbound replies, bounce/failure, opt-out and retry are verified with provider evidence.

### M21 — Templates and consent

Use case: reuse approved wording without sending unwanted messages. Flow: create template → preview variables → select customer/contact → check consent and WhatsApp window → send → retain exact rendered content.

- M21.1: reusable templates can be created, edited, archived and restored; archive is distinct from sending.
- M21.2: customer-level opt-out is honored for customer-linked messages and after lead conversion, not only on the original lead ID.
- M21.3: invalid template references/unresolved variables and unapproved WhatsApp templates cannot silently become queued outbound messages.

### M22 — Documents

Use case: collect policy evidence and retain versions privately. Flow: upload to record → validate/scan → store → categorize/version → preview/download → link to checklist.

- M22.1: supported files are versioned and readable; unsupported extensions/content mismatch are rejected.
- M22.2: nonexistent/wrong-company record references are rejected before storage, and failed metadata saves do not leave untracked objects.
- M22.3: production private-object access, malware scanning and object restoration are verified against the deployed services.

### M23 — Search, filters and navigation

Use case: find the right account/work without losing context. Flow: search/filter → open result → follow relationship → return to previous view with filters retained.

- M23.1: search returns stable typed IDs and pagination boundaries work on leads.
- M23.2: saved views are user-owned, persist criteria and do not expose another user's private view.
- M23.3: search can find tasks/service work as well as customer masters; lists remain usable at realistic volume with bounded responses.

### M24 — Reporting

Use case: understand conversion, retention and work quality. Flow: choose period/team/product → inspect metric → drill into contributing records → reconcile totals/export.

- M24.1: win rate is Won / (Won + Lost); conversion is converted leads / eligible leads, clearly labelled with period and population.
- M24.2: open-work counts exclude completed/archived tasks and aggregate owners consistently with the work queue.
- M24.3: reports support a date cohort/period and reconcile to underlying eligible records; retained premium and renewal retention have explicit denominators.

Renewal retention = renewed eligible terms / all resolved eligible terms in the chosen cohort. Overdue means incomplete, unarchived work with due date/time before the company-local cutoff. New-business, renewal and service metrics are kept distinct.

### M25 — Company settings

Use case: adapt the CRM to a broker's operating process. Flow: administrator configures stages/products/insurers/timezone/reminders → preview → save → validation/UI/reporting use the same configuration.

- M25.1: invalid timezone/reminder values are rejected; valid settings are retrievable.
- M25.2: configured lead stages are accepted by transition validation and included in pipeline/reporting, or unsupported configuration is rejected explicitly.
- M25.3: product and insurer choices drive relevant forms and validation consistently; existing records survive configuration changes.

### M26 — Duplicates, merge, archive and deletion

Use case: keep data clean without losing independent relationships. Flow: inspect duplicates → select survivor → review impacted records → merge; archive → hide operational work → restore previous state.

- M26.1: merge relinks operational references and refuses implicit merging of distinct converted customers.
- M26.2: archive/restore does not reopen previously archived tasks; lead deletion retains archived notes.
- M26.3: deleting a lead removes dependent servicing/endorsement/calendar relationships while retaining independent shared records; no dangling IDs remain.

For this product, the user's requested lead cascade is retained: lead-owned dependent operations are removed, notes retained as archive. A shared customer/contact/organization is not exclusively lead-owned merely because its label matches.

### M27 — Audit and accountability

Use case: reconstruct who changed what and why. Flow: create/edit/transition/assign/delete → append event → inspect entity history → verify chain.

- M27.1: core mutations produce actor/company-labelled audit events and chain verification detects tampering.
- M27.2: integration replay, migration, assignment and archive operations are audited; no mutating route is silently exempt.
- M27.3: rejected role access cannot modify another team member's profile or administrative credentials through alternate endpoints.

### M28 — Persistence, recovery, deployment and accessibility

Use case: operate reliably beyond one user's laptop. Flow: deploy → migrate/reconcile → monitor → back up data plus documents → restore into clean environment → broker acceptance.

- M28.1: concurrent local writers cannot silently overwrite each other; corrupt storage is not replaced with demo data; logical restore keeps a safety copy.
- M28.2: production PostgreSQL migration, constraints, concurrent writes, worker restarts and database-plus-object recovery are rehearsed with measured RPO/RTO.
- M28.3: authenticated screens load without JavaScript/request failures, mobile layouts avoid horizontal overflow, and full keyboard/screen-reader and load testing are completed.

## Cross-module acceptance journeys

- J01 New business: signed source → duplicate replay → routing → lead/task → meeting/follow-up → new-business quotes → conversion/reused deal → evidence → issuance → searchable customer history.
- J02 Renewal: issued policy → eligible queue once → multiple offers → compare/select valid offer → reminder → successor once even on retry → old/new policy links → retention report.
- J03 Servicing: customer with two policies and two contacts → request on one policy → documents → meeting → insurer response → completion → resolved alert → 360° evidence.
- J04 Work recovery: assign → upcoming alert → snooze → reschedule → old alert resolved → reassign → overdue manager escalation → complete → consistent counts.
- J05 Data administration: import preview → partial rejection report → canonical imported work → merge → archive/restore → safe deletion → audit → recovery.
- J06 Security: two companies and four roles → UI and direct API attempts → user-owned filters/documents/providers → logout/deactivation → rejected cross-company access.
- J07 Failure/retry: stale edit, duplicate webhook, double conversion/completion, provider timeout, worker crash, malformed document, failed persistence and restored backup; no partial graph or false success.

## Test and release rules

The acceptance register contains all 84 module criteria and all seven journeys. Each must be classified. A passing unit/API example is evidence only for the assertions actually executed; it does not pass a whole module or certify delivery to an external provider. A screen-load check is not a CRUD or accessibility certification.

Use PASS for a fully demonstrated criterion; PARTIAL for some demonstrated behavior with remaining assertions; FAIL for a reproducible violation; BLOCKED for a required external environment/provider/human check; NOT VERIFIED for a local criterion without adequate execution evidence. Keep source-review findings separate from executed failures. Never mark a known failure as an expected pass.

Release requires zero unresolved data-loss, access-control or core workflow blockers; all required criteria/journeys pass in a production-equivalent environment; broker UAT is signed. Provisional performance budgets: p95 main-list load ≤2 seconds at agreed client volume; reminders within 60 seconds of eligibility with a running worker. Proposed RPO ≤24 hours and RTO ≤4 hours require client agreement and a measured recovery drill. These are targets, not measurements or promises about the present CRM.

The test runner must use temporary files/companies, suppress external sends and never use the live CRM's data as its mutation target. This assessment phase adds documents and test code, not product fixes; detected defects remain visible for prioritization against this baseline.
