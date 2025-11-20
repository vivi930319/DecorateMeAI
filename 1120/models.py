from flask_login import UserMixin
from extensions import bcrypt

from extensions import db


class Members(db.Model,UserMixin):
    __tablename__ = 'members'
    id = db.Column(db.Integer,primary_key=True)
    name = db.Column(db.String(255),primary_key=False)
    email =db.Column(db.String(100),unique=True,nullable=False)
    password_hash = db.Column(db.String(255),nullable=False)
    level = db.Column(db.Enum('bronze','silver','gold',name='member_level'),default='bronze')
    age = db.Column(db.Integer)
    created_at = db.Column(db.DateTime,server_default=db.func.now())

@property
def password(self):
    raise AttributeError("密碼不是可讀取的屬性")

@password.setter
def password(self,password):
    self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

def verfiy_password(self,password):
    return bcrypt.check_password_hash(self.password_hash,password)

checkins = db.relationship('Checkin',backref='member',lazy=True)

class Products(db.Model):
    __tabelname__ = "products"
    id = db.Column(db.Integer,primary_key=True)
    name = db.Column(db.String(50),nullable=False)
    price = db.Column(db.Numeric(10,2),nullable=False)
    stock = db.Column(db.Integer,default=0)
    decription = db.Column(db.Text)
    created_at = db.Column(db.DateTime,server_default=db.func.now())\

class Checkin(db.Model):
    __tabelname__ ='checkins'
    id = db.Column(db.Integer,primary_key=True)
    member_id =  db.Column(db.Integer,db.ForeignKey('members.id'),nullable=False)
    checkin_time = db.Column(db.DateTime,server_default=db.func.now())
    location = db.Column(db.String(100))
    note = db.Column(db.Text)

    Members.checkins = db.relationship('Checkin', backref='member', lazy=True)