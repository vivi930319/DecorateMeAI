"""把某一個訓練批次的模型換上線——一次只換指定的部位。

為什麼需要這支
--------------
`training_worker.py` 刻意不自動換模型：「要不要換是決策，不是計算」。於是 37 個批次
的產出全都躺在 `models/training_runs/<批次>/`，線上目錄一個位元組都沒動過，而換模型
的實際動作從來沒有被寫下來——只能靠人記得複製哪幾個檔案。

這支把那件事寫成可重複、可回退、會擋錯的步驟。它只做本機做得到的部分（第 1~4 步），
上傳 GCS 與部署留給人明確執行。

換一次模型的完整流程
--------------------
    1. 從 training_runs/<批次>/ 複製到 models/basic_features_roi/   ← 這支
    2. 比對 classes.json，類別對不上就擋下來                        ← 這支
    3. 備份被換掉的舊模型                                           ← 這支
    4. 更新 tools/face_models_manifest.json 的版本與 sha256          ← 這支
    5. 上傳 GCS 新版本 prefix                                       ← 你執行
    6. docker build + 部署 Cloud Run                                ← 你執行

第 4 步不是可選的。`face/Dockerfile` 第 79 行會跑 `download_face_models.py --verify-only`，
manifest 裡的 sha256 對不上新檔案時，**build 會失敗**——而那個失敗訊息看起來像下載壞掉，
不像「你換了模型忘記更新 manifest」。

為什麼要擋「換上去更差」
------------------------
後台按鈕的比較基準是往回找歷史批次，不是實際線上模型——換過一次之後那個基準就過時。
所以這裡在動檔案之前用目前線上的 metrics 再算一次，任何一個部位會變差就整批擋下。
刻意回退用 --allow-regression。

為什麼要擋類別變動
------------------
2026-08-24 模型加入第四類眉型「挑眉」時，`analysis_package.BROW_SHAPE_CODES` 沒跟著加，
線上實測一萬張裡有 964 張（10%）的答案被丟成 unknown，而且不報錯。類別一改，
下游至少有四張表要跟上（見 tests/ollama_feature_labels_test.py）。所以預設擋下來，
真的要改就加 --allow-class-change，並照提示把那幾張表補齊。

用法
----
    python tools/promote_model.py --list
    python tools/promote_model.py --run TR-xxx --part 鼻型 --dry-run
    python tools/promote_model.py --run TR-xxx --part 鼻型
    python tools/promote_model.py --run TR-xxx --part 鼻型 --part 臉型
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "models" / "training_runs"
LIVE_DIR = ROOT / "models" / "basic_features_roi"
BACKUP_ROOT = ROOT / "models" / "promote_backups"
MANIFEST = Path(__file__).with_name("face_models_manifest.json")
LEDGER = ROOT / "models" / "promotion_ledger.json"

# 中文部位名 → 檔名前綴。接受中文是因為後台、回饋表與訓練報告用的都是中文，
# 換模型的人手上拿到的就是「鼻型 +11.7」這種句子。
PARTS = {
    "臉型": "face_shape",
    "眉型": "brow_shape",
    "眼型": "eye_shape",
    "鼻型": "nose_shape",
    "唇型": "lip_shape",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _macro(metrics_path: Path):
    """取出 identity 切分的最佳 macro accuracy。取不到就回 None，不要用 0 冒充。"""
    if not metrics_path.exists():
        return None
    try:
        data = _read_json(metrics_path)
    except ValueError:
        return None
    best = (data.get("identity") or {}).get("best") or {}
    value = best.get("macro_accuracy")
    return float(value) if isinstance(value, (int, float)) else None


def _pct(value) -> str:
    return "未記錄" if value is None else f"{value * 100:.1f}%"


def list_runs() -> int:
    if not RUNS_DIR.exists():
        print(f"找不到 {RUNS_DIR}")
        return 1
    runs = sorted((d for d in RUNS_DIR.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    if not runs:
        print("沒有任何訓練批次產出。")
        return 1
    print(f"{len(runs)} 個批次，新到舊：\n")
    for run in runs:
        parts = [name for name, stem in PARTS.items() if (run / f"{stem}.onnx").exists()]
        print(f"  {run.name}")
        for name in parts:
            stem = PARTS[name]
            new = _macro(run / f"{stem}_metrics.json")
            live = _macro(LIVE_DIR / f"{stem}_metrics.json")
            arrow = ""
            if new is not None and live is not None:
                delta = (new - live) * 100
                arrow = f"  線上 {_pct(live)} → {_pct(new)}  {delta:+.1f}"
            elif new is not None:
                arrow = f"  {_pct(new)}"
            print(f"      {name}{arrow}")
        print()
    return 0


def _check_classes(run_dir: Path, stem: str, part: str, allow_change: bool) -> bool:
    """類別表一致才放行。不一致時說清楚下游有哪些表要跟著改。"""
    new_path = run_dir / f"{stem}_classes.json"
    live_path = LIVE_DIR / f"{stem}_classes.json"
    if not new_path.exists():
        print(f"  ✗ {part}：批次裡沒有 {new_path.name}")
        return False
    if not live_path.exists():
        print(f"  ! {part}：線上沒有 {live_path.name}，視為新增")
        return True

    new_classes = _read_json(new_path).get("classes") or []
    live_classes = _read_json(live_path).get("classes") or []
    if new_classes == live_classes:
        print(f"  ✓ {part}：類別一致（{len(new_classes)} 類）")
        return True

    added = [c for c in new_classes if c not in live_classes]
    removed = [c for c in live_classes if c not in new_classes]
    print(f"  ✗ {part}：類別不一致")
    print(f"      線上 {len(live_classes)} 類：{'、'.join(live_classes)}")
    print(f"      批次 {len(new_classes)} 類：{'、'.join(new_classes)}")
    if added:
        print(f"      新增：{'、'.join(added)}")
    if removed:
        print(f"      移除：{'、'.join(removed)}")
    print("      下游至少這幾張表要一起改，否則答案會被靜靜丟成 unknown：")
    print("        face/analysis_package.py           *_SHAPE_CODES")
    print("        suggestion/Ollama_suggestion.py    MAP_*、*_LOGIC、*_METHOD")
    print("      改完跑 pytest tests/ollama_feature_labels_test.py 確認四層都對上。")
    if allow_change:
        print("      --allow-class-change 已指定，照樣換。")
        return True
    print("      確定要換請加 --allow-class-change。")
    return False


def _update_manifest(changed: list[str], version: str) -> None:
    """把換掉的檔案重新算 sha256 寫回 manifest，並換一個新的版本 prefix。

    版本名一定要換：沿用舊 prefix 等於在 GCS 上覆蓋掉舊檔，那之後就再也重建不出
    上一版的 image。
    """
    manifest = _read_json(MANIFEST)
    old_version = manifest.get("version", "")
    manifest["version"] = version
    prefix = manifest.get("gcsPrefix", "")
    if old_version and old_version in prefix:
        manifest["gcsPrefix"] = prefix.replace(old_version, version)
    else:
        manifest["gcsPrefix"] = f"gs://decorate-me-models/{version}"

    for entry in manifest.get("files", []):
        target = ROOT / entry["path"]
        if entry["path"] not in changed or not target.exists():
            continue
        entry["size"] = target.stat().st_size
        entry["sha256"] = _sha256(target)

    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(f"\nmanifest 已更新：{old_version} → {version}")
    print(f"  gcsPrefix: {manifest['gcsPrefix']}")
    return old_version


def stage(name: str) -> None:
    """印一行機器讀得懂的階段標記。

    worker 逐行讀這支的輸出，看到標記就把狀態寫回 Firestore，後台才有進度可看。
    先前整個換模型過程對後台是一個黑盒：狀態停在 running 好幾分鐘，看的人
    分不出「正在 build」與「卡住了」，於是會跑去按第二次。
    """
    print(f"[STAGE] {name}", flush=True)


def upload_to_gcs() -> bool:
    """把 manifest 列的**每一個**檔案上傳到新的版本 prefix。

    要傳全部，不能只傳這次換掉的那幾個：download_face_models.py 會照 manifest
    從 gcsPrefix 逐一抓，新 prefix 底下少任何一個，別台機器 clone 之後就組不出
    完整的模型組合——而那個失敗會發生在別人身上，不是換模型的人身上。
    """
    manifest = _read_json(MANIFEST)
    prefix = manifest["gcsPrefix"]
    stage("uploading")
    print(f"\n上傳到 {prefix}")
    for entry in manifest["files"]:
        source = ROOT / entry["path"]
        if not source.exists():
            print(f"  ✗ 缺檔 {entry['path']}")
            return False
        # gcloud 在 Windows 上是 .cmd，直接寫 gcloud 會 FileNotFoundError。
        result = subprocess.run(
            [_gcloud(), "storage", "cp", str(source), f"{prefix}/{entry['object']}"],
            capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ✗ {entry['path']}")
            print("   ", (result.stderr or "").strip().splitlines()[-1:] or "")
            return False
        print(f"  OK {entry['path']}")
    return True


def deploy_face() -> bool:
    """跑既有的部署腳本，不要另外拼一份 gcloud 指令。

    deploy_face_cloudrun.ps1 裡有模型驗證、共用參數與部署後的 Ready 檢查；
    在這裡重寫一份等於維護兩套會分岔的部署方式。
    """
    script = ROOT / "deploy_face_cloudrun.ps1"
    if not script.exists():
        print(f"找不到 {script.name}")
        return False
    stage("deploying")
    print(f"\n執行 {script.name}（build 與部署，需要數分鐘）")
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (result.stdout or "") + (result.stderr or "")
    # 只印尾巴：build log 很長，而失敗原因一定在最後。
    print("\n".join(output.strip().splitlines()[-12:]))
    return result.returncode == 0


def _gcloud() -> str:
    return "gcloud.cmd" if os.name == "nt" else "gcloud"


def _print_rollback(backup_dir, moves, previous_version) -> None:
    """把回退寫成可以直接貼進終端機的指令。

    先前這裡只有一句「把備份複製回去，並把 manifest 改回去」。那在出事的當下沒有用：
    要回退的人正在緊張，而他需要知道的是**哪幾個檔案**、**複製到哪**、
    **manifest 的哪個欄位改回什麼值**。少一項就得自己翻程式碼。
    """
    print("\n  要回退這一次，依序執行：")
    printed = False
    for part, stem, _live, _new in moves:
        for suffix in (".onnx", "_classes.json", "_metrics.json"):
            source = backup_dir / f"{stem}{suffix}"
            if not source.exists():
                continue
            rel_src = str(source.relative_to(ROOT)).replace("/", "\\")
            print(f"     copy /Y {rel_src} models\\basic_features_roi\\{stem}{suffix}")
            printed = True
    if not printed:
        print("     （備份是空的——這一次沒有覆蓋任何既有檔案，直接刪掉新檔即可）")
    if previous_version:
        print(f"\n     再把 tools/face_models_manifest.json 的 version 改回 \"{previous_version}\"，")
        print("     gcsPrefix 裡的版本字串也要一起改回去，sha256 會在下次 promote 時重算。")
    else:
        print("\n     manifest 這次還沒被改到，不用動它。")
    print("\n     最後執行 python tools/promote_model.py --list，")
    print("     確認「線上」那一欄的分數回到原本的數字。")


def _append_ledger(record: dict) -> None:
    """留一筆換模型的紀錄。沒有這個就只能靠人記得換過什麼。"""
    history = []
    if LEDGER.exists():
        try:
            history = _read_json(LEDGER)
        except ValueError:
            history = []
    history.append(record)
    LEDGER.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def promote(run_id: str, parts: list[str], allow_change: bool, dry_run: bool,
            version: str | None, upload: bool = False, deploy: bool = False,
            allow_regression: bool = False) -> int:
    run_dir = RUNS_DIR / run_id
    if not run_dir.is_dir():
        print(f"找不到批次 {run_id}（在 {RUNS_DIR}）")
        return 1

    print(f"批次 {run_id}")
    print("檢查類別表")
    checked = []
    for part in parts:
        stem = PARTS[part]
        if not (run_dir / f"{stem}.onnx").exists():
            print(f"  ✗ {part}：這個批次沒有訓練這個部位")
            return 1
        if not _check_classes(run_dir, stem, part, allow_change):
            return 1
        checked.append((part, stem))

    print("\n分數（identity 切分的最佳 macro）")
    moves = []
    worse = []
    for part, stem in checked:
        live = _macro(LIVE_DIR / f"{stem}_metrics.json")
        new = _macro(run_dir / f"{stem}_metrics.json")
        delta = f"{(new - live) * 100:+.1f}" if (new is not None and live is not None) else "—"
        print(f"  {part}：線上 {_pct(live)} → 批次 {_pct(new)}   {delta}")
        moves.append((part, stem, live, new))
        if live is not None and new is not None and new < live:
            worse.append((part, live, new))

    # 換上去比現在差就擋下來。
    #
    # 後台按鈕的比較基準是「往回找歷史批次」，不是實際線上模型。換過一次模型之後
    # 那個基準就過時了：線上臉型已經是 53.4%，後台仍拿 46.6% 去比，於是一個
    # 48.9% 的批次看起來是 +2.3，實際上是 -4.5。按下去的人看到的數字是錯的。
    #
    # 這裡用**執行當下**的 metrics 重新判斷，不相信請求裡帶的數字——這是最後一道，
    # 也是唯一一道能看到真實線上狀態的關卡。
    if worse and not allow_regression:
        print("\n  ✗ 擋下來：這些部位換上去會比現在差")
        for part, live, new in worse:
            print(f"      {part}：線上 {_pct(live)} → 批次 {_pct(new)}   {(new - live) * 100:+.1f}")
        print("      後台的比較基準是歷史批次，換過模型之後就會過時；上面用的是"
              "目前線上模型的實際分數。")
        print("      確定要換（例如刻意回退到舊模型）請加 --allow-regression。")
        return 1
    if worse and allow_regression:
        print("\n  ! --allow-regression 已指定，即使變差也照換。")

    if dry_run:
        print("\n--dry-run：以上都沒有真的執行。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    changed_paths = []
    stage("swapping")
    print(f"\n備份舊模型到 {backup_dir.relative_to(ROOT)}")
    for part, stem, _live, _new in moves:
        for suffix in (".onnx", "_classes.json", "_metrics.json"):
            live_file = LIVE_DIR / f"{stem}{suffix}"
            if live_file.exists():
                shutil.copy2(live_file, backup_dir / live_file.name)
        print(f"  {part} 已備份")

    print("\n換上新模型")
    done_parts = []
    for part, stem, _live, _new in moves:
        try:
            for suffix in (".onnx", "_classes.json", "_metrics.json"):
                source = run_dir / f"{stem}{suffix}"
                if not source.exists():
                    continue
                target = LIVE_DIR / f"{stem}{suffix}"
                shutil.copy2(source, target)
                rel = str(target.relative_to(ROOT)).replace("\\", "/")
                if suffix == ".onnx":
                    changed_paths.append(rel)
        except OSError as exc:
            # 中途失敗最危險：線上目錄現在是新舊混在一起，而 manifest 還沒更新，
            # 所以連 sha256 都對不上。這裡要把「壞在哪、換了什麼、怎麼還原」
            # 一次講完——只印一行「複製失敗」等於把人丟在半完成的狀態裡。
            print(f"\n  ✗ {part} 複製失敗：{type(exc).__name__}: {exc}")
            print("\n" + "=" * 70)
            print("換到一半就停了。線上目錄現在是新舊混合，manifest 尚未更新。")
            print(f"  已換完：{'、'.join(done_parts) if done_parts else '（無）'}")
            print(f"  失敗於：{part}")
            print(f"  未處理：{'、'.join(p for p, _s, _l, _n in moves[len(done_parts) + 1:]) or '（無）'}")
            _print_rollback(backup_dir, moves, None)
            print("=" * 70)
            return 1
        done_parts.append(part)
        print(f"  {part} 已換上")

    new_version = version or f"{datetime.now().strftime('%Y%m%d')}_{'_'.join(PARTS[p].split('_')[0] for p, _s, _l, _n in moves)}"
    previous_version = _update_manifest(changed_paths, new_version)

    _append_ledger({
        "at": datetime.now().isoformat(timespec="seconds"),
        "runId": run_id,
        "version": new_version,
        "backup": str(backup_dir.relative_to(ROOT)).replace("\\", "/"),
        "parts": [
            {"part": part, "liveMacro": live, "newMacro": new}
            for part, _stem, live, new in moves
        ],
    })

    manifest = _read_json(MANIFEST)
    print("\n" + "=" * 70)

    if upload or deploy:
        if not upload_to_gcs():
            print("\n上傳失敗，沒有繼續部署。線上仍是舊模型。")
            _print_rollback(backup_dir, moves, previous_version)
            print("=" * 70)
            return 1
        if deploy:
            if not deploy_face():
                print("\n部署失敗。模型檔與 manifest 已經換好，但線上仍是舊版——")
                print("修掉原因後可以只重跑 .\\deploy_face_cloudrun.ps1，不必重新 promote。")
                _print_rollback(backup_dir, moves, previous_version)
                print("=" * 70)
                return 1
            print("\n已上線。")
        else:
            print("\n已上傳 GCS，尚未部署：.\\deploy_face_cloudrun.ps1")
    else:
        print("本機部分完成。接下來這兩步要你自己跑——它們會動到線上服務：")
        print()
        print("  1. 上傳 GCS（新的版本 prefix，不覆蓋舊版）")
        print(f"     python tools/promote_model.py --upload-only")
        print()
        print("  2. 建置與部署（build 會用 manifest 驗 SHA-256）")
        print("     .\\deploy_face_cloudrun.ps1")
        print()
    _print_rollback(backup_dir, moves, previous_version)
    print("=" * 70)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="列出所有批次與各部位相對線上的增減")
    parser.add_argument("--run", help="要換上線的批次編號，例如 TR-0ba7a7e816b3f072")
    parser.add_argument("--part", action="append", choices=list(PARTS),
                        help="要換的部位，可重複指定；不指定就是這個批次訓練過的全部")
    parser.add_argument("--version", help="新的 manifest 版本名；不給就用日期加部位自動組")
    parser.add_argument("--allow-class-change", action="store_true",
                        help="允許類別表變動（下游那幾張表要自己補齊）")
    parser.add_argument("--allow-regression", action="store_true",
                        help="允許換上比目前線上差的模型（例如刻意回退）")
    parser.add_argument("--dry-run", action="store_true", help="只顯示會做什麼，不真的換")
    parser.add_argument("--upload", action="store_true",
                        help="換完直接把 manifest 列的全部檔案上傳到新的 GCS 版本")
    parser.add_argument("--deploy", action="store_true",
                        help="上傳後接著 build 與部署 face 服務（隱含 --upload）")
    parser.add_argument("--upload-only", action="store_true",
                        help="不換模型，只把目前的 manifest 內容重新上傳")
    args = parser.parse_args()

    if args.upload_only:
        return 0 if upload_to_gcs() else 1

    if args.list or not args.run:
        return list_runs()

    parts = args.part
    if not parts:
        run_dir = RUNS_DIR / args.run
        parts = [name for name, stem in PARTS.items() if (run_dir / f"{stem}.onnx").exists()]
        if not parts:
            print(f"批次 {args.run} 沒有任何可換上線的模型。")
            return 1
        print(f"未指定 --part，將換這個批次訓練過的全部：{'、'.join(parts)}\n")

    return promote(args.run, parts, args.allow_class_change, args.dry_run, args.version,
                   upload=args.upload or args.deploy, deploy=args.deploy,
                   allow_regression=args.allow_regression)


if __name__ == "__main__":
    sys.exit(main())
