"""雲端同步：新機器用這支把 git 裡沒有的東西拉下來。

管三類：訓練照片、正式模型、技術文件。

為什麼資料集不進 git
--------------------
訓練照片有 436 MB、3174 個檔案，而且是人臉。git 對二進位檔沒有壓縮優勢，
每次補資料重訓都會讓 repo 永久長大——刪掉也不會變小，因為歷史還在。
`.gitignore` 為了 ONNX 已經踩過同一個坑（見那份檔案裡 2026-07-31 的說明）。

所以分工是：

    GitHub   程式碼、訓練腳本、保留集切分、評估分數、訓練紀錄（含完整歷史）
    GCS      照片本身（私有 bucket，強制封鎖公開存取）
             ＋正式模型的整個目錄（不是只有 .onnx，見 MODELS 的說明）
             ＋技術文件的一份副本，讓「還沒 clone」也拿得到

技術文件兩邊都有，這是刻意的重複：git 是它們的歷史，GCS 是它們的取用點。
改文件請改 repo 裡的，然後 `--push`；不要只改雲端那份，那樣 git 就不知道。

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
PROJECT = "decorate-me"

DATA_BUCKET = "gs://decorate-me-datasets"
MODEL_BUCKET = "gs://decorate-me-models"

# 本機路徑 -> 雲端前綴。
#
# 雲端路徑帶日期，本機不帶：雲端要留得住舊版本（合併前後各一份，那是
# 2026-08-06 對照實驗的依據），本機只需要目前這一版。
# 換了資料集版本就改這裡，並在訓練紀錄裡寫明從哪一版換到哪一版。
DATASETS = {
    "data/basic_full/grouped": f"{DATA_BUCKET}/basic_full/grouped_post-merge_20260806",
    "data/pro_full/grouped": f"{DATA_BUCKET}/pro_full/grouped_20260807",
}

# 正式環境的模型。**整個目錄**，不是只有 `.onnx`。
#
# 雲端原本的 `20260806/` 只放了 5 個 `.onnx`，那還原不出能跑的服務：
# Dockerfile 第 70、72 行複製的是整個目錄，而 `face_feedback.py` 會讀
# `*_classes.json` 當合法類別表。少了它，修正回饋收到任何標籤都無從驗證。
# 只備份權重不備份標籤對應，是「檔案都在但系統起不來」的典型。
MODELS = {
    "models/basic_features_roi": f"{MODEL_BUCKET}/20260807_complete/basic_features_roi",
    "models/pro_nose_side": f"{MODEL_BUCKET}/20260807_complete/pro_nose_side",
}

# 技術文件。這些在 git 裡就有，而且 git 才是它們的歷史——這裡放一份，是為了
# 「還沒 clone 就想看」和「git 拿不到時仍然拿得到」。
#
# 所以路徑刻意不帶日期：git 已經記得每一版長什麼樣，雲端再壓一層版本只會兩邊
# 對不起來。照片的情況相反——照片不進 git，雲端是它們唯一的歷史，才需要日期。
DOCS = {
    "docs/技術文件書_詳細版": f"{DATA_BUCKET}/docs/技術文件書_詳細版",
}

# 只讀不寫的歷史快照，`--push` 不會動到它們。
ARCHIVED = {
    f"{DATA_BUCKET}/basic_full/grouped_pre-merge_20260806":
        "2026-08-06 眼型合併前的狀態，對照實驗用",
    f"{MODEL_BUCKET}/20260731":
        "2026-07-31 上線版，含 DINOv2 融合頭與規則樹",
    f"{MODEL_BUCKET}/20260806":
        "⚠ 只有 5 個 .onnx，缺 classes.json，單獨還原不出可用服務",
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
    """數雲端有幾個物件。

    刻意收 bytes 再自己解碼，不用 `text=True, encoding="utf-8"`：這台是繁中 Windows，
    gcloud 的訊息裡只要出現中文路徑（專案路徑本身就有「淡江大學」）就是 CP950 位元組，
    utf-8 解碼會在讀取執行緒裡炸掉，而那個例外**不會傳回主執行緒**——
    `.stdout` 只是變成 None，然後在下一行以 AttributeError 現形，看起來像別的問題。

    `errors="replace"` 讓壞位元組變成問號而不是中斷。這裡只數開頭是 gs:// 的行，
    壞掉的字元不影響計數。
    """
    proc = subprocess.run(
        [gcloud(), "storage", "ls", "--recursive", f"{prefix}/**", "--project", PROJECT],
        capture_output=True,
    )
    out = (proc.stdout or b"").decode("utf-8", errors="replace")
    return sum(1 for line in out.splitlines() if line.startswith("gs://") and not line.endswith("/"))


def main():
    p = argparse.ArgumentParser(description="雲端同步：訓練照片、正式模型、技術文件")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pull", action="store_true", help="從 GCS 拉到本機（新機器用這個）")
    mode.add_argument("--push", action="store_true", help="把本機的變更推上 GCS")
    mode.add_argument("--verify", action="store_true", help="只比對數量，不搬動任何檔案")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    print(f"資料 {DATA_BUCKET}\n模型 {MODEL_BUCKET}\n")
    failed = []

    for local_rel, remote in {**DATASETS, **MODELS, **DOCS}.items():
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
            code = run([gcloud(), "storage", "rsync", remote, str(local),
                        "--recursive", "--project", PROJECT], args.dry_run)
        else:
            if not local.exists():
                print("   本機沒有這個目錄，略過（避免把雲端清空）")
                continue
            code = run([gcloud(), "storage", "rsync", str(local), remote,
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
