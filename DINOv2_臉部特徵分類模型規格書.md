# DINOv2 臉部特徵分類模型規格書

## 1. 目標

本規格書定義 Decorate Me 臉部分析模組的新一代分類模型方案：

```text
DINOv2 frozen image encoder
+ Logistic Regression / SVM / LightGBM classifier
```

目標是取代目前 BASIC 模組中較單一的 MediaPipe 幾何閾值分類，提升臉型、眉型、眼型、鼻型、嘴型與 PRO 側臉鼻型分類的穩定性與準確率。

本方案不移除 MediaPipe / InsightFace，而是重新分工：

```text
InsightFace：人臉偵測、頭部姿態、正臉/側臉品質檢查
MediaPipe FaceMesh：landmark、裁切區域定位、幾何特徵輔助
DINOv2：抽取五官/臉部圖片 embedding
Logistic Regression / SVM / LightGBM：最終分類器
```

## 2. 適用範圍

### 2.1 BASIC 模組

BASIC 使用正面自拍，輸出：

```text
臉型：鵝蛋臉 / 圓形臉 / 方形臉 / 長形臉 / 心形臉
眉型：一字眉 / 彎月眉 / 落尾眉
眼型：瞇縫眼 / 下垂眼 / 圓眼 / 丹鳳眼 / 細長眼 / 桃花眼 / 杏仁眼
鼻型：標準鼻 / 寬鼻 / 窄鼻
嘴型：厚唇 / 薄唇 / M型唇 / 微笑唇 / 花瓣唇
```

### 2.2 PRO 模組

PRO 使用正面照 + 側面照，新增：

```text
側臉鼻型：塌鼻 / 高鼻樑 / 小翹鼻 / 水滴鼻 / 直挺鼻 / 朝天鼻 / 駝峰鼻
```

目前資料集中 PRO 側臉鼻型只有：

```text
塌鼻：149 張
高鼻樑：50 張
其他類別：0 張
```

因此 PRO 側臉鼻型第一版只能訓練二分類：

```text
塌鼻 vs 高鼻樑
```

待其他類別補足資料後再升級為多分類。

## 3. 為什麼選 DINOv2

DINOv2 是自監督視覺特徵模型，適合在小資料集場景中作為 frozen encoder。對本專案有三個優勢：

```text
1. 不需要從零訓練 CNN，降低小資料過擬合風險。
2. 能抽取比 MediaPipe 幾何比例更豐富的局部視覺特徵。
3. 可搭配傳統分類器，訓練快、部署簡單、容易做 A/B test。
```

參考來源：

```text
DINOv2: Learning Robust Visual Features without Supervision
https://arxiv.org/abs/2304.07193
```

## 4. 模型架構

### 4.1 訓練架構

```text
原始圖片
  ↓
InsightFace 偵測人臉與姿態
  ↓
MediaPipe FaceMesh 取得 landmarks
  ↓
依任務裁切 ROI
  ↓
DINOv2 frozen encoder 抽 embedding
  ↓
訓練分類器
  ├─ Logistic Regression
  ├─ SVM
  └─ LightGBM
  ↓
選擇驗證集表現最佳模型
```

### 4.2 推論架構

```text
使用者上傳圖片
  ↓
既有 FaceAnalyzer 進行人臉偵測與 landmarks
  ↓
裁切臉部/眉毛/眼睛/鼻子/嘴唇 ROI
  ↓
DINOv2 抽 embedding
  ↓
分類器輸出 label + confidence
  ↓
與既有規則分類結果合併
```

## 5. 資料集規格

### 5.1 BASIC 資料路徑

```text
data/basic_full/grouped/<feature>/<label>/*.{jpg,jpeg,png,webp}
```

目前可用特徵：

```text
face_shape
brow_shape
eye_shape
nose_shape
lip_shape
```

目前資料量：

```text
brow_shape：194 張
eye_shape：376 張
face_shape：305 張
lip_shape：266 張
nose_shape：156 張
```

### 5.2 PRO 資料路徑

```text
data/pro_full/grouped/nose_shape_side/<label>/*.{jpg,jpeg,png,webp}
```

第一版只啟用有資料的類別：

```text
塌鼻
高鼻樑
```

### 5.3 標籤要求

不可直接使用舊規則分類結果當正式標籤。正式訓練資料需符合：

```text
1. 每張圖片至少人工檢查一次。
2. 模糊、遮擋、非正臉、多人臉照片需排除。
3. 類別定義需固定，不能同一張圖片在不同 feature 中出現衝突標籤。
4. 每類建議至少 100 張；正式版建議每類 300 張以上。
```

## 6. ROI 裁切規格

### 6.1 臉型 face_shape

使用整張臉部 crop：

```text
來源：MediaPipe face oval 或 InsightFace bbox
範圍：額頭到下巴、左右臉頰完整包含
padding：bbox 寬高各 12%-18%
```

### 6.2 眉型 brow_shape

使用左右眉合併 crop：

