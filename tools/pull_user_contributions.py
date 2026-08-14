"""把使用者同意提供的修正樣本從 GCS 拉下來，並依「能不能直接拿去訓練」分류。

樣本長什麼樣
------------
`face_contributions.store()` 存的路徑本身就帶著全部資訊：

    gs://decorate-me-datasets/user_contributed/<roiSpecsVersion>/<part>/<label>/<jobId>.png
                                               └ 裁切規格版本   └ 部位  └ 使用者改成的類別

blob metadata 另有 `sampleForm`（`roi_crop` 或 `whole_front_image`／`whole_side_image`）、
`ownerId`（刪帳號時要用）、`mode`、`contributedAt`。

⚠ 兩種樣本不能混在一起訓練
--------------------------
    roi_crop           已經是 96²／128² 的部位裁切 —— **不可以再過一次 prepare_roi_cache**，
                       那會對一張裁切再裁一次，得到完全不同的東西
    whole_*_image      整張照片 —— 要走正常流程（prepare_roi_cache 裁 ROI）

所以這支把兩種分開放，並在最後印出各自的數量與去處。混用而不自知，
就是 identity_map 那種靜默失效：不會報錯，只是分數變差而且查不出原因。

⚠ 這些樣本沒有 identity
-----------------------
線上使用者不在 `identity_map` 裡，所以併進訓練集之後它們的 identity 是 -1。
依現行政策（`train_basic_cnn_roi.split_kfold_by_identity`）**它們只會留在 train、
永遠不進 val**——這是對的（不確定身分的樣本不能拿來驗證），但要知道：
**加再多這種樣本，驗證集也不會變大**，所以分數的信賴區間不會因此變窄。

用法
----
    .venv\\Scripts\\python.exe tools\\pull_user_contributions.py            # 只看有什麼，不下載
    .venv\\Scripts\\python.exe tools\\pull_user_contributions.py --download
"""

from __future__ import annotations

import argparse
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

BUCKET = "gs://decorate-me-datasets"
PREFIX = f"{BUCKET}/user_contributed"
PROJECT = "decorate-me"
# 已經是裁切的放這裡，跟策展資料集分開，避免有人不小心整包丟去重裁。
ROI_DEST = Path("data/user_contributed/roi_crops")
WHOLE_DEST = Path("data/user_contributed/whole_images")


def gcloud(*args: str) -> str:
    """呼叫 gcloud CLI。

    刻意用 CLI 而不是 google-cloud-storage 套件：這台本機的 .venv 不能裝它
    （protobuf 版本會跟 mediapipe 衝突，見專案慣例），而訓練流程需要 mediapipe。
    """
    result = subprocess.run(["gcloud.cmd", *args, "--project", PROJECT],
                            capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"gcloud 失敗：{' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="真的下載；預設只列出")
    args = parser.parse_args()

    listing = [line.strip() for line in gcloud("storage", "ls", f"{PREFIX}/**").splitlines()
               if line.strip().endswith(".png")]
    if not listing:
        print("目前沒有任何使用者貢獻樣本")
        return

    by_part: Counter[str] = Counter()
    by_label: dict[str, Counter[str]] = defaultdict(Counter)
    by_version: Counter[str] = Counter()
    for url in listing:
        parts = url.split("/")
        # …/user_contributed/<version>/<part>/<label>/<jobId>.png
        version, part, label = parts[-4], parts[-3], parts[-2]
        by_version[version] += 1
        by_part[part] += 1
        by_label[part][label] += 1

    print(f"共 {len(listing)} 張，裁切規格版本 {dict(by_version)}\n")
    for part, count in by_part.most_common():
        detail = "、".join(f"{label} {n}" for label, n in by_label[part].most_common())
        print(f"  {part:<12}{count:>4}   {detail}")

    if not args.download:
        print("\n（只列出，沒有下載。加 --download 才會真的抓下來）")
        return

    # sampleForm 存在 blob metadata 裡，一個一個問太慢；改用「規格版本」分流：
    # whole image 的樣本一律標成 roiSpecsVersion=whole_image（見 face_contributions）。
    for version in by_version:
        dest = WHOLE_DEST if version == "whole_image" else ROI_DEST
        target = dest / version
        target.mkdir(parents=True, exist_ok=True)
        print(f"\n下載 {version} → {target}")
        gcloud("storage", "cp", "-r", f"{PREFIX}/{version}/*", str(target))

    print(f"""
下載完成。接下來怎麼用：

  {WHOLE_DEST}   整張照片 → 可以併進 data/basic_full/grouped/<part>/<label>/
                             再重跑 prepare_roi_cache.py（正常流程）

  {ROI_DEST}     已經是裁切 → **不要**重跑 prepare_roi_cache，那會裁到裁切。
                             要用它得直接接進 rois.npz，或當成獨立的評估集。

兩種都沒有 identity，併進去之後只會出現在 train，不會進 val。""")


if __name__ == "__main__":
    main()
