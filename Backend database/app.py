from datetime import date
from flask import Flask, url_for, flash, redirect, request, render_template, jsonify
from flask_cors import CORS
from flask_login import login_user, current_user, logout_user, login_required
from sqlalchemy.exc import IntegrityError
import config
import os
from dotenv import load_dotenv
import redis
import base64
from redis.exceptions import RedisError

from extensions import db, bcrypt, login_manager
from models import (
    Members, Products, Favorites, ColorPalettes, Checkin,
    Blushes, Contouring, Eyebrows, EyelinerMascara,
    Eyeshadows, Foundations, Highlighters, Lipsticks
)
from forms import (
    RegistrationForm, LoginForm, ChangePasswordForm,
    ForgotPasswordRequestForm, ResetPasswordForm,
)
from otp_utils import generate_otp, redis_key, send_otp_email, attempt_key

load_dotenv()


#app.py 是整個 Flask 應用程式的主程式和入口點，負責設定環境、連接資料庫、定義網頁路徑（路由），以及處理所有的使用者互動邏輯（註冊、登入）
app = Flask(__name__)
CORS(app)
#從config.py 檔案中載入所有設定，和資料庫的連線資訊 (SQLALCHEMY_DATABASE_URI)
app.config.from_object(config)
#設定一個秘密金鑰，這是 Flask 用於保護網站安全
app.config['SECRET_KEY'] = config.SECRET_KEY
db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)
redis_url = os.getenv("REDIS_URL")
if redis_url:
    r = redis.from_url(redis_url, decode_responses=True)
else:
    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        password=os.getenv("REDIS_PASSWORD") or None,
        decode_responses=True
    )
OTP_EXPIRE = int(os.getenv("OTP_EXPIRE_SECONDS", 300))


#2. Flask-Login 會員管理，這部分是應用程式實現誰已登入的狀態
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'


@login_manager.user_loader
def load_user(user_id):
    # 使用 phone_number 查詢
    return Members.query.get(user_id)


@app.route('/')
def index():
    # 為了測試方便，顯示當前登入狀態
    if current_user.is_authenticated:
        return f"歡迎回來，{current_user.name}！<p><a href='{url_for('logout')}'>登出</a> | <a href='{url_for('profile')}'>會員中心</a></p>"
    return f"Flask MySQL 應用程式已啟動。<p><a href='{url_for('register')}'>註冊</a> | <a href='{url_for('login')}'>登入</a></p>"


@app.route('/healthz')
def healthz():
    return jsonify({"status": "ok"})


# 註冊功能
@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            member = Members(
                phone_number=form.phone_number.data,
                name=form.name.data,
                email=form.email.data.strip().lower(),
                password=form.password.data,
                age=form.age.data,
                level='bronze'
            )
            db.session.add(member)
            db.session.commit()
            flash('您的帳號已建立！現在可以登入了。', 'success')
            return redirect(url_for('login'))
        except IntegrityError:
            db.session.rollback()
            flash('電話或 Email 已存在，請改用其他資訊。', 'danger')
        except Exception:
            db.session.rollback()
            flash('註冊失敗，請稍後再試。', 'danger')

    # 需要 register.html 模板
    return render_template('register.html', title='註冊', form=form)


# 登入功能
@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        member = Members.query.filter_by(email=form.email.data.strip().lower()).first()
        if member and member.verify_password(form.password.data):
            login_user(member)
            next_page = request.args.get('next')
            flash('登入成功！', 'success')
            # 使用 flask 的 redirect
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('登入失敗，請檢查電子郵件或密碼', 'danger')

    # 需要 login.html 模板
    return render_template('login.html', title='登入', form=form)


# 忘記密碼 - 寄送 OTP
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
                    flash('驗證碼已寄出，請稍候再重新申請。', 'warning')
                    return redirect(url_for('reset_password', email=email))

                otp = generate_otp()
                r.setex(redis_key(email), OTP_EXPIRE, otp)
                r.delete(attempt_key(email))
                send_otp_email(email, otp, OTP_EXPIRE)

            flash('若該 Email 已註冊，系統已寄出重設密碼驗證碼。', 'info')
            return redirect(url_for('reset_password', email=email))
        except RedisError:
            flash('OTP 服務暫時不可用，請稍後再試。', 'danger')
        except Exception:
            try:
                r.delete(redis_key(email))
            except RedisError:
                pass
            flash('寄送驗證碼失敗，請稍後再試。', 'danger')

    return render_template('forgot_password.html', title='忘記密碼', form=form)


