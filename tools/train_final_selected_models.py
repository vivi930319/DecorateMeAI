"""依 5-fold 選型結果，用 100% 資料訓練正式候選模型。"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC
from torch import nn
from torch.utils.data import DataLoader, WeightedRandomSampler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from face_roi import ROI_SPECS  # noqa: E402
from train_basic_cnn_roi import (  # noqa: E402
    RoiDataset, build_model, build_part_data, load_cache,
)

OUT_DIR = Path("models/final_features_20260719")
MOBILE_PARTS = ("brow_shape", "lip_shape")
EPOCHS = 20
SEED = 42


def train_mobilenet(part, rois, labels, classes, device):
    counts = Counter(labels.tolist())
    weights = [1.0 / counts[int(label)] for label in labels]
    sampler = WeightedRandomSampler(
        weights, num_samples=len(labels), replacement=True,
        generator=torch.Generator().manual_seed(SEED),
    )
    loader = DataLoader(
        RoiDataset(rois, labels, train=True), batch_size=32,
        sampler=sampler, num_workers=0,
    )
    model = build_model("mobilenet_v3_small", len(classes), pretrained=True).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)
    for epoch in range(1, EPOCHS + 1):
        model.train()
        losses = []
        for images, targets in loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()
            losses.append(float(loss.detach()))
        scheduler.step()
        print(f"{part}: epoch {epoch:02d}/{EPOCHS}, loss={np.mean(losses):.4f}", flush=True)

    model = model.cpu().eval()
    size = ROI_SPECS[part]["size"]
    onnx_path = OUT_DIR / f"{part}.onnx"
    torch.onnx.export(
        model, torch.zeros(1, 3, size, size), str(onnx_path),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    torch.save(model.state_dict(), OUT_DIR / f"{part}.pt")
    (OUT_DIR / f"{part}_classes.json").write_text(json.dumps({
        "classes": classes, "size": size, "architecture": "mobilenet_v3_small",
        "epochs": EPOCHS, "train_count": len(labels), "training_scope": "100_percent",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def train_dinov2(records):
    embeddings = np.load("data/roi_cache/dinov2_embeddings.npz")["embeddings"]
    all_rois, _ = load_cache()
    # 2026-07-31：眼型由 logistic_regression 改成 linear_svc。
    #
    # 原本的選擇來自 per-image 切分的比較——那正是規格書 §八 標「不可採信」的協定
    # （同一個人的照片同時進 train 與 val）。改用 identity 切分的 5-fold 重量：
    #
    #     眼型  SVM 0.625 ± 0.060   vs   LogReg 0.592 ± 0.058
    #
    # ⚠️ 差距 +0.033 落在 std 內，依 §9.2 只能算並列，**不是**「SVM 明確較好」。
    # 換過去的理由是「原本的選擇依據壞掉，重選一次比較誠實」，而且兩者是同一條
    # DINOv2 推論路徑、只差一個線性頭，換過去零額外成本。
    selections = {
        "face_shape": (LinearSVC(class_weight="balanced", C=1.0, max_iter=5000), "linear_svc"),
        "eye_shape": (LinearSVC(class_weight="balanced", C=1.0, max_iter=5000), "linear_svc"),
        "nose_shape": (LinearSVC(class_weight="balanced", C=1.0, max_iter=5000), "linear_svc"),
    }
    for part, (classifier, classifier_name) in selections.items():
        rows = [i for i, record in enumerate(records) if part in record["labels"]]
        _, labels, _, classes = build_part_data(part, all_rois, records)
        classifier.fit(embeddings[rows], labels)
        joblib.dump(classifier, OUT_DIR / f"{part}_dinov2_{classifier_name}.joblib")
        (OUT_DIR / f"{part}_classes.json").write_text(json.dumps({
            "classes": classes, "architecture": "dinov2_vits14",
            "classifier": classifier_name, "embedding_size": 384,
            "input_size": 224, "train_count": len(labels), "training_scope": "100_percent",
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{part}: DINOv2 {classifier_name} fitted on {len(labels)} images", flush=True)


def main():
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_rois, records = load_cache()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    for part in MOBILE_PARTS:
        rois, labels, _, classes = build_part_data(part, all_rois, records)
        train_mobilenet(part, rois, labels, classes, device)
    train_dinov2(records)
    (OUT_DIR / "model_selection.json").write_text(json.dumps({
        "dataset_images": len(records),
        # 2026-07-31 改用 identity 切分。先前寫的是 per-image——那是規格書 §八 標
        # 「不可採信」的協定，同一個人的照片會同時進 train 與 val，分數虛高。
        # 眼型的分類器就是被那份比較選錯的。
        "selection_basis": "identity-grouped 5-fold macro accuracy (split_kfold_by_identity, seed=42)",
        "models": {
            "face_shape": "dinov2_vits14+linear_svc",
            "brow_shape": "mobilenet_v3_small",
            "eye_shape": "dinov2_vits14+linear_svc",
            "nose_shape": "dinov2_vits14+linear_svc",
            "lip_shape": "mobilenet_v3_small",
        },
        # 這裡列的是「訓練了哪些候選」，不等於線上實際採用哪一個——
        # 正式路由在 basic_roi_shadow.dinov2_first_parts()，目前只有眼型走 DINOv2，
        # 臉型／眉型／鼻型／唇型都是 CNN（見發展歷程規格書 §7.10、§13.2）。
        "measured_macro_identity_5fold": {
            "face_shape": {"cnn_6e4": 0.521, "dinov2_svm": 0.424, "chosen": "cnn"},
            "brow_shape": {"cnn_6e4": 0.511, "dinov2_logreg": 0.543, "chosen": "cnn",
                           "note": "DINOv2 高 0.032 但落在 std 0.074 內，維持 CNN 省一條推論路徑"},
            "eye_shape": {"cnn_6e4": 0.562, "dinov2_svm": 0.625, "dinov2_logreg": 0.592, "chosen": "dinov2_svm"},
            "nose_shape": {"cnn_6e4": 0.849, "dinov2_svm": 0.846, "chosen": "cnn"},
            "lip_shape": {"cnn_6e4": 0.553, "dinov2_logreg": 0.513, "chosen": "cnn"},
        },
        "note": "Accuracy comes from CV artifacts; these files were fitted on 100% of data.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"final candidates written to {OUT_DIR}")


if __name__ == "__main__":
    main()
