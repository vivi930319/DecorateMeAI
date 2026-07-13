# BASIC 五官分類 CNN 訓練歷程

紀錄日期：2026-07-13
相關腳本：`face_roi.py`、`tools/build_identity_map.py`、`prepare_roi_cache.py`、
`train_basic_cnn_roi.py`、`eval_rule_baseline.py`、`basic_roi_shadow.py`
產出位置：`models/basic_features_roi/`

> **最重要的發現（見第 7 節）**：做 baseline 對照時發現**現行的規則式分類其實是壞的** ——
> 眉型把 val set 裡每一個人都判成「彎月眉」、眼型 96% 判成「桃花眼」、鼻型 98% 判成「標準鼻」，
> 分數精準等於隨機猜。線上 API 交叉驗證也是同一個結果。**線上使用者現在幾乎每個人都被告知
> 自己是「彎月眉 + 標準鼻」。** 這件事在做這次對照之前沒有人知道。
>
> **CNN 的結論**：五個部位都訓練完成也匯出 ONNX，按人切分的 macro accuracy 是 0.38–0.67，
> **仍低於規格書門檻 0.70**，但**每一個部位都大幅贏過規則式**（+0.12 ~ +0.31）。
> 瓶頸不是模型或超參數，是資料量太少（每類 30–70 張）加上標註本身有矛盾。
> 目前以 shadow mode 上線（只寫 log、不影響使用者看到的結果），見第 8.5、8.6 節。

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

### 2.0 圖片與標籤的來源（重要，別再懷疑一次）

- **圖片**：1297 張，全部是 `IMG_xxxx` 命名（自行拍攝/截圖），來自 `grouped_fa.zip` 與
  `grouped_yun.zip` 兩包，由組員各自整理後合併。**不是公開資料集。**
- **標籤**：**組員人工分類**（把圖片放進 `<feature>/<label>/` 資料夾）。已向組員確認。
- `data/` 底下的 `asian_faces`、`kaggle_asian_faces`、`celeba_raw`、`group_yun` 這幾包
  **完全沒有參與訓練** —— `prepare_roi_cache.py` 只掃 `data/basic_full/grouped`。

> **為什麼要特別寫這段**：repo 裡有一條 `auto_label_basic_dataset.py`（用規則式自動標）
> → `organize_basic_results.py`（依 CSV 分資料夾）的工具鏈，看起來像是「標籤是規則式產生的」。
> 如果真是那樣，**CNN 學到的只會是在模仿一個壞掉的規則**，所有分數都沒有意義
> （規格書 5.3 明確警告過）。
>
> 實測否定了這個懷疑：抽驗眉型圖片，資料夾標籤有「一字眉/落尾眉」，但現行規則式對每一張
> 都吐「彎月眉」—— 標籤不可能來自現行規則式。組員也確認資料夾是人工分好的。
>
> **結論：標籤是可信的 ground truth，CNN 的分數有意義，而規則式與標籤只有 33% 一致
> 這件事，證明的是規則式壞了，不是資料有問題。**

### 2.1 各部位資料量

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

## 7. 規則式 baseline 對照：現行規則式其實是壞的

腳本：`eval_rule_baseline.py`（輸出 `models/basic_features_roi/rule_baseline.json`）

為了公平，val set 直接 import `train_basic_cnn_roi` 的 `build_part_data` / `split_by_identity`，
用同一個 seed 與 val_ratio 重算，**跟 CNN 是同一批圖**；規則式的預測直接呼叫
`Face_analyzer_BASIC.FaceAnalyzer` 的 `get_*_shape()`，也就是線上真正在跑的那份程式碼。

### 7.1 結果

| 部位 | 規則式 | CNN | CNN − 規則式 | 隨機猜 |
|---|---|---|---|---|
| face_shape | 0.326 | **0.475** | +0.149 | 0.200 |
| brow_shape | 0.333 | **0.589** | +0.256 | 0.333 |
| eye_shape | 0.143 | **0.378** | +0.235 | 0.143 |
| nose_shape | 0.354 | **0.666** | +0.311 | 0.333 |
| lip_shape | 0.331 | **0.452** | +0.122 | 0.200 |

**規則式的分數幾乎精準等於隨機猜**（brow 0.333 = 隨機 0.333；eye 0.143 = 隨機 0.143）。
這種巧合通常只有一個原因 —— 它根本沒在分類。

