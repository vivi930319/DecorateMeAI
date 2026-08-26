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

load_dotenv()

app = Flask(__name__)


def _configured_origins():
    """Only the Gateway / explicitly configured frontends may use cookies."""
    configured = os.getenv("CORS_ALLOWED_ORIGINS", "https://decorate-me.web.app,https://decorate-me.firebaseapp.com")
    return {origin.strip().rstrip("/") for origin in configured.split(",") if origin.strip()}


ALLOWED_ORIGINS = _configured_origins()
CORS(app, supports_credentials=True, origins=list(ALLOWED_ORIGINS))

# Gateway API key for authenticating public endpoints (Phase 4)
GATEWAY_API_KEY = os.getenv("UPSTREAM_MEMBER_API_KEY")
PRODUCT_ADMIN_API_KEY = os.getenv("PRODUCT_ADMIN_API_KEY")
# Public endpoints must be authenticated by the Gateway in production.  Local
# development can opt in to loose mode explicitly, never by default.
# The current Gateway authenticates normal member requests with its own session
# and forwards the member cookie; it does not attach X-Gateway-Key on /auth.
# Validate the header when present, but keep the upstream compatible until the
# Gateway contract is upgraded to send it for every request.
GATEWAY_KEY_LOOSE_MODE = os.getenv("GATEWAY_KEY_LOOSE_MODE", "true").lower() in ("1", "true", "yes")


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
    "/send-otp", "/verify-otp", "/register", "/login",
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
SESSION_MAX_AGE = 7200  # 2 小時
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
        "allowedPages": member.allowed_pages or _default_allowed_pages(member),
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


def error_response(code, message, status_code, request_id=None):
    return jsonify({"success": False, "status": "error", "error": {
        "code": code, "message": message, "retryable": status_code >= 500,
        "details": {}, "requestId": request_id or f"req_{uuid.uuid4().hex}",
    }}), status_code


def require_admin():
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


def require_product_audit_admin():
    """Accept the Gateway product-admin credential or an authenticated admin session."""
    token = read_bearer_token()
    if PRODUCT_ADMIN_API_KEY and token and hmac.compare_digest(token, PRODUCT_ADMIN_API_KEY):
        return None
    return require_admin()


def authenticated_member():
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


def _otp_rate_limit_key(email):
    digest = hashlib.sha256(email.encode("utf-8")).hexdigest()
    return f"otp:send-rate:{digest}"


