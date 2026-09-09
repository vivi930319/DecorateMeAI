"""七台裝置同時測試之後，把那段時間真正發生的事撈出來。

為什麼需要這支
----------------
「順不順」是感覺，而 Demo 前要決定的是具體的數字：CPU 要不要調回 4、記憶體 8 GiB
夠不夠、min-instances 要設多少。這些問題各自有對應的證據，而證據分散在四個地方
（Firestore 的 job 紀錄、Cloud Monitoring 的資源用量、Cloud Logging 的錯誤、
Replicate 的計費紀錄），手動一個一個查很容易漏掉其中一項——最容易漏的偏偏是
「有沒有 OOM」，因為它不會出現在任何一個成功率統計裡。

特別注意平時的用量數字**沒有參考價值**：一週 254 次 PRO 請求幾乎不會重疊，量到的
尖峰是「一個人用」的尖峰。七台同時才是第一次有併發樣本，所以這支報告的重點是
那個窗口，不是長期平均。

用法
------
    python tools/load_test_report.py --hours 2
    python tools/load_test_report.py --since "2026-09-11 20:00" --until "2026-09-11 21:30"

時間用本地時間（UTC+8）。不給 --until 就到現在為止。
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import urllib.parse
import urllib.request

PROJECT = "decorate-me"
REGION = "asia-east1"
SERVICES = ("ai-gateway", "face-basic", "face-pro", "replicate-render")
TZ = datetime.timezone(datetime.timedelta(hours=8))

# 各服務的配置，用來把百分比換算回實際用量。百分比本身沒有意義——
# 「記憶體 33%」在 8 GiB 和 4 GiB 上是完全不同的兩件事。
LIMITS = {
    "ai-gateway": (1, 0.5),
    "face-basic": (2, 8),
    "face-pro": (2, 8),
    "replicate-render": (1, 1),
}


def _token() -> str:
    out = subprocess.run(["gcloud", "auth", "print-access-token"],
                         capture_output=True, text=True, shell=True)
    token = (out.stdout or "").strip()
    if not token:
        raise SystemExit("拿不到 access token，請先執行 gcloud auth login。")
    return token


def _get_json(url: str, token: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(url: str, token: str, body: dict, timeout: int = 90):
    req = urllib.request.Request(
        url, method="POST", data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _series(token: str, metric: str, start: str, end: str, aligner: str,
            reducer: str = "REDUCE_MAX") -> dict[str, float]:
    """回傳 {service_name: 值}。讀不到就回空的——少一段報告，不要整支掛掉。"""
    params = {
        "filter": f'metric.type="run.googleapis.com/{metric}"',
        "interval.startTime": start, "interval.endTime": end,
        "aggregation.alignmentPeriod": "60s",
        "aggregation.perSeriesAligner": aligner,
        "aggregation.crossSeriesReducer": reducer,
        "aggregation.groupByFields": "resource.label.service_name",
    }
    url = (f"https://monitoring.googleapis.com/v3/projects/{PROJECT}/timeSeries?"
           + urllib.parse.urlencode(params))
    try:
        data = _get_json(url, token)
    except Exception as exc:  # noqa: BLE001
        print(f"    （讀不到 {metric}：{exc}）")
        return {}
    result: dict[str, float] = {}
    for entry in data.get("timeSeries", []):
        name = entry["resource"]["labels"].get("service_name", "?")
        values = []
        for point in entry.get("points", []):
            value = point.get("value", {})
            raw = value.get("doubleValue")
            if raw is None:
                raw = value.get("int64Value")
            if raw is not None:
                values.append(float(raw))
        if values:
            result[name] = max(values)
    return result


def _log_count(token: str, log_filter: str, start: str, end: str, limit: int = 200) -> list[str]:
    body = {
        "resourceNames": [f"projects/{PROJECT}"],
        "filter": f'{log_filter} AND timestamp>="{start}" AND timestamp<="{end}"',
        "orderBy": "timestamp desc",
        "pageSize": limit,
    }
    try:
        data = _post_json("https://logging.googleapis.com/v2/entries:list", token, body)
    except Exception as exc:  # noqa: BLE001
        print(f"    （讀不到日誌：{exc}）")
        return []
    return [e.get("timestamp", "") for e in data.get("entries", [])]


def _local(iso: str) -> str:
    try:
        return (datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
                .astimezone(TZ).strftime("%m-%d %H:%M:%S"))
    except Exception:  # noqa: BLE001
        return iso[:19]


def render_jobs(token: str, start_epoch: float, end_epoch: float) -> list[dict]:
    body = {"structuredQuery": {
        "from": [{"collectionId": "render_jobs"}],
        "orderBy": [{"field": {"fieldPath": "createdAt"}, "direction": "DESCENDING"}],
        "limit": 300}}
    url = (f"https://firestore.googleapis.com/v1/projects/{PROJECT}"
           "/databases/(default)/documents:runQuery")
    try:
        rows = _post_json(url, token, body)
    except Exception as exc:  # noqa: BLE001
        print(f"    （讀不到 render_jobs：{exc}）")
        return []
    jobs = []
    for row in rows:
        doc = row.get("document")
        if not doc:
            continue
        fields = doc.get("fields", {})

        def num(key):
            raw = fields.get(key, {}) or {}
            value = raw.get("doubleValue") or raw.get("integerValue")
            return float(value) if value is not None else None

        created = num("createdAt")
        if created is None or not (start_epoch <= created <= end_epoch):
            continue
        error = (fields.get("error", {}).get("mapValue", {}) or {}).get("fields", {})
        jobs.append({
            "createdAt": created,
            "finishedAt": num("finishedAt"),
            "status": (fields.get("status", {}) or {}).get("stringValue", ""),
            "code": (error.get("code", {}) or {}).get("stringValue", ""),
        })
    return jobs


def replicate_predictions(start_epoch: float, end_epoch: float) -> list[dict]:
    """Replicate 端的紀錄。用來對帳：有沒有「它成功計費、我們卻算失敗」的。"""
    out = subprocess.run(
        ["gcloud", "secrets", "versions", "access", "latest",
         "--secret=decorate-me-replicate-api-token", f"--project={PROJECT}"],
        capture_output=True, text=True, shell=True)
    api_token = (out.stdout or "").strip()
    if not api_token:
        print("    （讀不到 Replicate token，跳過對帳）")
        return []
    # User-Agent 一定要帶。urllib 預設送 "Python-urllib/3.x"，Replicate 對它回 403，
    # 而那個 403 看起來像「金鑰無效」——會讓人去查一把其實正確的金鑰。
    req = urllib.request.Request(
        "https://api.replicate.com/v1/predictions",
        headers={"Authorization": f"Bearer {api_token}",
                 "User-Agent": "decorate-me-load-test-report/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"    （讀不到 Replicate 紀錄：{exc}）")
        return []
    picked = []
    for prediction in data.get("results", []):
        created = prediction.get("created_at", "")
        try:
            epoch = datetime.datetime.fromisoformat(
                created.replace("Z", "+00:00")).timestamp()
        except Exception:  # noqa: BLE001
            continue
        if start_epoch <= epoch <= end_epoch:
            picked.append({
                "created": created,
                "status": prediction.get("status", ""),
                "seconds": (prediction.get("metrics") or {}).get("predict_time"),
            })
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=2,
                        help="往回看幾小時（預設 2）。給 --since 時忽略。")
    parser.add_argument("--since", help="起點，本地時間，例如 \"2026-09-11 20:00\"")
    parser.add_argument("--until", help="終點，本地時間。不給就到現在。")
    args = parser.parse_args()

    now = datetime.datetime.now(TZ)
    if args.since:
        try:
            start = datetime.datetime.fromisoformat(args.since).replace(tzinfo=TZ)
        except ValueError:
            raise SystemExit("--since 格式看不懂，用 \"2026-09-11 20:00\" 這種寫法。")
    else:
        start = now - datetime.timedelta(hours=args.hours)
    if args.until:
        try:
            end = datetime.datetime.fromisoformat(args.until).replace(tzinfo=TZ)
        except ValueError:
            raise SystemExit("--until 格式看不懂。")
    else:
        end = now
    if end <= start:
        raise SystemExit("終點必須晚於起點。")

    start_iso = start.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    token = _token()

    print()
    print("═" * 68)
    print(f"  區間：{start.strftime('%m-%d %H:%M')} ~ {end.strftime('%m-%d %H:%M')}"
          f"（本地時間，共 {(end - start).total_seconds() / 60:.0f} 分鐘）")
    print("═" * 68)

    # ── 1. 渲染成敗 ───────────────────────────────────────────────
    print("\n【渲染】")
    jobs = render_jobs(token, start.timestamp(), end.timestamp())
    if not jobs:
        print("  這段時間沒有渲染紀錄。")
    else:
        done = [j for j in jobs if j["status"] == "completed"]
        failed = [j for j in jobs if j["status"] == "failed"]
        stuck = [j for j in jobs if j["status"] in ("queued", "running")]
        print(f"  共 {len(jobs)} 筆：成功 {len(done)}、失敗 {len(failed)}、"
              f"還在跑或卡住 {len(stuck)}")
        if done:
            spans = sorted(j["finishedAt"] - j["createdAt"] for j in done
                           if j["finishedAt"])
            if spans:
                print(f"  成功耗時：最短 {spans[0]:.0f} 秒／"
                      f"中位 {spans[len(spans) // 2]:.0f} 秒／最長 {spans[-1]:.0f} 秒")
        for job in failed:
            print(f"    失敗 {_local(datetime.datetime.fromtimestamp(job['createdAt'], TZ).isoformat())}"
                  f"  {job['code'] or '(無錯誤碼)'}")

    # ── 2. Replicate 對帳 ─────────────────────────────────────────
    print("\n【Replicate 對帳】")
    predictions = replicate_predictions(start.timestamp(), end.timestamp())
    if not predictions:
        print("  這段時間 Replicate 沒有紀錄，或讀不到。")
    else:
        ok = [p for p in predictions if p["status"] == "succeeded"]
        print(f"  Replicate 端：{len(predictions)} 筆，其中 succeeded {len(ok)} 筆"
              f"（每筆約 $0.13）")
        our_done = len([j for j in jobs if j["status"] == "completed"])
        gap = len(ok) - our_done
        # job 文件只保留一小時（RENDER_JOB_RETENTION_SECONDS，未收藏的終態工作），
        # 所以只要窗口有一部分早於一小時前，缺的那幾筆可能只是被清掉了，不是丟圖。
        # 不講這件事的話，隔天回頭跑這份報告一定會誤報，而誤報比不報更浪費時間。
        stale = (datetime.datetime.now(TZ) - start).total_seconds() > 3600
        if gap > 0 and stale:
            print(f"  它成功 {len(ok)} 筆，我們的紀錄只有 {our_done} 筆，差 {gap} 筆。")
            print("    ⚠ 但這個區間有部分早於一小時前，而 job 文件只保留一小時——"
                  "差額可能只是紀錄被清掉了。")
            print("    要準確對帳，測試結束後**一小時內**跑這份報告。")
        elif gap > 0:
            print(f"  ⚠ 它成功 {len(ok)} 筆，我們只拿到 {our_done} 筆——"
                  f"差 {gap} 筆是**付了錢沒拿到圖**。")
            print("    這正是 wait=False 要修掉的那件事。若修正已上線仍出現，"
                  "代表輪詢途中也會斷，需要改成自己保管 prediction id。")
        elif gap < 0:
            print(f"  （我們的成功數比 Replicate 多 {-gap} 筆，多半是去重命中，不用圖也算成功。）")
        else:
            print("  對得上，沒有付了錢卻丟掉的圖。")

    # ── 3. 併發下的資源用量 ────────────────────────────────────────
    print("\n【資源用量尖峰（這才是七台同時的真實值）】")
    mem = _series(token, "container/memory/utilizations", start_iso, end_iso, "ALIGN_PERCENTILE_99")
    cpu = _series(token, "container/cpu/utilizations", start_iso, end_iso, "ALIGN_PERCENTILE_99")
    instances = _series(token, "container/instance_count", start_iso, end_iso, "ALIGN_MAX")
    print(f"  {'服務':<18}{'CPU 尖峰':>16}{'記憶體尖峰':>18}{'最多幾台':>10}")
    for service in SERVICES:
        vcpu, gib = LIMITS.get(service, (1, 1))
        c, m = cpu.get(service), mem.get(service)
        print(f"  {service:<18}"
              f"{(f'{c * 100:.0f}% = {c * vcpu:.2f} 顆' if c is not None else '—'):>16}"
              f"{(f'{m * 100:.0f}% = {m * gib:.1f} GiB' if m is not None else '—'):>18}"
              f"{(f'{instances.get(service, 0):.0f}' if service in instances else '—'):>10}")
    print("  判讀：CPU 接近 100% 代表該調回 4 vCPU；記憶體超過 70% 就不要再降。")

    # ── 4. OOM 與容器被殺 ──────────────────────────────────────────
    print("\n【OOM / 容器被殺】")
    oom = _log_count(
        token,
        'resource.type="cloud_run_revision" AND '
        '(textPayload:"Memory limit" OR textPayload:"exceeded memory" OR '
        'textPayload:"was terminated")',
        start_iso, end_iso)
    if oom:
        print(f"  ⚠ 有 {len(oom)} 筆。記憶體**不能再降**，可能還要調高。")
        for stamp in oom[:5]:
            print(f"    {_local(stamp)}")
    else:
        print("  沒有。記憶體撐得住這個併發量。")

    # ── 5. 建議服務 ────────────────────────────────────────────────
    print("\n【Ollama 建議服務】")
    down = _log_count(
        token,
        'resource.type="cloud_run_revision" AND '
        'resource.labels.service_name="replicate-render" AND '
        'textPayload:"建議服務不可用"',
        start_iso, end_iso)
    if down:
        print(f"  ⚠ 有 {len(down)} 次連不上——那段時間渲染是完全被擋住的（503）。")
        for stamp in down[:5]:
            print(f"    {_local(stamp)}")
        print("  Quick Tunnel 換過網址就會這樣，跑 update-ollama-url.ps1 更新兩個服務。")
    else:
        print("  全程正常。")

    print("\n" + "═" * 68)
    print("  這份報告不回答「畫面順不順」——那要靠現場的人看。")
    print("  它回答的是資源夠不夠、有沒有靜默失敗、以及錢有沒有白花。")
    print("═" * 68 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
