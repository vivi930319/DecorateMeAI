"""用裁切後的部位 ROI 訓練 MobileNetV3-small，並做「切分方式」對照實驗。

跟舊的 train_basic_features.py 的差別，也是這支存在的理由：

1. 餵的是部位 ROI，不是整張臉。舊腳本把整張臉 resize 成 160x160 後要模型判斷鼻型，
   鼻子在圖裡只剩幾十個像素，模型很容易改去學「這個人是誰」。
2. 支援按 identity 分組切分。資料是從影劇截圖蒐集的，同一個藝人常有多張，
   隨機切分會讓同一張臉同時出現在 train 和 val，驗證分數會虛高。
3. 每個部位跑兩種切分（random / identity）當對照組，把洩漏幅度量出來。
4. 額外算「現行規則式」在同一個 val set 上的分數當 baseline ——
   CNN 要贏過它才有替換的價值。

輸出：
    models/basic_features_roi/<part>.onnx        線上推論用（onnxruntime，不需要 torch）
    models/basic_features_roi/<part>_metrics.json
    models/basic_features_roi/training_summary.json
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

from face_roi import IMAGENET_MEAN, IMAGENET_STD, PARTS, ROI_SPECS

CACHE_DIR = Path("data/roi_cache")
OUT_DIR = Path("models/basic_features_roi")


class RoiDataset(Dataset):
    """ROI 已經是裁好的 uint8 陣列，這裡只做增強 + 正規化。

    刻意不做 RandomHorizontalFlip：眼型的「上揚/下垂」、眉型的「落尾」都是有左右方向性的，
    水平翻轉會把落尾眉變成上揚眉，等於餵錯標籤。舊腳本翻了，那是個 bug。
    """

    def __init__(self, rois: np.ndarray, labels: np.ndarray, train: bool):
        self.rois = rois
        self.labels = labels
        self.train = train

    def __len__(self):
        return len(self.labels)

    def __getitem__(self, index):
        img = self.rois[index].astype(np.float32) / 255.0  # 已是 RGB
        if self.train:
            img = self._augment(img)
        img = (img - IMAGENET_MEAN) / IMAGENET_STD
        return torch.from_numpy(np.ascontiguousarray(img.transpose(2, 0, 1))), int(self.labels[index])

    def _augment(self, img: np.ndarray) -> np.ndarray:
        # 亮度/對比抖動：模擬不同拍攝光線
        if random.random() < 0.7:
            img = img * random.uniform(0.85, 1.15) + random.uniform(-0.06, 0.06)
        # 小幅平移：模擬 landmark 偵測的抖動，讓模型別太依賴 ROI 對得剛剛好
        if random.random() < 0.5:
            shift = int(img.shape[0] * 0.04)
            dx, dy = random.randint(-shift, shift), random.randint(-shift, shift)
            img = np.roll(img, (dy, dx), axis=(0, 1))
        return np.clip(img, 0.0, 1.0)


def load_cache():
    rois = np.load(CACHE_DIR / "rois.npz")
    index = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))
    return {part: rois[part] for part in PARTS}, index["records"]


def build_part_data(part: str, all_rois, records):
    """挑出有這個部位標籤的樣本，回傳 (ROI 陣列, 類別索引, identity, 類別名稱)。"""
    rows = [i for i, r in enumerate(records) if part in r["labels"]]
    classes = sorted({records[i]["labels"][part] for i in rows})
    class_to_idx = {name: i for i, name in enumerate(classes)}

    rois = all_rois[part][rows]
    labels = np.array([class_to_idx[records[i]["labels"][part]] for i in rows], dtype=np.int64)
    identities = np.array([records[i]["identity"] for i in rows], dtype=np.int64)
    return rois, labels, identities, classes


def split_random(labels, identities, val_ratio, seed):
    """類別分層的隨機切分。會洩漏 —— 只當對照組，不要拿來選模型。"""
    rng = random.Random(seed)
    train_idx, val_idx = [], []
    by_class = defaultdict(list)
    for i, label in enumerate(labels):
        by_class[int(label)].append(i)
    for indices in by_class.values():
        rng.shuffle(indices)
        n_val = max(1, round(len(indices) * val_ratio))
        n_val = min(n_val, len(indices) - 1)
        val_idx.extend(indices[:n_val])
        train_idx.extend(indices[n_val:])
    return train_idx, val_idx


def split_by_identity(labels, identities, val_ratio, seed):
    """按 identity 分組切分：同一個人的所有照片只會落在 train 或 val 其中一邊。

    做法是在每個類別內，把該類的 identity 洗牌後依序丟進 val，直到湊到 val_ratio 的張數。
    identity = -1（聚類失敗）的樣本一律留在 train，避免污染驗證集。
    """
    rng = random.Random(seed)
    train_idx, val_idx = [], []

    by_class = defaultdict(list)
    for i, label in enumerate(labels):
        by_class[int(label)].append(i)

    for indices in by_class.values():
        id_to_rows = defaultdict(list)
        unknown = []
        for i in indices:
            ident = int(identities[i])
            (unknown if ident < 0 else id_to_rows[ident]).append(i)

        ids = list(id_to_rows)
        rng.shuffle(ids)
        target = len(indices) * val_ratio
        taken, chosen = 0, []
        for ident in ids:
            if taken >= target or len(chosen) >= len(ids) - 1:  # 至少留一個 identity 給 train
                break
            chosen.append(ident)
            taken += len(id_to_rows[ident])

        for ident in ids:
            (val_idx if ident in chosen else train_idx).extend(id_to_rows[ident])
        train_idx.extend(unknown)

    return train_idx, val_idx


def evaluate(model, loader, device, n_classes):
    model.eval()
    confusion = np.zeros((n_classes, n_classes), dtype=np.int64)
    with torch.inference_mode():
        for images, labels in loader:
            preds = model(images.to(device)).argmax(dim=1).cpu().numpy()
            for truth, pred in zip(labels.numpy(), preds):
                confusion[truth][pred] += 1
    correct = int(np.trace(confusion))
    total = int(confusion.sum())
    per_class_recall = [
        float(confusion[i][i] / confusion[i].sum()) if confusion[i].sum() else float("nan")
        for i in range(n_classes)
    ]
    valid = [r for r in per_class_recall if not np.isnan(r)]
    return {
        "accuracy": correct / total if total else 0.0,
        "macro_accuracy": float(np.mean(valid)) if valid else 0.0,
        "per_class_recall": per_class_recall,
        "confusion_matrix": confusion.tolist(),
        "val_count": total,
    }


def split_kfold_by_identity(labels, identities, n_folds, seed):
    """按 identity 分組的 k-fold：每個 identity 的所有照片整組落在同一個 fold 的 val。

    跟 split_by_identity 有一個重要差異：identity 是「全域」指派到 fold，不是在每個類別內
    各自指派。split_by_identity 在類別內分組，所以一個標註矛盾的身分（同部位被標成兩類）
    可能一半照片進 train、一半進 val —— 這是隱性的身分洩漏。這裡先按 identity 分組、
    用該身分的多數類做分層平衡，就不會發生。

    identity = -1（聚類失敗）的樣本一律留在 train，永遠不進任何 fold 的 val
    （沿用單次切分的政策：不確定身分的樣本不能拿來驗證）。
    """
    rng = random.Random(seed)
    id_to_rows = defaultdict(list)
    for i, ident in enumerate(identities):
        if int(ident) >= 0:
            id_to_rows[int(ident)].append(i)

    ids = list(id_to_rows)
    rng.shuffle(ids)
    ids.sort(key=lambda d: -len(id_to_rows[d]))  # 大身分先放，貪婪平衡才有效；同大小維持洗牌順序

    fold_val = [[] for _ in range(n_folds)]
    fold_class_counts = [Counter() for _ in range(n_folds)]
    for ident in ids:
        rows = id_to_rows[ident]
        dominant = Counter(int(labels[i]) for i in rows).most_common(1)[0][0]
        k = min(range(n_folds),
                key=lambda f: (fold_class_counts[f][dominant], sum(fold_class_counts[f].values())))
        fold_val[k].extend(rows)
        for i in rows:
            fold_class_counts[k][int(labels[i])] += 1

    all_idx = set(range(len(labels)))
    return [(sorted(all_idx - set(val)), sorted(val)) for val in fold_val]


# 眼型 7 類在每類 30~64 張的規模下分不乾淨（CNN macro 僅 0.378，
# 「杏仁/桃花/丹鳳/細長」的視覺差異本來就細微）。先併成 3 大類把準確率做起來，
# 之後資料補足再細分。分組依據是混淆矩陣：杏仁/桃花跟圓眼互相混、丹鳳/瞇縫跟細長眼互相混。
EYE_MERGE_MAP = {
    "杏仁眼": "圓眼",
    "桃花眼": "圓眼",
    "丹鳳眼": "細長眼",
    "瞇縫眼": "細長眼",
    # 圓眼、細長眼、下垂眼 維持原名
}


def apply_label_merge(labels, classes, merge_map):
    """把類別名稱依 merge_map 重新映射，回傳 (new_labels, new_classes)。"""
    merged_names = sorted({merge_map.get(name, name) for name in classes})
    name_to_idx = {name: i for i, name in enumerate(merged_names)}
    new_labels = np.array(
        [name_to_idx[merge_map.get(classes[l], classes[l])] for l in labels], dtype=np.int64)
    return new_labels, merged_names


def find_conflict_identities(labels, identities):
    """回傳「同一身分在這個部位被標成多個類別」的 identity 集合。

    同一個人的眉型不會在兩張照片之間改變，所以這些是標註矛盾 ——
    模型在這種樣本上學不到一致的決策邊界（正確標籤本身互相打架）。
    """
    seen = defaultdict(set)
    for label, ident in zip(labels, identities):
        if int(ident) >= 0:
            seen[int(ident)].add(int(label))
    return {ident for ident, labs in seen.items() if len(labs) > 1}


class SimpleRoiCNN(nn.Module):
    """不使用預訓練權重的基礎 CNN，作為 MobileNetV3 / DINOv2 的公平對照組。"""

    def __init__(self, n_classes):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.MaxPool2d(2),
            nn.Conv2d(128, 192, 3, padding=1), nn.BatchNorm2d(192), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d(1),
        )
        self.classifier = nn.Sequential(nn.Flatten(), nn.Dropout(0.25), nn.Linear(192, n_classes))

    def forward(self, x):
        return self.classifier(self.features(x))


def build_model(architecture, n_classes, pretrained=True):
    if architecture == "simple_cnn":
        return SimpleRoiCNN(n_classes)
    weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model = mobilenet_v3_small(weights=weights)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, n_classes)
    return model


def train_one(part, rois, labels, identities, classes, split_name, train_idx, val_idx, args, device):
    n_classes = len(classes)

    n_val_ids = len(set(int(identities[i]) for i in val_idx if identities[i] >= 0))
    n_train_ids = len(set(int(identities[i]) for i in train_idx if identities[i] >= 0))
    print(f"\n  [{part} / {split_name}] train={len(train_idx)} 張 ({n_train_ids} 人)  "
          f"val={len(val_idx)} 張 ({n_val_ids} 人)", flush=True)

    train_labels = labels[train_idx]
    counts = Counter(train_labels.tolist())
    weights = [1.0 / counts[int(l)] for l in train_labels]
    sampler = WeightedRandomSampler(weights, num_samples=len(train_idx), replacement=True,
                                    generator=torch.Generator().manual_seed(args.seed))

    train_loader = DataLoader(
        RoiDataset(rois[train_idx], train_labels, train=True),
        batch_size=args.batch_size, sampler=sampler, num_workers=0)
    val_loader = DataLoader(
        RoiDataset(rois[val_idx], labels[val_idx], train=False),
        batch_size=args.batch_size, shuffle=False, num_workers=0)

    model = build_model(args.architecture, n_classes, pretrained=True)
    model.to(device)

    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

    best = {"macro_accuracy": -1.0}
    best_state = None
    history = []

    for epoch in range(1, args.epochs + 1):
        model.train()
        for images, targets in train_loader:
            images, targets = images.to(device), targets.to(device)
            optimizer.zero_grad(set_to_none=True)
            loss = criterion(model(images), targets)
            loss.backward()
            optimizer.step()
        scheduler.step()

        metrics = evaluate(model, val_loader, device, n_classes)
        history.append({"epoch": epoch, "val_accuracy": metrics["accuracy"],
                        "val_macro_accuracy": metrics["macro_accuracy"]})
        print(f"    epoch {epoch:02d}/{args.epochs}  "
              f"val_acc={metrics['accuracy']:.3f}  macro={metrics['macro_accuracy']:.3f}", flush=True)

        if metrics["macro_accuracy"] > best["macro_accuracy"]:
            best = metrics
            best["epoch"] = epoch
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    return {
        "split": split_name,
        "classes": classes,
        "train_count": len(train_idx),
        "val_count": len(val_idx),
        "train_identities": n_train_ids,
        "val_identities": n_val_ids,
        "best": best,
        "history": history,
    }, best_state


def export_onnx(model_state, part, classes, device, architecture="mobilenet_v3_small"):
    """匯出 ONNX。線上用 onnxruntime 推論就好，不必把 200MB 的 torch 塞進 Cloud Run 映像
    （insightface 本來就依賴 onnxruntime，等於零額外成本）。"""
    model = build_model(architecture, len(classes), pretrained=False)
    model.load_state_dict(model_state)
    model.eval()

    size = ROI_SPECS[part]["size"]
    dummy = torch.zeros(1, 3, size, size)
    name = f"{part}_simple_cnn" if architecture == "simple_cnn" else part
    onnx_path = OUT_DIR / f"{name}.onnx"
    # dynamo=False：torch 2.12 的新 exporter 預設會把權重另外存成 <name>.onnx.data。
    # MobileNetV3-small 才 10MB，根本不需要 external data，拆成兩個檔只會讓部署多一個
    # 「少複製一個檔就靜默壞掉」的機會。舊 exporter 直接吐單一自帶權重的 .onnx。
    torch.onnx.export(
        model, dummy, str(onnx_path),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    torch.save(model_state, OUT_DIR / f"{name}.pt")  # 留著，之後要重匯出或接續訓練不必重跑
    (OUT_DIR / f"{name}_classes.json").write_text(
        json.dumps({"classes": classes, "size": size, "architecture": architecture},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return onnx_path


def parse_args():
    p = argparse.ArgumentParser(description="用部位 ROI 訓練 BASIC 臉部特徵分類器")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--val-ratio", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--parts", nargs="*", default=list(PARTS))
    p.add_argument("--skip-random", action="store_true",
                   help="跳過隨機切分對照組，只跑按人切分")
    p.add_argument("--cv", type=int, default=0, metavar="N",
                   help="改跑 N-fold 按人分組交叉驗證（只做評估，不匯出 ONNX）。"
                        "單次 25%% 切分的 val 只有 43~105 張、分數雜訊 ±0.1，"
                        "CV 讓每張圖都輪流當過考題，數字才穩得住")
    p.add_argument("--merge-eye", action="store_true",
                   help="眼型 7 類合併為 3 類（杏仁/桃花->圓眼、丹鳳/瞇縫->細長眼）")
    p.add_argument("--drop-conflicts", action="store_true",
                   help="剔除標註矛盾的身分（同一人同部位被標成多個類別）的所有照片")
    p.add_argument("--architecture", choices=("mobilenet_v3_small", "simple_cnn"),
                   default="mobilenet_v3_small",
                   help="訓練架構；simple_cnn 是不使用預訓練權重的基礎 CNN 對照組")
    p.add_argument("--identity-mode", choices=("cluster", "per_image"), default="cluster",
                   help="人物分組方式；per_image 適用於每個部位內每人只有一張照片的資料集")
    p.add_argument("--face-input", choices=("rgb", "contour"), default="rgb",
                   help="臉型輸入；contour 使用 MediaPipe 外輪廓二值遮罩")
    p.add_argument("--contour-file", default=None,
                   help="要讀哪一份輪廓快取（預設 face_contour.npy；高解析度是 face_contour_224.npy）")
    p.add_argument("--contour-parts", nargs="*", default=[], choices=list(PARTS),
                   help="指定使用 MediaPipe 二值形狀遮罩的部位")
    return p.parse_args()


def run_cv(part, rois, labels, identities, classes, args, device):
    """N-fold 按人分組交叉驗證。回傳可寫進 summary 的結果 dict。"""
    folds = split_kfold_by_identity(labels, identities, args.cv, args.seed)
    n_classes = len(classes)
    fold_macros = []
    agg_confusion = np.zeros((n_classes, n_classes), dtype=np.int64)

    for k, (train_idx, val_idx) in enumerate(folds, 1):
        result, _ = train_one(part, rois, labels, identities, classes,
                              f"cv {k}/{args.cv}", train_idx, val_idx, args, device)
        fold_macros.append(result["best"]["macro_accuracy"])
        agg_confusion += np.array(result["best"]["confusion_matrix"], dtype=np.int64)

    # 聚合混淆矩陣：每張（有 identity 的）圖恰好在某一個 fold 當過一次考題，
    # 所以聚合後的 per-class recall 是「整個資料集」的成績，不再受單一 val set 的運氣影響。
    per_class_recall = [
        float(agg_confusion[i][i] / agg_confusion[i].sum()) if agg_confusion[i].sum() else None
        for i in range(n_classes)
    ]
    valid = [r for r in per_class_recall if r is not None]
    pooled_macro = float(np.mean(valid)) if valid else 0.0

    print(f"\n  >> {part} CV{args.cv}：各 fold macro = "
          + ", ".join(f"{m:.3f}" for m in fold_macros))
    print(f"     平均 {np.mean(fold_macros):.3f} ± {np.std(fold_macros):.3f}"
          f"　聚合(pooled) {pooled_macro:.3f}")

    return {
        "classes": classes,
        "n_folds": args.cv,
        "fold_macro_accuracies": fold_macros,
        "mean_macro": float(np.mean(fold_macros)),
        "std_macro": float(np.std(fold_macros)),
        "pooled_macro": pooled_macro,
        "pooled_per_class_recall": per_class_recall,
        "pooled_confusion_matrix": agg_confusion.tolist(),
        "merge_eye": bool(args.merge_eye),
        "drop_conflicts": bool(args.drop_conflicts),
        "epochs": args.epochs,
        "architecture": args.architecture,
        "identity_mode": args.identity_mode,
        "face_input": args.face_input,
        "contour_parts": list(args.contour_parts),
    }


def main():
    args = parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"device={device}  epochs={args.epochs}\n")

    all_rois, records = load_cache()
    if args.face_input == "contour":
        # 解析度不同的遮罩存成不同檔名，這樣可以並存比較（見 prepare_face_contour_cache --size）
        contour_file = args.contour_file or "face_contour.npy"
        all_rois["face_shape"] = np.load(CACHE_DIR / contour_file)
        print(f"臉型改用輪廓遮罩：{contour_file} {all_rois['face_shape'].shape}")
    for part in args.contour_parts:
        all_rois[part] = np.load(CACHE_DIR / f"{part}_contour.npy")
    summary = {}

    for part in args.parts:
        rois, labels, identities, classes = build_part_data(part, all_rois, records)

        if args.identity_mode == "per_image":
            # 這批資料是一個人的五官分別分類；在單一部位內每張圖都是獨立人物。
            # 不使用 InsightFace 聚類，避免把外貌相似的不同人物錯誤綁成同一組。
            identities = np.arange(len(labels), dtype=np.int64)

        if args.merge_eye and part == "eye_shape":
            labels, classes = apply_label_merge(labels, classes, EYE_MERGE_MAP)

        if args.drop_conflicts:
            conflicts = find_conflict_identities(labels, identities)
            keep = [i for i, ident in enumerate(identities) if int(ident) not in conflicts]
            dropped = len(labels) - len(keep)
            if dropped:
                print(f"  剔除 {len(conflicts)} 個標註矛盾的身分，共 {dropped} 張")
                rois, labels, identities = rois[keep], labels[keep], identities[keep]

        print(f"\n===== {part} =====")
        print(f"  {len(labels)} 張, {len(classes)} 類: {classes}")

        if args.cv:
            # 不同實驗（合併類別/剔除矛盾）各自存檔，免得互相覆蓋、事後對不出哪個數字是哪個實驗的
            tag = ("_simple_cnn" if args.architecture == "simple_cnn" else "") + \
                  ("_per_image" if args.identity_mode == "per_image" else "") + \
                  ("_contour" if args.face_input == "contour" else "") + \
                  ("_feature_contour" if args.contour_parts else "") + \
                  ("_merged" if (args.merge_eye and part == "eye_shape") else "") + \
                  ("_noconflict" if args.drop_conflicts else "")
            summary[part] = {"cv": run_cv(part, rois, labels, identities, classes, args, device)}
            (OUT_DIR / f"{part}_cv{tag}_metrics.json").write_text(
                json.dumps(summary[part], ensure_ascii=False, indent=2), encoding="utf-8")
            continue

        splits = [("identity", split_by_identity)]
        if not args.skip_random:
            splits.insert(0, ("random", split_random))

        part_result = {}
        for split_name, split_fn in splits:
            train_idx, val_idx = split_fn(labels, identities, args.val_ratio, args.seed)
            result, state = train_one(part, rois, labels, identities, classes,
                                      split_name, train_idx, val_idx, args, device)
            part_result[split_name] = result
            if split_name == "identity":
                onnx_path = export_onnx(state, part, classes, device, args.architecture)
                print(f"    已匯出 {onnx_path}")

        if "random" in part_result:
            gap = (part_result["random"]["best"]["macro_accuracy"]
                   - part_result["identity"]["best"]["macro_accuracy"])
            part_result["leakage_gap"] = gap
            print(f"\n  >> 洩漏幅度：隨機切分 {part_result['random']['best']['macro_accuracy']:.3f} "
                  f"vs 按人切分 {part_result['identity']['best']['macro_accuracy']:.3f} "
                  f"(虛高 {gap:+.3f})")

        summary[part] = part_result
        (OUT_DIR / f"{part}_metrics.json").write_text(
            json.dumps(part_result, ensure_ascii=False, indent=2), encoding="utf-8")

    # CV 是評估用，寫到獨立檔案 —— training_summary.json 是單次切分的正式結果，
    # eval_rule_baseline.py / tune_hybrid.py 都讀它，覆蓋掉會讓對照表拿不到 CNN 分數。
    if args.cv:
        cv_tag = ("_simple_cnn" if args.architecture == "simple_cnn" else "") + \
                 ("_per_image" if args.identity_mode == "per_image" else "") + \
                 ("_contour" if args.face_input == "contour" else "") + \
                 ("_feature_contour" if args.contour_parts else "") + \
                 ("_merged" if args.merge_eye else "") + \
                 ("_noconflict" if args.drop_conflicts else "")
        summary_name = f"cv_summary{cv_tag}.json"
    else:
        summary_name = "training_summary.json"
    (OUT_DIR / summary_name).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n\n========== 總結（macro accuracy）==========")
    if args.cv:
        print(f"{'部位':12s} {'CV 平均':>10s} {'±std':>8s} {'聚合':>8s}   各 fold")
        for part, result in summary.items():
            cv = result["cv"]
            folds_s = ", ".join(f"{m:.3f}" for m in cv["fold_macro_accuracies"])
            print(f"{part:12s} {cv['mean_macro']:>10.3f} {cv['std_macro']:>8.3f} "
                  f"{cv['pooled_macro']:>8.3f}   [{folds_s}]")
        return

    header = f"{'部位':12s} {'隨機切分(虛高)':>16s} {'按人切分(可信)':>16s} {'洩漏':>8s}"
    print(header)
    for part, result in summary.items():
        rnd = result.get("random", {}).get("best", {}).get("macro_accuracy")
        ident = result["identity"]["best"]["macro_accuracy"]
        gap = result.get("leakage_gap")
        rnd_s = f"{rnd:.3f}" if rnd is not None else "-"
        gap_s = f"{gap:+.3f}" if gap is not None else "-"
        print(f"{part:12s} {rnd_s:>16s} {ident:>16.3f} {gap_s:>8s}")


if __name__ == "__main__":
    main()
