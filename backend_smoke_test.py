import argparse
import csv
import json
import os
import time
from pathlib import Path

import requests

# 已部署的 face-basic／face-pro 除了 Cloud Run IAM，還有一層服務自己的 x-api-key
# （見 Face_analyzer_BASIC 的 _api_key_guard），少了它每一支端點都回 401 FORBIDDEN。
# 沒有這個的時候，這支 CLI 實際上只測得到本機開發伺服器。
#
# 金鑰從環境變數取得，不寫進程式也不印出來：
#   $env:FACE_API_KEY = gcloud secrets versions access latest `
#       --secret=decorate-me-face-upstream-key --project decorate-me
# 本機沒有 API key 的開發伺服器不設這個變數即可，行為與先前相同。
FACE_API_KEY = os.getenv("FACE_API_KEY", "").strip()


def _auth_headers(existing=None):
    headers = dict(existing or {})
    if FACE_API_KEY:
        headers["x-api-key"] = FACE_API_KEY
    return headers

# 本檔是可直接執行的線上 smoke-test CLI，不是 pytest 測試模組。函式保留 test_* 名稱
# 方便閱讀既有操作紀錄，但明確禁止 pytest 收集，避免把 CLI 參數誤認成 fixtures。
__test__ = False


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
    kwargs["headers"] = _auth_headers(kwargs.get("headers"))
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


# 圖片安全層（image_safety.py）的拒絕案例。這幾個是「看起來會過、實際上不該過」的
# 輸入：偽 MIME、超大檔、解壓縮炸彈。它們失效時服務照樣回 200，沒有 smoke 就不會有人
# 發現——所以在部署後的實機上也要跑一次（見 issue #28）。
_SAFETY_REJECTION_CODES = {
    "PAYLOAD_TOO_LARGE", "EMPTY_UPLOAD", "UNSUPPORTED_IMAGE_TYPE",
    "INVALID_IMAGE", "IMAGE_TYPE_MISMATCH", "IMAGE_DIMENSIONS_TOO_LARGE",
    "IMAGE_DECODE_TIMEOUT",
}


def _error_code(payload):
    """從錯誤回應取出 error code；envelope 是 {\"error\": {\"code\": ...}}。"""
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return err.get("code", "")
    return ""


def _post_raw(url, filename, content_type, data):
    """送一段原始 bytes 當上傳檔，回 (status_code, json)；不因 4xx 丟例外。"""
    response = requests.post(url, files={"file": (filename, data, content_type)},
                             headers=_auth_headers(), timeout=60)
    try:
        payload = response.json()
    except Exception:
        payload = {"raw": response.text}
    return response.status_code, payload


def test_image_safety_rejections(base_url):
    """實機驗證圖片安全層：壞輸入被擋、好輸入放行（走 /v1/face/pose，同一條 _read_clean_image）。"""
    try:
        import io

        from PIL import Image
    except ImportError:
        print("[SAFETY] Pillow 未安裝，跳過圖片安全拒絕案例")
        return

    url = f"{base_url}/v1/face/pose"

    def png_bytes(w=16, h=16):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (180, 150, 130)).save(buf, format="PNG")
        return buf.getvalue()

    # 1) 偽 MIME：JPEG 檔頭黏上 PNG 內容。只看 magic bytes 會過、只看解碼格式也會過，
    #    兩邊比對才擋得下來。
    forged = b"\xff\xd8\xff\xe0" + png_bytes()
    status, payload = _post_raw(url, "forged.jpg", "image/jpeg", forged)
    code = _error_code(payload)
    if status != 400 or code not in {"INVALID_IMAGE", "IMAGE_TYPE_MISMATCH"}:
        raise RuntimeError(f"[SAFETY] 偽 MIME 未被正確擋下：status={status} code={code}")
    print(f"[SAFETY] fake MIME -> {status} {code}")

    # 2) 不支援的格式：GIF（Pillow 讀得出來，但不在白名單）。
    gif = io.BytesIO()
    Image.new("RGB", (16, 16)).save(gif, format="GIF")
    status, payload = _post_raw(url, "x.gif", "image/gif", gif.getvalue())
    code = _error_code(payload)
    if status != 400 or code != "UNSUPPORTED_IMAGE_TYPE":
        raise RuntimeError(f"[SAFETY] GIF 未被正確擋下：status={status} code={code}")
    print(f"[SAFETY] gif -> {status} {code}")

    # 3) 超大檔：超過位元組上限（預設 8MB），分段讀取應在超限當下就停。
    oversized = b"\xff\xd8\xff\xe0" + b"\x00" * (9 * 1024 * 1024)
    status, payload = _post_raw(url, "big.jpg", "image/jpeg", oversized)
    code = _error_code(payload)
    if status != 413 or code != "PAYLOAD_TOO_LARGE":
        raise RuntimeError(f"[SAFETY] 超大檔未被正確擋下：status={status} code={code}")
    print(f"[SAFETY] oversized -> {status} {code}")

    # 4) 解壓縮炸彈：小小的 PNG 宣告成天文數字尺寸，解碼前先卡像素數才擋得住。
    bomb = io.BytesIO()
    Image.new("L", (12000, 12000)).save(bomb, format="PNG")
    status, payload = _post_raw(url, "bomb.png", "image/png", bomb.getvalue())
    code = _error_code(payload)
    if status != 413 or code != "IMAGE_DIMENSIONS_TOO_LARGE":
        raise RuntimeError(f"[SAFETY] 解壓縮炸彈未被正確擋下：status={status} code={code}")
    print(f"[SAFETY] decompression bomb -> {status} {code} ({len(bomb.getvalue())} bytes on the wire)")

    # 5) 空上傳。
    status, payload = _post_raw(url, "empty.jpg", "image/jpeg", b"")
    code = _error_code(payload)
    if status != 400 or code not in {"EMPTY_UPLOAD", "INVALID_IMAGE"}:
        raise RuntimeError(f"[SAFETY] 空上傳未被正確擋下：status={status} code={code}")
    print(f"[SAFETY] empty -> {status} {code}")

    # 6) 正向對照：一張正常的合成 PNG 應通過安全層。它沒有臉，所以會在臉部偵測
    #    那一步被拒（400），但錯誤碼不能是任何一個圖片安全拒絕碼——那代表安全層
    #    誤擋了正常圖。
    status, payload = _post_raw(url, "ok.png", "image/png", png_bytes(64, 64))
    code = _error_code(payload)
    if code in _SAFETY_REJECTION_CODES:
        raise RuntimeError(f"[SAFETY] 正常 PNG 被安全層誤擋：status={status} code={code}")
    print(f"[SAFETY] valid png passed safety layer -> {status} {code or '(no safety rejection)'}")


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
    test_image_safety_rejections(args.basic_url)
    test_service("BASIC", args.basic_url, "/v1/face/analyze/basic", "/v1/face/jobs/basic", "file", image_path)
    # PRO 測試：正面與側面用同一張圖（smoke test 環境無真實側臉）
    test_service("PRO", args.pro_url, "/v1/face/analyze/pro", "/v1/face/jobs/pro", "front", image_path)
    print("backend smoke test passed")


if __name__ == "__main__":
    main()
