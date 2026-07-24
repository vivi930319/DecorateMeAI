import asyncio
import base64
import hashlib
import ipaddress
import json
import os
import re
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from http.cookies import SimpleCookie
from urllib.parse import quote, unquote, urlsplit

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from api_errors import install_api_error_handling, secret_equals
from fastapi.responses import JSONResponse, RedirectResponse, Response
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from dev_server_utils import get_cors_origins
import job_store


@dataclass(frozen=True)
class Upstream:
    base_url: str
    api_key: str
    client_api_key: str
    allowed_paths: tuple[re.Pattern[str], ...]
    requires_upstream_api_key: bool = True
    requires_cloud_run_iam: bool = True
    required_in_production: bool = True


FACE_JOB_ID = r"JOB-[0-9a-f]{12}"
RENDER_JOB_ID = r"[0-9a-f]{32}"


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"^{value}$") for value in values)


def _service_url(env_name: str) -> str:
    return os.getenv(env_name, "").strip().rstrip("/")


ALLOW_EXTERNAL_TEXT_UPSTREAM = os.getenv("GATEWAY_ALLOW_EXTERNAL_TEXT_UPSTREAM", "").strip().lower() in {"1", "true", "yes", "on"}


UPSTREAMS = {
    "face-basic": Upstream(
        base_url=_service_url("FACE_BASIC_URL"),
        api_key=os.getenv("UPSTREAM_FACE_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_FACE_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"v1/face/pose",
            r"v1/face/analyze/basic",
            r"v1/face/jobs/basic",
            rf"v1/face/jobs/{FACE_JOB_ID}",
            rf"v1/face/jobs/{FACE_JOB_ID}/result",
        ),
    ),
    "face-pro": Upstream(
        base_url=_service_url("FACE_PRO_URL"),
        api_key=os.getenv("UPSTREAM_FACE_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_FACE_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"v1/face/analyze/pro",
            r"v1/face/jobs/pro",
            rf"v1/face/jobs/{FACE_JOB_ID}",
            rf"v1/face/jobs/{FACE_JOB_ID}/result",
        ),
    ),
    "render-service": Upstream(
        base_url=_service_url("RENDER_URL"),
        api_key=os.getenv("UPSTREAM_RENDER_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_RENDER_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"render",
            r"render/jobs",
            rf"render/jobs/{RENDER_JOB_ID}",
            # Ownership-sensitive render routes (signed-url, content, retain,
            # artifact, media/*, users/*) are deliberately absent.  The Gateway
            # reaches them through _render_internal_request(), which builds the
            # upstream URL directly and never consults this allowlist, so the
            # browser has no reason — and no way — to call them.
        ),
    ),
    "text-suggestion": Upstream(
        base_url=_service_url("TEXT_SUGGESTION_URL"),
        api_key=os.getenv("UPSTREAM_TEXT_SUGGESTION_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_TEXT_SUGGESTION_API_KEY", ""),
        allowed_paths=_patterns(
            r"health",
            r"suggest",
        ),
        requires_upstream_api_key=False,
        requires_cloud_run_iam=False,
        required_in_production=ALLOW_EXTERNAL_TEXT_UPSTREAM,
    ),
    # Member API calls use the signed session as the access control.  The
    # database URL and any upstream credential stay inside Cloud Run.
    "member-database": Upstream(
        base_url=_service_url("MEMBER_DATABASE_URL"),
        api_key=os.getenv("UPSTREAM_MEMBER_API_KEY", ""),
        client_api_key=os.getenv("GATEWAY_MEMBER_API_KEY", ""),
        allowed_paths=_patterns(
            r"api/recommend/personal",
            r"api/favorites/toggle",
            r"api/members",
            r"api/members/[^/]+",
            r"api/members/[^/]+/points",
            # 收藏的「寫」走 api/favorites/toggle，「讀」走這條。少了它，前端把收藏
            # 同步回本機的那段永遠拿到 Gateway 的 404——寫得進去、讀不回來，
            # 換裝置就看不到自己收藏過的東西，而且畫面完全正常不會報錯。
            r"api/members/[^/]+/favorites",
            # 購物車跟收藏同一個模式：跨裝置同步靠會員 session。GET 讀回、POST 整台覆蓋。
            # 授權沿用 _authorize_member_path（MEMBER_SCOPE_RE）——只准存取自己 email
            # 底下的車，別人的擋 403。少了這條，前端寫得進 localStorage 卻同步不到伺服器，
            # 換裝置就看不到自己的購物車，而且畫面完全正常不會報錯（跟收藏當初一模一樣的坑）。
            r"api/members/[^/]+/cart",
            r"api/members/[^/]+/check-in",
            r"api/members/[^/]+/tasks",
            r"api/members/[^/]+/tasks/[^/]+/claim",
            r"api/members/[^/]+/theme-shop/[^/]+/redeem",
            r"api/members/[^/]+/saved-looks",
            r"api/members/[^/]+/saved-looks/[^/]+",
        ),
        requires_upstream_api_key=False,
        requires_cloud_run_iam=False,
    ),
}

MAX_BODY_BYTES = max(1024, int(os.getenv("AI_GATEWAY_MAX_BODY_BYTES", str(13 * 1024 * 1024))))
UPSTREAM_TIMEOUT_SECONDS = max(10, int(os.getenv("AI_GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "600")))


def _timeout_env(name: str, default: int) -> int:
    # A read never has any business holding the 600-second connect budget the
    # client is built with: a slow member database or a Quick Tunnel that stops
    # answering would otherwise pin a worker for ten minutes and starve everyone
    # else.  Each upstream gets its own bound, capped so a stray env value can
    # never re-open that window.
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(5, min(value, UPSTREAM_TIMEOUT_SECONDS))


# Per-service read timeouts.  Face and render are job-based (a quick submit,
# then polling), so they do not need the long default either.  The external
# text suggestion upstream is reached over a Quick Tunnel and must never hold a
# ten-minute connection.
UPSTREAM_TIMEOUTS = {
    "face-basic": _timeout_env("AI_GATEWAY_FACE_TIMEOUT_SECONDS", 120),
    "face-pro": _timeout_env("AI_GATEWAY_FACE_TIMEOUT_SECONDS", 120),
    "render-service": _timeout_env("AI_GATEWAY_RENDER_TIMEOUT_SECONDS", 120),
    "text-suggestion": _timeout_env("AI_GATEWAY_TEXT_TIMEOUT_SECONDS", 60),
    "member-database": _timeout_env("AI_GATEWAY_MEMBER_TIMEOUT_SECONDS", 30),
}


def upstream_timeout(service: str) -> int:
    return UPSTREAM_TIMEOUTS.get(service, _timeout_env("AI_GATEWAY_DEFAULT_TIMEOUT_SECONDS", 60))
MEMBER_DATABASE_URL = _service_url("MEMBER_DATABASE_URL")
PRODUCT_DATABASE_URL = _service_url("PRODUCT_DATABASE_URL")
PRODUCT_ADMIN_API_KEY = os.getenv("PRODUCT_ADMIN_API_KEY", "")
ADMIN_PROXY_TIMEOUT_SECONDS = max(5, min(int(os.getenv("ADMIN_PROXY_TIMEOUT_SECONDS", "15")), 60))
ADMIN_PROXY_MAX_BODY_BYTES = max(1024, min(int(os.getenv("ADMIN_PROXY_MAX_BODY_BYTES", "1048576")), 5 * 1024 * 1024))
SESSION_SECRET = os.getenv("GATEWAY_SESSION_SECRET", "")
SESSION_TTL_SECONDS = max(300, min(int(os.getenv("GATEWAY_SESSION_TTL_SECONDS", "7200")), 86400))
SESSION_ONLY_MODE = os.getenv("GATEWAY_SESSION_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("GATEWAY_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "600")))
LOGIN_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("GATEWAY_LOGIN_RATE_LIMIT_MAX_REQUESTS", "10")))
IS_PRODUCTION = os.getenv("APP_ENV", "").strip().lower() in {"prod", "production"}
# Firebase Hosting forwards exactly one cookie to a Cloud Run rewrite: the one
# named `__session`.  Every other cookie is dropped at the CDN before the request
# is proxied, which is why the session used to vanish between the browser and
# this service even though the browser was sending it (S56).  Both halves of the
# session therefore have to travel inside this single name.
SESSION_COOKIE = "__session"
# The gateway access token is a JWT (base64url plus dots) and the sealed upstream
# jar is a Fernet token (base64 plus padding).  Neither alphabet contains "|", so
# it can separate them unambiguously.
SESSION_COOKIE_SEPARATOR = "|"
MAX_SEALED_MEMBER_SESSION_BYTES = 3500

