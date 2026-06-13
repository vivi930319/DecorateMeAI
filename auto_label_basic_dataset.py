import argparse
import csv
import json
from pathlib import Path

from Face_analyzer_BASIC import FaceAnalyzer


def flatten_result(result):
    skin = result.get("膚色") or {}
    lab = skin.get("LAB") or {}
    lip_lab = result.get("嘴唇_LAB") or {}
    return {
        "analysis_version": result.get("分析版本", ""),
        "face_shape": result.get("臉型", ""),
        "brow_shape": result.get("眉型", ""),
        "eye_shape": result.get("眼型", ""),
        "nose_front": result.get("鼻型", ""),
        "lip_shape": result.get("嘴型", ""),
        "skin_season": skin.get("四季型", ""),
        "skin_level": skin.get("膚色分級", ""),
        "skin_lab_l": lab.get("L", ""),
        "skin_lab_a": lab.get("a", ""),
        "skin_lab_b": lab.get("b", ""),
        "lip_lab_l": lip_lab.get("L", ""),
        "lip_lab_a": lip_lab.get("a", ""),
        "lip_lab_b": lip_lab.get("b", ""),
        "raw_json": json.dumps(result, ensure_ascii=False),
    }


def main():
    parser = argparse.ArgumentParser(description="Run BASIC analyzer over selected dataset images.")
    parser.add_argument("--images", default="data/basic_usable/raw_images")
    parser.add_argument("--output", default="data/basic_usable/auto_labels_basic.csv")
    parser.add_argument("--limit", type=int, default=0, help="0 means all images")
    parser.add_argument("--batch-size", type=int, default=50, help="Maximum images to process in this run; 0 means no batch limit")
    parser.add_argument("--resume", action="store_true", help="Append to existing output and skip already processed image_id values")
    args = parser.parse_args()

    image_dir = Path(args.images)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    images = sorted(image_dir.glob("*.jpg"))
    processed_ids = set()
    if args.resume and output.exists():
        with output.open(encoding="utf-8", newline="") as f:
            processed_ids = {row["image_id"] for row in csv.DictReader(f) if row.get("image_id")}
        images = [path for path in images if path.name not in processed_ids]

    if args.limit:
        images = images[: args.limit]
    if args.batch_size:
        images = images[: args.batch_size]

    fieldnames = [
        "image_id",
        "status",
        "error",
        "analysis_version",
        "face_shape",
        "brow_shape",
        "eye_shape",
        "nose_front",
        "lip_shape",
        "skin_season",
        "skin_level",
        "skin_lab_l",
        "skin_lab_a",
        "skin_lab_b",
        "lip_lab_l",
        "lip_lab_a",
        "lip_lab_b",
        "raw_json",
    ]

    ok_count = 0
    fail_count = 0
    mode = "a" if args.resume and output.exists() else "w"
    with output.open(mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if mode == "w":
            writer.writeheader()
        for index, image_path in enumerate(images, start=1):
            row = {"image_id": image_path.name, "status": "ok", "error": ""}
            try:
                result = FaceAnalyzer(str(image_path)).export_json()
                row.update(flatten_result(result))
                ok_count += 1
            except Exception as exc:
                row["status"] = "failed"
                row["error"] = str(exc)
                fail_count += 1
            writer.writerow(row)
            f.flush()
            if index % 25 == 0:
                print(f"processed={index} ok={ok_count} failed={fail_count}")

    print(f"done this_run={len(images)} skipped_existing={len(processed_ids)} ok={ok_count} failed={fail_count}")
    print(f"output={output}")


if __name__ == "__main__":
    main()
