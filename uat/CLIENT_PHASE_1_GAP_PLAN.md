# Client blueprint comparison and Phase 1 plan

Reviewed: 7 September 2026. Status: planning proposal; no application implementation authorized by this document.

## 1. Decision

The existing CRM is a reusable foundation, but it is not yet the client's Phase 1 product. The client is building an outbound telecalling business selling **car and health insurance**, initially with an owner and four telecallers. Our current interface and data defaults emphasize commercial insurance broking, organizations, underwriting and renewals. The largest missing capability is the **human telecaller calling workflow**, not AI.

Use the client's requirements as the product scope. Retain the earlier internal blueprints as engineering and regression references, not as a competing feature brief. Do not rebuild working foundations unnecessarily; adapt them to the client's process and prove the connected workflow before release.

Source: `Insurance_Telecalling_CRM_Blueprint.pdf`, 50 pages, supplied from `/Users/aaravsharma/Downloads/Insurance_Telecalling_CRM_Blueprint.pdf`. Page references below refer to that PDF. All pages were text-reviewed; the phase roadmap, lead fields, telecaller dashboard, outcome rules, quotation flow, policy fields and AI phase label were also visually inspected.

### Evidence limits

- **Implemented foundation** means identifiable backend/frontend functionality exists. It does not mean client acceptance or production verification is complete.
- **Partial / needs adaptation** means some required behavior exists, but the complete client workflow does not.
- **Missing** means no corresponding active CRM implementation was found in the inspected models, routes and interface. A generic task or unused prototype is not that feature.
- **Unverified** means a provider, deployment or operational claim needs execution evidence.
- This was a source/document review, not a new runtime, browser, provider or security test run. No product code, configuration or live records were changed.
- The stored internal assessment was generated on 6 September 2026 and reports 105 passing checks, 8 failures and 4 blocked checks. Both `pipecat_server.py` and `web/app.js` have changed since its recorded hashes. Those counts are historical, concern our older standard, and must not be treated as today's client-requirement completion score. Some historical failures now have apparent source fixes that need retesting.

## 2. Scope and document conflicts

Use the explicit development roadmap on **page 38** provisionally:

- **Phase 1:** login/roles, leads/assignment, telecaller dashboard, calling integration/history, outcomes/follow-ups, customer profile, basic quotations/policies, basic reporting.
- **Phase 2:** WhatsApp, documents, renewals, commissions, advanced owner dashboard, leaderboard, incentives, call recordings.
- **Phase 3:** advanced analytics, AI call analysis, automated quality scoring, advanced automation.
- **Phase 4:** AI voice assistant, advanced customer automation, predictive lead scoring.

AI and later phases are retained, not ignored. Phase 1 human click-to-call is required even though AI voice calling is later.

Resolve these conflicts with the client before freezing scope:

1. Page 35 labels AI call analysis **Phase 2**, while page 38 places it in **Phase 3**. It is explicitly future development in either case, so it does not block Phase 1 planning.
2. Pages 7 and 15 describe calling with recording, but page 38 defers recordings to Phase 2. Plan Phase 1 call metadata/history and recording-ready relationships; do not silently make recording delivery a Phase 1 commitment.
3. The full journey includes WhatsApp, documents and renewals, while page 38 defers their complete modules. Phase 1 still needs a documented way to share/record a quotation, confirm a genuine sale and retain expiry/renewal dates. Confirm whether existing basic document capability remains available for sale evidence; do not remove it or weaken issuance checks without approval.
4. Page 9 mentions Email/SMS as possible integrations. SMS was explicitly removed at your request. Keep it excluded unless you explicitly reverse that decision; do not reinstall it because the deck names it.
5. Mockup figures, targets, incentive structures and scoring weights are illustrative, not seed data, fixed targets or approved formulas.

Security, backups, owner control, documentation and deployment (pages 39–42) are release prerequisites, not optional features to postpone merely because they are absent from the short MVP column.

## 3. Phase 1 requirement-by-requirement comparison

### P1-01 — Login, owner/telecaller access and employee management

Client: pages 3, 10, 38, 41–42. Owner controls the business; each telecaller sees assigned work and their own performance; a future manager sees their team.

