#sql.py 主要目的是在 Flask 應用程式啟動流程之外，提供一個獨立的環境來執行資料庫操作，特別是用於手動插入測試資料或進行批次資料管理
#(用於批量插入 CSV 資料)
import csv
import os

from app import app
from extensions import db
from models import Members, Checkin, Products, ColorPalettes

# 檔案路徑
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE_PATH = os.path.join(BASE_DIR, 'members_data.csv')
PRODUCT_CSV = os.path.join(BASE_DIR, 'products_data.csv')
COLOR_CSV = os.path.join(BASE_DIR, 'colors_data.csv')


# 批量插入 CSV 資料的函式
def batch_insert_members_from_csv():
    members_to_add = []
    try:
        with open(CSV_FILE_PATH, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if Members.query.filter_by(phone_number=row['phone_number']).first():
                    print(f"警告：電話號碼 {row['phone_number']} 已存在，跳過。")
                    continue
                member = Members(
                    phone_number=row['phone_number'],
                    name=row['name'],
                    email=row['email'],
                    password=row['raw_password'],
                    level=row['level'],
                    age=int(row['age'])
                )
                members_to_add.append(member)
        if members_to_add:
            db.session.add_all(members_to_add)
            db.session.commit()
            print(f"已從 CSV 插入 {len(members_to_add)} 筆會員資料。")
    except Exception as e:
        db.session.rollback()
        print(f"會員批量插入失敗：{e}")

# 單次插入測試資料的函式 (可選功能)
def insert_single_test_member():
    member_phone = "0987654321"
    try:
        member = Members.query.filter_by(phone_number=member_phone).first()
        if not member:
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
            print(f"新增會員成功: {new_member.phone_number}")
            target_member = new_member
        else:
            print("單次測試會員已存在，跳過新增。")
            target_member = member

        new_checkin = Checkin(member_id=target_member.phone_number, note="首次報到測試")
        db.session.add(new_checkin)
        db.session.commit()
        print(f"簽到記錄成功: {target_member.name}")
    except Exception as e:
        db.session.rollback()
        print(f"單次會員插入失敗：{e}")

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
    try:
        if not os.path.exists(PRODUCT_CSV): return
        with open(PRODUCT_CSV, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                if Products.query.filter_by(name=row['name']).first():
                    print(f"產品「{row['name']}」已存在，跳過。")
                    continue
                p = Products(
                    image_url=row['image_url'],
                    name=row['name'],
                    price=float(row['price']),
                    description=row['description']
                )
                db.session.add(p)
            db.session.commit()
            print("產品 CSV 處理完成。")
    except Exception as e:
        db.session.rollback()
        print(f"產品批量插入失敗：{e}")

# --- 產品單次插入功能 ---
def insert_single_product():
    test_products = [
        {"img": "https://images.unsplash.com/photo-1601049541289-9b1b7bbbfe19?w=500", "name": "美妝測試", "price": 380, "desc": "測試1"},
        {"img": "https://images.unsplash.com/photo-1512496015851-a90fb38ba796?w=500", "name": "美妝測試2", "price": 350, "desc": "測試2"}
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
                db.session.add(new_product) # 修正：確保在 if 內部
                print(f"單次產品新增成功: {item['name']}")
            else:
                print(f"產品「{item['name']}」已存在，跳過。")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"單次產品新增失敗: {e}")

# --- 色碼批量插入 (CSV) ---
COLOR_CSV = os.path.join(BASE_DIR, 'colors_data.csv')

# 2. 修正批量插入函式
def batch_insert_colors_from_csv():
    """從 color_data.csv 批量存放爬蟲資料，並檢查重複"""
    try:
        if not os.path.exists(COLOR_CSV):
            print(f"提示：找不到檔案 {COLOR_CSV}")
            return

        existing_hexes = {c.hex_code for c in ColorPalettes.query.with_entities(ColorPalettes.hex_code).all()}
        colors_to_add = []

        with open(COLOR_CSV, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                hex_val = row['hex_code']
                if hex_val in existing_hexes:
                    print(f"色碼「{hex_val}」已存在，跳過。")
                    continue

                color = ColorPalettes(
                    title=row['title'],
                    hex_code=hex_val,
                    source_url=row.get('source_url', ''),
                    tags=row.get('tags', '')
                )
                colors_to_add.append(color)
                existing_hexes.add(hex_val)

        if colors_to_add:
            db.session.add_all(colors_to_add)
            db.session.commit()
            print(f"成功存放 {len(colors_to_add)} 筆新色碼。")
    except Exception as e:
        db.session.rollback()
        print(f"批量色碼存放失敗：{e}")

# --- 色碼單次or手動插入 ---
def insert_single_test_colors():
    test_colors = [
        {"title": "蒂芬妮藍", "hex": "#0ABAB5", "url": "https://example.com", "tags": "測試1"},
        {"title": "亮橘", "hex": "#E65A28", "url": "https://example.com", "tags": "測試2"}
    ]
    try:
        for item in test_colors:
            existing = ColorPalettes.query.filter_by(hex_code=item['hex']).first()
            if not existing:
                new_c = ColorPalettes(
                    title=item['title'],
                    hex_code=item['hex'],
                    source_url=item['url'],
                    tags=item['tags']
                )
                db.session.add(new_c)
                print(f"單次色碼新增成功: {item['title']} ({item['hex']})")
            else:
                print(f"色碼「{item['hex']}」已存在，跳過。")
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"單次色碼新增失敗：{e}")

# 執行入口
if __name__ == '__main__':
    with app.app_context():
        # 執行批量and單人插入 CSV-會員
        print("=== [1] 會員與簽到系統 ===")
        batch_insert_members_from_csv()
        insert_single_test_member()

        # 執行批量and單人插入 CSV-產品
        print("\n=== [2] 產品系統 ===")
        batch_insert_products_from_csv()
        insert_single_product()

        # 執行插入我的最愛
        print("\n=== [3] 我的最愛系統 ===")
        insert_test_favorites()

        # 執行批量and單人插入 CSV-色碼
        print("\n=== [4] 色碼資料庫系統 ===")
        batch_insert_colors_from_csv()
        insert_single_test_colors()

        print("\n全部資料同步完成")
