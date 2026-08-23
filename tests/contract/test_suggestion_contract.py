"""POST /suggest（Ollama 文字建議）— suggestion、renderPromptEn 契約。

實際 URL 經 Gateway 同源代理：`/<gateway>/text-suggestion/suggest`
（見 js/api.js `Api.suggestMakeup`）。canonical 回傳欄位另見
`正式主題與Ollama契約部署測試_2026-08-10.md`：
status, provider, model, fallbackUsed, createdAt, suggestion, renderPromptEn,
fluxPromptEn, promptSignature。目前沒有 structured 的 overall/parts 欄位。
"""
import os

import pytest

from conftest import error_payload

SUGGEST_PATH = "/text-suggestion/suggest"

# 結構測試不需要真的分析結果，只要欄位存在即可觸發 Ollama 契約層。
_MINIMAL_FACE_ANALYSIS = {"faceShape": "oval", "skinTone": {"L": 60, "a": 10, "b": 15}}


@pytest.fixture(scope="session")
def sample_style():
    return os.environ.get("DM_TEST_STYLE", "richGirl").strip() or "richGirl"


def test_unauthenticated_returns_401(http, gateway_base_url, sample_style):
    res = http.request(
        "POST", f"{gateway_base_url}{SUGGEST_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": sample_style, "language": "zh-TW"},
    )
    assert res.status_code == 401, res.text
    err = error_payload(res)
    assert err and err.get("code") == "MEMBER_AUTH_REQUIRED", err


def test_missing_face_analysis_returns_4xx_or_flags_it(member_session, gateway_base_url, sample_style):
    """缺少 faceAnalysis 時，要嘛拒絕，要嘛**明講這次沒用到分析結果**。

    2026-08-14 契約變更：Ollama 端改成不拒絕，照樣回 200 與一份通用建議，
    但在回應裡加了 `faceAnalysisUsed` 與 `missingFields`。

    為什麼接受這個設計：使用者拿到建議總比看到錯誤好。
    **但前提是消費端要能分辨這份建議有沒有用到他的臉**——否則畫面會顯示一段
    跟他無關的內容，而且沒有任何跡象。所以這個測試現在守的是那個旗標，
    不是狀態碼：可以不拒絕，但不可以「安靜地給通用答案」。
    """
    res = member_session.post(
        f"{gateway_base_url}{SUGGEST_PATH}",
        json={"style": sample_style, "language": "zh-TW"},
    )
    if 400 <= res.status_code < 500:
        return
    assert res.status_code == 200, f"預期 4xx 或 200，實際 {res.status_code}：{res.text[:200]}"
    body = res.json()
    assert body.get("faceAnalysisUsed") is False, (
        "缺 faceAnalysis 卻回 200，就必須用 faceAnalysisUsed=false 明講；"
        f"目前回應沒有這個旗標或值不對：{ {k: body.get(k) for k in ('faceAnalysisUsed', 'missingFields')} }"
    )
    assert body.get("missingFields"), "應列出缺了哪些欄位，否則無從追查是誰沒送"


def test_wrong_type_face_analysis_returns_4xx(member_session, gateway_base_url, sample_style):
    """faceAnalysis 傳字串而非物件：型別錯誤案例。"""
    res = member_session.post(
        f"{gateway_base_url}{SUGGEST_PATH}",
        json={"faceAnalysis": "not-an-object", "style": sample_style, "language": "zh-TW"},
    )
    assert 400 <= res.status_code < 500, f"faceAnalysis 型別錯誤應回 4xx，實際 {res.status_code}：{res.text}"


def test_unknown_style_returns_4xx_not_500(member_session, gateway_base_url):
    """style 不在已知映射表：應是明確的業務錯誤，不是未預期的 500。"""
    res = member_session.post(
        f"{gateway_base_url}{SUGGEST_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": "not-a-real-style-xyz", "language": "zh-TW"},
    )
    assert res.status_code < 500, f"未知 style 不應觸發伺服器錯誤，實際 {res.status_code}：{res.text}"


def _skip_if_style_unsupported(res):
    """實測：派工書 analysisPackage 範例用的 style='richGirl' 會被建議服務以 422
    VALIDATION_ERROR「不支援的妝容風格」拒絕，rich_girl / natural / korean 等常見猜測
    也都不通。合法的 style 列舉值需由第 3 人（style 映射）交付，否則 happy-path 無法測。"""
    if res.status_code == 422:
        err = error_payload(res) or {}
        if err.get("code") == "VALIDATION_ERROR" and "風格" in str(err.get("message", "")):
            pytest.skip(
                f"建議服務不接受目前的 style（{err.get('message')}）。"
                " 需要第 3 人提供合法 style 列舉值，設定 DM_TEST_STYLE 後再測 happy-path。"
            )


def test_suggestion_contract_shape(member_session, gateway_base_url, sample_style):
    res = member_session.post(
        f"{gateway_base_url}{SUGGEST_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": sample_style, "language": "zh-TW"},
    )
    _skip_if_style_unsupported(res)
    assert res.status_code == 200, f"合法請求應成功，實際 {res.status_code}：{res.text}"
    data = res.json()
    for key in ("status", "provider", "suggestion", "renderPromptEn"):
        assert key in data, f"suggestion 回應缺少必要欄位 {key}：{data}"
    assert data["status"] == "completed", f"預期 status=completed，實際：{data['status']}"
    # 2026-08-14 契約變更：`suggestion` 從一段中文字串變成結構化物件
    #   {"overall": {"summary": ...}, "parts": {base, eyebrow, eyes, cheeks, lips}}
    # 前端的 makeup-contract.js 兩種都吃（同日修正），這裡也兩種都認。
    # 要守住的是「有內容」，不是「是字串」——先前寫死型別，對方一改結構就變紅，
    # 而那次它其實是升級不是壞掉。
    suggestion = data["suggestion"]
    if isinstance(suggestion, str):
        assert suggestion.strip(), "suggestion 是字串時不得為空"
    else:
        assert isinstance(suggestion, dict), f"suggestion 應為字串或結構化物件，實際 {type(suggestion)}"
        summary = ((suggestion.get("overall") or {}).get("summary") or "").strip()
        parts = suggestion.get("parts") or {}
        assert summary, f"結構化 suggestion 缺少 overall.summary：{suggestion}"
        assert parts, f"結構化 suggestion 缺少 parts：{suggestion}"
    # 英文渲染 prompt 只給渲染端用，不該是空字串（正式前端已不再顯示它，但契約上仍要存在）。
    assert isinstance(data["renderPromptEn"], str) and data["renderPromptEn"].strip(), (
        "renderPromptEn 應為非空字串，供渲染端使用"
    )


def test_suggestion_does_not_log_full_prompt_back_to_client_unexpectedly(member_session, gateway_base_url, sample_style):
    """Log 與錯誤訊息不得包含完整 Prompt；這裡至少確認成功回應沒有把內部 system prompt 原樣吐回。"""
    res = member_session.post(
        f"{gateway_base_url}{SUGGEST_PATH}",
        json={"faceAnalysis": _MINIMAL_FACE_ANALYSIS, "style": sample_style, "language": "zh-TW"},
    )
    _skip_if_style_unsupported(res)
    assert res.status_code == 200, res.text
    body_text = res.text
    for leaked_marker in ("SYSTEM PROMPT", "system_prompt", "OLLAMA_API_KEY", "tku_im_makeup_secret"):
        assert leaked_marker not in body_text, f"回應疑似洩漏內部 prompt 或金鑰片段：{leaked_marker}"
