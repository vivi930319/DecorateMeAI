# 妝容生成文字修飾服務：前端與呼叫端串接規格書

> 文件版本：`2026-06-v1-Final`  
> 適用服務：臉部分析後端 ↔ Ollama 妝容建議服務 ↔ 圖片渲染端  
> 合作方 API 內部預設位址：`http://127.0.0.1:8010`  
> 合作方 Ollama 內部預設位址：`http://127.0.0.1:11434`  
> 本專案正式呼叫位址：由合作方透過 Cloudflare Tunnel 交付的 HTTPS 網址

> 配套文件：核心業務後端請使用 `MAKEUP_AI_CALLER_INTEGRATION_SPEC.md`。

本文件定義「前端 App / Web」與「核心業務後端」如何與「妝容文字修飾服務（預設連接埠：`8010`）」進行封包串接。本服務主要接收臉部去識別化特徵代碼，對外產出給使用者觀看的繁體中文彩妝分析報告，並同時為圖片生成端（Stable Diffusion / ControlNet）產出精確的英文正向渲染提示詞。

> 正式架構說明：Ollama 與 `8010` API 都由外部合作方建置及維運。本專案只負責呼叫合作方交付的 Cloudflare HTTPS 網址，不負責在本機安裝或啟動 Ollama。

# A. 給 Ollama 合作方：從零建立 API 並透過 Cloudflare 交付

本章是合作方的施工順序。完成後，合作方必須交付一個 HTTPS API 網址與機器對機器驗證資料；不得要求本專案直接連接合作方的 Ollama `11434` Port。

## A1. 最終網路架構

```text
本專案核心業務後端
  │ HTTPS + Cloudflare Access service token
  ▼
https://makeup-ai.example.com
  │ Cloudflare Tunnel（只轉送 8010）
  ▼
合作方妝容文字修飾 API：http://127.0.0.1:8010
  │ 僅合作方本機／內網可連
  ▼
合作方 Ollama：http://127.0.0.1:11434
```

安全邊界：

- 公開入口只能是 Cloudflare HTTPS 網址。
- 不得在路由器、防火牆或雲端安全群組直接開放 `11434`。
- `8010` 建議只監聽 `127.0.0.1`；Cloudflare Tunnel 與 API 在同一台主機時不需要公開 Port。
- 正式請求只能由本專案核心後端發送，前端 App / Web 不得保存 Cloudflare service token。
- 本版只接收去識別化 `faceAnalysis`／`analysisPackage`，不傳照片。若未來要加入照片，必須另訂圖片大小、格式、保存與刪除規則後共同升版。

## A2. 合作方先完成 Ollama

合作方自行安裝 Ollama，啟動服務並下載雙方確認的模型。以下以 `gemma3` 為範例；實際模型名稱必須回報本專案。

```powershell
ollama pull gemma3
ollama list
ollama serve
```

在 Ollama 主機測試：

```powershell
$body = @{
  model = "gemma3"
  prompt = "Reply with exactly: OLLAMA_OK"
  stream = $false
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:11434/api/generate" `
  -ContentType "application/json" `
  -Body $body
```

必須先確認回應中有非空 `response`，再進行下一步。

## A3. 建立對外的 8010 API

合作方可使用 FastAPI、Node.js 或其他框架，但外部契約必須完全符合本文件。以下為 Python FastAPI 最小建置方式。

### A3.1 建立環境

```powershell
mkdir makeup-ollama-api
cd makeup-ollama-api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn requests pydantic
```

Linux/macOS 啟用環境：

```bash
source .venv/bin/activate
```

### A3.2 必須提供的路徑

| Method | Path | 說明 |
| --- | --- | --- |
| `GET` | `/health` | API 存活與 Ollama 連線狀態 |
| `POST` | `/suggest` | 接收本文件資料包，回傳中英文兩份結果 |

實作要求：

1. `POST /suggest` 驗證 `analysisPackage.faceAnalysis` 或相容模式的 `faceAnalysis`。
2. 從固定英文代碼建立 prompt，不把 `userId`、圖片 URL、token 或其他個資送入模型。
3. 第一次呼叫 Ollama 產生繁中 `suggestion`。
4. 第二次呼叫 Ollama 產生純英文 `renderPromptEn`。
5. 兩次皆成功才回 HTTP `200`。
6. Ollama 離線、逾時或任一輸出為空時回 HTTP `502 OLLAMA_UNAVAILABLE`。
7. 禁止固定展示文字、規則式假建議或 fallback。
8. 成功時 `provider` 固定 `ollama`、`fallbackUsed` 固定 `false`。

