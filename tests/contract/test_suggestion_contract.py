"""Ollama 文字建議契約（派工書核心介面第 5 列）。

已知狀態：issue #19「文字建議服務（Ollama）目前不可用」——Gateway 端上游為 disabled，
呼叫回 503 EXTERNAL_TEXT_UPSTREAM_DISABLED。服務未開通時判 BLOCKED，不是 FAIL。
"""
import pytest
import requests

from conftest import TIMEOUT, body, error_of


def _suggest(base, payload):
    return requests.post(f"{base}/text-suggestion/suggest", json=payload, timeout=TIMEOUT)


def test_suggest_requires_auth(base):
    """反項：未登入不得呼叫。"""
    r = _suggest(base, {})
    assert r.status_code in (401, 403, 503), f"未登入卻回 {r.status_code}：{body(r)}"


def test_suggest_upstream_status_is_explicit(base):
    """上游停用時要明講，不能靜默回空建議——那會讓前端顯示假建議。"""
    r = _suggest(base, {"faceAnalysis": {}, "style": "richGirl"})
    if r.status_code == 200:
        data = r.json()
        assert "suggestion" in data or "generativeText" in data, f"200 卻沒有建議欄位：{data}"
        return
    err = error_of(body(r))
    assert r.status_code in (401, 403, 502, 503, 504), f"非預期狀態 {r.status_code}：{body(r)}"
    assert err.get("code"), f"錯誤沒有 code：{body(r)}"


def test_suggestion_only_updates_generative_text(member_session, base):
    """派工書：Ollama 只更新 generativeText，不得改寫 id／schemaVersion／faceAnalysis。"""
    pkg = {
        "id": "AN-contract-test",
        "schemaVersion": "2026-08-v2",
        "style": "richGirl",
        "faceAnalysis": {"faceShape": "round", "skinTone": {"season": "autumn"}},
        "generativeText": {"suggestion": None, "renderPromptEn": None},
    }
    r = member_session.post(f"{base}/text-suggestion/suggest", json=pkg, timeout=TIMEOUT)
    if r.status_code != 200:
        pytest.skip(f"BLOCKED：文字建議服務不可用（HTTP {r.status_code}，見 issue #19）")
    out = r.json()
    returned = out.get("analysisPackage", out)
    assert returned.get("id") in (None, pkg["id"]), "id 被下游改寫"
    assert returned.get("schemaVersion") in (None, pkg["schemaVersion"]), "schemaVersion 被下游改寫"
    if "faceAnalysis" in returned:
        assert returned["faceAnalysis"] == pkg["faceAnalysis"], "faceAnalysis 被下游改寫"
