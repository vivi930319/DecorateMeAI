# 前端修改單：移除寫死妝容建議並改接真實 Ollama 結果

> 對象：前端負責人／核心業務後端負責人  
> 優先級：阻擋正式 Ollama 驗收  
> 目標：畫面只能顯示本次 `/suggest` 成功回傳的 AI 建議；API 未完成或失敗時不得顯示任何固定建議。

## 1. 目前問題與證據

畫面上的以下文字不是 Ollama 產生，而是寫死在前端：

```text
薄透光澤底妝，重點放在膚色均勻。
順著原生眉型補空隙，避免過重。
燕麥、奶茶色眼影，眼頭少量提亮。
低飽和裸粉或杏色，淡淡掃在蘋果肌。
奶茶玫瑰、裸豆沙色最穩。
```

來源：

```text
C:\Users\isach\OneDrive\桌面\web_frontend\js\data.js
```

此外，`router.js` 還有三層假資料退路：

1. `renderAnalysisResult()` 使用 `style.advice || defaultAdvice()`。
2. `suggestion()` 在 AI 文字不存在時使用 `style.intro`。
3. `suggestion()` 仍將 `style.advice` 顯示為「建議收藏」。

所以目前即使 Ollama 完全離線，畫面仍會出現看似個人化的妝容建議。

## 2. 必須移除的內容

### 2.1 `js/data.js`

從每個 `STYLES` 項目移除 `advice`：

```javascript
advice: {
    base: '...',
    brow: '...',
    eye: '...',
    blush: '...',
    lip: '...'
}
```

`name`、`img`、`tags`、`intro` 與 `palette` 可以保留，因為它們是風格展示資料，不可再被當成 AI 個人建議。

### 2.2 `js/router.js`

完整刪除：

```javascript
const advice = style.advice || defaultAdvice();
```

完整刪除 `defaultAdvice()`。

完整刪除下列固定建議版面：

```javascript
<div class="advice-grid">
    ... advice.base ...
    ... advice.brow ...
    ... advice.eye ...
    ... advice.blush ...
    ... advice.lip ...
</div>
```

在 `suggestion()` 中刪除：

```javascript
const advice = style.advice || { ... };
```

不得再使用：

```javascript
aiSuggestion || style.intro || '此風格介紹尚待補充。'
```

AI 建議區只能使用：

```javascript
pkg.generativeText?.suggestion
```

`style.intro` 只能出現在明確標示「風格介紹」的區域，不得出現在「專屬妝容建議」區域。

## 3. 真實 API 回應的成功驗證

目前程式有以下危險寫法：

```javascript
provider: response.provider || 'ollama'
status: response.status || 'completed'
```

這會把缺少欄位或錯誤回應偽裝成 Ollama 成功，必須移除預設值。

新增嚴格驗證函式：

```javascript
function validateOllamaSuggestion(response, analysisPackage) {
    const valid =
        response &&
        response.status === 'completed' &&
        response.provider === 'ollama' &&
        response.fallbackUsed === false &&
        response.analysisPackageId === analysisPackage.id &&
        response.schemaVersion === analysisPackage.schemaVersion &&
        typeof response.suggestion === 'string' &&
        response.suggestion.trim().length > 0 &&
        typeof response.renderPromptEn === 'string' &&
        response.renderPromptEn.trim().length > 0;

    if (!valid) {
        throw new Error('AI 建議服務回應不符合正式契約');
    }
    return response;
}
```

收到 `/suggest` 回應後，必須先驗證再寫入資料包：

```javascript
const response = validateOllamaSuggestion(
    await Api.suggestMakeup({
        analysisPackage: pkg,
        style: style.apiStyle,
        userNote: style.tags.join('、')
    }),
    pkg
);
```

## 4. 正確回填 `generativeText`

目前前端沒有把 `renderPromptEn` 寫入資料包，必須補上：

```javascript
generativeText: {
    status: 'completed',
    provider: response.provider,
    model: response.model,
    suggestion: response.suggestion.trim(),
    renderPromptEn: response.renderPromptEn.trim(),
    fallbackUsed: false,
    error: null
}
```

不得再使用 `prompt: null` 取代 `renderPromptEn`。

資料包初始化也要加入：

```javascript
generativeText: {
    provider: 'pending',
    model: null,
    suggestion: null,
    renderPromptEn: null,
    status: 'pending',
    fallbackUsed: false,
    error: null
}
```

只允許更新 `generativeText` 與最外層 `updatedAt`；不可改寫 `id`、`schemaVersion`、`faceAnalysis`、`images` 或 `render`。

## 5. 請求封包修正