### A3.3 合作方環境變數

```text
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3
OLLAMA_TIMEOUT=120
API_HOST=127.0.0.1
API_PORT=8010
```

合作方啟動 API：

```powershell
uvicorn main:app --host 127.0.0.1 --port 8010
```

先在合作方主機測試：

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8010/health"
```

只有當 `ollama.reachable=true`，才算 Ollama 已接通。`status=ok` 只表示外層 API 活著，不能單獨作為串接成功證明。

## A4. 用 Cloudflare Quick Tunnel 做第一次外網測試

Quick Tunnel 只用於短期測試，網址每次可能改變，不可交付為正式網址。

1. 合作方安裝官方 `cloudflared`。
2. 確認本機 `http://127.0.0.1:8010/health` 可用。
3. 執行：

```powershell
cloudflared tunnel --url http://127.0.0.1:8010
```

終端會顯示類似：

```text
https://random-name.trycloudflare.com
```

外網測試：

```powershell
Invoke-RestMethod `
  -Method Get `
  -Uri "https://random-name.trycloudflare.com/health"
```

Quick Tunnel 驗收完成後，停止它並建立正式 Named Tunnel。

## A5. 建立正式 Cloudflare Named Tunnel

前置條件：合作方必須有 Cloudflare 帳號，且正式網域已由 Cloudflare 管理。

### A5.1 登入並建立 Tunnel

```powershell
cloudflared tunnel login
cloudflared tunnel create makeup-ollama-api
```

記下命令輸出的 Tunnel UUID 與 credentials JSON 路徑。

### A5.2 建立 `config.yml`

Windows 常用位置：

```text
C:\Users\<使用者>\.cloudflared\config.yml
```

Linux 常用位置：

```text
~/.cloudflared/config.yml
```

內容：

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: C:\Users\<使用者>\.cloudflared\<TUNNEL-UUID>.json

ingress:
  - hostname: makeup-ai.example.com
    service: http://127.0.0.1:8010
  - service: http_status:404
```

Linux 的 `credentials-file` 改成實際 Linux 路徑。最後一條 `http_status:404` 不可省略。

### A5.3 建立 DNS 並啟動

```powershell
cloudflared tunnel route dns makeup-ollama-api makeup-ai.example.com
cloudflared tunnel run makeup-ollama-api
```

測試：

```powershell
Invoke-RestMethod -Method Get -Uri "https://makeup-ai.example.com/health"
```

正式環境需將 cloudflared 設成系統服務或由程序管理器維持執行，避免主機重開後 Tunnel 消失。合作方應依作業系統使用官方 service install 流程，並驗證重開機後 `/health` 仍可連線。

## A6. 使用 Cloudflare Access 保護 API

不能只靠一個難猜的網址。合作方應在 Cloudflare Zero Trust 建立 Self-hosted application，網域填入 `makeup-ai.example.com`，再建立 Service Auth policy 與 Service Token。

合作方交付兩個值：

```text
CF_ACCESS_CLIENT_ID=<client-id>.access
CF_ACCESS_CLIENT_SECRET=<client-secret>
```

本專案核心後端呼叫時加入：

```http
CF-Access-Client-Id: <client-id>.access
CF-Access-Client-Secret: <client-secret>
Content-Type: application/json
```

PowerShell 驗證範例：

```powershell
$headers = @{
  "CF-Access-Client-Id" = "<client-id>.access"
  "CF-Access-Client-Secret" = "<client-secret>"
}

Invoke-RestMethod `
  -Method Get `
  -Uri "https://makeup-ai.example.com/health" `
  -Headers $headers
```

注意：

- Service secret 只能透過安全管道交付一次，不可寫進 Git、MD、前端 JavaScript 或聊天截圖。
- Cloudflare Access 規則生效後，未帶 token 的請求應被拒絕；帶正確 token 才能到達 API。
- 若合作方選擇其他驗證方式，必須先與本專案確認 header 名稱與換發流程。

## A7. 合作方必須交付的資料

合作方完成後請提供：

```text
正式 API Base URL：https://makeup-ai.example.com
健康檢查：GET /health
產生建議：POST /suggest
模型名稱：例如 gemma3
schemaVersion：2026-06-v1
驗證方式：Cloudflare Access Service Token
CF Access Client ID：以安全管道交付
CF Access Client Secret：以安全管道交付
單次逾時：120 秒
最大請求大小：由合作方填寫
維運聯絡人：由合作方填寫
```

禁止交付：

