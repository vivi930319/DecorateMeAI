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
from api_errors import install_api_error_handling
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
            rf"render/jobs/{RENDER_JOB_ID}/signed-url",
            rf"render/jobs/{RENDER_JOB_ID}/content",
            rf"render/jobs/{RENDER_JOB_ID}/retain",
            rf"render/jobs/{RENDER_JOB_ID}/artifact",
            r"render/media/sign",
            r"render/media/content",
            r"render/media",
            r"render/users/actor_[0-9a-f]{24}",
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
MEMBER_SESSION_COOKIE = "dm_member_session"
MAX_SEALED_MEMBER_SESSION_BYTES = 3500
LOGIN_LIMIT_COLLECTION = os.getenv("GATEWAY_LOGIN_LIMIT_COLLECTION", "gateway_login_limits")
PUBLIC_PRODUCT_PATHS = _patterns(r"api/products", r"recommend-products")
SAVED_LOOK_PATH_RE = re.compile(r"^api/members/([^/]+)/saved-looks(?:/([^/]+))?$")
MEMBER_PATH_RE = re.compile(r"^api/members/([^/]+)$")
MEMBER_SCOPE_RE = re.compile(r"^api/members/([^/]+)(?:/|$)")
STABLE_RENDER_URL_RE = re.compile(r"(?:https://[^/]+)?/media/render/([0-9a-f]{32})(?:[?#].*)?$")
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
    if upstream.client_api_key and not secrets.compare_digest(supplied, upstream.client_api_key):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing API key."}})


def require_any_client_api_key(supplied: str) -> None:
    expected = {upstream.client_api_key for upstream in UPSTREAMS.values() if upstream.client_api_key}
    if expected and not any(secrets.compare_digest(supplied, key) for key in expected):
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


def enforce_login_rate_limit(request: Request) -> None:
    now = time.time()
    cutoff = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS
    key = client_ip(request)
    durable = job_store.consume_window_quota(
        LOGIN_LIMIT_COLLECTION,
        key,
        LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        LOGIN_RATE_LIMIT_MAX_REQUESTS,
        now=now,
    )
    if durable is not None:
        allowed, _, retry_after = durable
        if not allowed:
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                detail={"error": {"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts."}},
            )
        return
    with _login_rate_lock:
        bucket = _login_rate_hits.setdefault(key, deque())
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= LOGIN_RATE_LIMIT_MAX_REQUESTS:
            retry_after = max(1, int(bucket[0] + LOGIN_RATE_LIMIT_WINDOW_SECONDS - now))
            raise HTTPException(
                status_code=429,
                headers={"Retry-After": str(retry_after)},
                detail={"error": {"code": "LOGIN_RATE_LIMITED", "message": "Too many login attempts."}},
            )
        bucket.append(now)


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


def require_upstream_member_cookie(request: Request) -> str:
    sealed = request.cookies.get(MEMBER_SESSION_COOKIE, "")
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
    return _upstream_cookie_header(response) or upstream_cookie


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


