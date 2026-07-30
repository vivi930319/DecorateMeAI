"""找出很可能標錯的個別照片，產生人工複核清單。

## 為什麼要這支

這個資料集的每一次大幅提升都來自修標籤，不是修模型：

    窄鼻類別塌陷（標註者看的不是鼻翼寬度）  → 併成兩類
    眼型 6 類 → 5 類（桃杏眼）              → macro +0.069
    唇型 5 類 → 4 類                        → macro +0.068

那些是**整批類別**的界線不存在。這支處理下一層：**個別照片標錯**。

## 判斷方式：兩個模型都很有把握地說「這張不是這一類」

對每張圖取 out-of-fold 預測——也就是那張圖**沒有參與訓練**的那一折所給的答案，
否則模型只是在背它自己看過的東西。

同時跑 CNN 與 DINOv2，只挑**兩者都答錯、且都很有把握**的樣本。
單一模型答錯可能只是它自己的弱點；兩個架構完全不同的模型同時、有把握地
指向同一個別的答案，那比較可能是標籤本身有問題。

**這不是自動改標籤。** 產出是給人看的清單——模型沒有比標註同學更權威，
它只是很擅長指出「這一張跟同類的其他張長得不一樣」。最後仍由人決定。

## 產出

    models/basic_features_roi/label_review.csv    可排序的清單
    review_sheets/<part>_NN.jpg                   看圖複核用的拼圖

CSV 欄位裡的 `review_decision` 留空給複核者填：
    keep          標籤沒錯，模型錯了
    relabel       標籤要改成 suggested
    drop          這張圖不該用（角度、遮擋、模糊）
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.linear_model import LogisticRegression  # noqa: E402

from face_roi import PARTS  # noqa: E402
from torch.utils.data import DataLoader  # noqa: E402

from train_basic_cnn_roi import (  # noqa: E402
    RoiDataset,
    build_model,
    build_part_data,
    load_cache,
    split_kfold_by_identity,
    train_one,
)

OUT_CSV = Path("models/basic_features_roi/label_review.csv")
SHEET_DIR = Path("review_sheets")
# 兩個模型都要超過這個把握才列入。訂高一點：這份清單是要人一張一張看的，
# 寧可少列幾張，也不要塞滿模型只是「有點傾向」的樣本。
CONF_MIN = 0.60


def out_of_fold_cnn(part, rois, labels, identities, classes, args, device):
    """每張圖取它沒參與訓練的那一折所給的預測與信心。

    train_one 只回 (結果, 權重)，不回機率，所以這裡拿它挑出來的最佳權重
    自己再跑一次推論。刻意不去改 train_one——那支是主線訓練流程，
    為了一個分析工具去動它的簽章，等於讓所有訓練共擔這個風險。
    """
    import torch

    n = len(labels)
    pred = np.full(n, -1)
    conf = np.zeros(n)
    for k, (train_idx, val_idx) in enumerate(split_kfold_by_identity(labels, identities, 5, 42), 1):
        _, best_state = train_one(part, rois, labels, identities, classes,
                                  f"errfind {k}/5", train_idx, val_idx, args, device)
        if best_state is None:
            continue
        model = build_model(args.architecture, len(classes), pretrained=False).to(device)
        model.load_state_dict(best_state)
        model.eval()
        loader = DataLoader(RoiDataset(rois[val_idx], labels[val_idx], train=False),
                            batch_size=args.batch_size, shuffle=False)
        probs = []
        with torch.no_grad():
            for xb, _ in loader:
                probs.append(torch.softmax(model(xb.to(device)), dim=1).cpu().numpy())
        probs = np.concatenate(probs) if probs else np.zeros((0, len(classes)))
        pred[val_idx] = probs.argmax(1)
        conf[val_idx] = probs.max(1)
    return pred, conf


def out_of_fold_dinov2(X, labels, identities, classes):
    n = len(labels)
    pred = np.full(n, -1)
    conf = np.zeros(n)
    for train_idx, val_idx in split_kfold_by_identity(labels, identities, 5, 42):
        if len(np.unique(np.asarray(labels)[train_idx])) < 2:
            continue
        clf = LogisticRegression(max_iter=2000)
        clf.fit(X[train_idx], np.asarray(labels)[train_idx])
        p = clf.predict_proba(X[val_idx])
        pred[val_idx] = clf.classes_[p.argmax(1)]
        conf[val_idx] = p.max(1)
    return pred, conf


def main():
    ap = argparse.ArgumentParser(description="找出可能標錯的照片，產生複核清單")
    ap.add_argument("--parts", nargs="*", default=list(PARTS))
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--learning-rate", type=float, default=3e-4)
    ap.add_argument("--architecture", default="mobilenet_v3_small")
    # train_one 會讀 args.seed（DataLoader 的 generator）與 args.val_ratio，
    # 這支不走那條路徑也要給，否則 AttributeError。
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--val-ratio", type=float, default=0.25)
    ap.add_argument("--conf", type=float, default=CONF_MIN)
    ap.add_argument("--sheets", action="store_true", help="另外產生看圖用的拼圖")
    args = ap.parse_args()

    import torch
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    all_rois, records = load_cache()
    emb = np.load("data/roi_cache/dinov2_embeddings.npz")["embeddings"]

    rows = []
    for part in args.parts:
        rois, labels, identities, classes = build_part_data(part, all_rois, records)
        idx = [i for i, r in enumerate(records) if part in r["labels"]]
        y = np.asarray(labels)

        print(f"\n=== {part} === {len(y)} 張 / {len(classes)} 類", flush=True)
        c_pred, c_conf = out_of_fold_cnn(part, rois, labels, identities, classes, args, device)
        d_pred, d_conf = out_of_fold_dinov2(emb[idx], labels, identities, classes)

        # 兩個都答錯、都夠有把握、而且指向同一個別的類別
        agree = (c_pred == d_pred) & (c_pred != y) & (c_pred >= 0)
        strong = agree & (c_conf >= args.conf) & (d_conf >= args.conf)
        picked = np.flatnonzero(strong)
        order = picked[np.argsort(-(c_conf[picked] + d_conf[picked]))]
        print(f"  兩模型一致認為標錯且有把握：{len(order)} 張（{len(order)/max(len(y),1):.1%}）")

        for i in order:
            rows.append({
                "part": part,
                "path": records[idx[i]]["path"],
                "image": Path(records[idx[i]]["path"]).name,
                "current_label": classes[y[i]],
                "suggested": classes[c_pred[i]],
                "cnn_conf": f"{c_conf[i]:.3f}",
                "dinov2_conf": f"{d_conf[i]:.3f}",
                "review_decision": "",
            })

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["part", "path", "image", "current_label", "suggested",
                            "cnn_conf", "dinov2_conf", "review_decision"])
        w.writeheader()
        w.writerows(rows)
    print(f"\n共 {len(rows)} 張待複核 → {OUT_CSV}")

    if args.sheets and rows:
        make_sheets(rows)


def make_sheets(rows, per_sheet=20, cell=260):
    """把待複核的圖拼成大圖，一眼看得完，不必一張一張開。"""
    from PIL import Image, ImageDraw
    SHEET_DIR.mkdir(exist_ok=True)
    by_part = {}
    for r in rows:
        by_part.setdefault(r["part"], []).append(r)
    for part, items in by_part.items():
        for page in range((len(items) + per_sheet - 1) // per_sheet):
            chunk = items[page * per_sheet:(page + 1) * per_sheet]
            cols = 5
            rowsn = (len(chunk) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * cell, rowsn * (cell + 46)), (255, 255, 255))
            draw = ImageDraw.Draw(sheet)
            for k, item in enumerate(chunk):
                x, y = (k % cols) * cell, (k // cols) * (cell + 46)
                try:
                    im = Image.open(item["path"]).convert("RGB")
                    im.thumbnail((cell - 8, cell - 8))
                    sheet.paste(im, (x + 4, y + 4))
                except Exception:
                    draw.text((x + 8, y + 8), "(讀不到)", fill=(200, 0, 0))
                draw.text((x + 6, y + cell + 4), item["image"][:26], fill=(30, 30, 30))
                draw.text((x + 6, y + cell + 18), f'現:{item["current_label"]}', fill=(0, 0, 0))
                draw.text((x + 6, y + cell + 32), f'模型:{item["suggested"]}', fill=(180, 0, 0))
            out = SHEET_DIR / f"{part}_{page + 1:02d}.jpg"
            sheet.save(out, quality=88)
            print(f"  {out}")


if __name__ == "__main__":
    main()