**Implemented foundation:** login/logout, password hashing, session/CSRF protection, identity/user administration, role checks, company isolation, reporting hierarchy and owner-scoped lists/dashboard. Current roles include Administrator, Manager, Broker and Read-only/Auditor.

**Remaining:** map Broker to the client's Telecaller role and permissions; finalize owner/employee menus; verify assigned-record restrictions on every detail, related history, edit, search, report and export—not only lists. Define employee onboarding, password recovery and immediate access revocation. Preserve stable employee IDs instead of relying on display names for ownership and performance attribution.

Source evidence: `crm_security.py` identity/session/permission functions; `pipecat_server.py` authentication middleware, `visible_owners`, user/profile routes. For example, the customer list is scoped, but `get_customer` does not itself apply `require_visible`; related-detail access needs explicit acceptance coverage.

**Status: partial client fit; security foundations implemented, complete role boundary unverified.**

### P1-02 — Lead capture, editing and car/health data

Client: pages 2, 11, 38. Required lead fields: ID, customer name, mobile, email, city, product, vehicle details, existing-policy details/expiry, health needs, source, lead date, employee, priority, status, next follow-up and notes.

**Implemented foundation:** lead creation/editing, mobile/email/name, product label, expiry, source attribution, assignment, next action/date, notes, import with mapping/error handling, source/webhook framework, duplicate/merge/archive capabilities, list/Kanban and saved filters.

**Remaining:**

- Make individual customers first-class; company/organization must not be required for a personal car or health enquiry. The current browser lead form requires it.
- Replace fleet/corporate product defaults with client-approved Car Insurance and Health Insurance forms. Existing organization, turnover, employee-count and underwriting details should not clutter the normal telecaller flow.
- Add structured city, vehicle/risk details, existing-policy details and health-needs fields end-to-end: create, edit, import, validation, customer history and reporting. These are not presently dedicated fields on `LeadModel`.
- Use an immutable capture timestamp for lead date and response-time measurement. Current direct creation relies on `lastModified`, which changes later.
- Make source and priority consistently available across every capture path; distinguish editable labels from audited original attribution.
- Map old statuses safely. Current defaults are New, Contacted, Risk / Underwriting, Quotation Sent, Won and Lost. The client also needs Assigned, Interested, Follow-up, Documents Pending, Policy Sold, Not Interested, Call Later, Wrong Number and Unreachable. Configurable labels alone do not supply their workflow rules.

Proposed product field details such as vehicle registration/model or covered family members must be confirmed with the client; the PDF names the categories but does not supply their full field dictionary.

Source evidence: `LeadModel`, `create_lead`, lead update/import/ingestion routes; `web/index.html` lead form; `web/app.js` stage dialog.

**Status: partial; substantial reusable CRUD, important domain and workflow changes required.**

### P1-03 — Automatic assignment and calling priority

Client: pages 12–13. Assignment options include round-robin/equal distribution, product, availability, workload, performance and priority; owner can reassign. Priority factors include freshness, expiry, interest, interaction history, product, response speed and urgency, with Hot/Warm/Cold outcomes.

**Implemented foundation:** ordered conditional rules, product/source/premium/stage matching, round-robin, least-open-leads allocation, fixed assignee, weekday eligibility, active-user filtering and manual/bulk reassignment.

**Remaining:** real employee availability/shift state, capacity limits, performance-based routing, explicit priority routing and fallback when nobody is eligible. An Active user account is not evidence that someone is available to call. Review the current fallback that can reuse the assignee list even when none are active. Add Hot/Warm/Cold definitions and an explainable priority queue; current High/Medium/Low task/lead labels are not the requested scoring system. Test all entry paths and reassignment together, including notifications and work ownership.

Proposed MVP scope: approve simple deterministic priority and allocation rules first. Preserve the remaining listed factors in the backlog if deferred; predictive scoring belongs to Phase 4, not a prerequisite for a useful Phase 1 queue.

Source evidence: `RULE_FIELDS`, `ROUTING_METHODS`, `_pick_assignee`, `apply_assignment_rules`, bulk lead updates.

**Status: partial.**

### P1-04 — Telecaller daily dashboard

