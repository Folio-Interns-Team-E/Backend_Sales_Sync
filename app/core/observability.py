import contextvars
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import Request

request_id_context = contextvars.ContextVar("request_id", default="-")


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
