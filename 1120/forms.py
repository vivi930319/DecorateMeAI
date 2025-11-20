from flask_wtf import FlaskForm
from wtforms import StringField,PasswordField,SubmitField,IntegerField
from wtforms.validators import DataRequired, email, equal_to, length, ValidationError, EqualTo
from models import Members

class RegistrationFrom(FlaskForm):
    name = StringField('姓名',validators=[DataRequired(),length(min=2,max=50)])
    email = StringField('電子郵件',validators=[DataRequired(),email()])
    password = PasswordField('密碼',validators=[DataRequired(),length(min=6)])
    confirm_password = PasswordField("確認密碼",validators=[DataRequired(),EqualTo('password',message='密碼必須一致')])
    age = IntegerField('年齡',validators=[DataRequired()])
    level = StringField('會員等級（bronze/silver/gold)',default='bronze')
    submit = SubmitField('註冊')

    def validate_emial(self,email):
        member = Members.query.filter_by(email=email.date).first()
        if member:
            raise ValidationError('該電子郵件已被註冊，請使用不同的電子郵件')

class LoginForm(FlaskForm):
    email  = StringField('電子郵件',validators=[DataRequired(),email()])
    password =PasswordField('密碼',validators=[DataRequired()])
    submit = SubmitField('登入')