Client: page 14 and Phase 1 on page 38. Show today's assigned leads, calls done, connected calls, follow-ups due, interested customers, quotes sent, policies sold, target progress, priority leads and daily premium.

**Implemented foundation:** a user-scoped Dashboard with overdue/due/completed/upcoming work, a work queue, trend, pipeline and rearrangeable panels.

**Remaining:** a telecaller-specific home screen, next-lead/Call Now action, genuine call and connected-call metrics, interest/quote/sale events, basic employee targets and target achievement, and premium from confirmed policy sales. A completed task must not count as a completed phone call. Preserve the existing work/calendar system underneath instead of creating another follow-up list.

Source evidence: `get_dashboard`, dashboard layout routes and browser rendering. Current response contains task/pipeline metrics, not a call activity ledger or employee targets.

**Status: partial; generic work dashboard exists, client's telecaller dashboard does not.**

### P1-05 — Human calling integration and automatic call history

Client: pages 15–16, 38. Click-to-call from a customer record, customer context during a call, automatic duration/status/history, notes/outcomes and follow-up.

**Implemented foundation:** a task or calendar activity can be labelled Call; notes can be attached to records. A separate Sarvam AI voice prototype exists.

**Missing:** a production human telephony integration; employee extension/phone mapping; call initiation and in-call state; provider call IDs and signed event callbacks; automatic started/answered/ended timestamps and duration; missed/busy/no-answer/failed call states; a first-class call history; recovery of incomplete calls; duplicate-event protection; and a wrap-up form tied to each call.

No active human call-session API/data model or dialler flow was found in the inspected CRM. A scheduled Call task is not an actual call record. `pipecat_agent.py` provides conversational AI/text-to-speech, not this employee calling workflow, and must not be counted as Phase 1 telephony.

Choose a provider only after confirming the client's account, calling mode, numbers, employee devices and expected call volume. No provider setup or external calls were made in this review.

**Status: missing; principal Phase 1 build gap.**

### P1-06 — Structured call outcomes and automatic next actions

Client: page 16. Every standardized outcome triggers the appropriate action.

**Implemented foundation:** changing a lead stage can log a note, complete the previous canonical task and create a dated next action. Calendar completion can schedule a follow-up.

**Missing/adaptation:** call-specific outcome records and these rules, applied once per call wrap-up:

- Interested / Very Interested → quotation task.
- Quote Required → quotation work; Quote Sent → follow-up reminder.
- Call Back → required callback date/time.
- Not Interested → close the lead and resolve inappropriate outstanding follow-ups.
- Busy / Switched Off → retry at a defined time, within an approved retry policy.
- Wrong Number → flag for review and prevent normal repeated calling until corrected.
- Already Insured → capture expiry and place on a future renewal watchlist, without falsely recording a policy sold by this business.
- Documents Pending → document-request/reminder task; full document management remains Phase 2 unless brought forward.
- Policy Sold → confirm/link the actual policy and retain renewal date, once; do not manufacture a sale from an unverified dropdown selection.

Keep provider call status, employee conversation outcome, lead sales stage and policy issuance status distinct. They relate to one another but are not interchangeable labels. Retry delays, maximum attempts, closure/reopen rules and required fields need owner approval.

Source evidence: `StageTransitionPayload`, `transition_lead_stage`, browser `stageDefaults`, calendar completion routes. Current stage defaults concern fleet RC collection, surveyors and underwriting, not the client's outcome matrix.

**Status: partial foundation; client outcome engine missing.**

### P1-07 — Follow-ups, reminders and missed-work escalation

Client: pages 17, 33, 38. Due/overdue/upcoming work should show customer, employee, product, last interaction and next action; staff and owner receive relevant alerts.

**Implemented foundation:** tasks, meetings/calls/calendar, scheduling, due dates, notifications, read/snooze controls, escalation logic and a separate scheduler worker.

**Remaining:** connect real call outcomes and quotation actions to the canonical task; support precise callback times consistently; show last actual call and product; configure missed/high-value alerts; verify owner escalation is actually visible to its intended recipient rather than only stored as a label. Test completion, reschedule, reassignment, duplicate suppression, worker restart and browser-closed delivery. Add a defensible on-time completion metric.

