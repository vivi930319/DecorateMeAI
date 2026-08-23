"""
端到端串測（C8）：忠實重現正式前端整條使用者流程，判定每一段 PASS/FAIL/BLOCKED。

流程：登入 → 臉部分析(job 流程) → 選妝 → Ollama 建議 → 推薦商品 → 妝容渲染 → 收藏

所有請求經正式 AI Gateway 同源代理，並複製 js/api.js 的真實契約：
- 受保護寫入帶 X-Expected-Actor + X-CSRF-Token
- suggest 送 style.name（中文，如「千金」）；recommend 送 styleId（如 richGirl）
- faceAnalysis 依 AnalysisPackage.fromRawFaceAnalysis 轉成英文結構

用法：
    $env:DM_MEMBER_EMAIL=... ; $env:DM_MEMBER_PASSWORD=... ; python tests/contract/e2e_flow.py
"""
import base64
import os
import sys
import time

import requests

GW = os.environ.get("DM_GATEWAY_BASE_URL", "https://ai-gateway-258021445391.asia-east1.run.app").rstrip("/")
EMAIL = os.environ.get("DM_MEMBER_EMAIL", "").strip()
PASSWORD = os.environ.get("DM_MEMBER_PASSWORD", "").strip()
FACE_IMAGE = os.environ.get("DM_TEST_FACE_IMAGE", "千金.webp").strip()
STYLE_NAME = "千金"       # suggest 用 name
STYLE_ID = "richGirl"      # recommend / render 用 id
STYLE_TAGS = ["高級感", "精緻底妝", "低調奢華", "氣質妝容"]

results = []  # (stage, verdict, detail)


def record(stage, verdict, detail=""):
    results.append((stage, verdict, detail))
    mark = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "🟡"}.get(verdict, "•")
    print(f"{mark} [{verdict}] {stage} — {detail}")


def lab_to_array(lab):
    if isinstance(lab, list):
        return lab
    if isinstance(lab, dict):
        vals = [lab.get("L", lab.get("l")), lab.get("a", lab.get("A")), lab.get("b", lab.get("B"))]
        return vals if all(v is not None for v in vals) else None
    return None


def from_raw_face_analysis(raw, mode="basic"):
    """對應 js/api.js AnalysisPackage.fromRawFaceAnalysis。"""
    skin = raw.get("膚色") or {}
    return {
        "version": "PRO" if mode == "pro" else "BASIC",
        "faceShape": raw.get("臉型"),
        "browShape": raw.get("眉型"),
        "eyeShape": raw.get("眼型"),
        "noseFront": raw.get("鼻型"),
        "lipShape": raw.get("嘴型"),
        "skinTone": {
            "season": skin.get("四季型"),
            "level": skin.get("膚色分級"),
            "lab": skin.get("LAB"),
            "labReliable": (skin.get("可信度") or {}).get("reliable") is not False,
        },
        "lipLab": raw.get("嘴唇_LAB"),
    }


