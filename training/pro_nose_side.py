"""側臉鼻型分類（PRO）：ConvNeXt-Tiny 吃**整張側臉圖**，5-fold 按人分組。

跟 BASIC 那五支最大的不同：不裁切
----------------------------------
BASIC 的五個部位都餵 ROI 裁切，這一支餵整張圖。這不是偷懶，是實測的結果：
側臉的 MediaPipe FaceMesh **只認得 73.5%**，而且失敗率依類別偏斜
（塌鼻 60.4%、翹鼻 93.4%）。用裁切等於讓「能不能偵測到臉」去決定哪些樣本進得了
訓練集，類別分布會被扭曲——模型學到的會是「偵測得到的那種臉長什麼樣」。

所以這支不呼叫 Face BASIC 的 crop_roi。線上推論也是同一條路：
`pro_nose_side_model.predict()` 直接把整張 frame 縮到 224 丟進 ONNX，
而 `Face_analyzer_PRO.py` 只負責把側面照交給它。訓練與推論吃同一種輸入。

這個模型現在的狀況
------------------
    類別：塌鼻／直挺鼻／翹鼻／蒜頭鼻／駝峰鼻（models/pro_nose_side/*_classes.json）
    架構：convnext_tiny，224×224，40 epochs，train_count 636

    ⚠ 除了塌鼻，各類的驗證樣本只有 36～46 張，側臉 identity 覆蓋率僅 52%。
    模型自己會在回應裡帶 `caveat` 欄位講這件事，前端也照實顯示——
    這是**加值資訊，不是可靠判斷**，改動它之前先看清楚樣本量。

兩個踩過的坑，改這支之前務必知道
--------------------------------
1. **類別合併只做了一半**：朝天鼻資料夾的 61 個唯一內容全部也在翹鼻資料夾裡。
   去重時「先看到誰算誰」而順序由資料夾字母序決定，「朝」在「翹」前面，
   於是翹鼻 200 張只剩 133 張進訓練——這個類別的存在完全建立在字母排序上。
   正式腳本用 `LABEL_ALIASES` 對照表處理，不刪資料夾（刪了不能反悔，
   而且搬檔案會讓 identity map 的路徑鍵失效）。這支沿用同一張表。
2. **identity 要按人分組**：跟 BASIC 一樣，同一個人的側臉照不能同時出現在
   train 與 val，否則分數虛高。

正式腳本是根目錄的 `train_pro_nose_side.py`（它另外做 DINOv2 對照、幾何特徵融合、
ONNX 匯出）。這支只做「一個架構、一輪交叉驗證、印出完整指標」，方便單獨讀懂。

用法
----
    .venv\\Scripts\\python.exe training\\pro_nose_side.py
    .venv\\Scripts\\python.exe training\\pro_nose_side.py --epochs 40 --architecture mobilenet_v3_small
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset, WeightedRandomSampler
from torchvision.models import (ConvNeXt_Tiny_Weights, MobileNet_V3_Small_Weights,
                                convnext_tiny, mobilenet_v3_small)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from training import _dataset  # noqa: E402

ROOT = Path("data/pro_full/grouped/nose_shape_side")
IMG_SIZE = 224
EXTS = {".jpg", ".jpeg", ".png", ".webp"}
# 見上面第 1 點：朝天鼻的內容全部也在翹鼻裡，當成同一類。
LABEL_ALIASES = {"朝天鼻": "翹鼻"}
MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def load_images() -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """掃資料夾 → 去重 → 回傳 (影像, 標籤, 分組, 類別名)。

    去重用檔案內容的雜湊，不是檔名：同一張圖被複製到兩個類別資料夾時，
    靠檔名看不出來（見上面第 1 點的事故）。
    """
    if not ROOT.exists():
        raise SystemExit(f"找不到資料目錄 {ROOT}。先用 tools/sync_datasets.py --pull 把資料集拉下來。")

    import hashlib

    by_digest: dict[str, tuple[Path, str]] = {}
    for class_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        label = LABEL_ALIASES.get(class_dir.name, class_dir.name)
        for path in sorted(class_dir.iterdir()):
            if path.suffix.lower() not in EXTS:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            by_digest.setdefault(digest, (path, label))

    names = sorted({label for _, label in by_digest.values()})
    lookup = {name: i for i, name in enumerate(names)}

    images, labels, groups = [], [], []
    # 沒有現成的側臉 identity map 時，退回「同一個資料夾前綴視為同一人」的保守分組。
    # 這比不分組安全，但仍不如臉部 embedding 叢集——要更嚴謹請跑 tools/build_identity_map.py。
    prefix_to_id: dict[str, int] = defaultdict(lambda: len(prefix_to_id))
    for path, label in by_digest.values():
        # 用 imdecode 而不是 imread：這個資料集的類別資料夾是中文
        # （塌鼻／直挺鼻／翹鼻／蒜頭鼻／駝峰鼻／朝天鼻），而 Windows 上的
        # cv2.imread 對非 ASCII 路徑一律回 None——每一張都會走到下面的 continue，
        # 腳本最後報「0 張」或在空陣列上炸掉，而且**完全看不出原因**。
        # 這個檔案裡其餘的載入器（build_review_sheet、score_against_manual、
        # brow_geometry_probe）都已經改過，只有這一支漏掉。
        raw = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if raw is None:
            continue
        resized = cv2.resize(raw, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
        images.append(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
        labels.append(lookup[label])
        groups.append(prefix_to_id[path.stem.split("_")[0]])

    return np.array(images), np.array(labels), np.array(groups), names


def build_model(architecture: str, n_classes: int) -> nn.Module:
    if architecture == "convnext_tiny":
        model = convnext_tiny(weights=ConvNeXt_Tiny_Weights.DEFAULT)
        model.classifier[2] = nn.Linear(model.classifier[2].in_features, n_classes)
        return model
    model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, n_classes)
    return model


def to_tensor(images: np.ndarray) -> torch.Tensor:
    array = (images.astype(np.float32) / 255.0 - MEAN) / STD
    return torch.from_numpy(array.transpose(0, 3, 1, 2)).float()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", default="convnext_tiny",
                        choices=("convnext_tiny", "mobilenet_v3_small"))
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    images, labels, groups, names = load_images()
    print(f"側臉鼻型：{len(labels)} 張、{len(names)} 類 {names}、"
          f"{len(set(groups.tolist()))} 組、device={device}")

    all_true: list[int] = []
    all_pred: list[int] = []
    for fold, (train_idx, val_idx) in enumerate(_dataset.folds(labels, groups, args.folds, args.seed), 1):
        x_train, y_train = to_tensor(images[train_idx]), torch.from_numpy(labels[train_idx]).long()
        x_val = to_tensor(images[val_idx])

        counts = np.bincount(labels[train_idx], minlength=len(names))
        sampler = WeightedRandomSampler(
            [1.0 / counts[int(y)] for y in labels[train_idx]],
            num_samples=len(train_idx), replacement=True,
            generator=torch.Generator().manual_seed(args.seed))
        loader = DataLoader(TensorDataset(x_train, y_train),
                            batch_size=args.batch_size, sampler=sampler)

        model = build_model(args.architecture, len(names)).to(device)
        criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
        optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=0.05)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)

        for _ in range(args.epochs):
            model.train()
            for batch_x, batch_y in loader:
                batch_x, batch_y = batch_x.to(device), batch_y.to(device)
                optimizer.zero_grad(set_to_none=True)
                criterion(model(batch_x), batch_y).backward()
                optimizer.step()
            scheduler.step()

        model.eval()
        predictions = []
        with torch.no_grad():
            # 整張 224 圖比 ROI 吃記憶體，分批推論避免一次塞爆。
            for start in range(0, len(x_val), args.batch_size):
                chunk = x_val[start:start + args.batch_size].to(device)
                predictions += model(chunk).argmax(1).cpu().numpy().tolist()
        hit = float((np.array(predictions) == labels[val_idx]).mean())
        print(f"  fold {fold}/{args.folds}  val={len(val_idx)} 張  accuracy={hit:.3f}")
        all_true += labels[val_idx].tolist()
        all_pred += predictions

    print(f"\n===== 側臉鼻型（{args.folds}-fold 聚合，{args.architecture}）=====")
    _dataset.report(all_true, all_pred, names)


if __name__ == "__main__":
    main()
