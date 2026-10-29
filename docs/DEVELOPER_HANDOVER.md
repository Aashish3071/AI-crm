# InsureCRM — Developer Handover

For the next developer. Read this first, then [ARCHITECTURE.md](../ARCHITECTURE.md) for the
reasoning behind each part. The client's requirement document, the *Insurance Telecalling
CRM Blueprint*, is the scope authority. Code comments and tests cite its slide numbers.

## Code map

| File | Responsibility |
| --- | --- |
| `pipecat_server.py` | The app and the shared core: configuration, middleware, loading and saving (`load_db`, `save_db` and its pipeline), visibility, audit, the lead lifecycle rules, call outcomes, the scheduler and every helper more than one area uses. Five routes stay here because other server code calls them directly. Sections are headed `# ─── Name (client blueprint, slide N) ───`. |
| `crm_security.py` | Passwords, sessions, CSRF, the four roles (`ROLES`, `normalized_role`), which roles may read or change which API paths (`may_read_path`, `may_mutate_path`), company context |
| `crm_metrics.py` | The single definition of every measure (calls, connect rate, conversion, premium, on-time rate…), targets, awards, incentive lines and the sales funnel. Its docstring is the reference table. Pure functions, no I/O. |
| `crm_automation.py` | The automation engine: triggers, conditions, actions, guardrails (depth limit, idempotency keys, hourly caps, pause) and assignment methods. Pure logic; the server registers the executors. |
| `crm_schema.py` | Custom field types, field-definition and value validation, and lead stage categories, for the [AI customization plan](AI_CUSTOMIZATION_PLAN.md). Pure functions; not yet wired into the server. |
| `crm_ai.py` | The only way to reach a language model: OpenRouter, model from `AI_MODEL`, per-company daily cap and per-company error reporting |
| `crm_routes/` | The API, one `APIRouter` per area (28 modules: `leads`, `calls`, `customers`, `policies`, `renewals`, `quotations`, `messaging`, `channels`, `imports`, `automation`, `dashboards`, …), each with the helpers only it uses. A module reaches shared helpers as `core.name` (`import pipecat_server as core`) at call time, so tests that swap the server's settings, or patch a helper such as `server._dispatch`, apply to it too. `pipecat_server` includes each router at the end of the file. |
| `tools/split_server.py`, `tools/check_split.py` | Move an area out of `pipecat_server.py` by route path, and prove a change left routing and the OpenAPI description identical. Run the check after any change that moves routes. |
| `crm_telephony.py` | Telephony provider interface. Only `manual` (the telecaller's own phone via `tel:`) exists; a cloud provider implements `place_call` and `parse_callback`. |
| `crm_store.py`, `crm_storage.py` | PostgreSQL record store and scheduler lock; local or S3 document storage |
| `crm_worker.py` | The production scheduler process |
| `crm_test_isolation.py`, `conftest.py` | Force every test onto temporary storage, so tests can never touch live data |
| `web/index.html`, `web/app.js`, `web/style.css` | The single-page interface: vanilla JavaScript, Tailwind classes, no build step |
| `migrations/`, `migrate_to_postgres.py` | PostgreSQL schema and the JSON-to-PostgreSQL migration |
| `pipecat_agent.py`, `test_lmstudio_pipeline.py`, `requirements.txt` | The separate AI voice-calling prototype. It is not part of the CRM and not in scope yet. |

## How data flows

- **One document per company.** `load_db()` returns the company's whole data set as a dict of
  collections (`leads`, `customers`, `policies`, `renewals`, `callLogs`, `quotations`, `tasks`,
  `notes`, `documents`, `communications`, `users`, `targets`, `automationRules`,
  `notifications`, `auditLogs`, …). `save_db()` writes it back with a revision check, so two
  concurrent saves cannot silently overwrite each other.
- **Loading migrates.** `_ensure_db_shape()` upgrades older data every time it is loaded:
  statuses, products, sources, owner ids, call durations, status history. Each step is safe
  to repeat.
- **Saving derives.** `save_db()` runs a fixed pipeline before writing: normalise leads →
  expire quotations → reconcile owner ids → fix commission on newly sold policies → fire
  automation events (by comparing each record with its `automationState` marker) → reconcile
  work notifications. Because events are detected at save time, every entry path — form,
  import, webhook, call outcome — behaves the same.
- **Stable ids link records.** Names are labels. A person has an id (`assignedToId`) as well
  as the display name kept in `assignedTo`.

## Who can see what

Two layers, and both must agree:

1. **Path level:** `crm_security.may_read_path` / `may_mutate_path`. For example, commission,
   backups and export are Owner-only.
2. **Record level:** `visible_owners(db)` returns the names the caller may see (`None` means
   everyone). `scoped()` filters lists, `require_visible()` guards single records (returning
   404, never 403, so a record's existence is not revealed), and `child_visible()` lets notes,
   documents and similar records follow their parent.

Any new endpoint that returns records must use these. `tests/test_client_blueprint.py`
contains cross-telecaller leak tests to copy.

## Where each blueprint area lives

| Slides | Area | Routes (`crm_routes/`) | Shared logic | Tests (class in `tests/test_client_blueprint.py`) |
| --- | --- | --- | --- | --- |
| 10 | Roles and access | `team.py` | `crm_security.py`, `visible_owners` | `RolesAndAccess`, `RecordVisibility` |
| 11, 43 | Retail leads | `leads.py` (`LeadModel`, `create_lead`) | `_normalize_leads` | `RetailLeadCapture`, `LeadLifecycle` |
| 12 | Assignment | `automation.py`, `team.py` (`set_availability`) | `_pick_assignee` | `AssignmentMethods` |
| 14, 34, 47 | Dashboards | `dashboards.py` (`telecaller_dashboard`, `owner_dashboard`) | `crm_metrics.py` | `Performance` |
| 15–16 | Calling and outcomes | `calls.py` (`apply_call_outcome`) | `crm_telephony.py`, `CALL_OUTCOMES` | `Calling` |
| 17 | Follow-ups and alerts | `follow_ups.py`, `notifications.py` | `run_escalations` | `FollowUps` |
| 18 | Customer 360 | `customers.py` (`get_customer`) | | `Customer360` |
| 19, 21 | Documents and WhatsApp | `documents.py` (`_store_document`), `messaging.py` | `document_status`, `_compose_lead_message` | `Documents` |
| 20 | Quotations | `quotations.py` (`_quote_moves_lead`) | `QUOTE_TRANSITIONS` | `Quotations` |
| 23–24 | Renewals | `renewals.py` (`renewal_dashboard`) | `run_renewal_tracking` | `Renewals` |
| 25–30 | Commission, targets, incentives, leaderboard | `commission.py`, `dashboards.py`, `incentives.py` | `crm_metrics.py` | `Performance`, `MoneyAndRecognition` |
| 31–32 | Reports | `reports.py` (`get_reports`) | `crm_metrics.cohort/funnel/by_source` | `Reports` |
| 33 | Automation | `automation.py` (`RECIPES`) | `crm_automation.py` | `Automation`, `TargetAchieved` |
| 41–42 | Export, backups | `backups.py` (`export_data`) | | `DataExport` |

Search for `slide(` in the tests to list every requirement proven, with its slide.

## Tests

```bash
.venv/bin/pip install -r requirements-crm.txt -r requirements-test.txt
.venv/bin/python3 -m playwright install chromium
PYTHONWARNINGS=ignore .venv/bin/python3 -m pytest tests/test_client_blueprint.py tests/test_blueprint_acceptance.py \
    tests/test_e2e_remediation.py tests/test_workflow_integrity.py test_insurance_operations.py test_security_foundation.py \
    tests/test_crm_schema.py tests/test_ai_advisor.py -q
PYTHONWARNINGS=ignore .venv/bin/python3 -m pytest tests/test_browser_flows.py tests/test_blueprint_browser.py -q
```

Tests always run on temporary storage (`crm_test_isolation.py` is imported before the app).
Never point a test at real data. `tests/test_client_blueprint.py` signs in real users over
HTTP and never calls internal functions to fake a result. Follow that pattern.

## Conventions

- **Never invent data.** No placeholder premiums, cities or owners. An unknown value stays
  empty, and a measure with nothing to divide by is `None` (shown as "—"), never 0%.
- **One definition per number.** Add a measure to `crm_metrics.py`; don't compute it in an
  endpoint or in JavaScript.
- **The screens read vocabularies from the server** (`/api/lead-options`, `/api/calls/options`)
  rather than keeping their own copies.
- **Every change is audited** with `audit(db, action, entity, id, details)`.
- **Documentation travels with the code.** Update `ARCHITECTURE.md` and the README release
  notes with every change.
- **Route order matters in FastAPI.** A fixed path such as `/api/automations/pause` must be
  declared before `/api/automations/{id}`.

## Known limits and open decisions

- **Telephony:** only the manual provider exists; recordings need a cloud provider (client to choose).
- **Car and health lead fields:** the field list is a reasonable set, still to be confirmed by the client.
- **Retention and deletion controls** (slide 41) and a per-view access log are not built yet.
- **JSON storage** is for development and small single-machine installs; production uses PostgreSQL.
- **AI calling** (the client's phases 3–4) is out of scope for now.
- **Browser tests need the internet:** `web/index.html` loads Tailwind from `cdn.tailwindcss.com`. Without it no element is hidden, and the browser tests fail.