# 多帳號（同一個瀏覽器、跨分頁登入多個帳號）。
# 一個瀏覽器只有一份 `__session` cookie，所以多個帳號必須共存在它裡面，做成好幾個
# 「(gateway token, 封裝過的上游 cookie)」槽位。每個分頁用 `X-Expected-Actor`——就是
# 分頁本來就綁的那個不含 email 的 opaque actor——選出要用哪一個槽位。旗標關掉時，
# 登入是「覆蓋」（只有一個槽位），行為跟原本單帳號完全一樣；選擇邏輯照樣能用，因為
# 它只是看到一個槽位而已。
MULTI_SESSION_ENABLED = os.getenv("GATEWAY_MULTI_SESSION", "").strip().lower() in {"1", "true", "yes", "on"}
MAX_SESSION_SLOTS = max(1, min(int(os.getenv("GATEWAY_MAX_SESSION_SLOTS", "4")), 8))
MULTI_SESSION_PREFIX = "v2."
# cookie 必須遠低於瀏覽器約 4 KB 的上限。每個槽位是一個 JWT 加一份 Fernet 封裝的上游
# cookie；這個上限決定同時能存在幾個槽位，超過就從最舊的開始淘汰。
MAX_SESSION_COOKIE_BYTES = max(1024, min(int(os.getenv("GATEWAY_MAX_SESSION_COOKIE_BYTES", "3800")), 4000))
LOGIN_LIMIT_COLLECTION = os.getenv("GATEWAY_LOGIN_LIMIT_COLLECTION", "gateway_login_limits")
PUBLIC_PRODUCT_PATHS = _patterns(r"api/products", r"recommend-products")
SAVED_LOOK_PATH_RE = re.compile(r"^api/members/([^/]+)/saved-looks(?:/([^/]+))?$")
MEMBER_PATH_RE = re.compile(r"^api/members/([^/]+)$")
MEMBER_SCOPE_RE = re.compile(r"^api/members/([^/]+)(?:/|$)")
# The bare roster path — no member id — returns every account, so it is an
# administrator-only view rather than the self-scoped `api/members/<id>` route.
MEMBER_LIST_PATH_RE = re.compile(r"^api/members$")
# 妝前圖的網址多一段 /before，這裡要一起認得——否則從 saved_looks 讀回的
# beforeImageUrl 解析不出 job id，retain 與刪除都會把它當成不相干的外部網址略過。
STABLE_RENDER_URL_RE = re.compile(r"(?:https://[^/]+)?/media/render/([0-9a-f]{32})(?:/before)?(?:[?#].*)?$")
PRIVATE_RENDER_URL_RE = re.compile(
    r"^https://storage\.googleapis\.com/decorate-me-renders/(?:rendered|temporary|retained)/[A-Za-z0-9._/-]+$"
)


def _validate_configuration() -> None:
    if not IS_PRODUCTION:
        return
    missing = []
    for name, upstream in UPSTREAMS.items():
        if upstream.required_in_production and not upstream.base_url:
            missing.append(f"{name}.base_url")
        if upstream.requires_upstream_api_key and not upstream.api_key:
            missing.append(f"{name}.upstream_api_key")
        if not SESSION_ONLY_MODE and not upstream.client_api_key:
            missing.append(f"{name}.gateway_api_key")
    if not MEMBER_DATABASE_URL:
        missing.append("member_database_url")
    if len(SESSION_SECRET) < 32:
        missing.append("gateway_session_secret")
    if missing:
        raise RuntimeError(f"Missing production AI Gateway configuration: {', '.join(missing)}")


_validate_configuration()


class IdentityTokenCache:
    def __init__(self) -> None:
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _expiry(token: str) -> float:
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            return float(json.loads(base64.urlsafe_b64decode(payload))["exp"])
        except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return 0

    def get(self, audience: str) -> str:
        now = time.time()
        with self._lock:
            cached = self._tokens.get(audience)
            if cached and cached[1] > now + 60:
                return cached[0]

            token = id_token.fetch_id_token(GoogleAuthRequest(), audience)
            self._tokens[audience] = (token, self._expiry(token))
            return token


TOKEN_CACHE = IdentityTokenCache()
_login_rate_lock = threading.Lock()
_login_rate_hits: dict[str, deque[float]] = {}


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def is_path_allowed(upstream: Upstream, path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in upstream.allowed_paths)


def require_client_api_key(upstream: Upstream, supplied: str) -> None:
    if upstream.client_api_key and not secret_equals(supplied, upstream.client_api_key):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing API key."}})


def require_any_client_api_key(supplied: str) -> None:
    expected = {upstream.client_api_key for upstream in UPSTREAMS.values() if upstream.client_api_key}
    if expected and not any(secret_equals(supplied, key) for key in expected):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing API key."}})


def _valid_ip(value: str) -> str:
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return ""


def client_ip(request: Request) -> str:
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    # Cloud Run appends its load-balancer address. The entry immediately before it
    # is the caller address and is safer than trusting the first user-supplied value.
    if len(forwarded) >= 2:
        candidate = _valid_ip(forwarded[-2])
        if candidate:
            return candidate
    if request.client:
        candidate = _valid_ip(request.client.host)
        if candidate:
            return candidate
    return "unknown"


def _login_quota_exceeded(key: str, now: float) -> int | None:
    """這個 key 超量的話回傳「還要等幾秒」，否則回 None。

    優先用 Firestore 的共享視窗，讓限流在每一個 Cloud Run instance 之間一致（純記憶體
    計數是每個 instance 各自算的，服務一擴充就被繞過）；只有在 Firestore 不可用時
    （例如本機開發）才退回程序內的記憶體視窗。
    """
    durable = job_store.consume_window_quota(
        LOGIN_LIMIT_COLLECTION,
        key,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        LOGIN_RATE_LIMIT_MAX_REQUESTS,
        now=now,
    )
    if durable is not None:
        allowed, _, retry_after = durable
        return None if allowed else retry_after
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    with _login_rate_lock:
        bucket = _login_rate_hits.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= LOGIN_RATE_LIMIT_MAX_REQUESTS:
            return max(1, int(bucket[0] + LOGIN_RATE_LIMIT_WINDOW_SECONDS - now))
        bucket.append(now)
        return None


def enforce_login_rate_limit(request: Request, email: str = "") -> None:
    # 兩個維度，任一個超量就拒絕：呼叫端 IP（擋「一台主機狂試很多帳號」）與被鎖定的
    # 帳號（擋「一群 IP 一起暴力破解同一個帳號」，這種只看 IP 的限流完全抓不到）。
    # 帳號那把 key 是雜湊過的——限流器從不儲存 email 本身。
    now = time.time()
    keys = [f"ip:{client_ip(request)}"]
    normalized = str(email or "").strip().lower()
    if normalized:
        keys.append("account:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest())
    for key in keys:
        retry_after = _login_quota_exceeded(key, now)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                detail={"error": {"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts."}},
            )


def issue_access_token(email: str, role: str = "", status: str = "active") -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + SESSION_TTL_SECONDS
    token = jwt.encode(
        {
            "iss": "decorate-me-ai-gateway",
            "aud": "decorate-me-ai",
            "sub": email.strip().lower(),
            "role": role[:64],
            "status": status[:32],
            "iat": now,
            "exp": expires_at,
        },
        SESSION_SECRET,
        algorithm="HS256",
    )
    return token, expires_at


def issue_legacy_media_token(url: str, owner_id: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": "decorate-me-ai-gateway",
            "aud": "decorate-me-private-media",
            "url": url,
            "ownerId": owner_id,
            "iat": now,
            "exp": now + 600,
        },
        SESSION_SECRET,
        algorithm="HS256",
    )


