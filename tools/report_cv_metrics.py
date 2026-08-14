"""把交叉驗證的混淆矩陣展開成一份標準的分類評估報告。

存在的理由：`train_basic_cnn_roi.py` 只把 `pooled_confusion_matrix` 與整體
accuracy 寫進 metrics JSON，於是每次討論「模型準不準」都只剩一個數字。
一個數字看不出「錯在哪」——類別不平衡時整體 accuracy 甚至會騙人（把所有樣本
都猜成最大類就能拿到不錯的分數，但那個模型毫無用處）。

這支不重新訓練，只讀既有 metrics JSON，補出影像辨識該有的那一整套：
per-class precision / recall / F1 / support、macro 與 weighted 平均、
balanced accuracy、Cohen's kappa，以及最常互相搞混的類別配對。

用法：
    python tools/report_cv_metrics.py                      # 五個部位、預設架構
    python tools/report_cv_metrics.py --suffix cv_resnet50_metrics
    python tools/report_cv_metrics.py --out docs/cv_report.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

METRICS_DIR = Path("models/basic_features_roi")
PARTS = ("face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape")
PART_ZH = {
    "face_shape": "臉型",
    "brow_shape": "眉型",
    "eye_shape": "眼型",
    "nose_shape": "鼻型",
    "lip_shape": "唇型",
}


def per_class_metrics(confusion: np.ndarray) -> dict[str, np.ndarray]:
    """precision / recall / f1 / support。分母為 0 時給 0，不讓 NaN 汙染平均。"""
    true_positive = np.diag(confusion).astype(float)
    predicted = confusion.sum(axis=0).astype(float)
    support = confusion.sum(axis=1).astype(float)
    with np.errstate(divide="ignore", invalid="ignore"):
        precision = np.where(predicted > 0, true_positive / predicted, 0.0)
        recall = np.where(support > 0, true_positive / support, 0.0)
        denominator = precision + recall
        f1 = np.where(denominator > 0, 2 * precision * recall / denominator, 0.0)
    return {"precision": precision, "recall": recall, "f1": f1, "support": support}


def cohen_kappa(confusion: np.ndarray) -> float:
    """一致性指標。它會扣掉「純靠猜也會對」的那一部分，所以類別不平衡時比
    accuracy 誠實得多：全部猜同一類的模型 kappa 是 0。"""
    total = confusion.sum()
    if total == 0:
        return 0.0
    observed = np.trace(confusion) / total
    expected = (confusion.sum(axis=0) * confusion.sum(axis=1)).sum() / (total * total)
    if np.isclose(expected, 1.0):
        return 0.0
    return float((observed - expected) / (1 - expected))


def top_confusions(confusion: np.ndarray, classes: list[str], limit: int = 3) -> list[str]:
    """最常被搞混的（真實 → 預測）配對，附「該類有多少比例掉到那裡」。"""
    pairs = []
    supports = confusion.sum(axis=1)
    for i, true_name in enumerate(classes):
        for j, predicted_name in enumerate(classes):
            if i == j or confusion[i][j] == 0:
                continue
            rate = confusion[i][j] / supports[i] if supports[i] else 0.0
            pairs.append((confusion[i][j], rate, true_name, predicted_name))
    pairs.sort(key=lambda item: item[0], reverse=True)
    return [
        f"{true_name} → {predicted_name}（{int(count)} 筆，佔該類 {rate:.0%}）"
        for count, rate, true_name, predicted_name in pairs[:limit]
    ]


def render_part(part: str, payload: dict) -> tuple[str, dict]:
    cv = payload["cv"]
    classes = list(cv["classes"])
    confusion = np.array(cv["pooled_confusion_matrix"], dtype=np.int64)
    stats = per_class_metrics(confusion)
    support = stats["support"]
    total = support.sum()

    accuracy = float(np.trace(confusion) / total) if total else 0.0
    macro_f1 = float(stats["f1"].mean())
    weighted_f1 = float((stats["f1"] * support).sum() / total) if total else 0.0
    balanced_accuracy = float(stats["recall"].mean())
    kappa = cohen_kappa(confusion)
    folds = cv.get("fold_macro_accuracies", [])

    lines = [
        f"## {PART_ZH.get(part, part)}（{part}）",
        "",
        f"- 樣本數 **{int(total)}**、類別數 {len(classes)}、{cv.get('n_folds', '?')}-fold"
        f"、架構 `{cv.get('architecture', '?')}`、epochs {cv.get('epochs', '?')}"
        f"、切分 `{cv.get('identity_mode', '?')}`",
        f"- **Accuracy {accuracy:.3f}** ｜ Balanced accuracy {balanced_accuracy:.3f}"
        f" ｜ Macro-F1 {macro_f1:.3f} ｜ Weighted-F1 {weighted_f1:.3f}"
        f" ｜ Cohen's κ {kappa:.3f}",
    ]
    if folds:
        fold_text = "、".join(f"{value:.3f}" for value in folds)
        lines.append(
            f"- 逐 fold accuracy：{fold_text}"
            f"（平均 {np.mean(folds):.3f} ± {np.std(folds):.3f}）"
        )
    lines += [
        "",
        "| 類別 | Precision | Recall | F1 | Support |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, name in enumerate(classes):
        lines.append(
            f"| {name} | {stats['precision'][index]:.3f} | {stats['recall'][index]:.3f} "
            f"| {stats['f1'][index]:.3f} | {int(support[index])} |"
        )

    lines += ["", "混淆矩陣（列＝真實，欄＝預測）：", "", "| 真實＼預測 | " + " | ".join(classes) + " |",
              "| --- |" + " --- |" * len(classes)]
    for index, name in enumerate(classes):
        cells = " | ".join(str(int(value)) for value in confusion[index])
        lines.append(f"| **{name}** | {cells} |")

    confusions = top_confusions(confusion, classes)
    if confusions:
        lines += ["", "最常搞混：" + "；".join(confusions)]
    lines.append("")

    summary = {
        "part": part,
        "samples": int(total),
        "classes": classes,
        "accuracy": accuracy,
        "balanced_accuracy": balanced_accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "cohen_kappa": kappa,
        "per_class": {
            name: {
                "precision": float(stats["precision"][index]),
                "recall": float(stats["recall"][index]),
                "f1": float(stats["f1"][index]),
                "support": int(support[index]),
            }
            for index, name in enumerate(classes)
        },
        "top_confusions": confusions,
    }
    return "\n".join(lines), summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suffix", default="cv_metrics",
                        help="metrics 檔尾綴，用來挑架構（例：cv_resnet50_metrics）")
    parser.add_argument("--parts", nargs="*", default=list(PARTS))
    parser.add_argument("--dir", default=str(METRICS_DIR),
                        help=f"metrics 所在目錄，預設 {METRICS_DIR}；對照實驗用 --out-dir 另存時要指過去")
    parser.add_argument("--out", default=None, help="輸出 Markdown 檔；省略則印到畫面")
    parser.add_argument("--json-out", default=None, help="同時輸出一份機器可讀的 JSON")
    args = parser.parse_args()

    sections: list[str] = []
    summaries: list[dict] = []
    overview = [
        "| 部位 | 樣本 | Accuracy | Balanced acc. | Macro-F1 | Weighted-F1 | κ |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    metrics_dir = Path(args.dir)
    for part in args.parts:
        path = metrics_dir / f"{part}_{args.suffix}.json"
        if not path.exists():
            print(f"跳過 {part}：找不到 {path}")
            continue
        section, summary = render_part(part, json.loads(path.read_text(encoding="utf-8")))
        sections.append(section)
        summaries.append(summary)
        overview.append(
            f"| {PART_ZH.get(part, part)} | {summary['samples']} | {summary['accuracy']:.3f} "
            f"| {summary['balanced_accuracy']:.3f} | {summary['macro_f1']:.3f} "
            f"| {summary['weighted_f1']:.3f} | {summary['cohen_kappa']:.3f} |"
        )

    report = "\n".join(["# 五官分類交叉驗證報告", "", *overview, "", *sections])
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"已寫入 {args.out}")
    else:
        print(report)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已寫入 {args.json_out}")


if __name__ == "__main__":
    main()
