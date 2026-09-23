# InsureCRM — Operations Runbook

For whoever installs and looks after the server. Everything here can be done without the
original developer.

## What runs

| Piece | What it is |
| --- | --- |
| `pipecat_server.py` | The CRM: a FastAPI web server that serves the screens (`web/`) and the API |
| Scheduler | Opens renewals, sends reminders and escalations, runs timed automations and scheduled messages. It runs inside the web server during development and as `crm_worker.py` in production. |
| Data | Local JSON files in development (`crm_tenants/<company>.json`), PostgreSQL in production |
| Documents | `crm_documents/` in development; S3-compatible storage (MinIO) in production |
| Sign-in store | `crm_identity.json` (or `IDENTITY_STORE_PATH`): companies, users and password hashes |

## Running it on one computer

Needs Python 3.11 or newer.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-crm.txt
cp .env.example .env        # then fill in SESSION_SECRET and AUDIT_SIGNING_KEY
.venv/bin/python3 -m uvicorn pipecat_server:app --host 127.0.0.1 --port 8080
```

Open http://127.0.0.1:8080. On a new installation, the first screen creates the company and
its Owner / Admin.

**Keep the folder out of iCloud Drive, Dropbox or OneDrive.** Sync services offload files the
server needs and create conflict copies such as `crm_db 2.json`, which can silently lose
records.

## Running it in production

`docker-compose.yml` runs the full stack: the web server, one scheduler worker, PostgreSQL,
MinIO for documents, ClamAV to scan uploads, and a daily database backup.

```bash
cp .env.example .env        # fill in every value; keep .env out of git
docker compose config --quiet
docker compose up -d --build
docker compose ps
```

- Put HTTPS in front of it (a reverse proxy or load balancer). Forward the original `Host`
  and scheme, because integration callback and webhook addresses are built from the request.
- Keep PostgreSQL and MinIO on the private network only.
- Health check: `GET /api/health`.
- Set `APP_ENV=production`. The server then refuses to start without `SESSION_SECRET`,
  `AUDIT_SIGNING_KEY` and `OBJECT_STORAGE_BUCKET`, and it sends HSTS headers.

## Configuration (`.env`)

`.env.example` lists every setting with a comment. The ones that matter most:

| Setting | Why |
| --- | --- |
| `SESSION_SECRET` | Signs sign-in sessions. Long and random. Changing it signs everyone out. |
| `AUDIT_SIGNING_KEY` | Seals the audit log so edits to it can be detected. Never change it after go-live. |
| `CREDENTIAL_ENCRYPTION_KEY` | Encrypts stored integration credentials (a Fernet key). |
| `OAUTH_STATE_SECRET` | Protects the Meta/Google/LinkedIn connection flow |
| `DATABASE_URL` | PostgreSQL connection. Without it, the JSON files are used. |
| `IDENTITY_STORE_PATH` | Where sign-in details are kept |
| `ENABLE_REMINDER_SCHEDULER` | `1` runs the scheduler inside the web server (single machine); `0` when `crm_worker.py` runs |
| `SCHEDULER_INTERVAL_SECONDS` | How often the worker runs (default 60) |
| `META_CLIENT_ID` / `META_CLIENT_SECRET`, `GOOGLE_…`, `LINKEDIN_…` | Only needed to connect advertising lead forms |
| `OPENROUTER_API_KEY`, `ADVISOR_MODEL` | Only for the optional reporting assistant |
| `AUTH_DISABLED` | `1` switches sign-in off. **Development only — never on a real server.** |

Generate secrets with:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## The scheduler

Every run, for every company, the scheduler:

1. opens renewals for policies within 60 days of expiry;
2. raises follow-up, renewal-ladder, high-value-lead and target-achieved alerts, each once;
3. runs timed automations;
4. sends scheduled WhatsApp and email messages (respecting opt-outs and quiet hours).

The owner can see its last run and last error under Settings & Data → Backups (from
`GET /api/admin/jobs`). A failure for one company is recorded and does not stop the others.
To run it immediately, call `POST /api/admin/jobs/run` as the Owner.

## Backups, restore and export

| What | How | Where it goes |
| --- | --- | --- |
| In-app backup | Settings & Data → Backups → *Create backup* | `crm_backups/<company>/crm-<time>.json` |
| Restore | **Restore** next to a backup. A safety copy of the current data is saved first. | — |
| Production database | The `backup` service runs `pg_dump` daily and keeps `BACKUP_RETENTION_DAYS` (default 30) | the `backup-data` volume |
| Data export | Settings & Data → Backups → *Export records* (and documents) | a ZIP the owner downloads |

**Off-site copies are your responsibility.** A backup on the same machine does not survive
that machine being lost. At least weekly, copy the latest backup, or an export with
documents, somewhere else, and keep it encrypted.

**Restoring a production database dump** (in a maintenance window, ideally into a new
database first):

```bash
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" /path/to/insurecrm-TIMESTAMP.dump
```

After any restore, sign in as the Owner and as one telecaller, open a customer's documents,
and check Settings & Data → Backups for a fresh scheduler run.

**Practise a restore** before go-live and every few months: restore last night's backup into
a spare copy and confirm the numbers match.

## Security in short

- Passwords are stored only as salted hashes and are never exported or shown.
- Sessions expire after `SESSION_TTL_SECONDS` (default 8 hours). Deactivating a user ends
  their access immediately.
- Every change, and every data export, is written to a hash-chained audit log.
- Uploads are type-checked and, in production, virus-scanned before they are stored.
- Each telecaller sees only their own records. This is enforced by the server, not just
  hidden on screen.

## Updating the software

1. Create a backup (or, in production, confirm last night's dump exists).
2. `git pull`, then `.venv/bin/pip install -r requirements-crm.txt` (or `docker compose up -d --build`).
3. Restart the server. Data changes are applied automatically when records are loaded, and
   each is written to be safe to repeat.
4. Run the checks under [Developer handover → Tests](DEVELOPER_HANDOVER.md#tests) if you
   changed code.

## Common problems

| Symptom | Likely cause |
| --- | --- |
| Server hangs at start | Files offloaded by a sync service — move the folder out of iCloud or Dropbox |
| "Server is not running" in the browser | The uvicorn process stopped; start it again |
| Everyone is signed out | `SESSION_SECRET` changed (in development without one: the identity store was moved) |
| No reminders or renewals | Scheduler stopped or failing — see its last error |
| WhatsApp messages not delivered | Provider credentials, template approval or the 24-hour window — check the message's status on the lead |
