import argparse
import csv
from pathlib import Path

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
