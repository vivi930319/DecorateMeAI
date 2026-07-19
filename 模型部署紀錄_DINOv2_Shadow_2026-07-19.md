# 模型部署紀錄：DINOv2 Shadow 上線

文件日期：2026-07-19
對應實驗紀錄：`模型三方公平比較_2026-07-19.md`
影響服務：`face-basic`（Cloud Run，asia-east1）

---

## 一、這次做了什麼

把 2026-07-19 五官分類實驗選定的模型部署到正式服務，但**依實驗結論的部署決策，DINOv2 只跑 shadow、不接管使用者看到的答案**。

| 部位 | 選定模型 | 本次部署後的角色 |
|---|---|---|
| 臉型 | DINOv2 ViT-S/14 + LinearSVC | Shadow（記錄，不輸出） |
| 眼型 | DINOv2 ViT-S/14 + LogisticRegression | Shadow（記錄，不輸出） |
| 鼻型 | DINOv2 ViT-S/14 + LinearSVC | Shadow（記錄，不輸出） |
| 眉型 | MobileNetV3-small | **正式答案**（更新為 100% 資料重訓版） |
| 唇型 | MobileNetV3-small | **正式答案**（更新為 100% 資料重訓版） |

### 為什麼 DINOv2 不直接接手

沿用實驗紀錄的判斷，理由有三個：

1. **五個部位都沒有達到 0.70 的品質門檻**（臉型 0.522、眼型 0.387、唇型 0.451、眉型 0.667；只有新二分類鼻型 0.863 達標）。
2. 實驗紀錄的「建議正式配置」對臉型明確標註**先做 Shadow**。
3. Shadow 階段要先在真實流量上驗證推論耗時、記憶體與實際一致率，這些是離線交叉驗證看不出來的。

要升為正式答案時，設定環境變數 `ROI_DINOV2_MODEL_FIRST=1` 即可，**不需要改程式或重建映像**。

---

## 二、服務端不安裝 torch 的作法

DINOv2 原本靠 `torch.hub` 載入，但把 torch 放進部署映像會讓映像膨脹約 800MB，而 `face-basic` 的 `min-instances` 是 0，冷啟動時間會直接反映在使用者等待上。

改為**離線把 backbone 匯出成 ONNX**，服務端只用既有的 `onnxruntime` 推論：

```
訓練／匯出（本機 .venv-train，有 torch）
    DINOv2 ViT-S/14  ──匯出──>  dinov2_vits14.onnx（88.4 MB）

服務端（Cloud Run，無 torch）
    ROI 224x224 ──onnxruntime──> 384 維 embedding ──joblib 分類器──> 標籤
```

相依套件 `onnxruntime`、`scikit-learn`、`joblib` 本來就在 `requirements.txt`，**沒有新增任何套件**。

### 匯出時的注意事項

DINOv2 的 `forward(x, masks=None)` 有第二個參數，直接匯出會讓 ONNX 產生 `masks` 這個必填輸入，推論時會報
`Required inputs (['masks']) are missing`。需用 wrapper 固定成單一輸入：

```python
class Backbone(torch.nn.Module):
    def __init__(self, m): super().__init__(); self.m = m
    def forward(self, images): return self.m(images)
```

匯出過程會出現 TracerWarning（ViT 的位置編碼插值被折成常數），因為服務端固定使用 224×224，不影響結果——但**必須用數值驗證確認**，不能只看有沒有報錯。

---

## 三、驗證結果

### 1. ONNX 與原始 torch 模型等價

| 測試 | 結果 |
|---|---|
| 隨機張量（3 組，batch=2） | 最大絕對誤差 **2.6e-05** |
| 真實影像 224 裁切、L2 正規化後 | 最大誤差 **7.6e-07**，**cosine = 1.00000000** |

### 2. 分類器索引與類別對應正確

以 1,870 筆快取 embedding 實測，確認預測索引不會越界：

| 部位 | 預測索引範圍 | 類別數 |
|---|---|---|
| 臉型 | 0～4 | 5 |
| 眼型 | 0～7 | 8 |
| 鼻型 | 0～1 | **2** |

### 3. 前處理與訓練時逐步對齊

服務端 `_dino_tensor()` 與 `tools/dinov2_cv_experiment.py` 使用相同流程：

```
roi_bbox（與正式 CNN 同一套）→ 邊界 REPLICATE 補齊 → resize 224
→ BGR2RGB → /255 → (x - MEAN) / STD → CHW
→ DINOv2 → L2 正規化 → 分類器
```

`MEAN = [0.485, 0.456, 0.406]`、`STD = [0.229, 0.224, 0.225]`。
**L2 正規化不可省略**：訓練時的 embedding 有做，推論不做會讓輸入分佈偏移。

