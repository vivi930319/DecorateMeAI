import cv2
import mediapipe as mp

# ===== 初始化 mediapipe =====
mp_face_mesh = mp.solutions.face_mesh

# ===== 讀圖片 =====
image_path = r"C:\Users\isach\PycharmProjects\PythonProject12\IMG_0361.JPG"
img = cv2.imread(image_path)

if img is None:
    raise Exception("圖片讀取失敗")

# --- 新增：縮放圖片邏輯 ---
max_width = 800  # 你可以自行調整想要的寬度
h, w, _ = img.shape
if w > max_width:
    scale = max_width / w
    img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    h, w, _ = img.shape  # 更新縮放後的長寬
# ------------------------

# ===== 建立 face mesh =====
with mp_face_mesh.FaceMesh(
    static_image_mode=True,
    max_num_faces=1,
    min_detection_confidence=0.5
) as face_mesh:

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)

    if not results.multi_face_landmarks:
        raise Exception("沒偵測到人臉")

    lm = results.multi_face_landmarks[0].landmark

    # ===== 你要看的點 =====
    groups = {
        "left_eye": [33, 133, 159, 145],
        "right_eye": [362, 263, 386, 374],
        "face": [10, 152, 234, 454]
    }

    colors = {
        "left_eye": (0, 0, 255),   # 紅
        "right_eye": (255, 0, 0),  # 藍
        "face": (0, 255, 0)        # 綠
    }

    # ===== 畫點 =====
    for name, points in groups.items():
        color = colors[name]
        for idx in points:
            x = int(lm[idx].x * w)
            y = int(lm[idx].y * h)

            cv2.circle(img, (x, y), 3, color, -1) # 縮小點的大小(改為3)
            cv2.putText(
                img,
                str(idx),
                (x + 3, y - 3),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                color,
                1
            )

# ===== 顯示結果 =====
cv2.imshow("Face Landmarks Debug", img)
cv2.waitKey(0)
cv2.destroyAllWindows()