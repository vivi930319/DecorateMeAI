import argparse
import csv
from pathlib import Path


VALID_DECISIONS = {"", "keep", "drop", "quality_bad"}


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fieldnames):
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description="Apply BASIC dataset manual review decisions to labels.csv.")
    parser.add_argument("--labels", default="data/basic_usable/labels.csv")
    parser.add_argument("--review", default="data/basic_usable/review_queue.csv")
    parser.add_argument("--output", default="data/basic_usable/labels_review_applied.csv")
    parser.add_argument("--drop-output", default="data/basic_usable/dropped_by_review.csv")
    parser.add_argument("--in-place", action="store_true", help="Overwrite labels.csv after writing a backup.")
    args = parser.parse_args()

    labels_path = Path(args.labels)
    review_path = Path(args.review)
    output_path = labels_path if args.in_place else Path(args.output)
    drop_output = Path(args.drop_output)

    labels = read_csv(labels_path)
    reviews = read_csv(review_path)
    review_by_id = {}
    invalid = []
    for row in reviews:
        decision = (row.get("review_decision") or "").strip()
        if decision not in VALID_DECISIONS:
            invalid.append((row.get("image_id"), decision))
            continue
        review_by_id[row["image_id"]] = row

    if invalid:
        items = ", ".join(f"{image_id}:{decision}" for image_id, decision in invalid[:10])
        raise SystemExit(f"Invalid review_decision values: {items}")

    updated = []
    dropped = []
    counts = {"keep": 0, "drop": 0, "quality_bad": 0, "blank": 0}
    for label in labels:
        image_id = label["image_id"]
        review = review_by_id.get(image_id)
        if not review:
            updated.append(label)
            continue

        decision = (review.get("review_decision") or "").strip()
        if not decision:
            counts["blank"] += 1
            updated.append(label)
            continue

        if decision == "drop":
            counts["drop"] += 1
            dropped.append({
                "image_id": image_id,
                "file_path": label.get("file_path", ""),
                "reason": review.get("reason", ""),
                "note": review.get("note", ""),
            })
            continue

        if decision == "quality_bad":
            counts["quality_bad"] += 1
            label["quality"] = "bad"
            note = review.get("note") or review.get("reason") or "manual_review_quality_bad"
            label["note"] = append_note(label.get("note", ""), note)
            updated.append(label)
            continue

        if decision == "keep":
            counts["keep"] += 1
            if review.get("quality"):
                label["quality"] = review["quality"]
            note = review.get("note", "")
            if note:
                label["note"] = append_note(label.get("note", ""), note)
            updated.append(label)

    if args.in_place:
        backup_path = labels_path.with_suffix(".before_review.csv")
        write_csv(backup_path, labels, labels[0].keys())

    write_csv(output_path, updated, labels[0].keys())
    write_csv(drop_output, dropped, ["image_id", "file_path", "reason", "note"])

    print(f"labels_in={len(labels)} labels_out={len(updated)} dropped={len(dropped)}")
    print(f"decisions={counts}")
    print(f"output={output_path}")
    print(f"drop_output={drop_output}")


def append_note(existing, note):
    existing = (existing or "").strip()
    note = (note or "").strip()
    if not note:
        return existing
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"


if __name__ == "__main__":
    main()
