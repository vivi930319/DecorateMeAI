"""撿走後台登記的「換模型上線」請求，在訓練機上執行本機做得到的那幾步。

為什麼要有這一層
----------------
模型檔是 111MB 一個、打包進 face 服務的 image。換一次要複製檔案、重算 sha256、
更新 manifest、重新 build 與部署——全都需要這台機器的檔案系統與 gcloud 認證，
而後台跑在 Cloud Run 上，兩者都沒有。所以後台只能「下單」，執行在這裡。

這跟 training_worker.py 是同一套模式，理由也相同：雲端碰不到本機。

做到哪裡為止
------------
只做 tools/promote_model.py 做得到的部分：複製、類別檢查、備份、manifest。
做完把狀態寫成 ``prepared``，**不會自動部署**。上傳 GCS 與 deploy 要人明確執行——
那一步會動到線上服務，而且要跑好幾分鐘，不該是背景任務偷偷完成的事。

後台看到 ``prepared`` 就知道「檔案備妥了，等你部署」。

用法
----
    python tools/promotion_worker.py              # 一直守著，每 20 秒看一次
    python tools/promotion_worker.py --once       # 處理完目前排隊的就結束
    python tools/promotion_worker.py --dry-run    # 只顯示會做什麼
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

# _run_query 是 training_run_store 的私有函式，但這裡需要「依 status 查一個集合」，
# 而那支模組只公開了針對 face_training_runs 的 list_runs。與其複製一份 Firestore
# 查詢的建構與權杖處理，不如共用同一段——那段的重試與錯誤處理已經被實際用過。
from training_run_store import (  # noqa: E402
    _run_query,
    get_document,
    now_iso,
    patch_document,
)

PROMOTIONS_COLLECTION = "face_model_promotions"
LEDGER = ROOT / "models" / "promotion_ledger.json"


def list_queued(project: str, limit: int = 10) -> list[dict]:
    """排隊中的請求，最舊的排前面——管理員按下按鈕的順序就是他要的順序。"""
    query = {
        "from": [{"collectionId": PROMOTIONS_COLLECTION}],
        "where": {"fieldFilter": {
            "field": {"fieldPath": "status"},
            "op": "EQUAL",
            "value": {"stringValue": "queued"},
        }},
        "limit": int(limit),
    }
    # 只篩選、不在查詢裡排序：Firestore 對「用 A 篩選、用 B 排序」要求複合索引，
    # 而排隊中的請求一次不會超過個位數，拿回來自己排比建索引划算。
    rows = _run_query(project, {"structuredQuery": query})
    return sorted(rows, key=lambda row: str(row.get("createdAt") or ""))


def claim(project: str, promotion_id: str, worker_id: str) -> dict | None:
    """收下一筆 queued 請求。已經被收走就回 None。

    先讀再寫，不是原子操作——與 training_run_store.claim_run 同樣的取捨：
    實務上只有一台訓練機，這個競態跑不出來。
    """
    row = get_document(project, PROMOTIONS_COLLECTION, promotion_id)
    if not row or row.get("status") != "queued":
        return None
    patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
        "status": "claimed",
        "claimedAt": now_iso(),
        "workerId": worker_id,
        "error": None,
    })
    return row


def _last_ledger_entry(run_id: str) -> dict | None:
    """promote_model.py 每換一次就往 ledger 追加一筆。取最後一筆當這次的結果。

    比對 runId 是為了不要在 promote 其實沒寫成功時，把上一次的紀錄當成這次的。
    """
    if not LEDGER.exists():
        return None
    try:
        history = json.loads(LEDGER.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not history:
        return None
    entry = history[-1]
    return entry if entry.get("runId") == run_id else None


def _fail(project: str, promotion_id: str, message: str) -> None:
    """訊息會直接顯示在後台，所以寫給人看，不要貼整段 traceback。"""
    patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
        "status": "failed",
        "finishedAt": now_iso(),
        "error": message[:1500],
    })


def process(promotion: dict, project: str, dry_run: bool) -> bool:
    promotion_id = str(promotion.get("promotionId") or "")
    run_id = str(promotion.get("runId") or "")
    parts = [str(p) for p in (promotion.get("parts") or [])]
    if not promotion_id or not run_id or not parts:
        if promotion_id:
            _fail(project, promotion_id, "請求缺少批次編號或部位，無法執行。")
        return False

    cmd = [sys.executable, str(ROOT / "tools" / "promote_model.py"), "--run", run_id]
    for part in parts:
        cmd += ["--part", part]

    print(f"[{promotion_id}] {run_id} → {'、'.join(parts)}")
    if dry_run:
        print("  --dry-run：不執行")
        return True

    # promote_model.py 印的是中文。Windows 主控台預設不是 UTF-8，不指定的話
    # 失敗訊息回寫到後台會變成一串問號，而那正是管理員唯一看得到的線索。
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)
    output = (proc.stdout or "") + (proc.stderr or "")
    print(output.rstrip())

    if proc.returncode != 0:
        # 取尾端而不是開頭：擋下來的原因（類別不一致、找不到批次）印在最後。
        _fail(project, promotion_id, output.strip()[-1500:] or f"結束碼 {proc.returncode}")
        return False

    entry = _last_ledger_entry(run_id) or {}
    patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
        "status": "prepared",
        "finishedAt": now_iso(),
        "version": entry.get("version"),
        "backup": entry.get("backup"),
        "results": entry.get("parts"),
        # 說清楚還沒上線。後台如果把 prepared 顯示成「完成」，就會重演
        # 「已登記 macro 但其實沒上線」那個誤會。
        "note": "檔案已備妥，尚未部署。請在訓練機執行 GCS 上傳與 deploy_face_cloudrun.ps1。",
        "error": None,
    })
    print(f"  已備妥，版本 {entry.get('version')}——尚未部署。")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "decorate-me"))
    parser.add_argument("--worker-id", default=os.environ.get("COMPUTERNAME") or "local")
    parser.add_argument("--interval", type=int, default=20, help="幾秒看一次有沒有新請求")
    parser.add_argument("--once", action="store_true", help="把目前排隊中的做完就結束")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會做什麼")
    args = parser.parse_args()

    print(f"換模型 worker 啟動：專案 {args.project}，識別 {args.worker_id}")
    while True:
        try:
            queued = list_queued(args.project)
        except Exception as exc:
            # 讀不到不結束：網路或權杖問題多半是暫時的，而這支程式的價值就在於
            # 一直守著。印出來讓人看得到，然後照常等下一輪。
            print(f"讀取請求失敗（{type(exc).__name__}），下一輪再試")
            queued = []

        for promotion in queued:
            promotion_id = str(promotion.get("promotionId") or "")
            if not args.dry_run:
                if not claim(args.project, promotion_id, args.worker_id):
                    continue
            try:
                process(promotion, args.project, args.dry_run)
            except Exception as exc:
                print(f"[{promotion_id}] 執行失敗：{type(exc).__name__}: {exc}")
                if not args.dry_run and promotion_id:
                    _fail(args.project, promotion_id,
                          f"換模型時發生未預期的錯誤：{type(exc).__name__}: {exc}")

        if args.once:
            return 0
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
