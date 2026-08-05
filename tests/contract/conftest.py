"""契約測試共用設定（派工書：陳語宸_API認證Gateway與契約測試）。

所有 Base URL、帳密與金鑰都從環境變數取得，不寫進程式、不進報告。

    $env:CONTRACT_BASE       = "https://decorate-me.web.app"   # 預設值，可不設
    $env:CONTRACT_GATEWAY    = "https://ai-gateway-eu5pq7c53a-de.a.run.app"
    $env:FACE_API_KEY        = gcloud secrets versions access latest `
                                 --secret=decorate-me-face-upstream-key --project decorate-me
    $env:CONTRACT_BASIC_URL  = "http://127.0.0.1:8001"   # gcloud run services proxy face-basic
    $env:CONTRACT_PRO_URL    = "http://127.0.0.1:8002"   # gcloud run services proxy face-pro
    $env:CONTRACT_EMAIL / $env:CONTRACT_PASSWORD          # 一般會員測試帳號
    $env:CONTRACT_ADMIN_EMAIL / $env:CONTRACT_ADMIN_PASSWORD

沒設的部分對應的測試會 skip 並寫明原因，判定為 BLOCKED 而不是 PASS。
"""
import io
import os

import pytest
import requests

BASE = os.getenv("CONTRACT_BASE", "https://decorate-me.web.app").rstrip("/")
GATEWAY = os.getenv("CONTRACT_GATEWAY", "").rstrip("/")
FACE_KEY = os.getenv("FACE_API_KEY", "").strip()
BASIC_URL = os.getenv("CONTRACT_BASIC_URL", "").rstrip("/")
PRO_URL = os.getenv("CONTRACT_PRO_URL", "").rstrip("/")

TIMEOUT = 90


def face_headers(extra=None):
    h = dict(extra or {})
    if FACE_KEY:
        h["x-api-key"] = FACE_KEY
    return h


def png_bytes(w=64, h=64, colour=(200, 200, 200)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def error_of(payload):
    """把統一錯誤格式從各種包法裡挖出來（有的在頂層，有的包在 detail 底下）。"""
    if not isinstance(payload, dict):
        return {}
    return payload.get("error") or (payload.get("detail") or {}).get("error") or {}


def body(response):
    try:
        return response.json()
    except Exception:
        return {"raw": response.text[:400]}


@pytest.fixture(scope="session")
def base():
    return BASE


@pytest.fixture(scope="session")
def gateway():
    if not GATEWAY:
        pytest.skip("BLOCKED：未設定 CONTRACT_GATEWAY")
    return GATEWAY


@pytest.fixture(scope="session")
def basic_url():
    if not BASIC_URL:
        pytest.skip("BLOCKED：未設定 CONTRACT_BASIC_URL（需 gcloud run services proxy face-basic）")
    return BASIC_URL


@pytest.fixture(scope="session")
def pro_url():
    if not PRO_URL:
        pytest.skip("BLOCKED：未設定 CONTRACT_PRO_URL（需 gcloud run services proxy face-pro）")
    return PRO_URL


@pytest.fixture(scope="session")
def face_image():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for pattern in ("data/kaggle_asian_faces/generated_yellow-stylegan2/*.png",
                    "data/basic_usable/raw_images/*.jpg"):
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0].read_bytes()
    pytest.skip("BLOCKED：找不到含人臉的測試照片")


@pytest.fixture(scope="session")
def side_image():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    # 用 glob 而不是列目錄：資料夾裡有 .DS_Store 之類的非圖片檔，列目錄會抓到它，
    # 上傳後被圖片安全層擋成 400，看起來像服務壞了，其實是測試自己挑錯檔案。
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        hits = sorted(root.glob(f"data/pro_full/grouped/nose_shape_side/*/{ext}"))
        if hits:
            return hits[0].read_bytes()
    pytest.skip("BLOCKED：找不到側面測試照片")


@pytest.fixture(scope="session")
def member_session():
    """一般會員登入後的 session；沒有測試帳號就 skip。"""
    email = os.getenv("CONTRACT_EMAIL", "")
    password = os.getenv("CONTRACT_PASSWORD", "")
    if not (email and password):
        pytest.skip("BLOCKED：未設定 CONTRACT_EMAIL / CONTRACT_PASSWORD")
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"BLOCKED：測試帳號登入失敗 HTTP {r.status_code}（見 issue #29 / #34）")
    return s


@pytest.fixture(scope="session")
def admin_session():
    email = os.getenv("CONTRACT_ADMIN_EMAIL", "")
    password = os.getenv("CONTRACT_ADMIN_PASSWORD", "")
    if not (email and password):
        pytest.skip("BLOCKED：未設定 CONTRACT_ADMIN_EMAIL / CONTRACT_ADMIN_PASSWORD")
    s = requests.Session()
    r = s.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"BLOCKED：admin 帳號登入失敗 HTTP {r.status_code}（見 issue #30）")
    return s
