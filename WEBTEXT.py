import requests
import json
import random
import time
import csv
import os
from urllib.parse import unquote

# =========================================================
#                   A. API 配置與參數
# =========================================================

# 1. 完整 API 請求 URL (包含 GraphQL Query 和 Variables)
# 這個 URL 是你成功抓取到的，用於獲取臉部保養分類的前 100 筆資料
FULL_API_URL = 'https://fts-api.91app.com/pythia-cdn/graphql?shopId=2131&lang=zh-TW&query=query%20cms_shopCategory(%24shopId%3A%20Int!%2C%20%24categoryId%3A%20Int!%2C%20%24startIndex%3A%20Int!%2C%20%24fetchCount%3A%20Int!%2C%20%24orderBy%3A%20String%2C%20%24isShowCurator%3A%20Boolean%2C%20%24locationId%3A%20Int%2C%20%24tagFilters%3A%20%5BItemTagFilter%5D%2C%20%24tagShowMore%3A%20Boolean%2C%20%24serviceType%3A%20String%2C%20%24minPrice%3A%20Float%2C%20%24maxPrice%3A%20Float%2C%20%24payType%3A%20%5BString%5D%2C%20%24shippingType%3A%20%5BString%5D%2C%20%24includeSalePageGroup%3A%20Boolean)%20%7B%0A%20%20shopCategory(shopId%3A%20%24shopId%2C%20categoryId%3A%20%24categoryId)%20%7B%0A%20%20%20%20salePageList(startIndex%3A%20%24startIndex%2C%20maxCount%3A%20%24fetchCount%2C%20orderBy%3A%20%24orderBy%2C%20isCuratorable%3A%20%24isShowCurator%2C%20locationId%3A%20%24locationId%2C%20tagFilters%3A%20%24tagFilters%2C%20tagShowMore%3A%20%24tagShowMore%2C%20minPrice%3A%20%24minPrice%2C%20maxPrice%3A%20%24maxPrice%2C%20payType%3A%20%24payType%2C%20shippingType%3A%20%24shippingType%2C%20serviceType%3A%20%24serviceType%2C%20includeSalePageGroup%3A%20%24includeSalePageGroup)%20%7B%0A%20%20%20%20%20%20salePageList%20%7B%0A%20%20%20%20%20%20%20%20salePageId%0A%20%20%20%20%20%20%20%20title%0A%20%20%20%20%20%20%20%20picUrl%0A%20%20%20%20%20%20%20%20picList%0A%20%20%20%20%20%20%20%20salePageCode%0A%20%20%20%20%20%20%20%20price%0A%20%20%20%20%20%20%20%20suggestPrice%0A%20%20%20%20%20%20%20%20isFav%0A%20%20%20%20%20%20%20%20isComingSoon%0A%20%20%20%20%20%20%20%20isSoldOut%0A%20%20%20%20%20%20%20%20soldOutActionType%0A%20%20%20%20%20%20%20%20sellingQty%0A%20%20%20%20%20%20%20%20pairsPoints%0A%20%20%20%20%20%20%20%20pairsPrice%0A%20%20%20%20%20%20%20%20priceDisplayType%0A%20%20%20%20%20%20%20%20displayTags%20%7B%0A%20%20%20%20%20%20%20%20%20%20group%0A%20%20%20%20%20%20%20%20%20%20keys%20%7B%0A%20%20%20%20%20%20%20%20%20%20%20%20id%0A%20%20%20%20%20%20%20%20%20%20%20%20startTime%0A%20%20%20%20%20%20%20%20%20%20%20%20endTime%0A%20%20%20%20%20%20%20%20%20%20%20%20picUrl%20%7B%0A%20%20%20%20%20%20%20%20%20%20%20%20%20%20ratioOneToOne%0A%20%20%20%20%20%20%20%20%20%20%20%20%20%20ratioThreeToFour%0A%20%20%20%20%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20displayPointsPayPairsList%20%7B%0A%20%20%20%20%20%20%20%20%20%20pairsPoints%0A%20%20%20%20%20%20%20%20%20%20pairsPrice%0A%20%20%20%20%20%20%20%20%20%20pointsPayExpireDateTime%0A%20%20%20%20%20%20%20%20%20%20pointsPayId%0A%20%20%20%20%20%20%20%20%20%20pointsPayValidDateTime%0A%20%20%20%20%20%20%20%20%20%20skuId%0A%20%20%20%20%20%20%20%20%20%20pointsPayIsPeriod%0A%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20salePageGroup%20%7B%0A%20%20%20%20%20%20%20%20%20%20groupTitle%0A%20%20%20%20%20%20%20%20%20%20groupIconStyle%0A%20%20%20%20%20%20%20%20%20%20groupItems%20%7B%0A%20%20%20%20%20%20%20%20%20%20%20%20salePageId%0A%20%20%20%20%20%20%20%20%20%20%20%20itemTitle%0A%20%20%20%20%20%20%20%20%20%20%20%20itemUrl%0A%20%20%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20promotionPrices%20%7B%0A%20%20%20%20%20%20%20%20%20%20promotionEngineId%0A%20%20%20%20%20%20%20%20%20%20memberCollectionId%0A%20%20%20%20%20%20%20%20%20%20price%0A%20%20%20%20%20%20%20%20%20%20startDateTime%0A%20%20%20%20%20%20%20%20%20%20endDateTime%0A%20%20%20%20%20%20%20%20%20%20label%0A%20%20%20%20%20%20%20%20%20%20isWebPromotion%0A%20%20%20%20%20%20%20%20%20%20isAppPromotion%0A%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20isRestricted%0A%20%20%20%20%20%20%20%20enableIsComingSoon%0A%20%20%20%20%20%20%20%20isShowSellingStartDateTime%0A%20%20%20%20%20%20%20%20sellingStartDateTime%0A%20%20%20%20%20%20%20%20listingStartDateTime%0A%20%20%20%20%20%20%20%20metafields%0A%20%20%20%20%20%20%20%20salesChannel%0A%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20totalSize%0A%20%20%20%20%20%20shopCategoryId%0A%20%20%20%20%20%20shopCategoryName%0A%20%20%20%20%20%20statusDef%0A%20%20%20%20%20%20listModeDef%0A%20%20%20%20%20%20orderByDef%0A%20%20%20%20%20%20dataSource%0A%20%20%20%20%20%20tags%20%7B%0A%20%20%20%20%20%20%20%20isGroupShowMore%0A%20%20%20%20%20%20%20%20groups%20%7B%0A%20%20%20%20%20%20%20%20%20%20groupId%0A%20%20%20%20%20%20%20%20%20%20groupDisplayName%0A%20%20%20%20%20%20%20%20%20%20isKeyShowMore%0A%20%20%20%20%20%20%20%20%20%20keys%20%7B%0A%20%20%20%20%20%20%20%20%20%20%20%20keyId%0A%20%20%20%20%20%20%20%20%20%20%20%20keyDisplayName%0A%20%20%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20priceRange%20%7B%0A%20%20%20%20%20%20%20%20min%0A%20%20%20%20%20%20%20%20max%0A%20%20%20%20%20%20%20%20__typename%0A%20%20%20%20%20%20%7D%0A%20%20%20%20%20%20__typename%0A%20%20%20%20%7D%0A%20%20%20%20__typename%0A%20%20%7D%0A%7D%0A&operationName=cms_shopCategory&variables=%7B%22shopId%22%3A2131%2C%22categoryId%22%3A461823%2C%22startIndex%22%3A0%2C%22fetchCount%22%3A100%2C%22orderBy%22%3A%22%22%2C%22isShowCurator%22%3Atrue%2C%22tagFilters%22%3A%5B%5D%2C%22tagShowMore%22%3Afalse%2C%22includeSalePageGroup%22%3Atrue%2C%22locationId%22%3Anull%7D'