Source evidence: task routes, calendar relationship helpers, `run_escalations`, `update_notification`, `crm_worker.py`. Current task due dates are predominantly date-only, while appointments contain time; resolve that distinction deliberately for callbacks.

**Status: partial; reusable scheduling foundation, telecalling synchronization and operational proof required.**

### P1-08 — Customer profile and continuous history

Client: page 18. Basic details, previous insurance, calls, quotes, documents, policies, follow-ups and notes must form one continuous history.

**Implemented foundation:** editable customer profiles, primary/secondary contacts, multiple policies, lead conversion, tasks/notes, communication/document history, calendar and servicing relationships.

**Remaining:** actual call history and later recording links; structured personal car/health details/preferences; previous insurance distinct from policies sold here; continuity for repeat enquiries; and all new-business quotation history. Current `get_customer` gathers quotations by renewal IDs only, so direct lead/deal quotes are not included in that history query. Audit record visibility and preserve source/employee attribution through conversion and reassignment.

Source evidence: customer create/edit/360 routes, lead conversion, customer browser screen.

**Status: partial; Customer 360° exists but is not yet the client's complete customer history.**

### P1-09 — Basic quotation management

Client: page 20. Record customer/product, insurer, premium, status, date sent, customer response and follow-up date. Lifecycle: Draft, Sent, Viewed, Negotiation, Accepted/Rejected, Expired.

**Implemented foundation:** quotes linked to lead/deal/renewal at API level; insurer, premium, cover, deductible and validity; editing/version snapshots; comparison and renewal selection. A browser quotation form exists.

**Remaining:** customer-facing quotation workflow from the lead/customer screen; the current creation form primarily selects deals or renewals and records insurer quotes as Received. Add structured sent date, response, follow-up, approved lifecycle transitions and customer acceptance evidence. Link accepted offers to the actual policy sale and show them in Customer 360°.

Decide the Phase 1 sharing method because WhatsApp is Phase 2. A manually recorded external send must be labelled manual; do not claim Sent or Viewed from generating a quote, opening an employee screen or receiving an unrelated message read receipt. Confirm whether quotation document generation and insurer APIs are required, or whether staff record an insurer's quotation; the PDF does not specify a rating engine.

Source evidence: `QuotationModel`, quotation routes and `openQuotationModalPrompt`/comparison UI.

**Status: partial.**

### P1-10 — Basic policy sale and issuance record

Client: page 22. Record customer, product, real policy number, insurer, premium, term dates, employee, source, sale date, commission and renewal date. Commission workflow is Phase 2 per page 38.

**Implemented foundation:** policy create/edit, customer/lead links, insurer, product, dates, premium/tax calculations, issuance state, checklist/document evidence, conversion and renewal relationships.

**Remaining:** capture approved sale timestamp, selling employee and source attribution explicitly; distinguish previous cover, quote acceptance, recorded sale and insurer issuance. Product requirements must suit car/health rather than a universal commercial checklist. Preserve renewal eligibility/date now, while keeping the full renewal process in Phase 2. Plan commission linkage without pretending a commission ledger already exists.

Important source-review issue: `issue_policy` still supplies a generated policy number, default insurer and dates if omitted. These are not insurer evidence and must not be accepted as a real sale/issuance. Existing premium calculations should use confirmed insurer amounts and configured tax treatment, not invent insurance prices or assume one tax rate for every product.

Source evidence: `PolicyModel`, `policy_financials`, create/update/issue routes, conversion form. A deal's `commissionRate` field is not policy commission accounting.

**Status: partial; existing records/issuance machinery need client-specific validation and sale semantics.**

### P1-11 — Basic owner and employee reporting

Client: pages 26, 31–34, 38, 43, 47. Phase 1 needs a useful basic subset; advanced analytics, recognition and incentives remain later.

**Implemented foundation:** pipeline counts, source/product lead counts, lost reasons, employee lead/win/open-task summaries, overdue tasks, premium summaries and some date filtering.

**Remaining:** real calls/connected calls/duration, first-response time, quotes sent, confirmed policies sold and premium by selling employee; owner totals vs employee-only reports; consistent employee/product/source/date filters; targets where shown on the Phase 1 dashboard; reconciled source-to-sale conversion. Current reporting filters its lead population but other aggregates do not consistently use that same date/visibility scope. Current lead Won counts are not proof of policy sales.

