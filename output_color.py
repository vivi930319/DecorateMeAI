import cv2
import numpy as np
import json

# 讀skin_color.json
with open("skin_color.json", "r") as f:
    data = json.load(f)

skin_rgb = data["mean_color_RGB"]
lip_rgb  = data["lip_color_RGB"]

# rgb轉bgr，opencv畫圖要用bgr
skin_bgr = (int(skin_rgb[2]), int(skin_rgb[1]), int(skin_rgb[0]))
lip_bgr  = (int(lip_rgb[2]),  int(lip_rgb[1]),  int(lip_rgb[0]))

# 建一張空白畫布
canvas = np.ones((300, 500, 3), dtype=np.uint8) * 30  # 深灰背景

# 畫膚色色塊
cv2.rectangle(canvas, (50, 60), (190, 180), skin_bgr, -1)   # -1是填滿
cv2.rectangle(canvas, (50, 60), (190, 180), (200, 200, 200), 1)  # 外框

# 畫嘴唇色塊
cv2.rectangle(canvas, (260, 60), (400, 180), lip_bgr, -1)
cv2.rectangle(canvas, (260, 60), (400, 180), (200, 200, 200), 1)

# 文字標籤
cv2.putText(canvas, "Skin", (85, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)
cv2.putText(canvas, "Lip",  (295, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 1)

# rgb數值顯示在色塊下面
cv2.putText(canvas, f"R{int(skin_rgb[0])} G{int(skin_rgb[1])} B{int(skin_rgb[2])}", (30, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)
cv2.putText(canvas, f"R{int(lip_rgb[0])}  G{int(lip_rgb[1])} B{int(lip_rgb[2])}",  (240, 255), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 180, 180), 1)

cv2.imshow("Color Result", canvas)
cv2.waitKey(0)
cv2.destroyAllWindows()