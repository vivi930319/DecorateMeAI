# 妝容生成文字修飾服務：呼叫端正式串接規格書

> 文件版本：`2026-06-v1-Final`  
> 適用服務：核心業務後端 ↔ 合作方妝容修飾建議 API（內部預設 Port `8010`）↔ 圖片渲染端  
> 本專案正式呼叫入口：由合作方透過 Cloudflare Tunnel 交付的專屬 HTTPS 網址

本文件定義本專案核心業務後端與外部合作方維運之「妝容文字修飾服務」的正式對接規範。本服務接收臉部去識別化特徵代碼，產出供使用者閱讀的繁體中文彩妝分析報告，並同時為圖片生成端（Stable Diffusion / ControlNet）產出精確的英文正向渲染提示詞。

> 重要架構宣告：本專案主機不負責安裝 Ollama 或維運 `8010` 服務。本專案全面透過合作方交付的 Cloudflare HTTPS 安全隧道進行遠端呼叫。服務禁止提供 fallback 假建議；下游模型異常時必須回傳 HTTP `502 OLLAMA_UNAVAILABLE`。

## 1. 通訊與協議基本規則

| 項目 | 規格 |
| --- | --- |
| Protocol | HTTPS（HTTP/1.1 或 HTTP/2） |
| Encoding | UTF-8 |
| Request Content-Type | `application/json` |
| Response Content-Type | `application/json; charset=utf-8` |
| 安全驗證 Header | 必須攜帶 Cloudflare Access Service Token |
| 呼叫端逾時 | 必須設為 125～130 秒，避免大型模型推理被提早中斷 |
| 欄位命名 | camelCase；`raw` 節點保留既有中文標籤 |
| JSON null | 未取得或不適用時使用 `null`，不得以空字串假裝有值 |

安全要求：

- Cloudflare Access 憑證只能保存在核心業務後端的 Secret Manager 或環境變數。
- 前端 App、Web JavaScript、Git、log 與錯誤回應不得包含 Client Secret。
- 前端不得直接呼叫合作方 API，以免洩漏 Service Token。
- 本版封包只傳送去識別化分析資料，不傳送照片內容。

## 2. API 契約

正式環境的 Base URL 使用合作方安全交付的 Cloudflare 專屬網址：

```text
https://<合作方正式網域>
```

### 2.1 服務健康檢查 `GET /health`

用途：確認合作方 API 是否存活，以及它與下游 Ollama 推理模型的連通性。

正式網址：

```http
GET https://<合作方正式網域>/health
```

必帶 Headers：

```http
CF-Access-Client-Id: <合作方安全交付的 Client ID>
CF-Access-Client-Secret: <合作方安全交付的 Client Secret>
```

成功回應（HTTP `200`）：

```json
{
  "status": "ok",
  "service": "ollama-suggestion",
  "ollama": {
    "baseUrl": "http://127.0.0.1:11434",
    "model": "gemma3",
    "reachable": true,
    "error": null
  },
  "fallbackEnabled": false
}
```

判讀規則：

- `status=ok`：外層 API 正常回應。
- `ollama.reachable=true`：下游 Ollama 已連通。
- `fallbackEnabled` 固定為 `false`。
- 若 `ollama.reachable=false`，不得呼叫 `/suggest` 後期待替代文字；前端應顯示 AI 建議暫時不可用。

### 2.2 妝容建議與英文渲染指令 `POST /suggest`

用途：傳送分析資料包，同步產生繁體中文彩妝建議與圖片渲染端使用的英文提示詞。

正式網址：

```http
POST https://<合作方正式網域>/suggest
```

必帶 Headers：

```http
CF-Access-Client-Id: <合作方安全交付的 Client ID>
CF-Access-Client-Secret: <合作方安全交付的 Client Secret>
Content-Type: application/json
```

#### 標準請求封包

呼叫端應優先傳送完整 `analysisPackage`：

```json
{
  "analysisPackage": {
    "id": "AN-a1b2c3d4e5f6",
    "schemaVersion": "2026-06-v1",
    "mode": "BASIC",
    "client": "web",
    "userId": null,
    "status": "completed",
    "createdAt": "2026-06-24T07:20:00.000000+00:00",
    "updatedAt": "2026-06-24T07:20:00.000000+00:00",
    "images": {
      "front": {
        "originalName": "face.jpg",
        "originalType": "image/jpeg",
        "originalSize": 245678,
        "compressedWidth": 1024,
        "compressedHeight": 1024
      }
    },
    "faceAnalysis": {
      "version": "BASIC",
      "faceShape": "oval",
      "browShape": "curved",
      "eyeShape": "almond",
      "noseFront": "standard",
      "lipShape": "petal",
      "skinTone": {
        "season": "spring",
        "level": "白皙自然色",
        "lab": {
          "L": 74.21,
          "a": 8.13,
          "b": 18.64
        },
        "labSource": "正面照"
      },
      "raw": {
        "分析版本": "BASIC",
        "臉型": "鵝蛋臉",
        "眉型": "彎月眉"
      }
    },
    "generativeText": {
      "status": "pending",
      "provider": "ollama",
      "suggestion": null,
      "renderPromptEn": null,
      "error": null
    }
  },
  "style": "日常自然妝",
  "language": "zh-TW",
  "userNote": "希望上班使用，眼妝不要太濃",
  "model": null
}
```