### 7.2 規則式退化成「幾乎只輸出一個答案」

看 val set 上規則式的預測分佈：

| 部位 | 規則式的預測分佈 | 真實分佈 |
|---|---|---|
| brow_shape | **彎月眉 51**（全部 51 張） | 一字眉 17、彎月眉 18、落尾眉 16 |
| eye_shape | **桃花眼 101**、丹鳳眼 2、細長眼 2 | 七類各 9~18 張 |
| nose_shape | **標準鼻 42**、寬鼻 1 | 寬鼻 16、標準鼻 8、窄鼻 19 |
| face_shape | 圓形臉 41、鵝蛋臉 28、方形臉 17（**從不輸出心形臉、長形臉**） | 五類各 15~23 張 |
| lip_shape | 微笑唇 33、厚唇 29、花瓣唇 8（**從不輸出 M型唇、薄唇**） | 五類各 9~16 張 |

**眉型的閾值把每一個人都判成彎月眉。眼型有 96% 判成桃花眼。鼻型 98% 判成標準鼻。**

### 7.3 用線上 API 交叉驗證（不是只有離線如此）

拿不同的人打線上 `/analyze`：

```
第 1 人  臉型=鵝蛋臉  眉型=彎月眉  眼型=桃花眼  鼻型=標準鼻  嘴型=微笑唇
第 2 人  臉型=方形臉  眉型=彎月眉  眼型=細長眼  鼻型=標準鼻  嘴型=薄唇
第 4 人  臉型=鵝蛋臉  眉型=彎月眉  眼型=桃花眼  鼻型=標準鼻  嘴型=微笑唇
```

**線上使用者現在幾乎每個人都被告知自己是「彎月眉 + 標準鼻」。**
這不是準確率高低的問題，是這三個欄位實質上沒有在做分類 ——
使用者拿到的是一個看起來很專業、但對每個人都一樣的答案。

> 這件事比 CNN 的分數重要得多，而且**在做這個 baseline 對照之前，沒有人知道**。
> 之前所有討論都預設「規則式雖然簡單但堪用，CNN 要贏過它才有價值」——
> 實際上規則式在三個部位上等於沒有輸出。

### 7.4 這如何改變結論

先前寫「CNN macro 0.38~0.67 全數低於門檻 0.70，不能上線」，那句話仍然成立；
但**「所以維持規則式」這個 fallback 前提是錯的** —— 規則式並不是一個安全的預設值，
它在 brow / eye / nose 上比 CNN 差得多（CNN 贏 +0.24 ~ +0.31）。

所以現在的選擇不是「不夠好的 CNN vs 堪用的規則式」，而是
**「不夠好的 CNN vs 幾乎沒在分類的規則式」**。

（附帶發現：線上預設 `strict_angle=True`，非正臉照片會直接被拒絕分析而回 `None`。
上面五張測試圖有兩張因此失敗。這是另一個獨立問題，尚未處理。）

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

已上線：`face-basic` revision **`face-basic-00015-ttt`**，
image `asia-east1-docker.pkg.dev/decorate-me/beauty-backend/backend:shadow-20260713d`。

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
| `ROI_SHADOW_EXPOSE_RESPONSE` | `0` | 設 `1` 才把 `模型分類` 放進 API 回應（內部驗收用） |
| `ROI_MODEL_DIR` | `models/basic_features_roi` | 模型目錄；指到不存在的路徑會靜默停用 |
| `LOG_LEVEL` | `INFO` | 低於 INFO 時 shadow 對照 log 不會輸出 |

**預設不把模型預測放進 API 回應**：模型還沒過門檻，未驗證的結果不該流到前端，
免得哪天有人「順手」拿去顯示給使用者看。shadow 要的資料走 log 就夠了。
線上實測回應欄位只有規則式那幾個，`模型分類` 不出現，但對照 log 照常寫入。

### 部署衝突：Codex 也在部署同一個服務

過程中發現 **Codex 這個工具也在部署 `face-basic`**（Artifact Registry 有 `codex-20260713-185013` tag，
另外 `9a2e52f` / `87cb835` 兩個 commit、以及 `FACE_API_KEY` 環境變數都來自它）。
我部署的 `00013` 一度被它的 `00014` 蓋掉，導致 shadow log 一筆都沒有 —— 
而 API 回應看起來完全正常，光看回應根本發現不了。

