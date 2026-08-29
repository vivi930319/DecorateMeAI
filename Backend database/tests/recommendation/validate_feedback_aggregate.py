"""Validate a de-identified facial-feedback aggregate before analysis."""

import argparse
import json
import re
from pathlib import Path


FORBIDDEN_MARKERS = {
    "email", "ownerid", "jobid", "userid", "memberid", "imagebase64",
    "photobase64", "data:image", "authorization", "token", "cookie",
}
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w.-]+")


def validate(payload: dict) -> list[str]:
    errors = []
    if not isinstance(payload, dict):
        return ["根節點必須是 JSON object"]
    rows = payload.get("rows")
    minimum = payload.get("minCount")
    versions = payload.get("modelVersions")
    if not isinstance(rows, list):
        errors.append("rows 必須是陣列")
        rows = []
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        errors.append("minCount 必須是正整數")
        minimum = 1
    if not isinstance(versions, dict) or not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in (versions or {}).values()
    ):
        errors.append("modelVersions 必須是非負整數計數 object")

    raw = json.dumps(payload, ensure_ascii=False).casefold()
    leaked = sorted(marker for marker in FORBIDDEN_MARKERS if marker in raw)
    if leaked:
        errors.append(f"出現禁止欄位／內容標記：{', '.join(leaked)}")
    if EMAIL_PATTERN.search(raw):
        errors.append("內容疑似包含 Email")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"rows[{index}] 必須是 object")
            continue
        count = row.get("count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            errors.append(f"rows[{index}].count 必須是非負整數")
        if row.get("part") is not None and isinstance(count, int) and count < minimum:
            errors.append(f"rows[{index}] 未遵守 minCount={minimum} 小格抑制")
        if row.get("agreed") is True and row.get("corrected") is not None:
            errors.append(f"rows[{index}] agreed=true 時 corrected 應為 null")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    errors = validate(payload)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    row_total = sum(row["count"] for row in payload["rows"])
    event_total = sum(payload["modelVersions"].values())
    print(f"OK: rows={len(payload['rows'])}, rowTotal={row_total}, events={event_total}")
    parts = {row.get("part") for row in payload["rows"] if row.get("part") is not None}
    if event_total and len(parts) == 5 and row_total != event_total * 5:
        print(
            "WARNING: 五個部位的列總數與 events × 5 不一致："
            f"{row_total} != {event_total * 5}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