# 2. 請求標頭 (模擬瀏覽器)
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    'Content-Type': 'application/json'
}


# =========================================================
#                   B. API 數據抓取函式
# =========================================================

def crawl_cosmed_api(api_url):
    """直接爬取 GraphQL API 獲取產品列表數據"""
    print(f"--- 開始爬取 API: {api_url[:60]}...")

    # 隨機延遲
    delay_time = random.uniform(1.5, 3.5)
    print(f"    (休眠 {delay_time:.2f} 秒...)")
    time.sleep(delay_time)

    try:
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        json_data = response.json()

        # 提取產品列表和總數
        sale_page_list_data = json_data.get('data', {}) \
            .get('shopCategory', {}) \
            .get('salePageList', {})

        product_list = sale_page_list_data.get('salePageList', [])
        total_size = sale_page_list_data.get('totalSize', 0)

        print(f"--- 成功獲取 {len(product_list)} 筆資料，總共筆數: {total_size}")

        return product_list, total_size

    except requests.exceptions.RequestException as e:
        print(f"--- API 請求失敗: {e}")
        return [], 0
    except json.JSONDecodeError:
        print("--- API 返回的不是有效的 JSON 數據。")
        return [], 0
    except Exception as e:
        print(f"--- 發生未知錯誤: {e}")
        return [], 0


