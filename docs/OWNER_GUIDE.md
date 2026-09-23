# InsureCRM — Owner's Guide

For the Owner / Admin of a car and health insurance telecalling business. It covers where
you control each part of the business (the client blueprint, slide 42) and the routine
jobs only you can do. The daily calling workflow is in the
[Telecaller's Guide](TELECALLER_GUIDE.md).

## Signing in for the first time

The first person to open a new installation creates the company and becomes its Owner /
Admin. Nobody else can create that first account, and the setup screen does not appear
again once a company exists.

## The four roles

| Role | Can do |
| --- | --- |
| **Owner / Admin** | Everything, including users, settings, automation, commission, incentives, backups and data export |
| **Manager** | Work and reassign the leads of the people who report to them; see their team's performance and reports |
| **Telecaller** | Work their own leads, customers, follow-ups, calls and quotations — nothing belonging to anyone else |
| **Read-only** | Look at records and reports; change nothing |

A job title such as "Senior Telecaller" is only a label. What a person can do comes only
from their role. The company always keeps at least one active Owner / Admin: the last one
cannot be demoted or deactivated.

## Where you control each thing

| You control | Where |
| --- | --- |
| Users and employees | Settings & Data → **Users** (add, change role, deactivate). Deactivating keeps their name on past records and tells you how many open leads need a new owner. |
| Who reports to whom | Settings & Data → **Sales Hierarchy** |
| Leads | **Leads**. You can reassign any lead; a telecaller cannot. |
| Assignment rules | **Automation** → the *Share new leads between telecallers* recipe, or your own rule with the **Assign to** action. Methods: workload, round-robin, equal distribution, performance-based, priority-based. Product-based routing is a condition (*product is Car Insurance*). |
| Who is away | Your **Dashboard** → *Away — receiving no new leads*. Someone away gets no new leads until they are back. |
| Incentive rules | **Performance → Incentives** |
| Targets | **Performance → Targets** (monthly, per person; copy last month's in one step) |
| Commission rates | **Performance → Commission** (owner only). A rate is fixed on a policy when it is sold, so changing it later never rewrites past earnings. |
| Products, insurers, timezone | Settings & Data → **CRM Configuration** |
| Lead sources and integrations | **Lead Sources** (Meta and Google lead forms, website forms, WhatsApp) |
| Message templates | Settings & Data → **Message Templates** / **WhatsApp Templates** |
| Reports | **Reports** (sales funnel, lead sources, lost reasons) and **Performance** (team, leaderboard) |
| Customer and policy database | **Customers**, **Policies**, **Renewals** |
| Automations | **Automation**. Rules are off until you switch them on. *Pause everything* stops every rule at once. |
| Backups | Settings & Data → **Backups** → *Create backup*; **Restore** next to any backup. Restoring replaces all current data, and a safety copy of today's data is saved first, so a mistaken restore can be undone. |
| Data export | Settings & Data → **Backups** → *Export records* or *Export records and documents* |
| System access and history | Every change is written to the audit log, including exports. |

## Month-end routine

1. **Targets.** At the start of the month, set or copy targets under Performance → Targets.
2. **Commission.** Under Performance → Commission, mark policies whose commission has arrived
   from the insurer as *received*. *Apply today's rates* fills in policies sold while no rate
   applied.
3. **Incentives.** After the month closes, open Performance → Incentives, check each person's
   lines and press **Approve**. An approved month is frozen with the rules it used.
4. **Employee of the Month.** Performance → Leaderboard → **Announce**.
5. **Backup and export.** Create a backup, then export your data and store the file somewhere
   other than this computer. See [Operations](OPERATIONS.md#backups-restore-and-export).

## Renewals

A renewal opens by itself 60 days before a policy expires, owned by the telecaller who sold
the policy. The telecaller is reminded at 60, 30, 15 and 7 days and on the due date. If the
policy expires unrenewed, the telecaller and their manager are told. The **Renewals** screen
opens with the month's renewal rate (renewed ÷ due) and each telecaller's renewed against
pending.

## Taking your data with you

**Export records** downloads a ZIP containing:

- one spreadsheet per kind of record (leads, customers, policies, renewals, calls, quotations,
  follow-ups, notes, messages, calendar, team, targets, incentive statements, audit log);
- `crm-data.json`, the complete data in one file for moving to another system;
- `README.txt`, which explains each file.

**Export records and documents** also includes every uploaded file. Passwords are never
exported. The file holds your customers' personal information, so store it as carefully as
the CRM itself.

## When something looks wrong

- **A number on a dashboard looks off.** Every figure is defined once, in `crm_metrics.py`, and
  the dashboards, Performance and Reports all use it. A dash (—) means nothing to divide by,
  not zero.
- **Reminders stopped arriving.** Settings & Data → Backups shows when reminders and renewals
  last ran and the last error, if any. See [Operations](OPERATIONS.md#the-scheduler).
- **Someone can see too little or too much.** Check their role under Users and who they report
  to under Sales Hierarchy.
