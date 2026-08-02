# 新手程式碼教學導讀

這份文件是給剛接觸這個專案的人看的。它不取代 `README.md`，而是用更白話的方式說明「每個有程式碼的地方在做什麼」。

專案大方向很簡單：

```txt
前端 index.html
    讓使用者登入、上傳照片、看分析結果、選妝容風格、看商品

後端 FastAPI
    BASIC API 分析正面照
    PRO API 接收多角度照片，目前先沿用 BASIC 結果並保留精細分析欄位
    Ollama API 根據分析結果產生文字妝容建議

工具腳本
    準備資料、篩照片、自動標註、產生審核表、套用審核結果、測試 API
```

## 先認識常見名詞

- API：前端跟後端溝通的入口。例如前端把照片送到 `/analyze`，後端回傳臉型、眼型、膚色等結果。
- FastAPI：這個專案後端用的 Python 網頁 API 框架。
- MediaPipe FaceMesh：Google 的臉部特徵點工具，會找出臉上的眼睛、鼻子、嘴巴、臉輪廓位置。
- InsightFace：用來做臉部偵測的模型工具。
- ONNX：模型檔格式。這裡的 `eyelid_model.onnx` 用在眼皮/眼型相關判斷。
- BASIC：只用正面照片做比較穩定的分析。
- PRO：預計用正面、45 度、側面照片做更細的分析，目前入口已經先做好。
- smoke test：快速測試服務有沒有活著、API 能不能正常回應的小測試。

## 建議閱讀順序

1. 先看 `index.html`：知道使用者會怎麼操作。
2. 再看 `Face_analyzer_BASIC.py`：知道照片送到後端後怎麼分析。
3. 再看 `Face_analyzer_PRO.py`：知道多角度 API 目前怎麼包裝 BASIC。
4. 再看 `Ollama_suggestion.py`：知道怎麼把臉部分析變成妝容建議文字。
5. 最後看工具腳本：這些多半是資料整理、測試、審核用。

## 前端：index.html

`index.html` 是目前的網頁前端。它把 HTML、CSS、JavaScript 都寫在同一個檔案裡。

### HTML 區塊

HTML 負責畫出使用者看到的頁面，例如：

- 登入頁
- 註冊頁
- 忘記密碼頁
- 主選單
- 臉部分析頁
- 風格選擇頁
- 妝容建議頁
- 商品分類頁
- 商品詳情頁
- 收藏頁
- 個人資料相關頁面

新手可以把 HTML 想成「網頁骨架」。

### CSS 區塊

`<style>` 裡面的內容是 CSS，負責控制畫面長相，例如：

- 背景顏色
- 字體
- 按鈕樣式
- 卡片排版
- 上傳照片區塊
- 商品列表
- 手機版畫面調整

新手可以把 CSS 想成「裝潢和排版」。

### JavaScript 資料

`<script>` 裡最前面有幾個資料陣列：

- `STYLES`：妝容風格清單，例如日常、甜美、韓系等。
- `CATEGORIES`：商品分類，例如底妝、眼妝、唇妝。
- `ALL_PRODUCTS`：商品資料，包含名稱、分類、價格、說明。

這些資料目前是寫死在前端，還沒有真的接資料庫。

### JavaScript 狀態變數

- `currentUser`：目前登入的使用者。
- `favorites`：收藏商品清單，存到 `localStorage`。
- `analyzeMode`：目前是 BASIC 還是 PRO。
- `selectedFile`：BASIC 模式選到的照片。
- `proFiles`：PRO 模式選到的正面、左 45 度、右 45 度、側面照片。
- `cameraStream`：相機開啟後的串流。
- `analysisResult`：後端回傳的臉部分析結果。
- `selectedStyleId`：使用者選到的妝容風格。

### JavaScript 函式

