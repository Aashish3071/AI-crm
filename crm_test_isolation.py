"""Keep every test run away from live CRM data.

Import this before ``pipecat_server`` or ``crm_security`` in any test module. The
application reads its storage paths once, at import time, so they must be redirected
first. Paths are forced rather than defaulted: a developer's shell or ``.env`` may
point at the live store, and a test must never inherit that.

An end-to-end run once replaced the live identity store with test fixtures, which
removed every real sign-in. This module exists so that cannot recur.
"""
import atexit
import os
import shutil
import tempfile

TEST_ROOT = tempfile.mkdtemp(prefix="insurecrm-test-")

_PATHS = {
    "IDENTITY_STORE_PATH": "identity.json",
    "CRM_DB_FILE": "crm_db.json",
    "TENANT_ROOT": "tenants",
    "BACKUP_ROOT": "backups",
    "DOCUMENT_ROOT": "documents",
}

for _key, _name in _PATHS.items():
    os.environ[_key] = os.path.join(TEST_ROOT, _name)

os.environ.setdefault("ENABLE_REMINDER_SCHEDULER", "0")
atexit.register(shutil.rmtree, TEST_ROOT, True)
