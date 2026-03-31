USE app;

DROP VIEW IF EXISTS view_member_activity;
DROP TRIGGER IF EXISTS trg_auto_upgrade_level;
DROP TABLE IF EXISTS favorites;
DROP TABLE IF EXISTS checkins;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS members;
DROP TABLE IF EXISTS color_palettes;
DROP TABLE IF EXISTS member_level_history;
DROP PROCEDURE IF EXISTS sp_member_checkin;
DROP PROCEDURE IF EXISTS sp_add_favorite;
DROP PROCEDURE IF EXISTS sp_remove_favorite;
DROP PROCEDURE IF EXISTS sp_get_top_products;
DROP PROCEDURE IF EXISTS sp_member_favorites;
DROP EVENT IF EXISTS daily_member_stats;
DROP FUNCTION IF EXISTS fn_member_checkin_count;
DROP FUNCTION IF EXISTS fn_member_favorite_count;


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
  name VARCHAR(255) NOT NULL,
  price DECIMAL(10,2) NOT NULL,
  image_url VARCHAR(255) NOT null,
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

-- 會員升級時間
CREATE TABLE member_level_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    member_id VARCHAR(20),
    old_level VARCHAR(20),
    new_level VARCHAR(20),
    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

 -- view
 -- 會員活動統計視圖
 -- 收藏數量，註冊天數，活躍程度
CREATE OR REPLACE VIEW view_member_activity AS
SELECT
    m.phone_number,
    m.name,
    m.level,
    COUNT(DISTINCT c.id) AS total_checkins,
    COUNT(DISTINCT f.id) AS total_favorites,
    MAX(c.checkin_time) AS last_checkin_at,
    DATEDIFF(NOW(), m.created_at) AS member_days
FROM members m
LEFT JOIN checkins c ON m.phone_number = c.member_id
LEFT JOIN favorites f ON m.phone_number = f.member_id
GROUP BY m.phone_number;

-- 產品收藏排行榜
CREATE OR REPLACE VIEW view_product_popularity AS
SELECT
    p.id,
    p.name,
    p.price,
    COUNT(f.id) AS favorite_count,
    COUNT(f.id) * p.price AS popularity_score
FROM products p
LEFT JOIN favorites f ON p.id = f.product_id
GROUP BY p.id
ORDER BY favorite_count DESC;

-- 會員 + 收藏 + 簽到 綜合分析
CREATE OR REPLACE VIEW view_member_dashboard AS
SELECT
    m.phone_number,
    m.name,
    m.level,
    COUNT(DISTINCT c.id) AS checkins,
    COUNT(DISTINCT f.id) AS favorites,
    MAX(c.checkin_time) AS last_active
FROM members m
LEFT JOIN checkins c ON m.phone_number = c.member_id
LEFT JOIN favorites f ON m.phone_number = f.member_id
GROUP BY m.phone_number;

-- NT$
CREATE OR REPLACE VIEW view_product_list AS
SELECT
    id,
    name,
    CONCAT('NT$', FORMAT(price, 0)) AS formatted_price, -- 輸出 NT$1,580
    description
FROM products;

-- Trigger
-- 自動升級會員等級
DELIMITER //
CREATE TRIGGER trg_auto_upgrade_level
AFTER INSERT ON checkins
FOR EACH ROW
BEGIN
    DECLARE total INT;
    SELECT COUNT(*) INTO total FROM checkins WHERE member_id = NEW.member_id;
    IF total >= 10 THEN
        UPDATE members SET level = 'gold' WHERE phone_number = NEW.member_id;
    ELSEIF total >= 5 THEN
        UPDATE members SET level = 'silver' WHERE phone_number = NEW.member_id AND level = 'bronze';
    END IF;
END //
DELIMITER ;

-- 收藏安全性檢查
DELIMITER //

