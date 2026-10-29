# AI Customization — Plan

Status: proposal, not built. Written 29 October 2026 after a full read of the codebase.

## 1. The goal in one sentence

An owner should be able to say *"add a Bike Insurance product with engine CC and rider age, put it on its
own pipeline, and remind the telecaller 45 days before expiry"* — and the CRM changes itself, safely,
without a developer.

That splits into two separate things, and the order matters:

1. **A configurable CRM.** Fields, products, pipelines, forms, views, automations and reports are
   *data* the company owns, not code. Without this, AI has nothing safe to change.
2. **An AI builder on top.** The AI turns plain language into a proposed configuration change, shows
   it, and applies it only when the owner approves. The AI never writes or runs code.

Most of the work is step 1. Step 2 is comparatively small once step 1 exists.

## 2. What the codebase has today

### Strengths we build on

| Already there | Where | Why it helps |
| --- | --- | --- |
| Per-company isolation | `crm_security` company context, `crm_store.py` keyed by `company_id` | Each company's customization lives in its own space; no cross-tenant risk |
| Schemaless record storage | `crm_records.data jsonb` (`migrations/001_tenant_record_store.sql`) | Custom fields and custom record types need **no database migration** |
| Per-company settings | `db["settings"]`, `PUT /api/settings` | Natural home for a versioned configuration |
| Save-time pipeline | `save_db()` → normalise → reconcile → automation events | One place to validate custom fields for every entry path (form, import, webhook) |
| Rule engine with a registry | `crm_automation.py` `TRIGGERS` / `ACTIONS` / `FIELDS` | Already "when / if / then" data; just needs to read fields from the registry |
| Server-served vocabularies | `/api/lead-options`, `/api/calls/options` | Screens already read choices from the server — extend to fields and layouts |
| Single metric definitions | `crm_metrics.py` | Reports can be configured without letting anyone invent a wrong formula |
| `customFields` on leads | imports and webhooks (`pipecat_server.py` ~5917, ~6452) | A starting point, but untyped, read-only, and leads only |
| AI advisor with guardrails | `/api/ai-advisor`, fenced untrusted data, override-pattern guard | Proven pattern for prompting safely; reused for the builder |
| Audit on every change | `audit(db, …)` | Every AI-applied change is traceable |
| Strong test culture | 277 tests, blueprint-traced | Lets us refactor the core with confidence |

### What blocks customization today

| Hard-coded | Where | Effect |
| --- | --- | --- |
| Lead fields | `LeadModel` (pydantic) at `pipecat_server.py:2526` | Can't add a field without code |
| Car / health detail blocks | `VehicleDetails`, `HealthDetails`, and the form in `web/index.html:902` | Every new product needs a developer |
| Lead statuses | `LEAD_STATUSES`; `PUT /api/settings` refuses changes | One pipeline for every product and every business |
| Screens | `web/index.html` (1,159 lines) and `web/app.js` (5,056 lines) render fixed tables and forms | Nothing reads a layout |
| Automation condition fields | `crm_automation.FIELDS` fixed list | Rules can't test a custom field |
| Roles and access | four fixed roles; path-prefix checks in `crm_security.may_*_path` | No field-level or custom-role permissions |
| Industry | insurance terms in ~370 places in the server | Fine for now — see decision D1 |
| Size of one file | `pipecat_server.py` is 8,948 lines | Every change touches the same file; we should split as we go |

## 3. Target design

### 3.1 The company configuration ("schema")

One versioned document per company, stored beside its records:

```text
config v12
├── objects        lead, customer, policy, renewal, quotation, task  (system)
│                  + custom objects, e.g. "Vehicle Inspection"         (company-defined)
├── fields         per object: key, label, type, required, options, help, section, visibility
├── pipelines      per product: stages, each mapped to a *system stage category*
├── forms          per object (and per product): sections and field order
├── views          list columns, filters, kanban grouping, saved views per role
├── automations    existing rule format, now able to reference any field
├── dashboards     panels chosen from crm_metrics measures
└── permissions    per role: which objects/fields can be seen or edited
```

Key rules:

- **System fields stay system.** `status`, `assignedTo`, `mobile`, `leadDate`, `soldAt` and anything
  calls, commission or renewals depend on are marked `system: true` — they can be relabelled or
  hidden, never deleted or retyped.
- **Stages map to categories.** The reason statuses are locked today is that call outcomes, follow-ups
  and reports depend on them. Instead of locking the list, every custom stage is mapped to one of the
  existing categories (*being worked / parked / finished-won / finished-lost*, plus *quote sent* and
  *documents pending* where those workflows apply). The code tests the category, not the label, so a
  company can rename "Interested" to "Hot" or add "Site Visit" without breaking the funnel.
- **Field types are a closed list:** text, long text, number, currency, date, date-time, yes/no,
  single choice, multiple choice, phone, email, lookup (link to another record), file. Each type owns
  its validation and its filter operators. No free-form "formula" type in the first release.
- **Custom values live under `record.custom.<key>`** in the existing JSONB, so they never collide with
  system fields. The current untyped `customFields` from imports are migrated into it.
- **Versioned and reversible.** Every change creates a new config version with author, time, reason and
  diff. Any earlier version can be restored. Removing a field hides it; the data stays.

### 3.2 How the engine uses it

- **Validation:** a `crm_schema.py` module (pure functions, like `crm_metrics.py`) validates a record
  against the config. `save_db()` calls it, so forms, imports, webhooks, call outcomes and automations
  all get the same rules.
- **API:** `GET /api/schema` returns the caller's view of the config (filtered by their role).
  `LeadModel` keeps its system fields and accepts a validated `custom` block.
- **Screens:** forms, lead detail, list columns, filters and kanban are rendered from `/api/schema`
  instead of hand-written HTML. Car and health become the first two *configured* product templates —
  proving the model by rebuilding what exists.
- **Automation:** `crm_automation.FIELDS` is built from the registry, so a rule can say
  *"if Engine CC > 500"*.
- **Imports and webhooks:** the column-mapping screen offers custom fields as targets.
- **Reports and dashboards:** group and filter by any choice field; measures still come only from
  `crm_metrics.py`.
- **Export/backup:** custom fields become spreadsheet columns; the config is included in every export
  and backup so a restore brings the shape back with the data.

### 3.3 The AI builder

```text
Owner types a request
        │
        ▼
AI reads: current config (not customer records) + the list of allowed operations
        │
        ▼
AI returns a *change set* — structured operations only, e.g.
   add_field(lead, "engine_cc", number, section="Bike details", product="Bike")
   add_pipeline_stage("Bike", "Inspection", category="being_worked", after="Interested")
   add_automation(when=lead.expiring days=45, then=create_task …)
        │
        ▼
Server validates every operation against the schema rules  ──►  rejected ops explained to owner
        │
        ▼
Preview: plain-English summary + before/after form + "these 3 rules / 120 records are affected"
        │
        ▼
Owner approves  ──►  new config version, audited, one-click undo
```

Principles:

- **Operations, not code.** The model can only call a fixed set of tools (`add_field`,
  `rename_field`, `hide_field`, `add_choice`, `add_stage`, `add_product`, `set_form_layout`,
  `add_view`, `add_automation`, `add_dashboard_panel`, …). Anything outside that list is refused.
  This is exactly what the owner could do by hand in the settings screens — AI is a faster way to
  fill them in, never extra power.
- **Nothing applies without approval.** Same idea as automation rules starting switched off today.
- **The AI sees the shape, not the data.** The builder gets field definitions and counts, never
  customer names or phone numbers. (The existing advisor, which does read records, keeps its own
  guardrails.)
- **Owner/Admin only**, rate-limited, every prompt and resulting change set audited.
- **Works without AI.** Every operation also has a normal settings screen. If no AI key is configured
  the CRM is still fully customizable — same principle the advisor already follows.
- **Provider:** call the model through one adapter (today the advisor uses OpenRouter). Use tool-use /
  structured output so the response is machine-validated rather than parsed from prose.

Later AI uses, in the same "propose → approve" shape: *"build me a report of bike leads by source"*,
*"suggest automations from how my team actually works"*, *"map this spreadsheet's columns"*, and a
starter setup from a short business description during onboarding.

