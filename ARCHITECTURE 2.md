# InsureCRM — Enterprise System Architecture Specification

> **A High-Density Commercial Insurance Operating System & Relationship Management Platform**

## Implementation Status and Module Boundary

**CRM-first direction:** voice automation is outside the current production milestone.

```text
Lead capture → Qualification → Customer conversion → Policy issuance
                                                ↓
                              Insurance Operations
                       Policy servicing → Renewal case
                             ↓                 ↓
                    Communication       Quote comparison
                             ↓                 ↓
                       Audit trail ← Renewal outcome
```

`Leads & Accounts` owns pre-sale acquisition and qualification. `Insurance Operations` owns the durable customer-policy relationship after qualification: multiple policies, issuance, renewals, insurer quotations, outcomes, and communication history.

The current persistence adapter is atomic JSON for prototype compatibility. The production target is PostgreSQL with migrations, transactional audit logging, role-scoped access, object/document storage, and scheduled backup verification. Until that migration and authentication are complete, the application is a development build and not approved for real customer data.

### Production capability tracker

| Capability | Status |
|---|---|
| Customer, policy, renewal, quotation and communication domain APIs | Foundation implemented |
| Lead conversion to customer + draft policy | Implemented |
| Policy issuance validation and audit event | Implemented |
| Consent opt-out blocking and delivery event history | Implemented |
| Proper policy, quotation and communication forms | Implemented |
| Full master-data editing screens and quote selection | In progress |
| Renewal completion into successor policy | In progress |
| Scheduler, inbox and template management | In progress |
| Authentication and role-based permissions | Not production-ready |
| PostgreSQL migrations | Not production-ready |
| Documents, backups and comprehensive audit coverage | Not production-ready |

### Lifecycle orchestration and authoritative formulas

The application server owns cross-module transitions. A renewal can only complete when it has a selected quotation and the successor policy has a policy number, start date, and expiry date. Completion atomically marks the old policy `Expired/Renewed`, creates the successor policy, links both directions, closes the renewal as `Renewed`, and writes an audit event.

- `tax_amount = round(net_premium × tax_rate / 100, 2)`
- `total_premium = round(net_premium + tax_amount, 2)`
- `days_remaining = expiry_date − current_date`
- `retention_rate = renewed / (renewed + lost + lapsed) × 100`

`GET /api/lifecycle/{lead_id}` is the integrity view spanning lead, customer, policies, renewals, quotations, tasks, and communications.

### Lead deletion policy

Lead deletion is an explicit aggregate operation. The server resolves customer, policy and renewal identifiers before mutation, then removes linked operational children (quotes, tasks, communications, consents and notifications), matching deal/contact records, and an organization only when it is no longer referenced. Notes are excluded from deletion and converted to immutable-style archived records. A final audit record stores the lead snapshot and affected-record counts.

### Daily-work orchestration

Every active lead carries an owner, next action and due date. Record editing is distinct from stage transition: editing changes business facts and synchronizes the linked contact/open work ownership; stage transition advances the pipeline and writes its timeline event. Bulk assignment propagates to open linked tasks. Bulk follow-up scheduling updates lead discipline fields and creates one task per lead. Tasks use explicit activity types (`Follow-up`, `Call`, `Meeting`, `Email`, `Document Collection`, `Quotation`, `General Task`) so the CRM can become the user's complete work queue.

### Guided onboarding

The browser client contains a first-run module guide stored as a local display preference. Guide cards route directly to the corresponding operational view and explain each module in the context of the broker lifecycle. A permanent header entry makes the guide recoverable after dismissal. This preference is presentational only and contains no customer data.

---

## 1. Vision, Mission & Strategic Goals

### 1.1 Vision
To establish the industry standard in high-velocity relationship and pipeline management for commercial insurance brokerages, agencies, and risk underwriters—ensuring no policy renewal is ever neglected, and every client touchpoint drives measurable financial retention.

### 1.2 Mission
Empower commercial insurance brokers with enterprise-grade operational software that eliminates bloated, unintuitive ERPs. InsureCRM replaces administrative clutter with high-density execution workflows, rigorous **Next Action Discipline**, and intelligent conversational querying.

### 1.3 Strategic Goals: The 3-Pillar Framework

