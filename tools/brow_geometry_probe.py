"""量眉型的幾何特徵，看它能不能分開 CNN 分不開的那兩類。

為什麼要問這個
--------------
2026-08-24 的眉型 CNN（ConvNeXt-Tiny，去重後 422 張）macro 0.525，而錯誤集中在
彎月眉↔落尾眉這一對：三種訓練設定（ce／focal+cw／去重前後）跑下來，那一對的
互相誤判總數都在 51~59 之間紋風不動，只有方向在左右擺。

`find_label_errors.py` 用 CNN + DINOv2 取 out-of-fold 預測，找「兩個模型都以 >0.60
的信心說這張不是這一類」的樣本——結果是 **0 張**。所以問題不是少數照片標錯，
而是模型對整片邊界都沒把握。

那就值得問一個更基本的問題：**這四類的差別，是不是本來就不在 CNN 看得到的地方？**

眉型的定義本身是幾何的：
    一字眉  眉尾與眉頭齊高，弧度小
    彎月眉  眉峰明顯、整體成弧
    挑眉    眉峰高且靠外，眉尾上揚
    落尾眉  眉尾低於眉頭

「眉尾低於眉頭」是一個可以從 FaceMesh landmark 直接算出來的數，不需要卷積去猜。
如果幾何特徵能分開而 CNN 不能，那答案是把幾何量餵進去（專案裡 pro_nose_geometry
與 face_shape_geometry_probe 都是這個路數）；如果幾何也分不開，那就是標註的界線
在資料上不存在，該考慮合併類別——眼型 6→5、唇型 5→4 兩次合併各帶來約 +0.07。

量哪些
------
每側眉毛取上緣五點（外→內），全部除以兩眼外眥距離做正規化，讓不同解析度、
不同拍攝距離的照片可以比較。左右兩側取平均：單側會被臉部轉向放大誤差。

    tail_rise    眉頭 y − 眉尾 y。正值＝眉尾比眉頭高（挑），負值＝落尾。
                 這一個就是落尾眉的定義本身。
    peak_height  眉峰 y 比「眉頭與眉尾連線」高出多少。弧度的量。
    peak_pos     眉峰落在眉長的哪個位置（0=眉頭側，1=眉尾側）。挑眉的眉峰靠外。
    brow_len     眉長，正規化後。不是判別特徵，但用來看正規化有沒有生效。

用法
----
    ROI_CACHE_DIR=data/roi_cache_dedup python tools/brow_geometry_probe.py

輸出四類在每個特徵上的分布，以及一棵深度 3 的決策樹在這些特徵上能拿到的
macro recall——那個數字就是「幾何能不能分」的直接答案。
"""

from __future__ import annotations

import _bootstrap  # noqa: F401  # 讓 face/ training/ 的模組 import 得到
import json
import os
from collections import defaultdict
from pathlib import Path

import cv2
import mediapipe_ascii  # noqa: F401  # 必須早於 mediapipe，見該模組說明
import mediapipe as mp
import numpy as np
from sklearn.metrics import recall_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.tree import DecisionTreeClassifier, export_text

CACHE_DIR = Path(os.environ.get("ROI_CACHE_DIR", "data/roi_cache"))
MAX_IMAGE_SIZE = 1024   # 跟 prepare_roi_cache 一致，landmark 尺度才對得上

# FaceMesh 的眉毛上緣，由外側（眉尾）往內側（眉頭）排。
# 下緣不取：眉毛下緣貼著眼窩，形狀被眼皮影響，量到的不是眉型。
BROW_UPPER_LEFT = (70, 63, 105, 66, 107)
BROW_UPPER_RIGHT = (300, 293, 334, 296, 336)
# 兩眼外眥。用它當長度基準而不是臉寬：臉寬會被髮型與臉頰肉量影響，
# 眼距在同一個人身上穩定得多，而且不隨表情變。
OUTER_CANTHI = (33, 263)


def brow_features(pts: np.ndarray) -> dict[str, float] | None:
    """從 468 個 landmark 算出眉型的幾何量。左右取平均。"""
    scale = float(np.linalg.norm(pts[OUTER_CANTHI[0]] - pts[OUTER_CANTHI[1]]))
    if scale <= 1:
        return None

    per_side = []
    for idx in (BROW_UPPER_LEFT, BROW_UPPER_RIGHT):
        p = pts[list(idx)].astype(float)
        tail, head = p[0], p[-1]        # 外側=眉尾，內側=眉頭
        length = float(np.linalg.norm(tail - head))
        if length <= 1:
            return None

        # y 軸往下為正，所以「眉尾比眉頭高」是 head_y - tail_y 為正。
        tail_rise = float(head[1] - tail[1]) / scale

        # 眉峰：離「眉頭-眉尾連線」最遠的那一點，取垂直方向的距離。
        # 用點到線距離而不是最小 y，是因為整條眉毛本來就是斜的——
        # 取最小 y 的話，斜度大的眉毛會被誤判成弧度大。
        d = tail - head
        n = np.array([-d[1], d[0]]) / length
        offsets = (p - head) @ n
        k = int(np.argmax(np.abs(offsets)))
        peak_height = float(abs(offsets[k])) / scale
        # 眉峰在眉長上的位置：0=眉頭，1=眉尾。
        peak_pos = float(np.dot(p[k] - head, d) / (length ** 2))

        per_side.append((tail_rise, peak_height, peak_pos, length / scale))

    a = np.mean(per_side, axis=0)
    return {"tail_rise": a[0], "peak_height": a[1], "peak_pos": a[2], "brow_len": a[3]}


