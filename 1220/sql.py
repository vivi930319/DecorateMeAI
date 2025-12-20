#sql.py 主要目的是在 Flask 應用程式啟動流程之外，提供一個獨立的環境來執行資料庫操作，特別是用於手動插入測試資料或進行批次資料管理
#(用於批量插入 CSV 資料)
import csv
import os

from app import app
from extensions import db
from models import Members, Checkin  # 確保導入所有模型

# 檔案路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(BASE_DIR, 'members_data.csv')


# 批量插入 CSV 資料的函式
def batch_insert_members_from_csv():
    """從 members_data.csv 檔案中讀取並批量插入會員資料。"""
    members_to_add = []

    try:
        # 檔案操作
        with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)

            for row in reader:
                # 確保電話號碼不重複
                if Members.query.filter_by(phone_number=row['phone_number']).first():
                    print(f"警告：電話號碼 {row['phone_number']} 已存在，跳過。")
                    continue

                # 創建 Members 物件
                member = Members(
                    phone_number=row['phone_number'],
                    name=row['name'],
                    email=row['email'],
                    password=row['raw_password'],
                    level=row['level'],
                    age=int(row['age'])
                )
                members_to_add.append(member)

        # 資料庫操作
        if not members_to_add:
            print("CSV 檔案中沒有新的會員資料需要新增。")
            return

        db.session.add_all(members_to_add)
        db.session.commit()

        print(f"--- CSV 批量插入成功 ---")
        print(f"已從 CSV 檔案中插入 {len(members_to_add)} 筆會員資料。")
        print(f"--------------------------")

    # 3. 錯誤處理
    except FileNotFoundError:
        print(f"錯誤：找不到檔案 {CSV_FILE_PATH}。請確認檔案是否存在於 {BASE_DIR}")
    except Exception as e:
        db.session.rollback()
        print(f"批量插入過程中發生錯誤，已回滾：{e}")


# 單次插入測試資料的函式 (可選功能)
def insert_single_test_member():
    """插入單筆會員和簽到記錄的測試資料。"""
    member_phone = "0987654321"

    try:
        member = Members.query.filter_by(phone_number=member_phone).first()

        if not member:
            # 填入資料
            new_member = Members(
                phone_number=member_phone,
                name="David Test",
                email="david.test@example.com",
                password="abcde12345",
                level="gold",
                age=25
            )
            db.session.add(new_member)
            db.session.commit()
            print(f"新增會員成功，電話號碼: {new_member.phone_number}")
            target_member = new_member
        else:
            print("單次測試會員已存在，跳過新增會員。")
            target_member = member

        # 新增一筆簽到記錄
        new_checkin = Checkin(
            member_id=target_member.phone_number,
            note="首次報到測試"
        )
        db.session.add(new_checkin)
        db.session.commit()
        print(f"新增簽到記錄成功，會員: {target_member.name}")

    # 錯誤處理
    except Exception as e:
        db.session.rollback()
        print(f"單次插入過程中發生錯誤，已回滾：{e}")


# 執行入口
if __name__ == '__main__':
    with app.app_context():
        # 執行批量插入 CSV
        batch_insert_members_from_csv()