- `navigate(page)`：切換頁面。它會把所有頁面隱藏，只顯示指定頁面。
- `doLogin()`：模擬登入，把使用者資料存到瀏覽器。
- `guestLogin()`：訪客登入。
- `doRegister()`：模擬註冊。
- `doLogout()`：登出並清掉登入狀態。
- `toggleUserMenu()`：打開或關閉右上角使用者選單。
- `onFileSelected(e)`：BASIC 模式選照片後，把照片記到 `selectedFile`。
- `showPreview(file)`：把選到的照片顯示在畫面上。
- `setAnalyzeMode(mode)`：切換 BASIC / PRO 模式。
- `onProFileSelected(e, key)`：PRO 模式選不同角度照片。
- `startCamera()`：開啟瀏覽器相機。
- `capturePhoto()`：從相機畫面截一張照片，轉成可以上傳的檔案。
- `stopCamera()`：關閉相機。
- `labToRgb(L, a, b)`：把後端回傳的 LAB 顏色轉成網頁可以顯示的 RGB 顏色。
- `doAnalyze()`：最重要的前端函式。它把照片用 `fetch()` 送到後端 API，等待分析結果，再把結果顯示在畫面上。
- `renderStyles()`：把妝容風格清單畫到畫面上。
- `selectStyle(id)`：記住使用者選了哪個風格。
- `confirmStyle()`：確認風格後進入妝容建議頁。
- `generateDynamicAdvice(styleId, face, eye, season)`：根據風格、臉型、眼型、膚色季型產生簡單建議。
- `renderMakeupAnalysis()`：把妝容分析結果畫到畫面上。
- `renderCategories()`：畫出商品分類。
- `openCategory(cat)`：打開某個商品分類。
- `openProduct(id)`：打開商品詳情。
- `toggleFav(id)`：收藏或取消收藏商品。
- `renderFavorites()`：畫出收藏商品列表。

## 後端主程式：Face_analyzer_BASIC.py

這是 BASIC 正面照分析 API，也是目前最重要的後端檔案。

### 它提供的 API

- `GET /`：回傳 `index.html`。
- `GET /health`：檢查服務是否正常，也會回傳目前 jobs 狀態。
- `POST /analyze`：同步分析一張正面照。
- `POST /v1/face/analyze/basic`：跟 `/analyze` 做同一件事，只是路徑比較正式。
- `POST /v1/face/analyze/basic/jobs`：建立非同步分析工作。
- `GET /v1/face/analyze/basic/jobs/{job_id}`：查工作進度。
- `GET /v1/face/analyze/basic/jobs/{job_id}/result`：拿完成後的結果。

### 全域設定

- `_insight_app`：InsightFace 模型，第一次用到才載入。
- `_eyelid_sess`：ONNX 眼皮模型，第一次用到才載入。
- `_face_mesh`：MediaPipe FaceMesh，第一次用到才建立。
- `_jobs`：存在記憶體裡的非同步工作清單。
- `MAX_IMAGE_SIZE`：限制圖片最大尺寸，避免太大的圖片拖慢服務。
- `FACE_JOB_TIMEOUT_SECONDS`：job 最多可以跑多久。
- `FACE_JOB_RETENTION_SECONDS`：完成的 job 保留多久。
- `FACE_JOB_MAX_COUNT`：最多保留多少 job。

### 重要工具函式

- `_get_insight()`：取得 InsightFace 模型。模型很重，所以只初始化一次。
- `_get_eyelid_sess()`：取得眼皮 ONNX 模型。如果模型檔不存在，就回傳 `None`。
- `_get_face_mesh()`：取得 MediaPipe FaceMesh。也是只初始化一次。
- `shutdown_event()`：服務關閉時，把 FaceMesh 關掉。
- `_now_iso()`：產生現在時間字串。
- `_parse_iso(value)`：把時間字串轉回時間物件。
- `_seconds_since(value, now)`：計算某個時間到現在過了幾秒。
- `_mark_timed_out_jobs(now)`：把跑太久的 job 標成失敗。
- `_cleanup_jobs()`：清掉過期或太多的 jobs。
- `_job_stats()`：統計 queued、processing、completed、failed 各有幾個。
- `_job_view(job)`：回傳 job 資訊，但不直接把完整結果塞進列表。
- `_run_basic_job(job_id, contents)`：背景執行 BASIC 分析。

### FaceAnalyzer 類別

`FaceAnalyzer` 是真正做臉部分析的地方。使用方式大概是：

```python
analyzer = FaceAnalyzer(contents)
result = analyzer.export_json()
```

可以把它想成：

```txt
圖片 bytes
→ 解碼成 OpenCV 圖片
→ 找臉
→ 找臉部特徵點
→ 計算臉型、眉型、眼型、鼻型、嘴型、膚色
→ 輸出 JSON
```

主要方法：