```text
來源：MediaPipe eyebrow landmarks
範圍：左右眉毛 + 眉骨周圍皮膚
padding：高度 40%，寬度 20%
```

### 6.3 眼型 eye_shape

使用左右眼合併 crop：

```text
來源：MediaPipe eye landmarks
範圍：左右眼、上眼皮、下眼皮、眼尾
padding：高度 45%，寬度 20%
```

### 6.4 鼻型 nose_shape

使用正面鼻部 crop：

```text
來源：MediaPipe nose landmarks
範圍：鼻根、鼻樑、鼻尖、鼻翼
padding：高度 30%，寬度 35%
```

### 6.5 嘴型 lip_shape

使用嘴唇 crop：

```text
來源：MediaPipe lip landmarks
範圍：上下唇、嘴角
padding：高度 50%，寬度 25%
```

### 6.6 側臉鼻型 nose_shape_side

使用側臉鼻部輪廓 crop：

```text
來源：側面照人臉 bbox 或人工整理圖片
範圍：鼻根、鼻樑、鼻尖、鼻下緣、上唇前緣
要求：yaw 建議 70°-90°
```

## 7. Feature 設計

### 7.1 DINOv2 embedding

每個 ROI 經 DINOv2 輸出一組 embedding：

```text
模型：dinov2_vits14 或 dinov2_vitb14
輸入尺寸：224x224
輸出：CLS token embedding
正規化：L2 normalization
```

第一版建議使用：

```text
dinov2_vits14
```

原因是速度較快，適合後端推論。

### 7.2 輔助幾何特徵

DINOv2 embedding 可與現有 MediaPipe 幾何特徵串接：

```text
final_feature = concat(dinov2_embedding, landmark_ratio_features, pose_features)
```

BASIC 第一版可先只用 DINOv2 embedding。若準確率不足，再加入：

```text
yaw / pitch / roll
臉寬 / 臉高
眼寬 / 眼高
鼻寬 / 臉寬
唇高 / 唇寬
左右對稱差
```

## 8. 分類器候選

每個 feature 單獨訓練一個分類器：

```text
face_shape_classifier
brow_shape_classifier
eye_shape_classifier
nose_shape_classifier
lip_shape_classifier
nose_shape_side_classifier
```

### 8.1 Logistic Regression

用途：

```text
baseline
小資料
快速訓練
可輸出機率
```

建議參數：

```text
class_weight="balanced"
max_iter=3000
C in [0.1, 1.0, 3.0, 10.0]
```

### 8.2 SVM

用途：

```text
小資料高維 embedding
分類邊界較複雜時
```

建議參數：

```text
kernel="linear" 或 "rbf"
class_weight="balanced"
probability=True
C in [0.1, 1.0, 3.0, 10.0]
gamma in ["scale", "auto"]
```

### 8.3 LightGBM

用途：

```text
DINOv2 embedding + landmark features 混合
非線性分類
中小資料
```

建議參數：

```text
objective="multiclass"
class_weight="balanced"
num_leaves=15 或 31
learning_rate=0.03-0.08
n_estimators=100-500
feature_fraction=0.8
bagging_fraction=0.8
```

若部署環境不想新增 LightGBM dependency，可先使用 scikit-learn 的 Logistic Regression / SVM。

## 9. 訓練流程

### 9.1 資料切分

使用 stratified split：

```text
train：70%
validation：15%
test：15%
```

資料量太少時：

```text
StratifiedKFold 5-fold cross validation
```

注意同一張原始圖片不可同時出現在 train 與 test。

### 9.2 訓練步驟

```text
1. 掃描 data/basic_full/grouped 與 data/pro_full/grouped。
2. 對每張圖片偵測人臉與 landmarks。
3. 按 feature 裁切 ROI。
4. 將 ROI resize 到 224x224。
5. 使用 DINOv2 抽 embedding。
6. 儲存 embedding cache。
7. 分別訓練 Logistic Regression / SVM / LightGBM。
8. 用 validation macro F1 選最佳模型。
9. 在 test set 產生最終報告。
10. 輸出模型與 metrics。
```

### 9.3 輸出檔案

```text
models/dinov2_face_features/
  embeddings/
    face_shape_train.npz
    brow_shape_train.npz
    eye_shape_train.npz
    nose_shape_train.npz
    lip_shape_train.npz
    nose_shape_side_train.npz

  classifiers/
    face_shape_logreg.joblib
    face_shape_svm.joblib
    face_shape_lightgbm.joblib
    face_shape_best.joblib
    ...

  metrics/
    face_shape_metrics.json
    brow_shape_metrics.json
    eye_shape_metrics.json
    nose_shape_metrics.json
    lip_shape_metrics.json
    nose_shape_side_metrics.json

  label_maps/
    face_shape_labels.json
    brow_shape_labels.json
    eye_shape_labels.json
    nose_shape_labels.json
    lip_shape_labels.json
    nose_shape_side_labels.json
```

## 10. 評估指標

每個 feature 都需輸出：

