from app import app
from extensions import db
from models import Members

with app.app_context():
    email = "alice4@example.com"
    member = Members.query.filter_by(email=email).first()
    if not member:
        new_member = Members(
            name="Alice",
            email=email,
            password="secret123",
            level="bronze",
            age=25
        )
        db.session.add(new_member)
        db.session.commit()
        print("新增會員成功")
    else:
        print("會員已存在:", member.email)

    # 查詢第一筆會員
    first_member = Members.query.first()
    print("第一筆會員:", first_member.name, first_member.email)

