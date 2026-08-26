"""逐項驗證商品／推薦 API 的交接文件聲稱，對照線上實際行為。

2026-08-24 第一次跑：38 項中 26 項通過。落差整理在
`補充文件md檔案/給資料庫端_交接文件與線上實作落差_2026-08-24.md`。

網址每次換 tunnel 都要改 URL 常數，或用 PRODUCT_API_URL 環境變數覆蓋。

方法：改一個值、比對回來的內容有沒有跟著變——只看 HTTP 200 或欄位存不存在，
會把「參數被忽略」誤判成「功能正常」。這個專案踩過一次：category=lipsticks 看起來
有效，其實是預設排序剛好都是唇膏。
"""
import json
import urllib.error
import urllib.parse
import urllib.request

import os

# 不放預設網址。Tunnel 每次重啟就換一組，寫死的那個隔天就是錯的——
# 而錯的網址跑起來像「API 掛了」，不像「腳本過期了」，會讓人去查錯的地方。
# 它同時也是 CI 秘密掃描擋下的東西：暫時性網址不該躺在會被部署的程式裡。
URL = os.getenv("PRODUCT_API_URL", "").rstrip("/")
if not URL:
    raise SystemExit(
        "請先設定 PRODUCT_API_URL，例如："
        "  PRODUCT_API_URL=<商品 API 的網址> "
        "python tools/verify_product_api_contract.py")
results = []


