# InsureCRM

InsureCRM is a CRM-first operating system for commercial insurance brokers. It manages an enquiry from lead capture through follow-up, customer conversion, quotation, policy issuance, servicing and renewal. AI voice calling is intentionally outside the current release boundary.

## Current release

The build follows the client's own requirement document, *Insurance Telecalling CRM Blueprint* (car and health insurance, one owner and a small telecalling team). The agreed order is: finish the four working foundations first — identity and access, lead capture, follow-ups, WhatsApp and documents — then build the modules that are missing, starting with calling. AI calling is out of scope for now.

An alternative plan, [CLIENT_NON_AI_LAUNCH_PLAN.md](uat/CLIENT_NON_AI_LAUNCH_PLAN.md), proposes shipping every non-AI module before launch. It was written in a separate session and is **not** the plan being followed; it is kept for reference.

### Your own kinds of record — 29 October 2026

An owner can now add a whole new kind of record, kept on each lead or customer: vehicle inspections, family members, claims. Each gets its own fields, set up in Settings → Custom fields under "+ New record type". The lead card and Customer 360° then show a section for each kind, where the team adds, edits and deletes records. They're checked like any other field, and each person sees only the records on leads and customers they can see. Every kind of record gets its own spreadsheet in the export. A deleted record leaves a copy in the audit log. Customize with AI and setup files can create record types too.

### Customize with AI — 29 October 2026

**Settings → Customize with AI** (owner only): describe what the business needs — "we now sell bike insurance; note the engine CC and make big bikes hot" — and the AI proposes the products, fields, stages, lead sources and automation rules to add. Each step is listed in plain words, and anything that can't be done is marked with the reason. Nothing changes until you press **Apply**, and the latest change can be **undone**.

- **It can only add and adjust.** The AI can't delete anything, change a field's type or take away a choice; those stay under Custom fields and Lead stages, where their own safety checks apply. New automation rules arrive switched off.
- **It sees your settings, never your customers.**
- **Undo is careful.** It is refused when someone has changed the settings since, or when leads already use a field or stage it added; hiding is the safe way back then.
- **AI is off until a key is set** (`OPENROUTER_API_KEY` and `AI_MODEL`). The screen says so and points to the settings screens.

**Setup files.** The same screen downloads the company's setup — fields, stages, products, lead sources and automation rules, never records or people — and starts another company from one. Importing shows what it will add, as a change set you apply or undo; whatever the company already has is left alone.

For trying a model: `tools/run_builder_evals.py` scores it against 15 realistic, vague and hostile requests.

### Your own lead stages — 29 October 2026

Under **Settings → Lead stages** an owner can now shape the stages a lead moves through:

- **Add stages** of three kinds. *Being worked* needs a next action, like Interested. *Parked* is still open but has nothing scheduled, like Wrong Number. *Finished without a sale* needs a reason and closes the follow-ups, like Lost. A "Site inspection" or "Negotiating" stage behaves like the built-in stages of its kind everywhere: the stage dialog, follow-ups, open-lead counts, lost reasons, automations and the funnel. In the funnel it counts as the step before it.
- **Relabel built-in stages** ("Interested" → "Hot"), reorder the board, or hide stages you don't use from the pickers. The built-in thirteen keep their names underneath, because calls, quotations and reports move leads between them.
- **Safe changes.** Renaming your own stage moves its leads and automation rules with it. A stage still in use can't be deleted or change kind, and the message says how many leads or rules use it.

The CRM configuration tab no longer shows a stages box that was never saved.