```
                       ┌──────────────────────────────────────────────┐
                       │          InsureCRM Strategic Value           │
                       └──────────────────────┬───────────────────────┘
                                              │
         ┌────────────────────────────────────┼────────────────────────────────────┐
         │                                    │                                    │
         ▼                                    ▼                                    ▼
┌──────────────────┐                ┌──────────────────┐                ┌──────────────────┐
│  EFFECTIVENESS   │                │    EFFICIENCY    │                │     QUALITY      │
│ (Makes You Money)│                │ (Saves You Time) │                │(Client Experience│
├──────────────────┤                ├──────────────────┤                ├──────────────────┤
│• Zero Dead Leads │                │• High-Density UI │                │• Chronological   │
│  Next Action req │                │  Linear/Stripe UX│                │  Audit Ledgers   │
│• Renewal Radar   │                │• Triaged Tasks   │                │• Contextual Link │
│  ≤15d alerts     │                │  Overdue/Today   │                │  Notes & Tasks   │
│• 6 Stage Funnel  │                │• 360° Drawer     │                │• Enterprise Tone │
│  Velocity track  │                │  Zero reload     │                │  No toy emojis   │
└──────────────────┘                └──────────────────┘                └──────────────────┘
```

1. **Effectiveness (Revenue Generation & Retention)**:
   - **Mandatory Next Action Discipline**: Guarantees every active lead has a concrete next step and due date. No account becomes an unassigned, forgotten database row.
   - **Renewal Retention Radar**: Instant automated filtering of accounts expiring within &le;15 days, allowing brokers to secure renewals before competitor lock-in.
   - **Strict 6-Stage Pipeline Progression**: Direct alignment with commercial insurance sales cycles (`New` &rarr; `Contacted` &rarr; `Risk / Underwriting` &rarr; `Quotation Sent` &rarr; `Won` &rarr; `Lost`).

2. **Efficiency (Operational Speed & Reduced Clicks)**:
   - **High-Density Workspace**: Single-view table and 6-column Kanban board engineered for keyboard navigation, fast triage, and immediate visibility.
   - **Triaged Task Action Center**: Automatic categorization into `Overdue`, `Due Today`, `Upcoming`, and `Completed` with instant checkbox toggles.
   - **360° Slide-Over Detail Drawer**: Instant access to policy schedules, surveyor notes, and contact history without disrupting workspace state.
   - **AI Executive Advisor**: Query the database in natural language (e.g. *"Show overdue follow-ups in Logistics"* or *"Pipeline value by stage"*).

3. **Quality (Client Experience & Audit Integrity)**:
   - **Polymorphic Activity Ledgers**: Notes and tasks bind to parent accounts, creating a transparent chronological log of all underwriting decisions.
   - **Loss Reason Accountability**: Enforced audit reasons for any account marked as `Lost` to drive continuous sales process refinement.
   - **Enterprise Corporate Aesthetic**: Professional micro-vector stroke icons (14–16px, 1.25px stroke), tabular numerals (`₹`), and a clean monochromatic palette.

---

## 2. High-Level System Architecture

InsureCRM operates as a decoupled client-server architecture running on a single, high-performance runtime:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   CLIENT LAYER (Browser)                               │
├───────────────────────────────┬───────────────────────────────┬────────────────────────┤
│      Leads & Accounts         │       Triaged Task Center     │  AI Advisor Copilot    │
│  - Table View (High-Density)  │  - Overdue / Today / Upcoming │  - Natural Language    │
│  - Kanban View (6 Stages)     │  - Real-Time Checkbox Toggle  │    Database Queries    │
│  - Next Action Pills          │  - Direct 360° Drawer Trigger │  - Quick Insight Chips │
├───────────────────────────────┴───────────────────────────────┴────────────────────────┤
│                          Corporate Design System (Inter / Tailwind)                    │
│                  - 14px Micro-Vector SVGs  • Tabular Numerals  • 1px Borders           │
└───────────────────────────────────────────▲────────────────────────────────────────────┘
                                            │ HTTP / JSON REST APIs & WebSocket
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              APPLICATION SERVER (FastAPI :8080)                        │
├───────────────────────────────┬───────────────────────────────┬────────────────────────┤
│      Pipeline Engine          │       Discipline Engine       │   AI Intelligence      │
│  - 6 Confirmed Stages         │  - PUT /api/leads/{id}/stage  │  - /api/ai-advisor     │
│  - CRUD for Leads & Deals     │  - Auto Audit Memo Creation   │  - Pipeline Analytics  │
│  - Territory & Broker Filters │  - Auto Task Provisioning     │  - Renewal Alerts      │
├───────────────────────────────┴───────────────────────────────┴────────────────────────┤
│                            Polymorphic Relationship Services                           │
│                 - Notes Manager  • Tasks Manager  • Organizations & Contacts           │
└───────────────────────────────────────────▲────────────────────────────────────────────┘
                                            │ Atomic File System I/O
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                             PERSISTENT STORAGE (crm_db.json)                           │
│            Leads • Deals • Organizations • Contacts • Notes • Tasks • Activity         │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Modules & Component Design

