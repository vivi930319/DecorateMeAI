import cv2
import numpy as np
import mediapipe as mp
import json

# np.fromfile 解決 cv2.imread 不支援中文路徑和 webp 格式的問題
frame = cv2.imdecode(
    np.fromfile(r"C:\Users\isach\PycharmProjects\PythonProject12\IMG_9929.JPG", dtype=np.uint8),
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
lip_mask  = np.zeros((h, w), dtype=np.uint8)
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

# Lab可以把亮度獨立出來，ab才是純色彩，比HSV更適合膚色分析
lab = cv2.cvtColor(frame, cv2.COLOR_BGR2Lab)

# Lab膚色範圍，淺膚到深膚都涵蓋
# L(亮度)   20~230 : 排掉太暗的陰影和太亮的反光
# a(綠~紅) 135~175 : 皮膚偏紅調，低於135偏綠不是皮膚
# b(藍~黃) 130~175 : 皮膚偏黃調，低於130偏藍不是皮膚
color_mask = cv2.inRange(lab, np.array([20, 135, 130]), np.array([230, 175, 175]))

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

# ── 視覺化 ────────────────────────────────────────────────────────
# rgb轉bgr，opencv畫圖要用bgr
skin_bgr = (int(mean_rgb[2]),     int(mean_rgb[1]),     int(mean_rgb[0]))
lip_bgr  = (int(mean_lip_rgb[2]), int(mean_lip_rgb[1]), int(mean_lip_rgb[0]))

# 用小圖騙過cvtColor，它需要圖片格式才能轉色彩空間
skin_lab = cv2.cvtColor(np.uint8([[skin_bgr]]), cv2.COLOR_BGR2Lab)[0][0]
lip_lab  = cv2.cvtColor(np.uint8([[lip_bgr]]),  cv2.COLOR_BGR2Lab)[0][0]

# 建一張空白畫布
canvas = np.ones((320, 500, 3), dtype=np.uint8) * 30

# 膚色色塊，-1是填滿
cv2.rectangle(canvas, (50, 60),  (190, 180), skin_bgr, -1)
cv2.rectangle(canvas, (50, 60),  (190, 180), (200, 200, 200), 1)

# 嘴唇色塊
cv2.rectangle(canvas, (260, 60), (400, 180), lip_bgr, -1)
cv2.rectangle(canvas, (260, 60), (400, 180), (200, 200, 200), 1)

# 標籤
cv2.putText(canvas, "Skin", (85, 215),  cv2.FONT_HERSHEY_SIMPLEX, 0.7,  (200, 200, 200), 1)
cv2.putText(canvas, "Lip",  (295, 215), cv2.FONT_HERSHEY_SIMPLEX, 0.7,  (200, 200, 200), 1)

# RGB數值
cv2.putText(canvas, f"R{int(mean_rgb[0])} G{int(mean_rgb[1])} B{int(mean_rgb[2])}",             (25, 245),  cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1)
cv2.putText(canvas, f"R{int(mean_lip_rgb[0])} G{int(mean_lip_rgb[1])} B{int(mean_lip_rgb[2])}", (235, 245), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (180, 180, 180), 1)

# ab軸減128才是真正的Lab數值，opencv的ab是0~255但實際Lab是-128~127
cv2.putText(canvas, f"L{skin_lab[0]} a{skin_lab[1]-128} b{skin_lab[2]-128}", (25, 275),  cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1)
cv2.putText(canvas, f"L{lip_lab[0]} a{lip_lab[1]-128} b{lip_lab[2]-128}",    (235, 275), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (150, 150, 150), 1)

# 存成圖片，不用開視窗
cv2.imwrite("color_result.png", canvas)
print("color_result.png 已儲存")
cv2.imshow("Color Result", canvas)
cv2.waitKey(0)
cv2.destroyAllWindows()