def require_member_access(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if not token:
        token = request.cookies.get("dm_session", "")
        scheme = "bearer" if token else ""
    if scheme.lower() != "bearer" or not token:
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


def require_admin_access(request: Request) -> dict:
    claims = require_member_access(request)
    if str(claims.get("status") or "active").lower() != "active":
        raise HTTPException(status_code=403, detail={"error": {"code": "ADMIN_SUSPENDED", "message": "Administrator account is suspended."}})
    if str(claims.get("role") or "").lower() != "admin":
        raise HTTPException(status_code=403, detail={"error": {"code": "ADMIN_REQUIRED", "message": "Administrator permission is required."}})
    return claims


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


def _safe_render_gateway_url(request: Request, job_id: str) -> str:
    # Relative URLs keep local development and the formal Firebase origin on
    # the same authenticated path. They also fit the member DB's 500-char field.
    return f"/media/render/{job_id}"


def _sanitize_render_payload(request: Request, payload):
    if isinstance(payload, list):
        return [_sanitize_render_payload(request, item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    result = {key: _sanitize_render_payload(request, value) for key, value in payload.items()}
    job_id = str(result.get("jobId") or "")
    if re.fullmatch(RENDER_JOB_ID, job_id) and result.get("afterImageUrl"):
        result["afterImageUrl"] = _safe_render_gateway_url(request, job_id)
        result.pop("replicateTempUrl", None)
        result["isPermanent"] = True
    return result


async def _sign_legacy_media(request: Request, value: str, owner_id: str) -> str:
    if not PRIVATE_RENDER_URL_RE.fullmatch(str(value or "").strip()):
        return value
    response = await _render_internal_request(
        request,
        "POST",
        "render/media/sign",
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
            await _render_internal_request(
                request,
                "DELETE",
                f"render/jobs/{job_id}/artifact",
                user_id=owner_id,
                admin=admin,
            )
        elif PRIVATE_RENDER_URL_RE.fullmatch(value):
            await _render_internal_request(
                request,
                "DELETE",
                "render/media",
                user_id=owner_id,
                admin=admin,
                json_body={"url": value},
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
    allow_headers=["Accept", "Authorization", "Content-Type", "If-Match", "X-API-Key", "X-Job-Token"],
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


@app.get("/media/render/{job_id}")
async def render_media(job_id: str, request: Request):
    """Authenticate a member, then redirect to a ten-minute private GCS URL."""
    if not re.fullmatch(RENDER_JOB_ID, job_id):
        raise HTTPException(status_code=404, detail={"error": {"code": "MEDIA_NOT_FOUND", "message": "Render image was not found."}})
    claims = require_member_access(request)
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    owner_id = opaque_actor_id(str(claims.get("sub") or ""))
    response = await _render_internal_request(
        request,
        "GET",
        f"render/jobs/{job_id}/signed-url",
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
            f"render/jobs/{job_id}/content",
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
    enforce_login_rate_limit(request)
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
    payload = {"success": True, "member": member, "expiresAt": expires_at}
    if not SESSION_ONLY_MODE:
        payload.update({"accessToken": access_token, "tokenType": "Bearer"})
    result = JSONResponse(content=payload)
    result.set_cookie(
        key="dm_session",
        value=access_token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )
    result.set_cookie(
        key=MEMBER_SESSION_COOKIE,
        value=seal_member_cookie(upstream_cookie),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )
    return result


@app.post("/auth/logout")
async def logout():
    result = JSONResponse(content={"ok": True})
    result.delete_cookie(key="dm_session", path="/", secure=IS_PRODUCTION, httponly=True, samesite="lax")
    result.delete_cookie(key=MEMBER_SESSION_COOKIE, path="/", secure=IS_PRODUCTION, httponly=True, samesite="lax")
    return result


@app.get("/auth/session")
async def session_status(request: Request):
    """Verify both Gateway and upstream member sessions before loading private pages."""
    claims = require_member_access(request)
    upstream_cookie = await validate_upstream_member_session(request, claims)
    result = JSONResponse(content={
        "ok": True,
        "role": str(claims.get("role") or "member"),
        "status": str(claims.get("status") or "active"),
        "expiresAt": int(claims.get("exp") or 0) * 1000,
    })
    result.set_cookie(
        key=MEMBER_SESSION_COOKIE,
        value=seal_member_cookie(upstream_cookie),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        secure=IS_PRODUCTION,
        samesite="lax",
        path="/",
    )
    return result


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
    claims = require_admin_access(request)
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
    claims = require_member_access(request)
    target_email = _authorize_member_path(claims, path) if service == "member-database" else None
    acting_owner_id = opaque_actor_id(str(claims.get("sub") or ""))
    target_owner_id = opaque_actor_id(target_email) if target_email else acting_owner_id
    is_admin = str(claims.get("role") or "").strip().lower() == "admin"
    upstream_member_cookie = ""
    if service == "member-database":
        upstream_member_cookie = require_upstream_member_cookie(request)
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
            if before_delete.is_success:
                try:
                    prefetched_media = _saved_media_urls(
                        before_delete.json(),
                        saved_match.group(2) if saved_match and saved_match.group(2) else None,
                    )
                except ValueError:
                    prefetched_media = []
        response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{upstream.base_url}/{path}",
            params=list(request.query_params.multi_items()),
            headers=upstream_headers,
            content=body,
        )
    except httpx.TimeoutException:
        return JSONResponse(status_code=504, content={"error": {"code": "UPSTREAM_TIMEOUT", "message": "Upstream service timed out."}})
    except httpx.HTTPError:
        return JSONResponse(status_code=502, content={"error": {"code": "UPSTREAM_UNAVAILABLE", "message": "Upstream service is unavailable."}})
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
                await _render_internal_request(
                    request,
                    "POST",
                    f"render/jobs/{job_id}/retain",
                    user_id=target_owner_id,
                    admin=is_admin,
                )
        elif request.method == "DELETE" and saved_match:
            await _delete_saved_media(request, prefetched_media, target_owner_id, admin=is_admin)
        elif request.method == "DELETE" and member_match:
            await _delete_saved_media(request, prefetched_media, target_owner_id, admin=is_admin)
            await _render_internal_request(
                request,
                "DELETE",
                f"render/users/{target_owner_id}",
                user_id=target_owner_id,
                admin=is_admin,
            )

    result = Response(content=response_content, status_code=response.status_code, headers=response_headers)
    if service == "member-database":
        rotated_cookie = _upstream_cookie_header(response)
        if rotated_cookie:
            result.set_cookie(
                key=MEMBER_SESSION_COOKIE,
                value=seal_member_cookie(rotated_cookie),
                max_age=SESSION_TTL_SECONDS,
                httponly=True,
                secure=IS_PRODUCTION,
                samesite="lax",
                path="/",
            )
    return result


if __name__ == "__main__":
    from dev_server_utils import run_dev_server

    run_dev_server(app, "AI Gateway", "AI_GATEWAY", 8015)
