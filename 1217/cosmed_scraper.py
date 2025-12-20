import time
import random
import csv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By


url = 'https://shop.cosmed.com.tw/v2/official/SalePageCategory/103'
output_file = 'cosmed_blush_data.csv' 

def scrape_and_save_csv():
    print("偽裝爬蟲")
    
    options = uc.ChromeOptions()
    
    options.add_argument('--disable-popup-blocking')
    
    
    driver = uc.Chrome(options=options)
    
    results = []

    try:
    
        time.sleep(random.uniform(2.0, 4.0))
        
        driver.get(url)
        print(f"已進入網頁，等待加載...")

      
        for i in range(4):
            scroll_dist = random.randint(500, 900)
            driver.execute_script(f"window.scrollBy(0, {scroll_dist});")
            print(f"第 {i+1} 次滾動，移動 {scroll_dist} 像素...")
            time.sleep(random.uniform(2.0, 4.0))

        print(" 正在解析網頁內容...")
        
        items = driver.find_elements(By.CSS_SELECTOR, '[class*="ProductCard"]')
        
        if not items:
        
            items = driver.find_elements(By.XPATH, '//li[contains(@class, "item")]')

        print(f"成功偵測到 {len(items)} 個產品區塊")

        for item in items:
            try:
                text_content = item.text.split('\n')
                if len(text_content) > 1:
                    name = text_content[0]
                    price = "價格未標示"
                    for line in text_content:
                        if "$" in line:
                            price = line
                            break
                    
                    results.append([name, price])
            except:
                continue

       
        save_to_csv(results)

    except Exception as e:
        print(f" 錯誤: {e}")
    
    finally:
        print(f"隨機等待後關閉瀏覽器...")
        time.sleep(random.uniform(3, 5))
        driver.quit()

def save_to_csv(data):
    
    if not data:
        print("沒有資料可以儲存。")
        return

    try:
       
        with open(output_file, mode='w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
          
            writer.writerow(['商品名稱', '價格'])
           
            writer.writerows(data)
        
        print(f"\n已將 {len(data)} 筆資料儲存至：{output_file}")
    except Exception as e:
        print(f"儲存 CSV 時發生錯誤: {e}")

if __name__ == "__main__":
    scrape_and_save_csv()