- `http://127.0.0.1:11434`
- 區網 IP，例如 `192.168.x.x`
- 每次會改變的 `trycloudflare.com` 測試網址
- 沒有驗證機制的公開 API

## A8. 合作方交付前驗收

- [ ] Ollama `11434` 沒有直接暴露到網際網路。
- [ ] `GET https://正式網域/health` 可經 Cloudflare Access 取得結果。
- [ ] 未帶 Access token 時請求會被拒絕。
- [ ] `ollama.reachable=true`。
- [ ] `POST /suggest` 可接收本文件完整封包。
- [ ] 成功回應的 `provider=ollama`、`fallbackUsed=false`。
- [ ] `suggestion` 是本次模型生成的繁體中文內容。
- [ ] `renderPromptEn` 是本次模型生成的純英文渲染指令。
- [ ] Ollama 關閉時 `/suggest` 回 `502`，不回假資料。
- [ ] API 與 Tunnel 在主機重開後會自動恢復。
- [ ] 合作方已安全交付正式 URL 與 Access credentials。

## A9. 本專案收到交付資料後才做的事

本專案收到正式 URL 與驗證資料後，才將呼叫端設定為：

```text
MAKEUP_AI_BASE_URL=https://makeup-ai.example.com
CF_ACCESS_CLIENT_ID=<由合作方交付>
CF_ACCESS_CLIENT_SECRET=<由合作方交付>
MAKEUP_AI_TIMEOUT=130
```

在此之前，本機 `127.0.0.1:8010`、`127.0.0.1:11434` 或任何固定假建議都不代表已與合作方完成串接。

## 0. 可直接交給 Ollama 端 AI 的工作指令

請依照本文件實作「Ollama 妝容文字建議與英文渲染指令服務」。各端以 HTTP JSON 資料包串接，不以檔案、命令列文字或共享記憶體串接。

必須遵守：

1. 對外提供 `GET /health` 與 `POST /suggest`。
2. `POST /suggest` 的 `Content-Type` 必須是 `application/json`。
3. 輸入以完整 `analysisPackage` 為主；相容模式才接受單獨 `faceAnalysis`。
4. 不要求傳入圖片二進位；文字建議只使用 `analysisPackage.faceAnalysis`。
5. 必須保留 `analysisPackage.id` 與 `schemaVersion`，不得改寫臉部分析欄位。
6. 呼叫 Ollama 原生 `POST /api/generate`，使用非串流 JSON：`stream: false`。
7. 成功時同時回傳給使用者看的繁體中文 `suggestion`，以及給圖片渲染端使用的英文 `renderPromptEn`。
8. `renderPromptEn` 必須是可直接送給圖片生成／編輯模型的精簡英文指令，不可只是中文建議的逐字翻譯。
9. 模型輸出只能寫入指定文字欄位；不得讓模型輸出覆蓋其他封包欄位。
10. 所有回應使用 UTF-8；使用者建議預設語言為繁體中文 `zh-TW`，渲染指令固定使用英文。
11. 逾時、模型不存在、Ollama 離線與輸入錯誤必須回傳可機器判斷的 HTTP 狀態及錯誤 JSON。

## 1. 通訊與協議基本規則

| 項目 | 規格 |
| --- | --- |
| Protocol | HTTP/1.1 或 HTTP/2 |
| Encoding | UTF-8 |
| Request Content-Type | `application/json` |
| Response Content-Type | `application/json; charset=utf-8` |
| 通訊逾時建議 | 由於後端涉及大型 AI 模型推理，服務內部逾時為 120 秒；呼叫端必須設為 125～130 秒，避免模型冷啟動或大量請求造成提早中斷 |
| 串流 | 現行版本不使用；`stream=false` |
| 日期格式 | ISO 8601 UTC，例如 `2026-06-24T07:30:00.000000+00:00` |
| 欄位命名 | camelCase；`raw` 內保留既有中文欄位 |
| JSON null | 未取得或不適用時使用 `null`，不要用空字串假裝有值 |

正式環境建議額外傳送：

```http
Authorization: Bearer <service-token>
X-Request-Id: <uuid>
```

目前程式尚未驗證上述兩個 header；若對方新增驗證，必須與呼叫端同步上線，不能單方面啟用。

## 2. API 接口契約定義

### 2.1 服務健康檢查機制 `GET /health`

用途：確認文字修飾服務是否存活，並檢測與其關聯之下游文字推理引擎的連通性。

合作方本機測試網址：`http://127.0.0.1:8010/health`  
本專案正式請求網址：`https://<合作方正式網域>/health`

