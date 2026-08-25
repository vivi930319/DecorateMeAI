"""刪掉 GCS 上已經沒有用途的使用者貢獻影像。

為什麼會有這種東西
------------------
`user_contributed/` 底下的影像唯一的用途是當訓練標籤。有兩種情況它們會失去用途，
而在 2026-08-26 之前兩種都不會被刪：

1. **對應的 face_feedback 文件不見了**——會員刪除帳號、或早期測試留下的資料。
   沒有文件就沒有標籤，那張圖永遠不會被任何流程讀到。
2. **那筆修正被退回了**——退回代表管理員判定這個標註不可信。從 2026-08-26 起，
   退回會當場刪圖（見 face_feedback 的 review 端點），但在那之前退回的只改了狀態，
   圖還躺在 bucket 裡。

兩種都是在佔空間，而且是**臉部影像**：沒有用途的臉部資料留著，風險比刪掉大。

刻意保守的地方
--------------
- **partial 不刪**。同一次分析的五個部位共用一個 job_id、檔名都是 `<job_id>.png`，
  刪掉會把還要進訓練集的那幾張一起帶走。
- **pending 不刪**。還沒有人看過，不能替它決定。
- 預設只列出來，要加 `--apply` 才真的刪。刪除沒有回頭路。

用法
----
    python tools/purge_orphan_contributions.py              # 只看會刪什麼
    python tools/purge_orphan_contributions.py --apply      # 真的刪
    python tools/purge_orphan_contributions.py --apply --only orphan   # 只刪沒有文件的
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


def _request(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"GET {url.split('?')[0]} → HTTP {exc.code}: "
                           f"{exc.read().decode('utf-8', 'replace')[:200]}") from exc


def list_objects() -> dict[str, list[str]]:
    """job_id -> 該次分析在 GCS 上的所有物件路徑。"""
    listing = _gcloud("storage", "ls", "-r", f"gs://{BUCKET}/{PREFIX}/**")
    objects: dict[str, list[str]] = {}
    for line in listing.splitlines():
        path = line.strip()
        if not path.endswith(".png"):
            continue
        job_id = path.rsplit("/", 1)[-1][:-4]
        objects.setdefault(job_id, []).append(path)
    return objects


def load_feedback(project: str, token: str) -> dict[str, str]:
    """job_id -> reviewStatus。分頁要跟到底，否則後面的會被當成孤兒刪掉。"""
    base = (f"https://firestore.googleapis.com/v1/projects/{project}"
            f"/databases/(default)/documents/{COLLECTION}")
    statuses: dict[str, str] = {}
    page = ""
    while True:
        data = _request(f"{base}?pageSize=300" + (f"&pageToken={page}" if page else ""), token)
        for doc in data.get("documents", []):
            job_id = doc["name"].rsplit("/", 1)[-1]
            fields = doc.get("fields") or {}
            statuses[job_id] = (fields.get("reviewStatus") or {}).get("stringValue") or "pending"
        page = data.get("nextPageToken") or ""
        if not page:
            break
    return statuses


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="真的刪除（預設只列出來）")
    ap.add_argument("--only", choices=["orphan", "rejected"], default=None,
                    help="只處理其中一種")
    ap.add_argument("--project", default=None)
    args = ap.parse_args()

    project = args.project or _gcloud("config", "get-value", "project")
    token = _gcloud("auth", "print-access-token")

    objects = list_objects()
    statuses = load_feedback(project, token)
    print(f"GCS 上有影像的分析：{len(objects)} 次（共 {sum(len(v) for v in objects.values())} 個物件）")
    print(f"face_feedback 文件：{len(statuses)} 筆\n")

    orphan, rejected, keep = [], [], 0
    for job_id, paths in objects.items():
        status = statuses.get(job_id)
        if status is None:
            orphan.append((job_id, paths))
        elif status == "rejected":
            rejected.append((job_id, paths))
        else:
            keep += 1

    groups = []
    if args.only != "rejected":
        groups.append(("沒有對應的 face_feedback 文件", orphan))
    if args.only != "orphan":
        groups.append(("已退回，影像應該早就刪掉", rejected))

    total = sum(len(items) for _, items in groups)
    for title, items in groups:
        print(f"  {title}：{len(items)} 次分析、{sum(len(p) for _, p in items)} 個物件")
        for job_id, paths in items[:5]:
            print(f"      {job_id}（{len(paths)} 張）")
        if len(items) > 5:
            print(f"      …另外 {len(items) - 5} 次")
    print(f"  保留（待覆核／已採用／部分採用）：{keep} 次分析")

    if not total:
        print("\n沒有需要清理的。")
        return 0
    if not args.apply:
        print("\n這是預演，什麼都沒有刪。確認上面的清單沒問題後，加上 --apply 才會真的刪除。")
        return 0

    removed = failed = 0
    for _, items in groups:
        for job_id, paths in items:
            for path in paths:
                try:
                    _gcloud("storage", "rm", path)
                    removed += 1
                except Exception as exc:
                    print(f"  刪除失敗 {path}: {exc}")
                    failed += 1
    print(f"\n已刪除 {removed} 個物件" + (f"，{failed} 個失敗" if failed else ""))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
