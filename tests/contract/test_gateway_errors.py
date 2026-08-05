"""統一錯誤格式（派工書「統一錯誤格式」那張表）。

每個錯誤都要有 HTTP、code、message，並且不得洩漏 Token、Email、照片、
完整 Prompt、Admin Key 或 Secret。
"""
import re

import requests

from conftest import TIMEOUT, body, error_of

# 找的是「值」不是「欄位名」。驗證錯誤會回 body.password 這種欄位路徑指出哪一欄缺了，
# 那是正常且有用的訊息；把裸字 password 當標記會把它誤判成外洩。
LEAK_MARKERS = ("admin_api_key", "x-admin-key", "adminkey", "client_secret",
                "-----begin", "data:image")
LEAK_PATTERNS = (
    re.compile(r'"password"\s*:\s*"[^"]+"', re.I),      # 帶值的密碼欄位
    re.compile(r"bearer\s+[A-Za-z0-9._-]{16,}", re.I),  # 實際的 token
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),               # API 金鑰樣式
    re.compile(r"eyJ[A-Za-z0-9_-]{20,}\."),             # JWT
)


def _assert_no_leak(response, where):
    lowered = response.text.lower()
    for marker in LEAK_MARKERS:
        assert marker not in lowered, f"{where} 回應疑似外洩 {marker!r}"
    for pattern in LEAK_PATTERNS:
        hit = pattern.search(response.text)
        assert not hit, f"{where} 回應疑似外洩（樣式 {pattern.pattern}）"


def test_unauthenticated_shape(base):
    r = requests.get(f"{base}/auth/session", timeout=TIMEOUT)
    assert r.status_code == 401
    err = error_of(body(r))
    assert err.get("code"), f"401 沒有 error.code：{body(r)}"
    assert err.get("message"), f"401 沒有 error.message：{body(r)}"
    _assert_no_leak(r, "/auth/session")


def test_not_found_shape(base):
    r = requests.get(f"{base}/product-api/api/definitely-not-a-route", timeout=TIMEOUT)
    assert r.status_code in (404, 400), r.status_code
    _assert_no_leak(r, "不存在的路由")


def test_error_bodies_never_leak_secrets(base):
    """把幾個會出錯的端點都掃一遍，確認錯誤訊息不外流敏感資訊。"""
    probes = [
        ("GET", "/auth/session", None),
        ("POST", "/auth/login", {}),
        ("POST", "/auth/login", {"email": "x@example.com", "password": "wrong"}),
        ("GET", "/admin-api/api/admin/product-audit-logs", None),
    ]
    for method, path, payload in probes:
        r = (requests.get(f"{base}{path}", timeout=TIMEOUT) if method == "GET"
             else requests.post(f"{base}{path}", json=payload, timeout=TIMEOUT))
        _assert_no_leak(r, f"{method} {path}")


def test_error_code_is_stable_string(base):
    """error.code 要是可供程式判斷的穩定字串，不是句子。"""
    r = requests.get(f"{base}/auth/session", timeout=TIMEOUT)
    code = error_of(body(r)).get("code", "")
    assert code and code.replace("_", "").isalnum() and code.upper() == code, (
        f"error.code 不是穩定的大寫代碼：{code!r}"
    )