# 忘記密碼 - 驗證 OTP 並重設密碼
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
            flash('查無此 Email 對應的帳號。', 'danger')
            return render_template('reset_password.html', title='重設密碼', form=form)

        try:
            stored = r.get(redis_key(email))
            if stored is None:
                flash('驗證碼不存在或已逾時，請重新申請。', 'danger')
                return redirect(url_for('forgot_password'))

            attempts = r.incr(attempt_key(email))
            r.expire(attempt_key(email), OTP_EXPIRE)

            if attempts > 5:
                r.delete(redis_key(email))
                r.delete(attempt_key(email))
                flash('驗證失敗次數過多，請重新申請驗證碼。', 'danger')
                return redirect(url_for('forgot_password'))

            if otp != stored:
                flash('驗證碼錯誤，請重新輸入。', 'danger')
                return render_template('reset_password.html', title='重設密碼', form=form)

            member.password = form.new_password.data
            db.session.commit()
            r.delete(redis_key(email))
            r.delete(attempt_key(email))
            flash('密碼已重設成功，請使用新密碼登入。', 'success')
            return redirect(url_for('login'))
        except RedisError:
            flash('OTP 服務暫時不可用，請稍後再試。', 'danger')
        except Exception:
            db.session.rollback()
            flash('重設密碼失敗，請稍後再試。', 'danger')

    return render_template('reset_password.html', title='重設密碼', form=form)


# 更改密碼功能
@app.route("/change_password", methods=['GET', 'POST'])
@login_required  # 只有登入後才能存取
def change_password():
    form = ChangePasswordForm()

    if form.validate_on_submit():
        member = current_user  # 取得當前登入的使用者物件

        # 驗證舊密碼是否正確
        if member.verify_password(form.old_password.data):

            # 設定新密碼
            member.password = form.new_password.data

            # 儲存到資料庫
            db.session.commit()

            flash('密碼已成功更改！', 'success')
            # 更改成功後導向會員中心
            return redirect(url_for('profile'))
        else:
            flash('舊密碼輸入錯誤，請重試。', 'danger')

    # 需要 change_password.html 模板
    return render_template('change_password.html', title='更改密碼', form=form)

# ── OTP 路由 ──
@app.route("/api/send-otp", methods=["POST"])
def send_otp():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    if not email:
        return jsonify({"error": "Email 不得為空"}), 400
    try:
        ttl = r.ttl(redis_key(email))
        if ttl != -2 and ttl > (OTP_EXPIRE - 60):
            return jsonify({"error": "請稍後再重新發送"}), 429

        otp = generate_otp()
        r.setex(redis_key(email), OTP_EXPIRE, otp)
        send_otp_email(email, otp, OTP_EXPIRE)
        return jsonify({"message": "驗證碼已寄出"}), 200
    except RedisError:
        return jsonify({"error": "OTP 服務暫時不可用"}), 503
    except Exception as e:
        try:
            r.delete(redis_key(email))
        except RedisError:
            pass
        return jsonify({"error": str(e)}), 500

@app.route("/api/verify-otp", methods=["POST"])
def verify_otp():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    otp = data.get("otp", "").strip()

    try:
        stored = r.get(redis_key(email))

        if stored is None:
            return jsonify({"success": False, "error": "驗證碼不存在或已逾時"}), 400

        attempts = r.incr(attempt_key(email))
        r.expire(attempt_key(email), OTP_EXPIRE)
        if attempts > 5:
            r.delete(redis_key(email))
            return jsonify({"success": False, "error": "嘗試次數過多，請重新申請"}), 429

        if otp != stored:
            return jsonify({"success": False, "error": "驗證碼錯誤"}), 400

        r.delete(redis_key(email))
        r.delete(attempt_key(email))
        return jsonify({"success": True, "message": "驗證成功"}), 200
    except RedisError:
        return jsonify({"success": False, "error": "OTP 服務暫時不可用"}), 503

