import cv2
import numpy as np
import mediapipe as mp
import json
from fastapi import FastAPI, UploadFile, HTTPException, File
from fastapi.middleware.cors import CORSMiddleware

#初版上線docker 先調整膚色文獻 之後慢慢微調
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

    def _width_between(self, left_idx, right_idx, aligned=False):
        pts = np.array([self._pt(left_idx), self._pt(right_idx)], dtype=np.float32)
        if aligned:
            pts = self._align_points_by_eyes(pts)
        return float(np.linalg.norm(pts[0] - pts[1]))

    def _face_shape_ratios(self):
        """固定 landmark 量測 + 眼睛水平校正，避免 oval 掃描額寬飄掉。"""
        p234 = self._pt(234).astype(np.float32)
        p454 = self._pt(454).astype(np.float32)
        p10 = self._pt(10).astype(np.float32)
        p152 = self._pt(152).astype(np.float32)
        aligned = self._align_points_by_eyes(np.array([p10, p152, p234, p454], dtype=np.float32))

        face_width = float(np.linalg.norm(aligned[2] - aligned[3]))
        face_height = float(abs(aligned[1][1] - aligned[0][1]))
        forehead_width = self._width_between(103, 332, aligned=True)
        cheekbone_width = self._width_between(123, 352, aligned=True)
        jaw_width = self._width_between(172, 397, aligned=True)

        if face_width < 1e-6 or jaw_width < 1e-6 or face_height < 1e-6:
            return None

        return {
            "face_width": face_width,
            "face_height": face_height,
            "forehead_width": forehead_width,
            "cheekbone_width": cheekbone_width,
            "jaw_width": jaw_width,
            "ratio_height_width": round(face_height / face_width, 3),
            "ratio_forehead_jaw": round(forehead_width / jaw_width, 3),
            "ratio_cheekbone_jaw": round(cheekbone_width / jaw_width, 3),
            "ratio_jaw_face": round(jaw_width / face_width, 3),
        }

    def _eye_side_metrics(self, inner_idx, outer_idx, upper_ids, lower_idx, brow_ids):
        inner = self._pt(inner_idx).astype(np.float32)
        outer = self._pt(outer_idx).astype(np.float32)
        upper = np.array([self._pt(i) for i in upper_ids], dtype=np.float32)
        lower = self._pt(lower_idx).astype(np.float32)
        brows = np.array([self._pt(i) for i in brow_ids], dtype=np.float32)

        eye_width = float(np.linalg.norm(outer - inner))
        lid_center = upper.mean(axis=0)
        eye_height = float(np.linalg.norm(lid_center - lower))
        ear = eye_height / eye_width if eye_width > 0 else 0.0

        aligned = self._align_points_by_eyes(np.array([outer, inner], dtype=np.float32))
        if aligned[0][0] <= aligned[1][0]:
            outer_a, inner_a = aligned[0], aligned[1]
        else:
            outer_a, inner_a = aligned[1], aligned[0]
        dx = float(inner_a[0] - outer_a[0])
        dy = float(inner_a[1] - outer_a[1])
        angle = float(np.degrees(np.arctan2(dy, dx))) if dx > 1e-6 else 0.0

        brow_y = float(np.mean(brows[:, 1]))
        lid_y = float(np.mean(upper[:, 1]))
        lid_spread = float(np.max(upper[:, 1]) - np.min(upper[:, 1]))
        lid_curve = lid_spread / eye_height if eye_height > 0 else 0.0

        return {
            "eye_width": eye_width,
            "eye_height": eye_height,
            "ear": ear,
            "angle": angle,
            "brow_gap": max(0.0, lid_y - brow_y),
            "lid_curve": lid_curve,
        }

    def _eyelid_crease_score(self, inner, outer, upper, lower):
        """上眼皮區域水平梯度，雙眼皮摺線通常較明顯。"""
        cx = int((inner[0] + outer[0]) / 2)
        cy = int(np.mean(upper[:, 1]))
        ew = max(8, int(np.linalg.norm(outer - inner)))
        eye_h = max(4.0, float(np.linalg.norm(upper.mean(axis=0) - lower)))

        y1 = max(0, cy - int(eye_h * 1.1))
        y2 = min(self.h, cy + int(eye_h * 0.15))
        x1 = max(0, cx - ew)
        x2 = min(self.w, cx + ew)
        patch = self.frame[y1:y2, x1:x2]
        if patch.size == 0 or patch.shape[0] < 4:
            return 0.0

        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        row_a = int(gray.shape[0] * 0.15)
        row_b = int(gray.shape[0] * 0.70)
        if row_b <= row_a:
            return 0.0
        grad = float(np.mean(np.abs(gy[row_a:row_b, :])))
        return grad / max(1.0, float(np.std(gray)))

    def _classify_eyelid_type(self, left, right, face_width):
        brow_gap_norm = (left["brow_gap"] + right["brow_gap"]) / (2.0 * face_width)
        lid_curve = (left["lid_curve"] + right["lid_curve"]) / 2.0
        crease = (
            self._eyelid_crease_score(
                self._pt(133).astype(np.float32),
                self._pt(33).astype(np.float32),
                np.array([self._pt(i) for i in (157, 158, 159, 160, 161)], dtype=np.float32),
                self._pt(145).astype(np.float32),
            )
            + self._eyelid_crease_score(
                self._pt(362).astype(np.float32),
                self._pt(263).astype(np.float32),
                np.array([self._pt(i) for i in (385, 386, 387, 388, 398)], dtype=np.float32),
                self._pt(374).astype(np.float32),
            )
        ) / 2.0

        score = 0.0
        if brow_gap_norm >= 0.042:
            score += 1
        if lid_curve >= 0.12:
            score += 1
        if crease >= 0.35:
            score += 1

        return "雙眼皮" if score >= 2 else "單眼皮", {
            "brow_gap_norm": round(brow_gap_norm, 4),
            "lid_curve": round(lid_curve, 3),
            "crease": round(crease, 3),
            "score": score,
        }

    # 臉型
    def get_face_shape(self, debug=False):
        ratios = self._face_shape_ratios()
        if ratios is None:
            return "未知"

        if debug:
            print(json.dumps(ratios, ensure_ascii=False))

        ratio_height_width = ratios["ratio_height_width"]
        ratio_forehead_jaw = ratios["ratio_forehead_jaw"]
        ratio_cheekbone_jaw = ratios["ratio_cheekbone_jaw"]
        ratio_jaw_face = ratios["ratio_jaw_face"]

        if ratio_height_width >= 1.33 or (ratio_height_width >= 1.26 and ratio_cheekbone_jaw >= 1.18):
            return "長形臉"
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

    def get_eye_shape(self, debug=False):
        face_width = self._dist(234, 454)
        if face_width < 1e-6:
            return "未知"

        left = self._eye_side_metrics(
            inner_idx=133, outer_idx=33,
            upper_ids=(157, 158, 159, 160, 161),
            lower_idx=145,
            brow_ids=(46, 53, 52, 65, 55),
        )
        right = self._eye_side_metrics(
            inner_idx=362, outer_idx=263,
            upper_ids=(385, 386, 387, 388, 398),
            lower_idx=374,
            brow_ids=(276, 283, 282, 295, 285),
        )

        eye_width = (left["eye_width"] + right["eye_width"]) / 2.0
        if eye_width < 1e-6:
            return "未知"

        ear = (left["ear"] + right["ear"]) / 2.0
        angle = (left["angle"] + right["angle"]) / 2.0
        ratio_to_face = eye_width / face_width

        eyelid_type, eyelid_debug = self._classify_eyelid_type(left, right, face_width)

        if ratio_to_face < 0.055:
            eye_type = "瞇縫眼"
        elif angle > 8:
            eye_type = "下垂眼"
        elif angle < -8:
            eye_type = "上斜眼"
        elif ear > 0.38:
            eye_type = "圓杏眼"
        elif -8 < angle < -3 and ear < 0.25:
            eye_type = "丹鳳眼"
        elif -5 < angle < 2 and 0.25 < ear < 0.34:
            eye_type = "桃花眼"
        elif ear < 0.20:
            eye_type = "瑞鳳眼"
        else:
            eye_type = "杏仁眼"

        if debug:
            print(json.dumps({
                "ear": round(ear, 3),
                "angle": round(angle, 2),
                "ratio_to_face": round(ratio_to_face, 3),
                "left": {k: round(v, 3) if isinstance(v, float) else v for k, v in left.items()},
                "right": {k: round(v, 3) if isinstance(v, float) else v for k, v in right.items()},
                "eyelid": eyelid_debug,
            }, ensure_ascii=False))

        return f"{eyelid_type}・{eye_type}"

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

    _MAC_SHADE_RANGES = {
        "白皙自然色":     {"L_MIN": 73.2,  "L_MAX": 80.54, "A_MIN": 5.12, "A_MAX": 9.96,  "B_MIN": 15.58, "B_MAX": 22.67},
        "中等亮白自然色": {"L_MIN": 69.26, "L_MAX": 77.82, "A_MIN": 7.41, "A_MAX": 8.61,  "B_MIN": 17.1,  "B_MAX": 19.59},
        "白皙象牙色":     {"L_MIN": 80.54, "L_MAX": 85.37, "A_MIN": 2.65, "A_MAX": 5.12,  "B_MIN": 15.03, "B_MAX": 15.58},
        "自然象牙":       {"L_MIN": 68.88, "L_MAX": 82.99, "A_MIN": 2.97, "A_MAX": 9.85,  "B_MIN": 19.55, "B_MAX": 25.1},
        "健康象牙":       {"L_MIN": 65.32, "L_MAX": 76.37, "A_MIN": 7.16, "A_MAX": 9.05,  "B_MIN": 23.08, "B_MAX": 28.86},
        "古銅象牙":       {"L_MIN": 65.93, "L_MAX": 65.93, "A_MIN": 11.4, "A_MAX": 11.4,  "B_MIN": 30.85, "B_MAX": 30.85},
        "健康玫瑰色":     {"L_MIN": 68.88, "L_MAX": 68.88, "A_MIN": 9.85, "A_MAX": 9.85,  "B_MIN": 25.1,  "B_MAX": 25.1},
    }

    def _landmark_region_mask(self, connections, fill=255):
        """依 FACEMESH 連線建立凸包遮罩。"""
        indices = self._collect_landmark_indices(connections)
        mask = np.zeros((self.h, self.w), dtype=np.uint8)
        if not indices:
            return mask
        pts = np.array([self._pt(i) for i in indices], dtype=np.int32)
        cv2.fillConvexPoly(mask, cv2.convexHull(pts), fill)
        return mask

    def _bgr_mean_to_lab(self, mean_bgr):
        """BGR 平均色轉標準 LAB（L: 0~100, a/b: 以 0 為中心）。"""
        bgr_img = np.array([[[
            int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])
        ]]], dtype=np.uint8)
        lab_px = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2Lab)[0, 0]
        return (
            round(float(lab_px[0]) / 2.55, 2),
            round(float(lab_px[1]) - 128.0, 2),
            round(float(lab_px[2]) - 128.0, 2),
        )

    def _lab_mean_from_mask(self, lab_img, mask_u8):
        """遮罩區域平均 LAB，回傳標準 L/a/b。"""
        l_mean, a_mean_cv, b_mean_cv, _ = cv2.mean(lab_img, mask=mask_u8)
        return (
            float(l_mean) / 2.55,
            float(a_mean_cv - 128.0),
            float(b_mean_cv - 128.0),
        )

    def _classify_shade_12grid(self, lab_img, mask_u8):
        """依 MAC 膚色範圍分級，超出範圍時取最近色號。"""
        l_mean, a_axis, b_axis = self._lab_mean_from_mask(lab_img, mask_u8)

        matched = None
        for name, r in self._MAC_SHADE_RANGES.items():
            if (r["L_MIN"] <= l_mean <= r["L_MAX"] and
                    r["A_MIN"] <= a_axis <= r["A_MAX"] and
                    r["B_MIN"] <= b_axis <= r["B_MAX"]):
                matched = name
                break

        if matched is None:
            best_dist = float("inf")
            for name, r in self._MAC_SHADE_RANGES.items():
                lc = (r["L_MIN"] + r["L_MAX"]) / 2
                ac = (r["A_MIN"] + r["A_MAX"]) / 2
                bc = (r["B_MIN"] + r["B_MAX"]) / 2
                dist = ((l_mean - lc) ** 2 + (a_axis - ac) ** 2 + (b_axis - bc) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    matched = name

        return matched, l_mean, a_axis, b_axis

    def _classify_season(self, lab, hsv, combined_mask):
        """四季型：先判冷暖，再判亮/柔/清晰。"""
        _, s_mean, v_mean, _ = cv2.mean(hsv, mask=combined_mask)
        s_mean = float(s_mean)
        v_mean = float(v_mean)

        l_mean_cv, a_axis, b_axis = self._lab_mean_from_mask(lab, combined_mask)
        l_mean = l_mean_cv * 2.55  # 四季型規則沿用 OpenCV L 尺度

        if b_axis >= 12.0:
            undertone = "warm"
        elif b_axis <= 8.5:
            undertone = "cool"
        else:
            undertone = "neutral"

        bright = (l_mean >= 158.0) or (v_mean >= 168.0)
        soft = s_mean <= 110.0

        mask_bool = combined_mask.astype(bool)
        if np.any(mask_bool):
            v_std = float(np.std(hsv[:, :, 2][mask_bool].astype(np.float32)))
        else:
            v_std = 0.0
        clear = (v_std >= 18.0) or (s_mean >= 125.0)

        if undertone == "warm":
            return "春季" if (bright and clear) else "秋季"
        if undertone == "cool":
            return "夏季" if (bright and soft and not clear) else "冬季"
        if clear and not soft:
            return "冬季"
        if bright and soft:
            return "夏季"
        if bright:
            return "春季"
        return "秋季"

    # 膚色
    def get_skin_color(self):
        face_points = np.array([self._pt(i) for i in range(len(self.lm))], dtype=np.int32)
        face_mask = np.zeros((self.h, self.w), dtype=np.uint8)
        cv2.fillConvexPoly(face_mask, cv2.convexHull(face_points), 255)

        lip_mask = self._landmark_region_mask(self.mp_face_mesh.FACEMESH_LIPS)
        lip_L, lip_a, lip_b = self._bgr_mean_to_lab(cv2.mean(self.frame, mask=lip_mask)[:3])

        for region in (
            self.mp_face_mesh.FACEMESH_LIPS,
            self.mp_face_mesh.FACEMESH_LEFT_EYE,
            self.mp_face_mesh.FACEMESH_RIGHT_EYE,
        ):
            indices = self._collect_landmark_indices(region)
            if not indices:
                continue
            pts = np.array([self._pt(i) for i in indices], dtype=np.int32)
            cv2.fillConvexPoly(face_mask, cv2.convexHull(pts), 0)

        # 步驟5：Lab 膚色範圍過濾
        lab = cv2.cvtColor(self.frame, cv2.COLOR_BGR2Lab)
        color_mask = cv2.inRange(lab, np.array([20, 135, 130]), np.array([230, 175, 175]))

        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, kernel)
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)

        combined_mask = cv2.bitwise_and(face_mask, color_mask)
        hsv = cv2.cvtColor(self.frame, cv2.COLOR_BGR2HSV)

        season = self._classify_season(lab, hsv, combined_mask)
        shade_label, L, a, b = self._classify_shade_12grid(lab, combined_mask)
        return lip_L, lip_a, lip_b, season, shade_label, L, a, b

    # 輸出
    def export_json(self, save_path=None):
        lip_L, lip_a, lip_b, season, shade_label, L, a, b = self.get_skin_color()

        result = {
            "臉型": self.get_face_shape(),
            "眉型": self.get_eyebrow_shape(),
            "眼型": self.get_eye_shape(),
            "鼻型": self.get_nose_shape(),
            "嘴型": self.get_lip_shape(),
            "膚色": {
                "四季型": season,
                "膚色分級": shade_label,
                "LAB": {
                    "L": round(L, 2),
                    "a": round(a, 2),
                    "b": round(b, 2),
                },
            },
            "嘴唇_LAB": {
                "L": lip_L,
                "a": lip_a,
                "b": lip_b,
            },
        }

        # API 模式通常不存檔；本地 debug 才寫 json
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)

        return result

if __name__ == "__main__":
   import uvicorn

    # 本地跑
   uvicorn.run(app, host="0.0.0.0", port=8001)



    #本地單張圖測試

    #analyzer = FaceAnalyzer(r"C:\Users\isach\PycharmProjects\PythonProject12\IMG_9927.jpg")
    #result = analyzer.export_json(save_path="face_result.json")
    #print(json.dumps(result, indent=4, ensure_ascii=False))
