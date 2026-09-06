"""Safe, read-only product page preview crawler."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
import hashlib
import ipaddress
import json
import os
import re
import socket
import threading
import time
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from price_conversion import price_for_frontend


CONNECT_TIMEOUT = float(os.getenv("CRAWLER_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("CRAWLER_READ_TIMEOUT", "10"))
MAX_HTML_BYTES = int(os.getenv("CRAWLER_MAX_HTML_BYTES", str(2 * 1024 * 1024)))
MAX_REDIRECTS = int(os.getenv("CRAWLER_MAX_REDIRECTS", "3"))
USER_AGENT = os.getenv("CRAWLER_USER_AGENT", "DecorateMeProductPreview/1.0")


BRAND_SITE_PROFILES = (
    {
        "domains": ("maybelline.com.tw",),
        "brand": "MAYBELLINE",
        "defaultCurrency": "TWD",
    },
    {
        "domains": ("maybelline.com",),
        "brand": "MAYBELLINE",
        "defaultCurrency": "USD",
    },
    {
        "domains": ("bobbibrown.com.tw",),
        "brand": "BOBBI BROWN",
        "defaultCurrency": "TWD",
    },
    {
        "domains": ("bobbibrowncosmetics.com",),
        "brand": "BOBBI BROWN",
        "defaultCurrency": "USD",
    },
)


def _brand_site_profile(url: str) -> dict | None:
    hostname = (urlsplit(url).hostname or "").rstrip(".").lower()
    for profile in BRAND_SITE_PROFILES:
        if any(hostname == domain or hostname.endswith(f".{domain}") for domain in profile["domains"]):
            return profile
    return None


def _canonical_category(final_url: str, raw_category: Any = None) -> str | None:
    value = f"{urlsplit(final_url).path} {raw_category or ''}".casefold().replace("_", "-")
    category_markers = (
        ("foundations", ("foundation", "粉底", "底妝")),
        ("lipsticks", ("lipstick", "lip-color", "lip-colour", "唇膏", "唇彩", "唇釉")),
        ("blushes", ("blush", "腮紅")),
        ("eyeshadows", ("eye-shadow", "eyeshadow", "眼影")),
        ("eyeliner_mascara", ("eyeliner", "mascara", "眼線", "睫毛")),
        ("eyebrows", ("eyebrow", "brow", "眉")),
        ("contouring", ("contour", "bronzer", "修容")),
        ("highlighters", ("highlighter", "highlight", "打亮")),
    )
    return next((category for category, markers in category_markers
                 if any(marker in value for marker in markers)), None)


class CrawlerError(Exception):
    def __init__(self, code: str, message: str, http_status: int, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.detail = detail


def public_product_url(value: Any) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 2048:
        raise CrawlerError("INVALID_URL", "請提供完整的 http(s) 商品網址", 400)
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError as exc:
        raise CrawlerError("INVALID_URL", "商品網址格式錯誤", 400) from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise CrawlerError("INVALID_URL", "只允許 http 或 https 網址", 400)
    if parsed.username or parsed.password or port not in {None, 80, 443}:
        raise CrawlerError("INVALID_URL", "商品網址包含不允許的連線資訊", 400)

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".local"):
        raise CrawlerError("INVALID_URL", "不允許內部網路網址", 400)
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise CrawlerError("INVALID_URL", "網址的網域無法解析", 400) from exc
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise CrawlerError("INVALID_URL", "不允許私有、保留或本機 IP", 400)
    normalized = urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, ""))
    return normalized, hostname


def sanitized_url(value: str) -> str:
    parsed = urlsplit(value)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _peer_ip(response: requests.Response) -> str | None:
    socket_candidates = []
    try:
        socket_candidates.append(response.raw._connection.sock)
    except AttributeError:
        pass
    try:
        socket_candidates.append(response.raw._fp.fp.raw._sock)
    except AttributeError:
        pass
    for connected_socket in socket_candidates:
        try:
            if connected_socket:
                return connected_socket.getpeername()[0]
        except (OSError, TypeError):
            continue
    return None


def fetch_html(url: str) -> tuple[str, str, str]:
    session = requests.Session()
    session.trust_env = False
    current_url = url
    for redirect_count in range(MAX_REDIRECTS + 1):
        current_url, hostname = public_product_url(current_url)
        try:
            response = session.get(
                current_url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                allow_redirects=False,
                stream=True,
            )
        except requests.Timeout as exc:
            raise CrawlerError("FETCH_TIMEOUT", "目標網站連線逾時", 504) from exc
        except requests.RequestException as exc:
            raise CrawlerError("SCRAPE_BLOCKED", "無法取得目標商品頁", 502) from exc

        peer_ip = _peer_ip(response)
        if peer_ip and not ipaddress.ip_address(peer_ip).is_global:
            response.close()
            raise CrawlerError("INVALID_URL", "目標網站連線到不允許的 IP", 400)

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            response.close()
            if not location or redirect_count >= MAX_REDIRECTS:
                raise CrawlerError("SCRAPE_BLOCKED", "目標網站重新導向次數過多", 502)
            current_url = urljoin(current_url, location)
            continue
        if response.status_code == 429:
            response.close()
            raise CrawlerError("RATE_LIMITED", "目標網站限制請求頻率", 429)
        if response.status_code in {401, 403}:
            response.close()
            profile = _brand_site_profile(current_url)
            if profile:
                raise CrawlerError(
                    "SCRAPE_BLOCKED",
                    f"{profile['brand']} 官網目前拒絕伺服器自動讀取",
                    502,
                    "品牌官網啟用了自動存取防護；請保留原始商品連結，改由管理員人工補登並審核。",
                )
            raise CrawlerError("SCRAPE_BLOCKED", "目標網站拒絕爬蟲存取", 502)
        if response.status_code == 404:
            response.close()
            raise CrawlerError("NO_PRODUCT_FOUND", "商品頁不存在", 404)
        if response.status_code >= 400:
            status = response.status_code
            response.close()
            raise CrawlerError("SCRAPE_BLOCKED", "目標網站無法存取", 502, f"upstream status {status}")

        content_type = response.headers.get("Content-Type", "").lower()
        if content_type and "html" not in content_type and "xhtml" not in content_type:
            response.close()
            raise CrawlerError("PARSE_FAILED", "目標網址不是 HTML 商品頁", 422)
        chunks, total = [], 0
        for chunk in response.iter_content(65536):
            total += len(chunk)
            if total > MAX_HTML_BYTES:
                response.close()
                raise CrawlerError("PARSE_FAILED", "商品頁內容超過大小限制", 422)
            chunks.append(chunk)
        encoding = response.encoding or "utf-8"
        final_url = response.url
        response.close()
        html = b"".join(chunks).decode(encoding, errors="replace")
        blocked_markers = ("cf-chl-", "captcha", "verify you are human", "access denied")
        if any(marker in html[:200000].lower() for marker in blocked_markers):
            raise CrawlerError("SCRAPE_BLOCKED", "目標網站要求驗證或阻擋自動存取", 502)
        return html, final_url, hostname
    raise CrawlerError("SCRAPE_BLOCKED", "目標網站重新導向次數過多", 502)


def _product_nodes(value: Any):
    if isinstance(value, list):
        for item in value:
            yield from _product_nodes(item)
    elif isinstance(value, dict):
        node_type = value.get("@type")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(t).lower() == "product" for t in types):
            yield value
        if "@graph" in value:
            yield from _product_nodes(value["@graph"])


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


def _image_urls(value: Any, base_url: str) -> list[str]:
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        raw = item.get("url") or item.get("contentUrl") if isinstance(item, dict) else item
        if isinstance(raw, str) and raw.strip():
            absolute = urljoin(base_url, raw.strip())
            if absolute.startswith(("http://", "https://")) and absolute not in result:
                result.append(absolute)
    return result[:20]


def _number(value: Any) -> int | float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^0-9.,-]", "", value).replace(",", "")
    try:
        parsed = float(cleaned)
        return int(parsed) if parsed.is_integer() else parsed
    except (ValueError, TypeError):
        return None


def parse_product_preview(html: str, final_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    site_profile = _brand_site_profile(final_url)
    product = None
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            parsed = json.loads(script.string or script.get_text())
            product = next(_product_nodes(parsed), None)
            if product:
                break
        except (json.JSONDecodeError, TypeError):
            continue

    def meta(*keys):
        for key in keys:
            tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    product = product or {}
    offers = _first(product.get("offers")) or {}
    brand_value = product.get("brand")
    parsed_brand = (brand_value.get("name") if isinstance(brand_value, dict) else brand_value) or meta("product:brand")
    brand = site_profile["brand"] if site_profile else parsed_brand
    name = product.get("name") or meta("og:title", "twitter:title")
    description = product.get("description") or meta("og:description", "description")
    price = _number(offers.get("price") or offers.get("lowPrice") or meta("product:price:amount"))
    currency = (offers.get("priceCurrency") or meta("product:price:currency")
                or (site_profile["defaultCurrency"] if site_profile else None) or "TWD")
    images = _image_urls(product.get("image"), final_url)
    if not images:
        images = _image_urls(meta("og:image", "twitter:image"), final_url)
    raw_category = product.get("category") or meta("product:category")
    category = _canonical_category(final_url, raw_category) or raw_category
    specs = {}
    properties = product.get("additionalProperty") or []
    if isinstance(properties, dict):
        properties = [properties]
    for prop in properties:
        if isinstance(prop, dict) and prop.get("name") and prop.get("value") is not None:
            specs[str(prop["name"])] = prop["value"]

    product_id = product.get("sku") or product.get("productID") or product.get("mpn")
    if not product_id:
        product_id = next((part for part in reversed(urlsplit(final_url).path.split("/")) if part), None)
    if not name:
        raise CrawlerError("NO_PRODUCT_FOUND", "此頁不是可辨識的單一商品頁", 404)
    # A generic title alone is not enough evidence that this is a product page.
    product_evidence = bool(product or price is not None or meta("product:price:amount", "product:retailer_item_id"))
    if not product_evidence:
        raise CrawlerError("NO_PRODUCT_FOUND", "此頁不是可辨識的單一商品頁", 404)

    frontend_price = price_for_frontend(price, currency)
    missing = []
    for field, value in (("brand", brand), ("price", price), ("imageUrl", images[0] if images else None), ("category", category)):
        if value in {None, ""}:
            missing.append(field)
    return {
        "sourceUrl": final_url,
        "sourceSite": urlsplit(final_url).hostname,
        "sourceProductId": str(product_id) if product_id else None,
        "productName": str(name).strip(),
        "name": str(name).strip(),
        "brand": str(brand).strip() if brand else None,
        "price": price,
        "currency": str(currency).upper(),
        "displayPrice": frontend_price["display"],
        "priceValue": frontend_price["amount"],
        "displayCurrency": frontend_price["currency"],
        "priceConverted": frontend_price["converted"],
        "priceNote": frontend_price["note"],
        "priceConversion": frontend_price["conversion"],
        "description": BeautifulSoup(str(description), "html.parser").get_text(" ", strip=True) if description else None,
        "imageUrl": images[0] if images else None,
        "imageUrls": images,
        "category": str(category).strip() if category else None,
        "sourceProfile": site_profile["brand"] if site_profile else None,
        "specs": specs,
        "missingFields": missing,
        "lastCrawledAt": datetime.now().astimezone().isoformat(),
    }


class PreviewRateLimiter:
    def __init__(self):
        self.window = int(os.getenv("CRAWLER_RATE_WINDOW_SECONDS", "600"))
        self.admin_limit = int(os.getenv("CRAWLER_ADMIN_RATE_LIMIT", "10"))
        self.domain_limit = int(os.getenv("CRAWLER_DOMAIN_RATE_LIMIT", "30"))
        self.global_limit = int(os.getenv("CRAWLER_GLOBAL_RATE_LIMIT", "100"))
        self._events = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, admin: str, domain: str, redis_client=None):
        if redis_client is not None:
            bucket = int(time.time()) // self.window
            admin_hash = hashlib.sha256(admin.encode("utf-8")).hexdigest()[:24]
            domain_hash = hashlib.sha256(domain.encode("utf-8")).hexdigest()[:24]
            keys = (
                (f"crawler-rate:admin:{admin_hash}:{bucket}", self.admin_limit),
                (f"crawler-rate:domain:{domain_hash}:{bucket}", self.domain_limit),
                (f"crawler-rate:global:{bucket}", self.global_limit),
            )
            try:
                pipe = redis_client.pipeline(transaction=True)
                for key, _ in keys:
                    pipe.incr(key)
                    pipe.expire(key, self.window + 60)
                values = pipe.execute()
                counts = values[0::2]
                if any(count > limit for count, (_, limit) in zip(counts, keys)):
                    raise CrawlerError("RATE_LIMITED", "爬蟲預覽請求過於頻繁，請稍後再試", 429)
                return
            except CrawlerError:
                raise
            except Exception:
                # Redis is optional in local development; keep enforcing a
                # process-local limit if it is temporarily unavailable.
                pass
        now = time.monotonic()
        keys = ((f"admin:{admin}", self.admin_limit), (f"domain:{domain}", self.domain_limit), ("global", self.global_limit))
        with self._lock:
            for key, _ in keys:
                queue = self._events[key]
                while queue and queue[0] <= now - self.window:
                    queue.popleft()
            if any(len(self._events[key]) >= limit for key, limit in keys):
                raise CrawlerError("RATE_LIMITED", "爬蟲預覽請求過於頻繁，請稍後再試", 429)
            for key, _ in keys:
                self._events[key].append(now)


preview_rate_limiter = PreviewRateLimiter()


def build_product_preview(url: str) -> dict:
    validated_url, _ = public_product_url(url)
    html, final_url, _ = fetch_html(validated_url)
    return parse_product_preview(html, final_url)
