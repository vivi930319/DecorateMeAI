import cv2
import numpy as np
import mediapipe as mp
import json
from fastapi import FastAPI, UploadFile, HTTPException, File
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 前端串接要開 CORS，不然瀏覽器會擋
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    # 步驟1：先收前端上傳的圖片 bytes
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="上傳檔案是空的")

    try:
        # 步驟2：跑臉部分析，直接回傳 json 結果
        analyzer = FaceAnalyzer(contents)
        result = analyzer.export_json()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

class FaceAnalyzer:
    def __init__(self, image_input):
        # 入口只收兩種：檔案路徑(str) / API 上傳 bytes
        if isinstance(image_input, str):
            # 本地讀圖走 fromfile + imdecode，中文路徑比較不會炸
            self.frame = cv2.imdecode(
                np.fromfile(image_input, dtype=np.uint8),
                cv2.IMREAD_COLOR
            )
        elif isinstance(image_input, bytes):
            # API 傳進來的是 bytes，直接轉 np buffer 後 decode
            np_arr = np.frombuffer(image_input, np.uint8)
            self.frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        else:
            raise ValueError("image_input 只接受檔案路徑(str)或bytes")

        if self.frame is None:
            raise FileNotFoundError("圖片讀取失敗")

        self.h, self.w, _ = self.frame.shape

        # mesh 在 init 跑一次就好，後面所有分析都吃同一份 landmark
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = mp_face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            min_detection_confidence=0.5
        )
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            raise ValueError("沒偵測到人臉")

        # 這三個是後面每個分析函式都會用到的共用資料
        self.lm = results.multi_face_landmarks[0].landmark
        self.face_landmarks = results.multi_face_landmarks[0]
        self.mp_face_mesh = mp_face_mesh

    def _pt(self, index):
        # mediapipe 給的是 0~1 比例座標，這裡統一轉像素
        return np.array([
            int(self.lm[index].x * self.w),
            int(self.lm[index].y * self.h)
        ])

    def _dist(self, a, b):
        # 兩個 landmark 的直線距離
        return float(np.linalg.norm(self._pt(a) - self._pt(b)))

    def _collect_landmark_indices(self, connections_or_indices):
        """把 FACEMESH_* 轉成單純 landmark index list。"""
        if not connections_or_indices:
            return []

        # 有些常數是 frozenset，先轉 list 才能安全取值
        seq = list(connections_or_indices)
        if not seq:
            return []

        first = seq[0]
        if isinstance(first, (tuple, list)) and len(first) >= 2:
            s = set()
            for a, b in seq:
                s.add(int(a))
                s.add(int(b))
            return sorted(s)

        # 否則當成 index list 處理
        return sorted({int(x) for x in seq})

    def _align_points_by_eyes(self, points_xy):
        """先把點位依眼睛水平對齊，降低歪頭影響。"""
        # 拿左右眼外角當旋轉基準
        left_eye = self._pt(33).astype(np.float32)
        right_eye = self._pt(263).astype(np.float32)
        pivot = (left_eye + right_eye) / 2.0

        dx = float(right_eye[0] - left_eye[0])
        dy = float(right_eye[1] - left_eye[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return points_xy

        angle = np.arctan2(dy, dx)  # 眼睛連線相對水平角度
        # 目標是把眼線轉平，所以用 -angle
        cos_a = float(np.cos(-angle))
        sin_a = float(np.sin(-angle))
        R = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)

        pts = points_xy.astype(np.float32)
        return (pts - pivot) @ R.T + pivot

    # 臉型
    def get_face_shape(self, debug=False):
        # 流程：
        # 步驟1：先把臉部點位對齊（眼睛轉平）
        # 步驟2：用臉輪廓多點抓寬度，不只看單一點
        # 步驟3：如果輪廓抓不到，再退回固定 landmark 算法

        # 先拿臉外輪廓點
        oval_indices = self._collect_landmark_indices(self.mp_face_mesh.FACEMESH_FACE_OVAL)
        if len(oval_indices) < 5:
            # 輪廓點不足，直接走舊版固定點量測
            face_width = self._dist(234, 454)
            forehead_width = self._dist(103, 332)
            cheekbone_width = self._dist(123, 352)
            jaw_width = self._dist(172, 397)
            face_height = self._dist(10, 152)
        else:
            oval_pts = np.array([self._pt(i) for i in oval_indices], dtype=np.float32)
            oval_pts_rot = self._align_points_by_eyes(oval_pts)

            # 臉高改抓 10(額上) -> 152(下巴)
            # 比直接用 oval 的上下界穩，較不會把臉高算太短
            p10 = self._pt(10).astype(np.float32)[None, :]
            p152 = self._pt(152).astype(np.float32)[None, :]
            p10r = self._align_points_by_eyes(p10)[0]
            p152r = self._align_points_by_eyes(p152)[0]
            face_height = float(abs(p152r[1] - p10r[1]))

            if face_height < 1e-6:
                return "未知"

            y_min = float(np.min(oval_pts_rot[:, 1]))
            y_max = float(np.max(oval_pts_rot[:, 1]))

            # 在不同高度切 y 帶去抓寬度，避免單點抖動
            def width_at(level):
                y_level = y_min + face_height * level
                tol = face_height * 0.03  # 第一輪帶寬
                sel = np.abs(oval_pts_rot[:, 1] - y_level) < tol
                if int(np.sum(sel)) < 3:
                    tol2 = face_height * 0.05
                    sel = np.abs(oval_pts_rot[:, 1] - y_level) < tol2
                if int(np.sum(sel)) < 3:
                    return None
                x_min = float(np.min(oval_pts_rot[sel, 0]))
                x_max = float(np.max(oval_pts_rot[sel, 0]))
                return x_max - x_min

            # 掃一段高度，把最大寬當臉寬
            widths = []
            for lv in np.linspace(0.20, 0.85, 14):
                w = width_at(float(lv))
                if w is not None and w > 0:
                    widths.append(w)

            if not widths:
                # 這輪抓不到寬度就回退舊算法
                face_width = self._dist(234, 454)
                forehead_width = self._dist(103, 332)
                cheekbone_width = self._dist(123, 352)
                jaw_width = self._dist(172, 397)
            else:
                face_width = float(max(widths))
                forehead_width = width_at(0.27) or self._dist(103, 332)
                cheekbone_width = width_at(0.50) or self._dist(123, 352)
                jaw_width = width_at(0.80) or self._dist(172, 397)

        if face_width < 1e-6 or jaw_width < 1e-6:
            return "未知"

        ratio_height_width = round(face_height / face_width, 3)
        ratio_forehead_jaw = round(forehead_width / jaw_width, 3)
        ratio_cheekbone_jaw = round(cheekbone_width / jaw_width, 3)
        ratio_jaw_face = round(jaw_width / face_width, 3)

        if debug:
            print(
                json.dumps(
                    {
                        "face_width": round(float(face_width), 2),
                        "face_height": round(float(face_height), 2),
                        "forehead_width": round(float(forehead_width), 2),
                        "cheekbone_width": round(float(cheekbone_width), 2),
                        "jaw_width": round(float(jaw_width), 2),
                        "ratio_height_width": ratio_height_width,
                        "ratio_forehead_jaw": ratio_forehead_jaw,
                        "ratio_cheekbone_jaw": ratio_cheekbone_jaw,
                        "ratio_jaw_face": ratio_jaw_face,
                    },
                    ensure_ascii=False,
                )
            )

        # 長臉不要只看高寬比，會過判；多加下顎比例一起看
        if ratio_height_width >= 1.33 or (ratio_height_width >= 1.26 and ratio_cheekbone_jaw >= 1.18):
            return "長形臉"
        # V-line 且整體偏長時，優先當長形臉（不然常掉去心形）
        elif ratio_height_width >= 1.18 and ratio_forehead_jaw >= 1.30 and ratio_jaw_face <= 0.74:
            return "長形臉"
        elif ratio_height_width < 1.15 and ratio_cheekbone_jaw > 1.2 and ratio_forehead_jaw < 1.05:
            return "圓形臉"
        elif ratio_forehead_jaw > 1.1 and ratio_cheekbone_jaw > 1.2:
            return "心形臉"
        elif ratio_forehead_jaw < 0.92 and ratio_cheekbone_jaw < 1.15:
            return "梯形臉"
        elif ratio_forehead_jaw < 0.88 and ratio_cheekbone_jaw > 1.05:
            return "正三角臉"
        elif ratio_forehead_jaw < 0.95 and ratio_cheekbone_jaw < 1.05:
            return "方形臉"
        elif ratio_cheekbone_jaw > 1.2 and ratio_forehead_jaw < 0.9:
            return "菱形臉"
        else:
            return "鵝蛋臉"
    # 眉型
    def get_eyebrow_shape(self):
        brow_head_y = (self._pt(46)[1] + self._pt(276)[1]) / 2
        brow_peak_y = (self._pt(55)[1] + self._pt(285)[1]) / 2
        brow_tail_y = (self._pt(65)[1] + self._pt(295)[1]) / 2

        avg_head_tail_y = (brow_head_y + brow_tail_y) / 2
        peak_lift = avg_head_tail_y - brow_peak_y
        tail_vs_head = brow_head_y - brow_tail_y

        if peak_lift > 10:
            return "彎月眉"  # 眉峰明顯拱起，閾值拉高
        elif abs(tail_vs_head) < 8:
            return "一字眉"  # 頭尾幾乎等高，範圍放寬
        elif tail_vs_head > 12:
            return "落尾眉"  # 眉尾明顯下垂，閾值拉高避免誤判
        else:
            return "標準眉"  # 其餘都是標準眉

    # 眼型
    def get_eye_shape(self):
        # 左右眼各取：眼頭、眼尾、上眼瞼、下眼瞼

        left_eye_w  = self._dist(33,  133)
        right_eye_w = self._dist(362, 263)
        eye_width   = (left_eye_w + right_eye_w) / 2

        left_eye_h  = self._dist(159, 145)
        right_eye_h = self._dist(386, 374)
        eye_height  = (left_eye_h + right_eye_h) / 2

        # 眼尾 y - 眼頭 y：負值偏上揚，正值偏下垂
        left_angle  = self._pt(133)[1] - self._pt(33)[1]
        right_angle = self._pt(263)[1] - self._pt(362)[1]
        avg_angle   = (left_angle + right_angle) / 2

        ratio = eye_height / eye_width

        # 這段先留著當參考量，後面需要可再拿來加規則
        lid_dist_left  = self._pt(46)[1]  - self._pt(159)[1]
        lid_dist_right = self._pt(276)[1] - self._pt(386)[1]
        avg_lid = (lid_dist_left + lid_dist_right) / 2

        if ratio > 0.28:
            return "雙眼皮"
        elif ratio > 0.22:
            return "長眼"
        else:
            return "單眼皮"

    # 鼻型
    def get_nose_shape(self):
        # 用鼻翼寬、鼻高、鼻尖/鼻底相對位置做分類
        nose_width  = self._dist(129, 358)   # 鼻翼寬
        nose_height = self._dist(168, 2)     # 鼻根到鼻底高度
        face_width  = self._dist(234, 454)

        ratio_width  = nose_width / face_width
        ratio_height = nose_height / self._dist(10, 152)   # 鼻高/臉高

        # 鼻尖跟鼻底 y 差小，通常就是朝天鼻
        nose_tip_y    = self._pt(1)[1]
        nose_base_y   = self._pt(2)[1]
        tip_base_diff = nose_base_y - nose_tip_y

        if ratio_width > 0.25:
            return "寬鼻"
        elif ratio_height < 0.2:
            return "短鼻"
        elif tip_base_diff < 8:
            return "朝天鼻"
        elif ratio_width < 0.15:
            return "直鼻"
        else:
            return "蒜頭鼻"

    # 嘴型
    def get_lip_shape(self):
        # 先算唇厚，再看 M 峰跟嘴角弧度
        lip_width   = self._dist(61, 291)    # 嘴寬
        lip_height  = self._dist(0,  17)     # 唇高

        ratio = lip_height / lip_width

        # M 唇看兩側峰值和中點的高低關係
        peak_left_y  = self._pt(37)[1]
        peak_right_y = self._pt(267)[1]
        center_y     = self._pt(0)[1]
        m_diff = center_y - (peak_left_y + peak_right_y) / 2

        # 微笑唇看嘴角跟中點相對高度
        corner_avg_y = (self._pt(61)[1] + self._pt(291)[1]) / 2
        smile_diff   = center_y - corner_avg_y

        if ratio > 0.4:
            return "厚唇"
        elif ratio < 0.25:
            return "薄唇"
        elif m_diff > 5:
            return "M型唇"
        elif smile_diff < -3:
            return "微笑唇"
        else:
            return "花瓣唇"

    # 膚色
    def get_skin_color(self):
        face_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        lip_mask  = np.zeros((self.h, self.w), dtype=np.uint8)

        # 步驟1：先做整張臉遮罩
        face_points = np.array(
            [[int(lm.x * self.w), int(lm.y * self.h)] for lm in self.face_landmarks.landmark],
            dtype=np.int32
        )
        cv2.fillConvexPoly(face_mask, cv2.convexHull(face_points), 255)

        # 步驟2：先做嘴唇遮罩，之後可直接算唇色
        lip_pts = np.array(
            [[int(self.face_landmarks.landmark[i].x * self.w),
              int(self.face_landmarks.landmark[i].y * self.h)] for i, _ in self.mp_face_mesh.FACEMESH_LIPS],
            dtype=np.int32
        )
        cv2.fillConvexPoly(lip_mask, cv2.convexHull(lip_pts), 255)

        # 步驟3：先取嘴唇平均色
        mean_lip_bgr = cv2.mean(self.frame, mask=lip_mask)[:3]
        lip_rgb = [round(mean_lip_bgr[2], 1), round(mean_lip_bgr[1], 1), round(mean_lip_bgr[0], 1)]

        # 步驟4：把嘴、眼挖掉，盡量只留皮膚區
        def cutout(landmark_ids):
            pts = np.array(
                [[int(self.face_landmarks.landmark[i].x * self.w),
                  int(self.face_landmarks.landmark[i].y * self.h)] for i, _ in landmark_ids],
                dtype=np.int32
            )
            cv2.fillConvexPoly(face_mask, cv2.convexHull(pts), 0)

        cutout(self.mp_face_mesh.FACEMESH_LIPS)
        cutout(self.mp_face_mesh.FACEMESH_LEFT_EYE)
        cutout(self.mp_face_mesh.FACEMESH_RIGHT_EYE)

        # 步驟5：用 Lab 做膚色範圍過濾（比 RGB 抗光）
        lab = cv2.cvtColor(self.frame, cv2.COLOR_BGR2Lab)
        color_mask = cv2.inRange(lab, np.array([20, 135, 130]), np.array([230, 175, 175]))

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN,  kernel)
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)

        combined_mask = cv2.bitwise_and(face_mask, color_mask)

        mean_bgr = cv2.mean(self.frame, mask=combined_mask)[:3]
        skin_rgb = [round(mean_bgr[2], 1), round(mean_bgr[1], 1), round(mean_bgr[0], 1)]

        def classify_shade_12grid(lab_img, hsv_img, mask_u8):
            """12 格分級：粉/黃/中/橄欖 + 一白/二白/三白。"""
            l_mean, a_mean_cv, b_mean_cv, _ = cv2.mean(lab_img, mask=mask_u8)
            l_mean = float(l_mean)             # 0~255 (OpenCV Lab)
            a_axis = float(a_mean_cv - 128.0)  # +紅 / -綠
            b_axis = float(b_mean_cv - 128.0)  # +黃 / -藍

            # 先判底色
            if a_axis <= -6.0 and b_axis >= 6.0:
                undertone = "橄欖"
            elif a_axis >= 7.0 and b_axis <= 12.0:
                undertone = "粉"
            elif b_axis >= 13.0:
                undertone = "黃"
            else:
                undertone = "中"

            # 再判深淺
            if l_mean >= 175.0:
                depth = "一白"
            elif l_mean >= 155.0:
                depth = "二白"
            else:
                depth = "三白"

            return f"{undertone}{depth}", undertone, depth

        # 步驟6：四季型先判冷暖，再判亮/柔/清晰
        hsv = cv2.cvtColor(self.frame, cv2.COLOR_BGR2HSV)
        h_mean, s_mean, v_mean, _ = cv2.mean(hsv, mask=combined_mask)
        h_mean = float(h_mean)  # OpenCV Hue: 0~179
        s_mean = float(s_mean)  # 0~255
        v_mean = float(v_mean)  # 0~255

        # 用同一塊皮膚 mask 算平均，結果比較穩
        l_mean, a_mean_cv, b_mean_cv, _ = cv2.mean(lab, mask=combined_mask)
        l_mean = float(l_mean)             # 0~255
        a_axis = float(a_mean_cv - 128.0)  # +偏紅 / -偏綠
        b_axis = float(b_mean_cv - 128.0)  # +偏黃 / -偏藍

        # 冷暖主看 b 軸：越大越黃(暖)、越小越冷
        if b_axis >= 12.0:
            undertone = "warm"
        elif b_axis <= 8.5:
            undertone = "cool"
        else:
            undertone = "neutral"

        # bright / soft / clear 三個訊號分季型
        bright = (l_mean >= 158.0) or (v_mean >= 168.0)
        soft = s_mean <= 110.0

        v_chan = hsv[:, :, 2]
        mask = combined_mask.astype(bool)
        if np.any(mask):
            v_vals = v_chan[mask].astype(np.float32)
            v_std = float(np.std(v_vals))
        else:
            v_std = 0.0
        clear = (v_std >= 18.0) or (s_mean >= 125.0)

        # 春秋夏冬規則在這裡分流
        if undertone == "warm":
            season = "春季" if (bright and clear) else "秋季"
        elif undertone == "cool":
            season = "夏季" if (bright and soft and not clear) else "冬季"
        else:
            # 中性底色時，再用亮度/彩度補分
            if clear and not soft:
                season = "冬季"
            elif bright and soft:
                season = "夏季"
            elif bright:
                season = "春季"
            else:
                season = "秋季"

        shade_label, shade_undertone, shade_depth = classify_shade_12grid(lab, hsv, combined_mask)

        return skin_rgb, lip_rgb, season, shade_label, shade_undertone, shade_depth

    # 輸出
    def export_json(self, save_path=None):
        skin_rgb, lip_rgb, season, shade_label, shade_undertone, shade_depth = self.get_skin_color()

        result = {
            "臉型":    self.get_face_shape(),       # → face_logic key
            "眉型":    self.get_eyebrow_shape(),     # → eyebrow_logic key
            "眼型":    self.get_eye_shape(),         # → eye_logic key
            "鼻型":    self.get_nose_shape(),        # → nose_logic key
            "嘴型":    self.get_lip_shape(),         # → lip_logic key
            "膚色": {
                "四季型": season,
                "膚色分級": shade_label
            },
            "膚色_RGB": skin_rgb,
            "嘴唇_RGB": lip_rgb
        }

        # API 模式通常不存檔；本地 debug 才寫 json
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)

        return result

if __name__ == "__main__":
    import uvicorn

    # 本地跑
    uvicorn.run(app, host="0.0.0.0", port=8000)

    # 本地單張圖測試
    # analyzer = FaceAnalyzer(r"C:\Users\isach\PycharmProjects\PythonProject12\IMG_9929.JPG")
    # result = analyzer.export_json(save_path="face_result.json")
    # print(json.dumps(result, indent=4, ensure_ascii=False))