成功回應固定為 HTTP `200`；即使 Ollama 暫時離線，Suggestion API 本身仍可回 `200`，由 `ollama.reachable` 判斷下游狀態。

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

### 2.2 妝容建議與英文渲染指令 `POST /suggest`

用途：接收分析資料包並產生妝容建議。

#### 標準請求封包

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
        "compressedImageUrl": null,
        "compressedDataUrl": null,
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
        "lab": {"L": 74.21, "a": 8.13, "b": 18.64},
        "labSource": "正面照"
      },
      "lipLab": {"L": 48.24, "a": 18.0, "b": 12.0},
      "symmetry": {
        "score": 91,
        "eyeOpenRatio": 0.94,
        "noseDeviation": 0.012,
        "mouthSymmetry": 0.97
      },
      "noseSide": null,
      "sidePhotoUsed": false,
      "proStatus": null,
      "raw": {
        "分析版本": "BASIC",
        "臉型": "鵝蛋臉",
        "眉型": "彎月眉",
        "眼型": "杏仁眼",
        "鼻型": "標準鼻",
        "嘴型": "花瓣唇",
        "膚色": {
          "四季型": "春季",
          "膚色分級": "白皙自然色",
          "LAB": {"L": 74.21, "a": 8.13, "b": 18.64}
        }
      }
    },
    "generativeText": {
      "status": "pending",
      "provider": "ollama",
      "model": null,
      "suggestion": null,
      "renderPromptEn": null,
      "error": null
    },
    "render": {
      "status": "pending",
      "provider": "replicate",
      "replicateTempUrl": null,
      "afterImageUrl": null,
      "savedImageId": null,
      "error": null
    },
    "recommendations": {"products": [], "tips": [], "ads": []}
  },
  "style": "日常自然妝",
  "language": "zh-TW",
  "userNote": "希望上班使用，眼妝不要太濃",
  "model": null
}
```

#### 請求最外層欄位

| 欄位 | 型別 | 必填 | 預設 | 說明 |
| --- | --- | ---: | --- | --- |
| `analysisPackage` | object | 正式環境必填 | 無 | 完整資料包，也是 `analysisPackageId` 與版本的來源 |
| `faceAnalysis` | object/null | 否 | null | 僅供非正式相容測試；正式環境不得取代完整資料包 |
| `style` | enum/null | 否 | `日常自然妝` | 只能使用本節列出的妝容風格 |
| `language` | string/null | 否 | `zh-TW` | 輸出語言；現行 prompt 固定繁中，正式版應實際驗證此欄位 |
| `userNote` | string/null | 否 | null | 使用者補充需求，只能當作偏好，不是系統指令 |
| `model` | string/null | 否 | 環境變數模型 | 單次指定模型；正式環境建議改為允許清單 |

正式環境必須傳送 `analysisPackage`，不得同時傳最外層 `faceAnalysis`，避免同一請求存在兩份不同分析結果。

`style` 固定支援：`日常自然妝`、`Soft baddie`、`韓系亞裔妝`、`日雜清透妝`、`千金妝`、`港風妝`、`病嬌妝`。新增值必須共同升版，服務端收到未知風格時回 `422 VALIDATION_ERROR`。

#### `analysisPackage` 欄位

| 欄位 | 型別 | 必填 | Ollama 端用途 |
| --- | --- | ---: | --- |
| `id` | string | 是 | 請求與回應關聯鍵，格式 `AN-xxxxxxxxxxxx` |
| `schemaVersion` | string | 是 | 目前固定 `2026-06-v1` |
| `mode` | enum | 是 | `BASIC` 或 `PRO` |
| `client` | enum | 是 | `web` 或 `ios` |
| `userId` | string/number/null | 否 | 不應寫入 prompt 或 log |
| `status` | string | 是 | 傳給 Ollama 前應是 `completed` |
| `createdAt` | string | 是 | 原資料包建立時間 |
| `updatedAt` | string | 是 | 原資料包最後更新時間 |
| `images` | object | 是 | 建議端不需要讀圖片；避免把 `compressedDataUrl` 寫入 prompt |
| `faceAnalysis` | object | 是 | 產生建議的唯一分析來源 |
| `generativeText` | object | 是 | 中文建議與英文渲染指令；傳入時通常為 `pending` |
| `render` | object | 是 | 非文字建議服務責任，不得改寫 |
| `recommendations` | object | 是 | 非文字建議服務責任，不得改寫 |

#### `faceAnalysis` 固定代碼

| 欄位 | 可接受值 |
| --- | --- |
| `version` | `BASIC`, `PRO` |
| `faceShape` | `oval`, `round`, `square`, `oblong`, `heart`, `diamond`, `trapezoid`, `unknown` |
| `browShape` | `straight`, `curved`, `drooping_tail`, `standard`, `unknown` |
| `eyeShape` | `narrow`, `downturned`, `round`, `slender_phoenix`, `phoenix`, `slender`, `peach_blossom`, `almond`, `round_almond`, `unknown` |
| `noseFront` | `standard`, `wide`, `narrow`, `unknown` |
| `lipShape` | `full`, `thin`, `m_shape`, `smile`, `petal`, `unknown` |
| `skinTone.season` | `spring`, `summer`, `autumn`, `winter`, `unknown` |

其他數值：

- `skinTone.level`：中文膚色分級或 `null`。
- `skinTone.lab.L/a/b`：數字或 `null`。
- `skinTone.labSource`：來源文字，2026-08-05 起一律是 `正面照`（膚色不再做正面+側面平均，理由見《給演算法端_膚色可信度旗標接入_2026-08-03》§7）。仍請當成自由文字處理，不要對它做等值比對。
- `lipLab.L/a/b`：數字或 `null`。
- `symmetry.score`：建議範圍 0～100。
- `noseSide`：目前為 `null`，不可自行推論側面鼻型。
- `sidePhotoUsed`：boolean。代表「這次分析有收到並用到側面照」（用途是側臉鼻型），**不代表膚色用了側面照**——膚色一律只採正面照。
- `raw`：保留原始中文分析，供顯示與除錯；固定英文欄位才是服務間契約。

### 2.3 成功回應

HTTP `200`：

```json
{
  "status": "completed",
  "provider": "ollama",
  "model": "gemma3",
  "fallbackUsed": false,
  "createdAt": "2026-06-24T07:30:00.000000+00:00",
  "suggestion": "1. 整體妝容方向……",
  "renderPromptEn": "Apply a natural everyday makeup look with lightweight satin-finish foundation, soft peach blush placed high on the cheeks, softly defined brows, warm beige eyeshadow, thin brown eyeliner, naturally separated lashes, and a muted rose lip tint. Preserve identity, facial structure, skin tone, hairstyle, pose, camera angle, background, and lighting. Change makeup only.",
  "analysisPackageId": "AN-a1b2c3d4e5f6",
  "schemaVersion": "2026-06-v1"
}
```

| 欄位 | 型別 | 必有 | 說明 |
| --- | --- | ---: | --- |
| `status` | string | 是 | 成功固定 `completed` |
| `provider` | string | 是 | 成功時固定為 `ollama` |
| `model` | string | 是 | 實際要求使用的模型名稱 |
| `fallbackUsed` | boolean | 是 | 相容欄位，固定為 `false`；本服務不提供假資料或本機規則建議 |
| `createdAt` | string | 是 | UTC ISO 8601 |
| `suggestion` | string | 是 | 給使用者看的完整建議，不可為空 |
| `renderPromptEn` | string | 是 | 給圖片渲染端的英文妝容指令，不可為空 |
| `analysisPackageId` | string | 是 | 必須等於請求的 `analysisPackage.id` |
| `schemaVersion` | string | 是 | 必須等於請求的 `analysisPackage.schemaVersion` |

### 2.4 將回應寫回原資料包

Suggestion API 回應不是另一份臉部分析。呼叫端應以不可變方式更新原包：

```json
{
  "generativeText": {
    "status": "completed",
    "provider": "ollama",
    "model": "gemma3",
    "suggestion": "1. 整體妝容方向……",
    "renderPromptEn": "Apply a natural everyday makeup look ... Change makeup only.",
    "error": null
  },
  "updatedAt": "2026-06-24T07:30:00.000000+00:00"
}
```

只更新 `generativeText` 與最外層 `updatedAt`；`id`、`faceAnalysis`、`images`、`render` 與 `recommendations` 原封不動。渲染端取得資料包後，應直接讀取 `analysisPackage.generativeText.renderPromptEn`。

## 3. 串接邊界與資料流

```text
前端 App / Web 或核心業務後端
  1. 建立 analysisPackage
  2. POST /suggest 傳送 JSON 封包
              ↓
