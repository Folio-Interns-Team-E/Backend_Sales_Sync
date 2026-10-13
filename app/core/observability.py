import contextvars
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from fastapi import Request
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import settings

request_id_context = contextvars.ContextVar("request_id", default="-")

_SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key"}


def _scrub_sentry_event(event, hint):
    """Remove credentials and personal identifiers before telemetry leaves the app."""
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: "[Filtered]" if key.lower() in _SENSITIVE_HEADERS else value
                for key, value in headers.items()
            }
        request.pop("cookies", None)
        request.pop("data", None)
        request.pop("query_string", None)
        url = request.get("url")
        if isinstance(url, str):
            parts = urlsplit(url)
            request["url"] = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    user = event.get("user")
    if isinstance(user, dict):
        event["user"] = {"id": user["id"]} if user.get("id") else {}
    return event


def configure_error_tracking() -> bool:
    """Enable Sentry when configured; local and test environments remain dependency-free."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or settings.app_env,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        before_send=_scrub_sentry_event,
        integrations=[FastApiIntegration(), SqlalchemyIntegration()],
    )
    return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_context.get(),
            "service": os.getenv("SERVICE_NAME", "sales-sync-api"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


async def request_observability(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    request_id = supplied if 0 < len(supplied) <= 100 and supplied.replace("-", "").isalnum() else str(uuid.uuid4())
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    logger = logging.getLogger("sales_sync.http")
    with sentry_sdk.isolation_scope() as scope:
        scope.set_tag("request_id", request_id)
        scope.set_tag("http.route", request.url.path)
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info("request method=%s path=%s status=%s duration_ms=%s", request.method, request.url.path, response.status_code, duration_ms)
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.exception("request_failed method=%s path=%s duration_ms=%s", request.method, request.url.path, duration_ms)
            raise
        finally:
            request_id_context.reset(token)