- `__init__()`：讀取圖片、縮放圖片、呼叫模型找臉與臉部特徵點。
- `_pt()`：把某個 landmark 轉成圖片上的座標。
- `_dist()`：計算兩點距離。
- `_collect_landmark_indices()`：整理一組臉部特徵點。
- `_align_points_by_eyes()`：用眼睛位置校正臉部角度，避免頭歪影響判斷。
- `_width_between()`：計算某一高度左右邊界的寬度。
- `get_face_shape()`：判斷臉型。
- `get_eyebrow_shape()`：判斷眉型。
- `_eye_side_metrics()`：計算單邊眼睛的寬、高、角度等資訊。
- `get_eye_shape()`：判斷眼型。
- `get_nose_shape()`：判斷鼻型。
- `get_lip_shape()`：判斷嘴型。
- `_landmark_region_mask()`：用臉部特徵點做出某個區域的遮罩。
- `_bgr_mean_to_lab()`：把 OpenCV 的 BGR 平均色轉成 LAB。
- `_lab_mean_from_mask()`：計算遮罩區域的 LAB 平均色。
- `_skin_texture_mask()`：找出「夠平滑、像皮膚」的區域。頭髮有細密紋理，皮膚沒有——顏色分不出棕髮與皮膚時，靠紋理還分得出來。
- `_skin_sample_reliability()`：判斷這次的膚色取樣可不可信。臉頰被頭髮或陰影蓋住時，量到的亮度會忽明忽暗，就標成不可信。
- `_classify_shade_12grid()`：把膚色分類到 12 宮格。
- `_classify_season()`：判斷春夏秋冬膚色季型。
- `get_skin_color()`：計算膚色資訊。
- `export_json()`：把所有分析結果包成前端/API 可以用的 JSON。

## PRO API：Face_analyzer_PRO.py

這個檔案是 PRO 多角度分析入口。

目前 PRO 的重點不是已經完成所有精細分類，而是先把 API 介面做出來，讓前端和未來 iOS App 可以先照固定格式上傳多角度照片。

### 它提供的 API

- `GET /health`：檢查 PRO 服務狀態。
- `POST /analyze-pro`：同步分析 PRO 照片。
- `POST /v1/face/analyze/pro`：正式版 PRO 同步入口。
- `POST /v1/face/analyze/pro/jobs`：建立 PRO 非同步工作。
- `GET /v1/face/analyze/pro/jobs/{job_id}`：查 PRO 工作進度。
- `GET /v1/face/analyze/pro/jobs/{job_id}/result`：拿 PRO 分析結果。

### 重要函式

- `_read_image(file, label)`：讀取上傳照片，並檢查是不是空檔。
- `_merge_basic_and_pro(front_result, side_available)`：把 BASIC 正面照結果包成 PRO 結果，並加上「精細分析狀態」欄位。
- `_now_iso()`、`_parse_iso()`、`_seconds_since()`：時間處理。
- `_mark_timed_out_jobs()`、`_cleanup_jobs()`、`_job_stats()`、`_job_view()`：job 管理，邏輯跟 BASIC 類似。
- `_run_pro_job(job_id, front_bytes, angle_bytes)`：背景執行 PRO 分析。現在主要是先分析正面照，再加上 PRO 欄位。
- `health()`：回傳服務狀態。
- `analyze_pro()`：同步 PRO 分析。
- `create_pro_job()`：建立非同步 PRO job。
- `get_pro_job()`：查 job 狀態。
- `get_pro_job_result()`：拿 job 結果。

## 原始整合版：Face_analyzer.py

這個檔案看起來是早期整合版或參考版。它也有 FastAPI、`/analyze`，以及一個 `FaceAnalyzer` 類別。

如果你要開發正式 BASIC API，優先看 `Face_analyzer_BASIC.py`。

這個檔案的作用：

- 保留原本整合版邏輯。
- 可用來對照 BASIC 拆分前的寫法。
- 有些分析方法跟 BASIC 類似，例如臉型、眉型、眼型、鼻型、嘴型、膚色。

## 測試/舊版分析：Face_test.py

`Face_test.py` 是另一份測試或實驗版臉部分析程式。

它也有：

- FastAPI app
- `/` 回傳 `index.html`
- `/analyze` 上傳照片分析
- `FaceAnalyzer` 類別