#我的最愛清單-點擊收藏 (新增/刪除）
@app.route('/api/favorites/toggle', methods=['POST'])
@login_required
def toggle_favorite():
    data = request.get_json(silent=True) or {}
    i_id = data.get('item_id')
    i_type = data.get('item_type')

    if not i_id or not i_type:
        return jsonify({"status": "error", "message": "缺少 item_id 或 item_type"}), 400

    fav = Favorites.query.filter_by(member_id=current_user.phone_number, item_id=i_id, item_type=i_type).first()

    if fav:
        db.session.delete(fav)
        db.session.commit()
        return jsonify({"status": "removed", "message": "已取消收藏"})
    else:
        try:
            new_fav = Favorites(member_id=current_user.phone_number, item_id=i_id, item_type=i_type)
            db.session.add(new_fav)
            db.session.commit()
            return jsonify({"status": "added", "message": "已加入收藏"})
        except IntegrityError:
            db.session.rollback()
            return jsonify({"status": "error", "message": "加入收藏失敗"}), 400


@app.route('/api/members/<phone>/favorites', methods=['GET'])
def get_user_favorites(phone):
    favs = Favorites.query.filter_by(member_id=phone).all()

    model_mapping = {
        'lipsticks': Lipsticks,
        'blushes': Blushes,
        'contouring': Contouring,
        'eyebrows': Eyebrows,
        'eyeliner_mascara': EyelinerMascara,
        'eyeshadows': Eyeshadows,
        'foundations': Foundations,
        'highlighters': Highlighters,
        'products': Products
    }

    product_list = []
    for f in favs:
        model_class = model_mapping.get(f.item_type)
        if model_class:
            item = model_class.query.get(f.item_id)
            if item:
                name = getattr(item, 'name', getattr(item, 'product_name', '未知商品'))
                price = float(item.price) if getattr(item, 'price', None) else 0.0
                image = getattr(item, 'image_data', getattr(item, 'image_url', ''))

                product_list.append({
                    "id": f.item_id,
                    "type": f.item_type,
                    "name": name,
                    "price": price,
                    "image_data": image,
                    "description": getattr(item, 'description', '暫無描述')
                })

    return jsonify({"favorites": product_list})

# 會員簽到，對應資料庫 sp_member_checkin
@app.route('/api/checkins', methods=['POST'])
@login_required
def add_checkin():
    data = request.get_json(silent=True) or {}
    note = data.get('note', '')
    today = date.today()

    # 防止同一天重複簽到 (模擬 trigger trg_prevent_multiple_checkin)
    exists = Checkin.query.filter(
        Checkin.member_id == current_user.phone_number,
        db.func.date(Checkin.checkin_time) == today
    ).first()
    if exists:
        return jsonify({"message": "今日已簽到"}), 400

    new_checkin = Checkin(member_id=current_user.phone_number, note=note)
    db.session.add(new_checkin)
    db.session.commit()
    return jsonify({
        "message": "簽到完成",
        "checkin_time": new_checkin.checkin_time.isoformat() if new_checkin.checkin_time else None
    })


# 登出功能
@app.route("/logout")
def logout():
    logout_user()
    flash('您已成功登出！', 'info')
    return redirect(url_for('index'))


# 會員中心
@app.route("/profile")
@login_required
def profile():
    return f"歡迎來到會員中心，{current_user.name}！您的電話號碼是 {current_user.phone_number}，等級是 {current_user.level}。"


# 新增 API 路由給 Swift 使用
@app.route('/api/members', methods=['GET'])
def get_members_api():
    # 查詢資料庫中所有的會員
    members = Members.query.all()

    # JSON 格式
    member_list = []
    for m in members:
        member_list.append({
            "name": m.name,
            "phone_number": m.phone_number,
            "level": m.level,
            "email": m.email
        })
    return jsonify({"members": member_list})

@app.route('/api/members/<phone>/stats', methods=['GET'])
def get_member_stats(phone):
    member = Members.query.get(phone)
    if not member:
        return jsonify({"message": "找不到會員"}), 404

    checkins = Checkin.query.filter_by(member_id=phone).count()
    favorites = Favorites.query.filter_by(member_id=phone).count()
    last_checkin = db.session.query(db.func.max(Checkin.checkin_time)).filter_by(member_id=phone).scalar()

    return jsonify({
        "member": {
            "name": member.name,
            "level": member.level,
            "email": member.email,
            "phone_number": member.phone_number,
            "age": member.age,
        },
        "stats": {
            "total_checkins": checkins,
            "total_favorites": favorites,
            "last_checkin_at": last_checkin.isoformat() if last_checkin else None
        }
    })