#### 固定枚舉值

`faceAnalysis` 內的代碼必須符合以下清單：

| 欄位 | 允許值 |
| --- | --- |
| `faceShape` | `oval`, `round`, `square`, `oblong`, `heart`, `diamond`, `trapezoid`, `unknown` |
| `browShape` | `straight`, `curved`, `drooping_tail`, `standard`, `unknown` |
| `eyeShape` | `narrow`, `downturned`, `round`, `slender_phoenix`, `phoenix`, `slender`, `peach_blossom`, `almond`, `round_almond`, `unknown` |
| `noseFront` | `standard`, `wide`, `narrow`, `unknown` |
| `lipShape` | `full`, `thin`, `m_shape`, `smile`, `petal`, `unknown` |
| `skinTone.season` | `spring`, `summer`, `autumn`, `winter`, `unknown` |

`style` 支援清單：

- `日常自然妝`
- `Soft baddie`
- `韓系亞裔妝`
- `日雜清透妝`
- `千金妝`
- `港風妝`
- `病嬌妝`

呼叫端不得自行傳入清單以外的值。若新增風格，雙方必須共同更新契約版本後才可上線。

## 3. 成功回應與資料包回填

合作方完成繁中建議與英文渲染提示詞兩階段推理後，回傳 HTTP `200`：

```json
{
  "status": "completed",
  "provider": "ollama",
  "model": "gemma3",
  "fallbackUsed": false,
  "createdAt": "2026-06-24T07:30:00.000000+00:00",
  "suggestion": "1. 整體妝容方向\n配合您的鵝蛋臉與彎月眉，整體展現精緻柔和的氛圍……\n\n2. 底妝建議\n使用輕薄且帶緞面光澤的底妝……\n\n3. 眉眼妝建議\n使用霧面淺杏色在眼皮輕盈打底……\n\n4. 唇妝建議\n搭配茶色調水光唇釉……\n\n5. 避免事項\n上班妝應避免高飽和度眼影與過重陰影修容。",
  "renderPromptEn": "Apply a soft natural everyday makeup look with lightweight satin-finish foundation, subtle peach blush blended high on the cheeks, softly defined natural brows, warm beige eyeshadow concentrated near the lash line, thin brown eyeliner, naturally separated lashes, and a muted rose lip tint with a soft satin finish. Preserve the person's identity, facial structure, skin tone, hairstyle, pose, camera angle, background, and lighting. Change makeup only.",
  "analysisPackageId": "AN-a1b2c3d4e5f6",
  "schemaVersion": "2026-06-v1"
}
```

成功判定必須同時符合：

- HTTP 狀態為 `200`。
- `status=completed`。
- `provider=ollama`。
- `fallbackUsed=false`。
- `analysisPackageId` 等於送出封包的 `analysisPackage.id`。
- `schemaVersion` 等於送出封包的版本。
- `suggestion` 與 `renderPromptEn` 都是非空字串。

### 3.1 局部回填原則

核心業務後端收到有效成功回應後，只能進行以下更新：

1. 將 `suggestion` 寫入 `analysisPackage.generativeText.suggestion`。
2. 將 `renderPromptEn` 寫入 `analysisPackage.generativeText.renderPromptEn`。
3. 將 `analysisPackage.generativeText.status` 設為 `completed`。
4. 將 `analysisPackage.generativeText.provider` 設為 `ollama`。
5. 將 `analysisPackage.generativeText.model` 設為合作方回傳的模型。
6. 將 `analysisPackage.generativeText.error` 設為 `null`。
7. 將最外層 `analysisPackage.updatedAt` 更新為目前 UTC ISO 8601 時間。

禁止改寫：

- `analysisPackage.id`
- `analysisPackage.schemaVersion`
- `analysisPackage.faceAnalysis`
- `analysisPackage.images`
- `analysisPackage.render`
- 其他不屬於 `generativeText` 的業務資料

圖片渲染端只能讀取 `analysisPackage.generativeText.renderPromptEn` 作為 Prompt，不得自行翻譯中文 `suggestion`。

