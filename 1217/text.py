from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import csv
import os

# --- 配置區 ---
# 請確認此路徑與您的 Mac 實際路徑一致
webdriver_path = '/Users/liaolingya/Downloads/chromedriver-mac-arm64-2/chromedriver'
target_url = 'https://shop.cosmed.com.tw/v2/official/SalePageCategory/461825?sortMode=Curator'
output_file = "cosmed_blush_results.csv"

# --- 瀏覽器偽裝設定 ---
chrome_options = Options()
user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
chrome_options.add_argument(f'user-agent={user_agent}')
chrome_options.add_argument("--disable-blink-features=AutomationControlled")
chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', False)

def run_scraper():
    # 檢查驅動程式是否存在
    if not os.path.exists(webdriver_path):
        print(f"❌ 找不到 ChromeDriver，請檢查路徑：{webdriver_path}")
        return

    service = Service(webdriver_path)
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # 移除自動控制標記
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        print(f"🚀 正在開啟網頁：{target_url}")
        driver.get(target_url)
        
        # 等待網頁元素加載
        wait = WebDriverWait(driver, 15)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "li")))
        
        print("🖱️ 正在模擬真人捲動頁面以加載更多產品...")
        for i in range(3):
            driver.execute_script(f"window.scrollTo(0, {800 * (i+1)});")
            time.sleep(random.uniform(1.5, 2.5))

        # 抓取包含 SalePage 關鍵字的產品連結
        # 這是目前最穩定的抓取方式
        items = driver.find_elements(By.XPATH, '//a[contains(@href, "SalePage/Index/")]')
        
        # 過濾重複的產品連結
        unique_links = []
        seen_hrefs = set()
        for item in items:
            href = item.get_attribute('href')
            if href and href not in seen_hrefs:
                unique_links.append(item)
                seen_hrefs.add(href)

        print(f"✨ 成功找到 {len(unique_links)} 個產品！開始擷取詳細資料...")
        print("-" * 50)

        results = []
        for i, item in enumerate(unique_links):
            try:
                # 取得該區塊內的所有文字並分割
                raw_text = item.text.strip().split('\n')
                
                # 通常第一行是名稱，最後一行是價格
                name = raw_text[0] if len(raw_text) > 0 else "未知商品"
                price = raw_text[-1] if len(raw_text) > 1 else "未知價格"
                link = item.get_attribute('href')

                # 篩選掉不含價格的雜訊
                if "NT$" in price:
                    results.append([name, price, link])
                    print(f"[{i+1}] 已讀取：{name}")
            except Exception:
                continue

        # --- 儲存成 CSV 檔案 ---
        if results:
            with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['產品名稱', '價格', '商品連結']) # 寫入標題
                writer.writerows(results)
            print("-" * 50)
            print(f"✅ 任務成功！共儲存 {len(results)} 筆資料至：{output_file}")
        else:
            print("⚠️ 未抓取到有效資料。")

    except Exception as e:
        print(f"❌ 執行過程中發生錯誤：{e}")
    finally:
        driver.quit()
        print("🏁 瀏覽器已關閉。")

if __name__ == "__main__":
    run_scraper()