def _allow_otp_send(email):
    """Limit OTP delivery without retaining addresses in Redis keys."""
    try:
        key = _otp_rate_limit_key(email)
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
@app.route("/forgot_password", methods=['GET', 'POST'])
def forgot_password():
    form = ForgotPasswordRequestForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        member = Members.query.filter_by(email=email).first()
        try:
            if member:
                ttl = r.ttl(redis_key(email))
                if ttl != -2 and ttl > (OTP_EXPIRE - 60):
                    flash('系統訊息', 'warning')
                    return redirect(url_for('reset_password', email=email))
                otp = generate_otp()
                r.set(redis_key(email), bcrypt.generate_password_hash(otp).decode("utf-8"), ex=OTP_EXPIRE)
                r.delete(attempt_key(email))
                send_otp_email(email, otp, OTP_EXPIRE)
            flash('系統訊息', 'info')
            return redirect(url_for('reset_password', email=email))
        except RedisError:
            flash('系統訊息', 'danger')
        except Exception:
            try:
                r.delete(redis_key(email))
            except RedisError:
                pass
            flash('系統訊息', 'danger')
    return render_template('forgot_password.html', title='敹?撖Ⅳ', form=form)


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
        member = Members.query.filter_by(email=email).first()
        if not member:
            flash('系統訊息', 'danger')
            return render_template('reset_password.html', title='?身撖Ⅳ', form=form)
        try:
            stored = r.get(redis_key(email))
            if stored is None:
                flash('系統訊息', 'danger')
                return redirect(url_for('forgot_password'))
            attempts = r.incr(attempt_key(email))
            r.expire(attempt_key(email), OTP_EXPIRE)
            if attempts > 5:
                r.delete(redis_key(email))
                r.delete(attempt_key(email))
                flash('系統訊息', 'danger')
                return redirect(url_for('forgot_password'))
            if not bcrypt.check_password_hash(stored, otp):
                flash('系統訊息', 'danger')
                return render_template('reset_password.html', title='?身撖Ⅳ', form=form)
            member.password = form.new_password.data
            revoke_all_member_sessions(member)
            db.session.commit()
            r.delete(redis_key(email))
            r.delete(attempt_key(email))
            flash('系統訊息', 'success')
            return redirect(url_for('login'))
        except RedisError:
            flash('系統訊息', 'danger')
        except Exception:
            db.session.rollback()
            flash('系統訊息', 'danger')
    return render_template('reset_password.html', title='?身撖Ⅳ', form=form)


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
    if purpose == "registration" and not _allow_otp_send(email):
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
    except (TypeError, ValueError):
        return error_response("INVALID_AGE", "年齡格式無效", 400)
    except Exception:
        db.session.rollback()
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
                product_list.append({
                    "id": f.item_id, "type": f.item_type,
                    "name": getattr(item, 'name', '?芰??'),
                    "brand": getattr(item, 'brand', ''),
                    "price": f"NT${item.price:.0f}" if getattr(item, 'price', None) else "NT$0",
                    "image_url": getattr(item, 'image_webp_url', '') or getattr(item, 'image_url', ''),
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
    product_list = []
    for f in favs:
        model_class = model_mapping.get(f.item_type)
        if model_class:
            item = model_class.query.get(f.item_id)
            if item:
                item_vector = getattr(item, 'qdrant_vector_12d', None) or getattr(item, 'color_vector', None) or []
                product_list.append({
                    "id": f.item_id, "type": f.item_type,
                    "name": getattr(item, 'name', getattr(item, 'product_name', '?芰??')),
                    "brand": getattr(item, 'brand', ''),
                    "price": f"NT${item.price:.0f}" if getattr(item, 'price', None) else "NT$0",
                    "image_url": getattr(item, 'image_webp_url', '') or getattr(item, 'image_url', ''),
                    "description": getattr(item, 'description', '?怎?膩'),
                    "desc": getattr(item, "description", None) or "憓溶憟賣除?莎?靽桅ˇ?頛芸?",
                    "hex": getattr(item, "hex_primary", None) or "#E8A0B4",
                    "lab": getattr(item, 'lab', None) or {},
                    "vector": item_vector, "salepage": getattr(item, 'sale_page_id', '')
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
    admin_err = require_admin()
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


def _write_product_audit(product_id, action, actor, before_data=None, after_data=None):
    db.session.execute(db.text("""
        INSERT INTO product_audit_logs
            (product_id, product_type, action, admin_id, before_data, after_data, request_id, source_ip)
        VALUES
            (:product_id, 'products', :action, :admin_id, CAST(:before_data AS jsonb),
             CAST(:after_data AS jsonb), :request_id, CAST(:source_ip AS inet))
    """), {
        "product_id": str(product_id), "action": action, "admin_id": _opaque_actor(actor),
        "before_data": json.dumps(before_data) if before_data is not None else None,
        "after_data": json.dumps(after_data) if after_data is not None else None,
        "request_id": f"staging_{uuid.uuid4().hex}", "source_ip": request.remote_addr or None,
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
    old_role = member.role
    old_status = member.status
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
        member.role = role
        revoke_all_member_sessions(member)
        log_audit(actor.email, email, "role_change", "role", old_role, role)
    if "status" in data:
        status = data.get("status")
        if status not in {"active", "suspended"}:
            return error_response("INVALID_STATUS", "狀態無效", 400)
        member.status = status
        revoke_all_member_sessions(member)
        log_audit(actor.email, email, "status_change", "status", old_status, status)
    if "allowedPages" in data:
        member.allowed_pages = data.get("allowedPages")
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
    admin_err = require_admin()
    if admin_err:
        return admin_err
    data = request.get_json(silent=True) or {}
    name = data.get('name');
    price = data.get('price');
    image_url = data.get('image_url')
    if not all([name, price, image_url]):
        return error_response("MISSING_FIELDS", "缺少必填欄位", 400)
    category = cat_to_product_category(data.get('category'))
    if category not in {"base", "lip", "eye", "blush", "contour", "highlight", "brow"}:
        return error_response("INVALID_CATEGORY", "分類無效", 400)
    try:
        product = Products(
            name=name, price=float(price), image_url=image_url,
            description=data.get('description', ''),
            category=category, shades=data.get('shades', [])
        )
        db.session.add(product)
        db.session.flush()
        catalog_id = db.session.execute(db.text("""
            SELECT id FROM public.product_catalog WHERE product_type = 'products' AND source_id = :source_id
        """), {"source_id": product.id}).scalar_one()
        db.session.commit()
        return jsonify({
            "id": catalog_id, "sourceId": product.id, "type": "products",
            "name": product.name, "price": f'NT${product.price:.0f}',
            "image_url": product.image_url, "description": product.description,
            "category": product.category, "shades": product.shades
        }), 201
    except Exception:
        db.session.rollback()
        return error_response("CREATE_FAILED", "建立失敗", 500)


@app.route('/api/products/<int:product_id>', methods=['PATCH'])
def update_product_api(product_id):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    return _catalog_update_response(product_id, request.get_json(silent=True) or {})


@app.route('/api/products/<int:product_id>', methods=['GET'])
def get_product_api(product_id):
    item = _catalog_item_by_id(product_id)
    if item is None:
        return error_response("NOT_FOUND", "找不到商品", 404)
    response = jsonify(item)
    response.headers["ETag"] = str(item.get("version", 1))
    return response, 200


@app.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product_api(product_id):
    admin_err = require_admin()
    if admin_err:
        return admin_err
    item = _catalog_item_by_id(product_id)
    if item is None:
        return error_response("NOT_FOUND", "找不到商品", 404)
    table = _PRODUCT_CATALOG_TABLES[item["type"]]
    db.session.execute(db.text(f"DELETE FROM public.{table} WHERE id = :source_id"), {"source_id": item["sourceId"]})
    db.session.execute(db.text("DELETE FROM public.product_catalog WHERE id = :id"), {"id": product_id})
    db.session.commit()
    return jsonify({"message": "商品已刪除"}), 200


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
    looks = SavedLook.query.filter_by(member_email=target_email).order_by(SavedLook.created_at.desc()).limit(50).all()
    return jsonify({
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
    if count >= 50:
        return error_response("SAVED_LOOK_LIMIT", "收藏妝容已達 50 筆上限", 409)
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
    look = SavedLook.query.filter_by(id=look_id, member_email=target_email).first()
    if not look:
        return error_response("LOOK_NOT_FOUND", "找不到收藏妝容", 404)
    try:
        db.session.delete(look)
        db.session.commit()
    except Exception:
        db.session.rollback()
        return error_response("DELETE_FAILED", "刪除失敗", 500)
    return jsonify({"ok": True, "action": "saved_look_deleted"}), 200


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
        "eyebrow": "brow", "眉妝": "brow", "眉筆": "brow",
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


def display_price(value):
    if value is None: return "NT$0"
    try:
        return f"NT${float(value):.0f}"
    except (TypeError, ValueError):
        return str(value)


def get_product_vector(item):
    return getattr(item, "qdrant_vector_12d", None) or getattr(item, "color_vector", None) or []


def product_card_payload(item, category_type):
    pv = get_product_vector(item)
    return {
        "id": item.id, "type": category_type,
        "brand": getattr(item, "brand", "") or "",
        "name": getattr(item, "name", None) or getattr(item, "product_name", None) or "未命名商品",
        "price": display_price(getattr(item, "price", None)),
        "description": getattr(item, "description", "") or "暫無描述",
        "image_src": getattr(item, "image_url",
                             getattr(item, "image_webp_url", "https://via.placeholder.com/300x300.png")),
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
        "image_src": item.image_url,
        "imageUrl": item.image_url,
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


def _catalog_rows():
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
                       TRUE AS in_stock, 'active'::text AS status, 'approved'::text AS review_status, TRUE AS recommendation_ready
                FROM public.product_catalog c JOIN public.products p ON c.product_type='products' AND c.source_id=p.id
            """)
        elif product_type == "foundations":
            selects.append(f"""
                SELECT c.id AS global_id, c.product_type, p.id AS source_id, p.name, COALESCE(p.brand,'') AS brand,
                       p.price, p.description, p.image_webp_url AS image_url, p.source_url,
                       p.sale_page_id, p.category, NULL::jsonb AS shades, p.season_tags, p.undertone,
                       p.shade_code, p.shade_name, p.series_id, p.depth_index,
                       COALESCE(p.version, 1) AS version, p.hex_primary, p.lab,
                       COALESCE(p.in_stock,FALSE) AS in_stock, COALESCE(p.status,'inactive') AS status,
                       COALESCE(p.review_status,'pending') AS review_status, COALESCE(p.recommendation_ready,FALSE) AS recommendation_ready
                FROM public.product_catalog c JOIN public.{table} p ON c.product_type='{product_type}' AND c.source_id=p.id
            """)
        else:
            selects.append(f"""
                SELECT c.id AS global_id, c.product_type, p.id AS source_id, p.name, COALESCE(p.brand,'') AS brand,
                       p.price, p.description, p.image_webp_url AS image_url, p.source_url,
                       p.sale_page_id, p.category, NULL::jsonb AS shades, p.season_tags, p.undertone,
                       NULL::text AS shade_code, NULL::text AS shade_name,
                       NULL::text AS series_id, NULL::integer AS depth_index,
                       COALESCE(p.version, 1) AS version, p.hex_primary, p.lab,
                       COALESCE(p.in_stock,FALSE) AS in_stock, COALESCE(p.status,'inactive') AS status,
                       COALESCE(p.review_status,'pending') AS review_status, COALESCE(p.recommendation_ready,FALSE) AS recommendation_ready
                FROM public.product_catalog c JOIN public.{table} p ON c.product_type='{product_type}' AND c.source_id=p.id
            """)
    rows = db.session.execute(db.text(" UNION ALL ".join(selects))).mappings().all()
    return [_catalog_payload(row) for row in rows]


def _catalog_payload(row):
    source_url = str(row["source_url"] or "").strip()
    return {
        "id": int(row["global_id"]), "sourceId": int(row["source_id"]), "type": row["product_type"],
        "candidateKey": f"{row['product_type']}:{row['source_id']}",
        "name": row["name"] or "未命名商品", "brand": row["brand"] or "",
        "price": display_price(row["price"]), "description": row["description"] or "暫無描述",
        "imageUrl": row["image_url"] or "", "image_url": row["image_url"] or "", "image_src": row["image_url"] or "",
        "sourceUrl": source_url if source_url.startswith(("https://", "http://")) else None,
        "salePageId": row["sale_page_id"] or None, "sale_page_id": row["sale_page_id"] or None,
        "category": row["category"] or "", "shades": row["shades"] or [],
        "seasonTags": row["season_tags"] or [], "undertone": row["undertone"] or "",
        "shadeCode": row["shade_code"] or None, "shadeName": row["shade_name"] or "",
        "seriesId": row["series_id"] or None,
        "depthIndex": int(row["depth_index"]) if row["depth_index"] is not None else None,
        "version": int(row["version"] or 1), "hex_primary": row["hex_primary"], "lab": row["lab"] or None,
        "inStock": bool(row["in_stock"]), "status": row["status"], "reviewStatus": row["review_status"],
        "recommendationReady": bool(row["recommendation_ready"]),
    }


def _catalog_item_by_id(product_id):
    return next((item for item in _catalog_rows() if item["id"] == product_id), None)


def _catalog_list_response():
    items = _catalog_rows()
    raw_category = request.args.get("category") or request.args.get("type")
    if raw_category:
        normalized_category = cat_to_product_category(raw_category)
        normalized_type = category_to_frontend_type(normalized_category)
        items = [item for item in items if (
                cat_to_product_category(item.get("category") or item.get("type")) == normalized_category
                or item.get("type") == raw_category
                or item.get("type") == normalized_type
        )]
    raw_brand = (request.args.get("brand") or "").strip().casefold()
    if raw_brand:
        items = [item for item in items if str(item.get("brand") or "").casefold() == raw_brand]
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
    items.sort(key=lambda item: item["id"])
    raw_limit = request.args.get("limit")
    if raw_limit is None:
        return jsonify({"products": items})
    try:
        limit = max(1, min(int(raw_limit), 100))
        cursor = int(request.args.get("cursor", "0"))
    except ValueError:
        return error_response("INVALID_PAGINATION", "limit 或 cursor 格式無效", 400)
    page = [item for item in items if item["id"] > cursor][:limit]
    next_cursor = str(page[-1]["id"]) if len(page) == limit and any(
        item["id"] > page[-1]["id"] for item in items) else None
    return jsonify({"ok": True, "items": page, "products": page, "total": len(items), "nextCursor": next_cursor,
                    "query": query or None})


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
    db.session.commit()
    updated = _catalog_item_by_id(product_id)
    response = jsonify(updated)
    response.headers["ETag"] = str(updated["version"])
    return response, 200


def recommendation_candidates(categories=None):
    allowed = {cat_to_product_category(c) for c in categories} if categories else None
    candidates = []
    catalog_by_key = {item["candidateKey"]: item for item in _catalog_rows()}
    for cat in MAKEUP_CATEGORIES:
        category = cat_to_product_category(cat["type"])
        if allowed and category not in allowed:
            continue
        for item in cat["model"].query.all():
            cand = product_card_payload(item, cat["type"])
            catalog_item = catalog_by_key.get(f"{cat['type']}:{item.id}")
            if (catalog_item is None or not catalog_item["inStock"] or catalog_item["status"] != "active"
                    or catalog_item["reviewStatus"] != "approved" or not catalog_item["recommendationReady"]):
                continue
            cand.update({
                "id": catalog_item["id"], "sourceId": item.id,
                "candidateKey": catalog_item["candidateKey"],
                "category": category, "tags": [category, cat["type"]],
                "inStock": True, "shadeName": getattr(item, "shade_name", "") or "",
                "imageUrl": catalog_item["imageUrl"] or cand.get("image_src", ""),
                "productUrl": catalog_item["sourceUrl"] or "",
                "sourceUrl": catalog_item["sourceUrl"], "salePageId": catalog_item["salePageId"],
                "seasonTags": catalog_item["seasonTags"], "undertone": catalog_item["undertone"],
                "shadeCode": catalog_item["shadeCode"], "shadeName": catalog_item["shadeName"],
                "seriesId": catalog_item["seriesId"], "depthIndex": catalog_item["depthIndex"],
                "coverageCategory": cat["type"],
                "currency": "TWD",
                "hex_primary": getattr(item, "hex_primary", None), "lab": getattr(item, "lab", None),
            })
            candidates.append(cand)
    for item in Products.query.all():
        cand = generic_product_candidate(item)
        catalog_item = catalog_by_key.get(f"products:{item.id}")
        if catalog_item is None:
            continue
        cand.update({"id": catalog_item["id"], "sourceId": item.id,
                     "candidateKey": catalog_item["candidateKey"], "sourceUrl": catalog_item["sourceUrl"],
                     "salePageId": catalog_item["salePageId"], "productUrl": catalog_item["sourceUrl"] or "",
                     "seasonTags": catalog_item["seasonTags"], "undertone": catalog_item["undertone"],
                     "coverageCategory": category_to_frontend_type(cand["category"])})
        if cand and (not allowed or cand["category"] in allowed):
            candidates.append(cand)
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
            "recommendations": {"products": []},
        }, "products": [], "code": "RECOMMENDATION_EMPTY"}), 200
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
            "primary": result["primary"], "alternates": result["alternates"], "threshold": result["threshold"],
            "personalization": result["personalization"],
            "shadeRecommendation": result["shadeRecommendation"],
        },
    }
    return jsonify({
        "success": True, "status": "completed", "analysisPackage": response_package,
        "products": result["products"], "fallbackUsed": result["fallbackUsed"],
        "fallbackReason": result["fallbackReason"], "coverage": result["coverage"],
        "fallbackReasons": result["fallbackReasons"],
        "styleTagFallbackUsed": result["styleTagFallbackUsed"],
        "skinToneLabReliable": result["skinToneLabReliable"],
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


for cat in MAKEUP_CATEGORIES:
    def make_route(category):
        def route():
            items = category["model"].query.all()
            return jsonify({"products": [{
                "id": i.id, "type": category["type"],
                "brand": getattr(i, 'brand', ''),
                "name": getattr(i, 'name', '') or getattr(i, 'product_name', '') or '未命名商品',
                "price": f"NT${i.price:.0f}" if getattr(i, 'price', None) else "NT$0",
                "description": getattr(i, 'description', ''),
                "image_url": getattr(i, 'image_webp_url', '') or getattr(i, 'image_url', ''),
                "lab_json": decode_text(getattr(i, 'lab', '')),
                "qdrant_vector_12d": get_product_vector(i),
                "sale_page_id": getattr(i, 'sale_page_id', '')
            } for i in items]})

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
    return jsonify({"favorites": [{"item_id": f.item_id, "item_type": f.item_type} for f in favs]})


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
    return jsonify({"cart": [{"item_id": i.item_id, "qty": i.qty} for i in items]})


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
