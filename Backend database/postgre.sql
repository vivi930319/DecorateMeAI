--
-- PostgreSQL database dump
--

\restrict TrXHqVbCLrvfMyAmLume9Wj1ZSpVBgEn4LQPkSn8IVf0wosLeJpq9CjiELF7T9C

-- Dumped from database version 18.4
-- Dumped by pg_dump version 18.4

-- Started on 2026-07-29 14:47:09

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- TOC entry 2 (class 3079 OID 24000)
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- TOC entry 5680 (class 0 OID 0)
-- Dependencies: 2
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner:
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- TOC entry 973 (class 1247 OID 16965)
-- Name: member_level; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.member_level AS ENUM (
    'bronze',
    'silver',
    'gold'
);


ALTER TYPE public.member_level OWNER TO postgres;

--
-- TOC entry 970 (class 1247 OID 20892)
-- Name: member_level_enum; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.member_level_enum AS ENUM (
    'bronze',
    'silver',
    'gold'
);


ALTER TYPE public.member_level_enum OWNER TO postgres;

--
-- TOC entry 320 (class 1255 OID 19859)
-- Name: daily_member_stats(); Type: PROCEDURE; Schema: public; Owner: postgres
--

CREATE PROCEDURE public.daily_member_stats()
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO member_level_history(member_id, old_level, new_level)
    SELECT phone_number, level::VARCHAR, level::VARCHAR FROM members;
END;
$$;


ALTER PROCEDURE public.daily_member_stats() OWNER TO postgres;

