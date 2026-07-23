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


# ── Log 敏感資料遮罩（訊息「與」例外堆疊都要洗）────────────────────────────
# 未處理的例外通常是 httpx 錯誤，它的文字裡會夾帶上游請求的網址——而網址的
# query string 可能帶著 token——或是認證標頭。這些內容會透過 traceback 進到 log
# 儲存區，所以在寫入前一律用下面幾個樣式把它們遮掉。
_LOG_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+(?:@|%40)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.IGNORECASE)
_LOG_URL_QUERY_RE = re.compile(r"(https?://[^\s?#'\"|)>\]]+)\?[^\s#'\"|)>\]]*", re.IGNORECASE)
# Bearer／Basic 憑證要「先」洗，比標頭規則早一步。標頭規則只會抓一個 token，
# 若先跑標頭規則會把 scheme（Bearer）吃掉、反而把後面的 token 留在畫面上。
_LOG_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._\-=+/]+")
_LOG_AUTH_RE = re.compile(r"(?i)(authorization|cookie|x-api-key|x-serverless-authorization|x-job-token)(\s*[:=]\s*)\S+")


def redact_sensitive(text: str) -> str:
    """把 log 文字中的 email、網址 query string、認證／Cookie／Bearer 值遮掉。"""
    if not text:
        return text
    text = _LOG_URL_QUERY_RE.sub(r"\1?<redacted>", text)   # 網址 ?後面全部遮掉
    text = _LOG_SCHEME_RE.sub(r"\1 <redacted>", text)      # Bearer/Basic 的 token
    text = _LOG_AUTH_RE.sub(r"\1\2<redacted>", text)       # Authorization/Cookie/API key 等的值
    text = _LOG_EMAIL_RE.sub("<member>", text)             # email 一律換成 <member>
    return text


class RedactingFormatter(logging.Formatter):
    """會把「整筆 log 成品」——訊息＋例外堆疊——都洗過一遍的 formatter。

    刻意洗「最終字串」而不是只洗訊息：例外的 stack trace 正是 httpx 錯誤把網址
    query 或上游錯誤內容偷偷帶進 log 的地方，只洗訊息會漏掉那一段。
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive(super().format(record))


def _install_redacting_logging() -> None:
    # 把遮罩 formatter 掛到 root logger：所有服務（Gateway／Face／Render／Ollama）
    # 共用同一個 root，掛一次就全部涵蓋，不必逐一改每個 logging.exception 呼叫點。
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


# 帶 email 的路徑段——純文字（`user@example.com`）或瀏覽器送出的 URL 編碼形式
# （`user%40example.com`）。會員路由會把帳號 email 直接放進路徑
# （`/api/members/<email>/…`），不遮的話 access log 就會把 email 永久留在平台
# 的 log 儲存區。
_EMAIL_SEGMENT_RE = re.compile(r"[^/]*(?:@|%40)[^/]*", re.IGNORECASE)


def redact_log_path(path: str) -> str:
    """回傳把「帶 email 的路徑段」遮成 <member> 之後的請求路徑。

    路徑結構保留（debug 時仍看得出打的是哪條路由），只把帳號識別碼換成不透明的
    佔位字。這樣 access log 就不會殘留會員／收藏路徑裡的 email——log 絕不能變成
    第二份會員名冊。
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
