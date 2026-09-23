# InsureCRM - Client-Aligned Foundation and Complete Non-AI Launch Plan

## 1. Objective, scope and confirmed decisions

Build the insurance telecalling operating system described in the client's blueprint, initially supporting **one owner and 3-4 human telecallers**, selling **Car Insurance and Health Insurance**.

The CRM must answer two everyday questions:

- **Telecaller:** Who should I call, what happened previously, and what must I do next?
- **Owner:** What work is happening, what business is being generated, and where does my team need attention?

### Confirmed launch scope

- Deliver **all non-AI modules before client go-live**, using internal implementation milestones.
- Implement **integrated human click-to-call**, automatic call history and recording capability. Employees conduct the conversations.
- Selecting a client-owned telephony provider and passing a calling/recording trial are prerequisites.
- Staff obtain genuine quotations and issued-policy details from insurers. The CRM manages those records and workflows; automatic insurer pricing and issuance APIs are not launch requirements.
- Include documents, WhatsApp, renewals, commissions, targets, incentives, employee performance and non-AI analytics.
- Retain existing useful functionality without cluttering the telecaller workspace.
- Keep SMS excluded under the previous explicit instruction.

**AI voice, AI analysis, AI assistance, predictive scoring and automated AI quality assessment are deferred until a later expansion.** The differing AI phase labels in the PDF do not affect this launch.

The client's blueprint defines business requirements. Its sample figures, target values, scoring weights and screen illustrations are not fixed implementation rules.

### Current implementation position

Reuse existing authentication, leads, assignment, customers, tasks, calendar, quotations, policies, communications, documents, reporting and persistence foundations.

Recent backend additions include telecaller dashboards, call logs, outcomes and product-detail fields. Their existence does not establish complete browser integration, genuine telephony or commercial readiness.

Refresh the implementation inventory before each milestone. Do not rely on historical test totals or mark a module complete because its screen or endpoint exists.

## 2. Required modules and connected business behavior

### A. Users, roles and employee management

**Client references: pages 3, 10, 41-42.**

Use consistent user-facing names:

- **Owner / Admin:** company-wide operational visibility and control.
- **Telecaller:** assigned customers/leads and associated work, plus personal performance.
- **Manager:** team-scoped management, available as the organization grows.

Apply permissions to lists, individual records, edits, calls, recordings, documents, search, reports and exports - not only navigation.

Use stable employee identifiers. Renaming or reassigning an employee must not rewrite historical call ownership or sales credit.

Employee account status and calling availability must remain separate concepts.

### B. Lead capture and spreadsheet-to-CRM matching

**Client references: pages 11-13.**

Support the client's required lead information:

- Lead ID, customer name, mobile, email and city.
- Car or health insurance product.
- Vehicle details, health-insurance needs and existing-policy details where applicable.
- Policy expiry, source and original lead date.
- Assigned employee, priority, status, next follow-up and notes.

Organization must be optional for individual customers.

Establish **one shared field dictionary** used by:

- Create/edit forms.
- Spreadsheet templates and mapping.
- Connected lead sources.
- Backend validation.
- Customer history.
- Filters, exports and reporting.

The import workflow must be:

**Upload > map columns > preview normalized values > validate > review duplicates and assignments > commit > inspect results.**

Required safeguards:

- No silent loss of unmapped columns.
- No mapping city into a generic territory field without an explicit user choice.
- Keep net premium, gross premium and sum insured distinct.
- Keep previous-policy details separate from policies sold by this business.
- Resolve employee names against real users; flag ambiguous matches.
- Preview ambiguous dates and phone-number normalization.
- Report rejected rows with actionable reasons.
- Detect duplicates within the file and against CRM records.
- Make retries safe and preserve later edits during rollback.
- Apply the same assignment and next-action rules as direct lead creation.

Retain source attribution for the client's marketing channels, including website, Google Ads, Meta, referral and organic sources. Live connections require authorized accounts and successful ingestion tests.