妝容文字修飾服務（預設 8010）
  3. 驗證封包與抽取 faceAnalysis
  4. 建立繁中建議 prompt 與英文渲染 prompt
  5. 分別 POST Ollama /api/generate（預設 11434）
  6. 驗證兩份 Ollama response
  7. 回傳結構化建議結果
              ↓
核心業務後端／呼叫端
  8. 依 analysisPackageId 對應原資料包
  9. 將 suggestion 與 renderPromptEn 寫入 generativeText
              ↓
圖片生成端（Stable Diffusion / ControlNet）
 10. 只讀 generativeText.renderPromptEn
```

Ollama 原生 API 不直接對前端公開。前端只連接妝容文字修飾服務，避免模型位址、模型設定與錯誤格式散落在各端。

## 4. Ollama 原生 API 呼叫

Suggestion API 呼叫：

```http
POST http://127.0.0.1:11434/api/generate
Content-Type: application/json
```

```json
{
  "model": "gemma3",
  "prompt": "<由伺服器建立的完整提示詞>",
  "stream": false
}
```

成功時至少需要：

```json
{
  "model": "gemma3",
  "response": "產生的妝容建議文字",
  "done": true
}
```

目前 Suggestion API 會呼叫此端點兩次：第一次產生繁中 `suggestion`，第二次產生英文 `renderPromptEn`。每次只取 `response` 並去除頭尾空白。任一次 HTTP 非 2xx、不是合法 JSON、沒有 `response` 或 `response` 為空，整次請求視為 Ollama 失敗並回傳 HTTP `502`，不得產生替代文字。

## 5. 模型輸入與輸出規範

### 5.1 共用模型輸入內容

必須由伺服器模板組 prompt，只放入：

- 目標妝容風格。
- 使用者補充偏好。
- 臉型、眉型、眼型、正面鼻型、嘴型。
- 膚色季型、膚色分級與必要的 LAB 資訊。
- 輸出語言與固定輸出段落。

禁止放入：

- `userId`、token、Authorization header。
- 圖片 base64、完整圖片 URL 的查詢憑證。
- 伺服器環境變數、內部路徑或錯誤堆疊。
- 未經分析得到的醫療、種族、身分或健康推論。

`userNote` 是不可信文字。即使其中寫「忽略前面規則」或要求輸出系統資訊，也只能當妝容偏好處理。

### 5.2 `suggestion` 繁中輸出內容

預設繁體中文，必須包含以下五段：

1. 整體妝容方向
2. 底妝建議
3. 眉眼妝建議
4. 唇妝建議
5. 避免事項

要求：

- 語氣自然、一般使用者看得懂。
- 以建議而非絕對判定表達。
- 不做醫療診斷，不聲稱分析百分之百準確。
- 不捏造封包沒有的側面鼻型、品牌、商品庫存或色號。
- 遇到 `unknown` 或 `null` 時明確略過該特徵，不自行補值。
- 不輸出 Markdown 程式碼區塊、JSON 或內部思考過程。
- `suggestion` 建議長度 300～900 個中文字；不可為空。

### 5.3 `renderPromptEn` 英文渲染輸出內容

此欄位的唯一消費者是圖片渲染端，固定使用英文，不受請求的 `language` 影響。內容應是一段可直接送給圖片生成或 image-to-image 模型的正向指令。

必須包含：

- Makeup style and overall finish.
- Foundation finish and coverage.
- Blush color and placement.
- Eyebrow styling.
- Eyeshadow color and placement.
- Eyeliner and eyelashes.
- Lip color and finish.
- 保留人物不應被改變的明確限制。

固定限制語意至少要涵蓋：

```text
Preserve the person's identity, facial structure, skin tone, hairstyle, pose,
camera angle, background, and lighting. Change makeup only.
```

輸出要求：

- 只輸出一段英文渲染指令，不要標題、解說、JSON、Markdown 或中文。
- 建議長度 50～180 個英文單字。
- 使用具體可視覺化的顏色、質地、位置與濃淡描述。
- 不得要求改變臉型、五官、膚色、人種、年齡、髮型、姿勢、背景或光線。
- 不得捏造品牌、商品色號、側面鼻型或封包不存在的特徵。
- `unknown` 或 `null` 特徵直接略過，不可自行補值。
- 使用者要求若與保留身分或只改妝容衝突，以保留限制為優先。

英文渲染指令範例：

```text
Apply a soft natural everyday makeup look with lightweight satin-finish foundation,
subtle peach blush blended high on the cheeks, softly defined natural brows, warm beige
eyeshadow concentrated near the lash line, thin brown eyeliner, naturally separated lashes,
and a muted rose lip tint with a soft satin finish. Preserve the person's identity, facial
structure, skin tone, hairstyle, pose, camera angle, background, and lighting. Change makeup only.
```

## 6. 錯誤契約

### 6.1 現行錯誤格式

缺少分析資料，HTTP `400`：

```json
{
  "detail": {
    "error": {
      "message": "缺少 faceAnalysis 或 analysisPackage.faceAnalysis"
    }
  }
}
```

Ollama 連線或輸出失敗，HTTP `502`：

```json
{
  "detail": {
    "error": {
      "message": "Ollama 回應失敗：404 ..."
    }
  }
}
```

JSON 型別或結構無法通過 FastAPI/Pydantic 驗證時為 HTTP `422`。

### 6.2 建議正式錯誤格式

下一版建議統一為：

```json
{
  "status": "failed",
  "analysisPackageId": "AN-a1b2c3d4e5f6",
  "error": {
    "code": "OLLAMA_UNAVAILABLE",
    "message": "文字建議服務暫時無法使用",
    "retryable": true
  }
}
```

建議錯誤碼：

| HTTP | code | retryable | 情況 |
| ---: | --- | ---: | --- |
| 400 | `MISSING_FACE_ANALYSIS` | false | 沒有可用 `faceAnalysis` |
| 400 | `UNSUPPORTED_SCHEMA_VERSION` | false | 不支援的資料包版本 |
| 400 | `INVALID_ANALYSIS_PACKAGE` | false | id、狀態或欄位不合法 |
| 401 | `UNAUTHORIZED` | false | service token 無效 |
| 413 | `PAYLOAD_TOO_LARGE` | false | 封包過大，通常因誤傳圖片 base64 |
| 422 | `VALIDATION_ERROR` | false | JSON 型別或枚舉錯誤 |
| 429 | `RATE_LIMITED` | true | 請求過多 |
| 502 | `OLLAMA_UNAVAILABLE` | true | 無法連線或下游 HTTP 失敗 |
| 502 | `OLLAMA_INVALID_RESPONSE` | true | 下游沒有有效 `response` |
| 504 | `OLLAMA_TIMEOUT` | true | 超過模型逾時 |
| 500 | `INTERNAL_ERROR` | true | 未預期錯誤 |

正式環境不得把 Python exception、內部 IP、完整下游 response 或 prompt 回傳前端；詳細資料只寫伺服器 log，且 log 不記錄圖片 base64、token 與完整個資。

## 7. 禁止假資料與失敗處理

本服務不提供 fallback、本機規則建議、固定展示文字或其他假資料。只有 Ollama 兩份輸出皆成功時才能回 HTTP `200`。

判定規則：

- HTTP `200` 必須同時滿足 `provider="ollama"`、`fallbackUsed=false`、`suggestion` 非空及 `renderPromptEn` 非空。
- Ollama 無法連線、逾時、模型不存在、回應不是 JSON，或任一文字欄位為空時，回 HTTP `502`。
- 呼叫端收到非 `200` 時，應顯示「AI 建議暫時無法使用」或重試按鈕，不得顯示先前硬編碼建議冒充本次結果。
- `fallbackUsed` 暫時保留只是為了舊前端相容，數值永遠是 `false`；新版本可在共同升版後移除。

## 8. 環境變數與部署

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama 原生服務根網址，不含 `/api/generate` |
| `OLLAMA_MODEL` | `gemma3` | 預設模型；主機必須已下載 |
| `OLLAMA_TIMEOUT` | `120` | 呼叫 Ollama 的秒數逾時 |
| `OLLAMA_SUGGESTION_HOST` | `127.0.0.1` | 本機啟動監聽位址；容器通常由 uvicorn 指定 `0.0.0.0` |
| `OLLAMA_SUGGESTION_PORT` | `8010` | 對外建議服務 Port |
| `CORS_ORIGINS` | `*` | 多個前端來源以逗號分隔；正式環境不可用 `*` |

Docker 容器連宿主機 Ollama 時，目前使用：

```text
OLLAMA_BASE_URL=http://host.docker.internal:11434
```

若兩者都在 Docker Compose，應使用 Ollama service name，例如 `http://ollama:11434`，不要使用 `localhost`，因為容器內的 `localhost` 是容器自己。