Agree definitions before building dashboards. Proposed definitions, subject to client approval:

- Calls attempted: unique provider call sessions initiated in the reporting period, not webhook-event or task counts.
- Connected calls: sessions with an answered/connected event; talk duration is ended minus answered time, separate from ringing time.
- Contact rate: distinct leads reached / distinct eligible leads attempted; do not confuse this with connected calls / attempted calls.
- First-response time: first qualifying attempt minus immutable lead-capture time; specify separately if measuring first successful connection.
- Lead-to-sale conversion: eligible leads producing a confirmed policy / eligible leads in the agreed cohort. Multiple policies do not multiply converted leads.
- Policies sold and premium: count/sum confirmed sale records once, using sale date and the approved net/gross definition; define cancellation corrections.
- Follow-up on-time rate: work completed by its due timestamp / work due in the cohort; define rescheduling and cancellation treatment.
- Target achievement: actual qualifying result / configured target × 100; a missing/zero target displays Not set rather than an invented percentage.

All calculations must originate in backend records and be reproducible from drill-down lists. Mockup numbers in the PDF are not evidence of required volumes or ratios.

Source evidence: `get_dashboard`, `operations_report`, report/settings UI. These are partial reporting primitives, not the client's call-performance reporting system.

**Status: partial.**

### P1-12 — Owner control, security, deployment and handover

Client: pages 39–42, 46. The business owns accounts/data/source code and must not depend on one developer.

**Implemented foundation:** PostgreSQL adapter and migration tooling, audit events/integrity checks, document-storage adapter, backup/restore tools, Docker deployment, worker process, tests and technical documentation.

**Remaining/unverified:** client-owned hosting/database/telephony accounts; agreed retention/export/deletion policy; complete record-level access review; production-equivalent migration/concurrency and recovery rehearsal; monitoring and failed-call/worker alerts; owner-operable backups/export; onboarding/runbooks; source-code and credential handover; acceptance at the initial four-agent load with a agreed path to 10–20 agents.

The presence of deployment files is not evidence the live deployment is secure or recoverable. Calling permission, recording policy and sensitive health-data collection require a client-approved operating/compliance policy; this review is not a legal certification.

**Status: foundations implemented, release readiness unverified.**

## 4. Later-phase requirements retained in the plan

These are not deleted or ignored. Existing functionality should be retained safely, but not allowed to expand the Phase 1 acceptance boundary without an explicit decision.

### Phase 2, using page 38

- **WhatsApp (page 19): partial.** Templates, communication records, provider dispatch/consent/callback code exist. Actual authorized provider round trips and quote/payment/policy/document/renewal workflows remain to be proved. A message record is not confirmed delivery.
- **Documents (page 21): partial.** Uploads, categories, versions, private storage and scanner integration exist. Need client-approved RC/licence/identity/previous-policy/health categories, verification/missing-document workflow, role tests and production storage/scanning proof.
- **Renewals (pages 23–24): partial.** Queue generation, reminders, competing quotes and successor policies exist. Need the specific 60/30/15/7/due cadence, already-insured watchlist, accurate employee/month dashboards and validated closed/lost behavior. A 60-day generation window is not the complete reminder cadence.
- **Commissions (page 25): missing as a complete module.** There is a deal commission-rate field, but no complete configurable sale/renewal commission ledger, accrual/adjustment history or owner reconciliation.
- **Advanced owner dashboard (pages 26, 34, 47): partial.** Generic team/work counts exist; online/available employees, call metrics, support/performance indicators and commission/target totals are absent or incomplete.
- **Employee leaderboard (page 28): missing.** Needs defensible call/sales/follow-up metrics, periods and fair comparison rules.
- **Targets/incentives/employee of the month (pages 29–30): missing as full management workflows.** Basic target entry is proposed for Phase 1 only to support its dashboard. Configurable incentive rules, effective dates, monthly calculation, score normalization, ranking and recognition remain later. The example weights are not approved rules.
- **Recordings and manual quality review (page 27): missing as active CRM workflows.** Need provider media events, authorized playback, access/retention controls and manual review/quality feedback. Do not confuse these with AI analysis.

