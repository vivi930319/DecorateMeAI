# Ollama 渲染指令簽章：端對端密鑰規格書

> **給誰看**：Ollama 建議服務的維護者（組員）＋ 渲染服務維護者。
> **要解決什麼**：讓前端可以把 Ollama 產生的 `renderPromptEn` 送給渲染服務，
> 而渲染服務**能確認它真的是 Ollama 產生的、沒有被竄改**。
>
> 實作完成後，Ollama 只需生成一次（現在是兩次），畫面上顯示的建議與實際渲染的指令保證同源。

---

## 1. 為什麼需要簽章

### 1.1 現在的問題

渲染服務**收得到**資料包裡的 `renderPromptEn`，但**刻意不用它**，而是自己再打一次 Ollama。
原因只有一個：

**`renderApiKey` 是明文寫在 `https://decorate-me.web.app/config.local.js` 第 9 行的。**
任何人打開瀏覽器看網頁原始碼就拿得到。

所以如果渲染服務照著前端送來的 prompt 生圖：

```
任何人都可以：
  1. 打開網頁，複製 renderApiKey
  2. 自己組一個 JSON，renderPromptEn 塞任何他想要的內容
  3. POST /render
  4. 用我們的 Replicate 額度生成任何圖片（費用我們付、內容我們扛）
```

目前擋住這件事的唯一防線是 **styleId 白名單**（只接受 8 個預設風格，不接受自由文字）。

### 1.2 簽章解決什麼

**簽章讓「前端可以送 prompt」和「前端不能偽造 prompt」同時成立。**

```
Ollama 產生 prompt 時，用一把只有後端知道的密鑰算出一段簽章一起回傳。
渲染服務收到 prompt + 簽章後，用同一把密鑰重算一次，比對結果。

  簽章相符 → 這段 prompt 確實出自 Ollama，可以信任
  簽章不符 → 有人動過手腳，拒絕
```

**前端拿不到密鑰，所以它可以「轉送」prompt，但無法「偽造」prompt。**

---

## 2. 密鑰

### 2.1 產生

由**專案負責人產生一次**，然後分發給兩個服務。任何一方都不要自己另外產生。

```bash
# 產生一把 32 bytes（256 bit）的隨機密鑰，輸出成 hex 字串
python -c "import secrets; print(secrets.token_hex(32))"

# 範例輸出（請勿使用這一把，自己產生）：
# 8f3a9c2e5b1d47a06e8c1f9b3d5a7e2c4f6b8d0a2c4e6f8a0b2d4f6a8c0e2f4b
```

### 2.2 保管規則

| 規則 | 說明 |
|---|---|
| **不進 git** | 任何 repo、任何分支、任何 commit 都不能有它 |
| **不進前端** | 前端**永遠不需要**這把密鑰。它出現在前端的那一刻，整個機制就失效了 |
| **只放在兩個地方** | ① Ollama 服務的環境變數 ② 渲染服務的環境變數 |
| **兩邊必須完全一致** | 差一個字元、多一個空白、大小寫不同 → 簽章永遠對不上 |
| **外洩就換掉** | 換密鑰時兩邊要同時換，中間會有短暫的驗證失敗（會自動退回白名單風格，不會壞） |

### 2.3 環境變數名稱（兩邊統一）

```bash
RENDER_PROMPT_SIGNING_SECRET=<那一長串 hex>
```

**Ollama 服務**（組員的 Mac）：寫進 `.env` 或啟動時 export
**渲染服務**（Cloud Run）：

```bash
gcloud run services update replicate-render \
  --region asia-east1 \
  --update-env-vars RENDER_PROMPT_SIGNING_SECRET=<那一長串 hex>
```

---

## 3. 簽章演算法

### 3.1 規格

```
演算法：HMAC-SHA256
密鑰  ：RENDER_PROMPT_SIGNING_SECRET（UTF-8 編碼的位元組）
訊息  ：待簽名字串（見 3.2），UTF-8 編碼
輸出  ：hex 小寫字串（64 個字元）
```

### 3.2 待簽名字串（canonical string）

**這是最容易出錯的地方 —— 兩邊必須用完全一樣的規則組字串，否則簽章永遠對不上。**

```
待簽名字串 = renderPromptEn 的原始內容（不做任何處理）
```

就這樣，**不加鹽、不加時間戳、不做 trim、不轉大小寫、不正規化空白**。

> **為什麼這麼簡單**：多一道處理就多一個兩邊實作不一致的機會。
> prompt 本身就是唯一要保護的東西，直接簽它。

