"""Shared API error and request logging helpers.

All public services use the same top-level ``error`` envelope so the web and
iOS clients do not need service-specific parsing rules.
"""

from __future__ import annotations

import logging
import os
import re
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def error_payload(code: str, message: str, *, retryable: bool = False, **extra) -> dict:
    payload = {
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    payload.update(extra)
    return {"error": payload}


# A path segment that carries an email — plain (`user@example.com`) or the
# URL-encoded form (`user%40example.com`) the browser sends. Member routes put
# the account's email straight in the path (`/api/members/<email>/…`), so the
# access log would otherwise persist that email to the platform's log store.
_EMAIL_SEGMENT_RE = re.compile(r"[^/]*(?:@|%40)[^/]*", re.IGNORECASE)


def redact_log_path(path: str) -> str:
    """Return the request path with any email-bearing segment masked.

    The route shape is preserved (so logs stay useful for debugging) while the
    account identifier is replaced with an opaque placeholder. This keeps the
    access log free of the emails that appear in member and saved-look paths —
    logs must never be a second copy of the membership list.
    """
    return _EMAIL_SEGMENT_RE.sub("<member>", path or "")


def _request_id(request: Request) -> str:
    current = getattr(request.state, "request_id", None)
    if current:
        return current
    supplied = request.headers.get("x-request-id", "").strip()
    current = supplied[:96] if supplied else uuid.uuid4().hex
    request.state.request_id = current
    return current


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict) and isinstance(detail.get("error"), dict):
        content = detail
    else:
        content = error_payload(
            "HTTP_ERROR",
            str(detail) if detail else "Request failed.",
            retryable=exc.status_code >= 500,
        )
    headers = dict(exc.headers or {})
    headers["X-Request-ID"] = _request_id(request)
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
        headers=headers,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = []
    for item in exc.errors():
        location = ".".join(str(part) for part in item.get("loc", []))
        fields.append({"field": location, "message": item.get("msg", "Invalid value.")})
    return JSONResponse(
        status_code=422,
        content=error_payload(
            "VALIDATION_ERROR",
            "Request validation failed.",
            retryable=False,
            fields=fields,
        ),
        headers={"X-Request-ID": _request_id(request)},
    )


def install_api_error_handling(app: FastAPI, service_name: str) -> None:
    """Install a consistent error envelope and lightweight request logging."""

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    logger = logging.getLogger(service_name)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.exception("unhandled_exception request_id=%s", request_id)
        return JSONResponse(
            status_code=500,
            content=error_payload(
                "INTERNAL_ERROR",
                "服務暫時無法處理請求，請稍後再試。",
                retryable=True,
            ),
            headers={"X-Request-ID": request_id},
        )

    @app.middleware("http")
    async def _request_logging(request: Request, call_next):
        request_id = _request_id(request)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed",
                extra={"request_id": request_id},
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_completed method=%s path=%s status=%s duration_ms=%.1f",
            request.method, redact_log_path(request.url.path), response.status_code, elapsed_ms,
            extra={"request_id": request_id},
        )
        return response