def main() -> None:
    index = json.loads((CACHE_DIR / "index.json").read_text(encoding="utf-8"))
    records = [r for r in index["records"] if "brow_shape" in r.get("labels", {})]
    print(f"快取 {CACHE_DIR}｜眉型樣本 {len(records)} 張")

    mesh = mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=False,
        min_detection_confidence=0.5)

    rows, labels, groups, failed = [], [], [], 0
    for i, rec in enumerate(records, 1):
        path = Path(rec["path"])
        if not path.is_file():
            failed += 1
            continue
        frame = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            failed += 1
            continue
        h0, w0 = frame.shape[:2]
        s = MAX_IMAGE_SIZE / max(h0, w0)
        if s < 1:
            frame = cv2.resize(frame, (int(w0 * s), int(h0 * s)), interpolation=cv2.INTER_AREA)
        h, w = frame.shape[:2]
        res = mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if not res.multi_face_landmarks:
            failed += 1
            continue
        pts = np.array([[lm.x * w, lm.y * h] for lm in res.multi_face_landmarks[0].landmark])
        feat = brow_features(pts)
        if feat is None:
            failed += 1
            continue
        rows.append(feat)
        labels.append(rec["labels"]["brow_shape"])
        groups.append(rec.get("identity", -1))
        if i % 100 == 0:
            print(f"  {i}/{len(records)}  成功 {len(rows)}  失敗 {failed}", flush=True)
    mesh.close()

    names = ["tail_rise", "peak_height", "peak_pos", "brow_len"]
    x = np.array([[r[n] for n in names] for r in rows])
    classes = sorted(set(labels))
    y = np.array([classes.index(l) for l in labels])
    g = np.array(groups)
    print(f"\n可用 {len(rows)} 張、失敗 {failed} 張、{len(classes)} 類 {classes}")

    print(f"\n=== 每一類的分布（中位數 [四分位距]）===")
    print(f"  {'類別':8}{'n':>5}" + "".join(f"{n:>22}" for n in names))
    for ci, c in enumerate(classes):
        m = y == ci
        cells = []
        for j in range(len(names)):
            v = x[m, j]
            cells.append(f"{np.median(v):+.3f} [{np.percentile(v,25):+.3f},{np.percentile(v,75):+.3f}]")
        print(f"  {c:8}{m.sum():>5}" + "".join(f"{s:>22}" for s in cells))

    # 落尾眉的定義就是 tail_rise < 0。先看這條定義本身在資料上成不成立——
    # 如果落尾眉的中位數不是負的，那不是模型的問題，是標註沒有照定義走。
    if "落尾眉" in classes:
        ci = classes.index("落尾眉")
        v = x[y == ci, 0]
        print(f"\n  落尾眉的 tail_rise：中位數 {np.median(v):+.4f}，"
              f"其中 {(v < 0).mean():.0%} 是負的（眉尾真的比眉頭低）")
        for c in classes:
            if c == "落尾眉":
                continue
            o = x[y == classes.index(c), 0]
            print(f"    對照 {c:6} 中位數 {np.median(o):+.4f}，負的佔 {(o < 0).mean():.0%}")

    # 決策樹只吃這四個數，跟 CNN 用同一套按人分組的切分，數字才可比。
    print(f"\n=== 只用幾何特徵能分到什麼程度（決策樹 depth=3，5-fold 按人切）===")
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    true_all, pred_all = [], []
    for tr, va in cv.split(x, y, g):
        clf = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=42)
        clf.fit(x[tr], y[tr])
        true_all.extend(y[va])
        pred_all.extend(clf.predict(x[va]))
    per_class = recall_score(true_all, pred_all, average=None, labels=range(len(classes)))
    print(f"  {'類別':8}{'幾何 recall':>12}")
    for c, r in zip(classes, per_class):
        print(f"  {c:8}{r:>12.3f}")
    print(f"  {'macro':8}{per_class.mean():>12.3f}   （CNN 同一份快取是 0.525）")

    clf = DecisionTreeClassifier(max_depth=3, class_weight="balanced", random_state=42).fit(x, y)
    print(f"\n=== 樹學到的規則（全資料，只為了看它抓住什麼）===")
    for line in export_text(clf, feature_names=names).splitlines():
        print("  " + line)


if __name__ == "__main__":
    main()
