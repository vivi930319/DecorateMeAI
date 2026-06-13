import json
import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from Face_analyzer_BASIC import FaceAnalyzer


app = FastAPI(title="Face Analyzer PRO")
_jobs = {}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _read_image(file: UploadFile, label: str) -> bytes:
    contents = await file.read()
    if not contents:
        raise ValueError(f"{label}照片是空的")
    return contents


def _merge_basic_and_pro(front_result, side_available=False):
    result = dict(front_result)
    result["分析版本"] = "PRO"
    result["精細分析狀態"] = {
        "多角度照片": "已接收" if side_available else "未提供完整側面角度",
        "鼻型精細分類": "待實作",
        "臉型精細分類": "待實作",
    }
    result["精細分析備註"] = (
        "PRO 目前先保留多角度檔案上傳入口；"
        "鷹勾鼻、塌鼻、朝天鼻、翹鼻等側面特徵需等側面/45度特徵演算法完成後再啟用。"
    )
    return result


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _job_view(job):
    return {k: v for k, v in job.items() if k != "result"}


def _run_pro_job(job_id, front_bytes, angle_bytes):
    job = _jobs[job_id]
    job.update({"status": "processing", "stage": "face_analysis", "progress": 35, "startedAt": _now_iso()})
    try:
        front_result = FaceAnalyzer(front_bytes).export_json()
        side_available = any(angle_bytes.values())
        result = _merge_basic_and_pro(front_result, side_available=side_available)
        job.update({
            "status": "completed",
            "stage": "done",
            "progress": 100,
            "completedAt": _now_iso(),
            "result": result,
            "error": None,
        })
    except Exception as e:
        job.update({
            "status": "failed",
            "stage": "failed",
            "completedAt": _now_iso(),
            "error": {"message": str(e)},
        })


@app.get("/health")
async def health():
    return {"status": "ok", "service": "face-analyzer-pro"}


@app.post("/analyze-pro")
@app.post("/v1/face/analyze/pro")
async def analyze_pro(
    front: UploadFile = File(...),
    left45: UploadFile | None = File(default=None),
    right45: UploadFile | None = File(default=None),
    side: UploadFile | None = File(default=None),
):
    """
    PRO 檔案上傳版。

    目前可用流程：
    - front：必填正面照，先沿用 BASIC 的穩定分析。
    - left45/right45/side：先預留欄位，讓前端可以上傳多角度照片。

    掃描版預留：
    - 未來前端使用 getUserMedia 開鏡頭。
    - 依 yaw 自動擷取 front / left45 / right45 / side。
    - 擷取完成後仍送到這個 API，避免掃描版和檔案上傳版後端邏輯分裂。
    """
    try:
        front_bytes = await _read_image(front, "正面")
        front_result = FaceAnalyzer(front_bytes).export_json()

        side_available = False
        for label, upload in (("左45度", left45), ("右45度", right45), ("側面", side)):
            if upload is None:
                continue
            await _read_image(upload, label)
            side_available = True

        return _merge_basic_and_pro(front_result, side_available=side_available)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/face/jobs/pro")
async def create_pro_job(
    background_tasks: BackgroundTasks,
    front: UploadFile = File(...),
    left45: UploadFile | None = File(default=None),
    right45: UploadFile | None = File(default=None),
    side: UploadFile | None = File(default=None),
):
    try:
        front_bytes = await _read_image(front, "正面")
        angle_bytes = {}
        for label, role, upload in (("左45度", "left45", left45), ("右45度", "right45", right45), ("側面", "side", side)):
            angle_bytes[role] = await _read_image(upload, label) if upload is not None else None
    except ValueError as e:
        raise HTTPException(status_code=400, detail={"error": {"message": str(e)}})

    job_id = f"JOB-{uuid.uuid4().hex[:12]}"
    _jobs[job_id] = {
        "jobId": job_id,
        "analysisPackageId": None,
        "status": "queued",
        "progress": 0,
        "stage": "upload",
        "createdAt": _now_iso(),
        "startedAt": None,
        "completedAt": None,
        "error": None,
        "result": None,
    }
    background_tasks.add_task(_run_pro_job, job_id, front_bytes, angle_bytes)
    return _job_view(_jobs[job_id])


@app.get("/v1/face/jobs/{job_id}")
async def get_pro_job(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"error": {"message": "找不到 job"}})
    return _job_view(job)


@app.get("/v1/face/jobs/{job_id}/result")
async def get_pro_job_result(job_id: str):
    job = _jobs.get(job_id)
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8002)
