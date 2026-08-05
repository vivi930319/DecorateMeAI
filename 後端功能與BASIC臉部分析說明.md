# 後端功能與 BASIC 臉部分析說明

## 一、系統用途

後端負責接收使用者照片，確認照片中是否有人臉、判斷拍攝角度，再依臉部特徵點計算臉型、眉型、眼型、鼻型、嘴型、膚色與左右對稱性。分析結果會整理成統一的 `analysisPackage`，供前端顯示、妝容建議、圖片生成、商品推薦及資料庫保存使用。

目前後端分為三個服務：

| 服務 | 預設 Port | 用途 |
| --- | ---: | --- |
| Face Analyzer BASIC | 8001 | 單張正面照分析、姿勢判斷、BASIC 工作狀態管理 |
| Face Analyzer PRO | 8002 | 正面照搭配側面照，補充多角度膚色資訊 |
| Ollama Suggestion | 8010 | 根據臉部分析結果產生妝容文字建議 |

主要程式：

- `Face_analyzer_BASIC.py`：BASIC API 與完整臉部分析程式。
- `Face_analyzer_PRO.py`：PRO 多角度分析與結果合併。
- `Ollama_suggestion.py`：妝容文字建議。
- `analysis_package.py`：前後端共用資料包封裝。
- `dev_server_utils.py`：本機啟動、Port 檢查及 CORS 設定。
- `cloud_start.py`：雲端依環境變數選擇要啟動的服務。

## 二、後端功能

### 1. 圖片接收與檢查

前端使用 `multipart/form-data` 上傳圖片。後端會先確認檔案不是空檔，再使用 OpenCV 解碼。無法解碼時回傳「圖片讀取失敗」，圖片中沒有臉時回傳「沒偵測到人臉」。手機照片如果長邊超過 `MAX_IMAGE_SIZE`，會等比例縮小後再分析，避免原圖過大拖慢模型。

### 2. 人臉偵測與正面照驗證

InsightFace 負責找出照片中的人臉與臉部角度。照片中有多張臉時，選擇偵測信心最高的一張。BASIC 正面照限制為：

- `yaw` 左右偏轉不得超過 18 度。
- `pitch` 上下抬頭或低頭不得超過 15 度。

超出限制時不繼續分類，直接要求重新上傳正面照片，避免角度造成比例失真。

### 3. 臉部特徵點

MediaPipe FaceMesh 取得 468 個臉部特徵點。後續的臉寬、臉高、眼睛開合、眉毛弧度、鼻翼寬度及唇形比例，都由特徵點座標計算。分析前會以雙眼位置校正臉部旋轉，降低照片稍微歪斜造成的誤差。

### 4. 眼皮模型

系統會嘗試載入 `eyelid_model.onnx`。模型不存在時不會讓整個 API 無法啟動，而是保留其餘 BASIC 分析功能。目前正式輸出的眼型仍以 FaceMesh 幾何比例為主。

### 5. 同步分析

| Method | 路徑 | 輸入 | 輸出 |
| --- | --- | --- | --- |
| POST | `/analyze` | `file` 正面照 | BASIC 分析 JSON |
| POST | `/v1/face/analyze/basic` | `file` 正面照 | BASIC 分析 JSON |
| POST | `/v1/face/analyze/pro` | `front` 必填；`left45`、`right45`、`side` 選填 | PRO 分析 JSON |
| POST | `/analyze-pro` | 同上 | PRO 分析 JSON |

同步 API 適合單人測試與等待時間較短的畫面。請求會持續到分析完成後才回傳。

### 6. 拍攝角度判斷

`POST /v1/face/pose` 接收欄位 `file`，回傳：

```json
{
  "yaw": -2.31,
  "pitch": 1.42,
  "roll": 0.56,
  "captureRole": "front",
  "side": "left",
  "confidence": 0.9981
}
```

`captureRole` 分類方式：

- `front`：`|yaw| <= 8` 且 `|pitch| <= 12`。
- `side`：`|yaw| >= 10`。
- `angle45`：`|yaw| >= 6`，但未達 side。
- `turning`：介於上述條件之外。