def _member_cookie_cipher() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(SESSION_SECRET.encode("utf-8")).digest())
    return Fernet(key)


def _upstream_cookie_header(response: httpx.Response) -> str:
    jar = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        try:
            jar.load(value)
        except Exception:
            continue
    if not jar:
        return "; ".join(f"{name}={value}" for name, value in response.cookies.items())
    return "; ".join(f"{name}={morsel.value}" for name, morsel in jar.items())


def _is_cookie_deletion(morsel) -> bool:
    """A Set-Cookie that clears a name rather than rotating its value."""
    if not morsel.value:
        return True
    max_age = str(morsel.get("max-age") or "").strip()
    if max_age:
        try:
            return int(max_age) <= 0
        except ValueError:
            return False
    return False


def merge_upstream_cookies(existing: str, response: httpx.Response) -> str:
    """Fold a response's Set-Cookie headers into the session cookie jar.

    The member database rotates one cookie at a time and also sets unrelated
    cookies (CSRF, locale).  Replacing the whole jar with just the names in the
    latest response silently drops the session cookie, so the next request is
    rejected upstream and the browser sees a spurious 401.
    """
    jar: dict[str, str] = {}
    for pair in str(existing or "").split(";"):
        name, _, value = pair.partition("=")
        if name.strip():
            jar[name.strip()] = value.strip()

    incoming = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        try:
            incoming.load(value)
        except Exception:
            continue
    if not incoming:
        for name, value in response.cookies.items():
            jar[name] = value
        return "; ".join(f"{name}={value}" for name, value in jar.items())

    for name, morsel in incoming.items():
        if _is_cookie_deletion(morsel):
            jar.pop(name, None)
        else:
            jar[name] = morsel.value
    return "; ".join(f"{name}={value}" for name, value in jar.items())


def seal_member_cookie(cookie_header: str) -> str:
    if not cookie_header:
        return ""
    sealed = _member_cookie_cipher().encrypt(cookie_header.encode("utf-8")).decode("ascii")
    if len(sealed) > MAX_SEALED_MEMBER_SESSION_BYTES:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "MEMBER_SESSION_TOO_LARGE", "message": "Member authentication failed."}},
        )
    return sealed


def read_session_cookie(request: Request) -> tuple[str, str]:
    """Split `__session` into the gateway access token and the sealed upstream jar."""
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        return "", ""
    token, _, sealed = raw.partition(SESSION_COOKIE_SEPARATOR)
    return token, sealed


def request_access_token(request: Request) -> str:
    """The gateway access token for this request, from the header or the cookie."""
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token:
        return token
    return read_session_cookie(request)[0]


def set_session_cookie(response: Response, access_token: str, sealed_member_cookie: str) -> None:
    """Write both halves of the session as the single cookie Firebase forwards."""
    response.set_cookie(
        key=SESSION_COOKIE,
        value=f"{access_token}{SESSION_COOKIE_SEPARATOR}{sealed_member_cookie}",
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )


def require_upstream_member_cookie(request: Request) -> str:
    sealed = read_session_cookie(request)[1]
    if not sealed:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_REQUIRED", "message": "Member sign-in is required."}},
        )
    return unseal_member_cookie(sealed)


def unseal_member_cookie(sealed: str) -> str:
    """解開一份封裝過的上游 cookie；缺少或無效就回 401。"""
    if not sealed:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_REQUIRED", "message": "Member sign-in is required."}},
        )
    try:
        return _member_cookie_cipher().decrypt(
            sealed.encode("ascii"),
            ttl=SESSION_TTL_SECONDS,
        ).decode("utf-8")
    except (InvalidToken, UnicodeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_INVALID", "message": "Member session is invalid or expired."}},
        )


# ── 多帳號 session 槽位 ───────────────────────────────────────────────────────
# `__session` cookie 可能是舊的單槽格式（"token|sealed"），也可能是 v2 多槽格式
# （"v2." + base64url(JSON 的 {t, s} 陣列)）。讀取一律兩種都吃；寫入則看呼叫端選哪種
# （單帳號用舊格式，所以在多帳號旗標打開之前什麼都不會變）。

def read_session_slots(request: Request) -> list[tuple[str, str]]:
    """回傳 `__session` 裡的每一個 (gateway_token, 封裝上游 cookie) 槽位。"""
    raw = request.cookies.get(SESSION_COOKIE, "")
    if not raw:
        return []
    if raw.startswith(MULTI_SESSION_PREFIX):
        try:
            decoded = base64.urlsafe_b64decode(raw[len(MULTI_SESSION_PREFIX):].encode("ascii")).decode("utf-8")
            items = json.loads(decoded)
        except (ValueError, TypeError):
            # base64 壞掉會丟 binascii.Error（是 ValueError 的子類），JSON 壞掉也是。
            return []
        slots: list[tuple[str, str]] = []
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                token = str(item.get("t") or "")
                sealed = str(item.get("s") or "")
                if token:
                    slots.append((token, sealed))
        return slots
    token, _, sealed = raw.partition(SESSION_COOKIE_SEPARATOR)
    return [(token, sealed)] if token else []


def serialize_session_slots(slots: list[tuple[str, str]]) -> str:
    data = [{"t": token, "s": sealed} for token, sealed in slots]
    encoded = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    return MULTI_SESSION_PREFIX + encoded


def set_session_slots(response: Response, slots: list[tuple[str, str]]) -> None:
    """寫出多槽的 `__session`，從最舊的槽位開始淘汰直到大小塞得下。"""
    kept = slots[-MAX_SESSION_SLOTS:] if len(slots) > MAX_SESSION_SLOTS else list(slots)
    value = serialize_session_slots(kept)
    # 絕不送出瀏覽器會默默丟掉的過大 cookie：從最舊的帳號開始砍，直到塞得下，
    # 但至少保留最新的那一個。
    while len(value) > MAX_SESSION_COOKIE_BYTES and len(kept) > 1:
        kept = kept[1:]
        value = serialize_session_slots(kept)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=value,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )


def _slot_claims(access_token: str) -> dict | None:
    """驗證某個槽位的 gateway token 並回傳 claims；無效或過期則回 None。"""
    if not access_token:
        return None
    try:
        return jwt.decode(
            access_token,
            SESSION_SECRET,
            algorithms=["HS256"],
            audience="decorate-me-ai",
            issuer="decorate-me-ai-gateway",
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        return None


def session_accounts(request: Request) -> list[dict]:
    """這個瀏覽器 `__session` 裡所有已登入的帳號，無效槽位會被丟掉。

    最新的排在最後。每一筆帶著 opaque actor、subject（email）、role，以及要以該帳號
    身分發出請求所需的原始 token 與封裝上游 cookie。
    """
    accounts: list[dict] = []
    seen: set[str] = set()
    for token, sealed in read_session_slots(request):
        claims = _slot_claims(token)
        if not claims:
            continue
        sub = str(claims.get("sub") or "").strip().lower()
        if not sub:
            continue
        actor = opaque_actor_id(sub)
        if actor in seen:
            # 同一個帳號重新登入過：只保留最新的槽位。
            accounts = [a for a in accounts if a["actorId"] != actor]
        seen.add(actor)
        accounts.append({
            "actorId": actor,
            "sub": sub,
            "role": str(claims.get("role") or "member"),
            "status": str(claims.get("status") or "active"),
            "token": token,
            "sealed": sealed,
            "claims": claims,
        })
    return accounts


def select_account(request: Request, *, for_write: bool) -> dict:
    """用 `X-Expected-Actor` 選出這個請求要以哪一個已登入帳號的身分執行。

    這個選擇器就是跨分頁隔離用的那個 per-tab opaque actor；在這裡它同時「挑出」槽位，
    所以一個請求永遠只能以「真的在這個瀏覽器登入過」的帳號身分執行。寫入時缺選擇器
    一律 fail closed；選擇器指到的帳號若沒登入在這裡，就拒絕，讓分頁去請那個帳號重新
    登入，而不是默默用成別的帳號。
    """
    accounts = session_accounts(request)
    if not accounts:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_AUTH_REQUIRED", "message": "Member sign-in is required."}},
        )
    selector = str(request.headers.get("x-expected-actor") or "").strip()
    if selector:
        for account in accounts:
            if secret_equals(selector, account["actorId"]):
                return account
        # 分頁指名的帳號並沒有登入在這個瀏覽器（可能已登出、過期，或根本沒在這裡加過）。
        # 請分頁重新建立那個帳號，而不是默默用成另一個帳號。
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "ACCOUNT_NOT_AVAILABLE", "message": "登入帳號已在其他分頁變更，請重新整理頁面後再操作。"}},
        )
    if for_write:
        # 寫入一定要指名帳號，才絕不會落到錯的帳號上。
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "EXPECTED_ACTOR_REQUIRED", "message": "無法確認目前分頁的登入身分，請重新登入後再操作。"}},
        )
    if len(accounts) == 1:
        return accounts[0]
    # 讀取時登入了好幾個帳號卻沒帶選擇器，無法判斷要用哪一個。
    raise HTTPException(
        status_code=409,
        detail={"error": {"code": "EXPECTED_ACTOR_REQUIRED", "message": "無法確認目前分頁的登入身分，請重新登入後再操作。"}},
    )


