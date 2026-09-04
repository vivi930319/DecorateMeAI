"""撿走後台登記的「換模型上線」請求，在訓練機上執行本機做得到的那幾步。

為什麼要有這一層
----------------
模型檔是 111MB 一個、打包進 face 服務的 image。換一次要複製檔案、重算 sha256、
更新 manifest、重新 build 與部署——全都需要這台機器的檔案系統與 gcloud 認證，
而後台跑在 Cloud Run 上，兩者都沒有。所以後台只能「下單」，執行在這裡。

這跟 training_worker.py 是同一套模式，理由也相同：雲端碰不到本機。

做到哪裡為止
------------
預設一路做到上線：複製、類別檢查、備份、更新 manifest、上傳 GCS、build 與部署。

「決定」仍然是人做的——後台那顆按鈕就是決定，而且它只會提出比線上好的部位。
worker 做的是執行，不是判斷。把部署留在終端機並不會讓決定更謹慎，只會讓換模型
這件事因為麻煩而不做——37 個批次擺著沒上線就是那樣來的。

每個階段都回寫 Firestore，後台看得到走到哪：
    queued → claimed → running → deployed
失敗停在 ``failed``，並附上看得懂的原因；模型檔與 manifest 已經換好的話，
修掉原因後只要重跑部署腳本，不必重新 promote。

--prepare-only 保留舊行為：只換檔案，停在 ``prepared``，部署自己來。

用法
----
    python tools/promotion_worker.py                 # 一直守著，每 20 秒看一次
    python tools/promotion_worker.py --once          # 處理完目前排隊的就結束
    python tools/promotion_worker.py --prepare-only  # 換完就停，不上傳也不部署
    python tools/promotion_worker.py --dry-run       # 只顯示會做什麼
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
    publish_live_model_metrics,
)

LIVE_DIR = ROOT / "models" / "basic_features_roi"

# 程式改了就自己結束，讓外殼用新版把自己帶回來。
#
# 這支是常駐程式：改完 promotion_worker.py 之後，正在跑的那個行程仍然是舊碼，
# 而它「還活著」，所以工作排程的看門狗不會動它——看門狗只救死掉的行程。
# 結果是改動看起來沒生效，而唯一的線索要去比對啟動時間才看得出來。
#
# 只監看真的被載進這個行程的檔案。promote_model.py 是每次用子行程叫的，
# 它自己就會拿到新版，列進來只會造成沒有必要的重啟。
WATCHED_SOURCES = (Path(__file__), ROOT / "training" / "training_run_store.py")
# 外殼看到這個結束碼就立刻重啟，不套用指數退避——這不是失敗，是刻意的換版。
RELOAD_EXIT_CODE = 86


def _source_fingerprint() -> tuple:
    marks = []
    for path in WATCHED_SOURCES:
        try:
            stat = path.stat()
            marks.append((str(path), stat.st_mtime_ns, stat.st_size))
        except OSError:
            # 讀不到就記成固定值。這裡不能拋例外——原始碼一時讀不到
            # （同步中、防毒掃描）不該讓一支守候程式整個倒下。
            marks.append((str(path), 0, 0))
    return tuple(marks)

PROMOTIONS_COLLECTION = "face_model_promotions"
DEPLOYMENTS_COLLECTION = "face_service_deployments"

# 後台能觸發的部署。Ollama 建議服務不在裡面：它跑在另一台機器上，這支 worker
# 碰不到，列進來只會做出一顆按了沒反應的按鈕。
DEPLOY_SCRIPTS = {
    "face": "deploy_face_cloudrun.ps1",
    "gateway": "deploy_gateway_cloudrun.ps1",
    "render": "deploy_render_cloudrun.ps1",
}
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


STALE_MINUTES = 30
# 多久掃一次卡住的工作。不跟輪詢同步（預設 20 秒）——那會讓每一輪都多兩次
# Firestore 查詢，而卡住的工作本來就要等 STALE_MINUTES 才算數，掃那麼密沒有意義。
STALE_SWEEP_SECONDS = int(os.getenv("PROMOTION_STALE_SWEEP_SECONDS", "300"))


def _requeue_stale_in(project: str, collection: str, id_field: str) -> int:
    """把某個集合裡上次沒做完的請求排回佇列。回傳回收了幾筆。"""
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES)
    recovered = 0
    for status in ("claimed", "running"):
        query = {
            "from": [{"collectionId": collection}],
            "where": {"fieldFilter": {
                "field": {"fieldPath": "status"},
                "op": "EQUAL",
                "value": {"stringValue": status},
            }},
            "limit": 20,
        }
        try:
            rows = _run_query(project, {"structuredQuery": query})
        except Exception:
            return recovered
        for row in rows:
            started = str(row.get("claimedAt") or row.get("createdAt") or "")
            try:
                when = datetime.fromisoformat(started.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when > cutoff:
                continue  # 還在合理時間內，可能真的正在跑
            doc_id = str(row.get(id_field) or "")
            if not doc_id:
                continue
            patch_document(project, collection, doc_id, {
                "status": "queued",
                # stage 要一起清掉。它停在「正在部署 gateway」，重新排隊後那行還在，
                # 後台就會顯示一筆 queued 卻同時說它正在部署某個服務。
                "stage": None,
                "note": f"上一次沒有做完（訓練機可能中途關機），已重新排隊。"
                        f"停在 {status} 超過 {STALE_MINUTES} 分鐘。",
                "error": None,
            })
            print(f"[{doc_id}] 回收：停在 {status} 太久，重新排隊")
            recovered += 1
    return recovered


def requeue_stale(project: str) -> int:
    """把上次沒做完的請求排回佇列——換模型與部署兩種都要。

    換模型中途關機（或斷電、或 worker 被殺）時，那筆請求會停在 claimed 或
    running——而 list_queued 只找 queued，所以沒有人會再碰它。後台顯示「進行中」
    而實際上沒有任何程序在跑，跟訓練那邊踩過的十一小時是同一種壞法。

    部署也要一起回收，而且它的後果更硬。 這裡原本只掃換模型那個集合，但
    Gateway 在收到新的部署請求時會擋掉「還有一筆 queued/claimed/running」的情況——
    於是一筆卡死的部署不是「顯示怪怪的」而已，它會讓後台那顆部署按鈕**永遠**
    按不下去，而且沒有任何一條路徑會把它清掉。

    重做都是安全的：複製檔案、上傳 GCS、build 與部署都是冪等的，而且 promote_model
    會用執行當下的線上分數重新判斷——如果上一次其實已經換完，這次會看到
    live 等於 new，不算退步，照樣通過。部署更單純，它本來就只是「拿現在的程式碼
    再建一次、再送一次」。
    """
    return (_requeue_stale_in(project, PROMOTIONS_COLLECTION, "promotionId")
            + _requeue_stale_in(project, DEPLOYMENTS_COLLECTION, "deploymentId"))


def list_queued_in(project: str, collection: str, limit: int = 10) -> list[dict]:
    """某個集合裡排隊中的請求，最舊的排前面。"""
    query = {
        "from": [{"collectionId": collection}],
        "where": {"fieldFilter": {
            "field": {"fieldPath": "status"},
            "op": "EQUAL",
            "value": {"stringValue": "queued"},
        }},
        "limit": int(limit),
    }
    rows = _run_query(project, {"structuredQuery": query})
    return sorted(rows, key=lambda row: str(row.get("createdAt") or ""))


def process_deployment(row: dict, project: str, dry_run: bool, worker_id: str) -> bool:
    """重新建置並部署指定的服務。不換模型，只把現在的程式碼送上去。

    要先 claim 才做事。 這裡原本讀到 queued 就直接把狀態寫成 claimed，完全不看
    它現在是不是還在 queued——換模型那條路徑至少有 claim() 檔著，部署這條連
    那層都沒有。同時開兩個 worker（改完程式碼手動再起一個就會發生）時，兩邊
    都會去跑 deploy_*.ps1，互相覆蓋 Cloud Run revision，而且沒有人分得出線上
    最後是哪一次的產物。
    """
    dep_id = str(row.get("deploymentId") or "")
    services = [str(s) for s in (row.get("services") or []) if s in DEPLOY_SCRIPTS]
    if not dep_id or not services:
        if dep_id:
            patch_document(project, DEPLOYMENTS_COLLECTION, dep_id, {
                "status": "failed", "finishedAt": now_iso(),
                "error": "請求沒有指定可部署的服務。"})
        return False

    print(f"[{dep_id}] 部署 {'、'.join(services)}")
    if dry_run:
        print("  --dry-run：不執行")
        return True

    if not _claim_in(project, DEPLOYMENTS_COLLECTION, dep_id, worker_id):
        print("  已經被收走，略過")
        return False

    done = []
    for name in services:
        script = ROOT / DEPLOY_SCRIPTS[name]
        if not script.exists():
            patch_document(project, DEPLOYMENTS_COLLECTION, dep_id, {
                "status": "failed", "finishedAt": now_iso(),
                "error": f"找不到 {script.name}。已部署：{'、'.join(done) or '（無）'}"})
            return False
        patch_document(project, DEPLOYMENTS_COLLECTION, dep_id, {
            "status": "running", "stage": name,
            "note": f"正在建置並部署 {name}，需要數分鐘。已完成：{'、'.join(done) or '（無）'}"})
        print(f"  → {script.name}")
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
            cwd=str(ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace")
        tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).strip().splitlines()[-10:])
        print(tail)
        if proc.returncode != 0:
            # 說清楚停在哪一個：多個服務時，「部署失敗」不講是哪一個等於沒說。
            patch_document(project, DEPLOYMENTS_COLLECTION, dep_id, {
                "status": "failed", "finishedAt": now_iso(), "stage": None,
                "note": f"{name} 部署失敗。已完成：{'、'.join(done) or '（無）'}；"
                        f"未處理：{'、'.join(s for s in services if s not in done and s != name) or '（無）'}",
                "error": tail[-1500:]})
            return False
        done.append(name)

    patch_document(project, DEPLOYMENTS_COLLECTION, dep_id, {
        "status": "deployed", "finishedAt": now_iso(), "stage": None,
        "note": f"已部署：{'、'.join(done)}。", "error": None})
    print(f"  已部署：{'、'.join(done)}")
    return True


def _claim_in(project: str, collection: str, doc_id: str, worker_id: str) -> dict | None:
    """收下某個集合裡的一筆 queued 請求。已經被收走就回 None。

    先讀再寫，不是原子操作——與 training_run_store.claim_run 同樣的取捨：
    實務上只有一台訓練機，這個競態跑不出來。Firestore 的 REST 介面只支援
    「文件存不存在」的前置條件，要做欄位值的 CAS 得走 transaction commit，
    而這裡共用的那層沒有包那支。
    """
    row = get_document(project, collection, doc_id)
    if not row or row.get("status") != "queued":
        return None
    patch_document(project, collection, doc_id, {
        "status": "claimed",
        "claimedAt": now_iso(),
        "workerId": worker_id,
        "error": None,
    })
    return row


def claim(project: str, promotion_id: str, worker_id: str) -> dict | None:
    """收下一筆 queued 換模型請求。已經被收走就回 None。"""
    return _claim_in(project, PROMOTIONS_COLLECTION, promotion_id, worker_id)


# ledger 一筆有效紀錄至少要有的欄位。少任何一個都代表 promote_model 沒有走完
# 「換檔案 → 更新 manifest → 追加 ledger」那一段，這次的結果就不能當數。
LEDGER_REQUIRED_FIELDS = ("runId", "version", "backup", "parts")


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


def _ledger_problem(entry: dict | None, run_id: str) -> str:
    """這筆 ledger 能不能證明工作真的做完了。可以就回空字串。

    子程序結束碼 0 不等於模型換好了。 promote_model 在好幾條路徑上會印完訊息就
    return 0（--dry-run、沒有可換的部位），而更糟的是 ledger 寫入失敗時前面的
    複製其實已經發生。原本的寫法是 `entry = _last_ledger_entry(run_id) or {}`，
    然後把 version、backup、results 全填 None 照樣寫 status=deployed——後台會顯示
    一筆「已上線、版本空白」的紀錄，而沒有人能從那筆看出到底換了什麼、要怎麼還原。
    """
    if entry is None:
        return (f"找不到對應這次批次（{run_id}）的 ledger 紀錄。"
                "換模型腳本結束碼是 0，但沒有留下可以查證的工作紀錄，"
                "所以無法確認模型是否真的換好。請檢查 models/promotion_ledger.json。")
    missing = [f for f in LEDGER_REQUIRED_FIELDS if not entry.get(f)]
    if missing:
        return (f"ledger 紀錄不完整，缺少：{'、'.join(missing)}。"
                "這代表換模型只做到一半就中斷，不能當成已完成。")
    return ""


def _fail(project: str, promotion_id: str, message: str) -> None:
    """訊息會直接顯示在後台，所以寫給人看，不要貼整段 traceback。"""
    patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
        "status": "failed",
        "finishedAt": now_iso(),
        # note 要一起清掉。它在開始執行時被寫成「正在上傳並重新部署」，
        # 失敗後如果留著，後台就會同時顯示「進行中」與「失敗」——看的人
        # 不知道該信哪一個，而那正是他唯一能判斷狀況的兩個欄位。
        "note": "這次沒有換上線，線上仍是原本的模型。原因見下方。",
        "error": message[:1500],
    })


def process(promotion: dict, project: str, dry_run: bool, prepare_only: bool = False) -> bool:
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
    if not prepare_only:
        cmd.append("--deploy")

    print(f"[{promotion_id}] {run_id} → {'、'.join(parts)}"
          + ("（只準備檔案）" if prepare_only else "（含上傳與部署）"))
    if dry_run:
        print("  --dry-run：不執行")
        return True

    # build 與部署要好幾分鐘。先把狀態寫成 running，否則後台在這段期間看到的
    # 還是 claimed，會被讀成「卡住了」而有人跑去按第二次。
    if not prepare_only:
        patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
            "status": "running",
            "note": "正在上傳模型並重新部署 face 服務，需要數分鐘。",
        })

    # promote_model.py 印的是中文。Windows 主控台預設不是 UTF-8，不指定的話
    # 失敗訊息回寫到後台會變成一串問號，而那正是管理員唯一看得到的線索。
    # 逐行讀而不是等結束：換一次模型要好幾分鐘，等到最後才知道走到哪，
    # 後台那段時間只能顯示「進行中」。
    STAGE_NOTE = {
        "swapping": "正在換檔案並備份舊模型。",
        "uploading": "正在把模型上傳到雲端儲存。",
        "deploying": "正在重新建置並部署 face 服務，這一步最久。",
    }
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", env=env, bufsize=1)
    lines = []
    for line in proc.stdout:
        lines.append(line)
        print(line.rstrip())
        if line.startswith("[STAGE] "):
            name = line[8:].strip()
            if name in STAGE_NOTE:
                try:
                    patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
                        "stage": name, "note": STAGE_NOTE[name],
                    })
                except Exception:
                    # 寫不進去不該讓換模型停下來——那只是進度顯示。
                    pass
    proc.wait()
    output = "".join(lines)

    if proc.returncode != 0:
        # 取尾端而不是開頭：擋下來的原因（類別不一致、找不到批次）印在最後。
        _fail(project, promotion_id, output.strip()[-1500:] or f"結束碼 {proc.returncode}")
        return False

    # 結束碼 0 只代表子程序沒有崩潰。要宣告成功，還得拿得出這次的工作紀錄。
    entry = _last_ledger_entry(run_id)
    problem = _ledger_problem(entry, run_id)
    if problem:
        _fail(project, promotion_id, problem)
        print(f"  ✗ 無法驗證換模型結果：{problem}")
        return False
    patch_document(project, PROMOTIONS_COLLECTION, promotion_id, {
        # prepared 與 deployed 要分得開。混成同一個「完成」，就會重演
        # 「已登記 macro 但其實沒上線」那個誤會——那正是這整套要解決的問題。
        "status": "prepared" if prepare_only else "deployed",
        "finishedAt": now_iso(),
        "version": entry.get("version"),
        "backup": entry.get("backup"),
        "results": entry.get("parts"),
        "note": ("檔案已備妥，尚未部署。請執行 deploy_face_cloudrun.ps1。" if prepare_only
                 else "已上線。face-basic 與 face-pro 都換成這個版本的模型。"),
        "stage": None,
        "error": None,
    })
    # 換完就把「線上現在實際是什麼分數」寫回 face_model_metrics/current。
    #
    # Gateway 優先讀那一份，讀不到才退回「往回找最後一個回報該部位的歷史批次」。
    # 那個退路換過一次模型就會過時，後台於是拿舊基準去比，把一個其實變差的批次
    # 畫成有進步——使用者按下換上線，才被這支腳本用真實數字擋回來。按鈕在被按之前
    # 就已經講錯了，而那正是「明明顯示有進步卻換不上去」的來源。
    #
    # 寫失敗不影響這次換上線：模型已經在線上了，只是後台的比較基準會停在舊的一份。
    # 所以只記一行，不讓它把一次成功的換上線變成失敗。
    if not prepare_only:
        try:
            publish_live_model_metrics(project, LIVE_DIR)
            print("  已更新後台的線上比較基準。")
        except Exception as exc:  # noqa: BLE001
            print(f"  ! 線上比較基準沒更新（{exc}）。模型已上線，但後台仍會拿舊基準比較。")

    print(f"  {'已備妥' if prepare_only else '已上線'}，版本 {entry.get('version')}。")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "decorate-me"))
    parser.add_argument("--worker-id", default=os.environ.get("COMPUTERNAME") or "local")
    parser.add_argument("--interval", type=int, default=20, help="幾秒看一次有沒有新請求")
    parser.add_argument("--once", action="store_true", help="把目前排隊中的做完就結束")
    parser.add_argument("--prepare-only", action="store_true",
                        help="只換檔案與 manifest，不上傳也不部署（舊行為）")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會做什麼")
    args = parser.parse_args()

    # 啟動當下的原始碼樣貌。之後每一輪閒下來時比對，變了就結束換新版。
    startup_sources = _source_fingerprint()

    print(f"換模型 worker 啟動：專案 {args.project}，識別 {args.worker_id}")
    # 每一輪都掃，不能只在啟動時掃一次。
    #
    # 原本只在進迴圈前掃一次，而那個時機幾乎保證掃不到東西：worker 死掉之後
    # 看門狗大約五分鐘就把它拉回來，那時卡住那筆的 claimedAt 還很新，遠不到
    # STALE_MINUTES（30），於是被跳過；接著 worker 一直活著，再也不會掃第二次。
    # 那筆就永遠停在 running，後台的部署按鈕永遠回 DEPLOY_ALREADY_QUEUED——
    # 正是這個函式當初要消滅的症狀。只有「worker 剛好在 30 分鐘後又重啟一次」
    # 才救得回來，而那是碰運氣，不是機制。
    #
    # 掃描本身很便宜（兩個集合各一次 status 查詢，各限 20 筆），而且 cutoff 是
    # 絕對時間，重複掃不會誤判仍在執行中的工作。
    last_sweep = 0.0
    while True:
        if not args.dry_run and time.time() - last_sweep >= STALE_SWEEP_SECONDS:
            last_sweep = time.time()
            try:
                n = requeue_stale(args.project)
                if n:
                    print(f"回收了 {n} 筆沒做完的請求")
            except Exception as exc:
                print(f"回收檢查失敗（{type(exc).__name__}），繼續正常輪詢")
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
                process(promotion, args.project, args.dry_run, args.prepare_only)
            except Exception as exc:
                print(f"[{promotion_id}] 執行失敗：{type(exc).__name__}: {exc}")
                if not args.dry_run and promotion_id:
                    _fail(args.project, promotion_id,
                          f"換模型時發生未預期的錯誤：{type(exc).__name__}: {exc}")

        # 部署請求跟換模型共用這個迴圈：兩者都要動線上服務，同時跑會互相覆蓋
        # revision，而排在同一條隊伍裡自然就不會。
        try:
            deployments = list_queued_in(args.project, DEPLOYMENTS_COLLECTION)
        except Exception as exc:
            print(f"讀取部署請求失敗（{type(exc).__name__}），下一輪再試")
            deployments = []
        for row in deployments:
            try:
                process_deployment(row, args.project, args.dry_run, args.worker_id)
            except Exception as exc:
                dep_id = str(row.get("deploymentId") or "")
                print(f"[{dep_id}] 部署失敗：{type(exc).__name__}: {exc}")
                if not args.dry_run and dep_id:
                    patch_document(args.project, DEPLOYMENTS_COLLECTION, dep_id, {
                        "status": "failed", "finishedAt": now_iso(), "stage": None,
                        "error": f"部署時發生未預期的錯誤：{type(exc).__name__}: {exc}"})

        if args.once:
            return 0

        # 檢查點放在這裡是有意義的：這一輪的換模型與部署都已經做完，手上沒有
        # 任何進行中的工作。換模型中途結束會留下一筆卡在 running 的請求，
        # 那正是 2026-09-03 那個「後台顯示進行中、實際上沒有任何行程」的形狀。
        if _source_fingerprint() != startup_sources:
            print("偵測到程式碼已更新，結束讓外殼用新版重啟。")
            return RELOAD_EXIT_CODE

        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    sys.exit(main())
