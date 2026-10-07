from cryptography.fernet import Fernet
from app.config import settings

def _cipher() -> Fernet:
    if not settings.db_encryption_key:
        raise ValueError("DB_ENCRYPTION_KEY is required to store integration credentials")
    try:
        return Fernet(settings.db_encryption_key.encode())
    except Exception as exc:
        raise ValueError(f"Invalid DB_ENCRYPTION_KEY format: {exc}") from exc

def encrypt_key(plain_text: str) -> str:
    return _cipher().encrypt(plain_text.encode()).decode()

def decrypt_key(encrypted_text: str) -> str:
    return _cipher().decrypt(encrypted_text.encode()).decode()