async def _validate_upstream_member_cookie(request: Request, upstream_cookie: str, subject: str) -> str:
    """Return the accepted (and possibly rotated) upstream session cookie."""
    subject = str(subject or "").strip().lower()
    if not upstream_cookie or not subject or not MEMBER_DATABASE_URL:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    headers = {"Accept": "application/json", "Cookie": upstream_cookie}
    try:
        response = await request.app.state.http_client.get(
            f"{MEMBER_DATABASE_URL}/api/members/{quote(subject, safe='')}",
            headers=headers,
            timeout=10,
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    except httpx.HTTPError:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    if response.status_code in {401, 403, 404}:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "MEMBER_SESSION_INVALID", "message": "Member session is invalid or expired."}},
        )
    if not response.is_success:
        raise HTTPException(
            status_code=503,
            detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}},
        )
    return merge_upstream_cookies(upstream_cookie, response) or upstream_cookie


async def validate_upstream_member_session(request: Request, claims: dict) -> str:
    """Confirm the sealed upstream cookie is still accepted by the member DB.

    A sealed cookie can be cryptographically valid while the upstream session
    has already been revoked or expired.  A small profile read makes the
    session preflight reflect the real upstream authentication state without
    exposing the member email or cookie to the browser.
    """
    upstream_cookie = require_upstream_member_cookie(request)
    return await _validate_upstream_member_cookie(request, upstream_cookie, str(claims.get("sub") or ""))


def opaque_actor_id(subject: str) -> str:
    digest = hashlib.sha256(f"{SESSION_SECRET}:{subject.strip().lower()}".encode("utf-8")).hexdigest()
    return f"actor_{digest[:24]}"


STATE_CHANGING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def enforce_expected_actor(request: Request, acting_owner_id: str) -> None:
    """Reject a write whose tab was pinned to a different signed-in account.

    Every browser tab shares one `__session` cookie, so signing in elsewhere in
    the same browser silently rebinds this tab's requests to the new account.
    On login the tab records its opaque actor (see `/auth/session`) and echoes
    it back as `X-Expected-Actor`.  When the cookie has since been replaced, the
    actor derived from the *current* session no longer matches, and the write is
    stopped here — before it can reach the upstream and touch the wrong account.

    Safe reads do not need the header.  State-changing requests fail closed:
    an older or broken client that omits the pinned actor is refused instead of
    being allowed to write using whichever shared cookie happens to be current.
    """
    if str(request.method or "").upper() not in STATE_CHANGING_METHODS:
        return
    expected = str(request.headers.get("x-expected-actor") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "EXPECTED_ACTOR_REQUIRED", "message": "無法確認目前分頁的登入身分，請重新登入後再操作。"}},
        )
    if not secret_equals(expected, acting_owner_id):
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "SESSION_OWNER_CHANGED", "message": "登入帳號已在其他分頁變更，請重新整理頁面後再操作。"}},
        )


def require_member_access(request: Request) -> dict:
    token = request_access_token(request)
    if not token:
        raise HTTPException(status_code=401, detail={"error": {"code": "MEMBER_AUTH_REQUIRED", "message": "Member sign-in is required."}})
    try:
        return jwt.decode(
            token,
            SESSION_SECRET,
            algorithms=["HS256"],
            audience="decorate-me-ai",
            issuer="decorate-me-ai-gateway",
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail={"error": {"code": "MEMBER_AUTH_INVALID", "message": "Member session is invalid or expired."}})


def _require_admin_claims(claims: dict) -> dict:
    if str(claims.get("status") or "active").lower() != "active":
        raise HTTPException(status_code=403, detail={"error": {"code": "ADMIN_SUSPENDED", "message": "Administrator account is suspended."}})
    if str(claims.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail={"error": {"code": "ADMIN_REQUIRED", "message": "Administrator permission is required."}})
    return claims


def require_admin_access(request: Request) -> dict:
    return _require_admin_claims(require_member_access(request))


def validate_product_id(product_id: str) -> str:
    value = str(product_id or "").strip()
    if not value or len(value) > 160 or "/" in value or "\\" in value or ".." in value or any(ord(char) < 32 for char in value):
        raise HTTPException(status_code=400, detail={"error": {"code": "INVALID_PRODUCT_ID", "message": "Invalid product id."}})
    return value


def build_upstream_headers(request: Request, upstream: Upstream, identity_token: str) -> dict[str, str]:
    headers = {
        "Accept": request.headers.get("accept", "application/json"),
        "X-Forwarded-For": client_ip(request),
    }
    if upstream.api_key:
        headers["X-API-Key"] = upstream.api_key
    if upstream.requires_cloud_run_iam and identity_token:
        headers["X-Serverless-Authorization"] = f"Bearer {identity_token}"
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    result_token = request.headers.get("x-job-token")
    if result_token:
        headers["X-Job-Token"] = result_token
    return headers


def _authorize_member_path(claims: dict, path: str) -> str | None:
    """Return a target member e-mail and block cross-member path changes."""
    match = MEMBER_SCOPE_RE.match(path)
    if not match:
        return None
    target_email = unquote(match.group(1)).strip().lower()
    subject = str(claims.get("sub") or "").strip().lower()
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    if target_email != subject and not is_admin:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "MEMBER_SCOPE_FORBIDDEN", "message": "Another member's data cannot be accessed."}},
        )
    return target_email


def _render_job_id_from_url(value: str | None) -> str | None:
    match = STABLE_RENDER_URL_RE.fullmatch(str(value or "").strip())
    return match.group(1) if match else None


async def _render_internal_request(
    request: Request,
    method: str,
    path: str,
    *,
    user_id: str = "",
    admin: bool = False,
    json_body: dict | None = None,
) -> httpx.Response | None:
    upstream = UPSTREAMS["render-service"]
    if not upstream.base_url:
        return None
    try:
        identity_token = ""
        if upstream.requires_cloud_run_iam:
            identity_token = await asyncio.to_thread(TOKEN_CACHE.get, upstream.base_url)
        headers = {"Accept": "application/json", "X-API-Key": upstream.api_key}
        if identity_token:
            headers["X-Serverless-Authorization"] = f"Bearer {identity_token}"
        if user_id:
            headers["X-User-ID"] = user_id
        if admin:
            headers["X-Admin-Request"] = "1"
        return await request.app.state.http_client.request(
            method=method,
            url=f"{upstream.base_url}/{path}",
            headers=headers,
            json=json_body,
            timeout=30,
        )
    except Exception:
        return None


def _safe_render_gateway_url(request: Request, job_id: str, variant: str = "") -> str:
    # Relative URLs keep local development and the formal Firebase origin on
    # the same authenticated path. They also fit the member DB's 500-char field.
    #
    # variant 只有 "" 與 "/before" 兩種；妝前圖是使用者的原始照片，走同一條
    # 需驗證的路徑，權限與妝後圖完全相同。
    return f"/media/render/{job_id}{variant}"