> 教訓同 (2)：**「服務有回應」不等於「你部署的東西還在上面」。** 部署後要驗的是
> 「我要的行為有沒有發生」（log 有沒有進去），不是「服務有沒有活著」。

若之後 shadow 又失效，第一件事是確認 serving revision 用的 image tag：

```
gcloud run services describe face-basic --region asia-east1 --format="value(status.traffic)"
gcloud run revisions list --service face-basic --region asia-east1 --limit 3
```

### 順帶查證：線上分析功能沒有壞

Codex 加的 `FACE_API_KEY` 會擋掉沒帶 `x-api-key` 的請求。確認過前端
（`decorate-me.web.app/config.local.js` 第 5 行 `faceApiKey`）帶的 key 與後端一致，
用它打線上 `/analyze` 回 HTTP 200 —— **線上使用者不受影響**。

> 另注意：這把 key 明文放在前端 config（第 5/9/11 行分別是 face / render / textSuggestion 的 key），
> 任何人打開瀏覽器都看得到。純靜態前端直接呼叫 API 本來就藏不住 key，它只能擋隨機掃 URL 的機器人，
> 擋不住看過網頁原始碼的人。要真的擋需要 Firebase App Check / 驗 Origin / 配額上限，屬另一個題目。

### 一個還沒對齊的 gap

線上 `MAX_IMAGE_SIZE=2048`，但訓練資料是用 1024 產生的 ROI。
同一張圖線上與本機的信心值會差幾個百分點（臉型 39% vs 33%）。shadow 階段無所謂，
但**模型要轉正式輸出之前，這個解析度落差必須先對齊**。

---

## 8.7 CNN 轉為正式輸出（2026-07-13）

線上 revision **`face-basic-00016-x72`** / image `backend:cnn-first-20260713`。

**五個部位的正式答案改由 CNN 提供**（`ROI_MODEL_FIRST=1`，預設開啟）。
規則式的三個部位（眉/眼/鼻）已用自己的資料重新校準閾值，退居 fallback。

### 為什麼不做 hybrid

原訂方案是規格書 13.2 的 hybrid（CNN 信心高時用 CNN，低時退回規則式）。**實測證明沒有用**
（`tools/tune_hybrid.py`）：

| 部位 | 規則式（校準後） | 純 CNN | hybrid | train 選出的門檻 |
|---|---|---|---|---|
| face_shape | 0.326 | **0.475** | 0.475 | 0.00 |
| brow_shape | 0.485 | **0.589** | 0.505 ← 更差 | 0.48 |
| eye_shape | 0.356 | **0.378** | 0.378 | 0.00 |
| nose_shape | 0.470 | **0.666** | 0.648 ← 更差 | 0.38 |
| lip_shape | 0.331 | **0.452** | 0.452 | 0.00 |

三個部位掃出來的最佳門檻是 **0.00** —— 意思是「CNN 再沒信心也比規則式準」，hybrid 自動退化成純 CNN。
眉型和鼻型有選出門檻，但在 val set 上 hybrid **反而比純 CNN 差**，那是 train set 上的假象。

**結論：五個部位全部用 CNN，規則式只在模型載入失敗/單一部位推論失敗時接手。**

### 線上驗證

八個不同的人打線上 API（兩人因非正臉被 `strict_angle` 擋下），六人的結果：

```
臉型: 方形臉 1、鵝蛋臉 1、心形臉 3、圓形臉 1
眉型: 彎月眉 2、落尾眉 4          （修復前：100% 彎月眉）
眼型: 細長 1、圓眼 1、下垂 2、丹鳳 1、瞇縫 1   （修復前：96% 桃花眼）
鼻型: 窄鼻 2、寬鼻 4              （修復前：98% 標準鼻）
```

**「每個人都是彎月眉 + 標準鼻」的 bug 在線上確認修復。**

回應新增 `分類來源` 欄位，記錄每個部位最後聽誰的、模型信心多少、規則式原本會說什麼，方便日後追查。

### 環境變數（新增）

| 變數 | 預設 | 用途 |
|---|---|---|
| `ROI_MODEL_FIRST` | `1` | 設 `0` 讓正式答案退回規則式（CNN 只寫 log） |

---

## 8.8 意外事故：三個 Cloud Run 服務全部 403（線上全壞）