此 API 可供拍照頁提示使用者向左、向右或回到正面。

### 7. 非同步工作

| Method | 路徑 | 用途 |
| --- | --- | --- |
| POST | `/v1/face/jobs/basic` | 建立 BASIC 分析工作 |
| POST | `/v1/face/jobs/pro` | 建立 PRO 分析工作 |
| GET | `/v1/face/jobs/{jobId}` | 查詢進度 |
| GET | `/v1/face/jobs/{jobId}/result` | 工作完成後取得結果 |

工作狀態包含 `queued`、`processing`、`completed`、`failed`。BASIC 的階段為 `upload → face_analysis → done`；PRO 為 `upload → front_analysis → side_analysis → done`。

目前工作資料保存在記憶體：

- 預設逾時 180 秒。
- 完成或失敗後保留 3600 秒。
- 最多保留 200 筆。
- 服務重新啟動後，尚未保存的工作狀態會消失。

### 8. 健康檢查

三個服務都有 `GET /health`。Face API 會回傳服務名稱、各工作狀態數量、逾時秒數、保留秒數與最大工作筆數。Suggestion API 另外檢查 Ollama 是否能連線，並顯示目前模型；`fallbackEnabled` 固定為 `false`。

### 9. PRO 補充分析

PRO 先使用正面照完成一份 BASIC 結果。若有提供 `side`，則以 `strict_angle=False` 分析側面照片的膚色，最後將正面與側面的 LAB 各軸取平均，降低單一角度的光線誤差。

目前 `left45`、`right45` 已保留上傳欄位，但尚未加入正式分類。現有約 10 度的側面照也不足以可靠判斷鷹鉤鼻、翹鼻、塌鼻或下巴前後縮，這些項目必須使用 70 至 90 度輪廓照後再實作。

### 10. 妝容文字建議

`POST /suggest` 可接收完整 `analysisPackage`，也可只接收 `faceAnalysis`。另外可傳入 `style`、`language`、`userNote` 與指定模型。後端抽出臉型、眉型、眼型、鼻型、嘴型與膚色，組成妝容提示後送至 Ollama。

服務會向 Ollama 分別取得繁體中文建議 `suggestion` 與英文渲染指令 `renderPromptEn`。Ollama 無法連線、逾時或輸出無效時直接回 HTTP 502，不提供本機規則建議或固定假資料。成功回應的 `provider` 固定為 `ollama`，`fallbackUsed` 固定為 `false`。

### 11. CORS 與啟動設定

`CORS_ORIGINS` 可設定允許的前端來源，多個來源以逗號分隔；未設定時為 `*`。本機服務啟動前會檢查 Port 是否已被占用，若該 Port 已有本專案服務，會提示目前正在執行的服務名稱。

## 三、BASIC 臉部分析具體分類

### 1. 臉型

臉型以臉高、最大臉寬、額頭寬、顴骨寬、下顎寬及下巴寬度判斷。

| 輸出 | 主要判斷內容 |
| --- | --- |
| 鵝蛋臉 | 臉高略大於臉寬，上中下臉寬度接近，輪廓平順 |
| 圓形臉 | 臉高與臉寬較接近，顴骨區較寬 |
| 方形臉 | 額頭、顴骨、下顎寬度接近，臉長比例偏短或下顎明顯 |
| 長形臉 | 臉高與臉寬比大於或接近 1.35 |
| 心形臉 | 額頭明顯寬於下顎，顴骨較寬且下巴收窄 |
| 菱形臉 | 顴骨最寬，額頭與下顎都明顯較窄 |
| 梯形臉 | 下顎寬於顴骨與額頭，且臉長比例不屬方形 |
| 未知 | 特徵點距離不足，無法形成有效比例 |

心形臉與菱形臉容易受髮際線、瀏海和取樣高度影響，因此程式只在寬度差異明顯時輸出。

### 2. 眉型

眉型使用左右眉各五個外輪廓點，計算眉峰高度及眉尾落差。

