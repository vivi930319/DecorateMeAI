# 模型紀錄書 — BASIC 五官分類

用途：每嘗試一個分類方案，就填一份。**所有方案必須在同一個 val set 上評估**，否則數字不能互相比較。

> **公平比較的鐵則**：val set 一律用 `train_basic_cnn_roi.py` 的
> `split_by_identity(seed=42, val_ratio=0.25)` 產生 —— 按人切分，同一個人的照片不會同時出現在
> train 和 val。任何用「隨機切分」得到的分數都會虛高（實測虛高最多 +0.11），不可拿來比較。
>
> 現成工具：`eval_rule_baseline.py` 已經示範怎麼在同一個 val set 上評估任意分類器，
> 新方案照抄它的切分邏輯即可（直接 import，不要自己重寫一份）。

---

## 總表（一眼看完，每次新增方案就補一行）

單位：macro accuracy（各類 recall 的平均；用 macro 而非 accuracy，少數類才不會被多數類蓋掉）

| 部位 | 隨機猜 | ① 規則式（原始，壞掉） | ①b 規則式（校準後） | ② ROI CNN | ③ hybrid | 規格書門檻 |
|---|---|---|---|---|---|---|
| face_shape | 0.200 | 0.326 | 0.326 ※ | **0.475** ✅ | 0.475 | 0.70 |
| brow_shape | 0.333 | 0.333 ⚠️ | 0.485 | **0.589** ✅ | 0.505 | 0.75 |
| eye_shape | 0.143 | 0.143 ⚠️ | 0.356 | **0.378** ✅ | 0.378 | 0.70 |
| nose_shape | 0.333 | 0.354 | 0.470 | **0.666** ✅ | 0.648 | 0.70 |
| lip_shape | 0.200 | 0.331 | 0.331 ※ | **0.452** ✅ | 0.452 | 0.70 |

- ⚠️ = 分數等於隨機亂猜（規則式退化成常數輸出，見 `規則式閾值Bug_完整診斷記錄_新手版.md`）
- ※ = 臉型與嘴型的閾值尚未校準（只修了眉/眼/鼻三個壞得最徹底的）
- ✅ = **線上採用中**（2026-07-13 起，五個部位皆由 CNN 提供正式答案）

**結論：CNN 全面最佳，hybrid 沒有幫助（甚至在 brow/nose 上更差）。**
**但沒有任何方案達標** —— CNN 仍低於規格書門檻 0.70，只是遠優於原本壞掉的規則式。

### CV 修正（2026-07-14）：② ROI CNN 的可信分數

上表的數字全部來自**同一次**單次切分（為了跨方案可比，保留不動）。
第二輪改用 5-fold CV 重新量測 CNN，這才是它的真實水準：

| 部位 | 上表（單次切分） | **5-fold CV（可信）** | 單次切分的偏差 |
|---|---|---|---|
| nose_shape | 0.666 | **0.675 ± 0.065** | 準 |
| face_shape | 0.475 | **0.532 ± 0.067** | 低估 |
| brow_shape | 0.589 | **0.511 ± 0.046** | **高估 +0.08 —— 運氣好的考卷** |
| lip_shape | 0.452 | **0.444 ± 0.067** | 準 |
| eye_shape | 0.378 | **0.368 ± 0.055** | 準 |

**重要修正**：眉型 CNN（0.511）對校準後規則式（0.485）的優勢從 +0.10 縮到約 +0.03，
在 fold std ±0.046 之下**不顯著**。其餘部位 CNN 的優勢仍然成立。

另：剔除 33 個標註矛盾身分的實驗**無效**（eye 砍 21% 資料分數不動、face 反而變差），
詳見 `CNN訓練歷程_BASIC五官分類.md` 11.4/11.5。今後所有方案比較一律用 5-fold CV
（`train_basic_cnn_roi.py --cv 5`）。

### 第三輪快報（2026-07-14）：③ DINOv2 在眼型上大勝

同 fold 對決：**eye 0.471 vs CNN 0.368（+0.103，5/5 fold 全勝）**、nose 0.713（名目過線）、
face 反而 CNN 好 0.05。結論是**按部位混搭**而非全面換架構 —— 詳見 ③ 的完整紀錄。

---

# ① 規則式（MediaPipe 幾何閾值）

| 項目 | 內容 |
|---|---|
| 狀態 | **線上正式輸出中**（使用者看到的就是這個） |
| 程式 | `Face_analyzer_BASIC.py` 的 `get_face_shape()` / `get_eyebrow_shape()` / `get_eye_shape()` / `get_nose_shape()` / `get_lip_shape()` |
| 原理 | MediaPipe FaceMesh 468 landmark，算幾何比值後套閾值 |
| 訓練資料 | 無（人工訂閾值，不需訓練） |
| 評估腳本 | `eval_rule_baseline.py` |
| 評估日期 | 2026-07-13 |

