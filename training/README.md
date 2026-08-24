# `training/` — 一個模型一個檔案

這個目錄是**給人讀的**：每個模型一支獨立的 `.py`，可以單獨打開、單獨跑，
檔案開頭寫著這個模型現在的分數、錯在哪、可以動手試什麼。

正式在維護的訓練腳本仍然是根目錄那兩支（`train_basic_cnn_roi.py`、
`train_pro_nose_side.py`）——它們負責對照實驗、ONNX 匯出、holdout 等線上流程要的東西。
**這裡的檔案不匯出模型、不覆蓋 `models/basic_features_roi/`**，跑壞了不會影響線上服務。

| 檔案 | 模型 | 輸入 | 類別 |
| --- | --- | --- | --- |
| `basic_face_shape.py` | MobileNetV3-Small | 臉部外框 ROI 128² | 圓形／心形／方形／長形／鵝蛋 |
| `basic_brow_shape.py` | MobileNetV3-Small | 眉毛 ROI 96² | 一字／彎月／落尾 |
| `basic_eye_shape.py` | MobileNetV3-Small | 眼周 ROI 96² | 下垂／圓／桃杏／鳳 |
| `basic_nose_shape.py` | MobileNetV3-Small | 鼻部 ROI 96² | 寬鼻／標準鼻 |
| `basic_lip_shape.py` | MobileNetV3-Small | 嘴唇 ROI 96² | 厚／微笑／花瓣／薄 |
| `pro_nose_side.py` | ConvNeXt-Tiny | **整張側臉圖** 224² | 塌／直挺／翹／蒜頭／駝峰 |
| `_dataset.py` | — | 共用的資料層 | — |

## 怎麼跑

```powershell
# 只要做一次：把每張圖的五個部位 ROI 裁好存快取（這一步會呼叫 MediaPipe，比較慢）
.venv\Scripts\python.exe prepare_roi_cache.py

# 然後就可以單獨跑任何一支
.venv\Scripts\python.exe training\basic_brow_shape.py
.venv\Scripts\python.exe training\basic_brow_shape.py --epochs 40 --focal --class-weight
```

## Face BASIC／PRO 是「被呼叫」的，不是被複製的

- **BASIC 五支**不自己裁圖。ROI 由 `prepare_roi_cache.py` 事先裁好，而那支用的是
  `face_roi.ROI_SPECS` / `crop_roi`——**線上服務餵給模型的同一種圖**。
  訓練與推論吃同一份規格，模型上線才不會無聲掉分。
- **PRO 那支**不裁圖，因為線上也不裁：`pro_nose_side_model.predict()` 直接把整張
  側臉 frame 縮到 224 丟進 ONNX。理由見該檔案開頭（側臉 FaceMesh 只認得 73.5%，
  而且失敗率依類別偏斜，裁切會扭曲類別分布）。

## `_dataset.py` 為什麼要共用

只有三件事放在共用檔裡：讀快取、按人切分、算指標。不是為了省行數，
是**這三件事錯了會靜默地毀掉結論**，而且每一支都必須錯得一模一樣才公平：

- 讀快取不檢查筆數 → 拿 A 圖的像素配 B 圖的標籤（2026-07-29 踩過，差點整份結果全錯）
- 切分不按人分組 → 同一個人同時在 train 與 val，分數虛高，換人就崩
- `identity = -1`（叢集失敗）不能當成一個普通的 group → 否則所有「不知道是誰」的樣本
  會變成同一個超大的人，整包掉進某一折。實測鼻型出現過 fold 1 的 val 有 250 張、
  其餘四折各 17～26 張。現在的政策跟正式腳本一致：**-1 一律留在 train，永不進 val**。
- 只看 accuracy → 類別不平衡時它會騙人。所以 `report()` 一律印出
  per-class precision／recall／F1、macro／weighted 平均、balanced accuracy、Cohen's κ
  與混淆矩陣。

## 想看目前的整體成績

```powershell
.venv\Scripts\python.exe tools\report_cv_metrics.py
```

它讀既有的 `models/basic_features_roi/*_cv_metrics.json`，不重跑訓練。
**注意**：那些 metrics 檔的產生時間可能早於最近一次 ROI 快取重建，
支撐數對不上就代表資料換過了，該重跑而不是直接引用。