### 3.1 The 6 Confirmed Insurance Stages
The core sales funnel reflects commercial brokerage operations:
```
[ 1. New ] ─────────► [ 2. Contacted ] ─────────► [ 3. Risk / Underwriting ]
  Inbound lead           Initial call /             Surveyor inspection,
  or renewal due         coverage scoping           NCB check, slip drafting
                                                            │
                                                            ▼
[ 6. Lost ] ◄──────────────────────────────────── [ 4. Quotation Sent ]
  Competitor pricing,                               Comparative quote delivered,
  underwriter decline                               terms negotiation
  (Reason Required)                                         │
                                                            ▼
                                                     [ 5. Won ]
                                                    Premium collected,
                                                    policy schedule bound
```

### 3.2 The Next Action Discipline Engine
Every lead update requires a **Next Action** and a **Due Date**:
- **Trigger**: Clicking a stage pill, dragging a Kanban card, or changing stage in the 360° drawer.
- **Payload**:
  ```json
  {
    "status": "Risk / Underwriting",
    "nextAction": "Dispatch Surveyor for On-site Inspection",
    "nextActionDate": "2026-09-08",
    "stageNote": "Client confirmed Pune warehouse inspection date with CFO.",
    "author": "Sarah Connor"
  }
  ```
- **Automated Side Effects**:
  1. Lead status, next action, and due date are updated atomically.
  2. A timestamped audit memo is added to the account's Activity Timeline.
  3. A scheduled task is created in the broker's daily task queue.

### 3.3 360° Slide-Over Account Drawer
Provides complete relationship context in a non-modal slide-over:
- **Visual Stage Progression Chevron**: Interactive tracker for the 6 stages.
- **Pinned Next Action Card**: Prominent callout showing next deliverable, due date, and quick reschedule link.
- **Commercial Policy Schedule**: Mobile, email, policy category, annual premium, renewal due date, and policy number.
- **Chronological Activity Timeline**: Consolidated ledger of surveyor reports, notes, and previous stage updates.
- **Action Triggers**: One-click shortcuts to add notes, schedule tasks, or launch follow-ups.

### 3.4 Triaged Operational Task Center
Replaces flat task lists with operational grouping:
- **Overdue Tab**: Highlighted in high-contrast red for tasks requiring immediate intervention.
- **Due Today Tab**: Highlighted in amber for the broker's immediate daily agenda.
- **Upcoming Tab**: Operational schedule for the week ahead.
- **Completed Tab**: Audit trail of completed action items.
- **Interactive Checkbox**: Toggles `Pending` &harr; `Completed` with database synchronization (`PUT /api/tasks/{id}`).
- **Click-to-Context**: Clicking any task row or account badge opens the parent account's 360° drawer.

### 3.5 AI Executive Advisor Copilot
An unobtrusive slide-over assistant providing instant answers from the database:
- Natural language queries across active accounts, renewals, and revenue.
- Quick insight chips:
  - *“Which policies are expiring in the next 15 days?”*
  - *“Show me active next actions and due dates”*
  - *“What is our current pipeline stage breakdown?”*

---

## 4. Data Models & Entity Relationships

