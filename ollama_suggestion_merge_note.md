# Ollama_suggestion.py 合體版說明

## 背景

本次整合了兩份 `Ollama_suggestion.py`：

- **Isa 版（主版本）**：彈性 schema、中英文 key 都接受、搭配前端 `js/api.js` 的 `analysisPackage` 封包
- **Amy 版（`Amy` 分支 `0510/` 資料夾）**：嚴格 Pydantic 驗證、英文 enum 代碼、豐富的妝容知識庫

合體原則：**以 Isa 版為主體架構，把 Amy 版的妝容知識庫完整整合進來**。

---

## 主要更改細節

### 1. Schema 驗證：維持 Isa 版的彈性設計

Amy 版使用嚴格 Pydantic 模型（`FaceAnalysis`、`AnalysisPackage`），要求所有欄位必須是英文 enum 代碼，例如：

```python
# Amy 版 — 必須這樣送
faceShape: Literal["oval", "round", "square", ...]
skinTone.season: Literal["spring", "summer", "autumn", "winter", "unknown"]
```

**合體版維持 Isa 版的彈性 dict：**

```python
class SuggestRequest(BaseModel):
    analysisPackage: dict[str, Any] | None = None
    faceAnalysis: dict[str, Any] | None = None
    style: str | None = Field(default="日常自然妝")
    language: str | None = Field(default="zh-TW")
    userNote: str | None = None
    model: str | None = None
```

前端送中文字串（如 `"橢圓形"`）或英文 enum（如 `"oval"`）都能正常處理，不會被 Pydantic 拒絕。

---

### 2. 新增：`_map_or_raw()` 橋接函式

為了讓知識庫可以同時吃兩種格式，新增了一個橋接函式：

```python
def _map_or_raw(value: str, mapping: dict) -> str:
    if not value or value == "未提供":
        return value
    return mapping.get(value, value)
```

**運作邏輯：**

- 前端送 `"oval"` → `MAP_FACE["oval"]` → `"鵝蛋臉"` → 進入知識庫邏輯
- 前端送 `"鵝蛋臉"` → `MAP_FACE` 查不到 → 直接用 `"鵝蛋臉"` → 進入知識庫邏輯

兩條路都能正確導向同一個知識庫。

---

### 3. 新增：妝容知識庫（從 Amy 版整合）

從 Amy 版的 `analysis_package.py` 完整搬入：

```python
MAKEUP_DATABASE   # 每種風格的詳細底妝、眼妝、腮紅、唇妝配方
MAP_FACE / MAP_BROW / MAP_EYE / MAP_NOSE / MAP_LIP / MAP_SEASON  # 英文 enum → 中文對照
FACE_LOGIC / EYEBROW_LOGIC / EYE_LOGIC / NOSE_LOGIC / LIP_LOGIC / SKIN_LOGIC  # 特徵描述
FACE_METHOD / EYEBROW_METHOD  # 臉型/眉型對應具體技法
```

---

### 4. 風格名稱對齊前端 `data.js`

Amy 版的 `MAKEUP_DATABASE` key 與前端實際傳來的 `style` 字串不一致，已全部對齊：

| Amy 版 key | 合體版 key（對齊前端） |
|---|---|
| `"Soft baddie"` | `"Soft Baddie"` |
| `"韓系亞裔妝"` | `"韓系亞裔"` |
| `"日雜清透妝"` | `"日雜清透"` |
| `"千金妝"` | `"千金"` |
| `"港風妝"` | `"港風"` |
| `"病嬌妝"` | `"病嬌"` |

---

### 5. 新增：`男士白開水` 風格

Amy 版沒有這個風格。合體版根據前端 `js/data.js` 的 `advice` 欄位補入：

```python
"男士白開水": {
    "description": "保留男性原生輪廓與肌膚質感...",
    "base_detail": "局部遮瑕並薄透均勻膚色，保留自然肌理，T 字輕微控油。",
    "eye_layers": "使用霧面淺棕輕掃眼窩與下眼尾，不堆疊珠光，避免明顯眼線。",
    "blush_detail": "以低飽和裸杏色少量修飾氣色，也可依膚況省略。",
    "lip_detail": "使用透明護唇或低彩度裸豆沙色，修飾唇色不製造明顯妝感。",
    ...
}
```

---

### 6. `build_prompt` 升級：加入知識庫上下文

Isa 原版的 `build_prompt` 只送原始特徵給 model，沒有技法指引。

合體版參考 Amy 版的 `compile_prompts` 架構，讓 prompt 帶入完整技法：

```
[五官膚色特徵摘要]: 臉型：鵝蛋臉（比例完美流暢）、眉型：一字眉（眉型平直無邪）...
[目標風格設定]: 韓系亞裔（風格特點：融合韓式清透...；推薦色彩：低飽和粉棕系）

【專屬技法融合指引】:
- 底妝：針對春季型特性，打造柔焦感的輕霧面底妝...
- 眉毛：執行縮短中庭，眉尾拉平。
- 眼妝：步驟為先使用灰感粉棕色...
- 腮紅/修容：輕掃下顎線...腮紅斜向掃在顴骨下方...
- 唇妝：選擇霧面莫蘭迪粉色...
```

並加入格式限制，避免 model 輸出星號或 Markdown 符號。

---

### 7. `build_render_prompt` 升級：加入風格配方

Isa 原版 render prompt 只送原始特徵。合體版加入風格配方的英文說明，讓渲染端有更明確的技法指引：

```
Style foundation: 柔焦感的輕霧面底妝，呈現勻稱精緻的膚色。
Style eye technique: 先使用灰感粉棕色在整個眼皮進行大面積消腫...
Style blush placement: 與眼妝色調統一，斜向掃在顴骨下方。
Style lip finish: 選擇霧面莫蘭迪粉色...
```

---

## 不變的部分

- `/health` 端點格式完全不變
- `/suggest` 端點回傳格式完全不變（`status`, `suggestion`, `renderPromptEn`, `createdAt` 等）
- `dev_server_utils.py` 完全不變
- 啟動指令不變：`python Ollama_suggestion.py`（port 8010）
- 前端 `js/api.js` 不需要任何修改

---

## 給 Amy 的換檔步驟

1. 把 `Ollama_suggestion.py` 和 `dev_server_utils.py` 複製到妳的專案資料夾
2. 把原本的 `analysis_package.py` 移除（知識庫已整合進主檔，不再需要）
3. `requirements.txt` 確認有 `fastapi`、`uvicorn`、`requests`、`pydantic`
4. 啟動：`python Ollama_suggestion.py`
5. 健康檢查：`GET http://127.0.0.1:8010/health`

---

## 測試封包範例

```json
POST /suggest

{
  "faceAnalysis": {
    "version": "BASIC",
    "faceShape": "oval",
    "browShape": "straight",
    "eyeShape": "almond",
    "noseFront": "standard",
    "lipShape": "thin",
    "skinTone": { "season": "spring", "level": "白皙" },
    "sidePhotoUsed": false
  },
  "style": "韓系亞裔",
  "language": "zh-TW",
  "userNote": "希望看起來自然清透"
}
```

中文字串也可以直接送，一樣有效：

```json
{
  "faceAnalysis": {
    "臉型": "橢圓形",
    "眉型": "平眉",
    "眼型": "杏眼",
    "鼻型": "小巧鼻",
    "嘴型": "薄唇",
    "膚色": { "season": "spring" }
  },
  "style": "韓系亞裔"
}
```
