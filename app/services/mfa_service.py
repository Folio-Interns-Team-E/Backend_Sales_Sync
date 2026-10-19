"""Authenticator-app MFA with one-time login tickets and recovery codes."""

import hashlib
import hmac
import json
import secrets
import string
from uuid import UUID

import pyotp
from fastapi import HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.core.crypto import decrypt_key, encrypt_key
from app.core.redis import get_redis
from app.core.security import create_access_token, create_refresh_token, session_claims, verify_password
from app.models.security_event import SecurityAction
from app.models.user import User
from app.schemas.auth import LoginResponse, MfaRecoveryCodesResponse, MfaSetupResponse
from app.services.security_activity import record_security_event

MFA_SETUP_TTL_SECONDS = 10 * 60
MFA_LOGIN_TTL_SECONDS = 5 * 60
RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = string.ascii_uppercase + string.digits


def _redis_required():
    client = get_redis()
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MFA service is temporarily unavailable")
    return client


def _text(value) -> str | None:
    if value is None:
        return None
    return value.decode() if isinstance(value, bytes) else str(value)


def _ticket_key(ticket: str) -> str:
    digest = hashlib.sha256(ticket.encode()).hexdigest()
    return f"mfa:login:{digest}"


def _setup_key(user_id: UUID) -> str:
    return f"mfa:setup:{user_id}"


def _normalize_code(code: str) -> str:
    return "".join(character for character in code.upper() if character.isalnum())


def _recovery_digest(code: str) -> str:
    return hmac.new(
        settings.jwt_secret.encode(),
        _normalize_code(code).encode(),
        hashlib.sha256,
    ).hexdigest()


def generate_recovery_codes() -> list[str]:
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(12))
        codes.append(f"{raw[:4]}-{raw[4:8]}-{raw[8:]}")
    return codes


def issue_login_challenge(user_id: UUID) -> str:
    client = _redis_required()
    ticket = secrets.token_urlsafe(32)
    if not client.set(_ticket_key(ticket), str(user_id), ex=MFA_LOGIN_TTL_SECONDS, nx=True):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not create MFA challenge")
    return ticket


async def begin_setup(user: User) -> MfaSetupResponse:
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")
    client = _redis_required()
    secret = pyotp.random_base32()
    try:
        encrypted = encrypt_key(secret)
    except ValueError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MFA encryption is not configured") from exc
    client.set(_setup_key(user.id), encrypted, ex=MFA_SETUP_TTL_SECONDS)
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name="SaleSync")
    return MfaSetupResponse(secret=secret, otpauth_uri=uri, expires_in=MFA_SETUP_TTL_SECONDS)


def _valid_totp(encrypted_secret: str | None, code: str) -> bool:
    if not encrypted_secret:
        return False
    try:
        secret = decrypt_key(encrypted_secret)
    except Exception:
        return False
    return bool(pyotp.TOTP(secret).verify(code.strip(), valid_window=1))


def verify_user_code(user: User, code: str, *, allow_recovery: bool = True) -> bool:
    if _valid_totp(user.mfa_secret_encrypted, code):
        return True
    if not allow_recovery or not user.mfa_recovery_code_hashes:
        return False
    candidate = _recovery_digest(code)
    try:
        stored = json.loads(user.mfa_recovery_code_hashes)
    except (TypeError, ValueError):
        return False
    remaining = [digest for digest in stored if not hmac.compare_digest(digest, candidate)]
    if len(remaining) == len(stored):
        return False
    user.mfa_recovery_code_hashes = json.dumps(remaining)
    return True


async def enable_mfa(user: User, code: str, db) -> MfaRecoveryCodesResponse:
    if user.mfa_enabled:
        raise HTTPException(409, "MFA is already enabled")
    client = _redis_required()
    encrypted = _text(client.get(_setup_key(user.id)))
    if not encrypted:
        raise HTTPException(400, "MFA setup expired. Start again.")
    if not _valid_totp(encrypted, code):
        raise HTTPException(400, "Invalid authenticator code")
    codes = generate_recovery_codes()
    user.mfa_secret_encrypted = encrypted
    user.mfa_recovery_code_hashes = json.dumps([_recovery_digest(value) for value in codes])
    user.mfa_enabled = True
    record_security_event(db, user.id, SecurityAction.mfa_enabled)
    await db.commit()
    client.delete(_setup_key(user.id))
    return MfaRecoveryCodesResponse(recovery_codes=codes)


async def complete_login(ticket: str, code: str, db) -> tuple[LoginResponse, str]:
    client = _redis_required()
    user_id = _text(client.get(_ticket_key(ticket)))
    if not user_id:
        raise HTTPException(401, "MFA challenge expired. Sign in again.")
    try:
        parsed_user_id = UUID(user_id)
    except ValueError as exc:
        raise HTTPException(401, "Invalid MFA challenge") from exc
    user = (await db.execute(select(User).where(User.id == parsed_user_id))).scalar_one_or_none()
    if user is None or not user.mfa_enabled or not verify_user_code(user, code):
        raise HTTPException(401, "Invalid authenticator or recovery code")
    client.delete(_ticket_key(ticket))
    record_security_event(db, user.id, SecurityAction.mfa_login)
    await db.commit()
    claims = session_claims(user)
    return LoginResponse(
        access_token=create_access_token(claims),
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
    ), create_refresh_token(claims)


async def disable_mfa(user: User, password: str, code: str, db) -> None:
    if not verify_password(password, user.hashed_password) or not verify_user_code(user, code):
        raise HTTPException(401, "Password or MFA code is invalid")
    user.mfa_enabled = False
    user.mfa_secret_encrypted = None
    user.mfa_recovery_code_hashes = None
    user.session_version = int(user.session_version or 0) + 1
    record_security_event(db, user.id, SecurityAction.mfa_disabled)
    await db.commit()


async def regenerate_recovery_codes(user: User, code: str, db) -> MfaRecoveryCodesResponse:
    if not user.mfa_enabled or not verify_user_code(user, code, allow_recovery=False):
        raise HTTPException(401, "A current authenticator code is required")
    codes = generate_recovery_codes()
    user.mfa_recovery_code_hashes = json.dumps([_recovery_digest(value) for value in codes])
    record_security_event(db, user.id, SecurityAction.mfa_recovery_regenerated)
    await db.commit()
    return MfaRecoveryCodesResponse(recovery_codes=codes)