| 輸出 | 判斷內容 |
| --- | --- |
| 一字眉 | 眉弓高度低，眉頭與眉尾落差小 |
| 彎月眉 | 眉弓高度明顯，眉尾沒有過度下降 |
| 落尾眉 | 眉尾垂直落差明顯 |
| 標準眉 | 不屬於以上明顯特徵的中間類型 |

### 3. 眼型

眼型使用眼寬、眼高、眼高寬比、眼尾角度及眼寬占臉寬比例判斷，左右眼數值取平均。

| 輸出 | 判斷內容 |
| --- | --- |
| 瞇縫眼 | 眼寬占臉寬比例偏小 |
| 下垂眼 | 眼尾方向呈明顯下垂 |
| 圓眼 | 眼高寬比較高 |
| 瑞鳳眼 | 眼高寬比非常低，外形細長 |
| 丹鳳眼 | 眼形細長且眼尾方向上揚 |
| 細長眼 | 眼高寬比偏低，眼尾角度不明顯 |
| 桃花眼 | 中等眼高寬比、眼寬較大且眼尾微揚 |
| 杏仁眼 | 中等比例，沒有明顯上揚或下垂 |
| 圓杏眼 | 比杏仁眼更圓，但未達圓眼條件 |

### 4. 鼻型

BASIC 只比較鼻翼寬度與臉寬：

| 輸出 | 條件 |
| --- | --- |
| 寬鼻 | 鼻寬／臉寬大於或等於 0.325 |
| 窄鼻 | 鼻寬／臉寬小於或等於 0.205 |
| 標準鼻 | 介於兩者之間 |

正面照沒有足夠深度資訊，因此 BASIC 不輸出鷹鉤鼻、塌鼻、朝天鼻、翹鼻、高鼻樑或低鼻樑。

### 5. 嘴型

嘴型使用唇高寬比、上唇 M 峰與中心落差，以及嘴角和唇中心的垂直關係判斷。

| 輸出 | 條件 |
| --- | --- |
| 厚唇 | 唇高／唇寬大於 0.40 |
| 薄唇 | 唇高／唇寬小於 0.25 |
| M型唇 | 上唇雙峰與中央落差明顯 |
| 微笑唇 | 嘴角相對唇中心呈上揚 |
| 花瓣唇 | 比例位於中間且沒有以上明顯特徵 |

### 6. 膚色

系統先建立全臉遮罩，再排除嘴唇及雙眼，只保留可用皮膚區域。皮膚像素不足 100 點時停止分析，要求使用光線均勻且臉部清楚的照片。

膚色輸出分成三部分：

- 四季型：春季、夏季、秋季、冬季。
- 膚色分級：白皙自然色、中等亮白自然色、白皙象牙色、自然象牙、健康象牙、古銅象牙、健康玫瑰色。
- LAB：`L` 表示明度，`a` 表示紅綠軸，`b` 表示黃藍軸。

四季型會綜合 LAB、HSV 的明度、飽和度及皮膚區域的明暗變化。暖色調偏向春、秋；冷色調偏向夏、冬，再依明亮、柔和或清晰程度細分。

### 7. 唇色 LAB

嘴唇區域使用 FaceMesh 唇部輪廓建立遮罩，再計算平均 LAB。此欄位保留原始數值，之後可用於口紅色號配對或妝後圖片生成。

### 8. 臉部對稱性

對稱分數範圍為 0 至 100，100 表示量測結果最接近左右一致。組成方式：

- 左右眼開合比例占 50%。
- 鼻尖偏離臉部中線占 30%。
- 左右嘴角距離對稱占 20%。

這是照片上的幾何對稱分數，會受到表情、拍攝角度、鏡頭變形和光線影響，不等同醫療或身分辨識結果。

## 四、BASIC 回傳格式

```json
{
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
  },
  "嘴唇_LAB": {"L": 48.24, "a": 18.0, "b": 12.0},
  "臉部對稱性": {
    "score": 91,
    "eyeOpenRatio": 0.94,
    "noseDeviation": 0.012,
    "mouthSymmetry": 0.97
  }
}
```

