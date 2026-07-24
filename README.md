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
- **Generic Lead-Capture Webhook** — one secured URL that turns any external payload into a CRM Lead, so leads from Google, Meta, LinkedIn, TikTok, web forms, etc. all flow in via Zapier/Make/webhooks (see below).

## Lead-capture webhook

A single endpoint captures leads from any platform, so you are not limited to the built-in Facebook sync.

**1. Enable it** (server-side secret, never exposed by any API):

```bash
bench --site <your-site> set-config crm_lead_webhook_token "$(openssl rand -hex 24)"
```

**2. Point Zapier / Make / a web form at:**

```
POST https://<your-domain>/api/method/ai_crm.api.capture_lead
Header:  X-CRM-Webhook-Token: <the token you set>
Body (JSON): { "first_name": "...", "email": "...", "organization": "...", "message": "..." }
```

Accepted fields: `first_name, last_name, email, mobile_no, phone, organization, job_title, website, lead_name, source, territory, industry`, plus a free-text `message`/`notes` mapped to the AI challenge field. Unknown fields are ignored; invalid link values (e.g. an unknown `source`) are dropped rather than failing. The endpoint is rate-limited (120/min) and requires at least one identifying field.

## White-labeling

This build is neutral ("CRM") with no upstream branding, so it can be resold as the customer's own product:

- **Per-customer brand** — set name, logo and favicon at runtime in **Settings → Custom Branding** (no rebuild).
- Browser tab, installable-app (PWA) name, login screen, onboarding and About dialog all read "CRM" / the custom brand — no "Frappe" text.
- Removed: the "Permissions update" banner, the Frappe Mail email option, the Frappe Cloud menu entry, and all external links to frappe.io / docs / blog.
- Email accounts still connect via Gmail, Outlook, and other standard providers (client-configured SMTP/IMAP).

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
2. `crm-tracked-changes.patch` — apply with `git apply` on a checkout of that commit (AI score card, AI Advisor wiring, and all white-label changes)
3. `frontend/src/components/Layouts/AIAdvisorPanel.vue` — new file; copy into the same path in the CRM app
4. Rebuild the CRM frontend (`yarn build` in `apps/crm`)

The patch also sets the CRM app title to "CRM" (`crm/hooks.py`, `crm/__init__.py`). After applying, run `bench --site <site> clear-cache` and restart so the new title and login-page brand take effect.

## Requirements

- Frappe Framework v15
- Frappe CRM (see `crm_customizations/BASE_COMMIT.txt` for the tested base)
- An OpenAI-compatible LLM endpoint
