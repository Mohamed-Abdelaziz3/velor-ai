import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import SessionLocal, assert_database_schema_compatible
from services.demo_catalog_service import ensure_trusted_demo_tenant


def main() -> None:
    if os.getenv("ALLOW_SYNTHETIC_DEMO_SEED", "").strip() != "1":
        raise SystemExit(
            "Refusing to seed synthetic data. Set ALLOW_SYNTHETIC_DEMO_SEED=1 "
            "only for an isolated development or verification database."
        )

    database_status = assert_database_schema_compatible(require_migration_head=True)
    db = SessionLocal()
    try:
        result = ensure_trusted_demo_tenant(db)
        result["database_target"] = database_status["database_target"]
        result["migration_revision"] = database_status["migration_revision"]
        result["migration_head"] = database_status["migration_head"]
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        print(
            "Seed status={seed_status} company={company_id} slug={public_chat_slug} "
            "owner_access={owner_access} catalog_records={record_count} products={product_count} "
            "bundles={bundle_count} database={database_target} migration={migration_revision}".format(**result)
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
