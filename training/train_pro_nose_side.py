"""PRO 側臉鼻型分類：DINOv2 frozen encoder vs MobileNetV3 fine-tune，同一組 5-fold 對決。

與 BASIC 流程的差異

BASIC 走的是「MediaPipe FaceMesh 抓 landmark → 依 ROI_SPECS 裁部位」。這條路在
側臉上不成立：實測 438 張側臉，FaceMesh 只認得 73.5%，而且失敗率依類別嚴重
偏斜（塌鼻 60.4%、翹鼻 93.4%）。丟掉失敗樣本不是隨機損失，是把塌鼻從 149 張砍成
90 張、把類別分布整個扭曲，訓出來的模型會系統性偏向「好偵測」的那些鼻型。

所以這裡改成整張圖餵給模型，不做 landmark 裁切，438 張全部保留。

兩種做法

- DINOv2 ViT-S/14（凍結）+ 線性分類器：小資料場景的標準解，encoder 不動，
  只訓練最後的線性層，過擬合風險低。BASIC 鼻型用這條拿到最好的分數。
- MobileNetV3-small fine-tune：跟 BASIC 眉型／唇型同一套，權重本機已有。

兩者用完全相同的 fold（split_kfold_by_identity, seed=42），所以逐 fold 可直接比較。

身分切分

同一個人常有多張不同角度的側臉（檔名 IMG_8055/8057/8058 就是連拍）。隨機切分會讓
同一張臉同時出現在 train 和 val，分數會虛高。這裡沿用 BASIC 的政策：InsightFace
抽 embedding 聚類成 identity，同一個人整組落在同一 fold；抽不到臉的標 -1，一律
留在 train，永不進 val。

輸出：
    data/pro_roi_cache/images.npz          224x224 RGB，列順序＝index.json
    data/pro_roi_cache/index.json          路徑、標籤、identity
    data/pro_roi_cache/dinov2_embeddings.npz
    models/pro_nose_side/cv_results.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pro_nose_geometry  # noqa: E402
from train_basic_cnn_roi import split_kfold_by_identity  # noqa: E402

ROOT = Path("data/pro_full/grouped/nose_shape_side")
CACHE_DIR = Path("data/pro_roi_cache")
OUT_DIR = Path("models/pro_nose_side")
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# 側臉鼻型的類別合併對照表。
#
# 2026-07-31：朝天鼻併入翹鼻。理由不是分數，是資料本身——
# 朝天鼻資料夾的 65 個檔案、61 個唯一內容，全部也存在於翹鼻資料夾，
# 獨有內容是 0。這是 BASIC 世代 3 §5.1 記載過的「類別合併只做了一半」：
# 舊類別的圖被複製到新類別資料夾，舊資料夾沒刪。
#
# 在加這張表之前，去重是「先看到誰算誰」，而順序由資料夾字母序決定——
# 「朝」在「翹」之前，於是那 61 張全被判給朝天鼻、翹鼻 200 張只剩 133 張進訓練。
# 朝天鼻這個類別的存在完全建立在字母排序上，換個資料夾名它就消失。
#
# 刻意用對照表而不是刪資料夾：標註資料夾是人工分好的原始事實，
# 刪掉就沒辦法反悔；而且搬動檔案會讓 identity map 的路徑鍵失效（BASIC §7.6 的事故）。
LABEL_ALIASES = {
    "朝天鼻": "翹鼻",
}

IMG_SIZE = 224          # DINOv2 原生輸入；MobileNet 也吃這個尺寸，兩邊條件一致
MAX_IMAGE_SIZE = 1024   # 抽 identity 前的縮圖上限，跟 BASIC 一致
SEED = 42

_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


# ── 資料收集 ────────────────────────────────────────────────────────────────

def collect_images() -> list[tuple[Path, str]]:
    """收集圖片並依內容雜湊去重；跨類別衝突一律剔除，不猜。

    去重是必要的，不是保險：內容完全相同的兩個檔案若被切到 train 與 val 兩邊，
    模型是在驗證集上看它訓練時看過的同一組像素，分數會虛高而且完全測不出泛化。

    2026-07-31 的修正：同類內重複與跨類衝突要分開處理

    舊版這裡只有一條規則——「先看到誰算誰」。而迴圈是 `sorted(ROOT.iterdir())`，
    所以「先看到誰」完全由資料夾名的字母序決定。

    這在同類內重複上沒問題（兩份標籤一樣，留誰都行），但實測發現這批資料有
    64 組跨類別衝突（同一張照片同時放在「朝天鼻」與「翹鼻」兩個資料夾）：

        朝天鼻/IMG_8122.jpg  ==  翹鼻/IMG_8122.jpg
        朝天鼻/IMG_8198.jpg  ==  翹鼻/IMG_8198.jpg

    「朝」排在「翹」前面，於是那 64 張全部被標成朝天鼻，翹鼻那一份被丟掉——
    翹鼻資料夾有 200 張，實際只有 133 張進訓練，而歸屬是字母序決定的，
    不是任何標註決定。 docstring 既有寫「0 組跨類衝突」，那個描述早就過期了。

    現在改成：同類內重複照舊留一份；跨類衝突整組剔除，並寫出清單供人工複核。
    這與 BASIC 的 `prepare_roi_cache` 一致——標籤有歧義時不要猜，交給人決定。
    """
    by_digest: dict[str, list[tuple[Path, str]]] = {}
    for label_dir in sorted(p for p in ROOT.iterdir() if p.is_dir()):
        for path in sorted(label_dir.iterdir()):
            if path.suffix.lower() not in EXTS or path.name.startswith("._"):
                continue
            digest = hashlib.md5(path.read_bytes()).hexdigest()
            # 先套合併對照表再比對，否則「朝天鼻 vs 翹鼻」會被當成跨類衝突整組剔除，
            # 而它們其實是同一類（見上方 LABEL_ALIASES 的說明）。
            label = LABEL_ALIASES.get(label_dir.name, label_dir.name)
            by_digest.setdefault(digest, []).append((path.resolve(), label))

    kept: list[tuple[Path, str]] = []
    dup_same_label = 0
    conflicts: list[dict] = []
    for digest, entries in by_digest.items():
        labels = {label for _, label in entries}
        if len(labels) > 1:
            conflicts.append({
                "md5": digest,
                "labels": sorted(labels),
                "files": [str(p) for p, _ in entries],
            })
            continue                      # 有歧義 → 整組不用
        dup_same_label += len(entries) - 1
        kept.append(entries[0])

    if dup_same_label:
        print(f"同類內重複：剔除 {dup_same_label} 個多餘檔（標籤一致，留一份）")
    if conflicts:
        out = OUT_DIR / "label_conflicts.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(conflicts, ensure_ascii=False, indent=2), encoding="utf-8")
        pairs = Counter(" vs ".join(c["labels"]) for c in conflicts)
        print(f"跨類別衝突：剔除 {len(conflicts)} 組（同一張圖被標成不同類別），清單見 {out}")
        for pair, n in pairs.most_common():
            print(f"    {pair}  {n} 組")
    return kept


def build_identity_map(paths: list[Path]) -> dict[str, int]:
    """InsightFace 抽臉部 embedding 聚類；抽不到的給 -1。

    側臉本來就不是人臉辨識的強項，抽不到臉是預期內的事——這也是
    抽不到的樣本要留在 train 而不是被丟掉或被拿去驗證。
    """
    from insightface.app import FaceAnalysis
    from sklearn.cluster import AgglomerativeClustering

    app = FaceAnalysis(name="buffalo_l")
    app.prepare(ctx_id=0, det_size=(640, 640))

    embeddings, kept = [], []
    for i, path in enumerate(paths, 1):
        frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        h0, w0 = frame.shape[:2]
        scale = MAX_IMAGE_SIZE / max(h0, w0)
        if scale < 1:
            frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
        faces = app.get(frame)
        if not faces:
            continue
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        vec = np.asarray(face.normed_embedding, dtype=np.float32)
        embeddings.append(vec)
        kept.append(str(path))
        if i % 100 == 0:
            print(f"  identity {i}/{len(paths)}，抽到 {len(kept)}", flush=True)

    if len(kept) < 2:
        print(f"警告：只抽到 {len(kept)} 張臉，無法聚類，identity 全部標 -1")
        return {}

    labels = AgglomerativeClustering(
        n_clusters=None, distance_threshold=1.0 - 0.45,
        metric="cosine", linkage="average",
    ).fit_predict(np.stack(embeddings))
    print(f"identity：{len(kept)}/{len(paths)} 張抽到臉，聚成 {len(set(labels))} 個身分")
    return {path: int(label) for path, label in zip(kept, labels)}


def _nose_geometry(frame: np.ndarray, mesh) -> np.ndarray | None:
    """跑 FaceMesh 並抽鼻型幾何特徵；偵測不到臉時回 None。"""
    h0, w0 = frame.shape[:2]
    scale = MAX_IMAGE_SIZE / max(h0, w0)
    if scale < 1:
        frame = cv2.resize(frame, (int(w0 * scale), int(h0 * scale)), interpolation=cv2.INTER_AREA)
    h, w = frame.shape[:2]
    result = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if not result.multi_face_landmarks:
        return None
    pts = np.array([[lm.x * w, lm.y * h] for lm in result.multi_face_landmarks[0].landmark],
                   dtype=np.float64)
    return pro_nose_geometry.extract(pts)


def prepare_cache(force: bool = False):
    """把圖縮成 224x224 RGB 存快取，並記錄標籤、identity 與幾何特徵。"""
    index_path = CACHE_DIR / "index.json"
    images_path = CACHE_DIR / "images.npz"
    geom_path = CACHE_DIR / "geometry.npz"
    if not force and index_path.is_file() and images_path.is_file() and geom_path.is_file():
        print(f"已有快取 {images_path}，直接使用")
        return (json.loads(index_path.read_text(encoding="utf-8")),
                np.load(images_path)["images"],
                np.load(geom_path)["geometry"])

    import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe
    import mediapipe as mp

    rows = collect_images()
    print(f"PRO 側臉鼻型圖片：{len(rows)} 張")
    identity = build_identity_map([p for p, _ in rows])

    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5,
    )

    images, records, geometry = [], [], []
    n_geom = 0
    for path, label in rows:
        frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            print(f"  讀取失敗，跳過：{path.name}")
            continue
        feats = _nose_geometry(frame, mesh)
        if feats is not None:
            n_geom += 1
        geometry.append(feats if feats is not None
                        else np.full(len(pro_nose_geometry.FEATURE_NAMES), np.nan, dtype=np.float32))
        resized = cv2.resize(frame, (IMG_SIZE, IMG_SIZE), interpolation=cv2.INTER_AREA)
        images.append(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
        records.append({
            "path": str(path),
            "label": label,
            "identity": identity.get(str(path), -1),
            "has_geometry": feats is not None,
        })
    mesh.close()
    print(f"幾何特徵：{n_geom}/{len(records)} 張抽得到（FaceMesh 在側臉上本來就會漏）")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    arr = np.stack(images)
    geo = np.stack(geometry)
    np.savez_compressed(images_path, images=arr)
    np.savez_compressed(geom_path, geometry=geo)
    index_path.write_text(json.dumps({"records": records}, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"快取完成：影像 {arr.shape}，幾何 {geo.shape}")
    return {"records": records}, arr, geo


# ── 特徵 ────────────────────────────────────────────────────────────────────

def compute_dinov2_embeddings(images: np.ndarray, force: bool = False) -> np.ndarray:
    emb_path = CACHE_DIR / "dinov2_embeddings.npz"
    if not force and emb_path.is_file():
        print(f"已有 DINOv2 embedding 快取 {emb_path}")
        return np.load(emb_path)["embeddings"]

    import torch
    print("載入 DINOv2 ViT-S/14（第一次會從 torch.hub 下載權重）...", flush=True)
    dino = torch.hub.load("facebookresearch/dinov2", "dinov2_vits14")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dino.eval().to(device)

    out = np.zeros((len(images), 384), dtype=np.float32)
    batch = 32
    with torch.inference_mode():
        for start in range(0, len(images), batch):
            chunk = images[start:start + batch].astype(np.float32) / 255.0
            chunk = (chunk - _MEAN) / _STD
            tensor = torch.from_numpy(chunk.transpose(0, 3, 1, 2)).to(device)
            feats = dino(tensor).float().cpu().numpy()
            out[start:start + batch] = feats
            print(f"  embedding {min(start + batch, len(images))}/{len(images)}", flush=True)

    out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-9
    np.savez_compressed(emb_path, embeddings=out)
    return out


# ── 評估 ────────────────────────────────────────────────────────────────────

def macro_accuracy(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> float:
    """各類別 recall 的平均。類別不均時，它不會被最大類蓋過去。"""
    accs = []
    for c in range(n_classes):
        mask = y_true == c
        if mask.sum():
            accs.append(float((y_pred[mask] == c).mean()))
    return float(np.mean(accs)) if accs else 0.0


def export_final(images, labels, classes, epochs: int, architecture: str):
    """用全部資料訓一個最終模型並匯出 ONNX，供 PRO 服務推論。

    與 CV 的差別：CV 是為了估計泛化能力（每折留一部分當考題），這裡是為了
    產出上線用的模型，所以吃 100% 資料——分數請看 CV 那組，不要看這裡的訓練損失。

    注意： 沒有驗證集，所以沒辦法挑最佳 epoch，只能訓滿。這在 CV 顯示
    「40 epochs 仍在上升、沒有過擬合」的前提下是可接受的；若哪天曲線變成
    先升後降，這個做法就會匯出一個過擬合的模型而且不會有任何徵兆。

    dynamo=False 的理由同 BASIC：新 exporter 會把權重另存成 <name>.onnx.data，
    拆成兩個檔就多一個「少複製一個檔就靜默壞掉」的機會。
    """
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

    from train_basic_cnn_roi import build_model

    device = "cuda" if torch.cuda.is_available() else "cpu"

    class Ds(Dataset):
        def __len__(self):
            return len(labels)

        def __getitem__(self, i):
            img = images[i].astype(np.float32) / 255.0
            img = (img - _MEAN) / _STD
            return torch.from_numpy(np.ascontiguousarray(img.transpose(2, 0, 1))), int(labels[i])

    counts = Counter(labels.tolist())
    weights = [1.0 / counts[int(l)] for l in labels]
    sampler = WeightedRandomSampler(weights, num_samples=len(labels), replacement=True,
                                    generator=torch.Generator().manual_seed(SEED))
    loader = DataLoader(Ds(), batch_size=32, sampler=sampler, num_workers=0)

    model = build_model(architecture, len(classes), pretrained=True).to(device)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
    optimiser = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)

    model.train()
    for ep in range(1, epochs + 1):
        total = 0.0
        for xb, yb in loader:
            xb, yb = xb.to(device), yb.to(device)
            optimiser.zero_grad()
            loss = criterion(model(xb), yb)
            loss.backward()
            optimiser.step()
            total += float(loss) * len(yb)
        scheduler.step()
        if ep % 5 == 0 or ep == epochs:
            print(f"  ep {ep:02d}/{epochs}  train_loss={total / len(labels):.4f}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    model.eval().cpu()
    onnx_path = OUT_DIR / "nose_shape_side.onnx"
    torch.onnx.export(
        model, torch.zeros(1, 3, IMG_SIZE, IMG_SIZE), str(onnx_path),
        input_names=["input"], output_names=["logits"],
        dynamic_axes={"input": {0: "batch"}, "logits": {0: "batch"}},
        opset_version=17, dynamo=False,
    )
    (OUT_DIR / "nose_shape_side_classes.json").write_text(json.dumps({
        "classes": list(classes), "size": IMG_SIZE, "architecture": architecture,
        "epochs": epochs, "train_count": len(labels), "training_scope": "100_percent",
        "input": "whole_image",   # 不是 ROI 裁切；側臉 FaceMesh 只認得 73.5%
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已匯出 {onnx_path}（{onnx_path.stat().st_size / 1e6:.1f} MB）")
    return onnx_path


def run_feature_models(folds, features, labels, classes, prefix, subset=None):
    """在給定特徵矩陣上跑線性分類器。

    `subset` 是布林遮罩：只有 73.5% 的圖抽得到幾何特徵，比較幾何與像素做法時
    必須限制在同一批樣本上，否則是拿不同的題目在比分數。
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import LinearSVC

    results = {}
    for name, make in (
        (f"{prefix}_logreg",
         lambda: make_pipeline(StandardScaler(),
                               LogisticRegression(max_iter=5000, C=1.0, class_weight="balanced"))),
        (f"{prefix}_linearsvc",
         lambda: make_pipeline(StandardScaler(),
                               LinearSVC(C=1.0, class_weight="balanced"))),
    ):
        per_fold, preds_all, true_all = [], [], []
        for train_idx, val_idx in folds:
            if subset is not None:
                train_idx = [i for i in train_idx if subset[i]]
                val_idx = [i for i in val_idx if subset[i]]
            if not val_idx or len(set(labels[train_idx].tolist())) < 2:
                continue
            clf = make()
            clf.fit(features[train_idx], labels[train_idx])
            pred = clf.predict(features[val_idx])
            per_fold.append(macro_accuracy(labels[val_idx], pred, len(classes)))
            preds_all.append(pred)
            true_all.append(labels[val_idx])
        if per_fold:
            results[name] = _summarise(name, per_fold, np.concatenate(true_all),
                                       np.concatenate(preds_all), classes)
    return results


