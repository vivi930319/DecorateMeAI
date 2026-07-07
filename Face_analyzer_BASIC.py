import cv2
import numpy as np
import mediapipe as mp
import json
import os
import uuid
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from fastapi import BackgroundTasks, FastAPI, UploadFile, HTTPException, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
import insightface
from insightface.app import FaceAnalysis as InsightFaceApp
from dev_server_utils import get_cors_origins, run_dev_server


@asynccontextmanager
async def _lifespan(_app):
    # 預熱模型，避免第一個請求額外承擔模型初始化時間。
    _get_insight()
    _get_face_mesh()
    yield
    global _face_mesh
    if _face_mesh is not None:
        _face_mesh.close()
        _face_mesh = None


app = FastAPI(title="Face Analyzer BASIC", lifespan=_lifespan)

# 啟用 CORS 允許前端跨來源存取
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

import job_store

_insight_app = None
_face_mesh = None
_COL = "face_jobs_basic"

MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "1024"))
INSIGHT_DET_SIZE = int(os.getenv("INSIGHT_DET_SIZE", "384"))
INSIGHT_ALLOWED_MODULES = [
    module.strip()
    for module in os.getenv("INSIGHT_ALLOWED_MODULES", "detection,landmark_3d_68").split(",")
    if module.strip()
]
FACE_JOB_TIMEOUT_SECONDS = int(os.getenv("FACE_JOB_TIMEOUT_SECONDS", "180"))

# ─── 亮度增強 ───────────────────────────────────────────────────────────────
BRIGHTNESS_LOW_THRESHOLD = float(os.getenv("BRIGHTNESS_LOW_THRESHOLD", "70"))
BRIGHTNESS_GAMMA         = float(os.getenv("BRIGHTNESS_GAMMA", "0.65"))
_BRIGHTNESS_LUT = np.array([int(255 * (i / 255.0) ** BRIGHTNESS_GAMMA) for i in range(256)], dtype=np.uint8)


def _measure_brightness(frame_bgr: np.ndarray) -> float:
    """回傳影像 HSV V 通道的平均值（0–255）作為亮度指標。"""
    return float(np.mean(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)[:, :, 2]))


def _enhance_brightness_auto(frame_bgr: np.ndarray, gamma: float = 0.65) -> np.ndarray:
    """Gamma 校正提亮中間調（皮膚色調），自然不過曝；gamma < 1 越小越亮。"""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    lut = _BRIGHTNESS_LUT if abs(gamma - BRIGHTNESS_GAMMA) < 1e-6 else np.array([int(255 * (i / 255.0) ** gamma) for i in range(256)], dtype=np.uint8)
    return cv2.cvtColor(cv2.merge([lut[l], a, b]), cv2.COLOR_LAB2BGR)


def _enhance_brightness_manual(frame_bgr: np.ndarray, level: float) -> np.ndarray:
    """將 HSV V 通道乘以 level（>1 提亮，<1 調暗），結果限制在 0–255。"""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * level, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
FACE_JOB_RETENTION_SECONDS = int(os.getenv("FACE_JOB_RETENTION_SECONDS", "3600"))
FACE_JOB_MAX_COUNT = int(os.getenv("FACE_JOB_MAX_COUNT", "200"))
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5500")

def _get_insight():
    global _insight_app
    if _insight_app is None:
        _insight_app = InsightFaceApp(
            name="buffalo_l",
            root="/app/.insightface",
            allowed_modules=INSIGHT_ALLOWED_MODULES or None,
            providers=["CPUExecutionProvider"]
        )
        _insight_app.prepare(ctx_id=-1, det_size=(INSIGHT_DET_SIZE, INSIGHT_DET_SIZE))
    return _insight_app


def _get_face_mesh():
    """共用 MediaPipe FaceMesh，避免每次分析都重新建立模型造成越跑越慢。"""
    global _face_mesh
    if _face_mesh is None:
        _face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            min_detection_confidence=0.5
        )
    return _face_mesh

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url=FRONTEND_URL, status_code=307)


@app.get("/health")
async def health():
    _cleanup_jobs()
    return {
        "status": "ok",
        "service": "face-analyzer-basic",
        "jobs": _job_stats(),
        "limits": {
            "timeoutSeconds": FACE_JOB_TIMEOUT_SECONDS,
            "retentionSeconds": FACE_JOB_RETENTION_SECONDS,
            "maxCount": FACE_JOB_MAX_COUNT,
        },
    }


