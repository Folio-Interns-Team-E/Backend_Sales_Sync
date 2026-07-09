from cryptography.fernet import Fernet
from app.config import settings

# Initialize Fernet using your centralized config file
try:
    cipher = Fernet(settings.db_encryption_key.encode())
except Exception as e:
    # Handles issues if the key is improperly formatted (e.g., not 32-byte base64)
    raise ValueError(f"Invalid DB_ENCRYPTION_KEY format: {e}")

def encrypt_key(plain_text: str) -> str:
    return cipher.encrypt(plain_text.encode()).decode()

def decrypt_key(encrypted_text: str) -> str:
    return cipher.decrypt(encrypted_text.encode()).decode()