```text
accuracy
macro_precision
macro_recall
macro_f1
weighted_f1
confusion_matrix
per_class_precision
per_class_recall
per_class_f1
```

正式採用門檻：

```text
BASIC face_shape：macro F1 >= 0.70
BASIC brow_shape：macro F1 >= 0.75
BASIC eye_shape：macro F1 >= 0.70
BASIC nose_shape：macro F1 >= 0.70
BASIC lip_shape：macro F1 >= 0.70
PRO nose_shape_side：macro F1 >= 0.75
```

若低於門檻：

```text
保留舊規則分類作為正式輸出
DINOv2 模型只作為 shadow prediction
```

## 11. API 輸出規格

### 11.1 BASIC 新增欄位

既有中文輸出保留：

```json
{
  "分析版本": "BASIC",
  "臉型": "鵝蛋臉",
  "眉型": "彎月眉",
  "眼型": "杏仁眼",
  "鼻型": "標準鼻",
  "嘴型": "花瓣唇"
}
```

新增模型資訊：

```json
{
  "模型分類": {
    "provider": "dinov2",
    "encoder": "dinov2_vits14",
    "classifier": "svm",
    "臉型": {
      "label": "鵝蛋臉",
      "confidence": 0.82,
      "source": "dinov2_svm"
    },
    "眉型": {
      "label": "彎月眉",
      "confidence": 0.76,
      "source": "dinov2_svm"
    }
  }
}
```

### 11.2 合併策略

第一階段採用保守合併：

```text
若 DINOv2 confidence >= 0.70：
    使用 DINOv2 label
否則：
    使用舊規則 label
```

輸出中保留兩者：

```json
{
  "臉型": "鵝蛋臉",
  "分類來源": {
    "臉型": {
      "final": "dinov2",
      "ruleLabel": "圓形臉",
      "modelLabel": "鵝蛋臉",
      "modelConfidence": 0.82
    }
  }
}
```

## 12. 部署規格

### 12.1 後端載入

服務啟動時載入：

```text
DINOv2 encoder
各 feature classifier
label maps
```

建議 lazy load：

```text
第一次分析時才載入 DINOv2
避免 Cloud Run cold start 過久
```

### 12.2 推論效能

CPU 模式預估：

```text
每張圖 5 個 ROI
DINOv2 ViT-S/14 推論可能成為主要耗時
```

優化方向：

```text
1. ROI batch inference
2. 啟用 GPU 環境時使用 CUDA
3. 只在 PRO 或高階方案啟用 DINOv2
4. BASIC 可先用 LightGBM landmark model，DINOv2 作為 PRO
```

### 12.3 依賴

新增套件：

```text
torch
torchvision
scikit-learn
joblib
```

可選：

```text
lightgbm
timm
```

DINOv2 載入方式可選：

```text
torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
```

或使用本地權重快取，避免正式環境每次連網下載。

## 13. 版本規劃

### 13.1 v0 Shadow Mode

```text
訓練 DINOv2 分類器
API 仍輸出舊規則結果
額外記錄 model prediction
人工比較差異
```

### 13.2 v1 Hybrid Mode

```text
confidence >= 0.70 時使用 DINOv2
低信心時 fallback 到舊規則
```

### 13.3 v2 Model First

```text
DINOv2 作為主分類器
MediaPipe 規則作為 fallback
錯誤案例回流標註資料集
```

### 13.4 v3 PRO Fine-Tune

```text
資料量補足後
改測 EfficientNetV2 / ConvNeXt-Tiny fine-tune
或保留 DINOv2 + classifier 作為 ensemble
```

## 14. 風險與限制

```text
1. 現有資料量偏少，驗證分數可能不穩。
2. 若標籤由舊規則自動產生，模型只會學會模仿舊規則。
3. PRO 側臉鼻型類別嚴重不平衡，目前不能做完整多分類。
4. DINOv2 推論成本高於純 MediaPipe 幾何規則。
5. 五官 crop 品質會直接影響分類準確率。
```

## 15. 建議執行順序

```text
1. 先建立 ROI crop + DINOv2 embedding cache 腳本。
2. 對 BASIC 五個 feature 訓練 Logistic Regression / SVM baseline。
3. 對同一批 embedding 訓練 LightGBM。
4. 比較 macro F1，選 best classifier。
5. 建立 shadow mode API，不直接覆蓋舊結果。
6. 補人工標註資料，特別是鼻型與嘴型少數類。
7. PRO 側臉鼻型先做二分類，等資料補齊再升級多分類。
```

## 16. 最終建議

本專案目前最適合採用：

```text
BASIC：
DINOv2 ViT-S/14 frozen encoder
+ SVM / Logistic Regression
+ 舊規則 fallback

PRO：
DINOv2 ViT-S/14 frozen encoder
+ LightGBM / SVM
+ 側臉鼻型二分類起步
```

若未來每類資料達 300-500 張以上，再評估：

```text
EfficientNetV2-S fine-tune
ConvNeXt-Tiny fine-tune
DINOv2 + classifier ensemble
```
