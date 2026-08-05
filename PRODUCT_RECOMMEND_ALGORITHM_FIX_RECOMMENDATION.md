# 商品推薦演算法優化建議（給商品資料庫維護者）

> 文件版本：`2026-07-07`
> 問題回報對象：`/recommend-products` 服務維護者
> 相關端點：`POST https://<你們的網址>/recommend-products`

## 一、問題現況（附實測證據）

前端呼叫 `/recommend-products` 時會帶 `faceShape`、`eyeShape`、`skinTone`（含 `season`/`level`/`lab`）、`lipLab`、`style` 這幾個欄位。**`style` 目前完全沒有被拿來影響推薦結果。**

實測：同一組臉部/膚色/唇色資料，只把 `style` 從 `"港風"` 換成 `"韓系亞裔"`，兩次呼叫回傳的 **12 筆商品一模一樣，連排序都相同**：

```json
// style: "港風"（復古濃烈風）
{"category":"lip","name":"情挑誘光水唇膏 - 205純慾赤裸(明星色)", "matchReason":"接近你的柔和唇色，能保留自然氣色"}
{"category":"base","name":"恆久完美無瑕持妝粉底 - LC6", "matchReason":"貼近你的暖調春季膚色，適合作為底妝色選"}
{"category":"eye","name":"heme 六色眼影盤 – 杏桔 9g", "matchReason":"和你的臉部色彩溫度相容，適合搭配春季風格眼妝"}
... (共12筆)

// style: "韓系亞裔"（清透自然風）—— 完全相同的 12 筆，順序也一樣
{"category":"lip","name":"情挑誘光水唇膏 - 205純慾赤裸(明星色)", "matchReason":"接近你的柔和唇色，能保留自然氣色"}
{"category":"base","name":"恆久完美無瑕持妝粉底 - LC6", "matchReason":"貼近你的暖調春季膚色，適合作為底妝色選"}
{"category":"eye","name":"heme 六色眼影盤 – 杏桔 9g", "matchReason":"和你的臉部色彩溫度相容，適合搭配春季風格眼妝"}
... (共12筆，一字不差)
```

觀察 `matchReason` 的用詞：全部都只提到「暖調春季膚色」「春季風格眼妝」——這代表目前只有 `skinTone.season` 在影響 `eye` 類別的推薦，跟真正的 `style`（使用者選的妝容風格，例如港風/韓系/日常自然妝）完全無關。

## 二、目前哪些部分是對的，不用動

- **`base`（底妝）跟 `lip`（口紅）類別的顏色比對邏輯是合理的**：`matchReason` 有正確反映 `skinTone.lab` 和 `lipLab` 的比對結果（暖調春季膚色配暖色系底妝、柔和唇色配對應唇膏），這塊不用改。

## 三、建議修法：把推薦拆成兩條邏輯

### 3.1 顏色比對類（沿用現有邏輯，不用改）
- **`base`（底妝）**：用 `skinTone.lab` 算 ΔE 找最接近的粉底色號
- **`lip`（口紅）**：用 `lipLab` 算 ΔE 找最接近的唇膏色號

### 3.2 風格比對類（目前完全沒做，需要新增）
- **`eye`（眼影）、`brow`（眉彩）、`blush`（腮紅）、`contour`（修容）、`highlight`（打亮）** 這幾類，應該要依照 `style` 篩選/排序，而不是只看膚色溫度。

建議做法：比照 `base`/`lip` 已經在用的 `tags` 欄位（實測看到商品本身有 `tags: ["base","light","warm","foundations"]` 這種結構），幫每個 `style` 建一份對應的關鍵字/tag 清單，篩選出符合的商品再依 ΔE 排序：

```python
# 範例：style → 對應商品 tag 的權重表（實際 tag 名稱請對照你們資料庫現有的 tags 欄位調整）
STYLE_TAG_MAP = {
    "港風": ["bold", "dramatic", "smoky", "red", "defined"],
    "韓系亞裔": ["sheer", "dewy", "natural", "soft", "light"],
    "日常自然妝": ["natural", "light", "soft", "sheer"],
    "千金": ["luxury", "shimmer", "soft", "pearl"],
    "Soft Baddie": ["smoky", "bold", "glossy"],
    "日雜清透": ["sheer", "dewy", "natural", "soft"],
    "病嬌": ["pale", "soft", "rosy"],
    "男士白開水": ["natural", "minimal", "no-makeup"],
}

def recommend_eye_brow_blush(style, skin_tone, candidates):
    wanted_tags = set(STYLE_TAG_MAP.get(style, []))
    scored = []
    for product in candidates:
        tag_overlap = len(wanted_tags & set(product["tags"]))
        color_score = compute_delta_e(skin_tone, product)  # 沿用現有的顏色比對
        # 風格符合度優先，同分再比顏色接近程度
        scored.append((tag_overlap, -color_score, product))
    scored.sort(reverse=True)
    return [p for _, _, p in scored]
```

## 四、驗收標準

修好之後，麻煩實測：同一組膚色/唇色資料，只換 `style` 參數（例如 `港風` vs `韓系亞裔`），確認：

1. `base`／`lip` 類別的推薦結果可以維持不變（顏色比對邏輯不變，本來就對）。
2. `eye`／`brow`／`blush`／`contour`／`highlight` 類別的推薦結果**必須不一樣**，且風格對得起來——`港風` 應該推薦大地色系/煙燻/正紅這類濃烈商品，`韓系亞裔` 應該推薦裸色/清透/水潤這類自然商品。

前端這邊不需要改動，`style` 欄位本來就有正確傳送，只等後端把這個欄位真正用起來。
