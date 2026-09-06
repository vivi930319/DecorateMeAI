"""Safely merge member-domain rows from a restored source DB into the primary DB.

The script is dry-run by default.  It never copies login sessions and it never
overwrites an existing member row.  This makes a previously split database
reconcilable without restoring stale passwords, permissions, or sessions.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import MetaData, Table, create_engine, inspect, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SQLALCHEMY_DATABASE_URI


def stable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: stable(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [stable(item) for item in value]
    return value


def fingerprint(row: dict[str, Any], excluded: set[str] | None = None) -> str:
    excluded = excluded or set()
    payload = {key: stable(value) for key, value in row.items() if key not in excluded}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def key_fields(*fields: str) -> Callable[[dict[str, Any]], str]:
    return lambda row: fingerprint({field: row.get(field) for field in fields})


def points_key(row: dict[str, Any]) -> str:
    if row.get("idempotency_key"):
        return "idempotency:" + str(row["idempotency_key"])
    return fingerprint(row, {"id", "balance_after"})


def idempotency_or(*fields: str) -> Callable[[dict[str, Any]], str]:
    fallback = key_fields(*fields)

    def build(row: dict[str, Any]) -> str:
        if row.get("idempotency_key"):
            return "idempotency:" + str(row["idempotency_key"])
        return fallback(row)

    return build


TABLE_KEYS: dict[str, Callable[[dict[str, Any]], str]] = {
    "daily_checkins": key_fields("member_email", "checkin_date"),
    "favorites": key_fields("member_id", "item_id", "item_type"),
    "points_transactions": points_key,
    "saved_looks": lambda row: fingerprint(row, {"id"}),
    "task_claims": idempotency_or("member_email", "task_id", "claimed_date", "claim_date"),
    "unlocked_themes": idempotency_or("member_email", "theme_id"),
    "analysis_history": lambda row: fingerprint(row, {"id"}),
    "cart": key_fields("member_id", "item_id"),
    "cart_items": key_fields("member_email", "item_id"),
    "checkins": lambda row: fingerprint(row, {"id"}),
    "referrals": key_fields("referred_email"),
    "tryon_records": lambda row: fingerprint(row, {"id"}),
    "member_audit_logs": lambda row: fingerprint(row, {"id"}),
    "member_deletion_jobs": key_fields("request_id"),
    "member_level_history": lambda row: fingerprint(row, {"id"}),
    "admin_audit_logs": key_fields("request_id"),
    "audit_logs": lambda row: fingerprint(row, {"id"}),
}

# Authentication sessions are intentionally excluded. Old sessions must never
# become valid again merely because databases were merged.
EXCLUDED_TABLES = ["member_sessions", "otp_codes", "pending_registrations"]


def rows(connection, table: Table) -> list[dict[str, Any]]:
    return [dict(row._mapping) for row in connection.execute(select(table))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", required=True)
    parser.add_argument(
        "--source-url",
        help="Optional complete source URL when the restored source is on another server/port",
    )
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    destination_engine = create_engine(SQLALCHEMY_DATABASE_URI)
    base_url = SQLALCHEMY_DATABASE_URI.rsplit("/", 1)[0]
    source_engine = create_engine(args.source_url or (base_url + "/" + args.source_database))
    destination_meta = MetaData()
    source_meta = MetaData()
    destination_members = Table("members", destination_meta, autoload_with=destination_engine)
    source_members = Table("members", source_meta, autoload_with=source_engine)

    report: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry-run",
        "members_inserted": [],
        "member_conflicts": [],
        "tables": {},
        "excluded_tables": EXCLUDED_TABLES,
    }

    with source_engine.connect() as source, destination_engine.begin() as destination:
        destination_rows = rows(destination, destination_members)
        source_rows = rows(source, source_members)
        by_email = {row["email"].casefold(): row for row in destination_rows}
        by_phone = {row["phone_number"]: row for row in destination_rows}

        for source_row in source_rows:
            email_match = by_email.get(source_row["email"].casefold())
            phone_match = by_phone.get(source_row["phone_number"])
            if email_match or phone_match:
                if not email_match or not phone_match or email_match is not phone_match:
                    report["member_conflicts"].append(
                        {
                            "source_email": source_row["email"],
                            "source_phone": source_row["phone_number"],
                            "reason": "email_or_phone_matches_different_destination_member",
                        }
                    )
                # Existing primary member data (password, role, permissions,
                # points and verification state) remains authoritative.
                continue
            report["members_inserted"].append(source_row["email"])
            if args.apply:
                destination.execute(destination_members.insert().values(**source_row))
            by_email[source_row["email"].casefold()] = source_row
            by_phone[source_row["phone_number"]] = source_row

        if report["member_conflicts"]:
            raise RuntimeError(json.dumps(report, ensure_ascii=False, default=stable))

        source_inspector = inspect(source_engine)
        destination_inspector = inspect(destination_engine)
        for table_name, make_key in TABLE_KEYS.items():
            if not source_inspector.has_table(table_name) or not destination_inspector.has_table(table_name):
                report["tables"][table_name] = {"status": "missing", "inserted": 0}
                continue
            source_table = Table(table_name, source_meta, autoload_with=source_engine)
            destination_table = Table(table_name, destination_meta, autoload_with=destination_engine)
            destination_keys = {make_key(row) for row in rows(destination, destination_table)}
            inserted = 0
            skipped = 0
            primary_keys = set(destination_inspector.get_pk_constraint(table_name).get("constrained_columns") or [])
            for source_row in rows(source, source_table):
                identity = make_key(source_row)
                if identity in destination_keys:
                    skipped += 1
                    continue
                payload = dict(source_row)
                # Integer surrogate keys are local to each split database.
                for primary_key in primary_keys:
                    if isinstance(payload.get(primary_key), int):
                        payload.pop(primary_key)
                if args.apply:
                    destination.execute(destination_table.insert().values(**payload))
                destination_keys.add(identity)
                inserted += 1
            report["tables"][table_name] = {"status": "ok", "inserted": inserted, "skipped": skipped}

        if not args.apply:
            destination.rollback()

    print(json.dumps(report, ensure_ascii=False, indent=2, default=stable))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
