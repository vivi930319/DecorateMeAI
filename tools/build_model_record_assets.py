"""產生模型紀錄書用的資料樣本、5-fold 與混淆矩陣圖。"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "roi_cache"
RESULTS = ROOT / "models" / "basic_features_roi"
OUT = ROOT / "docs" / "model_record_assets"
PARTS = ("face_shape", "brow_shape", "eye_shape", "nose_shape", "lip_shape")
PART_TITLES = {
    "face_shape": "臉型", "brow_shape": "眉型", "eye_shape": "眼型",
    "nose_shape": "鼻型", "lip_shape": "唇型",
}
DINO_PICK = {
    "face_shape": "svm", "brow_shape": "svm", "eye_shape": "logreg",
    "nose_shape": "svm", "lip_shape": "logreg",
}


def setup_font():
    candidates = ["Microsoft JhengHei", "Microsoft YaHei", "Noto Sans CJK TC", "Arial Unicode MS"]
    names = {f.name for f in font_manager.fontManager.ttflist}
    for candidate in candidates:
        if candidate in names:
            plt.rcParams["font.sans-serif"] = [candidate]
            break
    plt.rcParams["axes.unicode_minus"] = False


def actual_path(raw):
    text = str(raw)
    if text.upper().startswith("T:\\"):
        return ROOT / text[3:]
    return Path(text)


def read_rgb(path):
    data = np.fromfile(path, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return cv2.cvtColor(image, cv2.COLOR_BGR2RGB)


def fit_thumbnail(image, width=280, height=220):
    canvas = np.full((height, width, 3), 247, dtype=np.uint8)
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(image, (max(1, int(image.shape[1] * scale)), max(1, int(image.shape[0] * scale))))
    y = (height - resized.shape[0]) // 2
    x = (width - resized.shape[1]) // 2
    canvas[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
    return canvas


def save_sample_sheets(records, rois):
    contour_files = {
        "face_shape": CACHE / "face_contour.npy",
        "brow_shape": CACHE / "brow_shape_contour.npy",
        "lip_shape": CACHE / "lip_shape_contour.npy",
    }
    contours = {part: np.load(path, mmap_mode="r") for part, path in contour_files.items() if path.is_file()}
    for part in PARTS:
        rows = [i for i, record in enumerate(records) if part in record["labels"]]
        by_label = {}
        for row in rows:
            by_label.setdefault(records[row]["labels"][part], row)
        columns = 3 if part in contours else 2
        fig, axes = plt.subplots(len(by_label), columns, figsize=(columns * 3.3, len(by_label) * 2.65))
        axes = np.asarray(axes).reshape(len(by_label), columns)
        for y, (label, row) in enumerate(sorted(by_label.items())):
            original = fit_thumbnail(read_rgb(actual_path(records[row]["path"])))
            axes[y, 0].imshow(original)
            axes[y, 0].set_ylabel(label, fontsize=11, fontweight="bold")
            axes[y, 1].imshow(rois[part][row])
            if part in contours:
                axes[y, 2].imshow(contours[part][row], cmap="gray")
            for axis in axes[y]:
                axis.set_xticks([]); axis.set_yticks([])
        titles = ["原始圖片", "MediaPipe RGB ROI"] + (["MediaPipe 形狀遮罩"] if part in contours else [])
        for axis, title in zip(axes[0], titles):
            axis.set_title(title, fontsize=12, fontweight="bold")
        fig.suptitle(f"{PART_TITLES[part]}：每類代表資料與模型輸入", fontsize=16, fontweight="bold")
        fig.tight_layout(rect=(0, 0, 1, 0.97))
        fig.savefig(OUT / f"samples_{part}.png", dpi=160, bbox_inches="tight")
        plt.close(fig)


def load_results():
    simple = json.loads((RESULTS / "cv_summary_simple_cnn_per_image.json").read_text(encoding="utf-8"))
    mobile = json.loads((RESULTS / "cv_summary_per_image.json").read_text(encoding="utf-8"))
    dino = json.loads((RESULTS / "dinov2_cv_per_image_results.json").read_text(encoding="utf-8"))
    return simple, mobile, dino


def save_fold_charts(simple, mobile, dino):
    for part in PARTS:
        values = {
            "基礎 CNN": simple[part]["cv"]["fold_macro_accuracies"],
            "MobileNetV3": mobile[part]["cv"]["fold_macro_accuracies"],
            "DINOv2": dino[part][DINO_PICK[part]]["fold_macros"],
        }
        x = np.arange(1, 6)
        fig, axis = plt.subplots(figsize=(9, 4.8))
        for name, scores in values.items():
            axis.plot(x, scores, marker="o", linewidth=2, label=f"{name}（平均 {np.mean(scores):.3f}）")
        axis.set(title=f"{PART_TITLES[part]}：相同 5-fold Macro Accuracy",
                 xlabel="Fold", ylabel="Macro Accuracy", xticks=x, ylim=(0, 0.8))
        axis.grid(alpha=0.25); axis.legend()
        fig.tight_layout(); fig.savefig(OUT / f"folds_{part}.png", dpi=170); plt.close(fig)


def save_confusions(simple, mobile, dino):
    for part in PARTS:
        classes = simple[part]["cv"]["classes"]
        matrices = [
            ("基礎 CNN", simple[part]["cv"]["pooled_confusion_matrix"]),
            ("MobileNetV3", mobile[part]["cv"]["pooled_confusion_matrix"]),
            ("DINOv2", dino[part][DINO_PICK[part]]["pooled_confusion_matrix"]),
        ]
        fig, axes = plt.subplots(1, 3, figsize=(17, 5.3))
        for axis, (name, raw) in zip(axes, matrices):
            cm = np.asarray(raw, dtype=float)
            norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
            image = axis.imshow(norm, cmap="Blues", vmin=0, vmax=1)
            for i in range(len(classes)):
                for j in range(len(classes)):
                    axis.text(j, i, f"{int(cm[i,j])}\n{norm[i,j]:.0%}", ha="center", va="center",
                              fontsize=7, color="white" if norm[i,j] > 0.55 else "black")
            axis.set_title(name, fontweight="bold")
            axis.set_xticks(range(len(classes)), classes, rotation=45, ha="right", fontsize=8)
            axis.set_yticks(range(len(classes)), classes, fontsize=8)
            axis.set_xlabel("模型預測"); axis.set_ylabel("人工標籤")
        fig.colorbar(image, ax=axes, fraction=0.02, pad=0.02)
        fig.suptitle(f"{PART_TITLES[part]}：5-fold 聚合混淆矩陣", fontsize=16, fontweight="bold")
        fig.subplots_adjust(top=0.85, bottom=0.22, wspace=0.38)
        fig.savefig(OUT / f"confusion_{part}.png", dpi=180, bbox_inches="tight")
        plt.close(fig)


def save_overview(simple, mobile, dino):
    labels = [PART_TITLES[p] for p in PARTS]
    series = {
        "基礎 CNN": [simple[p]["cv"]["mean_macro"] for p in PARTS],
        "MobileNetV3": [mobile[p]["cv"]["mean_macro"] for p in PARTS],
        "DINOv2": [dino[p][DINO_PICK[p]]["mean"] for p in PARTS],
    }
    x = np.arange(len(PARTS)); width = 0.25
    fig, axis = plt.subplots(figsize=(11, 5.5))
    for offset, (name, scores) in zip((-width, 0, width), series.items()):
        bars = axis.bar(x + offset, scores, width, label=name)
        axis.bar_label(bars, labels=[f"{score:.1%}" for score in scores], fontsize=8, padding=2)
    axis.axhline(0.70, color="#b23a48", linestyle="--", label="目標 70%")
    axis.set_xticks(x, labels); axis.set_ylim(0, 0.8); axis.set_ylabel("5-fold Macro Accuracy")
    axis.set_title("三種模型在五個分類任務的公平比較", fontsize=15, fontweight="bold")
    axis.grid(axis="y", alpha=0.2); axis.legend(ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout(); fig.savefig(OUT / "model_overview.png", dpi=180, bbox_inches="tight"); plt.close(fig)


def main():
    setup_font(); OUT.mkdir(parents=True, exist_ok=True)
    records = json.loads((CACHE / "index.json").read_text(encoding="utf-8"))["records"]
    archive = np.load(CACHE / "rois.npz")
    rois = {part: archive[part] for part in PARTS}
    save_sample_sheets(records, rois)
    simple, mobile, dino = load_results()
    save_fold_charts(simple, mobile, dino)
    save_confusions(simple, mobile, dino)
    save_overview(simple, mobile, dino)
    print(f"assets written to {OUT}")


if __name__ == "__main__":
    main()
