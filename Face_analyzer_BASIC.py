import cv2
import numpy as np
import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp
import json
import os
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
from threading import Lock
from fastapi import BackgroundTasks, FastAPI, UploadFile, HTTPException, File, Form, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from insightface.app import FaceAnalysis as InsightFaceApp
import basic_roi_shadow
import basic_rule_trees
from api_errors import (
    enforce_service_api_key,
    error_payload,
    install_api_error_handling,
    secret_equals,
)
from dev_server_utils import get_cors_origins, run_dev_server
from image_safety import sanitize_image_bytes, sanitize_upload

# Cloud Run 上 root logger 預設是 WARNING，logger.info 會被整個丟掉。
# ROI shadow 的「規則式 vs 模型」對照就是 INFO 等級 —— 少了這行，shadow 照樣消耗 CPU，
# 但比較資料一筆都不會進 Cloud Logging，等於白跑。
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def _lifespan(_app):
    # 預熱模型，避免第一個請求額外承擔模型初始化時間。
    _get_insight()
    with _face_mesh_lock:
        _get_face_mesh()
    yield
    global _face_mesh
    with _face_mesh_lock:
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

# 分析端點加 API key，擋掉直接掃 Cloud Run URL 濫用運算資源。
# /health、根路徑、CORS preflight(OPTIONS) 一律放行。
#
# 缺金鑰就「拒絕啟動」（fail closed），本機要免驗證只能明確設 ALLOW_INSECURE_LOCAL_DEV=1（P0-7）。
# 檢查掛在啟動流程（見 enforce_service_api_key），不是 import 時——本模組同時被
# 離線訓練／標註工具當函式庫 import，import 就炸會把那些工具一起弄壞。
FACE_API_KEY = os.getenv("FACE_API_KEY", "")
enforce_service_api_key(app, "FACE_API_KEY")
_API_KEY_OPEN_PATHS = {"/health", "/"}


@app.middleware("http")
async def _api_key_guard(request, call_next):
    if (FACE_API_KEY and request.method != "OPTIONS"
            and request.url.path not in _API_KEY_OPEN_PATHS):
        if not secret_equals(request.headers.get("x-api-key"), FACE_API_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": error_payload("FORBIDDEN", "Invalid or missing API key.", retryable=False)},
            )
    return await call_next(request)


install_api_error_handling(app, "face-analyzer-basic")

import job_store
import face_feedback
import face_corrections

_insight_app = None
_face_mesh = None
_face_mesh_lock = Lock()
_COL = "face_jobs_basic"

MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", "1024"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))  # 上傳大小上限（預設 8MB），避免超大檔先塞滿記憶體
MAX_IMAGE_PIXELS = max(1, int(os.getenv("MAX_IMAGE_PIXELS", "16000000")))


async def _read_clean_image(file, label: str = "上傳檔案") -> bytes:
    """讀上傳檔案並回傳「驗過、去掉 EXIF／GPS」的位元組。

    細節都在 `image_safety`：分段讀取超限即停、magic bytes 白名單、偽 MIME 檢查、
    解碼前先卡像素數（擋解壓縮炸彈）、移除中繼資料。這裡只負責把限額帶進去。
    """
    contents, _mime = await sanitize_upload(
        file,
        max_bytes=MAX_UPLOAD_BYTES,
        max_pixels=MAX_IMAGE_PIXELS,
        label=label,
    )
    return contents


def _reject_if_too_large(contents: bytes) -> bytes:
    """同步版驗證，給已經拿到 bytes 的呼叫端（例如 PRO 的多張照片流程）。

    回傳去中繼資料後的位元組——舊版只做檢查、不回傳，所以呼叫端請改用回傳值，
    否則帶著 GPS 的原始照片還是會往下走。
    """
    cleaned, _mime = sanitize_image_bytes(
        contents,
        max_bytes=MAX_UPLOAD_BYTES,
        max_pixels=MAX_IMAGE_PIXELS,
    )
    return cleaned


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

def _insight_root() -> str:
    """模型放在哪。

    容器裡模型烘在映像的 `/app/.insightface`，舊版這個路徑是寫死的。
    但本機沒有那個目錄，InsightFace 找不到就會嘗試重新下載 ——
    離線、或像這台開發機一樣有 TLS 攔截的環境，下載必定失敗，
    於是整份分析在容器外實際上跑不起來（模型明明已經在 ~/.insightface）。

    順序：環境變數 > 容器路徑 > 使用者家目錄。三個都找不到才交給
    InsightFace 自己處理（那時下載是唯一選擇，也該讓它報錯）。
    """
    candidates = [os.getenv("INSIGHTFACE_ROOT", ""), "/app/.insightface",
                  os.path.join(os.path.expanduser("~"), ".insightface")]
    for candidate in candidates:
        if candidate and os.path.isdir(os.path.join(candidate, "models", "buffalo_l")):
            return candidate
    return "/app/.insightface"


def _get_insight():
    global _insight_app
    if _insight_app is None:
        _insight_app = InsightFaceApp(
            name="buffalo_l",
            root=_insight_root(),
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


def _process_face_mesh(rgb: np.ndarray):
    with _face_mesh_lock:
        return _get_face_mesh().process(rgb)

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url=FRONTEND_URL, status_code=307)


