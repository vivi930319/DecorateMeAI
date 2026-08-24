"""鼻型分類（BASIC，正面）：MobileNetV3-Small 吃鼻部 ROI，5-fold 按人分組。

這個模型現在的狀況（2026-08-13 的評估報告）
-------------------------------------------
    accuracy 0.840｜macro-F1 0.839｜κ 0.680   ← 五個部位裡唯一堪用的

    寬鼻    P 0.912  R 0.759  n=137
    標準鼻  P 0.786  R 0.924  n=131

**為什麼這個特別準**：只有兩類，而且「寬 vs 不寬」是可以量的幾何差異，
不像眉型彎月／落尾那樣主觀。κ 0.680 代表它明顯超越亂猜。

剩下的錯誤集中在單一方向：寬鼻有 24% 被判成標準鼻（反向只有 8%），
也就是模型偏向「不太願意說寬」。調整決策閾值或類別權重就能換取兩者的平衡。

注意：正面鼻型跟 PRO 的側臉鼻型是**兩個不同的模型、不同的分類法**。
這支是正面兩類；側臉那支是五類（塌鼻／直挺鼻／翹鼻／蒜頭鼻／駝峰鼻），
見 `training/pro_nose_side.py`。兩者不要混用標籤。

用法
----
    .venv\\Scripts\\python.exe training\\basic_nose_shape.py
    .venv\\Scripts\\python.exe training\\basic_nose_shape.py --epochs 40 --focal --class-weight
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ shared/ 的模組 import 得到
import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from face_roi import IMAGENET_MEAN, IMAGENET_STD  # noqa: E402
from training import _dataset  # noqa: E402

PART = "nose_shape"


def build_model(n_classes: int) -> nn.Module:
    model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, n_classes)
    return model


def to_tensor(images: np.ndarray) -> torch.Tensor:
    """(N,H,W,3) uint8 RGB → 正規化後的 (N,3,H,W) float。

    快取存的就是 RGB（prepare_roi_cache 特地轉過）。這裡若再轉一次通道順序，
    訓練與線上推論吃的顏色就會相反，模型上線會無聲掉分。
    """
    array = images.astype(np.float32) / 255.0
    array = (array - np.array(IMAGENET_MEAN)) / np.array(IMAGENET_STD)
    return torch.from_numpy(array.transpose(0, 3, 1, 2)).float()


class FocalLoss(nn.Module):
    """(1-pt)^gamma 把已經分得好的樣本降權，梯度留給難分的。"""

    def __init__(self, weight=None, gamma=2.0):
        super().__init__()
        self.weight, self.gamma = weight, gamma

    def forward(self, logits, target):
        ce = nn.functional.cross_entropy(logits, target, weight=self.weight,
                                         label_smoothing=0.05, reduction="none")
        with torch.no_grad():   # pt 用未加權機率，否則稀有類梯度會被二次放大
            pt = logits.softmax(1).gather(1, target[:, None]).squeeze(1)
        return ((1 - pt) ** self.gamma * ce).mean()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--focal", action="store_true", help="改用 focal loss")
    parser.add_argument("--class-weight", action="store_true", help="損失加上類別權重")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    images, labels, groups, names = _dataset.load_part(PART)
    print(f"{PART}：{len(labels)} 張、{len(names)} 類 {names}、"
          f"{len(set(groups.tolist()))} 人、device={device}")

    all_true: list[int] = []
    all_pred: list[int] = []
    for fold, (train_idx, val_idx) in enumerate(_dataset.folds(labels, groups, args.folds, args.seed), 1):
        x_train, y_train = to_tensor(images[train_idx]), torch.from_numpy(labels[train_idx]).long()
        x_val, y_val = to_tensor(images[val_idx]), torch.from_numpy(labels[val_idx]).long()

        counts = np.bincount(labels[train_idx], minlength=len(names))
        # 稀有類抽中的機率提高，讓模型至少「看得到」它們。
        sampler = WeightedRandomSampler(
            [1.0 / counts[int(y)] for y in labels[train_idx]],
            num_samples=len(train_idx), replacement=True,
            generator=torch.Generator().manual_seed(args.seed))
        train_loader = DataLoader(TensorDataset(x_train, y_train),
                                  batch_size=args.batch_size, sampler=sampler)

        weight = None
        if args.class_weight:
            totals = torch.tensor(np.maximum(counts, 1), dtype=torch.float, device=device)
            weight = totals.sum() / (len(names) * totals)

        model = build_model(len(names)).to(device)
        criterion = (FocalLoss(weight=weight) if args.focal
                     else nn.CrossEntropyLoss(weight=weight, label_smoothing=0.05))
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

        for _ in range(args.epochs):
            model.train()
            for batch_x, batch_y in train_loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                optimizer.zero_grad(set_to_none=True)
                criterion(model(batch_x), batch_y).backward()
                optimizer.step()
            scheduler.step()

        model.eval()
        with torch.no_grad():
            predicted = model(x_val.to(device)).argmax(1).cpu().numpy()
        hit = float((predicted == labels[val_idx]).mean())
        print(f"  fold {fold}/{args.folds}  val={len(val_idx)} 張  accuracy={hit:.3f}")
        all_true += labels[val_idx].tolist()
        all_pred += predicted.tolist()

    print(f"\n===== {PART}（{args.folds}-fold 聚合）=====")
    _dataset.report(all_true, all_pred, names)


if __name__ == "__main__":
    main()