⚠️ **注意**：`renderPromptEn` 送出去之後**一個字元都不能變**。
前端不可以對它做 `.trim()`、不可以換行正規化、不可以截斷。
它必須**原封不動**地從 Ollama → 前端 → 渲染服務。

### 3.3 Ollama 端：產生簽章

```python
import hashlib
import hmac
import os

SIGNING_SECRET = os.getenv("RENDER_PROMPT_SIGNING_SECRET", "")


def sign_render_prompt(render_prompt_en: str) -> str | None:
    """對渲染指令簽章。沒設密鑰就回 None（渲染端會退回白名單風格，不會壞）。"""
    if not SIGNING_SECRET:
        return None
    return hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        render_prompt_en.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
```

在 `/suggest` 的回應加上這個欄位：

```python
render_prompt_en = ...  # 你現在產生 renderPromptEn 的邏輯

return {
    "status": "completed",
    "provider": "ollama",
    "model": model,
    "suggestion": suggestion,
    "renderPromptEn": render_prompt_en,
    "promptSignature": sign_render_prompt(render_prompt_en),   # ← 新增這行
    "fluxPromptEn": flux_prompt_en,
}
```

### 3.4 渲染端：驗證簽章

```python
import hashlib
import hmac
import os

SIGNING_SECRET = os.getenv("RENDER_PROMPT_SIGNING_SECRET", "")


def verify_render_prompt(render_prompt_en: str, signature: str) -> bool:
    """驗證這段 prompt 確實出自 Ollama。"""
    if not SIGNING_SECRET or not render_prompt_en or not signature:
        return False

    expected = hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        render_prompt_en.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # 一定要用 compare_digest，不能用 ==
    # 一般的字串比較會在第一個不同的字元就回傳，攻擊者可以從「比較花了多久」
    # 反推出正確簽章的前綴，一個字元一個字元地把簽章猜出來（timing attack）。
    return hmac.compare_digest(expected, signature)
```

---

## 4. 完整流程

```
┌──────────┐
│ Ollama   │  1. 產生 renderPromptEn
│ /suggest │  2. signature = HMAC_SHA256(SECRET, renderPromptEn)
└──────────┘  3. 回傳 { renderPromptEn, promptSignature, suggestion, ... }
      │
      ▼
┌──────────┐
│ 前端      │  4. 兩者原封不動寫進資料包 generativeText
│          │       （不可 trim、不可修改、不可截斷）
└──────────┘  5. 渲染時把資料包送給 render
      │
      ▼
┌──────────────────────────────────────────────────┐
│ render /render                                    │
│                                                   │
│  6. 從資料包取出 renderPromptEn + promptSignature │
│  7. expected = HMAC_SHA256(SECRET, renderPromptEn)│
│  8. compare_digest(expected, promptSignature)     │
│                                                   │
│     ├─ 相符   → 用這段 prompt（promptSource=ollama_signed）│
│     └─ 不符   → 拒絕，退回 styleId 白名單風格       │
│                  （promptSource=style_allowlist）  │
│                                                   │
│  9. 疊上 identity lock（後端自己加，不可省略）      │
│ 10. 送給 Replicate                                │
└──────────────────────────────────────────────────┘
```

### 4.1 identity lock 一定要由渲染端疊

**簽章只保證「這段 prompt 出自 Ollama」，不保證「這段 prompt 是安全的」。**

Ollama 只負責「要上什麼妝」。那 11 句「不要改變這個人的長相/姿勢/背景」的鎖定句，
**一律由渲染服務自己疊上去**，不管 prompt 從哪來。

理由：不能讓外部模型（即使是我們自己的 Ollama）決定「可不可以改變這個人的臉」。

---

## 5. 失敗時的行為

**任何一種失敗，都不可以讓渲染整個掛掉。** 一律靜默退回 styleId 白名單的固定 prompt。

| 情況 | 行為 | `promptSource` |
|---|---|---|
| 簽章相符 | 用 Ollama 的個人化 prompt | `ollama_signed` |
| 簽章不符 | **拒絕該 prompt**，退回白名單，寫 WARNING log | `style_allowlist` |
| 沒有 `promptSignature` 欄位 | 退回白名單 | `style_allowlist` |
| 兩邊密鑰不一致 | 簽章必然不符 → 退回白名單 | `style_allowlist` |
| 任一邊沒設密鑰 | 退回白名單 | `style_allowlist` |
| Ollama 服務掛掉 | 前端拿不到 prompt → 退回白名單 | `style_allowlist` |

**簽章不符要記 log**，那代表**要嘛有人在竄改，要嘛兩邊密鑰不同步** —— 兩種都需要人去看：

