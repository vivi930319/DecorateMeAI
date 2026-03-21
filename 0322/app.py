from datetime import date
from flask import Flask, url_for, flash, redirect, request, render_template, jsonify
from flask_cors import CORS
from flask_login import login_user, current_user, logout_user, login_required
from sqlalchemy.exc import IntegrityError

import config
from extensions import db, bcrypt, login_manager
from models import Members, Products, Favorites, ColorPalettes, Checkin
from forms import RegistrationForm, LoginForm, ChangePasswordForm


#app.py 是整個 Flask 應用程式的主程式和入口點，負責設定環境、連接資料庫、定義網頁路徑（路由），以及處理所有的使用者互動邏輯（註冊、登入）
app = Flask(__name__)
CORS(app)
#從config.py 檔案中載入所有設定，和資料庫的連線資訊 (SQLALCHEMY_DATABASE_URI)
app.config.from_object(config)
#設定一個秘密金鑰，這是 Flask 用於保護網站安全
app.config['SECRET_KEY'] = getattr(config, 'SECRET_KEY', 'change-me')
db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

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
                level=form.level.data if form.level.data in {"bronze", "silver", "gold"} else "bronze"
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

#我的最愛清單-點擊收藏 (新增/刪除）
@app.route('/api/favorites/toggle', methods=['POST'])
def toggle_favorite():
    data = request.get_json(silent=True) or {}
    phone = data.get('phone_number')
    p_id = data.get('product_id')

    if not phone or p_id is None:
        return jsonify({"status": "error", "message": "缺少 phone_number 或 product_id"}), 400

    # 檢查是否已收藏
    fav = Favorites.query.filter_by(member_id=phone, product_id=p_id).first()

    # 取消收藏
    if fav:
        db.session.delete(fav)
        product = Products.query.get(p_id)
        if product and product.favorite_count > 0:
            product.favorite_count -= 1
        db.session.commit()
        return jsonify({"status": "removed", "message": "已從我的最愛移除"})
    #加入收藏
    else:
        try:
            new_fav = Favorites(member_id=phone, product_id=p_id)
            db.session.add(new_fav)
            product = Products.query.get(p_id)
            if product:
                product.favorite_count = (product.favorite_count or 0) + 1
            db.session.commit()
            return jsonify({"status": "added", "message": "已加入我的最愛"})
        except IntegrityError:
            db.session.rollback()
            return jsonify({"status": "error", "message": "此商品已在收藏清單"}), 400


@app.route('/api/members/<phone>/favorites', methods=['GET'])
def get_user_favorites(phone):
    # 找出該會員的所有收藏
    favs = Favorites.query.filter_by(member_id=phone).all()
    # 透過關聯取得產品詳細資訊
    product_list = [{
        "id": f.product.id,
        "name": f.product.name,
        "price": float(f.product.price),
        "image_url": f.product.image_url or "https://via.placeholder.com/150.png",
        "description": f.product.description or "暫無描述",
        "favorite_count": f.product.favorite_count or 0
    } for f in favs]
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
    return jsonify({"message": "簽到完成", "checkin_time": new_checkin.checkin_time})


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
            "last_checkin_at": last_checkin
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


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        app.run(host='0.0.0.0', port=8080, debug=True)
