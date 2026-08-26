"""產出去識別化的五官回饋彙總，供演算法端觀察上游輸入品質與分布漂移。

用途與界線（演算法端 2026-08-26 回覆已劃清，這裡照著做）
--------------------------------------------------------
**可以**用來觀察上游輸入品質與分布漂移。
**不能**直接拿去校正 `ColorScore = 1 - ΔE00/20`——色彩曲線需要膚色／商品色差
與實際色號適合度標記，這份資料沒有那些。
**不能**當推薦金標——推薦評估要的是對推薦商品的接受、收藏、試妝或人工適合度標註。

輸出欄位（對方指定的範圍，不多給）
----------------------------------
    日期區間、模型版本、部位、原預測類別、修正類別、同意與否、彙總筆數

**不含**身分、影像、job id，也不含逐筆時間戳。日期只給整份匯出的區間，
不給每一筆的日期——後者配合其他資訊有機會回推到某一個人的某一次使用。

小格抑制
--------
筆數低於 --min-count 的組合會被併成一列「其他（N 種組合，共 M 筆）」。
單獨一筆的罕見組合，配合外部知識仍有回推的可能；而對「看分布」這個用途來說，
只出現一次的組合本來就沒有統計意義。預設 3。

用法
----
    python tools/export_feedback_aggregate.py --out feedback_aggregate.json
    python tools/export_feedback_aggregate.py --out x.json --min-count 1   # 不抑制
"""
from __future__ import annotations

import _bootstrap  # noqa: F401
import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

EVAL_COL = "face_eval_events"
FEEDBACK_COL = "face_feedback"


def _gcloud(*args: str) -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise SystemExit("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")
    out = subprocess.run([exe, *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode:
        raise SystemExit(f"gcloud {' '.join(args)} 失敗：{out.stderr.strip()[:300]}")
    return out.stdout.strip()


def _fetch(project: str, token: str, collection: str) -> list[dict]:
    base = (f"https://firestore.googleapis.com/v1/projects/{project}"
            f"/databases/(default)/documents/{collection}")
    docs, page = [], ""
    while True:
        req = urllib.request.Request(base + "?pageSize=300" + (f"&pageToken={page}" if page else ""),
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise SystemExit(f"讀取 {collection} 失敗：HTTP {exc.code}") from exc
        docs += data.get("documents", [])
        page = data.get("nextPageToken") or ""
        if not page:
            return docs


def _val(doc: dict, key: str):
    field = (doc.get("fields") or {}).get(key)
    if not isinstance(field, dict):
        return None
    for kind in ("stringValue", "booleanValue", "timestampValue"):
        if kind in field:
            return field[kind]
    if "integerValue" in field:
        return int(field["integerValue"])
    if "mapValue" in field:
        return {k: _val({"fields": {k: v}}, k)
                for k, v in (field["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in field:
        return [x.get("stringValue") for x in (field["arrayValue"].get("values") or [])]
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="輸出的 JSON")
    ap.add_argument("--project", default="decorate-me")
    ap.add_argument("--min-count", type=int, default=3,
                    help="低於這個筆數的組合會被併成「其他」（預設 3；設 1 等於不抑制）")
    args = ap.parse_args()

    token = _gcloud("auth", "print-access-token")
    events = _fetch(args.project, token, EVAL_COL)
    feedback = {d["name"].rsplit("/", 1)[-1]: d for d in _fetch(args.project, token, FEEDBACK_COL)}
    print(f"讀到 {len(events)} 筆評估事件、{len(feedback)} 筆回饋紀錄")

    # 日期區間只取整份的頭尾。逐筆時間戳不輸出——那是「可回推個人」的那一項。
    stamps = sorted(s for s in (_val(d, "createdAt") for d in events) if s)
    date_range = {"from": stamps[0][:10], "to": stamps[-1][:10]} if stamps else None

    # (模型版本, 部位, 原預測, 修正後, 同意與否) -> 筆數
    cells: Counter = Counter()
    versions: Counter = Counter()
    for ev in events:
        version = _val(ev, "modelVersion") or "unknown"
        versions[version] += 1
        predicted = _val(ev, "predicted") or {}
        agreed = set(_val(ev, "agreed") or [])
        corrected = set(_val(ev, "corrected") or [])
        # 修正後的值在 face_feedback，不在事件裡；用 job_id 對起來。
        # 對不到就把修正值留成 None——寧可少一個欄位，不要猜。
        job_id = _val(ev, "jobId") or ""
        corrections = (_val(feedback.get(job_id, {}), "corrections") or {}) if job_id else {}
        for part, before in predicted.items():
            if part in agreed:
                cells[(version, part, str(before), None, True)] += 1
            elif part in corrected:
                cells[(version, part, str(before), corrections.get(part), False)] += 1

    rows, suppressed_cells, suppressed_count = [], 0, 0
    for (version, part, before, after, agreed_flag), n in sorted(cells.items(), key=lambda kv: -kv[1]):
        if n < args.min_count:
            suppressed_cells += 1
            suppressed_count += n
            continue
        rows.append({
            "modelVersion": version,
            "part": part,
            "predicted": before,
            "corrected": after,      # 同意時為 null
            "agreed": agreed_flag,
            "count": n,
        })
    if suppressed_cells:
        rows.append({
            "modelVersion": None, "part": None, "predicted": None, "corrected": None,
            "agreed": None, "count": suppressed_count,
            "note": f"其他（{suppressed_cells} 種組合，每種少於 {args.min_count} 筆，已合併）",
        })

    payload = {
        "generatedFor": "演算法端（Decorate Me 商品推薦）",
        "dateRange": date_range,
        "modelVersions": dict(versions),
        "minCount": args.min_count,
        "rows": rows,
        "usage": {
            "ok": "觀察上游輸入品質與分布漂移",
            "notOk": [
                "不能直接校正 ColorScore = 1 - ΔE00/20（需要膚色／商品色差與色號適合度標記）",
                "不能當推薦金標（需要對推薦商品的接受／收藏／試妝或人工適合度標註）",
            ],
            "bias": "自願回饋不是隨機抽樣；會動手修正的人多半是覺得結果不對的人，"
                    "所以同意率偏向低估，適合當下限與趨勢，不適合當精確值。",
        },
        "excluded": ["身分", "影像", "job id", "逐筆時間戳"],
    }

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"\n日期區間 {date_range}")
    print("模型版本：" + "、".join(f"{k} {v} 筆" for k, v in versions.most_common()))
    print(f"輸出 {len(rows)} 列" + (f"（另有 {suppressed_cells} 種罕見組合被併成一列）"
                                    if suppressed_cells else ""))
    print(f"寫入 {args.out}")

    # 最後自己檢查一次沒有夾帶身分或影像欄位。這份是要交出去的，
    # 「應該沒有」不夠——要在交出去之前確認過。
    text = json.dumps(payload, ensure_ascii=False)
    leaks = [w for w in ("email", "@", "ownerId", "dataUrl", "base64", "jobId", "JOB-") if w in text]
    print("夾帶檢查：" + ("乾淨" if not leaks else f"[注意] 發現可疑字串 {leaks}"))
    return 0 if not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