### 成績（按人切分 val set）

| 部位 | macro accuracy | 隨機猜 | 結論 |
|---|---|---|---|
| face_shape | 0.326 | 0.200 | 略優於隨機 |
| brow_shape | 0.333 | 0.333 | **等同隨機** |
| eye_shape | 0.143 | 0.143 | **等同隨機** |
| nose_shape | 0.354 | 0.333 | **幾乎等同隨機** |
| lip_shape | 0.331 | 0.200 | 略優於隨機 |

### 致命問題：退化成幾乎只輸出一個答案

| 部位 | 在 val set 上的預測分佈 |
|---|---|
| brow_shape | **彎月眉 51/51（100%）** |
| eye_shape | **桃花眼 101/105（96%）** |
| nose_shape | **標準鼻 42/43（98%）** |
| face_shape | 只輸出 3 類，從不輸出「心形臉」「長形臉」 |
| lip_shape | 只輸出 3 類，從不輸出「M型唇」「薄唇」 |

線上 API 交叉驗證同樣結果：**每個使用者都被判成「彎月眉 + 標準鼻」**。

### 待辦

- [ ] 查眉型為什麼永遠輸出彎月眉（多半是某個比值的門檻讓所有人落在同一區間）
- [ ] 眼型、鼻型同上
- [ ] 修好後重跑 `eval_rule_baseline.py`，把新分數填回總表

---

# ② ROI CNN（MobileNetV3-small）

| 項目 | 內容 |
|---|---|
| 狀態 | **Shadow mode 上線**（只寫 log，不影響使用者看到的結果） |
| 線上版本 | revision `face-basic-00015-ttt` / image `backend:shadow-20260713d` |
| 架構 | MobileNetV3-small（ImageNet 預訓練）＋ 每個部位一顆獨立分類器 |
| 輸入 | 部位 ROI 裁切圖：臉型 128×128、其餘 96×96（定義在 `face_roi.ROI_SPECS`） |
| 訓練腳本 | `prepare_roi_cache.py` → `train_basic_cnn_roi.py` |
| 推論程式 | `basic_roi_shadow.py`（ONNX，onnxruntime CPU，單執行緒） |
| 產出 | `models/basic_features_roi/<part>.onnx`（各 6MB） |
| 訓練日期 | 2026-07-13 |

### 訓練設定

```
optimizer      AdamW, lr=3e-4, weight_decay=1e-4
scheduler      CosineAnnealingLR
loss           CrossEntropy, label_smoothing=0.05
epochs         25（40 epochs 沒有更好，見下）
batch size     32
類別不平衡      WeightedRandomSampler
資料增強        亮度/對比抖動、小幅平移
              ※ 刻意不做水平翻轉：落尾眉翻轉後會變成上揚眉，等於餵錯標籤
切分           按 identity 切分（InsightFace embedding 聚類），val 25%, seed 42
```

### 成績（按人切分 val set）

| 部位 | macro accuracy | vs 規則式 | 門檻 | 達標？ |
|---|---|---|---|---|
| face_shape | 0.475 | +0.149 | 0.70 | ✗ |
| brow_shape | 0.589 | +0.256 | 0.75 | ✗ |
| eye_shape | 0.378 | +0.235 | 0.70 | ✗ |
| nose_shape | 0.666 | +0.311 | 0.70 | ✗（最接近） |
| lip_shape | 0.452 | +0.122 | 0.70 | ✗ |

### 效能

| 項目 | 數值 |
|---|---|
| 五個部位推論總計 | 14 ms（單執行緒；預設多執行緒反而要 60ms） |
| 在整條分析流程的佔比 | ~70ms / 383ms（18%） |
| 線上端到端（含網路） | 0.53 ~ 0.70 秒 |

### 已知限制

- 每類只有 30~70 張，遠低於規格書建議（100 張起、正式版 300 張）
- 33 個身分有標註矛盾（同一個人同一部位被標成不同類別）
- val set 只有 43~105 張，**分數雜訊 ±0.1** —— 不足以用來選模型或調參
- 訓練資料用 `MAX_IMAGE_SIZE=1024`，線上是 2048，解析度未對齊

### 待辦

- [ ] 對齊線上/訓練的 `MAX_IMAGE_SIZE`
- [ ] 從 Cloud Logging 撈 shadow 對照 log，統計真實流量上的規則式 vs 模型一致率
- [ ] 決定是否讓 brow / eye / nose 三個部位改由 CNN 輸出

