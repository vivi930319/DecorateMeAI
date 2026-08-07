"""訓練資料集的雲端同步：新機器用這支把照片拉下來。

為什麼資料集不進 git
--------------------
訓練照片有 436 MB、3174 個檔案，而且是人臉。git 對二進位檔沒有壓縮優勢，
每次補資料重訓都會讓 repo 永久長大——刪掉也不會變小，因為歷史還在。
`.gitignore` 為了 ONNX 已經踩過同一個坑（見那份檔案裡 2026-07-31 的說明）。

所以分工是：

    GitHub   程式碼、訓練腳本、保留集切分、評估分數、訓練紀錄
    GCS      照片本身（私有 bucket，強制封鎖公開存取）

可重現性不因此受損：保留集用 sha256 當鍵，clone 下來配上這支還原的照片，
就能重跑出同樣的數字（見 tools/build_holdout_split.py）。

用法
----
    # 新機器：把訓練資料集拉下來
    .venv\\Scripts\\python.exe tools\\sync_datasets.py --pull

    # 只看要下載什麼，不真的下載
    .venv\\Scripts\\python.exe tools\\sync_datasets.py --pull --dry-run

    # 本機資料有更新時推上去（會問過才刪雲端多出來的檔案）
    .venv\\Scripts\\python.exe tools\\sync_datasets.py --push

    # 確認本機與雲端一致
    .venv\\Scripts\\python.exe tools\\sync_datasets.py --verify
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUCKET = "gs://decorate-me-datasets"
PROJECT = "decorate-me"

# 本機路徑 -> 雲端前綴。
#
# 雲端路徑帶日期，本機不帶：雲端要留得住舊版本（合併前後各一份，那是
# 2026-08-06 對照實驗的依據），本機只需要目前這一版。
# 換了資料集版本就改這裡，並在訓練紀錄裡寫明從哪一版換到哪一版。
DATASETS = {
    "data/basic_full/grouped": "basic_full/grouped_post-merge_20260806",
    "data/pro_full/grouped": "pro_full/grouped_20260807",
}

# 只讀不寫的歷史快照，`--push` 不會動到它們。
ARCHIVED = {
    "basic_full/grouped_pre-merge_20260806": "2026-08-06 眼型合併前的狀態，對照實驗用",
}


def gcloud() -> str:
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("找不到 gcloud CLI。請先安裝 Google Cloud SDK 並登入。")


def run(args, dry_run=False):
    if dry_run:
        print("   （dry-run，不執行）" + " ".join(str(a) for a in args[-3:]))
        return 0
    return subprocess.run(args).returncode


def count_local(path: Path) -> int:
    return sum(1 for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def count_remote(prefix: str) -> int:
    out = subprocess.run(
        [gcloud(), "storage", "ls", "--recursive", f"{BUCKET}/{prefix}/**", "--project", PROJECT],
        capture_output=True, text=True, encoding="utf-8",
    ).stdout
    return sum(1 for line in out.splitlines() if line.startswith("gs://") and not line.endswith("/"))


def main():
    p = argparse.ArgumentParser(description="訓練資料集的雲端同步")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pull", action="store_true", help="從 GCS 拉到本機（新機器用這個）")
    mode.add_argument("--push", action="store_true", help="把本機的變更推上 GCS")
    mode.add_argument("--verify", action="store_true", help="只比對數量，不搬動任何檔案")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    print(f"bucket: {BUCKET}\n")
    failed = []

    for local_rel, remote in DATASETS.items():
        local = ROOT / local_rel
        n_local, n_remote = count_local(local), count_remote(remote)
        print(f"{local_rel}")
        print(f"   本機 {n_local} 檔   雲端 {n_remote} 檔")

        if args.verify:
            if n_local != n_remote:
                print(f"   ⚠ 數量不一致，差 {abs(n_local - n_remote)} 個")
                failed.append(local_rel)
            else:
                print("   一致")
            continue

        if args.pull:
            local.mkdir(parents=True, exist_ok=True)
            # 不加 --delete-unmatched-destination-objects：拉取不該刪掉本機的東西。
            # 本機多出來的檔案可能是還沒推上去的新標註，靜默刪掉會弄丟人工成果。
            code = run([gcloud(), "storage", "rsync", f"{BUCKET}/{remote}", str(local),
                        "--recursive", "--project", PROJECT], args.dry_run)
        else:
            if not local.exists():
                print("   本機沒有這個目錄，略過（避免把雲端清空）")
                continue
            code = run([gcloud(), "storage", "rsync", str(local), f"{BUCKET}/{remote}",
                        "--recursive", "--project", PROJECT], args.dry_run)
        if code != 0:
            print(f"   ✗ 失敗（結束碼 {code}）")
            failed.append(local_rel)
        print()

    if ARCHIVED:
        print("唯讀的歷史快照（--push 不會動到）：")
        for prefix, why in ARCHIVED.items():
            print(f"   {prefix}\n      {why}")

    if failed:
        print(f"\n失敗／不一致：{'、'.join(failed)}")
        return 1
    print("\n完成。")
    if args.pull:
        print("接著跑：tools/build_identity_map.py -> prepare_roi_cache.py"
              "（照片路徑變了就必須重建，見訓練紀錄 §5.3.1）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