def _sanitize_render_payload(request: Request, payload):
    if isinstance(payload, list):
        return [_sanitize_render_payload(request, item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result = {key: _sanitize_render_payload(request, value) for key, value in payload.items()}
    # 渲染服務的 job 紀錄是整包回來的（_job_view 只濾掉 token），裡面有幾個純內部欄位：
    # objectName / beforeObjectName 是 GCS 的物件路徑（而且含擁有者的 actor id），
    # ownerId 是內部識別碼。bucket 是私有的，拿到路徑也開不了，但這些是實作細節，
    # 瀏覽器不需要、也不該知道——洩漏儲存結構只會幫到想摸清系統的人。
    for internal in ("objectName", "beforeObjectName", "ownerId"):
        result.pop(internal, None)

    job_id = str(result.get("jobId") or "")
    if re.fullmatch(RENDER_JOB_ID, job_id) and result.get("afterImageUrl"):
        result["afterImageUrl"] = _safe_render_gateway_url(request, job_id)
        result.pop("replicateTempUrl", None)
        result["isPermanent"] = True
        # 妝前圖同樣要改寫。渲染服務回的是 GCS 直連網址，那個網址不該進瀏覽器——
        # 改寫成 /media/render/<job>/before，讀取時才會經過擁有者檢查。
        if result.get("beforeImageUrl"):
            result["beforeImageUrl"] = _safe_render_gateway_url(request, job_id, "/before")
    return result


async def _sign_legacy_media(request: Request, value: str, owner_id: str) -> str:
    if not PRIVATE_RENDER_URL_RE.fullmatch(str(value or "").strip()):
        return value
    response = await _render_internal_request(
        request,
        "POST",
        "render/media/sign",
        user_id=owner_id,
        json_body={"url": value},
    )
    if response is None or not response.is_success:
        return f"/media/legacy/{issue_legacy_media_token(value, owner_id)}"
    try:
        signed = str(response.json().get("signedUrl") or "")
        parsed = urlsplit(signed)
        return signed if parsed.scheme == "https" and parsed.netloc == "storage.googleapis.com" else value
    except (TypeError, ValueError):
        return value


async def _refresh_saved_look_media(request: Request, payload, owner_id: str):
    if not isinstance(payload, dict):
        return payload
    looks = payload.get("looks")
    if not isinstance(looks, list):
        return payload
    raw_urls = []
    for look in looks:
        if not isinstance(look, dict):
            continue
        value = str(look.get("afterImageUrl") or look.get("after_image_url") or "")
        if PRIVATE_RENDER_URL_RE.fullmatch(value):
            raw_urls.append(value)
    signed_values = await asyncio.gather(*[_sign_legacy_media(request, value, owner_id) for value in raw_urls])
    replacements = dict(zip(raw_urls, signed_values))
    if not replacements:
        return payload
    result = dict(payload)
    result["looks"] = []
    for look in looks:
        item = dict(look) if isinstance(look, dict) else look
        if isinstance(item, dict):
            for key in ("afterImageUrl", "after_image_url"):
                if item.get(key) in replacements:
                    item[key] = replacements[item[key]]
        result["looks"].append(item)
    return result


def _saved_media_urls(payload, saved_look_id: str | None = None) -> list[str]:
    if not isinstance(payload, dict) or not isinstance(payload.get("looks"), list):
        return []
    values = []
    for look in payload["looks"]:
        if not isinstance(look, dict):
            continue
        if saved_look_id is not None and str(look.get("id")) != str(saved_look_id):
            continue
        value = str(look.get("afterImageUrl") or look.get("after_image_url") or "").strip()
        if _render_job_id_from_url(value) or PRIVATE_RENDER_URL_RE.fullmatch(value):
            values.append(value)
    return list(dict.fromkeys(values))


async def _delete_saved_media(
    request: Request,
    values: list[str],
    owner_id: str,
    *,
    admin: bool,
) -> None:
    for value in values:
        job_id = _render_job_id_from_url(value)
        if job_id:
            response = await _render_internal_request(
                request,
                "DELETE",
                f"render/jobs/{job_id}/artifact",
                user_id=owner_id,
                admin=admin,
            )
        elif PRIVATE_RENDER_URL_RE.fullmatch(value):
            response = await _render_internal_request(
                request,
                "DELETE",
                "render/media",
                user_id=owner_id,
                admin=admin,
                json_body={"url": value},
            )
        else:
            continue
        if response is None or not response.is_success:
            raise HTTPException(
                status_code=503,
                detail={"error": {"code": "MEDIA_DELETE_INCOMPLETE", "message": "圖片刪除尚未完成，請稍後重試。"}},
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(
        follow_redirects=False,
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        timeout=httpx.Timeout(UPSTREAM_TIMEOUT_SECONDS, connect=10),
    )
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="DecorateMe AI Gateway", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "If-Match", "X-API-Key", "X-Expected-Actor", "X-Job-Token"],
    max_age=3600,
)
install_api_error_handling(app, "ai-gateway")


@app.get("/health")
async def health():
    configured = all(upstream.base_url for upstream in UPSTREAMS.values() if upstream.required_in_production)
    return {
        "status": "ok" if configured else "degraded",
        "service": "ai-gateway",
        "privateUpstreamAuth": "cloud-run-iam",
        "memberAuth": "short-lived-access-token",
        "browserAuth": "member-session-only" if SESSION_ONLY_MODE else "client-key-and-member-session",
        "externalTextUpstream": "enabled-for-demo" if ALLOW_EXTERNAL_TEXT_UPSTREAM else "disabled",
    }


@app.get("/public-config")
async def public_config():
    """Only publish stable same-origin Gateway paths; never reveal upstream URLs."""
    return {
        "apiMode": "gateway",
        "memberDatabaseUrl": "/member-database",
        "productUrl": "/product-api",
        "crawlerUrl": "/admin-api",
    }


@app.get("/media/render/{job_id}/before")
async def render_media_before(job_id: str, request: Request):
    """妝前圖。權限與妝後圖完全相同——它是使用者的原始照片，只能更嚴不能更鬆。"""
    return await _serve_render_media(job_id, request, variant="before")


@app.get("/media/render/{job_id}")
async def render_media(job_id: str, request: Request):
    return await _serve_render_media(job_id, request, variant="after")


async def _serve_render_media(job_id: str, request: Request, variant: str = "after"):
    """Authenticate a member, then redirect to a ten-minute private GCS URL."""
    if not re.fullmatch(RENDER_JOB_ID, job_id):
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    # variant 只會是這兩個字面值，直接拼進 query 沒有注入空間
    query = "?variant=before" if variant == "before" else ""
    claims = require_member_access(request)
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    owner_id = opaque_actor_id(str(claims.get("sub") or ""))
    response = await _render_internal_request(
        request,
        "GET",
        f"render/jobs/{job_id}/signed-url{query}",
        user_id=owner_id,
        admin=is_admin,
    )
    if response is None:
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    if response.status_code in {403, 404}:
        raise HTTPException(status_code=response.status_code, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    if not response.is_success:
        fallback = await _render_internal_request(
            request,
            "GET",
            f"render/jobs/{job_id}/content{query}",
            user_id=owner_id,
            admin=is_admin,
        )
        if fallback is None or not fallback.is_success:
            raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
        content_type = str(fallback.headers.get("content-type") or "")
        if not content_type.startswith("image/"):
            raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
        return Response(
            content=fallback.content,
            media_type=content_type.split(";", 1)[0],
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )
    try:
        signed_url = str(response.json().get("signedUrl") or "")
    except ValueError:
        signed_url = ""
    parsed = urlsplit(signed_url)
    if parsed.scheme != "https" or parsed.netloc != "storage.googleapis.com":
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    return RedirectResponse(
        url=signed_url,
        status_code=302,
        headers={"Cache-Control": "private, no-store", "Referrer-Policy": "no-referrer"},
    )


@app.get("/media/legacy/{media_token}")
async def legacy_render_media(media_token: str, request: Request):
    """Serve an old saved GCS URL through an expiring, member-bound link."""
    claims = require_member_access(request)
    try:
        media_claims = jwt.decode(
            media_token,
            SESSION_SECRET,
            algorithms=["HS256"],
            audience="decorate-me-private-media",
            issuer="decorate-me-ai-gateway",
            options={"require": ["exp", "iat", "url", "ownerId"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    acting_owner_id = opaque_actor_id(str(claims.get("sub") or ""))
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    if acting_owner_id != str(media_claims.get("ownerId") or "") and not is_admin:
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    media_url = str(media_claims.get("url") or "")
    if not PRIVATE_RENDER_URL_RE.fullmatch(media_url):
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    response = await _render_internal_request(
        request,
        "POST",
        "render/media/content",
        user_id=acting_owner_id,
        admin=is_admin,
        json_body={"url": media_url},
    )
    if response is None or not response.is_success:
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    content_type = str(response.headers.get("content-type") or "")
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=503, detail={"error": {"code": "MEDIA_UNAVAILABLE", "message": "Render image is temporarily unavailable."}})
    return Response(
        content=response.content,
        media_type=content_type.split(";", 1)[0],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.post("/auth/login")
async def login(body: LoginRequest, request: Request):
    # In session-only mode the browser has no reusable API key.  Login is
    # protected by the rate limiter and the member credentials themselves.
    if not SESSION_ONLY_MODE:
        require_any_client_api_key(request.headers.get("x-api-key", ""))
    enforce_login_rate_limit(request, body.email)
    if not MEMBER_DATABASE_URL or not SESSION_SECRET:
        raise HTTPException(status_code=503, detail={"error": {"code": "AUTH_NOT_CONFIGURED", "message": "Member authentication is unavailable."}})

    try:
        response = await request.app.state.http_client.post(
            f"{MEMBER_DATABASE_URL}/api/login",
            json={"email": body.email, "password": body.password},
            timeout=20,
        )
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member authentication is unavailable."}})

    # 「信箱尚未驗證」必須與「帳密錯誤」分開，否則使用者只會看到「帳號或密碼錯誤」，
    # 完全不知道要去收驗證信——照著重試密碼永遠不會成功。
    #
    # 這裡刻意只透傳這一個碼，不是把上游的錯誤照單全收：其餘的 401/403/404 仍然
    # 一律壓成同一句 INVALID_CREDENTIALS，避免用回應差異枚舉哪些信箱已註冊。
    if response.status_code == 403 and _upstream_error_code(response) == "EMAIL_NOT_VERIFIED":
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "EMAIL_NOT_VERIFIED",
                              "message": "此帳號尚未完成信箱驗證，請至信箱收取驗證碼。",
                              "retryable": False}},
        )
    if response.status_code in {401, 403, 404}:
        raise HTTPException(status_code=401, detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}})
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail={"error": {"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts."}})
    if not response.is_success:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})

    try:
        payload = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})
    if payload.get("success") is False:
        raise HTTPException(status_code=401, detail={"error": {"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."}})

    member = payload.get("member") or payload.get("user")
    if not isinstance(member, dict) or not member:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})
    verified_email = str(member.get("email") or "").strip().lower()
    if not verified_email or verified_email != body.email.strip().lower():
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SERVICE_ERROR", "message": "Member authentication failed."}})
    role = str(member.get("role") or member.get("member_role") or "")
    member_status = str(member.get("status") or "active")
    access_token, expires_at = issue_access_token(verified_email, role, member_status)
    upstream_cookie = _upstream_cookie_header(response)
    if not upstream_cookie:
        raise HTTPException(status_code=502, detail={"error": {"code": "MEMBER_SESSION_MISSING", "message": "Member authentication failed."}})
    try:
        upstream_cookie = await _validate_upstream_member_cookie(request, upstream_cookie, verified_email)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise HTTPException(
                status_code=502,
                detail={"error": {"code": "MEMBER_SESSION_UNUSABLE", "message": "Member authentication session could not be established."}},
            )
        raise
    actor_id = opaque_actor_id(verified_email)
    payload = {"success": True, "member": member, "expiresAt": expires_at, "actorId": actor_id}
    if not SESSION_ONLY_MODE:
        payload.update({"accessToken": access_token, "tokenType": "Bearer"})
    result = JSONResponse(content=payload)
    sealed_new = seal_member_cookie(upstream_cookie)
    if MULTI_SESSION_ENABLED:
        # 把這個帳號「加」到這個瀏覽器已登入的其他帳號旁邊。
        # 同一個帳號重複登入，就更新（覆蓋）它自己那一個槽位。
        slots = [
            (token, sealed)
            for token, sealed in read_session_slots(request)
            if not (_slot_claims(token) and opaque_actor_id(str(_slot_claims(token).get("sub") or "").strip().lower()) == actor_id)
        ]
        slots.append((access_token, sealed_new))
        set_session_slots(result, slots)
    else:
        set_session_cookie(result, access_token, sealed_new)
    return result


