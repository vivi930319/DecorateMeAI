from extensions import db, bcrypt
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime, date


class Members(db.Model, UserMixin):
    __tablename__ = 'members'

    phone_number = db.Column(db.String(20), primary_key=True, unique=True)
    name = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    level = db.Column(db.Enum('bronze', 'silver', 'gold', name='member_level'), default='bronze')
    role = db.Column(db.String(20), nullable=False, default='member')
    status = db.Column(db.String(20), nullable=False, default='active')
    age = db.Column(db.Integer)
    points = db.Column(db.Integer, nullable=False, default=0)
    lifetime_points = db.Column(db.Integer, nullable=False, default=0)
    total_earned_points = db.Column(db.Integer, nullable=False, default=0)
    allowed_pages = db.Column(JSONB, nullable=True)
    vip_requested = db.Column(db.Boolean, default=False)
    render_daily_limit = db.Column(db.Integer, nullable=False, default=3)
    render_remaining = db.Column(db.Integer, nullable=False, default=3)
    render_reset_at = db.Column(db.DateTime, nullable=True)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    referral_code = db.Column(db.String(32), nullable=True, unique=True)
    referred_by_email = db.Column(db.String(100), nullable=True)
    active_theme = db.Column(db.String(20), nullable=False, default='classic')
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)
    deleted_by = db.Column(db.String(254), nullable=True)
    deletion_reason = db.Column(db.String(255), nullable=True)
    deletion_request_id = db.Column(db.String(64), nullable=True)
    deletion_state = db.Column(db.String(20), nullable=True)
    deletion_attempts = db.Column(db.Integer, nullable=False, default=0)
    deletion_last_error = db.Column(db.String(500), nullable=True)
    # Incrementing this invalidates every previously issued cookie session and JWT.
    session_version = db.Column(db.Integer, nullable=False, default=1)

    @property
    def password(self):
        raise AttributeError("密碼不是可讀取的屬性")

    @password.setter
    def password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def verify_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def get_id(self):
        return str(self.phone_number)

    checkins = db.relationship('Checkin', backref='member', lazy=True)

    def level_label(self):
        return {"bronze": "一般會員", "silver": "VIP會員", "gold": "VIP會員"}.get(self.level, "一般會員")

    def member_role(self):
        return self.role or "member"


class Products(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    favorite_count = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50), nullable=True)
    shades = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Checkin(db.Model):
    __tablename__ = 'checkins'
    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.String(20), db.ForeignKey('members.phone_number'), nullable=False)
    checkin_time = db.Column(db.DateTime, server_default=db.func.now())
    note = db.Column(db.Text)