@app.get("/health")
async def health():
    _cleanup_jobs()
    model_state = basic_roi_shadow.model_status()
    return {
        "status": "ok" if model_state["ready"] else "degraded",
        "service": "face-analyzer-basic",
        "models": model_state,
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
    x_user_id: str | None = Header(default=None),
):
    # BASIC 同時支援「檔案上傳」與「拍照上傳」：
    # 前端檔案 input 直接送 File；相機拍照則把 canvas/blob 包成 File 後送到同一個欄位。
    contents = await _read_clean_image(file, "上傳照片")
    if brightness_mode not in {"none", "auto", "manual"}:
        raise HTTPException(status_code=400, detail="brightness_mode 必須為 none / auto / manual")
    if not (0.1 <= brightness_level <= 5.0):
        raise HTTPException(status_code=400, detail="brightness_level 必須在 0.1 ~ 5.0 之間")
    try:
        analyzer = FaceAnalyzer(contents, brightness_mode=brightness_mode, brightness_level=brightness_level)
        result = analyzer.export_json()
        result = face_corrections.apply(
            result,
            face_corrections.image_hash(contents),
            owner_id=x_user_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logging.exception("臉部分析失敗")
        raise HTTPException(status_code=500, detail="臉部分析服務發生錯誤，請稍後再試")


_CJK_RE = re.compile(r"[㐀-鿿]")


def unusable_image_message(exc: BaseException) -> str | None:
    """這個例外是不是「寫給使用者看的照片問題」？是就回傳那句話，不是就回 None。

    FaceAnalyzer 對照片本身的問題一律用**中文**訊息 raise ValueError——pose_guidance 的
    「請把頭轉向你的右邊」、「沒偵測到人臉」、「膚色區域不足…」。那些句子是設計來直接
    顯示給會員的。

    但 numpy／cv2 或程式邏輯也會丟 ValueError，訊息是英文內部文字（例如
    "image_input 只接受 str 或 bytes" 那類，或 cv2 的 shape 錯誤）。把它原樣當成重拍建議
    送到前端，等於用一句使用者看不懂的話叫他重拍，而真正的 bug 只留在 INFO log 裡、
    沒有 traceback——最難查的那種。

    所以用「訊息裡有沒有中文」當分界：有中文代表是我們刻意寫給人看的，其餘一律當內部錯誤。
    """
    text = str(exc).strip()
    return text if text and _CJK_RE.search(text) else None


def pose_guidance(yaw: float, pitch: float, yaw_limit: float, pitch_limit: float) -> str:
    """把 yaw／pitch 的角度翻成使用者做得到的動作。

    舊版這裡直接把數字丟給使用者（「偏角：yaw=-19.9°, pitch=23.6°」）。沒有人知道
    yaw 和 pitch 是什麼，所以看到訊息也不知道要動哪裡——線上日誌有人 80 秒內連試三次，
    pitch 一直停在 23.6~23.8°，他很可能一直在左右轉頭，但超標的其實是抬頭低頭。

    每一句都同時講「你現在的狀態」與「該做的動作」。狀態是使用者在預覽畫面上看得到的，
    所以萬一左右慣例反了，他靠前半句就能自行修正，不會被指令帶到更錯的方向。
    """
    hints = []
    if abs(yaw) > yaw_limit:
        # yaw < 0 代表左臉朝鏡頭：沿用 _detect_pose 的 side 判定，PRO 的即時掃描
        # 也是用同一套慣例在標「左臉／右臉」，兩邊必須一致。
        # 左臉朝鏡頭 = 頭轉向了自己的右邊，要轉回來就是往自己的左邊轉。
        if yaw < 0:
            hints.append("你現在露出的是左臉，請把頭轉向你的左邊，正對鏡頭")
        else:
            hints.append("你現在露出的是右臉，請把頭轉向你的右邊，正對鏡頭")
    if abs(pitch) > pitch_limit:
        # pitch 的正負號在 InsightFace 不同版本並不一致，這裡不敢斷言是抬頭還是低頭，
        # 改講使用者一定做得到、而且講錯不了的動作：把下巴放平、把鏡頭移到眼睛高度。
        # 自拍時這個角度幾乎都是手機拿得比眼睛高或低造成的。
        hints.append("下巴請放平，把鏡頭移到與眼睛差不多的高度（手機拿太高或太低都會偏）")
    if not hints:
        hints.append("請正對鏡頭重拍一張")
    return "；".join(hints) + "。"


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
    contents = await _read_clean_image(file, "上傳照片")
    try:
        return _detect_pose(contents)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logging.exception("臉部分析失敗")
        raise HTTPException(status_code=500, detail="臉部分析服務發生錯誤，請稍後再試")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def fail_job(col, job_id, exc, *, log_label):
    """job 失敗的統一出口。BASIC 與 PRO 共用，呼叫端只要 `fail_job(...); return`。

    分岔只有一個：unusable_image_message 認得的訊息是寫給使用者看的拍攝問題，
    原樣傳出去；其餘一律當內部錯誤，留 traceback，並用固定的中文句子回覆——
    英文內部文字送到前端等於叫使用者重拍一句他看不懂的話。
    """
    hint = unusable_image_message(exc) if isinstance(exc, ValueError) else None
    if hint is None:
        logging.exception("%s job 失敗 job_id=%s", log_label, job_id)
        patch = {
            "status": "failed", "stage": "failed",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "FACE_ANALYSIS_ERROR", "message": "臉部分析失敗，請稍後再試", "retryable": True},
        }
    else:
        logging.info("%s job 因照片問題中止 job_id=%s: %s", log_label, job_id, hint)
        patch = {
            "status": "failed", "stage": "unusable_image",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "FACE_IMAGE_UNUSABLE", "message": hint, "retryable": True},
        }
    job_store.patch_if_status(col, job_id, {"processing"}, patch)


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
                job_store.patch_if_status(_COL, job_id, {"queued", "processing"}, {
                    "status": "failed", "stage": "timeout",
                    "completedAt": _now_iso(),
                    "updatedAt": _now_iso(),
                    "error": {
                        "code": "FACE_ANALYSIS_TIMEOUT",
                        "message": f"臉部分析逾時，已超過 {FACE_JOB_TIMEOUT_SECONDS} 秒",
                        "retryable": True,
                    },
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


def _job_view(job, include_token=False):
    hidden = {"result", "imageHash", "ownerId"}
    if not include_token:
        hidden.add("resultToken")
    return {k: v for k, v in job.items() if k not in hidden}


def _verify_job_token(job, x_job_token=None, result_token=None):
    expected = job.get("resultToken")
    if expected and (x_job_token or result_token) != expected:
        raise HTTPException(
            status_code=403,
            detail={"error": {"message": "job token 不正確或未提供"}},
        )


def _run_basic_job(job_id, contents, brightness_mode="none", brightness_level=1.0, owner_id=None):
    if not job_store.patch_if_status(
        _COL,
        job_id,
        {"queued"},
        {"status": "processing", "stage": "face_analysis", "progress": 35, "startedAt": _now_iso(), "updatedAt": _now_iso()},
    ):
        return
    # 分開處理分析與資料包建立錯誤，讓上層能顯示正確原因。
    try:
        result = FaceAnalyzer(contents, brightness_mode=brightness_mode, brightness_level=brightness_level).export_json()
        # 套用已儲存的修正，並在 _modelRaw 保留模型原始輸出供回饋使用。
        result = face_corrections.apply(
            result,
            face_corrections.image_hash(contents),
            owner_id=owner_id,
        )
    except Exception as exc:
        # ValueError 代表可由使用者修正的拍攝問題，例如角度、光線或未偵測到人臉。
        # 保留原始訊息，讓前端提示正確的重拍方式。
        #
        # 錯誤碼刻意用一個前端 USER_ERROR_ZH 沒有收錄的新碼：那張表命中就會用固定字串
        # 取代訊息，收錄了反而又把這裡的具體指引蓋掉一次。沒收錄時前端會原樣顯示中文訊息。
        fail_job(_COL, job_id, exc, log_label="臉部分析")
        return

    try:
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "completed", "stage": "done", "progress": 100,
            "completedAt": _now_iso(), "updatedAt": _now_iso(), "result": result, "error": None,
        })
    except Exception:
        # 分析成功、封裝／儲存失敗。stage 標成 analysis_completed，錯誤碼獨立，
        # 這樣呼叫端就知道問題不在照片、重拍沒有用，該修的是後端封裝這一段。
        logging.exception("臉部分析結果封裝失敗 job_id=%s（分析已成功）", job_id)
        job_store.patch_if_status(_COL, job_id, {"processing"}, {
            "status": "failed", "stage": "analysis_completed",
            "completedAt": _now_iso(), "updatedAt": _now_iso(),
            "error": {"code": "PACKAGE_BUILD_FAILED",
                      "message": "臉部分析已完成，但結果封裝失敗，請稍後再試（不需重拍）。",
                      "retryable": True},
        })