上線前確認模型存在：

```powershell
ollama list
ollama pull gemma3
```

## 9. 相容性與版本規則

1. 目前送出的 `schemaVersion` 是 `2026-08-v2`（2026-08-03 新增 `labReliable` 時升版，見《給演算法端_膚色可信度旗標接入_2026-08-03》）。**不要對版本字串做等值比對**：`2026-06-v1` 與 `2026-08-v2` 的差別只有新增選填欄位，照第 2、3 條處理即可。真的要擋版本時請先與呼叫端議定，不要單方面改成硬性拒絕。
2. 新增選填欄位屬向後相容；刪除欄位、改名、改型別或改枚舉值必須升版。
3. 不認識的選填欄位應忽略並原樣保留，不得因此失敗。
4. 不認識的 `schemaVersion` 不得默默猜測欄位語意。
5. 英文代碼是服務契約；`raw` 中文標籤只供顯示與除錯。
6. 封包重送時使用相同 `analysisPackage.id`；建議正式版搭配 `X-Request-Id` 或 Idempotency-Key 防止重複計費／重複工作。

## 10. 驗收清單

Ollama 端交付前必須逐項通過：

- [ ] `GET /health` 能辨別 Suggestion API 正常但 Ollama 離線的狀態。
- [ ] 完整 `analysisPackage` 可成功產生五段繁體中文建議。
- [ ] 同一請求可產生非空的英文 `renderPromptEn`。
- [ ] `renderPromptEn` 只有英文渲染指令，沒有中文、JSON、Markdown 或分析解說。
- [ ] `renderPromptEn` 明確要求保留人物身分、五官結構、膚色、髮型、姿勢、鏡頭、背景與光線。
- [ ] 相容模式的單獨 `faceAnalysis` 可成功處理。
- [ ] 缺少兩種分析輸入時回 `400`。
- [ ] JSON 欄位型別錯誤時回 `422` 或統一驗證錯誤。
- [ ] 不支援的 schema version 有明確處理。
- [ ] `unknown`、`null`、缺少 LAB 時不會崩潰或捏造結果。
- [ ] `userNote` 含 prompt injection 時仍只輸出妝容建議。
- [ ] 圖片 base64 不會被寫進 prompt 或一般 log。
- [ ] Ollama 離線時回 `502 OLLAMA_UNAVAILABLE`，不回傳假建議。
- [ ] 專案中沒有固定展示用的中文建議或英文渲染假資料。
- [ ] 模型回空字串或非法 JSON 時視為錯誤。
- [ ] 請求超過 120 秒可正確逾時，不會永久卡住 worker。
- [ ] 回應 `suggestion` 不為空且包含五個指定段落，`renderPromptEn` 亦不可為空。
- [ ] 呼叫端只更新原資料包的 `generativeText` 與 `updatedAt`。
- [ ] 渲染端只讀 `generativeText.renderPromptEn`，不自行翻譯 `suggestion`。
- [ ] BASIC 與 PRO 資料包都可接受；不得從正面資料自行推論 `noseSide`。
- [ ] 同一 `analysisPackage.id` 可在 log 中追蹤請求，但 log 不含 userId、token 或圖片資料。