### C. Lead statuses, assignment and priority

**Client references: pages 11-13.**

Use the client's lead labels:

**New, Assigned, Contacted, Interested, Quote Sent, Follow-up, Documents Pending, Policy Sold, Not Interested, Call Later, Wrong Number, Unreachable, Lost.**

These are not thirteen mandatory sequential steps. Closed, unreachable and review outcomes create branches.

Keep these concepts distinct:

- Lead status.
- Call connection status.
- Conversation outcome.
- Quotation status.
- Policy issuance status.
- Renewal status.

Support configurable assignment using the client's listed methods: round-robin/equal distribution, product, availability, workload, performance and priority, with owner reassignment.

Support **Hot / Warm / Cold** priority using the blueprint's factors: freshness, expiry, interest, interaction history, product, response speed and urgency.

**Approval required:** scoring weights, thresholds, allocation precedence, capacity limits and unavailable-employee fallback. Do not silently hard-code them.

### D. Human calling, history and recordings

**Client references: pages 15-16, 27.**

Provide:

- Click-to-call from the lead/customer context.
- Customer details and previous interactions during the call.
- Automatically recorded provider call ID, employee, numbers, timestamps, technical status and duration.
- Notes and business outcome attached to the actual call.
- Owner-authorized recording playback and manual quality review.
- Visible failed-call and incomplete-wrap-up handling.

Provider callbacks must be authenticated and safe to replay. Duplicate or late events must not create extra calls, overwrite final outcomes or inflate KPIs.

Do not invent default durations, connected states, phone numbers or recording URLs. A scheduled Call task is not a completed call.

Recording access, retention and operating permissions must be approved before recording is enabled.

### E. Call outcomes, follow-ups and notifications

**Client references: pages 16-17, 33.**

Implement the blueprint's outcome-driven actions:

- **Interested / Very Interested:** create quotation work.
- **Quote Required:** create quotation work; do not claim it was sent.
- **Quote Sent:** record the actual send and create follow-up.
- **Call Back:** require a callback date/time.
- **Not Interested:** close the lead and resolve inappropriate outstanding work.
- **Busy / Switched Off:** schedule retry under the approved retry policy.
- **Wrong Number:** flag for review and stop normal repeated calling until resolved.
- **Already Insured:** retain existing-policy expiry and add renewal-watchlist eligibility.
- **Documents Pending:** create the relevant document collection reminder.
- **Policy Sold:** confirm or link a genuine policy sale and its renewal information.

"Renewal Watchlist" is a separate classification/work queue, not an unapproved additional lead status.

Use one canonical follow-up task. Calendar, dashboard and notifications reference that task rather than creating independent copies.

Show due today, overdue and upcoming work, with customer, employee, product, last interaction and next action.

Support reminder, missed-follow-up, overdue and high-value alerts; owner escalation; rescheduling; completion; reassignment; and worker restart recovery.

**Approval required:** retry intervals, calling windows, escalation delays and high-value thresholds.

### F. Customer 360°, quotations and policy sales

**Client references: pages 18, 20, 22.**

Customer history must include:

- Basic details and preferences.
- Previous insurance.
- Calls and authorized recordings.
- Quotations and customer responses.
- Documents.
- Active and past policies.
- Upcoming/completed follow-ups.
- Notes.

These are required information categories, not a mandate for eight tabs.

Ensure direct lead/deal quotations appear alongside renewal quotations. Conversion and repeat enquiries must preserve continuous history without duplicating customers.

Quotation management must record genuine insurer offers, product/customer context, premium, terms, validity, sent date, customer response and follow-up.

Use the client's quotation labels: **Draft, Sent, Viewed, Negotiation, Accepted, Rejected, Expired**. Acceptance and rejection are alternatives, not sequential steps.

Do not infer Viewed from an employee opening a quote or from an unrelated message receipt. Keep manually reported actions visibly distinct from provider-confirmed events.

