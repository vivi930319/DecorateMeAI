import cv2
import numpy as np

frame = cv2.imread(r"C:\Users\isach\PycharmProjects\PythonProject12\c230aaf4233e477da62072669d342acf.webp")
h, w, _ = frame.shape

# 1. 轉 HSV
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

# 2. 膚色範圍（先用這個預設值）
lower_skin = np.array([0,  40,  80],  dtype=np.uint8)
upper_skin = np.array([20, 170, 255], dtype=np.uint8)

# 3. 產生遮罩
mask = cv2.inRange(hsv, lower_skin, upper_skin)

# 先看原始遮罩（還很雜亂）
cv2.imshow("原始遮罩", mask)
cv2.waitKey(0)
# 接在上面的程式碼後面

kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

# 去掉小白點（雜訊）
mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

# 補起小黑洞（讓膚色區域更完整）
mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

# 看清理後的遮罩
cv2.imshow("清理後遮罩", mask)
cv2.waitKey(0)
# 套用遮罩看效果
result = cv2.bitwise_and(frame, frame, mask=mask)
cv2.imshow("膚色區域", result)

# 計算平均膚色
mean_bgr = cv2.mean(frame, mask=mask)[:3]
mean_rgb = (mean_bgr[2], mean_bgr[1], mean_bgr[0])

print(f"平均膚色 BGR: {mean_bgr[0]:.1f}, {mean_bgr[1]:.1f}, {mean_bgr[2]:.1f}")
print(f"平均膚色 RGB: {mean_rgb[0]:.1f}, {mean_rgb[1]:.1f}, {mean_rgb[2]:.1f}")

cv2.waitKey(0)