@app.post("/auth/logout")
async def logout(request: Request):
    result = JSONResponse(content={"ok": True})
    # 多帳號：帶 `?actor=<id>` 只登出那一個帳號，這個瀏覽器上的其他帳號維持登入。
    # 沒帶（或旗標關掉）時，就跟以前一樣把整個 session 清掉。
    actor = str(request.query_params.get("actor") or "").strip()
    remaining: list[tuple[str, str]] = []
    if MULTI_SESSION_ENABLED and actor:
        for token, sealed in read_session_slots(request):
            claims = _slot_claims(token)
            slot_actor = opaque_actor_id(str(claims.get("sub") or "").strip().lower()) if claims else ""
            if slot_actor and slot_actor != actor:
                remaining.append((token, sealed))
    if remaining:
        set_session_slots(result, remaining)
        return result
    result.delete_cookie(key=SESSION_COOKIE, path="/", secure=IS_PRODUCTION, httponly=True, samesite="lax")
    # Browsers that signed in before S56 still carry the two retired cookies.
    # Nothing reads them any more, but clearing them on the way out keeps stale
    # credentials from sitting in the jar until they expire on their own.
    for retired in ("dm_session", "dm_member_session"):
        result.delete_cookie(key=retired, path="/", secure=IS_PRODUCTION, httponly=True, samesite="lax")
    return result


@app.get("/auth/session")
async def session_status(request: Request):
    """Verify both Gateway and upstream member sessions before loading private pages."""
    if not MULTI_SESSION_ENABLED:
        claims = require_member_access(request)
        upstream_cookie = await validate_upstream_member_session(request, claims)
        # `sub` tells the browser *who* this session belongs to.  Without it a page
        # that still holds a stale profile in localStorage keeps addressing member
        # routes as the previous account: signing in as an administrator replaces
        # the single `__session` cookie, every member call then asks the database
        # for somebody else's rows, and the 403 that comes back is indistinguishable
        # from a permission bug.  The subject is the caller's own identity, so
        # returning it to the authenticated owner reveals nothing new.
        result = JSONResponse(content={
            "ok": True,
            "sub": str(claims.get("sub") or ""),
            "actorId": opaque_actor_id(str(claims.get("sub") or "")),
            "role": str(claims.get("role") or "member"),
            "status": str(claims.get("status") or "active"),
            "expiresAt": int(claims.get("exp") or 0) * 1000,
        })
        set_session_cookie(result, request_access_token(request), seal_member_cookie(upstream_cookie))
        return result

    # 多帳號：回報這個分頁選中的帳號（全新分頁則預設用最新登入的那個），外加這個
    # 瀏覽器上所有已登入帳號的清單，讓前端可以畫出「帳號切換器」。只回傳 opaque actor
    # 與呼叫者自己本來就擁有的 subject——不會外洩其他帳號的任何資料。
    accounts = session_accounts(request)
    if not accounts:
        require_member_access(request)  # preserves the 401 MEMBER_AUTH_* contract
    selector = str(request.headers.get("x-expected-actor") or "").strip()
    account = None
    if selector:
        for candidate in accounts:
            if secret_equals(selector, candidate["actorId"]):
                account = candidate
                break
        if account is None:
            raise HTTPException(
                status_code=409,
                detail={"error": {"code": "ACCOUNT_NOT_AVAILABLE", "message": "登入帳號已在其他分頁變更，請重新整理頁面後再操作。"}},
            )
    else:
        account = accounts[-1]  # 全新分頁沒帶選擇器時，預設用最新登入的帳號
    upstream_cookie = await _validate_upstream_member_cookie(
        request, unseal_member_cookie(account["sealed"]), account["sub"]
    )
    result = JSONResponse(content={
        "ok": True,
        "sub": account["sub"],
        "actorId": account["actorId"],
        "role": account["role"],
        "status": account["status"],
        "expiresAt": int(account["claims"].get("exp") or 0) * 1000,
        "accounts": [
            {"actorId": a["actorId"], "sub": a["sub"], "role": a["role"], "status": a["status"]}
            for a in accounts
        ],
    })
    sealed = seal_member_cookie(upstream_cookie)
    rebuilt: list[tuple[str, str]] = []
    for token, slot_sealed in read_session_slots(request):
        slot_claims = _slot_claims(token)
        slot_actor = opaque_actor_id(str(slot_claims.get("sub") or "").strip().lower()) if slot_claims else ""
        rebuilt.append((account["token"], sealed) if slot_actor == account["actorId"] else (token, slot_sealed))
    set_session_slots(result, rebuilt)
    return result


