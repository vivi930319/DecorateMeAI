from datetime import date, datetime, timedelta
from datetime import timezone
from flask import Flask, url_for, flash, redirect, request, render_template, jsonify, session, make_response
from flask_cors import CORS
from flask_login import login_user, current_user, logout_user, login_required
from sqlalchemy.exc import IntegrityError, OperationalError
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException
from urllib.parse import urlparse
import config
import os
import math
import json
import time
import uuid
import hmac
import hashlib
import re
import secrets
import gzip
import threading
import shutil
import subprocess
from dotenv import load_dotenv
import redis
import base64
from redis.exceptions import RedisError

from extensions import db, bcrypt, login_manager
from models import (
    Members, Products, Favorites, ColorPalettes, Checkin,
    Blushes, Contouring, Eyebrows, EyelinerMascara,
    Eyeshadows, Foundations, Highlighters, Lipsticks, TryonRecords,
    AuditLog, AdminAuditLog, PointsTransaction, SavedLook,
    OTPCode, AnalysisHistory, DailyCheckin, TaskClaim,
    UnlockedTheme, Referral, CartItem, MemberSession, MemberDeletionJob,
    CrawlerStagingProduct,
    PendingRegistration
)
from forms import (
    RegistrationForm, LoginForm, ChangePasswordForm,
    ForgotPasswordRequestForm, ResetPasswordForm,
)
from otp_utils import generate_otp, redis_key, send_otp_email, attempt_key
from recommendation import (
    recommend_products, health_check, STYLE_FALLBACK_TAGS,
    hex_to_rgb, rgb_to_lab, delta_e,
)
from recommendation import AnalysisContractError
from crawler_preview import (
    CrawlerError, build_product_preview, preview_rate_limiter,
    public_product_url, sanitized_url,
)
from price_conversion import display_price, price_for_frontend
from product_image_mirror import mirrored_image_url
from shade_neighbors import (
    comparable_lab as _shade_comparable_lab,
    is_concealer as _is_concealer_product,
    is_eligible_candidate as _is_shade_match_candidate,
    shade_neighbor_index,
    shade_sort_key as _shade_sort_key,
)
from password_policy import password_policy_error

load_dotenv()

app = Flask(__name__)
# The service currently runs through a cost-saving tunnel in debug mode.  Do
# not let Flask's debug pretty-printer inflate large catalog responses.
app.json.compact = True


def _configured_origins():
    """Only the Gateway / explicitly configured frontends may use cookies."""
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "https://decorate-me.web.app,https://decorate-me.firebaseapp.com")
    return {origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()}


ALLOWED_ORIGINS = _configured_origins()
CORS(app, supports_credentials=True, origins=list(ALLOWED_ORIGINS))

# 收藏本身只保存短網址與 JSON 摘要，主要儲存成本在 GCS 圖片。
# 會員既有收藏已接近 100 筆；即使舊環境變數仍為 50，也不得再把使用者擋回
# localStorage 而產生不同步的幽靈收藏。200 筆是目前正式的帳號上限。
SAVED_LOOK_LIMIT = max(200, int(os.getenv("SAVED_LOOK_LIMIT", "200")))


