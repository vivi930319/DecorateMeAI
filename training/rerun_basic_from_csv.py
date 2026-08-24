"""
從既有的 rerun CSV 重新跑 BASIC 臉部分析，產生新的輸出 CSV。
用法：
    python rerun_basic_from_csv.py \
        --input  data/basic_full/basic_face_analysis_rerun_20260616.csv \
        --output data/basic_full/basic_face_analysis_rerun_20260622.csv \
        [--limit 100]
"""

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import csv
from pathlib import Path

from Face_analyzer_BASIC import FaceAnalyzer

HEADER = [
    "image_id", "file_path", "status", "error",
    "analysis_version", "face_shape", "brow_shape",
    "eye_shape", "nose_shape", "lip_shape",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit",  type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=200)
    args = parser.parse_args()

    input_csv  = Path(args.input)
    output_csv = Path(args.output)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if args.limit > 0:
        rows = rows[: args.limit]

    processed = ok_count = fail_count = 0

    with output_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADER)

        for row in rows:
            image_path = Path(row["file_path"])
            processed += 1
            try:
                analyzer = FaceAnalyzer(str(image_path))
                writer.writerow([
                    row["image_id"],
                    row["file_path"],
                    "ok",
                    "",
                    "BASIC",
                    analyzer.get_face_shape(),
                    analyzer.get_eyebrow_shape(),
                    analyzer.get_eye_shape(),
                    analyzer.get_nose_shape(),
                    analyzer.get_lip_shape(),
                ])
                ok_count += 1
            except Exception as exc:
                writer.writerow([
                    row["image_id"],
                    row["file_path"],
                    "failed",
                    str(exc),
                    "", "", "", "", "", "",
                ])
                fail_count += 1

            if processed % args.progress_every == 0:
                f.flush()
                print(f"processed={processed} ok={ok_count} failed={fail_count} last={image_path.name}")

    print(f"done processed={processed} ok={ok_count} failed={fail_count} output={output_csv}")


if __name__ == "__main__":
    main()
