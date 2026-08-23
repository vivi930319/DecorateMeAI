"""用裁切後的部位 ROI 訓練 MobileNetV3-small，並做「切分方式」對照實驗。

跟舊的 train_basic_features.py 的差別，也是本程式存在的理由：

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
import hashlib
import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision.models import (
    AlexNet_Weights, ConvNeXt_Tiny_Weights, EfficientNet_B0_Weights,
    MobileNet_V3_Small_Weights, ResNet50_Weights,
    alexnet, convnext_tiny, efficientnet_b0, mobilenet_v3_small, resnet50,
)

from face_roi import IMAGENET_MEAN, IMAGENET_STD, PARTS, ROI_SPECS

# 跟 prepare_roi_cache.py 讀同一個環境變數。先前這裡是寫死的 `data/roi_cache`，
# 而產生快取的那支吃 ROI_CACHE_DIR——兩邊指到不同目錄時，訓練會安靜地拿舊快取跑完，
# 指標看起來完全正常。2026-08-17 就是這樣：使用者校對過的眼型標註放在另一個資料夾，
# 重建的快取沒有被訓練讀到，跑出來的數字與校對無關。
# 這與 §3.1 記載的 build_identity_map／prepare_roi_cache 指向不同目錄是同一種坑。
CACHE_DIR = Path(os.environ.get("ROI_CACHE_DIR", "data/roi_cache"))
# 正式模型的預設輸出位置。**這是線上服務讀的目錄**——不加 --out-dir 就會直接覆蓋它。
# 2026-08-06 因此發生過兩次誤覆蓋：一次把線上的 ConvNeXt 換成 MobileNetV3（架構預設值），
# 一次差點把對照實驗的產物寫進來。做對照實驗一律要指定 --out-dir。
DEFAULT_OUT_DIR = Path("models/basic_features_roi")
OUT_DIR = DEFAULT_OUT_DIR


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


def load_excluded_rows(records, holdout_split: str | None, exclude_file: str | None) -> set[int]:
    """算出「訓練時完全不能碰」的 record 索引。

    回傳的是索引而不是過濾後的 records，因為 `all_rois[part]` 是用**原始索引**取值的；
    從 records 刪元素會讓兩者錯位，而且錯得很安靜——ROI 會配到別人的標籤。

    比對用相對路徑（快），對不上的再用 sha256 補（慢但穩）。數量對不上會直接喊，
    不會默默少排除幾張——`identity_map.json` 就是靠絕對路徑比對而靜默失效的，
    當時 101 張照片查不到、一律留在 train，眼型有 15% 的資料從此不曾當過考題。
    """
    wanted: set[str] = set()
    label = []
    if holdout_split:
        path = CACHE_DIR / f"holdout_split_{holdout_split}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        keys = {s["sha256"] for s in data["samples"] if s["split"] == "holdout"}
        wanted |= keys
        label.append(f"保留集 {holdout_split}（{len(keys)} 張）")
    if exclude_file:
        lines = [l.strip() for l in Path(exclude_file).read_text(encoding="utf-8").splitlines()]
        keys = {l for l in lines if l and not l.startswith("#")}
        wanted |= keys
        label.append(f"額外排除清單（{len(keys)} 張）")
    if not wanted:
        return set()

    excluded, seen = set(), set()
    for i, r in enumerate(records):
        p = Path(r["path"])
        if not p.exists():
            continue
        h = hashlib.sha256(p.read_bytes()).hexdigest()
        if h in wanted:
            excluded.add(i)
            seen.add(h)

    print(f"訓練排除：{'、'.join(label)} -> 命中 {len(excluded)} 筆")
    missed = wanted - seen
    if missed:
        print(f"  ⚠ 有 {len(missed)} 個 sha256 在快取裡找不到對應樣本。"
              f"可能是快取過期，請重跑 prepare_roi_cache.py 再訓練。")
    return excluded


def build_part_data(part: str, all_rois, records, exclude_rows=frozenset()):
    """挑出有這個部位標籤的樣本，回傳 (ROI 陣列, 類別索引, identity, 類別名稱)。"""
    rows = [i for i, r in enumerate(records)
            if part in r["labels"] and i not in exclude_rows]
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


# 已移除不再使用的 --merge-eye 實驗旗標。
# 它把杏仁/桃花併進圓眼、丹鳳/瞇縫併進細長眼——而細長眼本身已在 07-31 併入鳳眼，
# 那個對照表會產出不在官方分類表裡的類別。類別合併現在一律寫在
# prepare_roi_cache.LABEL_ALIASES，是唯一事實來源。


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
    # 2026-07-31 加入的三個架構對照組。參數量差距很大（2.5M / 5.3M / 25M / 28M），
    # 而每個部位只有 269~676 張——大容量預期會過擬合，加進來是為了把這件事量出來，
    # 而不是憑「參數多會過擬合」的通則下結論。
    #
    # 共同的結構性疑慮：這些架構都下採樣 32 倍，輸入 96×96 到最後一層只剩 3×3 的
    # 特徵圖。MobileNetV3-small 的設計本來就假設小輸入，其餘三個是為 224×224 設計的。
    if architecture == "resnet50":
        model = resnet50(weights=ResNet50_Weights.DEFAULT if pretrained else None)
        model.fc = nn.Linear(model.fc.in_features, n_classes)
        return model
    if architecture == "efficientnet_b0":
        model = efficientnet_b0(weights=EfficientNet_B0_Weights.DEFAULT if pretrained else None)
        model.classifier[1] = nn.Linear(model.classifier[1].in_features, n_classes)
        return model
    if architecture == "convnext_tiny":
        model = convnext_tiny(weights=ConvNeXt_Tiny_Weights.DEFAULT if pretrained else None)
        model.classifier[2] = nn.Linear(model.classifier[2].in_features, n_classes)
        return model
    if architecture == "alexnet":
        # 2012 年的架構，放進來當歷史基準。61M 參數裡有 58M 在最後三層全連接，
        # 那正是小資料最容易過擬合的地方。
        # 另一個疑慮：conv1 是 11×11 stride 4，對 96×96 的輸入等於一開始就砍掉大部分
        # 空間資訊（224 設計的模型用在 96 上，第一層就只剩 23×23）。
        model = alexnet(weights=AlexNet_Weights.DEFAULT if pretrained else None)
        model.classifier[6] = nn.Linear(model.classifier[6].in_features, n_classes)
        return model
    weights = MobileNet_V3_Small_Weights.DEFAULT if pretrained else None
    model = mobilenet_v3_small(weights=weights)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, n_classes)
    return model


class FocalLoss(nn.Module):
    """對「已經分得很好」的樣本降權，把梯度留給難分的那些。

    `(1 - pt) ** gamma` 這一項是全部的重點：模型已經很有把握的樣本，pt 接近 1，
    這個係數就趨近 0，等於自動退場；分不開的樣本 pt 小，係數接近 1，權重不變。
    gamma=0 時退化成一般的 CrossEntropy。

    label_smoothing 沿用外面原本的設定（0.05），不然「換損失」會同時換掉兩個變因，
    分數變動就分不出是誰造成的。
    """

    def __init__(self, weight=None, gamma=2.0, label_smoothing=0.0):
        super().__init__()
        self.weight = weight
        self.gamma = gamma
        self.label_smoothing = label_smoothing

    def forward(self, logits, target):
        ce = nn.functional.cross_entropy(
            logits, target, weight=self.weight,
            label_smoothing=self.label_smoothing, reduction="none",
        )
        # pt 要用「沒有加權、沒有 smoothing」的機率，否則 focal 係數會被 class weight
        # 二次放大，稀有類的梯度會爆掉。
        with torch.no_grad():
            pt = nn.functional.softmax(logits, dim=1).gather(1, target[:, None]).squeeze(1)
        return ((1.0 - pt) ** self.gamma * ce).mean()


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

    # 損失函數：預設維持原本的 CrossEntropy（既有結果才比得下去），
    # 另外提供 class weight 與 focal loss 兩個開關，兩者可以疊加。
    #
    # 為什麼在已經有 WeightedRandomSampler 的情況下還需要它們：sampler 治的是
    # 「稀有類被看到的次數太少」，focal loss 治的是「**已經看過但仍然分不開**」。
    # 眉型的病症是後者——落尾眉變成垃圾桶（precision 0.355、recall 0.592，一字眉有
    # 29%、彎月眉有 41% 被倒進去），那是模型對難分樣本沒有額外用力，多抽幾次也沒用。
    # 用 getattr 取，不要直接 args.class_weight：`train_one` 是公開給其他工具用的
    # （tools/find_label_errors.py、tools/train_final_rule_trees.py），那些工具自己組
    # Namespace，不會有這裡新增的旗標。直接取屬性的話，這支腳本每加一個參數就會
    # 讓那些工具在跑到一半時 AttributeError——2026-08-14 已經發生過一次。
    # 預設值＝原本的行為，所以沒帶這些旗標的呼叫端結果完全不變。
    loss_kind = getattr(args, "loss", "ce")
    focal_gamma = getattr(args, "focal_gamma", 2.0)
    class_weight = None
    if getattr(args, "class_weight", "none") == "balanced":
        # 有 sampler 在前面時，這裡的權重是疊在「已經被平衡過的抽樣」之上，
        # 效果比單獨使用溫和；counts 用該折的訓練集算，不能用全體，否則等於偷看驗證集。
        totals = torch.tensor(
            [max(1, counts[i]) for i in range(n_classes)], dtype=torch.float
        )
        class_weight = (totals.sum() / (n_classes * totals)).to(device)
        print(f"    class weight: {[round(float(w), 3) for w in class_weight]}", flush=True)

    if loss_kind == "focal":
        criterion = FocalLoss(weight=class_weight, gamma=focal_gamma,
                              label_smoothing=0.05)
        print(f"    loss: focal(gamma={focal_gamma})", flush=True)
    else:
        criterion = nn.CrossEntropyLoss(weight=class_weight, label_smoothing=0.05)
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
    # MobileNetV3-small 約 10 MB，不需要 external data；拆檔只會增加一個容易漏掉的
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
    p.add_argument("--loss", choices=("ce", "focal"), default="ce",
                   help="ce=CrossEntropy（預設，與既有結果可比）；focal=對難分樣本加重")
    p.add_argument("--focal-gamma", type=float, default=2.0,
                   help="focal loss 的 gamma；0 等於退化成 CrossEntropy")
    p.add_argument("--class-weight", choices=("none", "balanced"), default="none",
                   help="balanced=用該折訓練集的類別頻率倒數當損失權重")
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
    p.add_argument("--drop-conflicts", action="store_true",
                   help="剔除標註矛盾的身分（同一人同部位被標成多個類別）的所有照片")
    p.add_argument("--out-dir", default=None, metavar="DIR",
                   help=f"模型與指標的輸出目錄，預設 {DEFAULT_OUT_DIR}（**線上服務讀的那個**）。"
                        "做對照實驗請指定別的目錄，否則會覆蓋線上模型")
    p.add_argument("--holdout-split", default=None, metavar="VERSION",
                   help="讀 data/roi_cache/holdout_split_<VERSION>.json，把保留集完全排除在訓練外。"
                        "要拿 tools/eval_on_holdout.py 做跨版本比較時**必須**指定，"
                        "否則模型看過考題，分數不能跟別版比")
    p.add_argument("--exclude-list", default=None, metavar="FILE",
                   help="額外排除的照片清單（每行一個 sha256）。用於「假裝某批資料還沒加入」"
                        "的對照實驗")
    p.add_argument("--architecture",
                   choices=("mobilenet_v3_small", "simple_cnn", "resnet50",
                            "efficientnet_b0", "convnext_tiny", "alexnet"),
                   default="mobilenet_v3_small",
                   help="訓練架構。simple_cnn 是無預訓練的基礎對照組；"
                        "resnet50/efficientnet_b0/convnext_tiny 是容量更大的對照組")
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
        "drop_conflicts": bool(args.drop_conflicts),
        "epochs": args.epochs,
        "architecture": args.architecture,
        # 損失設定要寫進結果，否則兩個 metrics 檔擺在一起沒人分得出哪個是 focal 跑的。
        "loss": args.loss,
        "focal_gamma": args.focal_gamma if args.loss == "focal" else None,
        "class_weight": args.class_weight,
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
    global OUT_DIR
    if args.out_dir:
        OUT_DIR = Path(args.out_dir)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if OUT_DIR == DEFAULT_OUT_DIR and not args.cv:
        print(f"⚠ 即將覆蓋線上模型目錄 {OUT_DIR}。對照實驗請加 --out-dir。")
    print(f"輸出目錄：{OUT_DIR}")
    print(f"device={device}  epochs={args.epochs}\n")

    all_rois, records = load_cache()
    if args.face_input == "contour":
        # 解析度不同的遮罩存成不同檔名，這樣可以並存比較（見 prepare_face_contour_cache --size）
        contour_file = args.contour_file or "face_contour.npy"
        all_rois["face_shape"] = np.load(CACHE_DIR / contour_file)
        print(f"臉型改用輪廓遮罩：{contour_file} {all_rois['face_shape'].shape}")
    for part in args.contour_parts:
        all_rois[part] = np.load(CACHE_DIR / f"{part}_contour.npy")
    excluded_rows = load_excluded_rows(records, args.holdout_split, args.exclude_list)
    summary = {}

    for part in args.parts:
        rois, labels, identities, classes = build_part_data(part, all_rois, records, excluded_rows)

        if args.identity_mode == "per_image":
            # 這批資料是一個人的五官分別分類；在單一部位內每張圖都是獨立人物。
            # 不使用 InsightFace 聚類，避免把外貌相似的不同人物錯誤綁成同一組。
            identities = np.arange(len(labels), dtype=np.int64)

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
            # 非預設架構一律進檔名，否則不同架構的結果會互相覆蓋，事後對不出
            # 哪個數字屬於哪個模型架構。
            # 損失設定也要進檔名。少了這一段，focal 那一輪會直接蓋掉同架構的 CE 基準線，
            # 而「對照實驗」把基準線蓋掉就沒有東西可以對照了。
            tag = ("" if args.architecture == "mobilenet_v3_small" else f"_{args.architecture}") + \
                  ("" if args.loss == "ce" else f"_{args.loss}{args.focal_gamma:g}") + \
                  ("" if args.class_weight == "none" else "_cw") + \
                  ("_per_image" if args.identity_mode == "per_image" else "") + \
                  ("_contour" if args.face_input == "contour" else "") + \
                  ("_feature_contour" if args.contour_parts else "") + \
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
        cv_tag = ("" if args.architecture == "mobilenet_v3_small" else f"_{args.architecture}") + \
                 ("_per_image" if args.identity_mode == "per_image" else "") + \
                 ("_contour" if args.face_input == "contour" else "") + \
                 ("_feature_contour" if args.contour_parts else "") + \
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
