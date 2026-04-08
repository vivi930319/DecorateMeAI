from app import app
from sql import (
    batch_insert_members_from_csv,
    insert_single_test_member,
    batch_insert_products_from_csv,
    insert_single_product,
    insert_test_favorites,
    batch_insert_colors_from_csv,
    insert_single_test_colors,
)


def main() -> None:
    with app.app_context():
        print("=== [1] 會員與簽到系統 ===")
        batch_insert_members_from_csv()
        insert_single_test_member()

        print("\n=== [2] 產品系統 ===")
        batch_insert_products_from_csv()
        insert_single_product()

        print("\n=== [3] 我的最愛系統 ===")
        insert_test_favorites()

        print("\n=== [4] 色碼資料庫系統 ===")
        batch_insert_colors_from_csv()
        insert_single_test_colors()

        print("\n全部資料同步完成")


if __name__ == "__main__":
    main()
