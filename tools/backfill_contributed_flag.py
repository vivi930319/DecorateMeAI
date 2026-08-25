"""把 face_feedback 的 contributed 欄位補回去。

為什麼會缺
----------
`_store_contribution` 原本沒有回傳值（永遠是 None），所以 `save()` 從來沒有把
「這一筆有沒有留下影像」寫進文件。2026-08-24 修好之後，新的修正會帶著這個欄位，
但在那之前累積的紀錄全都是空的——後台因此把它們一律顯示成「沒有影像可看」，
而 GCS 上其實有圖。

看不到圖就沒辦法覆核：眉型、唇型要看到形狀才有辦法判斷使用者說得對不對。
那 108 筆正是最想拿來重訓的資料，所以值得補。

怎麼補
------
GCS 的物件路徑是 `user_contributed/<版本>/<部位>/<類別>/<job_id>.png`，
檔名就是 job_id，而 face_feedback 的文件 id 也是 job_id——兩邊對得起來。

只補 True，不寫 False。「GCS 上沒有圖」有好幾種可能（使用者沒同意、上傳失敗、
保留期限到了被清掉），把它們一律標成 False 會蓋掉本來就正確的紀錄，
而那個欄位的用途只是決定要不要顯示「看樣本影像」的按鈕——少顯示一顆按鈕，
比錯誤地宣稱有圖來得安全。

不一致的情況（文件說有、GCS 沒有）會列出來但不動，那需要人看過再決定。

用法
----
    python tools/backfill_contributed_flag.py            # 只看會改什麼
    python tools/backfill_contributed_flag.py --write    # 實際寫入
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

BUCKET = "decorate-me-datasets"
PREFIX = "user_contributed"
COLLECTION = "face_feedback"


def _gcloud_exe() -> str:
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")


def _gcloud(*args: str) -> str:
    out = subprocess.run([_gcloud_exe(), *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"gcloud {' '.join(args)} 失敗：{out.stderr.strip()[:300]}")
    return out.stdout.strip()


def _request(url: str, token: str, method: str = "GET", body: dict | None = None) -> dict:
    req = urllib.request.Request(
        url, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}",
                 **({"Content-Type": "application/json"} if body is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"{method} {url.split('?')[0]} → HTTP {exc.code}: "
                           f"{exc.read().decode('utf-8', 'replace')[:200]}") from exc


def jobs_with_samples() -> set[str]:
    """GCS 上有影像的 job_id。檔名就是 job_id。"""
    listing = _gcloud("storage", "ls", "-r", f"gs://{BUCKET}/{PREFIX}/**")
    return {line.strip().rsplit("/", 1)[-1][:-4]
            for line in listing.splitlines() if line.strip().endswith(".png")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="實際寫入（預設只列出會改什麼）")
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    project = args.project or _gcloud("config", "get-value", "project")
    token = _gcloud("auth", "print-access-token")
    base = f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"

    have = jobs_with_samples()
    print(f"GCS 上有影像的 job：{len(have)} 個")

    # 讀出整個集合。分頁要跟到底，否則排在後面的就默默漏掉了。
    docs: list[tuple[str, dict]] = []
    page = ""
    while True:
        data = _request(f"{base}/{COLLECTION}?pageSize=300"
                        + (f"&pageToken={page}" if page else ""), token)
        for doc in data.get("documents", []):
            docs.append((doc["name"].rsplit("/", 1)[-1], doc.get("fields") or {}))
        page = data.get("nextPageToken") or ""
        if not page:
            break
    print(f"face_feedback 共 {len(docs)} 筆")

    to_set, already, mismatched, no_sample = [], [], [], 0
    for job_id, fields in docs:
        flag = fields.get("contributed", {}).get("booleanValue")
        if job_id in have:
            (already if flag is True else to_set).append(job_id)
        elif flag is True:
            # 文件說有、GCS 沒有。可能是保留期限清掉了，也可能是別的問題——
            # 這裡不動它，列出來讓人看過再決定。
            mismatched.append(job_id)
        else:
            no_sample += 1

    print(f"\n  要補上 contributed=true ：{len(to_set):4} 筆")
    print(f"  已經標好的            ：{len(already):4} 筆")
    print(f"  本來就沒有影像        ：{no_sample:4} 筆")
    if mismatched:
        print(f"  [注意] 文件說有、GCS 找不到：{len(mismatched):4} 筆（不動，需人工確認）")
        for j in mismatched[:5]:
            print(f"      {j}")

    if not to_set:
        print("\n沒有要補的。")
        return 0
    if not args.write:
        print(f"\n這是預演。加上 --write 才會實際寫入。前 5 筆：")
        for j in to_set[:5]:
            print(f"  {j}")
        return 0

    ok = 0
    for job_id in to_set:
        try:
            # updateMask 只帶 contributed：不寫遮罩的話，PATCH 會被當成整份覆寫，
            # 其餘欄位（corrections、predicted、覆核狀態）會被清空。
            _request(f"{base}/{COLLECTION}/{job_id}?updateMask.fieldPaths=contributed",
                     token, "PATCH", {"fields": {"contributed": {"booleanValue": True}}})
            ok += 1
        except Exception as exc:
            print(f"  失敗 {job_id}: {exc}")
    print(f"\n完成：{ok}/{len(to_set)} 筆已補上 contributed=true")
    return 0 if ok == len(to_set) else 1


if __name__ == "__main__":
    sys.exit(main())
