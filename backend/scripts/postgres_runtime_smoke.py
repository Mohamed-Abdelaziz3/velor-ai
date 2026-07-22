"""PostgreSQL migration/runtime smoke used by CI.

The check creates two transaction-scoped tenants and leads, proves the
canonical pagination helper cannot cross tenant boundaries, then rolls the
entire transaction back. It refuses to run against non-PostgreSQL databases.
"""

import os
import secrets
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from database import Base, Company, Lead, get_leads_paginated, get_password_hash, hash_api_key
from schema_verification import schema_status


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    engine = create_engine(database_url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        raise SystemExit("This smoke test must run against PostgreSQL")

    backend_dir = Path(__file__).resolve().parents[1]
    status = schema_status(engine, Base.metadata, backend_dir, require_migration_head=True)
    if not status.get("schema_compatible"):
        raise SystemExit(f"Schema is not compatible: {status}")

    suffix = uuid.uuid4().hex[:12]
    tenant_a = f"pg_smoke_a_{suffix}"
    tenant_b = f"pg_smoke_b_{suffix}"
    password_hash = get_password_hash(secrets.token_urlsafe(32))

    with Session(engine) as db:
        transaction = db.begin()
        try:
            db.add_all(
                [
                    Company(
                        company_id=tenant_a,
                        company_name="PostgreSQL Smoke A",
                        email=f"{tenant_a}@example.invalid",
                        password=password_hash,
                        api_key_hash=hash_api_key(secrets.token_urlsafe(48)),
                        plan="FREE",
                    ),
                    Company(
                        company_id=tenant_b,
                        company_name="PostgreSQL Smoke B",
                        email=f"{tenant_b}@example.invalid",
                        password=password_hash,
                        api_key_hash=hash_api_key(secrets.token_urlsafe(48)),
                        plan="FREE",
                    ),
                ]
            )
            db.flush()
            db.add_all(
                [
                    Lead(company_id=tenant_a, name="Tenant A lead", phone=f"01{suffix[:9]}", is_test=False),
                    Lead(company_id=tenant_b, name="Tenant B lead", phone=f"02{suffix[:9]}", is_test=False),
                ]
            )
            db.flush()

            result_a = get_leads_paginated(db, tenant_a, page=1, page_size=20)
            result_b = get_leads_paginated(db, tenant_b, page=1, page_size=20)
            assert result_a["total"] == 1
            assert result_b["total"] == 1
            assert {row.company_id for row in result_a["items"]} == {tenant_a}
            assert {row.company_id for row in result_b["items"]} == {tenant_b}
        finally:
            transaction.rollback()

    print(f"PostgreSQL runtime smoke passed at migration {status['migration_revision']}")


if __name__ == "__main__":
    main()