@app.route('/api/products', methods=['GET'])
def get_products_api():
    products = Products.query.all()
    return jsonify({
        "products": [
            {
                "id": p.id,
                "image_url": p.image_url if p.image_url else "https://via.placeholder.com/150.png",
                "name": p.name,
                "price": f'NT${p.price:.0f}',
                "description": p.description or "暫無描述",
                "favorite_count": p.favorite_count or 0
            } for p in products
        ]
    })

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({"message": "請輸入 email 與密碼"}), 400

    member = Members.query.filter_by(email=email).first()
    if not member or not member.verify_password(password):
        return jsonify({"message": "帳號或密碼錯誤"}), 401

    # 需要會話的網頁端可直接獲得登入狀態
    login_user(member)

    return jsonify({
        "member": {
            "name": member.name,
            "phone_number": member.phone_number,
            "level": member.level,
            "email": member.email
        }
    })

@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json(silent=True) or {}
    phone    = data.get('phone_number', '').strip()
    name     = data.get('name', '').strip()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')
    age      = data.get('age')

    if not all([phone, name, email, password, age]):
        return jsonify({"message": "所有欄位皆為必填"}), 400

    if Members.query.filter_by(email=email).first():
        return jsonify({"message": "Email 已被註冊"}), 409
    if Members.query.filter_by(phone_number=phone).first():
        return jsonify({"message": "電話號碼已被註冊"}), 409

    try:
        member = Members(
            phone_number=phone,
            name=name,
            email=email,
            password=password,
            age=int(age),
            level='bronze'
        )
        db.session.add(member)
        db.session.commit()
        return jsonify({
            "message": "註冊成功",
            "member": {
                "phone_number": phone,
                "name": name,
                "email": email,
                "level": "bronze"
            }
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"註冊失敗：{e}"}), 500



@app.route('/api/colors', methods=['GET'])
def get_colors():
    colors = ColorPalettes.query.all()
    return jsonify({
        "colors": [
            {
                "title": c.title,
                "hex": c.hex_code,
                "tags": c.tags
            } for c in colors
        ]
    })


MAKEUP_CATEGORIES = [
    {"name": "口紅", "type": "lipsticks", "endpoint": "/api/lipsticks", "model": Lipsticks},
    {"name": "粉底", "type": "foundations", "endpoint": "/api/foundations", "model": Foundations},
    {"name": "腮紅", "type": "blushes", "endpoint": "/api/blushes", "model": Blushes},
    {"name": "眼影", "type": "eyeshadows", "endpoint": "/api/eyeshadows", "model": Eyeshadows},
    {"name": "眼線與睫毛膏", "type": "eyeliner_mascara", "endpoint": "/api/eyeliner_mascara", "model": EyelinerMascara},
    {"name": "修容", "type": "contouring", "endpoint": "/api/contouring", "model": Contouring},
    {"name": "打亮", "type": "highlighters", "endpoint": "/api/highlighters", "model": Highlighters},
    {"name": "眉彩", "type": "eyebrows", "endpoint": "/api/eyebrows", "model": Eyebrows},
]


def category_payload(category):
    return {
        "name": category["name"],
        "type": category["type"],
        "endpoint": category["endpoint"],
    }


def find_makeup_category(category_type):
    for category in MAKEUP_CATEGORIES:
        if category["type"] == category_type:
            return category
    return None


def guess_image_mime_from_base64(data):
    if data.startswith("/9j/"):
        return "image/jpeg"
    if data.startswith("iVBOR"):
        return "image/png"
    if data.startswith("R0lG"):
        return "image/gif"
    if data.startswith("UklGR"):
        return "image/webp"
    return "image/jpeg"


def guess_image_mime_from_bytes(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"GIF"):
        return "image/gif"
    if data.startswith(b"RIFF"):
        return "image/webp"
    return "image/jpeg"


def image_src(data):
    if not data:
        return ""

    if isinstance(data, bytes):
        mime = guess_image_mime_from_bytes(data)
        encoded = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    value = str(data).strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "data:", "/")):
        return value
    if value.startswith("//"):
        return f"https:{value}"

    compact_value = "".join(value.split())
    mime = guess_image_mime_from_base64(compact_value)
    return f"data:{mime};base64,{compact_value}"


def display_price(value):
    if value is None:
        return "NT$0"
    try:
        return f"NT${float(value):.0f}"
    except (TypeError, ValueError):
        return str(value)


