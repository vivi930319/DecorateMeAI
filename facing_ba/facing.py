import cv2
import mediapipe as mp
import numpy as np

# 讀取圖片路徑
image_path = r"C:\Users\isach\Downloads\IMG_4093.png"
img = cv2.imread(image_path)  # 讀進圖片資料
if img is None:
    print("圖片載入失敗")  # 沒讀到就直接結束
    exit()

# 拿原圖的高寬
h, w = img.shape[:2]
draw_img = img.copy()  # 做一份副本用來畫標記

# 初始化 mediapipe 的臉部模型
face_model = mp.solutions.face_mesh.FaceMesh(
    static_image_mode=True,  # 單張圖片模式
    refine_landmarks=True     # 開 refine 才能抓眼部細節
)

# 把 BGR 轉成 RGB 給 mediapipe 處理
results = face_model.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

# 如果沒偵測到臉就結束
if not results.multi_face_landmarks:
    print("未偵測到臉部")
    exit()

# 拿第一張臉的特徵點
key_points = results.multi_face_landmarks[0].landmark

# 轉換顏色空間到 HSV，方便分析亮度
hsv_img = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# 定義眼下方的採樣點（用 mediapipe 的索引）
# 這裡取眼睛下緣幾個點，不包含眼球區域
L_EYE_POINTS = [374, 380, 381, 382, 385, 386, 387, 388]
R_EYE_POINTS = [145, 153, 154, 155, 157, 158, 159, 160]
SAMPLING_INDICES = L_EYE_POINTS + R_EYE_POINTS  # 合併左右眼

# 建立空陣列存放 HSV 值與座標
hsv_samples = []
all_coords = []

# 逐點取樣
for idx in SAMPLING_INDICES:
    if idx < len(key_points):  # 確保索引沒超出
        lm = key_points[idx]
        cx, cy = int(lm.x * w), int(lm.y * h)  # 把相對座標轉成像素座標
        cy += int(0.035 * h)  # 往下移大約臉高3.5%，避開眼球區域
        if 0 <= cx < w and 0 <= cy < h:  # 確保沒超出圖片範圍
            hsv_samples.append(hsv_img[cy, cx])  # 存取樣的 HSV
            all_coords.append([cx, cy])  # 存像素座標
            cv2.circle(draw_img, (cx, cy), 2, (0, 255, 255), -1)  # 畫出取樣點（黃色點）

# 如果沒取到點就直接結束
if not hsv_samples:
    print("採樣失敗")
    exit()

# 把取樣的 HSV 值轉 numpy 陣列
hsv_array = np.array(hsv_samples)

# 從取樣區算平均亮度 (V)
avg_v = int(np.mean(hsv_array[:, 2]))

# 設定暗部的亮度門檻
# 平均亮度以下一點就算暗部
V_THRESHOLD = max(50, avg_v - 15)
dark_lower = np.array([0, 0, 0])  # 最低值
dark_upper = np.array([180, 255, V_THRESHOLD])  # 高於這亮度就不算暗
dark_mask = cv2.inRange(hsv_img, dark_lower, dark_upper)  # 做出暗部遮罩

# 只針對眼下區域
coords_np = np.array(all_coords)
if coords_np.size > 0:
    # 算出眼下取樣區域的邊界
    x_min, y_min = np.min(coords_np, axis=0)
    x_max, y_max = np.max(coords_np, axis=0)

    # 設定上下左右的額外邊界範圍
    margin_x = 35           # 左右邊多一點寬度
    margin_y_top = 10       # 上方留一點空間
    margin_y_bottom = 80    # 下方延伸比較多，往臉頰方向

    # 計算實際邊界框座標（要考慮不超出圖片）
    x_min_rect = max(0, x_min - margin_x)
    y_min_rect = max(0, y_min - margin_y_top)
    x_max_rect = min(w, x_max + margin_x)
    y_max_rect = min(h, y_max + margin_y_bottom)

    # 做出這一塊區域的遮罩
    region_mask = np.zeros((h, w), dtype=np.uint8)
    region_mask[y_min_rect:y_max_rect, x_min_rect:x_max_rect] = 255

    # 結合暗部遮罩跟眼下區域
    final_dark_mask = cv2.bitwise_and(dark_mask, dark_mask, mask=region_mask)

    # 模糊邊緣讓遮罩自然一點
    final_dark_mask = cv2.GaussianBlur(final_dark_mask, (15, 15), 5)
else:
    # 沒抓到點的情況就直接用整張暗部遮罩
    final_dark_mask = dark_mask

# 偵測暗部輪廓
dark_contours, _ = cv2.findContours(final_dark_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# 畫出暗部範圍的矩形框
for cnt in dark_contours:
    if cv2.contourArea(cnt) > 150:  # 過小的雜訊不要
        x, y, ww, hh = cv2.boundingRect(cnt)
        cv2.rectangle(draw_img, (x, y), (x + ww, y + hh), (139, 0, 0), 2)  # 深紅色框
        cv2.putText(draw_img, "Dark_Area", (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (139, 0, 0), 1)

resized = cv2.resize(draw_img, (800, 800))
cv2.imshow("Face Dark Area Detection", resized)
cv2.waitKey(0)
cv2.destroyAllWindows()
