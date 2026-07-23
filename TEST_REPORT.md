# AI CRM — Security Sweep, Feature Test & Gap Report

**Date:** 23 July 2026
**Stack:** Frappe Framework 15.115.4 · Frappe CRM 2.0.0-dev (`develop` @ `988211b`) · custom app `ai_crm` · LM Studio (`qwen/qwen3-4b`) via OpenAI-compatible API
**Test environment:** local Docker devcontainer, site `crm.localhost`, demo data loaded

---

## 1. Security sweep — findings & fixes

All issues below were found in the custom `ai_crm` app, fixed, and **verified live** against the running instance.

| # | Severity | Issue | Fix | Live verification |
|---|----------|-------|-----|-------------------|
| 1 | Critical | `get_ai_settings` was whitelisted and returned the **decrypted API key** to any logged-in user | Removed from client API surface (server-internal only) | `POST /api/method/ai_crm.api.get_ai_settings` → **403 not whitelisted** |
| 2 | Critical | LLM calls had `timeout=None` — a hung model call could freeze web workers indefinitely | Finite `timeout=(10, 120)` + explicit timeout handling | Timeout error logged cleanly in Error Log during test (job failed safely, site unaffected) |
| 3 | Critical | `smart_entry` created leads with `ignore_permissions=True` and no permission check | Real `create` permission check; `ignore_permissions` removed; LLM-extracted email validated | Endpoint works through permission-checked path (lead CRM-LEAD-2026-00016 created) |
| 4 | High | Raw exception text leaked to clients | Generic client message; full traceback logged server-side only | Confirmed in code + compile check |
| 5 | High | No rate limits or input caps on AI endpoints (cost/abuse exposure) | `@rate_limit` on all 4 endpoints; 10k-char cap on `smart_entry`, 2k-char cap on `chat_query` | 2,500-char query → **417 "Query is too long"** |
| 6 | High | Daily stale-lead job enqueued unlimited LLM calls | Capped at 50/run, oldest first | Code review + compile check |
| 7 | Medium | `score_lead` / `recommend_action` required only **read** permission but wrote to the lead | Tightened to **write** permission | Code review + live scoring succeeded as authorized user |

**Also checked, clean:** AIAdvisorPanel.vue (no XSS — safe `{{ }}` interpolation, no `v-html`; no hardcoded secrets), all modified CRM frontend files, no secrets anywhere in the repository, no console errors in any tested page.

**Known non-blocking quirk:** the installed bench copy of `ai_crm` has structural drift (stray `aicrm/` module dir, empty `modules.txt`). The repository copy is clean and authoritative; a fresh install from this repo does not have the issue.

---

## 2. Feature test matrix

### Tested and working ✅

| Feature | What was tested | Result |
|---------|-----------------|--------|
| Authentication | Login via web UI | ✅ Session established |
| Leads — list | List view, columns, pagination, filters present | ✅ Renders (7→16 records through test) |
| Leads — create | Created "Priya Deshmukh / Meridian Logistics" via UI dialog | ✅ `CRM-LEAD-2026-00015` created, activity logged |
| Leads — detail | Tabs (Activity, Emails, Comments, Data, Calls, Tasks, Notes, Attachments), side panel fields | ✅ Renders fully |
| **AI Predictive Lead Score card** | Custom UI card on lead page | ✅ Renders with score badge + Recalculate / Draft buttons |
| **AI lead scoring (manual)** | `score_lead` end-to-end incl. LLM | ✅ Score 45 + explanation saved |
| **AI lead scoring (automatic)** | `after_insert` hook → queue → worker → LLM | ✅ Lead 16 auto-scored 70 with explanation |
| **AI follow-up draft** | `recommend_action` end-to-end | ✅ Personalized subject + body generated & saved |
| **AI Advisor chat** | `chat_query` — "lead status breakdown" | ✅ Answer matched DB exactly (4 New / 7 Qualified / 2 Nurture / 2 Contacted = 15) |
| **AI smart entry** | Raw email → structured lead | ✅ Extracted name, org, title, challenge; created `CRM-LEAD-2026-00016` |
| Lead → Deal conversion | `convert_to_deal` with mandatory-field validation | ✅ `CRM-DEAL-2026-00008` created; validation enforced |
| Deals | List view, multi-currency values, pipeline statuses | ✅ 7 deals render |
| Contacts | List view | ✅ 11 contacts render |
| Organizations | List view | ✅ Renders |
| Notes | Notes view with rich content | ✅ 6 notes render |
| Tasks | List, priorities, statuses, due dates, assignment | ✅ 6 tasks render |
| Calendar | Week view | ✅ Renders |
| Call Logs | List, direction, duration, status | ✅ 6 logs render |
| Dashboard | KPIs, sales trend, forecast, funnel, sources, territories | ✅ Full analytics render |
| Background workers | RQ queue processing + failure logging | ✅ Job ran; a slow-LLM job failed *safely* with a logged 120s timeout |
| Security regressions | Key-leak endpoint blocked; input caps active | ✅ 403 / 417 confirmed |

