# renderPromptEn 修復建議（給 Ollama 服務維護者）

> 文件版本：`2026-07-06`
> 問題回報對象：`Ollama_suggestion.py`（或線上實際部署的等價服務）維護者
> 相關訊息：語辰同學曾表示前端只要抓 `res.data.fluxPromptEn` 就能拿到「簡潔精準」的英文 render prompt，但實測結果跟這個描述對不上，見下方問題。

## 一、問題現況（附實測證據）

線上服務（`https://morning-deeper-kick-medium.trycloudflare.com/suggest`）目前會在回應裡多回傳一個 `renderPromptEn` 欄位。實測發現這個欄位有兩種失敗模式：

### 問題 1：內容空洞，沒有具體妝容描述

風格 `日常自然妝` / `港風` 實測得到：

```
Apply deep optimized individual layout for requested 日常自然妝.
Apply deep optimized individual layout for requested 港風妝.
```

「deep optimized individual layout」是語意上完全空洞的詞組，沒有任何顏色、技法、部位資訊，圖像生成模型（flux-kontext-pro）拿到這種指令等於沒有明確的妝容指示。

### 問題 2：內容跟選擇的風格完全對不上

風格 `男士白開水`（設計上應該是「乾淨清爽、幾乎不上妝」）實測得到：

```
high quality makeup, natural skin, matte foundation, light brown eyebrows,
soft peach eyeshadow, subtle peach blush, glossy gradient lips, cherry lip gloss,
flawless skin, localized makeup rendering, clean makeup, minimalist makeup,
subtle contouring, light skin tone, water skin texture, youthful appearance
```

這裡出現 `eyeshadow`（眼影）、`blush`（腮紅）、`glossy gradient lips`、`cherry lip gloss`（漸層唇、唇蜜）—— 都是明顯的女性濃妝元素，跟「男士白開水：不著妝為目標」的風格定位完全矛盾。這代表目前 `renderPromptEn` 的生成邏輯**沒有真的根據 `style` 參數調整內容**，可能是不管選哪個風格都套用類似的通用化妝詞彙。

## 二、根本原因判斷

`Ollama_suggestion.py` 現有的中文建議生成邏輯（`build_prompt()` + `MAKEUP_DATABASE`）其實設計得很好——每個風格都有明確區分的 `eye_layers`、`base_detail`、`lip_detail`、`blush_detail`、`custom_tip`，「男士白開水」也正確寫著「整體以不著妝為目標」。

問題出在：**`renderPromptEn` 目前很可能是另外拿 LLM 自由生成／翻譯出來的**，而不是照著這份已經設計好的結構化知識庫組出來的。LLM 自由發揮翻譯英文 prompt，容易出現：
- 空話（deep optimized individual layout 這種完全不具體的詞）
- 沒有真的把 style 差異帶進去（風格知識庫的內容沒被引用到）

## 三、建議修法：不要再讓 LLM 生成 renderPromptEn，改成規則式組裝

比照中文 `MAKEUP_DATABASE` 的結構，另外建一份**已經翻好、每個風格固定的英文關鍵詞表**，`renderPromptEn` 直接查表組出來，完全不經過 LLM 的自由發揮。這樣做的好處：

- 100% 不會出現空話，因為內容是人工先寫好、驗證過的
- 保證每個風格的英文描述都跟中文知識庫的風格定位一致（尤其「男士白開水」這種需要刻意「淡化妝感」的風格）
- 少一次 LLM 呼叫，速度更快、更穩定

### 建議程式碼（可直接放進 `Ollama_suggestion.py`）

```python
# ═══ 英文渲染關鍵詞表：對應 MAKEUP_DATABASE 的風格，人工先翻好、不經過 LLM ═══
EN_RENDER_KEYWORDS = {
    "日常自然妝": [
        "dewy natural glass-skin base", "soft peach eyeshadow wash",
        "brown eyeshadow used instead of eyeliner", "glossy tea-brown lip tint",
        "bright peach blush across cheeks",
    ],
    "Soft Baddie": [
        "glossy cream skin with cool blue-toned highlight", "smoky cocoa-brown eyeshadow blended from outer corner",
        "starlight blue shimmer at inner corner", "cinnamon matte gradient lip",
        "soft pink blush on apples of cheeks",
    ],
    "韓系亞裔": [
        "soft matte de-puffed base", "cool taupe-brown smoky eyeshadow",
        "ivory matte inner-corner highlight", "muted mauve blurred-edge gradient lip",
        "low-saturation blush swept below cheekbone",
    ],
    "日雜清透": [
        "airy dewy cream-finish skin", "soft apricot eyeshadow wash",
        "brown eyeshadow used instead of eyeliner", "glossy tea-brown lip tint",
        "bright peach blush across cheeks",
    ],
    "千金": [
        "porcelain glossy skin with pearl highlight on brow bone and cheekbone",
        "champagne gold eyeshadow with deep cocoa upturned eyeliner", "silver glitter on lower lash line",
        "dewy soft pink gradient lip", "sakura pink blush swept upward on smile muscle",
    ],
    "港風": [
        "matte porcelain fully-contoured base", "charcoal-brown smoky eyeshadow half-halo along lash line",
        "bold classic matte red lip with precise liner", "low-saturation contour blush blended to hairline",
        "thick defined brows for strong color contrast with red lip",
    ],
    "病嬌": [
        "extremely pale matte skin with feverish flush", "smoky dusty-rose eyeshadow concentrated on lower lid",
        "deep wine bitten-lip gradient effect", "blush placed high, directly under the eyes",
        "wet clumped lashes for fragile delicate look",
    ],
    "男士白開水": [
        "sheer skin-like base with no visible coverage, natural texture preserved",
        "soft brown eyeshadow wash only, absolutely no eyeliner and no shimmer",
        "clear lip balm or barely-there nude tint, no obvious lip color change",
        "minimal low-saturation blush, may be omitted entirely",
        "no-makeup-makeup look: the goal is looking like nothing was applied",
    ],
}

def build_render_prompt_en(payload: SuggestRequest) -> str:
    style = payload.style or "日常自然妝"
    keywords = EN_RENDER_KEYWORDS.get(style, EN_RENDER_KEYWORDS["日常自然妝"])
    return ", ".join(keywords)
```

然後在 `/suggest` 回應裡把這個結果放進 `renderPromptEn`：

```python
return {
    "status": "completed",
    "provider": "ollama",
    "model": model,
    "fallbackUsed": False,
    "createdAt": _now_iso(),
    "suggestion": suggestion,
    "renderPromptEn": build_render_prompt_en(payload),  # 新增，規則式組裝，不經過 LLM
}
```

## 四、驗收標準

修好之後，麻煩實測以下兩個風格，確認：

1. `日常自然妝` / `港風`：`renderPromptEn` 應該包含具體顏色與技法詞彙，不會出現「deep optimized individual layout」這種空話。
2. `男士白開水`：`renderPromptEn` 絕對不能出現 `eyeshadow`（明顯眼影）、`blush`（腮紅，除非明確寫「minimal/may be omitted」）、`lip gloss`/`gradient lip`（唇蜜/漸層唇）這些明顯濃妝詞彙，應該要是「no eyeliner」「barely-there」「no-makeup-makeup」這類詞彙。

前端這邊已經改成優先採用 `renderPromptEn`（沒有才 fallback），只要這個欄位品質穩定，就不需要前端再做任何調整。