def run_mobilenet(folds, images, labels, classes, epochs: int,
                  architecture: str = "mobilenet_v3_small"):
    """CNN fine-tune。架構可換。

    2026-07-31 BASIC 的架構對照顯示大架構在五個部位全勝（15/15），
    「小資料要用小模型」的假設是錯的——遷移學習微調的是已經學好的表示，
    不是從零學。PRO 的資料更少（639 張、6 類），這個假設更該被測試。

    build_model 直接沿用 train_basic_cnn_roi 那一份，不在這裡再抄一份架構清單。
    """
    import torch
    from torch import nn
    from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

    from train_basic_cnn_roi import build_model

    device = "cuda" if torch.cuda.is_available() else "cpu"

    class Ds(Dataset):
        def __init__(self, idx, train):
            self.idx, self.train = idx, train

        def __len__(self):
            return len(self.idx)

        def __getitem__(self, i):
            row = self.idx[i]
            img = images[row].astype(np.float32) / 255.0
            if self.train:
                # 不做水平翻轉：側臉朝向左右是這批資料的固有屬性，翻了等於製造
                # 不存在的臉。亮度/位移抖動則是模擬拍攝條件差異，安全。
                if random.random() < 0.7:
                    img = img * random.uniform(0.85, 1.15) + random.uniform(-0.06, 0.06)
                if random.random() < 0.5:
                    shift = int(img.shape[0] * 0.04)
                    img = np.roll(img, (random.randint(-shift, shift),
                                        random.randint(-shift, shift)), axis=(0, 1))
                img = np.clip(img, 0.0, 1.0)
            img = (img - _MEAN) / _STD
            return torch.from_numpy(np.ascontiguousarray(img.transpose(2, 0, 1))), int(labels[row])

    per_fold, preds_all, true_all = [], [], []
    for fold_i, (train_idx, val_idx) in enumerate(folds, 1):
        torch.manual_seed(SEED)
        counts = Counter(labels[train_idx].tolist())
        weights = [1.0 / counts[int(labels[r])] for r in train_idx]
        sampler = WeightedRandomSampler(weights, num_samples=len(train_idx), replacement=True,
                                        generator=torch.Generator().manual_seed(SEED))
        loader = DataLoader(Ds(train_idx, True), batch_size=32, sampler=sampler, num_workers=0)

        model = build_model(architecture, len(classes), pretrained=True).to(device)
        criterion = nn.CrossEntropyLoss(label_smoothing=0.05)
        optimiser = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimiser, T_max=epochs)

        model.train()
        for _ in range(epochs):
            for xb, yb in loader:
                xb, yb = xb.to(device), yb.to(device)
                optimiser.zero_grad()
                loss = criterion(model(xb), yb)
                loss.backward()
                optimiser.step()
            scheduler.step()

        model.eval()
        val_loader = DataLoader(Ds(val_idx, False), batch_size=64, num_workers=0)
        preds = []
        with torch.inference_mode():
            for xb, _ in val_loader:
                preds.append(model(xb.to(device)).argmax(1).cpu().numpy())
        pred = np.concatenate(preds) if preds else np.array([], dtype=np.int64)
        per_fold.append(macro_accuracy(labels[val_idx], pred, len(classes)))
        preds_all.append(pred)
        true_all.append(labels[val_idx])
        print(f"  fold {fold_i}/{len(folds)} macro={per_fold[-1]:.4f}", flush=True)

    return {architecture: _summarise(architecture, per_fold,
                                     np.concatenate(true_all),
                                     np.concatenate(preds_all), classes)}


