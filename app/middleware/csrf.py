"""Protect auth mutations from cross-site requests, including login CSRF."""
from fastapi import HTTPException, Request

from app.config import settings


def require_auth_request(request: Request) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    # A custom header forces browser cross-origin requests through CORS preflight.
    # Native clients can send this header without an Origin.
    if request.headers.get("X-SalesSync-Request") != "1":
        raise HTTPException(403, "Missing authentication request header")
    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.frontend_origins:
        raise HTTPException(403, "Untrusted request origin")
