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
    selections = {
        "face_shape": (LinearSVC(class_weight="balanced", C=1.0, max_iter=5000), "linear_svc"),
        "eye_shape": (LogisticRegression(max_iter=3000, class_weight="balanced", C=1.0), "logistic_regression"),
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
        "selection_basis": "per-image stratified 5-fold macro accuracy",
        "models": {
            "face_shape": "dinov2_vits14+linear_svc",
            "brow_shape": "mobilenet_v3_small",
            "eye_shape": "dinov2_vits14+logistic_regression",
            "nose_shape": "dinov2_vits14+linear_svc",
            "lip_shape": "mobilenet_v3_small",
        },
        "note": "Accuracy comes from CV artifacts; these files were fitted on 100% of data.",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"final candidates written to {OUT_DIR}")


if __name__ == "__main__":
    main()