--
-- TOC entry 348 (class 1255 OID 23819)
-- Name: enforce_product_contract(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.enforce_product_contract() RETURNS trigger
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


ALTER FUNCTION public.enforce_product_contract() OWNER TO postgres;

--
-- TOC entry 309 (class 1255 OID 19854)
-- Name: fn_member_checkin_count(character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_member_checkin_count(p_member character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM checkins WHERE member_id = p_member;
    RETURN total;
END;
$$;


ALTER FUNCTION public.fn_member_checkin_count(p_member character varying) OWNER TO postgres;

--
-- TOC entry 321 (class 1255 OID 19860)
-- Name: fn_member_favorite_count(character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.fn_member_favorite_count(p_member character varying) RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE total INT;
BEGIN
    SELECT COUNT(*) INTO total FROM favorites WHERE member_id = p_member;
    RETURN total;
END;
$$;


ALTER FUNCTION public.fn_member_favorite_count(p_member character varying) OWNER TO postgres;

--
-- TOC entry 306 (class 1255 OID 19846)
-- Name: func_auto_upgrade_level(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.func_auto_upgrade_level() RETURNS trigger
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


ALTER FUNCTION public.func_auto_upgrade_level() OWNER TO postgres;

--
-- TOC entry 305 (class 1255 OID 19848)
-- Name: func_before_favorite_insert(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.func_before_favorite_insert() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM favorites WHERE member_id = NEW.member_id AND item_id = NEW.item_id AND item_type = NEW.item_type) THEN
        RAISE EXCEPTION 'Error: This item is already in favorites!';
    END IF;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.func_before_favorite_insert() OWNER TO postgres;

--
-- TOC entry 308 (class 1255 OID 19852)
-- Name: func_member_level_history(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.func_member_level_history() RETURNS trigger
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


ALTER FUNCTION public.func_member_level_history() OWNER TO postgres;

--
-- TOC entry 307 (class 1255 OID 19850)
-- Name: func_prevent_multiple_checkin(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.func_prevent_multiple_checkin() RETURNS trigger
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


ALTER FUNCTION public.func_prevent_multiple_checkin() OWNER TO postgres;

--
-- TOC entry 347 (class 1255 OID 23818)
-- Name: product_hex_to_lab(text); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.product_hex_to_lab(h text) RETURNS jsonb
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


ALTER FUNCTION public.product_hex_to_lab(h text) OWNER TO postgres;

--
-- TOC entry 293 (class 1255 OID 24180)
-- Name: register_product_catalog_item(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.register_product_catalog_item() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO public.product_catalog (product_type, source_id)
    VALUES (TG_TABLE_NAME, NEW.id)
    ON CONFLICT (product_type, source_id) DO NOTHING;
    RETURN NEW;
END;
$$;


ALTER FUNCTION public.register_product_catalog_item() OWNER TO postgres;

--
-- TOC entry 310 (class 1255 OID 19855)
-- Name: sp_add_favorite(character varying, integer, character varying); Type: PROCEDURE; Schema: public; Owner: postgres
--

CREATE PROCEDURE public.sp_add_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying)
    LANGUAGE plpgsql
    AS $$
BEGIN
    INSERT INTO favorites(member_id, item_id, item_type) VALUES(p_member, p_item, p_type);
END;
$$;


ALTER PROCEDURE public.sp_add_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying) OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- TOC entry 222 (class 1259 OID 20913)
-- Name: products; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.products (
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


ALTER TABLE public.products OWNER TO postgres;

--
-- TOC entry 319 (class 1255 OID 21115)
-- Name: sp_get_top_products(); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.sp_get_top_products() RETURNS SETOF public.products
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY SELECT * FROM products ORDER BY favorite_count DESC LIMIT 10;
END;
$$;


ALTER FUNCTION public.sp_get_top_products() OWNER TO postgres;

--
-- TOC entry 346 (class 1255 OID 19858)
-- Name: sp_member_favorites(character varying); Type: FUNCTION; Schema: public; Owner: postgres
--

CREATE FUNCTION public.sp_member_favorites(p_member character varying) RETURNS TABLE(id integer, category character varying, name character varying, price numeric, description text, image_url character varying)
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


ALTER FUNCTION public.sp_member_favorites(p_member character varying) OWNER TO postgres;

--
-- TOC entry 318 (class 1255 OID 19856)
-- Name: sp_remove_favorite(character varying, integer, character varying); Type: PROCEDURE; Schema: public; Owner: postgres
--

CREATE PROCEDURE public.sp_remove_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying)
    LANGUAGE plpgsql
    AS $$
BEGIN
    DELETE FROM favorites WHERE member_id = p_member AND item_id = p_item AND item_type = p_type;
END;
$$;


ALTER PROCEDURE public.sp_remove_favorite(IN p_member character varying, IN p_item integer, IN p_type character varying) OWNER TO postgres;

--
-- TOC entry 277 (class 1259 OID 23551)
-- Name: admin_audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.admin_audit_logs (
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


ALTER TABLE public.admin_audit_logs OWNER TO postgres;

--
-- TOC entry 264 (class 1259 OID 23176)
-- Name: analysis_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.analysis_history (
    id bigint NOT NULL,
    member_email character varying(191),
    mode character varying(10),
    result jsonb,
    analysis_package_id character varying(64),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.analysis_history OWNER TO postgres;

--
-- TOC entry 263 (class 1259 OID 23175)
-- Name: analysis_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.analysis_history_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.analysis_history_id_seq OWNER TO postgres;

--
-- TOC entry 5681 (class 0 OID 0)
-- Dependencies: 263
-- Name: analysis_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.analysis_history_id_seq OWNED BY public.analysis_history.id;


--
-- TOC entry 258 (class 1259 OID 23116)
-- Name: audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.audit_logs (
    id integer NOT NULL,
    actor_email character varying(100) NOT NULL,
    target_email character varying(100) NOT NULL,
    action character varying(50) NOT NULL,
    field_name character varying(50),
    before_value character varying(255),
    after_value character varying(255),
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.audit_logs OWNER TO postgres;

--
-- TOC entry 257 (class 1259 OID 23115)
-- Name: audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.audit_logs_id_seq OWNER TO postgres;

--
-- TOC entry 5682 (class 0 OID 0)
-- Dependencies: 257
-- Name: audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.audit_logs_id_seq OWNED BY public.audit_logs.id;


--
-- TOC entry 236 (class 1259 OID 21388)
-- Name: blushes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.blushes (
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


ALTER TABLE public.blushes OWNER TO postgres;

--
-- TOC entry 235 (class 1259 OID 21387)
-- Name: blushes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.blushes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.blushes_id_seq OWNER TO postgres;

--
-- TOC entry 5683 (class 0 OID 0)
-- Dependencies: 235
-- Name: blushes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.blushes_id_seq OWNED BY public.blushes.id;


--
-- TOC entry 274 (class 1259 OID 23268)
-- Name: cart; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cart (
    id bigint NOT NULL,
    member_id character varying(20),
    item_id bigint NOT NULL,
    qty integer DEFAULT 1 NOT NULL,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT cart_qty_check CHECK ((qty >= 1))
);


ALTER TABLE public.cart OWNER TO postgres;

--
-- TOC entry 273 (class 1259 OID 23267)
-- Name: cart_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.cart_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.cart_id_seq OWNER TO postgres;

--
-- TOC entry 5684 (class 0 OID 0)
-- Dependencies: 273
-- Name: cart_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.cart_id_seq OWNED BY public.cart.id;


--
-- TOC entry 276 (class 1259 OID 23289)
-- Name: cart_items; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.cart_items (
    id integer NOT NULL,
    member_email character varying(100) NOT NULL,
    item_id integer NOT NULL,
    qty integer NOT NULL,
    updated_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.cart_items OWNER TO postgres;

--
-- TOC entry 275 (class 1259 OID 23288)
-- Name: cart_items_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.cart_items_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.cart_items_id_seq OWNER TO postgres;

--
-- TOC entry 5685 (class 0 OID 0)
-- Dependencies: 275
-- Name: cart_items_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.cart_items_id_seq OWNED BY public.cart_items.id;


--
-- TOC entry 224 (class 1259 OID 21015)
-- Name: checkins; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.checkins (
    id integer NOT NULL,
    member_id character varying(20) NOT NULL,
    checkin_time timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    note text
);


ALTER TABLE public.checkins OWNER TO postgres;

--
-- TOC entry 223 (class 1259 OID 21014)
-- Name: checkins_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.checkins_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.checkins_id_seq OWNER TO postgres;

--
-- TOC entry 5686 (class 0 OID 0)
-- Dependencies: 223
-- Name: checkins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.checkins_id_seq OWNED BY public.checkins.id;


--
-- TOC entry 228 (class 1259 OID 21051)
-- Name: color_palettes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.color_palettes (
    id integer NOT NULL,
    title character varying(100),
    hex_code character varying(7) NOT NULL,
    source_url character varying(255),
    tags character varying(100),
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.color_palettes OWNER TO postgres;

--
-- TOC entry 227 (class 1259 OID 21050)
-- Name: color_palettes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.color_palettes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.color_palettes_id_seq OWNER TO postgres;

--
-- TOC entry 5687 (class 0 OID 0)
-- Dependencies: 227
-- Name: color_palettes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.color_palettes_id_seq OWNED BY public.color_palettes.id;


--
-- TOC entry 246 (class 1259 OID 22602)
-- Name: contouring; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.contouring (
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


ALTER TABLE public.contouring OWNER TO postgres;

--
-- TOC entry 245 (class 1259 OID 22601)
-- Name: contouring_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.contouring_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.contouring_id_seq OWNER TO postgres;

--
-- TOC entry 5688 (class 0 OID 0)
-- Dependencies: 245
-- Name: contouring_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.contouring_id_seq OWNED BY public.contouring.id;


--
-- TOC entry 284 (class 1259 OID 24119)
-- Name: crawler_staging_products; Type: TABLE; Schema: public; Owner: postgres
--

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


ALTER TABLE public.crawler_staging_products OWNER TO postgres;

--
-- TOC entry 5689 (class 0 OID 0)
-- Dependencies: 284
-- Name: TABLE crawler_staging_products; Type: COMMENT; Schema: public; Owner: postgres
--

COMMENT ON TABLE public.crawler_staging_products IS 'Crawler-only staging area. Backend review/import is required before formal products are changed.';


--
-- TOC entry 283 (class 1259 OID 24118)
-- Name: crawler_staging_products_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.crawler_staging_products ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.crawler_staging_products_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 266 (class 1259 OID 23192)
-- Name: daily_checkins; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.daily_checkins (
    id bigint NOT NULL,
    member_email character varying(191),
    checkin_date date NOT NULL,
    streak integer DEFAULT 1,
    awarded integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    idempotency_key character varying(128)
);


ALTER TABLE public.daily_checkins OWNER TO postgres;

--
-- TOC entry 265 (class 1259 OID 23191)
-- Name: daily_checkins_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.daily_checkins_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.daily_checkins_id_seq OWNER TO postgres;

--
-- TOC entry 5692 (class 0 OID 0)
-- Dependencies: 265
-- Name: daily_checkins_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.daily_checkins_id_seq OWNED BY public.daily_checkins.id;


--
-- TOC entry 238 (class 1259 OID 21403)
-- Name: eyebrows; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.eyebrows (
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


ALTER TABLE public.eyebrows OWNER TO postgres;

--
-- TOC entry 237 (class 1259 OID 21402)
-- Name: eyebrows_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.eyebrows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.eyebrows_id_seq OWNER TO postgres;

--
-- TOC entry 5693 (class 0 OID 0)
-- Dependencies: 237
-- Name: eyebrows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.eyebrows_id_seq OWNED BY public.eyebrows.id;


--
-- TOC entry 244 (class 1259 OID 22465)
-- Name: eyeliner_mascara; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.eyeliner_mascara (
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


ALTER TABLE public.eyeliner_mascara OWNER TO postgres;

--
-- TOC entry 243 (class 1259 OID 22464)
-- Name: eyeliner_mascara_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.eyeliner_mascara_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.eyeliner_mascara_id_seq OWNER TO postgres;

--
-- TOC entry 5694 (class 0 OID 0)
-- Dependencies: 243
-- Name: eyeliner_mascara_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.eyeliner_mascara_id_seq OWNED BY public.eyeliner_mascara.id;


--
-- TOC entry 242 (class 1259 OID 22389)
-- Name: eyeshadows; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.eyeshadows (
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


ALTER TABLE public.eyeshadows OWNER TO postgres;

--
-- TOC entry 241 (class 1259 OID 22388)
-- Name: eyeshadows_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.eyeshadows_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.eyeshadows_id_seq OWNER TO postgres;

--
-- TOC entry 5695 (class 0 OID 0)
-- Dependencies: 241
-- Name: eyeshadows_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.eyeshadows_id_seq OWNED BY public.eyeshadows.id;


--
-- TOC entry 226 (class 1259 OID 21032)
-- Name: favorites; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.favorites (
    id integer NOT NULL,
    member_id character varying(20) NOT NULL,
    item_id integer NOT NULL,
    item_type character varying(50) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.favorites OWNER TO postgres;

--
-- TOC entry 225 (class 1259 OID 21031)
-- Name: favorites_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.favorites_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.favorites_id_seq OWNER TO postgres;

--
-- TOC entry 5696 (class 0 OID 0)
-- Dependencies: 225
-- Name: favorites_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.favorites_id_seq OWNED BY public.favorites.id;


--
-- TOC entry 250 (class 1259 OID 22830)
-- Name: foundations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.foundations (
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
    deleted_at timestamp with time zone
);


ALTER TABLE public.foundations OWNER TO postgres;

--
-- TOC entry 249 (class 1259 OID 22829)
-- Name: foundations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.foundations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.foundations_id_seq OWNER TO postgres;

--
-- TOC entry 5697 (class 0 OID 0)
-- Dependencies: 249
-- Name: foundations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.foundations_id_seq OWNED BY public.foundations.id;


--
-- TOC entry 240 (class 1259 OID 21418)
-- Name: highlighters; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.highlighters (
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


ALTER TABLE public.highlighters OWNER TO postgres;

--
-- TOC entry 239 (class 1259 OID 21417)
-- Name: highlighters_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.highlighters_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.highlighters_id_seq OWNER TO postgres;

--
-- TOC entry 5698 (class 0 OID 0)
-- Dependencies: 239
-- Name: highlighters_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.highlighters_id_seq OWNED BY public.highlighters.id;


--
-- TOC entry 248 (class 1259 OID 22817)
-- Name: lipsticks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.lipsticks (
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


ALTER TABLE public.lipsticks OWNER TO postgres;

--
-- TOC entry 247 (class 1259 OID 22816)
-- Name: lipsticks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.lipsticks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.lipsticks_id_seq OWNER TO postgres;

--
-- TOC entry 5699 (class 0 OID 0)
-- Dependencies: 247
-- Name: lipsticks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.lipsticks_id_seq OWNED BY public.lipsticks.id;


--
-- TOC entry 254 (class 1259 OID 23082)
-- Name: member_audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.member_audit_logs (
    id integer NOT NULL,
    actor_email character varying(100) NOT NULL,
    target_email character varying(100) NOT NULL,
    action character varying(50) NOT NULL,
    before_value jsonb,
    after_value jsonb,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.member_audit_logs OWNER TO postgres;

--
-- TOC entry 253 (class 1259 OID 23081)
-- Name: member_audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.member_audit_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.member_audit_logs_id_seq OWNER TO postgres;

--
-- TOC entry 5700 (class 0 OID 0)
-- Dependencies: 253
-- Name: member_audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.member_audit_logs_id_seq OWNED BY public.member_audit_logs.id;


--
-- TOC entry 281 (class 1259 OID 24047)
-- Name: member_deletion_jobs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.member_deletion_jobs (
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


ALTER TABLE public.member_deletion_jobs OWNER TO postgres;

--
-- TOC entry 230 (class 1259 OID 21063)
-- Name: member_level_history; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.member_level_history (
    id integer NOT NULL,
    member_id character varying(20),
    old_level character varying(20),
    new_level character varying(20),
    changed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.member_level_history OWNER TO postgres;

--
-- TOC entry 229 (class 1259 OID 21062)
-- Name: member_level_history_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.member_level_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.member_level_history_id_seq OWNER TO postgres;

--
-- TOC entry 5701 (class 0 OID 0)
-- Dependencies: 229
-- Name: member_level_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.member_level_history_id_seq OWNED BY public.member_level_history.id;


--
-- TOC entry 280 (class 1259 OID 23954)
-- Name: member_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.member_sessions (
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


ALTER TABLE public.member_sessions OWNER TO postgres;

--
-- TOC entry 220 (class 1259 OID 20899)
-- Name: members; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.members (
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


ALTER TABLE public.members OWNER TO postgres;

--
-- TOC entry 262 (class 1259 OID 23163)
-- Name: otp_codes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.otp_codes (
    id bigint NOT NULL,
    email character varying(191) NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    attempts integer DEFAULT 0,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    code_hash character varying(255) NOT NULL,
    purpose character varying(40) DEFAULT 'email_verification'::character varying NOT NULL,
    verified_at timestamp without time zone
);


ALTER TABLE public.otp_codes OWNER TO postgres;

--
-- TOC entry 261 (class 1259 OID 23162)
-- Name: otp_codes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.otp_codes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.otp_codes_id_seq OWNER TO postgres;

--
-- TOC entry 5702 (class 0 OID 0)
-- Dependencies: 261
-- Name: otp_codes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.otp_codes_id_seq OWNED BY public.otp_codes.id;


--
-- TOC entry 282 (class 1259 OID 24102)
-- Name: pending_registrations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.pending_registrations (
    email character varying(100) NOT NULL,
    phone_number character varying(20) NOT NULL,
    name character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    age integer NOT NULL,
    expires_at timestamp without time zone NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.pending_registrations OWNER TO postgres;

--
-- TOC entry 256 (class 1259 OID 23096)
-- Name: points_transactions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.points_transactions (
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


ALTER TABLE public.points_transactions OWNER TO postgres;

--
-- TOC entry 255 (class 1259 OID 23095)
-- Name: points_transactions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.points_transactions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.points_transactions_id_seq OWNER TO postgres;

--
-- TOC entry 5703 (class 0 OID 0)
-- Dependencies: 255
-- Name: points_transactions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.points_transactions_id_seq OWNED BY public.points_transactions.id;


--
-- TOC entry 279 (class 1259 OID 23602)
-- Name: product_audit_logs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.product_audit_logs (
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


ALTER TABLE public.product_audit_logs OWNER TO postgres;

--
-- TOC entry 278 (class 1259 OID 23601)
-- Name: product_audit_logs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.product_audit_logs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.product_audit_logs_id_seq OWNER TO postgres;

--
-- TOC entry 5704 (class 0 OID 0)
-- Dependencies: 278
-- Name: product_audit_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.product_audit_logs_id_seq OWNED BY public.product_audit_logs.id;


--
-- TOC entry 286 (class 1259 OID 24168)
-- Name: product_catalog; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.product_catalog (
    id bigint NOT NULL,
    product_type character varying(40) NOT NULL,
    source_id integer NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP NOT NULL
);


ALTER TABLE public.product_catalog OWNER TO postgres;

--
-- TOC entry 285 (class 1259 OID 24167)
-- Name: product_catalog_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

ALTER TABLE public.product_catalog ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.product_catalog_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- TOC entry 221 (class 1259 OID 20912)
-- Name: products_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.products_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.products_id_seq OWNER TO postgres;

--
-- TOC entry 5705 (class 0 OID 0)
-- Dependencies: 221
-- Name: products_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.products_id_seq OWNED BY public.products.id;


--
-- TOC entry 272 (class 1259 OID 23246)
-- Name: referrals; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.referrals (
    id bigint NOT NULL,
    referrer_email character varying(191),
    referred_email character varying(191),
    points_awarded integer DEFAULT 20,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


ALTER TABLE public.referrals OWNER TO postgres;

--
-- TOC entry 271 (class 1259 OID 23245)
-- Name: referrals_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.referrals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.referrals_id_seq OWNER TO postgres;

--
-- TOC entry 5706 (class 0 OID 0)
-- Dependencies: 271
-- Name: referrals_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.referrals_id_seq OWNED BY public.referrals.id;


--
-- TOC entry 260 (class 1259 OID 23130)
-- Name: saved_looks; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.saved_looks (
    id integer NOT NULL,
    member_email character varying(100) NOT NULL,
    style character varying(120) NOT NULL,
    before_image_url text NOT NULL,
    after_image_url text NOT NULL,
    analysis_summary jsonb,
    created_at timestamp without time zone DEFAULT now()
);


ALTER TABLE public.saved_looks OWNER TO postgres;

--
-- TOC entry 259 (class 1259 OID 23129)
-- Name: saved_looks_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.saved_looks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.saved_looks_id_seq OWNER TO postgres;

--
-- TOC entry 5707 (class 0 OID 0)
-- Dependencies: 259
-- Name: saved_looks_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.saved_looks_id_seq OWNED BY public.saved_looks.id;


--
-- TOC entry 268 (class 1259 OID 23211)
-- Name: task_claims; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.task_claims (
    id bigint NOT NULL,
    member_email character varying(191),
    task_id character varying(40) NOT NULL,
    claimed_date date DEFAULT CURRENT_DATE,
    claimed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    claim_date date NOT NULL,
    idempotency_key character varying(128)
);


ALTER TABLE public.task_claims OWNER TO postgres;

--
-- TOC entry 267 (class 1259 OID 23210)
-- Name: task_claims_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.task_claims_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.task_claims_id_seq OWNER TO postgres;

--
-- TOC entry 5708 (class 0 OID 0)
-- Dependencies: 267
-- Name: task_claims_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.task_claims_id_seq OWNED BY public.task_claims.id;


--
-- TOC entry 232 (class 1259 OID 21072)
-- Name: tryon_records; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.tryon_records (
    id integer NOT NULL,
    member_id character varying(20) NOT NULL,
    item_id integer NOT NULL,
    item_type character varying(50) NOT NULL,
    original_image_url character varying(500) NOT NULL,
    generated_image_url character varying(500) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    makeup_advice text
);


ALTER TABLE public.tryon_records OWNER TO postgres;

--
-- TOC entry 231 (class 1259 OID 21071)
-- Name: tryon_records_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.tryon_records_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.tryon_records_id_seq OWNER TO postgres;

--
-- TOC entry 5709 (class 0 OID 0)
-- Dependencies: 231
-- Name: tryon_records_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.tryon_records_id_seq OWNED BY public.tryon_records.id;


--
-- TOC entry 270 (class 1259 OID 23229)
-- Name: unlocked_themes; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.unlocked_themes (
    id bigint NOT NULL,
    member_email character varying(191),
    theme_id character varying(20) NOT NULL,
    unlocked_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    idempotency_key character varying(128)
);


ALTER TABLE public.unlocked_themes OWNER TO postgres;

--
-- TOC entry 269 (class 1259 OID 23228)
-- Name: unlocked_themes_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.unlocked_themes_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.unlocked_themes_id_seq OWNER TO postgres;

--
-- TOC entry 5710 (class 0 OID 0)
-- Dependencies: 269
-- Name: unlocked_themes_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.unlocked_themes_id_seq OWNED BY public.unlocked_themes.id;


--
-- TOC entry 251 (class 1259 OID 23071)
-- Name: view_member_activity; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.view_member_activity AS
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


ALTER VIEW public.view_member_activity OWNER TO postgres;

--
-- TOC entry 252 (class 1259 OID 23076)
-- Name: view_member_dashboard; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.view_member_dashboard AS
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


ALTER VIEW public.view_member_dashboard OWNER TO postgres;

--
-- TOC entry 234 (class 1259 OID 21107)
-- Name: view_product_list; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.view_product_list AS
 SELECT id,
    name,
    ('NT$'::text || to_char(price, 'FM999,999,999'::text)) AS formatted_price,
    description
   FROM public.products;


ALTER VIEW public.view_product_list OWNER TO postgres;

--
-- TOC entry 233 (class 1259 OID 21097)
-- Name: view_product_popularity; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.view_product_popularity AS
 SELECT p.id,
    p.name,
    p.price,
    count(f.id) AS favorite_count,
    ((count(f.id))::numeric * p.price) AS popularity_score
   FROM (public.products p
     LEFT JOIN public.favorites f ON (((p.id = f.item_id) AND ((f.item_type)::text = 'products'::text))))
  GROUP BY p.id, p.name, p.price
  ORDER BY (count(f.id)) DESC;


ALTER VIEW public.view_product_popularity OWNER TO postgres;

--
-- TOC entry 5277 (class 2604 OID 23179)
-- Name: analysis_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.analysis_history ALTER COLUMN id SET DEFAULT nextval('public.analysis_history_id_seq'::regclass);


--
-- TOC entry 5269 (class 2604 OID 23119)
-- Name: audit_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_logs ALTER COLUMN id SET DEFAULT nextval('public.audit_logs_id_seq'::regclass);


--
-- TOC entry 5121 (class 2604 OID 21391)
-- Name: blushes id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.blushes ALTER COLUMN id SET DEFAULT nextval('public.blushes_id_seq'::regclass);


--
-- TOC entry 5291 (class 2604 OID 23271)
-- Name: cart id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart ALTER COLUMN id SET DEFAULT nextval('public.cart_id_seq'::regclass);


--
-- TOC entry 5294 (class 2604 OID 23292)
-- Name: cart_items id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_items ALTER COLUMN id SET DEFAULT nextval('public.cart_items_id_seq'::regclass);


--
-- TOC entry 5111 (class 2604 OID 21018)
-- Name: checkins id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkins ALTER COLUMN id SET DEFAULT nextval('public.checkins_id_seq'::regclass);


--
-- TOC entry 5115 (class 2604 OID 21054)
-- Name: color_palettes id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.color_palettes ALTER COLUMN id SET DEFAULT nextval('public.color_palettes_id_seq'::regclass);


--
-- TOC entry 5211 (class 2604 OID 22605)
-- Name: contouring id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contouring ALTER COLUMN id SET DEFAULT nextval('public.contouring_id_seq'::regclass);


--
-- TOC entry 5279 (class 2604 OID 23195)
-- Name: daily_checkins id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_checkins ALTER COLUMN id SET DEFAULT nextval('public.daily_checkins_id_seq'::regclass);


--
-- TOC entry 5139 (class 2604 OID 21406)
-- Name: eyebrows id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyebrows ALTER COLUMN id SET DEFAULT nextval('public.eyebrows_id_seq'::regclass);


--
-- TOC entry 5193 (class 2604 OID 22468)
-- Name: eyeliner_mascara id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyeliner_mascara ALTER COLUMN id SET DEFAULT nextval('public.eyeliner_mascara_id_seq'::regclass);


--
-- TOC entry 5175 (class 2604 OID 22392)
-- Name: eyeshadows id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyeshadows ALTER COLUMN id SET DEFAULT nextval('public.eyeshadows_id_seq'::regclass);


--
-- TOC entry 5113 (class 2604 OID 21035)
-- Name: favorites id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.favorites ALTER COLUMN id SET DEFAULT nextval('public.favorites_id_seq'::regclass);


--
-- TOC entry 5246 (class 2604 OID 22833)
-- Name: foundations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.foundations ALTER COLUMN id SET DEFAULT nextval('public.foundations_id_seq'::regclass);


--
-- TOC entry 5157 (class 2604 OID 21421)
-- Name: highlighters id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.highlighters ALTER COLUMN id SET DEFAULT nextval('public.highlighters_id_seq'::regclass);


--
-- TOC entry 5229 (class 2604 OID 22820)
-- Name: lipsticks id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.lipsticks ALTER COLUMN id SET DEFAULT nextval('public.lipsticks_id_seq'::regclass);


--
-- TOC entry 5265 (class 2604 OID 23085)
-- Name: member_audit_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_audit_logs ALTER COLUMN id SET DEFAULT nextval('public.member_audit_logs_id_seq'::regclass);


--
-- TOC entry 5117 (class 2604 OID 21066)
-- Name: member_level_history id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_level_history ALTER COLUMN id SET DEFAULT nextval('public.member_level_history_id_seq'::regclass);


--
-- TOC entry 5273 (class 2604 OID 23166)
-- Name: otp_codes id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.otp_codes ALTER COLUMN id SET DEFAULT nextval('public.otp_codes_id_seq'::regclass);


--
-- TOC entry 5267 (class 2604 OID 23099)
-- Name: points_transactions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.points_transactions ALTER COLUMN id SET DEFAULT nextval('public.points_transactions_id_seq'::regclass);


--
-- TOC entry 5297 (class 2604 OID 23605)
-- Name: product_audit_logs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.product_audit_logs ALTER COLUMN id SET DEFAULT nextval('public.product_audit_logs_id_seq'::regclass);


--
-- TOC entry 5108 (class 2604 OID 20916)
-- Name: products id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products ALTER COLUMN id SET DEFAULT nextval('public.products_id_seq'::regclass);


--
-- TOC entry 5288 (class 2604 OID 23249)
-- Name: referrals id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referrals ALTER COLUMN id SET DEFAULT nextval('public.referrals_id_seq'::regclass);


--
-- TOC entry 5271 (class 2604 OID 23133)
-- Name: saved_looks id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.saved_looks ALTER COLUMN id SET DEFAULT nextval('public.saved_looks_id_seq'::regclass);


--
-- TOC entry 5283 (class 2604 OID 23214)
-- Name: task_claims id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_claims ALTER COLUMN id SET DEFAULT nextval('public.task_claims_id_seq'::regclass);


--
-- TOC entry 5119 (class 2604 OID 21075)
-- Name: tryon_records id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tryon_records ALTER COLUMN id SET DEFAULT nextval('public.tryon_records_id_seq'::regclass);


--
-- TOC entry 5286 (class 2604 OID 23232)
-- Name: unlocked_themes id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unlocked_themes ALTER COLUMN id SET DEFAULT nextval('public.unlocked_themes_id_seq'::regclass);


--
-- TOC entry 5449 (class 2606 OID 23564)
-- Name: admin_audit_logs admin_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_audit_logs
    ADD CONSTRAINT admin_audit_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 5451 (class 2606 OID 23566)
-- Name: admin_audit_logs admin_audit_logs_request_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.admin_audit_logs
    ADD CONSTRAINT admin_audit_logs_request_id_key UNIQUE (request_id);


--
-- TOC entry 5414 (class 2606 OID 23185)
-- Name: analysis_history analysis_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.analysis_history
    ADD CONSTRAINT analysis_history_pkey PRIMARY KEY (id);


--
-- TOC entry 5404 (class 2606 OID 23128)
-- Name: audit_logs audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.audit_logs
    ADD CONSTRAINT audit_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 5348 (class 2606 OID 21398)
-- Name: blushes blushes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.blushes
    ADD CONSTRAINT blushes_pkey PRIMARY KEY (id);


--
-- TOC entry 5350 (class 2606 OID 21400)
-- Name: blushes blushes_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.blushes
    ADD CONSTRAINT blushes_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5445 (class 2606 OID 23299)
-- Name: cart_items cart_items_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_pkey PRIMARY KEY (id);


--
-- TOC entry 5441 (class 2606 OID 23279)
-- Name: cart cart_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart
    ADD CONSTRAINT cart_pkey PRIMARY KEY (id);


--
-- TOC entry 5334 (class 2606 OID 21025)
-- Name: checkins checkins_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_pkey PRIMARY KEY (id);


--
-- TOC entry 5340 (class 2606 OID 21061)
-- Name: color_palettes color_palettes_hex_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.color_palettes
    ADD CONSTRAINT color_palettes_hex_code_key UNIQUE (hex_code);


--
-- TOC entry 5342 (class 2606 OID 21059)
-- Name: color_palettes color_palettes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.color_palettes
    ADD CONSTRAINT color_palettes_pkey PRIMARY KEY (id);


--
-- TOC entry 5378 (class 2606 OID 22612)
-- Name: contouring contouring_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contouring
    ADD CONSTRAINT contouring_pkey PRIMARY KEY (id);


--
-- TOC entry 5380 (class 2606 OID 22614)
-- Name: contouring contouring_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.contouring
    ADD CONSTRAINT contouring_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5477 (class 2606 OID 24137)
-- Name: crawler_staging_products crawler_staging_products_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crawler_staging_products
    ADD CONSTRAINT crawler_staging_products_pkey PRIMARY KEY (id);


--
-- TOC entry 5416 (class 2606 OID 24075)
-- Name: daily_checkins daily_checkins_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT daily_checkins_idempotency_key_key UNIQUE (idempotency_key);


--
-- TOC entry 5418 (class 2606 OID 23202)
-- Name: daily_checkins daily_checkins_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT daily_checkins_pkey PRIMARY KEY (id);


--
-- TOC entry 5354 (class 2606 OID 21413)
-- Name: eyebrows eyebrows_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyebrows
    ADD CONSTRAINT eyebrows_pkey PRIMARY KEY (id);


--
-- TOC entry 5356 (class 2606 OID 21415)
-- Name: eyebrows eyebrows_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyebrows
    ADD CONSTRAINT eyebrows_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5372 (class 2606 OID 22475)
-- Name: eyeliner_mascara eyeliner_mascara_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyeliner_mascara
    ADD CONSTRAINT eyeliner_mascara_pkey PRIMARY KEY (id);


--
-- TOC entry 5374 (class 2606 OID 22477)
-- Name: eyeliner_mascara eyeliner_mascara_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyeliner_mascara
    ADD CONSTRAINT eyeliner_mascara_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5366 (class 2606 OID 22399)
-- Name: eyeshadows eyeshadows_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyeshadows
    ADD CONSTRAINT eyeshadows_pkey PRIMARY KEY (id);


--
-- TOC entry 5368 (class 2606 OID 22401)
-- Name: eyeshadows eyeshadows_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.eyeshadows
    ADD CONSTRAINT eyeshadows_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5336 (class 2606 OID 21042)
-- Name: favorites favorites_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_pkey PRIMARY KEY (id);


--
-- TOC entry 5389 (class 2606 OID 22841)
-- Name: foundations foundations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.foundations
    ADD CONSTRAINT foundations_pkey PRIMARY KEY (id);


--
-- TOC entry 5391 (class 2606 OID 22843)
-- Name: foundations foundations_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.foundations
    ADD CONSTRAINT foundations_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5360 (class 2606 OID 21428)
-- Name: highlighters highlighters_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.highlighters
    ADD CONSTRAINT highlighters_pkey PRIMARY KEY (id);


--
-- TOC entry 5362 (class 2606 OID 21430)
-- Name: highlighters highlighters_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.highlighters
    ADD CONSTRAINT highlighters_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5385 (class 2606 OID 22826)
-- Name: lipsticks lipsticks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.lipsticks
    ADD CONSTRAINT lipsticks_pkey PRIMARY KEY (id);


--
-- TOC entry 5387 (class 2606 OID 22828)
-- Name: lipsticks lipsticks_sale_page_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.lipsticks
    ADD CONSTRAINT lipsticks_sale_page_id_key UNIQUE (sale_page_id);


--
-- TOC entry 5396 (class 2606 OID 23094)
-- Name: member_audit_logs member_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_audit_logs
    ADD CONSTRAINT member_audit_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 5465 (class 2606 OID 24067)
-- Name: member_deletion_jobs member_deletion_jobs_member_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_deletion_jobs
    ADD CONSTRAINT member_deletion_jobs_member_email_key UNIQUE (member_email);


--
-- TOC entry 5467 (class 2606 OID 24063)
-- Name: member_deletion_jobs member_deletion_jobs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_deletion_jobs
    ADD CONSTRAINT member_deletion_jobs_pkey PRIMARY KEY (id);


--
-- TOC entry 5469 (class 2606 OID 24065)
-- Name: member_deletion_jobs member_deletion_jobs_request_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_deletion_jobs
    ADD CONSTRAINT member_deletion_jobs_request_id_key UNIQUE (request_id);


--
-- TOC entry 5344 (class 2606 OID 21070)
-- Name: member_level_history member_level_history_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_level_history
    ADD CONSTRAINT member_level_history_pkey PRIMARY KEY (id);


--
-- TOC entry 5461 (class 2606 OID 23962)
-- Name: member_sessions member_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_sessions
    ADD CONSTRAINT member_sessions_pkey PRIMARY KEY (session_hash);


--
-- TOC entry 5463 (class 2606 OID 24070)
-- Name: member_sessions member_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_sessions
    ADD CONSTRAINT member_sessions_session_id_key UNIQUE (session_id);


--
-- TOC entry 5328 (class 2606 OID 23417)
-- Name: members members_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_email_key UNIQUE (email);


--
-- TOC entry 5330 (class 2606 OID 20909)
-- Name: members members_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.members
    ADD CONSTRAINT members_pkey PRIMARY KEY (phone_number);


--
-- TOC entry 5412 (class 2606 OID 23174)
-- Name: otp_codes otp_codes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.otp_codes
    ADD CONSTRAINT otp_codes_pkey PRIMARY KEY (id);


--
-- TOC entry 5472 (class 2606 OID 24116)
-- Name: pending_registrations pending_registrations_phone_number_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pending_registrations
    ADD CONSTRAINT pending_registrations_phone_number_key UNIQUE (phone_number);


--
-- TOC entry 5474 (class 2606 OID 24114)
-- Name: pending_registrations pending_registrations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.pending_registrations
    ADD CONSTRAINT pending_registrations_pkey PRIMARY KEY (email);


--
-- TOC entry 5400 (class 2606 OID 24073)
-- Name: points_transactions points_transactions_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.points_transactions
    ADD CONSTRAINT points_transactions_idempotency_key_key UNIQUE (idempotency_key);


--
-- TOC entry 5402 (class 2606 OID 23109)
-- Name: points_transactions points_transactions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.points_transactions
    ADD CONSTRAINT points_transactions_pkey PRIMARY KEY (id);


--
-- TOC entry 5456 (class 2606 OID 23616)
-- Name: product_audit_logs product_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.product_audit_logs
    ADD CONSTRAINT product_audit_logs_pkey PRIMARY KEY (id);


--
-- TOC entry 5484 (class 2606 OID 24177)
-- Name: product_catalog product_catalog_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.product_catalog
    ADD CONSTRAINT product_catalog_pkey PRIMARY KEY (id);


--
-- TOC entry 5332 (class 2606 OID 20926)
-- Name: products products_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.products
    ADD CONSTRAINT products_pkey PRIMARY KEY (id);


--
-- TOC entry 5437 (class 2606 OID 23254)
-- Name: referrals referrals_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_pkey PRIMARY KEY (id);


--
-- TOC entry 5439 (class 2606 OID 23381)
-- Name: referrals referrals_referred_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_referred_id_key UNIQUE (referred_email);


--
-- TOC entry 5408 (class 2606 OID 23143)
-- Name: saved_looks saved_looks_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.saved_looks
    ADD CONSTRAINT saved_looks_pkey PRIMARY KEY (id);


--
-- TOC entry 5423 (class 2606 OID 24077)
-- Name: task_claims task_claims_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT task_claims_idempotency_key_key UNIQUE (idempotency_key);


--
-- TOC entry 5425 (class 2606 OID 23220)
-- Name: task_claims task_claims_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT task_claims_pkey PRIMARY KEY (id);


--
-- TOC entry 5346 (class 2606 OID 21086)
-- Name: tryon_records tryon_records_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tryon_records
    ADD CONSTRAINT tryon_records_pkey PRIMARY KEY (id);


--
-- TOC entry 5431 (class 2606 OID 24079)
-- Name: unlocked_themes unlocked_themes_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT unlocked_themes_idempotency_key_key UNIQUE (idempotency_key);


--
-- TOC entry 5433 (class 2606 OID 23237)
-- Name: unlocked_themes unlocked_themes_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT unlocked_themes_pkey PRIMARY KEY (id);


--
-- TOC entry 5447 (class 2606 OID 23301)
-- Name: cart_items uq_cart_item; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT uq_cart_item UNIQUE (member_email, item_id);


--
-- TOC entry 5482 (class 2606 OID 24139)
-- Name: crawler_staging_products uq_crawler_staging_source_product; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crawler_staging_products
    ADD CONSTRAINT uq_crawler_staging_source_product UNIQUE (source_site, source_product_id);


--
-- TOC entry 5443 (class 2606 OID 23281)
-- Name: cart uq_member_cart_item; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart
    ADD CONSTRAINT uq_member_cart_item UNIQUE (member_id, item_id);


--
-- TOC entry 5420 (class 2606 OID 23388)
-- Name: daily_checkins uq_member_checkin_date; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT uq_member_checkin_date UNIQUE (member_email, checkin_date);


--
-- TOC entry 5338 (class 2606 OID 21044)
-- Name: favorites uq_member_item; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.favorites
    ADD CONSTRAINT uq_member_item UNIQUE (member_id, item_id, item_type);


--
-- TOC entry 5427 (class 2606 OID 23395)
-- Name: task_claims uq_member_task_date; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT uq_member_task_date UNIQUE (member_email, task_id, claimed_date);


--
-- TOC entry 5435 (class 2606 OID 23410)
-- Name: unlocked_themes uq_member_theme; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT uq_member_theme UNIQUE (member_email, theme_id);


--
-- TOC entry 5486 (class 2606 OID 24179)
-- Name: product_catalog uq_product_catalog_source; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.product_catalog
    ADD CONSTRAINT uq_product_catalog_source UNIQUE (product_type, source_id);


--
-- TOC entry 5429 (class 2606 OID 23983)
-- Name: task_claims uq_task_claim_date; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT uq_task_claim_date UNIQUE (member_email, task_id, claim_date);


--
-- TOC entry 5475 (class 1259 OID 24158)
-- Name: crawler_staging_dedupe_uidx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX crawler_staging_dedupe_uidx ON public.crawler_staging_products USING btree (dedupe_key);


--
-- TOC entry 5478 (class 1259 OID 24160)
-- Name: crawler_staging_source_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX crawler_staging_source_idx ON public.crawler_staging_products USING btree (source_site, source_product_id);


--
-- TOC entry 5479 (class 1259 OID 24159)
-- Name: crawler_staging_status_idx; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX crawler_staging_status_idx ON public.crawler_staging_products USING btree (status, updated_at DESC);


--
-- TOC entry 5452 (class 1259 OID 23572)
-- Name: idx_admin_audit_target_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_admin_audit_target_created ON public.admin_audit_logs USING btree (target_email, created_at DESC);


--
-- TOC entry 5351 (class 1259 OID 23631)
-- Name: idx_blushes_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_blushes_recommendable ON public.blushes USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5352 (class 1259 OID 21401)
-- Name: idx_blushes_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_blushes_spid ON public.blushes USING btree (sale_page_id);


--
-- TOC entry 5381 (class 1259 OID 23699)
-- Name: idx_contouring_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_contouring_recommendable ON public.contouring USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5382 (class 1259 OID 22615)
-- Name: idx_contouring_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_contouring_spid ON public.contouring USING btree (sale_page_id);


--
-- TOC entry 5480 (class 1259 OID 24145)
-- Name: idx_crawler_staging_products_status_crawled_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_crawler_staging_products_status_crawled_at ON public.crawler_staging_products USING btree (status, crawled_at DESC);


--
-- TOC entry 5375 (class 1259 OID 22478)
-- Name: idx_em_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_em_spid ON public.eyeliner_mascara USING btree (sale_page_id);


--
-- TOC entry 5357 (class 1259 OID 23648)
-- Name: idx_eyebrows_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_eyebrows_recommendable ON public.eyebrows USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5358 (class 1259 OID 21416)
-- Name: idx_eyebrows_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_eyebrows_spid ON public.eyebrows USING btree (sale_page_id);


--
-- TOC entry 5376 (class 1259 OID 23682)
-- Name: idx_eyeliner_mascara_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_eyeliner_mascara_recommendable ON public.eyeliner_mascara USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5369 (class 1259 OID 23665)
-- Name: idx_eyeshadows_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_eyeshadows_recommendable ON public.eyeshadows USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5370 (class 1259 OID 22402)
-- Name: idx_eyeshadows_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_eyeshadows_spid ON public.eyeshadows USING btree (sale_page_id);


--
-- TOC entry 5392 (class 1259 OID 23714)
-- Name: idx_foundations_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_foundations_recommendable ON public.foundations USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5393 (class 1259 OID 22844)
-- Name: idx_foundations_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_foundations_spid ON public.foundations USING btree (sale_page_id);


--
-- TOC entry 5363 (class 1259 OID 23745)
-- Name: idx_highlighters_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_highlighters_recommendable ON public.highlighters USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5364 (class 1259 OID 21431)
-- Name: idx_highlighters_spid; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_highlighters_spid ON public.highlighters USING btree (sale_page_id);


--
-- TOC entry 5383 (class 1259 OID 23760)
-- Name: idx_lipsticks_recommendable; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_lipsticks_recommendable ON public.lipsticks USING btree (status, review_status, in_stock, recommendation_ready);


--
-- TOC entry 5394 (class 1259 OID 23113)
-- Name: idx_member_audit_logs_target_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_member_audit_logs_target_email ON public.member_audit_logs USING btree (target_email);


--
-- TOC entry 5457 (class 1259 OID 24071)
-- Name: idx_member_sessions_session_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_member_sessions_session_id ON public.member_sessions USING btree (session_id);


--
-- TOC entry 5458 (class 1259 OID 24080)
-- Name: idx_member_sessions_source; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_member_sessions_source ON public.member_sessions USING btree (source_identifier);


--
-- TOC entry 5324 (class 1259 OID 24090)
-- Name: idx_members_email_verified_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_members_email_verified_at ON public.members USING btree (email_verified_at);


--
-- TOC entry 5325 (class 1259 OID 23456)
-- Name: idx_members_referral_code; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX idx_members_referral_code ON public.members USING btree (referral_code) WHERE (referral_code IS NOT NULL);


--
-- TOC entry 5326 (class 1259 OID 23570)
-- Name: idx_members_status_deleted_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_members_status_deleted_at ON public.members USING btree (status, deleted_at);


--
-- TOC entry 5409 (class 1259 OID 23458)
-- Name: idx_otp_codes_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_otp_codes_email ON public.otp_codes USING btree (email);


--
-- TOC entry 5397 (class 1259 OID 23401)
-- Name: idx_points_transactions_member_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_points_transactions_member_email ON public.points_transactions USING btree (member_email);


--
-- TOC entry 5454 (class 1259 OID 23791)
-- Name: idx_product_audit_logs_product; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_product_audit_logs_product ON public.product_audit_logs USING btree (product_type, product_id, created_at DESC);


--
-- TOC entry 5405 (class 1259 OID 23571)
-- Name: idx_saved_looks_member_created; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_saved_looks_member_created ON public.saved_looks USING btree (member_email, created_at DESC);


--
-- TOC entry 5406 (class 1259 OID 23459)
-- Name: idx_saved_looks_member_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_saved_looks_member_email ON public.saved_looks USING btree (member_email);


--
-- TOC entry 5421 (class 1259 OID 23984)
-- Name: idx_task_claims_member_task_date; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_task_claims_member_task_date ON public.task_claims USING btree (member_email, task_id, claim_date DESC);


--
-- TOC entry 5453 (class 1259 OID 23567)
-- Name: ix_admin_audit_logs_target_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_admin_audit_logs_target_email ON public.admin_audit_logs USING btree (target_email);


--
-- TOC entry 5459 (class 1259 OID 24044)
-- Name: ix_member_sessions_member_version; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_member_sessions_member_version ON public.member_sessions USING btree (member_id, session_version, revoked_at);


--
-- TOC entry 5410 (class 1259 OID 24043)
-- Name: ix_otp_codes_email_purpose_expiry; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_otp_codes_email_purpose_expiry ON public.otp_codes USING btree (email, purpose, expires_at DESC);


--
-- TOC entry 5470 (class 1259 OID 24117)
-- Name: ix_pending_registrations_expires_at; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_pending_registrations_expires_at ON public.pending_registrations USING btree (expires_at);


--
-- TOC entry 5398 (class 1259 OID 23402)
-- Name: ix_points_transactions_member_email; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_points_transactions_member_email ON public.points_transactions USING btree (member_email);


--
-- TOC entry 5672 (class 2618 OID 23074)
-- Name: view_member_activity _RETURN; Type: RULE; Schema: public; Owner: postgres
--

CREATE OR REPLACE VIEW public.view_member_activity AS
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


--
-- TOC entry 5504 (class 2620 OID 21111)
-- Name: checkins trg_auto_upgrade_level; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_auto_upgrade_level AFTER INSERT ON public.checkins FOR EACH ROW EXECUTE FUNCTION public.func_auto_upgrade_level();


--
-- TOC entry 5506 (class 2620 OID 21112)
-- Name: favorites trg_before_favorite_insert; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_before_favorite_insert BEFORE INSERT ON public.favorites FOR EACH ROW EXECUTE FUNCTION public.func_before_favorite_insert();


--
-- TOC entry 5507 (class 2620 OID 23820)
-- Name: blushes trg_blushes_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_blushes_product_contract BEFORE INSERT OR UPDATE ON public.blushes FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5517 (class 2620 OID 23824)
-- Name: contouring trg_contouring_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_contouring_product_contract BEFORE INSERT OR UPDATE ON public.contouring FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5509 (class 2620 OID 23821)
-- Name: eyebrows trg_eyebrows_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_eyebrows_product_contract BEFORE INSERT OR UPDATE ON public.eyebrows FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5515 (class 2620 OID 23823)
-- Name: eyeliner_mascara trg_eyeliner_mascara_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_eyeliner_mascara_product_contract BEFORE INSERT OR UPDATE ON public.eyeliner_mascara FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5513 (class 2620 OID 23822)
-- Name: eyeshadows trg_eyeshadows_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_eyeshadows_product_contract BEFORE INSERT OR UPDATE ON public.eyeshadows FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5521 (class 2620 OID 23825)
-- Name: foundations trg_foundations_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_foundations_product_contract BEFORE INSERT OR UPDATE ON public.foundations FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5511 (class 2620 OID 23826)
-- Name: highlighters trg_highlighters_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_highlighters_product_contract BEFORE INSERT OR UPDATE ON public.highlighters FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5519 (class 2620 OID 23827)
-- Name: lipsticks trg_lipsticks_product_contract; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_lipsticks_product_contract BEFORE INSERT OR UPDATE ON public.lipsticks FOR EACH ROW EXECUTE FUNCTION public.enforce_product_contract();


--
-- TOC entry 5502 (class 2620 OID 21114)
-- Name: members trg_member_level_history; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_member_level_history AFTER UPDATE ON public.members FOR EACH ROW EXECUTE FUNCTION public.func_member_level_history();


--
-- TOC entry 5505 (class 2620 OID 21113)
-- Name: checkins trg_prevent_multiple_checkin; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_prevent_multiple_checkin BEFORE INSERT ON public.checkins FOR EACH ROW EXECUTE FUNCTION public.func_prevent_multiple_checkin();


--
-- TOC entry 5508 (class 2620 OID 24182)
-- Name: blushes trg_product_catalog_blushes; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_blushes AFTER INSERT ON public.blushes FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5518 (class 2620 OID 24188)
-- Name: contouring trg_product_catalog_contouring; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_contouring AFTER INSERT ON public.contouring FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5510 (class 2620 OID 24184)
-- Name: eyebrows trg_product_catalog_eyebrows; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_eyebrows AFTER INSERT ON public.eyebrows FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5516 (class 2620 OID 24183)
-- Name: eyeliner_mascara trg_product_catalog_eyeliner_mascara; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_eyeliner_mascara AFTER INSERT ON public.eyeliner_mascara FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5514 (class 2620 OID 24185)
-- Name: eyeshadows trg_product_catalog_eyeshadows; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_eyeshadows AFTER INSERT ON public.eyeshadows FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5522 (class 2620 OID 24186)
-- Name: foundations trg_product_catalog_foundations; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_foundations AFTER INSERT ON public.foundations FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5512 (class 2620 OID 24187)
-- Name: highlighters trg_product_catalog_highlighters; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_highlighters AFTER INSERT ON public.highlighters FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5520 (class 2620 OID 24181)
-- Name: lipsticks trg_product_catalog_lipsticks; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_lipsticks AFTER INSERT ON public.lipsticks FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5503 (class 2620 OID 24189)
-- Name: products trg_product_catalog_products; Type: TRIGGER; Schema: public; Owner: postgres
--

CREATE TRIGGER trg_product_catalog_products AFTER INSERT ON public.products FOR EACH ROW EXECUTE FUNCTION public.register_product_catalog_item();


--
-- TOC entry 5499 (class 2606 OID 23424)
-- Name: cart_items cart_items_member_email_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart_items
    ADD CONSTRAINT cart_items_member_email_fkey FOREIGN KEY (member_email) REFERENCES public.members(email);


--
-- TOC entry 5498 (class 2606 OID 23282)
-- Name: cart cart_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.cart
    ADD CONSTRAINT cart_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON DELETE CASCADE;


--
-- TOC entry 5487 (class 2606 OID 21026)
-- Name: checkins checkins_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.checkins
    ADD CONSTRAINT checkins_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON UPDATE CASCADE ON DELETE RESTRICT;


--
-- TOC entry 5501 (class 2606 OID 24140)
-- Name: crawler_staging_products crawler_staging_products_imported_product_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.crawler_staging_products
    ADD CONSTRAINT crawler_staging_products_imported_product_id_fkey FOREIGN KEY (imported_product_id) REFERENCES public.products(id);


--
-- TOC entry 5488 (class 2606 OID 21045)
-- Name: favorites favorites_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.favorites
    ADD CONSTRAINT favorites_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- TOC entry 5492 (class 2606 OID 23444)
-- Name: analysis_history fk_analysis_history_email; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.analysis_history
    ADD CONSTRAINT fk_analysis_history_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;


--
-- TOC entry 5493 (class 2606 OID 23429)
-- Name: daily_checkins fk_daily_checkins_email; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.daily_checkins
    ADD CONSTRAINT fk_daily_checkins_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;


--
-- TOC entry 5490 (class 2606 OID 23439)
-- Name: points_transactions fk_points_transactions_email; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.points_transactions
    ADD CONSTRAINT fk_points_transactions_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;


--
-- TOC entry 5494 (class 2606 OID 23434)
-- Name: task_claims fk_task_claims_email; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.task_claims
    ADD CONSTRAINT fk_task_claims_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;


--
-- TOC entry 5495 (class 2606 OID 23449)
-- Name: unlocked_themes fk_unlocked_themes_email; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.unlocked_themes
    ADD CONSTRAINT fk_unlocked_themes_email FOREIGN KEY (member_email) REFERENCES public.members(email) ON DELETE CASCADE;


--
-- TOC entry 5500 (class 2606 OID 23963)
-- Name: member_sessions member_sessions_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.member_sessions
    ADD CONSTRAINT member_sessions_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number);


--
-- TOC entry 5496 (class 2606 OID 23382)
-- Name: referrals referrals_referred_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_referred_id_fkey FOREIGN KEY (referred_email) REFERENCES public.members(phone_number) ON DELETE CASCADE;


--
-- TOC entry 5497 (class 2606 OID 23375)
-- Name: referrals referrals_referrer_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.referrals
    ADD CONSTRAINT referrals_referrer_id_fkey FOREIGN KEY (referrer_email) REFERENCES public.members(phone_number) ON DELETE CASCADE;


--
-- TOC entry 5491 (class 2606 OID 23419)
-- Name: saved_looks saved_looks_member_email_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.saved_looks
    ADD CONSTRAINT saved_looks_member_email_fkey FOREIGN KEY (member_email) REFERENCES public.members(email);


--
-- TOC entry 5489 (class 2606 OID 21087)
-- Name: tryon_records tryon_records_member_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.tryon_records
    ADD CONSTRAINT tryon_records_member_id_fkey FOREIGN KEY (member_id) REFERENCES public.members(phone_number) ON UPDATE CASCADE ON DELETE CASCADE;


--
-- TOC entry 5679 (class 0 OID 0)
-- Dependencies: 6
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: pg_database_owner
--

GRANT USAGE ON SCHEMA public TO decorate_me_crawler;


--
-- TOC entry 5690 (class 0 OID 0)
-- Dependencies: 284
-- Name: TABLE crawler_staging_products; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.crawler_staging_products TO decorate_me_crawler;


--
-- TOC entry 5691 (class 0 OID 0)
-- Dependencies: 283
-- Name: SEQUENCE crawler_staging_products_id_seq; Type: ACL; Schema: public; Owner: postgres
--

GRANT SELECT,USAGE ON SEQUENCE public.crawler_staging_products_id_seq TO decorate_me_crawler;


-- Completed on 2026-07-29 14:47:09

--
-- PostgreSQL database dump complete
--

\unrestrict TrXHqVbCLrvfMyAmLume9Wj1ZSpVBgEn4LQPkSn8IVf0wosLeJpq9CjiELF7T9C

