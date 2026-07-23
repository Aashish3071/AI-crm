# AI CRM

AI enhancements for [Frappe CRM](https://github.com/frappe/crm): predictive lead scoring, AI-drafted follow-ups, chat-based CRM insights, and smart lead entry from raw emails — powered by any OpenAI-compatible LLM endpoint (LM Studio, OpenAI, etc.).

## What's in this repository

| Path | What it is |
|------|-----------|
| `ai_crm/` | The Frappe app: API endpoints, document hooks, scheduler jobs, AI CRM Settings doctype |
| `crm_customizations/` | Frontend customizations applied on top of Frappe CRM (see below) |
| `TEST_REPORT.md` | Security sweep, feature test matrix, and gap analysis (23 Jul 2026) |

## Features

- **AI Predictive Lead Score** — every lead gets a 0–100 conversion-likelihood score with a plain-English explanation. New leads are scored automatically in the background.
- **AI Follow-up Drafts** — one click generates a personalized follow-up email grounded in the lead's recorded challenges and notes.
- **AI Advisor** — a chat panel that answers questions about live CRM data (lead breakdowns, deals in play, pending follow-ups), respecting user permissions.
- **Smart Entry** — paste a raw enquiry email; the AI extracts name, company, role and pain-point and creates a structured lead.
- **Stale-lead watchdog** — a daily job drafts follow-ups for leads with no activity in 14 days (capped at 50/day).

## Security hardening (applied)

- LLM API key is never exposed to clients (server-side only)
- Finite timeouts on all LLM calls
- Permission checks on every endpoint (create/write enforced, no `ignore_permissions`)
- Rate limits and input-length caps on all AI endpoints
- Generic client errors; full tracebacks only in server logs

See `TEST_REPORT.md` for the full audit and live verification results.

## Installation

```bash
bench get-app https://github.com/Aashish3071/AI-crm
bench --site <your-site> install-app ai_crm
```

Then set your LLM endpoint in **AI CRM Settings** (API URL, model name, API key). Any OpenAI-compatible `/chat/completions` endpoint works.

## `crm_customizations/` — applying the frontend changes

The AI Advisor panel and AI score card live in the Frappe CRM frontend, not in this app. `crm_customizations/` contains everything needed to recreate that fork:

1. `BASE_COMMIT.txt` — the exact upstream `frappe/crm` commit these changes were built against
2. `crm-tracked-changes-*.patch` — apply with `git apply` on a checkout of that commit
3. `frontend/src/components/Layouts/AIAdvisorPanel.vue` — new file; copy into the same path in the CRM app
4. Rebuild the CRM frontend (`yarn build` in `apps/crm`)

## Requirements

- Frappe Framework v15
- Frappe CRM (see `crm_customizations/BASE_COMMIT.txt` for the tested base)
- An OpenAI-compatible LLM endpoint