---

# ③ DINOv2 frozen encoder + 線性分類器

| 項目 | 內容 |
|---|---|
| 狀態 | **實驗完成，未上線**（上線需部署決策，見下） |
| 架構 | DINOv2 ViT-S/14（frozen，不 fine-tune）＋ LogisticRegression / LinearSVC |
| 輸入 | 部位 ROI 從原圖重裁成 224×224（同一套 `roi_bbox`） |
| 訓練腳本 | `tools/dinov2_cv_experiment.py` |
| 產出 | `data/roi_cache/dinov2_embeddings.npz`、`models/basic_features_roi/dinov2_cv_results.json` |
| 訓練日期 | 2026-07-14 |

### 為什麼要試這個方案（動機）

規格書第 16 節的原始建議路線。要解決的具體問題：**eye_shape 在 376 張 / 7 類下
fine-tune CNN 過擬合**（CV 僅 0.368，全部位最低）。自監督預訓練的凍結特徵不需要
從小資料學表徵，理論上更穩。做的時機點：5-fold CV 量尺已就位（第二輪），
可以用**與 CNN 完全相同的 fold** 逐 fold 配對比較，雜訊被扣掉。

### 訓練設定

```
encoder     DINOv2 ViT-S/14（torch.hub, frozen）→ CLS embedding 384 維，L2 正規化
分類器       LogisticRegression(C=1, balanced) / LinearSVC(C=1, balanced)
評估        與 CNN 基準完全相同的按人 5-fold（split_kfold_by_identity, seed=42）
```

### 成績（5-fold CV，與 ② 的 CV 修正數字同尺度可比）

| 部位 | DINOv2+SVM | vs ROI CNN（CV） | 逐 fold 勝負 | 門檻 | 達標？ |
|---|---|---|---|---|---|
| eye_shape | **0.471 ± 0.053** | **+0.103** | **5/5 全勝** | 0.70 | ✗（但大幅改善） |
| nose_shape | **0.713 ± 0.098** | +0.038 | 4/5 | 0.70 | 名目過線，波動下不能宣稱 |
| brow_shape | 0.535 ± 0.084 | +0.024 | — | 0.75 | ✗（誤差內） |
| lip_shape | 0.444 ± 0.038 | ±0.000 | — | 0.70 | ✗（平手） |
| face_shape | 0.485 ± 0.037 | **−0.047** | — | 0.70 | ✗（CNN 較好） |

### 效能

| 項目 | 數值 |
|---|---|
| 推論耗時 | ViT-S/14 CPU 單張 ROI 約 0.3~0.5s（可轉 ONNX 壓到 ~0.1-0.3s） |
| 模型大小 | 權重 84MB（vs MobileNetV3 的 6MB） |

### 結論

- [x] **eye_shape：優於 ROI CNN，值得取代**（+0.103、5/5 fold 全勝，非雜訊）
- [x] nose_shape：方向偏正（+0.038、4/5），可跟著 eye 一起換或再觀察
- [x] brow / lip：差異在雜訊內，維持 CNN（不值得為此背 84MB 依賴）
- [x] **face_shape：CNN 較好，維持 CNN**（臉型看整體輪廓，fine-tune 的任務特化特徵對口）

**正確的下一步不是全面換架構，是按部位混搭**：eye（＋可能 nose）走 DINOv2+SVM，
其餘維持 MobileNetV3。上線需先解決：torch/ONNX 依賴進映像、雙推論路徑的
fallback 邏輯、shadow log 對照真實流量。

---

## 附錄：填寫這份紀錄書時的三個提醒

1. **一定要用同一個 val set。** 隨機切分會讓分數虛高最多 +0.11（因為同一個藝人的多張照片會
   同時落在 train 和 val，模型認人就能猜對）。用 `split_by_identity`。

2. **±0.1 以內的差距不算差距。** val set 只有 43~105 張，一張分類結果就值 1~2 個百分點。
   實測把 epochs 從 25 加到 40，五個部位三個變差兩個變好，方向完全隨機 —— 那不是模型變好變壞，
   是雜訊。要真正分辨方案優劣，得先把 val set 做大（或改用 5-fold cross validation）。

3. **記錄「為什麼失敗」比記錄分數更有價值。** 分數會隨資料更新而過期，但
   「眉型永遠輸出彎月眉」「InsightFace 對佔滿畫面的大頭照會漏偵測四成」
   這類發現不會過期，而且下一個人不知道就會再踩一次。

詳細的踩坑過程見 `CNN訓練歷程_BASIC五官分類.md`。