class Favorites(db.Model):
    __tablename__ = 'favorites'

    __table_args__ = (
        db.UniqueConstraint('member_id', 'item_id', 'item_type', name='uq_member_item'),
    )

    id = db.Column(db.Integer, primary_key=True)
    member_id = db.Column(db.String(20), db.ForeignKey('members.phone_number'), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    item_type = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    member = db.relationship('Members', backref=db.backref('favorite_list', lazy=True))


class ColorPalettes(db.Model):
    __tablename__ = 'color_palettes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(100))
    hex_code = db.Column(db.String(7), nullable=False, unique=True)
    source_url = db.Column(db.String(255))
    tags = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    actor_email = db.Column(db.String(100), nullable=False)
    target_email = db.Column(db.String(100), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    field_name = db.Column(db.String(50), nullable=True)
    before_value = db.Column(db.String(255), nullable=True)
    after_value = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class MemberSession(db.Model):
    __tablename__ = 'member_sessions'

    session_hash = db.Column(db.String(64), primary_key=True)
    # Opaque, non-PII identifier for multi-session slot selection.
    session_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    member_id = db.Column(db.String(20), db.ForeignKey('members.phone_number'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_seen_at = db.Column(db.DateTime(timezone=True), nullable=True)
    session_version = db.Column(db.Integer, nullable=False, default=1)
    # Source identifier for session count limiting per device/source.
    source_identifier = db.Column(db.String(128), nullable=True, index=True)

    member = db.relationship('Members', backref='sessions', lazy=True)


class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_logs'
    id = db.Column(db.String(36), primary_key=True)
    request_id = db.Column(db.String(64), nullable=False, unique=True)
    actor_email = db.Column(db.String(254), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    target_email = db.Column(db.String(254), nullable=True, index=True)
    target_id = db.Column(db.String(80), nullable=True)
    result = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(255), nullable=True)
    metadata_json = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)


class MemberDeletionJob(db.Model):
    __tablename__ = 'member_deletion_jobs'
    id = db.Column(db.String(36), primary_key=True)
    request_id = db.Column(db.String(64), nullable=False, unique=True)
    member_email = db.Column(db.String(254), nullable=False, unique=True)
    state = db.Column(db.String(20), nullable=False, default='pending')
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_error_code = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), onupdate=db.func.now(),
                           nullable=False)


class PointsTransaction(db.Model):
    __tablename__ = 'points_transactions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    delta = db.Column(db.Integer, nullable=False)
    balance_after = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(100), nullable=False)
    ref_id = db.Column(db.String(255), nullable=True)
    note = db.Column(db.Text, nullable=True)
    meta = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class SavedLook(db.Model):
    __tablename__ = 'saved_looks'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    style = db.Column(db.String(120), nullable=False)
    before_image_url = db.Column(db.Text, nullable=False)
    after_image_url = db.Column(db.Text, nullable=False)
    analysis_summary = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🔴 OTP 驗證碼 (待辦 §1) ==========
class OTPCode(db.Model):
    __tablename__ = 'otp_codes'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    email = db.Column(db.String(100), nullable=False, index=True)
    # Store a bcrypt hash only; plaintext OTP values must never be persisted.
    code_hash = db.Column(db.String(255), nullable=False)
    purpose = db.Column(db.String(40), nullable=False, default='email_verification')
    verified_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class CrawlerStagingProduct(db.Model):
    """Untrusted crawler output awaiting an administrator's approval."""
    __tablename__ = "crawler_staging_products"

    id = db.Column(db.Integer, primary_key=True)
    source_site = db.Column(db.String(100), nullable=False)
    source_product_id = db.Column(db.String(255), nullable=False)
    source_url = db.Column(db.String(1000), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=True)
    currency = db.Column(db.String(8), nullable=False, default="TWD")
    description = db.Column(db.Text, nullable=True)
    category = db.Column(db.String(50), nullable=True)
    image_url = db.Column(db.String(1000), nullable=True)
    image_urls = db.Column(JSONB, nullable=True)
    shades = db.Column(JSONB, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="pending")
    validation_error_code = db.Column(db.String(64), nullable=True)
    validation_error_message = db.Column(db.String(500), nullable=True)
    crawled_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_by = db.Column(db.String(64), nullable=True)
    review_note = db.Column(db.String(500), nullable=True)
    imported_product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("source_site", "source_product_id", name="uq_crawler_staging_source_product"),
        db.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'imported', 'failed')",
                           name="ck_crawler_staging_status"),
    )


