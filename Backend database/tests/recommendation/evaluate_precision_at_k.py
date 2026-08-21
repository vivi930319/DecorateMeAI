"""Repeatable offline recommendation metrics for manually labelled gold sets.

Usage:
  python tests/recommendation/evaluate_precision_at_k.py gold.json predictions.json

gold.json: {"richGirl": [global_product_id, ...], ...}
predictions.json: {"richGirl": [{"id": 1, "type": "lipsticks", ...}], ...}
"""
import json
import sys
from pathlib import Path


def precision_at_k(recommended, relevant, k):
    top = recommended[:k]
    return (sum(item.get("id") in relevant for item in top) / k) if k else 0.0


def main(gold_path, predictions_path):
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    predictions = json.loads(Path(predictions_path).read_text(encoding="utf-8"))
    rows = []
    for style, relevant_ids in gold.items():
        recommended = predictions.get(style, [])
        ids = [item.get("id") for item in recommended]
        disabled = sum(not item.get("inStock", True) for item in recommended)
        rows.append({
            "style": style,
            "precisionAt5": precision_at_k(recommended, set(relevant_ids), 5),
            "precisionAt10": precision_at_k(recommended, set(relevant_ids), 10),
            "duplicateRate": (len(ids) - len(set(ids))) / len(ids) if ids else 0.0,
            "disabledRate": disabled / len(recommended) if recommended else 0.0,
            "hallucinationRate": sum(not isinstance(item.get("id"), int) for item in recommended) / len(recommended) if recommended else 0.0,
        })
    print(json.dumps({"styles": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: evaluate_precision_at_k.py gold.json predictions.json")
    main(sys.argv[1], sys.argv[2])
