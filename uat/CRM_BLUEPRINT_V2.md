# Commercial Insurance CRM Blueprint v2

Baseline date: 5 September 2026. Supersedes the target set in [v1](CRM_BLUEPRINT.md) without lowering any standard in it.

v1 described the target and was written before most of the product existed. v2 keeps every v1 acceptance criterion and adds what a year of building has shown the v1 text did not say clearly enough: which failures block a paying client, which are cosmetic, and what "done" means for the half-built modules a broker can already click into.

Measured position on this date: **43 of 89 acceptance tests pass, 42 fail, 4 skip.** That is the honest starting line for v2. Nothing below assumes a fix that has not been demonstrated.

## What changed since v1

Three things v1 got wrong or left unsaid, corrected here:

1. **v1 treated assigned-only visibility as optional** ("a separate configurable company policy"). Client instruction is explicit: an administrator sees the whole book, an assigned user sees only their own. v2 makes record-level visibility a **release requirement**, not a setting a deployment might leave off.
2. **v1 had no standard for a half-built module.** A broker can open Quotation Comparison and Policy Service Requests today and reach a dead end. v2 adds M29: a module reachable from navigation must either work end to end or say plainly what is missing.
3. **v1 counted dashboard correctness as one criterion.** Three separate arithmetic defects hid behind it. v2 splits the dashboard's numeric contract from its layout contract.

## Release gates

A release requires all four. They are ordered by what stops a broker working.

| Gate | Contains | Status |
| --- | --- | --- |
| **G1 — Trust** | Identity, visibility, audit truthfulness | Visibility done; profile identity and note authorship still fail |
| **G2 — Daily work** | Dashboard, tasks, calendar, notifications | Dashboard numeric contract done; escalation and search fail |
| **G3 — Placing business** | Conversion, policies, quotations, renewals | 16 failing criteria — the largest gate |
| **G4 — Servicing & retention** | Service requests, endorsements, communications, documents | 7 failing criteria |

## Priority order for v2

This is the order to build in, derived from the failure grouping rather than module numbering.

### P1 — Identity truthfulness (4 failures, G1)

The profile endpoint edits whoever a shared company setting points at, not the signed-in user, and note authorship accepts a caller-supplied name. Both let one user act as another inside an audited system, which undermines every audit record the CRM produces.

- **V2.1**: `/api/profile` reads and writes only the session's own identity. Selecting another user is an administrative action against `/api/users/{id}`, never a profile edit.
- **V2.2**: note, task and communication authorship derives from the session. A caller-supplied author field is ignored, not trusted.
- **V2.3**: a broker cannot reach an administrative path through a legacy alias.

### P2 — Placing business correctly (16 failures, G3)

The largest gate and the one a brokerage is actually paid for. Quotation comparison and issuance evidence are the visible holes.

- **V2.4**: policy amounts reject negatives and reversed terms; premium and tax use decimal arithmetic end to end.
- **V2.5**: issuance requires linked document evidence, not four booleans a user can tick without uploading anything. No other endpoint may set a policy Active.
- **V2.6**: a quotation cannot be selected if it belongs to another renewal or has expired; new-business quotes attach to an open deal with no policy in existence.
- **V2.7**: **quotation comparison is a screen, not an endpoint.** A broker can enter competing insurer offers against one renewal or deal and see cover, excess, exclusions, validity and premium side by side, then record a selection with the actor and version.
- **V2.8**: renewal generation excludes drafts and cancelled policies; completing the same renewal twice yields one successor.

### P3 — Servicing that a user can start (7 failures, G4)

Today "New request" answers *Create or repair a customer-linked policy first*, which states a precondition without offering a route to satisfy it.

- **V2.9**: a service request cannot be raised against a policy belonging to another customer, and the refusal names the customer and offers the conversion route that would create a valid policy.
- **V2.10**: completing a service request requires an outcome; endorsement completion synchronises the servicing record, 360°, calendar and alerts.
- **V2.11**: deleting a lead removes or archives its dependent service graph without orphaning records.

### P4 — Work reaching the right person (6 failures, G2)

- **V2.12**: overdue work escalates to the configured manager after the configured delay, once, across worker restarts.
- **V2.13**: global search finds tasks and service work, not only leads and customers.
- **V2.14**: reports filter by their stated period; conversion metrics use all eligible leads.

### P5 — Communication integrity (4 failures, G4)

- **V2.15**: consent survives lead-to-customer conversion.
- **V2.16**: a retried send does not dispatch twice; out-of-order provider callbacks never regress a delivery state backwards.

## New module standards

### M29 — Honest module boundaries

Every module reachable from primary navigation must be in one of three states, and must say which:

- **M29.1**: **working** — the documented flow completes end to end.
- **M29.2**: **partial** — the screen states what is available and what is not, with the next step a user can take. A blocking precondition must name the record that would satisfy it and link to where it is created.
- **M29.3**: **not started** — the screen says so plainly rather than presenting empty controls that appear functional.

An empty panel with a working-looking button is a defect under M29 even when the underlying endpoint is healthy.

### M30 — Record-level visibility (promoted from optional)

- **M30.1**: administrators and auditors read the whole company book; a manager reads their own plus their reporting line; every other role reads only records assigned to them.
- **M30.2**: the boundary applies to lists, aggregates and direct record requests alike. Requesting an out-of-scope record by ID returns 404, never a redacted body that confirms existence.
- **M30.3**: reassigning work moves visibility with it, and a deactivated user's access ends immediately.

### M31 — Dashboard numeric contract (split from M01.3)

- **M31.1**: every dated KPI uses the period in its own label.
- **M31.2**: monetary aggregates use decimal parsing and exclude closed business from open-pipeline value.
- **M31.3**: completion counts derive from recorded completion time, not from the due date.
- **M31.4**: panel arrangement is per user and never alters another user's view or any underlying record.

## Deferred, with reasons

Not weakened, but explicitly out of the next release so the plan is honest:

- **AI voice calling** — carried over from v1 as deferred. The conversational prototype was removed on 5 September 2026; this is a from-scratch build requiring telephony, streaming speech and call-state handling.
- **Real provider certification** (M03.3, M20.3) — needs authorised Meta/Google/LinkedIn sandboxes and app review. The ingestion and sending paths are built and tested against provider payload shapes and a stand-in Graph API; that is not the same as certified delivery.
- **Accessibility and load acceptance** (M28) — requires human assessment and a load environment.
- **PostgreSQL and object-storage recovery proof** — adapters exist; combined database and document recovery is unproven.

## How to assess against v2

```bash
PYTHONWARNINGS=ignore .venv/bin/python3 -m pytest tests/test_blueprint_acceptance.py -q
PYTHONWARNINGS=ignore .venv/bin/python3 -m tests.run_blueprint_audit --browser
```

Rules carried forward from v1, unchanged: PARTIAL is not a release pass; a passing scenario demonstrates only its own assertions; product edits after a run invalidate that run. Record results in `CRM_BLUEPRINT_ASSESSMENT.md` against the source hashes tested, and never edit a test to make a failing product look passing.