```python
logging.warning(
    "渲染指令簽章驗證失敗，已退回白名單風格。"
    "可能是兩邊密鑰不同步，或有人竄改了 prompt。styleId=%s",
    style_id,
)
```

---

## 6. 測試向量（兩邊都要能跑出一樣的結果）

**實作完成後，兩邊各跑一次這段，確認輸出跟下面的預期值完全相同。**
如果對不上，就是有一邊的實作不符規格（通常是編碼，或多做了一道字串處理）。

**這裡用的是固定的測試密鑰，不是生產密鑰** —— 可以放心貼在文件裡、放心拿去測。

```python
import hashlib, hmac

SECRET = "test-secret-do-not-use-in-production"


def sign(prompt: str) -> str:
    return hmac.new(SECRET.encode("utf-8"), prompt.encode("utf-8"), hashlib.sha256).hexdigest()


# 測試 1：基本
print(sign("Apply a soft baddie makeup look to this person."))
# 測試 2：含中文、破折號、單引號
print(sign("Apply makeup — soft, dewy, 自然感. Don't change the person's identity."))
```

**預期輸出（兩邊都必須一字不差）：**

```
測試 1: f6776107fa29e48107ff4eb46426923c3c7a4d327be103c7a41b9bf36bcf77ba
測試 2: 5b63b379c23558f7087a1eae09787b05e13c9eeb02895700304f038196bbd92f
```

**測試 2 特別重要**：它含破折號 `—`、中文、單引號。
如果任一邊做了編碼轉換、Unicode 正規化、或跳脫處理，這一組就會對不上 ——
而**測試 1 反而可能矇混過關**（純 ASCII 看不出差異）。**兩組都要通過才算實作正確。**

---

## 7. 交付檢查清單

### Ollama 服務端（組員）

- [ ] 加入 `RENDER_PROMPT_SIGNING_SECRET` 環境變數（跟渲染端同一把）
- [ ] 實作 `sign_render_prompt()`（第 3.3 節）
- [ ] `/suggest` 回應新增 `promptSignature` 欄位
- [ ] 跑測試向量（第 6 節），把輸出跟渲染端比對
- [ ] **把程式碼推回 repo** —— 目前線上的 Ollama 版本跟 repo 不一致
      （線上會回 `renderPromptEn` / `fluxPromptEn`，repo 裡的 `Ollama_suggestion.py` 沒有這兩個欄位），
      這代表 repo 不是真相，後續維護會出事

### 渲染服務端

- [ ] 加入 `RENDER_PROMPT_SIGNING_SECRET` 環境變數
- [ ] 實作 `verify_render_prompt()`（第 3.4 節，**必須用 `compare_digest`**）
- [ ] `/render` 與 `/render/jobs` 改為：驗簽通過就用資料包裡的 prompt，否則退回白名單
- [ ] 保留 identity lock 的疊加（第 4.1 節）
- [ ] 簽章失敗要記 WARNING log
- [ ] `promptSource` 回傳 `ollama_signed` / `style_allowlist`

### 前端

- [ ] 把 `promptSignature` 跟 `renderPromptEn` 一起寫進資料包
- [ ] **確保兩者原封不動**（不 trim、不截斷、不做任何字串處理）
- [ ] 渲染時整包送出

### 驗收

- [ ] 正常流程：渲染回傳 `promptSource: "ollama_signed"`
- [ ] 竄改測試：手動改掉資料包裡的 `renderPromptEn` 一個字 → 應退回 `style_allowlist` 並留下 WARNING log
- [ ] Ollama 掛掉：渲染仍成功，`promptSource: "style_allowlist"`

---

## 8. 這個方案不能解決什麼（誠實說明）

| 擋不住 | 說明 |
|---|---|
| **有人拿 key 重複呼叫 Ollama 產生合法 prompt 再拿去渲染** | 簽章只保證 prompt 出自 Ollama，不保證「這個人有權渲染」。這要靠 rate limit（已有）＋ 會員配額（已有）擋。 |
| **Ollama 被誘導產生不當內容** | 簽章不檢查內容。Ollama 的 prompt 本身要防注入（`userNote` 是使用者輸入的）。 |
| **API key 明文暴露** | 這是純靜態前端的本質限制，簽章解決的是「prompt 不被偽造」，不是「key 不被偷」。 |
| **密鑰外洩** | 密鑰一旦流出（進 git、進前端、貼到聊天室），整個機制歸零。這是唯一的信任根。 |

---

## 相關文件

- `Ollama與資料包_系統接口全覽.md` —— 資料包與 Ollama 在整個系統的所有接口
- `OLLAMA_DATA_PACKET_INTEGRATION_SPEC.md` —— 資料包的原始規格書