def call(method, path, body=None, timeout=45):
    # path 可能含中文（category=腮紅）。urllib 不會自己編碼，送出去會 UnicodeEncodeError，
    # 而下面的 except 會把它變成「0 筆結果」——看起來就像「後端正確回了空陣列」。
    # 2026-08-24 就是這樣把一個被忽略的參數誤判成通過的。
    path = urllib.parse.quote(path, safe="/?=&:")
    req = urllib.request.Request(
        URL + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"} if body is not None else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}
    except Exception as exc:
        # 回 0 而不是拋出，讓單一項目失敗不中斷整輪；但呼叫端必須把 0 當成
        # 「沒測到」而不是「回了空結果」——這兩者的結論完全相反。
        return 0, {"_err": f"{type(exc).__name__}: {exc}"}


def check(section, claim, ok, detail=""):
    results.append((section, claim, ok, detail))
    print(f"  {'OK  ' if ok else 'FAIL'} {claim}" + (f"   {detail}" if detail else ""))


def pkg(**over):
    p = {
        "analysisPackage": {
            "id": "AN-TEST", "schemaVersion": "2026-08-v2", "style": "richGirl",
            "faceAnalysis": {
                "faceShape": "oval", "eyeShape": "almond", "lipShape": "full",
                "skinTone": {"lab": [65.2, 8.1, 18.4], "season": "warm",
                             "level": "medium", "labReliable": True},
                "lipLab": [48.2, 28.1, 16.5],
            },
            "generativeText": {"styleTags": ["luxury", "soft"],
                               "preferredColors": ["champagne"], "avoidTags": ["glitter"]},
        },
        "limit": 12,
    }
    p.update(over)
    return p


def rec_of(body):
    return (body.get("analysisPackage") or {}).get("recommendations") or {}


print("=== 三、推薦回應的結構 ===")
st, body = call("POST", "/recommend-products", pkg())
rec = rec_of(body)
prods = rec.get("products") or []
check("3.1", "analysisPackage.recommendations.products 存在", bool(prods), f"{len(prods)} 件")
for key in ("primary", "alternates", "threshold", "coverage", "fallbackReasons",
            "skinToneLabReliable", "personalization", "shadeRecommendation"):
    present = key in rec and rec[key] is not None
    check("3.1", f"recommendations.{key}", present,
          "" if present else ("鍵不存在" if key not in rec else "值是 null"))

if prods:
    p = prods[0]
    for key in ("candidateKey", "matchScore", "scoreBreakdown", "matchedKeywords",
                "matchReason", "matchReasons"):
        present = key in p and p[key] is not None
        check("3.2", f"商品欄位 {key}", present,
              "" if present else ("鍵不存在" if key not in p else "值是 null"))

print("\n=== 3.3 眉彩 ===")
brows = [p for p in prods if p.get("type") == "eyebrows"]
check("3.3", "眉彩出現在 products", bool(brows), f"{len(brows)} 件")
codes = {p.get("colorMethod") for p in brows}
check("3.3", "眉彩不再回 BROW_COLOR_UNAVAILABLE",
      "brow_color_unavailable" not in {str(c).lower() for c in codes}, f"colorMethod={codes}")
fb = rec.get("fallbackReasons") or []
check("3.3", "fallbackReasons 不含 BROW_COLOR_UNAVAILABLE",
      not any("BROW_COLOR" in str(x).upper() for x in fb), f"{fb}")

print("\n=== 3.5 avoidedBrands 是硬性排除 ===")
brands = sorted({p.get("brand") for p in prods if p.get("brand")})
target = brands[0] if brands else None
if target:
    st2, b2 = call("POST", "/recommend-products",
                   pkg(recommendationOptions={"avoidedBrands": [target]}))
    p2 = rec_of(b2).get("products") or []
    got = [p.get("brand") for p in p2]
    check("3.5", f"排除 {target} 後結果不含該品牌", target not in got,
          f"回來 {len(p2)} 件，含該品牌 {got.count(target)} 件")

print("\n=== 2.1 輸入驗證 ===")
cases = [
    ("limit 是字串應被拒", pkg(limit="12"), (400, 422)),
    ("limit 超過 50 應被拒", pkg(limit=999), (400, 422)),
    ("limit=0 應被拒", pkg(limit=0), (400, 422)),
    ("analysisPackage 空物件應被拒", {"analysisPackage": {}, "limit": 5}, (400, 422)),
    ("未知 style 應被拒", pkg(analysisPackage={**pkg()["analysisPackage"], "style": "不存在的風格"}), (400, 422)),
    ("lab 只有兩個值應被拒或標成不可信",
     pkg(analysisPackage={**pkg()["analysisPackage"],
                          "faceAnalysis": {"skinTone": {"lab": [65.2, 8.1], "labReliable": True}}}),
     (200, 400, 422)),
]
for name, b, expect in cases:
    s, r = call("POST", "/recommend-products", b)
    code = ((r.get("error") or {}).get("code")) if isinstance(r, dict) else None
    check("2.1", name, s in expect, f"HTTP {s} code={code}")

print("\n=== 2.1 PII 應被拒（IDENTITY_DATA_NOT_ALLOWED）===")
pii = pkg()
pii["analysisPackage"]["email"] = "someone@example.com"
s, r = call("POST", "/recommend-products", pii)
code = (r.get("error") or {}).get("code")
check("六", "夾帶 email 會被擋", s in (400, 422), f"HTTP {s} code={code}")

print("\n=== 四、商品列表 ===")
s, no_limit = call("GET", "/api/products")
check("4.1", "未傳 limit 回 {products:[...]}",
      "products" in no_limit and "nextCursor" not in no_limit, f"鍵={list(no_limit)[:6]}")
s, with_limit = call("GET", "/api/products?limit=5")
check("4.1", "有傳 limit 回 ok/items/products/total/nextCursor",
      all(k in with_limit for k in ("ok", "items", "products", "total", "nextCursor")),
      f"鍵={list(with_limit)}")

# 4.2 四組差異：改值比內容，不看 HTTP 狀態
def ids(path):
    s, d = call("GET", path)
    items = d.get("products") or d.get("items") or []
    return [i.get("id") for i in items], items

lip_ids, lip = ids("/api/products?limit=20&category=lipsticks")
blush_ids, blush = ids("/api/products?limit=20&category=blushes")
check("4.2", "category=lipsticks 與 blushes 結果不同",
      bool(lip_ids) and bool(blush_ids) and set(lip_ids) != set(blush_ids),
      f"唇膏 {len(lip_ids)} 件 / 腮紅 {len(blush_ids)} 件，重疊 {len(set(lip_ids) & set(blush_ids))}")
check("4.2", "category=lipsticks 回來的都是唇膏",
      bool(lip) and all(str(i.get("type")) == "lipsticks" for i in lip),
      f"型別={set(str(i.get('type')) for i in lip)}")

mac_ids, mac = ids("/api/products?limit=20&brand=MAC")
check("4.2", "brand=MAC 回來的都是 MAC",
      bool(mac) and all(str(i.get("brand")).upper() == "MAC" for i in mac),
      f"品牌={set(str(i.get('brand')) for i in mac)}")

in_ids, _ = ids("/api/products?limit=20&inStock=true")
out_ids, _ = ids("/api/products?limit=20&inStock=false")
check("4.2", "inStock=true 與 false 結果不同",
      set(in_ids) != set(out_ids),
      f"true {len(in_ids)} 件 / false {len(out_ids)} 件，重疊 {len(set(in_ids) & set(out_ids))}")

s_none, d_none = call("GET", "/api/products?limit=20&category=不存在的分類")
none_ids = [i.get("id") for i in (d_none.get("products") or d_none.get("items") or [])]
base_ids, _ = ids("/api/products?limit=20")
check("4.2", "不存在的分類回空陣列（不是全庫）",
      s_none == 200 and len(none_ids) == 0,
      f"HTTP {s_none}、{len(none_ids)} 件"
      + ("，與無篩選結果完全相同＝參數被忽略" if none_ids == base_ids else ""))

# 游標分頁真的往前走
p1, _ = ids("/api/products?limit=5")
s, d1 = call("GET", "/api/products?limit=5")
cur = d1.get("nextCursor")
p2, _ = ids(f"/api/products?limit=5&cursor={cur}")
check("4.1", "cursor 取到下一頁（不重疊）",
      bool(p1) and bool(p2) and not (set(p1) & set(p2)), f"第一頁 {p1} → 第二頁 {p2}")

print("\n=== 五、相似商品 ===")
real_id = (no_limit.get("products") or [{}])[0].get("id")
for pid in [real_id, 504]:
    s, d = call("GET", f"/api/products/{pid}/similar?limit=6")
    check("5.1", f"/api/products/{pid}/similar 可用", s == 200,
          f"HTTP {s} code={(d.get('error') or {}).get('code')}")

print("\n=== 六、錯誤格式 ===")
s, d = call("GET", "/api/products/999999")
err = d.get("error") or {}
check("六", "錯誤含 code 與 requestId",
      bool(err.get("code")) and bool(err.get("requestId")),
      f"code={err.get('code')} requestId={'有' if err.get('requestId') else '無'}")
s, d = call("GET", "/api/products?limit=99999")
err = d.get("error") or {}
check("六", "limit 超範圍回 INVALID_LIMIT/INVALID_PAGINATION",
      s in (400, 422), f"HTTP {s} code={err.get('code')}")

ok = sum(1 for *_, o, _ in results if o)
print(f"\n{ok}/{len(results)} 項通過")
fails = [(sec, c, d) for sec, c, o, d in results if not o]
if fails:
    print("\n未通過：")
    for sec, c, d in fails:
        print(f"  [{sec}] {c}   {d}")
