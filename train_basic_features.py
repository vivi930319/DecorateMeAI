"""Train one lightweight image classifier for each BASIC facial feature.

Input layout:
    data/basic_full/grouped/<feature>/<class>/*.{jpg,jpeg,png,webp}

Outputs:
    models/basic_features/<feature>.pt
    models/basic_features/<feature>_metrics.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]
COMPARISON_COLUMNS = {
    "face_shape": "face_shape_new",
    "brow_shape": "brow_shape_new",
    "eye_shape": "eye_shape_new",
    "nose_shape": "nose_new",
    "lip_shape": "lip_new",
}


class ImageSamples(Dataset):
    def __init__(self, samples: list[tuple[Path, int]], transform) -> None:
        self.samples = samples
        self.transform = transform

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, label = self.samples[index]
        with Image.open(path) as image:
            image = image.convert("RGB")
        return self.transform(image), label


def discover_samples(feature_dir: Path) -> tuple[list[str], list[tuple[Path, int]]]:
    classes_and_files: list[tuple[str, list[Path]]] = []
    for class_dir in sorted((p for p in feature_dir.iterdir() if p.is_dir()), key=lambda p: p.name):
        files = sorted(
            p for p in class_dir.iterdir()
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS and not p.name.startswith("._")
        )
        if files:
            classes_and_files.append((class_dir.name, files))

    classes = [name for name, _ in classes_and_files]
    samples = [
        (path, class_index)
        for class_index, (_, files) in enumerate(classes_and_files)
        for path in files
    ]
    return classes, samples


def discover_grouped_files(data_dir: Path) -> dict[str, dict[str, list[Path]]]:
    result: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    if not data_dir.is_dir():
        return result
    for feature_dir in (p for p in data_dir.iterdir() if p.is_dir()):
        for class_dir in (p for p in feature_dir.iterdir() if p.is_dir()):
            for path in class_dir.iterdir():
                if (
                    path.is_file()
                    and path.suffix.lower() in IMAGE_EXTENSIONS
                    and not path.name.startswith("._")
                ):
                    result[feature_dir.name][class_dir.name].append(path)
    return result


def load_comparison_files(
    comparison_csv: Path, path_csv: Path
) -> dict[str, dict[str, list[Path]]]:
    with path_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        image_paths = {
            row["image_id"]: Path(row["file_path"])
            for row in csv.DictReader(handle)
            if row.get("image_id") and row.get("file_path")
        }

    result: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    with comparison_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("status_new") != "ok":
                continue
            path = image_paths.get(row.get("image_id", ""))
            if path is None or not path.is_file():
                continue
            for feature, column in COMPARISON_COLUMNS.items():
                label = (row.get(column) or "").strip()
                if label:
                    result[feature][label].append(path)
    return result


def merge_labeled_files(*sources) -> dict[str, dict[str, list[Path]]]:
    merged: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    seen: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for source in sources:
        for feature, labels in source.items():
            for label, paths in labels.items():
                for path in paths:
                    key = (label, str(path.resolve()).lower())
                    if key not in seen[feature]:
                        merged[feature][label].append(path)
                        seen[feature].add(key)
    return merged


def index_labeled_files(
    labels: dict[str, list[Path]], min_samples: int
) -> tuple[list[str], list[tuple[Path, int]], dict[str, int]]:
    kept = sorted(name for name, paths in labels.items() if len(paths) >= min_samples)
    counts = {name: len(labels[name]) for name in kept}
    samples = [
        (path, class_index)
        for class_index, name in enumerate(kept)
        for path in sorted(labels[name])
    ]
    return kept, samples, counts


def stratified_split(
    samples: list[tuple[Path, int]], val_ratio: float, seed: int
) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
    grouped: dict[int, list[tuple[Path, int]]] = defaultdict(list)
    for sample in samples:
        grouped[sample[1]].append(sample)

    rng = random.Random(seed)
    train_samples: list[tuple[Path, int]] = []
    val_samples: list[tuple[Path, int]] = []
    for class_samples in grouped.values():
        rng.shuffle(class_samples)
        val_count = max(1, round(len(class_samples) * val_ratio))
        val_count = min(val_count, len(class_samples) - 1)
        val_samples.extend(class_samples[:val_count])
        train_samples.extend(class_samples[val_count:])
    rng.shuffle(train_samples)
    rng.shuffle(val_samples)
    return train_samples, val_samples


def make_transforms(image_size: int):
    train_transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.RandomHorizontalFlip(),
        transforms.RandomResizedCrop(image_size, scale=(0.82, 1.0), ratio=(0.9, 1.1)),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.12),
        transforms.RandomRotation(5),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    val_transform = transforms.Compose([
        transforms.Resize((image_size, image_size)),
        transforms.ToTensor(),
        transforms.Normalize(IMAGENET_MEAN, IMAGENET_STD),
    ])
    return train_transform, val_transform


def evaluate(model, loader, criterion, device, num_classes: int):
    model.eval()
    loss_sum = 0.0
    correct = 0
    total = 0
    confusion = [[0 for _ in range(num_classes)] for _ in range(num_classes)]
    with torch.inference_mode():
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            logits = model(images)
            loss_sum += criterion(logits, labels).item() * labels.size(0)
            predictions = logits.argmax(dim=1)
            correct += (predictions == labels).sum().item()
            total += labels.size(0)
            for truth, prediction in zip(labels.cpu().tolist(), predictions.cpu().tolist()):
                confusion[truth][prediction] += 1
    recalls = [
        confusion[index][index] / sum(confusion[index])
        for index in range(num_classes)
        if sum(confusion[index])
    ]
    macro_accuracy = sum(recalls) / len(recalls)
    return loss_sum / total, correct / total, macro_accuracy, confusion


def train_feature(
    feature_name: str,
    classes: list[str],
    samples: list[tuple[Path, int]],
    class_counts: dict[str, int],
    output_dir: Path,
    args,
    device: torch.device,
) -> dict | None:
    if len(classes) < 2:
        print(f"[skip] {feature_name}: 有效類別少於 2（找到 {len(classes)} 類）", flush=True)
        return None

    train_samples, val_samples = stratified_split(samples, args.val_ratio, args.seed)
    train_transform, val_transform = make_transforms(args.image_size)
    train_class_counts = Counter(label for _, label in train_samples)
    sample_weights = [1.0 / train_class_counts[label] for _, label in train_samples]
    sampler = WeightedRandomSampler(
        sample_weights,
        num_samples=len(train_samples),
        replacement=True,
        generator=torch.Generator().manual_seed(args.seed),
    )
    train_loader = DataLoader(
        ImageSamples(train_samples, train_transform),
        batch_size=args.batch_size,
        sampler=sampler,
        num_workers=0,
    )
    val_loader = DataLoader(
        ImageSamples(val_samples, val_transform),
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=0,
    )

    print(
        f"\n[{feature_name}] counts={class_counts} train={len(train_samples)} val={len(val_samples)}",
        flush=True,
    )
    model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(classes))
    model.to(device)

    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    best_accuracy = -1.0
    best_epoch = 0
    history = []
    model_path = output_dir / f"{feature_name}.pt"

    for epoch in range(1, args.epochs + 1):
        model.train()
        loss_sum = 0.0
        correct = 0
        total = 0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(images)
            loss = criterion(logits, labels)
            loss.backward()
            optimizer.step()
            loss_sum += loss.item() * labels.size(0)
            correct += (logits.argmax(dim=1) == labels).sum().item()
            total += labels.size(0)
        scheduler.step()

        val_loss, val_accuracy, val_macro_accuracy, confusion = evaluate(
            model, val_loader, criterion, device, len(classes)
        )
        train_loss = loss_sum / total
        train_accuracy = correct / total
        history.append({
            "epoch": epoch,
            "train_loss": train_loss,
            "train_accuracy": train_accuracy,
            "val_loss": val_loss,
            "val_accuracy": val_accuracy,
            "val_macro_accuracy": val_macro_accuracy,
        })
        print(
            f"  epoch {epoch:02d}/{args.epochs} loss={train_loss:.4f} "
            f"train={train_accuracy:.3f} val={val_accuracy:.3f} macro={val_macro_accuracy:.3f}",
            flush=True,
        )
        if val_macro_accuracy > best_accuracy:
            best_accuracy = val_macro_accuracy
            best_epoch = epoch
            torch.save({
                "architecture": "mobilenet_v3_small",
                "state_dict": model.state_dict(),
                "classes": classes,
                "class_to_idx": {name: index for index, name in enumerate(classes)},
                "image_size": args.image_size,
                "normalization": {"mean": IMAGENET_MEAN, "std": IMAGENET_STD},
                "feature": feature_name,
                "best_val_macro_accuracy": best_accuracy,
                "best_epoch": best_epoch,
            }, model_path)

    checkpoint = torch.load(model_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["state_dict"])
    val_loss, val_accuracy, val_macro_accuracy, confusion = evaluate(
        model, val_loader, criterion, device, len(classes)
    )
    metrics = {
        "feature": feature_name,
        "classes": classes,
        "class_counts": class_counts,
        "sample_count": len(samples),
        "train_count": len(train_samples),
        "val_count": len(val_samples),
        "seed": args.seed,
        "best_epoch": best_epoch,
        "best_val_accuracy": val_accuracy,
        "best_val_macro_accuracy": val_macro_accuracy,
        "val_loss": val_loss,
        "confusion_matrix": confusion,
        "history": history,
    }
    metrics_path = output_dir / f"{feature_name}_metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"  saved {model_path} (best val={val_accuracy:.3f}, macro={val_macro_accuracy:.3f})",
        flush=True,
    )
    return metrics


def parse_args():
    parser = argparse.ArgumentParser(description="Train BASIC facial-feature classifiers.")
    parser.add_argument("--data-dir", type=Path, default=Path("data/basic_full/grouped"))
    parser.add_argument("--output-dir", type=Path, default=Path("models/basic_features"))
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--image-size", type=int, default=160)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--val-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--comparison-csv", type=Path)
    parser.add_argument(
        "--path-csv",
        type=Path,
        default=Path("data/basic_full/basic_face_analysis.csv"),
    )
    parser.add_argument("--min-samples", type=int, default=2)
    parser.add_argument(
        "--no-grouped",
        action="store_true",
        help="Do not merge images already organized under --data-dir.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if not args.data_dir.is_dir():
        raise SystemExit(f"找不到資料目錄：{args.data_dir}")
    if not 0 < args.val_ratio < 1:
        raise SystemExit("--val-ratio 必須介於 0 和 1 之間")

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"device={device} epochs={args.epochs} output={args.output_dir}", flush=True)

    sources = []
    if args.comparison_csv:
        if not args.comparison_csv.is_file() or not args.path_csv.is_file():
            raise SystemExit("找不到 comparison CSV 或影像路徑 CSV")
        sources.append(load_comparison_files(args.comparison_csv, args.path_csv))
    if not args.no_grouped:
        sources.append(discover_grouped_files(args.data_dir))
    labeled_files = merge_labeled_files(*sources)

    results = []
    for feature_name in sorted(labeled_files):
        classes, samples, class_counts = index_labeled_files(
            labeled_files[feature_name], args.min_samples
        )
        result = train_feature(
            feature_name, classes, samples, class_counts, args.output_dir, args, device
        )
        if result:
            results.append(result)

    summary = {
        "device": str(device),
        "epochs": args.epochs,
        "features": [
            {
                "feature": item["feature"],
                "classes": item["classes"],
                "sample_count": item["sample_count"],
                "best_val_accuracy": item["best_val_accuracy"],
                "best_val_macro_accuracy": item["best_val_macro_accuracy"],
            }
            for item in results
        ],
    }
    summary_path = args.output_dir / "training_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成，摘要：{summary_path}", flush=True)


if __name__ == "__main__":
    main()