@app.post("/analyze")
@app.post("/v1/face/analyze/basic")
async def analyze(
    file: UploadFile = File(...),
    brightness_mode: str  = Form("none"),
    brightness_level: float = Form(1.0),
):
    # BASIC 同時支援「檔案上傳」與「拍照上傳」：
    # 前端檔案 input 直接送 File；相機拍照則把 canvas/blob 包成 File 後送到同一個欄位。
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="上傳檔案是空的")
    if brightness_mode not in {"none", "auto", "manual"}:
        raise HTTPException(status_code=400, detail="brightness_mode 必須為 none / auto / manual")
    if not (0.1 <= brightness_level <= 5.0):
        raise HTTPException(status_code=400, detail="brightness_level 必須在 0.1 ~ 5.0 之間")
    try:
        analyzer = FaceAnalyzer(contents, brightness_mode=brightness_mode, brightness_level=brightness_level)
        result = analyzer.export_json()
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _detect_pose(contents: bytes):
    frame = cv2.imdecode(np.frombuffer(contents, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise FileNotFoundError("圖片讀取失敗")

    h0, w0 = frame.shape[:2]
    scale = MAX_IMAGE_SIZE / max(h0, w0)
    if scale < 1:
        frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    faces = _get_insight().get(rgb)
    if not faces:
        raise ValueError("沒偵測到人臉")

    face = max(faces, key=lambda f: f.det_score)
    if not hasattr(face, "pose") or face.pose is None:
        raise ValueError("無法取得臉部角度")

    yaw = float(face.pose[0])
    pitch = float(face.pose[1])
    roll = float(face.pose[2]) if len(face.pose) > 2 else 0.0
    abs_yaw = abs(yaw)
    if abs_yaw <= 8 and abs(pitch) <= 12:
        capture_role = "front"
    elif abs_yaw >= 10:
        capture_role = "side"
    elif abs_yaw >= 6:
        capture_role = "angle45"
    else:
        capture_role = "turning"

    return {
        "yaw": round(yaw, 2),
        "pitch": round(pitch, 2),
        "roll": round(roll, 2),
        "captureRole": capture_role,
        "side": "left" if yaw < 0 else "right",
        "confidence": round(float(face.det_score), 4),
    }


@app.post("/v1/face/pose")
async def detect_pose(file: UploadFile = File(...)):
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="上傳檔案是空的")
    try:
        return _detect_pose(contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _seconds_since(value, now):
    dt = _parse_iso(value)
    if not dt:
        return None
    return (now - dt).total_seconds()


def _cleanup_jobs():
    now = datetime.now(timezone.utc)
    jobs = job_store.all_jobs(_COL)
    to_delete = []
    for job in jobs:
        job_id = job.get("jobId")
        status = job.get("status")
        if status in {"queued", "processing"}:
            anchor = job.get("startedAt") or job.get("createdAt")
            age = _seconds_since(anchor, now)
            if age is not None and age > FACE_JOB_TIMEOUT_SECONDS:
                job_store.patch(_COL, job_id, {
                    "status": "failed", "stage": "timeout",
                    "completedAt": _now_iso(),
                    "error": {"message": f"臉部分析逾時，已超過 {FACE_JOB_TIMEOUT_SECONDS} 秒"},
                })
        elif status in {"completed", "failed"}:
            age = _seconds_since(job.get("completedAt"), now)
            if age is not None and age > FACE_JOB_RETENTION_SECONDS:
                to_delete.append(job_id)
    for job_id in to_delete:
        job_store.delete(_COL, job_id)
    remaining = job_store.all_jobs(_COL)
    if len(remaining) > FACE_JOB_MAX_COUNT:
        ordered = sorted(remaining, key=lambda j: j.get("createdAt") or "")
        for job in ordered[: len(remaining) - FACE_JOB_MAX_COUNT]:
            job_store.delete(_COL, job.get("jobId"))


def _job_stats():
    jobs = job_store.all_jobs(_COL)
    stats = {"total": len(jobs), "queued": 0, "processing": 0, "completed": 0, "failed": 0}
    for job in jobs:
        status = job.get("status")
        if status in stats:
            stats[status] += 1
    return stats


def _job_view(job):
    return {k: v for k, v in job.items() if k != "result"}


def _run_basic_job(job_id, contents, brightness_mode="none", brightness_level=1.0):
    job_store.patch(_COL, job_id, {"status": "processing", "stage": "face_analysis", "progress": 35, "startedAt": _now_iso()})
    try:
        result = FaceAnalyzer(contents, brightness_mode=brightness_mode, brightness_level=brightness_level).export_json()
        job_store.patch(_COL, job_id, {
            "status": "completed", "stage": "done", "progress": 100,
            "completedAt": _now_iso(), "result": result, "error": None,
        })
    except Exception as e:
        job_store.patch(_COL, job_id, {
            "status": "failed", "stage": "failed",
            "completedAt": _now_iso(), "error": {"message": str(e)},
        })


@app.post("/v1/face/jobs/basic")
async def create_basic_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    brightness_mode: str   = Form("none"),
    brightness_level: float = Form(1.0),
):
    _cleanup_jobs()
    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail={"error": {"message": "上傳檔案是空的"}})
    if brightness_mode not in {"none", "auto", "manual"}:
        raise HTTPException(status_code=400, detail={"error": {"message": "brightness_mode 必須為 none / auto / manual"}})
    if not (0.1 <= brightness_level <= 5.0):
        raise HTTPException(status_code=400, detail={"error": {"message": "brightness_level 必須在 0.1 ~ 5.0 之間"}})
    job_id = f"JOB-{uuid.uuid4().hex[:12]}"
    job_data = {
        "jobId": job_id, "analysisPackageId": None, "status": "queued",
        "progress": 0, "stage": "upload", "createdAt": _now_iso(),
        "startedAt": None, "completedAt": None, "error": None, "result": None,
    }
    job_store.create(_COL, job_id, job_data)
    background_tasks.add_task(_run_basic_job, job_id, contents, brightness_mode, brightness_level)
    return _job_view(job_data)