### Present but not testable in this environment ⚠️

| Feature | Why untested | What it needs |
|---------|--------------|---------------|
| Email sending/receiving from CRM | No SMTP/IMAP account configured | Configure an email account + SPF/DKIM/DMARC before customer use |
| Email templates | 0 templates defined | Create templates (feature surface exists) |
| Telephony — Twilio / Exotel | Requires paid accounts + keys | Customer-specific setup |
| WhatsApp | The separate Frappe WhatsApp app is **not installed** | Install + Meta Business API |
| Facebook Lead Syncing | Requires Meta developer account + access token | Customer-specific setup |
| ERPNext integration | Backend exists; settings tab intentionally removed in this fork | N/A (removed by design) |
| Invite team / multi-user flows | Needs outbound email working | SMTP first |

**Test-environment note:** the local `qwen3-4b` model takes 20–120s per response (thinking mode). One background job exceeded the 120s job timeout and failed safely. For production, use a faster hosted model or raise job timeouts.

---

## 3. Feature inventory & use cases

**Core CRM (from Frappe CRM):**
- **Leads** — capture and qualify prospects; statuses (New/Contacted/Nurture/Qualified/Unqualified/Junk), assignment, territories, industries, sources
- **Deals** — pipeline management with stages (Qualification → Negotiation → Won/Lost), multi-currency deal values, probability, expected close dates
- **Contacts & Organizations** — relationship records linked to leads/deals
- **Notes** — meeting/call notes attached to leads and deals (feed the AI's context)
- **Tasks** — follow-ups with priority, due date, assignee, kanban-style statuses
- **Calendar & Events** — scheduling view
- **Call Logs** — inbound/outbound call history with duration and outcome
- **Dashboard** — sales trend, forecasted vs actual revenue, funnel conversion, lost-deal reasons, source and territory analytics
- **Email in CRM** — send/receive against leads and deals (needs SMTP config)
- **Telephony** — Twilio and Exotel integrations for in-CRM calling (needs accounts)
- **Lead Syncing** — automatic lead capture from ad platforms; **currently Facebook only**
- **Assignment rules, SLA, custom fields/forms, brand settings** — admin configurability
- **Lead enrichment button** — "Enrich" action on lead page (upstream `develop` feature)

**AI layer (custom `ai_crm` app + fork customizations):**
- **AI Predictive Lead Score** — 0–100 conversion-likelihood score with explanation, on every lead; auto-scores new leads in the background; use case: prioritize the pipeline every morning
- **AI Follow-up Drafts** — personalized email drafts grounded in the lead's challenge + notes; one click to load into the email composer; use case: cut follow-up writing time
- **AI Advisor chat** — natural-language questions over live CRM data (counts, breakdowns, per-lead detail), permission-aware; use case: managers get answers without building reports
- **AI Smart Entry** — paste a raw enquiry email, get a structured lead; use case: zero-typing lead capture from inbound email
- **Stale-lead watchdog** — daily job drafts follow-ups for leads untouched 14+ days (capped at 50/day)
- **UI white-labeling** — Desk/About hidden for non-admin users *(cosmetic only — see gaps)*

---

## 4. Gap analysis (roadmap candidates)

| Gap | Detail | Effort signal |
|-----|--------|---------------|
| **Lead sources beyond Facebook** | `supportedSourceTypes` is a pluggable list with one entry. Google Lead Form Ads, TikTok, Snapchat, LinkedIn Lead Gen each need their own API integration + doctype mapping | Per-platform backend work; the frontend config is ready for it |
| **Generic webhook/web-form lead capture** | Fastest route to "capture from any platform": one authenticated webhook endpoint + Zapier/Make templates covers most ad platforms without per-platform builds | Recommended first roadmap item |
| **WhatsApp** | Supported by CRM but the companion app isn't installed | Install + Meta Business verification |
| **Email out-of-the-box** | No SMTP configured; email features dormant until then | Config, not code |
| **Desk hiding is cosmetic** | Non-admin users don't *see* the Desk link but `/app` is still reachable by URL; real restriction must come from Frappe roles | Configure roles properly per customer |
| **Unreleased base version** | Fork sits on CRM `develop` (2.0.0-dev), which itself declares Frappe 16 compatibility while running on Frappe 15 | Pin commit now; migrate to CRM v2 stable when released |
| **LLM latency & hosting** | Local LM Studio is dev-only; production needs a hosted/faster model and the endpoint is already configurable via AI CRM Settings | Config + provider choice (with DPA for PII) |

---

## 5. Production readiness (carried from deployment audit)

Code-level blockers are now fixed. Remaining before selling: production deployment stack (nginx/gunicorn/supervisor or frappe_docker production compose), HTTPS, rotated credentials, automated tested backups, SMTP, error monitoring, AGPL-3.0 compliance review, and privacy documentation for AI processing of customer PII (GDPR/UK-GDPR/PIPEDA/UAE PDPL). See the deployment runbook/checklist for details.
