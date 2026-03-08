import cv2
import numpy as np
import mediapipe as mp
import json

# np.fromfile 解決 cv2.imread 不支援中文路徑和 webp 格式的問題
frame = cv2.imdecode(
    np.fromfile(r"C:\Users\isach\PycharmProjects\PythonProject12\c230aaf4233e477da62072669d342acf.webp", dtype=np.uint8),
    cv2.IMREAD_COLOR
)

# 圖片讀取失敗就直接終止
if frame is None:
    raise FileNotFoundError("圖片讀取失敗")

# 把圖片的高寬存起來，之後換算座標點位會用到，_ 是顏色通道固定3不用管
h, w, _ = frame.shape

# 導入人臉468點位模組
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=True,      # True是單張圖片，False是影片
    max_num_faces=1,             # 一次只偵測一張臉
    min_detection_confidence=0.5 # 信心值低於這個就不算
)

# mediapipe只吃rgb但opencv讀進來是bgr，所以要先轉
rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

# 丟進mediapipe跑人臉偵測，結果會存在results裡
results = face_mesh.process(rgb)

# 建一張跟原圖一樣大的全黑畫布，之後要在上面畫臉部遮罩
# 只要兩維(h,w)就好，遮罩只有黑(0)跟白(255)不需要顏色通道
face_mask = np.zeros((h, w), dtype=np.uint8)

# 嘴唇遮罩要獨立出來
# 因為等等cutout會把嘴唇從face_mask挖掉，先算才來得及
lip_mask = np.zeros((h, w), dtype=np.uint8)
mean_lip_rgb = None

# 如果沒偵測到臉multi_face_landmarks會是None，所以要先判斷
if results.multi_face_landmarks:
    for face_landmarks in results.multi_face_landmarks:

        # mediapipe回傳的座標是0~1的比例值，要乘以寬高才是實際像素座標
        face_points = np.array(
            [[int(lm.x * w), int(lm.y * h)] for lm in face_landmarks.landmark],
            dtype=np.int32
        )

        # convexHull從468個散點找最外圍邊界，fillConvexPoly把邊界內塗白
        # 255是白色，這樣才會被後續計算納入
        cv2.fillConvexPoly(face_mask, cv2.convexHull(face_points), 255)

        # cutout之前先把嘴唇畫到lip_mask
        # 等cutout跑完嘴唇就被挖掉了，到時候就算不到嘴唇顏色
        lip_pts = np.array(
            [[int(face_landmarks.landmark[i].x * w),
              int(face_landmarks.landmark[i].y * h)] for i, _ in mp_face_mesh.FACEMESH_LIPS],
            dtype=np.int32
        )
        cv2.fillConvexPoly(lip_mask, cv2.convexHull(lip_pts), 255)

        # 用lip_mask算嘴唇的平均顏色
        mean_lip_bgr = cv2.mean(frame, mask=lip_mask)[:3]
        mean_lip_rgb = [round(mean_lip_bgr[2], 1), round(mean_lip_bgr[1], 1), round(mean_lip_bgr[0], 1)]

        # 這裡是去挖掉五官
        def cutout(landmark_ids):
            # landmark_ids裡面裝的是(點A,點B)的連線對，i是第一個點，_是第二個點不需要
            pts = np.array(
                [[int(face_landmarks.landmark[i].x * w),
                  int(face_landmarks.landmark[i].y * h)] for i, _ in landmark_ids],
                dtype=np.int32
            )
            # 填0(黑色)把五官挖掉，眼睛嘴巴就不會算進膚色
            cv2.fillConvexPoly(face_mask, cv2.convexHull(pts), 0)

        # 直接套mediapipe內建的點位群組定位五官範圍
        cutout(mp_face_mesh.FACEMESH_LIPS)
        cutout(mp_face_mesh.FACEMESH_LEFT_EYE)
        cutout(mp_face_mesh.FACEMESH_RIGHT_EYE)

# hsv可以把顏色拆成色相、飽和、亮度，比bgr更好定義膚色範圍
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

# 膚色範圍根據大眾膚色定義，淺膚到深膚都涵蓋到
# H(色相)  0~25  : 皮膚的橘紅色調，超過就不是皮膚
# S(飽和) 20~180 : 下限排掉太灰的，上限排掉太豔的妝容
# V(亮度) 50~255 : 下限排掉臉上太暗的陰影
color_mask = cv2.inRange(hsv, np.array([0, 20, 50]), np.array([25, 180, 255]))

# 橢圓形核比方形更貼合皮膚邊緣的自然曲線
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# MORPH_OPEN 先腐蝕再膨脹，把零散的小白點雜訊消掉
color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN,  kernel)

# MORPH_CLOSE 先膨脹再腐蝕，把皮膚區域裡的小黑洞補起來
color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)

# 兩個遮罩取交集，要同時在臉部範圍內且顏色是膚色才保留
combined_mask = cv2.bitwise_and(face_mask, color_mask)

# 只算combined_mask白色區域的平均顏色，也就是純皮膚的平均膚色
# opencv用bgr存色彩，所以[2]是R，[1]是G，[0]是B
mean_bgr = cv2.mean(frame, mask=combined_mask)[:3]
mean_rgb = [round(mean_bgr[2], 1), round(mean_bgr[1], 1), round(mean_bgr[0], 1)]

print(f"平均膚色 RGB: {mean_rgb[0]}, {mean_rgb[1]}, {mean_rgb[2]}")
print(f"嘴唇顏色 RGB: {mean_lip_rgb[0]}, {mean_lip_rgb[1]}, {mean_lip_rgb[2]}")

result = {
    "mean_color_RGB": mean_rgb,
    "lip_color_RGB": mean_lip_rgb
}
with open("skin_color.json", "w") as f:
    json.dump(result, f, indent=4)