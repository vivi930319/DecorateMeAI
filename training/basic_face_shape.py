"""臉型分類（BASIC）：MobileNetV3-Small 吃臉部外框 ROI，5-fold 按人分組。

這個模型現在的狀況（2026-08-13 的評估報告）
-------------------------------------------
    accuracy 0.492｜macro-F1 0.483｜κ 0.365

    圓形臉  P 0.505  R 0.440  n=116
    心形臉  P 0.463  R 0.250  n=100   ← 幾乎認不出來
    方形臉  P 0.527  R 0.557  n=106
    長形臉  P 0.583  R 0.680  n=103
    鵝蛋臉  P 0.392  R 0.533  n=105

**問題不是不平衡（五類樣本很平均），是相鄰類別的界線模糊。** 心形臉的 recall 只有
0.250——36% 被判成鵝蛋臉、25% 被判成長形臉；圓形臉也有 29% 掉進方形臉。

臉型跟其他部位難的地方不一樣：它要看的是**整張臉的長寬比例與下顎輪廓**，是全局形狀，
不是局部紋理。

可以動手試的方向
----------------
1. **確認裁切沒有切掉輪廓**：臉型 ROI 是外框 + 8% 邊距（face_roi.ROI_SPECS）。
   額頭、下巴、兩頰任何一邊被切掉，判斷臉型最關鍵的資訊就沒了。
2. **對齊品質對臉型特別致命**：臉沒轉正的話長寬比例會失真，圓臉會被拉成橢圓。
   `tools/measure_angle_sensitivity.py` 可以量這件事對分數的影響。
3. **加 landmark 幾何特徵**：臉型本質上就是幾何（長寬比、下顎角度），
   可以用 MediaPipe 輪廓點算出比例當額外特徵，跟 CNN 特徵結合。
   這是臉型特別適合、但眉型不適合的做法（`tools/cascade_face_shape.py` 有相關嘗試）。

用法
----
    .venv\\Scripts\\python.exe training\\basic_face_shape.py
    .venv\\Scripts\\python.exe training\\basic_face_shape.py --epochs 40 --focal --class-weight
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

PART = "face_shape"


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