def product_card_payload(item, category_type):
    return {
        "id": item.id,
        "type": category_type,
        "brand": getattr(item, "brand", "") or "",
        "name": getattr(item, "product_name", None) or getattr(item, "name", "未命名商品"),
        "price": display_price(getattr(item, "price", None)),
        "description": getattr(item, "description", "") or "暫無描述",
        "image_src": image_src(getattr(item, "image_data", "")),
        "shade_name": getattr(item, "shade_name", "") or "",
        "category_name": getattr(item, "category_name", "") or "",
        "sale_page_id": getattr(item, "sale_page_id", "") or "",
    }


@app.route('/products-page')
@app.route('/products-page/<category_type>')
def products_page(category_type='lipsticks'):
    selected_category = find_makeup_category(category_type) or MAKEUP_CATEGORIES[0]
    page = request.args.get("page", 1, type=int)
    pagination = (
        selected_category["model"]
        .query
        .order_by(selected_category["model"].id.desc())
        .paginate(page=page, per_page=24, error_out=False)
    )
    products = [
        product_card_payload(item, selected_category["type"])
        for item in pagination.items
    ]

    return render_template(
        "products.html",
        title="商品瀏覽",
        categories=[category_payload(category) for category in MAKEUP_CATEGORIES],
        selected_category=category_payload(selected_category),
        products=products,
        pagination=pagination,
    )


def decode_image(data):
    #將資料庫的 BLOB 圖片轉為前端可用的 Base64 字串
    if isinstance(data, bytes):
        return base64.b64encode(data).decode('utf-8')
    return data

def decode_text(data):
    #將資料庫的二進位文字解碼為一般字串
    if isinstance(data, bytes):
        try:
            return data.decode('utf-8')
        except UnicodeDecodeError:
            return ""
    return data

@app.route('/api/products/all', methods=['GET'])
def get_all_makeup_categories():
    return jsonify({
        "categories": [category_payload(category) for category in MAKEUP_CATEGORIES]
    })

@app.route('/api/lipsticks', methods=['GET'])
def get_lipsticks():
    items = Lipsticks.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "lipsticks", "brand": getattr(i, 'brand', ''),
        "name": getattr(i, 'product_name', ''),
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab_json', '')),
        "shade_name": getattr(i, 'shade_name', '')
    } for i in items]})

@app.route('/api/foundations', methods=['GET'])
def get_foundations():
    items = Foundations.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "foundations", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "shade_name": getattr(i, 'shade_name', '')
    } for i in items]})

@app.route('/api/blushes', methods=['GET'])
def get_blushes():
    items = Blushes.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "blushes", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "sale_page_id": getattr(i, 'sale_page_id', '')
    } for i in items]})

@app.route('/api/eyeshadows', methods=['GET'])
def get_eyeshadows():
    items = Eyeshadows.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "eyeshadows", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "sale_page_id": getattr(i, 'sale_page_id', '')
    } for i in items]})

@app.route('/api/eyeliner_mascara', methods=['GET'])
def get_eyeliner_mascara():
    items = EyelinerMascara.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "eyeliner_mascara", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "category_name": getattr(i, 'category_name', ''),
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "sale_page_id": getattr(i, 'sale_page_id', '')
    } for i in items]})

@app.route('/api/contouring', methods=['GET'])
def get_contouring():
    items = Contouring.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "contouring", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "sale_page_id": getattr(i, 'sale_page_id', '')
    } for i in items]})

@app.route('/api/highlighters', methods=['GET'])
def get_highlighters():
    items = Highlighters.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "highlighters", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "sale_page_id": getattr(i, 'sale_page_id', '')
    } for i in items]})

@app.route('/api/eyebrows', methods=['GET'])
def get_eyebrows():
    items = Eyebrows.query.all()
    return jsonify({"products": [{
        "id": i.id, "type": "eyebrows", "brand": getattr(i, 'brand', ''),
        "name": i.name,
        "category_name": getattr(i, 'category_name', ''),
        "price": f"NT${i.price:.0f}" if i.price else "NT$0", "description": i.description,
        "image_data": decode_image(i.image_data),
        "lab_json": decode_text(getattr(i, 'lab', '')),
        "sale_page_id": getattr(i, 'sale_page_id', '')
    } for i in items]})

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        app.run(
            host='0.0.0.0',
            port=int(os.getenv("PORT", 5001)),
            debug=os.getenv("FLASK_DEBUG", "1") == "1"
        )
