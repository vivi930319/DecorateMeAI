# 專案結構

> 2026-08-23 整理。整理前根目錄有 45 個 `.py` 混在一起，看不出哪些會部署、
> 哪些只是訓練或測試用的腳本。現在按「會不會進到正式環境」分開。

---

## 一分鐘看懂

```
PythonProject12/
│
├── face/          ← 【會部署】臉部分析（BASIC + PRO）
├── gateway/       ← 【會部署】AI Gateway 與 API 管理
├── render/        ← 【會部署】外接渲染端
├── suggestion/    ← 【會部署】文字建議（與 face 共用映像）
├── shared/        ← 【會部署】三邊共用的模組
│
├── training/      ← 不部署：模型訓練與評估
├── tests/         ← 不部署：測試
├── scripts/       ← 不部署：一次性文件產生腳本
├── tools/         ← 部分部署（只有 download_face_models.py 進映像）
│
├── models/        模型權重（.onnx 進映像，.pt 不進）
├── data/          訓練資料（不進映像）
└── 補充文件md檔案/  文件
```

**判斷原則：`face/`、`gateway/`、`render/`、`suggestion/`、`shared/` 裡的東西會上正式環境，其餘不會。**

---

## 三個方向

### `face/` — 臉部分析

| 檔案 | 做什麼 |
|---|---|
| `Face_analyzer_BASIC.py` | BASIC 分析主體：五官判斷、膚色取樣、四季型、亮度增強、CIEDE2000 色差 |
| `Face_analyzer_PRO.py` | PRO 分析：BASIC 全部 + 側臉鼻型 |
| `basic_roi_shadow.py` | 五個部位的 ConvNeXt 推論與融合（決定最終答案） |
| `basic_rule_trees.py` | 幾何決策樹的推論路徑（目前 `RULE_TREE_PARTS` 是空的，保留是為了回滾） |
| `rule_features.py` / `eye_features.py` | 幾何特徵定義 |
| `face_roi.py` | 部位 ROI 裁切 |
| `pro_nose_side_model.py` | PRO 側臉鼻型推論 |
| `analysis_package.py` | 對外的資料契約（前後端共用的欄位定義、類別別名） |
| `face_feedback.py` | 使用者對五官判斷的修正回饋（路由由它註冊） |
| `face_contributions.py` | 使用者同意提供的訓練樣本（只存部位 ROI，不存原圖） |
| `face_corrections.py` | 修正快取與類別正規化 |
| `mediapipe_ascii.py` | 必須早於 mediapipe import（Windows 路徑問題） |
| `cloud_start.py` | Cloud Run 進入點 |
| `Dockerfile` / `requirements.txt` | 這個服務的建置設定 |

進入點：`uvicorn Face_analyzer_BASIC:app` / `Face_analyzer_PRO:app`

### `gateway/` — Gateway 與 API 管理

| 檔案 | 做什麼 |
|---|---|
| `ai_gateway.py` | 唯一對瀏覽器開放的服務。所有上游都在它後面，負責 session、路徑白名單、限流、訪客票券、admin proxy |
| `admin_audit.py` | 高風險管理操作的稽核 |

進入點：`uvicorn ai_gateway:app`

### `render/` — 外接渲染端

| 檔案 | 做什麼 |
|---|---|
| `replicate_render_api.py` | 渲染 API（job 建立、查詢、媒體授權） |
| `replicate_render.py` | 實際呼叫 Replicate 的部分 |

進入點：`uvicorn replicate_render_api:app`

### `suggestion/` — 文字建議

`Ollama_suggestion.py`。上游是組員 Mac 上的 Ollama，透過 Cloudflare Tunnel 連。

> 它**與 face 共用同一個映像與 Dockerfile**（`face/Dockerfile` 會 COPY 它）。
> 分成獨立資料夾只是為了讀起來清楚，部署方式沒有變。

### `shared/` — 三邊共用

`api_errors.py`（統一錯誤格式）、`job_store.py`（job 狀態，Firestore + 記憶體 fallback）、
`image_safety.py`（上傳影像的安全處理）、`dev_server_utils.py`。