class PendingRegistration(db.Model):
    """Registration data exists here only until email ownership is proven."""
    __tablename__ = 'pending_registrations'

    email = db.Column(db.String(100), primary_key=True)
    phone_number = db.Column(db.String(20), nullable=False, unique=True)
    name = db.Column(db.String(50), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🟠 分析歷史 (待辦 §6) ==========
class AnalysisHistory(db.Model):
    __tablename__ = 'analysis_history'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    mode = db.Column(db.String(10), nullable=False)  # basic / pro
    result = db.Column(JSONB, nullable=True)
    analysis_package_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🟠 每日簽到 (待辦 §5) ==========
class DailyCheckin(db.Model):
    __tablename__ = 'daily_checkins'

    __table_args__ = (
        db.UniqueConstraint('member_email', 'checkin_date', name='uq_checkin_date'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    checkin_date = db.Column(db.Date, nullable=False)
    streak = db.Column(db.Integer, nullable=False, default=1)
    awarded = db.Column(db.Integer, nullable=False, default=10)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🟠 任務領取 (待辦 §5) ==========
class TaskClaim(db.Model):
    __tablename__ = 'task_claims'

    __table_args__ = (
        db.UniqueConstraint('member_email', 'task_id', 'claim_date', name='uq_task_claim_date'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    task_id = db.Column(db.String(40), nullable=False)
    claim_date = db.Column(db.Date, nullable=False)
    claimed_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🟠 已解鎖主題 (待辦 §5) ==========
class UnlockedTheme(db.Model):
    __tablename__ = 'unlocked_themes'

    __table_args__ = (
        db.UniqueConstraint('member_email', 'theme_id', name='uq_theme'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    theme_id = db.Column(db.String(20), nullable=False)
    unlocked_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🟠 推薦紀錄 (待辦 §5) ==========
class Referral(db.Model):
    __tablename__ = 'referrals'

    __table_args__ = (
        db.UniqueConstraint('referred_email', name='uq_referred'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    referrer_email = db.Column(db.String(100), nullable=False)
    referred_email = db.Column(db.String(100), nullable=False)
    points_awarded = db.Column(db.Integer, nullable=False, default=20)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


# ========== 🟠 購物車 (待辦 §8) ==========
class CartItem(db.Model):
    __tablename__ = 'cart_items'

    __table_args__ = (
        db.UniqueConstraint('member_email', 'item_id', name='uq_cart_item'),
    )

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_email = db.Column(db.String(100), db.ForeignKey('members.email'), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime, onupdate=db.func.now(), server_default=db.func.now())


# ========== 美容彩妝爬蟲資料表 ==========
class Blushes(db.Model):
    __tablename__ = 'blushes'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime)


class Contouring(db.Model):
    __tablename__ = 'contouring'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)


class Eyebrows(db.Model):
    __tablename__ = 'eyebrows'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime)


class EyelinerMascara(db.Model):
    __tablename__ = 'eyeliner_mascara'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime)


class Eyeshadows(db.Model):
    __tablename__ = 'eyeshadows'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime)


class Foundations(db.Model):
    __tablename__ = 'foundations'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    source_type = db.Column(db.String(50))
    shade_code = db.Column(db.String(30))
    shade_name = db.Column(db.Text)
    series_id = db.Column(db.String(120))
    depth_index = db.Column(db.Integer)
    undertone = db.Column(db.String(20))
    created_at = db.Column(db.DateTime)


class Highlighters(db.Model):
    __tablename__ = 'highlighters'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.Text)
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    created_at = db.Column(db.DateTime)


class Lipsticks(db.Model):
    __tablename__ = 'lipsticks'
    id = db.Column(db.Integer, primary_key=True)
    brand = db.Column(db.String(100))
    sale_page_id = db.Column(db.String(50))
    name = db.Column(db.String(255))
    price = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_webp_url = db.Column(db.String(500))
    lab = db.Column(JSONB)
    color_vector = db.Column(JSONB)
    qdrant_vector_12d = db.Column(JSONB)
    hex_primary = db.Column(db.String(10))
    palette_colors = db.Column(JSONB, nullable=False, default=list, server_default='[]')
    palette_image_url = db.Column(db.Text)
    source_type = db.Column(db.String(50))
    created_at = db.Column(db.DateTime)


class TryonRecords(db.Model):
    __tablename__ = 'tryon_records'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    member_id = db.Column(db.String(20), db.ForeignKey('members.phone_number'), nullable=False)
    item_id = db.Column(db.Integer, nullable=False)
    item_type = db.Column(db.String(50), nullable=False)
    original_image_url = db.Column(db.String(500), nullable=False)
    generated_image_url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    makeup_advice = db.Column(db.Text, nullable=True)