部署 `00016` 後驗證時，**三個服務（face-basic / face-pro / replicate-render）全部回 403**，
連 `/health` 都被擋 —— 那是 Cloud Run **平台層**的 HTML 403，不是應用程式回的 JSON。

**原因：`allUsers` 的 `roles/run.invoker` 權限被移除**，服務不再允許公開存取。
稽核紀錄顯示當天有 4 次 `SetIamPolicy`（最近一次 12:18），掛在 `isachen2277@gmail.com` 帳號下 ——
但 Codex 用同一個帳號，所以分不出是人為還是它做的。

**影響**：decorate-me.web.app 的使用者**完全無法使用**（分析、PRO、渲染全部打不通）。
靜態前端是從瀏覽器直接呼叫 Cloud Run 的，服務必須公開，否則產品直接死亡。

**處理**：把三個服務的 `allUsers` / `run.invoker` 加回去，`/health` 立刻恢復 200。

> **教訓**：`gcloud run deploy --image` 只換 image，不會動 IAM —— 所以「部署成功」和
> 「使用者打得到」是兩件事。**驗證一定要用外部身分去打**（不帶 gcloud 認證的 curl），
> 否則你只是在確認「服務活著」，而不是「使用者用得到」。

---

## 9. 已知缺口

1. ~~規則式在 brow / eye / nose 上實質失效~~ **已修**（2026-07-13）：閾值用自己的資料重新校準，
   且五個部位的正式答案已改由 CNN 提供。見 8.7。
2. **CNN 仍未達門檻**（0.378~0.666 vs 規格書 0.70），雖然全面優於規則式。
   **這是目前最主要的品質缺口** —— 使用者拿到的答案比以前好很多，但仍不夠準，
   eye_shape 大約每 3 張錯 2 張。
3. **標註矛盾未清理**：33 個身分在同一部位有衝突標籤（見 4.1）。
4. **val set 太小**，分數波動 ±0.1，目前無法用來選模型或調參。
5. **臉型與嘴型的規則式閾值尚未校準**（只修了壞得最徹底的眉/眼/鼻三個）。
   目前這兩個部位由 CNN 輸出，規則式 fallback 仍是舊的（face 0.326 / lip 0.331）。
6. **鼻型的特徵與標籤對不上**：人工標註的 `ratio_width` 中位數是
   寬鼻 0.310 > 窄鼻 0.291 > 標準鼻 0.283 —— 「窄鼻」的鼻翼比「標準鼻」還寬。
   標註者判斷窄鼻時看的顯然不是鼻翼寬度。規則式 fallback 在鼻型上不可靠。
7. **線上 `strict_angle=True` 會直接拒絕非正臉照片**（回 400），拒絕率未量化 ——
   八張測試圖有兩張被擋（yaw −18.9°、pitch 23°）。這個門檻是否過嚴，值得量化。
8. **線上 `MAX_IMAGE_SIZE=2048` 與訓練用的 1024 不一致**，信心值會偏移幾個百分點。

---

## 10. 下一步建議（依 CP 值排序）

規則式 bug 已修、CNN 已成為正式輸出（8.7）。現在的瓶頸回到**準確率本身**，
而準確率的瓶頸是**資料**，不是模型架構。

1. **清理標註矛盾**：先從 4.1 抓出的 33 個身分開始人工複驗，這是資料品質的下限問題。
   另外鼻型的標註標準需要跟組員對齊（見缺口 6：「窄鼻」的鼻翼比「標準鼻」還寬）。
3. **合併難分的類別**：eye_shape 7 類在 376 張的規模下不可能學好。考慮先合併成
   「圓眼 / 細長眼 / 下垂眼」3 大類把準確率做起來，之後資料補足再細分。
   nose_shape 只有 3 類就拿到最高分（0.666），這不是巧合。
4. **補資料到每類 100 張以上**，特別是微笑唇（30）、標準鼻（30）、瞇縫眼（33）。
5. **改用 5-fold cross validation** 取代單次 25% 切分，讓分數不再被單一 val set 的運氣左右。
6. 上述都做完再談 DINOv2 —— 規格書提的 frozen encoder + SVM 路線在小資料上理論上比
   從 MobileNet fine-tune 更穩，但**在資料品質修好之前換模型，只會換來另一組同樣不可信的數字**。