def _summarise(name, per_fold, y_true, y_pred, classes):
    per_class = {}
    for i, cls in enumerate(classes):
        mask = y_true == i
        per_class[cls] = {
            "support": int(mask.sum()),
            "recall": round(float((y_pred[mask] == i).mean()), 4) if mask.sum() else None,
        }
    confusion = [[int(((y_true == a) & (y_pred == b)).sum()) for b in range(len(classes))]
                 for a in range(len(classes))]
    summary = {
        "fold_macro_accuracies": [round(v, 4) for v in per_fold],
        "mean_macro": round(float(np.mean(per_fold)), 4),
        "std_macro": round(float(np.std(per_fold)), 4),
        "pooled_macro": round(macro_accuracy(y_true, y_pred, len(classes)), 4),
        "per_class": per_class,
        "confusion": confusion,
    }
    print(f"{name:22} mean_macro={summary['mean_macro']:.4f} ± {summary['std_macro']:.4f}")
    return summary


def main():
    p = argparse.ArgumentParser(description="PRO 側臉鼻型：DINOv2 vs MobileNetV3")
    p.add_argument("--folds", type=int, default=5)
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--rebuild-cache", action="store_true")
    p.add_argument("--skip-mobilenet", action="store_true")
    p.add_argument("--architectures", nargs="*", default=["mobilenet_v3_small"],
                   help="要測哪些 CNN 架構；可給多個一次跑完")
    p.add_argument("--export", metavar="ARCH",
                   help="用全部資料訓一個最終模型並匯出 ONNX（例如 --export convnext_tiny）；"
                        "指定時只做匯出，不跑 CV")
    p.add_argument("--skip-dinov2", action="store_true")
    p.add_argument("--skip-geometry", action="store_true")
    args = p.parse_args()

    random.seed(SEED)
    np.random.seed(SEED)

    index, images, geometry = prepare_cache(force=args.rebuild_cache)
    records = index["records"]
    classes = sorted({r["label"] for r in records})
    labels = np.array([classes.index(r["label"]) for r in records], dtype=np.int64)
    identities = np.array([r["identity"] for r in records], dtype=np.int64)

    if args.export:
        print(f"匯出模式：{args.export}，用全部 {len(labels)} 張訓練（分數請看 CV 那組）")
        export_final(images, labels, classes, args.epochs, args.export)
        return

    dist = Counter(r["label"] for r in records)
    n_ident = len({i for i in identities.tolist() if i >= 0})
    print(f"\n類別 {classes}")
    print(f"分布 {dict(dist)}")
    print(f"樣本 {len(records)}，有身分的 {(identities >= 0).sum()} 張／{n_ident} 個身分，"
          f"無身分（只進 train）{(identities < 0).sum()} 張\n")

    folds = split_kfold_by_identity(labels, identities, args.folds, SEED)
    for i, (tr, va) in enumerate(folds, 1):
        print(f"  fold {i}: train {len(tr)} / val {len(va)}")
    print()

    has_geom = np.array([bool(r.get("has_geometry")) for r in records])
    print(f"幾何特徵可用 {has_geom.sum()}/{len(records)} 張\n")

    results = {}
    emb = None
    if not args.skip_dinov2:
        emb = compute_dinov2_embeddings(images, force=args.rebuild_cache)
        results.update(run_feature_models(folds, emb, labels, classes, "dinov2"))

    if not args.skip_geometry and has_geom.any():
        geo = np.nan_to_num(geometry, nan=0.0)
        print("\n幾何特徵（僅限抽得到 landmark 的樣本）...")
        results.update(run_feature_models(folds, geo, labels, classes,
                                          "geometry", subset=has_geom))
        if emb is not None:
            print("\n幾何 + DINOv2 合併...")
            combined = np.hstack([emb, geo])
            results.update(run_feature_models(folds, combined, labels, classes,
                                              "geometry_dinov2", subset=has_geom))
            # 同一子集上的 DINOv2 單獨表現，作為「加幾何有沒有用」的對照組。
            # 不做這個對照就無法區分「幾何有幫助」與「這個子集本來就比較好分」。
            print("\n對照：同一子集上只用 DINOv2...")
            results.update(run_feature_models(folds, emb, labels, classes,
                                              "dinov2_geomsubset", subset=has_geom))

    if not args.skip_mobilenet:
        for arch in args.architectures:
            print(f"\n{arch} fine-tune...")
            results.update(run_mobilenet(folds, images, labels, classes, args.epochs, arch))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": "pro_nose_side",
        "classes": classes,
        "distribution": dict(dist),
        "n_samples": len(records),
        "n_identities": n_ident,
        "n_without_identity": int((identities < 0).sum()),
        "n_folds": args.folds,
        "seed": SEED,
        "image_size": IMG_SIZE,
        "input": "whole_image",
        "results": results,
    }
    (OUT_DIR / "cv_results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果寫入 {OUT_DIR / 'cv_results.json'}")

    if results:
        best = max(results.items(), key=lambda kv: kv[1]["mean_macro"])
        print(f"最佳：{best[0]}  mean_macro={best[1]['mean_macro']:.4f}")


if __name__ == "__main__":
    main()
