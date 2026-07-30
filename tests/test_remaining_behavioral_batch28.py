from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy import create_engine, inspect

from app.database import Base


ADMIN_DSN = "postgresql://postgres:postgres@127.0.0.1:5433/postgres"
DB_PREFIX = "salessync_migration_case_"


@contextmanager
def disposable_database(case: str):
    database = f"{DB_PREFIX}{case}_{uuid4().hex[:10]}"
    assert database.startswith(DB_PREFIX)
    admin = psycopg2.connect(ADMIN_DSN)
    admin.autocommit = True
    try:
        with admin.cursor() as cursor:
            cursor.execute(f'CREATE DATABASE "{database}"')
        url = f"postgresql://postgres:postgres@127.0.0.1:5433/{database}"
        yield database, url
    finally:
        with admin.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (database,),
            )
            cursor.execute(f'DROP DATABASE IF EXISTS "{database}"')
        admin.close()


def run_alembic(url: str, *arguments: str):
    env = {
        **os.environ,
        "APP_ENV": "test",
        "DATABASE_URL": url.replace("postgresql://", "postgresql+asyncpg://"),
        "JWT_SECRET": "migration-test-only-secret",
        "DB_ENCRYPTION_KEY": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=",
        "FRONTEND_ORIGINS": '["http://127.0.0.1:5173"]',
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def create_current_schema(url: str):
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def test_core_12_pre_feature_upgrade_preserves_existing_business_data():
    with disposable_database("core12") as (_, url):
        create_current_schema(url)
        engine = create_engine(url)
        user_id, team_id, asset_id = uuid4(), uuid4(), uuid4()
        subscription_id, invoice_id = uuid4(), uuid4()
        now = datetime.now(timezone.utc)
        try:
            with engine.begin() as connection:
                # Reconstruct a pre-billing/pre-RAG/pre-OTP snapshot from the
                # application schema without using any development data.
                connection.exec_driver_sql(
                    "ALTER TABLE teams DROP COLUMN IF EXISTS stripe_customer_id"
                )
                for column in (
                    "source_url",
                    "status",
                    "embedding_id",
                    "chunk_count",
                    "indexed_at",
                    "processing_error",
                ):
                    connection.exec_driver_sql(
                        f"ALTER TABLE knowledge_assets DROP COLUMN IF EXISTS {column}"
                    )
                connection.exec_driver_sql(
                    "DROP TABLE IF EXISTS knowledge_asset_chunks"
                )
                connection.exec_driver_sql(
                    "ALTER TABLE users DROP COLUMN IF EXISTS email_verified"
                )

                connection.exec_driver_sql(
                    "INSERT INTO users "
                    "(id, full_name, email, hashed_password) VALUES (%s, %s, %s, %s)",
                    (user_id, "Preserved User", "preserved@example.invalid", "hash"),
                )
                connection.exec_driver_sql(
                    "INSERT INTO teams (id, name, invite_code) VALUES (%s, %s, %s)",
                    (team_id, "Preserved Team", "preserved-code"),
                )
                connection.exec_driver_sql(
                    "INSERT INTO knowledge_assets "
                    "(id, team_id, title, tags, file_url, file_type, file_size) "
                    "VALUES (%s, %s, %s, '[]'::jsonb, %s, %s, %s)",
                    (
                        asset_id,
                        team_id,
                        "Preserved Asset",
                        "https://example.invalid/preserved.pdf",
                        "pdf",
                        42,
                    ),
                )
                connection.exec_driver_sql(
                    "INSERT INTO subscriptions "
                    "(id, team_id, stripe_subscription_id, stripe_price_id, tier, "
                    "status, current_period_start, current_period_end, "
                    "cancel_at_period_end) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        subscription_id,
                        team_id,
                        "sub_preserved",
                        "price_preserved",
                        "growth",
                        "active",
                        now,
                        now,
                        False,
                    ),
                )
                connection.exec_driver_sql(
                    "INSERT INTO invoices "
                    "(id, team_id, stripe_invoice_id, amount_due, amount_paid, "
                    "currency, status, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        invoice_id,
                        team_id,
                        "inv_preserved",
                        1000,
                        1000,
                        "usd",
                        "paid",
                        now,
                    ),
                )
        finally:
            engine.dispose()

        upgraded = run_alembic(url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr

        engine = create_engine(url)
        try:
            inspector = inspect(engine)
            assert {"subscriptions", "invoices"}.issubset(inspector.get_table_names())
            with engine.connect() as connection:
                assert connection.exec_driver_sql(
                    "SELECT full_name FROM users WHERE id = %s", (user_id,)
                ).scalar_one() == "Preserved User"
                assert connection.exec_driver_sql(
                    "SELECT name FROM teams WHERE id = %s", (team_id,)
                ).scalar_one() == "Preserved Team"
                assert connection.exec_driver_sql(
                    "SELECT title FROM knowledge_assets WHERE id = %s", (asset_id,)
                ).scalar_one() == "Preserved Asset"
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM subscriptions WHERE id = %s",
                    (subscription_id,),
                ).scalar_one() == 1
                assert connection.exec_driver_sql(
                    "SELECT count(*) FROM invoices WHERE id = %s", (invoice_id,)
                ).scalar_one() == 1
        finally:
            engine.dispose()


def test_core_13_alembic_head_matches_runtime_orm_metadata():
    with disposable_database("core13") as (_, url):
        create_current_schema(url)
        stamped = run_alembic(url, "stamp", "head")
        assert stamped.returncode == 0, stamped.stderr

        checked = run_alembic(url, "check")
        diagnostic = f"{checked.stdout}\n{checked.stderr}"
        assert checked.returncode == 0, diagnostic
        assert "New upgrade operations detected" not in diagnostic