def _upstream_error_code(response) -> str:
    """取出上游 JSON 裡的 error.code；格式不符時回空字串。

    上游壞掉或回了非 JSON 時不能讓登入整個爆掉——取不到就當作沒有，
    呼叫端會落到一般的錯誤處理。
    """
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return str(error.get("code") or "")
    return str(payload.get("code") or "")


async def proxy_public_member_request(request: Request, upstream_path: str):
    """Forward only the three pre-login member operations.

    These routes deliberately do not accept arbitrary paths.  The browser can
    register or verify an OTP, but it never learns the member database URL.
    Login attempts and OTP operations share the gateway rate limiter.
    """
    enforce_login_rate_limit(request)
    body = await request.body()
    if len(body) > 256 * 1024:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})
    if not MEMBER_DATABASE_URL:
        raise HTTPException(status_code=503, detail={"error": {"code": "AUTH_NOT_CONFIGURED", "message": "Member authentication is unavailable."}})
    headers = {"Accept": request.headers.get("accept", "application/json"), "Content-Type": request.headers.get("content-type", "application/json")}
    try:
        response = await request.app.state.http_client.post(
            f"{MEMBER_DATABASE_URL}{upstream_path}",
            content=body,
            headers=headers,
            timeout=20,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "MEMBER_SERVICE_TIMEOUT", "message": "Member service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"error": {"code": "MEMBER_SERVICE_UNAVAILABLE", "message": "Member service is unavailable."}})
    response_headers = {"X-Content-Type-Options": "nosniff"}
    if response.headers.get("content-type"):
        response_headers["content-type"] = response.headers["content-type"]
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.post("/auth/register")
async def register(request: Request):
    return await proxy_public_member_request(request, "/api/register")


@app.post("/auth/send-otp")
async def send_otp(request: Request):
    return await proxy_public_member_request(request, "/api/send-otp")


@app.post("/auth/verify-otp")
async def verify_otp(request: Request):
    return await proxy_public_member_request(request, "/api/verify-otp")


async def proxy_admin_request(request: Request, upstream_path: str):
    if MULTI_SESSION_ENABLED:
        is_write = str(request.method or "").upper() in STATE_CHANGING_METHODS
        claims = _require_admin_claims(select_account(request, for_write=is_write)["claims"])
    else:
        claims = require_admin_access(request)
        enforce_expected_actor(request, opaque_actor_id(str(claims.get("sub") or "")))
    if not PRODUCT_DATABASE_URL or not PRODUCT_ADMIN_API_KEY:
        raise HTTPException(status_code=503, detail={"error": {"code": "ADMIN_PROXY_NOT_CONFIGURED", "message": "Admin proxy is not configured."}})

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > ADMIN_PROXY_MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}})
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": {"code": "BAD_CONTENT_LENGTH", "message": "Invalid Content-Length header."}})
    body = await request.body()
    if len(body) > ADMIN_PROXY_MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}})

    headers = {
        "Accept": request.headers.get("accept", "application/json"),
        "Authorization": f"Bearer {PRODUCT_ADMIN_API_KEY}",
        "X-Admin-Actor": opaque_actor_id(str(claims.get("sub") or "")),
        "X-Request-ID": request.headers.get("x-request-id", secrets.token_hex(16))[:128],
    }
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    if request.headers.get("if-match"):
        headers["If-Match"] = request.headers["if-match"][:32]

    try:
        response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{PRODUCT_DATABASE_URL}{upstream_path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=body,
            timeout=ADMIN_PROXY_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"detail": {"error": {"code": "PRODUCT_UPSTREAM_TIMEOUT", "message": "Product service timed out.", "retryable": True}}})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"detail": {"error": {"code": "PRODUCT_SERVICE_UNAVAILABLE", "message": "Product service is unavailable.", "retryable": True}}})

    response_headers = {"X-Content-Type-Options": "nosniff"}
    for header in ("content-type", "cache-control", "retry-after", "x-request-id"):
        if response.headers.get(header):
            response_headers[header] = response.headers[header]
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.api_route("/admin-api/products", methods=["GET", "POST"])
async def admin_products(request: Request):
    return await proxy_admin_request(request, "/api/products")


@app.api_route("/admin-api/products/{product_id}", methods=["GET", "PATCH", "DELETE"])
async def admin_product(product_id: str, request: Request):
    safe_id = validate_product_id(product_id)
    return await proxy_admin_request(request, f"/api/products/{safe_id}")


@app.post("/admin-api/crawler/product-preview")
async def admin_crawler_preview(request: Request):
    return await proxy_admin_request(request, "/api/crawler/product-preview")


@app.post("/admin-api/crawler/search-preview")
async def admin_crawler_search(request: Request):
    return await proxy_admin_request(request, "/api/crawler/search-preview")


@app.get("/admin-api/product-audit-logs")
async def admin_product_audit_logs(request: Request):
    return await proxy_admin_request(request, "/api/admin/product-audit-logs")


async def proxy_public_product_request(request: Request, path: str):
    if not PRODUCT_DATABASE_URL or not any(pattern.fullmatch(path) for pattern in PUBLIC_PRODUCT_PATHS):
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Route not found."}})
    if (path == "api/products" and request.method != "GET") or (path == "recommend-products" and request.method != "POST"):
        raise HTTPException(status_code=405, detail={"error": {"code": "METHOD_NOT_ALLOWED", "message": "Method not allowed."}})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})
    headers = {"Accept": request.headers.get("accept", "application/json")}
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    try:
        response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{PRODUCT_DATABASE_URL}/{path}",
            params=list(request.query_params.multi_items()),
            headers=headers,
            content=body,
            timeout=ADMIN_PROXY_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "PRODUCT_UPSTREAM_TIMEOUT", "message": "Product service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=503, content={"error": {"code": "PRODUCT_SERVICE_UNAVAILABLE", "message": "Product service is unavailable."}})
    response_headers = {"X-Content-Type-Options": "nosniff"}
    for header in ("content-type", "cache-control", "etag", "retry-after"):
        if response.headers.get(header):
            response_headers[header] = response.headers[header]
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.api_route("/product-api/{path:path}", methods=["GET", "POST"])
async def public_product_proxy(path: str, request: Request):
    return await proxy_public_product_request(request, path)


