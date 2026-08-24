"""五官分類共用的資料層：讀 ROI 快取、按人分組切分、算指標。

這個目錄的設計
--------------
`training/` 底下**一個模型一個檔案**，每一支都能單獨讀、單獨跑，用途是學習與實驗。
真正在維護的正式訓練腳本仍然是根目錄的 `train_basic_cnn_roi.py`（它支援對照實驗、
ONNX 匯出、holdout 等線上流程需要的東西）——這裡的檔案不匯出模型、不覆蓋線上目錄。

只有「資料怎麼來、怎麼切、怎麼算分」這三件事放在這支共用檔裡。理由不是省行數，
是**這三件事錯了會靜默地毀掉結論**，而且每一支都必須錯得一模一樣才公平：

  - 讀快取不檢查筆數 → 拿 A 圖的像素配 B 圖的標籤（S72 踩過，差點整份結果全錯）
  - 切分不按人分組  → 同一個人同時出現在 train 與 val，分數虛高，換人就崩
  - 只看 accuracy    → 類別不平衡時它會騙人（全部猜最大類也有不錯的分數）

影像從哪裡來
------------
不在這裡跑 MediaPipe。ROI 由根目錄的 `prepare_roi_cache.py` 事先裁好存成 npz，
而那支呼叫的是 **Face BASIC 的裁切規格**（`face_roi.ROI_SPECS`、`crop_roi`）——
也就是線上服務實際餵給模型的同一種圖。訓練與推論吃同一份規格，模型上線才不會掉分。

    先跑一次：  .venv\\Scripts\\python.exe prepare_roi_cache.py
    再跑訓練：  .venv\\Scripts\\python.exe training\\basic_brow_shape.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.model_selection import StratifiedGroupKFold

CACHE_DIR = Path("data/roi_cache")


def load_part(part: str) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """回傳 (影像, 標籤索引, 人別分組, 類別名稱)。

    只取「這個部位有標籤」的樣本：index.json 裡每張圖各部位的標註是分開的，
    一張圖可能只標了眼型沒標鼻型，硬湊會產生沒有根據的標籤。
    """
    rois = np.load(CACHE_DIR / "rois.npz")[part]
    index = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))
    records = index["records"]

    # 快取與索引必須同一批。少了這道檢查，換過資料之後訓練會安靜地拿錯配對跑完。
    if len(records) != len(rois):
        raise SystemExit(
            f"快取與索引筆數不符（rois {len(rois)} vs index {len(records)}）。"
            f"請重跑 prepare_roi_cache.py 再訓練。"
        )

    keep = [i for i, record in enumerate(records) if part in (record.get("labels") or {})]
    if not keep:
        raise SystemExit(f"{part} 在快取裡沒有任何標籤")

    names = sorted({records[i]["labels"][part] for i in keep})
    lookup = {name: idx for idx, name in enumerate(names)}
    labels = np.array([lookup[records[i]["labels"][part]] for i in keep])
    # identity 是用臉部 embedding 叢集出來的（tools/build_identity_map.py），
    # **不是**從檔名推的——同一個人在不同截圖裡的檔名毫無關聯。
    groups = np.array([records[i].get("identity", -1) for i in keep])
    return rois[keep], labels, groups, names


def folds(labels: np.ndarray, groups: np.ndarray, n_splits: int = 5, seed: int = 42):
    """按人分組的分層交叉驗證。同一個人的照片只會出現在同一邊。

    identity = -1 是「叢集失敗、不知道是誰」。這些**一律留在 train，永遠不進 val**，
    沿用正式腳本 `train_basic_cnn_roi.split_kfold_by_identity` 的政策：身分不確定的
    樣本不能拿來驗證，否則它可能跟 train 裡的某張是同一個人，洩漏又回來了。

    這裡不能把 -1 當成一個普通的 group 丟給 StratifiedGroupKFold——那會讓所有身分
    不明的樣本變成「同一個超大的人」，整包落到某一折的 val。實測鼻型就是這樣：
    fold 1 的 val 有 250 張、其餘四折各只有 17～26 張，分數完全失去意義。
    """
    known = np.flatnonzero(groups >= 0)
    unknown = np.flatnonzero(groups < 0)
    if len(known) == 0:
        raise SystemExit("沒有任何樣本有 identity，無法做按人分組的切分")

    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    result = []
    for train_local, val_local in splitter.split(np.zeros(len(known)), labels[known], groups[known]):
        train_idx = np.concatenate([known[train_local], unknown]).astype(int)
        result.append((train_idx, known[val_local].astype(int)))
    return result


def report(y_true, y_pred, names: list[str]) -> dict:
    """印出並回傳整套指標：per-class P/R/F1、macro/weighted、混淆矩陣。"""
    from sklearn.metrics import (balanced_accuracy_score, classification_report,
                                 cohen_kappa_score, confusion_matrix, f1_score)

    print("\n" + classification_report(y_true, y_pred, target_names=names, digits=3, zero_division=0))
    matrix = confusion_matrix(y_true, y_pred)
    print("混淆矩陣（列＝真實，欄＝預測）")
    width = max(len(n) for n in names) + 2
    print(" " * width + "".join(f"{n:>8}" for n in names))
    for name, row in zip(names, matrix):
        print(f"{name:<{width}}" + "".join(f"{v:>8}" for v in row))

    summary = {
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y_true, y_pred, average="weighted", zero_division=0)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "cohen_kappa": float(cohen_kappa_score(y_true, y_pred)),
    }
    print(f"\nmacro-F1 {summary['macro_f1']:.3f}｜weighted-F1 {summary['weighted_f1']:.3f}"
          f"｜balanced acc {summary['balanced_accuracy']:.3f}｜κ {summary['cohen_kappa']:.3f}")
    return summary