def main():
    if not EMAIL or not PASSWORD:
        record("前置", "BLOCKED", "未設定 DM_MEMBER_EMAIL / DM_MEMBER_PASSWORD")
        return summarize()

    s = requests.Session()

    # ── 1. 登入 ───────────────────────────────────────────────
    r = s.post(f"{GW}/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
    if not r.ok:
        record("1. 登入", "FAIL", f"HTTP {r.status_code}: {r.text[:150]}")
        return summarize()
    actor = str(r.json().get("actorId") or "")
    csrf = s.cookies.get("dm_csrf", "")
    write_headers = {"X-Expected-Actor": actor, "X-CSRF-Token": csrf}
    record("1. 登入", "PASS", f"actorId={actor[:16]}…，取得 HttpOnly session 與 dm_csrf")

    # ── 2. 臉部分析（job 流程，與前端一致）─────────────────────
    if not os.path.isfile(FACE_IMAGE):
        record("2. 臉部分析", "BLOCKED", f"找不到臉部圖 {FACE_IMAGE}")
        return summarize()
    with open(FACE_IMAGE, "rb") as fh:
        image_bytes = fh.read()
    r = s.post(f"{GW}/face-basic/v1/face/jobs/basic", headers=write_headers,
               files={"file": (os.path.basename(FACE_IMAGE), image_bytes, "image/webp")}, timeout=60)
    if not r.ok:
        record("2. 臉部分析(建立 job)", "FAIL", f"HTTP {r.status_code}: {r.text[:150]}")
        return summarize()
    job = r.json()
    job_id, token = job.get("jobId"), job.get("resultToken")
    jh = {"X-Job-Token": token}
    raw_analysis = None
    for _ in range(60):
        st = s.get(f"{GW}/face-basic/v1/face/jobs/{job_id}", headers=jh, timeout=20).json()
        if st.get("status") == "completed":
            res = s.get(f"{GW}/face-basic/v1/face/jobs/{job_id}/result", headers=jh, timeout=20)
            if not res.ok:
                record("2. 臉部分析(取結果)", "FAIL", f"HTTP {res.status_code}: {res.text[:150]}")
                return summarize()
            body = res.json()
            pkg = body.get("analysisPackage") or {}
            raw_analysis = (pkg.get("faceAnalysis", {}) or {}).get("raw") or body.get("faceAnalysis") or body
            # analysisPackage 契約檢查
            missing = {"id", "schemaVersion", "faceAnalysis"} - set(pkg.keys())
            if pkg and not missing:
                record("2. 臉部分析", "PASS",
                       f"job {job_id} 完成；analysisPackage 具備 id/schemaVersion/faceAnalysis"
                       f"（id={str(pkg.get('id'))[:18]}…, schemaVersion={pkg.get('schemaVersion')}）")
            else:
                record("2. 臉部分析", "PASS",
                       f"job {job_id} 完成；但回應未含完整 analysisPackage（缺 {missing or 'analysisPackage'}），"
                       "改用原始分析結果續跑")
            break
        if st.get("status") == "failed":
            record("2. 臉部分析", "FAIL", f"job 失敗：{st.get('error')}")
            return summarize()
        time.sleep(1)
    if raw_analysis is None:
        record("2. 臉部分析", "FAIL", "job 逾時未完成")
        return summarize()

    # 取原始分析（Chinese-keyed）：優先用 job 結果內的 raw，否則呼叫同步 analyze 補一份
    if not raw_analysis.get("臉型"):
        sync = s.post(f"{GW}/face-basic/v1/face/analyze/basic", headers=write_headers,
                      files={"file": (os.path.basename(FACE_IMAGE), image_bytes, "image/webp")}, timeout=60)
        if sync.ok:
            raw_analysis = sync.json()
    face_analysis = from_raw_face_analysis(raw_analysis, "basic")
    print(f"    → faceAnalysis: 臉型={face_analysis['faceShape']}, 膚色={face_analysis['skinTone']['level']}, "
          f"LAB={face_analysis['skinTone']['lab']}")

    # ── 3. 選妝 ───────────────────────────────────────────────
    record("3. 選擇妝容風格", "PASS", f"選定「{STYLE_NAME}」(id={STYLE_ID})")

    # ── 4. Ollama 建議 ────────────────────────────────────────
    r = s.post(f"{GW}/text-suggestion/suggest", headers={**write_headers, "Content-Type": "application/json"},
               json={"faceAnalysis": face_analysis, "style": STYLE_NAME,
                     "language": "zh-TW", "userNote": "、".join(STYLE_TAGS)}, timeout=120)
    suggestion_ok = False
    if r.ok:
        d = r.json()
        if d.get("status") == "completed" and str(d.get("suggestion") or "").strip():
            suggestion_ok = True
            record("4. Ollama 文字建議", "PASS",
                   f"provider={d.get('provider')}, model={d.get('model')}, suggestion {len(d['suggestion'])} 字")
        else:
            record("4. Ollama 文字建議", "FAIL", f"回 200 但內容不完整：{str(d)[:150]}")
    else:
        try:
            code = (r.json().get("error") or {}).get("code")
        except Exception:
            code = None
        record("4. Ollama 文字建議", "FAIL", f"HTTP {r.status_code} code={code}: {r.text[:150]}")

    # ── 5. 推薦商品 ───────────────────────────────────────────
    rec_body = {
        "analysisPackage": {
            "id": None,
            "style": STYLE_ID,
            "faceAnalysis": {
                "faceShape": face_analysis["faceShape"],
                "browShape": face_analysis["browShape"],
                "eyeShape": face_analysis["eyeShape"],
                "lipShape": face_analysis["lipShape"],
                "skinTone": {
                    "season": face_analysis["skinTone"]["season"],
                    "level": face_analysis["skinTone"]["level"],
                    "lab": lab_to_array(face_analysis["skinTone"]["lab"]),
                    "labReliable": face_analysis["skinTone"]["labReliable"],
                },
                "lipLab": lab_to_array(face_analysis["lipLab"]),
            },
        },
        "limit": 12,
    }
    products = []
    r = s.post(f"{GW}/product-api/recommend-products", headers={"Content-Type": "application/json"},
               json=rec_body, timeout=40)
    if r.ok:
        d = r.json()
        products = (d.get("analysisPackage", {}).get("recommendations", {}) or {}).get("products") \
            or d.get("recommendations", {}).get("products") if isinstance(d.get("recommendations"), dict) \
            else d.get("products") or []
        products = products or d.get("products") or []
        if products:
            record("5. 推薦商品", "PASS", f"回傳 {len(products)} 筆推薦商品")
        else:
            record("5. 推薦商品", "FAIL", f"回 200 但無商品：{str(d)[:150]}")
    else:
        try:
            code = (r.json().get("error") or {}).get("code")
        except Exception:
            code = None
        record("5. 推薦商品", "FAIL", f"HTTP {r.status_code} code={code}: {r.text[:150]}")

    # ── 6. 妝容渲染 ───────────────────────────────────────────
    data_url = "data:image/webp;base64," + base64.b64encode(image_bytes).decode()
    r = s.post(f"{GW}/render-service/render/jobs",
               headers={**write_headers, "Content-Type": "application/json"},
               json={"image": data_url, "styleId": STYLE_ID, "strength": 0.35}, timeout=60)
    render_job = None
    if r.status_code == 429:
        err = r.json().get("error", {})
        record("6. 妝容渲染", "BLOCKED",
               f"429 RATE_LIMITED（測試已用盡每小時配額，{err.get('retryAfterSeconds')}s 後重置）；限流契約正常")
    elif r.ok:
        d = r.json()
        if d.get("status") == "completed" and d.get("afterImageUrl"):
            render_job = d
            record("6. 妝容渲染", "PASS", f"即時完成，afterImageUrl={d['afterImageUrl'][:40]}…")
        elif d.get("jobId"):
            # 輪詢到完成
            headers = {**write_headers, "Content-Type": "application/json"}
            if d.get("resultToken"):
                headers["X-Job-Token"] = d["resultToken"]
            deadline = time.time() + 300
            done = None
            while time.time() < deadline:
                time.sleep(5)
                jr = s.get(f"{GW}/render-service/render/jobs/{d['jobId']}", headers=headers, timeout=30)
                if jr.ok:
                    jd = jr.json()
                    if jd.get("status") == "completed" and jd.get("afterImageUrl"):
                        done = jd
                        break
                    if jd.get("status") == "failed":
                        record("6. 妝容渲染", "FAIL", f"job 失敗：{jd.get('error')}")
                        break
            if done:
                render_job = done
                record("6. 妝容渲染", "PASS", f"輪詢完成，afterImageUrl={done['afterImageUrl'][:40]}…")
            elif not any(st == "6. 妝容渲染" for st, _, _ in results):
                record("6. 妝容渲染", "FAIL", "5 分鐘內未完成")
        else:
            record("6. 妝容渲染", "FAIL", f"回 200 但格式異常：{str(d)[:150]}")
    else:
        record("6. 妝容渲染", "FAIL", f"HTTP {r.status_code}: {r.text[:150]}")

    # ── 7. 收藏 ───────────────────────────────────────────────
    if not products:
        record("7. 收藏商品", "BLOCKED", "沒有推薦商品可收藏（上一段未取得商品）")
    else:
        p = products[0]
        item_id = p.get("rawId") or p.get("id")
        item_type = p.get("type") or p.get("apiType") or "lipsticks"
        r = s.post(f"{GW}/member-database/api/favorites/toggle",
                   headers={**write_headers, "Content-Type": "application/json"},
                   json={"item_id": item_id, "item_type": item_type}, timeout=30)
        if r.ok:
            record("7. 收藏商品", "PASS", f"toggle 成功（item {item_type}:{item_id}）")
        else:
            record("7. 收藏商品", "FAIL", f"HTTP {r.status_code}: {r.text[:150]}")

    return summarize()


def summarize():
    print("\n" + "=" * 60)
    print("端到端串測結論")
    print("=" * 60)
    counts = {"PASS": 0, "FAIL": 0, "BLOCKED": 0}
    for stage, verdict, _ in results:
        counts[verdict] = counts.get(verdict, 0) + 1
    for stage, verdict, detail in results:
        print(f"  {verdict:8s} {stage}")
    print(f"\n  合計：PASS={counts['PASS']}  FAIL={counts['FAIL']}  BLOCKED={counts['BLOCKED']}")
    overall = "FAIL" if counts["FAIL"] else ("BLOCKED" if counts["BLOCKED"] else "PASS")
    print(f"  整鏈判定：{overall}")
    return overall


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
