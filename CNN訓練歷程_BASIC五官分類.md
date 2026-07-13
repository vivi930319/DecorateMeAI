# BASIC 五官分類 CNN 訓練歷程

紀錄日期：2026-07-13
相關腳本：`face_roi.py`、`tools/build_identity_map.py`、`prepare_roi_cache.py`、`train_basic_cnn_roi.py`
產出位置：`models/basic_features_roi/`

> **一句話結論**：五個部位的 CNN 都訓練完成也匯出 ONNX 了，但按人切分的 macro accuracy 只有
> 0.38–0.67，**全數低於規格書門檻 0.70，還不能上線**。真正的瓶頸不是模型或超參數，是資料量
> 太少（每類 30–70 張）加上標註本身有矛盾。

---

## 1. 為什麼要重做

BASIC 目前的臉型/眉型/眼型/鼻型/嘴型是 MediaPipe 幾何閾值規則判的（`Face_analyzer_BASIC.py`）。
規則式的問題是閾值一動整批結果就跳，而且像「桃花眼 vs 杏仁眼」這種差在眼型輪廓曲率的類別，
單靠幾個 landmark 比值分不開。

上一版 `train_basic_features.py`（整張臉 resize 160x160 餵 CNN）有兩個結構性缺陷：

1. **餵整張臉去判鼻型**：鼻子在 160x160 的圖裡只剩幾十個像素，模型更容易去學「這個人是誰」。
2. **隨機切分**：資料是影劇截圖，同一個藝人有多張照片，隨機切分會讓同一張臉同時出現在
   train 和 val，驗證分數虛高。

這一版：**裁部位 ROI 餵 CNN + 按人（identity）切分驗證**，並把「隨機切分」也跑一次當對照組，
把洩漏幅度實際量出來。

---

## 2. 資料集現況

`data/basic_full/grouped/<feature>/<label>/*.jpg`，共 1297 張。

| 部位 | 張數 | 類別（張數） |
|---|---|---|
| brow_shape | 194 | 彎月眉 71、落尾眉 62、一字眉 61 |
| eye_shape | 376 | 圓眼 64、細長眼 62、丹鳳眼 60、桃花眼 57、杏仁眼 53、下垂眼 47、瞇縫眼 33 |
| face_shape | 305 | 方形臉 63、心形臉 61、鵝蛋臉 61、圓形臉 60、長形臉 60 |
| lip_shape | 266 | 厚唇 62、花瓣唇 60、薄唇 58、M型唇 56、微笑唇 30 |
| nose_shape | 156 | 窄鼻 65、寬鼻 61、標準鼻 30 |

規格書（`DINOv2_臉部特徵分類模型規格書.md`）建議每類至少 100 張、正式版 300 張以上。
目前每類約 30–70 張，**只有建議量的三分之一到一半**。

---

## 3. 訓練前修掉的兩個坑

### 3.1 BGR / RGB 通道不一致（會讓模型上線無聲掉分）

`face_roi.crop_roi()` 回傳 BGR，`prepare_roi_cache.py` 原本直接把 BGR 存進快取；
但 `RoiDataset` 註解寫「已是 RGB」就直接正規化，而**線上推論**走的 `roi_to_tensor()`
會先做 BGR→RGB。

結果是訓練吃 BGR、推論吃 RGB。離線驗證分數完全正常，一上線就掉分，而且不會有任何報錯。

**修正**：快取階段就統一轉成 RGB 存，讓訓練與推論看到同一種通道順序。

### 3.2 缺 identity map，按人切分無法運作

`prepare_roi_cache.py` 會去讀 `data/roi_cache/identity_map.json`，但專案裡沒有任何腳本產生它。
沒有這個檔，所有樣本的 identity 都是 -1，`split_by_identity()` 會把它們全部丟進 train、
val 直接變空 → 訓練當場崩潰。

**修正**：補上 `tools/build_identity_map.py` —— InsightFace(buffalo_l) 抽 512 維人臉 embedding，
L2 正規化後做 cosine 階層式聚類（相似度門檻 0.45），把同一個人的照片聚成同一個 identity。

---

## 4. identity 聚類：偵測器一開始漏掉四成的臉

第一次跑 `build_identity_map.py`，**1297 張裡有 545 張（42%）抽不到人臉**。

