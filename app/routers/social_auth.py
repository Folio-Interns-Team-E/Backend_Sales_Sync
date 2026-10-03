from typing import Literal
import logging

from fastapi import APIRouter, Depends, Request, Response, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.middleware.csrf import require_auth_request
from app.middleware.auth_middleware import get_current_user
from app.core.security import create_refresh_token, session_claims
from app.routers.auth import _set_refresh_cookie
from app.services import social_auth as service

router = APIRouter(prefix="/auth/oauth", tags=["social sign-in"])
Provider = Literal["google", "github"]
logger = logging.getLogger(__name__)


def start_response(provider, response, user=None):
    url, binding = service.begin(provider, user)
    response.set_cookie("oauth_binding_" + provider, binding, max_age=600, httponly=True,
                        secure=settings.app_env.lower() != "development", samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"data": {"url": url}}


@router.post("/{provider}/start", dependencies=[Depends(require_auth_request)])
async def start(provider: Provider, response: Response):
    return start_response(provider, response)


@router.post("/{provider}/link", dependencies=[Depends(require_auth_request)])
async def link(provider: Provider, response: Response, user=Depends(get_current_user)):
    return start_response(provider, response, user)


@router.get("/{provider}/callback")
async def callback(provider: Provider, request: Request, state: str = "", code: str = "", error: str = "",
                   db: AsyncSession = Depends(get_db)):
    target = settings.oauth_frontend_url.rstrip("/")
    try:
        record = service.consume(provider, state, request.cookies.get("oauth_binding_" + provider))
        if error or not code:
            raise HTTPException(400, "Sign-in cancelled")
        subject, email, name = await service.provider_profile(provider, code, record["verifier"])
        user = await service.resolve_user(db, provider, subject, email, name, record["link"])
        response = RedirectResponse(target + ("/settings" if record["link"] else "/dashboard"), status_code=303)
        _set_refresh_cookie(response, create_refresh_token(session_claims(user)))
    except HTTPException as exc:
        reason = "account_exists" if exc.status_code == 409 else "failed"
        response = RedirectResponse(target + "/login?social_error=" + reason, status_code=303)
    except Exception:
        # Do not log provider response bodies, codes, state, or tokens.
        logger.warning("Social sign-in failed for provider %s", provider)
        response = RedirectResponse(target + "/login?social_error=failed", status_code=303)
    response.delete_cookie("oauth_binding_" + provider, path="/")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response
