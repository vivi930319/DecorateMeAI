USE my_app; 

DROP TABLE IF EXISTS checkins;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS members;

-- members 表格 (會員)
-- phone_number
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

-- products 表格（產品）
CREATE TABLE products (
  id INT NOT NULL AUTO_INCREMENT,
  name VARCHAR(50) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  stock INT DEFAULT 0,    -- 庫存數量
  description TEXT, -- 產品描述
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP, -- 創建時間：記錄該產品資訊首次加入系統的時間。可用於排序、新品標籤或數據分析
  
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- checkins 表格 (簽到記錄)
-- 外鍵 member_id 參照 members.phone_number
CREATE TABLE checkins (
  id INT NOT NULL AUTO_INCREMENT,
  -- 外鍵欄位必須與參照的主鍵型別一致 (VARCHAR(20))
  member_id VARCHAR(20) NOT NULL,  -- 對應members 表格中的 phone_number 欄位，這個欄位用於標識是哪一位會員進行了這次簽到。
  checkin_time DATETIME DEFAULT CURRENT_TIMESTAMP,
  note TEXT, -- 備註：一個可選的長文本欄位，用於記錄這次簽到的額外資訊
  
  PRIMARY KEY (id),
  KEY member_id_fk_idx (member_id),
  
  -- 外鍵，這裡參照 members 表格的 phone_number 欄位
  CONSTRAINT fk_checkin_member_phone FOREIGN KEY (member_id) 
    REFERENCES members (phone_number) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;