檢查失敗樣本的尺寸（1036x778、1369x979…）跟成功樣本沒差別，排除「圖太小」。
真正原因是：**這批圖是截圖裁出來的大頭照，臉幾乎佔滿整個畫面、貼齊邊緣**。
RetinaFace 這類 anchor-based 偵測器需要臉周圍留一點餘裕才框得住，臉太大反而漏掉。

驗證方式與結果：

| 做法 | 20 張失敗樣本救回幾張 |
|---|---|
| 原圖重測（對照） | 0 / 20 |
| 補一圈 40% `BORDER_REPLICATE` 邊框 | **20 / 20** |
| 偵測門檻 0.5 → 0.25 | 0 / 20 |

門檻降到 0.25 一張都沒救回，確認不是信心分數的問題，而是尺度問題。

**修正**：`build_identity_map.detect()` 在第一次偵測失敗時補邊框重試。

重跑後：

```
完成：1296 張抽到臉、1 張沒抽到（標為 -1）
聚出 750 個身分，其中 245 個身分有多張照片
最大的群：13, 11, 11, 10, 10, 10, 10, 9, 9, 9 張
```

> 附帶發現：`prepare_roi_cache.py` 用的 MediaPipe FaceMesh **沒有**這個問題，1297 張全部成功。
> 同一批圖、兩個偵測器、結果差 42%，所以「換偵測器要重測」不是形式主義。

### 4.1 順手抓到的標註矛盾

聚類完做了一個檢查：同一個 identity 的照片，在同一個部位底下有沒有被標成不同類別？
**有 33 個身分中標**，例如：

```
identity 109: brow_shape/一字眉 + brow_shape/落尾眉
identity 21:  brow_shape/一字眉 + brow_shape/彎月眉
identity 34:  eye_shape/圓眼   + eye_shape/杏仁眼
```

同一個人的眉型不會在兩張截圖之間改變。這代表**標註本身有矛盾**（表情/角度不同就被標到不同類），
模型再怎麼訓練也學不到一致的決策邊界。這是準確率上不去的根因之一。

---

## 5. ROI 快取

```
1297 張成功、0 張失敗
face_shape   (1297, 128, 128, 3)
brow_shape   (1297,  96,  96, 3)
eye_shape    (1297,  96,  96, 3)
nose_shape   (1297,  96,  96, 3)
lip_shape    (1297,  96,  96, 3)
```

裁切定義集中在 `face_roi.ROI_SPECS`，訓練與線上推論共用同一份，避免兩邊飄掉。

---

## 6. 訓練結果

模型：MobileNetV3-small（ImageNet 預訓練），AdamW lr=3e-4、cosine 排程、label smoothing 0.05、
類別不平衡用 `WeightedRandomSampler` 補、val 佔 25%。**刻意不做水平翻轉**（落尾眉翻轉後
會變成上揚眉，等於餵錯標籤）。

### 第一輪（25 epochs）

| 部位 | 類別數 | 隨機切分（虛高） | 按人切分（可信） | 洩漏 |
|---|---|---|---|---|
| face_shape | 5 | 0.483 | **0.530** | −0.048 |
| brow_shape | 3 | 0.493 | **0.603** | −0.110 |
| eye_shape | 7 | 0.368 | **0.346** | +0.022 |
| nose_shape | 3 | 0.749 | **0.773** | −0.024 |
| lip_shape | 5 | 0.498 | **0.386** | +0.112 |

### 第二輪（40 epochs，其餘不變）

| 部位 | 類別數 | 隨機切分（虛高） | 按人切分（可信） | 洩漏 | 隨機猜 | vs 第一輪 |
|---|---|---|---|---|---|---|
| face_shape | 5 | 0.588 | **0.475** | +0.113 | 0.200 | −0.055 |
| brow_shape | 3 | 0.590 | **0.589** | +0.000 | 0.333 | −0.014 |
| eye_shape | 7 | 0.481 | **0.378** | +0.103 | 0.143 | +0.032 |
| nose_shape | 3 | 0.771 | **0.666** | +0.105 | 0.333 | −0.107 |
| lip_shape | 5 | 0.479 | **0.452** | +0.027 | 0.200 | +0.066 |

（數字是 macro accuracy = 各類 recall 的平均，不是 accuracy，所以少數類不會被多數類蓋掉。）

