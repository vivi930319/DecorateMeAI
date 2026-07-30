"""用**手寫規則式**批次標註照片，輸出 CSV。原用途是為 CelebA bootstrap 初始標籤。

## ⚠️ 這支不能拿來驗證線上模型

它呼叫的是 `analyzer.get_face_shape()` / `get_eye_shape()` 這類**手寫 if-else**，
**完全不經過 ROI CNN／DINOv2**——也就是說它量到的是 fallback 的表現，不是線上答案。

兩者差距很大（同一組 5-fold）：

    眼型   規則式 0.439   vs   ConvNeXt 0.693
    唇型   規則式 0.422   vs   ConvNeXt 0.640

2026-07-31 踩過：拿這支做部署驗證，看到「桃杏眼 → 鳳眼 9/11」而以為模型或 ROI
裁切壞掉，花了很久去查通道順序與裁切邏輯，最後發現 ROI 像素**完全相同**，
是工具本身根本沒走模型那條路。規則式的眼型分支在 ear <= 0.327 一律回鳳眼，
那個「系統性偏移」正是它的正常行為。

**要驗證線上模型請直接跑：**

    from Face_analyzer_BASIC import FaceAnalyzer
    r = FaceAnalyzer(path).export_json()
    r["分類來源"]["眼型"]   # 應該是 roi_cnn 或 roi_dinov2_*，不是 rule_*

並檢查 `分類來源` 每個部位的 `final` 欄位，確認答案真的來自模型。
"""
import argparse
import csv
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 移到 tools/ 後仍能匯入根目錄的 Face_analyzer_BASIC
from Face_analyzer_BASIC import FaceAnalyzer


DEFAULT_SOURCE = Path("celeba_raw/img_align_celeba/img_align_celeba")
DEFAULT_OUTPUT = Path("data/basic_full/basic_face_analysis.csv")


def existing_ids(output_csv: Path) -> set[str]:
    if not output_csv.exists():
        return set()
    with output_csv.open("r", encoding="utf-8", newline="") as f:
        return {row["image_id"] for row in csv.DictReader(f) if row.get("image_id")}


def ensure_header(output_csv: Path) -> None:
    if output_csv.exists():
        return
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "image_id",
            "file_path",
            "status",
            "error",
            "analysis_version",
            "face_shape",
            "brow_shape",
            "eye_shape",
            "nose_front",
            "lip_shape",
        ])


def coarse_basic_result(image_path: Path) -> dict:
    analyzer = FaceAnalyzer(str(image_path))
    return {
        "分析版本": "BASIC",
        "臉型": analyzer.get_face_shape(),
        "眉型": analyzer.get_eyebrow_shape(),
        "眼型": analyzer.get_eye_shape(),
        "鼻型": analyzer.get_nose_shape(),
        "嘴型": analyzer.get_lip_shape(),
    }


def row_from_result(image_path: Path, result: dict) -> list:
    return [
        image_path.name,
        str(image_path),
        "ok",
        "",
        result.get("分析版本", ""),
        result.get("臉型", ""),
        result.get("眉型", ""),
        result.get("眼型", ""),
        result.get("鼻型", ""),
        result.get("嘴型", ""),
    ]


def row_from_error(image_path: Path, exc: Exception) -> list:
    return [
        image_path.name,
        str(image_path),
        "failed",
        str(exc),
        "",
        "",
        "",
        "",
        "",
        "",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch BASIC face analysis over CelebA images.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--limit", type=int, default=0, help="0 means no limit")
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--resume", action="store_true", help="Skip image_ids already written to output CSV")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    ensure_header(output)

    done_ids = existing_ids(output) if args.resume else set()
    images = sorted(source.glob("*.jpg"))
    if args.limit > 0:
        images = images[: args.limit]

    processed = 0
    ok_count = 0
    fail_count = 0

    with output.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        for image_path in images:
            if image_path.name in done_ids:
                continue

            processed += 1
            try:
                result = coarse_basic_result(image_path)
                writer.writerow(row_from_result(image_path, result))
                ok_count += 1
            except Exception as exc:
                writer.writerow(row_from_error(image_path, exc))
                fail_count += 1

            if processed % args.progress_every == 0:
                f.flush()
                print(
                    f"processed={processed} ok={ok_count} failed={fail_count} "
                    f"last={image_path.name}"
                )

    print(f"done processed={processed} ok={ok_count} failed={fail_count} output={output}")


if __name__ == "__main__":
    main()
