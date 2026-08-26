PGDMP$9~TKU18.418.4 .00ENCODINGENCODINGSET client_encoding = 'UTF8';
false/00
STDSTRINGS
STDSTRINGS(SET standard_conforming_strings = 'on';
false000
SEARCHPATH
SEARCHPATH8SELECT pg_catalog.set_config('search_path', '', false);
false1126216815TKUDATABASECREATE DATABASE "TKU" WITH TEMPLATE = template0 ENCODING = 'UTF8' LOCALE_PROVIDER = libc LOCALE = 'English_United Kingdom.1252';
DROP DATABASE "TKU";
postgresfalse200DATABASE "TKU"ACL8GRANT CONNECT ON DATABASE "TKU" TO decorate_me_crawler;
postgresfalse5681300
SCHEMA publicACL5GRANT USAGE ON SCHEMA public TO decorate_me_crawler;
pg_database_ownerfalse6307924000pgcrypto   EXTENSION<CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
DROP EXTENSION pgcrypto;
false400EXTENSION pgcryptoCOMMENT<COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';
false2124716965member_levelTYPETCREATE TYPE public.member_level AS ENUM (
    'bronze',
    'silver',
    'gold'
);
DROP TYPE public.member_level;
publicpostgresfalse124720892member_level_enumTYPEYCREATE TYPE public.member_level_enum AS ENUM (
    'bronze',
    'silver',
    'gold'
);
$DROP TYPE public.member_level_enum;
publicpostgresfalse@125519859daily_member_stats() PROCEDURECREATE PROCEDURE public.daily_member_stats()
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO member_level_history(member_id, old_level, new_level)
    SELECT phone_number, level::VARCHAR, level::VARCHAR FROM members;
END;
$$;
,DROP PROCEDURE public.daily_member_stats();
publicpostgresfalse\125523819enforce_product_contract()FUNCTIONjCREATE FUNCTION public.enforce_product_contract() RETURNS trigger
    LANGUAGE plpgsql
    AS $_$
                BEGIN
                    NEW.category := CASE TG_TABLE_NAME
                        WHEN 'blushes' THEN '腮紅' WHEN 'eyebrows' THEN '眉毛彩妝'
                        WHEN 'eyeshadows' THEN '眼影' WHEN 'eyeliner_mascara' THEN '眼線/睫毛'
                        WHEN 'contouring' THEN '修容' WHEN 'foundations' THEN '底妝'
                        WHEN 'highlighters' THEN '打亮' WHEN 'lipsticks' THEN '唇彩' END;
                    NEW.product_type := TG_TABLE_NAME;
                    NEW.status := COALESCE(NEW.status,'active');
                    NEW.review_status := COALESCE(NEW.review_status,'approved');
                    NEW.in_stock := COALESCE(NEW.in_stock,TRUE);
                    NEW.currency := COALESCE(NEW.currency,'TWD');
                    NEW.sku := COALESCE(NULLIF(NEW.sku,''),NEW.sale_page_id);
                    NEW.source_product_id := COALESCE(NEW.source_product_id,NEW.sale_page_id);
                    NEW.source_site := COALESCE(NULLIF(NEW.source_site,''),substring(COALESCE(NEW.source_url,NEW.image_webp_url,'') from 'https?://([^/]+)'));
                    NEW.image_urls := CASE WHEN COALESCE(NEW.image_webp_url,'')<>'' THEN jsonb_build_array(NEW.image_webp_url) ELSE '[]'::jsonb END;
                    NEW.shade_name := COALESCE(NULLIF(NEW.shade_name,''),substring(NEW.name from ' - (.+)$'));
                    NEW.style_tags := CASE WHEN cardinality(NEW.style_tags)=0 THEN ARRAY['daily'] ELSE NEW.style_tags END;
                    NEW.finish_tags := CASE WHEN cardinality(NEW.finish_tags)=0 THEN ARRAY['natural'] ELSE NEW.finish_tags END;
                    NEW.season_tags := CASE WHEN cardinality(NEW.season_tags)=0 THEN ARRAY['neutral'] ELSE NEW.season_tags END;
                    NEW.occasion_tags := CASE WHEN cardinality(NEW.occasion_tags)=0 THEN ARRAY['daily'] ELSE NEW.occasion_tags END;
                    NEW.lab := COALESCE(NEW.lab,product_hex_to_lab(NEW.hex_primary));
                    NEW.last_crawled_at := COALESCE(NEW.last_crawled_at,CURRENT_TIMESTAMP);
                    NEW.recommendation_ready := NEW.status='active' AND NEW.review_status='approved' AND NEW.in_stock
                        AND COALESCE(NEW.image_webp_url,'')<>'' AND NEW.hex_primary ~ '^#[0-9A-Fa-f]{6}$' AND NEW.lab IS NOT NULL;
                    NEW.data_quality_score := LEAST(1.0,(CASE WHEN NEW.name<>'' THEN 0.1 ELSE 0 END)+(CASE WHEN NEW.brand<>'' THEN 0.1 ELSE 0 END)+
                        (CASE WHEN NEW.price>0 THEN 0.1 ELSE 0 END)+(CASE WHEN COALESCE(NEW.image_webp_url,'')<>'' THEN 0.15 ELSE 0 END)+
                        (CASE WHEN COALESCE(NEW.source_url,'')<>'' THEN 0.1 ELSE 0 END)+(CASE WHEN NEW.hex_primary ~ '^#[0-9A-Fa-f]{6}$' THEN 0.15 ELSE 0 END)+
                        (CASE WHEN NEW.lab IS NOT NULL THEN 0.15 ELSE 0 END)+(CASE WHEN cardinality(NEW.style_tags)>0 THEN 0.075 ELSE 0 END)+(CASE WHEN cardinality(NEW.finish_tags)>0 THEN 0.075 ELSE 0 END));
                    NEW.updated_at := CURRENT_TIMESTAMP;
                    RETURN NEW;
                END $_$;
1DROP FUNCTION public.enforce_product_contract();
publicpostgresfalse5125519854*fn_member_checkin_count(character varying)FUNCTIONCREATE FUNCTION public.fn_member_checkin_count(p_member character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM checkins WHERE member_id = p_member;
    RETURN total;
END;
$$;
JDROP FUNCTION public.fn_member_checkin_count(p_member character varying);
publicpostgresfalseA125519860+fn_member_favorite_count(character varying)FUNCTIONCREATE FUNCTION public.fn_member_favorite_count(p_member character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM favorites WHERE member_id = p_member;
    RETURN total;
END;
$$;
KDROP FUNCTION public.fn_member_favorite_count(p_member character varying);
publicpostgresfalse2125519846func_auto_upgrade_level()FUNCTIONCREATE FUNCTION public.func_auto_upgrade_level() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;
0DROP FUNCTION public.func_auto_upgrade_level();
publicpostgresfalse1125519848func_before_favorite_insert()FUNCTIONYCREATE FUNCTION public.func_before_favorite_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM favorites WHERE member_id = NEW.member_id AND item_id = NEW.item_id AND item_type = NEW.item_type) THEN
        RAISE EXCEPTION 'Error: This item is already in favorites!';
    END IF;
    RETURN NEW;
END;
$$;
4DROP FUNCTION public.func_before_favorite_insert();
publicpostgresfalse4125519852func_member_level_history()FUNCTIONFCREATE FUNCTION public.func_member_level_history() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF OLD.level <> NEW.level THEN
        INSERT INTO member_level_history (member_id, old_level, new_level)
        VALUES (NEW.phone_number, OLD.level::VARCHAR, NEW.level::VARCHAR);
    END IF;
    RETURN NEW;
END;
$$;
2DROP FUNCTION public.func_member_level_history();
publicpostgresfalse3125519850func_prevent_multiple_checkin()FUNCTIONNCREATE FUNCTION public.func_prevent_multiple_checkin() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM checkins WHERE member_id = NEW.member_id AND DATE(checkin_time) = CURRENT_DATE
    ) THEN
        RAISE EXCEPTION 'You have already checked in today';
    END IF;
    RETURN NEW;
END;
$$;
6DROP FUNCTION public.func_prevent_multiple_checkin();
publicpostgresfalse[125523818product_hex_to_lab(text)FUNCTION8CREATE FUNCTION public.product_hex_to_lab(h text) RETURNS jsonb
    LANGUAGE plpgsql IMMUTABLE
    AS $_$
                DECLARE r DOUBLE PRECISION; g DOUBLE PRECISION; b DOUBLE PRECISION;
                        x DOUBLE PRECISION; y DOUBLE PRECISION; z DOUBLE PRECISION;
                        fx DOUBLE PRECISION; fy DOUBLE PRECISION; fz DOUBLE PRECISION;
                BEGIN
                    IF h IS NULL OR h !~ '^#[0-9A-Fa-f]{6}$' THEN RETURN NULL; END IF;
                    r := (('x'||substr(h,2,2))::bit(8)::int) / 255.0;
                    g := (('x'||substr(h,4,2))::bit(8)::int) / 255.0;
                    b := (('x'||substr(h,6,2))::bit(8)::int) / 255.0;
                    r := CASE WHEN r>0.04045 THEN power((r+0.055)/1.055,2.4) ELSE r/12.92 END;
                    g := CASE WHEN g>0.04045 THEN power((g+0.055)/1.055,2.4) ELSE g/12.92 END;
                    b := CASE WHEN b>0.04045 THEN power((b+0.055)/1.055,2.4) ELSE b/12.92 END;
                    x := (r*0.4124+g*0.3576+b*0.1805)/0.95047;
                    y := r*0.2126+g*0.7152+b*0.0722;
                    z := (r*0.0193+g*0.1192+b*0.9505)/1.08883;
                    fx := CASE WHEN x>0.008856 THEN power(x,1.0/3) ELSE 7.787*x+16.0/116 END;
                    fy := CASE WHEN y>0.008856 THEN power(y,1.0/3) ELSE 7.787*y+16.0/116 END;
                    fz := CASE WHEN z>0.008856 THEN power(z,1.0/3) ELSE 7.787*z+16.0/116 END;
                    RETURN jsonb_build_array(round((116*fy-16)::numeric,2),round((500*(fx-fy))::numeric,2),round((200*(fy-fz))::numeric,2));
                END $_$;
1DROP FUNCTION public.product_hex_to_lab(h text);
publicpostgresfalse%125524180register_product_catalog_item()FUNCTIONCREATE FUNCTION public.register_product_catalog_item() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO public.product_catalog (product_type, source_id)
    VALUES (TG_TABLE_NAME, NEW.id)
    ON CONFLICT (product_type, source_id) DO NOTHING;
    RETURN NEW;
END;
$$;
6DROP FUNCTION public.register_product_catalog_item();
publicpostgresfalse6125519855>sp_add_favorite(character varying, integer, character varying)   PROCEDURECREATE PROCEDURE public.sp_add_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying)
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO favorites(member_id, item_id, item_type) VALUES(p_member, p_item, p_type);
END;
$$;
vDROP PROCEDURE public.sp_add_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying);
publicpostgresfalse125920913productsTABLEnCREATE TABLE public.products (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    price numeric(10,2) NOT NULL,
    image_url character varying(500) NOT NULL,
    description text,
    favorite_count integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    category character varying(100),
    shades jsonb
);
DROP TABLE public.products;
publicheaprpostgresfalse?125521115sp_get_top_products()FUNCTIONCREATE FUNCTION public.sp_get_top_products() RETURNS SETOF public.products
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY SELECT * FROM products ORDER BY favorite_count DESC LIMIT 10;
END;
$$;
,DROP FUNCTION public.sp_get_top_products();
publicpostgresfalse222Z125519858&sp_member_favorites(character varying)FUNCTIONCREATE FUNCTION public.sp_member_favorites(p_member character varying) RETURNS TABLE(id integer, category character varying, name character varying, price numeric, description text, image_url character varying)
    LANGUAGE plpgsql
    AS $$
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
$$;
FDROP FUNCTION public.sp_member_favorites(p_member character varying);
publicpostgresfalse>125519856Asp_remove_favorite(character varying, integer, character varying)    PROCEDURE
CREATE PROCEDURE public.sp_remove_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying)
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM favorites WHERE member_id = p_member AND item_id = p_item AND item_type = p_type;
END;
$$;
yDROP PROCEDURE public.sp_remove_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying);
publicpostgresfalse125923551admin_audit_logsTABLECREATE TABLE public.admin_audit_logs (
    id character varying(36) NOT NULL,
    request_id character varying(64) NOT NULL,
    actor_email character varying(254) NOT NULL,
    action character varying(80) NOT NULL,
    target_email character varying(254),
    target_id character varying(80),
    result character varying(20) NOT NULL,
    reason character varying(255),
    metadata_json jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
$DROP TABLE public.admin_audit_logs;
publicheaprpostgresfalse125923176analysis_historyTABLECREATE TABLE public.analysis_history (
    id bigint NOT NULL,
    member_email character varying(191),
    mode character varying(10),
    result jsonb,
    analysis_package_id character varying(64),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
$DROP TABLE public.analysis_history;
publicheaprpostgresfalse125923175analysis_history_id_seqSEQUENCECREATE SEQUENCE public.analysis_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
.DROP SEQUENCE public.analysis_history_id_seq;
publicpostgresfalse264500analysis_history_id_seqSEQUENCE OWNED BYSALTER SEQUENCE public.analysis_history_id_seq OWNED BY public.analysis_history.id;
publicpostgresfalse263125923116
audit_logsTABLE{CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    actor_email character varying(100) NOT NULL,
    target_email character varying(100) NOT NULL,
    action character varying(50) NOT NULL,
    field_name character varying(50),
    before_value character varying(255),
    after_value character varying(255),
    created_at timestamp without time zone DEFAULT now()
);
DROP TABLE public.audit_logs;
publicheaprpostgresfalse125923115audit_logs_id_seqSEQUENCECREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
(DROP SEQUENCE public.audit_logs_id_seq;
publicpostgresfalse258600audit_logs_id_seqSEQUENCE OWNED BYGALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;
publicpostgresfalse257125921388blushesTABLECREATE TABLE public.blushes (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(50),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(500),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    created_at timestamp without time zone DEFAULT now(),
    qdrant_vector_12d double precision[],
    shade_code character varying(150),
    source_url text,
    in_stock boolean DEFAULT true,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    swatch_html text
);
DROP TABLE public.blushes;
publicheaprpostgresfalse125921387blushes_id_seqSEQUENCECREATE SEQUENCE public.blushes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
%DROP SEQUENCE public.blushes_id_seq;
publicpostgresfalse236700blushes_id_seqSEQUENCE OWNED BYAALTER SEQUENCE public.blushes_id_seq OWNED BY public.blushes.id;
publicpostgresfalse235125923268cartTABLECREATE TABLE public.cart (
    id bigint NOT NULL,
    member_id character varying(20),
    item_id bigint NOT NULL,
    qty integer DEFAULT 1 NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT cart_qty_check CHECK ((qty >= 1))
);
DROP TABLE public.cart;
publicheaprpostgresfalse125923267cart_id_seqSEQUENCEtCREATE SEQUENCE public.cart_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
"DROP SEQUENCE public.cart_id_seq;
publicpostgresfalse274800cart_id_seqSEQUENCE OWNED BY;ALTER SEQUENCE public.cart_id_seq OWNED BY public.cart.id;
publicpostgresfalse273125923289
cart_itemsTABLECREATE TABLE public.cart_items (
    id integer NOT NULL,
    member_email character varying(100) NOT NULL,
    item_id integer NOT NULL,
    qty integer NOT NULL,
    updated_at timestamp without time zone DEFAULT now()
);
DROP TABLE public.cart_items;
publicheaprpostgresfalse125923288cart_items_id_seqSEQUENCECREATE SEQUENCE public.cart_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
(DROP SEQUENCE public.cart_items_id_seq;
publicpostgresfalse276900cart_items_id_seqSEQUENCE OWNED BYGALTER SEQUENCE public.cart_items_id_seq OWNED BY public.cart_items.id;
publicpostgresfalse275125921015checkinsTABLECREATE TABLE public.checkins (
    id integer NOT NULL,
    member_id character varying(20) NOT NULL,
    checkin_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    note text
);
DROP TABLE public.checkins;
publicheaprpostgresfalse125921014checkins_id_seqSEQUENCECREATE SEQUENCE public.checkins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
&DROP SEQUENCE public.checkins_id_seq;
publicpostgresfalse224:00checkins_id_seqSEQUENCE OWNED BYCALTER SEQUENCE public.checkins_id_seq OWNED BY public.checkins.id;
publicpostgresfalse223125921051color_palettesTABLECREATE TABLE public.color_palettes (
    id integer NOT NULL,
    title character varying(100),
    hex_code character varying(7) NOT NULL,
    source_url character varying(255),
    tags character varying(100),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
"DROP TABLE public.color_palettes;
publicheaprpostgresfalse125921050color_palettes_id_seqSEQUENCECREATE SEQUENCE public.color_palettes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
,DROP SEQUENCE public.color_palettes_id_seq;
publicpostgresfalse228;00color_palettes_id_seqSEQUENCE OWNED BYOALTER SEQUENCE public.color_palettes_id_seq OWNED BY public.color_palettes.id;
publicpostgresfalse227125922602
contouringTABLEHCREATE TABLE public.contouring (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(50),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(500),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    created_at timestamp without time zone DEFAULT now(),
    qdrant_vector_12d double precision[],
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    in_stock boolean DEFAULT true,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_url text,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
DROP TABLE public.contouring;
publicheaprpostgresfalse125922601contouring_id_seqSEQUENCECREATE SEQUENCE public.contouring_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
(DROP SEQUENCE public.contouring_id_seq;
publicpostgresfalse246<00contouring_id_seqSEQUENCE OWNED BYGALTER SEQUENCE public.contouring_id_seq OWNED BY public.contouring.id;
publicpostgresfalse245125924119crawler_staging_productsTABLE
CREATE TABLE public.crawler_staging_products (
    id integer NOT NULL,
    source_site character varying(100) NOT NULL,
    source_product_id character varying(255) NOT NULL,
    source_url character varying(1000) NOT NULL,
    name character varying(255),
    price numeric(10,2),
    currency character varying(8) DEFAULT 'TWD'::character varying NOT NULL,
    description text,
    category character varying(50),
    image_url character varying(1000),
    image_urls jsonb,
    shades jsonb,
    status character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    validation_error_code character varying(64),
    validation_error_message character varying(500),
    crawled_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL,
    reviewed_at timestamp with time zone,
    reviewed_by character varying(64),
    review_note character varying(500),
    imported_product_id integer,
    dedupe_key character(64) NOT NULL,
    crawler_name character varying(120) NOT NULL,
    crawl_run_id uuid NOT NULL,
    first_seen_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    product_name character varying(300),
    brand character varying(100),
    sku character varying(200),
    shade_code character varying(100),
    hex_primary character(7),
    in_stock boolean,
    specs jsonb DEFAULT '{}'::jsonb NOT NULL,
    image_original_url text,
    image_320_url text,
    image_640_url text,
    image_1280_url text,
    image_mime character varying(40),
    image_bytes integer,
    image_width integer,
    image_height integer,
    image_sha256 character(64),
    image_validation_status character varying(20) DEFAULT 'not_checked'::character varying NOT NULL,
    validation_errors jsonb DEFAULT '[]'::jsonb NOT NULL,
    error_code character varying(80),
    error_summary character varying(500),
    content_fingerprint character(64) NOT NULL,
    imported_at timestamp with time zone,
    imported_product_ref character varying(255),
    CONSTRAINT ck_crawler_staging_status CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'imported'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT crawler_staging_category_ck CHECK (((category IS NULL) OR ((category)::text = ANY ((ARRAY['foundations'::character varying, 'lipsticks'::character varying, 'blushes'::character varying, 'eyeshadows'::character varying, 'eyeliner_mascara'::character varying, 'eyebrows'::character varying, 'contouring'::character varying, 'highlighters'::character varying])::text[])))),
    CONSTRAINT crawler_staging_currency_ck CHECK (((currency IS NULL) OR ((currency)::text = ANY ((ARRAY['TWD'::character varying, 'USD'::character varying, 'JPY'::character varying, 'KRW'::character varying, 'EUR'::character varying, 'GBP'::character varying, 'CNY'::character varying, 'HKD'::character varying])::text[])))),
    CONSTRAINT crawler_staging_image_status_ck CHECK (((image_validation_status)::text = ANY ((ARRAY['not_checked'::character varying, 'valid'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT crawler_staging_source_https_ck CHECK (((source_url)::text ~ '^https://'::text)),
    CONSTRAINT crawler_staging_status_ck CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'approved'::character varying, 'rejected'::character varying, 'imported'::character varying, 'failed'::character varying])::text[])))
);
,DROP TABLE public.crawler_staging_products;
publicheaprpostgresfalse=00TABLE crawler_staging_productsCOMMENTCOMMENT ON TABLE public.crawler_staging_products IS 'Crawler-only staging area. Backend review/import is required before formal products are changed.';
publicpostgresfalse284>00TABLE crawler_staging_productsACL\GRANT SELECT,INSERT,UPDATE ON TABLE public.crawler_staging_products TO decorate_me_crawler;
publicpostgresfalse284125924118crawler_staging_products_id_seqSEQUENCEALTER TABLE public.crawler_staging_products ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.crawler_staging_products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
publicpostgresfalse284?00(SEQUENCE crawler_staging_products_id_seqACL^GRANT SELECT,USAGE ON SEQUENCE public.crawler_staging_products_id_seq TO decorate_me_crawler;
publicpostgresfalse283
125923192daily_checkinsTABLE7CREATE TABLE public.daily_checkins (
    id bigint NOT NULL,
    member_email character varying(191),
    checkin_date date NOT NULL,
    streak integer DEFAULT 1,
    awarded integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    idempotency_key character varying(128)
);
"DROP TABLE public.daily_checkins;
publicheaprpostgresfalse   125923191daily_checkins_id_seqSEQUENCE~CREATE SEQUENCE public.daily_checkins_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
,DROP SEQUENCE public.daily_checkins_id_seq;
publicpostgresfalse266@00daily_checkins_id_seqSEQUENCE OWNED BYOALTER SEQUENCE public.daily_checkins_id_seq OWNED BY public.daily_checkins.id;
publicpostgresfalse265125921403eyebrowsTABLEoCREATE TABLE public.eyebrows (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(50),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(500),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    created_at timestamp without time zone DEFAULT now(),
    category_name character varying(50),
    qdrant_vector_12d double precision[],
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    in_stock boolean DEFAULT true,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_url text,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
DROP TABLE public.eyebrows;
publicheaprpostgresfalse125921402eyebrows_id_seqSEQUENCECREATE SEQUENCE public.eyebrows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
&DROP SEQUENCE public.eyebrows_id_seq;
publicpostgresfalse238A00eyebrows_id_seqSEQUENCE OWNED BYCALTER SEQUENCE public.eyebrows_id_seq OWNED BY public.eyebrows.id;
publicpostgresfalse237125922465eyeliner_mascaraTABLENCREATE TABLE public.eyeliner_mascara (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(50),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(500),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    created_at timestamp without time zone DEFAULT now(),
    qdrant_vector_12d double precision[],
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    in_stock boolean DEFAULT true,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_url text,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
$DROP TABLE public.eyeliner_mascara;
publicheaprpostgresfalse125922464eyeliner_mascara_id_seqSEQUENCECREATE SEQUENCE public.eyeliner_mascara_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
.DROP SEQUENCE public.eyeliner_mascara_id_seq;
publicpostgresfalse244B00eyeliner_mascara_id_seqSEQUENCE OWNED BYSALTER SEQUENCE public.eyeliner_mascara_id_seq OWNED BY public.eyeliner_mascara.id;
publicpostgresfalse243125922389
eyeshadowsTABLEHCREATE TABLE public.eyeshadows (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(50),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(500),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    created_at timestamp without time zone DEFAULT now(),
    qdrant_vector_12d double precision[],
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    in_stock boolean DEFAULT true,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_url text,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
DROP TABLE public.eyeshadows;
publicheaprpostgresfalse125922388eyeshadows_id_seqSEQUENCECREATE SEQUENCE public.eyeshadows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
(DROP SEQUENCE public.eyeshadows_id_seq;
publicpostgresfalse242C00eyeshadows_id_seqSEQUENCE OWNED BYGALTER SEQUENCE public.eyeshadows_id_seq OWNED BY public.eyeshadows.id;
publicpostgresfalse241125921032 favoritesTABLECREATE TABLE public.favorites (
    id integer NOT NULL,
    member_id character varying(20) NOT NULL,
    item_id integer NOT NULL,
    item_type character varying(50) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
DROP TABLE public.favorites;
publicheaprpostgresfalse125921031favorites_id_seqSEQUENCECREATE SEQUENCE public.favorites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
'DROP SEQUENCE public.favorites_id_seq;
publicpostgresfalse226D00favorites_id_seqSEQUENCE OWNED BYEALTER SEQUENCE public.favorites_id_seq OWNED BY public.favorites.id;
publicpostgresfalse225125922830foundationsTABLECREATE TABLE public.foundations (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(200),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(1000),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    source_type character varying(50) DEFAULT 'foundations'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    qdrant_vector_12d double precision[],
    shade_code character varying(30),
    source_url text,
    swatch_image_url text,
    swatch_html text,
    in_stock boolean DEFAULT true,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    series_id character varying(120),
    depth_index integer,
    CONSTRAINT foundations_depth_index_nonnegative CHECK (((depth_index IS NULL) OR (depth_index >= 0)))
);
DROP TABLE public.foundations;
publicheaprpostgresfalseE00COLUMN foundations.series_idCOMMENTCOMMENT ON COLUMN public.foundations.series_id IS '同品牌同粉底系列的穩定識別碼；只有相同 series_id 才能稱為官方相鄰色階。';
publicpostgresfalse250F00COLUMN foundations.depth_indexCOMMENTCOMMENT ON COLUMN public.foundations.depth_index IS '品牌系列內由淺至深遞增的正式色階順序；不得從色號文字猜測。';
publicpostgresfalse250125922829foundations_id_seqSEQUENCECREATE SEQUENCE public.foundations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
)DROP SEQUENCE public.foundations_id_seq;
publicpostgresfalse250G00foundations_id_seqSEQUENCE OWNED BYIALTER SEQUENCE public.foundations_id_seq OWNED BY public.foundations.id;
publicpostgresfalse249125921418highlightersTABLEJCREATE TABLE public.highlighters (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(50),
    name text,
    price integer,
    description text DEFAULT ''::text,
    image_data bytea,
    image_webp_url character varying(500),
    lab jsonb,
    color_vector jsonb,
    hex_primary character varying(10),
    created_at timestamp without time zone DEFAULT now(),
    qdrant_vector_12d double precision[],
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    in_stock boolean DEFAULT true,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_url text,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
 DROP TABLE public.highlighters;
publicheaprpostgresfalse125921417highlighters_id_seqSEQUENCECREATE SEQUENCE public.highlighters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
*DROP SEQUENCE public.highlighters_id_seq;
publicpostgresfalse240H00highlighters_id_seqSEQUENCE OWNED BYKALTER SEQUENCE public.highlighters_id_seq OWNED BY public.highlighters.id;
publicpostgresfalse239125922817 lipsticksTABLECREATE TABLE public.lipsticks (
    id integer NOT NULL,
    brand character varying(100),
    sale_page_id character varying(500),
    name character varying(500),
    price integer,
    description text,
    image_data bytea,
    image_webp_url text,
    lab jsonb,
    color_vector json,
    hex_primary character varying(7),
    source_type character varying(100),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    qdrant_vector_12d double precision[],
    shade_code character varying(100),
    source_url text,
    in_stock boolean DEFAULT true,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    swatch_image_url text,
    swatch_html text,
    sku text,
    category character varying(30),
    product_type character varying(40),
    status character varying(20) DEFAULT 'active'::character varying,
    review_status character varying(20) DEFAULT 'approved'::character varying,
    currency character varying(3) DEFAULT 'TWD'::character varying,
    image_urls jsonb DEFAULT '[]'::jsonb,
    source_site text,
    source_product_id text,
    last_crawled_at timestamp with time zone,
    crawl_fingerprint text,
    style_tags text[] DEFAULT '{}'::text[],
    finish_tags text[] DEFAULT '{}'::text[],
    season_tags text[] DEFAULT '{}'::text[],
    occasion_tags text[] DEFAULT '{}'::text[],
    feature_tags text[] DEFAULT '{}'::text[],
    avoid_tags text[] DEFAULT '{}'::text[],
    shade_name text,
    coverage character varying(20),
    undertone character varying(20),
    texture text,
    recommendation_ready boolean DEFAULT false,
    data_quality_score numeric(4,3) DEFAULT 0,
    version integer DEFAULT 1 NOT NULL,
    deleted_at timestamp with time zone
);
DROP TABLE public.lipsticks;
publicheaprpostgresfalse125922816lipsticks_id_seqSEQUENCECREATE SEQUENCE public.lipsticks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
'DROP SEQUENCE public.lipsticks_id_seq;
publicpostgresfalse248I00lipsticks_id_seqSEQUENCE OWNED BYEALTER SEQUENCE public.lipsticks_id_seq OWNED BY public.lipsticks.id;
publicpostgresfalse247125923082member_audit_logsTABLE:CREATE TABLE public.member_audit_logs (
    id integer NOT NULL,
    actor_email character varying(100) NOT NULL,
    target_email character varying(100) NOT NULL,
    action character varying(50) NOT NULL,
    before_value jsonb,
    after_value jsonb,
    created_at timestamp without time zone DEFAULT now()
);
%DROP TABLE public.member_audit_logs;
publicheaprpostgresfalse125923081member_audit_logs_id_seqSEQUENCECREATE SEQUENCE public.member_audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
/DROP SEQUENCE public.member_audit_logs_id_seq;
publicpostgresfalse254J00member_audit_logs_id_seqSEQUENCE OWNED BYUALTER SEQUENCE public.member_audit_logs_id_seq OWNED BY public.member_audit_logs.id;
publicpostgresfalse253125924047member_deletion_jobsTABLECREATE TABLE public.member_deletion_jobs (
    id character varying(36) NOT NULL,
    request_id character varying(64) NOT NULL,
    member_email character varying(254) NOT NULL,
    state character varying(20) DEFAULT 'pending'::character varying NOT NULL,
    attempts integer DEFAULT 0 NOT NULL,
    last_error_code character varying(80),
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT chk_member_deletion_job_state CHECK (((state)::text = ANY ((ARRAY['pending'::character varying, 'deleting'::character varying, 'completed'::character varying, 'failed'::character varying])::text[])))
);
(DROP TABLE public.member_deletion_jobs;
publicheaprpostgresfalse125921063member_level_historyTABLECREATE TABLE public.member_level_history (
    id integer NOT NULL,
    member_id character varying(20),
    old_level character varying(20),
    new_level character varying(20),
    changed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
(DROP TABLE public.member_level_history;
publicheaprpostgresfalse125921062member_level_history_id_seqSEQUENCECREATE SEQUENCE public.member_level_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
2DROP SEQUENCE public.member_level_history_id_seq;
publicpostgresfalse230K00member_level_history_id_seqSEQUENCE OWNED BY[ALTER SEQUENCE public.member_level_history_id_seq OWNED BY public.member_level_history.id;
publicpostgresfalse229125923954member_sessionsTABLECREATE TABLE public.member_sessions (
    session_hash character varying(64) NOT NULL,
    member_id character varying(20) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    last_seen_at timestamp with time zone,
    session_version integer DEFAULT 1 NOT NULL,
    session_id character varying(64),
    source_identifier character varying(128)
);
#DROP TABLE public.member_sessions;
publicheaprpostgresfalse125920899membersTABLECREATE TABLE public.members (
    phone_number character varying(20) NOT NULL,
    name character varying(50) DEFAULT NULL::character varying,
    email character varying(191) NOT NULL,
    password_hash character varying(255) NOT NULL,
    level public.member_level_enum DEFAULT 'bronze'::public.member_level_enum,
    age integer,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    status character varying(50) DEFAULT 'active'::character varying,
    role character varying(20) DEFAULT 'member'::character varying NOT NULL,
    points integer DEFAULT 0 NOT NULL,
    allowed_pages jsonb,
    total_earned_points integer DEFAULT 0 NOT NULL,
    used_points integer DEFAULT 0 NOT NULL,
    vip_requested boolean DEFAULT false,
    render_daily_limit integer DEFAULT 5,
    render_remaining integer DEFAULT 5,
    render_reset_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    email_verified boolean DEFAULT false,
    points_balance integer DEFAULT 0,
    lifetime_points integer DEFAULT 0,
    referral_code character varying(32),
    referred_by_email character varying(100),
    active_theme character varying(20) DEFAULT 'classic'::character varying,
    deleted_at timestamp with time zone,
    deleted_by character varying(254),
    deletion_reason character varying(255),
    deletion_request_id character varying(64),
    session_version integer DEFAULT 1 NOT NULL,
    deletion_state character varying(20),
    deletion_attempts integer DEFAULT 0 NOT NULL,
    deletion_last_error character varying(500),
    email_verified_at timestamp without time zone,
    CONSTRAINT members_status_check CHECK (((status)::text = ANY ((ARRAY['active'::character varying, 'suspended'::character varying, 'deleted'::character varying])::text[])))
);
DROP TABLE public.members;
publicheaprpostgresfalse970970125923163  otp_codesTABLECREATE TABLE public.otp_codes (
    id bigint NOT NULL,
    email character varying(191) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    attempts integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    code_hash character varying(255) NOT NULL,
    purpose character varying(40) DEFAULT 'email_verification'::character varying NOT NULL,
    verified_at timestamp without time zone
);
DROP TABLE public.otp_codes;
publicheaprpostgresfalse125923162otp_codes_id_seqSEQUENCEyCREATE SEQUENCE public.otp_codes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
'DROP SEQUENCE public.otp_codes_id_seq;
publicpostgresfalse262L00otp_codes_id_seqSEQUENCE OWNED BYEALTER SEQUENCE public.otp_codes_id_seq OWNED BY public.otp_codes.id;
publicpostgresfalse261125924102pending_registrationsTABLExCREATE TABLE public.pending_registrations (
    email character varying(100) NOT NULL,
    phone_number character varying(20) NOT NULL,
    name character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    age integer NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);
)DROP TABLE public.pending_registrations;
publicheaprpostgresfalse125923096points_transactionsTABLECREATE TABLE public.points_transactions (
    id integer NOT NULL,
    member_email character varying(191) NOT NULL,
    delta integer NOT NULL,
    balance_after integer NOT NULL,
    reason character varying(50) NOT NULL,
    ref_id character varying(100),
    note text,
    created_at timestamp without time zone DEFAULT now(),
    meta jsonb,
    idempotency_key character varying(128)
);
'DROP TABLE public.points_transactions;
publicheaprpostgresfalse125923095points_transactions_id_seqSEQUENCECREATE SEQUENCE public.points_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
1DROP SEQUENCE public.points_transactions_id_seq;
publicpostgresfalse256M00points_transactions_id_seqSEQUENCE OWNED BYYALTER SEQUENCE public.points_transactions_id_seq OWNED BY public.points_transactions.id;
publicpostgresfalse255125923602product_audit_logsTABLE{CREATE TABLE public.product_audit_logs (
    id bigint NOT NULL,
    product_id text NOT NULL,
    product_type character varying(40) NOT NULL,
    action character varying(20) NOT NULL,
    admin_id text NOT NULL,
    before_data jsonb,
    after_data jsonb,
    request_id text,
    source_ip inet,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);
&DROP TABLE public.product_audit_logs;
publicheaprpostgresfalse125923601product_audit_logs_id_seqSEQUENCECREATE SEQUENCE public.product_audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
0DROP SEQUENCE public.product_audit_logs_id_seq;
publicpostgresfalse279N00product_audit_logs_id_seqSEQUENCE OWNED BYWALTER SEQUENCE public.product_audit_logs_id_seq OWNED BY public.product_audit_logs.id;
publicpostgresfalse278125924168product_catalogTABLECREATE TABLE public.product_catalog (
    id bigint NOT NULL,
    product_type character varying(40) NOT NULL,
    source_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);
#DROP TABLE public.product_catalog;
publicheaprpostgresfalse125924167product_catalog_id_seqSEQUENCEALTER TABLE public.product_catalog ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.product_catalog_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);
publicpostgresfalse286125920912products_id_seqSEQUENCECREATE SEQUENCE public.products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
&DROP SEQUENCE public.products_id_seq;
publicpostgresfalse222O00products_id_seqSEQUENCE OWNED BYCALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;
publicpostgresfalse221125923246 referralsTABLECREATE TABLE public.referrals (
    id bigint NOT NULL,
    referrer_email character varying(191),
    referred_email character varying(191),
    points_awarded integer DEFAULT 20,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);
DROP TABLE public.referrals;
publicheaprpostgresfalse125923245referrals_id_seqSEQUENCEyCREATE SEQUENCE public.referrals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
'DROP SEQUENCE public.referrals_id_seq;
publicpostgresfalse272P00referrals_id_seqSEQUENCE OWNED BYEALTER SEQUENCE public.referrals_id_seq OWNED BY public.referrals.id;
publicpostgresfalse271125923130saved_looksTABLE7CREATE TABLE public.saved_looks (
    id integer NOT NULL,
    member_email character varying(100) NOT NULL,
    style character varying(120) NOT NULL,
    before_image_url text NOT NULL,
    after_image_url text NOT NULL,
    analysis_summary jsonb,
    created_at timestamp without time zone DEFAULT now()
);
DROP TABLE public.saved_looks;
publicheaprpostgresfalse125923129saved_looks_id_seqSEQUENCECREATE SEQUENCE public.saved_looks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
)DROP SEQUENCE public.saved_looks_id_seq;
publicpostgresfalse260Q00saved_looks_id_seqSEQUENCE OWNED BYIALTER SEQUENCE public.saved_looks_id_seq OWNED BY public.saved_looks.id;
publicpostgresfalse259125923211task_claimsTABLEMCREATE TABLE public.task_claims (
    id bigint NOT NULL,
    member_email character varying(191),
    task_id character varying(40) NOT NULL,
    claimed_date date DEFAULT CURRENT_DATE,
    claimed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    claim_date date NOT NULL,
    idempotency_key character varying(128)
);
DROP TABLE public.task_claims;
publicheaprpostgresfalse125923210task_claims_id_seqSEQUENCE{CREATE SEQUENCE public.task_claims_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
)DROP SEQUENCE public.task_claims_id_seq;
publicpostgresfalse268R00task_claims_id_seqSEQUENCE OWNED BYIALTER SEQUENCE public.task_claims_id_seq OWNED BY public.task_claims.id;
publicpostgresfalse267125921072
tryon_recordsTABLECREATE TABLE public.tryon_records (
    id integer NOT NULL,
    member_id character varying(20) NOT NULL,
    item_id integer NOT NULL,
    item_type character varying(50) NOT NULL,
    original_image_url character varying(500) NOT NULL,
    generated_image_url character varying(500) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    makeup_advice text
);
!DROP TABLE public.tryon_records;
publicheaprpostgresfalse125921071tryon_records_id_seqSEQUENCECREATE SEQUENCE public.tryon_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
+DROP SEQUENCE public.tryon_records_id_seq;
publicpostgresfalse232S00tryon_records_id_seqSEQUENCE OWNED BYMALTER SEQUENCE public.tryon_records_id_seq OWNED BY public.tryon_records.id;
publicpostgresfalse231125923229unlocked_themesTABLE  CREATE TABLE public.unlocked_themes (
    id bigint NOT NULL,
    member_email character varying(191),
    theme_id character varying(20) NOT NULL,
    unlocked_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    idempotency_key character varying(128)
);
#DROP TABLE public.unlocked_themes;
publicheaprpostgresfalse
125923228unlocked_themes_id_seqSEQUENCECREATE SEQUENCE public.unlocked_themes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
-DROP SEQUENCE public.unlocked_themes_id_seq;
publicpostgresfalse270T00unlocked_themes_id_seqSEQUENCE OWNED BYQALTER SEQUENCE public.unlocked_themes_id_seq OWNED BY public.unlocked_themes.id;
publicpostgresfalse269125923071view_member_activityVIEWCREATE VIEW public.view_member_activity AS
SELECT
    NULL::character varying(20) AS phone_number,
    NULL::character varying(50) AS name,
    NULL::public.member_level_enum AS level,
    NULL::character varying(50) AS status,
    NULL::character varying(20) AS role,
    NULL::bigint AS total_checkins,
    NULL::bigint AS total_favorites,
    NULL::timestamp without time zone AS last_checkin_at,
    NULL::numeric AS member_days;
'DROP VIEW public.view_member_activity;
publicvpostgresfalse970125923076view_member_dashboardVIEWCREATE VIEW public.view_member_dashboard AS
 SELECT m.phone_number,
    m.name,
    m.level,
    m.status,
    m.role,
    count(DISTINCT c.id) AS checkins,
    count(DISTINCT f.id) AS favorites,
    max(c.checkin_time) AS last_active
   FROM ((public.members m
     LEFT JOIN public.checkins c ON (((m.phone_number)::text = (c.member_id)::text)))
     LEFT JOIN public.favorites f ON (((m.phone_number)::text = (f.member_id)::text)))
  GROUP BY m.phone_number, m.name, m.level, m.status, m.role;
(DROP VIEW public.view_member_dashboard;
publicvpostgresfalse220220220220220224224224226226970125921107view_product_listVIEWCREATE VIEW public.view_product_list AS
 SELECT id,
    name,
    ('NT$'::text || to_char(price, 'FM999,999,999'::text)) AS formatted_price,
    description
   FROM public.products;
$DROP VIEW public.view_product_list;
publicvpostgresfalse222222222222125921097view_product_popularityVIEWxCREATE VIEW public.view_product_popularity AS
 SELECT p.id,
    p.name,
    p.price,
    count(f.id) AS favorite_count,
    ((count(f.id))::numeric * p.price) AS popularity_score
   FROM (public.products p
     LEFT JOIN public.favorites f ON (((p.id = f.item_id) AND ((f.item_type)::text = 'products'::text))))
  GROUP BY p.id, p.name, p.price
  ORDER BY (count(f.id)) DESC;
*DROP VIEW public.view_product_popularity;
publicvpostgresfalse226222222222226226260423179analysis_history idDEFAULTzALTER TABLE ONLY public.analysis_history ALTER COLUMN id SET DEFAULT nextval('public.analysis_history_id_seq'::regclass);
BALTER TABLE public.analysis_history ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse263264264260423119
audit_logs idDEFAULTnALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);
<ALTER TABLE public.audit_logs ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse257258258260421391
blushes idDEFAULThALTER TABLE ONLY public.blushes ALTER COLUMN id SET DEFAULT nextval('public.blushes_id_seq'::regclass);
9ALTER TABLE public.blushes ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse236235236260423271cart idDEFAULTbALTER TABLE ONLY public.cart ALTER COLUMN id SET DEFAULT nextval('public.cart_id_seq'::regclass);
6ALTER TABLE public.cart ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse274273274260423292
cart_items idDEFAULTnALTER TABLE ONLY public.cart_items ALTER COLUMN id SET DEFAULT nextval('public.cart_items_id_seq'::regclass);
<ALTER TABLE public.cart_items ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse276275276260421018checkins idDEFAULTjALTER TABLE ONLY public.checkins ALTER COLUMN id SET DEFAULT nextval('public.checkins_id_seq'::regclass);
:ALTER TABLE public.checkins ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse223224224260421054color_palettes idDEFAULTvALTER TABLE ONLY public.color_palettes ALTER COLUMN id SET DEFAULT nextval('public.color_palettes_id_seq'::regclass);
@ALTER TABLE public.color_palettes ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse228227228[260422605
contouring idDEFAULTnALTER TABLE ONLY public.contouring ALTER COLUMN id SET DEFAULT nextval('public.contouring_id_seq'::regclass);
<ALTER TABLE public.contouring ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse246245246260423195daily_checkins idDEFAULTvALTER TABLE ONLY public.daily_checkins ALTER COLUMN id SET DEFAULT nextval('public.daily_checkins_id_seq'::regclass);
@ALTER TABLE public.daily_checkins ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse265266266260421406eyebrows idDEFAULTjALTER TABLE ONLY public.eyebrows ALTER COLUMN id SET DEFAULT nextval('public.eyebrows_id_seq'::regclass);
:ALTER TABLE public.eyebrows ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse237238238I260422468eyeliner_mascara idDEFAULTzALTER TABLE ONLY public.eyeliner_mascara ALTER COLUMN id SET DEFAULT nextval('public.eyeliner_mascara_id_seq'::regclass);
BALTER TABLE public.eyeliner_mascara ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse2442432447260422392
eyeshadows idDEFAULTnALTER TABLE ONLY public.eyeshadows ALTER COLUMN id SET DEFAULT nextval('public.eyeshadows_id_seq'::regclass);
<ALTER TABLE public.eyeshadows ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse241242242260421035favorites idDEFAULTlALTER TABLE ONLY public.favorites ALTER COLUMN id SET DEFAULT nextval('public.favorites_id_seq'::regclass);
;ALTER TABLE public.favorites ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse225226226~260422833foundations idDEFAULTpALTER TABLE ONLY public.foundations ALTER COLUMN id SET DEFAULT nextval('public.foundations_id_seq'::regclass);
=ALTER TABLE public.foundations ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse250249250%260421421highlighters idDEFAULTrALTER TABLE ONLY public.highlighters ALTER COLUMN id SET DEFAULT nextval('public.highlighters_id_seq'::regclass);
>ALTER TABLE public.highlighters ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse239240240m260422820lipsticks idDEFAULTlALTER TABLE ONLY public.lipsticks ALTER COLUMN id SET DEFAULT nextval('public.lipsticks_id_seq'::regclass);
;ALTER TABLE public.lipsticks ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse248247248260423085member_audit_logs idDEFAULT|ALTER TABLE ONLY public.member_audit_logs ALTER COLUMN id SET DEFAULT nextval('public.member_audit_logs_id_seq'::regclass);
CALTER TABLE public.member_audit_logs ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse253254254260421066member_level_history idDEFAULTALTER TABLE ONLY public.member_level_history ALTER COLUMN id SET DEFAULT nextval('public.member_level_history_id_seq'::regclass);
FALTER TABLE public.member_level_history ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse230229230260423166otp_codes idDEFAULTlALTER TABLE ONLY public.otp_codes ALTER COLUMN id SET DEFAULT nextval('public.otp_codes_id_seq'::regclass);
;ALTER TABLE public.otp_codes ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse262261262260423099points_transactions idDEFAULTALTER TABLE ONLY public.points_transactions ALTER COLUMN id SET DEFAULT nextval('public.points_transactions_id_seq'::regclass);
EALTER TABLE public.points_transactions ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse256255256260423605product_audit_logs idDEFAULT~ALTER TABLE ONLY public.product_audit_logs ALTER COLUMN id SET DEFAULT nextval('public.product_audit_logs_id_seq'::regclass);
DALTER TABLE public.product_audit_logs ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse279278279260420916products idDEFAULTjALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);
:ALTER TABLE public.products ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse221222222260423249referrals idDEFAULTlALTER TABLE ONLY public.referrals ALTER COLUMN id SET DEFAULT nextval('public.referrals_id_seq'::regclass);
;ALTER TABLE public.referrals ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse272271272260423133saved_looks idDEFAULTpALTER TABLE ONLY public.saved_looks ALTER COLUMN id SET DEFAULT nextval('public.saved_looks_id_seq'::regclass);
=ALTER TABLE public.saved_looks ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse259260260260423214task_claims idDEFAULTpALTER TABLE ONLY public.task_claims ALTER COLUMN id SET DEFAULT nextval('public.task_claims_id_seq'::regclass);
=ALTER TABLE public.task_claims ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse267268268260421075tryon_records idDEFAULTtALTER TABLE ONLY public.tryon_records ALTER COLUMN id SET DEFAULT nextval('public.tryon_records_id_seq'::regclass);
?ALTER TABLE public.tryon_records ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse232231232260423232unlocked_themes idDEFAULTxALTER TABLE ONLY public.unlocked_themes ALTER COLUMN id SET DEFAULT nextval('public.unlocked_themes_id_seq'::regclass);
AALTER TABLE public.unlocked_themes ALTER COLUMN id DROP DEFAULT;
publicpostgresfalse270269270K260623564&admin_audit_logs admin_audit_logs_pkey
CONSTRAINTdALTER TABLE ONLY public.admin_audit_logs
    ADD CONSTRAINT admin_audit_logs_pkey PRIMARY KEY (id);
PALTER TABLE ONLY public.admin_audit_logs DROP CONSTRAINT admin_audit_logs_pkey;
publicpostgresfalse277M2606235660admin_audit_logs admin_audit_logs_request_id_key
CONSTRAINTqALTER TABLE ONLY public.admin_audit_logs
    ADD CONSTRAINT admin_audit_logs_request_id_key UNIQUE (request_id);
ZALTER TABLE ONLY public.admin_audit_logs DROP CONSTRAINT admin_audit_logs_request_id_key;
publicpostgresfalse277(260623185&analysis_history analysis_history_pkey
CONSTRAINTdALTER TABLE ONLY public.analysis_history
    ADD CONSTRAINT analysis_history_pkey PRIMARY KEY (id);
PALTER TABLE ONLY public.analysis_history DROP CONSTRAINT analysis_history_pkey;
publicpostgresfalse264260623128audit_logs audit_logs_pkey
CONSTRAINTXALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);
DALTER TABLE ONLY public.audit_logs DROP CONSTRAINT audit_logs_pkey;
publicpostgresfalse258260621398blushes blushes_pkey
CONSTRAINTRALTER TABLE ONLY public.blushes
    ADD CONSTRAINT blushes_pkey PRIMARY KEY (id);
>ALTER TABLE ONLY public.blushes DROP CONSTRAINT blushes_pkey;
publicpostgresfalse236260621400 blushes blushes_sale_page_id_key
CONSTRAINTcALTER TABLE ONLY public.blushes
    ADD CONSTRAINT blushes_sale_page_id_key UNIQUE (sale_page_id);
JALTER TABLE ONLY public.blushes DROP CONSTRAINT blushes_sale_page_id_key;
publicpostgresfalse236G260623299cart_items cart_items_pkey
CONSTRAINTXALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_pkey PRIMARY KEY (id);
DALTER TABLE ONLY public.cart_items DROP CONSTRAINT cart_items_pkey;
publicpostgresfalse276C260623279cart cart_pkey
CONSTRAINTLALTER TABLE ONLY public.cart
    ADD CONSTRAINT cart_pkey PRIMARY KEY (id);
8ALTER TABLE ONLY public.cart DROP CONSTRAINT cart_pkey;
publicpostgresfalse274260621025checkins checkins_pkey
CONSTRAINTTALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_pkey PRIMARY KEY (id);
@ALTER TABLE ONLY public.checkins DROP CONSTRAINT checkins_pkey;
publicpostgresfalse224260621061*color_palettes color_palettes_hex_code_key
CONSTRAINTiALTER TABLE ONLY public.color_palettes
    ADD CONSTRAINT color_palettes_hex_code_key UNIQUE (hex_code);
TALTER TABLE ONLY public.color_palettes DROP CONSTRAINT color_palettes_hex_code_key;
publicpostgresfalse228260621059"color_palettes color_palettes_pkey
CONSTRAINT`ALTER TABLE ONLY public.color_palettes
    ADD CONSTRAINT color_palettes_pkey PRIMARY KEY (id);
LALTER TABLE ONLY public.color_palettes DROP CONSTRAINT color_palettes_pkey;
publicpostgresfalse228260622612contouring contouring_pkey
CONSTRAINTXALTER TABLE ONLY public.contouring
    ADD CONSTRAINT contouring_pkey PRIMARY KEY (id);
DALTER TABLE ONLY public.contouring DROP CONSTRAINT contouring_pkey;
publicpostgresfalse246260622614&contouring contouring_sale_page_id_key
CONSTRAINTiALTER TABLE ONLY public.contouring
    ADD CONSTRAINT contouring_sale_page_id_key UNIQUE (sale_page_id);
PALTER TABLE ONLY public.contouring DROP CONSTRAINT contouring_sale_page_id_key;
publicpostgresfalse246g2606241376crawler_staging_products crawler_staging_products_pkey
CONSTRAINTtALTER TABLE ONLY public.crawler_staging_products
    ADD CONSTRAINT crawler_staging_products_pkey PRIMARY KEY (id);
`ALTER TABLE ONLY public.crawler_staging_products DROP CONSTRAINT crawler_staging_products_pkey;
publicpostgresfalse284*2606240751daily_checkins daily_checkins_idempotency_key_key
CONSTRAINTwALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT daily_checkins_idempotency_key_key UNIQUE (idempotency_key);
[ALTER TABLE ONLY public.daily_checkins DROP CONSTRAINT daily_checkins_idempotency_key_key;
publicpostgresfalse266,260623202"daily_checkins daily_checkins_pkey
CONSTRAINT`ALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT daily_checkins_pkey PRIMARY KEY (id);
LALTER TABLE ONLY public.daily_checkins DROP CONSTRAINT daily_checkins_pkey;
publicpostgresfalse266260621413eyebrows eyebrows_pkey
CONSTRAINTTALTER TABLE ONLY public.eyebrows
    ADD CONSTRAINT eyebrows_pkey PRIMARY KEY (id);
@ALTER TABLE ONLY public.eyebrows DROP CONSTRAINT eyebrows_pkey;
publicpostgresfalse238260621415"eyebrows eyebrows_sale_page_id_key
CONSTRAINTeALTER TABLE ONLY public.eyebrows
    ADD CONSTRAINT eyebrows_sale_page_id_key UNIQUE (sale_page_id);
LALTER TABLE ONLY public.eyebrows DROP CONSTRAINT eyebrows_sale_page_id_key;
publicpostgresfalse238260622475&eyeliner_mascara eyeliner_mascara_pkey
CONSTRAINTdALTER TABLE ONLY public.eyeliner_mascara
    ADD CONSTRAINT eyeliner_mascara_pkey PRIMARY KEY (id);
PALTER TABLE ONLY public.eyeliner_mascara DROP CONSTRAINT eyeliner_mascara_pkey;
publicpostgresfalse2442606224772eyeliner_mascara eyeliner_mascara_sale_page_id_key
CONSTRAINTuALTER TABLE ONLY public.eyeliner_mascara
    ADD CONSTRAINT eyeliner_mascara_sale_page_id_key UNIQUE (sale_page_id);
\ALTER TABLE ONLY public.eyeliner_mascara DROP CONSTRAINT eyeliner_mascara_sale_page_id_key;
publicpostgresfalse244260622399eyeshadows eyeshadows_pkey
CONSTRAINTXALTER TABLE ONLY public.eyeshadows
    ADD CONSTRAINT eyeshadows_pkey PRIMARY KEY (id);
DALTER TABLE ONLY public.eyeshadows DROP CONSTRAINT eyeshadows_pkey;
publicpostgresfalse242260622401&eyeshadows eyeshadows_sale_page_id_key
CONSTRAINTiALTER TABLE ONLY public.eyeshadows
    ADD CONSTRAINT eyeshadows_sale_page_id_key UNIQUE (sale_page_id);
PALTER TABLE ONLY public.eyeshadows DROP CONSTRAINT eyeshadows_sale_page_id_key;
publicpostgresfalse242260621042favorites favorites_pkey
CONSTRAINTVALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_pkey PRIMARY KEY (id);
BALTER TABLE ONLY public.favorites DROP CONSTRAINT favorites_pkey;
publicpostgresfalse226260622841foundations foundations_pkey
CONSTRAINTZALTER TABLE ONLY public.foundations
    ADD CONSTRAINT foundations_pkey PRIMARY KEY (id);
FALTER TABLE ONLY public.foundations DROP CONSTRAINT foundations_pkey;
publicpostgresfalse250260622843(foundations foundations_sale_page_id_key
CONSTRAINTkALTER TABLE ONLY public.foundations
    ADD CONSTRAINT foundations_sale_page_id_key UNIQUE (sale_page_id);
RALTER TABLE ONLY public.foundations DROP CONSTRAINT foundations_sale_page_id_key;
publicpostgresfalse250260621428highlighters highlighters_pkey
CONSTRAINT\ALTER TABLE ONLY public.highlighters
    ADD CONSTRAINT highlighters_pkey PRIMARY KEY (id);
HALTER TABLE ONLY public.highlighters DROP CONSTRAINT highlighters_pkey;
publicpostgresfalse240260621430*highlighters highlighters_sale_page_id_key
CONSTRAINTmALTER TABLE ONLY public.highlighters
    ADD CONSTRAINT highlighters_sale_page_id_key UNIQUE (sale_page_id);
TALTER TABLE ONLY public.highlighters DROP CONSTRAINT highlighters_sale_page_id_key;
publicpostgresfalse240
260622826lipsticks lipsticks_pkey
CONSTRAINTVALTER TABLE ONLY public.lipsticks
    ADD CONSTRAINT lipsticks_pkey PRIMARY KEY (id);
BALTER TABLE ONLY public.lipsticks DROP CONSTRAINT lipsticks_pkey;
publicpostgresfalse248260622828$lipsticks lipsticks_sale_page_id_key
CONSTRAINTgALTER TABLE ONLY public.lipsticks
    ADD CONSTRAINT lipsticks_sale_page_id_key UNIQUE (sale_page_id);
NALTER TABLE ONLY public.lipsticks DROP CONSTRAINT lipsticks_sale_page_id_key;
publicpostgresfalse248260623094(member_audit_logs member_audit_logs_pkey
CONSTRAINTfALTER TABLE ONLY public.member_audit_logs
    ADD CONSTRAINT member_audit_logs_pkey PRIMARY KEY (id);
RALTER TABLE ONLY public.member_audit_logs DROP CONSTRAINT member_audit_logs_pkey;
publicpostgresfalse254[260624067:member_deletion_jobs member_deletion_jobs_member_email_key
CONSTRAINT}ALTER TABLE ONLY public.member_deletion_jobs
    ADD CONSTRAINT member_deletion_jobs_member_email_key UNIQUE (member_email);
dALTER TABLE ONLY public.member_deletion_jobs DROP CONSTRAINT member_deletion_jobs_member_email_key;
publicpostgresfalse281]260624063.member_deletion_jobs member_deletion_jobs_pkey
CONSTRAINTlALTER TABLE ONLY public.member_deletion_jobs
    ADD CONSTRAINT member_deletion_jobs_pkey PRIMARY KEY (id);
XALTER TABLE ONLY public.member_deletion_jobs DROP CONSTRAINT member_deletion_jobs_pkey;
publicpostgresfalse281_2606240658member_deletion_jobs member_deletion_jobs_request_id_key
CONSTRAINTyALTER TABLE ONLY public.member_deletion_jobs
    ADD CONSTRAINT member_deletion_jobs_request_id_key UNIQUE (request_id);
bALTER TABLE ONLY public.member_deletion_jobs DROP CONSTRAINT member_deletion_jobs_request_id_key;
publicpostgresfalse281260621070.member_level_history member_level_history_pkey
CONSTRAINTlALTER TABLE ONLY public.member_level_history
    ADD CONSTRAINT member_level_history_pkey PRIMARY KEY (id);
XALTER TABLE ONLY public.member_level_history DROP CONSTRAINT member_level_history_pkey;
publicpostgresfalse230W260623962$member_sessions member_sessions_pkey
CONSTRAINTlALTER TABLE ONLY public.member_sessions
    ADD CONSTRAINT member_sessions_pkey PRIMARY KEY (session_hash);
NALTER TABLE ONLY public.member_sessions DROP CONSTRAINT member_sessions_pkey;
publicpostgresfalse280Y260624070.member_sessions member_sessions_session_id_key
CONSTRAINToALTER TABLE ONLY public.member_sessions
    ADD CONSTRAINT member_sessions_session_id_key UNIQUE (session_id);
XALTER TABLE ONLY public.member_sessions DROP CONSTRAINT member_sessions_session_id_key;
publicpostgresfalse280260623417members members_email_key
CONSTRAINTUALTER TABLE ONLY public.members
    ADD CONSTRAINT members_email_key UNIQUE (email);
CALTER TABLE ONLY public.members DROP CONSTRAINT members_email_key;
publicpostgresfalse220260620909members members_pkey
CONSTRAINT\ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_pkey PRIMARY KEY (phone_number);
>ALTER TABLE ONLY public.members DROP CONSTRAINT members_pkey;
publicpostgresfalse220&260623174otp_codes otp_codes_pkey
CONSTRAINTVALTER TABLE ONLY public.otp_codes
    ADD CONSTRAINT otp_codes_pkey PRIMARY KEY (id);
BALTER TABLE ONLY public.otp_codes DROP CONSTRAINT otp_codes_pkey;
publicpostgresfalse262b260624116<pending_registrations pending_registrations_phone_number_key
CONSTRAINTALTER TABLE ONLY public.pending_registrations
    ADD CONSTRAINT pending_registrations_phone_number_key UNIQUE (phone_number);
fALTER TABLE ONLY public.pending_registrations DROP CONSTRAINT pending_registrations_phone_number_key;
publicpostgresfalse282d2606241140pending_registrations pending_registrations_pkey
CONSTRAINTqALTER TABLE ONLY public.pending_registrations
    ADD CONSTRAINT pending_registrations_pkey PRIMARY KEY (email);
ZALTER TABLE ONLY public.pending_registrations DROP CONSTRAINT pending_registrations_pkey;
publicpostgresfalse282260624073;points_transactions points_transactions_idempotency_key_key
CONSTRAINTALTER TABLE ONLY public.points_transactions
    ADD CONSTRAINT points_transactions_idempotency_key_key UNIQUE (idempotency_key);
eALTER TABLE ONLY public.points_transactions DROP CONSTRAINT points_transactions_idempotency_key_key;
publicpostgresfalse256260623109,points_transactions points_transactions_pkey
CONSTRAINTjALTER TABLE ONLY public.points_transactions
    ADD CONSTRAINT points_transactions_pkey PRIMARY KEY (id);
VALTER TABLE ONLY public.points_transactions DROP CONSTRAINT points_transactions_pkey;
publicpostgresfalse256R260623616*product_audit_logs product_audit_logs_pkey
CONSTRAINThALTER TABLE ONLY public.product_audit_logs
    ADD CONSTRAINT product_audit_logs_pkey PRIMARY KEY (id);
TALTER TABLE ONLY public.product_audit_logs DROP CONSTRAINT product_audit_logs_pkey;
publicpostgresfalse279n260624177$product_catalog product_catalog_pkey
CONSTRAINTbALTER TABLE ONLY public.product_catalog
    ADD CONSTRAINT product_catalog_pkey PRIMARY KEY (id);
NALTER TABLE ONLY public.product_catalog DROP CONSTRAINT product_catalog_pkey;
publicpostgresfalse286260620926products products_pkey
CONSTRAINTTALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);
@ALTER TABLE ONLY public.products DROP CONSTRAINT products_pkey;
publicpostgresfalse222?260623254referrals referrals_pkey
CONSTRAINTVALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_pkey PRIMARY KEY (id);
BALTER TABLE ONLY public.referrals DROP CONSTRAINT referrals_pkey;
publicpostgresfalse272A260623381#referrals referrals_referred_id_key
CONSTRAINThALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_referred_id_key UNIQUE (referred_email);
MALTER TABLE ONLY public.referrals DROP CONSTRAINT referrals_referred_id_key;
publicpostgresfalse272"260623143saved_looks saved_looks_pkey
CONSTRAINTZALTER TABLE ONLY public.saved_looks
    ADD CONSTRAINT saved_looks_pkey PRIMARY KEY (id);
FALTER TABLE ONLY public.saved_looks DROP CONSTRAINT saved_looks_pkey;
publicpostgresfalse2601260624077+task_claims task_claims_idempotency_key_key
CONSTRAINTqALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT task_claims_idempotency_key_key UNIQUE (idempotency_key);
UALTER TABLE ONLY public.task_claims DROP CONSTRAINT task_claims_idempotency_key_key;
publicpostgresfalse2683260623220task_claims task_claims_pkey
CONSTRAINTZALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT task_claims_pkey PRIMARY KEY (id);
FALTER TABLE ONLY public.task_claims DROP CONSTRAINT task_claims_pkey;
publicpostgresfalse268260621086 tryon_records tryon_records_pkey
CONSTRAINT^ALTER TABLE ONLY public.tryon_records
    ADD CONSTRAINT tryon_records_pkey PRIMARY KEY (id);
JALTER TABLE ONLY public.tryon_records DROP CONSTRAINT tryon_records_pkey;
publicpostgresfalse23292606240793unlocked_themes unlocked_themes_idempotency_key_key
CONSTRAINTyALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT unlocked_themes_idempotency_key_key UNIQUE (idempotency_key);
]ALTER TABLE ONLY public.unlocked_themes DROP CONSTRAINT unlocked_themes_idempotency_key_key;
publicpostgresfalse270;260623237$unlocked_themes unlocked_themes_pkey
CONSTRAINTbALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT unlocked_themes_pkey PRIMARY KEY (id);
NALTER TABLE ONLY public.unlocked_themes DROP CONSTRAINT unlocked_themes_pkey;
publicpostgresfalse270I260623301cart_items uq_cart_item
CONSTRAINTcALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT uq_cart_item UNIQUE (member_email, item_id);
AALTER TABLE ONLY public.cart_items DROP CONSTRAINT uq_cart_item;
publicpostgresfalse276276l260624139:crawler_staging_products uq_crawler_staging_source_product
CONSTRAINTALTER TABLE ONLY public.crawler_staging_products
    ADD CONSTRAINT uq_crawler_staging_source_product UNIQUE (source_site, source_product_id);
dALTER TABLE ONLY public.crawler_staging_products DROP CONSTRAINT uq_crawler_staging_source_product;
publicpostgresfalse284284E260623281cart uq_member_cart_item
CONSTRAINTaALTER TABLE ONLY public.cart
    ADD CONSTRAINT uq_member_cart_item UNIQUE (member_id, item_id);
BALTER TABLE ONLY public.cart DROP CONSTRAINT uq_member_cart_item;
publicpostgresfalse274274.260623388%daily_checkins uq_member_checkin_date
CONSTRAINTvALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT uq_member_checkin_date UNIQUE (member_email, checkin_date);
OALTER TABLE ONLY public.daily_checkins DROP CONSTRAINT uq_member_checkin_date;
publicpostgresfalse266266260621044favorites uq_member_item
CONSTRAINTlALTER TABLE ONLY public.favorites
    ADD CONSTRAINT uq_member_item UNIQUE (member_id, item_id, item_type);
BALTER TABLE ONLY public.favorites DROP CONSTRAINT uq_member_item;
publicpostgresfalse2262262265260623395task_claims uq_member_task_date
CONSTRAINTyALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT uq_member_task_date UNIQUE (member_email, task_id, claimed_date);
IALTER TABLE ONLY public.task_claims DROP CONSTRAINT uq_member_task_date;
publicpostgresfalse268268268=260623410unlocked_themes uq_member_theme
CONSTRAINTlALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT uq_member_theme UNIQUE (member_email, theme_id);
IALTER TABLE ONLY public.unlocked_themes DROP CONSTRAINT uq_member_theme;
publicpostgresfalse270270p260624179)product_catalog uq_product_catalog_source
CONSTRAINTwALTER TABLE ONLY public.product_catalog
    ADD CONSTRAINT uq_product_catalog_source UNIQUE (product_type, source_id);
SALTER TABLE ONLY public.product_catalog DROP CONSTRAINT uq_product_catalog_source;
publicpostgresfalse2862867260623983task_claims uq_task_claim_date
CONSTRAINTvALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT uq_task_claim_date UNIQUE (member_email, task_id, claim_date);
HALTER TABLE ONLY public.task_claims DROP CONSTRAINT uq_task_claim_date;
publicpostgresfalse268268268e125924158crawler_staging_dedupe_uidxINDEXmCREATE UNIQUE INDEX crawler_staging_dedupe_uidx ON public.crawler_staging_products USING btree (dedupe_key);
/DROP INDEX public.crawler_staging_dedupe_uidx;
publicpostgresfalse284h125924160crawler_staging_source_idxINDEXyCREATE INDEX crawler_staging_source_idx ON public.crawler_staging_products USING btree (source_site, source_product_id);
.DROP INDEX public.crawler_staging_source_idx;
publicpostgresfalse284284i125924159crawler_staging_status_idxINDEXrCREATE INDEX crawler_staging_status_idx ON public.crawler_staging_products USING btree (status, updated_at DESC);
.DROP INDEX public.crawler_staging_status_idx;
publicpostgresfalse284284N125923572idx_admin_audit_target_createdINDEXtCREATE INDEX idx_admin_audit_target_created ON public.admin_audit_logs USING btree (target_email, created_at DESC);
2DROP INDEX public.idx_admin_audit_target_created;
publicpostgresfalse277277125923631idx_blushes_recommendableINDEX~CREATE INDEX idx_blushes_recommendable ON public.blushes USING btree (status, review_status, in_stock, recommendation_ready);
-DROP INDEX public.idx_blushes_recommendable;
publicpostgresfalse236236236236125921401idx_blushes_spidINDEXLCREATE INDEX idx_blushes_spid ON public.blushes USING btree (sale_page_id);
$DROP INDEX public.idx_blushes_spid;
publicpostgresfalse236125923699idx_contouring_recommendableINDEXCREATE INDEX idx_contouring_recommendable ON public.contouring USING btree (status, review_status, in_stock, recommendation_ready);
0DROP INDEX public.idx_contouring_recommendable;
publicpostgresfalse246246246246125922615idx_contouring_spidINDEXRCREATE INDEX idx_contouring_spid ON public.contouring USING btree (sale_page_id);
'DROP INDEX public.idx_contouring_spid;
publicpostgresfalse246j125924145.idx_crawler_staging_products_status_crawled_atINDEXCREATE INDEX idx_crawler_staging_products_status_crawled_at ON public.crawler_staging_products USING btree (status, crawled_at DESC);
BDROP INDEX public.idx_crawler_staging_products_status_crawled_at;
publicpostgresfalse284284125922478idx_em_spidINDEXPCREATE INDEX idx_em_spid ON public.eyeliner_mascara USING btree (sale_page_id);
DROP INDEX public.idx_em_spid;
publicpostgresfalse244125923648idx_eyebrows_recommendableINDEXCREATE INDEX idx_eyebrows_recommendable ON public.eyebrows USING btree (status, review_status, in_stock, recommendation_ready);
.DROP INDEX public.idx_eyebrows_recommendable;
publicpostgresfalse238238238238125921416idx_eyebrows_spidINDEXNCREATE INDEX idx_eyebrows_spid ON public.eyebrows USING btree (sale_page_id);
%DROP INDEX public.idx_eyebrows_spid;
publicpostgresfalse238125923682"idx_eyeliner_mascara_recommendableINDEXCREATE INDEX idx_eyeliner_mascara_recommendable ON public.eyeliner_mascara USING btree (status, review_status, in_stock, recommendation_ready);
6DROP INDEX public.idx_eyeliner_mascara_recommendable;
publicpostgresfalse244244244244125923665idx_eyeshadows_recommendableINDEXCREATE INDEX idx_eyeshadows_recommendable ON public.eyeshadows USING btree (status, review_status, in_stock, recommendation_ready);
0DROP INDEX public.idx_eyeshadows_recommendable;
publicpostgresfalse242242242242125922402idx_eyeshadows_spidINDEXRCREATE INDEX idx_eyeshadows_spid ON public.eyeshadows USING btree (sale_page_id);
'DROP INDEX public.idx_eyeshadows_spid;
publicpostgresfalse242125923714idx_foundations_recommendableINDEXCREATE INDEX idx_foundations_recommendable ON public.foundations USING btree (status, review_status, in_stock, recommendation_ready);
1DROP INDEX public.idx_foundations_recommendable;
publicpostgresfalse250250250250125924221idx_foundations_series_depthINDEXCREATE INDEX idx_foundations_series_depth ON public.foundations USING btree (series_id, depth_index) WHERE ((series_id IS NOT NULL) AND (depth_index IS NOT NULL));
0DROP INDEX public.idx_foundations_series_depth;
publicpostgresfalse250250250250125922844idx_foundations_spidINDEXTCREATE INDEX idx_foundations_spid ON public.foundations USING btree (sale_page_id);
(DROP INDEX public.idx_foundations_spid;
publicpostgresfalse250125923745idx_highlighters_recommendableINDEXCREATE INDEX idx_highlighters_recommendable ON public.highlighters USING btree (status, review_status, in_stock, recommendation_ready);
2DROP INDEX public.idx_highlighters_recommendable;
publicpostgresfalse240240240240125921431idx_highlighters_spidINDEXVCREATE INDEX idx_highlighters_spid ON public.highlighters USING btree (sale_page_id);
)DROP INDEX public.idx_highlighters_spid;
publicpostgresfalse240125923760idx_lipsticks_recommendableINDEXCREATE INDEX idx_lipsticks_recommendable ON public.lipsticks USING btree (status, review_status, in_stock, recommendation_ready);
/DROP INDEX public.idx_lipsticks_recommendable;
publicpostgresfalse248248248248125923113"idx_member_audit_logs_target_emailINDEXhCREATE INDEX idx_member_audit_logs_target_email ON public.member_audit_logs USING btree (target_email);
6DROP INDEX public.idx_member_audit_logs_target_email;
publicpostgresfalse254S125924071idx_member_sessions_session_idINDEX`CREATE INDEX idx_member_sessions_session_id ON public.member_sessions USING btree (session_id);
2DROP INDEX public.idx_member_sessions_session_id;
publicpostgresfalse280T125924080idx_member_sessions_sourceINDEXcCREATE INDEX idx_member_sessions_source ON public.member_sessions USING btree (source_identifier);
.DROP INDEX public.idx_member_sessions_source;
publicpostgresfalse280125924090idx_members_email_verified_atINDEX^CREATE INDEX idx_members_email_verified_at ON public.members USING btree (email_verified_at);
1DROP INDEX public.idx_members_email_verified_at;
publicpostgresfalse220125923456idx_members_referral_codeINDEXCREATE UNIQUE INDEX idx_members_referral_code ON public.members USING btree (referral_code) WHERE (referral_code IS NOT NULL);
-DROP INDEX public.idx_members_referral_code;
publicpostgresfalse220220125923570idx_members_status_deleted_atINDEX_CREATE INDEX idx_members_status_deleted_at ON public.members USING btree (status, deleted_at);
1DROP INDEX public.idx_members_status_deleted_at;
publicpostgresfalse220220#125923458idx_otp_codes_emailINDEXJCREATE INDEX idx_otp_codes_email ON public.otp_codes USING btree (email);
'DROP INDEX public.idx_otp_codes_email;
publicpostgresfalse262125923401$idx_points_transactions_member_emailINDEXlCREATE INDEX idx_points_transactions_member_email ON public.points_transactions USING btree (member_email);
8DROP INDEX public.idx_points_transactions_member_email;
publicpostgresfalse256P125923791idx_product_audit_logs_productINDEXCREATE INDEX idx_product_audit_logs_product ON public.product_audit_logs USING btree (product_type, product_id, created_at DESC);
2DROP INDEX public.idx_product_audit_logs_product;
publicpostgresfalse279279279125923571idx_saved_looks_member_createdINDEXoCREATE INDEX idx_saved_looks_member_created ON public.saved_looks USING btree (member_email, created_at DESC);
2DROP INDEX public.idx_saved_looks_member_created;
publicpostgresfalse260260 125923459idx_saved_looks_member_emailINDEX\CREATE INDEX idx_saved_looks_member_email ON public.saved_looks USING btree (member_email);
0DROP INDEX public.idx_saved_looks_member_email;
publicpostgresfalse260/125923984 idx_task_claims_member_task_dateINDEXzCREATE INDEX idx_task_claims_member_task_date ON public.task_claims USING btree (member_email, task_id, claim_date DESC);
4DROP INDEX public.idx_task_claims_member_task_date;
publicpostgresfalse268268268O125923567 ix_admin_audit_logs_target_emailINDEXeCREATE INDEX ix_admin_audit_logs_target_email ON public.admin_audit_logs USING btree (target_email);
4DROP INDEX public.ix_admin_audit_logs_target_email;
publicpostgresfalse277U125924044!ix_member_sessions_member_versionINDEXCREATE INDEX ix_member_sessions_member_version ON public.member_sessions USING btree (member_id, session_version, revoked_at);
5DROP INDEX public.ix_member_sessions_member_version;
publicpostgresfalse280280280$125924043!ix_otp_codes_email_purpose_expiryINDEXrCREATE INDEX ix_otp_codes_email_purpose_expiry ON public.otp_codes USING btree (email, purpose, expires_at DESC);
5DROP INDEX public.ix_otp_codes_email_purpose_expiry;
publicpostgresfalse262262262`125924117#ix_pending_registrations_expires_atINDEXkCREATE INDEX ix_pending_registrations_expires_at ON public.pending_registrations USING btree (expires_at);
7DROP INDEX public.ix_pending_registrations_expires_at;
publicpostgresfalse282125923402#ix_points_transactions_member_emailINDEXkCREATE INDEX ix_points_transactions_member_email ON public.points_transactions USING btree (member_email);
7DROP INDEX public.ix_points_transactions_member_email;
publicpostgresfalse256*261823074view_member_activity _RETURNRULEdCREATE OR REPLACE VIEW public.view_member_activity AS
 SELECT m.phone_number,
    m.name,
    m.level,
    m.status,
    m.role,
    count(DISTINCT c.id) AS total_checkins,
    count(DISTINCT f.id) AS total_favorites,
    max(c.checkin_time) AS last_checkin_at,
    EXTRACT(day FROM (now() - (m.created_at)::timestamp with time zone)) AS member_days
   FROM ((public.members m
     LEFT JOIN public.checkins c ON (((m.phone_number)::text = (c.member_id)::text)))
     LEFT JOIN public.favorites f ON (((m.phone_number)::text = (f.member_id)::text)))
  GROUP BY m.phone_number, m.name, m.level, m.status, m.role;
CREATE OR REPLACE VIEW public.view_member_activity AS
SELECT
    NULL::character varying(20) AS phone_number,
    NULL::character varying(50) AS name,
    NULL::public.member_level_enum AS level,
    NULL::character varying(50) AS status,
    NULL::character varying(20) AS role,
    NULL::bigint AS total_checkins,
    NULL::bigint AS total_favorites,
    NULL::timestamp without time zone AS last_checkin_at,
    NULL::numeric AS member_days;
publicpostgresfalse2202202202202262242242245331226220220251262021111checkins trg_auto_upgrade_levelTRIGGERCREATE TRIGGER trg_auto_upgrade_level AFTER INSERT ON public.checkins FOR EACH ROW EXECUTE FUNCTION public.func_auto_upgrade_level();
8DROP TRIGGER trg_auto_upgrade_level ON public.checkins;
publicpostgresfalse306224262021112$favorites trg_before_favorite_insertTRIGGERCREATE TRIGGER trg_before_favorite_insert BEFORE INSERT ON public.favorites FOR EACH ROW EXECUTE FUNCTION public.func_before_favorite_insert();
=DROP TRIGGER trg_before_favorite_insert ON public.favorites;
publicpostgresfalse226305262023820$blushes trg_blushes_product_contractTRIGGERCREATE TRIGGER trg_blushes_product_contract BEFORE INSERT OR UPDATE ON public.blushes FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
=DROP TRIGGER trg_blushes_product_contract ON public.blushes;
publicpostgresfalse348236262023824*contouring trg_contouring_product_contractTRIGGERCREATE TRIGGER trg_contouring_product_contract BEFORE INSERT OR UPDATE ON public.contouring FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
CDROP TRIGGER trg_contouring_product_contract ON public.contouring;
publicpostgresfalse246348262023821&eyebrows trg_eyebrows_product_contractTRIGGERCREATE TRIGGER trg_eyebrows_product_contract BEFORE INSERT OR UPDATE ON public.eyebrows FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
?DROP TRIGGER trg_eyebrows_product_contract ON public.eyebrows;
publicpostgresfalse3482382620238236eyeliner_mascara trg_eyeliner_mascara_product_contractTRIGGERCREATE TRIGGER trg_eyeliner_mascara_product_contract BEFORE INSERT OR UPDATE ON public.eyeliner_mascara FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
ODROP TRIGGER trg_eyeliner_mascara_product_contract ON public.eyeliner_mascara;
publicpostgresfalse244348262023822*eyeshadows trg_eyeshadows_product_contractTRIGGERCREATE TRIGGER trg_eyeshadows_product_contract BEFORE INSERT OR UPDATE ON public.eyeshadows FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
CDROP TRIGGER trg_eyeshadows_product_contract ON public.eyeshadows;
publicpostgresfalse348242262023825,foundations trg_foundations_product_contractTRIGGERCREATE TRIGGER trg_foundations_product_contract BEFORE INSERT OR UPDATE ON public.foundations FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
EDROP TRIGGER trg_foundations_product_contract ON public.foundations;
publicpostgresfalse348250262023826.highlighters trg_highlighters_product_contractTRIGGERCREATE TRIGGER trg_highlighters_product_contract BEFORE INSERT OR UPDATE ON public.highlighters FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
GDROP TRIGGER trg_highlighters_product_contract ON public.highlighters;
publicpostgresfalse348240262023827(lipsticks trg_lipsticks_product_contractTRIGGERCREATE TRIGGER trg_lipsticks_product_contract BEFORE INSERT OR UPDATE ON public.lipsticks FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();
ADROP TRIGGER trg_lipsticks_product_contract ON public.lipsticks;
publicpostgresfalse348248262021114 members trg_member_level_historyTRIGGERCREATE TRIGGER trg_member_level_history AFTER UPDATE ON public.members FOR EACH ROW EXECUTE FUNCTION public.func_member_level_history();
9DROP TRIGGER trg_member_level_history ON public.members;
publicpostgresfalse308220262021113%checkins trg_prevent_multiple_checkinTRIGGERCREATE TRIGGER trg_prevent_multiple_checkin BEFORE INSERT ON public.checkins FOR EACH ROW EXECUTE FUNCTION public.func_prevent_multiple_checkin();
>DROP TRIGGER trg_prevent_multiple_checkin ON public.checkins;
publicpostgresfalse224307262024182#blushes trg_product_catalog_blushesTRIGGERCREATE TRIGGER trg_product_catalog_blushes AFTER INSERT ON public.blushes FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
<DROP TRIGGER trg_product_catalog_blushes ON public.blushes;
publicpostgresfalse236293262024188)contouring trg_product_catalog_contouringTRIGGERCREATE TRIGGER trg_product_catalog_contouring AFTER INSERT ON public.contouring FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
BDROP TRIGGER trg_product_catalog_contouring ON public.contouring;
publicpostgresfalse293246262024184%eyebrows trg_product_catalog_eyebrowsTRIGGERCREATE TRIGGER trg_product_catalog_eyebrows AFTER INSERT ON public.eyebrows FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
>DROP TRIGGER trg_product_catalog_eyebrows ON public.eyebrows;
publicpostgresfalse2382932620241835eyeliner_mascara trg_product_catalog_eyeliner_mascaraTRIGGERCREATE TRIGGER trg_product_catalog_eyeliner_mascara AFTER INSERT ON public.eyeliner_mascara FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
NDROP TRIGGER trg_product_catalog_eyeliner_mascara ON public.eyeliner_mascara;
publicpostgresfalse293244262024185)eyeshadows trg_product_catalog_eyeshadowsTRIGGERCREATE TRIGGER trg_product_catalog_eyeshadows AFTER INSERT ON public.eyeshadows FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
BDROP TRIGGER trg_product_catalog_eyeshadows ON public.eyeshadows;
publicpostgresfalse242293262024186+foundations trg_product_catalog_foundationsTRIGGERCREATE TRIGGER trg_product_catalog_foundations AFTER INSERT ON public.foundations FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
DDROP TRIGGER trg_product_catalog_foundations ON public.foundations;
publicpostgresfalse293250262024187-highlighters trg_product_catalog_highlightersTRIGGERCREATE TRIGGER trg_product_catalog_highlighters AFTER INSERT ON public.highlighters FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
FDROP TRIGGER trg_product_catalog_highlighters ON public.highlighters;
publicpostgresfalse293240262024181'lipsticks trg_product_catalog_lipsticksTRIGGERCREATE TRIGGER trg_product_catalog_lipsticks AFTER INSERT ON public.lipsticks FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
@DROP TRIGGER trg_product_catalog_lipsticks ON public.lipsticks;
publicpostgresfalse293248262024189%products trg_product_catalog_productsTRIGGERCREATE TRIGGER trg_product_catalog_products AFTER INSERT ON public.products FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();
>DROP TRIGGER trg_product_catalog_products ON public.products;
publicpostgresfalse293222}260623424'cart_items cart_items_member_email_fkey
FK CONSTRAINTALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_member_email_fkey FOREIGN KEY (member_email) REFERENCES public.members(email);
QALTER TABLE ONLY public.cart_items DROP CONSTRAINT cart_items_member_email_fkey;
publicpostgresfalse5329276220|260623282cart cart_member_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.cart
    ADD CONSTRAINT cart_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON DELETE CASCADE;
BALTER TABLE ONLY public.cart DROP CONSTRAINT cart_member_id_fkey;
publicpostgresfalse2205331274q260621026 checkins checkins_member_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON UPDATE CASCADE ON DELETE RESTRICT;
JALTER TABLE ONLY public.checkins DROP CONSTRAINT checkins_member_id_fkey;
publicpostgresfalse2245331220260624140Jcrawler_staging_products crawler_staging_products_imported_product_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.crawler_staging_products
    ADD CONSTRAINT crawler_staging_products_imported_product_id_fkey FOREIGN KEY (imported_product_id) REFERENCES public.products(id);
tALTER TABLE ONLY public.crawler_staging_products DROP CONSTRAINT crawler_staging_products_imported_product_id_fkey;
publicpostgresfalse5333284222r260621045"favorites favorites_member_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON UPDATE CASCADE ON DELETE CASCADE;
LALTER TABLE ONLY public.favorites DROP CONSTRAINT favorites_member_id_fkey;
publicpostgresfalse2205331226v260623444*analysis_history fk_analysis_history_email
FK CONSTRAINTALTER TABLE ONLY public.analysis_history
    ADD CONSTRAINT fk_analysis_history_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;
TALTER TABLE ONLY public.analysis_history DROP CONSTRAINT fk_analysis_history_email;
publicpostgresfalse2202645329w260623429&daily_checkins fk_daily_checkins_email
FK CONSTRAINTALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT fk_daily_checkins_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;
PALTER TABLE ONLY public.daily_checkins DROP CONSTRAINT fk_daily_checkins_email;
publicpostgresfalse2202665329t2606234390points_transactions fk_points_transactions_email
FK CONSTRAINTALTER TABLE ONLY public.points_transactions
    ADD CONSTRAINT fk_points_transactions_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;
ZALTER TABLE ONLY public.points_transactions DROP CONSTRAINT fk_points_transactions_email;
publicpostgresfalse2562205329x260623434 task_claims fk_task_claims_email
FK CONSTRAINTALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT fk_task_claims_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;
JALTER TABLE ONLY public.task_claims DROP CONSTRAINT fk_task_claims_email;
publicpostgresfalse2685329220y260623449(unlocked_themes fk_unlocked_themes_email
FK CONSTRAINTALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT fk_unlocked_themes_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;
RALTER TABLE ONLY public.unlocked_themes DROP CONSTRAINT fk_unlocked_themes_email;
publicpostgresfalse5329220270~260623963.member_sessions member_sessions_member_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.member_sessions
    ADD CONSTRAINT member_sessions_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number);
XALTER TABLE ONLY public.member_sessions DROP CONSTRAINT member_sessions_member_id_fkey;
publicpostgresfalse5331280220z260623382$referrals referrals_referred_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_referred_id_fkey FOREIGN KEY (referred_email) REFERENCES public.members(phone_number) ON DELETE CASCADE;
NALTER TABLE ONLY public.referrals DROP CONSTRAINT referrals_referred_id_fkey;
publicpostgresfalse2205331272{260623375$referrals referrals_referrer_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_referrer_id_fkey FOREIGN KEY (referrer_email) REFERENCES public.members(phone_number) ON DELETE CASCADE;
NALTER TABLE ONLY public.referrals DROP CONSTRAINT referrals_referrer_id_fkey;
publicpostgresfalse2722205331u260623419)saved_looks saved_looks_member_email_fkey
FK CONSTRAINTALTER TABLE ONLY public.saved_looks
    ADD CONSTRAINT saved_looks_member_email_fkey FOREIGN KEY (member_email) REFERENCES public.members(email);
SALTER TABLE ONLY public.saved_looks DROP CONSTRAINT saved_looks_member_email_fkey;
publicpostgresfalse2605329220s260621087*tryon_records tryon_records_member_id_fkey
FK CONSTRAINTALTER TABLE ONLY public.tryon_records
    ADD CONSTRAINT tryon_records_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON UPDATE CASCADE ON DELETE CASCADE;
TALTER TABLE ONLY public.tryon_records DROP CONSTRAINT tryon_records_member_id_fkey;
publicpostgresfalse2205331232
