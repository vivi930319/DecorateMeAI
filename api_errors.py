"""Shared API error and request logging helpers.

All public services use the same top-level ``error`` envelope so the web and
iOS clients do not need service-specific parsing rules.
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager

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


def rate_limited_error(code: str, message: str, retry_after_seconds: int, **extra) -> HTTPException:
    """所有 429 都用這一個形狀：`Retry-After` 標頭 ＋ 回應內的 `retryAfterSeconds`。

    兩邊都給是有原因的：標頭是 HTTP 的標準做法（代理與瀏覽器看得懂），但瀏覽器的
    `fetch` 在跨來源時預設讀不到自訂標頭，前端要顯示「請等 43 秒」只能從回應內容拿。
    先前每個服務各寫各的，Gateway 的登入限流只有標頭、沒有秒數，前端於是只能顯示
    一句沒有時間的「請稍後再試」——使用者不知道要等多久，就會一直重試。
    """
    seconds = max(1, int(retry_after_seconds))
    return HTTPException(
        status_code=429,
        headers={"Retry-After": str(seconds)},
        detail=error_payload(
            code,
            message,
            retryable=True,
            retryAfterSeconds=seconds,
            **extra,
        ),
    )


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


# ── 服務金鑰：fail closed 啟動檢查與固定時間比較（P0-7）──────────────────────
# 四個服務（Face BASIC／PRO、Suggestion、Render）本來各自複製同一段環境變數解析與
# 金鑰比較，改成共用這一組 helper，之後要調整政策只改這裡一處。


def env_flag(name: str) -> bool:
    """讀布林環境變數；接受 1／true／yes／on（不分大小寫），其餘一律視為關閉。"""
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def is_production() -> bool:
    """`APP_ENV=prod`／`production` 視為正式環境。"""
    return os.getenv("APP_ENV", "").strip().lower() in {"prod", "production"}


def insecure_local_dev_allowed() -> bool:
    """本機免驗證旗標是否生效。

    關鍵在後半段：正式環境一律無效。`ALLOW_INSECURE_LOCAL_DEV=1` 若被誤留在
    Cloud Run，服務會照樣「拒絕啟動」，而不是安靜地起來又把驗證整個關掉——
    後者正是 P0-7 要消滅的「靜默匿名開放」狀態。
    """
    return env_flag("ALLOW_INSECURE_LOCAL_DEV") and not is_production()


def secret_equals(provided: str | None, expected: str | None) -> bool:
    """固定時間比較金鑰／token，避免逐字元試探的 timing attack。

    比 bytes 不比 str：`hmac.compare_digest` 對含非 ASCII 字元的 str 會丟
    `TypeError`，而 HTTP 標頭是由 latin-1 解出來的，用戶端只要送一個非 ASCII 的
    `x-api-key` 就會讓守衛炸成 500——本來應該是乾淨的 401。
    """
    if not expected:
        return False
    return hmac.compare_digest(
        (provided or "").encode("utf-8", "surrogateescape"),
        expected.encode("utf-8", "surrogateescape"),
    )


def require_service_api_key(env_name: str) -> None:
    """缺金鑰就丟 `RuntimeError`（fail closed）。只給啟動流程呼叫，不要在 import 時呼叫。"""
    if os.getenv(env_name, "") or insecure_local_dev_allowed():
        return
    raise RuntimeError(
        f"{env_name} 未設定，服務拒絕啟動。正式環境必須設定此金鑰；"
        "本機開發要免驗證請明確設 ALLOW_INSECURE_LOCAL_DEV=1（此旗標在 APP_ENV=production 下無效）。"
    )


def enforce_service_api_key(app: FastAPI, env_name: str) -> None:
    """把「缺金鑰就拒絕啟動」掛到 app 的啟動流程上，而不是 module import 時。

    刻意不在 import 時檢查：`Face_analyzer_BASIC` 這類模組同時被離線訓練／標註
    工具當函式庫 import（`train_rf_classifiers.py`、`tools/batch_basic_classify.py`
    等十餘支），import 就炸會讓這些完全不碰網路的工具也跑不起來，測試同理。
    掛在啟動流程後，「正式環境漏設金鑰就起不來」照樣成立，import 則維持無副作用。

    用包住 `lifespan_context` 的方式接上去，這樣不管該服務原本有沒有自己的
    lifespan 都適用（Starlette 在有 lifespan 時會忽略 `on_startup`）。
    """
    previous = app.router.lifespan_context

    @asynccontextmanager
    async def _guarded(scoped_app):
        require_service_api_key(env_name)
        async with previous(scoped_app) as state:
            yield state

    app.router.lifespan_context = _guarded


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
