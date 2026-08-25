"""小型 Firestore REST client，供本機匯入／訓練腳本更新後台訓練批次。

訓練環境不必安裝 google-cloud-firestore；沿用既有 gcloud access token 流程，讓「後台
送去訓練」與「本機真的跑完」共用同一份 Firestore 紀錄。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUNS_COLLECTION = "face_training_runs"
METRICS_COLLECTION = "face_model_metrics"


def _gcloud_exe() -> str:
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")


def _token() -> str:
    out = subprocess.run([_gcloud_exe(), "auth", "print-access-token"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode:
        raise RuntimeError(f"gcloud 取得 Firestore token 失敗：{out.stderr.strip()[:300]}")
    return out.stdout.strip()


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