@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PATCH", "DELETE"])
async def proxy(service: str, path: str, request: Request):
    upstream = UPSTREAMS.get(service)
    if upstream is None or not is_path_allowed(upstream, path):
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Route not found."}})

    if service == "text-suggestion" and not ALLOW_EXTERNAL_TEXT_UPSTREAM:
        raise HTTPException(status_code=503, detail={"error": {"code": "EXTERNAL_TEXT_UPSTREAM_DISABLED", "message": "External text suggestion is disabled until the trusted service is ready."}})

    if not SESSION_ONLY_MODE:
        require_client_api_key(upstream, request.headers.get("x-api-key", ""))
    # `X-Expected-Actor` 同時負責隔離與（多帳號時）選帳號。多帳號打開時，它決定要以
    # 哪一個已登入帳號的身分執行；關掉時，行為就是原本的單帳號路徑（單槽、寫入要帶
    # 標頭、對不上就拒絕）。關掉時刻意維持一模一樣，所以連 bearer token（非 session-only）
    # 的請求也照舊不受影響。
    selected_sealed = ""
    if MULTI_SESSION_ENABLED:
        is_write = str(request.method or "").upper() in STATE_CHANGING_METHODS
        account = select_account(request, for_write=is_write)
        claims = account["claims"]
        acting_owner_id = account["actorId"]
        selected_sealed = account["sealed"]
    else:
        claims = require_member_access(request)
        acting_owner_id = opaque_actor_id(str(claims.get("sub") or ""))
        enforce_expected_actor(request, acting_owner_id)
    target_email = _authorize_member_path(claims, path) if service == "member-database" else None
    target_owner_id = opaque_actor_id(target_email) if target_email else acting_owner_id
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    # The full member roster is an administrator-only view.  `_authorize_member_path`
    # only guards `api/members/<id>` routes; the bare list path matches nothing
    # there, so without this any signed-in member could read every account.
    if service == "member-database" and MEMBER_LIST_PATH_RE.fullmatch(path) and not is_admin:
        raise HTTPException(
            status_code=403,
            detail={"error": {"code": "ADMIN_REQUIRED", "message": "Administrator permission is required."}},
        )
    upstream_member_cookie = ""
    if service == "member-database":
        upstream_member_cookie = unseal_member_cookie(selected_sealed) if MULTI_SESSION_ENABLED else require_upstream_member_cookie(request)
    if not upstream.base_url:
        raise HTTPException(status_code=503, detail={"error": {"code": "NOT_CONFIGURED", "message": "Upstream service is not configured."}})

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_BYTES:
                raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})
        except ValueError:
            raise HTTPException(status_code=400, detail={"error": {"code": "BAD_CONTENT_LENGTH", "message": "Invalid Content-Length header."}})

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Request body is too large."}})

    try:
        identity_token = ""
        if upstream.requires_cloud_run_iam:
            identity_token = await asyncio.to_thread(TOKEN_CACHE.get, upstream.base_url)
        upstream_headers = build_upstream_headers(request, upstream, identity_token)
        if upstream_member_cookie:
            upstream_headers["Cookie"] = upstream_member_cookie
        if service == "render-service":
            upstream_headers["X-User-ID"] = acting_owner_id

        prefetched_media: list[str] = []
        saved_match = SAVED_LOOK_PATH_RE.fullmatch(path) if service == "member-database" else None
        member_match = MEMBER_PATH_RE.fullmatch(path) if service == "member-database" else None
        if service == "member-database" and request.method == "DELETE" and (saved_match or member_match):
            list_path = f"api/members/{saved_match.group(1) if saved_match else member_match.group(1)}/saved-looks"
            before_delete = await request.app.state.http_client.get(
                f"{upstream.base_url}/{list_path}",
                headers=upstream_headers,
                timeout=20,
            )
            if not before_delete.is_success:
                raise HTTPException(
                    status_code=503,
                    detail={"error": {"code": "MEDIA_OWNERSHIP_LOOKUP_FAILED", "message": "無法確認待刪圖片，請稍後重試。"}},
                )
            try:
                prefetched_media = _saved_media_urls(
                    before_delete.json(),
                    saved_match.group(2) if saved_match and saved_match.group(2) else None,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=503,
                    detail={"error": {"code": "MEDIA_OWNERSHIP_LOOKUP_FAILED", "message": "無法確認待刪圖片，請稍後重試。"}},
                ) from exc

            # Privacy-first deletion: remove private media while the member row
            # still exists and can be retried.  If storage deletion fails, stop
            # before deleting the database row instead of returning a false
            # success and leaving untracked face images behind.
            await _delete_saved_media(request, prefetched_media, target_owner_id, admin=is_admin)
            if member_match:
                render_cleanup = await _render_internal_request(
                    request,
                    "DELETE",
                    f"render/users/{target_owner_id}",
                    user_id=target_owner_id,
                    admin=is_admin,
                )
                if render_cleanup is None or not render_cleanup.is_success:
                    raise HTTPException(
                        status_code=503,
                        detail={"error": {"code": "MEMBER_MEDIA_DELETE_INCOMPLETE", "message": "會員圖片刪除尚未完成，請稍後重試。"}},
                    )
        response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{upstream.base_url}/{path}",
            params=list(request.query_params.multi_items()),
            headers=upstream_headers,
            content=body,
            timeout=upstream_timeout(service),
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "UPSTREAM_TIMEOUT", "message": "Upstream service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=502, content={"error": {"code": "UPSTREAM_UNAVAILABLE", "message": "Upstream service is unavailable."}})
    except HTTPException:
        raise
    except Exception:
        return JSONResponse(status_code=503, content={"error": {"code": "IDENTITY_TOKEN_UNAVAILABLE", "message": "Service authentication is unavailable."}})

    response_headers = {"X-Content-Type-Options": "nosniff"}
    for header in ("content-type", "cache-control", "retry-after"):
        if response.headers.get(header):
            response_headers[header] = response.headers[header]
    response_content = response.content
    if response.is_success and service == "render-service":
        try:
            response_content = json.dumps(
                _sanitize_render_payload(request, response.json()),
                ensure_ascii=False,
            ).encode("utf-8")
            response_headers["content-type"] = "application/json"
        except ValueError:
            pass
    if response.is_success and service == "member-database" and request.method == "GET" and SAVED_LOOK_PATH_RE.fullmatch(path):
        try:
            response_content = json.dumps(
                await _refresh_saved_look_media(request, response.json(), target_owner_id),
                ensure_ascii=False,
            ).encode("utf-8")
            response_headers["content-type"] = "application/json"
        except ValueError:
            pass

    if response.is_success and service == "member-database":
        saved_match = SAVED_LOOK_PATH_RE.fullmatch(path)
        member_match = MEMBER_PATH_RE.fullmatch(path)
        if request.method == "POST" and saved_match and not saved_match.group(2):
            try:
                submitted = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                submitted = {}
            job_id = _render_job_id_from_url(submitted.get("afterImageUrl"))
            if job_id:
                retained = await _render_internal_request(
                    request,
                    "POST",
                    f"render/jobs/{job_id}/retain",
                    user_id=target_owner_id,
                    admin=is_admin,
                )
                if retained is None or not retained.is_success:
                    raise HTTPException(
                        status_code=503,
                        detail={"error": {"code": "MEDIA_RETAIN_INCOMPLETE", "message": "妝前與妝後圖片尚未完整保存，請稍後重試。"}},
                    )

    result = Response(content=response_content, status_code=response.status_code, headers=response_headers)
    if service == "member-database":
        rotated_cookie = merge_upstream_cookies(upstream_member_cookie, response)
        if rotated_cookie and rotated_cookie != upstream_member_cookie:
            try:
                sealed = seal_member_cookie(rotated_cookie)
            except HTTPException:
                # The upstream work already succeeded.  Failing to refresh the
                # sealed jar must not turn that into an error the caller will
                # retry; the previous cookie stays valid until it expires.
                sealed = ""
            if sealed and MULTI_SESSION_ENABLED:
                # 只更新「正在操作的那個帳號」的槽位；這個瀏覽器上其他已登入帳號的
                # 封裝 cookie 必須原封不動保留。
                rebuilt: list[tuple[str, str]] = []
                replaced = False
                for token, slot_sealed in read_session_slots(request):
                    slot_claims = _slot_claims(token)
                    slot_actor = opaque_actor_id(str(slot_claims.get("sub") or "").strip().lower()) if slot_claims else ""
                    if slot_actor == acting_owner_id:
                        rebuilt.append((account["token"], sealed))
                        replaced = True
                    else:
                        rebuilt.append((token, slot_sealed))
                if not replaced:
                    rebuilt.append((account["token"], sealed))
                set_session_slots(result, rebuilt)
            elif sealed:
                set_session_cookie(result, request_access_token(request), sealed)
    return result


if __name__ == "__main__":
    from dev_server_utils import run_dev_server

    run_dev_server(app, "AI Gateway", "AI_GATEWAY", 8015)
