import argparse
import csv
import math
import re
from pathlib import Path

from PIL import Image, ImageDraw


def draw_wrapped(draw, text, xy, max_chars, fill):
    x, y = xy
    lines = [text[i : i + max_chars] for i in range(0, len(text), max_chars)] or [""]
    for line in lines[:3]:
        draw.text((x, y), line, fill=fill)
        y += 13


def compact_reason(reason):
    yaw = re.search(r"yaw=([-0-9.]+)", reason)
    pitch = re.search(r"pitch=([-0-9.]+)", reason)
    if yaw or pitch:
        return f"yaw={yaw.group(1) if yaw else '?'} pitch={pitch.group(1) if pitch else '?'}"
    if "膚色區域不足" in reason:
        return "skin region too small"
    return reason.encode("ascii", "ignore").decode("ascii") or "manual review"


def main():
    parser = argparse.ArgumentParser(description="Create contact sheets for BASIC dataset manual review.")
    parser.add_argument("--csv", default="data/basic_usable/needs_review.csv")
    parser.add_argument("--images", default="data/basic_usable/raw_images")
    parser.add_argument("--output", default="data/basic_usable/review_sheets")
    parser.add_argument("--per-sheet", type=int, default=20)
    args = parser.parse_args()

    rows = list(csv.DictReader(Path(args.csv).open(encoding="utf-8", newline="")))
    image_dir = Path(args.images)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    thumb_w, thumb_h = 170, 230
    cols = 4
    rows_per_sheet = math.ceil(args.per_sheet / cols)

    for sheet_index in range(math.ceil(len(rows) / args.per_sheet)):
        chunk = rows[sheet_index * args.per_sheet : (sheet_index + 1) * args.per_sheet]
        canvas = Image.new("RGB", (cols * thumb_w, rows_per_sheet * thumb_h), "white")
        draw = ImageDraw.Draw(canvas)
        for idx, row in enumerate(chunk):
            image_path = image_dir / row["image_id"]
            x0 = (idx % cols) * thumb_w
            y0 = (idx // cols) * thumb_h
            if image_path.exists():
                image = Image.open(image_path).convert("RGB")
                image.thumbnail((thumb_w - 12, 155))
                canvas.paste(image, (x0 + (thumb_w - image.width) // 2, y0 + 4))
            draw.text((x0 + 6, y0 + 162), row["image_id"], fill=(20, 20, 20))
            reason = compact_reason(row["reason"])
            draw_wrapped(draw, reason, (x0 + 6, y0 + 180), 20, fill=(120, 30, 30))

        out_path = out_dir / f"needs_review_sheet_{sheet_index + 1:02d}.jpg"
        canvas.save(out_path, quality=92)
        print(out_path)


if __name__ == "__main__":
    main()
