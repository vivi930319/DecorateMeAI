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


# ── Sensitive-data scrubbing for logs (messages AND exception tracebacks) ─────
# An unhandled exception is often an httpx error whose text embeds the upstream
# request URL — which can carry a token in its query string — or an auth header.
# These patterns strip those before anything is written to the log store.
_LOG_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+(?:@|%40)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.IGNORECASE)
_LOG_URL_QUERY_RE = re.compile(r"(https?://[^\s?#'\"|)>\]]+)\?[^\s#'\"|)>\]]*", re.IGNORECASE)
# Bearer/Basic credentials are scrubbed before the header rule so the header
# rule (which only grabs one token) does not consume the scheme and leave the
# token behind.
_LOG_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-=+/]+")
_LOG_AUTH_RE = re.compile(r"(?i)(authorization|cookie|x-api-key|x-serverless-authorization|x-job-token)(\s*[:=]\s*)\S+")


def redact_sensitive(text: str) -> str:
    """Scrub emails, URL query strings, and auth/cookie/bearer values from log text."""
    if not text:
        return text
    text = _LOG_URL_QUERY_RE.sub(r"\1?<redacted>", text)
    text = _LOG_SCHEME_RE.sub(r"\1 <redacted>", text)
    text = _LOG_AUTH_RE.sub(r"\1\2<redacted>", text)
    text = _LOG_EMAIL_RE.sub("<member>", text)
    return text


class RedactingFormatter(logging.Formatter):
    """Formatter that scrubs the fully rendered record — message and traceback.

    Scrubbing the final string (rather than just the message) is deliberate: the
    exception stack trace is where an httpx error quietly brings a URL query or
    an upstream error body into the log.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive(super().format(record))


def _install_redacting_logging() -> None:
    root = logging.getLogger()
    root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    formatter = RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setFormatter(formatter)


_install_redacting_logging()


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
