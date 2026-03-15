from extensions import db, bcrypt
from flask_login import UserMixin


#會員資料，主要目的是儲存和管理所有使用者或會員的身份信息、認證憑證以及其在系統中的等級屬性，裡面包括了提供每位會員的唯一識別碼（透過 phone_number 欄位）、安全加密後的密
# 碼雜湊值（password_hash），以及姓名、電子郵件和會員等級這些基本資訊，透過這些數據讓系統能夠驗證使用者的身份、管理登入和登出的狀態、並根據會員等級提供不同的服務或權限
class Members(db.Model, UserMixin):
    __tablename__ = 'members'

    # 使用 phone_number 作為主鍵
    phone_number = db.Column(db.String(20), primary_key=True, unique=True)

    name = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    # 密碼儲存雜湊值
    password_hash = db.Column(db.String(255), nullable=False)
    level = db.Column(db.Enum('bronze', 'silver', 'gold', name='member_level'), default='bronze')
    age = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    @property
    def password(self):
        raise AttributeError("密碼不是可讀取的屬性")

    @password.setter
    def password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def verify_password(self, password):
        # 用於登入時驗證密碼
        return bcrypt.check_password_hash(self.password_hash, password)


    def get_id(self):
        return str(self.phone_number)

    # 一個會員可以有多筆 checkin 記錄
    checkins = db.relationship('Checkin', backref='member', lazy=True)

#產品資料，用於儲存和管理應用程式中所有可供銷售、展示或追蹤的商品信息，裡面包括了每件產品的唯一識別碼（id 欄位）、名稱（name）和定價（price），stock 欄位追蹤每件商品
# 的庫存數量，也包含詳細的描述（description）和商品創建的時間
 # 儲存圖片網址
class Products(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    image_url = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text)
    favorite_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


class Checkin(db.Model):
    __tablename__ = 'checkins'
    id = db.Column(db.Integer, primary_key=True)
    # 外鍵參照 members.phone_number
    member_id = db.Column(db.String(20), db.ForeignKey('members.phone_number'), nullable=False)
    checkin_time = db.Column(db.DateTime, server_default=db.func.now())
    note = db.Column(db.Text)


class Favorites(db.Model):
    __tablename__ = 'favorites'
    __table_args__ = (
        db.UniqueConstraint('member_id', 'product_id', name='uq_member_product'),
    )

    id = db.Column(db.Integer, primary_key=True)
    # 指向會員的電話 (外鍵)
    member_id = db.Column(db.String(20), db.ForeignKey('members.phone_number'), nullable=False)
    # 指向產品的 ID (外鍵)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    # 建立關聯，方便在 Python 裡直接查詢物件
    member = db.relationship('Members', backref=db.backref('favorite_list', lazy=True))
    product = db.relationship('Products', backref=db.backref('favorited_by', lazy=True))

class ColorPalettes(db.Model):
    __tablename__ = 'color_palettes'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    title = db.Column(db.String(100))
    hex_code = db.Column(db.String(7), nullable=False, unique=True)
    source_url = db.Column(db.String(255))
    tags = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, server_default=db.func.now())