正式環境不要同時傳 `analysisPackage` 與第二份 `faceAnalysis`。目前程式同時傳兩份，可能產生內容衝突。

`Api.suggestMakeup()` 應改成：

```javascript
async suggestMakeup({ analysisPackage, style, userNote }) {
    const res = await fetch(this.config.url('textSuggestion', 'suggestPath'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            analysisPackage,
            style,
            language: 'zh-TW',
            userNote,
            model: null
        })
    });

    const body = await res.json().catch(() => null);
    if (!res.ok) {
        const code = body?.error?.code || body?.detail?.error?.code || 'SUGGESTION_API_ERROR';
        const message = body?.error?.message || body?.detail?.error?.message || 'AI 建議服務暫時無法使用';
        const error = new Error(message);
        error.code = code;
        error.status = res.status;
        throw error;
    }
    return body;
}
```

## 6. 妝容風格代碼必須對齊 API

目前畫面名稱和 API 契約不完全一致，例如：

| 前端目前名稱 | API 必須傳送 |
| --- | --- |
| `Soft Baddie` | `Soft baddie` |
| `千金` | `千金妝` |
| `港風` | `港風妝` |
| `韓系亞裔` | `韓系亞裔妝` |
| `日雜清透` | `日雜清透妝` |
| `病嬌` | `病嬌妝` |

每個 `STYLES` 項目新增 `apiStyle`，畫面顯示繼續使用 `name`：

```javascript
{
    id: 'richGirl',
    name: '千金',
    apiStyle: '千金妝',
    // 其他純展示資料
}
```

不得直接把 `style.name` 當成 API 值。

## 7. API 狀態對應 UI

畫面必須區分以下狀態：

### `pending`

```text
正在產生專屬妝容建議，請稍候……
```

只顯示 loading，不顯示任何建議。

### `completed`

只有通過第 3 節完整驗證後才顯示：

```text
AI 專屬妝容建議
```

內容只取 `generativeText.suggestion`。

### `failed`

HTTP `502` 或 `504` 時顯示：

```text
AI 建議服務目前無法使用，請稍後再試。
```

提供「重新產生」按鈕，不得顯示固定建議、風格介紹或上一次結果。

建議失敗回填：

```javascript
generativeText: {
    ...pkg.generativeText,
    status: 'failed',
    suggestion: null,
    renderPromptEn: null,
    error: {
        code: err.code || 'SUGGESTION_API_ERROR',
        message: err.message
    }
}
```

## 8. Cloudflare 架構限制

前端不可直接呼叫合作方 Cloudflare API，因為以下憑證不能放入瀏覽器：

```http
CF-Access-Client-Id
CF-Access-Client-Secret
```

正確架構：

```text
Web / App
  → 本專案核心業務後端
  → 加入 Cloudflare Access Service Token
  → 合作方 /suggest
  → 核心後端驗證並回傳前端
```

因此 `RuntimeApiConfig.textSuggestionUrl` 應指向本專案核心後端的代理端點，不是合作方 Cloudflare 網址，更不能把 Service Secret 寫入 `config.js`。

目前直接打開的是 `file:///.../index.html`。正式測試應以 HTTP 啟動前端，例如：

```text
http://127.0.0.1:5500
```

不要使用 `file://` 作為正式串接驗收環境。

## 9. 驗收條件

- [ ] `js/data.js` 不再包含任何 `advice` 固定建議。
- [ ] `router.js` 不存在 `defaultAdvice()`。
- [ ] API 失敗時畫面不顯示 `style.advice` 或 `style.intro` 冒充 AI 建議。
- [ ] 缺少 `provider` 時不會自動補成 `ollama`。
- [ ] 缺少 `status` 時不會自動補成 `completed`。
- [ ] 只有 `provider=ollama` 且 `fallbackUsed=false` 才顯示成功結果。
- [ ] `analysisPackageId` 與 `schemaVersion` 必須和請求一致。
- [ ] `suggestion` 與 `renderPromptEn` 都非空才算成功。
- [ ] `renderPromptEn` 正確寫入 `generativeText`。
- [ ] 正式請求只傳一份完整 `analysisPackage`。
- [ ] 七種風格皆使用契約允許的 `apiStyle`。
- [ ] 502／504 時顯示錯誤與重試，不顯示假建議。
- [ ] Cloudflare Service Secret 不存在任何前端檔案。
- [ ] 前端透過 HTTP 而非 `file://` 執行。

## 10. 可用來確認假資料已移除的搜尋

修改完成後，在前端專案執行：

```powershell
rg -n "advice:|defaultAdvice|薄透光澤底妝|奶茶玫瑰|燕麥、奶茶色眼影" js
```

預期不應找到任何固定妝容建議。