### Phase 3

- **Advanced analytics (pages 31–32, 43): partial primitives only.** Source lead counts and pipeline counts exist; source contact/interest/quote/sale rates, call productivity, attribution and cohort reports require completion.
- **AI call analysis and automated quality scoring (page 35): not integrated.** Transcription, summary, sentiment, objections, opportunities, quality/compliance flags, recommended follow-up and coaching need call/recording inputs and human-review controls. Resolve the page 35 Phase 2 label against page 38 before scheduling.
- **Advanced automation (page 33): partial.** Assignment/tasks/notifications and scheduled messages exist; call-driven rules, target/incentive updates and durable end-to-end retry behavior are incomplete. Basic assignment and call-outcome automation remain Phase 1 requirements, not deferred wholesale.

### Phase 4

- **AI voice assistant (pages 36–37): prototype only, not an accepted CRM capability.** Initial qualification, intent capture, callbacks, FAQs, human transfer and renewal calls need explicit CRM/telephony integration and controls. Existing conversational speech code is not the complete workflow.
- **Predictive scoring and advanced customer automation:** no complete implementation found. Keep stable call/outcome/consent relationships now so these can be added without rebuilding history later.

Other external connections on page 9 (insurer/policy systems, email) need scope confirmation. Do not infer a commitment to automatic insurer quotation or issuance APIs from the architecture illustration alone.

## 5. Proposed connected Phase 1 workflow

1. **Capture:** source/direct/import → validated person and car/health enquiry, original source/time, duplicate check.
2. **Assign:** approved rule → employee ID, assignment event and notification → employee priority queue.
3. **Call:** employee opens lead → sees customer context → starts human call → provider events update one call session automatically.
4. **Wrap up:** outcome + note + required next action → atomic update of lead state, call wrap-up and one canonical task; failed saves retain entered work.
5. **Follow up or quote:** callback appears in Tasks/Calendar and reminder queue; quote task opens the same enquiry context. Sent quote records its send method/time and next follow-up.
6. **Sell:** accepted quote + confirmed sale evidence → create/reuse customer and actual policy; retain lead, employee and source attribution. Repeated clicks cannot duplicate sales.
7. **Continue history:** Customer 360° includes prior enquiry, calls, outcomes, quotes, policy, notes and follow-ups. Record future expiry/renewal eligibility for Phase 2.
8. **Measure:** owner and employee views derive their appropriately scoped totals from these same events; every number has a matching record list.

Branching outcomes such as Not Interested, Wrong Number and Already Insured are not forced through a linear sales funnel. They close, pause or redirect work according to the agreed rules.

### Record ownership to settle before implementation

- **Lead/enquiry:** acquisition, risk requirements, owner, stage and current next-action reference.
- **Customer/contact:** enduring person identity, preferences, previous insurance and all linked enquiries/policies.
- **Call session (new):** provider ID, employee/customer/lead, timestamps, technical status and duration. Provider events are deduplicated inputs, not additional calls.
- **Call wrap-up/outcome (new):** employee's business result, notes and the next action; preserved separately from technical call status.
- **Task:** one actionable obligation with due timestamp/status. Calendar and notification views reference it rather than duplicating it.
- **Quotation:** versioned offer plus send/response/acceptance evidence, tied to the correct enquiry and resulting policy.
- **Policy:** actual cover and confirmed sale/issuance facts; customer/source/selling employee retained independently of later reassignment.
- **Target (basic new):** employee, metric, period and value; no incentive engine required in Phase 1.
- **Audit/provider-event history:** actor, company, event ID, timestamp and outcome; future recordings/AI attach to call IDs, not loose notes.

## 6. Implementation order after plan approval