跟 BASIC 相比，它多了一些實驗方法：

- `_face_shape_ratios()`：計算臉型比例。
- `_eyelid_crease_score()`：計算眼皮摺痕分數。
- `_classify_eyelid_type()`：判斷眼皮類型。

新手可以把它看成「曾經用來測試判斷規則的版本」。

## 文字建議 API：Ollama_suggestion.py

這個檔案負責把臉部分析結果變成文字妝容建議。

### 它提供的 API

- `GET /health`：檢查服務是否正常，並測試能不能連到 Ollama。
- `POST /suggest`：接收分析資料，產生妝容建議。

### 重要設定

- `OLLAMA_BASE_URL`：Ollama 服務位置，預設是 `http://127.0.0.1:11434`。
- `OLLAMA_MODEL`：使用的模型名稱，預設 `gemma3`。
- `OLLAMA_TIMEOUT`：等 Ollama 回應的秒數。
- `ALLOW_FALLBACK`：如果 Ollama 失敗，是否回傳內建的簡單建議。

### 重要結構與函式

- `SuggestRequest`：定義 `/suggest` 可以接收哪些欄位。
- `_now_iso()`：產生現在時間。
- `_extract_face_analysis(payload)`：從 `analysisPackage` 或 `faceAnalysis` 裡拿出臉部分析資料。
- `_pick(face_analysis, english_key, chinese_key, default)`：同時支援英文 key 和中文 key。
- `build_prompt(payload)`：把使用者風格、臉型、眉型、眼型、鼻型、嘴型、膚色整理成給 AI 的 prompt。
- `fallback_suggestion(payload)`：Ollama 不能用時，回傳一段固定邏輯產生的建議。
- `call_ollama(prompt, model)`：真的呼叫 Ollama `/api/generate`。
- `health()`：檢查 API 和 Ollama 連線。
- `suggest(payload)`：主要入口，負責產生建議。

## API 測試：backend_smoke_test.py

這個檔案是用來快速測 BASIC / PRO API 的。

它會：

1. 找一張預設測試圖片。
2. 測 `GET /health`。
3. 測同步分析 API。
4. 測非同步 jobs API。
5. 檢查回傳結果有沒有基本欄位。

重要函式：

- `pick_default_image()`：找可以拿來測試的圖片。
- `request_json(method, url)`：發送 HTTP 請求並解析 JSON。
- `post_image(url, field_name, image_path, extra_files)`：上傳圖片。
- `wait_for_job(base_url, job_id)`：輪詢 job，等它完成。
- `assert_result_shape(result, mode)`：檢查結果格式。
- `test_service(...)`：測某一個服務。
- `main()`：整個測試流程入口。

## Ollama 測試：ollama_suggestion_smoke_test.py

這個檔案用來快速測 `Ollama_suggestion.py`。

它會測：

- `/health` 是否正常。
- `/suggest` 是否能根據假資料回傳建議。
- fallback 是否能在 Ollama 不可用時提供文字。

主要函式：

- `main()`：執行整個測試。

## 資料準備：prepare_data.py

這個檔案用來準備眼皮模型訓練資料。

它處理 CelebA 資料集，目標是從人臉圖片中切出眼睛區域，整理成可以訓練模型的資料。

重要設定：

- `KAGGLE_DATASET`：Kaggle 上的 CelebA 資料集名稱。
- `DOWNLOAD_DIR`：下載資料放哪裡。
- `OUTPUT_DIR`：輸出整理後資料的位置。
- `IMG_DIR`：原始圖片資料夾。
- `ATTR_FILE`：CelebA 屬性標註檔。
- `MAX_PER_CLASS`：每個類別最多取幾張。
- `PATCH_SIZE`：眼睛裁切圖大小。
- `MARGIN_RATIO`：裁切眼睛時多留多少邊界。

重要函式：

- `download_celeba()`：下載 CelebA。
- `load_labels()`：讀取標註資料。
- `extract_eye_patches(img_bgr)`：從臉部圖片切出眼睛圖。
- `process_class(file_list, class_name)`：處理某個類別的圖片。

## 訓練眼皮模型：Traineyelid.py

這個檔案用來訓練眼皮/眼型相關模型。

重要設定：

