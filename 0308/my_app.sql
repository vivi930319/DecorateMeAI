USE my_app;

DROP TABLE IF EXISTS favorites;
DROP TABLE IF EXISTS checkins;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS members;
DROP TABLE IF EXISTS color_palettes;

-- 創建 members 表格 (會員)
-- 主鍵: phone_number
-- 密碼欄位: password_hash
CREATE TABLE members (
  phone_number VARCHAR(20) NOT NULL,
  name VARCHAR(50) DEFAULT NULL,
  email VARCHAR(100) NOT NULL UNIQUE,
  -- 儲存加密後的密碼
  password_hash VARCHAR(255) NOT NULL,
  -- 等級使用 ENUM 型別
  level ENUM('bronze','silver','gold') DEFAULT 'bronze',
  age INT DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 記錄會員註冊的準確日期和時間，計算會籍時長、活躍度分析或排序

  PRIMARY KEY (phone_number),
  UNIQUE KEY email_unique (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 創建 products 表格 (產品)
CREATE TABLE products (
  id INT NOT NULL AUTO_INCREMENT,
  image_url VARCHAR(255) NOT null, -- 儲存產品圖片的連結
  name VARCHAR(50) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  description TEXT, -- 產品描述
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 創建時間：記錄該產品資訊首次加入系統的時間。可用於排序、新品標籤或數據分析

  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- 創建簽到記錄表格
CREATE TABLE checkins (
  id INT NOT NULL AUTO_INCREMENT,
  -- 外鍵欄位必須與參照的主鍵型別一致 (VARCHAR(20))
  member_id VARCHAR(20) NOT NULL,  -- 對應members 表格中的 phone_number 欄位，這個欄位用於標識是哪一位會員進行了這次簽到。
  checkin_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  note TEXT, -- 備註：一個可選的長文本欄位，用於記錄這次簽到的額外資訊

  PRIMARY KEY (id),
  KEY member_id_fk_idx (member_id),

  -- 參照 members 表格的 phone_number 欄位
  CONSTRAINT fk_checkin_member_phone FOREIGN KEY (member_id)
    REFERENCES members (phone_number) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 創建我的最愛/收藏表格
CREATE TABLE favorites (
  id INT NOT NULL AUTO_INCREMENT,
  member_id VARCHAR(20) NOT NULL,
  product_id INT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  -- 會員或產品被刪除時自動刪除相關的收藏記錄
  CONSTRAINT fk_fav_member FOREIGN KEY (member_id)
    REFERENCES members (phone_number) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT fk_fav_product FOREIGN KEY (product_id)
    REFERENCES products (id) ON DELETE CASCADE ON UPDATE CASCADE,
  -- 確保同一個會員不會重複收藏同一個產品
  UNIQUE KEY unique_user_product (member_id, product_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 創建色碼資料庫表格
CREATE TABLE color_palettes (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(100),           -- 顏色、組合、名稱
    hex_code VARCHAR(7) NOT NULL UNIQUE,-- 色碼
    source_url VARCHAR(255),      -- 爬蟲來源網址
    tags VARCHAR(100),            -- 標籤 （溫暖, 色調）
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;