@app.post("/v1/face/jobs/basic")
async def create_basic_job(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    brightness_mode: str   = Form("none"),
    brightness_level: float = Form(1.0),
    x_user_id: str | None = Header(default=None),
):
    _cleanup_jobs()
    contents = await _read_clean_image(file, "上傳照片")
    if brightness_mode not in {"none", "auto", "manual"}:
        raise HTTPException(status_code=400, detail={"error": {"message": "brightness_mode 必須為 none / auto / manual"}})
    if not (0.1 <= brightness_level <= 5.0):
        raise HTTPException(status_code=400, detail={"error": {"message": "brightness_level 必須在 0.1 ~ 5.0 之間"}})
    job_id = f"JOB-{uuid.uuid4().hex[:12]}"
    result_token = uuid.uuid4().hex
    job_data = {
        # 這張照片的穩定識別碼（SHA-256，不是影像本身）。修正快取靠它認出「同一張臉又來了」，
        # 回饋也靠它把修正記到正確的那張臉上。見 face_corrections 的模組說明。
        "imageHash": face_corrections.image_hash(contents),
        "ownerId": str(x_user_id or "").strip() or None,
        "jobId": job_id, "analysisPackageId": None, "status": "queued",
        "progress": 0, "stage": "upload", "createdAt": _now_iso(),
        "startedAt": None, "completedAt": None, "updatedAt": _now_iso(), "error": None, "result": None,
        "resultToken": result_token,
        "expiresAt": datetime.now(timezone.utc) + timedelta(seconds=FACE_JOB_RETENTION_SECONDS),
    }
    job_store.create(_COL, job_id, job_data)
    background_tasks.add_task(
        _run_basic_job,
        job_id,
        contents,
        brightness_mode,
        brightness_level,
        job_data["ownerId"],
    )
    return _job_view(job_data, include_token=True)