CREATE TRIGGER trg_before_favorite_insert
BEFORE INSERT ON favorites
FOR EACH ROW
BEGIN
    IF EXISTS (SELECT 1 FROM favorites WHERE member_id = NEW.member_id AND product_id = NEW.product_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Error: This product is already in favorites!';
    END IF;
END //

DELIMITER ;

-- 防止一天重複簽到
DELIMITER $$

CREATE TRIGGER trg_prevent_multiple_checkin
BEFORE INSERT ON checkins
FOR EACH ROW
BEGIN
    IF EXISTS (
        SELECT 1
        FROM checkins
        WHERE member_id = NEW.member_id
        AND DATE(checkin_time) = CURDATE()
    ) THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'You have already checked in today';
    END IF;
END$$

DELIMITER ;

-- 自動記錄會員升級時間
DELIMITER $$

CREATE TRIGGER trg_member_level_history
AFTER UPDATE ON members
FOR EACH ROW
BEGIN
    IF OLD.level <> NEW.level THEN
        INSERT INTO member_level_history
        (member_id, old_level, new_level)
        VALUES
        (NEW.phone_number, OLD.level, NEW.level);
    END IF;
END$$

DELIMITER ;

-- 收藏商品時自動更新人氣
ALTER TABLE products
ADD COLUMN favorite_count INT DEFAULT 0;

DELIMITER $$

CREATE TRIGGER trg_update_product_favorite
AFTER INSERT ON favorites
FOR EACH ROW
BEGIN
    UPDATE products
    SET favorite_count = favorite_count + 1
    WHERE id = NEW.product_id;
END$$

DELIMITER ;

-- 取消收藏時扣除人氣
DELIMITER $$

CREATE TRIGGER trg_reduce_product_favorite
AFTER DELETE ON favorites
FOR EACH ROW
BEGIN
    UPDATE products
    SET favorite_count = favorite_count - 1
    WHERE id = OLD.product_id;
END$$

DELIMITER ;

-- stored procedures
-- 會員簽到
DELIMITER $$

CREATE PROCEDURE sp_member_checkin(IN p_member VARCHAR(20))
BEGIN
    INSERT INTO checkins(member_id, checkin_time)
    VALUES(p_member, NOW());
END$$

DELIMITER ;

-- 收藏商品
DELIMITER $$

CREATE PROCEDURE sp_add_favorite(
IN p_member VARCHAR(20),
IN p_product INT
)
BEGIN

INSERT INTO favorites(member_id, product_id)
VALUES(p_member, p_product);

END$$

DELIMITER ;

-- 取消收藏
DELIMITER $$

CREATE PROCEDURE sp_remove_favorite(
IN p_member VARCHAR(20),
IN p_product INT
)
BEGIN

DELETE FROM favorites
WHERE member_id = p_member
AND product_id = p_product;

END$$

DELIMITER ;

-- 查詢熱門商品
DELIMITER $$

CREATE PROCEDURE sp_get_top_products()
BEGIN

SELECT *
FROM products
ORDER BY favorite_count DESC
LIMIT 10;

END$$

DELIMITER ;

-- 查詢會員收藏商品
DELIMITER $$

CREATE PROCEDURE sp_member_favorites(IN p_member VARCHAR(20))
BEGIN

SELECT p.*
FROM products p
JOIN favorites f ON p.id = f.product_id
WHERE f.member_id = p_member;

END$$

DELIMITER ;

-- Event
-- 每天自動記錄會員狀態
SET GLOBAL event_scheduler = ON;

CREATE EVENT daily_member_stats
ON SCHEDULE EVERY 1 DAY
STARTS CURRENT_TIMESTAMP
DO
INSERT INTO member_level_history(member_id, old_level, new_level)
SELECT phone_number, level, level
FROM members;

-- Function
-- 取得會員簽到次數
DELIMITER $$

CREATE FUNCTION fn_member_checkin_count(p_member VARCHAR(20))
RETURNS INT
DETERMINISTIC
BEGIN

DECLARE total INT;

SELECT COUNT(*)
INTO total
FROM checkins
WHERE member_id = p_member;

RETURN total;

END$$

DELIMITER ;

-- 取得會員收藏數量
DELIMITER $$

CREATE FUNCTION fn_member_favorite_count(p_member VARCHAR(20))
RETURNS INT
DETERMINISTIC
BEGIN

DECLARE total INT;

SELECT COUNT(*)
INTO total
FROM favorites
WHERE member_id = p_member;

RETURN total;

END$$

DELIMITER ;

