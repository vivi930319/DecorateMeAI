#sql.py 主要目的是在 Flask 應用程式啟動流程之外，提供一個獨立的環境來執行資料庫操作，特別是用於手動插入測試資料或進行批次資料管理
#(用於批量插入 CSV 資料)
import csv
import os

from app import app
from extensions import db
from models import Members, Checkin, Products

# 檔案路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(BASE_DIR, 'members_data.csv')
PRODUCT_CSV = os.path.join(BASE_DIR, 'products_data.csv')


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
                name="Cindy",
                email="Cindy.test@example.com",
                password="rtery13789",
                level="silver",
                age=28
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

# 產品加入我的最愛
def insert_test_favorites():
    with app.app_context():

        test_phone = "0987654321"
        member = Members.query.filter_by(phone_number=test_phone).first()

        if not member:
            print(f"錯誤：會員 {test_phone} 不存在，無法建立收藏。")
            return

        # 抓取資料庫中現有的第一個產品，確保 ID 是一定存在的
        product = Products.query.first()
        if not product:
            print("錯誤：資料庫裡沒有任何產品，無法建立收藏。")
            return

        # 檢查是否已收藏過
        from models import Favorites
        existing = Favorites.query.filter_by(member_id=member.phone_number, product_id=product.id).first()

        if not existing:
            try:
                new_fav = Favorites(member_id=member.phone_number, product_id=product.id)
                db.session.add(new_fav)
                db.session.commit()
                print(f"成功為會員 {member.name} 新增收藏：{product.name} (ID: {product.id})")
            except Exception as e:
                db.session.rollback()
                print(f" 寫入收藏時發生意外錯誤: {e}")
        else:
            print(f"{member.name} 已收藏過「{product.name}」")

# --- 產品批量插入功能 ---
def batch_insert_products_from_csv():
    """從 products_data.csv 批量插入產品，包含重複檢查與回滾"""
    products_to_add = []
    try:
        if not os.path.exists(PRODUCT_CSV):
            print(f"錯誤：找不到檔案 {PRODUCT_CSV}")
            return

        with open(PRODUCT_CSV, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                # 重複檢查,根據名稱判斷產品是否已存在
                if Products.query.filter_by(name=row['name']).first():
                    print(f"產品「{row['name']}」已存在，跳過。")
                    continue

                product = Products(
                    image_url=row['image_url'],
                    name=row['name'],
                    price=float(row['price']),
                    description=row['description']
                )
                products_to_add.append(product)

        if products_to_add:
            db.session.add_all(products_to_add)
            db.session.commit()
            print(f"成功批量插入 {len(products_to_add)} 筆產品資料。")
        else:
            print("沒有新產品需要新增。")

    except Exception as e:
        # 發生錯誤時回滾
        db.session.rollback()
        print(f"產品批量插入失敗，已執行回滾。錯誤資訊: {e}")

# --- 產品單次插入功能 ---
def insert_single_product():
    """單次插入產品測試資料"""
    test_products= [
        {
            "img": "https://images.unsplash.com/photo-1601049541289-9b1b7bbbfe19?w=500",
            "name": "美妝測試",
            "price": 380,
            "desc": "測試1"
        },
        {
            "img": "https://images.unsplash.com/photo-1512496015851-a90fb38ba796?w=500",
            "name": "美妝測試2",
            "price": 350,
            "desc": "測試2"
        }
    ]
    try:
        for item in test_products:
            existing = Products.query.filter_by(name=item['name']).first()
            if not existing:
                new_product = Products(
                    image_url=item['img'],
                    name=item['name'],
                    price=item['price'],
                    description=item['desc']
                )
            db.session.add(new_product)
            print(f"單次產品新增成功")
            db.session.commit()
        else:
            print(f"產品已存在，跳過單次新增。")
    except Exception as e:
        db.session.rollback()
        print(f"單次產品新增失敗，已回滾: {e}")

        print("--- 開始處理產品資料 ---")


# 執行入口
if __name__ == '__main__':
    with app.app_context():
        # 執行批量and單人插入 CSV-會員
        batch_insert_members_from_csv()
        insert_single_test_member()

        # 執行批量and單人插入 CSV-產品
        batch_insert_products_from_csv()
        insert_single_product()

        # 執行插入我的最愛
        insert_test_favorites()