**Shared views.** An owner or manager saving a lead view can share it with whole roles — "Bike leads over 500cc" for every telecaller. Saved views now remember the custom-field filter too. A shared view is only a filter: each person still sees just their own leads (or their team's).

Verification: 369 automated tests pass, 16 of them for lead stages, including one that keeps each company's stages to itself.

### Custom fields on leads — 29 October 2026

An owner can now add their own details to every lead — engine CC, chassis number, a referral code — under **Settings → Custom fields**. A field is short or long text, a number, an amount, a date, a date and time, yes/no, one choice or several, a phone, an email, a link to another record or a document. It can sit in its own section of the lead form, be required, carry help text, and apply to some products only (a bike field only on bike leads).

- **On the lead form and card.** The fields appear in their sections; the card lists what was filled in.
- **Checked wherever a lead is written.** The form, an edit and a spreadsheet import all check the same way: "1,200" reads as a number, "petrol" as Petrol, and a value that can't be read is refused with the field's name. In an import, a bad cell rejects only its row, with the reason. A spreadsheet column whose heading matches a field's label is matched to it automatically.
- **Filters, search and automations.** The lead list has a filter for any field ("Engine CC more than 500"), and search finds custom text such as a chassis number. Automation rules can test the fields, comparing numbers as numbers and dates as dates.
- **Export.** The leads spreadsheet has a column for each field.
- **Safe changes.** A field is never deleted, only hidden, and its values stay. Removing a choice that leads still use is refused with how many use it. Switching from one choice to several keeps every value. Every change is in the audit log.

**Reports by your fields.** The Reports screen can break the period's leads down by any of your choice or yes/no fields — leads, sales and conversion for each value ("Fuel: Petrol, EV…").

Telecallers and managers fill the fields in; only the owner defines them, and can limit who may change a field ("Discount approved": managers only) — others see its value but can't change it. **Customers and policies** have their own custom fields too (PAN, add-on covers…), on their forms, in Customer 360° and in the export; a policy field can be limited to some products. An **advertising or website lead source** can send a form field straight into a lead's custom field; a value that can't be read is kept on the lead as an extra detail and noted in the source's event log, so no enquiry is lost.

Verification: 348 automated tests pass, 30 of them for custom fields. A new browser test, from defining a field in Settings to seeing its value on the lead card, passes here with a stand-in for the Tailwind stylesheet (see the note below on browser tests).

### Server split — 29 October 2026

The API is no longer one 8,758-line file. Each area — leads, calls, customers, policies, renewals, quotations, messaging, lead sources, imports, automation, dashboards and the rest — now has its own module in `crm_routes/` (28 in all). `pipecat_server.py` keeps what every area shares: loading and saving, who may see what, the audit log, the lead rules and the scheduler. It is now 3,307 lines. Nothing a user does changes. Every address, input and response is the same, and a check (`tools/check_split.py`) proves it by comparing the API before and after.

**Fix:** the container image now includes the `crm_routes` folder. Since the assistant moved into it in the previous update, the image built from this branch could not start.

Verification: 318 automated tests pass; the routing and API comparison shows no difference. The browser tests still can't run in this build environment (see below).

### AI customization, phase 0 — 29 October 2026

Groundwork for letting each agency shape the CRM to its own business, following the [AI customization plan](docs/AI_CUSTOMIZATION_PLAN.md). Agreed: insurance agencies first, and companies will be able to change their lead stages.

- **The reporting assistant now answers only from what you may see.** It used to read the whole company's leads, policies, renewals and customers, so a telecaller could ask about a colleague's customers. It now sees exactly what the person asking sees on every other screen.
- **AI runs through one place, with a daily limit.** Set `OPENROUTER_API_KEY` and `AI_MODEL` — while testing, one of OpenRouter's free models. Without a model the assistant says so and uses its built-in answers rather than quietly picking a paid one. Each company gets `AI_DAILY_LIMIT` requests a day (50 unless set). If a free model is busy, the assistant says so. Free models may keep what they are sent, so test with demo data.
- **Custom fields and stages: the rules are written.** `crm_schema.py` defines the thirteen kinds of field an agency will be able to add and checks every value typed, imported or received. It also defines the four stage categories that will let an agency rename or add stages without breaking calls, follow-ups or reports. Nothing on screen changes yet; the fields appear in Phase 1.
- **Fixes:** the container image now includes every CRM module (it left out three the server needs to start), a renewal test no longer depends on a date that has passed, and `requirements-test.txt` now installs pytest.

Verification: 318 automated tests pass, including 41 new ones for custom fields and the assistant. The browser tests could not be checked in this build environment: it cannot reach the Tailwind stylesheet the screens load from `cdn.tailwindcss.com`, so 28 of 29 fail with or without these changes. None of the screens changed.

### Data export and handover — 23 September 2026

**Export all data** (Settings & Data → Backups, Owner only) downloads a ZIP with a spreadsheet for every kind of record — leads, customers, policies, renewals, calls, quotations, follow-ups, notes, messages, calendar, team, targets, incentive statements and the audit log — plus one complete file for moving to another system, and optionally every uploaded document. The spreadsheets open correctly in Excel, including ₹ and Indian names. Text a stranger typed into a web form can't run as a spreadsheet formula. Passwords are never included, and every export is recorded in the audit log.

**Restore** now has a button next to each backup. A safety copy of the current data is saved first, so a mistaken restore can be undone. The Backups tab also shows when reminders and renewals last ran and any error.

**Handover documents** are in [`docs/`](docs/): an [Owner's Guide](docs/OWNER_GUIDE.md) (where each thing on slide 42 is controlled and the month-end routine), a [Telecaller's Guide](docs/TELECALLER_GUIDE.md), an [Operations Runbook](docs/OPERATIONS.md) (install, configuration, scheduler, backups, restore, updates, troubleshooting) and a [Developer Handover](docs/DEVELOPER_HANDOVER.md) (code map, data flow, visibility rules, where each slide lives, tests, conventions). `.env.example` now lists every setting the code reads.

The repository no longer tracks iCloud conflict copies (`README 2.md`, `ARCHITECTURE 2.md`, and `crm_identity 2.json`, a test account's sign-in file) or the outdated `Read.md`.

Verification: 277 automated tests pass, 108 of them against the client's blueprint, and all 7 browser tests.

### Clean-up — 23 September 2026

- **Target achieved:** a telecaller is now notified once, the moment they reach 100% of their monthly target, and their manager sees it too. Their incentive estimate already updated with every sale. The last row of the automation table is now marked as built in.
- **No more invented owners:** new deals, policies and policies imported from leads no longer default to the sample person "Sarah Connor". They belong to whoever creates them, or to the lead's owner.
- **Telecalling wording:** the browser tab, the sidebar and the reporting assistant describe a car and health insurance telecalling business instead of a commercial broker. Template previews use a car-insurance example.
- **Correct open-lead counts:** the Users and Team settings screens counted open leads using the old Won/Lost statuses. They now use the same definition as the rest of the CRM.

Verification: 275 automated tests pass, 106 of them against the client's blueprint, and all 7 browser tests.

### Customer 360° — 23 September 2026

A customer's profile now shows the eight blocks on slide 18: **basic details** (contact, city, preferences such as language or best time to call, and which enquiry they came from), **insurance history** (the policy they held before us, then our own policies that have ended), **call history** with outcomes, notes and durations, **quotations**, **documents**, **policies** with any open renewal, **follow-ups** upcoming and completed, and **notes**. It pulls together every enquiry the person made, so a customer who bought car insurance and later asked about health cover has one history. City and preferences can be edited from *Edit profile*.

Verification: 274 automated tests pass, 105 of them against the client's blueprint, and all 7 browser tests.

### Lead assignment methods — 23 September 2026

The *Assign to* action in Automation now offers every method on slide 12: **workload** (fewest open leads), **round-robin**, **equal distribution** (fewest leads received this month), **performance-based** (leads shared by each person's conversion over the last 30 days — better converters get more, nobody gets none) and **priority-based** (HOT leads to the best converter, the rest by workload). Product-based routing is a condition on the rule, as before.

**Availability:** a telecaller can press *I'm away* on their dashboard (with an optional reason such as "on leave until Monday"), and receives no new leads until they press *I'm back*. The owner's dashboard shows who is away and can mark anyone away or back; a manager can do the same for their own team. Every method respects it.

Verification: 273 automated tests pass, 104 of them against the client's blueprint, and all 7 browser tests.

### Quotations and renewals — 23 September 2026

**Quotations on leads.** A telecaller can add quotations to their own lead from the lead card. A quote moves Draft → Sent → Viewed → Negotiation → Accepted or Rejected, and the history of each move is kept. Sending a quote moves the lead to *Quote Sent* with a follow-up; acceptance moves it to *Documents Pending* and names the documents still missing. A quote past its validity date expires by itself, and an accepted quote can't be edited.

**Renewals run themselves.** A renewal opens automatically 60 days before a policy expires, owned by the telecaller who sold it. The telecaller is reminded at 60, 30, 15 and 7 days and on the due date; if the policy expires unrenewed, they and their manager are told. Each reminder is sent once. The Renewals screen now opens with a **renewal dashboard** for a chosen month — due this month and next, renewed, pending, lost, the renewal rate (renewed ÷ due) and each telecaller's renewed against pending — and each renewal shows which reminder stage it is at.

Verification: 269 automated tests pass, 100 of them against the client's blueprint, and all 7 browser tests.

### Reports — 23 September 2026

**A Reports screen** for owners and managers follows the leads that arrived in a chosen period. The **sales funnel** shows how many reached each stage from new lead to policy sold, as a share of the start and of the stage before. The **lead sources** table shows, for each source, contact, interest, quote and conversion rates and the premium it brought — including premium per lead, so the best source isn't mistaken for the busiest. A list shows why leads were lost. Everything can be filtered by telecaller, product, source and dates.

Older leads without a recorded arrival date can't be placed in a period, and the report says how many there are. The operations summary in Settings is replaced by this screen; that tab now holds backups only.

Verification: 269 automated tests pass, 93 of them against the client's blueprint and all 7 browser tests.

### Commission, incentives and recognition — 23 September 2026

**Commission.** The owner sets commission rates by product and insurer, with separate rates for new business and renewals. Each sale's commission is worked out when it is sold and kept — changing a rate later doesn't rewrite what earlier sales earned. The owner sees commission per sale and per telecaller each month, can correct a figure (with a reason), and can mark commission as received. Only the owner sees commission.

**Incentives.** The owner writes the incentive rules — so much per policy, a percentage of premium, a bonus for hitting target, or levels — and can limit a rule to one product or one lead source for campaigns. Each telecaller's incentive for the month is worked out as sales happen, with the reasoning shown line by line; telecallers see their own estimate on their dashboard. When a month ends, the owner approves it for payroll and it no longer changes.

**Leaderboard and Employee of the Month.** A leaderboard ranks the team and names the most policies, highest premium, highest conversion, best follow-up discipline and best renewal performer — but only once there is enough to judge by. Employee of the Month is a weighted score the owner can adjust. Call quality isn't measured yet, so it's left out of the score and the screen says so rather than inventing a number.

All of this is on the Performance screen, alongside the team table and targets.

Verification: 265 automated tests pass, 89 of them against the client's blueprint and all 7 browser tests.

### Dashboards, performance and targets — 23 September 2026

**The dashboard now depends on who you are.** A telecaller sees their day as the client's blueprint draws it: today's leads, calls done, connected, follow-ups due, interested, quotes sent, policies sold and target achieved, above a list of priority leads with a Call button on each. The owner sees today, this week and this month side by side, the team's best performer, who needs support, target achievement and who is online, and what needs attention today. The existing panels stay below and can still be arranged.

**A Performance screen** for owners and managers shows each telecaller's new leads, calls, connection rate, average call length, quotes, policies, premium, conversion, follow-ups kept on time, renewals and documents, for today, this week, this month or any range. Its **Targets** tab sets monthly targets per telecaller and shows progress against them; last month's targets can be copied forward.

**One definition of every number.** All of these figures come from a single place, so the dashboard, the Performance screen and targets always agree. Where there is nothing to measure yet the screen shows a dash, not a zero or an invented figure.

Verification: 256 automated tests pass, 80 of them against the client's blueprint and all 7 browser tests.

### Calling — 23 September 2026

**Telecallers can call from the CRM.** A Call button on the lead list, the lead card and every follow-up dials the customer from the telecaller's own phone and opens a call screen showing their record — product, priority, current insurer and expiry, car or health details, missing documents and earlier calls — with space for notes. When the call ends, the telecaller picks one of the blueprint's eight outcomes, and the CRM takes the next step itself: a quotation follow-up for an interested customer, a booked call-back, a retry for no answer, a renewal-watchlist call before a competitor's policy expires, a document chase, or — for a sale — the customer and policy with its renewal date. Wrong numbers are flagged to a manager. Each lead now shows its call history.

The CRM times each call on screen and says so; a call logged afterwards records only the length the telecaller enters. A cloud calling provider can be connected later through the same interface, at which point it supplies call lengths and recordings.

**Conversion fixes.** Recording a sale now stores when it was sold, where the lead came from and when it renews. It no longer creates an organisation called "Private Individual" or an unused deal, and a telecaller can no longer convert another telecaller's lead.

Verification: 250 automated tests pass, 74 of them against the client's blueprint and all 7 browser tests.

### Automation — 23 September 2026

**A general automation engine**, built from the blueprint reviewed before building. Every rule reads as one sentence — *when* something happens, *if* the record matches, *then* act — and is built from three dropdowns on a new **Automation** screen (owner and managers only). The client's own slide-33 table is offered as ready-made rules: switch on "Share new leads between telecallers", "Quote interested customers the same day", "Chase quotations after two days", "Open a renewal for every policy sold", "Warn telecallers 30 days before expiry", "Tell telecallers about new leads" or "Ask customers for missing documents" with one click. The two rows the product already does are marked built in, and the incentive row is marked as coming with targets.

**Safe by design.** Rules start switched off and can be tried against recent records first without changing anything. Two rules that trigger each other stop instead of looping. A rule never repeats itself for the same event, stops at an hourly limit, and never messages customers who opted out, outside WhatsApp's rules, or at night — messages due in quiet hours wait for the morning. One switch pauses everything. Every run is logged in an Activity tab, showing what each action did or why it was blocked.

**Assignment rules moved here.** Existing assignment rules were carried over unchanged, and the Settings tab that edited them is replaced by this screen. Rules no longer assign leads to someone who has been deactivated.

**Fixes found along the way:** scheduled WhatsApp template messages were sent as free text, which WhatsApp rejects outside its 24-hour window; renewals created without an owner defaulted to the demo user "Sarah Connor"; and `/api/auth/me` crashed when sign-in was disabled for local development.

Verification: 236 automated tests pass, including 60 against the client's blueprint and all 7 browser tests. The browser tests were updated for the renamed and removed screens; where they counted screens, they now check the exact expected set.

### Documents and customer messaging — 23 September 2026

**The client's document types.** RC, Driving Licence, ID Proof, Previous Policy and Health Documents replace the corporate list. Each lead shows what its product needs — a car policy needs the RC, previous policy and ID proof — and which of those are missing, awaiting a check, verified or rejected. One button drafts a WhatsApp or email message asking for exactly the missing documents.

**Verification.** An Owner / Admin or Manager marks each document verified or rejected, and a rejection says why. A rejected document doesn't count towards the checklist or as evidence for issuing a policy.

**Two serious problems removed.** Converting any lead whose name started with "Issue" silently created fake KYC, payment and proposal documents, letting a policy be issued with no real evidence. And a second upload route stored anything as a PDF, skipped every file check, and saved the words "document content" as the file when nothing was sent. Both came from uncommitted work in a separate session; neither is in the product now, and every upload goes through the same checks.

**Access fixes.** A telecaller could previously message another telecaller's customer and attach documents to their record. Both now respect the same boundary as the lead list.

**The lead card no longer shows a finished action as upcoming.** When a follow-up is done and nothing is scheduled after it, the card says so and offers to schedule the next step.

Verification: 214 automated tests pass, 45 of them against the client's blueprint. Two older test fixtures uploaded the word "Hello" as a PDF with no file name; they now upload a minimal real PDF, since the product rightly rejects the old fixture.

### Follow-ups — 23 September 2026

**Reminders now run for real companies.** On a normal single-process start, the built-in scheduler only ever processed the demo workspace, so follow-up reminders and escalations never reached a real company. It now runs for every company and records failures instead of silently swallowing them.

**A Follow-ups screen replaces the blank "Follow-up Queue".** It shows the four counters from the client's blueprint — due today, overdue, upcoming and on-time rate — and lists every follow-up with the customer, product, calling priority, next action, telecaller and the last time anyone spoke to them. Call, Done and Reschedule sit on each row. Marking one done asks what happens next, so no lead is left without a next step. "Action Tasks" is no longer in the sidebar, since this screen covers it.

**Follow-ups can have a time**, not just a date, so "call this afternoon" can be scheduled and a missed call-back is noticed within the day.

**The on-time rate is measured.** It is the share of follow-ups finished by their due time over the last 30 days. It used to show 96% whenever nothing had been completed — the illustrative figure from the client's own deck.

**Four alerts, as the blueprint lists them:** a reminder before a follow-up is due, a missed alert to the telecaller when it passes, an overdue alert escalated to their manager after the escalation period, and a high-value alert when a HOT lead has a follow-up due.

**Access fixes.** Any user could edit, complete or delete any task, and every form's record picker loaded the whole company's customers and phone numbers. Both now respect visibility. Tasks created without an owner no longer default to the demo user "Sarah Connor".

**Removed from the sidebar:** "Telecaller Dashboard" and "Call History", which opened a blank page. They return when those modules are built.

Verification: 207 automated tests pass, 38 of them against the client's blueprint.

### Retail lead model — 23 September 2026

**Leads now describe car and health enquiries.** A lead is a person, not a company. The form asks for name, mobile, product, source and current policy, with optional car details (registration, make, model, year, fuel, no-claim bonus) or health details (plan, who is covered, cover wanted, existing illnesses) that open to match the product. Registration numbers are normalised — "mh 12 de 4521" is stored as MH12DE4521 — and invalid values are refused with a message saying why.

**No more invented data.** Every lead used to get a made-up city, territory, industry, company revenue, headcount and a ₹ 35,000–₹ 50,000 premium, and pipeline value was summed from those premiums. The list also showed "Sarah Connor" for unassigned leads and "Follow-up discussion" for leads with no next action. All of these are gone. Existing records keep their values, because an invented figure can't be told apart from a real one after the fact.

**Thirteen statuses from the client's process** replace the six commercial stages, with existing leads migrated. A finished lead (Policy Sold, Not Interested, Lost) needs no next action; Not Interested and Lost need a reason. The status can no longer be set directly through lead editing to skip those rules. Calling priority (HOT / WARM / COLD) is now shown on the list, board and lead card.

**Sources come from a fixed list**, with any older wording kept alongside — "Cold Outreach" becomes *Calling list*, "Meta Lead Ads" becomes *Meta Ads*. Each lead records when the enquiry arrived, fixed at creation, so response time can be measured. Existing demo leads have no evidence of when they arrived and show "Not recorded" rather than a guess. Sales record their own date, so editing an old sale no longer counts it in this month's figures.

**Tighter access.** A telecaller could previously edit any lead by id — including reassigning it to themselves — and move any lead's status. Both now respect the same boundary as the lead list. Only an Owner / Admin or Manager can reassign, and a lead a telecaller creates stays theirs.

Deals, Contacts and Organisations are removed from the sidebar and search; their data is kept.

Verification: 197 automated tests pass. Suites that exercise premiums, issuance and renewals now declare the product catalogue they use instead of relying on the old commercial default; no assertion changed. The migration was dry-run on a copy of the live workspace (18 leads in, 18 out, no field removed, other collections untouched) and the live file was backed up before the switch.

### Roles, record visibility and test safety — 23 September 2026

**Sign-in restored.** An end-to-end test run had replaced the live identity store with test fixtures, so no real account could sign in. A new administrator was created through first-run setup, and `.env` points the app at it with `IDENTITY_STORE_PATH`. The `.env` file was previously loaded *after* the security module read its settings, so any security setting placed there was silently ignored; it now loads first.

**Tests can no longer touch live data.** Every test module imports `crm_test_isolation`, which forces all storage into a throwaway directory before the app loads. Live data files were fingerprinted before and after the full suite to confirm they are unchanged.

**Four fixed roles.** Owner / Admin, Manager, Telecaller and Read-only. Roles used to be free text matched by substring, so "Senior Sales Executive" — offered by the user form — and any title containing "lead" silently became managers. Job title is now a separate display-only field. Unknown roles are refused. The last active Owner / Admin cannot be demoted or deactivated, and names stay unique on rename.

**A telecaller sees only their own work — everywhere.** Global search, notes, communications, documents (including download), quotations, contacts and direct customer and lifecycle lookups were previously company-wide. They now follow the owner of the record they belong to.

**Stable ownership.** Every owned record now carries an `assignedToId` alongside the owner's name, so renames heal across every collection and future commission attribution is by person rather than by name.

**Removed:** the profile screen's "Viewing the CRM as" switcher, which impersonated another user and has been refused by the server since the identity fix. "Add user" now asks for the temporary password the server requires; before, it always failed.

Verification: 181 automated tests pass (169 existing, 12 new in `tests/test_client_blueprint.py`, each tagged with the blueprint slide it proves).

### Client requirements planning — 7 September 2026

The client's supplied Insurance Telecalling CRM Blueprint defines a car/health insurance telecalling product. See the [client Phase 1 gap comparison and plan](uat/CLIENT_PHASE_1_GAP_PLAN.md) for existing foundations, missing human-calling workflows, required adaptations and retained later-phase work. This is a planning-only source review, not a new test certification or implementation. Page 38's Phase 1 roadmap is used provisionally; conflicting recording/AI phase labels and the quotation/document handoff need client confirmation. Earlier internal blueprints remain engineering references, not a substitute for the client's scope. SMS remains excluded under the user's explicit instruction.

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
| `pipecat_server.py` | FastAPI app and shared CRM core: persistence, visibility, audit, lifecycle rules, scheduler |
| `crm_routes/` | The API, one module per area |
| `crm_security.py` | Passwords, sessions, CSRF, roles and company identity context |
| `crm_store.py` | PostgreSQL transactional record/link adapter and scheduler lock |
| `crm_storage.py` | Local-development and S3-compatible document adapter |
| `crm_worker.py` | Durable reminder, escalation and scheduled-message worker |
| `crm_metrics.py` | The single definition of every measure, target, incentive and funnel figure |
| `crm_automation.py` | Automation engine: triggers, conditions, actions, guardrails and assignment methods |
| `crm_telephony.py` | Telephony provider interface (manual calling today) |
| `crm_test_isolation.py`, `conftest.py` | Keep every test on temporary storage |
| `docs/` | Handover: owner's guide, telecaller's guide, operations runbook, developer handover |
| `migrations/001_tenant_record_store.sql` | PostgreSQL record, relationship and identity constraints |
| `migrate_to_postgres.py` | Guarded legacy JSON-to-PostgreSQL migration |
| `web/` | Accessible responsive single-page CRM |
| `test_insurance_operations.py` | Lifecycle, recovery, servicing and integration tests |
| `test_security_foundation.py` | Authentication, CSRF, roles, revocation and tenant-isolation tests |
| `uat/` | Anonymized broker acceptance scenarios and sign-off record |
| `Dockerfile`, `docker-compose.yml` | Repeatable production runtime |
| `tests/test_browser_flows.py`, `requirements-test.txt` | Isolated Playwright browser acceptance suite |

`pipecat_agent.py`, `test_lmstudio_pipeline.py` and `requirements.txt` belong to the separate AI voice-calling prototype. It is not part of the CRM and does not run in this release.

## Local development

Prerequisites: Python 3.11+ and a modern browser.

```bash
.venv/bin/pip install -r requirements-crm.txt
.venv/bin/python3 -m uvicorn pipecat_server:app --host 127.0.0.1 --port 8080 --reload
```

Open `http://127.0.0.1:8080/`. On the first authenticated launch, the CRM asks for the company and first administrator. Local JSON storage is supported only for development and migration rehearsals.

Keep the project out of iCloud Drive, Dropbox or any folder that offloads files. macOS once moved the virtual environment and the live database to the cloud, and the server then hung on startup waiting for files that were not on disk. Sync services also create conflict copies such as `crm_db 2.json`, which can silently lose records.

To use the existing demonstration workspace without authentication during automated local checks only:

```bash
AUTH_DISABLED=1 .venv/bin/python3 -m uvicorn pipecat_server:app --host 127.0.0.1 --port 8080
```

## Automated verification

```bash
.venv/bin/python3 -m py_compile pipecat_server.py crm_*.py crm_routes/*.py migrate_to_postgres.py
.venv/bin/python3 -m unittest -v test_insurance_operations.py test_security_foundation.py tests.test_workflow_integrity
PYTHONWARNINGS=ignore .venv/bin/python3 -m pytest tests/test_client_blueprint.py tests/test_blueprint_acceptance.py tests/test_e2e_remediation.py -q
```

`tests/test_client_blueprint.py` is the acceptance suite for the client's own requirement document; each test names the slide it proves.

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
2. Set provider OAuth application IDs/secrets, a Fernet `CREDENTIAL_ENCRYPTION_KEY`, and independent `SESSION_SECRET`, `OAUTH_STATE_SECRET` and `AUDIT_SIGNING_KEY`. Callback and webhook addresses are built from the incoming request, so the HTTPS proxy must forward the original host and scheme. [docs/OPERATIONS.md](docs/OPERATIONS.md) explains every setting.
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