### 6.1 讀出來的三件事

**(1) 多訓練沒有用，而且分數本身不可靠。**
epochs 從 25 加到 40，三個部位變差、兩個變好，方向隨機。val set 只有 43–105 張，
一張分類結果就值 1–2 個百分點，**分數的隨機波動大約 ±0.1**。
換句話說「0.53 vs 0.47」這種差距在目前資料量下沒有意義，不能拿來選模型或調參。

**(2) 洩漏幅度證實了按人切分是必要的，但方向不穩。**
第二輪五個部位全部是隨機切分虛高（最多 +0.113），符合預期；但第一輪有三個是負的。
負值同樣是 val 太小造成的雜訊，不代表「隨機切分比較保守」。結論是：
**只看隨機切分的分數一定會高估，但要精確量出洩漏幅度，資料量還不夠。**

**(3) 沒有一個部位達標。** 規格書門檻是 macro F1 ≥ 0.70：

| 部位 | 按人切分 | 門檻 | 差距 |
|---|---|---|---|
| nose_shape | 0.666 | 0.70 | −0.03（最接近，但只有 3 類，且 val 僅 43 張） |
| brow_shape | 0.589 | 0.75 | −0.16 |
| face_shape | 0.475 | 0.70 | −0.23 |
| lip_shape | 0.452 | 0.70 | −0.25 |
| eye_shape | 0.378 | 0.70 | −0.32 |

**eye_shape 最慘**：7 個類別、376 張，平均每類 54 張，而「杏仁眼/桃花眼/丹鳳眼/細長眼」
四者的視覺差異本來就細微。per-class recall 顯示模型幾乎分不開細長眼（0.22）和下垂眼（0.17）。

---

## 7. 已修的部署地雷：ONNX 被拆成兩個檔

第一輪匯出後發現產出是 `face_shape.onnx` + `face_shape.onnx.data` 一對。
原因是 torch 2.12 的新 dynamo exporter 預設把權重另存成 external data。
MobileNetV3-small 才 6MB，完全不需要 external data，拆兩個檔只是多製造一個
「部署時少複製一個檔就靜默壞掉」的機會。

**修正**：`export_onnx()` 加 `dynamo=False`，改回單一自帶權重的 `.onnx`（每個 6MB）。
同時多存一份 `<part>.pt`，之後要重新匯出或接續訓練不必重跑整輪。

匯出後驗證（onnxruntime vs torch，batch=8）：

```
face_shape   最大差 9.89e-06   預測一致 True
brow_shape   最大差 1.08e-05   預測一致 True
eye_shape    最大差 3.36e-05   預測一致 True
nose_shape   最大差 1.06e-05   預測一致 True
lip_shape    最大差 3.24e-05   預測一致 True
```

動態 batch 軸可用，線上推論可以五個 ROI 一次餵進去。

---

## 8. 目前產出

```
models/basic_features_roi/
  <part>.onnx           線上推論用（onnxruntime，不需要 torch）
  <part>.pt             torch state dict，供重新匯出/接續訓練
  <part>_classes.json   類別順序 + 輸入尺寸
  <part>_metrics.json   兩種切分的完整 history、confusion matrix、per-class recall
  training_summary.json 五個部位的總表
data/roi_cache/
  rois.npz              1297 張 × 5 部位的 ROI（RGB uint8）
  index.json            每張圖的路徑、標籤、identity
  identity_map.json     750 個身分的聚類結果
```

**這批模型不要接進 BASIC 的正式輸出。** 依規格書第 10 節，未達門檻時應保留規則式作為
正式結果、模型只做 shadow prediction。

---

## 8.5 Shadow mode 上線（2026-07-13）

依規格書 13.1，把模型接進 BASIC 但**不讓它影響使用者看到的結果**。

新增 `basic_roi_shadow.py`，`Face_analyzer_BASIC.export_json()` 在組完規則式結果後多跑一次
ROI CNN，把預測放進新的 `模型分類` 欄位，並把「規則式 vs 模型」的差異寫進 log。

設計上的三個保險：