# =========================================================
#                   C. 數據格式化與清洗 (已修正)
# =========================================================

def format_product_data(product):
    """將單個產品的 JSON 數據格式化為我們需要的字典"""

    image_url = 'N/A'
    pic_list = product.get('picList')

    # 安全檢查並提取圖片 URL
    if isinstance(pic_list, list) and pic_list and isinstance(pic_list[0], dict):
        image_url = pic_list[0].get('picUrl')

    elif product.get('picUrl'):
        # 備用：如果 picList 不是預期格式，則嘗試從 picUrl 字段獲取
        image_url = product.get('picUrl')

    return {
        '名稱': product.get('title', 'N/A').strip(),
        '價格': f"NT${product.get('price')}",
        '圖片網址': image_url if image_url else 'N/A',
        # 產品介紹 (Description) 不在列表 API 中，這裡先留空
        '產品介紹': ''
    }


# =========================================================
#                   D. 儲存到 CSV 函式
# =========================================================

def save_to_csv(data_list, filename='cosmed_products.csv'):
    """將格式化後的產品列表儲存到 CSV 文件"""

    if not data_list:
        print("--- 沒有數據可寫入 CSV 文件。")
        return

    # 欄位名稱 (從第一個字典的鍵中獲取)
    fieldnames = list(data_list[0].keys())

    # 寫入模式：'w' (覆蓋) 適合測試，'a' (附加) 適合多頁爬取
    # 這裡使用 'w' 進行乾淨的測試輸出
    mode = 'w'

    # encoding='utf-8-sig' 確保中文在 Excel 中能正確顯示
    with open(filename, mode, newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # 寫入表頭 (Header)
        writer.writeheader()

        # 寫入數據
        writer.writerows(data_list)
        print(f"\n--- 數據已成功寫入 CSV 文件: {filename}")


# =========================================================
#                       E. 執行區塊
# =========================================================

if __name__ == '__main__':

    # 1. 爬取 API
    product_list, total_count = crawl_cosmed_api(FULL_API_URL)

    # 2. 格式化所有數據
    formatted_data = [format_product_data(p) for p in product_list]

    # 3. 儲存到 CSV
    save_to_csv(formatted_data)

    # 4. 總結
    if formatted_data:
        print("\n==================================")
        print(f"✅ 爬蟲和 CSV 儲存完成！總共 {len(formatted_data)} 筆資料。")
        print("==================================")

        # 打印第一個產品的結果作為驗證
        first_product = formatted_data[0]
        print("\n--- 第一筆資料驗證 ---")
        for key, value in first_product.items():
            print(f"**{key}:** {value}")
    else:
        print("\n--- 爬蟲失敗或 API 返回空數據，請檢查 URL。 ---")