- `DATA_DIR`：訓練資料資料夾。
- `MODEL_PT`：PyTorch 模型輸出檔。
- `MODEL_ONNX`：ONNX 模型輸出檔。
- `IMG_SIZE`：輸入圖片大小。
- `BATCH_SIZE`：每次訓練拿幾張圖。
- `EPOCHS`：訓練幾輪。
- `LR`：學習率。
- `VAL_RATIO`：驗證集比例。
- `DEVICE`：用 CPU 或 GPU。
- `train_tf`、`val_tf`：訓練和驗證時的圖片轉換流程。

主要函式：

- `main()`：載入資料、建立模型、訓練、驗證、輸出模型。

## BASIC 圖片篩選：select_basic_usable_images.py

這個檔案用來從大量圖片中挑出 BASIC 可用的正面照。

重要函式：

- `landmark_xy(landmarks, index, width, height)`：把 FaceMesh landmark 轉成圖片座標。
- `assess_basic_usable(image_path, face_mesh)`：判斷一張圖是否適合 BASIC，例如臉是否清楚、是否接近正面。
- `main()`：跑完整批圖片篩選流程。

## BASIC 自動標註：auto_label_basic_dataset.py

這個檔案會呼叫 BASIC 分析邏輯，幫資料集圖片先產生初步標註。

重要函式：

- `flatten_result(result)`：把巢狀 JSON 攤平成 CSV 比較好看的欄位。
- `main()`：讀圖片、分析、輸出自動標註結果。

## 批次 BASIC 分類：batch_basic_classify.py

這個檔案也是批次跑 BASIC 分析用的工具。

重要設定：

- `DEFAULT_SOURCE`：預設圖片來源資料夾。
- `DEFAULT_OUTPUT`：預設輸出 CSV。

重要函式：

- `existing_ids(output_csv)`：讀取已經處理過的圖片 ID，避免重複跑。
- `ensure_header(output_csv)`：確保 CSV 有表頭。
- `coarse_basic_result(image_path)`：對一張圖片跑粗略 BASIC 分析。
- `row_from_result(image_path, result)`：把成功結果轉成 CSV 一列。
- `row_from_error(image_path, exc)`：把失敗原因轉成 CSV 一列。
- `main()`：批次處理整個資料夾。

## 產生審核表：make_review_sheets.py

這個檔案用來把自動標註結果做成方便人工檢查的圖片/表格。

重要函式：

- `draw_wrapped(draw, text, xy, max_chars, fill)`：在圖片上畫可以自動換行的文字。
- `compact_reason(reason)`：把原因文字縮短，方便放進審核表。
- `main()`：產生審核用輸出。

## 套用人工審核結果：apply_review_decisions.py

這個檔案用來把人工審核後的決定套回資料集。

重要設定：

- `VALID_DECISIONS`：允許的審核決定，例如接受、拒絕、修改等。

重要函式：

- `read_csv(path)`：讀 CSV。
- `write_csv(path, rows, fieldnames)`：寫 CSV。
- `append_note(existing, note)`：把新備註接到舊備註後面。
- `main()`：讀取審核結果並套用。

## CSV 檢查：check_csv.py

這是很小的檢查腳本。

它主要做：

- 設定 `ATTR_FILE`。
- 用 pandas 讀取 CSV 或屬性檔。
- 快速檢查資料內容。

這類檔案通常是開發過程中用來確認資料格式是否正確。

## Dockerfile

`Dockerfile` 是用來把後端服務包成 Docker image 的設定。

逐段看：

- `FROM python:3.10-slim`：使用 Python 3.10 的輕量版環境。
- `WORKDIR /app`：容器裡的工作資料夾是 `/app`。
- `ENV PYTHONDONTWRITEBYTECODE=1`：不要產生 `.pyc` 快取檔。
- `ENV PYTHONUNBUFFERED=1`：讓 log 立即輸出。
- `apt-get install libgl1 libglib2.0-0`：安裝 OpenCV 需要的 Linux 套件。
- `COPY requirements.txt .`：把依賴清單複製進容器。
- `pip install -r requirements.txt`：安裝 Python 套件。
- `COPY Face_analyzer*.py`、`COPY Ollama_suggestion.py`、`COPY index.html`：把程式碼複製進容器。
- `EXPOSE 8001 8002 8010`：宣告容器可能使用的 port。
- `CMD ... Face_analyzer_BASIC:app ...`：預設啟動 BASIC API。

