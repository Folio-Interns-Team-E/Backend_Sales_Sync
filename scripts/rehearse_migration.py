"""Rehearse Alembic upgrades against an explicitly isolated Neon branch."""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from dotenv import dotenv_values
from sqlalchemy import create_engine, text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
production = dotenv_values(ROOT / "backend" / ".env")
test = dotenv_values(ROOT / "backend" / ".env.migration-test")
production_url = production.get("DATABASE_URL")
test_url = test.get("DATABASE_URL")
if not production_url or not test_url:
    raise SystemExit("Both local backend/.env and backend/.env.migration-test need DATABASE_URL")

production_host = urlparse(production_url).hostname
test_host = urlparse(test_url).hostname
if not production_host or not test_host or production_host == test_host or not test_host.endswith(".neon.tech"):
    raise SystemExit("Refusing migration: test endpoint is missing, non-Neon, or matches the local production endpoint")

encryption_key = test.get("DB_ENCRYPTION_KEY") or production.get("DB_ENCRYPTION_KEY")
if not encryption_key:
    raise SystemExit("DB_ENCRYPTION_KEY is required to migrate Gmail credentials")

sync_url = test_url.replace("postgresql+asyncpg://", "postgresql://", 1)
engine = create_engine(sync_url)
with engine.connect() as connection:
    version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    oauth_exists = connection.execute(text("SELECT to_regclass('public.oauth_identities') IS NOT NULL")).scalar_one()
    encrypted_exists = connection.execute(text("""
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'google_credentials'
            AND column_name = 'encrypted_refresh_token'
        )
    """)).scalar_one()
engine.dispose()
target_revision = "20261011_invite_code_expiry"
if version not in {"6f2efeef68f7", "20261011_workspace_api_keys", "20261011_logout_all_sessions", target_revision} or not oauth_exists:
    raise SystemExit("Test branch does not match the expected pre-migration schema; no changes made")
if version == "6f2efeef68f7" and encrypted_exists:
    raise SystemExit("Unexpected encrypted Gmail column before migration; no changes made")

print(f"Verified isolated Neon host: {test_host}")
print(f"Starting revision: {version}")
os.environ["DATABASE_URL"] = test_url
os.environ["DB_ENCRYPTION_KEY"] = encryption_key
config = Config(str(ROOT / "alembic.ini"))
if version != target_revision:
    command.upgrade(config, "head")

engine = create_engine(sync_url)
with engine.connect() as connection:
    version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    encrypted_exists = connection.execute(text("""
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'google_credentials'
            AND column_name = 'encrypted_refresh_token'
        )
    """)).scalar_one()
    old_column = connection.execute(text("""
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'google_credentials'
            AND column_name = 'refresh_token'
        )
    """)).scalar_one()
    gmail_tokens = connection.execute(text("SELECT encrypted_refresh_token FROM google_credentials")).scalars().all()
engine.dispose()
from app.core.crypto import decrypt_key
for token in gmail_tokens:
    if not decrypt_key(token):
        raise SystemExit("An encrypted Gmail token did not decrypt")
if version != target_revision or not encrypted_exists or old_column:
    raise SystemExit("The rehearsal did not reach the expected final schema")
print(f"Final revision: {version}")
print(f"Encrypted Gmail column present: {encrypted_exists}")
print(f"Gmail tokens successfully decrypted: {len(gmail_tokens)}")
