# Ollama 與資料包（analysisPackage）：系統接口全覽

> **這份文件回答一個問題**：資料包從哪裡來、經過誰、被誰讀、被誰改；Ollama 在整條線上出現幾次、
> 每次產出什麼、誰在用。
>
> 最後更新：2026-07-14。所有內容都是從**線上實際跑的程式碼**查證出來的，不是設計文件的理想狀態。

---

## 目錄

1. [兩張總圖](#1-兩張總圖)
2. [資料包是什麼](#2-資料包是什麼)
3. [資料包的完整生命週期](#3-資料包的完整生命週期)
4. [Ollama 的兩個出口](#4-ollama-的兩個出口)
5. [每個接口的詳細規格](#5-每個接口的詳細規格)
6. [渲染 prompt 的安全策略（為什麼後端不信任前端送的 prompt）](#6-渲染-prompt-的安全策略)
7. [歷史演進：這條線被切斷過又接回來](#7-歷史演進)
8. [已知問題與待辦](#8-已知問題與待辦)

---

## 1. 兩張總圖

### 1.1 資料包的流動

```
[使用者上傳自拍]
      │
      ▼
┌─────────────────┐
│ face-basic      │  臉部分析（Cloud Run）
│ /analyze        │  → 回傳中文分析結果
└─────────────────┘
      │
      ▼
┌───────────────────────────────────────────────────┐
│ 前端 AnalysisPackage.fromRawFaceAnalysis()        │
│ 把中文結果正規化成 analysisPackage（資料包誕生）    │
└───────────────────────────────────────────────────┘
      │
      ├──────────────► [localStorage 草稿 AnalysisDraft]
      │
      ├──────────────► ┌─────────────────┐
      │   資料包        │ Ollama /suggest │  文字建議（組員的 Mac）
      │                └─────────────────┘
      │                        │
      │                        ▼ suggestion（中文）＋ renderPromptEn（英文）
      │                ┌───────────────────────────┐
      │                │ 寫回資料包 generativeText │
      │                └───────────────────────────┘
      │
      ├──────────────► ┌─────────────────┐
      │  faceAnalysis  │ 商品推薦服務     │
      │                └─────────────────┘
      │
      └──────────────► ┌─────────────────────────────────────┐
          資料包        │ replicate-render /render            │
        （剔除 images） │ 只讀 faceAnalysis / styleId          │
                       │ ✗ 忽略資料包裡的 renderPromptEn      │
                       └─────────────────────────────────────┘
                                   │
                                   ▼ 後端自己去跟 Ollama 要 prompt
                       ┌─────────────────┐
                       │ Ollama /suggest │  ← 第二次呼叫！
                       └─────────────────┘
                                   │
                                   ▼ renderPromptEn（英文指令）
                       ┌─────────────────────────────┐
                       │ ＋ identity lock（後端疊上） │
                       └─────────────────────────────┘
                                   │
                                   ▼
                       ┌─────────────────┐
                       │ Replicate 生圖   │
                       └─────────────────┘
```

### 1.2 Ollama 被呼叫兩次

```
                      ┌──── 前端呼叫 ────► 拿 suggestion（中文）→ 顯示給使用者看
Ollama /suggest ──────┤
                      └──── render 呼叫 ─► 拿 renderPromptEn（英文）→ 送去生圖
```

**這兩次是獨立的生成。** LLM 每次輸出不完全一樣，所以**畫面上顯示的建議，跟實際渲染用的指令，
是兩次不同生成的產物** —— 大方向一致，細節可能對不起來。
（要解決得靠 HMAC 簽章，見第 6.3 節。）

---

## 2. 資料包是什麼

**`analysisPackage`** 是前端維護的一個 JSON 物件，從臉部分析完成的那一刻誕生，
之後所有服務串接都從它取資料。

程式碼：`analysis_package.py`（後端定義）、`firebase-hosting-full/public/js/api.js` 的
`AnalysisPackage`（前端維護）。

### 2.1 結構

```jsonc
{
  "faceAnalysis": {              // 臉部分析結果（正規化後的英文代碼）
    "version": "BASIC",
    "faceShape": "oval",         // 鵝蛋臉
    "browShape": "arched",       // 彎月眉
    "eyeShape": "almond",        // 杏仁眼
    "noseFront": "standard",     // 標準鼻
    "lipShape": "petal",         // 花瓣唇
    "skinTone": { "season": "spring", "level": "...", "lab": {...} },
    "lipLab": {...},
    "symmetry": {...},
    "raw": { /* face-basic 回傳的完整中文原文 */ }
  },

  "images": {                    // ⚠️ base64 原圖，很大
    "front": { "dataUrl": "data:image/jpeg;base64,...", "compressedDataUrl": "..." }
  },

  "generativeText": {            // Ollama 的產出
    "provider": "ollama",
    "suggestion": "1. 整體妝容方向\n\n寶寶，妳想做...",   // 中文建議（給人看）
    "renderPromptEn": "Apply a soft baddie makeup look...", // 英文指令
    "ollamaRenderPromptEn": "...",
    "status": "completed"
  },

  "recommendations": { "style": "Soft Baddie", ... },   // 商品推薦

  "render": {                    // 渲染結果
    "status": "completed",
    "styleId": "softBaddie",
    "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/...",
    "renderPrompt": "...",       // 實際送給模型的指令（後端回傳）
    "promptSource": "ollama"     // 'ollama' 或 'style_allowlist'
  },

  "updatedAt": "2026-07-14T..."
}
```

### 2.2 它被存在哪

| 位置 | 說明 |
|---|---|
| `Router.analysisPackage` | 前端記憶體，頁面間傳遞用 |
| `localStorage` (`beautyAnalysisDraft`) | 草稿，重新整理不會遺失（`AnalysisDraft.save()`） |
| 收藏的 look | 收藏妝容對比圖時整包存下來 |

**前端 `router.js` 引用它 61 次** —— 它是整個前端的狀態核心，不只是傳輸格式。

---

## 3. 資料包的完整生命週期

| 階段 | 誰動它 | 動了什麼 |
|---|---|---|
| **1. 誕生** | 前端 `AnalysisPackage.fromRawFaceAnalysis()` | 把 face-basic 的中文結果正規化，填入 `faceAnalysis`、`images` |
| **2. 加建議** | 前端呼叫 Ollama `/suggest` 後 | 填入 `generativeText.suggestion` 與 `renderPromptEn` |
| **3. 加推薦** | 前端呼叫商品推薦服務後 | 填入 `recommendations` |
| **4. 渲染** | 前端送資料包給 render，拿回結果後 | 填入 `render.afterImageUrl` / `renderPrompt` / `promptSource` |
| **5. 收藏** | 使用者按「收藏妝容對比圖」 | 整包存進 look 紀錄 |

---

## 4. Ollama 的兩個出口

Ollama 建議服務（`Ollama_suggestion.py`）跑在**組員的 Mac** 上，透過 **Cloudflare tunnel** 對外。

> ⚠️ **tunnel 網址一重啟就換。** 前端的 `config.local.js` 和 render 服務的
> `SUGGESTION_SERVICE_URL` 環境變數都要跟著更新，否則個人化建議/指令會失效。

### 4.1 出口一：給前端（顯示用）

```
前端 Api.suggestMakeup()
  → POST {tunnel}/suggest
  → body: { analysisPackage, faceAnalysis, style, language: 'zh-TW', userNote }
  → 回傳: { suggestion, renderPromptEn, fluxPromptEn, model, ... }
  → 前端只取 suggestion，寫進資料包，顯示在 compare 頁的「Ollama 妝容建議」
```

### 4.2 出口二：給渲染服務（生圖用）

```
replicate-render 收到 /render 請求
  → 從資料包讀出 faceAnalysis + styleId
  → POST {tunnel}/suggest   ← render 服務自己呼叫，不是前端轉送
  → body: { faceAnalysis, style }
  → 回傳: { renderPromptEn, ... }
  → 取 renderPromptEn，疊上 identity lock，送給 Replicate
```

程式碼：`replicate_render.fetch_ollama_render_prompt()` / `build_personalized_render_prompt()`

### 4.3 Ollama 產出的三個欄位

| 欄位 | 語言 | 用途 | 誰在用 |
|---|---|---|---|
| `suggestion` | 中文 | 給使用者看的妝容建議（六段式） | **前端顯示** |
| `renderPromptEn` | 英文 | 給圖像模型的渲染指令 | **render 服務** |
| `fluxPromptEn` | 英文 | 給 Flux 模型的指令 | 目前**沒有人用** |

> **注意**：`Ollama_suggestion.py` 在 repo 裡的版本**沒有** `renderPromptEn` / `fluxPromptEn`
> 這兩個欄位，但線上服務會回傳它們 —— **組員 Mac 上跑的是跟 repo 不同的版本**。
> 你 review repo 的 Ollama 程式碼時，看到的不是線上真相。

---

## 5. 每個接口的詳細規格

### 5.1 臉部分析 face-basic

```
POST https://face-basic-eu5pq7c53a-de.a.run.app/analyze
Header: x-api-key: <FACE_API_KEY>
Body:   multipart/form-data { file: <圖片> }

回傳:
{
  "分析版本": "BASIC",
  "臉型": "鵝蛋臉", "眉型": "彎月眉", "眼型": "杏仁眼",
  "鼻型": "標準鼻", "嘴型": "花瓣唇",
  "膚色": {...}, "嘴唇_LAB": {...}, "臉部對稱性": {...},
  "分類來源": {            // 2026-07-13 新增：每個欄位最後聽誰的
    "臉型": { "final": "roi_cnn", "modelLabel": "鵝蛋臉",
              "modelConfidence": 0.89, "ruleLabel": "圓形臉" }
  }
}
```

> 這五個欄位現在由 **ROI CNN** 提供（規則式退居 fallback）。
> 詳見 `CNN訓練歷程_BASIC五官分類.md`。

**資料包關係**：前端把這包丟給 `AnalysisPackage.fromRawFaceAnalysis()`，
正規化成 `faceAnalysis`（中文 → 英文代碼），原文保留在 `faceAnalysis.raw`。

---

### 5.2 Ollama 文字建議

```
POST {tunnel}/suggest
Header: X-API-Key: <textSuggestionApiKey>
Body:
{
  "analysisPackage": { ... },     // ← 整包送
  "faceAnalysis": { ... },        // ← 也單獨送一份（後端二選一都能讀）
  "style": "Soft Baddie",
  "language": "zh-TW",
  "userNote": "柔霧底妝、甜酷氛圍"
}

回傳:
{
  "status": "completed",
  "provider": "ollama",
  "model": "...",
  "suggestion": "1. 整體妝容方向\n\n寶寶，妳想做 Soft baddie 風格...",
  "renderPromptEn": "Apply a soft baddie makeup look to this person...",
  "fluxPromptEn": "..."
}
```

**Ollama 收到的 prompt 要求**（`Ollama_suggestion.build_prompt()`）：

```
必須且只能分為六個段落：
  1. 整體妝容方向   2. 底妝建議   3. 眉眼妝建議
  4. 唇妝建議       5. 避免事項   6. 總結與建議
總字數 350 ~ 1050 中文字
```

> ⚠️ **實測：輸出會被截斷。** 實際只跑到第 5 段（唇妝建議）就斷在句子中間，
> **「避免事項」和「總結與建議」從來沒出現過**。這是 Ollama 的輸出長度上限卡住了。

---

### 5.3 商品推薦

```
POST {tunnel}/recommend
Body: { faceAnalysis: {...}, styleId: "softBaddie" }
```

**只送 `faceAnalysis`，不送整包。**

---

### 5.4 AI 渲染 replicate-render

```
POST https://replicate-render-eu5pq7c53a-de.a.run.app/render
Header: X-API-Key: <renderApiKey>
Body:
{
  "image": "data:image/jpeg;base64,...",   // 圖片單獨送
  "styleId": "softBaddie",
  "strength": 0.35,
  "analysisPackage": { ...，images 已剔除 }  // ← 2026-07-14 起改收資料包
}

回傳:
{
  "status": "completed",
  "afterImageUrl": "https://storage.googleapis.com/decorate-me-renders/...",
  "renderPrompt": "Apply a soft baddie makeup look... [＋identity lock]",
  "promptSource": "ollama",     // 或 "style_allowlist"（Ollama 沒回應時）
  "model": "...",
  "isPermanent": true
}
```

**後端從資料包讀什麼**（`replicate_render_api._render_inputs()`）：

| 讀取 | 用途 |
|---|---|
| `analysisPackage.faceAnalysis` | 送給 Ollama 產生個人化指令 |
| `analysisPackage.render.styleId` | 風格（若請求沒直接給 styleId） |
| ~~`analysisPackage.generativeText.renderPromptEn`~~ | **刻意忽略！見第 6 節** |

**非同步版本**（前端實際用的）：

```
POST /render/jobs   → 回 { jobId, resultToken, renderPrompt, promptSource, estimatedSeconds }
GET  /render/jobs/{jobId}  → 輪詢，回 { status, progress, afterImageUrl, ... }
```

> 渲染要 50~150 秒（Replicate 轉手 OpenAI 排隊），所以走非同步。
> Cloud Run 必須開 `--no-cpu-throttling`，否則背景 thread 會被凍住。

---

## 6. 渲染 prompt 的安全策略

### 6.1 為什麼後端不信任資料包裡的 renderPromptEn

資料包裡**明明有** `generativeText.renderPromptEn`，render 服務也**確實收到了整包**，
但它**刻意不讀那個欄位**。原因：

**`renderApiKey` 是明文寫在 `https://decorate-me.web.app/config.local.js` 的第 9 行**，
任何人打開瀏覽器看原始碼就拿得到。

如果 render 照著資料包裡的 prompt 渲染，那麼任何人都可以：

```
1. 打開網頁，複製 renderApiKey
2. 自己組一個資料包，renderPromptEn 塞任何他想要的內容
3. POST /render
4. 用你的 Replicate 額度生成任何圖片
```

**`styleId` 白名單是目前唯一擋住這件事的防線。** 拆掉它，等於把付費的圖像生成 API 對全世界開放。

### 6.2 現在的做法

```
前端 ──[資料包（含 renderPromptEn，但會被忽略）]──► render 服務
                                                      │
                                                      │ 只讀 faceAnalysis + styleId
                                                      ▼
                                              自己去跟 Ollama 要 renderPromptEn
                                                      │
                                                      ▼
                                        ＋ identity lock（後端自己疊，
                                          不讓外部模型決定能不能改變這個人的長相）
                                                      │
                                                      ▼
                                                  Replicate
```

**Ollama 掛掉時**（tunnel 換網址、Mac 關機）→ 靜默退回 `styleId` 白名單的固定 prompt，
渲染不會失敗，前端會顯示 `［固定風格指令：建議服務沒回應，已退回白名單］`。

### 6.3 如果要讓前端送的 prompt 也能被信任：HMAC 簽章

這是**唯一能同時滿足「前端送 prompt」與「不被竄改」的做法**：

```
1. Ollama 產生 renderPromptEn
2. Ollama 用共用密鑰算簽章： signature = HMAC_SHA256(SECRET, renderPromptEn)
3. 回傳 { renderPromptEn, promptSignature } → 進資料包
4. 前端把資料包送給 render（照原本的架構）
5. render 用同一把密鑰重算 HMAC，比對簽章
     ├─ 相符 → 這確實是 Ollama 產生的，照用
     └─ 不符 → 有人竄改，拒絕
```

前端拿不到 `SECRET`，所以**編不出有效簽章**。

**好處**：Ollama 只需生成一次（現在是兩次），畫面顯示的建議與實際渲染的指令保證同源。

**阻礙**：需要**組員在 Ollama 服務加簽章程式碼**，並跟 render 共用同一把密鑰。
而且組員 Mac 上的 Ollama 版本跟 repo 不同步，改動無法透過 repo 交付。

---

## 7. 歷史演進

這條線被切斷過，又接回來：

| 時間 | 事件 |
|---|---|
| **早期** | Ollama 把英文指令黏在中文建議尾巴（「第二部分」）。前端用 `splitOllamaTwoPartSuggestion()` 切出來 → `buildRenderPrompt()` 組合 → **送給 render**。渲染吃得到個人化指令。 |
| **2026-07-13 19:27**<br>`989c522` | **"Move render prompts behind backend policy"**：為了防 prompt 注入，前端改成只能送 `styleId`，後端從白名單取固定 prompt。<br>➜ **副作用：Ollama 的個人化指令從此無人使用**，每個選同一風格的人送出的 prompt 一模一樣。 |
| **2026-07-13**<br>`a117a25` | render 服務**自己**去跟 Ollama 要 `renderPromptEn`。個人化指令回來了，但前端仍不能送 prompt（安全防線保留）。 |
| **2026-07-14**<br>`1032221` | render 改收 `analysisPackage`，與其他串接一致。資料包裡的 `renderPromptEn` 仍然忽略。 |

> **`splitOllamaTwoPartSuggestion()` 現在是遺骸** —— Ollama 已改成把英文放在獨立的
> `renderPromptEn` 欄位，不再黏在中文後面。那個函式留著只是防舊資料，實際上不會觸發。

---

## 8. 已知問題與待辦

| # | 問題 | 影響 | 建議 |
|---|---|---|---|
| 1 | **Ollama 被呼叫兩次**（前端一次、render 一次） | 兩次生成內容有細節差異：**畫面顯示的建議 ≠ 實際渲染用的指令** | 做 HMAC 簽章（6.3），讓 Ollama 只生成一次 |
| 2 | **Ollama 輸出被截斷** | 六段只跑到第五段，「避免事項」「總結與建議」從未出現 | 調高 Ollama 的 `num_predict`（在組員機器上） |
| 3 | **組員 Mac 上的 Ollama 版本 ≠ repo** | repo 裡的 `Ollama_suggestion.py` 沒有 `renderPromptEn`，但線上有 | 請組員把版本推回 repo |
| 4 | **Cloudflare tunnel 網址一重啟就換** | 前端 `config.local.js` 與 render 的 `SUGGESTION_SERVICE_URL` 都要手動更新，否則個人化失效（會靜默退回固定 prompt） | 把 Ollama 搬到固定網址，或改用 Cloudflare 具名 tunnel |
| 5 | **`fluxPromptEn` 沒有人用** | Ollama 白白生成一段沒人要的內容 | 確認是否還需要，不需要就從 Ollama 的 prompt 拿掉 |
| 6 | **API key 明文公開在前端** | 任何人都能拿到 `faceApiKey` / `renderApiKey` / `textSuggestionApiKey` | 純靜態前端無解，要靠 Firebase App Check / 驗 Origin / 配額上限 |
| 7 | **兩份前端分歧** | 線上跑 `firebase-hosting-full/`，OneDrive 的 `web_frontend/` 是另一版（還在送 prompt） | 收斂成一份 |

---

## 相關文件

- `CNN訓練歷程_BASIC五官分類.md` —— face-basic 的五官分類模型（CNN 取代規則式）
- `規則式閾值Bug_完整診斷記錄_新手版.md` —— 規則式為什麼壞掉、怎麼修
- `模型紀錄書_BASIC五官分類.md` —— 三個分類方案的成績對照
- `OLLAMA_DATA_PACKET_INTEGRATION_SPEC.md` —— 資料包的原始規格書