## docker-compose.yml

`docker-compose.yml` 可以一次啟動多個服務。

目前有三個服務：

- `face_analysis_basic`：BASIC API，對外 port 是 `8001`。
- `face_analysis_pro`：PRO API，對外 port 是 `8002`。
- `ollama_suggestion`：文字建議 API，對外 port 是 `8010`。

重要概念：

- `build: .`：用目前資料夾的 Dockerfile 建 image。
- `ports`：把容器內 port 映射到本機 port。
- `environment`：設定環境變數，例如 timeout、模型名稱。
- `volumes`：把本機的 ONNX 模型檔掛進容器。
- `command`：覆蓋 Dockerfile 預設啟動命令，讓不同服務啟動不同 API。
- `restart: always`：服務掛掉時自動重啟。

## requirements.txt

這個檔案列出 Python 需要安裝的套件。

- `fastapi`：建立 API。
- `uvicorn`：啟動 FastAPI 的伺服器。
- `python-multipart`：讓 FastAPI 可以接收上傳檔案。
- `numpy<2`：數值計算，限制小於 2 是為了跟部分套件相容。
- `opencv-python-headless`：處理圖片，不含 GUI。
- `mediapipe`：臉部特徵點。
- `onnxruntime`：執行 ONNX 模型。
- `insightface`：臉部偵測/臉部分析模型工具。
- `requests`：呼叫其他 HTTP API，例如 Ollama。

## setup.bat

`setup.bat` 是 Windows 批次檔，通常用來幫忙建立或啟動環境。

新手看到 `.bat` 可以先知道：

- 它不是 Python。
- 它是 Windows 命令列腳本。
- 通常會做安裝套件、啟動服務、設定環境等事情。

## .dockerignore

`.dockerignore` 告訴 Docker build 時哪些檔案不要放進 image。

常見用途：

- 排除 `.git`
- 排除虛擬環境 `.venv`
- 排除暫存檔或大型資料

這樣 Docker image 會比較小，build 也比較快。

## .gitignore

`.gitignore` 告訴 Git 哪些檔案不要追蹤。

雖然這份教學不做任何 Git 操作，但你仍然可以把它理解成：

```txt
專案裡有些檔案是本機產生的、很大、或每個人都不同
這些檔案不應該放進版本控制
```

## 常見執行方式

### 啟動 BASIC API

```bash
uvicorn Face_analyzer_BASIC:app --host 0.0.0.0 --port 8001
```

### 啟動 PRO API

```bash
uvicorn Face_analyzer_PRO:app --host 0.0.0.0 --port 8002
```

### 啟動文字建議 API

```bash
uvicorn Ollama_suggestion:app --host 0.0.0.0 --port 8010
```

### 用 Docker Compose 啟動全部服務

```bash
docker compose up --build
```

## 新手除錯方向

如果前端按「開始分析」失敗，先看：

1. BASIC API 有沒有啟動在 `http://127.0.0.1:8001`。
2. 瀏覽器 Console 有沒有錯誤。
3. 後端終端機有沒有錯誤訊息。
4. 圖片是不是空檔或格式不支援。
5. `eyelid_model.onnx` 是否存在，雖然它不存在時部分邏輯會跳過，但眼皮相關分析會受影響。

如果 PRO 失敗，先看：

1. PRO API 有沒有啟動在 `http://127.0.0.1:8002`。
2. 正面照 `front` 是否有上傳，因為目前 PRO 仍然靠正面照跑 BASIC 分析。
3. 其他角度照片是否是空檔。

如果文字建議失敗，先看：

1. `Ollama_suggestion.py` 有沒有啟動在 `http://127.0.0.1:8010`。
2. Ollama 本機服務有沒有啟動。
3. `OLLAMA_MODEL` 指定的模型是否已下載。
4. `OLLAMA_ALLOW_FALLBACK=true` 時，即使 Ollama 失敗也應該會回傳 fallback 建議。

## 一句話總結

這個專案目前可以看成三層：

```txt
index.html
    使用者操作畫面

Face_analyzer_BASIC.py / Face_analyzer_PRO.py
    圖片分析 API

Ollama_suggestion.py
    根據分析結果產生妝容文字建議
```

其他 Python 檔大多是資料準備、模型訓練、批次標註、人工審核和 API 測試用的輔助工具。
