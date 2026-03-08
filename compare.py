import cv2
import numpy as np
import json

with open("skin_color.json", "r") as f:
    data = json.load(f)

skin_rgb = data["mean_color_RGB"]
lip_rgb  = data["lip_color_RGB"]

skin_bgr = (skin_rgb[2], skin_rgb[1], skin_rgb[0])
lip_bgr  = (lip_rgb[2],  lip_rgb[1],  lip_rgb[0])

canvas = np.zeros((200, 400, 3), dtype=np.uint8)

canvas[0:200, 0:200]   = skin_bgr
canvas[0:200, 200:400] = lip_bgr

cv2.imshow("skin / lip", canvas)
cv2.waitKey(0)
cv2.destroyAllWindows()