@app.get("/v1/face/jobs/{job_id}")
async def get_basic_job(
    job_id: str,
    x_job_token: str | None = Header(default=None),
    result_token: str | None = Query(default=None),
):
    job = job_store.get(_COL, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    return _job_view(job)


@app.get("/v1/face/jobs/{job_id}/result")
async def get_basic_job_result(
    job_id: str,
    x_job_token: str | None = Header(default=None),
    result_token: str | None = Query(default=None),
):
    job = job_store.get(_COL, job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    _verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
    if job["status"] != "completed":
        raise HTTPException(status_code=409, detail={"error": {"message": "job 尚未完成", "status": job["status"]}})
    return {
        "jobId": job_id,
        "analysisPackageId": job["analysisPackageId"],
        "status": "completed",
        "result": job["result"],
    }


# 五官判斷回饋的路由由 face_feedback 統一提供——BASIC 與 PRO 的內容一模一樣，
# 各抄一份的結果是註解已經先分歧了。真正不同的只有 job 集合與 token 驗證，
# 所以那兩樣用參數傳進去。
face_feedback.register_route(app, mode="basic", jobs_collection=_COL, verify_job_token=_verify_job_token)


class FaceAnalyzer:
    # 角度門檻。用環境變數覆寫，因為這些數字還在被量測——同學在跑系統性測試，
    # 有更好的數字時改設定就好，不必動程式重新建置。
    #
    # 預設值來自 2026-07-22 在 data/basic_full/grouped/face_shape（386 張，CelebA）
    # 量到的臉型準確率對 |yaw| 的衰減：
    #
    #     0-5°   0.538      5-8°   0.389      8-12°  0.339
    #    12-18°  0.162     18-25°  0.031
    #
    # 那條曲線描述的是規則式分類器。線上開著 ROI_MODEL_FIRST=1，使用者看到的是
    # CNN 覆蓋後的答案，而 CNN 在同一批圖上幾乎不受角度影響：
    #
    #     0-5°  0.831   5-8°  0.741   8-12° 0.769   12-18° 0.812   18-25° 0.781
    #
    # 所以角度抑制預設關閉（門檻設成不可能達到的值）。按規則式的數字去抑制，
    # 等於把 CNN 81% 準確的答案丟掉——那是拿錯的量測結果去傷害對的分類器。
    #
    # 機制留著，因為它在兩種情況下會需要：
    #   1. 關掉 MODEL_FIRST 退回規則式時（那時衰減是真的）
    #   2. 之後量到某個五官／某個軸真的敏感時（例如眼型對 pitch，還沒量）
    # 要啟用就設環境變數，例如 FACE_YAW_UNRELIABLE=12 FACE_YAW_UNCERTAIN=8。
    #
    # 注意：上面 CNN 那組數字尚未排除訓練集。tools/measure_angle_sensitivity.py 目前
    # 對整個資料夾評估，裡面可能含 CNN 訓練過的圖，準確率與平坦度都可能被記憶效應灌水。
    # 要當結論用，必須先限制在 val split（做法見 eval_rule_baseline.py）。
    YAW_LIMIT      = float(os.getenv("FACE_YAW_LIMIT", "18.0"))
    YAW_UNRELIABLE = float(os.getenv("FACE_YAW_UNRELIABLE", "9999"))
    YAW_UNCERTAIN  = float(os.getenv("FACE_YAW_UNCERTAIN", "9999"))
    # pitch 維持 15：同一批資料顯示它對臉型幾乎沒有影響（0-5° 0.307、12-18° 0.250），
    # 但那只量了臉型。抬頭低頭會直接改變眼睛的開合，眼型很可能是 pitch 敏感的，
    # 而我們還沒量。沒有量過的東西不要放寬。
    PITCH_LIMIT   = float(os.getenv("FACE_PITCH_LIMIT", "15.0"))

    # ── 膚色取樣被頭髮污染 ────────────────────────────────────────────────
    # get_skin_color 的膚色範圍過濾只擋得住黑髮（靠 LAB 的 L>=35 下限）。實測把同一張
    # 照片的真實頭髮移植到臉頰（40 張、160 組遮蔽案例）：棕髮與染髮平均有 53% 的
    # 像素直接通過那層過濾——顏色範圍本來就分不開棕髮與皮膚，兩者在 LAB／HSV／YCrCb
    # 三個空間裡都重疊。純色塗塊的對照組更極端，通過率 100%。
    #
    # 後段的分位裁切與中位數離群剔除多數時候擋得住，但不是每次：ΔE>5 佔 19%，最差 45。
    # 也就是說每五次就有一次膚色明顯算錯，而且完全不會報錯——粉底推薦與色號比對
    # 都會跟著錯。
    #
    # 兩道防線，都用上面那批資料量過：
    #   1. 紋理過濾。皮膚平滑、頭髮有高頻紋理，這是顏色分不開時還能用的訊號。
    #      走完整程式碼路徑複驗（tools/measure_hair_contamination.py）：最差 ΔE 從 45.01
    #      降到 22.41，ΔE>5 從 19% 降到 15%。
    #   2. 可信度標記。光靠 1 不夠（只是把錯誤變小，不是消除），所以再量一個能預測
    #      「這次算錯了」的訊號。試過四個候選，頰部 ROI 內 L 的 MAD 分離度最好（1.28）：
    #        乾淨照片 p50 6.67 / p95 9.55  |  算錯案例中位數 15.69、算對 8.24
    #      門檻取 9.5（≈乾淨照片的 p95）→ 抓到 100% 的算錯案例，乾淨照片誤報 5%。
    SKIN_TEXTURE_STD_MAX  = float(os.getenv("FACE_SKIN_TEXTURE_STD_MAX", "6.0"))
    SKIN_TEXTURE_WINDOW   = int(os.getenv("FACE_SKIN_TEXTURE_WINDOW", "7"))
    SKIN_SPREAD_UNRELIABLE = float(os.getenv("FACE_SKIN_SPREAD_UNRELIABLE", "9.5"))

    def __init__(self, image_input, strict_angle=True, brightness_mode="none", brightness_level=1.0, require_insight=True):
        if isinstance(image_input, str):
            self.frame = cv2.imdecode(np.fromfile(image_input, dtype=np.uint8), cv2.IMREAD_COLOR)
        elif isinstance(image_input, bytes):
            self.frame = cv2.imdecode(np.frombuffer(image_input, np.uint8), cv2.IMREAD_COLOR)
        else:
            raise ValueError("image_input 只接受 str 或 bytes")

        if self.frame is None:
            raise FileNotFoundError("圖片讀取失敗")

        # 沒跑 InsightFace（require_insight=False，例如訓練與校正工具）時就沒有角度可用。
        # 維持 None 而不是 0：0 會被當成「完美正臉」，讓可信度標記靜靜消失。
        self.pose_yaw = None
        self.pose_pitch = None

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

            if hasattr(face, "pose") and face.pose is not None:
                # 一律保存臉部角度，讓 export_json 標示不可靠的分析欄位。
                self.pose_yaw = float(face.pose[0])
                self.pose_pitch = float(face.pose[1])
                if strict_angle and (
                    abs(self.pose_yaw) > self.YAW_LIMIT or abs(self.pose_pitch) > self.PITCH_LIMIT
                ):
                    raise ValueError(
                        pose_guidance(self.pose_yaw, self.pose_pitch, self.YAW_LIMIT, self.PITCH_LIMIT)
                    )

        # Step 2：MediaPipe FaceMesh
        mp_face_mesh = mp.solutions.face_mesh
        results = _process_face_mesh(rgb)

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

    def face_outline_points(self):
        """旋正後的臉部外框點（N×2）。量不出來回 None。

        單獨開一個方法，是因為「寬度比值」描述不了下顎轉角的曲率——
        而圓形臉與方形臉的差別正是那個轉角（實測互認率 23%、對稱 0.89，
        代表模型完全分不開這兩類）。要算曲率就得拿到點本身，不能只拿彙總後的寬度。
        """
        idx = self._collect_landmark_indices(self.mp_face_mesh.FACEMESH_FACE_OVAL)
        if len(idx) < 5:
            return None
        pts = np.array([self._pt(i) for i in idx], dtype=np.float32)
        return self._align_points_by_eyes(pts)

    def face_measurements(self) -> dict[str, float] | None:
        """回傳臉型判斷用的原始量測值（像素單位），量不出來時回 None。

        抽成獨立方法是為了讓「規則判斷」與「機器學習特徵抽取」共用同一份量測。
        這段沿著臉部外框在多個高度取寬度，邏輯不短；複製第二份到工具腳本裡，
        兩邊遲早會走樣，屆時比較規則式與模型的分數就是在比兩個不同的東西。
        """
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
                return None

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
            return None

        return {
            "face_width": float(face_width),
            "face_height": float(face_height),
            "forehead_width": float(forehead_width),
            "cheekbone_width": float(cheekbone_width),
            "jaw_width": float(jaw_width),
            "chin_width": float(self._dist(150, 379)),
        }

    def get_face_shape(self, debug=False):
        m = self.face_measurements()
        if m is None:
            return "未知"
        face_width, face_height = m["face_width"], m["face_height"]
        forehead_width, cheekbone_width = m["forehead_width"], m["cheekbone_width"]
        jaw_width, chin_width = m["jaw_width"], m["chin_width"]

        hw = round(face_height / face_width, 3)
        max_w = max(forehead_width, cheekbone_width, jaw_width)
        fw_n  = forehead_width / max_w
        jw_n  = jaw_width / max_w
        jaw_to_forehead = jaw_width / forehead_width if forehead_width > 1e-6 else 1.0
        forehead_to_jaw = forehead_width / jaw_width
        cheek_to_jaw    = cheekbone_width / jaw_width
        forehead_to_cheek = forehead_width / cheekbone_width if cheekbone_width > 1e-6 else 1.0
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

        # 2026-07-31：拿掉「梯形臉」與「菱形臉」兩個分支。官方分類表只有五類
        # （圓形／心形／方形／長形／鵝蛋），這兩個名字從來不在裡面——吐出來之後
        # analysis_package._code 會落成 "unknown"，前端回饋選項也沒有它們。
        # 不自己發明對應關係，直接讓它落到下面已經調過的正規分支。
        if jaw_width >= cheekbone_width and jaw_width > forehead_width * 1.16:
            return "方形臉"

        if cheekbone_width >= forehead_width and cheekbone_width >= jaw_width:
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
        tail_ratio = (left_tail + right_tail) / 2.0

        # 門檻由本專案自己的 194 張人工標註資料校準（tools/calibrate_rule_thresholds.py），
        # 只用 train set 找切點、val set 驗證：macro accuracy 0.333 -> 0.485。
        #
        # 舊版的門檻是「以 CelebA 分位數校正」，但 CelebA 以西方人臉為主，分佈跟本專案的
        # 亞洲人自拍不同，那組門檻整組落在資料範圍之外（落尾眉需 tail>0.100 但實際最大只有 0.090；
        # 一字眉需 arch<0.115 但實際最小是 0.138），兩個分支都是永遠不會執行的死碼，
        # 結果每一個人都掉進 fallback 判成「彎月眉」。詳見 規則式閾值Bug_完整診斷記錄_新手版.md。
        #
        # arch_ratio 已棄用：三類的中位數是 0.155/0.161/0.166、類內標準差卻有 0.029，
        # 分離度僅 0.40（類內雜訊大於類間差距），沒有鑑別力，門檻怎麼調都沒用。
        if tail_ratio < -0.014: return "一字眉"
        if tail_ratio >  0.030: return "落尾眉"
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
        ratio_to_face = eye_width / face_width

        # 門檻由本專案自己的 376 張人工標註資料校準（tools/calibrate_rule_thresholds.py）：
        # 在 train set 上訓練淺決策樹（max_depth 由 train 內部 5-fold CV 選出）再移植成 if-else，
        # val macro accuracy 0.143 -> 0.371。
        #
        # 舊版門檻同樣來自 CelebA，在本專案資料上有三個死碼（瞇縫眼需 ratio<0.12 但實際最小 0.194、
        # 下垂眼需 angle>6 但實際最大 0.603、圓眼需 ear>0.40 但實際最大 0.392）
        # 外加一個恆真條件（桃花眼需 ratio>0.16，而所有人都 >0.194），
        # 導致 96% 的人被判成「桃花眼」。詳見 規則式閾值Bug_完整診斷記錄_新手版.md。
        #
        # 類別名稱依官方分類表：瞇縫眼併入細長眼、丹鳳眼併入鳳眼（2026-07-24），
        # 眼型現行四類（2026-07-31）：下垂眼／圓眼／桃杏眼／鳳眼。
        # 杏仁眼＋桃花眼 → 桃杏眼（07-30）；細長眼 → 鳳眼（07-31）。
        #
        # 這組手寫 if-else 現在是最後一層 fallback。幾何決策樹已於 07-30 全面退場
        # （見 basic_rule_trees 與發展歷程規格書 §7.11），正式答案是 CNN／DINOv2；
        # 這裡維持可用，是為了模型載入失敗時仍有東西可回。
        #
        # 誠實的限制：三個弱特徵（ear / angle / ratio_to_face）分不乾淨，
        # 這組規則在同一套 5-fold 上只有 0.44 左右，明顯輸給 CNN 的 0.56。
        if ear <= 0.264:
            return "鳳眼"
        if ear <= 0.327:
            if ratio_to_face <= 0.207: return "下垂眼"
            return "鳳眼"
        if ratio_to_face <= 0.229 and ear <= 0.346:
            return "桃杏眼"
        return "圓眼"

    def get_nose_shape(self):
        nose_width  = self._dist(129, 358)
        face_width  = self._dist(234, 454)

        if face_width < 1e-6:
            return "未知"

        ratio_width = nose_width / face_width

        # 正面照只能穩定估鼻翼相對寬窄；鼻樑高度、鷹勾、塌鼻、朝天鼻需要側面或深度資訊。
        #
        # 門檻由本專案自己的 156 張人工標註資料校準（tools/calibrate_rule_thresholds.py）：
        # val macro accuracy 0.354 -> 0.470。舊版的「窄鼻需 <= 0.205」是死碼 ——
        # 本專案資料的最小值是 0.259，沒有任何一個人達標，於是 98% 的人被判成「標準鼻」。
        #
        # 「窄鼻」已經併入「標準鼻」，不再是一個輸出類別。
        #
        # 併掉的理由，從當初的校準數字就看得出來：人工標註的三類，ratio_width 中位數是
        # 寬鼻 0.310 > 窄鼻 0.291 > 標準鼻 0.283 —— 「窄鼻」的鼻翼比「標準鼻」還寬。
        # 標註者判斷窄鼻時看的顯然不是鼻翼寬度（可能是鼻頭大小或鼻樑），
        # 也就是這個特徵跟那個標籤本來就對不上。
        #
        # 模型端更明顯：併之前的三類 CNN，「標準鼻」召回率只有 0.061——
        # 33 個標準鼻裡有 30 個被判成窄鼻，整個類別塌陷。併成兩類重訓後
        # 兩類召回率都是 0.800（models/basic_features_roi/nose_shape_metrics.json）。
        #
        # 0.300 是寬鼻與其他鼻型的既有界線；合併後界線以下皆為標準鼻。
        if ratio_width > 0.300: return "寬鼻"
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
        elif m_diff_ratio > 0.06:          return "花瓣唇"   # M型唇已併入花瓣唇（2026-07-30）
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

    def _skin_texture_mask(self):
        """回傳「夠平滑，像皮膚」的遮罩。頭髮的高頻方向性紋理在這裡會被剔掉。

        用局部標準差而不是 Laplacian：對雜訊比較不敏感，而且一次 blur 就算得出來，
        不會拖慢分析。見 SKIN_TEXTURE_STD_MAX 的說明。
        """
        gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
        win  = (self.SKIN_TEXTURE_WINDOW, self.SKIN_TEXTURE_WINDOW)
        mean = cv2.blur(gray, win)
        sq   = cv2.blur(gray * gray, win)
        std  = np.sqrt(np.maximum(sq - mean * mean, 0.0))
        return (std <= self.SKIN_TEXTURE_STD_MAX).astype(np.uint8) * 255

    def _skin_sample_reliability(self, lab_img, roi_mask) -> dict:
        """頰部取樣區的亮度離散程度——遮擋的偵測訊號，門檻由實測決定。

        量的是顏色過濾之前的幾何取樣區：污染的證據就在那些被過濾掉、或沒被
        過濾掉但明顯偏離的像素裡。過濾之後才量等於先把證據刪掉再找證據。
        """
        l_vals = lab_img[:, :, 0][roi_mask > 0].astype(np.float32) / 2.55
        if l_vals.size < 100:
            return {"measured": False, "reliable": True, "hint": ""}
        spread = float(np.median(np.abs(l_vals - np.median(l_vals))))
        reliable = spread <= self.SKIN_SPREAD_UNRELIABLE
        return {
            "measured": True,
            "reliable": reliable,
            "spread": round(spread, 2),
            "threshold": self.SKIN_SPREAD_UNRELIABLE,
            # 值照樣回傳，不清空：它仍是目前最好的估計，只是要讓下游知道別拿它去比色號。
            "hint": "" if reliable else "臉頰被頭髮或陰影遮住，膚色可能不準；把頭髮撥到耳後、在均勻光線下重拍會更準確。",
        }

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

        # 顏色分不開棕髮與皮膚，紋理可以——完整理由與實測數字見 SKIN_TEXTURE_STD_MAX。
        textured = cv2.bitwise_and(combined_mask, self._skin_texture_mask())
        # 紋理過濾不能反過來把樣本殺光：粗顆粒、對焦不準或高 ISO 的照片整張都是高頻
        # 雜訊，那種照片上這一層會濾掉幾乎所有像素。剩太少就退回沒濾的版本——
        # 寧可污染風險照舊（下面的可信度標記還會抓），也不要沒有樣本可算。
        shade_mask = textured if cv2.countNonZero(textured) >= 150 else combined_mask

        # 可信度只量頰部這塊幾何取樣區。門檻 9.5 是在頰部上校準的（乾淨照片 p95 = 9.55），
        # 而 sample_mask 在頰部太小時會退回整臉凸包——那塊含額頭反光與下顎陰影，
        # 實測 MAD 中位數 8.43、p95 13.06，拿同一個門檻去套，乾淨照片的誤報率會從
        # 5% 跳到 37.5%。所以這裡固定用頰部；頰部本來就不夠大時不宣稱可信度。
        self.skin_reliability = self._skin_sample_reliability(lab, cheek_mask)

        # 季型算在**紋理過濾前**的遮罩上，膚色分級才用過濾後的。
        #
        # 兩者要的東西不同：紋理過濾是為了「別把頭髮的顏色算進膚色」，而 _classify_season
        # 的 clear 判定吃的是 v_std >= 18.0 —— 明暗分佈的離散程度，那需要完整取樣。
        # 先前兩者共用過濾後的遮罩，等於把「專門剔除高變異像素」的結果餵進一個為未過濾
        # 資料校準的門檻：實測 40 張乾淨照片，v_std 平均 28.42 掉到 24.57，**12%（5/40）
        # 的四季型被改掉**（夏季→秋季、冬季→夏季），而使用者與我們都看不出來。
        season               = self._classify_season(lab, hsv, combined_mask)
        shade_label, L, a, b = self._classify_shade_12grid(lab, shade_mask)
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

    def _pose_reliability(self) -> dict:
        """這次拍攝角度，以及哪些欄位在這個角度下不該被當真。

        臉型的判別式幾乎全是水平跨距的比值（hw、額/顴/顎寬、jaw_to_forehead…），
        轉頭會把水平距離壓縮約 cos(yaw)，而且遠近兩側壓縮程度不同——比值被不對稱
        扭曲，不是單純縮放能校正的。實測（386 張）也證實了這件事：8-12° 準確率
        0.339，12-18° 掉到 0.162，低於五分類的隨機基準 0.20。

        膚色刻意不列入：它是區域顏色平均，任何角度都成立。把它一起標成不可靠是
        白白丟資訊，也會讓這個標記本身失去意義——什麼都標不確定，等於沒標。

        眼型／鼻型／唇型／眉型同樣含水平跨距，理論上也會受影響，但還沒有實測數字，
        所以先不列。沒有量過就不要宣稱，寧可少標也不要標錯。
        """
        if self.pose_yaw is None:
            return {"measured": False, "lowConfidenceFields": [], "suppressedFields": []}
        yaw = abs(self.pose_yaw)
        suppressed = ["臉型"] if yaw > self.YAW_UNRELIABLE else []
        low = ["臉型"] if (not suppressed and yaw > self.YAW_UNCERTAIN) else []
        if suppressed:
            hint = "拍攝角度偏斜較多，這張無法判斷臉型；其餘結果仍然有效。想看臉型請正對鏡頭重拍一張。"
        elif low:
            hint = "拍攝角度略偏，臉型判斷可能不準，建議正對鏡頭重拍一張。"
        else:
            hint = ""
        return {
            "measured": True,
            "yaw": round(self.pose_yaw, 2),
            "pitch": round(self.pose_pitch, 2) if self.pose_pitch is not None else None,
            "lowConfidenceFields": low,
            "suppressedFields": suppressed,
            "hint": hint,
        }

    def export_json(self, save_path=None):
        lip_L, lip_a, lip_b, season, shade_label, L, a, b = self.get_skin_color()
        pose_report = self._pose_reliability()
        result = {
            "分析版本": "BASIC",
            # 角度抑制不在這裡做——MODEL_FIRST 會在後面覆蓋整個 result，
            # 寫在這裡會被蓋掉。統一放到函式最後，見那裡的說明。
            "臉型": self.get_face_shape(),
            "眉型": self.get_eyebrow_shape(),
            "眼型": self.get_eye_shape(),
            "鼻型": self.get_nose_shape(),
            "嘴型": self.get_lip_shape(),
            "膚色": {
                "四季型":   season,
                "膚色分級": shade_label,
                "LAB": {"L": float(round(L,2)), "a": float(round(a,2)), "b": float(round(b,2))},
                # 頭髮／陰影遮住臉頰時這裡會是 reliable:false。值照樣給——它仍是最好的
                # 估計，但下游要拿它去算 ΔE 比色號之前應該先看這個旗標。
                "可信度": getattr(self, "skin_reliability", {"measured": False, "reliable": True, "hint": ""}),
            },
            "嘴唇_LAB": {"L": float(lip_L), "a": float(lip_a), "b": float(lip_b)},
            "臉部對稱性": self.get_face_symmetry(),
            "brightnessEnhancement": self.brightness_info,
            "拍攝角度": pose_report,
        }

        # ROI CNN：預設由模型提供五個部位的正式答案，規則式退居 fallback（ROI_MODEL_FIRST）。
        #
        # 原因見 規則式閾值Bug_完整診斷記錄_新手版.md：規則式的門檻是從 CelebA（西方人臉）
        # 抄來的，套在亞洲人自拍上整組落在資料範圍之外，導致每個人都被判成「彎月眉+標準鼻」。
        # 閾值已用自己的資料重新校準，但校準後仍全面輸給 CNN（brow 0.485 vs 0.589、
        # nose 0.470 vs 0.666），所以正式答案改由 CNN 提供。
        #
        # 整段包 try —— 模型壞掉不能影響正式分析，失敗時五個欄位維持規則式的答案。
        try:
            shadow = basic_roi_shadow.predict(self.frame, self._pts_cache)

            # DINOv2 的 shadow 結果要在正式模型覆蓋答案前記錄，才能正確比較。
            #
            # shadow 模式下改成抽樣：DINOv2 佔整個分析 57% 的時間，而它的輸出只進對照 log，
            # 每個使用者都替一份離線比較實驗等了那 343ms。對照要的是統計不是每一筆。
            # 抽樣率見 basic_roi_shadow.DINOV2_SAMPLE_RATE；MODEL_FIRST 開啟時不抽樣。
            dino = (
                basic_roi_shadow.predict_dinov2(self.frame, self._pts_cache)
                if basic_roi_shadow.should_run_dinov2()
                else None
            )
            basic_roi_shadow.log_dinov2_comparison(shadow, dino)

            if shadow:
                # 注意順序：對照 log 必須在覆蓋之前記，否則就變成模型跟自己比對了。
                basic_roi_shadow.log_comparison(result, shadow)
                if basic_roi_shadow.MODEL_FIRST:
                    sources = basic_roi_shadow.apply_model_first(result, shadow)
                    if sources:
                        result["分類來源"] = sources
                if basic_roi_shadow.EXPOSE_IN_RESPONSE:
                    result["模型分類"] = shadow

            # 觀察期結束、確認 DINOv2 表現後，設 ROI_DINOV2_MODEL_FIRST=1 讓它接手這三個部位。
            if dino and basic_roi_shadow.DINOV2_MODEL_FIRST:
                dino_sources = basic_roi_shadow.apply_model_first(result, dino)
                if dino_sources:
                    result.setdefault("分類來源", {}).update(dino_sources)
            if dino and basic_roi_shadow.EXPOSE_IN_RESPONSE:
                result["模型分類_dinov2"] = dino
        except Exception:
            logging.getLogger(__name__).exception("ROI 模型預測失敗，改用規則式結果")

        # 幾何決策樹接手眼型與臉型。放在 CNN 之後，因為在同一套 5-fold 上它贏了：
        # 眼型 0.406 vs 0.332（5/5 fold）、臉型 0.544 vs 0.477（4/5 fold）。
        # 其餘三個部位維持 CNN——樹在那裡輸，但差距小於逐 fold 差的標準差，
        # 屬於傾向而非定論，不值得為此更動既有部署。
        # 詳見 模型訓練記錄_2026-07-24.md 第 5.3.1 節。
        try:
            tree_pred = basic_rule_trees.predict(self)
            tree_sources = basic_rule_trees.apply(result, tree_pred)
            if tree_sources:
                result.setdefault("分類來源", {}).update(tree_sources)
            if tree_pred and basic_roi_shadow.EXPOSE_IN_RESPONSE:
                result["模型分類_規則樹"] = tree_pred
        except Exception:
            logging.getLogger(__name__).exception("規則樹預測失敗，維持既有答案")

        # DINOv2 逐部位覆蓋。必須放在決策樹之後：樹負責眼型與臉型，
        # 而眼型的最佳來源是 DINOv2（0.542 vs 樹 0.428 vs CNN 0.495）——
        # 放在樹之前會被樹蓋回去。臉型仍由樹決定，因為 DINOv2 在那裡最差（0.424）。
        # 哪些部位見 basic_roi_shadow.dinov2_first_parts()，預設只有眼型。
        #
        # 放在角度抑制之前，理由跟 MODEL_FIRST 那段一樣：抑制必須是最後一手，
        # 否則會被後面的覆蓋蓋掉，等於沒做。
        try:
            first_parts = basic_roi_shadow.dinov2_first_parts()
            if dino and first_parts:
                for part in first_parts:
                    field = basic_roi_shadow.PART_TO_FIELD.get(part)
                    entry = dino.get(field) if field else None
                    if isinstance(entry, dict) and entry.get("label"):
                        result[field] = entry["label"]
                        result.setdefault("分類來源", {})[field] = entry.get("source", "dinov2")
        except Exception:
            logging.getLogger(__name__).exception("DINOv2 逐部位覆蓋失敗，維持既有答案")

        # 角度抑制要在模型覆蓋答案後執行，否則結果會再次被模型答案取代。
        #
        # 注意這裡抑制的是模型的答案，而角度衰減曲線目前只量過規則式。CNN 從
        # landmark 裁 ROI，斜臉的裁切同樣會失真，但失真多少沒有量過，所以這道抑制
        # 現在是「合理的預防」而不是「有數據支撐的門檻」。量完再回來調 YAW_UNRELIABLE。
        if "臉型" in pose_report.get("suppressedFields", []):
            result["臉型"] = "無法判斷（拍攝角度偏斜）"
            if isinstance(result.get("分類來源"), dict):
                result["分類來源"]["臉型"] = "角度抑制"

        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(result, f, indent=4, ensure_ascii=False)
        return result


if __name__ == "__main__":
    run_dev_server(app, service_name="Face Analyzer BASIC", env_prefix="FACE_BASIC", default_port=8001)
