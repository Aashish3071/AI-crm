# InsureCRM — Enterprise Commercial Insurance Platform

> **A High-Density Relationship Management & Pipeline Operations System Engineered for Commercial Insurance Brokers and Risk Advisors.**

## Current Product Scope (September 2026)

InsureCRM is being developed CRM-first. AI voice calling is intentionally deferred until the customer, policy, renewal, permission, consent, and audit foundations are production-ready.

The product is split into two operational areas:

- **Leads & Accounts** is the pre-sale workspace for prospect capture, qualification, ownership, follow-ups, and conversion.
- **Insurance Operations** is the post-qualification workspace for customer policies, issuance, renewal cases, competing insurer quotations, retention outcomes, and communication history.

Currently implemented in the working prototype: customer creation during lead conversion, multiple linked policies and contacts, policy issuance validation, renewal generation and stages, quotation records, communication history, consent/opt-out enforcement, escalation notifications, and audit events for conversion and issuance. Policy, quotation, and communication entry use in-app forms rather than browser prompts.

Production work still in progress: complete customer/organization/contact editing screens, visual quotation selection, renewal completion into a successor policy, scheduled background reminders, notification and template management screens, authentication/RBAC, PostgreSQL migrations, document storage, automated backup/restore, and audit coverage for every mutation. The JSON database remains prototype-only and must not be used for a commercial deployment.

### End-to-end lifecycle and calculations

The backend now owns lifecycle synchronization: lead creation provisions organization/contact/task records; conversion creates a customer and draft policy; issuance activates the policy; renewal generation creates a linked renewal case; quote selection identifies the winning insurer offer; renewal completion expires the prior policy and issues a linked successor policy. `/api/lifecycle/{lead_id}` returns the complete connected record for verification.

Premium calculations are server-side: `tax_amount = net_premium × tax_rate ÷ 100` and `total_premium = net_premium + tax_amount`. Days remaining is recalculated from `expiry_date - current_date`. Renewal retention is `renewed_closed_cases ÷ all_closed_cases × 100`. Frontend values are display-only; backend results are authoritative.

Lead-table checkboxes now open a bulk-selection toolbar. Deleting a lead cascades to its linked customer, policies, renewals, quotations, tasks, communications, consent records, notifications, matching deal/contact records, and an organization only when no surviving record still uses it. Activity notes are never deleted: they are marked as archived with the deleted lead identifier and preserved as historical evidence. The cascade itself is retained in the audit log.

### Daily work management

The CRM is the broker's operating workspace, not just a database. Individual leads can be edited from the 360° drawer, including identity, company, phone, email, insurance requirement, premium, expiry date, owner, next action and due date. Lead-table selection supports bulk assignment and bulk follow-up scheduling in addition to deletion. Scheduling a bulk follow-up creates actionable task records. Tasks classify work as Follow-up, Call, Meeting, Email, Document Collection, Quotation or General Task. Owner changes synchronize linked open tasks, while contact changes synchronize the lead's linked contact record.

### User onboarding guide

First-time users see a six-card workflow guide explaining Leads & Accounts, Action Tasks, Pipeline Deals, Contacts & Organizations, Insurance Operations, and Dashboard. Every card opens the relevant module so onboarding teaches the real workflow rather than presenting passive documentation. Users may dismiss automatic display, and the persistent `? Guide` control in the header reopens it at any time.

---

## 🎯 Vision, Mission & Core Values

### Our Vision
To build the most disciplined, high-velocity commercial insurance relationship platform in the industry—where no policy renewal is ever lost to neglect, and every broker action drives measurable financial retention.

### Our Mission
Empower commercial insurance brokerages and agencies with enterprise-grade operational software that replaces bloated, school-like ERPs with high-density execution workflows, mandatory next-action discipline, and intelligent conversational copilot capabilities.

### Our Core Philosophy: The 3-Pillar Operational Standard
Every screen, button, and interaction in InsureCRM is measured against three non-negotiable operational principles:

| Pillar | Focus | What InsureCRM Delivers |
| :--- | :--- | :--- |
| **1. Effectiveness** | *Makes You Money* | **Zero Dead Leads**: Every account requires a scheduled **Next Action** and **Due Date**. No record becomes an untracked, forgotten row. Proactive renewal radar alerts for policies expiring in &le;15 days to protect recurring commissions. |
| **2. Efficiency** | *Saves You Time* | **Single-Screen High-Density Workspace**: Linear and Stripe-inspired data density. Dual List/Kanban views, triaged task buckets (`Overdue`, `Due Today`, `Upcoming`), and instant 360° slide-over drawers eliminate page reloads. |
| **3. Quality** | *Improves Client Experience* | **Audit & Underwriting Integrity**: Full chronological activity ledgers for surveyor reports and terms. Loss-reason tracking on every dropped account. Micro-vector iconography with zero toy emojis. |

---

## 🏛️ System Architecture

InsureCRM is built on a clean, unified architecture separating presentation from persistent transactional state:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Client Layer (Single Page App)                    │
│       Tailwind CSS • Inter Typography • Tabular Numerals • Micro-SVGs        │
├──────────────────────────────┬──────────────────────────────┬───────────────┤
│    Leads & Accounts Engine   │    Triaged Task Center       │  AI Advisor   │
│  - High-Density Table View   │  - Overdue / Today / Upcoming│  - Copilot    │
│  - 6-Stage Kanban Board      │  - Interactive Checkbox Sync │  - Instant DB │
│  - Next Action Discipline    │  - 360° Drawer Deep Links    │    Analytics  │
└──────────────────────────────┴──────────────┬───────────────┴───────────────┘
                                              │ HTTP REST / JSON / WebSocket
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     FastAPI Application Server (Python 3.14)                │
├──────────────────────────────┬──────────────────────────────┬───────────────┤
│    Pipeline Stage Manager    │  Polymorphic Entity Ledger   │ Batch Import  │
│  - 6 Confirmed Stages        │  - Activity Notes & Memos    │ - CSV Parser  │
│  - PUT /api/leads/{id}/stage │  - Action Tasks (Due Dates)  │ - Dedup Rules │
│  - Auto-Audit Memo Logging   │  - Contacts & Organizations  │   (Skip/Update│
└──────────────────────────────┴──────────────┬───────────────┴───────────────┘
                                              │ Atomic JSON File I/O
                                              ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Persistent Database (crm_db.json)                        │
│          Commercial Accounts • Policies • Tasks • Memos • Deals             │
└─────────────────────────────────────────────────────────────────────────────┘
```

For the full architectural specification, refer to [ARCHITECTURE.md](file:///Users/aaravsharma/Desktop/AI%20Call/ARCHITECTURE.md).

---

## ⚡ Core Operational Features

### 1. The 6 Confirmed Commercial Insurance Stages
Standardized across the entire platform to mirror real commercial insurance closing cycles:
1. `New` — Inbound opportunity or policy renewal identification.
2. `Contacted` — Initial broker discovery and policy scoping.
3. `Risk / Underwriting` — Surveyor site inspection, NCB verification, and underwriter slip drafting.
4. `Quotation Sent` — Delivery of comparative quotes across insurers (ICICI Lombard, Tata AIG, HDFC ERGO, Bajaj Allianz).
5. `Won` — Premium collected, cover note and policy schedule bound.
6. `Lost` — Competitor loss or underwriter rejection (mandatory audit reason required).

### 2. Next Action Discipline Engine
- Changing an account's stage (via table pill, Kanban card drop, or 360° drawer chevron) opens the **Stage Transition Modal**.
- The broker must confirm:
  - **Target Stage**
  - **Scheduled Next Action** (*"Collect Fleet RC Books"*, *"Dispatch Surveyor"*, *"Deliver Comparative Quote"*, *"Negotiate Terms"*)
  - **Next Action Due Date**
  - **Conversation / Surveyor Memo**
- Submitting atomically updates the lead, logs an immutable audit note in the timeline, and provisions a task in the broker's agenda.

### 3. Triaged Action Task Center
- Tasks are automatically grouped into operational triage tabs:
  - **All Tasks**
  - **Overdue** *(high-contrast red badge)* — Immediate attention required.
  - **Due Today** *(amber badge)* — Today's execution queue.
  - **Upcoming** — Forward pipeline.
  - **Completed** — Audit archive.
- Interactive checkboxes toggle completion state in real time with backend persistence (`PUT /api/tasks/{id}`).
- Clicking any task row or account badge opens the **Lead 360° Drawer** so the broker can act immediately.

### 4. Polymorphic Activity Notes & Memos
- Notes attach directly to commercial accounts (`Lead`, `Organization`, `Deal`).
- Filter by category: `Underwriting Note`, `Risk Assessment`, `Stage Progression`, `Meeting Minutes`, or `General Memo`.
- Prominent account header badge allows one-click navigation directly to the client's 360° record.

### 5. 360° Slide-Over Account Drawer
- Stage progress chevron bar (`New > Contacted > Risk/UW > Quotation Sent > Won`).
- Pinned Next Action card with due date alert.
- Complete commercial policy schedule (Category, Premium, Expiry, Days Remaining, Policy #).
- Chronological activity timeline of all client interactions.

### 6. AI Executive Advisor Copilot
- Unobtrusive slide-over assistant accessible via floating trigger button.
- Query pipeline health in plain English:
  - *"Which policies are expiring in the next 15 days?"*
  - *"Show me active next actions and due dates"*
  - *"What is our current pipeline stage breakdown?"*

---

## 📂 Project Repository Structure

```
├── ARCHITECTURE.md                  # Comprehensive technical & system architecture spec
├── README.md                        # Product overview, mission, and user guide
├── Read.md                          # Quick-reference documentation pointer
├── pipecat_server.py                # FastAPI backend server & REST API endpoints
├── pipecat_agent.py                 # Conversational voice agent engine (Sarvam AI / TTS)
├── crm_db.json                      # Persistent database for commercial accounts & activity
├── requirements.txt                 # Python project dependencies
├── web/
│   ├── index.html                   # High-density corporate SPA interface
│   ├── app.js                       # Client engine (Dual views, Next Action modal, 360° drawer)
│   └── style.css                    # Corporate design tokens, tabular numerals, chevron steps
└── scratch/
    ├── test_corporate_crm.py        # Automated test suite for stages, discipline & UI
    └── test_notes_tasks_ux.py       # Automated test suite for triaged tasks & notes UX
```

---

## 🚀 Getting Started & Local Setup

### 1. Prerequisites
- Python 3.11+ (or the preconfigured `.venv` at `.venv/bin/python3`)
- Modern web browser (Chrome, Safari, Edge, Firefox)

### 2. Install Dependencies
```bash
.venv/bin/pip install -r requirements.txt
```

### 3. Launch the Server
```bash
.venv/bin/python3 -m uvicorn pipecat_server:app --host 0.0.0.0 --port 8080 --reload
```
The application will be live at **`http://localhost:8080/`**.

---

## 🧪 Automated Verification & Testing

Run the automated test suites to verify backend integrity, stage transition discipline, and corporate frontend UI compliance:

```bash
# 1. Verify Confirmed 6 Stages, Next Action Discipline & Clean UI Standards
.venv/bin/python3 scratch/test_corporate_crm.py

# 2. Verify Triaged Tasks, Polymorphic Notes & Modal Functionality
.venv/bin/python3 scratch/test_notes_tasks_ux.py
```

Expected output:
```bash
✅ ALL CORPORATE CRM VERIFICATION CHECKS PASSED!
✅ ALL NOTES, TASKS & MODAL TESTS PASSED!
```

## Commercial CRM Release — September 2026

The daily-use CRM has been expanded as one connected workflow rather than independent screens:

- **Dashboard-first startup:** every fresh page load opens the operational dashboard; users enter individual work queues from there. Settings navigation visibly follows the selected settings section.

- **Guided conversion:** a lead is confirmed into a permanent customer, linked organization and contacts, a won deal and a draft policy. The conversion is audited and prevents duplicate conversion.
- **Unambiguous conversion action:** selecting exactly one lead now exposes **Convert to Customer** in the selection toolbar. Bulk conversion is intentionally disallowed because customer, policy and ownership details must be confirmed for each account.
- **Customer 360°:** searchable customer master records expose linked contacts, multiple policies, communications and customer-edit audit history.
- **Editable masters:** customers, deals, contacts, organizations and policies now use proper modal forms; renewal loss/lapse, issuance and completion no longer use browser prompts.
- **Separate policy and renewal workspaces:** policy registration/issuance and renewal/quotation work are distinct navigation destinations backed by the same lifecycle records.
- **Policy issuance:** final policy number plus a proposal/KYC/payment/schedule checklist is required before issuance. Premium, tax and total premium are calculated by the backend.
- **Renewal completion:** a selected insurer quotation can generate a successor policy while linking and closing the previous policy.
- **Notification inbox:** escalation checks, read/unread, assignment and snooze actions are available. A five-minute background worker creates deduplicated overdue-renewal alerts.
- **Documents:** allow-listed uploads up to 10 MB, SHA-256 checksums, categories, version metadata, browser preview/download and archive status.
- **Data quality:** duplicate lead detection and merge APIs, validation-aware CSV import results, reversible lead archive/restore and retained historical notes.
- **Operations:** conversion/retention/workload/lost-reason reporting, configurable stages/products/insurers, health status, manual backups and restore with an automatic pre-restore safety copy.
- **Accessibility and responsive layout:** visible keyboard focus, reduced-motion support and compact mobile navigation.

Run the current backend acceptance suite:

```bash
.venv/bin/python3 -m unittest test_insurance_operations.py
```

The suite currently covers eleven workflows, including lead-to-renewal completion, relational sync, cascading deletion with note retention, customer 360°, document versioning, backups, duplicate merge, archive/restore, policy checklist enforcement, notification operations, lead-source ingestion/deduplication, and the message-template archive/restore/delete lifecycle.

### Navigation and message-template lifecycle

- The header breadcrumb is interactive: **Dashboard** returns to the operational overview, while the current-module crumb reloads that module.
- Every shared form and setup dialog has a consistent header-level **Back** control. In the lead-source wizard, Back returns from provider details to provider selection; on the first step it closes the dialog.
- Active message templates are reusable starting points offered by **Send message** on a lead or customer record. Archiving removes a template from sending without removing its audit history.
- Archived templates live in a collapsed history section in Settings. They can be restored, or permanently deleted after an explicit confirmation. Only an already archived template can be permanently deleted.

### Accessible Lead Sources setup

Connecting an advertising source now uses a three-step progressive workflow:

1. Choose Meta, Google Ads or LinkedIn; less-common website, WhatsApp, email and automation sources stay in a collapsed secondary group.
2. Enter only a friendly connection name and, optionally, a default insurance product. The CRM generates callback and verification values automatically.
3. Copy the generated values into the provider and run **Test connection**. The test must create an attributed lead and follow-up task; repeating it must match the existing lead rather than duplicate it.

Field mapping, sending credentials, pause and disconnect controls are intentionally placed under **More options**. Setup instructions are collapsed after the source has received its first enquiry. The dialog has an accessible name, keyboard focus styles, plain-language help and live status announcements.

### Commercial deployment boundaries

This repository still uses the local JSON persistence adapter and simulated outbound delivery. Before real users are onboarded, complete the previously excluded authentication/role model and PostgreSQL migration, then select and configure production Email/SMS/WhatsApp providers, encrypted object storage, secrets management, monitoring, hosted backup retention and a tested disaster-recovery environment. AI voice calling remains intentionally outside the CRM-first release.