Policy records must retain actual insurer details, policy number, product, premium, dates, customer, selling employee, source, sale date and renewal information.

Never:

- Generate insurer policy numbers as substitutes for real evidence.
- Default the insurer or policy term to manufacture issuance.
- Treat quotation acceptance alone as confirmed issuance.
- Assume every renewal is exactly one year after policy start.
- Create duplicate policies when a user retries confirmation.

### G. Documents and WhatsApp

**Client references: pages 19, 21, 41.**

Document categories must support RC, driving licence, required identity evidence, previous policy, applicable health documents and other required documents.

Provide:

- Private centralized storage.
- Categorization and version history.
- Missing, received and verification states.
- Role-controlled upload, preview, download and verification.
- Parent-record validation, malware checks and auditable access.
- Product-specific requirement checklists.
- Retention, archive and recovery controls.

Verify document contents through the authorized workflow; a filename or checkbox alone is not verification.

WhatsApp must support quotation sharing, document requests, policy/payment information, follow-up and renewal reminders, with a unified communication history.

Use approved messaging templates and consent controls. Distinguish queued, sent, delivered, read and failed attempts; expose failures and prevent duplicate dispatch on retries.

Payment information sharing does not imply building a payment-processing system.

### H. Renewals, commissions and employee recognition

**Client references: pages 23-30.**

Renewals must track actual policy expiry, customer, product, employee, previous premium and outcome. Implement the client's **60/30/15/7-day and due-date reminder stages**, without duplicate reminders or successor policies.

Separate renewal opportunities from existing insurance not sold by this business. Record renewed/lost outcomes and reasons.

Commission management must link each sale/renewal to employee, product, premium, applicable rule, commission amount and totals.

Targets and incentives must support the client's categories: policies, premium, conversion, achievement, renewals, campaigns and products.

Provide:

- Employee leaderboard.
- Manual call-quality review.
- Configurable employee-of-the-month scoring.
- The client's recognition categories, including sales, conversion, quality, follow-up and renewal performance.

Keep **commission**, **incentive** and **recognition score** separate.

Rules must be configurable and historically traceable. The PDF's example weights must not become fixed defaults. Monetary rules and scoring policies remain draft until the owner approves them.

### I. Dashboards, KPIs and analytics

**Client references: pages 14, 24, 26, 28, 31-34, 43, 47.**

Telecaller views must show assigned priority leads, calls, connected calls, follow-ups, interest, quotes, sales, premium and target progress.

Owner views must cover today/week/month/custom periods, team activity, call quality, missed work, sales, premium, commissions, renewals, targets and performance.

Include employee-, product-, source- and date-filtered sales funnels and source performance. Do not add marketing ROI claims without approved cost inputs.

Every KPI must have:

- A defined source record/event.
- A period and timezone.
- An employee/team visibility rule.
- A clear numerator, denominator and exclusions where applicable.
- A drill-down list reconciling to its total.

Required distinctions:

- Assigned today is not edited today.
- Call attempts are not completed tasks.
- Connected calls require connection evidence, not an arbitrary duration.
- Quotes created, sent and accepted are separate events.
- Leads converted and policies sold are different counts.
- Current assignee and historical selling employee are different attributes.
- Due today and overdue are separate work groups.
- Missing targets display "Not configured," not fabricated achievement.

Exact metric definitions, premium basis, cohort rules and cancellation treatment require owner approval before reports are accepted.

## 3. Foundation and interface requirements

Retain the existing application stack where suitable. Consolidate shared validation and workflow services rather than implementing parallel rules in each screen.

Minimum interface additions and changes:

