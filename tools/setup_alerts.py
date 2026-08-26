"""在 GCP 建立錯誤告警：服務出錯與部署失敗會寄信。

為什麼需要
----------
2026-08-26 訓練機因為一次 DNS 失敗死掉，躺了十一個小時沒有人發現——後台那段時間
一直顯示「訓練中」。程式那邊已經修成會自己重啟，但**「沒有人發現」這件事本身**
要有對策：不能靠人記得去看畫面。

這支腳本設定的是雲端那一半：Cloud Run 回 5xx、或 Cloud Build 失敗時寄信。
訓練機本身不在 GCP 的指標裡（它跑在你的電腦上），那一半靠後台面板的心跳圓點。

可以重複執行
------------
每一項都先查有沒有同名的，有就跳過。所以改完再跑一次不會產生第二份。

用法
----
    python tools/setup_alerts.py --email you@example.com
    python tools/setup_alerts.py --email you@example.com --dry-run
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

BASE = "https://monitoring.googleapis.com/v3/projects/{project}"


def _token() -> str:
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise SystemExit("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")
    out = subprocess.run([exe, "auth", "print-access-token"], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    if out.returncode:
        raise SystemExit(f"取得 token 失敗：{out.stderr.strip()[:200]}")
    return out.stdout.strip()


def _call(url: str, token: str, body: dict | None = None, method: str | None = None) -> dict:
    req = urllib.request.Request(
        url, method=method or ("POST" if body is not None else "GET"),
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise SystemExit(f"{'POST' if body else 'GET'} {url.split('/v3/')[-1]} → "
                         f"HTTP {exc.code}\n{detail}") from exc


def ensure_channel(project: str, token: str, email: str, dry: bool) -> str:
    base = BASE.format(project=project)
    existing = _call(f"{base}/notificationChannels", token).get("notificationChannels", [])
    for ch in existing:
        if ch.get("type") == "email" and (ch.get("labels") or {}).get("email_address") == email:
            print(f"  通知管道已存在：{ch['name'].rsplit('/', 1)[-1]}"
                  f"（驗證狀態 {ch.get('verificationStatus', '未知')}）")
            return ch["name"]
    if dry:
        print(f"  （預演）會建立 email 通知管道給 {email}")
        return "dry-run-channel"
    created = _call(f"{base}/notificationChannels", token, {
        "type": "email",
        "displayName": "Decorate Me 錯誤通知",
        "description": "Cloud Run 服務錯誤與 Cloud Build 失敗會寄到這裡",
        "labels": {"email_address": email},
        "enabled": True,
    })
    print(f"  已建立通知管道，驗證狀態：{created.get('verificationStatus', '未知')}")
    return created["name"]


# 兩條政策。刻意只有兩條——告警多到會被忽略的時候，它就等於沒有。
def policies(channel: str) -> list[dict]:
    return [
        {
            "displayName": "Cloud Run 回應 5xx",
            "documentation": {
                "content": "face-basic／face-pro／ai-gateway 其中之一回了伺服器錯誤。"
                           "先看 Cloud Run 的 Logs，再看是不是剛部署過。",
                "mimeType": "text/markdown",
            },
            "conditions": [{
                "displayName": "五分鐘內出現 5xx",
                "conditionThreshold": {
                    "filter": ('metric.type="run.googleapis.com/request_count" '
                               'AND resource.type="cloud_run_revision" '
                               'AND metric.labels.response_code_class="5xx"'),
                    "aggregations": [{
                        "alignmentPeriod": "300s",
                        "perSeriesAligner": "ALIGN_SUM",
                        "crossSeriesReducer": "REDUCE_SUM",
                        "groupByFields": ["resource.labels.service_name"],
                    }],
                    # 門檻 0：這個專案流量很小，任何一個 5xx 都值得知道。
                    # 不必擔心被信淹沒——指標型告警是「開啟時寄一次、關閉時寄一次」，
                    # 不是每次超過門檻都寄。持續壞著只會有第一封。
                    "comparison": "COMPARISON_GT",
                    "thresholdValue": 0,
                    "duration": "0s",
                    "trigger": {"count": 1},
                },
            }],
            "combiner": "OR",
            "notificationChannels": [channel],
            # notificationRateLimit **只有記錄型政策能設**（實測回 400：
            # "only log-based alert policies may specify a notification rate limit"）。
            # 這裡只留 autoClose：一小時沒有再出現就自動關閉，下次壞掉才會是新的一封。
            "alertStrategy": {"autoClose": "3600s"},
            "enabled": True,
        },
        {
            "displayName": "Cloud Build 失敗",
            "documentation": {
                "content": "部署的映像沒有建成功。重跑部署腳本會印出日誌尾巴，"
                           "或到 Cloud Build 主控台看。",
                "mimeType": "text/markdown",
            },
            "conditions": [{
                "displayName": "build 記錄出現錯誤",
                # 記錄型告警：Cloud Build 的失敗不是一個「指標」，它是一筆記錄。
                "conditionMatchedLog": {"filter": 'resource.type="build" AND severity>=ERROR'},
            }],
            "combiner": "OR",
            "notificationChannels": [channel],
            "alertStrategy": {"notificationRateLimit": {"period": "900s"}},
            "enabled": True,
        },
        {
            "displayName": "訓練機失聯",
            "documentation": {
                "content": "訓練機超過 15 分鐘沒有回報。可能是那台電腦關機、睡眠、"
                           "或網路斷了。開機並確認工作排程「DecorateMe 訓練機」在跑；"
                           "記錄在 logs/training_worker.log。\n\n"
                           "排隊中的批次不會消失，它們會等訓練機回來。",
                "mimeType": "text/markdown",
            },
            "conditions": [{
                "displayName": "十五分鐘沒有心跳",
                # 這一條是**指標消失**才告警，不是指標超標。
                #
                # 訓練機跑在本機，它壞掉的原因很可能就是網路斷了——那時候本機
                # 不可能自己寄信。所以反過來做：本機定期往 Google 推「我還活著」，
                # 由 Google 盯著那個訊號有沒有中斷。
                # 負責發現的東西，不能是可能壞掉的那個東西。
                "conditionAbsent": {
                    "filter": ('metric.type="custom.googleapis.com/training_worker/alive" '
                               'AND resource.type="global"'),
                    "aggregations": [{
                        "alignmentPeriod": "300s",
                        "perSeriesAligner": "ALIGN_COUNT",
                    }],
                    "duration": "900s",
                    "trigger": {"count": 1},
                },
            }],
            "combiner": "OR",
            "notificationChannels": [channel],
            "enabled": True,
        },
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True, help="收告警信的信箱")
    ap.add_argument("--project", default="decorate-me")
    ap.add_argument("--dry-run", action="store_true", help="只顯示會建立什麼")
    args = ap.parse_args()

    token = _token()
    base = BASE.format(project=args.project)
    print(f"專案 {args.project}｜收件信箱 {args.email}\n")

    channel = ensure_channel(args.project, token, args.email, args.dry_run)

    existing = {p.get("displayName"): p for p in
                _call(f"{base}/alertPolicies", token).get("alertPolicies", [])}
    for policy in policies(channel):
        name = policy["displayName"]
        found = existing.get(name)
        if found:
            # 換信箱時要把既有政策**指過去**。只建新管道不改政策的話，
            # 信會繼續寄到舊信箱，而畫面上看起來像已經改好了。
            if found.get("notificationChannels") == [channel]:
                print(f"  告警政策已存在且收件人正確，略過：{name}")
            elif args.dry_run:
                print(f"  （預演）會把「{name}」的收件人改成這個管道")
            else:
                _call(f"https://monitoring.googleapis.com/v3/{found['name']}"
                      f"?updateMask=notificationChannels", token,
                      {"notificationChannels": [channel]}, method="PATCH")
                print(f"  已把收件人改到新管道：{name}")
            continue
        if args.dry_run:
            print(f"  （預演）會建立告警政策：{name}")
            continue
        _call(f"{base}/alertPolicies", token, policy)
        print(f"  已建立告警政策：{name}")

    # 沒有任何政策在用的 email 管道就清掉。留著等於在專案設定裡放一個
    # 不會收到通知、卻仍然存著某個人信箱的東西。
    if not args.dry_run:
        in_use = {channel}
        for p in _call(f"{base}/alertPolicies", token).get("alertPolicies", []):
            in_use.update(p.get("notificationChannels") or [])
        for ch in _call(f"{base}/notificationChannels", token).get("notificationChannels", []):
            if ch.get("type") == "email" and ch["name"] not in in_use:
                _call(f"https://monitoring.googleapis.com/v3/{ch['name']}?force=true",
                      token, method="DELETE")
                print(f"  已移除沒有人在用的舊管道："
                      f"{(ch.get('labels') or {}).get('email_address')}")

    if not args.dry_run:
        print("\n⚠ Google 會寄一封驗證信到這個信箱。**沒有點下驗證連結之前，"
              "這個管道不會收到任何告警**——那正是最容易以為設好了、其實沒有的一步。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
