"""把管理員在後台採用的使用者修正，併進 ROI 快取供重訓。

這是「使用者按了『這判斷不準』→ 後台覆核 → 進下一次訓練」這條線的最後一段。
前兩段分別在 `face/face_feedback.py`（收下修正、記錄覆核）與 admin 的「模型修正複核」
（人工採用或退回）。

為什麼只收 accepted
-------------------
使用者的修正是免費但**未經查核**的標籤：可能誤點，也可能自己就判斷錯——眉型、
唇型這種本來就主觀。全收會把誤點學進去，全不收等於這批標註白拿。所以中間插一個
人工關卡，而這支腳本只認那個關卡的產出。沒有 reviewStatus 的舊資料一律當 pending，
不當已採用：沒人看過的東西不該因為欄位是後來才加的就自動獲得信任。

資料從哪來
----------
標籤在 Firestore 的 `face_feedback`，影像在 GCS 的 `user_contributed/<版本>/<部位>/
<類別>/<job_id>.png`，兩邊用 job_id 對起來。只有使用者勾了「同意作為訓練資料」的
才會有影像；沒有影像的那些只能貢獻標籤，對 CNN 沒有用，這裡會跳過並回報數量。

影像已經是裁好的 ROI（除了臉型與側臉鼻型存整張圖，見 face_contributions.store），
所以不必再跑一次 MediaPipe——這也是為什麼這支腳本可以直接寫進 npz。

identity 怎麼給
---------------
每一個 job 一個新的 identity，且從既有快取的最大值 +1 開始往上編。同一個 job 裡
不同部位的樣本共用同一個 identity，因為它們來自同一張臉。不這樣做的話，
按人分組的交叉驗證會把同一張臉的不同部位拆到 train 與 val 兩邊——那會讓分數虛高。

用法
----
    # 先看會收進什麼，不動任何檔案
    python training/import_feedback_samples.py --dry-run

    # 實際併進去，輸出成新的快取目錄（不覆蓋原本的）
    python training/import_feedback_samples.py \
        --cache-dir data/roi_cache_dedup --out-dir data/roi_cache_plus_feedback

    # 然後用新快取重訓
    ROI_CACHE_DIR=data/roi_cache_plus_feedback python training/train_basic_cnn_roi.py ...

需要 `gcloud auth login` 過的憑證：Firestore 與 GCS 都透過 gcloud 取 token / 下載，
所以本機不必裝 google-cloud-* 套件。
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

from face_roi import PARTS
from training.training_run_store import RUNS_COLLECTION, get_document, now_iso, patch_document

# 反查：GCS 路徑用部位代號，覆核決定用中文欄位名。

BUCKET = "decorate-me-datasets"
PREFIX = "user_contributed"
FEEDBACK_COL = "face_feedback"

# 中文欄位名 → 快取用的部位代號。跟 basic_roi_shadow.PART_TO_FIELD 反過來，
# 但那個模組在 face/ 底下且會連帶 import 模型相關的東西，這裡只需要這張對照表。
FIELD_TO_PART = {
    "臉型": "face_shape",
    "眉型": "brow_shape",
    "眼型": "eye_shape",
    "鼻型": "nose_shape",
    "嘴型": "lip_shape",
}
PART_TO_FIELD = {v: k for k, v in FIELD_TO_PART.items()}


def _gcloud_exe() -> str:
    """找出 gcloud 執行檔。

    Windows 上它是 `gcloud.cmd`，而 subprocess 不走 shell、也不會自己補副檔名，
    直接傳 "gcloud" 會得到 WinError 2（找不到指定的檔案）——那個訊息完全看不出
    是「沒裝」還是「名字不對」。用 which 找一次就沒有這個歧義。
    """
    for name in ("gcloud", "gcloud.cmd"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError("找不到 gcloud，請先安裝 Google Cloud SDK 並執行 gcloud auth login")


def _gcloud(*args: str) -> str:
    """跑一個 gcloud 指令並回傳 stdout。失敗就讓例外往上拋。

    用 CLI 而不是 SDK：本機沒有 google-cloud-firestore／storage，而這支腳本是
    離線工具，不值得為它在訓練環境多裝兩個套件（那兩個又各自拉一串相依）。
    """
    out = subprocess.run([_gcloud_exe(), *args], capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise RuntimeError(f"gcloud {' '.join(args)} 失敗：{out.stderr.strip()[:300]}")
    return out.stdout.strip()


def _unwrap(value: dict):
    """把 Firestore REST 的型別包裝剝掉，還原成一般的 Python 值。"""
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "booleanValue", "timestampValue"):
        if key in value:
            return value[key]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "mapValue" in value:
        return {k: _unwrap(v) for k, v in (value["mapValue"].get("fields") or {}).items()}
    if "arrayValue" in value:
        return [_unwrap(v) for v in (value["arrayValue"].get("values") or [])]
    if "nullValue" in value:
        return None
    return value


def fetch_feedback(project: str) -> list[dict]:
    """讀出整個 face_feedback 集合。

    分頁要跟到底：只讀第一頁的話，採用了但排在後面的修正會被安靜地漏掉，
    而畫面上完全看不出來——那種漏掉最難查。
    """
    token = _gcloud("auth", "print-access-token")
    base = (f"https://firestore.googleapis.com/v1/projects/{project}"
            f"/databases/(default)/documents/{FEEDBACK_COL}")
    docs: list[dict] = []
    page_token = ""
    while True:
        url = f"{base}?pageSize=300" + (f"&pageToken={page_token}" if page_token else "")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for doc in data.get("documents", []):
            docs.append({k: _unwrap(v) for k, v in (doc.get("fields") or {}).items()})
        page_token = data.get("nextPageToken") or ""
        if not page_token:
            break
    return docs


def list_samples() -> dict[str, list[str]]:
    """job_id → 那個 job 在 GCS 上的所有樣本路徑。"""
    listing = _gcloud("storage", "ls", "-r", f"gs://{BUCKET}/{PREFIX}/**")
    by_job: dict[str, list[str]] = defaultdict(list)
    for line in listing.splitlines():
        line = line.strip()
        if not line.endswith(".png"):
            continue
        by_job[Path(line).stem].append(line)
    return by_job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=None,
                        help="GCP 專案（預設讀 gcloud config）")
    parser.add_argument("--cache-dir", default="data/roi_cache",
                        help="要併進去的既有快取")
    parser.add_argument("--out-dir", default=None,
                        help="輸出目錄。不給就是 <cache-dir>_plus_feedback")
    parser.add_argument("--dry-run", action="store_true",
                        help="只印出會收進什麼，不寫檔")
    parser.add_argument("--training-run", default="",
                        help="只匯入後台指定的 face_training_runs 批次")
    args = parser.parse_args()

    project = args.project or _gcloud("config", "get-value", "project")
    cache_dir = Path(args.cache_dir)
    out_dir = Path(args.out_dir) if args.out_dir else cache_dir.with_name(cache_dir.name + "_plus_feedback")

    print(f"專案 {project}｜既有快取 {cache_dir}")

    docs = fetch_feedback(project)
    training_run = None
    run_selections: dict[str, dict[str, str]] = {}
    if args.training_run:
        training_run = get_document(project, RUNS_COLLECTION, args.training_run)
        if not training_run:
            raise SystemExit(f"找不到訓練批次：{args.training_run}")
        run_selections = training_run.get("selections") or {}
        selected_ids = set(run_selections)
        docs = [d for d in docs if (d.get("feedbackId") or f"FB-{d.get('jobId')}") in selected_ids]
        print(f"訓練批次 {args.training_run}：限定 {len(docs)} 筆回饋")
    status = Counter(d.get("reviewStatus") or "pending" for d in docs)
    print(f"face_feedback 共 {len(docs)} 筆：" +
          "、".join(f"{k} {v}" for k, v in sorted(status.items())))

    # 逐部位採用：一筆修正裡可能只有嘴型被採用、眼型被退回，所以要看
    # reviewDecisions 而不是文件層級的 reviewStatus（那只是摘要）。
    # 舊格式（只有 reviewStatus 沒有 reviewDecisions）仍然支援：整筆 accepted
    # 就視同每個修正過的部位都被採用。
    accepted = []
    for d in docs:
        dec = d.get("reviewDecisions") or {}
        if dec:
            # accepted  用使用者的標籤
            # corrected 用管理員的標籤（管理員看得到影像，使用者是憑印象改的）
            # rejected  不收
            fields = {f for f, v in dec.items() if v in ("accepted", "corrected")}
        elif d.get("reviewStatus") == "accepted":
            fields = set((d.get("corrections") or {}).keys())
        else:
            fields = set()
        # 舊版整筆 accepted 會在 reviewDecisions 留下 _all；它不是實際部位，
        # 但仍代表 corrections 中的每一個欄位都被採用。
        if fields == {"_all"}:
            fields = set((d.get("corrections") or {}).keys())
        if training_run:
            selected = run_selections.get(d.get("feedbackId") or f"FB-{d.get('jobId')}") or {}
            fields &= set(selected)
        if fields:
            accepted.append({**d, "_acceptedFields": fields,
                             "_runLabels": (run_selections.get(d.get("feedbackId") or f"FB-{d.get('jobId')}") or {})})
    if not accepted:
        print("\n沒有任何一筆被採用，沒有東西可以併。")
        print("請先到後台的「模型修正複核」逐筆看過並按「採用」——這一步刻意需要人，"
              "未經查核的標籤混進訓練集之後很難查回來。")
        return 0

    by_job = list_samples()
    print(f"GCS 上有影像樣本的 job：{len(by_job)} 個")

    # 先盤點：哪些採用的修正真的有影像可用。
    usable: list[tuple[str, str, str, str]] = []   # (job_id, part, label, gs_path)
    no_sample = 0
    for doc in accepted:
        job_id = doc.get("jobId") or ""
        paths = by_job.get(job_id) or []
        if not paths:
            no_sample += 1
            continue
        for gs_path in paths:
            parts = gs_path.split("/")
            if len(parts) < 4:
                continue
            part, label = parts[-3], parts[-2]
            if part not in PARTS:
                # PRO 的側臉鼻型（nose_shape_side）走另一顆模型、另一個快取，
                # 不屬於 BASIC 的五個部位，這裡跳過而不是硬塞。
                continue
            # 被退回的部位不能進訓練集，即使同一筆的其他部位被採用了。
            # GCS 的路徑用部位代號（brow_shape），覆核用中文欄位名（眉型），
            # 所以要換算過去再比對。
            field = PART_TO_FIELD.get(part)
            if field and field not in doc["_acceptedFields"]:
                continue
            # GCS 的路徑是存檔當下寫的，用的是**使用者**說的類別。管理員改判之後
            # 那個路徑就不代表正確答案了——檔案不必搬，讀進來的時候換掉標籤即可。
            override = doc.get("_runLabels", {}).get(field or "") or (doc.get("reviewLabels") or {}).get(field or "")
            if override:
                label = override
            usable.append((job_id, part, label, gs_path))

    print(f"\n採用 {len(accepted)} 筆，其中 {no_sample} 筆沒有影像（使用者沒同意保存），"
          f"可用的樣本 {len(usable)} 張：")
    tally = Counter(f"{p}/{l}" for _, p, l, _ in usable)
    for key, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {key:28} {n:3} 張")

    if args.dry_run:
        print("\n--dry-run：沒有寫入任何檔案。")
        return 0
    if not usable:
        print("\n沒有可用的影像樣本，不產生新快取。")
        return 0

    # 讀既有快取。np.load 的 npz 是惰性的，要先全部取出來才能改。
    rois = {part: arr for part, arr in np.load(cache_dir / "rois.npz").items()}
    index = json.loads((cache_dir / "index.json").read_text(encoding="utf-8"))
    records = index["records"]
    sizes = {part: rois[part].shape[1] for part in rois}
    print(f"\n既有快取 {len(records)} 張，各部位尺寸 {sizes}")

    next_identity = max((r.get("identity", -1) for r in records), default=-1) + 1
    identity_of: dict[str, int] = {}

    tmp = Path(tempfile.mkdtemp(prefix="feedback_roi_"))
    added: dict[str, list[np.ndarray]] = defaultdict(list)
    new_records: list[dict] = []
    skipped: list[tuple[str, str]] = []
    try:
        # 一次抓一個 job 的全部檔案，比一張一張 cp 少掉大量的行程啟動成本。
        for job_id in sorted({j for j, _, _, _ in usable}):
            job_dir = tmp / job_id
            job_dir.mkdir(parents=True, exist_ok=True)

        for job_id, part, label, gs_path in usable:
            local = tmp / job_id / f"{part}__{label}.png"
            try:
                _gcloud("storage", "cp", gs_path, str(local))
            except Exception as exc:
                skipped.append((gs_path, f"下載失敗：{exc}"))
                continue
            img = cv2.imdecode(np.fromfile(str(local), dtype=np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                skipped.append((gs_path, "讀不出影像"))
                continue

            size = sizes[part]
            if img.shape[0] != size or img.shape[1] != size:
                # 臉型與側臉鼻型存的是整張圖，其餘存 ROI；尺寸對不上就縮到快取的規格。
                # 這對 ROI 是無害的重取樣，對整張臉型圖則是把外框壓成正方形——
                # 跟 crop_roi 對臉型做的事一致（它的 ROI 本來就接近整張臉）。
                img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)

            # 快取一律存 RGB，見 prepare_roi_cache 的說明。存進 BGR 會讓訓練吃到的
            # 通道順序跟線上推論不同，模型上線後會無聲掉分。
            added[part].append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))

            if job_id not in identity_of:
                identity_of[job_id] = next_identity
                next_identity += 1
            new_records.append({
                "path": gs_path,
                "labels": {part: label},
                "identity": identity_of[job_id],
                # 標記來源，之後才分得出「這張是使用者貢獻的」——線上照片與影劇截圖
                # 的分布不同，需要分開看分數時就靠這個欄位。
                "source": "user_feedback",
            })
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if skipped:
        print(f"\n跳過 {len(skipped)} 張：")
        for path, why in skipped[:5]:
            print(f"  - {Path(path).name}: {why}")

    # npz 的每個部位都必須有相同的第一維長度：index.json 的第 i 筆對應每個部位的第 i 張。
    # 一筆貢獻樣本只有一個部位有影像，其餘部位補一張全零並且**不給標籤**——
    # load_part 只取「這個部位有標籤」的樣本，所以補的那些不會被任何一個部位讀到。
    total_new = len(new_records)
    per_part_cursor = {part: 0 for part in rois}
    stacked = {part: np.zeros((total_new, sizes[part], sizes[part], 3), dtype=rois[part].dtype)
               for part in rois}
    for i, record in enumerate(new_records):
        part = next(iter(record["labels"]))
        stacked[part][i] = added[part][per_part_cursor[part]]
        per_part_cursor[part] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_dir / "rois.npz",
        **{part: np.concatenate([rois[part], stacked[part]]) for part in rois},
    )
    (out_dir / "index.json").write_text(
        json.dumps({"records": records + new_records, "failed": index.get("failed", [])},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # identity_map 一起帶過去，訓練腳本與 prepare_roi_cache 都會找它。
    src_map = cache_dir / "identity_map.json"
    if src_map.is_file():
        shutil.copy2(src_map, out_dir / "identity_map.json")

    if training_run and not args.dry_run:
        patch_document(project, RUNS_COLLECTION, args.training_run, {
            "samplesImported": len(new_records),
            "samplesImportedAt": now_iso(),
            "cacheDir": str(out_dir),
        })

    print(f"\n完成：{len(records)} + {total_new} = {len(records) + total_new} 張，寫到 {out_dir}")
    for part in PARTS:
        n = sum(1 for r in new_records if part in r["labels"])
        if n:
            print(f"  {part:12} 新增 {n:3} 張")
    print(f"\n接著用新快取重訓：")
    print(f"  ROI_CACHE_DIR={out_dir} python training/train_basic_cnn_roi.py --parts <部位> ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
