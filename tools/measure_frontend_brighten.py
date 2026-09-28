"""前端「自動提亮」對膚色的影響。

web_frontend/js/router.js 的 bpRegisterFile：照片平均亮度 < 110 就自動把滑桿設成
min(50, (110 - 亮度) / 2)，再用 bpTransform 提亮，**分析收到的是提亮後的照片**。
這支把 bpTransform 逐行搬成 numpy，量兩件事：
  1. 多少照片會被自動提亮
  2. 被提亮的照片，膚色 LAB 跟原圖差多少（ΔE00）

用法：python tools/measure_frontend_brighten.py [--limit N]
"""
from __future__ import annotations

import argparse
import glob
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import measure_skin_consistency as m  # noqa: E402  共用 skin_lab 與 insightface 空殼


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def luminance(img_bgr):
    # 前端先縮到最長邊 80px 再算平均亮度
    h, w = img_bgr.shape[:2]
    s = min(1.0, 80 / max(h, w))
    small = cv2.resize(img_bgr, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    b, g, r = [small[..., i].astype(np.float64) for i in range(3)]
    return float(np.mean(0.299 * r + 0.587 * g + 0.114 * b))


def bp_transform(img_bgr, slider):
    """router.js bpTransform 的 val > 0 分支。"""
    val = max(-100, min(100, slider)) / 100
    f = img_bgr.astype(np.float64)
    b, g, r = f[..., 0], f[..., 1], f[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    yn = y / 255
    shadow_w = 1 - smoothstep(0.32, 0.86, yn)
    mid_w = np.sin(np.pi * np.clip(yn, 0, 1))
    hl = smoothstep(0.64, 0.96, yn)
    sat = (f.max(axis=2) - f.min(axis=2)) / 255
    white = (1 - sat) * smoothstep(0.72, 0.98, yn)
    lift = val * (58 * shadow_w + 24 * mid_w) * (1 - 0.88 * hl) * (1 - 0.70 * white)
    target = np.minimum(246, y + lift)
    ratio = np.where(y > 1, target / np.maximum(y, 1e-6), 1.0)
    return np.clip(np.round(f * ratio[..., None]), 0, 255).astype(np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()
    paths = []
    for person in sorted(p for p in m.PERSON_DIR.iterdir() if p.is_dir()):
        paths += sorted(glob.glob(str(person / "*.jpg")))[: args.limit]

    triggered, deltas, dl = 0, [], []
    for path in paths:
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        lum = luminance(img)
        if lum >= 110:
            continue
        slider = min(50, round((110 - lum) / 2))
        orig = m.skin_lab(img)
        bright = m.skin_lab(bp_transform(img, slider))
        triggered += 1
        if orig is None or bright is None:
            continue
        deltas.append(m.de(orig, bright))
        dl.append(bright[0] - orig[0])
        print(f"{Path(path).name:<12} 亮度 {lum:6.1f}  滑桿 +{slider:<3} 膚色 L* {orig[0]:5.1f} → {bright[0]:5.1f}  ΔE00 {deltas[-1]:5.2f}")

    print(f"\n{len(paths)} 張裡有 {triggered} 張（{triggered / max(1, len(paths)):.0%}）會被前端自動提亮")
    if deltas:
        print(f"膚色 ΔE00：中位數 {statistics.median(deltas):.2f}  p90 {m.pct(deltas, .9):.2f}  最大 {max(deltas):.2f}")
        print(f"L* 平均變亮 {statistics.mean(dl):+.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
