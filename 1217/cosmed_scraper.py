import time
import random
import csv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

# --- 配置區 ---
url = 'https://shop.cosmed.com.tw/v2/official/SalePageCategory/103'
output_file = 'cosmed_blush_data.csv' # 存檔檔名

def scrape_and_save_csv():
    print("啟動深度偽裝爬蟲...")
    
    options = uc.ChromeOptions()
    # 基本偽裝設定
    options.add_argument('--disable-popup-blocking')
    
    # 啟動瀏覽器
    driver = uc.Chrome(options=options)
    
    results = []

    try:
        # 1. 隨機初始等待
        time.sleep(random.uniform(2.0, 4.0))
        
        driver.get(url)
        print(f"已進入網頁，等待加載...")

        # 2. 模擬真人滾動並隨機停頓 (滾動多次以加載更多商品)
        for i in range(4):
            scroll_dist = random.randint(500, 900)
            driver.execute_script(f"window.scrollBy(0, {scroll_dist});")
            print(f"第 {i+1} 次滾動，移動 {scroll_dist} 像素...")
            time.sleep(random.uniform(2.0, 4.0))

        # 3. 擷取產品資訊
        print("🔍 正在解析網頁內容...")
        # 這裡使用更廣泛的 CSS 選擇器來定位商品卡片
        items = driver.find_elements(By.CSS_SELECTOR, '[class*="ProductCard"]')
        
        if not items:
            # 備用方案：尋找 li 標籤
            items = driver.find_elements(By.XPATH, '//li[contains(@class, "item")]')

        print(f"📋 成功偵測到 {len(items)} 個產品區塊")

        for item in items:
            try:
                text_content = item.text.split('\n')
                if len(text_content) > 1:
                    # 假設第一行通常是品名，尋找包含 $ 的是價格
                    name = text_content[0]
                    price = "價格未標示"
                    for line in text_content:
                        if "$" in line:
                            price = line
                            break
                    
                    results.append([name, price])
            except:
                continue

        # 4. 儲存至 CSV
        save_to_csv(results)

    except Exception as e:
        print(f" 發生錯誤: {e}")
    
    finally:
        print(f"隨機等待後關閉瀏覽器...")
        time.sleep(random.uniform(3, 5))
        driver.quit()

def save_to_csv(data):
    """將資料存入 CSV 檔案"""
    if not data:
        print("沒有資料可以儲存。")
        return

    try:
        # 使用 utf-8-sig 編碼以確保 Excel 開啟中文不會亂碼
        with open(output_file, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            # 寫入標題列
            writer.writerow(['商品名稱', '價格'])
            # 寫入內容
            writer.writerows(data)
        
        print(f"\n✨ 成功！已將 {len(data)} 筆資料儲存至：{output_file}")
    except Exception as e:
        print(f"儲存 CSV 時發生錯誤: {e}")

if __name__ == "__main__":
    scrape_and_save_csv()