## 4. 錯誤契約

合作方 API 必須回傳可機器判讀的錯誤 JSON：

```json
{
  "status": "failed",
  "analysisPackageId": "AN-a1b2c3d4e5f6",
  "error": {
    "code": "OLLAMA_UNAVAILABLE",
    "message": "文字建議服務失敗。下游 Ollama 推理引擎離線、逾時或回傳空字串",
    "retryable": true
  }
}
```

| HTTP | `error.code` | `retryable` | 情境與呼叫端處理 |
| ---: | --- | ---: | --- |
| 400 | `MISSING_FACE_ANALYSIS` | false | 沒有有效 `faceAnalysis`；停止重試並檢查封包建立流程 |
| 422 | `VALIDATION_ERROR` | false | JSON 結構、欄位型別或枚舉值錯誤；停止重試並記錄驗證問題 |
| 502 | `OLLAMA_UNAVAILABLE` | true | Ollama 離線、模型未載入或推理輸出無效；顯示暫時不可用，可有限次重試 |
| 504 | `OLLAMA_TIMEOUT` | true | 下游推理超過 120 秒；顯示逾時，可稍後重試 |

### 4.1 失敗時的資料處理

- 不得把錯誤頁面、固定文字或上一次建議寫入 `suggestion`。
- 不得把中文建議自行翻譯後寫入 `renderPromptEn`。
- 保留原本 `analysisPackage.id` 與分析內容。
- 可將 `generativeText.status` 設為 `failed`，並將結構化錯誤寫入 `generativeText.error`。
- 自動重試應限制次數並採退避策略，避免合作方故障時形成請求風暴。
- 前端顯示「AI 建議暫時無法使用」，不得偽裝成成功結果。

## 5. 呼叫端設定

核心業務後端以 Secret Manager 或環境變數保存：

```text
MAKEUP_AI_BASE_URL=https://<合作方正式網域>
CF_ACCESS_CLIENT_ID=<合作方安全交付>
CF_ACCESS_CLIENT_SECRET=<合作方安全交付>
MAKEUP_AI_TIMEOUT=130
```

禁止將真實值提交到 Git。

## 6. 最小呼叫範例

### 6.1 PowerShell 健康檢查

```powershell
$headers = @{
  "CF-Access-Client-Id" = $env:CF_ACCESS_CLIENT_ID
  "CF-Access-Client-Secret" = $env:CF_ACCESS_CLIENT_SECRET
}

Invoke-RestMethod `
  -Method Get `
  -Uri "$($env:MAKEUP_AI_BASE_URL)/health" `
  -Headers $headers `
  -TimeoutSec 10
```

### 6.2 Python 呼叫骨架

```python
import os

import requests


base_url = os.environ["MAKEUP_AI_BASE_URL"].rstrip("/")
headers = {
    "CF-Access-Client-Id": os.environ["CF_ACCESS_CLIENT_ID"],
    "CF-Access-Client-Secret": os.environ["CF_ACCESS_CLIENT_SECRET"],
    "Content-Type": "application/json",
}

response = requests.post(
    f"{base_url}/suggest",
    headers=headers,
    json=request_packet,
    timeout=130,
)
response.raise_for_status()
result = response.json()

if (
    result.get("status") != "completed"
    or result.get("provider") != "ollama"
    or result.get("fallbackUsed") is not False
    or not result.get("suggestion")
    or not result.get("renderPromptEn")
):
    raise RuntimeError("合作方回應不符合成功契約")
```

## 7. 正式上線驗收清單

- [ ] 呼叫端 Timeout 已設為 125～130 秒，而非 HTTP 套件預設值。
- [ ] 所有請求均帶有 `CF-Access-Client-Id` 與 `CF-Access-Client-Secret`。
- [ ] 未帶 Cloudflare Service Token 時，入口會拒絕請求。
- [ ] 憑證只保存在核心後端 Secret，不存在前端或 Git。
- [ ] 完整 `analysisPackage` 可成功送達合作方。
- [ ] 所有英文枚舉與 `style` 都在契約清單內。
- [ ] 成功回應包含相同的 `analysisPackageId` 與 `schemaVersion`。
- [ ] 呼叫端只更新 `generativeText` 與最外層 `updatedAt`。
- [ ] 圖片渲染端只讀 `generativeText.renderPromptEn`。
- [ ] Ollama 離線時，呼叫端可解析 HTTP `502 OLLAMA_UNAVAILABLE`。
- [ ] 發生錯誤時沒有假資料、舊資料或自行翻譯內容污染資料庫。
- [ ] `null` 或 `unknown` 特徵不會造成呼叫端崩潰。
- [ ] `suggestion` 與 `renderPromptEn` 非空才視為完成。