@app.get("/v1/face/jobs/{job_id}")
async def get_basic_job(job_id: str):
    job = job_store.get(_COL, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    return _job_view(job)


@app.get("/v1/face/jobs/{job_id}/result")
async def get_basic_job_result(job_id: str):
    job = job_store.get(_COL, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail={"error": {"message": "job 尚未完成", "status": job["status"]}})
    return {
        "jobId": job_id,
        "analysisPackageId": job["analysisPackageId"],
        "status": "completed",
        "result": job["result"],
    }


class FaceAnalyzer:
    YAW_LIMIT   = 18.0
    PITCH_LIMIT = 15.0

    def __init__(self, image_input, strict_angle=True, brightness_mode="none", brightness_level=1.0, require_insight=True):
        if isinstance(image_input, str):
            self.frame = cv2.imdecode(np.fromfile(image_input, dtype=np.uint8), cv2.IMREAD_COLOR)
        elif isinstance(image_input, bytes):
            self.frame = cv2.imdecode(np.frombuffer(image_input, np.uint8), cv2.IMREAD_COLOR)
        else:
            raise ValueError("image_input 只接受 str 或 bytes")

        if self.frame is None:
            raise FileNotFoundError("圖片讀取失敗")

        # 手機原圖通常很大，先等比例縮小可以明顯加快 InsightFace / MediaPipe。
        h0, w0 = self.frame.shape[:2]
        scale = MAX_IMAGE_SIZE / max(h0, w0)
        if scale < 1:
            self.frame = cv2.resize(
                self.frame,
                (int(w0 * scale), int(h0 * scale)),
                interpolation=cv2.INTER_AREA
            )

        # ── 亮度增強（在特徵分析前處理）──────────────────────────────────
        self.brightness_info: dict = {
            "mode": brightness_mode,
            "originalBrightness": None,
            "enhanced": False,
            "enhancedBrightness": None,
        }
        if brightness_mode != "none":
            original_brightness = _measure_brightness(self.frame)
            self.brightness_info["originalBrightness"] = round(original_brightness, 1)
            if brightness_mode == "auto" and original_brightness < BRIGHTNESS_LOW_THRESHOLD:
                self.frame = _enhance_brightness_auto(self.frame, BRIGHTNESS_GAMMA)
                self.brightness_info["enhanced"] = True
                self.brightness_info["enhancedBrightness"] = round(_measure_brightness(self.frame), 1)
            elif brightness_mode == "manual" and abs(brightness_level - 1.0) > 0.01:
                self.frame = _enhance_brightness_manual(self.frame, brightness_level)
                self.brightness_info["enhanced"] = True
                self.brightness_info["enhancedBrightness"] = round(_measure_brightness(self.frame), 1)

        self.h, self.w, _ = self.frame.shape
        rgb = cv2.cvtColor(self.frame, cv2.COLOR_BGR2RGB)

        # Step 1：InsightFace 正臉驗證
        if require_insight:
            insight = _get_insight()
            faces = insight.get(rgb)

            if not faces:
                raise ValueError("沒偵測到人臉")

            face = max(faces, key=lambda f: f.det_score)

            if strict_angle and hasattr(face, "pose") and face.pose is not None:
                yaw, pitch = float(face.pose[0]), float(face.pose[1])
                if abs(yaw) > self.YAW_LIMIT or abs(pitch) > self.PITCH_LIMIT:
                    raise ValueError(f"請上傳正面照片（偏角：yaw={yaw:.1f}°, pitch={pitch:.1f}°）")

        # Step 2：MediaPipe FaceMesh
        mp_face_mesh = mp.solutions.face_mesh
        face_mesh = _get_face_mesh()
        results = face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            raise ValueError("沒偵測到人臉")

        self.lm             = results.multi_face_landmarks[0].landmark
        self.face_landmarks = results.multi_face_landmarks[0]
        self.mp_face_mesh   = mp_face_mesh
        self._pts_cache = np.array(
            [[int(lm.x * self.w), int(lm.y * self.h)] for lm in self.lm],
            dtype=np.int32,
        )
        self._landmark_indices_cache = {}

    def _pt(self, index):
        return self._pts_cache[index].copy()

    def _dist(self, a, b):
        return float(np.linalg.norm(self._pt(a) - self._pt(b)))

    def _collect_landmark_indices(self, connections_or_indices):
        if not connections_or_indices:
            return []
        cache_key = id(connections_or_indices)
        cached = self._landmark_indices_cache.get(cache_key)
        if cached is not None:
            return cached
        seq = list(connections_or_indices)
        if not seq:
            return []
        first = seq[0]
        if isinstance(first, (tuple, list)) and len(first) >= 2:
            s = set()
            for a, b in seq:
                s.add(int(a)); s.add(int(b))
            result = sorted(s)
        else:
            result = sorted({int(x) for x in seq})
        self._landmark_indices_cache[cache_key] = result
        return result

    def _align_points_by_eyes(self, points_xy):
        left_eye  = self._pt(33).astype(np.float32)
        right_eye = self._pt(263).astype(np.float32)
        pivot     = (left_eye + right_eye) / 2.0
        dx = float(right_eye[0] - left_eye[0])
        dy = float(right_eye[1] - left_eye[1])
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return points_xy
        angle = np.arctan2(dy, dx)
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

    def get_face_shape(self, debug=False):
        oval_indices = self._collect_landmark_indices(self.mp_face_mesh.FACEMESH_FACE_OVAL)
        if len(oval_indices) < 5:
            face_width      = self._dist(234, 454)
            forehead_width  = self._dist(103, 332)
            cheekbone_width = self._dist(123, 352)
            jaw_width       = self._dist(132, 361)
            face_height     = self._dist(10, 152)
        else:
            oval_pts     = np.array([self._pt(i) for i in oval_indices], dtype=np.float32)
            oval_pts_rot = self._align_points_by_eyes(oval_pts)
            p10r  = self._align_points_by_eyes(self._pt(10).astype(np.float32)[None, :])[0]
            p152r = self._align_points_by_eyes(self._pt(152).astype(np.float32)[None, :])[0]
            face_height = float(abs(p152r[1] - p10r[1]))

            if face_height < 1e-6:
                return "未知"

            y_min = float(np.min(oval_pts_rot[:, 1]))

            def width_at(level):
                y_level = y_min + face_height * level
                tol = face_height * 0.05
                sel = np.abs(oval_pts_rot[:, 1] - y_level) < tol
                if int(np.sum(sel)) < 2:
                    tol = face_height * 0.08
                    sel = np.abs(oval_pts_rot[:, 1] - y_level) < tol
                if int(np.sum(sel)) < 2:
                    return None
                return float(np.max(oval_pts_rot[sel, 0]) - np.min(oval_pts_rot[sel, 0]))

            widths = [w for lv in np.linspace(0.15, 0.90, 20) if (w := width_at(float(lv))) is not None and w > 0]

            if not widths:
                face_width      = self._dist(234, 454)
                forehead_width  = self._dist(103, 332)
                cheekbone_width = self._dist(123, 352)
                jaw_width       = self._dist(132, 361)
            else:
                face_width      = float(max(widths))
                forehead_width  = width_at(0.25) or self._dist(103, 332)
                cheekbone_width = width_at(0.50) or self._dist(123, 352)
                # 0.80 太接近下巴，會把一般臉誤判成額頭寬、下顎窄的心形臉。
                jaw_samples = [width_at(level) for level in (0.66, 0.70, 0.74)]
                jaw_samples = [w for w in jaw_samples if w is not None and w > 0]
                jaw_width   = float(np.median(jaw_samples)) if jaw_samples else self._dist(132, 361)

        if face_width < 1e-6 or jaw_width < 1e-6:
            return "未知"

        hw = round(face_height / face_width, 3)
        max_w = max(forehead_width, cheekbone_width, jaw_width)
        fw_n  = forehead_width / max_w
        cw_n  = cheekbone_width / max_w
        jw_n  = jaw_width / max_w
        jaw_to_forehead = jaw_width / forehead_width if forehead_width > 1e-6 else 1.0
        forehead_to_jaw = forehead_width / jaw_width
        cheek_to_jaw    = cheekbone_width / jaw_width
        forehead_to_cheek = forehead_width / cheekbone_width if cheekbone_width > 1e-6 else 1.0
        chin_width      = self._dist(150, 379)
        chin_to_jaw     = chin_width / jaw_width if jaw_width > 1e-6 else 1.0
        all_similar = fw_n > 0.88 and jw_n > 0.88

        if all_similar:
            if hw >= 1.35: return "長形臉"
            elif hw < 1.16: return "方形臉"
            elif jw_n > 0.96 and jaw_to_forehead >= 0.98: return "方形臉"
            else: return "鵝蛋臉"

        # 心形臉從正面很容易被髮際線、瀏海、鏡頭距離放大誤判，因此只在特徵非常明顯時輸出。
        is_heart = (
            forehead_to_jaw >= 1.28
            and forehead_to_cheek >= 1.03
            and cheek_to_jaw >= 1.18
            and fw_n >= 0.97
            and jw_n <= 0.78
            and chin_to_jaw <= 0.64
            and 1.05 <= hw < 1.38
        )
        if is_heart:
            return "心形臉"

        if jaw_width >= cheekbone_width and jaw_width > forehead_width * 1.16:
            return "方形臉" if hw < 1.25 else "梯形臉"

        if cheekbone_width >= forehead_width and cheekbone_width >= jaw_width:
            # 菱形臉也容易被下顎取樣高度影響，改成顴骨與上下寬度差距都很明顯才判。
            if fw_n < 0.78 and jw_n < 0.78 and cheek_to_jaw >= 1.20: return "菱形臉"
            if hw < 1.16: return "圓形臉"
            if hw >= 1.35: return "長形臉"
            if 1.16 <= hw <= 1.45 and jw_n >= 0.76: return "鵝蛋臉"

        if hw >= 1.35: return "長形臉"
        elif hw < 1.16: return "圓形臉"
        else: return "鵝蛋臉"

    def get_eyebrow_shape(self):
        # 用眉毛輪廓 5 點的最高點（min-y）作為弓頂，而非固定骨架點 105/334（眉骨脊）。
        # 骨架點測量骨骼結構，輪廓點測量實際可見眉形，閾值以 CelebA 100 張分位數校正。
        _L_BROW = (46, 53, 52, 65, 55)   # 左眉輪廓，外→內
        _R_BROW = (276, 283, 282, 295, 285)  # 右眉輪廓，外→內

        def brow_metrics(outer_idx, inner_idx, outline):
            head = self._pt(outer_idx).astype(np.float32)
            tail = self._pt(inner_idx).astype(np.float32)
            width = float(np.linalg.norm(tail - head))
            if width < 1e-6:
                return 0.0, 0.0
            pts = np.array([self._pt(i) for i in outline], dtype=np.float32)
            peak_y   = float(np.min(pts[:, 1]))          # 輪廓最高點
            base_y   = (float(head[1]) + float(tail[1])) / 2.0
            arch_ratio = (base_y - peak_y) / width
            tail_ratio = (float(head[1]) - float(tail[1])) / width
            return arch_ratio, tail_ratio

        left_arch, left_tail   = brow_metrics(46, 55, _L_BROW)
        right_arch, right_tail = brow_metrics(276, 285, _R_BROW)
        arch_ratio = (left_arch + right_arch) / 2.0
        tail_ratio = (left_tail + right_tail) / 2.0

        if tail_ratio > 0.100:                               return "落尾眉"
        if arch_ratio < 0.115 and abs(tail_ratio) < 0.080: return "一字眉"
        if arch_ratio > 0.155 and abs(tail_ratio) < 0.115: return "彎月眉"
        return "彎月眉"

    def _eye_side_metrics(self, inner_idx, outer_idx, upper_ids, lower_idx, brow_ids):
        inner = self._pt(inner_idx).astype(np.float32)
        outer = self._pt(outer_idx).astype(np.float32)
        upper = np.array([self._pt(i) for i in upper_ids], dtype=np.float32)
        lower = self._pt(lower_idx).astype(np.float32)
        brows = np.array([self._pt(i) for i in brow_ids], dtype=np.float32)

        eye_width  = float(np.linalg.norm(outer - inner))
        lid_center = upper.mean(axis=0)
        eye_height = float(np.linalg.norm(lid_center - lower))
        ear        = eye_height / eye_width if eye_width > 0 else 0.0

        aligned = self._align_points_by_eyes(np.array([outer, inner], dtype=np.float32))
        outer_a, inner_a = (aligned[0], aligned[1]) if aligned[0][0] <= aligned[1][0] else (aligned[1], aligned[0])
        dx    = float(inner_a[0] - outer_a[0])
        dy    = float(inner_a[1] - outer_a[1])
        angle = float(np.degrees(np.arctan2(dy, dx))) if dx > 1e-6 else 0.0

        brow_y     = float(np.mean(brows[:, 1]))
        lid_y      = float(np.mean(upper[:, 1]))
        lid_spread = float(np.max(upper[:, 1]) - np.min(upper[:, 1]))
        lid_curve  = lid_spread / eye_height if eye_height > 0 else 0.0

        return {"eye_width": eye_width, "eye_height": eye_height, "ear": ear, "angle": angle, "brow_gap": max(0.0, lid_y - brow_y), "lid_curve": lid_curve}

    def get_eye_shape(self, debug=False):
        face_width = self._dist(234, 454)
        if face_width < 1e-6: return "未知"

        left = self._eye_side_metrics(133, 33, (157,158,159,160,161), 145, (46,53,52,65,55))
        left["angle"] = -left["angle"]  # left eye's outer-to-inner direction is mirrored vs right eye
        right = self._eye_side_metrics(362, 263, (385,386,387,388,398), 374, (276,283,282,295,285))

        eye_width = (left["eye_width"] + right["eye_width"]) / 2.0
        if eye_width < 1e-6: return "未知"

        ear           = (left["ear"]   + right["ear"])   / 2.0
        angle         = (left["angle"] + right["angle"]) / 2.0
        ratio_to_face = eye_width / face_width

        if ratio_to_face < 0.12: return "瞇縫眼"
        elif angle > 6: return "下垂眼"
        elif ear > 0.40: return "圓眼"
        elif ear < 0.20: return "細長眼"
        elif ear <= 0.24:
            return "丹鳳眼" if angle < -2 else "細長眼"
        elif ear <= 0.35:
            if angle < -1 and ratio_to_face > 0.16: return "桃花眼"
            elif angle > 3: return "下垂眼"
            else: return "杏仁眼"
        else:
            return "桃花眼" if angle < -1 else "圓眼"

    def get_nose_shape(self):
        nose_width  = self._dist(129, 358)
        face_width  = self._dist(234, 454)

        if face_width < 1e-6:
            return "未知"

        ratio_width = nose_width / face_width

        # 正面照只能穩定估鼻翼相對寬窄；鼻樑高度、鷹勾、塌鼻、朝天鼻需要側面或深度資訊。
        if ratio_width >= 0.325: return "寬鼻"
        if ratio_width <= 0.205: return "窄鼻"
        return "標準鼻"

    def get_lip_shape(self):
        lip_width  = self._dist(61, 291)
        lip_height = self._dist(0, 17)
        ratio      = lip_height / lip_width

        peak_left_y  = self._pt(37)[1]
        peak_right_y = self._pt(267)[1]
        center_y     = self._pt(0)[1]
        m_diff       = center_y - (peak_left_y + peak_right_y) / 2

        corner_avg_y = (self._pt(61)[1] + self._pt(291)[1]) / 2
        smile_diff   = center_y - corner_avg_y

        m_diff_ratio     = m_diff     / lip_width if lip_width > 1e-6 else 0
        smile_diff_ratio = smile_diff / lip_width if lip_width > 1e-6 else 0

        if ratio > 0.4:                    return "厚唇"
        elif ratio < 0.25:                 return "薄唇"
        elif m_diff_ratio > 0.06:          return "M型唇"
        elif smile_diff_ratio < -0.04:     return "微笑唇"
        else:                              return "花瓣唇"

    _MAC_SHADE_RANGES = {
        "白皙自然色":     {"L_MIN": 73.2,  "L_MAX": 80.54, "A_MIN": 5.12, "A_MAX": 9.96,  "B_MIN": 15.58, "B_MAX": 22.67},
        "中等亮白自然色": {"L_MIN": 69.26, "L_MAX": 77.82, "A_MIN": 7.41, "A_MAX": 8.61,  "B_MIN": 17.1,  "B_MAX": 19.59},
        "白皙象牙色":     {"L_MIN": 80.54, "L_MAX": 85.37, "A_MIN": 2.65, "A_MAX": 5.12,  "B_MIN": 15.03, "B_MAX": 15.58},
        "自然象牙":       {"L_MIN": 68.88, "L_MAX": 82.99, "A_MIN": 2.97, "A_MAX": 9.85,  "B_MIN": 19.55, "B_MAX": 25.1},
        "健康象牙":       {"L_MIN": 65.32, "L_MAX": 76.37, "A_MIN": 7.16, "A_MAX": 9.05,  "B_MIN": 23.08, "B_MAX": 28.86},
        "古銅象牙":       {"L_MIN": 62.5,  "L_MAX": 69.5,  "A_MIN": 9.5,  "A_MAX": 13.5, "B_MIN": 27.5,  "B_MAX": 34.5},
        "健康玫瑰色":     {"L_MIN": 65.5,  "L_MAX": 72.5,  "A_MIN": 8.0,  "A_MAX": 11.5, "B_MIN": 22.0,  "B_MAX": 28.0},
    }

    def _landmark_region_mask(self, connections, fill=255):
        indices = self._collect_landmark_indices(connections)
        mask    = np.zeros((self.h, self.w), dtype=np.uint8)
        if not indices: return mask
        pts = np.array([self._pt(i) for i in indices], dtype=np.int32)
        cv2.fillConvexPoly(mask, cv2.convexHull(pts), fill)
        return mask

    def _landmark_poly_mask(self, indices, fill=255):
        mask = np.zeros((self.h, self.w), dtype=np.uint8)
        pts = []
        for idx in indices:
            if 0 <= idx < len(self.lm):
                pts.append(self._pt(idx))
        if len(pts) < 3:
            return mask
        cv2.fillConvexPoly(mask, cv2.convexHull(np.array(pts, dtype=np.int32)), fill)
        return mask

    def _bgr_mean_to_lab(self, mean_bgr):
        bgr_img = np.array([[[int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])]]], dtype=np.uint8)
        lab_px  = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2Lab)[0, 0]
        return (round(float(lab_px[0]) / 2.55, 2), round(float(lab_px[1]) - 128.0, 2), round(float(lab_px[2]) - 128.0, 2))

    def _lab_mean_from_mask(self, lab_img, mask_u8):
        l_mean, a_mean_cv, b_mean_cv, _ = cv2.mean(lab_img, mask=mask_u8)
        return (float(l_mean) / 2.55, float(a_mean_cv - 128.0), float(b_mean_cv - 128.0))

    def _lab_robust_from_mask(self, lab_img, mask_u8):
        pixels = lab_img[mask_u8 > 0]
        if pixels.size == 0:
            return self._lab_mean_from_mask(lab_img, mask_u8)

        l_vals = pixels[:, 0].astype(np.float32) / 2.55
        a_vals = pixels[:, 1].astype(np.float32) - 128.0
        b_vals = pixels[:, 2].astype(np.float32) - 128.0

        # Remove hard shadows and glossy highlights before averaging skin tone.
        l_low, l_high = np.percentile(l_vals, [18, 82])
        keep = (l_vals >= l_low) & (l_vals <= l_high)
        if int(np.count_nonzero(keep)) >= 80:
            l_vals, a_vals, b_vals = l_vals[keep], a_vals[keep], b_vals[keep]

        med = np.array([np.median(l_vals), np.median(a_vals), np.median(b_vals)], dtype=np.float32)
        dist = np.sqrt((l_vals - med[0]) ** 2 + (a_vals - med[1]) ** 2 + (b_vals - med[2]) ** 2)
        cutoff = np.percentile(dist, 85)
        keep = dist <= cutoff
        if int(np.count_nonzero(keep)) >= 80:
            l_vals, a_vals, b_vals = l_vals[keep], a_vals[keep], b_vals[keep]

        return (float(np.median(l_vals)), float(np.median(a_vals)), float(np.median(b_vals)))

    def _classify_shade_12grid(self, lab_img, mask_u8):
        l_mean, a_axis, b_axis = self._lab_robust_from_mask(lab_img, mask_u8)
        matched = None
        for name, r in self._MAC_SHADE_RANGES.items():
            if (r["L_MIN"] <= l_mean <= r["L_MAX"] and r["A_MIN"] <= a_axis <= r["A_MAX"] and r["B_MIN"] <= b_axis <= r["B_MAX"]):
                matched = name; break
        if matched is None:
            best_dist = float("inf")
            for name, r in self._MAC_SHADE_RANGES.items():
                lc   = (r["L_MIN"] + r["L_MAX"]) / 2
                ac   = (r["A_MIN"] + r["A_MAX"]) / 2
                bc   = (r["B_MIN"] + r["B_MAX"]) / 2
                dist = ((l_mean-lc)**2 + (a_axis-ac)**2 + (b_axis-bc)**2) ** 0.5
                if dist < best_dist: best_dist = dist; matched = name
        return matched, l_mean, a_axis, b_axis

    def _classify_season(self, lab, hsv, combined_mask):
        _, s_mean, v_mean, _ = cv2.mean(hsv, mask=combined_mask)
        s_mean = float(s_mean); v_mean = float(v_mean)
        l_mean, a_axis, b_axis = self._lab_robust_from_mask(lab, combined_mask)
        l_mean_cv = l_mean * 2.55

        undertone = "warm" if b_axis >= 12.0 else "cool" if b_axis <= 8.5 else "neutral"
        bright    = (l_mean_cv >= 158.0) or (v_mean >= 168.0)
        soft      = s_mean <= 110.0
        mask_bool = combined_mask.astype(bool)
        v_std     = float(np.std(hsv[:,:,2][mask_bool].astype(np.float32))) if np.any(mask_bool) else 0.0
        clear     = (v_std >= 18.0) or (s_mean >= 125.0)

        if undertone == "warm": return "春季" if (bright and clear) else "秋季"
        if undertone == "cool": return "夏季" if (bright and soft and not clear) else "冬季"
        if clear and not soft:  return "冬季"
        if bright and soft:     return "夏季"
        if bright:              return "春季"
        return "秋季"

    def get_skin_color(self):
        face_points = np.array([self._pt(i) for i in range(len(self.lm))], dtype=np.int32)
        face_mask   = np.zeros((self.h, self.w), dtype=np.uint8)
        cv2.fillConvexPoly(face_mask, cv2.convexHull(face_points), 255)

        # Cheek-side sampling is more stable than averaging the whole face:
        # it avoids forehead shine, jaw shadows, hairline, brows, lips, and background bleed.
        cheek_mask = cv2.bitwise_or(
            self._landmark_poly_mask([50, 101, 118, 117, 123, 205, 187, 147, 177, 137]),
            self._landmark_poly_mask([280, 330, 347, 346, 352, 425, 411, 376, 401, 366]),
        )
        sample_mask = cheek_mask if cv2.countNonZero(cheek_mask) >= 180 else face_mask.copy()

        lip_mask = self._landmark_region_mask(self.mp_face_mesh.FACEMESH_LIPS)
        lip_L, lip_a, lip_b = self._bgr_mean_to_lab(cv2.mean(self.frame, mask=lip_mask)[:3])

        for region in (self.mp_face_mesh.FACEMESH_LIPS, self.mp_face_mesh.FACEMESH_LEFT_EYE, self.mp_face_mesh.FACEMESH_RIGHT_EYE):
            indices = self._collect_landmark_indices(region)
            if not indices: continue
            pts = np.array([self._pt(i) for i in indices], dtype=np.int32)
            cv2.fillConvexPoly(face_mask, cv2.convexHull(pts), 0)
            cv2.fillConvexPoly(sample_mask, cv2.convexHull(pts), 0)

        lab        = cv2.cvtColor(self.frame, cv2.COLOR_BGR2Lab)
        hsv        = cv2.cvtColor(self.frame, cv2.COLOR_BGR2HSV)
        ycrcb      = cv2.cvtColor(self.frame, cv2.COLOR_BGR2YCrCb)

        lab_skin   = cv2.inRange(lab,   np.array([35, 130, 124]), np.array([235, 178, 184]))
        hsv_skin   = cv2.inRange(hsv,   np.array([0,  12,  35]),  np.array([35, 175, 245]))
        ycc_skin   = cv2.inRange(ycrcb, np.array([35, 128,  72]), np.array([245, 185, 142]))
        color_mask = cv2.bitwise_and(lab_skin, cv2.bitwise_or(hsv_skin, ycc_skin))
        kernel     = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN,  kernel)
        color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)

        combined_mask = cv2.bitwise_and(sample_mask, color_mask)
        if cv2.countNonZero(combined_mask) < 100 and sample_mask is not face_mask:
            combined_mask = cv2.bitwise_and(face_mask, color_mask)
        if cv2.countNonZero(combined_mask) < 100:
            raise ValueError("膚色區域不足，請使用光線均勻、臉部清楚的正面照片")

        season               = self._classify_season(lab, hsv, combined_mask)
        shade_label, L, a, b = self._classify_shade_12grid(lab, combined_mask)
        return lip_L, lip_a, lip_b, season, shade_label, L, a, b

    def get_face_symmetry(self):
        """
        用 MediaPipe landmarks 計算臉部左右對稱分數（0-100，100 = 完全對稱）。
        測量三項指標：雙眼開合比、鼻尖偏移、嘴角對稱。
        """
        try:
            fl = self._pt(234)   # 左臉邊緣
            fr = self._pt(454)   # 右臉邊緣
            fw = float(fr[0] - fl[0])
            if fw <= 0:
                return None
            mid_x = (float(fl[0]) + float(fr[0])) / 2.0

            # 鼻尖偏移（相對臉寬）
            nose_dev = min(1.0, abs(float(self._pt(4)[0]) - mid_x) / fw * 4)

            # 雙眼開合高度比
            lh = abs(float(self._pt(159)[1]) - float(self._pt(145)[1]))  # 左眼
            rh = abs(float(self._pt(386)[1]) - float(self._pt(374)[1]))  # 右眼
            eye_ratio = min(lh, rh) / max(lh, rh) if max(lh, rh) > 0 else 1.0

            # 嘴角對稱性
            ml_dist = abs(float(self._pt(61)[0]) - mid_x)
            mr_dist = abs(float(self._pt(291)[0]) - mid_x)
            mouth_sym = min(ml_dist, mr_dist) / max(ml_dist, mr_dist) if max(ml_dist, mr_dist) > 0 else 1.0

            score = int(round(eye_ratio * 50 + (1.0 - nose_dev) * 30 + mouth_sym * 20))
            return {
                "score": max(0, min(100, score)),
                "eyeOpenRatio": round(eye_ratio, 3),
                "noseDeviation": round(abs(float(self._pt(4)[0]) - mid_x) / fw, 3),
                "mouthSymmetry": round(mouth_sym, 3),
            }
        except Exception:
            return None

    def export_json(self, save_path=None):
        lip_L, lip_a, lip_b, season, shade_label, L, a, b = self.get_skin_color()
        result = {
            "分析版本": "BASIC",
            "臉型": self.get_face_shape(),
            "眉型": self.get_eyebrow_shape(),
            "眼型": self.get_eye_shape(),
            "鼻型": self.get_nose_shape(),
            "嘴型": self.get_lip_shape(),
            "膚色": {
                "四季型":   season,
                "膚色分級": shade_label,
                "LAB": {"L": float(round(L,2)), "a": float(round(a,2)), "b": float(round(b,2))},
            },
            "嘴唇_LAB": {"L": float(lip_L), "a": float(lip_a), "b": float(lip_b)},
            "臉部對稱性": self.get_face_symmetry(),
            "brightnessEnhancement": self.brightness_info,
        }
        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
        return result


if __name__ == "__main__":
    run_dev_server(app, service_name="Face Analyzer BASIC", env_prefix="FACE_BASIC", default_port=8001)
