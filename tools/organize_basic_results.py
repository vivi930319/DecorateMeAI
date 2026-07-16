import argparse
import csv
import shutil
from pathlib import Path


DEFAULT_INPUT = Path("data/basic_full/basic_face_analysis.csv")
DEFAULT_OUTPUT = Path("data/basic_full/grouped")

FEATURES = {
    "face_shape": "face_shape",
    "brow_shape": "brow_shape",
    "eye_shape": "eye_shape",
    "nose_shape": "nose_shape",
    "lip_shape": "lip_shape",
}


def safe_name(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    return (
        text.replace("/", "_")
        .replace("\\", "_")
        .replace(" ", "_")
        .replace("　", "_")
    )


def ensure_structure(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for feature in FEATURES:
        (root / feature).mkdir(parents=True, exist_ok=True)


def organize_rows(input_csv: Path, output_root: Path, copy_mode: str) -> tuple[int, int]:
    ensure_structure(output_root)
    copied = 0
    skipped = 0

    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") != "ok":
                skipped += 1
                continue

            source = Path(row["file_path"])
            if not source.exists():
                skipped += 1
                continue

            for feature, column in FEATURES.items():
                label = safe_name(row.get(column, ""))
                if not label:
                    skipped += 1
                    continue
                target_dir = output_root / feature / label
                target_dir.mkdir(parents=True, exist_ok=True)
                target_file = target_dir / source.name

                if target_file.exists():
                    continue

                if copy_mode == "copy":
                    shutil.copy2(source, target_file)
                else:
                    shutil.move(source, target_file)
                copied += 1

    return copied, skipped


def write_manifests(input_csv: Path, output_root: Path) -> None:
    rows_by_feature: dict[str, list[list[str]]] = {feature: [] for feature in FEATURES}

    with input_csv.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("status") != "ok":
                continue

            image_id = row.get("image_id", "")
            file_path = row.get("file_path", "")
            for feature, column in FEATURES.items():
                label = safe_name(row.get(column, ""))
                if not label:
                    continue
                grouped_path = output_root / feature / label / image_id
                rows_by_feature[feature].append([image_id, file_path, label, str(grouped_path)])

    for feature, rows in rows_by_feature.items():
        manifest = output_root / f"{feature}_manifest.csv"
        with manifest.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["image_id", "source_file", "label", "grouped_file"])
            writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Organize BASIC batch analysis results into training-friendly folders.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--mode", choices=["copy", "move"], default="copy")
    args = parser.parse_args()

    input_csv = Path(args.input)
    output_root = Path(args.output)
    if not input_csv.exists():
        raise SystemExit(f"Input CSV not found: {input_csv}")

    copied, skipped = organize_rows(input_csv, output_root, args.mode)
    write_manifests(input_csv, output_root)
    print(f"done copied={copied} skipped={skipped} output={output_root}")


if __name__ == "__main__":
    main()