## 11. 最小測試命令

### 健康檢查

```powershell
Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8010/health"
```

### 最小建議請求

```powershell
$body = @{
  faceAnalysis = @{
    version = "BASIC"
    faceShape = "oval"
    browShape = "curved"
    eyeShape = "almond"
    noseFront = "standard"
    lipShape = "petal"
    skinTone = @{
      season = "spring"
      level = "白皙自然色"
      lab = @{ L = 74.21; a = 8.13; b = 18.64 }
    }
  }
  style = "日常自然妝"
  language = "zh-TW"
  userNote = "上班使用，眼妝不要太濃"
} | ConvertTo-Json -Depth 10

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8010/suggest" `
  -ContentType "application/json; charset=utf-8" `
  -Body $body
```

## 12. 現有程式位置

- `Ollama_suggestion.py`：Suggestion API、prompt 與 Ollama 呼叫；不含 fallback 假資料。
- `analysis_package.py`：資料包建立、正規化與建議回填。
- `ollama_suggestion_smoke_test.py`：最小 prompt 結構測試。
- `docker-compose.yml`：容器 Port 與 Ollama 位址設定。

實作判定以本文件和 `analysis_package.py` 的 `SCHEMA_VERSION` 一致為原則；若文件與執行中程式不一致，兩端必須先確認版本，不可自行選一邊猜測。

## 13. 官方操作文件

合作方實際安裝時應以官方文件的最新指令為準：

- Cloudflare：Create a locally-managed tunnel  
  `https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/create-local-tunnel/`
- Cloudflare：Quick Tunnels  
  `https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/`
- Cloudflare：Access service tokens  
  `https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/`
- Ollama：Generate API  
  `https://docs.ollama.com/api/generate`