判斷標準很簡單：**兩個以上的服務都要 COPY 的，就放這裡。**

---

## ⚠️ 最重要的一件事：容器裡是扁平的

Dockerfile 寫的是：

```dockerfile
COPY face/Face_analyzer_BASIC.py .
COPY shared/job_store.py .
```

結尾那個 `.` 是關鍵 —— 檔案被**扁平**複製到容器的 `/app`，所以容器裡所有 `.py` 仍在同一層。

**因此 `import` 寫法完全不用改**，維持 `import job_store`、`import api_errors`。資料夾只存在於 repo 裡，是給人讀的；容器內的結構跟整理前一模一樣，部署行為零變化。

已驗證：容器內 19 個 `.py` 全在 `/app`，`import job_store, api_errors, image_safety, face_roi, analysis_package` 全部成功。

**本機直接跑**才需要讓 Python 找得到各資料夾，那個由 `pytest.ini` 的 `pythonpath` 處理：

```ini
pythonpath = . face gateway render shared suggestion
```

新增檔案時要記得：**`.dockerignore` 與 `.gcloudignore`（含 `.gateway` / `.render` 兩個變體）是白名單**，
沒放行的檔案 COPY 不到，build 會失敗。Dockerfile 的 COPY 和 ignore 的白名單，兩邊都要加。

---

## 不會部署的部分

### `training/` — 模型訓練與評估

`train_basic_cnn_roi.py`、`train_basic_features.py`、`train_pro_nose_side.py`、
`train_rf_classifiers.py`、`prepare_roi_cache.py`、`eval_rule_baseline.py`、
`predict_basic_roi.py`、`rerun_basic_from_csv.py`、`pro_nose_geometry.py`

這些產出 `models/` 底下的 `.onnx`。**推論用的 `.onnx` 會進映像，訓練腳本本身不會。**

### `tests/` — 測試

```bash
python -m pytest          # 全部，目前 171 個，約 6 秒
```

分層見 `補充文件md檔案/單元測試規格_2026-08-23.md`：L1 單元（不碰網路）、
L2 契約（FastAPI TestClient）、L3 整合（要起容器，在 `tools/api_tests/`）。

> `deploy_gateway_cloudrun.ps1` 與 `deploy_render_cloudrun.ps1` **會在部署前跑測試**，
> 失敗就中止部署。所以測試的位置改變時，那兩個腳本要一起改。

### `scripts/` — 一次性腳本

產生提案文件、線框圖、CSV 檢查用。跑過就好，不屬於任何服務。

### `tools/` — 工具

只有 `download_face_models.py` 與 `face_models_manifest.json` 會進 face 映像
（build 時驗證模型的大小與 SHA-256，缺模型就讓 build 失敗，避免做出「表面健康、
實際退回規則式」的映像）。`tools/api_tests/` 是需要容器的 L3 測試，不部署。

---

## 部署

三個服務現在是**同一套做法**（整理前 face 是特例）：

| 服務 | 腳本 | 建置設定 | ignore |
|---|---|---|---|
| face | `deploy_face_cloudrun.ps1` | `cloudbuild.face.yaml` | `.gcloudignore` |
| gateway | `deploy_gateway_cloudrun.ps1` | `cloudbuild.gateway.yaml` | `.gcloudignore.gateway` |
| render | `deploy_render_cloudrun.ps1` | `cloudbuild.render.yaml` | `.gcloudignore.render` |

每個 cloudbuild 都明確指定 `-f <資料夾>/Dockerfile`。

> face 原本用 `gcloud builds submit --tag .`，那條路徑會去找**根目錄的 Dockerfile**。
> 原始碼分資料夾之後根目錄不再有 Dockerfile，所以改成跟另外兩個一樣。

### 本機

```bash
docker compose up -d                      # 後端全部
cd ../web_frontend && docker compose up -d --build   # 前端
# 開 http://localhost:8080
```

| 服務 | 本機埠 |
|---|---|
| 前端 nginx | 8080 |
| gateway | 8015 |
| face BASIC | 8001 |
| face PRO | 8002 |
| 文字建議 | 8010 |
| 渲染（optional profile） | 8020 |