1. **只附加、不覆蓋**：`臉型`/`眉型`/`眼型`/`鼻型`/`嘴型` 五個正式欄位完全不動。
2. **整段包 try**：模型檔缺失、onnxruntime 載入失敗、ROI 裁切失敗，一律靜默跳過，
   正式分析照常回傳。實測把 `ROI_MODEL_DIR` 指到不存在的目錄，API 仍正常回應、
   只是 `模型分類` 欄位不出現。
3. **Kill switch**：`ROI_SHADOW_ENABLED=0` 整個關掉。

**確認不會汙染使用者收到的建議**：`analysis_package.normalize_face_analysis()` 會把整包原始輸出
放進 `faceAnalysis.raw`，但 `Ollama_suggestion.py` 是逐個具名取欄位（`faceShape` / `臉型`），
不是把 raw 整包塞進 prompt，所以 `模型分類` 不會流進化妝建議的生成內容。

本機實測（`/analyze`，一張標註為「圓眼」的圖）：

```
使用者看到的（規則式，跟以前一模一樣）：
   臉型: 圓形臉   眉型: 彎月眉   眼型: 桃花眼   鼻型: 標準鼻   嘴型: 薄唇

背景記錄的（CNN，使用者看不到）：
   臉型: 長形臉 (32%)   眉型: 彎月眉 (59%)   眼型: 杏仁眼 (94%)
   鼻型: 寬鼻 (58%)     嘴型: 薄唇 (33%)

log: ROI shadow 對照：一致 3/5　差異 -> 臉型: 規則=圓形臉 模型=長形臉(0.32)；...
```

> 這張圖的標註真值是「圓眼」—— 規則式說桃花眼、CNN 說杏仁眼 **94% 信心**，**兩個都錯**。
> 這正是為什麼要走 shadow：**CNN 的高信心不代表答對，直接接上去只會讓使用者拿到更差的答案。**

---

## 8.6 部署到 Cloud Run（2026-07-13）

已上線：`face-basic` revision **`face-basic-00010-lgm`**，
image `asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:shadow-20260713c`。

刻意**不覆蓋 `backend:latest`**：`face-basic` 與 `face-pro` 共用同一個 image，而
`Face_analyzer_PRO.py` 也 import 了 BASIC 的 `FaceAnalyzer`，覆蓋 latest 會讓 PRO 下次部署時
默默跟著跑 shadow。用獨立 tag 就只有 face-basic 動到，回滾也乾淨。

### 部署過程踩到的三個坑

**(1) `.gcloudignore` 不存在 → 模型檔根本上傳不到 Cloud Build。**
`gcloud builds submit` 上傳來源時看的是 `.gcloudignore`，**不是** `.dockerignore`；
而這個 repo 沒有 `.gcloudignore`，gcloud 會 fallback 去套 `.gitignore` —— 那是「`*` 全擋」的
白名單，沒放行 `models/`。結果就是模型檔不會被上傳，build 會在 `COPY models/` 直接失敗。
補上 `.gcloudignore`（內容對齊 Dockerfile 的 COPY 清單）後才 build 得起來。

**(2) Cloud Run 上 log 是啞的 → shadow 白跑。**
第一次部署後撈 Cloud Logging，**一筆 shadow 對照 log 都沒有**。
原因是這個專案從來沒有配置過 logging，而 Python root logger 預設是 WARNING —— 
`logger.info` 全部被丟掉。shadow 照樣吃 CPU，但比較資料一筆都沒留下，等於白花錢。
在 `Face_analyzer_BASIC.py` 補上 `logging.basicConfig(level=LOG_LEVEL 預設 INFO)` 才解決。

> 這個坑很值得記：**shadow mode 的全部價值就在那些 log**。服務有回應、欄位有出現，
> 看起來一切正常，但真正要的東西（對照資料）其實一筆都沒進去。「有回應」不等於「有效」。

**(3) onnxruntime 預設開滿執行緒，反而更慢。**
profiling 發現五個部位推論要 60ms，但把 `intra_op_num_threads` / `inter_op_num_threads`
設成 1 之後只要 **14ms（快 4 倍）**。模型很小（MobileNetV3-small / 96x96），多執行緒的排程開銷
蓋過運算本身，還會去跟 MediaPipe、InsightFace 搶 CPU —— 而 Cloud Run 上只有 1 個 CPU，
爭用只會更嚴重。已在 `basic_roi_shadow._load()` 綁成單執行緒。

