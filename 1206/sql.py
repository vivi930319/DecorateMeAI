from app import app
from extensions import db
from models import Members, Checkin

#sql.py 主要目的是在 Flask 應用程式啟動流程之外，提供一個獨立的環境來執行資料庫操作，特別是用於手動插入測試資料或進行批次資料管理
with app.app_context():

    member_phone = "0987654321"

    # 查詢 phone_number 是否已存在
    member = Members.query.filter_by(phone_number=member_phone).first()

    if not member:
        # 填入資料
        new_member = Members(
            phone_number=member_phone,
            name="David",
            email="david.test@example.com",
            password="abcde12345",  # 傳給 password 屬性，會自動雜湊並存入 password_hash 欄位
            level="gold",
            age=25
        )

        # 加入會話之後提交
        db.session.add(new_member)
        db.session.commit()
        print(f"新增會員成功，電話號碼: {new_member.phone_number}")
    else:
        print("會員已存在:", member.phone_number)

    # 示範新增一筆簽到記錄
    if member or new_member:
        # 使用剛才新增的會員，或查詢到的會員
        target_member = member if member else new_member

        new_checkin = Checkin(
            member_id=target_member.phone_number,
            note="首次報到測試"
        )
        db.session.add(new_checkin)
        db.session.commit()
        print(f"新增簽到記錄成功，會員: {target_member.name}")