```
┌───────────────────────────┐           ┌───────────────────────────┐
│       Organization        │           │          Contact          │
├───────────────────────────┤           ├───────────────────────────┤
│ id: "O1"                  │◄──────────┤ id: "C1"                  │
│ name: string              │ 1       N │ name: string              │
│ industry: string          │           │ email: string             │
│ annualRevenue: string     │           │ phone: string             │
│ territory: string         │           │ designation: string       │
└─────────────┬─────────────┘           └───────────────────────────┘
              │ 1
              │
              │ N
┌─────────────▼─────────────┐           ┌───────────────────────────┐
│     Lead / Account        │           │           Note            │
├───────────────────────────┤           ├───────────────────────────┤
│ id: "L1"                  │◄──────────┤ id: "N1"                  │
│ name: string              │ 1       N │ associatedId: "L1"        │
│ organization: string      │           │ associatedType: "Lead"    │
│ status: enum(6 stages)    │           │ title: string             │
│ nextAction: string        │           │ category: string          │
│ nextActionDate: ISO Date  │           │ content: string           │
│ premium: string           │           │ pinned: boolean           │
│ policyType: string        │           └───────────────────────────┘
│ expiryDate: ISO Date      │
│ daysRemaining: integer    │           ┌───────────────────────────┐
│ assignedTo: string        │           │           Task            │
└─────────────┬─────────────┘           ├───────────────────────────┤
              │ 1                       │ id: "T1"                  │
              │                       N │ associatedId: "L1"        │
              └────────────────────────►│ title: string             │
                                        │ priority: High/Med/Low    │
                                        │ dueDate: ISO Date         │
                                        │ status: Pending/Completed │
                                        └───────────────────────────┘
```

---

## 5. API Reference & Endpoint Specification

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/dashboard` | Returns executive KPIs, 6-stage distribution funnel, tasks due today, and renewals &le;15d. |
| `GET` | `/api/leads` | Lists leads. Supports `?status=`, `?assignedTo=`, `?search=`, and `?filter=expiring_soon\|due_today\|overdue`. |
| `POST` | `/api/leads` | Creates a new commercial lead; syncs organization and contact records. |
| `GET` | `/api/leads/{id}` | Returns 360° lead details including all linked activity notes and tasks. |
| `PUT` | `/api/leads/{id}/stage` | Atomically transitions lead stage, updates next action and due date, logs timeline memo, and creates a task. |
| `GET` | `/api/deals` | Returns pipeline deals with revenue figures. |
| `GET` | `/api/contacts` | Returns all client decision-makers. |
| `GET` | `/api/organizations` | Returns commercial client accounts. |
| `GET` | `/api/notes` | Returns chronological notes across all accounts. |
| `POST` | `/api/notes` | Creates a polymorphic activity note linked to an account. |
| `DELETE`| `/api/notes/{id}` | Deletes a note. |
| `GET` | `/api/tasks` | Returns action tasks. |
| `POST` | `/api/tasks` | Creates a scheduled task with priority and due date. |
| `PUT` | `/api/tasks/{id}` | Updates task status (`Completed` / `Pending`) or details. |
| `DELETE`| `/api/tasks/{id}` | Deletes a task. |
| `POST` | `/api/leads/import` | Bulk imports leads from CSV with deduplication (`skip`, `update`, `create`). |
| `POST` | `/api/ai-advisor` | Natural language database query copilot. |

---

## 6. Corporate UI & Design System Tokens

- **Palette**:
  - Sidebar Background: `#090D16` (Deep Slate)
  - Navigation Hover: `#131A29`
  - Active Tab: `#1E293B`
  - Page Canvas: `#F8FAFC`
  - Card Surfaces: `#FFFFFF`
  - Structural Borders: `#E2E8F0`
- **Typography**:
  - Font Family: `Inter`, system font stack
  - Letter Spacing: `-0.011em` for high readability
  - Category Headers: `11px`, `uppercase`, `tracking-wider`, `font-semibold`
  - Numeric Data: Tabular figures (`num-tabular`, monospace alignment for monetary premiums `₹`)
- **Iconography**:
  - Precision 14–16px micro-vector stroke SVGs (`stroke-width="1.25"` or `"1.5"`). Zero emojis.
- **Stage Badges**:
  - `New`: `bg-slate-100 text-slate-800 border-slate-200`
  - `Contacted`: `bg-blue-50 text-blue-800 border-blue-200`
  - `Risk / Underwriting`: `bg-amber-50 text-amber-800 border-amber-200`
  - `Quotation Sent`: `bg-purple-50 text-purple-800 border-purple-200`
  - `Won`: `bg-emerald-50 text-emerald-900 border-emerald-300 font-semibold`
  - `Lost`: `bg-rose-50 text-rose-800 border-rose-200`
