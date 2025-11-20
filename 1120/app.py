from flask import Flask, url_for,request,flash
from werkzeug.utils import redirect

from extensions import db, bcrypt, login_manager
import config
from models import Members
from forms import RegistrationFrom,LoginForm
from flask_login import login_user,current_user,logout_user,login_required

app=  Flask(__name__)
app.config.from_object(config)
app.config['SECRET_KEY'] = 'your_secret_key_here'
db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

login_manager.login_view='login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    return Members.query.get(int(user_id))

@app.route('/')
def index():
    return "flask mySQL DB initialized successfully"

@app.route("/login",methods=['GET','POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        member  =  Members.query.filter_by(email=form.email.data).first()
        if member and member.verify_password(form.password.data):
            login_user(member)
            next_page = request.args.get('next')
            flash('登入成功！','success')
            return  redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('登入失敗，請檢查電子郵件或密碼','danger')

            return "登入頁面（需要login.html模板）"

@app.route("/logout")
def logout():
    logout_user()
    flash('你已成功登出！','info')
    return redirect(url_for('index'))

@app.route("/profile")
@login_required
def profile():
    return f"歡迎來到會員中心，{current_user.name}!您的等級是{current_user.level}"

if __name__ =="__main__":
    with app.app_context():
        db.create_all()
        app.run(debug=True)

if __name__ =="__main__":
    with app.app_context():
        db.create_all()
        app.run(debug=True)