---

## 四、鼻型類別檔的衝突處理（重要）

鼻型是唯一**兩套模型類別數不同**的部位：

| 模型 | 類別 |
|---|---|
| 現行 CNN（正式答案） | 寬鼻、標準鼻、**窄鼻**（3 類） |
| DINOv2（shadow） | 寬鼻、標準鼻（2 類，`grouped_yun` 新標準） |

若讓兩者共用 `nose_shape_classes.json`，CNN 輸出 3 個 logits 但只有 2 個類別名，`classes[best]` 會在預測到索引 2 時 **IndexError**，使鼻型欄位整個失效。

因此 DINOv2 使用獨立檔名 `{part}_dinov2_classes.json`，兩套互不影響。

> 這也代表：**線上正式答案的鼻型目前仍會輸出已退場的「窄鼻」**。要一併修正，需另外用 `grouped_yun` 資料訓練一個二分類的 MobileNetV3 ONNX（該標準下 5-fold 為 0.828，同樣超過 0.70），或等 DINOv2 升為正式答案。

---

## 五、部署內容

### 新增到 `models/basic_features_roi/`

```
dinov2_vits14.onnx                            88.4 MB   backbone
face_shape_dinov2_linear_svc.joblib           16 KB     分類器
eye_shape_dinov2_logistic_regression.joblib   13 KB     分類器
nose_shape_dinov2_linear_svc.joblib           3.8 KB    分類器
face_shape_dinov2_classes.json                          類別定義
eye_shape_dinov2_classes.json                           類別定義
nose_shape_dinov2_classes.json                          類別定義
```

### 更新（100% 資料重訓版，成為正式答案）

```
brow_shape.onnx / brow_shape_classes.json
lip_shape.onnx  / lip_shape_classes.json
```

模型目錄總計約 144 MB，由 `Dockerfile` 的 `COPY models/basic_features_roi/` 一併打包。

### 程式異動

| 檔案 | 內容 |
|---|---|
| `basic_roi_shadow.py` | 新增 `_load_dinov2()`、`_dino_tensor()`、`_dino_confidence()`、`predict_dinov2()`、`log_dinov2_comparison()` |
| `Face_analyzer_BASIC.py` | 在既有 shadow 流程後呼叫 DINOv2 預測與對照記錄 |

沿用模組原本的容錯原則：**每個進入點都不拋例外**，模型檔缺失、載入失敗、單一部位推論失敗一律略過，正式分析不受影響。

---

## 六、環境變數

| 變數 | 預設 | 說明 |
|---|---|---|
| `ROI_DINOV2_ENABLED` | `1` | 設 `0` 完全停用 DINOv2，其餘功能不受影響 |
| `ROI_DINOV2_MODEL_FIRST` | `0` | 設 `1` 讓 DINOv2 接手臉型／眼型／鼻型的正式答案 |
| `ROI_SHADOW_EXPOSE_RESPONSE` | `0` | 設 `1` 時 API 額外回傳 `模型分類_dinov2` 欄位供驗收 |
| `ROI_MODEL_FIRST` | `1` | 現行 CNN 是否作為正式答案（既有變數） |
| `ROI_SHADOW_ENABLED` | `1` | 整組 shadow 開關（既有變數） |

---

## 七、Shadow 觀察期要看什麼

從 Cloud Logging 撈這行：

```
DINOv2 shadow 對照：一致 N/M　差異 -> 臉型: CNN=... DINOv2=...
```

觀察三件事：

1. **推論耗時**：DINOv2 每張圖要跑 3 次 ViT-S/14 forward，明顯比 MobileNetV3（約 1 ms）慢。若造成分析逾時或冷啟動惡化，優先考慮停用或只保留鼻型。
2. **記憶體**：backbone 88 MB 常駐，需確認 Cloud Run 記憶體上限仍充裕。
3. **一致率**：與現行 CNN 差異過大的部位，要回頭看是模型判斷不同，還是 ROI 裁切或前處理有問題。

**判定升級的條件**：耗時與記憶體可接受，且差異樣本人工抽查後確認 DINOv2 較合理，才設 `ROI_DINOV2_MODEL_FIRST=1`。

---

## 八、尚未完成

- 鼻型正式答案仍是三分類 CNN，會輸出已退場的「窄鼻」（見第四節）。
- 臉型、眼型、唇型三個部位不論用哪個模型都未達 0.70，需補資料與重新確認標註定義。
- 實驗紀錄提到的「RGB ROI 與輪廓遮罩雙分支融合」尚未嘗試。
- 最終驗收仍需使用完全未參與訓練與調參的新照片。
