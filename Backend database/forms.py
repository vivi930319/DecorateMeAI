from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError
from models import Members

#forms.py 的內容是用來定義Flask 應用程式中所有使用者介面表單的結構、欄位類型和驗證規則，並且使用了 Flask-WTF 庫，該庫是基於 WTForms 的 Flask 整合套件
# 註冊表單
class RegistrationForm(FlaskForm):
    phone_number = StringField('電話號碼 (會員ID)', validators=[DataRequired(), Length(min=8, max=20)])
    name = StringField('姓名', validators=[DataRequired(), Length(min=2, max=50)])
    email = StringField('電子郵件', validators=[DataRequired(), Email()])
    password = PasswordField('密碼', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('確認密碼', validators=[
        DataRequired(),
        EqualTo('password', message='密碼必須一致')
    ])
    age = IntegerField('年齡', validators=[DataRequired()])
    submit = SubmitField('註冊')

    # 檢查 Email 是否已存在
    def validate_email(self, email):
        member = Members.query.filter_by(email=email.data).first()
        if member:
            raise ValidationError('該電子郵件已被註冊。')

    # 檢查 phone_number 是否已存在
    def validate_phone_number(self, phone_number):
        member = Members.query.filter_by(phone_number=phone_number.data).first()
        if member:
            raise ValidationError('該電話號碼已被註冊。')


# 登入表單
class LoginForm(FlaskForm):
    # 這裡使用 phone_number 或 email 登入都可以，
    email = StringField('電子郵件', validators=[DataRequired(), Email()])
    password = PasswordField('密碼', validators=[DataRequired()])
    submit = SubmitField('登入')


class ForgotPasswordRequestForm(FlaskForm):
    email = StringField('註冊電子郵件', validators=[DataRequired(), Email()])
    submit = SubmitField('寄送驗證碼')


class ResetPasswordForm(FlaskForm):
    email = StringField('註冊電子郵件', validators=[DataRequired(), Email()])
    otp = StringField('驗證碼', validators=[DataRequired(), Length(min=6, max=6)])
    new_password = PasswordField('新密碼', validators=[DataRequired(), Length(min=6)])
    confirm_new_password = PasswordField('確認新密碼', validators=[
        DataRequired(),
        EqualTo('new_password', message='新密碼必須一致')
    ])
    submit = SubmitField('重設密碼')


# 更改密碼表單
class ChangePasswordForm(FlaskForm):
    # 舊密碼用於驗證使用者身份
    old_password = PasswordField('舊密碼', validators=[DataRequired()])

    # 新密碼的長度要求
    new_password = PasswordField('新密碼', validators=[DataRequired(), Length(min=6)])

    # 確認新密碼，確保與新密碼欄位一致
    confirm_new_password = PasswordField('確認新密碼', validators=[
        DataRequired(),
        EqualTo('new_password', message='新密碼必須一致')
    ])
    submit = SubmitField('更改密碼')
