"""訓練機：把後台按下「送去訓練」的批次，在這台裝了 PyTorch 的電腦上跑完。

為什麼需要它
------------
後台跑在 Cloud Run 上，一個 request 最長 600 秒、沒有 GPU、記憶體 512 MB，而一次
ConvNeXt 訓練是好幾分鐘的 CPU 工作。所以那顆按鈕**註定**只能建立待辦，不可能當場
訓練。少了這支腳本，那個待辦就要人工打一次 `--training-run TR-xxxx` 才會動。

有了它，流程變成：管理員按按鈕 → 批次躺在 Firestore → 這台電腦只要有跑這支腳本
就會自己撿走、訓練、回寫結果。**電腦不必 24 小時開著**：批次會等，關機期間排隊的
批次會在下次啟動時依序做完。

它會怎麼被看見
--------------
每一輪都寫一次心跳（`face_training_workers/<worker-id>`）。後台靠它分辨兩件很容易
被混為一談的事：批次還停在 queued，是因為**訓練機沒開**，還是因為**訓練失敗**。
沒有心跳就只能顯示「已排隊」，而管理員會以為系統壞了。

不會做的事
----------
**不會自動把訓練出來的模型換上線。** 每個批次的產出都寫進自己的
`models/training_runs/<批次編號>/`，線上模型目錄一個位元組都不會動。要不要換是決策，
不是計算——尤其眉型這種單次切分分數會在 0.43 ~ 0.56 之間跳的模型（見訓練歷程
§16.4），自動換上分數最高的那顆等於自動部署一次運氣。

用法
----
    python tools/training_worker.py                 # 一直守著，每 20 秒看一次
    python tools/training_worker.py --once          # 只處理目前排隊中的，做完就結束
    python tools/training_worker.py --dry-run       # 只顯示會做什麼，不真的訓練
    python tools/training_worker.py --auto-collect  # 相容舊流程：自動收集未送訓回饋

預設不會自動收集回饋。管理員必須在後台按「送去訓練」或失敗批次的
「重新送訓這一批」，Worker 只執行已明確進入 queued 的批次；``--auto-collect``
只保留給需要舊行為的手動維運，不應放進正式啟動排程。
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import shutil
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401  # 讓 tools/ 底下的腳本找得到 training/ 與 face/

from training.training_run_store import (
    RUNS_COLLECTION, claim_run, create_run_from_accepted, fail_run, heartbeat, list_runs,
    patch_document,
)

ROOT = Path(__file__).resolve().parents[1]
# 後台的 selections 用的是使用者看到的中文欄位名；訓練腳本要的是部位代號。
FIELD_TO_PART = {
    "臉型": "face_shape",
    "眉型": "brow_shape",
    "眼型": "eye_shape",
    "鼻型": "nose_shape",
    "嘴型": "lip_shape",
}


def _log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def _parts_of(run: dict) -> list[str]:
    """這一批要重訓哪幾個部位——只訓練真的有新樣本的那些。

    全部五個一起訓練要跑五倍時間，而其中四個的訓練資料跟上一次一模一樣，
    產出的也會是同樣的東西。把沒有新樣本的部位一起跑，除了讓人等，還會讓
    modelBefore/modelAfter 出現一堆「差 0.000」的列，把真正變動的那一個埋掉。
    """
    parts: list[str] = []
    for fields in (run.get("selections") or {}).values():
        for field in (fields or {}):
            part = FIELD_TO_PART.get(str(field))
            if part and part not in parts:
                parts.append(part)
    return parts


# Windows 的閒置計時器看的是**使用者輸入**，不是 CPU 忙不忙。這台機器設定成
# 插電 5 分鐘、電池 3 分鐘就睡，而一次訓練要跑一兩個小時——按下送訓之後走開，
# 五分鐘後機器就睡了，訓練停在半路，十五分鐘後你收到「訓練機失聯」。
#
# 所以訓練期間明確跟系統說「別睡」，訓練一結束就放掉。只在跑的時候擋，
# 不是一直擋著：讓一台筆電永遠不能睡，代價比偶爾重跑一次訓練大得多。
#
# 只要求 ES_SYSTEM_REQUIRED，不要 ES_DISPLAY_REQUIRED——螢幕該關就關，
# 要的是機器別睡，不是把螢幕一直點著。
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextlib.contextmanager
def _keep_awake(label: str = ""):
    """訓練期間阻止系統睡眠。非 Windows 或呼叫失敗就照常跑，不要因此不訓練。"""
    held = False
    if sys.platform == "win32":
        try:
            if ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED) != 0:
                held = True
                _log(f"已阻止系統睡眠{('（' + label + '）') if label else ''}")
            else:
                _log("[注意] 無法阻止系統睡眠，訓練期間電腦若閒置可能會睡著")
        except Exception as exc:
            _log(f"[注意] 阻止睡眠失敗（{exc}），訓練期間電腦若閒置可能會睡著")
    try:
        yield
    finally:
        # 一定要還原，否則這支程式活著的期間電腦永遠睡不著。
        if held:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                _log("已恢復系統的睡眠設定")
            except Exception:
                pass


def _run_step(cmd: list[str], env: dict, tail: deque) -> int:
    """執行一個步驟，即時印出來，同時留下最後幾行給失敗訊息用。

    邊跑邊印很重要：訓練是好幾分鐘的沉默，看不到 epoch 在動的時候，人分不出
    「在跑」跟「當掉」。而 tail 是給 Firestore 的——後台的對話框要顯示為什麼失敗，
    貼一整段 traceback 沒有人看得懂，最後幾行才是原因。
    """
    _log("$ " + " ".join(cmd[1:]))
    process = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", bufsize=1)
    for line in process.stdout:
        line = line.rstrip()
        if line:
            print("   " + line, flush=True)
            tail.append(line)
    return process.wait()


def _ensure_holdout_split(cache_dir: str, plus_dir: str, split_version: str | None) -> Path | None:
    """讓合併回饋後的快取也帶著同一份保留集切分。

    training_worker 把新回饋匯入 ``*_plus_feedback`` 後，訓練腳本會以
    ``ROI_CACHE_DIR`` 指向那個新目錄；但保留集 JSON 原本只放在基礎快取
    ``data/roi_cache``。少了這個檔案，訓練還沒進第一個 epoch 就會因為
    FileNotFoundError 失敗，重新送訓只是在重複同一個錯誤。

    只在目標快取缺檔時複製，不重建、不改寫已存在的切分，確保所有批次仍使用
    同一份 v2 基準。回傳 None 代表呼叫端沒有要求保留集。
    """
    if not split_version:
        return None
    filename = f"holdout_split_{split_version}.json"
    target = ROOT / plus_dir / filename
    if target.is_file():
        source = target
    else:
        candidates = [
            ROOT / cache_dir / filename,
            ROOT / "data" / "roi_cache" / filename,
        ]
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            raise FileNotFoundError(
                f"找不到保留集切分 {filename}；已檢查 "
                + "、".join(str(path) for path in candidates)
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        _log(f"已補齊訓練保留集：{target}（來源 {source}）")

    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"保留集切分 {target} 不是可讀的 JSON：{exc}") from exc
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if not isinstance(samples, list) or not samples:
        raise ValueError(f"保留集切分 {target} 缺少有效 samples 清單")
    if not any(isinstance(row, dict) and row.get("split") == "holdout" for row in samples):
        raise ValueError(f"保留集切分 {target} 沒有 holdout 樣本")
    return target


def process_run(run: dict, args, project: str) -> bool:
    run_id = str(run.get("runId") or "")
    parts = _parts_of(run)
    if not parts:
        fail_run(project, run_id, "這個批次沒有任何可訓練的部位——採用的欄位對不到五官分類。")
        _log(f"{run_id} 沒有可訓練的部位，標記為失敗")
        return False

    out_dir = f"models/training_runs/{run_id}"
    cache_dir = args.cache_dir
    plus_dir = f"{cache_dir}_plus_feedback"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "ROI_CACHE_DIR": plus_dir}
    tail: deque = deque(maxlen=25)

    _log(f"{run_id}：{len(run.get('selections') or {})} 筆回饋、部位 {'、'.join(parts)}")

    steps = [
        # 先把這一批被採用的樣本併進既有快取。--training-run 會讓它只收這個批次的
        # selections，不會順手把其他還沒覆核的回饋一起拉進來。
        [sys.executable, "training/import_feedback_samples.py",
         "--training-run", run_id, "--cache-dir", cache_dir, "--out-dir", plus_dir],
        # 再訓練。輸出到批次自己的目錄，線上模型目錄不動。
        [sys.executable, "training/train_basic_cnn_roi.py",
         "--training-run", run_id, "--parts", *parts,
         "--architecture", "convnext_tiny", "--epochs", str(args.epochs),
         "--skip-random", "--out-dir", out_dir,
         *(["--holdout-split", args.holdout_split] if args.holdout_split else [])],
    ]

    if args.dry_run:
        for cmd in steps:
            _log("（預演）" + " ".join(cmd[1:]))
        return True

    heartbeat(project, args.worker_id, "training", f"{run_id}：{'、'.join(parts)}")
    for index, cmd in enumerate(steps):
        with _keep_awake(run_id):
            code = _run_step(cmd, env, tail)
        if code != 0:
            reason = "\n".join(list(tail)[-8:]) or f"步驟結束碼 {code}"
            fail_run(project, run_id, f"{Path(cmd[1]).name} 失敗（結束碼 {code}）：\n{reason}")
            _log(f"{run_id} 失敗，已寫回後台")
            return False
        # 匯入這一步就算什麼都沒收到也會回 0，而且不會建立輸出目錄
        # （見 import_feedback_samples 的 usable 判斷）。發生在文件說有影像、
        # GCS 上其實已經沒有的時候——保留期限到了，或先前被清理掉。
        #
        # 不擋的話下一步會拿一個不存在的快取目錄去訓練，錯誤訊息變成「找不到檔案」的
        # 堆疊，後台顯示的就是那一段——真正的原因（這批沒有影像）反而看不到。
        if index == 0 and not (ROOT / plus_dir).is_dir():
            fail_run(project, run_id,
                     "這個批次沒有任何影像可以訓練。文件標示有影像，但 GCS 上已經找不到——"
                     "可能是保留期限到了，或先前被清理掉。")
            _log(f"{run_id} 沒有可用影像，標記為失敗")
            return False
        if index == 0 and args.holdout_split:
            try:
                _ensure_holdout_split(cache_dir, plus_dir, args.holdout_split)
            except (OSError, ValueError) as exc:
                reason = f"訓練前置檢查失敗：{exc}"
                fail_run(project, run_id, reason)
                _log(f"{run_id} {reason}")
                return False

    # 訓練腳本自己會把 status 寫成 done 並附上前後指標；這裡只補上產出位置，
    # 讓「這批的模型在哪」不必靠猜。
    patch_document(project, RUNS_COLLECTION, run_id, {"outDir": out_dir})
    _log(f"{run_id} 完成，產出在 {out_dir}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "decorate-me"))
    parser.add_argument("--cache-dir", default="data/roi_cache_manual",
                        help="既有的 ROI 快取；新樣本會併進它的 _plus_feedback 版本")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--interval", type=int, default=20, help="幾秒看一次有沒有新批次")
    parser.add_argument("--worker-id", default=os.environ.get("COMPUTERNAME") or "local",
                        help="心跳用的識別字；後台顯示的就是這個")
    parser.add_argument("--once", action="store_true", help="把目前排隊中的做完就結束")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會做什麼")
    parser.add_argument(
        "--auto-collect", action="store_true",
        help="相容舊流程：沒有 queued 批次時自動收集已採用回饋；正式排程不要開啟",
    )
    # 保留集要在**每一次**訓練都排除，否則它就不是保留集了。
    #
    # v1 就是這樣花掉的：2026-08-06 為了多拿 27% 的資料，讓線上模型把 v1 的 613 張
    # 全部訓練過，從此沒有任何一份考卷能拿來比較不同版本的模型——後台顯示的
    # 「訓練前 → 訓練後」只能在同一批次內部看，跨批次比等於比運氣。
    #
    # 所以預設值是 v2 而不是 None：這件事一旦要「記得加參數」就會有人忘記，
    # 而忘記一次的代價是整個基準作廢。要關掉必須明講 --holdout-split ''。
    parser.add_argument("--holdout-split", default="v2", metavar="VERSION",
                        help="每次訓練都排除 data/roi_cache/holdout_split_<VERSION>.json "
                             "裡標為 holdout 的樣本，讓 tools/eval_on_holdout.py 的分數"
                             "可以跨批次比較。傳空字串可停用（會讓基準失效）。")
    args = parser.parse_args()

    _log(f"訓練機 {args.worker_id} 啟動｜專案 {args.project}｜快取 {args.cache_dir}")
    _log("後台按下「送去訓練」或「重新送訓這一批」的批次會在這裡自動執行；沒有按鈕就不會建立新批次。")

    # 開機時把自己上次沒做完的批次撿回來。
    #
    # 被關機、當掉、或工作排程重啟殺掉的時候，那一批會留在 running——而 running 的意思是
    # 「正在訓練」，後台會一直顯示訓練中，實際上沒有任何程式在跑。這是最難發現的一種壞：
    # 畫面看起來一切正常，只是永遠不會結束。
    #
    # 只撿 workerId 是自己的：多台機器時，別人正在跑的那一批不該被這裡搶回來。
    if not args.dry_run:
        try:
            for stale in list_runs(args.project, status="running", limit=20):
                if stale.get("workerId") != args.worker_id:
                    continue
                patch_document(args.project, RUNS_COLLECTION, str(stale.get("runId")), {
                    "status": "queued", "startedAt": None,
                    "error": "上一次執行被中斷，已自動放回排隊。",
                })
                _log(f"撿回中斷的批次 {stale.get('runId')}，放回排隊")
        except Exception as exc:
            _log(f"檢查中斷批次時失敗（{exc}），略過")

    current: str | None = None
    try:
        while True:
            # 整輪都包起來，不是只包讀取。
            #
            # 2026-08-26 實測：一次 DNS 解析失敗（getaddrinfo failed）讓訓練腳本掛掉，
            # worker 想寫「失敗」回 Firestore，那個寫入**也**因為同一個網路問題拋例外，
            # 而那個例外沒有人接——worker 整支死掉，批次留在 running。
            # 後台於是顯示了十一個小時的「訓練中」，實際上什麼都沒在跑。
            #
            # 這是最糟的一種壞：畫面看起來正常，只是永遠不會結束。守候型的程式
            # 不能因為任何單一例外而離開迴圈——網路會斷，而它應該等網路回來。
            try:
                queued = list_runs(args.project, status="queued", limit=10)
            except Exception as exc:
                _log(f"讀取批次失敗（{exc}），{args.interval} 秒後重試")
                time.sleep(args.interval)
                continue

            if not queued and args.auto_collect:
                # 舊版流程會在這裡自動收集回饋。保留成明確的維運開關，避免既有
                # 手動腳本突然失效；正式啟動不開這個旗標，批次只能由管理員按鈕建立。
                try:
                    made = None if args.dry_run else create_run_from_accepted(args.project, args.worker_id)
                except Exception as exc:
                    _log(f"收集批次失敗（{exc}），{args.interval} 秒後重試")
                    time.sleep(args.interval)
                    continue
                if made:
                    _log(f"收集到新批次 {made['runId']}：{made['sampleCount']} 個部位標註、"
                         f"{len(made['feedbackIds'])} 筆回饋")
                    queued = [made]

            if not queued:
                heartbeat(args.project, args.worker_id, "idle")
                if args.once:
                    _log("沒有排隊中的批次；請由管理員按鈕送訓後再執行。")
                    return 0
                time.sleep(args.interval)
                continue

            for run in queued:
                run_id = str(run.get("runId") or "")
                try:
                    claimed = claim_run(args.project, run_id, args.worker_id) if not args.dry_run else run
                    if not claimed:
                        continue
                    current = run_id
                    process_run(claimed, args, args.project)
                except Exception as exc:
                    # 到這裡代表連「把失敗寫回去」都失敗了（多半是網路斷在同一段時間）。
                    # 那一筆會留在 running，但下次啟動時的撿回機制會把它放回排隊——
                    # 前提是 worker 還活著，所以這裡絕對不能讓例外逃出迴圈。
                    _log(f"{run_id} 處理時發生未預期的錯誤：{exc}")
                    try:
                        fail_run(args.project, run_id, f"訓練機遇到未預期的錯誤：{exc}")
                    except Exception:
                        _log(f"  連錯誤都寫不回去，{run_id} 會留在 running，"
                             f"下次啟動時會被撿回排隊")
                # ⚠️ 這裡**不能**用 finally 清掉 current。
                #
                # KeyboardInterrupt 是 BaseException，不會被上面的 except Exception 接住，
                # 但 finally 照樣會先跑一遍——等外層的 except KeyboardInterrupt 拿到控制權時，
                # current 已經是 None，那段「把批次放回排隊」就被跳過了。
                # 結果是 Ctrl+C 之後批次永遠停在 running，正好是那段程式要防的事。
                # 而且啟動器把結束碼 130 當成「使用者明確要停」，不會重啟，
                # 所以連撿回機制也救不了。
                #
                # 改成只在**正常走完**時清掉。
                current = None

            if args.once:
                _log("排隊中的批次都處理完了，結束。")
                return 0
    except KeyboardInterrupt:
        # 中途按 Ctrl+C 的話，把批次放回 queued。留在 running 會讓後台一直顯示
        # 「訓練中」，而實際上沒有任何程式在跑——那比顯示「排隊中」更誤導。
        if current:
            patch_document(args.project, RUNS_COLLECTION, current,
                           {"status": "queued", "startedAt": None,
                            "error": "訓練被手動中斷，已放回排隊。"})
            _log(f"{current} 已放回排隊")
        heartbeat(args.project, args.worker_id, "offline", "手動停止")
        _log("已停止。")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