## 五、analysisPackage 資料包

資料包不是另一份分析結果，而是把照片資訊、臉部分析、文字建議、妝後圖片及推薦內容放在同一個固定格式中。各端只要認得這個格式，就不需要直接依賴臉部模型的中文原始欄位。

主要欄位：

| 欄位 | 說明 |
| --- | --- |
| `id` | 單次分析識別碼，格式為 `AN-xxxxxxxxxxxx` |
| `schemaVersion` | 資料結構版本，避免新舊前端欄位不相容 |
| `mode` | `BASIC` 或 `PRO` |
| `client` | `web` 或 `ios` |
| `userId` | 登入會員識別碼，訪客可為 null |
| `images` | 正面照與側面照的檔名、型別、大小、尺寸及位置 |
| `faceAnalysis` | 英文統一欄位與完整中文原始結果 |
| `generativeText` | Ollama 建議狀態與內容 |
| `render` | 妝後圖片生成狀態與網址 |
| `recommendations` | 商品、技巧及廣告資料 |

資料包程式放在 `analysis_package.py`。基本使用方式：

```python
from analysis_package import build_analysis_package, build_image_info
from Face_analyzer_BASIC import FaceAnalyzer

with open("photo.jpg", "rb") as file:
    image_bytes = file.read()

raw_result = FaceAnalyzer(image_bytes).export_json()
front_image = build_image_info(
    original_name="photo.jpg",
    content_type="image/jpeg",
    size=len(image_bytes),
    width=1024,
    height=1024,
)

analysis_package = build_analysis_package(
    raw_result,
    front_image,
    client="web",
    user_id=None,
)
```

`normalize_face_analysis()` 會保留 `raw` 中文結果，同時轉出 `faceShape`、`eyeShape`、`noseFront` 等固定英文代碼。前端顯示可讀 `raw`，其他服務串接則使用英文欄位。

## 六、臉部分析程式碼位置

完整可執行程式為 `Face_analyzer_BASIC.py`，其中：

- `FaceAnalyzer.__init__()`：圖片解碼、人臉偵測、角度驗證及 FaceMesh 建立。
- `get_face_shape()`：臉型分析。
- `get_eyebrow_shape()`：眉型分析。
- `get_eye_shape()`：眼型分析。
- `get_nose_shape()`：鼻型分析。
- `get_lip_shape()`：嘴型分析。
- `get_skin_color()`：膚色、四季型與唇色 LAB。
- `get_face_symmetry()`：左右對稱分數。
- `export_json()`：組合最終 BASIC JSON。

最精簡的呼叫方式：

```python
from Face_analyzer_BASIC import FaceAnalyzer

with open("photo.jpg", "rb") as file:
    result = FaceAnalyzer(file.read()).export_json()

print(result)
```

## 七、錯誤回應

| HTTP 狀態 | 發生情況 |
| ---: | --- |
| 400 | 空檔、圖片無法讀取、沒有人臉、角度不符、皮膚區域不足 |
| 404 | 找不到指定 job |
| 409 | job 尚未完成就要求取得結果 |
| 500 | 模型或程式執行時發生未預期錯誤 |
| 502 | Ollama 無法連線、逾時、模型失敗或輸出無效 |

正式環境不應直接把完整 Python 例外訊息回傳給前端；伺服器保留詳細 log，前端只需要穩定的錯誤代碼及可理解的提示文字。

## 八、目前限制

- BASIC 只適用單人、正面、清楚、光線均勻的照片。
- 膚色會受相機白平衡、濾鏡、螢幕翻拍及環境光影響。
- 幾何規則是外觀分類，不是醫療判斷，也不是人臉身分辨識。
- 非同步工作目前只存在單一 Python 程序記憶體，不適合多台主機共用。
- `left45` 與 `right45` 目前只有接收欄位，尚未進入正式分析。
- PRO 的側面鼻型、下巴前後縮及臉部立體度仍需增加輪廓照規格與標註資料。