- **Shared field definitions:** product-aware fields, labels, import aliases and validation used consistently by UI, APIs and spreadsheets.
- **Calling interfaces:** call initiation, provider events, call history, recording access and wrap-up linked by stable call IDs.
- **Workflow transitions:** validated lead/outcome/quotation/policy actions that commit related records together and are safe to retry.
- **Work interfaces:** canonical tasks with due timestamps, assignments and notification references.
- **Business configuration:** owner-managed targets, routing, scoring, document requirements, commissions and incentives, with approval/effective-history controls.
- **Reporting interfaces:** backend aggregates and corresponding scoped drill-down records using the same filters.

Use stable record and employee IDs. Preserve original capture times, source attribution and historical sales ownership.

Keep call technical events, business outcomes, tasks, quotes, policies, documents and financial records linked but distinct.

Production foundations must include PostgreSQL constraints/transactions, private document/recording storage, protected credentials, audit history, durable scheduling, monitoring and coordinated database/object backups.

Migration must reconcile existing fields and legacy statuses without inventing history. Old Won records must not automatically become verified policy sales.

The owner must control hosting, provider accounts, data export, backups, access and source-code handover.

## 4. Internal delivery milestones and acceptance

All milestones must pass before client launch.

1. **Requirements and provider readiness:** approve the field dictionary, role matrix, workflow terminology, document requirements, KPI definitions and business-rule register; validate the chosen telephony provider.
2. **Data and access foundation:** align forms/imports/sources, employee IDs, product records, permissions, storage and migration.
3. **Complete daily telecalling flow:** capture > assign > human call > history/recording > outcome > follow-up/calendar > reminder and escalation.
4. **Complete sales flow:** customer history > insurer quotation > WhatsApp > documents > confirmed policy > correct sale attribution.
5. **Complete business management:** renewals, commissions, targets, incentives, manual quality review, recognition and source/team reporting.
6. **Production validation and handover:** recovery, monitoring, accessibility, client UAT and owner documentation.

### Required acceptance scenarios

- Import representative car/health spreadsheets, including ambiguous columns, duplicates, invalid dates and unknown employees; verify every accepted field in the CRM.
- Test the same enquiry through direct entry, spreadsheet and connected source; confirm equivalent assignment and next-action behavior.
- Use one owner and four telecaller accounts to test peer-record restrictions across every module, recording, document, report and export.
- Exercise real answered, busy, unanswered, failed and disconnected calls, plus duplicate/late provider events.
- Exercise every business outcome, including missing callback time, closure, wrong-number correction and already-insured handling.
- Reschedule, reassign and complete work; verify consistent tasks, calendar, notifications and KPIs after worker restart.
- Complete quote-to-policy and renewal-to-successor journeys; repeat submissions without duplicating records or revenue.
- Reconcile commissions, incentives, leaderboard and report totals against an approved hand-calculated fixture.
- Test private document access, rejected files, verification, version recovery and coordinated database/document restoration.
- Have the owner and telecallers complete anonymized client workflows on supported desktop/mobile layouts, including keyboard navigation and failed-save recovery.

Existing automated suites are reusable evidence, not substitutes for these client-specific scenarios.

## 5. Requirements versus proposals and release rules

Maintain a requirements register with three explicit categories:

- **Client requirement:** directly supported by the blueprint.
- **Confirmed decision:** clarified in this planning conversation.
- **Proposed business rule:** needs owner/client approval.

Proposed rules include detailed car/health subfields, priority thresholds, retry timing, availability/capacity policy, escalation delays, commission structures, incentives, targets, score normalization and retention periods.

Build the capability to configure these rules; do not activate speculative values. Missing approved configuration must be visible and must block the affected launch acceptance - not trigger an invented fallback.

Provider selection, approved business configuration, client-owned accounts and production credentials are prerequisites, not decisions left for an implementer to guess.

Update README and ARCHITECTURE during implementation, maintain traceability to client requirements, and provide user/admin operating guides.

**Go-live requires the complete non-AI workflow to function with real authorized human telephony, reliable records, reconciled KPIs, secure documents, tested recovery and signed client acceptance. AI is neither a prerequisite nor a substitute for any of these foundations.**
