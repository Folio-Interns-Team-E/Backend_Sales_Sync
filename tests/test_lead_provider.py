from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.services.lead_provider_service import provider_key, reset_usage_if_needed


def test_provider_key_is_decrypted_only_when_needed():
    key = Fernet.generate_key().decode()
    cipher = Fernet(key.encode())
    encrypted = cipher.encrypt(b"apollo-secret").decode()
    record = SimpleNamespace(encrypted_api_key=encrypted)

    with patch("app.core.crypto.settings.db_encryption_key", key):
        assert provider_key(record) == "apollo-secret"
    assert record.encrypted_api_key != "apollo-secret"


def test_provider_usage_resets_in_a_new_month():
    record = SimpleNamespace(usage_month=date(2020, 1, 1), used_this_month=42)
    reset_usage_if_needed(record)
    assert record.usage_month == date.today().replace(day=1)
    assert record.used_this_month == 0
