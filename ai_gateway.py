import asyncio
import base64
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

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from dev_server_utils import get_cors_origins


@dataclass(frozen=True)
class Upstream:
    base_url: str
    api_key: str
    client_api_key: str
    allowed_paths: tuple[re.Pattern[str], ...]


FACE_JOB_ID = r"JOB-[0-9a-f]{12}"
RENDER_JOB_ID = r"[0-9a-f]{32}"


def _patterns(*values: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(rf"^{value}$") for value in values)


def _service_url(env_name: str) -> str:
    return os.getenv(env_name, "").strip().rstrip("/")


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
        ),
    ),
}

MAX_BODY_BYTES = max(1024, int(os.getenv("AI_GATEWAY_MAX_BODY_BYTES", str(13 * 1024 * 1024))))
UPSTREAM_TIMEOUT_SECONDS = max(10, int(os.getenv("AI_GATEWAY_UPSTREAM_TIMEOUT_SECONDS", "600")))
MEMBER_DATABASE_URL = _service_url("MEMBER_DATABASE_URL")
SESSION_SECRET = os.getenv("GATEWAY_SESSION_SECRET", "")
SESSION_TTL_SECONDS = max(300, min(int(os.getenv("GATEWAY_SESSION_TTL_SECONDS", "7200")), 86400))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = max(60, int(os.getenv("GATEWAY_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "600")))
LOGIN_RATE_LIMIT_MAX_REQUESTS = max(1, int(os.getenv("GATEWAY_LOGIN_RATE_LIMIT_MAX_REQUESTS", "10")))
IS_PRODUCTION = os.getenv("APP_ENV", "").strip().lower() in {"prod", "production"}


def _validate_configuration() -> None:
    if not IS_PRODUCTION:
        return
    missing = []
    for name, upstream in UPSTREAMS.items():
        if not upstream.base_url:
            missing.append(f"{name}.base_url")
        if not upstream.api_key:
            missing.append(f"{name}.upstream_api_key")
        if not upstream.client_api_key:
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


def issue_access_token(email: str, role: str = "") -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + SESSION_TTL_SECONDS
    token = jwt.encode(
        {
            "iss": "decorate-me-ai-gateway",
            "aud": "decorate-me-ai",
            "sub": email.strip().lower(),
            "role": role[:64],
            "iat": now,
            "exp": expires_at,
        },
        SESSION_SECRET,
        algorithm="HS256",
    )
    return token, expires_at


def require_member_access(request: Request) -> dict:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
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


def build_upstream_headers(request: Request, upstream: Upstream, identity_token: str) -> dict[str, str]:
    headers = {
        "Accept": request.headers.get("accept", "application/json"),
        "X-Serverless-Authorization": f"Bearer {identity_token}",
        "X-API-Key": upstream.api_key,
        "X-Forwarded-For": client_ip(request),
    }
    content_type = request.headers.get("content-type")
    if content_type:
        headers["Content-Type"] = content_type
    result_token = request.headers.get("x-job-token")
    if result_token:
        headers["X-Job-Token"] = result_token
    return headers


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
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-API-Key", "X-Job-Token"],
    max_age=3600,
)


@app.get("/health")
async def health():
    configured = all(upstream.base_url for upstream in UPSTREAMS.values())
    return {
        "status": "ok" if configured else "degraded",
        "service": "ai-gateway",
        "privateUpstreamAuth": "cloud-run-iam",
        "memberAuth": "short-lived-access-token",
    }


@app.post("/auth/login")
async def login(body: LoginRequest, request: Request):
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
    access_token, expires_at = issue_access_token(verified_email, role)
    return {"accessToken": access_token, "expiresAt": expires_at, "tokenType": "Bearer"}


@app.api_route("/{service}/{path:path}", methods=["GET", "POST"])
async def proxy(service: str, path: str, request: Request):
    upstream = UPSTREAMS.get(service)
    if upstream is None or not is_path_allowed(upstream, path):
        raise HTTPException(status_code=404, detail={"error": {"code": "NOT_FOUND", "message": "Route not found."}})

    require_client_api_key(upstream, request.headers.get("x-api-key", ""))
    require_member_access(request)
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
        identity_token = await asyncio.to_thread(TOKEN_CACHE.get, upstream.base_url)
        response = await request.app.state.http_client.request(
            method=request.method,
            url=f"{upstream.base_url}/{path}",
            params=list(request.query_params.multi_items()),
            headers=build_upstream_headers(request, upstream, identity_token),
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
    return Response(content=response.content, status_code=response.status_code, headers=response_headers)


if __name__ == "__main__":
    from dev_server_utils import run_dev_server

    run_dev_server(app, "AI Gateway", "AI_GATEWAY", 8015)
