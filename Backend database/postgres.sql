-- ==========================================
-- 1. 核心會員與產品表格
-- ==========================================
CREATE TABLE members (
  phone_number VARCHAR(20) PRIMARY KEY,
  name VARCHAR(50) DEFAULT NULL,
  email VARCHAR(100) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  level member_level_enum DEFAULT 'bronze',
  age INT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE products (
  id SERIAL PRIMARY KEY,
  name VARCHAR(255) NOT NULL,
  price NUMERIC(10,2) NOT NULL,
  image_url VARCHAR(500) NOT NULL,
  description TEXT,
  favorite_count INT DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 2. 八大彩妝分類表格 (完全對齊你的 Python 爬蟲設定)
-- ==========================================
CREATE TABLE blushes (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    sale_page_id VARCHAR(50),
    name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE contouring (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    sale_page_id VARCHAR(50),
    name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT
);

CREATE TABLE eyebrows (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    sale_page_id VARCHAR(50),
    category_name VARCHAR(100),
    name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE eyeliner_mascara (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    sale_page_id VARCHAR(50),
    category_name VARCHAR(100),
    name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE eyeshadows (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    sale_page_id VARCHAR(50),
    name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE foundations (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    name VARCHAR(255),
    shade_name VARCHAR(100),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE highlighters (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    sale_page_id VARCHAR(50),
    name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE lipsticks (
    id SERIAL PRIMARY KEY,
    brand VARCHAR(100),
    product_name VARCHAR(255),
    price NUMERIC(10, 2),
    description TEXT,
    image_url VARCHAR(500),
    lab_json TEXT,
    shade_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==========================================
-- 3. 系統功能表格 (簽到、收藏、紀錄等)
-- ==========================================
CREATE TABLE checkins (
  id SERIAL PRIMARY KEY,
  member_id VARCHAR(20) NOT NULL REFERENCES members(phone_number) ON DELETE RESTRICT ON UPDATE CASCADE,
  checkin_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  note TEXT
);

CREATE TABLE favorites (
  id SERIAL PRIMARY KEY,
  member_id VARCHAR(20) NOT NULL REFERENCES members(phone_number) ON DELETE CASCADE ON UPDATE CASCADE,
  item_id INT NOT NULL,
  item_type VARCHAR(50) NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT uq_member_item UNIQUE (member_id, item_id, item_type)
);

CREATE TABLE color_palettes (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100),
    hex_code VARCHAR(7) NOT NULL UNIQUE,
    source_url VARCHAR(255),
    tags VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE member_level_history (
    id SERIAL PRIMARY KEY,
    member_id VARCHAR(20),
    old_level VARCHAR(20),
    new_level VARCHAR(20),
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tryon_records (
    id SERIAL PRIMARY KEY,
    member_id VARCHAR(20) NOT NULL REFERENCES members(phone_number) ON DELETE CASCADE ON UPDATE CASCADE,
    item_id INT NOT NULL,
    item_type VARCHAR(50) NOT NULL,
    original_image_url VARCHAR(500) NOT NULL,
    generated_image_url VARCHAR(500) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    makeup_advice TEXT
);

-- ==========================================
-- 4. 視圖 (Views)
-- ==========================================
CREATE OR REPLACE VIEW view_member_activity AS
SELECT
    m.phone_number, m.name, m.level,
    COUNT(DISTINCT c.id) AS total_checkins,
    COUNT(DISTINCT f.id) AS total_favorites,
    MAX(c.checkin_time) AS last_checkin_at,
    EXTRACT(DAY FROM (NOW() - m.created_at)) AS member_days
FROM members m
LEFT JOIN checkins c ON m.phone_number = c.member_id
LEFT JOIN favorites f ON m.phone_number = f.member_id
GROUP BY m.phone_number, m.name, m.level;

CREATE OR REPLACE VIEW view_product_popularity AS
SELECT
    p.id, p.name, p.price,
    COUNT(f.id) AS favorite_count,
    COUNT(f.id) * p.price AS popularity_score
FROM products p
LEFT JOIN favorites f ON p.id = f.item_id AND f.item_type = 'products'
GROUP BY p.id, p.name, p.price
ORDER BY favorite_count DESC;

CREATE OR REPLACE VIEW view_member_dashboard AS
SELECT
    m.phone_number, m.name, m.level,
    COUNT(DISTINCT c.id) AS checkins,
    COUNT(DISTINCT f.id) AS favorites,
    MAX(c.checkin_time) AS last_active
FROM members m
LEFT JOIN checkins c ON m.phone_number = c.member_id
LEFT JOIN favorites f ON m.phone_number = f.member_id
GROUP BY m.phone_number, m.name, m.level;

CREATE OR REPLACE VIEW view_product_list AS
SELECT
    id, name,
    'NT$' || TO_CHAR(price, 'FM999,999,999') AS formatted_price,
    description
FROM products;

-- ==========================================
-- 5. 觸發器 (Triggers) 與 函數 (Functions)
-- ==========================================
CREATE OR REPLACE FUNCTION func_auto_upgrade_level() RETURNS TRIGGER AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM checkins WHERE member_id = NEW.member_id;
    IF total >= 10 THEN
        UPDATE members SET level = 'gold' WHERE phone_number = NEW.member_id;
    ELSIF total >= 5 THEN
        UPDATE members SET level = 'silver' WHERE phone_number = NEW.member_id AND level = 'bronze';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_auto_upgrade_level AFTER INSERT ON checkins
FOR EACH ROW EXECUTE FUNCTION func_auto_upgrade_level();

CREATE OR REPLACE FUNCTION func_before_favorite_insert() RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM favorites WHERE member_id = NEW.member_id AND item_id = NEW.item_id AND item_type = NEW.item_type) THEN
        RAISE EXCEPTION 'Error: This item is already in favorites!';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_before_favorite_insert BEFORE INSERT ON favorites
FOR EACH ROW EXECUTE FUNCTION func_before_favorite_insert();

CREATE OR REPLACE FUNCTION func_prevent_multiple_checkin() RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM checkins WHERE member_id = NEW.member_id AND DATE(checkin_time) = CURRENT_DATE
    ) THEN
        RAISE EXCEPTION 'You have already checked in today';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_prevent_multiple_checkin BEFORE INSERT ON checkins
FOR EACH ROW EXECUTE FUNCTION func_prevent_multiple_checkin();

CREATE OR REPLACE FUNCTION func_member_level_history() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.level <> NEW.level THEN
        INSERT INTO member_level_history (member_id, old_level, new_level)
        VALUES (NEW.phone_number, OLD.level::VARCHAR, NEW.level::VARCHAR);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_member_level_history AFTER UPDATE ON members
FOR EACH ROW EXECUTE FUNCTION func_member_level_history();

-- ==========================================
-- 6. 預存程序 (Stored Procedures)
-- ==========================================
CREATE OR REPLACE FUNCTION fn_member_checkin_count(p_member VARCHAR(20)) RETURNS INT AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM checkins WHERE member_id = p_member;
    RETURN total;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE PROCEDURE sp_add_favorite(p_member VARCHAR(20), p_item INT, p_type VARCHAR(50)) LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO favorites(member_id, item_id, item_type) VALUES(p_member, p_item, p_type);
END;
$$;

CREATE OR REPLACE PROCEDURE sp_remove_favorite(p_member VARCHAR(20), p_item INT, p_type VARCHAR(50)) LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM favorites WHERE member_id = p_member AND item_id = p_item AND item_type = p_type;
END;
$$;

CREATE OR REPLACE FUNCTION sp_get_top_products() RETURNS SETOF products AS $$
BEGIN
    RETURN QUERY SELECT * FROM products ORDER BY favorite_count DESC LIMIT 10;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sp_member_favorites(p_member VARCHAR(20))
RETURNS TABLE (
    id INT, category VARCHAR, name VARCHAR, price NUMERIC, description TEXT, image_url VARCHAR
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        f.item_id AS id,
        f.item_type::VARCHAR AS category,
        COALESCE(p.name, l.product_name, b.name, c.name, e.name, em.name, es.name, fd.name, h.name)::VARCHAR AS name,
        COALESCE(p.price, l.price, b.price, c.price, e.price, em.price, es.price, fd.price, h.price)::NUMERIC AS price,
        COALESCE(p.description, l.description, b.description, c.description, e.description, em.description, es.description, fd.description, h.description)::TEXT AS description,
        COALESCE(p.image_url, l.image_url, b.image_url, c.image_url, e.image_url, em.image_url, es.image_url, fd.image_url, h.image_url)::VARCHAR AS image_url
    FROM favorites f
    LEFT JOIN products p ON f.item_id = p.id AND f.item_type = 'products'
    LEFT JOIN lipsticks l ON f.item_id = l.id AND f.item_type = 'lipsticks'
    LEFT JOIN blushes b ON f.item_id = b.id AND f.item_type = 'blushes'
    LEFT JOIN contouring c ON f.item_id = c.id AND f.item_type = 'contouring'
    LEFT JOIN eyebrows e ON f.item_id = e.id AND f.item_type = 'eyebrows'
    LEFT JOIN eyeliner_mascara em ON f.item_id = em.id AND f.item_type = 'eyeliner_mascara'
    LEFT JOIN eyeshadows es ON f.item_id = es.id AND f.item_type = 'eyeshadows'
    LEFT JOIN foundations fd ON f.item_id = fd.id AND f.item_type = 'foundations'
    LEFT JOIN highlighters h ON f.item_id = h.id AND f.item_type = 'highlighters'
    WHERE f.member_id = p_member;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE PROCEDURE daily_member_stats() LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO member_level_history(member_id, old_level, new_level)
    SELECT phone_number, level::VARCHAR, level::VARCHAR FROM members;
END;
$$;

CREATE OR REPLACE FUNCTION fn_member_favorite_count(p_member VARCHAR(20)) RETURNS INT AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM favorites WHERE member_id = p_member;
    RETURN total;
END;
$$ LANGUAGE plpgsql;