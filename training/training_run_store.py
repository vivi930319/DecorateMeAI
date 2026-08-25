"""小型 Firestore REST client，供本機匯入／訓練腳本更新後台訓練批次。

訓練環境不必安裝 google-cloud-firestore；沿用既有 gcloud access token 流程，讓「後台
送去訓練」與「本機真的跑完」共用同一份 Firestore 紀錄。
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUNS_COLLECTION = "face_training_runs"
METRICS_COLLECTION = "face_model_metrics"
# 訓練機的心跳。放在自己的集合裡，不要混進 face_training_runs——後台是用
# createdAt 排序整個集合來列出最近批次的，混進去會讓心跳文件擠掉一筆真的批次。
WORKERS_COLLECTION = "face_training_workers"


def _gcloud_exe() -> str:
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")


_TOKEN_CACHE: dict[str, float | str] = {"value": "", "expires": 0.0}


def _token() -> str:
    """取 access token，並在記憶體裡快取。

    原本每一次讀寫都 spawn 一次 gcloud，單次約 1 秒。腳本一輪只寫兩三次還好，
    但 training_worker 是每隔幾秒輪詢一次，那就變成整台機器都在跑 gcloud。
    token 實際有效約一小時，這裡只留 45 分鐘，把時鐘誤差與換發留出餘裕。
    """
    now = time.time()
    if _TOKEN_CACHE["value"] and now < float(_TOKEN_CACHE["expires"]):
        return str(_TOKEN_CACHE["value"])
    out = subprocess.run([_gcloud_exe(), "auth", "print-access-token"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode:
        raise RuntimeError(f"gcloud 取得 Firestore token 失敗：{out.stderr.strip()[:300]}")
    token = out.stdout.strip()
    _TOKEN_CACHE["value"] = token
    _TOKEN_CACHE["expires"] = now + 45 * 60
    return token


def _unwrap(value):
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "booleanValue", "timestampValue"):
        if key in value:
            return value[key]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "mapValue" in value:
        return {k: _unwrap(v) for k, v in (value["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in value:
        return [_unwrap(v) for v in (value["arrayValue"].get("values") or [])]
    if "nullValue" in value:
        return None
    return value


def _wrap(value):
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_wrap(v) for v in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(k): _wrap(v) for k, v in value.items()}}}
    return {"stringValue": str(value)}


def _url(project: str, collection: str, doc_id: str) -> str:
    from urllib.parse import quote
    return (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
            f"/databases/(default)/documents/{quote(collection, safe='')}/{quote(doc_id, safe='')}")


def get_document(project: str, collection: str, doc_id: str) -> dict | None:
    req = urllib.request.Request(_url(project, collection, doc_id), headers={"Authorization": f"Bearer {_token()}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    return {k: _unwrap(v) for k, v in (data.get("fields") or {}).items()}


def patch_document(project: str, collection: str, doc_id: str, updates: dict) -> None:
    from urllib.parse import quote
    fields = "&".join(f"updateMask.fieldPaths={quote(str(k), safe='')}" for k in updates)
    req = urllib.request.Request(
        f"{_url(project, collection, doc_id)}?{fields}",
        data=json.dumps({"fields": {str(k): _wrap(v) for k, v in updates.items()}}).encode("utf-8"),
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=60):
        pass


def _run_query(project: str, body: dict) -> list[dict]:
    from urllib.parse import quote
    url = (f"https://firestore.googleapis.com/v1/projects/{quote(project, safe='')}"
           f"/databases/(default)/documents:runQuery")
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        rows = json.loads(resp.read().decode("utf-8"))
    out = []
    for row in rows:
        doc = row.get("document")
        if not doc:
            continue
        record = {k: _unwrap(v) for k, v in (doc.get("fields") or {}).items()}
        record.setdefault("runId", doc.get("name", "").rsplit("/", 1)[-1])
        out.append(record)
    return out


def list_runs(project: str, status: str | None = None, limit: int = 20) -> list[dict]:
    """列出訓練批次，最舊的排前面。

    worker 要先做最早排隊的那一批：管理員按下按鈕的順序就是他想要的順序，
    後進先出會讓最早送的那一批永遠排在後面。
    """
    query: dict = {
        "from": [{"collectionId": RUNS_COLLECTION}],
        "orderBy": [{"field": {"fieldPath": "createdAt"}, "direction": "ASCENDING"}],
        "limit": int(limit),
    }
    if status:
        query["where"] = {"fieldFilter": {
            "field": {"fieldPath": "status"}, "op": "EQUAL", "value": {"stringValue": status}}}
    return _run_query(project, {"structuredQuery": query})


def claim_run(project: str, run_id: str, worker_id: str) -> dict | None:
    """把一筆 queued 批次收下來，回傳批次內容；已經被別人收走就回 None。

    這裡是先讀再寫，不是原子操作。實務上只有一台訓練機，這個競態跑不出來；
    真的要跑兩台的話，這一段必須換成 Firestore 的 updateTime precondition，
    否則兩台會同時訓練同一批（結果不會錯，但會白跑一次八分鐘）。
    """
    run = get_document(project, RUNS_COLLECTION, run_id)
    if not run or run.get("status") != "queued":
        return None
    patch_document(project, RUNS_COLLECTION, run_id, {
        "status": "running",
        "startedAt": now_iso(),
        "workerId": worker_id,
        "error": None,
    })
    run["status"] = "running"
    return run


def fail_run(project: str, run_id: str, message: str) -> None:
    """把批次標成失敗，並留下**看得懂的**原因。

    訊息會直接顯示在後台的對話框裡，所以要寫給人看，不是貼一整段 traceback。
    截斷是必要的：Firestore 單一欄位有大小上限，而一段 PyTorch 的錯誤輕易就上千字。
    """
    patch_document(project, RUNS_COLLECTION, run_id, {
        "status": "failed",
        "finishedAt": now_iso(),
        "error": (message or "訓練失敗，但沒有取得錯誤訊息").strip()[:1500],
    })


def heartbeat(project: str, worker_id: str, state: str, detail: str = "") -> None:
    """訓練機回報「我還在」。

    後台需要它才能分辨兩件會被混為一談的事：批次還沒開始，是因為**訓練機沒開**，
    還是因為**訓練失敗了**。沒有心跳的話，管理員按下按鈕看到「已排隊」會以為壞掉。
    """
    try:
        patch_document(project, WORKERS_COLLECTION, worker_id, {
            "workerId": worker_id,
            "state": state,
            "detail": detail[:300],
            "lastSeenAt": now_iso(),
        })
    except Exception:
        # 心跳寫不進去不該讓訓練停下來——它只是狀態顯示，不是訓練的一部分。
        pass


def model_digests(model_dir: Path) -> dict:
    """算出模型目錄裡每個 ONNX 的 sha256。

    這是把「這次訓練」跟「線上跑的那顆模型」綁在一起的那一環。少了它，紀錄只能
    證明「有一次訓練跑完、分數從 A 變成 B」，不能證明線上那顆就是它的產物——
    中間有人手動換掉模型，紀錄看不出來。tools/face_models_manifest.json 存的是
    同一種雜湊，兩邊可以直接比對。
    """
    digests = {}
    for onnx in sorted(Path(model_dir).glob("*.onnx")):
        digest = hashlib.sha256()
        with onnx.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digests[onnx.stem] = digest.hexdigest()
    return digests


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_model_metrics(model_dir: Path) -> dict:
    """讀目前 ConvNeXt 模型的正式指標，供 training_runs 的 before/after 使用。"""
    result = {"architecture": "ConvNeXt-Tiny", "parts": {}}
    for part in ("face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape"):
        classes_path = model_dir / f"{part}_classes.json"
        metrics_path = model_dir / f"{part}_metrics.json"
        try:
            classes = json.loads(classes_path.read_text(encoding="utf-8"))
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            identity = metrics.get("identity") or {}
            best = identity.get("best") or {}
            result["parts"][part] = {
                "architecture": classes.get("architecture", "convnext_tiny"),
                "macroAccuracy": best.get("macro_accuracy"),
                "accuracy": best.get("accuracy"),
                "classes": classes.get("classes", []),
                "metricsFile": str(metrics_path),
            }
        except (OSError, ValueError, TypeError):
            continue
    return result