## 4. Delivery phases

Each phase ships on its own, keeps all existing tests green, and adds blueprint-style tests.

### Phase 0 — Groundwork (≈1–2 weeks)

- Split `pipecat_server.py` into routers by area (leads, calls, policies, settings, …) without changing
  behaviour. Customization touches every area; doing it in a 9,000-line file is where regressions hide.
- Introduce `crm_schema.py` with the field-type catalogue and validators, fully unit-tested.
- Decide D1–D5 below.

### Phase 1 — Custom fields (≈2–3 weeks) · *first visible value*

- Config v1 with `fields` for lead, customer and policy; versioning and audit.
- Settings → **Fields** screen: add, rename, reorder, hide, choices, required.
- Lead/customer/policy forms and detail cards render custom fields from `/api/schema`.
- Validation in `save_db()`; imports and webhooks map to custom fields; existing `customFields`
  migrated; export/backup include them.
- Automation conditions and list filters can use custom fields.

### Phase 2 — Products, pipelines and layouts (≈3–4 weeks)

- Products as configuration: each product has its own detail section and its own pipeline.
- Stages mapped to system categories; replace hard-coded status checks with category checks
  (`_checked_status_change`, metrics, call outcomes, reports). This is the riskiest refactor — the
  blueprint tests are the safety net.
- Car and health rebuilt as configured templates (proof that the model is complete).
- Form layout editor (sections, order) and saved list/kanban views per role.

### Phase 3 — AI builder (≈2–3 weeks)

- Operation catalogue + server-side validator + diff/preview + apply/undo.
- Chat panel in Settings ("Customize with AI"), Owner only.
- Evaluation set: ~50 realistic owner requests (including ambiguous and malicious ones) with expected
  change sets, run in CI against the validator so a model change can't quietly regress.

### Phase 4 — Deeper customization (≈4+ weeks, prioritise with users)

- Custom objects (e.g. *Vehicle Inspection*, *Claim*) with lookups to existing records.
- Field-level permissions and custom roles on top of the four system roles.
- Configurable dashboards and reports from `crm_metrics` measures.
- AI suggestions: automations, reports, onboarding templates.
- Config templates: export one company's setup and start another from it.

## 5. Decisions needed before Phase 1

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | Who are "the actual users"? Only this insurance client, other insurance agencies, or any small business? | Insurance agencies first (car/health/bike/life/travel). The data model in §3 is industry-neutral, so other industries stay possible without committing to them now. |
| D2 | Can a company change the lead statuses? | Yes, via stage categories (§3.1). Today's lock exists only because code tests labels. |
| D3 | Which AI provider and who pays for usage? | One adapter; Claude via tool use. Add a per-company monthly usage cap — the current advisor has none (the old Frappe app did). |
| D4 | Does the existing client want this now, or does it follow their blueprint scope? | Ship Phase 1 to them as a settings feature; it doesn't conflict with the blueprint and removes "car/health fields to be confirmed" from the open-questions list. |
| D5 | Self-serve signup for new companies? | Not until Phase 2; `/api/auth/bootstrap` works for onboarding by hand meanwhile. |

## 6. Risks and how we handle them

| Risk | Mitigation |
| --- | --- |
| Custom stages break calls, renewals, commission or reports | Stage categories; system fields protected; blueprint tests run on every phase |
| AI proposes something harmful or wrong | Closed operation list, server validation, preview, owner approval, undo |
| Prompt injection via record content | Builder never receives record data; only config and counts |
| Deleted field loses data | Fields are hidden, never purged; config versions restorable; included in backups |
| Performance with many custom fields | JSONB + existing GIN index; add expression indexes for fields used in filters if needed |
| Front-end complexity in a 5,000-line vanilla JS file | Build a small schema-driven form/table renderer once and reuse it; split `app.js` by screen as we touch it |

## 7. Suggested first step

Phase 0 plus a thin slice of Phase 1: **custom fields on leads only**, end to end (define in Settings →
appears on the lead form → validated on save → filterable → usable in an automation → in the export).
It proves the whole chain on one object in about two weeks, and everything after it is repetition and
widening.
