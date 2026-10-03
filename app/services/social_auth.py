import base64
import hashlib
import hmac
import json
import secrets
from urllib.parse import urlencode
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.core.redis import get_redis
from app.core.security import hash_password, session_claims, session_matches_user
from app.models.user import User
from app.models.oauth_identity import OAuthIdentity

PROVIDERS = {
    "google": ("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token", "openid email profile"),
    "github": ("https://github.com/login/oauth/authorize", "https://github.com/login/oauth/access_token", "read:user user:email"),
}


def credentials(provider):
    if provider not in PROVIDERS:
        raise HTTPException(404, "Unknown sign-in provider")
    prefix = "google_login" if provider == "google" else "github"
    client_id = getattr(settings, prefix + "_client_id")
    secret = getattr(settings, prefix + "_client_secret")
    if not client_id or not secret:
        raise HTTPException(503, f"{provider.title()} sign-in is not configured yet.")
    return client_id, secret


def redis_client():
    client = get_redis()
    if client is None:
        raise HTTPException(503, "Sign-in service unavailable")
    return client


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def callback_url(provider):
    return settings.oauth_public_base_url.rstrip("/") + f"/auth/oauth/{provider}/callback"


def begin(provider, user=None):
    client_id, _ = credentials(provider)
    if settings.oauth_frontend_url.rstrip("/") not in settings.frontend_origins:
        raise HTTPException(503, "Sign-in frontend is not configured as a trusted origin")
    state, binding, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    record = {"binding": digest(binding), "verifier": verifier, "provider": provider,
              "link": session_claims(user) if user else None}
    redis_client().set("oauth_state:" + digest(state), json.dumps(record), ex=600, nx=True)
    params = {"client_id": client_id, "redirect_uri": callback_url(provider), "response_type": "code",
              "scope": PROVIDERS[provider][2], "state": state, "code_challenge": challenge,
              "code_challenge_method": "S256"}
    return PROVIDERS[provider][0] + "?" + urlencode(params), binding


def consume(provider, state, binding):
    if not state or len(state) > 128 or not binding:
        raise HTTPException(400, "Invalid sign-in state")
    client = redis_client()
    key = "oauth_state:" + digest(state)
    raw = client.get(key)
    if not raw:
        raise HTTPException(400, "Sign-in expired")
    record = json.loads(raw)
    if record["provider"] != provider or not hmac.compare_digest(record["binding"], digest(binding)):
        raise HTTPException(400, "Invalid sign-in state")
    if not client.getdel(key):
        raise HTTPException(400, "Sign-in already used")
    return record


async def provider_profile(provider, code, verifier):
    client_id, secret = credentials(provider)
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(PROVIDERS[provider][1], headers={"Accept": "application/json"}, data={
            "client_id": client_id, "client_secret": secret, "code": code,
            "redirect_uri": callback_url(provider), "grant_type": "authorization_code", "code_verifier": verifier,
        })
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise HTTPException(400, "Provider rejected authorization")
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        url = "https://openidconnect.googleapis.com/v1/userinfo" if provider == "google" else "https://api.github.com/user"
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        profile = response.json()
        if provider == "google":
            email = profile.get("email") if profile.get("email_verified") is True else None
            subject = profile.get("sub")
        else:
            response = await client.get("https://api.github.com/user/emails", headers=headers)
            response.raise_for_status()
            email = next((item["email"] for item in response.json() if item.get("verified") and item.get("primary")), None)
            subject = profile.get("id")
        if not email or not subject:
            raise HTTPException(400, "A verified provider email is required")
        email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
        return str(subject), email, str(profile.get("name") or profile.get("login") or email.split("@")[0])[:200]


async def resolve_user(db, provider, subject, email, name, link=None):
    identity = (await db.execute(select(OAuthIdentity).where(
        OAuthIdentity.provider == provider, OAuthIdentity.subject == subject))).scalar_one_or_none()
    if link:
        user = (await db.execute(select(User).where(User.id == UUID(link["sub"])))).scalar_one_or_none()
        if not user or not user.email_verified or not session_matches_user(link, user):
            raise HTTPException(401, "Linking session expired")
        if identity and identity.user_id != user.id:
            raise HTTPException(409, "Provider account is already linked")
    elif identity:
        user = (await db.execute(select(User).where(User.id == identity.user_id))).scalar_one_or_none()
        if not user or not user.email_verified:
            raise HTTPException(401, "Account unavailable")
        return user
    else:
        existing = (await db.execute(select(User).where(func.lower(User.email) == email.lower()))).scalar_one_or_none()
        if existing:
            # Email equality alone must never link a provider to an existing account.
            raise HTTPException(409, "Sign in with your existing method, then link this provider in Settings.")
        user = User(full_name=name, email=email, email_verified=True, hashed_password=hash_password(secrets.token_urlsafe(32)))
        db.add(user)
        await db.flush()
    if not identity:
        db.add(OAuthIdentity(provider=provider, subject=subject, user_id=user.id))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Account already exists or provider already linked")
    return user
