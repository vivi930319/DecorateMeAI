import argparse
import csv
import json
import time
from pathlib import Path

import requests


def iter_smoke_image_candidates():
    auto_labels = Path("data/basic_usable/auto_labels_basic.csv")
    if auto_labels.exists():
        with auto_labels.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "ok":
                    yield Path("data/basic_usable/raw_images") / row["image_id"]

    preferred_dirs = [
        Path("data/basic_usable/raw_images"),
        Path("data/asian_faces/DCleaning_tool/raw_images"),
        Path("data"),
    ]
    for base_dir in preferred_dirs:
        if not base_dir.exists():
            continue
        pattern = "**/*.jpg" if base_dir.name != "raw_images" else "*.jpg"
        for candidate in base_dir.glob(pattern):
            yield candidate


def pick_default_image():
    seen = set()
    for candidate in iter_smoke_image_candidates():
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    raise SystemExit(
        "No smoke-test image found. Checked data/basic_usable/raw_images and fallback image folders."
    )


def request_json(method, url, **kwargs):
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 180), **kwargs)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    if not response.ok:
        raise RuntimeError(f"{method} {url} failed: {response.status_code} {json.dumps(payload, ensure_ascii=False)}")
    return payload


def post_image(url, field_name, image_path, extra_files=None):
    files = {field_name: (image_path.name, image_path.open("rb"), "image/jpeg")}
    opened = [files[field_name][1]]
    try:
        for key, path in (extra_files or {}).items():
            handle = Path(path).open("rb")
            opened.append(handle)
            files[key] = (Path(path).name, handle, "image/jpeg")
        return request_json("POST", url, files=files)
    finally:
        for handle in opened:
            handle.close()


def wait_for_job(base_url, job_id, result_token=None):
    status_url = f"{base_url}/v1/face/jobs/{job_id}"
    headers = {"X-Job-Token": result_token} if result_token else None
    for _ in range(120):
        job = request_json("GET", status_url, timeout=30, headers=headers)
        if job.get("status") in {"completed", "failed"}:
            return job
        time.sleep(1)
    raise RuntimeError(f"Job timed out: {job_id}")


def assert_result_shape(result, mode):
    if result.get("status") != "completed":
        raise RuntimeError(f"{mode} job did not complete: {json.dumps(result, ensure_ascii=False)}")
    payload = result.get("result") or {}

    required = ["臉型", "眉型", "眼型", "鼻型", "嘴型", "膚色", "嘴唇_LAB", "臉部對稱性"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"{mode} result missing keys: {missing}")

    sym = payload.get("臉部對稱性")
    if sym is not None:
        for sym_key in ("score", "eyeOpenRatio", "noseDeviation", "mouthSymmetry"):
            if sym_key not in sym:
                raise RuntimeError(f"{mode} 臉部對稱性 missing '{sym_key}'")
        score = sym["score"]
        if not (0 <= score <= 100):
            raise RuntimeError(f"{mode} 臉部對稱性 score out of range: {score}")

    if mode == "PRO":
        pro_status = payload.get("精細分析狀態")
        if pro_status is None:
            raise RuntimeError("PRO result missing 精細分析狀態")
        for v in pro_status.values():
            if v == "待實作":
                raise RuntimeError(f"PRO 精細分析狀態 still has placeholder '待實作': {pro_status}")
        if payload.get("分析版本") != "PRO":
            raise RuntimeError(f"PRO result has wrong 分析版本: {payload.get('分析版本')}")


def test_pose(base_url, image_path):
    print("[BASIC] /v1/face/pose")
    result = post_image(f"{base_url}/v1/face/pose", "file", image_path)
    for key in ("yaw", "pitch", "roll", "captureRole", "side", "confidence"):
        if key not in result:
            raise RuntimeError(f"pose result missing key: '{key}'")
    if result["captureRole"] not in {"front", "side", "angle45", "turning"}:
        raise RuntimeError(f"pose captureRole unexpected: {result['captureRole']}")
    if result["side"] not in {"left", "right"}:
        raise RuntimeError(f"pose side unexpected: {result['side']}")
    print(json.dumps(result, ensure_ascii=False))


def test_service(name, base_url, sync_path, job_path, file_field, image_path):
    print(f"[{name}] health")
    health = request_json("GET", f"{base_url}/health")
    if health.get("status") != "ok":
        raise RuntimeError(f"{name} /health not ok: {health}")
    print(json.dumps(health, ensure_ascii=False))

    print(f"[{name}] sync analyze")
    sync_result = post_image(f"{base_url}{sync_path}", file_field, image_path)
    print(json.dumps({k: sync_result.get(k) for k in ["分析版本", "臉型", "眼型", "鼻型", "臉部對稱性"]}, ensure_ascii=False))

    print(f"[{name}] create async job")
    job = post_image(f"{base_url}{job_path}", file_field, image_path)
    job_id = job["jobId"]
    result_token = job.get("resultToken")
    print(json.dumps(job, ensure_ascii=False))

    print(f"[{name}] poll async job")
    completed_job = wait_for_job(base_url, job_id, result_token=result_token)
    print(json.dumps(completed_job, ensure_ascii=False))

    print(f"[{name}] get async result")
    headers = {"X-Job-Token": result_token} if result_token else None
    result = request_json("GET", f"{base_url}/v1/face/jobs/{job_id}/result", headers=headers)
    assert_result_shape(result, name)
    sym_score = (result.get("result") or {}).get("臉部對稱性", {})
    sym_score = sym_score.get("score") if isinstance(sym_score, dict) else None
    print(json.dumps({
        "jobId": job_id,
        "status": result.get("status"),
        "version": result.get("result", {}).get("分析版本"),
        "symmetryScore": sym_score,
    }, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Smoke test Face Analysis BASIC/PRO backend services.")
    parser.add_argument("--image", default=None)
    parser.add_argument("--basic-url", default="http://127.0.0.1:8001")
    parser.add_argument("--pro-url", default="http://127.0.0.1:8002")
    args = parser.parse_args()

    image_path = Path(args.image) if args.image else pick_default_image()
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")

    print(f"image={image_path}")
    test_pose(args.basic_url, image_path)
    test_service("BASIC", args.basic_url, "/v1/face/analyze/basic", "/v1/face/jobs/basic", "file", image_path)
    # PRO 測試：正面與側面用同一張圖（smoke test 環境無真實側臉）
    test_service("PRO", args.pro_url, "/v1/face/analyze/pro", "/v1/face/jobs/pro", "front", image_path)
    print("backend smoke test passed")


if __name__ == "__main__":
    main()
