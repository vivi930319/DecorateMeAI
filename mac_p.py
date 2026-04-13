"""
MAC Cosmetics 商品頁面 Playwright 爬蟲
目標: https://www.maccosmetics.com.tw/product/13847/120653/...

DOM 結構 (來自截圖):
  <li class="product-full__shades-grid-item ..."
      data-sku-id="SKU213473"
      data-product-code="SRMY33"
      data-color-family="...">
    <div class="product-full__shade">
      <div class="product-full__shade-swatch" style="background:#f5caa8"></div>
      <div class="product-full__shade-name">NC7</div>
    </div>
  </li>

輸出欄位:
    brand, name, shade_name, price, lab_json, rgb_hex, description, image_data
    + sku_id, product_code, color_family（bonus）

安裝:
    pip install playwright
    playwright install chromium

執行:
    python scrape_mac_cosmetics.py
"""

import asyncio
import csv
import json
import re
from playwright.async_api import async_playwright

URL = (
    "https://www.maccosmetics.com.tw/product/13847/120653/"
    "studio-fix-skin-balancing-complex-longwear-soft-matte-foundation/spf25pa"
)
OUTPUT_CSV = "mac_shades.csv"
BRAND = "MAC"


# ── 色彩轉換 ──────────────────────────────────────────────────────────────────

def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_lab(r: int, g: int, b: int) -> dict:
    """sRGB (0-255) → CIE L*a*b* (D65 白點)"""
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = lin(r), lin(g), lin(b)
    X = rl*0.4124564 + gl*0.3575761 + bl*0.1804375
    Y = rl*0.2126729 + gl*0.7151522 + bl*0.0721750
    Z = rl*0.0193339 + gl*0.1191920 + bl*0.9503041
    Xn, Yn, Zn = 0.95047, 1.00000, 1.08883

    def f(t):
        return t**(1/3) if t > 0.008856 else 7.787*t + 16/116

    fx, fy, fz = f(X/Xn), f(Y/Yn), f(Z/Zn)
    return {
        "L": round(116*fy - 16, 2),
        "a": round(500*(fx - fy), 2),
        "b": round(200*(fy - fz), 2),
    }


def css_to_hex(css: str) -> str:
    css = css.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,6})", css)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c*2 for c in h)
        return f"#{h.upper()}"
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", css)
    if m:
        return f"#{int(m.group(1)):02X}{int(m.group(2)):02X}{int(m.group(3)):02X}"
    return ""


# ── 主爬蟲 ───────────────────────────────────────────────────────────────────

async def scrape(url: str) -> list:
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-TW",
            viewport={"width": 1440, "height": 900},
        )
        page = await context.new_page()

        await page.route(
            re.compile(r"(google-analytics|gtm\.js|facebook\.net|doubleclick|hotjar)"),
            lambda route: route.abort(),
        )

        print(f"[*] 開啟頁面...")
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        print("[*] 等待色號 grid...")
        try:
            await page.wait_for_selector(
                ".product-full__shades-grid-item, .js-spp-shades-grid-item",
                timeout=20_000,
            )
        except Exception:
            print("[!] 等待 shade grid 超時，繼續嘗試...")
        await page.wait_for_timeout(2_000)

        # 商品名稱
        product_name = ""
        for sel in ["h1.product-full__name", "h1", "[class*='product-name']"]:
            try:
                t = (await page.locator(sel).first.inner_text(timeout=3_000)).strip()
                if t:
                    product_name = t; break
            except Exception:
                continue

        # 價格
        price = ""
        for sel in [".product-full__price", "[class*='product-price']", "[class*='price']"]:
            try:
                t = (await page.locator(sel).first.inner_text(timeout=3_000)).strip()
                if t and re.search(r"\d", t):
                    price = t; break
            except Exception:
                continue

        # 描述
        description = ""
        for sel in [".product-full__description", "[class*='product-description']", "[class*='description']"]:
            try:
                t = (await page.locator(sel).first.inner_text(timeout=3_000)).strip()
                if len(t) > 20:
                    description = t; break
            except Exception:
                continue

        # 主圖 base64
        image_data = ""
        for sel in [".product-full__image img", "[class*='hero'] img", "img[class*='product']"]:
            try:
                src = await page.locator(sel).first.get_attribute("src", timeout=3_000)
                if src:
                    if src.startswith("//"):
                        src = "https:" + src
                    b64 = await page.evaluate("""async (src) => {
                        try {
                            const r = await fetch(src);
                            const buf = await r.arrayBuffer();
                            const bytes = new Uint8Array(buf);
                            let bin = '';
                            for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
                            const mime = r.headers.get('content-type') || 'image/jpeg';
                            return `data:${mime};base64,` + btoa(bin);
                        } catch(e) { return ''; }
                    }""", src)
                    if b64:
                        image_data = b64; break
            except Exception:
                continue

        # ── 色號擷取（精準對應截圖 DOM）────────────────────────────
        print("[*] 擷取色號 swatch...")
        raw_shades = await page.evaluate("""() => {
            const items = document.querySelectorAll(
                '.product-full__shades-grid-item, .js-spp-shades-grid-item'
            );
            const results = [];
            items.forEach(li => {
                // swatch div → inline style background
                const swatchEl = li.querySelector(
                    '.product-full__shade-swatch, [class*="shade-swatch"]'
                );
                const style = swatchEl ? (swatchEl.getAttribute('style') || '') : '';
                const bgMatch = style.match(/background(?:-color)?\\s*:\\s*([^;\"\\s]+)/i);
                const bg = bgMatch ? bgMatch[1].trim() : '';

                // shade name text
                const nameEl = li.querySelector(
                    '.product-full__shade-name, [class*="shade-name"]'
                );
                const shadeName = nameEl ? nameEl.innerText.trim() : '';

                results.push({
                    shadeName,
                    bg,
                    skuId:       li.getAttribute('data-sku-id') || '',
                    skuBaseId:   li.getAttribute('data-sku-base-id') || '',
                    productCode: li.getAttribute('data-product-code') || '',
                    colorFamily: li.getAttribute('data-color-family') || '',
                });
            });
            return results;
        }""")

        print(f"[+] 找到 {len(raw_shades)} 個色號")

        rows = []
        for s in raw_shades:
            rgb_hex = css_to_hex(s["bg"]) if s["bg"] else ""
            lab = {}
            if rgb_hex:
                try:
                    lab = rgb_to_lab(*hex_to_rgb(rgb_hex))
                except Exception:
                    pass

            rows.append({
                "brand":        BRAND,
                "name":         product_name,
                "shade_name":   s["shadeName"],
                "price":        price,
                "lab_json":     json.dumps(lab, ensure_ascii=False),
                "rgb_hex":      rgb_hex,
                "description":  description,
                "image_data":   image_data,
                # bonus
                "sku_id":       s["skuId"],
                "product_code": s["productCode"],
                "color_family": s["colorFamily"],
            })

        await browser.close()
        return rows


def save_csv(rows: list, path: str):
    if not rows:
        print("[!] 無資料可寫入"); return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[✓] CSV 已儲存: {path}（{len(rows)} 筆）")


async def main():
    print("=" * 55)
    print("  MAC Cosmetics Shade Scraper")
    print("=" * 55)
    rows = await scrape(URL)
    for r in rows[:3]:
        preview = {k: v for k, v in r.items() if k != "image_data"}
        print(json.dumps(preview, ensure_ascii=False, indent=2))
    save_csv(rows, OUTPUT_CSV)

if __name__ == "__main__":
    asyncio.run(main())