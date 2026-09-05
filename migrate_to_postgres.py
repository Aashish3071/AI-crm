"""One-time, idempotence-aware migration from a tenant JSON export to PostgreSQL."""
import argparse
import json
import os
import shutil
from datetime import datetime, timezone

import crm_store
from crm_security import company_context
from pipecat_server import _empty_company_db, _ensure_db_shape, relational_integrity, repair_relational_model


def main():
    parser = argparse.ArgumentParser(description="Migrate one InsureCRM company to PostgreSQL")
    parser.add_argument("--source", required=True, help="Source crm_db.json or tenant export")
    parser.add_argument("--company-id", required=True, help="Company ID created during secure setup")
    parser.add_argument("--replace", action="store_true", help="Replace a non-empty target company")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("DATABASE_URL is required")
    source = os.path.abspath(args.source)
    with open(source, "r", encoding="utf-8") as handle:
        state = _ensure_db_shape(json.load(handle))
    token = company_context.set(args.company_id)
    try:
        result = repair_relational_model(state)
        hard_errors = {key:value for key,value in relational_integrity(state).items()
                       if key not in {"prospectContactsAwaitingConversion"} and value}
        if hard_errors:
            raise SystemExit(f"Migration stopped because relationships remain invalid: {hard_errors}")
        target = crm_store.load_state(args.company_id, _empty_company_db())
        target_count = sum(len(value) for key,value in target.items() if isinstance(value, list) and key != "auditLogs")
        if target_count and not args.replace:
            raise SystemExit("Target company is not empty; use --replace only after taking a PostgreSQL backup")
        if args.dry_run:
            print(json.dumps({"dryRun":True, "source":source, "companyId":args.company_id,
                              "records":sum(len(v) for v in state.values() if isinstance(v,list)), **result}, indent=2))
            return
        backup_root = os.environ.get("BACKUP_ROOT", "crm_backups")
        os.makedirs(backup_root, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(source, os.path.join(backup_root, f"migration-source-{stamp}.json"))
        state["_revision"] = target.get("_revision")
        crm_store.save_state(args.company_id, state)
        verified = crm_store.load_state(args.company_id, _empty_company_db())
        print(json.dumps({"migrated":True, "companyId":args.company_id,
                          "records":sum(len(v) for v in verified.values() if isinstance(v,list)),
                          "integrity":relational_integrity(verified)}, indent=2))
    finally:
        company_context.reset(token)


if __name__ == "__main__":
    main()
