# InsureCRM — Enterprise Commercial Insurance Platform

> **A High-Density Relationship Management & Pipeline Operations System Engineered for Commercial Insurance Brokers and Risk Advisors.**

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
