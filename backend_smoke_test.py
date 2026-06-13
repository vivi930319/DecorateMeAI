import argparse
import csv
import json
import time
from pathlib import Path

import requests


def pick_default_image():
    auto_labels = Path("data/basic_usable/auto_labels_basic.csv")
    if auto_labels.exists():
        with auto_labels.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status") == "ok":
                    candidate = Path("data/basic_usable/raw_images") / row["image_id"]
                    if candidate.exists():
                        return candidate

    raw_dir = Path("data/basic_usable/raw_images")
    first = next(raw_dir.glob("*.jpg"), None) if raw_dir.exists() else None
    if first:
        return first

    raise SystemExit("No smoke-test image found. Run select_basic_usable_images.py first.")


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


def wait_for_job(base_url, job_id):
    status_url = f"{base_url}/v1/face/jobs/{job_id}"
    for _ in range(120):
        job = request_json("GET", status_url, timeout=30)
        if job.get("status") in {"completed", "failed"}:
            return job
        time.sleep(1)
    raise RuntimeError(f"Job timed out: {job_id}")


def assert_result_shape(result, mode):
    if result.get("status") != "completed":
        raise RuntimeError(f"{mode} job did not complete: {json.dumps(result, ensure_ascii=False)}")
    payload = result.get("result") or {}
    required = ["臉型", "眉型", "眼型", "鼻型", "嘴型", "膚色"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"{mode} result missing keys: {missing}")


def test_service(name, base_url, sync_path, job_path, file_field, image_path):
    print(f"[{name}] health")
    health = request_json("GET", f"{base_url}/health")
    print(json.dumps(health, ensure_ascii=False))

    print(f"[{name}] sync analyze")
    sync_result = post_image(f"{base_url}{sync_path}", file_field, image_path)
    print(json.dumps({k: sync_result.get(k) for k in ["分析版本", "臉型", "眼型", "鼻型"]}, ensure_ascii=False))

    print(f"[{name}] create async job")
    job = post_image(f"{base_url}{job_path}", file_field, image_path)
    job_id = job["jobId"]
    print(json.dumps(job, ensure_ascii=False))

    print(f"[{name}] poll async job")
    completed_job = wait_for_job(base_url, job_id)
    print(json.dumps(completed_job, ensure_ascii=False))

    print(f"[{name}] get async result")
    result = request_json("GET", f"{base_url}/v1/face/jobs/{job_id}/result")
    assert_result_shape(result, name)
    print(json.dumps({"jobId": job_id, "status": result.get("status"), "version": result.get("result", {}).get("分析版本")}, ensure_ascii=False))


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
    test_service("BASIC", args.basic_url, "/v1/face/analyze/basic", "/v1/face/jobs/basic", "file", image_path)
    test_service("PRO", args.pro_url, "/v1/face/analyze/pro", "/v1/face/jobs/pro", "front", image_path)
    print("backend smoke test passed")


if __name__ == "__main__":
    main()