### 效能實測（本機，同一張圖）

| | 耗時（中位數） |
|---|---|
| 分析本身（規則式，原本就有） | ~310 ms |
| shadow 額外增加 | **~70 ms**（佔 18%） |
| 單執行緒修正後 | 五部位推論 60ms → **14ms** |

線上端到端（含網路，連打三次）：**0.53 ~ 0.58 秒**。使用者感覺不到 shadow 的存在。

> 註：一開始量到「shadow 多花 480ms」是**錯的** —— 那是本機 CPU 波動造成的雜訊
> （同一組測量範圍 409–742ms）。用乾淨的量法（丟掉 warmup、量 shadow 區段本身）
> 才得到 70ms 這個真實數字。

### 線上驗證（不是「有回應」就算數）

```
$ curl -X POST https://face-basic-eu5pq7c53a-de.a.run.app/analyze -F "file=@圓眼.jpg"
規則式: 臉型=圓形臉  眼型=桃花眼  嘴型=薄唇      ← 使用者看到的，跟以前一模一樣
模型  : 臉型=長形臉  眼型=杏仁眼  嘴型=薄唇      ← 只在 模型分類 欄位

$ gcloud logging read '... textPayload:"ROI shadow 對照"'
INFO basic_roi_shadow: ROI shadow 對照：一致 2/5　差異 -> 臉型: 規則=圓形臉 模型=長形臉(0.39)；
眼型: 規則=桃花眼 模型=杏仁眼(0.93)；鼻型: 規則=標準鼻 模型=寬鼻(0.60)
```

對照 log 確認已進 Cloud Logging，中文編碼正確，可直接拿來統計一致率。

### 環境變數

| 變數 | 預設 | 用途 |
|---|---|---|
| `ROI_SHADOW_ENABLED` | `1` | 設 `0` 整個關掉 shadow，不需重新 build |
| `ROI_MODEL_DIR` | `models/basic_features_roi` | 模型目錄；指到不存在的路徑會靜默停用 |
| `LOG_LEVEL` | `INFO` | 低於 INFO 時 shadow 對照 log 不會輸出 |

### 一個還沒對齊的 gap

線上 `MAX_IMAGE_SIZE=2048`，但訓練資料是用 1024 產生的 ROI。
同一張圖線上與本機的信心值會差幾個百分點（臉型 39% vs 33%）。shadow 階段無所謂，
但**模型要轉正式輸出之前，這個解析度落差必須先對齊**。

---

## 9. 已知缺口

1. **沒有規則式 baseline 可比。** `train_basic_cnn_roi.py` 的 docstring 說會「額外算現行規則式
   在同一個 val set 上的分數當 baseline」，但這段**沒有實作**。所以現在無法回答最關鍵的問題：
   **CNN 到底有沒有贏過現在線上跑的規則式？** 這應該優先補上 —— 如果規則式在同一個 val set 上
   也只有 0.4，那 CNN 0.45 就不是「很差」而是「打平」。
2. **標註矛盾未清理**：33 個身分在同一部位有衝突標籤（見 4.1）。
3. **val set 太小**，分數波動 ±0.1，目前無法用來選模型或調參。

---

## 10. 下一步建議（依 CP 值排序）

1. **補上規則式 baseline 對照**（半天工，決定後續一切方向）。沒有這個數字，任何「模型好不好」
   的討論都是空的。
2. **清理標註矛盾**：先從 4.1 抓出的 33 個身分開始人工複驗，這是資料品質的下限問題。
3. **合併難分的類別**：eye_shape 7 類在 376 張的規模下不可能學好。考慮先合併成
   「圓眼 / 細長眼 / 下垂眼」3 大類把準確率做起來，之後資料補足再細分。
   nose_shape 只有 3 類就拿到最高分（0.666），這不是巧合。
4. **補資料到每類 100 張以上**，特別是微笑唇（30）、標準鼻（30）、瞇縫眼（33）。
5. **改用 5-fold cross validation** 取代單次 25% 切分，讓分數不再被單一 val set 的運氣左右。
6. 上述都做完再談 DINOv2 —— 規格書提的 frozen encoder + SVM 路線在小資料上理論上比
   從 MobileNet fine-tune 更穩，但**在資料品質修好之前換模型，只會換來另一組同樣不可信的數字**。