def _runtime_secret(env_name, gcp_secret_name):
    """Read local tunnel credentials without committing plaintext secrets.

    Cloud Run supplies normal environment variables.  The cost-saving local
    service has the gcloud CLI but no managed secret injection, so it reads the
    same Secret Manager versions at process start.  Values are captured in
    memory and are never printed or written to `.env`.
    """
    configured = os.getenv(env_name)
    if configured:
        return configured
    if os.getenv("DISABLE_LOCAL_GCLOUD_SECRET_BOOTSTRAP", "false").casefold() in {"1", "true", "yes"}:
        return None
    gcloud = shutil.which("gcloud")
    if not gcloud:
        return None
    try:
        result = subprocess.run(
            [gcloud, "secrets", "versions", "access", "latest",
             f"--secret={gcp_secret_name}", "--project=decorate-me"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


# Gateway API keys for delegated member administration and product management.
GATEWAY_API_KEY = _runtime_secret("UPSTREAM_MEMBER_API_KEY", "decorate-me-member-upstream-key")
PRODUCT_ADMIN_API_KEY = _runtime_secret("PRODUCT_ADMIN_API_KEY", "product-admin-api-key")
# Public endpoints must be authenticated by the Gateway in production.  Local
# development can opt in to loose mode explicitly, never by default.
# The current Gateway authenticates normal member requests with its own session
# and forwards the member cookie; it does not attach X-Gateway-Key on /auth.
# Validate the header when present, but keep the upstream compatible until the
# Gateway contract is upgraded to send it for every request.
GATEWAY_KEY_LOOSE_MODE = os.getenv("GATEWAY_KEY_LOOSE_MODE", "true").lower() in ("1", "true", "yes")


class _GatewayAdminActor:
    """Non-PII service actor used only after both admin headers validate."""
    email = "gateway-admin@service.invalid"
    phone_number = "gateway-admin"
    status = "active"

    @staticmethod
    def member_role():
        return "admin"


GATEWAY_ADMIN_ACTOR = _GatewayAdminActor()


def _gateway_service_authenticated():
    """Return whether the request came from the configured trusted Gateway."""
    provided = request.headers.get("X-Gateway-Key", "")
    if not GATEWAY_API_KEY or not provided:
        return False
    return hmac.compare_digest(provided, GATEWAY_API_KEY)


def _gateway_admin_actor():
    """Authenticate Gateway-delegated admin operations.

    ``X-Admin-Request`` is never trusted by itself because a browser can forge
    it. The member service accepts it only alongside the configured shared
    Gateway key, compared in constant time. Loose-mode does not apply here.
    """
    if request.headers.get("X-Admin-Request", "").strip() != "1":
        return None
    return GATEWAY_ADMIN_ACTOR if _gateway_service_authenticated() else None


def _check_gateway_key():
    """Validate X-Gateway-Key on public endpoints.
    In loose mode: validate if present, but don't require (for safe rollout).
    In strict mode: require the key.
    """
    provided = request.headers.get("X-Gateway-Key", "")
    if not provided:
        if GATEWAY_KEY_LOOSE_MODE:
            return None  # Allow without key during transition
        return error_response("UNAUTHENTICATED", "缺少 Gateway 認證", 401)
    if not GATEWAY_API_KEY:
        # No key configured yet; allow in loose mode
        if GATEWAY_KEY_LOOSE_MODE:
            return None
        return error_response("UNAUTHENTICATED", "Gateway 認證未配置", 503)
    # Constant-time comparison
    if not hmac.compare_digest(provided, GATEWAY_API_KEY):
        return error_response("UNAUTHENTICATED", "Gateway 認證無效", 401)
    return None


# Public endpoints that require gateway key validation
PUBLIC_ENDPOINTS = frozenset({
    "/api/register", "/api/send-otp", "/api/verify-otp", "/api/login",
    "/api/forgot-password", "/api/reset-password",
    "/send-otp", "/verify-otp", "/register", "/login",
    "/forgot_password", "/reset_password",
})


@app.before_request
def _validate_gateway_key():
    """Check X-Gateway-Key on public endpoints before processing."""
    if request.method == "OPTIONS":
        return None  # Preflight handled separately
    if request.path in PUBLIC_ENDPOINTS or request.path.startswith("/api/"):
        # Only check for the specific public endpoints
        if request.path in PUBLIC_ENDPOINTS:
            return _check_gateway_key()
    return None


app.config.from_object(config)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['WTF_CSRF_CHECK_DEFAULT'] = False
app.config['SESSION_COOKIE_SAMESITE'] = 'None'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

# ========== PostgreSQL Session 系統 ==========
MEMBER_SESSION_COOKIE = 'member_session'
# 必須與 Gateway 的 GATEWAY_SESSION_TTL_SECONDS 一致，否則 Gateway 尚顯示登入中，
# 上游會員 Session 卻已過期，收藏妝容等寫入會在中途收到 HTTP 401。
SESSION_MAX_AGE = max(300, int(os.getenv("MEMBER_SESSION_TTL_SECONDS", "28800")))
MAX_SESSIONS_PER_SOURCE = 5  # 同裝置/來源最多同時並存 session 數

# 拋棄式/一次性 email 域名黑名單
DISPOSABLE_EMAIL_DOMAINS = frozenset({
    "mailinator.com", "10minutemail.com", "guerrillamail.com",
    "yopmail.com", "temp-mail.org", "throwaway.email",
    "maildrop.cc", "tempmail.net", "fakeinbox.com",
    "getnada.com", "mailnesia.com", "trashmail.com",
    "sharklasers.com", "guerrillamailblock.com", "spamgourmet.com",
    "mailinator2.com", "mytrashmail.com", "temporaryemail.com",
    "deadaddress.com", "mailinator.net", "meltmail.com",
    "spam.su", "keemail.me", "guerrillamail.org",
})

# Admin accounts that are allowed to bypass email domain validation
# (e.g., admin@decorateme.local uses a .local domain which has no MX record)
ADMIN_EMAIL_WHITELIST = frozenset({
    "admin@decorateme.local",
})


def _generate_session_token():
    return secrets.token_hex(32)


def _hash_session_token(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def _source_identifier():
    """Derive a source identifier from request metadata for session limiting."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "unknown"


def create_member_session(member):
    token = _generate_session_token()
    session_hash = _hash_session_token(token)
    session_id = secrets.token_hex(24)  # opaque, non-PII
    now = datetime.utcnow()
    source = _source_identifier()

    # Session count limiting: evict oldest if exceeding MAX_SESSIONS_PER_SOURCE
    existing = MemberSession.query.filter(
        MemberSession.member_id == member.phone_number,
        MemberSession.source_identifier == source,
        MemberSession.revoked_at == None,
        MemberSession.expires_at > now,
    ).order_by(MemberSession.created_at.asc()).all()
    if len(existing) >= MAX_SESSIONS_PER_SOURCE:
        for old in existing[:len(existing) - MAX_SESSIONS_PER_SOURCE + 1]:
            old.revoked_at = now
        db.session.flush()

    db.session.add(MemberSession(
        session_hash=session_hash,
        session_id=session_id,
        member_id=member.phone_number,
        created_at=now,
        expires_at=now + timedelta(seconds=SESSION_MAX_AGE),
        last_seen_at=now,
        session_version=member.session_version,
        source_identifier=source,
    ))
    db.session.commit()
    return token, session_id


def get_session_member():
    token = request.cookies.get(MEMBER_SESSION_COOKIE)
    if not token:
        return None
    session_hash = _hash_session_token(token)
    now = datetime.utcnow()
    session_record = MemberSession.query.filter_by(
        session_hash=session_hash, revoked_at=None
    ).filter(MemberSession.expires_at > now).first()
    if not session_record:
        return None
    session_record.last_seen_at = now
    db.session.commit()
    member = Members.query.get(session_record.member_id)
    if (not member or member.status in {"suspended", "deleted"}
            or session_record.session_version != member.session_version):
        return None
    return member


def revoke_member_session():
    """Revoke only the session identified by the current cookie (per-session logout)."""
    token = request.cookies.get(MEMBER_SESSION_COOKIE)
    if not token:
        return
    session_hash = _hash_session_token(token)
    MemberSession.query.filter_by(session_hash=session_hash, revoked_at=None).update(
        {"revoked_at": datetime.utcnow()}
    )
    db.session.commit()


def revoke_all_member_sessions(member):
    """Invalidate every cookie session and bearer token for this member."""
    member.session_version = (member.session_version or 0) + 1
    MemberSession.query.filter_by(member_id=member.phone_number, revoked_at=None).update(
        {"revoked_at": datetime.utcnow()}, synchronize_session=False
    )


redis_url = os.getenv("REDIS_URL")
UPLOAD_FOLDER = os.path.join('static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
if redis_url:
    r = redis.from_url(redis_url, decode_responses=True, protocol=2)
else:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True,
        protocol=2
    )
OTP_EXPIRE = int(os.getenv("OTP_EXPIRE_SECONDS", 300))
PENDING_REGISTRATION_EXPIRE = int(os.getenv("PENDING_REGISTRATION_EXPIRE_SECONDS", 1800))
OTP_SEND_WINDOW_SECONDS = int(os.getenv("OTP_SEND_WINDOW_SECONDS", 900))
OTP_SEND_MAX_ATTEMPTS = int(os.getenv("OTP_SEND_MAX_ATTEMPTS", 5))
OTP_VERIFIED_CODE = "VERIFIED"
OTP_VERIFIED_WINDOW_SECONDS = int(os.getenv("OTP_VERIFIED_WINDOW_SECONDS", 900))
TOKEN_ISSUER = os.getenv("JWT_ISSUER", "decorate-me-member-service")
TOKEN_EXPIRES_IN = int(os.getenv("JWT_EXPIRES_IN", 3600))
JWT_SECRET = os.getenv("JWT_SECRET") or config.SECRET_KEY
TAIPEI_TZ = timezone(timedelta(hours=8), name="Asia/Taipei")
ONE_TIME_TASK_DATE = date(1970, 1, 1)
DUMMY_PASSWORD_HASH = "$2b$12$x4PSgKnojHC83ovCBipftOEtntOhEG6DnIW.Tlqw1B9VmMfHQPKvG"

login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Members, user_id)


# ========== JWT ==========
def _b64url_encode(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(value):
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _json_b64url(data):
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _b64url_encode(raw)


def create_access_token(member):
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": TOKEN_ISSUER,
        "sub": member.email,
        "sv": member.session_version,
        "iat": now,
        "exp": now + TOKEN_EXPIRES_IN,
        "jti": str(uuid.uuid4()),
    }
    signing_input = f"{_json_b64url(header)}.{_json_b64url(payload)}"
    signature = hmac.new(
        JWT_SECRET.encode("utf-8"),
        signing_input.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{signing_input}.{_b64url_encode(signature)}"


def read_bearer_token(auth_header=None):
    auth_header = auth_header if auth_header is not None else request.headers.get("Authorization", "")
    if not auth_header:
        return None
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def verify_access_token(token):
    try:
        header_part, payload_part, signature_part = token.split(".", 2)
        signing_input = f"{header_part}.{payload_part}"
        expected_signature = hmac.new(
            JWT_SECRET.encode("utf-8"),
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        actual_signature = _b64url_decode(signature_part)
        if not hmac.compare_digest(expected_signature, actual_signature):
            return None, "INVALID_TOKEN"
        header = json.loads(_b64url_decode(header_part))
        payload = json.loads(_b64url_decode(payload_part))
        if header.get("alg") != "HS256":
            return None, "INVALID_TOKEN"
        if payload.get("iss") != TOKEN_ISSUER or not payload.get("sub"):
            return None, "INVALID_TOKEN"
        if int(payload.get("exp", 0)) < int(time.time()):
            return None, "TOKEN_EXPIRED"
        return payload, None
    except Exception:
        return None, "INVALID_TOKEN"


def member_from_bearer_token():
    token = read_bearer_token()
    if not token:
        return None, "AUTH_REQUIRED"
    claims, err = verify_access_token(token)
    if err:
        return None, err
    member = Members.query.filter_by(email=claims.get("sub", "").strip().lower()).first()
    if not member:
        return None, "AUTH_REQUIRED"
    if member.status in {"suspended", "deleted"}:
        return None, "ACCOUNT_SUSPENDED"
    if claims.get("sv") != member.session_version:
        return None, "AUTH_REQUIRED"
    return member, None


@login_manager.request_loader
def load_user_from_request(req):
    token = read_bearer_token(req.headers.get("Authorization", ""))
    if not token:
        return None
    claims, err = verify_access_token(token)
    if err:
        return None
    member = Members.query.filter_by(email=claims.get("sub", "").strip().lower()).first()
    if (not member or member.status in {"suspended", "deleted"}
            or claims.get("sv") != member.session_version):
        return None
    return member


# ========== Preflight / CORS ==========
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        origin = request.headers.get('Origin', '').rstrip('/')
        if origin not in ALLOWED_ORIGINS:
            return make_response("", 403)
        response = make_response("", 204)
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Cookie, X-Requested-With'
        response.headers['Access-Control-Max-Age'] = '86400'
        return response


@app.before_request
def protect_cookie_writes_from_csrf():
    """Cookie-authenticated writes must originate from an approved frontend."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    if not request.cookies.get(MEMBER_SESSION_COOKIE):
        return None
    origin = request.headers.get("Origin", "").rstrip("/")
    if not origin:
        referer = request.headers.get("Referer", "")
        parsed = urlparse(referer)
        origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/") if parsed.scheme and parsed.netloc else ""
    # Browser cross-site traffic always has an Origin or Sec-Fetch-Site marker.
    # Gateway-to-service requests intentionally have neither and must be allowed.
    fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
    if origin and origin not in ALLOWED_ORIGINS:
        return error_response("CSRF_ORIGIN_REJECTED", "請求來源不被允許", 403)
    if fetch_site == "cross-site" and origin not in ALLOWED_ORIGINS:
        return error_response("CSRF_ORIGIN_REJECTED", "請求來源不被允許", 403)
    return None


_last_registration_cleanup_at = 0.0


@app.before_request
def clean_expired_registration_data():
    """Bound retention of pending registrations and spent/expired registration OTPs."""
    global _last_registration_cleanup_at
    now_monotonic = time.monotonic()
    if now_monotonic - _last_registration_cleanup_at < 300:
        return None
    _last_registration_cleanup_at = now_monotonic
    try:
        now = datetime.utcnow()
        PendingRegistration.query.filter(PendingRegistration.expires_at <= now).delete(synchronize_session=False)
        OTPCode.query.filter(
            OTPCode.purpose == "registration", OTPCode.expires_at <= now
        ).delete(synchronize_session=False)
        db.session.commit()
    except Exception:
        db.session.rollback()
    return None


@app.after_request
def after_request(response):
    origin = request.headers.get('Origin', '')
    if origin.rstrip('/') in ALLOWED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, DELETE, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, Cookie, X-Requested-With'
        response.headers['Vary'] = 'Origin'
    if request.method == "GET" and request.path == "/api/products":
        response.headers["Cache-Control"] = "public, max-age=10, stale-while-revalidate=20"
    accepted_encoding = request.headers.get("Accept-Encoding", "").casefold()
    if ("gzip" in accepted_encoding and not response.direct_passthrough
            and response.status_code == 200 and response.is_json
            and not response.headers.get("Content-Encoding")):
        raw = response.get_data()
        if len(raw) >= 1024:
            compressed = gzip.compress(raw, compresslevel=5)
            if len(compressed) < len(raw):
                response.set_data(compressed)
                response.headers["Content-Encoding"] = "gzip"
                response.headers["Content-Length"] = str(len(compressed))
                vary = {value.strip() for value in response.headers.get("Vary", "").split(",") if value.strip()}
                vary.add("Accept-Encoding")
                response.headers["Vary"] = ", ".join(sorted(vary, key=str.casefold))
    return response


@app.errorhandler(HTTPException)
def api_http_error(error):
    if request.path.startswith("/api/"):
        return error_response(error.name.upper().replace(" ", "_"), "請求無法完成", error.code)
    return error


@app.errorhandler(Exception)
def api_unexpected_error(error):
    app.logger.exception("unhandled request error request_id=%s", request.headers.get("X-Request-ID", ""))
    if request.path.startswith("/api/"):
        return error_response("INTERNAL_ERROR", "系統暫時無法處理請求", 500)
    return "系統暫時無法處理請求", 500


# ========== 輔助函式 ==========
def member_profile_payload(member):
    return {
        "name": member.name,
        "email": member.email,
        "phone_number": member.phone_number,
        "age": member.age,
        "level": member.level_label(),
        "role": member.member_role(),
        "status": member.status or "active",
        "emailVerified": member.email_verified,
        # An administrator's authority comes from the server-side role, never
        # from a previously saved page checklist.  Old/incomplete
        # ``allowed_pages`` values must not hide admin features after login.
        "allowedPages": (
            _default_allowed_pages(member)
            if member.member_role() == "admin"
            else (member.allowed_pages or _default_allowed_pages(member))
        ),
        "vipRequested": member.vip_requested or False,
        "points": member.points or 0,
        "lifetime": member.lifetime_points or member.total_earned_points or 0,
        "renderQuota": {
            "dailyLimit": member.render_daily_limit,
            "remaining": member.render_remaining,
            "resetAt": member.render_reset_at.isoformat() if member.render_reset_at else None
        }
    }


def _default_allowed_pages(member):
    base_pages = ["dashboard", "analysisBasic", "style", "products", "favorites", "history", "compare", "suggestion",
                  "profile"]
    if member.member_role() == "admin":
        return base_pages + ["admin", "analysisPro", "unlimitedRender"]
    if member.level_label() == "VIP會員":
        return base_pages + ["analysisPro"]
    return base_pages


def member_level_label(level):
    return {"bronze": "一般會員", "silver": "VIP會員", "gold": "管理員"}.get(level, "一般會員")


def member_level_value(label):
    return {"一般會員": "bronze", "VIP會員": "silver", "管理員": "gold", "bronze": "bronze", "silver": "silver",
            "gold": "gold"}.get(label)


def member_role(member):
    return member.member_role()


def is_admin_member(member):
    return member is not None and member_role(member) == "admin"


def error_response(code, message, status_code, request_id=None, details=None):
    return jsonify({"success": False, "status": "error", "error": {
        "code": code, "message": message, "retryable": status_code >= 500,
        "details": details or {}, "requestId": request_id or f"req_{uuid.uuid4().hex}",
    }}), status_code


def require_admin():
    if _gateway_admin_actor() is not None:
        return None
    bearer_member = None
    bearer_error = None
    if read_bearer_token():
        bearer_member, bearer_error = member_from_bearer_token()
        if bearer_error == "ACCOUNT_SUSPENDED":
            return error_response("ACCOUNT_SUSPENDED", "帳號已停權", 403)
    session_member = get_session_member() if bearer_member is None else None
    member = bearer_member if bearer_member is not None else (
        session_member if session_member is not None else (
            current_user if current_user.is_authenticated else None
        )
    )
    if member is None:
        return error_response("UNAUTHENTICATED", "請先登入", 401)
    if getattr(member, "status", "active") in {"suspended", "deleted"}:
        return error_response("ACCOUNT_SUSPENDED", "帳號已停權", 403)
    if not is_admin_member(member):
        return error_response("ADMIN_REQUIRED", "需要管理員權限", 403)
    return None


def require_member_directory_admin():
    """Authorize the read-only member directory.

    The Gateway already rejects the bare member-list route for non-admin
    claims. Accepting its shared service credential here keeps that read path
    available if an older proxy revision omits ``X-Admin-Request``. All
    state-changing member routes continue to use ``require_admin`` and still
    require the explicit admin marker or a real administrator login.
    """
    if request.method == "GET" and _gateway_service_authenticated():
        return None
    return require_admin()


def require_product_audit_admin():
    """Accept the Gateway product-admin credential or an authenticated admin session."""
    token = read_bearer_token()
    if PRODUCT_ADMIN_API_KEY and token and hmac.compare_digest(token, PRODUCT_ADMIN_API_KEY):
        return None
    return require_admin()


def authenticated_member():
    gateway_actor = _gateway_admin_actor()
    if gateway_actor is not None:
        return gateway_actor, None
    if read_bearer_token():
        member, error = member_from_bearer_token()
        if error == "ACCOUNT_SUSPENDED":
            return None, error
        if member is not None:
            return member, None
    session_member = get_session_member()
    if session_member is not None:
        return session_member, None
    if current_user.is_authenticated:
        if getattr(current_user, "status", "active") in {"suspended", "deleted"}:
            return None, "AUTH_REQUIRED"
        return current_user, None
    return None, "AUTH_REQUIRED"


def require_actor():
    actor, auth_error = authenticated_member()
    if auth_error == "ACCOUNT_SUSPENDED":
        return None, error_response("ACCOUNT_SUSPENDED", "帳號已停權", 403)
    if actor is None:
        return None, error_response("UNAUTHENTICATED", "請先登入", 401)
    return actor, None


def require_self(actor, email):
    target_email = normalized_email(email)
    if not target_email:
        return None, error_response("INVALID_EMAIL", "Email 格式無效", 422)
    if actor.email.strip().lower() != target_email:
        return None, error_response("FORBIDDEN", "無權限", 403)
    return target_email, None


def require_self_or_admin(actor, email):
    target_email = normalized_email(email)
    if not target_email:
        return None, error_response("INVALID_EMAIL", "Email 格式無效", 422)
    if actor.email.strip().lower() != target_email and not is_admin_member(actor):
        return None, error_response("FORBIDDEN", "無權限", 403)
    return target_email, None


def normalized_email(value):
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return None
    return email


def _login_credentials_valid(member, password):
    """Run the same bcrypt work whether or not the account exists."""
    password_hash = member.password_hash if member is not None else DUMMY_PASSWORD_HASH
    valid = bcrypt.check_password_hash(password_hash, password or "")
    return member is not None and valid


def invalid_credentials_response():
    return jsonify({
        "error": {"code": "INVALID_CREDENTIALS", "message": "帳號或密碼錯誤"}
    }), 401


def _taipei_today():
    return datetime.now(TAIPEI_TZ).date()


def _opaque_actor(member):
    """Return an opaque, non-PII actor identifier for logging."""
    return "actor_" + hashlib.sha256(str(getattr(member, "email", "")).encode()).hexdigest()[:16]


def _is_disposable_email(email):
    """Check if email domain is a known disposable/temporary email provider."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip().lower()
    return domain in DISPOSABLE_EMAIL_DOMAINS


def _check_mx_record(email):
    """Verify that the domain is configured to receive email (not merely resolvable)."""
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].strip().lower()
    try:
        import dns.resolver
        return bool(dns.resolver.resolve(domain, "MX", lifetime=3))
    except Exception:
        return False


def validate_registration_email(email):
    """Accept real mail domains; the final proof is successful OTP verification."""
    email = normalized_email(email)
    if not email:
        return None, "INVALID_EMAIL", "Email 格式無效"
    if email in ADMIN_EMAIL_WHITELIST:
        return email, None, None
    if _is_disposable_email(email):
        return None, "DISPOSABLE_EMAIL", "不支援暫時性信箱"
    if not _check_mx_record(email):
        return None, "INVALID_DOMAIN", "Email 網域無法接收郵件"
    return email, None, None


def _create_pending_registration(phone, name, email, password, age):
    """Replace any expired/retried pending registration; never create a Member yet."""
    now = datetime.utcnow()
    PendingRegistration.query.filter(PendingRegistration.expires_at <= now).delete(synchronize_session=False)
    pending = PendingRegistration.query.filter_by(email=email).first()
    phone_owner = PendingRegistration.query.filter_by(phone_number=phone).first()
    if phone_owner is not None and phone_owner.email != email:
        raise ValueError("PHONE_PENDING")
    if pending is None:
        pending = PendingRegistration(email=email)
        db.session.add(pending)
    pending.phone_number = phone
    pending.name = name
    pending.password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
    pending.age = int(age)
    pending.expires_at = now + timedelta(seconds=PENDING_REGISTRATION_EXPIRE)
    db.session.commit()
    return pending


def _remove_legacy_unverified_member(member):
    """Release an account created by the old pre-verification registration flow."""
    email, phone = member.email, member.phone_number
    SavedLook.query.filter_by(member_email=email).delete(synchronize_session=False)
    Favorites.query.filter_by(member_id=phone).delete(synchronize_session=False)
    CartItem.query.filter_by(member_email=email).delete(synchronize_session=False)
    AnalysisHistory.query.filter_by(member_email=email).delete(synchronize_session=False)
    TryonRecords.query.filter_by(member_id=phone).delete(synchronize_session=False)
    Checkin.query.filter_by(member_id=phone).delete(synchronize_session=False)
    PointsTransaction.query.filter_by(member_email=email).delete(synchronize_session=False)
    DailyCheckin.query.filter_by(member_email=email).delete(synchronize_session=False)
    TaskClaim.query.filter_by(member_email=email).delete(synchronize_session=False)
    UnlockedTheme.query.filter_by(member_email=email).delete(synchronize_session=False)
    Referral.query.filter(
        (Referral.referrer_email == email) | (Referral.referred_email == email)
    ).delete(synchronize_session=False)
    MemberSession.query.filter_by(member_id=phone).delete(synchronize_session=False)
    OTPCode.query.filter_by(email=email).delete(synchronize_session=False)
    db.session.delete(member)


def _otp_rate_limit_key(email, purpose="registration"):
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
    safe_purpose = re.sub(r"[^a-z0-9_-]", "", str(purpose).casefold()) or "otp"
    return f"otp:send-rate:{safe_purpose}:{digest}"


def _allow_otp_send(email, purpose="registration"):
    """Limit OTP delivery without retaining addresses in Redis keys."""
    try:
        key = _otp_rate_limit_key(email, purpose)
        attempts = r.incr(key)
        if attempts == 1:
            r.expire(key, OTP_SEND_WINDOW_SECONDS)
        return attempts <= OTP_SEND_MAX_ATTEMPTS
    except RedisError:
        # Registration must not silently lose protection when Redis is down.
        return False


def log_audit(actor_email, target_email, action, field_name=None, before=None, after=None):
    try:
        log = AuditLog(
            actor_email="actor_" + hashlib.sha256(str(actor_email).encode()).hexdigest()[:16],
            target_email="target_" + hashlib.sha256(str(target_email).encode()).hexdigest()[:16],
            action=action,
            field_name=field_name,
            before_value=str(before) if before else None,
            after_value=str(after) if after else None
        )
        db.session.add(log)
        db.session.commit()
    except Exception:
        db.session.rollback()


def add_points_transaction(email, delta, reason, ref_id=None, note=None, commit=True):
    member = Members.query.filter_by(email=email).first()
    if not member:
        return None
    member.points = (member.points or 0) + delta
    if delta > 0:
        member.lifetime_points = (member.lifetime_points or 0) + delta
        member.total_earned_points = (member.total_earned_points or 0) + delta
    txn = PointsTransaction(
        member_email=email,
        delta=delta,
        balance_after=member.points,
        reason=reason,
        ref_id=ref_id,
        note=note
    )
    db.session.add(txn)
    if commit:
        db.session.commit()
    return member.points


# ========== 頁面路由 ==========
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/healthz')
def healthz():
    return jsonify({"status": "ok"})


@app.route('/health')
def health():
    return jsonify({
        "status": "ok",
        "service": request.args.get("service", "member-database")
    })


@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            email, code, message = validate_registration_email(form.email.data)
            if code:
                flash(message, 'danger')
                return render_template('register.html', title='註冊', form=form)
            existing = Members.query.filter_by(email=email).with_for_update().first()
            if existing:
                if existing.email_verified or existing.member_role() == "admin":
                    flash('此 Email 已被使用', 'danger')
                    return render_template('register.html', title='註冊', form=form)
                _remove_legacy_unverified_member(existing)
            if Members.query.filter_by(phone_number=form.phone_number.data).first():
                flash('此電話號碼已被使用', 'danger')
                return render_template('register.html', title='註冊', form=form)
            _create_pending_registration(
                form.phone_number.data, form.name.data, email,
                form.password.data, form.age.data,
            )
            sent, msg, _ = create_and_send_otp(email, purpose="registration")
            if not sent:
                flash('驗證碼寄送失敗，請稍後重新註冊', 'danger')
                return render_template('register.html', title='註冊', form=form)
            flash('驗證碼已寄出；完成驗證後才會建立會員帳號', 'success')
            return redirect(url_for('verify_email_page', email=email))
        except IntegrityError:
            db.session.rollback()
            flash('系統訊息', 'danger')
        except Exception:
            db.session.rollback()
            flash('系統訊息', 'danger')
    return render_template('register.html', title='閮餃?', form=form)


@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated and request.method == 'GET':
        if request.is_json:
            return jsonify({
                "success": True,
                "message": "已經是登入狀態",
                "member": member_profile_payload(current_user),
            }), 200
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        member = Members.query.filter_by(email=form.email.data.strip().lower()).first()
        if not _login_credentials_valid(member, form.password.data):
            flash('帳號或密碼錯誤', 'danger')
        elif member.status in {"suspended", "deleted"}:
            flash('帳號已停權', 'danger')
        elif not member.email_verified and member.member_role() != "admin":
            flash('請先完成 Email 驗證', 'danger')
        else:
            login_user(member)
            session.permanent = True
            next_page = request.args.get('next')
            flash('系統訊息', 'success')
            return redirect(next_page) if next_page else redirect(url_for('index'))
    if request.is_json:
        data = request.get_json(silent=True) or {}
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        if not email or not password:
            return jsonify({"success": False, "message": "請輸入電子郵件與密碼"}), 400
        member = Members.query.filter_by(email=email).first()
        if not _login_credentials_valid(member, password):
            return invalid_credentials_response()
        if member.status in {"suspended", "deleted"}:
            return error_response("ACCOUNT_SUSPENDED", "帳號已停權", 403)
        if not member.email_verified and member.member_role() != "admin":
            return error_response("EMAIL_NOT_VERIFIED", "請先完成 Email 驗證", 403)

        # 同時提供跨網域 Cookie Session 與 Bearer Token。
        session_token, session_id = create_member_session(member)
        access_token = create_access_token(member)

        # 設定 Cookie
        resp = make_response(jsonify({
            "success": True,
            "member": member_profile_payload(member),
            "profile": member_profile_payload(member),
            "accessToken": access_token,
            "tokenType": "Bearer",
            "sessionId": session_id,
            "expiresIn": TOKEN_EXPIRES_IN,
        }))

        resp.set_cookie(
            MEMBER_SESSION_COOKIE,
            value=session_token,
            max_age=SESSION_MAX_AGE,
            path='/',
            httponly=True,
            secure=True,
            samesite='None'
        )

        return resp, 200

    # 如果是 JSON 請求但驗證失敗，回傳 JSON
    if request.is_json:
        return error_response("INVALID_CREDENTIALS", "登入失敗", 401)

    return render_template('login.html', title='登入', form=form)


# ========== OTP ==========
def _request_password_reset_otp(email):
    """Issue a reset OTP only for an existing, usable account."""
    member = Members.query.filter_by(email=email).first()
    if member is None:
        return False, "EMAIL_NOT_REGISTERED", "此電子郵件尚未註冊，請確認信箱後再試", 404
    if not member.email_verified and member.member_role() != "admin":
        return False, "EMAIL_NOT_VERIFIED", "此帳號尚未完成電子郵件驗證，請先完成註冊驗證", 403
    if member.status in {"suspended", "deleted"}:
        return False, "ACCOUNT_UNAVAILABLE", "此帳號目前無法重設密碼，請聯絡管理員", 403
    try:
        ttl = r.ttl(redis_key(email))
        if ttl != -2 and ttl > (OTP_EXPIRE - 60):
            return True, "OTP_ALREADY_SENT", "驗證碼已寄出，請先檢查收件匣或垃圾郵件；60 秒後可重新申請", 200
        if not _allow_otp_send(email, purpose="password_reset"):
            return False, "OTP_RATE_LIMITED", "驗證碼申請次數過多，請稍後再試", 429
        otp = generate_otp()
        r.set(redis_key(email), bcrypt.generate_password_hash(otp).decode("utf-8"), ex=OTP_EXPIRE)
        r.delete(attempt_key(email))
        send_otp_email(email, otp, OTP_EXPIRE)
        return True, "OTP_SENT", "驗證碼已寄出，請於 5 分鐘內完成密碼重設", 200
    except RedisError:
        app.logger.exception("forgot-password Redis operation failed")
        return False, "OTP_SERVICE_UNAVAILABLE", "驗證碼服務暫時無法使用，請稍後再試", 503
    except Exception:
        try:
            r.delete(redis_key(email))
        except RedisError:
            pass
        app.logger.exception("forgot-password email delivery failed")
        return False, "OTP_SEND_FAILED", "驗證碼寄送失敗，請確認信箱或稍後再試", 502


def _reset_password_with_otp(email, otp, new_password):
    """Validate one reset OTP and update the password using the shared policy."""
    policy_error = password_policy_error(new_password)
    if policy_error:
        return False, "INVALID_PASSWORD", policy_error, 422
    member = Members.query.filter_by(email=email).first()
    if member is None:
        return False, "EMAIL_NOT_REGISTERED", "此電子郵件尚未註冊", 404
    try:
        stored = r.get(redis_key(email))
        if stored is None:
            return False, "OTP_EXPIRED", "驗證碼不存在或已過期，請重新申請", 410
        attempts = r.incr(attempt_key(email))
        r.expire(attempt_key(email), OTP_EXPIRE)
        if attempts > 5:
            r.delete(redis_key(email))
            r.delete(attempt_key(email))
            return False, "OTP_TOO_MANY_ATTEMPTS", "驗證碼錯誤次數過多，請重新申請", 429
        if not bcrypt.check_password_hash(stored, otp):
            return False, "OTP_INVALID", "驗證碼不正確，請重新輸入", 400
        member.password = new_password
        revoke_all_member_sessions(member)
        db.session.commit()
        try:
            r.delete(redis_key(email))
            r.delete(attempt_key(email))
        except RedisError:
            # The password is already committed.  Cleanup failure must not
            # make the user think the reset failed; the OTP still expires.
            app.logger.warning("reset-password succeeded but OTP cleanup failed")
        return True, "PASSWORD_RESET", "密碼已重設，請使用新密碼登入", 200
    except RedisError:
        db.session.rollback()
        app.logger.exception("reset-password Redis operation failed")
        return False, "OTP_SERVICE_UNAVAILABLE", "驗證碼服務暫時無法使用，請稍後再試", 503
    except Exception:
        db.session.rollback()
        app.logger.exception("reset-password failed")
        return False, "PASSWORD_RESET_FAILED", "密碼重設失敗，請稍後再試", 500


@app.route("/forgot_password", methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordRequestForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        success, code, message, _ = _request_password_reset_otp(email)
        flash(message, 'success' if code == "OTP_SENT" else ('warning' if success else 'danger'))
        if success:
            return redirect(url_for('reset_password', email=email))
    return render_template('forgot_password.html', title='忘記密碼', form=form)


@app.route("/reset_password", methods=['GET', 'POST'])
def reset_password():
    form = ResetPasswordForm()
    if request.method == 'GET':
        prefill_email = request.args.get('email', '').strip().lower()
        if prefill_email:
            form.email.data = prefill_email
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        otp = form.otp.data.strip()
        success, code, message, _ = _reset_password_with_otp(email, otp, form.new_password.data)
        flash(message, 'success' if success else 'danger')
        if success:
            return redirect(url_for('login'))
        if code in {"OTP_EXPIRED", "OTP_TOO_MANY_ATTEMPTS"}:
            return redirect(url_for('forgot_password'))
    return render_template('reset_password.html', title='重設密碼', form=form)


@app.route("/api/forgot-password", methods=["POST"])
def api_forgot_password():
    data = request.get_json(silent=True) or {}
    email = normalized_email(data.get("email"))
    if not email:
        return error_response("INVALID_EMAIL", "Email 格式不正確", 400)
    success, code, message, status = _request_password_reset_otp(email)
    if not success:
        return error_response(code, message, status)
    return jsonify({
        "success": True,
        "code": code,
        "message": message,
        "otpSent": code == "OTP_SENT",
        "expiresIn": OTP_EXPIRE,
        "resendAfter": 60,
        "passwordPolicy": {"minLength": 6, "maxLength": 128},
    }), status


@app.route("/api/reset-password", methods=["POST"])
def api_reset_password():
    data = request.get_json(silent=True) or {}
    email = normalized_email(data.get("email"))
    otp = data.get("otp")
    new_password = data.get("newPassword", data.get("new_password"))
    confirmation = data.get("confirmPassword", data.get("confirm_password"))
    if not email:
        return error_response("INVALID_EMAIL", "Email 格式不正確", 400)
    if not isinstance(otp, str) or not re.fullmatch(r"\d{6}", otp.strip()):
        return error_response("OTP_INVALID", "驗證碼固定為 6 位數字", 400)
    if confirmation is not None and confirmation != new_password:
        return error_response("PASSWORD_MISMATCH", "兩次輸入的新密碼不一致", 422)
    success, code, message, status = _reset_password_with_otp(email, otp.strip(), new_password)
    if not success:
        return error_response(code, message, status)
    return jsonify({"success": True, "code": code, "message": message}), status


@app.route("/api/change-password", methods=["POST"])
def api_change_password():
    """Change the signed-in member's password and revoke every old session."""
    actor, err = require_actor()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    current_password = data.get(
        "currentPassword", data.get("current_password", data.get("oldPassword"))
    )
    new_password = data.get("newPassword", data.get("new_password"))
    confirmation = data.get("confirmPassword", data.get("confirm_password"))

    if not isinstance(current_password, str) or not current_password:
        return error_response("CURRENT_PASSWORD_REQUIRED", "請輸入目前密碼", 400)
    if confirmation is not None and confirmation != new_password:
        return error_response("PASSWORD_MISMATCH", "兩次輸入的新密碼不一致", 422)
    policy_error = password_policy_error(new_password)
    if policy_error:
        return error_response("INVALID_PASSWORD", policy_error, 422)
    if not actor.verify_password(current_password):
        return error_response("CURRENT_PASSWORD_INCORRECT", "目前密碼不正確", 401)
    if actor.verify_password(new_password):
        return error_response("PASSWORD_UNCHANGED", "新密碼不可與目前密碼相同", 422)

    try:
        actor.password = new_password
        revoke_all_member_sessions(actor)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("authenticated password change failed")
        return error_response("PASSWORD_CHANGE_FAILED", "密碼變更失敗，請稍後再試", 500)

    response = make_response(jsonify({
        "success": True,
        "code": "PASSWORD_CHANGED",
        "message": "密碼已更新，請使用新密碼重新登入",
        "logoutRequired": True,
    }), 200)
    response.delete_cookie(MEMBER_SESSION_COOKIE, path="/")
    return response


@app.route("/change_password", methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        member = current_user
        if member.verify_password(form.old_password.data):
            member.password = form.new_password.data
            revoke_all_member_sessions(member)
            db.session.commit()
            flash('系統訊息', 'success')
            return redirect(url_for('profile'))
        else:
            flash('系統訊息', 'danger')
    return render_template('change_password.html', title='?湔撖Ⅳ', form=form)


def email_has_verified_otp(email):
    now = datetime.utcnow()
    return OTPCode.query.filter(
        OTPCode.email == email,
        OTPCode.purpose == "email_verified",
        OTPCode.verified_at.isnot(None),
        OTPCode.expires_at > now,
    ).order_by(OTPCode.created_at.desc()).first() is not None


def create_and_send_otp(email, purpose="registration"):
    email = normalized_email(email)
    if not email:
        return False, "Email 不得為空", 400
    if purpose == "registration" and not _allow_otp_send(email, purpose="registration"):
        return False, "驗證碼發送過於頻繁，請稍後再試", 429
    now = datetime.utcnow()
    # Invalidate any existing unused OTPs for this email
    OTPCode.query.filter(
        OTPCode.email == email,
        OTPCode.purpose == purpose,
        OTPCode.expires_at > now,
    ).update({"expires_at": now}, synchronize_session=False)
    otp = generate_otp()
    otp_record = OTPCode(
        email=email,
        code_hash=bcrypt.generate_password_hash(otp).decode("utf-8"),
        purpose=purpose,
        expires_at=now + timedelta(seconds=OTP_EXPIRE),
        attempts=0,
    )
    db.session.add(otp_record)
    db.session.commit()
    try:
        send_otp_email(email, otp, OTP_EXPIRE)
        return True, "驗證碼已寄出", 200
    except Exception:
        # Keep an error response free of recipient address and SMTP details.
        return False, "驗證碼暫時無法寄送", 502


@app.route("/send-otp", methods=["POST"])
@app.route("/api/send-otp", methods=["POST"])
def send_otp():
    data = request.get_json(silent=True) or {}
    email = normalized_email(data.get("email"))
    if not email:
        return error_response("INVALID_EMAIL", "Email 必須為格式正確的字串", 400)
    email, code, message = validate_registration_email(email)
    if code:
        return error_response(code, message, 400)
    if not PendingRegistration.query.filter_by(email=email).first():
        return error_response("REGISTRATION_NOT_PENDING", "請先提交註冊資料", 409)
    success, message, status_code = create_and_send_otp(email, purpose="registration")
    if not success:
        return error_response("OTP_SEND_FAILED", message, status_code)
    return jsonify({"success": success, "message": message}), status_code


@app.route("/verify-otp", methods=["POST"])
@app.route("/api/verify-otp", methods=["POST"])
def verify_otp():
    data = request.get_json(silent=True) or {}
    email = normalized_email(data.get("email"))
    raw_otp = data.get("otp", data.get("code"))
    if not email:
        return error_response("INVALID_EMAIL", "Email 必須為格式正確的字串", 400)
    if not isinstance(raw_otp, str) or not raw_otp.strip():
        return error_response("OTP_INVALID", "驗證碼格式不正確", 400)
    otp = raw_otp.strip()
    if not re.fullmatch(r"\d{6}", otp):
        return error_response("OTP_INVALID", "驗證碼格式不正確", 400)
    now = datetime.utcnow()
    record = OTPCode.query.filter(
        OTPCode.email == email,
        OTPCode.purpose == "registration",
        OTPCode.expires_at > now,
        OTPCode.attempts < 5
    ).order_by(OTPCode.created_at.desc()).first()
    if not record:
        # The current frontend uses the shared verify-otp step for both
        # registration and password reset. Registration OTPs live in
        # PostgreSQL, while password-reset OTPs live in Redis. Fall back to
        # the reset store only when no active registration OTP exists.
        try:
            stored_reset_otp = r.get(redis_key(email))
            reset_member = Members.query.filter_by(email=email).first()
            if stored_reset_otp is not None and reset_member is not None:
                reset_attempts = r.incr(attempt_key(email))
                r.expire(attempt_key(email), OTP_EXPIRE)
                if reset_attempts > 5:
                    r.delete(redis_key(email))
                    r.delete(attempt_key(email))
                    return error_response(
                        "OTP_TOO_MANY_ATTEMPTS",
                        "驗證碼錯誤次數過多，請重新申請",
                        429,
                    )
                if not bcrypt.check_password_hash(stored_reset_otp, otp):
                    return error_response("OTP_INVALID", "驗證碼不正確，請重新輸入", 400)
                return jsonify({
                    "success": True,
                    "message": "OTP 驗證成功，請設定新密碼",
                    "otpVerified": True,
                    "purpose": "password_reset",
                    "registrationCompleted": False,
                }), 200
        except RedisError:
            app.logger.exception("verify password-reset OTP Redis operation failed")
            return error_response(
                "OTP_SERVICE_UNAVAILABLE",
                "驗證碼服務暫時無法使用，請稍後再試",
                503,
            )
        return error_response("OTP_EXPIRED", "驗證碼不存在或已逾時", 400)
    record.attempts += 1
    db.session.commit()
    if not bcrypt.check_password_hash(record.code_hash, otp):
        if record.attempts >= 5:
            # Invalidate the code after too many attempts
            record.expires_at = now
            db.session.commit()
            return error_response("OTP_TOO_MANY_ATTEMPTS", "驗證碼嘗試次數過多，請重新發送", 429)
        return error_response("OTP_INVALID", "驗證碼錯誤", 400)
    pending = PendingRegistration.query.filter_by(email=email).with_for_update().first()
    if not pending or pending.expires_at <= now:
        record.expires_at = now
        db.session.commit()
        return error_response("REGISTRATION_EXPIRED", "註冊資料已逾時，請重新註冊", 409)
    if Members.query.filter_by(email=email).first() or Members.query.filter_by(
            phone_number=pending.phone_number).first():
        return error_response("ACCOUNT_EXISTS", "帳號已存在，請登入", 409)
    member = Members(
        phone_number=pending.phone_number,
        name=pending.name,
        email=pending.email,
        password_hash=pending.password_hash,
        age=pending.age,
        level="bronze", role="member", points=0,
        render_daily_limit=3, render_remaining=3,
        email_verified=True, email_verified_at=now,
    )
    record.attempts = 5
    record.verified_at = now
    record.expires_at = now
    db.session.add(member)
    db.session.delete(pending)
    db.session.commit()
    return jsonify({
        "success": True,
        "message": "OTP 驗證成功",
        "emailVerified": True,
        "registrationCompleted": True,
    }), 200


@app.route("/verify-email")
def verify_email_page():
    return render_template(
        "verify_email.html",
        email=request.args.get("email", "").strip().lower(),
        next_url=request.args.get("next", ""),
    )


# ========== [Gateway API] 會員登入（使用 PostgreSQL Session） ==========
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    email = normalized_email(data.get('email'))
    password = data.get('password') or ''
    if not email:
        return error_response("INVALID_EMAIL", "Email 格式不正確", 400)
    if not isinstance(password, str) or not password:
        return error_response("MISSING_CREDENTIALS", "缺少帳號或密碼", 400)

    member = Members.query.filter_by(email=email).first()
    if not _login_credentials_valid(member, password):
        return invalid_credentials_response()
    if member.status in {"suspended", "deleted"}:
        return error_response("ACCOUNT_SUSPENDED", "帳號已停權", 403)
    # Admins bypass email verification; all other accounts must have email_verified=true
    if not member.email_verified and member.member_role() != "admin":
        return jsonify({
            "success": False,
            "error": {"code": "EMAIL_NOT_VERIFIED", "message": "請先完成 Email 驗證"},
            "member": member_profile_payload(member),
        }), 403

    # 同時提供跨網域 Cookie Session 與 Bearer Token。
    session_token, session_id = create_member_session(member)
    access_token = create_access_token(member)

    # 設定 Cookie
    resp = make_response(jsonify({
        "success": True,
        "member": member_profile_payload(member),
        "profile": member_profile_payload(member),
        "accessToken": access_token,
        "tokenType": "Bearer",
        "sessionId": session_id,
        "expiresIn": TOKEN_EXPIRES_IN,
    }))

    resp.set_cookie(
        MEMBER_SESSION_COOKIE,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        path='/',
        httponly=True,
        secure=True,
        samesite='None'
    )

    return resp, 200


# ========== [Gateway API] 會員登出 ==========
@app.route('/api/logout', methods=['POST'])
def api_logout():
    actor, _ = authenticated_member()
    if actor:
        revoke_all_member_sessions(actor)
        db.session.commit()
    else:
        revoke_member_session()
    resp = make_response(jsonify({"success": True, "message": "已登出"}))
    resp.delete_cookie(MEMBER_SESSION_COOKIE, path='/')
    return resp, 200


# ========== [Gateway API] 用 Session Cookie 讀取會員資料 ==========
@app.route('/api/me', methods=['GET'])
def get_my_profile_api():
    """Preferred profile endpoint: identity always comes from the session."""
    actor, err = require_actor()
    if err:
        return err
    return jsonify({"member": member_profile_payload(actor), "profile": member_profile_payload(actor)}), 200


@app.route('/api/members/<path:email>', methods=['GET'])
def get_member_api(email):
    """Gateway 用登入取得的 Cookie 驗證並讀取會員資料"""
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    return jsonify({
        "member": member_profile_payload(actor),
        "profile": member_profile_payload(actor),
    }), 200


# ========== 其他 API 註冊 ==========
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    raw_phone = data.get('phone_number')
    raw_name = data.get('name')
    phone = raw_phone.strip() if isinstance(raw_phone, str) else ''
    name = raw_name.strip() if isinstance(raw_name, str) else ''
    email = normalized_email(data.get('email'))
    password = data.get('password') or ''
    age = data.get('age')
    if not email:
        return error_response("INVALID_EMAIL", "Email 格式不正確", 400)
    if not isinstance(password, str) or not all([phone, name, password]) or age is None:
        return error_response("MISSING_FIELDS", "缺少必填欄位", 400)
    policy_error = password_policy_error(password)
    if policy_error:
        return error_response("INVALID_PASSWORD", policy_error, 422)
    email, error_code, error_message = validate_registration_email(email)
    if error_code:
        return error_response(error_code, error_message, 400)
    existing = Members.query.filter_by(email=email).with_for_update().first()
    if existing:
        if existing.email_verified or existing.member_role() == "admin":
            return error_response("EMAIL_EXISTS", "Email 已被使用", 409)
        _remove_legacy_unverified_member(existing)
    if Members.query.filter_by(phone_number=phone).first():
        return error_response("PHONE_EXISTS", "電話號碼已被使用", 409)
    try:
        _create_pending_registration(phone, name, email, password, int(age))
        otp_sent, otp_message, _ = create_and_send_otp(email, purpose="registration")
        if not otp_sent:
            return jsonify({
                "success": False,
                "message": "註冊尚未完成，驗證碼寄送失敗，請稍後重試",
                "otpSent": False,
            }), 502
        return jsonify({
            "success": True,
            "message": "驗證碼已寄出；完成驗證後才會建立會員帳號",
            "otpSent": True,
            "registrationPending": True,
        }), 202
    except ValueError as exc:
        db.session.rollback()
        if str(exc) == "PHONE_PENDING":
            return error_response(
                "PHONE_PENDING",
                "此電話號碼已有尚未完成的註冊流程，請使用原信箱完成驗證或稍後再試",
                409,
            )
        return error_response("INVALID_AGE", "年齡格式無效", 400)
    except TypeError:
        db.session.rollback()
        return error_response("INVALID_AGE", "年齡格式無效", 400)
    except Exception:
        db.session.rollback()
        app.logger.exception("registration transaction failed")
        return error_response("REGISTER_FAILED", "註冊失敗", 500)


# ========== 收藏 ==========
@app.route('/api/favorites/toggle', methods=['POST'])
def toggle_favorite():
    actor, err = require_actor()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    i_id = data.get('item_id')
    i_type = data.get('item_type')
    if not i_id or not i_type:
        return jsonify({"status": "error", "message": "缺少 item_id 或 item_type"}), 400
    fav = Favorites.query.filter_by(member_id=actor.phone_number, item_id=i_id, item_type=i_type).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({"status": "removed", "message": "已取消收藏"})
    else:
        try:
            new_fav = Favorites(member_id=actor.phone_number, item_id=i_id, item_type=i_type)
            db.session.add(new_fav)
            db.session.commit()
            return jsonify({"status": "added", "message": "已加入收藏"})
        except IntegrityError:
            db.session.rollback()
            return jsonify({"status": "error", "message": "加入收藏失敗"}), 400


@app.route('/favorites')
@login_required
def favorites_page():
    favs = Favorites.query.filter_by(member_id=current_user.phone_number).all()
    model_mapping = {
        'lipsticks': Lipsticks, 'blushes': Blushes, 'contouring': Contouring,
        'eyebrows': Eyebrows, 'eyeliner_mascara': EyelinerMascara,
        'eyeshadows': Eyeshadows, 'foundations': Foundations,
        'highlighters': Highlighters, 'products': Products
    }
    product_list = []
    for f in favs:
        model_class = model_mapping.get(f.item_type)
        if model_class:
            item = model_class.query.get(f.item_id)
            if item:
                item_vector = getattr(item, 'qdrant_vector_12d', None) or getattr(item, 'color_vector', None) or []
                frontend_price = _price_for_frontend(
                    getattr(item, 'price', None), getattr(item, 'currency', 'TWD')
                )
                product_list.append({
                    "id": f.item_id, "type": f.item_type,
                    "name": getattr(item, 'name', '?芰??'),
                    "brand": getattr(item, 'brand', ''),
                    "price": frontend_price["display"],
                    "priceValue": frontend_price["amount"],
                    "currency": frontend_price["currency"],
                    "priceConverted": frontend_price["converted"],
                    "priceNote": frontend_price["note"],
                    "priceConversion": frontend_price["conversion"],
                    "image_url": mirrored_image_url(
                        getattr(item, 'image_webp_url', '') or getattr(item, 'image_url', '')),
                    "desc": getattr(item, "description", None) or "憓溶憟賣除?莎?靽桅ˇ?頛芸?",
                    "hex": getattr(item, "hex_primary", None) or "#E8A0B4",
                    "lab": getattr(item, 'lab', None) or {},
                    "vector": item_vector, "salepage": getattr(item, 'sale_page_id', '')
                })
    return render_template('favorites.html', favorites=product_list)


@app.route('/api/members/<phone>/favorites', methods=['GET'])
def get_user_favorites(phone):
    actor, err = require_actor()
    if err:
        return err
    if actor.phone_number != phone and not is_admin_member(actor):
        return error_response("FORBIDDEN", "無權限", 403)
    favs = Favorites.query.filter_by(member_id=phone).all()
    model_mapping = {
        'lipsticks': Lipsticks, 'blushes': Blushes, 'contouring': Contouring,
        'eyebrows': Eyebrows, 'eyeliner_mascara': EyelinerMascara,
        'eyeshadows': Eyeshadows, 'foundations': Foundations,
        'highlighters': Highlighters, 'products': Products
    }
    available_sources, _ = _catalog_availability_sets(_catalog_rows())
    product_list = []
    for f in favs:
        model_class = model_mapping.get(f.item_type)
        unavailable = (str(f.item_type), int(f.item_id)) not in available_sources
        if model_class:
            item = model_class.query.get(f.item_id)
            if item:
                item_vector = getattr(item, 'qdrant_vector_12d', None) or getattr(item, 'color_vector', None) or []
                frontend_price = _price_for_frontend(
                    getattr(item, 'price', None), getattr(item, 'currency', 'TWD')
                )
                product_list.append({
                    "id": f.item_id, "type": f.item_type,
                    "name": getattr(item, 'name', getattr(item, 'product_name', '?芰??')),
                    "brand": getattr(item, 'brand', ''),
                    "price": frontend_price["display"],
                    "priceValue": frontend_price["amount"],
                    "currency": frontend_price["currency"],
                    "priceConverted": frontend_price["converted"],
                    "priceNote": frontend_price["note"],
                    "priceConversion": frontend_price["conversion"],
                    "image_url": mirrored_image_url(
                        getattr(item, 'image_webp_url', '') or getattr(item, 'image_url', '')),
                    "description": getattr(item, 'description', '?怎?膩'),
                    "desc": getattr(item, "description", None) or "憓溶憟賣除?莎?靽桅ˇ?頛芸?",
                    "hex": getattr(item, "hex_primary", None) or "#E8A0B4",
                    "lab": getattr(item, 'lab', None) or {},
                    "vector": item_vector, "salepage": getattr(item, 'sale_page_id', ''),
                    "item_id": f.item_id, "item_type": f.item_type, "unavailable": unavailable,
                })
                continue
        product_list.append({
            "id": f.item_id, "type": f.item_type,
            "item_id": f.item_id, "item_type": f.item_type,
            "name": "此商品已下架", "unavailable": True,
        })
    return jsonify({"favorites": product_list})


# ========== 簽到 ==========
@app.route('/api/checkins', methods=['POST'])
def add_checkin():
    actor, err = require_actor()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    note = data.get('note', '')
    today = date.today()
    exists = Checkin.query.filter(
        Checkin.member_id == actor.phone_number,
        db.func.date(Checkin.checkin_time) == today
    ).first()
    if exists:
        return jsonify({"message": "今天已經簽到過"}), 400
    new_checkin = Checkin(member_id=actor.phone_number, note=note)
    db.session.add(new_checkin)
    points = add_points_transaction(actor.email, 10, "check_in", commit=False)
    db.session.commit()
    return jsonify({
        "message": "簽到成功", "points_earned": 10, "balance": points,
        "checkin_time": new_checkin.checkin_time.isoformat() if new_checkin.checkin_time else None
    })


# ========== 試妝 ==========
@app.route('/api/tryon/save', methods=['POST'])
def save_tryon_record():
    actor, err = require_actor()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    i_id = data.get('item_id')
    i_type = data.get('item_type')
    orig_img = data.get('original_image_url')
    gen_img = data.get('generated_image_url')
    advice = data.get('makeup_advice')
    if not all([i_id, i_type, orig_img, gen_img]):
        return jsonify({"status": "error", "message": "缺少必要欄位"}), 400
    try:
        new_record = TryonRecords(
            member_id=actor.phone_number, item_id=i_id, item_type=i_type,
            original_image_url=orig_img, generated_image_url=gen_img, makeup_advice=advice
        )
        db.session.add(new_record)
        db.session.commit()
        return jsonify({"status": "success", "message": "試妝紀錄已儲存"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"儲存失敗：{e}"}), 500


@app.route('/tryon-history')
@login_required
def tryon_history():
    records = TryonRecords.query.filter_by(member_id=current_user.phone_number).order_by(
        TryonRecords.created_at.desc()).all()
    return render_template('history.html', title='我的試妝紀錄', records=records)


@app.route("/logout")
def logout():
    if current_user.is_authenticated:
        revoke_all_member_sessions(current_user)
        db.session.commit()
    logout_user()
    flash('系統訊息', 'info')
    return redirect(url_for('index'))


@app.route("/profile")
@login_required
def profile():
    return render_template('profile.html', title='會員中心')


# ========== Admin 頁面 ==========
@app.route('/admin')
def admin_dashboard():
    admin_err = require_admin()
    if admin_err:
        return admin_err
    return render_template('admin_dashboard.html', title='管理員後台')


# ========== 管理員 API ==========
@app.route('/api/members', methods=['GET'])
def get_members_api():
    admin_err = require_member_directory_admin()
    if admin_err:
        return admin_err
    members = Members.query.filter(Members.status != "deleted").all()
    return jsonify({"members": [member_profile_payload(m) for m in members]})


@app.route('/api/admin/product-audit-logs', methods=['GET'])
def get_product_audit_logs():
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    try:
        limit = int(request.args.get("limit", 100))
    except (TypeError, ValueError):
        return error_response("INVALID_LIMIT", "limit 必須是整數", 400)
    limit = max(1, min(limit, 100))
    rows = db.session.execute(db.text("""
        SELECT id, product_id, product_type, action, before_data, after_data,
               request_id, created_at
        FROM product_audit_logs
        ORDER BY created_at DESC, id DESC
        LIMIT :limit
    """), {"limit": limit}).mappings().all()
    return jsonify({"items": [{
        "id": str(row["id"]),
        "productId": row["product_id"],
        "productType": row["product_type"],
        "action": row["action"],
        "beforeData": row["before_data"],
        "afterData": row["after_data"],
        "requestId": row["request_id"],
        "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
    } for row in rows]}), 200


def _staging_product_payload(item):
    return {
        "id": item.id,
        "sourceSite": item.source_site,
        "sourceProductId": item.source_product_id,
        "sourceUrl": item.source_url,
        "name": item.name,
        "price": float(item.price) if item.price is not None else None,
        "currency": item.currency,
        "description": item.description,
        "category": item.category,
        "imageUrl": item.image_url,
        "imageUrls": item.image_urls or {},
        "shades": item.shades or [],
        "status": item.status,
        "validationError": ({"code": item.validation_error_code, "message": item.validation_error_message}
                            if item.validation_error_code else None),
        "crawledAt": item.crawled_at.isoformat() if item.crawled_at else None,
        "reviewedAt": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "importedProductId": item.imported_product_id,
    }


def _staging_import_validation(item):
    name = (item.name or "").strip()
    if not name or len(name) > 255:
        return "INVALID_NAME", "商品名稱無效"
    if item.price is None or item.price < 0 or item.price > 99999999.99:
        return "INVALID_PRICE", "商品價格無效"
    image_url = (item.image_url or (item.image_urls or {}).get("width640") or "").strip()
    parsed = urlparse(image_url)
    if parsed.scheme != "https" or not parsed.netloc:
        return "INVALID_IMAGE_URL", "商品圖片網址必須是 HTTPS"
    category = cat_to_product_category(item.category)
    if category not in {"base", "lip", "eye", "blush", "contour", "highlight", "brow"}:
        return "INVALID_CATEGORY", "商品分類無效"
    return None, None


def _write_product_audit(product_id, action, actor, before_data=None, after_data=None,
                         product_type="products", request_id=None):
    actor_id = actor if isinstance(actor, str) else _opaque_actor(actor)
    request_id = (
            (request_id or request.headers.get("X-Request-ID") or "").strip()[:128]
            or f"req_{uuid.uuid4().hex}"
    )
    db.session.execute(db.text("""
        INSERT INTO product_audit_logs
            (product_id, product_type, action, admin_id, before_data, after_data, request_id, source_ip)
        VALUES
            (:product_id, :product_type, :action, :admin_id, CAST(:before_data AS jsonb),
             CAST(:after_data AS jsonb), :request_id, CAST(:source_ip AS inet))
    """), {
        "product_id": str(product_id), "product_type": product_type,
        "action": action, "admin_id": actor_id,
        "before_data": json.dumps(before_data) if before_data is not None else None,
        "after_data": json.dumps(after_data) if after_data is not None else None,
        "request_id": request_id, "source_ip": request.remote_addr or None,
    })


@app.route('/api/admin/crawler-staging-products', methods=['GET'])
def list_crawler_staging_products():
    admin_err = require_admin()
    if admin_err:
        return admin_err
    status = (request.args.get("status") or "pending").strip().lower()
    if status not in {"pending", "approved", "rejected", "imported", "failed", "all"}:
        return error_response("INVALID_STATUS", "status 無效", 400)
    query = CrawlerStagingProduct.query
    if status != "all":
        query = query.filter_by(status=status)
    items = query.order_by(CrawlerStagingProduct.crawled_at.desc(), CrawlerStagingProduct.id.desc()).limit(100).all()
    return jsonify({"items": [_staging_product_payload(item) for item in items]}), 200


@app.route('/api/admin/crawler-staging-products/<int:staging_id>/approve', methods=['POST'])
def approve_crawler_staging_product(staging_id):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    actor, err = require_actor()
    if err:
        return err
    item = db.session.get(CrawlerStagingProduct, staging_id)
    if item is None:
        return error_response("NOT_FOUND", "找不到暫存商品", 404)
    if item.status != "pending":
        return error_response("INVALID_STATE", "只有待審核商品可以匯入", 409)
    code, message = _staging_import_validation(item)
    if code:
        item.status = "failed"
        item.validation_error_code = code
        item.validation_error_message = message
        db.session.commit()
        return error_response(code, message, 422)
    image_url = item.image_url or (item.image_urls or {}).get("width640")
    product = Products(name=item.name.strip(), price=item.price, image_url=image_url,
                       description=item.description or "", category=cat_to_product_category(item.category),
                       shades=item.shades or [])
    db.session.add(product)
    db.session.flush()
    catalog_id = db.session.execute(db.text("""
        SELECT id FROM public.product_catalog WHERE product_type = 'products' AND source_id = :source_id
    """), {"source_id": product.id}).scalar_one()
    item.status = "imported"
    item.imported_product_id = product.id
    item.reviewed_at = datetime.now(timezone.utc)
    item.reviewed_by = _opaque_actor(actor)
    item.review_note = ((request.get_json(silent=True) or {}).get("note") or "").strip()[:500] or None
    _write_product_audit(catalog_id, "import", actor, after_data={"stagingId": item.id, "sourceSite": item.source_site})
    db.session.commit()
    return jsonify({"item": _staging_product_payload(item), "productId": catalog_id, "sourceId": product.id}), 201


@app.route('/api/admin/crawler-staging-products/<int:staging_id>/reject', methods=['POST'])
def reject_crawler_staging_product(staging_id):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    actor, err = require_actor()
    if err:
        return err
    item = db.session.get(CrawlerStagingProduct, staging_id)
    if item is None:
        return error_response("NOT_FOUND", "找不到暫存商品", 404)
    if item.status != "pending":
        return error_response("INVALID_STATE", "只有待審核商品可以拒絕", 409)
    note = ((request.get_json(silent=True) or {}).get("note") or "").strip()
    item.status = "rejected"
    item.reviewed_at = datetime.now(timezone.utc)
    item.reviewed_by = _opaque_actor(actor)
    item.review_note = note[:500] or "管理員拒絕匯入"
    db.session.commit()
    return jsonify({"item": _staging_product_payload(item)}), 200


@app.route('/api/members/<path:email>', methods=['PATCH'])
def update_member_api(email):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    actor, err = require_actor()
    if err:
        return err
    member = Members.query.filter_by(email=email.strip().lower()).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    data = request.get_json(silent=True) or {}
    old_level = member.level_label()
    old_role = member.member_role()
    old_status = member.status or "active"
    if "level" in data:
        level = member_level_value(data.get("level"))
        if level is None:
            return error_response("INVALID_LEVEL", "等級無效", 400)
        member.level = level
        log_audit(actor.email, email, "level_change", "level", old_level, data.get("level"))
    if "role" in data:
        role = data.get("role")
        if role not in {"member", "admin"}:
            return error_response("INVALID_ROLE", "角色無效", 400)
        # The admin UI saves every row as a batch, including unchanged rows.
        # Revoking sessions for an admin -> admin no-op logs the operator out
        # midway through the batch and makes every later PATCH fail with 401.
        if role != old_role:
            member.role = role
            revoke_all_member_sessions(member)
            log_audit(actor.email, email, "role_change", "role", old_role, role)
    if "status" in data:
        status = data.get("status")
        if status not in {"active", "suspended"}:
            return error_response("INVALID_STATUS", "狀態無效", 400)
        if status != old_status:
            member.status = status
            revoke_all_member_sessions(member)
            log_audit(actor.email, email, "status_change", "status", old_status, status)
    if "allowedPages" in data:
        member.allowed_pages = (
            _default_allowed_pages(member)
            if member.member_role() == "admin"
            else data.get("allowedPages")
        )
    if "vipRequested" in data:
        member.vip_requested = data.get("vipRequested")
    if "renderQuota" in data:
        quota = data["renderQuota"]
        if "dailyLimit" in quota:
            member.render_daily_limit = quota["dailyLimit"]
        if "remaining" in quota:
            member.render_remaining = quota["remaining"]
    db.session.commit()
    return jsonify({"member": member_profile_payload(member)}), 200


@app.route('/api/members/<path:email>', methods=['DELETE'])
def delete_member_api(email):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    target_email = (email or "").strip().lower()
    if not target_email or "@" not in target_email:
        return error_response("INVALID_EMAIL", "Email 格式無效", 422)
    actor, _ = authenticated_member()
    if actor.email.strip().lower() == target_email:
        return error_response("CANNOT_DELETE_SELF", "不可刪除目前登入的管理員帳號", 403)
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 255):
        return error_response("INVALID_REASON", "刪除原因最多 255 字", 400)
    reason = reason.strip() if isinstance(reason, str) else None
    request_id = f"req_{uuid.uuid4().hex}"
    try:
        member = Members.query.filter_by(email=target_email).first()
        if not member:
            return error_response("USER_NOT_FOUND", "找不到會員", 404)
        if member.member_role() == "admin":
            active_admins = Members.query.filter(
                Members.role == "admin", Members.status == "active"
            ).count()
            if active_admins <= 1:
                return error_response("LAST_ADMIN_PROTECTED", "不可刪除最後一個啟用中的管理員", 409)
        # Session has a foreign key to members; revoke is not enough for a hard
        # deletion because the row would still block DELETE FROM members.
        MemberSession.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
        # 硬刪除關聯資料
        SavedLook.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        Favorites.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
        CartItem.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        AnalysisHistory.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        TryonRecords.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
        Checkin.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
        PointsTransaction.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        DailyCheckin.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        TaskClaim.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        UnlockedTheme.query.filter_by(member_email=target_email).delete(synchronize_session=False)
        OTPCode.query.filter_by(email=target_email).delete(synchronize_session=False)
        Referral.query.filter(
            (Referral.referrer_email == target_email) | (Referral.referred_email == target_email)
        ).delete(synchronize_session=False)
        db.session.add(AdminAuditLog(
            id=str(uuid.uuid4()), request_id=request_id,
            actor_email=actor.email, action="delete_member",
            target_email=target_email, result="success",
            reason=reason, metadata_json={"mode": "hard"}
        ))
        db.session.delete(member)
        db.session.commit()
        return jsonify({"success": True, "mode": "hard", "requestId": request_id}), 200
    except Exception:
        db.session.rollback()
        return error_response("DELETE_FAILED", "刪除會員失敗，資料庫已回復原狀", 409, request_id=request_id)


@app.route('/api/members/<path:email>/audit-log', methods=['GET'])
def get_audit_log_api(email):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    target = email.strip().lower()
    logs = AuditLog.query.filter_by(target_email=target).order_by(AuditLog.created_at.desc()).limit(100).all()
    return jsonify({
        "logs": [{
            "actorEmail": log.actor_email,
            "targetEmail": log.target_email,
            "action": log.action,
            "before": log.before_value,
            "after": log.after_value,
            "timestamp": log.created_at.isoformat() if log.created_at else None
        } for log in logs]
    })


@app.route('/api/members/<phone>/stats', methods=['GET'])
def get_member_stats(phone):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    member = Members.query.get(phone)
    if not member:
        return jsonify({"message": "找不到會員"}), 404
    checkins = Checkin.query.filter_by(member_id=phone).count()
    favorites = Favorites.query.filter_by(member_id=phone).count()
    last_checkin = db.session.query(db.func.max(Checkin.checkin_time)).filter_by(member_id=phone).scalar()
    return jsonify({
        "member": member_profile_payload(member),
        "stats": {
            "total_checkins": checkins, "total_favorites": favorites,
            "last_checkin_at": last_checkin.isoformat() if last_checkin else None
        }
    })


# ========== 商品 API ==========
@app.route('/api/products', methods=['GET'])
def get_products_api():
    return _catalog_list_response()


@app.route('/api/products', methods=['POST'])
def create_product_api():
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    data = request.get_json(silent=True) or {}
    category_labels = {item["type"]: item["name"] for item in MAKEUP_CATEGORIES}
    type_aliases = {label: product_type for product_type, label in category_labels.items()}
    type_aliases.update({"粉底": "foundations", "口紅": "lipsticks", "眉妝": "eyebrows",
                         "眼線睫毛": "eyeliner_mascara", "高光": "highlighters"})
    raw_type = str(data.get("type") or "").strip().lower().replace("-", "_")
    raw_category = str(data.get("category") or "").strip()
    product_type = raw_type or type_aliases.get(raw_category)
    if not product_type and raw_category:
        product_type = category_to_frontend_type(cat_to_product_category(raw_category))
    if product_type not in _PRODUCT_CATALOG_TABLES or product_type == "products":
        return error_response(
            "INVALID_CATEGORY", "type 必須是合法的商品分類代碼", 422,
            details={"field": "type", "allowed": sorted(
                value for value in _PRODUCT_CATALOG_TABLES if value != "products"
            )},
        )
    if raw_category and type_aliases.get(raw_category, product_type) != product_type:
        return error_response(
            "INVALID_CATEGORY", "category 與 type 不相符", 422,
            details={"field": "category", "allowed": sorted(category_labels.values())},
        )

    name = str(data.get("name") or "").strip()
    brand = str(data.get("brand") or "").strip()
    description = str(data.get("description") or "").strip()
    image_url = str(data.get("imageUrl") or data.get("image_url") or "").strip()
    source_url = str(data.get("sourceUrl") or data.get("source_url") or "").strip()
    source_product_id = str(data.get("sourceProductId") or "").strip()
    sku = str(data.get("sku") or "").strip()
    shade_name = str(data.get("shadeName") or data.get("shade_name") or "").strip()
    colour_required = product_type in {"foundations", "blushes", "lipsticks"}
    # 眼線等非敏感類別可沒有色號；用明確的 N/A 值保持 API 欄位形狀，
    # 不捏造顏色，也不讓前端把空字串誤認為爬蟲漏抓。
    if not shade_name and not colour_required:
        shade_name = "官方單一規格"
    currency = str(data.get("currency") or "").strip().upper()
    missing = [field for field, value in (("name", name), ("brand", brand),
                                          ("type", product_type), ("price", data.get("price")),
                                          ("description", description),
                                          ("imageUrl", image_url), ("sourceUrl", source_url),
                                          ("sourceProductId", source_product_id), ("sku", sku),
                                          ("shadeName", shade_name), ("currency", currency))
               if value in (None, "")]
    if missing:
        return error_response("MISSING_FIELDS", "缺少必填欄位", 400, details={"fields": missing})
    try:
        price = int(float(data["price"]))
        if not 0 < price <= 10_000_000:
            raise ValueError
    except (TypeError, ValueError):
        return error_response("PRODUCT_VALIDATION_FAILED", "商品價格無效", 422)
    parsed_image = urlparse(image_url)
    if parsed_image.scheme not in {"http", "https"} or not parsed_image.netloc:
        return error_response("PRODUCT_VALIDATION_FAILED", "imageUrl 格式無效", 422)
    parsed_source = urlparse(source_url)
    if parsed_source.scheme not in {"http", "https"} or not parsed_source.netloc:
        return error_response("PRODUCT_VALIDATION_FAILED", "sourceUrl 格式無效", 422)
    if currency not in {"TWD", "USD", "JPY", "KRW", "EUR", "GBP", "CNY", "HKD"}:
        return error_response("PRODUCT_VALIDATION_FAILED", "currency 格式無效", 422)
    status = str(data.get("status") or "active")
    review_status = str(data.get("reviewStatus") or "approved")
    if status not in {"active", "inactive", "archived"} or review_status not in {"pending", "approved", "rejected"}:
        return error_response("PRODUCT_VALIDATION_FAILED", "商品狀態無效", 422)
    palette_colors = data.get("paletteColors") or []
    if not isinstance(palette_colors, list):
        return error_response("PRODUCT_VALIDATION_FAILED", "paletteColors 必須是陣列", 422)
    palette_image_url = str(data.get("paletteImageUrl") or "").strip()
    if palette_colors and (
            not _is_https_url(palette_image_url) or
            any(not isinstance(pan, dict) or not str(pan.get("name") or "").strip()
                or pan.get("position") is None for pan in palette_colors)):
        return error_response("PRODUCT_VALIDATION_FAILED", "多色盤的色格與圖片資料不完整", 422)
    lab = data.get("lab")
    if lab is not None and (not isinstance(lab, list) or len(lab) != 3
                            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in lab)):
        return error_response("PRODUCT_VALIDATION_FAILED", "lab 必須是三個數字", 422)
    # A multi-pan palette is never represented by one averaged colour.
    hex_primary = None if palette_colors else (data.get("hex") or data.get("hex_primary") or None)
    lab = None if palette_colors else lab
    if hex_primary and not re.fullmatch(r"#[0-9A-Fa-f]{6}", str(hex_primary)):
        return error_response("PRODUCT_VALIDATION_FAILED", "hex 格式無效", 422)
    if (colour_required and not palette_colors and shade_name != "官方單一規格"
            and (not hex_primary or lab is None)):
        return error_response("PRODUCT_VALIDATION_FAILED", "單色色號必須提供官方 hex 與 lab", 422)

    sale_page_id = str(data.get("salePageId") or f"admin-{uuid.uuid4().hex[:16]}")[:50]
    shade_code = str(data.get("shadeCode") or shade_name).strip()[:30]
    table = product_type
    params = {
        "sale_page_id": sale_page_id, "name": name, "brand": brand, "price": price,
        "description": description, "image_url": image_url,
        "hex_primary": hex_primary, "lab": json.dumps(lab) if lab is not None else None,
        "palette_colors": json.dumps(palette_colors, ensure_ascii=False),
        "palette_image_url": palette_image_url or None, "sku": sku,
        "category": category_labels[product_type], "product_type": product_type,
        "status": status, "review_status": review_status, "in_stock": bool(data.get("inStock", True)),
        "currency": currency,
        "image_urls": json.dumps(data.get("imageUrls") or [image_url]),
        "source_url": source_url, "source_site": parsed_source.hostname,
        "source_product_id": source_product_id,
        "fingerprint": hashlib.sha256(f"{source_url or sale_page_id}|{sku}|{shade_name}".encode()).hexdigest(),
        "style_tags": data.get("styleTags") or [], "finish_tags": data.get("finishTags") or [],
        "season_tags": data.get("seasonTags") or [], "occasion_tags": data.get("occasionTags") or [],
        "feature_tags": data.get("featureTags") or [], "avoid_tags": data.get("avoidTags") or [],
        "shade_name": shade_name, "coverage": data.get("coverage"), "undertone": data.get("undertone"),
        "texture": data.get("texture"),
    }
    try:
        source_id = db.session.execute(db.text(f"""INSERT INTO public.{table}(
            sale_page_id,name,brand,price,description,image_webp_url,hex_primary,lab,palette_colors,palette_image_url,
            sku,category,product_type,status,review_status,in_stock,currency,image_urls,source_url,source_site,
            source_product_id,crawl_fingerprint,style_tags,finish_tags,season_tags,occasion_tags,feature_tags,
            avoid_tags,shade_name,coverage,undertone,texture,version,updated_at)
            VALUES(:sale_page_id,:name,:brand,:price,:description,:image_url,:hex_primary,CAST(:lab AS jsonb),
            CAST(:palette_colors AS jsonb),:palette_image_url,:sku,:category,:product_type,:status,:review_status,
            :in_stock,:currency,CAST(:image_urls AS jsonb),:source_url,:source_site,:source_product_id,:fingerprint,
            :style_tags,:finish_tags,:season_tags,:occasion_tags,:feature_tags,:avoid_tags,:shade_name,:coverage,
            :undertone,:texture,1,CURRENT_TIMESTAMP) RETURNING id"""), params).scalar_one()
        if product_type in {"foundations", "lipsticks"}:
            db.session.execute(db.text(f"UPDATE public.{table} SET shade_code=:shade_code WHERE id=:id"),
                               {"shade_code": shade_code, "id": source_id})
        catalog_id = db.session.execute(db.text("""INSERT INTO public.product_catalog(product_type,source_id)
            VALUES(:product_type,:source_id)
            ON CONFLICT(product_type,source_id) DO UPDATE SET product_type=EXCLUDED.product_type
            RETURNING id"""), {"product_type": product_type, "source_id": source_id}).scalar_one()
        _write_product_audit(f"{product_type}:{source_id}", "create", _product_delete_actor(),
                             after_data={"catalogId": catalog_id, "name": name, "brand": brand},
                             product_type=product_type)
        db.session.commit()
        _invalidate_catalog_cache()
        return jsonify({"ok": True, "product": _catalog_item_by_id(catalog_id)}), 201
    except IntegrityError:
        db.session.rollback()
        return error_response("PRODUCT_ALREADY_EXISTS", "商品已存在", 409)
    except Exception:
        db.session.rollback()
        app.logger.exception("product create failed")
        return error_response("CREATE_FAILED", "建立失敗", 500)


@app.route('/api/products/<int:product_id>', methods=['PATCH'])
def update_product_api(product_id):
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    return _catalog_update_response(product_id, request.get_json(silent=True) or {})


@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product_api(product_id):
    item = _catalog_item_by_id(product_id)
    if item is None:
        return error_response("NOT_FOUND", "找不到商品", 404)
    if item.get("type") == "foundations":
        neighbors = _product_shade_neighbors(item)
        item["shadeNeighbors"] = neighbors
        # The storefront already knows how to render ``foundationCrossBrand``
        # on a product detail page.  ``shadeNeighbors`` is intentionally a
        # compact, precomputed index; adapt it here to that public storefront
        # contract with the complete candidate payloads.  Do not make the
        # browser infer colour matches or scan the catalogue itself.
        item["foundationCrossBrand"] = _foundation_cross_brand_detail(item, neighbors)
    response = jsonify(item)
    # The detail representation gained colour-comparison fields independent of
    # the product-row version.  A schema revision in the validator prevents a
    # browser that cached the old detail JSON from silently retaining a page
    # with no cross-brand section.
    response.headers["ETag"] = f'"product-detail-v2-{item.get("version", 1)}"'
    response.headers["Cache-Control"] = "private, no-cache, must-revalidate"
    return response, 200


def _product_shade_neighbors(item):
    """Read precomputed neighbours; never compare against the catalogue here."""
    payload = shade_neighbor_index.neighbors_payload(item)
    if payload and payload.get("status") == "pending":
        # The index has not seen this snapshot (e.g. first request after a
        # restart).  Small updates finish inline, large ones in the background.
        if _refresh_shade_neighbor_index(_catalog_rows()) == "ready":
            payload = shade_neighbor_index.neighbors_payload(item)
    return payload


def _foundation_cross_brand_detail(item, neighbors):
    """Expose indexed cross-brand matches in the existing product-page shape.

    ``shadeNeighbors`` remains the machine-readable index response.  The SPA
    expects each cross-brand entry to carry a complete ``product`` object so a
    visitor can open that candidate without a second client-side catalogue
    search.  Candidate IDs come exclusively from the trusted precomputed
    index; loading their display payloads does not recompute any colour score.
    """
    candidate_rows = _catalog_rows()
    by_id = {candidate.get("id"): candidate for candidate in candidate_rows}
    source_brand = str(item.get("brand") or "").strip().casefold()
    source_is_concealer = _is_concealer_product(item)
    eligible_candidates = [
        candidate for candidate in candidate_rows
        if (_is_shade_match_candidate(candidate)
            and str(candidate.get("brand") or "").strip()
            and str(candidate.get("brand") or "").strip().casefold() != source_brand
            and _is_concealer_product(candidate) == source_is_concealer)
    ]
    available_target_brands = sorted({
                                         str(candidate.get("brand") or "").strip()
                                         for candidate in eligible_candidates
                                     } | ({str(item.get("brand") or "").strip()} if _is_shade_match_candidate(
        item) else set()),
                                     key=str.casefold)
    cross_brand = neighbors.get("crossBrand") if isinstance(neighbors, dict) else None
    if isinstance(cross_brand, dict) and isinstance(cross_brand.get("closest"), list):
        compact_candidates = cross_brand["closest"]
        precomputed = True
    else:
        # The first request after a service restart can arrive before the
        # all-products index is ready.  Do one bounded server-side source-to-N
        # comparison so the first visitor still sees a useful result.  This is
        # deliberately not an N×N rebuild and never moves colour work into the
        # browser; later requests use the precomputed index above.
        source_lab = _comparable_foundation_lab(item)
        if source_lab is None:
            return None
        ranked = [
            (float(delta_e(source_lab, _comparable_foundation_lab(candidate))), candidate)
            for candidate in eligible_candidates
        ]
        ranked.sort(key=lambda pair: _shade_sort_key(*pair))
        compact_candidates = [
            {"id": candidate.get("id"), "brand": candidate.get("brand"),
             "shadeCode": candidate.get("shadeCode"), "deltaE": distance}
            for distance, candidate in ranked[:5]
        ]
        precomputed = False
    entries = []
    for candidate in compact_candidates:
        if not isinstance(candidate, dict):
            continue
        product = by_id.get(candidate.get("id"))
        if product is None:
            # A stale candidate must never be rendered after it was unpublished
            # or became out of stock between index refreshes.
            continue
        entries.append({
            "brand": candidate.get("brand") or product.get("brand"),
            "shadeCode": candidate.get("shadeCode") or product.get("shadeCode"),
            "anchorDeltaE": candidate.get("deltaE"),
            "reason": "依可信色彩資料以 CIEDE2000 計算的跨品牌相近色號。",
            "product": product,
        })
    return {
        "status": "ready",
        "anchorCandidateKey": item.get("candidateKey"),
        # The compact neighbour payload deliberately stores just the nearest
        # matches.  The selector must still list every currently eligible
        # target brand so selecting one can call the existing filtered API.
        "availableTargetBrands": available_target_brands,
        "items": entries,
        "noResultReason": "" if entries else "目前沒有可比較的其他品牌粉底色號。",
        "precomputed": precomputed,
    }


def _product_relation_exists(table):
    return db.session.execute(
        db.text("SELECT to_regclass(:relation)"), {"relation": f"public.{table}"}
    ).scalar() is not None


def _product_relation_columns(table):
    return set(db.session.execute(db.text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :table
    """), {"table": table}).scalars().all())


def _product_reference_values(item):
    source_id = int(item["sourceId"])
    catalog_id = int(item["id"])
    ids = sorted({source_id, catalog_id})
    product_type = str(item["type"])
    category = cat_to_product_category(item.get("category") or product_type)
    types = sorted({product_type, category, category_to_frontend_type(category)})
    return ids, types


def _product_query_parameters(item):
    ids, types = _product_reference_values(item)
    while len(ids) < 2:
        ids.append(ids[0])
    while len(types) < 3:
        types.append(types[-1])
    return {
        "source_id": ids[0], "catalog_id": ids[-1],
        "type_a": types[0], "type_b": types[len(types) // 2], "type_c": types[-1],
    }


def _count_preserved_product_rows(item):
    """Count user-owned/history rows without changing or cascading them."""
    params = _product_query_parameters(item)
    result = {"favorites": 0, "cartItems": 0, "recommendationRecords": 0}

    if _product_relation_exists("favorites"):
        result["favorites"] = int(db.session.execute(db.text("""
            SELECT COUNT(*) FROM public.favorites
            WHERE item_id IN (:source_id, :catalog_id)
              AND item_type IN (:type_a, :type_b, :type_c)
        """), params).scalar() or 0)

    for table in ("cart_items", "cart"):
        if not _product_relation_exists(table):
            continue
        columns = _product_relation_columns(table)
        if "item_id" not in columns:
            continue
        type_filter = (
            " AND item_type IN (:type_a, :type_b, :type_c)"
            if "item_type" in columns else ""
        )
        result["cartItems"] += int(db.session.execute(db.text(
            f"SELECT COUNT(*) FROM public.{table} "
            "WHERE item_id IN (:source_id, :catalog_id)" + type_filter
        ), params).scalar() or 0)

    for table in ("recommendation_records", "recommendations", "tryon_records"):
        if not _product_relation_exists(table):
            continue
        columns = _product_relation_columns(table)
        id_column = "product_id" if "product_id" in columns else (
            "item_id" if "item_id" in columns else None
        )
        if not id_column:
            continue
        type_column = "item_type" if "item_type" in columns else (
            "product_type" if "product_type" in columns else None
        )
        type_filter = (
            f" AND {type_column} IN (:type_a, :type_b, :type_c)"
            if type_column else ""
        )
        result["recommendationRecords"] += int(db.session.execute(db.text(
            f"SELECT COUNT(*) FROM public.{table} "
            f"WHERE {id_column} IN (:source_id, :catalog_id)" + type_filter
        ), params).scalar() or 0)
    return result


def _delete_product_shade_rows(item):
    params = _product_query_parameters(item)
    deleted = 0
    for table in ("product_shades", "shades"):
        if not _product_relation_exists(table):
            continue
        columns = _product_relation_columns(table)
        if "product_id" not in columns:
            continue
        type_filter = (
            " AND product_type IN (:type_a, :type_b, :type_c)"
            if "product_type" in columns else ""
        )
        result = db.session.execute(db.text(
            f"DELETE FROM public.{table} "
            "WHERE product_id IN (:source_id, :catalog_id)" + type_filter
        ), params)
        deleted += int(result.rowcount or 0)
    return deleted


def _delete_product_staging_rows(item):
    """Remove crawler rows that refer to the product being hard-deleted."""
    table = "crawler_staging_products"
    if not _product_relation_exists(table):
        return 0
    columns = _product_relation_columns(table)
    clauses = []
    params = {}
    source_id = int(item["sourceId"])
    catalog_id = int(item["id"])
    refs = sorted({str(source_id), str(catalog_id), f"{item['type']}:{source_id}"})

    if "imported_product_id" in columns and item["type"] == "products":
        clauses.append("imported_product_id = :source_id")
        params["source_id"] = source_id
    if "imported_product_ref" in columns:
        placeholders = []
        for index, value in enumerate(refs):
            key = f"ref_{index}"
            params[key] = value
            placeholders.append(f":{key}")
        clauses.append(f"imported_product_ref IN ({', '.join(placeholders)})")
    source_product_id = str(item.get("sourceProductId") or "").strip()
    if "source_product_id" in columns and source_product_id:
        clauses.append("source_product_id = :source_product_id")
        params["source_product_id"] = source_product_id
    source_url = str(item.get("sourceUrl") or "").strip()
    if "source_url" in columns and source_url:
        clauses.append("source_url = :source_url")
        params["source_url"] = source_url
    if not clauses:
        return 0
    result = db.session.execute(db.text(
        f"DELETE FROM public.{table} WHERE " + " OR ".join(f"({clause})" for clause in clauses)
    ), params)
    return int(result.rowcount or 0)


def _product_delete_actor():
    forwarded = (request.headers.get("X-Admin-Actor") or "").strip()[:128]
    if forwarded:
        return forwarded
    actor, _ = authenticated_member()
    return _opaque_actor(actor) if actor is not None else "gateway_product_admin"


@app.route('/api/products/<int:product_id>/delete-impact', methods=['GET'])
def get_product_delete_impact_api(product_id):
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    item = _catalog_item_by_id(product_id, include_incomplete=True)
    if item is None:
        return error_response("PRODUCT_NOT_FOUND", "商品不存在", 404)
    return jsonify({**_count_preserved_product_rows(item), "canDelete": True}), 200


@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product_api(product_id):
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    request_id = (
            (request.headers.get("X-Request-ID") or "").strip()[:128]
            or f"req_{uuid.uuid4().hex}"
    )
    try:
        catalog_ref = db.session.execute(db.text("""
            SELECT product_type, source_id
            FROM public.product_catalog
            WHERE id = :id
            FOR UPDATE
        """), {"id": product_id}).mappings().first()
        if catalog_ref is None or catalog_ref["product_type"] not in _PRODUCT_CATALOG_TABLES:
            db.session.rollback()
            return error_response("PRODUCT_NOT_FOUND", "商品不存在", 404, request_id=request_id)

        item = _catalog_item_by_id(product_id, include_incomplete=True)
        if item is None:
            db.session.rollback()
            return error_response("PRODUCT_NOT_FOUND", "商品不存在", 404, request_id=request_id)

        table = _PRODUCT_CATALOG_TABLES[item["type"]]
        preserved = _count_preserved_product_rows(item)
        _write_product_audit(
            f"{item['type']}:{item['sourceId']}", "delete", _product_delete_actor(),
            before_data=item, product_type=item["type"], request_id=request_id,
        )
        shades = _delete_product_shade_rows(item)
        staging_rows = _delete_product_staging_rows(item)
        source_delete = db.session.execute(
            db.text(f"DELETE FROM public.{table} WHERE id = :source_id"),
            {"source_id": item["sourceId"]},
        )
        if source_delete.rowcount != 1:
            db.session.rollback()
            return error_response("PRODUCT_NOT_FOUND", "商品不存在", 404, request_id=request_id)
        db.session.execute(
            db.text("DELETE FROM public.product_catalog WHERE id = :id"), {"id": product_id}
        )
        db.session.commit()
        _invalidate_catalog_cache()
        deleted_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        return jsonify({
            "ok": True, "mode": "hard", "id": product_id, "deletedAt": deleted_at,
            "cascaded": {"shades": shades, "stagingRows": staging_rows},
            "preserved": preserved,
        }), 200
    except Exception:
        db.session.rollback()
        app.logger.exception("product hard delete failed product_id=%s request_id=%s", product_id, request_id)
        return error_response(
            "DELETE_FAILED", "刪除商品失敗，資料庫已回復原狀", 409, request_id=request_id
        )


def _staging_contract_payload(row):
    """Project both the legacy and the current staging schema consistently."""
    row = dict(row)
    specs = row.get("specs") if isinstance(row.get("specs"), dict) else {}
    images = [
        row.get(key) for key in (
            "image_original_url", "image_1280_url", "image_640_url",
            "image_320_url", "image_url",
        ) if str(row.get(key) or "").startswith("https://")
    ]
    validation_errors = row.get("validation_errors")
    if not isinstance(validation_errors, list):
        validation_errors = []
    if row.get("error_code"):
        validation_errors.append({
            "code": row.get("error_code"),
            "message": row.get("error_summary") or "資料驗證失敗",
        })
    return {
        "id": int(row["id"]),
        "sourceSite": row.get("source_site"),
        "sourceProductId": row.get("source_product_id"),
        "sourceUrl": row.get("source_url"),
        "name": row.get("product_name") or row.get("name"),
        "brand": row.get("brand"),
        "price": float(row["price"]) if row.get("price") is not None else None,
        "currency": row.get("currency") or "TWD",
        "description": row.get("description") or "",
        "category": row.get("category"),
        "sku": row.get("sku"),
        "shadeCode": row.get("shade_code") or specs.get("shade"),
        "hex": row.get("hex_primary"),
        "specs": specs,
        "imageUrl": images[0] if images else None,
        "imageUrls": images,
        "inStock": row.get("in_stock") is not False,
        "status": row.get("status"),
        "validationErrors": validation_errors,
        "crawledAt": row.get("crawled_at").isoformat() if row.get("crawled_at") else None,
        "reviewedAt": row.get("reviewed_at").isoformat() if row.get("reviewed_at") else None,
        "importedAt": row.get("imported_at").isoformat() if row.get("imported_at") else None,
        "importedProductRef": row.get("imported_product_ref"),
    }


def _staging_row(staging_id):
    return db.session.execute(
        db.text("SELECT * FROM public.crawler_staging_products WHERE id=:id"),
        {"id": staging_id},
    ).mappings().first()


@app.route('/api/crawler-staging/products', methods=['GET'])
def crawler_staging_products_api():
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    status = (request.args.get("status") or "pending").strip().casefold()
    if status not in {"pending", "approved", "rejected", "imported", "failed", "all"}:
        return error_response("INVALID_STATUS", "status 無效", 422)
    try:
        limit = int(request.args.get("limit", 100))
        offset = int(request.args.get("cursor", 0) or 0)
        if not 1 <= limit <= 200 or offset < 0:
            raise ValueError
    except (TypeError, ValueError):
        return error_response("INVALID_PAGINATION", "limit 或 cursor 格式無效", 422)
    where = "" if status == "all" else "WHERE status=:status"
    params = {"status": status, "limit": limit, "offset": offset}
    total = int(db.session.execute(
        db.text(f"SELECT COUNT(*) FROM public.crawler_staging_products {where}"), params
    ).scalar() or 0)
    rows = db.session.execute(db.text(f"""
        SELECT * FROM public.crawler_staging_products {where}
        ORDER BY COALESCE(updated_at,crawled_at) DESC,id DESC
        LIMIT :limit OFFSET :offset
    """), params).mappings().all()
    next_cursor = str(offset + limit) if offset + limit < total else None
    return jsonify({
        "ok": True, "items": [_staging_contract_payload(row) for row in rows],
        "total": total, "nextCursor": next_cursor,
    }), 200


@app.route('/api/crawler-staging/products/<int:staging_id>', methods=['GET', 'PATCH'])
def crawler_staging_product_api(staging_id):
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    row = _staging_row(staging_id)
    if row is None:
        return error_response("STAGING_PRODUCT_NOT_FOUND", "找不到暫存商品", 404)
    if request.method == "GET":
        return jsonify({"ok": True, "item": _staging_contract_payload(row)}), 200
    if row["status"] == "imported":
        return error_response("INVALID_STATE", "已匯入商品不可再修改", 409)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return error_response("INVALID_PAYLOAD", "請提供 JSON 商品資料", 400)
    columns = _product_relation_columns("crawler_staging_products")
    field_map = {
        "name": "product_name", "brand": "brand", "description": "description",
        "category": "category", "price": "price", "currency": "currency",
        "sku": "sku", "shadeCode": "shade_code", "hex": "hex_primary",
        "inStock": "in_stock", "imageUrl": "image_original_url", "status": "status",
    }
    updates = {
        column: data[key] for key, column in field_map.items()
        if key in data and column in columns
    }
    requested_status = updates.get("status")
    if requested_status is not None and requested_status not in {"pending", "approved", "rejected", "failed"}:
        return error_response("INVALID_STATUS", "status 無效", 422)
    if "category" in updates and updates["category"] not in {
        value for value in _PRODUCT_CATALOG_TABLES if value != "products"}:
        return error_response("INVALID_CATEGORY", "category 無效", 422)
    if "price" in updates:
        try:
            if float(updates["price"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return error_response("INVALID_PRICE", "price 必須大於 0", 422)
    if not updates:
        return error_response("NO_UPDATABLE_FIELDS", "沒有可更新欄位", 400)
    assignments = [f"{column}=:{column}" for column in updates]
    if "updated_at" in columns:
        assignments.append("updated_at=CURRENT_TIMESTAMP")
    if requested_status in {"approved", "rejected"}:
        if "reviewed_at" in columns:
            assignments.append("reviewed_at=CURRENT_TIMESTAMP")
        if "reviewed_by" in columns:
            updates["reviewed_by"] = _product_delete_actor()
            assignments.append("reviewed_by=:reviewed_by")
    updates["id"] = staging_id
    db.session.execute(db.text(
        "UPDATE public.crawler_staging_products SET " + ",".join(assignments) + " WHERE id=:id"
    ), updates)
    db.session.commit()
    return jsonify({"ok": True, "item": _staging_contract_payload(_staging_row(staging_id))}), 200


def _staging_image_url(row):
    return next((str(row.get(key) or "").strip() for key in (
        "image_original_url", "image_1280_url", "image_640_url", "image_320_url", "image_url"
    ) if str(row.get(key) or "").startswith("https://")), "")


@app.route('/api/crawler-staging/products/<int:staging_id>/import', methods=['POST'])
def import_crawler_staging_product_api(staging_id):
    admin_err = require_product_audit_admin()
    if admin_err:
        return admin_err
    row = _staging_row(staging_id)
    if row is None:
        return error_response("STAGING_PRODUCT_NOT_FOUND", "找不到暫存商品", 404)
    if row["status"] == "imported":
        return jsonify({"ok": True, "mode": "idempotent", "item": _staging_contract_payload(row)}), 200
    if row["status"] in {"rejected", "failed"}:
        return error_response("INVALID_STATE", "被拒絕或驗證失敗的商品不可匯入", 409)

    row = dict(row)
    specs = row.get("specs") if isinstance(row.get("specs"), dict) else {}
    category = str(row.get("category") or "")
    name = str(row.get("product_name") or row.get("name") or "").strip()
    brand = str(row.get("brand") or "").strip()
    source_url = str(row.get("source_url") or "").strip()
    source_product_id = str(row.get("source_product_id") or "").strip()
    sku = str(row.get("sku") or source_product_id).strip()
    shade = str(row.get("shade_code") or specs.get("shade") or "官方單一規格").strip()
    image_url = _staging_image_url(row)
    currency = str(row.get("currency") or "TWD").strip().upper()
    palette_colors = specs.get("paletteColors") if isinstance(specs.get("paletteColors"), list) else []
    palette_image_url = str(specs.get("paletteImageUrl") or "").strip() or None
    hex_primary = str(row.get("hex_primary") or "").strip().lower() or None
    errors = []
    if category not in {value for value in _PRODUCT_CATALOG_TABLES if value != "products"}:
        errors.append("category")
    for field, value in (("name", name), ("brand", brand), ("sourceUrl", source_url),
                         ("sourceProductId", source_product_id), ("sku", sku),
                         ("shadeCode", shade), ("imageUrl", image_url)):
        if not value:
            errors.append(field)
    if not source_url.startswith("https://") or not image_url.startswith("https://"):
        errors.append("httpsUrl")
    try:
        price = int(float(row.get("price") or 0))
        if price <= 0:
            raise ValueError
    except (TypeError, ValueError):
        price = 0
        errors.append("price")
    if currency not in {"TWD", "USD", "JPY", "KRW", "EUR", "GBP", "CNY", "HKD"}:
        errors.append("currency")
    if str(row.get("image_validation_status") or "") != "valid":
        errors.append("imageValidation")
    if palette_colors and (not _is_https_url(palette_image_url) or any(
            not isinstance(pan, dict) or not pan.get("name") or pan.get("position") is None
            for pan in palette_colors)):
        errors.append("paletteColors")
    if not palette_colors and hex_primary and not re.fullmatch(r"#[0-9a-f]{6}", hex_primary):
        errors.append("hex")
    if (category in {"foundations", "blushes", "lipsticks"} and not palette_colors and not hex_primary
            and specs.get("colorRepresentation") not in {"official_name_only", "not_applicable", "transparent"}):
        errors.append("officialColour")
    if errors:
        return error_response(
            "STAGING_PRODUCT_INCOMPLETE", "暫存商品欄位不完整，未匯入正式表", 422,
            details={"fields": sorted(set(errors))},
        )

    lab = None
    if hex_primary:
        rgb = hex_to_rgb(hex_primary)
        lab = list(rgb_to_lab(*rgb)) if rgb else None
    category_label = next(item["name"] for item in MAKEUP_CATEGORIES if item["type"] == category)
    sale_raw = re.sub(r"[^A-Za-z0-9._-]", "-", f"{brand}-{source_product_id}").strip("-")
    sale_page_id = (sale_raw[:50] if len(sale_raw) <= 50 else
                    f"stage-{hashlib.sha1(sale_raw.encode()).hexdigest()[:20]}")
    table = category
    try:
        found = db.session.execute(db.text(f"""
            SELECT id FROM public.{table} WHERE UPPER(brand)=:brand AND
              (source_product_id=:source_product_id OR sale_page_id=:sale_page_id OR
               (source_url=:source_url AND sku=:sku)) LIMIT 1
        """), {"brand": brand.upper(), "source_product_id": source_product_id,
               "sale_page_id": sale_page_id, "source_url": source_url, "sku": sku}).scalar()
        params = {
            "sale_page_id": sale_page_id, "name": name, "brand": brand, "price": price,
            "description": str(row.get("description") or f"{brand} 官方商品；色號 {shade}"),
            "image_url": image_url, "hex_primary": hex_primary,
            "lab": json.dumps(lab) if lab is not None else None,
            "palette_colors": json.dumps(palette_colors, ensure_ascii=False),
            "palette_image_url": palette_image_url, "sku": sku, "category_label": category_label,
            "category": category, "in_stock": row.get("in_stock") is not False,
            "currency": currency, "image_urls": json.dumps([image_url]),
            "source_url": source_url, "source_site": urlparse(source_url).hostname,
            "source_product_id": source_product_id, "shade_name": shade,
        }
        if found:
            params["id"] = int(found)
            db.session.execute(db.text(f"""UPDATE public.{table} SET
                name=:name,brand=:brand,price=:price,description=:description,image_webp_url=:image_url,
                hex_primary=:hex_primary,lab=CAST(:lab AS jsonb),palette_colors=CAST(:palette_colors AS jsonb),
                palette_image_url=:palette_image_url,sku=:sku,category=:category_label,product_type=:category,
                status='active',review_status='approved',in_stock=:in_stock,currency=:currency,
                image_urls=CAST(:image_urls AS jsonb),source_url=:source_url,source_site=:source_site,
                source_product_id=:source_product_id,shade_name=:shade_name,deleted_at=NULL,
                version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id"""), params)
            source_id = int(found)
            mode = "updated"
        else:
            source_id = int(db.session.execute(db.text(f"""INSERT INTO public.{table}(
                sale_page_id,name,brand,price,description,image_webp_url,hex_primary,lab,palette_colors,
                palette_image_url,sku,category,product_type,status,review_status,in_stock,currency,image_urls,
                source_url,source_site,source_product_id,shade_name,version,updated_at)
                VALUES(:sale_page_id,:name,:brand,:price,:description,:image_url,:hex_primary,CAST(:lab AS jsonb),
                CAST(:palette_colors AS jsonb),:palette_image_url,:sku,:category_label,:category,'active','approved',
                :in_stock,:currency,CAST(:image_urls AS jsonb),:source_url,:source_site,:source_product_id,
                :shade_name,1,CURRENT_TIMESTAMP) RETURNING id"""), params).scalar_one())
            mode = "inserted"
        if category == "foundations":
            series_id = f"{brand.casefold()}::{hashlib.sha1(source_url.encode()).hexdigest()[:16]}" if hex_primary else None
            db.session.execute(db.text("""UPDATE public.foundations
                SET shade_code=:shade,series_id=:series_id WHERE id=:id"""),
                               {"shade": shade, "series_id": series_id, "id": source_id})
        elif category == "lipsticks":
            db.session.execute(db.text("UPDATE public.lipsticks SET shade_code=:shade WHERE id=:id"),
                               {"shade": shade[:30], "id": source_id})
        catalog_id = int(db.session.execute(db.text("""INSERT INTO public.product_catalog(product_type,source_id)
            VALUES(:category,:source_id) ON CONFLICT(product_type,source_id)
            DO UPDATE SET product_type=EXCLUDED.product_type RETURNING id"""),
                                            {"category": category, "source_id": source_id}).scalar_one())
        staging_columns = _product_relation_columns("crawler_staging_products")
        set_parts = ["status='imported'", "reviewed_at=CURRENT_TIMESTAMP"]
        stage_params = {"id": staging_id, "actor": _product_delete_actor()}
        if "imported_at" in staging_columns:
            set_parts.append("imported_at=CURRENT_TIMESTAMP")
        if "imported_product_ref" in staging_columns:
            set_parts.append("imported_product_ref=:product_ref")
            stage_params["product_ref"] = f"{category}:{source_id}"
        if "reviewed_by" in staging_columns:
            set_parts.append("reviewed_by=:actor")
        db.session.execute(db.text(
            "UPDATE public.crawler_staging_products SET " + ",".join(set_parts) + " WHERE id=:id"
        ), stage_params)
        _write_product_audit(
            f"{category}:{source_id}", "import", _product_delete_actor(),
            after_data={"stagingId": staging_id, "catalogId": catalog_id, "mode": mode},
            product_type=category,
        )
        db.session.commit()
        _invalidate_catalog_cache()
        return jsonify({
            "ok": True, "mode": mode, "id": catalog_id,
            "item": _staging_contract_payload(_staging_row(staging_id)),
            "product": _catalog_item_by_id(catalog_id),
        }), 201 if mode == "inserted" else 200
    except IntegrityError:
        db.session.rollback()
        return error_response("PRODUCT_ALREADY_EXISTS", "商品已存在", 409)
    except Exception:
        db.session.rollback()
        app.logger.exception("staging import failed staging_id=%s", staging_id)
        return error_response("STAGING_IMPORT_FAILED", "暫存商品匯入失敗", 500)


# ========== Crawler ==========
def crawler_error_response(error):
    payload = {"success": False, "error": {"code": error.code, "message": error.message}}
    if error.detail:
        payload["error"]["detail"] = error.detail
    return jsonify(payload), error.http_status


@app.route('/api/crawler/product-preview', methods=['POST'])
def crawler_product_preview_api():
    actor, auth_error = authenticated_member()
    if actor is None:
        return crawler_error_response(CrawlerError("UNAUTHORIZED", "請先登入", 401))
    if not is_admin_member(actor):
        return crawler_error_response(CrawlerError("ADMIN_REQUIRED", "需要管理員權限", 403))
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return crawler_error_response(CrawlerError("INVALID_URL", "請提供 JSON 格式的商品網址", 400))
    source_url = data.get("url")
    request_id = f"crawler_{uuid.uuid4().hex}"
    started = time.monotonic()
    safe_log_url = "invalid-url"
    try:
        validated_url, domain = public_product_url(source_url)
        safe_log_url = sanitized_url(validated_url)
        preview_rate_limiter.check(actor.email, domain, r if redis_url else None)
        preview = build_product_preview(validated_url)
        status = "partial" if preview["missingFields"] else "ok"
        app.logger.info(
            "crawler preview request_id=%s actor=%s url=%s status=%s elapsed_ms=%d",
            request_id, _opaque_actor(actor), safe_log_url, status,
            int((time.monotonic() - started) * 1000),
        )
        return jsonify({
            "success": True,
            "status": status,
            "message": "部分欄位缺漏" if status == "partial" else "商品資料已建立預覽",
            "data": preview,
        }), 200
    except CrawlerError as error:
        return crawler_error_response(error)
    except Exception:
        app.logger.exception("crawler preview request_id=%s actor=%s", request_id, _opaque_actor(actor))
        return crawler_error_response(CrawlerError("CRAWLER_INTERNAL_ERROR", "商品預覽服務發生錯誤", 500))


# ========== 點數 ==========
@app.route('/api/members/<path:email>/points', methods=['GET'])
def get_member_points(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self_or_admin(actor, email)
    if err:
        return err
    member = Members.query.filter_by(email=target_email).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    txn = PointsTransaction.query.filter_by(member_email=target_email).order_by(
        PointsTransaction.created_at.desc()).limit(50).all()
    return jsonify({
        "balance": member.points or 0,
        "lifetime": member.lifetime_points or member.total_earned_points or 0,
        "transactions": [{
            "delta": t.delta, "reason": t.reason,
            "balance_after": t.balance_after,
            "created_at": t.created_at.isoformat() if t.created_at else None
        } for t in txn]
    })


@app.route('/api/members/<path:email>/points/adjust', methods=['POST'])
def adjust_member_points(email):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    actor, err = require_actor()
    if err:
        return err
    member = Members.query.filter_by(email=email.strip().lower()).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    data = request.get_json(silent=True) or {}
    delta = data.get("delta", 0)
    reason = data.get("reason", "admin_adjust")
    note = data.get("note", "")
    balance = add_points_transaction(email, delta, reason, note=note)
    log_audit(actor.email, email, "points_adjust", "points", str(delta), str(balance))
    return jsonify({"balance": balance}), 200


# ========== Saved Looks ==========
@app.route('/api/members/<path:email>/saved-looks', methods=['GET'])
def get_saved_looks(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self_or_admin(actor, email)
    if err:
        return err
    if not Members.query.filter_by(email=target_email, status="active").first():
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    looks = SavedLook.query.filter_by(member_email=target_email).order_by(SavedLook.created_at.desc()).limit(
        SAVED_LOOK_LIMIT).all()
    return jsonify({
        "limit": SAVED_LOOK_LIMIT,
        "looks": [{
            "id": look.id, "style": look.style,
            "beforeImageUrl": look.before_image_url,
            "afterImageUrl": look.after_image_url,
            "analysisSummary": look.analysis_summary,
            "createdAt": look.created_at.isoformat() if look.created_at else None
        } for look in looks]
    })


@app.route('/api/members/<path:email>/saved-looks', methods=['POST'])
def create_saved_look(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    style = data.get("style")
    before_url = data.get("beforeImageUrl", "")
    after_url = data.get("afterImageUrl")
    summary = data.get("analysisSummary")
    if not isinstance(style, str) or not style.strip() or len(style) > 120:
        return error_response("INVALID_STYLE", "style 必填且最多 120 字", 400)
    valid_after_url = isinstance(after_url, str) and (
            re.match(r"^https?://", after_url, re.I) is not None
            or re.fullmatch(r"^(?:https://[^/]+)?/media/render/[0-9a-f]{32}$", after_url) is not None
    )
    if not valid_after_url:
        return error_response(
            "INVALID_AFTER_IMAGE_URL",
            "afterImageUrl 必須是 http(s) URL 或有效的私有媒體路徑",
            400,
        )
    count = SavedLook.query.filter_by(member_email=target_email).count()
    if count >= SAVED_LOOK_LIMIT:
        return error_response("SAVED_LOOK_LIMIT", f"收藏妝容已達 {SAVED_LOOK_LIMIT} 筆上限", 409)
    look = SavedLook(
        member_email=target_email, style=style.strip(),
        before_image_url=before_url,
        after_image_url=after_url,
        analysis_summary=summary
    )
    db.session.add(look)
    db.session.commit()
    return jsonify({
        "id": look.id, "style": look.style,
        "beforeImageUrl": look.before_image_url,
        "afterImageUrl": look.after_image_url,
        "analysisSummary": look.analysis_summary,
        "createdAt": look.created_at.isoformat() if look.created_at else None
    }), 201


@app.route('/api/members/<path:email>/saved-looks/<int:look_id>', methods=['DELETE'])
def delete_saved_look(email, look_id):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self_or_admin(actor, email)
    if err:
        return err
    try:
        # 直接發出 SQL DELETE；不做 soft delete，也不只刪除後台畫面快取。
        deleted = SavedLook.query.filter_by(id=look_id, member_email=target_email).delete(
            synchronize_session=False
        )
        if deleted != 1:
            db.session.rollback()
            return error_response("LOOK_NOT_FOUND", "找不到收藏妝容", 404)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error_response("DELETE_FAILED", "刪除失敗", 500)
    return jsonify({"ok": True, "action": "saved_look_hard_deleted", "id": look_id}), 200


# ========== 色碼 ==========
@app.route('/api/colors', methods=['GET'])
def get_colors():
    colors = ColorPalettes.query.all()
    product_colors = []
    for category in MAKEUP_CATEGORIES:
        for item in category["model"].query.filter(category["model"].hex_primary.isnot(None)).all():
            product_colors.append({"title": getattr(item, "shade_name", "") or getattr(item, "name", ""),
                                   "hex": item.hex_primary, "type": category["type"], "productId": item.id})
    return jsonify({
        "colors": ([{"title": c.title, "hex": c.hex_code, "tags": c.tags} for c in colors] + product_colors)
    })


# ========== MAKEUP CATEGORIES ==========
MAKEUP_CATEGORIES = [
    {"name": "唇彩", "type": "lipsticks", "endpoint": "/api/lipsticks", "model": Lipsticks},
    {"name": "底妝", "type": "foundations", "endpoint": "/api/foundations", "model": Foundations},
    {"name": "腮紅", "type": "blushes", "endpoint": "/api/blushes", "model": Blushes},
    {"name": "眼影", "type": "eyeshadows", "endpoint": "/api/eyeshadows", "model": Eyeshadows},
    {"name": "眼線睫毛", "type": "eyeliner_mascara", "endpoint": "/api/eyeliner_mascara", "model": EyelinerMascara},
    {"name": "修容", "type": "contouring", "endpoint": "/api/contouring", "model": Contouring},
    {"name": "打亮", "type": "highlighters", "endpoint": "/api/highlighters", "model": Highlighters},
    {"name": "眉毛", "type": "eyebrows", "endpoint": "/api/eyebrows", "model": Eyebrows},
]


def category_payload(c):
    return {"name": c["name"], "type": c["type"], "endpoint": c["endpoint"]}


def cat_to_product_category(cat_type: str) -> str:
    mapping = {
        "foundations": "base", "lipsticks": "lip", "eyeshadows": "eye",
        "blushes": "blush", "contouring": "contour",
        "highlighters": "highlight", "eyebrows": "brow",
        "eyeliner_mascara": "eye",
    }
    normalized = (cat_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        **mapping,
        "foundation": "base", "base_makeup": "base", "底妝": "base", "粉底": "base",
        "lipstick": "lip", "lips": "lip", "唇彩": "lip", "口紅": "lip",
        "eyeshadow": "eye", "eye_makeup": "eye", "眼妝": "eye", "眼影": "eye",
        "blusher": "blush", "腮紅": "blush",
        "contour": "contour", "修容": "contour",
        "highlighter": "highlight", "打亮": "highlight",
        "eyebrow": "brow", "眉毛": "brow", "眉毛彩妝": "brow",
        "眉妝": "brow", "眉筆": "brow", "染眉": "brow", "染眉膏": "brow",
    }
    return aliases.get(normalized, normalized)


def category_to_frontend_type(category):
    return {
        "base": "foundations", "lip": "lipsticks", "eye": "eyeshadows",
        "blush": "blushes", "contour": "contouring",
        "highlight": "highlighters", "brow": "eyebrows",
    }.get(category, category)


def find_makeup_category(category_type):
    for c in MAKEUP_CATEGORIES:
        if c["type"] == category_type: return c
    return None


def _price_for_frontend(value, currency="TWD"):
    """Compatibility wrapper retained for existing callers and tests."""
    return price_for_frontend(value, currency)


def get_product_vector(item):
    return getattr(item, "qdrant_vector_12d", None) or getattr(item, "color_vector", None) or []


def product_card_payload(item, category_type):
    pv = get_product_vector(item)
    frontend_price = _price_for_frontend(
        getattr(item, "price", None), getattr(item, "currency", "TWD")
    )
    return {
        "id": item.id, "type": category_type,
        "brand": getattr(item, "brand", "") or "",
        "name": getattr(item, "name", None) or getattr(item, "product_name", None) or "未命名商品",
        "price": frontend_price["display"], "priceValue": frontend_price["amount"],
        "currency": frontend_price["currency"],
        "priceConverted": frontend_price["converted"],
        "priceNote": frontend_price["note"],
        "priceConversion": frontend_price["conversion"],
        "description": getattr(item, "description", "") or "暫無描述",
        "image_src": mirrored_image_url(
            getattr(item, "image_url", getattr(item, "image_webp_url", "https://via.placeholder.com/300x300.png"))),
        "shade_name": getattr(item, "shade_name", "") or "",
        "sale_page_id": getattr(item, "sale_page_id", "") or "",
        "hex_primary": getattr(item, "hex_primary", None),
        "lab": getattr(item, "lab", None) or {},
        "color_vector": pv, "qdrant_vector_12d": pv
    }


def _first_product_hex(shades):
    if isinstance(shades, dict):
        shades = [shades]
    if not isinstance(shades, list):
        return None
    for shade in shades:
        value = shade if isinstance(shade, str) else next(
            (shade.get(k) for k in ("hex", "hexCode", "hex_code", "color", "value") if shade.get(k)),
            None,
        ) if isinstance(shade, dict) else None
        if isinstance(value, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", value.strip()):
            return f"#{value.strip().lstrip('#').upper()}"
    return None


def generic_product_candidate(item):
    category = cat_to_product_category(item.category)
    if category not in {"base", "lip", "eye", "blush", "contour", "highlight", "brow"}:
        category = "other"
    hex_color = _first_product_hex(item.shades)
    lab = None
    if hex_color:
        rgb = hex_to_rgb(hex_color)
        lab = list(rgb_to_lab(*rgb)) if rgb else None
    shade_tags = []
    for shade in item.shades if isinstance(item.shades, list) else []:
        if isinstance(shade, dict):
            shade_tags.extend(str(shade.get(k)).lower() for k in ("name", "label") if shade.get(k))
    return {
        "id": item.id,
        "type": "products",
        "candidateKey": f"products:{item.id}",
        "category": category,
        "brand": "",
        "name": item.name,
        "price": display_price(item.price),
        "description": item.description or "暫無描述",
        "image_src": mirrored_image_url(item.image_url),
        "imageUrl": mirrored_image_url(item.image_url),
        "hex_primary": hex_color,
        "lab": lab or {},
        "tags": [category, category_to_frontend_type(category), *shade_tags],
        "inStock": True,
        "shades": item.shades or [],
        "currency": "TWD",
    }


# A catalog id is the only public product id.  Category-table ids remain an
# internal implementation detail and are preserved in candidateKey/sourceId.
_PRODUCT_CATALOG_TABLES = {
    "lipsticks": "lipsticks", "blushes": "blushes", "eyeliner_mascara": "eyeliner_mascara",
    "eyebrows": "eyebrows", "eyeshadows": "eyeshadows", "foundations": "foundations",
    "highlighters": "highlighters", "contouring": "contouring", "products": "products",
}

_CATALOG_CACHE_TTL_SECONDS = 10.0
_catalog_cache_lock = threading.Lock()
_catalog_cache_expires_at = 0.0
_catalog_cache_items = None


def _invalidate_catalog_cache():
    global _catalog_cache_expires_at, _catalog_cache_items
    with _catalog_cache_lock:
        _catalog_cache_expires_at = 0.0
        _catalog_cache_items = None


def _catalog_rows(include_incomplete=False):
    global _catalog_cache_expires_at, _catalog_cache_items
    now = time.monotonic()
    with _catalog_cache_lock:
        if _catalog_cache_items is not None and now < _catalog_cache_expires_at:
            cached = [dict(item) for item in _catalog_cache_items]
            return cached if include_incomplete else [item for item in cached if _catalog_item_is_publishable(item)]
    selects = []
    for product_type, table in _PRODUCT_CATALOG_TABLES.items():
        if product_type == "products":
            selects.append("""
                SELECT c.id AS global_id, c.product_type, p.id AS source_id, p.name, ''::text AS brand,
                       p.price, p.description, p.image_url AS image_url, NULL::text AS source_url,
                       NULL::text AS sale_page_id, p.category, p.shades, NULL::text[] AS season_tags,
                       NULL::text AS undertone, NULL::text AS shade_code, NULL::text AS shade_name,
                       NULL::text AS series_id, NULL::integer AS depth_index,
                       1 AS version, NULL::text AS hex_primary, NULL::jsonb AS lab,
                        '[]'::jsonb AS palette_colors, NULL::text AS palette_image_url, '{}'::jsonb AS color_evidence, 'TWD'::text AS currency,
                       NULL::text AS sku, NULL::text AS source_site, NULL::text AS source_product_id,
                       TRUE AS in_stock, 'active'::text AS status, 'approved'::text AS review_status, TRUE AS recommendation_ready
                FROM public.product_catalog c JOIN public.products p ON c.product_type='products' AND c.source_id=p.id
            """)
        else:
            # Foundation codes have their own normalized field.  Other makeup
            # tables use the full official shade name as the public code; this
            # avoids the legacy 30-character lipstick column truncating names.
            shade_code = "p.shade_code" if product_type == "foundations" else "p.shade_name"
            series_id = "p.series_id" if product_type == "foundations" else "NULL::text"
            depth_index = "p.depth_index" if product_type == "foundations" else "NULL::integer"
            selects.append(f"""
                SELECT c.id AS global_id, c.product_type, p.id AS source_id, p.name, COALESCE(p.brand,'') AS brand,
                       p.price, p.description, p.image_webp_url AS image_url, p.source_url,
                       p.sale_page_id, p.category, NULL::jsonb AS shades, p.season_tags, p.undertone,
                       {shade_code} AS shade_code, p.shade_name,
                       {series_id} AS series_id, {depth_index} AS depth_index,
                       COALESCE(p.version, 1) AS version, p.hex_primary, p.lab,
                        p.palette_colors, p.palette_image_url, p.color_evidence, COALESCE(p.currency,'TWD') AS currency,
                       p.sku, p.source_site, p.source_product_id,
                       COALESCE(p.in_stock,FALSE) AS in_stock, COALESCE(p.status,'inactive') AS status,
                       COALESCE(p.review_status,'pending') AS review_status, COALESCE(p.recommendation_ready,FALSE) AS recommendation_ready
                FROM public.product_catalog c JOIN public.{table} p ON c.product_type='{product_type}' AND c.source_id=p.id
            """)
    rows = db.session.execute(db.text(" UNION ALL ".join(selects))).mappings().all()
    items = [_catalog_payload(row) for row in rows]
    _attach_foundation_shades(items)
    with _catalog_cache_lock:
        _catalog_cache_items = [dict(item) for item in items]
        _catalog_cache_expires_at = time.monotonic() + _CATALOG_CACHE_TTL_SECONDS
    _refresh_shade_neighbor_index([item for item in items if _catalog_item_is_publishable(item)])
    result = [dict(item) for item in items]
    return result if include_incomplete else [item for item in result if _catalog_item_is_publishable(item)]


def _refresh_shade_neighbor_index(publishable_items):
    """Recompute only shade neighbours affected by a catalogue change.

    Large rebuilds run in the background; a failure here must never take the
    storefront down, product pages then report the comparison as pending.
    """
    try:
        return shade_neighbor_index.refresh(publishable_items)
    except Exception:
        app.logger.exception("shade neighbour index refresh failed")
        return "pending"


def _catalog_availability_sets(catalog_items):
    """Return live source references and global ids without dropping stale member data."""
    source_references = {
        (str(item.get("type") or ""), int(item["sourceId"]))
        for item in catalog_items if item.get("sourceId") is not None
    }
    global_ids = {int(item["id"]) for item in catalog_items if item.get("id") is not None}
    return source_references, global_ids


def _catalog_payload(row):
    from color_contract import color_payload
    quality = color_payload(row)
    source_url = str(row["source_url"] or "").strip()
    frontend_price = _price_for_frontend(row["price"], row["currency"])
    palette_colors = row["palette_colors"] if isinstance(row["palette_colors"], list) else []
    if palette_colors:
        color_representation = "palette"
    elif row["hex_primary"]:
        color_representation = "single"
    elif str(row["shade_name"] or "").strip() == "官方單一規格":
        color_representation = "not_applicable"
    else:
        color_representation = "official_name_only"
    return {
        "id": int(row["global_id"]), "sourceId": int(row["source_id"]), "type": row["product_type"],
        "candidateKey": f"{row['product_type']}:{row['source_id']}",
        "name": row["name"] or "未命名商品", "brand": row["brand"] or "",
        "price": frontend_price["display"], "priceValue": frontend_price["amount"],
        "currency": frontend_price["currency"],
        "priceConverted": frontend_price["converted"],
        "priceNote": frontend_price["note"],
        "priceConversion": frontend_price["conversion"],
        "description": row["description"] or "暫無描述",
        # Brand CDNs block hotlinked images; serve the verified same-origin
        # copy when one is published and keep the original for admins/tools.
        "imageUrl": mirrored_image_url(row["image_url"] or ""),
        "image_url": mirrored_image_url(row["image_url"] or ""),
        "image_src": mirrored_image_url(row["image_url"] or ""),
        "sourceImageUrl": row["image_url"] or "",
        "sourceUrl": source_url if source_url.startswith(("https://", "http://")) else None,
        "sourceSite": row["source_site"] or None, "sourceProductId": row["source_product_id"] or None,
        "sku": row["sku"] or None,
        "salePageId": row["sale_page_id"] or None, "sale_page_id": row["sale_page_id"] or None,
        "category": row["category"] or "", "shades": row["shades"] or [],
        "seasonTags": row["season_tags"] or [], "undertone": row["undertone"] or "",
        "shadeCode": row["shade_code"] or None, "shadeName": row["shade_name"] or "",
        # Only a verified single-colour shade may participate in a shade
        # ladder.  Primers, removers and other colourless products are valid
        # catalogue rows, but must never become a fake brighter/deeper option.
        "seriesId": (row["series_id"] or None) if color_representation == "single" else None,
        "depthIndex": (int(row["depth_index"])
                       if color_representation == "single" and row["depth_index"] is not None
                       else None),
        "version": int(row["version"] or 1), "hex": row["hex_primary"],
        "hex_primary": row["hex_primary"], "lab": row["lab"] or None,
        "paletteColors": palette_colors,
        "paletteImageUrl": row["palette_image_url"] or None,
        "colorRepresentation": color_representation,
        "inStock": bool(row["in_stock"]), "status": row["status"], "reviewStatus": row["review_status"],
        # Complete single-colour rows with a real Lab triple are eligible for
        # colour matching.  A stale legacy default must not silently remove a
        # valid foundation shade from CIEDE2000 comparison.
        **quality,
        "displayReady": bool(row["status"] == "active" and row["review_status"] == "approved"),
        "styleRecommendationReady": bool(
            row["status"] == "active" and row["review_status"] == "approved" and row["in_stock"]),
        "recommendationReady": bool(
            quality["colorMatchReady"] if row["product_type"] == "foundations" else row["status"] == "active" and row[
                "review_status"] == "approved" and row["in_stock"]),
    }


def _attach_foundation_shades(items):
    """Attach the complete, ordered shade family to every foundation payload.

    ``depth_index`` is currently derived from official swatch Lab L* (light to
    deep), not copied from a brand-published ordinal.  Expose that provenance
    explicitly so the storefront uses "brighter/deeper alternative" wording
    and never presents the computed order as an official brand shade ladder.
    """
    by_series = {}
    for item in items:
        if (item.get("type") == "foundations"
                and (item.get("colorMatchReady") or item.get("colorReferenceReady"))
                and item.get("status") == "active" and item.get("reviewStatus") == "approved" and item.get("inStock")
                and item.get("seriesId")
                and item.get("hex_primary")
                and isinstance(item.get("lab"), list)
                and len(item["lab"]) == 3):
            by_series.setdefault(item["seriesId"], []).append(item)
    for members in by_series.values():
        members.sort(key=lambda member: (
            member.get("depthIndex") is None,
            member.get("depthIndex") if member.get("depthIndex") is not None else 10 ** 9,
            -(float(member["lab"][0]) if isinstance(member.get("lab"), list)
                                         and len(member["lab"]) == 3 else float("-inf")),
            str(member.get("shadeCode") or ""),
        ))
        shades = [{
            "id": member["id"],
            "shadeCode": member.get("shadeCode"),
            "depthIndex": member.get("depthIndex"),
            "lab": member.get("lab"),
            "hex": member.get("hex_primary"),
            "hex_primary": member.get("hex_primary"),
        } for member in members]
        for member in members:
            # Copy the list container so a consumer cannot mutate a sibling's
            # top-level array while normalizing its own response object.
            member["shades"] = list(shades)
            member["shadeCount"] = len(shades)
            member["depthIndexOfficial"] = False
            member["shadeOrderSource"] = "lab_lightness"


def _catalog_item_is_publishable(item):
    """Keep incomplete crawler rows out of every storefront/recommendation API."""
    required_text = ("name", "brand", "description", "imageUrl", "sourceUrl", "salePageId",
                     "category", "currency", "sku", "sourceProductId")
    colour_required = item.get("type") in {"foundations", "blushes", "lipsticks"}
    has_required_shade_identity = (
            not colour_required
            or bool(str(item.get("shadeName") or "").strip()
                    and str(item.get("shadeCode") or "").strip())
    )
    has_verified_colour = (
            item.get("type") not in {"foundations", "blushes", "lipsticks"}
            or item.get("colorRepresentation") in {"single", "palette", "not_applicable", "transparent",
                                                   "official_name_only"}
    )
    return (
            item.get("status") == "active"
            and item.get("reviewStatus") == "approved"
            and all(
        str(item.get(field) or "").strip() or (field == "imageUrl" and item.get("imageIdentityStatus") == "mismatch")
        for field in required_text)
            and float(item.get("priceValue") or 0) > 0
            and has_required_shade_identity
            and has_verified_colour
    )


def _catalog_item_by_id(product_id, include_incomplete=False):
    return next((item for item in _catalog_rows(include_incomplete=include_incomplete)
                 if item["id"] == product_id), None)


def _catalog_list_response():
    items = _catalog_rows()
    raw_category = request.args.get("category") or request.args.get("type")
    if raw_category:
        normalized_raw = raw_category.strip().lower().replace("-", "_").replace(" ", "_")
        category_types = {
            "底妝": "foundations", "粉底": "foundations", "唇彩": "lipsticks", "口紅": "lipsticks",
            "腮紅": "blushes", "眼影": "eyeshadows", "眼線/睫毛": "eyeliner_mascara",
            "眼線睫毛": "eyeliner_mascara", "修容": "contouring", "打亮": "highlighters",
            "高光": "highlighters", "眉毛彩妝": "eyebrows", "眉毛": "eyebrows", "眉妝": "eyebrows",
        }
        selected_type = (normalized_raw if normalized_raw in _PRODUCT_CATALOG_TABLES
                         else category_types.get(raw_category.strip()))
        if selected_type is None:
            normalized_category = cat_to_product_category(raw_category)
            selected_type = category_to_frontend_type(normalized_category)
        if selected_type not in _PRODUCT_CATALOG_TABLES:
            return error_response("INVALID_CATEGORY", "分類無效", 422)
        items = [item for item in items if item.get("type") == selected_type]
    brands = {
        value.strip().casefold() for value in (request.args.get("brand") or "").split(",")
        if value.strip()
    }
    if brands:
        items = [item for item in items if str(item.get("brand") or "").casefold() in brands]
    try:
        min_price = float(request.args["minPrice"]) if request.args.get("minPrice") not in {None, ""} else None
        max_price = float(request.args["maxPrice"]) if request.args.get("maxPrice") not in {None, ""} else None
    except (TypeError, ValueError):
        return error_response("INVALID_PRICE_RANGE", "價格必須是數字", 422)
    if ((min_price is not None and min_price < 0) or (max_price is not None and max_price < 0)
            or (min_price is not None and max_price is not None and min_price > max_price)):
        return error_response("INVALID_PRICE_RANGE", "價格區間無效", 422)
    if min_price is not None:
        items = [item for item in items if (_catalog_numeric_price(item.get("price")) or 0) >= min_price]
    if max_price is not None:
        items = [item for item in items if (_catalog_numeric_price(item.get("price")) or 0) <= max_price]
    raw_stock = request.args.get("inStock")
    if raw_stock is not None:
        stock_value = raw_stock.strip().casefold()
        if stock_value not in {"true", "false", "1", "0"}:
            return error_response("INVALID_FILTER", "inStock 必須是布林值", 400)
        expected_stock = stock_value in {"true", "1"}
        items = [item for item in items if item.get("inStock") is expected_stock]
    query = (request.args.get("query") or request.args.get("q") or "").strip().casefold()
    if query:
        items = [item for item in items if query in " ".join(
            str(item.get(key) or "") for key in ("name", "brand", "description", "salePageId")).casefold()]
    sort_aliases = {
        "default": "default", "relevance": "default", "id": "default",
        "price_asc": "price_asc", "price-asc": "price_asc", "priceAsc": "price_asc",
        "price_desc": "price_desc", "price-desc": "price_desc", "priceDesc": "price_desc",
        "newest": "newest", "name_asc": "name_asc", "name-asc": "name_asc",
        "name_desc": "name_desc", "name-desc": "name_desc",
    }
    requested_sort = request.args.get("sort", "default")
    sort_by = sort_aliases.get(requested_sort)
    if sort_by is None:
        return error_response("INVALID_SORT", "排序方式無效", 422)
    if sort_by == "price_asc":
        items.sort(
            key=lambda item: (_catalog_numeric_price(item.get("price")) or 0, str(item.get("name") or "").casefold(),
                              item["id"]))
    elif sort_by == "price_desc":
        items.sort(
            key=lambda item: (-(_catalog_numeric_price(item.get("price")) or 0), str(item.get("name") or "").casefold(),
                              item["id"]))
    elif sort_by == "name_asc":
        items.sort(key=lambda item: (str(item.get("name") or "").casefold(), item["id"]))
    elif sort_by == "name_desc":
        items.sort(key=lambda item: (str(item.get("name") or "").casefold(), item["id"]), reverse=True)
    elif sort_by == "newest":
        items.sort(key=lambda item: item["id"], reverse=True)
    else:
        items.sort(key=lambda item: item["id"])
    prices = [_catalog_numeric_price(item.get("price")) for item in items]
    prices = [price for price in prices if price is not None]
    facets = {
        "brands": sorted({item.get("brand") for item in items if item.get("brand")}, key=str.casefold),
        "categories": sorted({item.get("category") for item in items if item.get("category")}),
        "priceRange": {"min": min(prices) if prices else None, "max": max(prices) if prices else None},
    }
    applied_filters = {
        "brands": sorted(brands), "category": raw_category or None,
        "minPrice": min_price, "maxPrice": max_price, "sort": sort_by,
    }
    raw_limit = request.args.get("limit")

    def response_payload(page_items, next_cursor, **extra):
        payload = {
            "ok": True,
            "items": page_items,
            "total": len(items),
            "nextCursor": next_cursor,
            "facets": facets,
            "appliedFilters": applied_filters,
            **extra,
        }
        # ``products`` used to duplicate the complete items array and doubled
        # every catalog response.  The deployed storefront reads ``items``
        # first.  Keep an explicit compatibility switch for older clients
        # without penalising every mobile request.
        legacy_aliases = (request.args.get("legacyAliases") or "").strip().casefold()
        if legacy_aliases in {"1", "true", "yes"}:
            payload["products"] = page_items
        return payload

    if raw_limit is None:
        return jsonify(response_payload(items, None))
    try:
        limit = int(raw_limit)
        if not 1 <= limit <= 200:
            raise ValueError
        cursor_value = request.args.get("cursor")
        if cursor_value and cursor_value.isdigit() and sort_by == "default":
            offset = next((index for index, item in enumerate(items) if item["id"] > int(cursor_value)), len(items))
        elif cursor_value:
            import base64
            offset = int(base64.urlsafe_b64decode(cursor_value + "==").decode())
        else:
            offset = 0
        if offset < 0:
            raise ValueError
    except (ValueError, TypeError):
        return error_response("INVALID_PAGINATION", "limit 或 cursor 格式無效", 400)
    page = items[offset:offset + limit]
    if offset + limit < len(items):
        import base64
        next_cursor = base64.urlsafe_b64encode(str(offset + limit).encode()).decode().rstrip("=")
    else:
        next_cursor = None
    return jsonify(response_payload(page, next_cursor, query=query or None))


def _catalog_numeric_price(value):
    match = re.search(r"\d[\d,.]*", str(value or ""))
    return float(match.group(0).replace(",", "")) if match else None


def _catalog_similarity(anchor, candidate):
    anchor_lab, candidate_lab = anchor.get("lab"), candidate.get("lab")
    color_distance = delta_e(tuple(anchor_lab), tuple(candidate_lab)) if (
            isinstance(anchor_lab, (list, tuple)) and len(anchor_lab) == 3
            and isinstance(candidate_lab, (list, tuple)) and len(candidate_lab) == 3
    ) else None
    color_score = max(0.0, 1.0 - color_distance / 30.0) if color_distance is not None else 0.5
    category_score = 1.0 if cat_to_product_category(
        anchor.get("category") or anchor.get("type")) == cat_to_product_category(
        candidate.get("category") or candidate.get("type")) else 0.0
    brand_score = 1.0 if anchor.get("brand") and str(anchor["brand"]).casefold() == str(
        candidate.get("brand") or "").casefold() else 0.5
    anchor_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", " ".join(
        str(anchor.get(k) or "") for k in ("name", "description", "undertone")).casefold()))
    candidate_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", " ".join(
        str(candidate.get(k) or "") for k in ("name", "description", "undertone")).casefold()))
    style_score = len(anchor_tokens & candidate_tokens) / len(
        anchor_tokens | candidate_tokens) if anchor_tokens | candidate_tokens else 0.5
    anchor_price, candidate_price = _catalog_numeric_price(anchor.get("price")), _catalog_numeric_price(
        candidate.get("price"))
    price_score = (max(0.0, 1.0 - abs(anchor_price - candidate_price) / max(anchor_price, candidate_price, 1.0))
                   if anchor_price is not None and candidate_price is not None else 0.5)
    total = 0.40 * color_score + 0.25 * style_score + 0.20 * category_score + 0.15 * price_score
    if color_distance is not None and candidate_lab[0] > anchor_lab[0] + 1:
        relation, text = "lighter_variant", "同品類且顏色較明亮"
    elif color_distance is not None and candidate_lab[0] < anchor_lab[0] - 1:
        relation, text = "darker_variant", "同品類且顏色較深"
    elif brand_score == 1.0:
        relation, text = "same_brand", "同品牌的其他選擇"
    elif candidate_price is not None and anchor_price is not None and candidate_price < anchor_price:
        relation, text = "budget_alt", "相近妝感且價格較親民"
    else:
        relation, text = "same_style_alt", "同品類的相似風格選擇"
    return total, {"color": round(color_score, 4), "style": round(style_score, 4),
                   "category": round(category_score, 4), "brand": round(brand_score, 4),
                   "price": round(price_score, 4)}, relation, text


def _comparable_foundation_lab(item):
    return _shade_comparable_lab(item)


def _is_https_url(value):
    """Accept only ordinary HTTPS URLs; palette assets must not be blank or HTTP."""
    parsed = urlparse(str(value or "").strip())
    return parsed.scheme == "https" and bool(parsed.netloc) and not parsed.username and not parsed.password


def _cross_brand_shade_presentation(distance):
    """Return a consistent, customer-facing similarity score for every match."""
    match_percent = max(0, min(100, round(100 - distance * 4)))
    if distance <= 2.0:
        tier = "strong_match"
    elif distance <= 5.0:
        tier = "close_match"
    else:
        tier = "reference_only"
    return {
        "deltaE": round(float(distance), 2),
        "matchPercent": match_percent,
        "displayScore": True,
        "recommendationLabel": f"推薦契合度 {match_percent}%",
        "tier": tier,
    }


def _foundation_shade_ladder(source, candidates):
    """Return the three customer-facing colour steps for one target brand.

    A brand / series name is never used as a colour rule.  ``closest`` is the
    best CIEDE2000 match; lighter and darker candidates additionally have to
    keep their a*/b* colour direction close to the source.  This lets a
    visitor compare MAC, NARS or any other available brand by the same
    contract, while avoiding a pink/cool shade being presented as a lighter
    version of a yellow/warm shade merely because its L* is higher.
    """
    source_lab = _comparable_foundation_lab(source)
    if source_lab is None:
        return [], ["lighter", "closest", "darker"]

    ranked = []
    for candidate in candidates:
        candidate_lab = _comparable_foundation_lab(candidate)
        if candidate_lab is None:
            continue
        distance = float(delta_e(source_lab, candidate_lab))
        lightness = float(candidate_lab[0] - source_lab[0])
        # Compare colour direction at the same lightness.  This is the same
        # guard used by the neighbour index, kept here because target-brand
        # requests intentionally compare one source only.
        tone_distance = delta_e(source_lab, (source_lab[0], candidate_lab[1], candidate_lab[2]))
        ranked.append((distance, lightness, float(tone_distance), candidate))
    ranked.sort(key=lambda row: _shade_sort_key(row[0], row[3]))
    if not ranked:
        return [], ["lighter", "closest", "darker"]

    selected, used_shades = [], set()
    rules = (
        ("lighter", "較淺相近色", lambda lightness, tone, distance: (
                lightness >= 1.0 and tone <= 3.0 and distance <= 10.0)),
        ("closest", "最相近色", lambda lightness, tone, distance: True),
        ("darker", "較深相近色", lambda lightness, tone, distance: (
                lightness <= -1.0 and tone <= 3.0 and distance <= 10.0)),
    )
    missing = []
    for relation, label, eligible in rules:
        match = next((row for row in ranked
                      if (str(row[3].get("brand") or "").casefold(),
                          str(row[3].get("shadeCode") or row[3].get("shadeName") or row[3].get("id")).casefold())
                      not in used_shades
                      and eligible(row[1], row[2], row[0])), None)
        used_fallback = False
        if match is None and relation != "closest":
            # The visitor explicitly chose HEX reference comparison.  A
            # catalogue sometimes has no colour-direction-safe shade in one
            # direction even though it has a full shade range.  Keep the
            # strict result first; then fill that direction from the same
            # brand's converted swatch, visibly marked as a reference rather
            # than pretending it passed the undertone guard.
            direction = 1 if relation == "lighter" else -1
            match = next((row for row in ranked
                          if (str(row[3].get("brand") or "").casefold(),
                              str(row[3].get("shadeCode") or row[3].get("shadeName") or row[3].get("id")).casefold())
                          not in used_shades
                          and row[1] * direction >= 1.0), None)
            used_fallback = match is not None
        if match is None and relation != "closest":
            # A catalogue can legitimately contain no swatch on one side of
            # the source depth (for example the imported range starts lighter
            # than NC35).  The selector still promises three usable choices,
            # so use the next closest *different* shade as a clearly labelled
            # reference instead of leaving the brand with an empty third card.
            match = next((row for row in ranked
                          if (str(row[3].get("brand") or "").casefold(),
                              str(row[3].get("shadeCode") or row[3].get("shadeName") or row[3].get("id")).casefold())
                          not in used_shades), None)
            used_fallback = match is not None
        if match is None:
            missing.append(relation)
            continue
        distance, lightness, tone_distance, candidate = match
        shade_identity = (str(candidate.get("brand") or "").casefold(),
                          str(candidate.get("shadeCode") or candidate.get("shadeName") or candidate.get(
                              "id")).casefold())
        used_shades.add(shade_identity)
        output_label = (f"{label}（色卡參考）" if used_fallback else label)
        selected.append({
            **candidate,
            "shadeMatch": {
                **_cross_brand_shade_presentation(distance),
                "relation": relation,
                "label": output_label,
                "lightnessDifference": round(lightness, 2),
                "toneDeltaE": round(tone_distance, 2),
                "toneGuardPassed": not used_fallback,
                "referenceOnly": used_fallback or not candidate.get("colorMatchReady"),
            },
        })
    return selected, missing


@app.route('/api/products/<int:product_id>/shade-matches', methods=['GET'])
def get_cross_brand_foundation_shade_matches_api(product_id):
    """Return the closest foundation shades from brands other than the source."""
    source = _catalog_item_by_id(product_id)
    if source is None:
        return error_response("PRODUCT_NOT_FOUND", "商品不存在", 404)
    if source.get("type") != "foundations":
        return error_response(
            "SHADE_MATCH_NOT_SUPPORTED", "跨品牌色號比較目前僅支援底妝", 422
        )
    source_lab = _comparable_foundation_lab(source)
    if source_lab is None:
        return error_response("SHADE_COLOR_UNAVAILABLE", "來源色號缺少可比較的色彩資料", 422)

    try:
        limit = int(request.args.get("limit", 5))
    except (TypeError, ValueError):
        return error_response("INVALID_LIMIT", "limit 必須是整數", 400)
    if not 1 <= limit <= 20:
        return error_response("INVALID_LIMIT", "limit 必須介於 1 至 20", 400)

    target_brand = (request.args.get("targetBrand") or "").strip()
    source_brand = str(source.get("brand") or "").strip()
    catalog = _catalog_rows()
    precomputed = None
    if not target_brand:
        precomputed = shade_neighbor_index.cross_brand_ranking(source, limit)
        if precomputed is None and _refresh_shade_neighbor_index(catalog) == "ready":
            precomputed = shade_neighbor_index.cross_brand_ranking(source, limit)
    all_ranked_for_ladder = None
    if precomputed is not None:
        by_id = {item.get("id"): item for item in catalog}
        ranked = [(distance, by_id[candidate_id]) for distance, candidate_id in precomputed["ranking"]
                  if candidate_id in by_id]
        available_target_brands = precomputed["availableTargetBrands"]
        total_candidates = precomputed["totalCandidates"]
    else:
        # Brand-filtered queries (or a stale index) compare one source only.
        # Unlike the compact cross-brand index, explicitly selecting the
        # source brand is valid: it is how the product page shows its own
        # lighter / closest / darker colour ladder after a visitor returns
        # from another brand.
        source_is_concealer = _is_concealer_product(source)
        ranked = []
        brands = set()
        for item in catalog:
            item_brand = str(item.get("brand") or "").strip()
            if (not _is_shade_match_candidate(item)
                    or _is_concealer_product(item) != source_is_concealer):
                continue
            # The legacy no-filter endpoint is genuinely cross-brand, so keep
            # its response stable.  Same-brand entries are allowed only for
            # an explicit brand selection, where they form that brand's own
            # three-step ladder.
            if not target_brand and (item.get("id") == product_id
                                     or item_brand.casefold() == source_brand.casefold()):
                continue
            brands.add(item_brand)
            if target_brand and item_brand.casefold() != target_brand.casefold():
                continue
            ranked.append((float(delta_e(source_lab, _comparable_foundation_lab(item))), item))
        ranked.sort(key=lambda pair: _shade_sort_key(*pair))
        available_target_brands = sorted(brands, key=str.casefold)
        total_candidates = len(ranked)
        all_ranked_for_ladder = list(ranked)
        ranked = ranked[:limit]
    items = [
        {**item, "shadeMatch": _cross_brand_shade_presentation(distance)}
        for distance, item in ranked
    ]
    # The selector has an explicit target brand: return a stable three-step
    # ladder as well as the legacy ranked ``items`` list.  Existing clients
    # keep working, while the storefront can render the promised three colour
    # choices for every brand without doing colour work in JavaScript.
    shade_ladder, missing_shade_steps = ([], [])
    if target_brand:
        ladder_candidates = [item for _, item in (all_ranked_for_ladder or ranked)]
        shade_ladder, missing_shade_steps = _foundation_shade_ladder(source, ladder_candidates)
    return jsonify({
        "ok": True,
        "comparisonMethod": "CIEDE2000",
        "source": {
            "id": source["id"], "brand": source_brand,
            "shadeCode": source.get("shadeCode"), "shadeName": source.get("shadeName"),
            "seriesId": source.get("seriesId"), "lab": list(source_lab),
        },
        "targetBrand": target_brand or None,
        "availableTargetBrands": available_target_brands,
        "items": items,
        "shadeLadder": shade_ladder,
        "missingShadeSteps": missing_shade_steps,
        "totalCandidates": total_candidates,
        "precomputed": precomputed is not None,
    }), 200


@app.route('/api/products/<int:product_id>/similar', methods=['GET'])
def get_similar_products_api(product_id):
    anchor = _catalog_item_by_id(product_id)
    if anchor is None:
        return error_response("NOT_FOUND", "找不到商品", 404)
    try:
        limit = int(request.args.get("limit", 6))
    except (TypeError, ValueError):
        return error_response("INVALID_LIMIT", "limit 必須是整數", 400)
    if not 1 <= limit <= 20:
        return error_response("INVALID_LIMIT", "limit 必須介於 1 至 20", 400)
    category = cat_to_product_category(anchor.get("category") or anchor.get("type"))
    candidates = [item for item in _catalog_rows() if item["id"] != product_id
                  and item.get("inStock") and item.get("status") == "active"
                  and item.get("reviewStatus") == "approved"
                  and cat_to_product_category(item.get("category") or item.get("type")) == category]
    ranked = []
    for item in candidates:
        similarity, breakdown, relation, reason = _catalog_similarity(anchor, item)
        ranked.append({**item, "similarity": round(similarity, 4),
                       "similarityBreakdown": breakdown, "relation": relation,
                       "matchReason": reason})
    ranked.sort(key=lambda item: (-item["similarity"], item["id"]))
    return jsonify({"anchor": {"id": anchor["id"], "name": anchor["name"], "type": anchor["type"]},
                    "similar": ranked[:limit]}), 200


def _catalog_update_response(product_id, data):
    item = _catalog_item_by_id(product_id)
    if item is None:
        return error_response("NOT_FOUND", "找不到商品", 404)
    if not isinstance(data, dict):
        return error_response("INVALID_PAYLOAD", "請提供 JSON 商品資料", 400)
    expected = request.headers.get("If-Match", "").strip().strip('"')
    if expected and expected != str(item["version"]):
        return error_response("VERSION_CONFLICT", "商品已被其他管理員更新，請重新載入", 409)
    table = _PRODUCT_CATALOG_TABLES[item["type"]]
    column_map = {"name": "name", "price": "price", "description": "description"}
    if item["type"] == "products":
        column_map.update({"image_url": "image_url", "category": "category", "shades": "shades"})
    else:
        column_map.update({"image_url": "image_webp_url", "source_url": "source_url"})
    if item["type"] == "foundations":
        column_map.update({
            "shadeCode": "shade_code", "shade_code": "shade_code",
            "shadeName": "shade_name", "shade_name": "shade_name",
            "seriesId": "series_id", "series_id": "series_id",
            "depthIndex": "depth_index", "depth_index": "depth_index",
            "undertone": "undertone",
        })
    updates = {column_map[key]: value for key, value in data.items() if key in column_map}
    if (column_map.get("image_url") in updates
            and updates[column_map["image_url"]] == item.get("imageUrl") != item.get("sourceImageUrl")):
        # An admin form echoing the displayed mirror must not replace the
        # original brand image URL stored in the database.
        updates.pop(column_map["image_url"])
    if not updates:
        return error_response("NO_UPDATABLE_FIELDS", "沒有可更新欄位", 400)
    if "depth_index" in updates:
        value = updates["depth_index"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            return error_response("INVALID_DEPTH_INDEX", "depthIndex 必須是大於或等於 0 的整數", 400)
    assignments = ", ".join(f"{column} = :{column}" for column in updates)
    params = {**updates, "source_id": item["sourceId"]}
    if item["type"] != "products":
        assignments += ", version = version + 1"
        params["version"] = item["version"]
        where = "id = :source_id AND version = :version"
    else:
        where = "id = :source_id"
    result = db.session.execute(db.text(f"UPDATE public.{table} SET {assignments} WHERE {where}"), params)
    if result.rowcount != 1:
        db.session.rollback()
        return error_response("VERSION_CONFLICT", "商品已被其他管理員更新，請重新載入", 409)
    _write_product_audit(
        f"{item['type']}:{item['sourceId']}", "update", _product_delete_actor(),
        before_data=item, after_data=updates, product_type=item["type"],
    )
    db.session.commit()
    _invalidate_catalog_cache()
    updated = _catalog_item_by_id(product_id)
    response = jsonify(updated)
    response.headers["ETag"] = str(updated["version"])
    return response, 200


def recommendation_candidates(categories=None):
    """Build recommendation candidates from the live catalog projection.

    The catalog query deliberately selects only the product contract columns.
    Querying every SQLAlchemy category model here previously selected legacy
    vector columns (for example ``qdrant_vector_12d``) that are not present in
    the current product database, making ``/recommend-products`` fail even
    though ``/api/products`` was healthy.
    """
    allowed = {cat_to_product_category(c) for c in categories} if categories else None
    candidates = []
    for catalog_item in _catalog_rows():
        category = cat_to_product_category(
            catalog_item.get("category") or catalog_item.get("type")
        )
        if allowed and category not in allowed:
            continue
        # 可否推薦、與色彩是否通過數值驗證，是兩件事。
        # `recommendationReady` 由資料庫觸發器計算，條件包含
        # `color_evidence.status = 'verified_official_numeric'`，
        # 拿它當候選集門檻會讓 3,981 筆上架商品只剩 381 筆（9.6%）進得了推薦，
        # 打亮整個品類是 0 筆。缺色值的商品仍有名稱、品牌、妝效與風格標籤，
        # 足以做風格推薦；色彩比對另由 `lab` 是否存在把關（見 _cross_brand_*）。
        if (not catalog_item.get("inStock")
                or catalog_item.get("status") != "active"
                or catalog_item.get("reviewStatus") != "approved"):
            continue
        product_type = str(catalog_item.get("type") or "products")
        candidates.append({
            **catalog_item,
            "category": category,
            "type": product_type,
            "tags": [category, product_type],
            "inStock": True,
            "imageUrl": catalog_item.get("imageUrl") or "",
            "image_src": catalog_item.get("imageUrl") or "",
            "productUrl": catalog_item.get("sourceUrl") or "",
            "sourceUrl": catalog_item.get("sourceUrl") or "",
            "coverageCategory": product_type,
            "currency": catalog_item.get("currency") or "TWD",
        })
    return candidates


def recommendation_behavior_profile(actor, candidates):
    """Build a minimal, server-side preference profile for ranking.

    Only the signed-in member's existing favourites, try-on saves and cart are
    read.  No email, image, token or raw event history is sent into the
    recommendation engine or returned to the browser.
    """
    if actor is None:
        return {"interactionCount": 0, "categoryAffinities": {}, "brandAffinities": {}}

    by_source = {str(item.get("candidateKey")): item for item in candidates}
    category_totals, brand_totals = {}, {}
    signal_count = 0

    def add_signal(item_type, item_id, weight):
        nonlocal signal_count
        candidate = by_source.get(f"{item_type}:{item_id}")
        if candidate is None:
            return
        signal_count += 1
        category = str(candidate.get("category") or "").casefold()
        brand = str(candidate.get("brand") or "").casefold()
        if category:
            category_totals[category] = category_totals.get(category, 0.0) + weight
        if brand:
            brand_totals[brand] = brand_totals.get(brand, 0.0) + weight

    for item in Favorites.query.filter_by(member_id=actor.phone_number).order_by(Favorites.created_at.desc()).limit(50):
        add_signal(item.item_type, item.item_id, 1.0)
    for item in TryonRecords.query.filter_by(member_id=actor.phone_number).order_by(
            TryonRecords.created_at.desc()).limit(50):
        add_signal(item.item_type, item.item_id, 0.8)
    for item in CartItem.query.filter_by(member_email=actor.email).order_by(CartItem.updated_at.desc()).limit(50):
        # Cart items historically do not retain item_type.  Match their global
        # catalog id only when that id maps to exactly one eligible candidate.
        matches = [candidate for candidate in candidates if candidate.get("id") == item.item_id]
        if len(matches) == 1:
            add_signal(matches[0].get("type"), matches[0].get("sourceId"), 0.65)

    def normalize(values):
        maximum = max(values.values(), default=0.0)
        return {key: round(value / maximum, 4) for key, value in values.items()} if maximum else {}

    return {
        "interactionCount": signal_count,
        "categoryAffinities": normalize(category_totals),
        "brandAffinities": normalize(brand_totals),
    }


@app.route('/recommend-products', methods=['POST'])
def recommend_products_api():
    """Recommend only products that currently exist in the shared database."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("INVALID_REQUEST", "請提供格式正確的 JSON 物件", 400)
    analysis_package = payload.get("analysisPackage")
    if not isinstance(analysis_package, dict) or not analysis_package or not isinstance(
            analysis_package.get("faceAnalysis"), dict):
        return error_response("INVALID_ANALYSIS_PACKAGE", "缺少臉部分析資料包", 422)
    raw_limit = payload.get("limit", 12)
    if isinstance(raw_limit, bool) or not isinstance(raw_limit, int):
        return error_response("INVALID_REQUEST", "limit 必須是整數", 400)
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return error_response("INVALID_REQUEST", "limit 必須是整數", 400)
    if not 1 <= limit <= 50:
        return error_response("INVALID_REQUEST", "limit 必須介於 1 至 50", 400)
    try:
        candidates = recommendation_candidates()
        actor, _ = authenticated_member()
        behavior_profile = recommendation_behavior_profile(actor, candidates)
        result = recommend_products(
            analysis_package, candidates, limit,
            recommendation_options=payload.get("recommendationOptions"),
            behavior_profile=behavior_profile,
        )
    except AnalysisContractError as exc:
        code = str(exc)
        messages = {
            "UNKNOWN_MAKEUP_STYLE": "找不到妝容風格",
            "INVALID_ANALYSIS_PACKAGE": "臉部分析資料包格式無效",
            "INVALID_FACE_ANALYSIS": "缺少臉部分析資料",
            "IDENTITY_DATA_NOT_ALLOWED": "分析資料不得包含身分、憑證或原始影像資料",
            "INVALID_REQUEST": "推薦選項格式或範圍無效",
        }
        return error_response(code, messages.get(code, "推薦資料格式無效"), 400 if code == "INVALID_REQUEST" else 422)
    except OperationalError as exc:
        app.logger.exception("product recommendation database error")
        if "timeout" in str(getattr(exc, "orig", exc)).lower():
            return error_response("PRODUCT_DB_TIMEOUT", "商品資料庫查詢逾時", 504)
        return error_response("PRODUCT_DB_UNAVAILABLE", "商品資料庫暫時不可用", 502)
    except Exception:
        app.logger.exception("product recommendation query failed")
        return error_response("PRODUCT_DB_UNAVAILABLE", "商品資料庫暫時不可用", 502)
    if not result["products"]:
        return jsonify({"success": True, "status": "completed", "analysisPackage": {
            "id": analysis_package.get("id"), "schemaVersion": analysis_package.get("schemaVersion"),
            "style": analysis_package.get("style"), "faceAnalysis": analysis_package.get("faceAnalysis"),
            "recommendations": {
                "products": [], "fallbackUsed": result["fallbackUsed"],
                "fallbackReason": result["fallbackReason"], "fallbackReasons": result["fallbackReasons"],
                "coverage": result["coverage"], "skinToneLabReliable": result["skinToneLabReliable"],
                "colorDifferencePolicy": result["colorDifferencePolicy"],
                "foundationMatchStatus": result["foundationMatchStatus"],
                "foundationCrossBrandAlternatives": result["foundationCrossBrandAlternatives"],
                "primary": [], "alternates": [], "threshold": result["threshold"],
                "personalizationInputs": result["personalizationInputs"],
                "personalization": result["personalization"], "shadeRecommendation": None,
            },
        }, "products": [], "code": "RECOMMENDATION_EMPTY",
                        "fallbackUsed": result["fallbackUsed"], "fallbackReason": result["fallbackReason"],
                        "fallbackReasons": result["fallbackReasons"], "coverage": result["coverage"],
                        "skinToneLabReliable": result["skinToneLabReliable"],
                        "colorDifferencePolicy": result["colorDifferencePolicy"],
                        "foundationMatchStatus": result["foundationMatchStatus"],
                        "foundationCrossBrandAlternatives": result["foundationCrossBrandAlternatives"]}), 200
    response_package = {
        "id": analysis_package.get("id"),
        "schemaVersion": analysis_package.get("schemaVersion"),
        "style": analysis_package.get("style"),
        "faceAnalysis": analysis_package.get("faceAnalysis"),
        "recommendations": {
            "products": result["products"], "fallbackUsed": result["fallbackUsed"],
            "fallbackReason": result["fallbackReason"], "coverage": result["coverage"],
            "fallbackReasons": result["fallbackReasons"],
            "skinToneLabReliable": result["skinToneLabReliable"],
            "colorDifferencePolicy": result["colorDifferencePolicy"],
            "foundationMatchStatus": result["foundationMatchStatus"],
            "primary": result["primary"], "alternates": result["alternates"], "threshold": result["threshold"],
            "personalizationInputs": result["personalizationInputs"],
            "personalization": result["personalization"],
            "shadeRecommendation": result["shadeRecommendation"],
            "foundationCrossBrandAlternatives": result["foundationCrossBrandAlternatives"],
        },
    }
    return jsonify({
        "success": True, "status": "completed", "analysisPackage": response_package,
        "products": result["products"], "fallbackUsed": result["fallbackUsed"],
        "fallbackReason": result["fallbackReason"], "coverage": result["coverage"],
        "fallbackReasons": result["fallbackReasons"],
        "styleTagFallbackUsed": result["styleTagFallbackUsed"],
        "skinToneLabReliable": result["skinToneLabReliable"],
        "colorDifferencePolicy": result["colorDifferencePolicy"],
        "foundationMatchStatus": result["foundationMatchStatus"],
        "foundationCrossBrandAlternatives": result["foundationCrossBrandAlternatives"],
        "personalizationInputs": result["personalizationInputs"],
        "personalization": result["personalization"],
    }), 200


@app.route('/products-page')
@app.route('/products-page/<category_type>')
def products_page(category_type='lipsticks'):
    selected = find_makeup_category(category_type) or MAKEUP_CATEGORIES[0]
    page = request.args.get("page", 1, type=int)
    pagination = selected["model"].query.order_by(selected["model"].id.desc()).paginate(page=page, per_page=24,
                                                                                        error_out=False)
    products = [product_card_payload(item, selected["type"]) for item in pagination.items]
    return render_template("products.html", title="商品推薦",
                           categories=[category_payload(c) for c in MAKEUP_CATEGORIES],
                           selected_category=category_payload(selected), products=products, pagination=pagination)


@app.route('/tryon-recommendations')
def tryon_recommendations_page():
    return render_template("tryon_recommendations.html", title="試妝色彩推薦")


def decode_text(data):
    if isinstance(data, bytes):
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return ""
    return data


@app.route('/api/products/all', methods=['GET'])
def get_all_makeup_categories():
    return jsonify({"categories": [category_payload(c) for c in MAKEUP_CATEGORIES]})


def _legacy_category_item_payload(item, category):
    """Keep legacy category routes usable without losing price provenance."""
    frontend_price = _price_for_frontend(
        getattr(item, 'price', None), getattr(item, 'currency', 'TWD')
    )
    return {
        "id": item.id, "type": category["type"],
        "brand": getattr(item, 'brand', ''),
        "name": getattr(item, 'name', '') or getattr(item, 'product_name', '') or '未命名商品',
        "price": frontend_price["display"],
        "priceValue": frontend_price["amount"],
        "currency": frontend_price["currency"],
        "priceConverted": frontend_price["converted"],
        "priceNote": frontend_price["note"],
        "priceConversion": frontend_price["conversion"],
        "description": getattr(item, 'description', ''),
        "image_url": mirrored_image_url(getattr(item, 'image_webp_url', '') or getattr(item, 'image_url', '')),
        "lab_json": decode_text(getattr(item, 'lab', '')),
        "qdrant_vector_12d": get_product_vector(item),
        "sale_page_id": getattr(item, 'sale_page_id', ''),
    }


for cat in MAKEUP_CATEGORIES:
    def make_route(category):
        def route():
            items = category["model"].query.all()
            return jsonify({"products": [
                _legacy_category_item_payload(item, category) for item in items
            ]})

        route.__name__ = f"get_{category['type']}"
        return route


    app.route(cat["endpoint"], methods=['GET'])(make_route(cat))


# ========== 簽到、任務、主題、推薦、收藏、歷史、購物車 ==========
@app.route('/api/members/<path:email>/check-in', methods=['GET'])
def get_checkin_status(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    today = _taipei_today()
    dc = DailyCheckin.query.filter_by(member_email=target_email, checkin_date=today).first()
    return jsonify({
        "checkedToday": dc is not None,
        "streak": dc.streak if dc else 0,
        "awarded": dc.awarded if dc else 0
    })


@app.route('/api/members/<path:email>/check-in', methods=['POST'])
def do_checkin(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    today = _taipei_today()
    existing = DailyCheckin.query.filter_by(member_email=target_email, checkin_date=today).first()
    if existing:
        return jsonify({"checkedToday": True, "awarded": 0, "streak": existing.streak}), 200
    yesterday = today - timedelta(days=1)
    prev = DailyCheckin.query.filter_by(member_email=target_email, checkin_date=yesterday).first()
    streak = (prev.streak or 0) + 1 if prev else 1
    base_award = 10
    bonus = _checkin_streak_bonus(streak)
    total_award = base_award + bonus
    dc = DailyCheckin(member_email=target_email, checkin_date=today, streak=streak, awarded=total_award)
    db.session.add(dc)
    reason = "check_in"
    if bonus > 0:
        reason = f"check_in_streak_bonus_{streak}d"
    balance = add_points_transaction(target_email, total_award, reason, commit=False)
    if not balance:
        db.session.rollback()
        return error_response("ERROR", "錯誤", 500)
    db.session.commit()
    return jsonify({
        "checkedToday": True, "streak": streak,
        "awarded": total_award, "streakBonus": bonus,
        "balance": balance,
        "lifetime": (Members.query.filter_by(email=target_email).first().lifetime_points or 0)
    }), 200


def _checkin_streak_bonus(streak):
    if streak >= 30: return 100
    if streak >= 14: return 40
    if streak >= 7: return 20
    if streak >= 3: return 5
    return 0


TASK_REWARDS = {
    "first_analysis": 20, "first_favorite": 10,
    "first_referral": 20, "daily_checkin": 5
}


def _task_claim_date(task_id, today=None):
    return (today or _taipei_today()) if task_id == "daily_checkin" else ONE_TIME_TASK_DATE


def _task_done_map(member, today=None):
    today = today or _taipei_today()
    return {
        "first_analysis": AnalysisHistory.query.filter_by(member_email=member.email).first() is not None,
        "first_favorite": Favorites.query.filter_by(member_id=member.phone_number).first() is not None,
        "first_referral": Referral.query.filter_by(referrer_email=member.email).first() is not None,
        "daily_checkin": DailyCheckin.query.filter_by(
            member_email=member.email, checkin_date=today
        ).first() is not None,
    }


@app.route('/api/members/<path:email>/tasks', methods=['GET'])
def get_tasks(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    member = Members.query.filter_by(email=target_email).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    today = _taipei_today()
    done_map = _task_done_map(member, today)
    claimed = TaskClaim.query.filter_by(member_email=target_email).all()
    claimed_set = {
        t.task_id for t in claimed
        if t.claim_date == _task_claim_date(t.task_id, today)
    }
    return jsonify({
        "tasks": [
            {
                "taskId": tid,
                "reward": rew,
                "done": done_map.get(tid, False),
                "claimed": tid in claimed_set,
            }
            for tid, rew in TASK_REWARDS.items()
        ]
    })


@app.route('/api/members/<path:email>/tasks/<taskId>/claim', methods=['POST'])
def claim_task(email, taskId):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    if taskId not in TASK_REWARDS:
        return error_response("INVALID_TASK", "無效任務", 400)
    claim_date = _task_claim_date(taskId)
    try:
        member = Members.query.filter_by(email=target_email).with_for_update().first()
        if not member:
            return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
        if not _task_done_map(member).get(taskId, False):
            return error_response("TASK_NOT_COMPLETED", "任務尚未完成", 409)
        existing = TaskClaim.query.filter_by(
            member_email=target_email, task_id=taskId, claim_date=claim_date
        ).first()
        if existing:
            return error_response("ALREADY_CLAIMED", "已領取", 409)
        reward = TASK_REWARDS[taskId]
        db.session.add(TaskClaim(member_email=target_email, task_id=taskId, claim_date=claim_date))
        balance = add_points_transaction(target_email, reward, f"task_{taskId}", commit=False)
        db.session.commit()
        return jsonify({"claimed": True, "taskId": taskId, "reward": reward, "balance": balance}), 200
    except IntegrityError:
        db.session.rollback()
        return error_response("ALREADY_CLAIMED", "已領取", 409)
    except Exception:
        db.session.rollback()
        return error_response("TASK_CLAIM_FAILED", "任務領取失敗", 500)


THEME_PRICES = {"classic": 0, "rose": 80, "jade": 120, "noir": 180}


@app.route('/api/members/<path:email>/theme-shop/<themeId>/redeem', methods=['POST'])
def redeem_theme(email, themeId):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    if themeId not in THEME_PRICES:
        return error_response("INVALID_THEME", "無效主題", 400)
    price = THEME_PRICES[themeId]
    if price == 0:
        return jsonify({"themeId": themeId, "unlocked": True}), 200
    existing = UnlockedTheme.query.filter_by(member_email=target_email, theme_id=themeId).first()
    if existing:
        return error_response("ALREADY_OWNED", "已擁有", 400)
    member = Members.query.filter_by(email=target_email).first()
    if (member.points or 0) < price:
        return error_response("INSUFFICIENT_POINTS", "點數不足", 400)
    ut = UnlockedTheme(member_email=target_email, theme_id=themeId)
    db.session.add(ut)
    add_points_transaction(target_email, -price, f"redeem_theme_{themeId}", commit=False)
    db.session.commit()
    return jsonify({"themeId": themeId, "unlocked": True, "balance": member.points}), 200


@app.route('/api/members/<path:email>/themes', methods=['GET'])
def get_unlocked_themes(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self_or_admin(actor, email)
    if err:
        return err
    themes = UnlockedTheme.query.filter_by(member_email=target_email).all()
    return jsonify({"themes": [t.theme_id for t in themes] + ["classic"]})


@app.route('/api/members/<email>/referral', methods=['GET', 'POST'])
def referral_not_implemented(email):
    return error_response("NOT_FOUND", "此端點尚未實作", 404)


@app.route('/api/members/<path:email>/referral-code', methods=['GET'])
def get_referral_code(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    member = Members.query.filter_by(email=target_email).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    if not member.referral_code:
        member.referral_code = hashlib.sha256(target_email.encode()).hexdigest()[:16]
        db.session.commit()
    referrals = Referral.query.filter_by(referrer_email=target_email).count()
    return jsonify({"code": member.referral_code, "totalReferrals": referrals})


@app.route('/api/members/<path:email>/favorites', methods=['GET'])
def get_member_favorites(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self_or_admin(actor, email)
    if err:
        return err
    member = Members.query.filter_by(email=target_email).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    favs = Favorites.query.filter_by(member_id=member.phone_number).all()
    available_sources, _ = _catalog_availability_sets(_catalog_rows())
    return jsonify({"favorites": [{
        "item_id": f.item_id,
        "item_type": f.item_type,
        "unavailable": (str(f.item_type), int(f.item_id)) not in available_sources,
    } for f in favs]})


@app.route('/api/members/<path:email>/favorites/toggle', methods=['POST'])
def toggle_member_favorite(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    member = Members.query.filter_by(email=target_email).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    data = request.get_json(silent=True) or {}
    i_id = data.get('item_id');
    i_type = data.get('item_type')
    if not i_id or not i_type:
        return error_response("MISSING_FIELDS", "缺少欄位", 400)
    fav = Favorites.query.filter_by(member_id=member.phone_number, item_id=i_id, item_type=i_type).first()
    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({"status": "removed"})
    fav = Favorites(member_id=member.phone_number, item_id=i_id, item_type=i_type)
    db.session.add(fav)
    db.session.commit()
    task_reward = 0
    claim = TaskClaim.query.filter_by(member_email=target_email, task_id="first_favorite").first()
    if not claim:
        c2 = TaskClaim(
            member_email=target_email,
            task_id="first_favorite",
            claim_date=ONE_TIME_TASK_DATE,
        )
        db.session.add(c2)
        task_reward = 10
        add_points_transaction(target_email, 10, "task_first_favorite", commit=False)
    db.session.commit()
    return jsonify({"status": "added", "taskReward": task_reward}), 200


@app.route('/api/members/<path:email>/favorites/<int:item_id>', methods=['DELETE'])
def remove_member_favorite(email, item_id):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    member = Members.query.filter_by(email=target_email).first()
    if not member:
        return error_response("MEMBER_NOT_FOUND", "找不到會員", 404)
    fav = Favorites.query.filter_by(member_id=member.phone_number, item_id=item_id).first()
    if not fav:
        return error_response("NOT_FOUND", "找不到", 404)
    db.session.delete(fav)
    db.session.commit()
    return jsonify({"status": "removed"}), 200


@app.route('/api/members/<path:email>/history', methods=['GET'])
def get_analysis_history(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self_or_admin(actor, email)
    if err:
        return err
    records = AnalysisHistory.query.filter_by(member_email=target_email).order_by(
        AnalysisHistory.created_at.desc()).limit(50).all()
    return jsonify({"results": [{
        "id": r.id, "mode": r.mode, "result": r.result,
        "analysisPackageId": r.analysis_package_id,
        "createdAt": r.created_at.isoformat() if r.created_at else None
    } for r in records]})


@app.route('/api/members/<path:email>/history', methods=['POST'])
def create_analysis_history(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    record = AnalysisHistory(
        member_email=target_email,
        mode=data.get("mode", "basic"),
        result=data.get("result"),
        analysis_package_id=data.get("analysisPackageId")
    )
    db.session.add(record)
    db.session.commit()
    return jsonify({"id": record.id, "createdAt": record.created_at.isoformat() if record.created_at else None}), 201


@app.route('/api/members/<path:email>/cart', methods=['GET'])
def get_cart(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    items = CartItem.query.filter_by(member_email=target_email).all()
    _, available_catalog_ids = _catalog_availability_sets(_catalog_rows())
    cart = [{
        "item_id": i.item_id,
        "qty": i.qty,
        "unavailable": int(i.item_id) not in available_catalog_ids,
    } for i in items]
    # `cart` preserves the existing frontend contract. `items` follows the
    # newer response wording and includes `id` as a compatibility alias.
    return jsonify({
        "cart": cart,
        "items": [{"id": item["item_id"], **item} for item in cart],
    })


@app.route('/api/members/<path:email>/cart', methods=['PUT'])
def put_cart(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    items_data = data.get("cart", [])
    CartItem.query.filter_by(member_email=target_email).delete()
    for item in items_data:
        ci = CartItem(member_email=target_email, item_id=item.get("item_id"), qty=item.get("qty", 1))
        db.session.add(ci)
    db.session.commit()
    return jsonify({"status": "ok"}), 200


@app.route('/api/members/<path:email>/cart/items', methods=['POST'])
def add_cart_item(email):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id");
    qty = data.get("qty", 1)
    if not item_id:
        return error_response("MISSING_FIELDS", "缺少欄位", 400)
    existing = CartItem.query.filter_by(member_email=target_email, item_id=item_id).first()
    if existing:
        existing.qty += qty
    else:
        ci = CartItem(member_email=target_email, item_id=item_id, qty=qty)
        db.session.add(ci)
    db.session.commit()
    return jsonify({"status": "ok", "qty": existing.qty if existing else qty}), 200


@app.route('/api/members/<path:email>/cart/items/<int:item_id>', methods=['PATCH'])
def update_cart_item(email, item_id):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    qty = data.get("qty", 1)
    ci = CartItem.query.filter_by(member_email=target_email, item_id=item_id).first()
    if not ci:
        return error_response("NOT_FOUND", "找不到", 404)
    if qty <= 0:
        db.session.delete(ci)
    else:
        ci.qty = qty
    db.session.commit()
    return jsonify({"status": "ok"}), 200


@app.route('/api/members/<path:email>/cart/items/<int:item_id>', methods=['DELETE'])
def delete_cart_item(email, item_id):
    actor, err = require_actor()
    if err:
        return err
    target_email, err = require_self(actor, email)
    if err:
        return err
    ci = CartItem.query.filter_by(member_email=target_email, item_id=item_id).first()
    if ci:
        db.session.delete(ci)
        db.session.commit()
    return jsonify({"status": "removed"}), 200


# ========== 自動清理已刪除會員 ==========
def _auto_purge_deleted_members():
    try:
        deleted_members = Members.query.filter_by(status='deleted').all()
        if not deleted_members:
            return
        print(f"[AUTO_PURGE] 發現 {len(deleted_members)} 個 status='deleted' 的會員，開始自動清理...")
        for member in deleted_members:
            target_email = member.email
            try:
                SavedLook.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                Favorites.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
                CartItem.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                AnalysisHistory.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                TryonRecords.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
                Checkin.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
                PointsTransaction.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                DailyCheckin.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                TaskClaim.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                UnlockedTheme.query.filter_by(member_email=target_email).delete(synchronize_session=False)
                OTPCode.query.filter_by(email=target_email).delete(synchronize_session=False)
                Referral.query.filter(
                    (Referral.referrer_email == target_email) | (Referral.referred_email == target_email)
                ).delete(synchronize_session=False)
                MemberSession.query.filter_by(member_id=member.phone_number).delete(synchronize_session=False)
                db.session.delete(member)
                db.session.commit()
                print("[AUTO_PURGE] member purge completed")
            except Exception as e:
                db.session.rollback()
                print("[AUTO_PURGE] member purge failed")
    except Exception as e:
        print("[AUTO_PURGE] purge worker failed")


if __name__ == "__main__":
    with app.app_context():
        # Apply reviewed PostgreSQL migrations before starting the service.
        # Runtime schema creation can silently drift from production migrations.
        # SECURITY: Never enable debug mode in production - it exposes full tracebacks
        # and sensitive information (SQL statements, environment variables, etc.)
        is_debug = os.getenv("FLASK_DEBUG", "0") == "1" and os.getenv("FLASK_ENV") != "production"
        app.run(
            host='0.0.0.0',
            port=int(os.getenv("PORT", 5000)),
            debug=is_debug
        )
