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
import shutil
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
            version: str | None) -> int:
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
    for part, stem in checked:
        live = _macro(LIVE_DIR / f"{stem}_metrics.json")
        new = _macro(run_dir / f"{stem}_metrics.json")
        delta = f"{(new - live) * 100:+.1f}" if (new is not None and live is not None) else "—"
        print(f"  {part}：線上 {_pct(live)} → 批次 {_pct(new)}   {delta}")
        moves.append((part, stem, live, new))

    if dry_run:
        print("\n--dry-run：以上都沒有真的執行。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = BACKUP_ROOT / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    changed_paths = []
    print(f"\n備份舊模型到 {backup_dir.relative_to(ROOT)}")
    for part, stem, _live, _new in moves:
        for suffix in (".onnx", "_classes.json", "_metrics.json"):
            live_file = LIVE_DIR / f"{stem}{suffix}"
            if live_file.exists():
                shutil.copy2(live_file, backup_dir / live_file.name)
        print(f"  {part} 已備份")

    print("\n換上新模型")
    for part, stem, _live, _new in moves:
        for suffix in (".onnx", "_classes.json", "_metrics.json"):
            source = run_dir / f"{stem}{suffix}"
            if not source.exists():
                continue
            target = LIVE_DIR / f"{stem}{suffix}"
            shutil.copy2(source, target)
            rel = str(target.relative_to(ROOT)).replace("\\", "/")
            if suffix == ".onnx":
                changed_paths.append(rel)
        print(f"  {part} 已換上")

    new_version = version or f"{datetime.now().strftime('%Y%m%d')}_{'_'.join(PARTS[p].split('_')[0] for p, _s, _l, _n in moves)}"
    _update_manifest(changed_paths, new_version)

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
    print("本機部分完成。接下來這兩步要你自己跑——它們會動到線上服務：")
    print()
    print("  1. 上傳 GCS（新的版本 prefix，不覆蓋舊版）")
    for path in changed_paths:
        entry = next((f for f in manifest["files"] if f["path"] == path), None)
        if entry:
            print(f"     gsutil cp {path} {manifest['gcsPrefix']}/{entry['object']}")
    print()
    print("  2. 建置與部署（build 會用 manifest 驗 SHA-256）")
    print("     .\\deploy_face_cloudrun.ps1")
    print()
    print(f"  要回退：把 {backup_dir.relative_to(ROOT)} 的檔案複製回 models/basic_features_roi/，")
    print("  並把 manifest 的 version 與 sha256 改回去。")
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
    parser.add_argument("--dry-run", action="store_true", help="只顯示會做什麼，不真的換")
    args = parser.parse_args()

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

    return promote(args.run, parts, args.allow_class_change, args.dry_run, args.version)


if __name__ == "__main__":
    sys.exit(main())