1. **Freeze the client brief and screen flows:** resolve the scope questions below; approve the field dictionary, role matrix, stage/outcome map and metric definitions. Treat old “Won” records cautiously—do not bulk relabel them as confirmed policy sales.
2. **Align data and permissions:** car/health profiles, optional organizations, stable employee IDs, timestamps and migration checks; enforce owner/telecaller access across related records. Preserve old data and audit the mapping.
3. **Deliver one complete telecalling slice:** assignment → My Leads → human call → history → outcome → callback task/calendar → notification. Include duplicate callbacks, failed calls and late provider events before expanding features.
4. **Complete quotation-to-policy:** simple customer-facing quote lifecycle, approved sharing method, acceptance, real policy/sale evidence and continuous history. Reconcile Phase 1 evidence needs with existing document gates.
5. **Build client dashboards/reports:** telecaller queue/KPIs, basic owner summary and targets; calculate from canonical call/sale/work events, not UI counters.
6. **Release validation and handover:** client-supplied anonymized cases, four-telecaller role tests, provider sandbox, recovery drill, responsive/keyboard checks, owner runbook and signed UAT.

Do not put commission, leaderboard or AI development ahead of the missing human calling slice. Conversely, do not remove working renewal/document/communication modules simply because their full client acceptance is later. Keep them behind appropriate navigation/permissions or an agreed rollout scope.

### Low-clutter screen proposal

Telecaller: **My Day → My Leads → Follow-ups/Calendar → Customers → Quotations → Policies → My Performance.** Lead detail provides the call, outcome, notes, quote and scheduling actions without repeated module switching. Owner additionally sees Team, Assignment, Reports and Settings. Existing Deals/Organizations/Servicing can remain underlying or secondary screens where relevant; an individual customer should not need to understand those modules to get a quote.

Use a clear next action, visible save/error feedback, keyboard-operable controls, predictable back navigation and mobile layouts. This is a proposal, not a UI change made in this review.

## 7. Client-specific acceptance plan

These are planned tests, not tests executed during this review:

- **A01 Access:** owner + four telecallers; assigned-only list/detail/history/edit/report access; reassignment, deactivation and account recovery.
- **A02 Product intake:** personal car and health enquiries without a company; required product fields; direct entry and mapped import; duplicate phone handling and original capture timestamp.
- **A03 Assignment:** agreed rule distribution, inactive/unavailable staff, no eligible assignee, manual reassignment and one useful next action/notification.
- **A04 Real human calling:** sandbox click-to-call; answered, busy, unanswered, failed and disconnected calls; correct duration/history; duplicate/out-of-order provider events; no invented connected counts.
- **A05 Outcomes:** every page 16 outcome, its mandatory fields, correct lead state, exactly one follow-up or closure and visible failed-save recovery.
- **A06 Reminders:** timed callback, reschedule, completion, missed deadline, owner escalation, timezone, browser closed and worker restart.
- **A07 Quote and sale:** quote from a lead, share/record send, response, acceptance/rejection/expiry; customer/history continuity; genuine insurer data; repeated confirmation without duplicate policy/sale.
- **A08 Reports:** hand-calculated synthetic ledger reconciles employee/owner counts, date/source/product filters, premium, conversion and targets; reassignment does not rewrite historical selling credit.
- **A09 Release:** clean deployment, backed-up database and required documents restored, permission/export/retention checks, accessible responsive flows and signed owner/telecaller UAT.

Phase 1 is accepted only when the owner's four telecallers can execute these workflows with real authorized telephony, accurate records and no live-data/security blockers. Internal test percentages alone are not acceptance.

## 8. Decisions needed before writing product code

1. **Telephony:** is there an existing provider/account/number? Should employees call through a browser headset, desk phone or mobile callback bridge? Who owns the account and numbers?
2. **Phase boundary:** confirm page 38 as the roadmap; confirm recording and AI-analysis phase; decide whether basic existing documents and WhatsApp are exposed in Phase 1 or kept later.
3. **Sales operation:** where do insurer quotes and policy numbers come from? What constitutes Policy Sold, who confirms it, and what is the Phase 1 quote-sharing method?
4. **Fields and outcomes:** approve car/health fields, lead-stage migration, call outcomes, retry intervals, calling availability, consent/do-not-call behavior and closure/reopen rules.
5. **Performance:** approve attribution, net/gross premium, date/cohort definitions, daily/monthly targets and which assignment/priority methods are MVP requirements.
6. **Go-live ownership:** confirm hosting, recovery objectives, retention, export rights, admin ownership and the named owner/telecaller UAT participants.

No provider purchase, external message/call, data migration or product code change is included in this planning review.
