"""Create or reset a VELOR administrator without embedded credentials.

The password is accepted only through an environment variable so it is not
stored in shell history or exposed in the process list. Run this script from
the repository root or from ``backend/`` after applying database migrations.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys

from database import (
    Company,
    SessionLocal,
    UsageStats,
    generate_api_key,
    get_password_hash,
    hash_api_key,
)


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
CONFIRM_VALUES = {"1", "true", "yes", "on"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or reset a VELOR administrator account safely."
    )
    parser.add_argument(
        "--email",
        default=os.getenv("VELOR_ADMIN_EMAIL", ""),
        help="Administrator email (or set VELOR_ADMIN_EMAIL).",
    )
    parser.add_argument(
        "--company-name",
        default=os.getenv("VELOR_ADMIN_COMPANY_NAME", "VELOR Admin"),
        help="Display name for a newly created account.",
    )
    parser.add_argument(
        "--role",
        choices=("admin", "super_admin"),
        default=os.getenv("VELOR_ADMIN_ROLE", "super_admin"),
        help="Role to assign. Defaults to super_admin.",
    )
    parser.add_argument(
        "--password-env",
        default="VELOR_ADMIN_PASSWORD",
        metavar="ENV_NAME",
        help="Name of the environment variable containing the password.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the account creation/reset operation.",
    )
    return parser


def _validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[str, str]:
    email = args.email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        parser.error("Provide a valid email with --email or VELOR_ADMIN_EMAIL.")

    if not ENV_NAME_PATTERN.fullmatch(args.password_env):
        parser.error("--password-env must be a valid environment variable name.")

    password = os.getenv(args.password_env, "")
    password_bytes = password.encode("utf-8")
    if len(password) < 16:
        parser.error(f"{args.password_env} must contain at least 16 characters.")
    if len(password_bytes) > 72:
        parser.error(f"{args.password_env} must be at most 72 UTF-8 bytes for bcrypt.")

    confirmed_by_env = os.getenv("VELOR_ADMIN_CONFIRM", "").strip().lower() in CONFIRM_VALUES
    if not args.yes and not confirmed_by_env:
        parser.error("Refusing to change an administrator without --yes or VELOR_ADMIN_CONFIRM=yes.")

    company_name = args.company_name.strip()
    if len(company_name) < 2 or len(company_name) > 200:
        parser.error("--company-name must contain between 2 and 200 characters.")

    return email, password


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    email, password = _validate(args, parser)

    db = SessionLocal()
    try:
        admin = db.query(Company).filter(Company.email == email).first()
        action = "updated"

        if admin is None:
            company_id = f"company_{secrets.token_hex(8)}"
            admin = Company(
                company_id=company_id,
                company_name=args.company_name.strip(),
                email=email,
                password=get_password_hash(password),
                api_key_hash=hash_api_key(generate_api_key()),
                role=args.role,
                plan="FREE",
            )
            db.add(admin)
            db.add(UsageStats(company_id=company_id))
            action = "created"
        else:
            admin.password = get_password_hash(password)
            admin.role = args.role
            admin.is_deleted = False

        db.commit()
        print(f"Administrator {action}: {email} (role={args.role}).")
        print("The password was read from the environment and was not printed.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Administrator reset failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
