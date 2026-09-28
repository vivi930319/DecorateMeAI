"""膚色一致性量測：光線一換，同一個人的膚色 LAB 跑掉多少？白平衡校正能拉回多少？

沒有人工標註的真值，所以不量「偏多少」，量兩件替代但真實的事：

1. 合成色偏（有真值）：同一張照片人為加上暖光／冷光／過曝／欠曝，
   原圖算出來的 LAB 就是答案。量「加了色偏之後差多少」與「校正之後剩多少」。
2. 真實照片一致性（無真值）：同一個人的 20 多張不同場合照片，
   每張到該人中位數 LAB 的 ΔE00。同一個人本來就該是同一個膚色，散得越開越不準。

環境
----
專案的 .venv 裝的是 protobuf 7，而 mediapipe 0.10.21 需要 protobuf 4.x，直接跑會在
建 FaceMesh 時丟 AttributeError（'FieldDescriptor' object has no attribute 'label'）。
另建一個短路徑的 venv（Windows 路徑太長 mediapipe 會裝不起來）：

    python -m venv %TEMP%\\sv
    %TEMP%\\sv\\Scripts\\python -m pip install "numpy<2" opencv-python-headless==4.10.0.84 ^
        mediapipe==0.10.21 "scikit-image<0.25" fastapi python-multipart pydantic scikit-learn joblib Pillow requests

insightface 不用裝（這裡一律 require_insight=False，下面會放空殼）。

2026-09-28 的結果（51 張）：不校正時同一人照片之間中位數 ΔE00 7.7；四種白平衡在合成色偏上
有效，在真實照片上都沒有改善；3 張取中位數最差一成的誤差約減半。

用法
----
    python tools/measure_skin_consistency.py                # 全部方法
    python tools/measure_skin_consistency.py --limit 10     # 每人只取 10 張（快速）
"""
from __future__ import annotations

import argparse
import glob
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000

ROOT = Path(__file__).resolve().parents[1]
for folder in ("face", "shared"):
    sys.path.insert(0, str(ROOT / folder))

# Face_analyzer_BASIC 在檔案開頭 import insightface，但這裡一律 require_insight=False，
# 完全用不到它。insightface 在 Windows 常常裝不起來，沒裝就放一個空殼，不影響量測。
try:
    import insightface.app  # noqa: F401
except Exception:
    import types
    _pkg, _app = types.ModuleType("insightface"), types.ModuleType("insightface.app")
    _app.FaceAnalysis = object
    _pkg.app = _app
    sys.modules.update({"insightface": _pkg, "insightface.app": _app})

PERSON_DIR = ROOT /"data/source_material/asian_faces/DCleaning_tool/raw_images"


# ── 候選校正 ────────────────────────────────────────────────────────────
def wb_none(img):
    return img


def wb_shades_of_gray(img, p=6):
    """Finlayson & Trezzi 2004：各通道的 p 次方平均視為光源色，除掉它。p=1 是灰色世界，p→∞ 是白點。"""
    f = img.astype(np.float32) + 1.0
    illum = np.power(np.mean(np.power(f, p), axis=(0, 1)), 1.0 / p)
    gain = illum.mean() / illum
    return np.clip(f * gain, 0, 255).astype(np.uint8)


def _landmarks(img):
    """跑一次 FaceMesh 拿特徵點（沿用分析器自己的偵測，才跟正式流程取到同一張臉）。"""
    from Face_analyzer_BASIC import FaceAnalyzer
    ok, buf = cv2.imencode(".png", img)
    try:
        return FaceAnalyzer(buf.tobytes(), strict_angle=False, require_insight=False)
    except Exception:
        return None


def _face_hull(an):
    pts = np.array([an._pt(i) for i in range(len(an.lm))], np.int32)
    mask = np.zeros(an.frame.shape[:2], np.uint8)
    cv2.fillConvexPoly(mask, cv2.convexHull(pts), 255)
    return mask


def _gain_to_neutral(mean_bgr, keep_luma=True):
    mean_bgr = np.maximum(np.asarray(mean_bgr, np.float32), 1.0)
    gain = mean_bgr.mean() / mean_bgr
    return gain


def wb_background(img):
    """只用臉以外的像素（背景、衣服）估光源：避免皮膚本身把校正拉向灰色。"""
    an = _landmarks(img)
    if an is None:
        return img
    hull = cv2.dilate(_face_hull(an), np.ones((31, 31), np.uint8))
    f = img.astype(np.float32) + 1.0
    sel = f[hull == 0]
    if len(sel) < 500:
        return img
    illum = np.power(np.mean(np.power(sel, 6), axis=0), 1 / 6)
    return np.clip(f * (illum.mean() / illum), 0, 255).astype(np.uint8)


def _sclera_mean(img, an):
    """眼睛多邊形裡「最亮、最不飽和」的像素＝眼白。太少就放棄（瞇眼、墨鏡、太小）。"""
    mask = np.zeros(img.shape[:2], np.uint8)
    for region in (an.mp_face_mesh.FACEMESH_LEFT_EYE, an.mp_face_mesh.FACEMESH_RIGHT_EYE):
        idx = an._collect_landmark_indices(region)
        pts = np.array([an._pt(i) for i in idx], np.int32)
        cv2.fillConvexPoly(mask, cv2.convexHull(pts), 255)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    inside = mask > 0
    if inside.sum() < 40:
        return None
    v, s = hsv[..., 2][inside], hsv[..., 1][inside]
    pick = (v >= np.percentile(v, 70)) & (s <= np.percentile(s, 40))
    if pick.sum() < 12:
        return None
    return img[inside][pick].astype(np.float32).mean(axis=0)


def wb_sclera(img):
    """用眼白去色偏（只改色度，不改亮度）。"""
    an = _landmarks(img)
    if an is None:
        return img
    m = _sclera_mean(img, an)
    if m is None:
        return img
    return np.clip(img.astype(np.float32) * _gain_to_neutral(m), 0, 255).astype(np.uint8)


def wb_sclera_exposure(img, target_v=215.0):
    """眼白去色偏＋把眼白亮度拉到固定值（連曝光一起校正）。"""
    an = _landmarks(img)
    if an is None:
        return img
    m = _sclera_mean(img, an)
    if m is None:
        return img
    gain = _gain_to_neutral(m) * (target_v / max(float(m.max()), 1.0))
    return np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)


METHODS = {"none": wb_none, "sog6": wb_shades_of_gray, "背景": wb_background,
           "眼白": wb_sclera, "眼白+曝光": wb_sclera_exposure}

# ── 合成色偏（BGR 增益）──────────────────────────────────────────────────
CASTS = {
    "暖光3200K": (0.78, 1.00, 1.18),
    "冷光7500K": (1.15, 1.00, 0.88),
    "過曝+30%": (1.30, 1.30, 1.30),
    "欠曝-30%": (0.70, 0.70, 0.70),
}


def apply_cast(img, gains):
    return np.clip(img.astype(np.float32) * np.array(gains, np.float32), 0, 255).astype(np.uint8)


def skin_lab(img):
    from Face_analyzer_BASIC import FaceAnalyzer
    ok, buf = cv2.imencode(".png", img)
    try:
        analyzer = FaceAnalyzer(buf.tobytes(), strict_angle=False, require_insight=False)
        *_, L, a, b = analyzer.get_skin_color()
    except Exception:
        return None
    return np.array([L, a, b], np.float64)


def de(x, y):
    return float(deltaE_ciede2000(x.reshape(1, 1, 3), y.reshape(1, 1, 3))[0, 0])


def pct(values, q):
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))] if v else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=100)
    args = ap.parse_args()

    persons = {p.name: sorted(glob.glob(str(p / "*.jpg")))[: args.limit] for p in sorted(PERSON_DIR.iterdir()) if p.is_dir()}
    # 先縮到分析器自己的上限：分析器內部會縮圖，特徵點座標是縮圖後的，
    # 校正若在原尺寸上做，眼白／臉部遮罩就對不上位置。
    from Face_analyzer_BASIC import MAX_IMAGE_SIZE

    def load(path):
        img = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        scale = MAX_IMAGE_SIZE / max(img.shape[:2])
        return cv2.resize(img, (int(img.shape[1] * scale), int(img.shape[0] * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else img

    images = {path: load(path) for paths in persons.values() for path in paths}

    # 1. 合成色偏
    print("=== 1. 合成色偏：原圖的結果當真值，ΔE00（中位數 / p90）===")
    cast_err = {m: {c: [] for c in CASTS} for m in METHODS}
    usable = 0
    for path, img in images.items():
        for m, fn in METHODS.items():
            truth = skin_lab(fn(img))
            if truth is None:
                continue
            usable += m == "none"
            for c, gains in CASTS.items():
                got = skin_lab(fn(apply_cast(img, gains)))
                if got is not None:
                    cast_err[m][c].append(de(truth, got))
    print(f"可分析照片 {usable} 張")
    print(f"{'方法':<8}" + "".join(f"{c:>16}" for c in CASTS))
    for m in METHODS:
        print(f"{m:<8}" + "".join(f"{statistics.median(v):>8.2f} / {pct(v, .9):<5.2f}" if v else f"{'—':>16}" for v in cast_err[m].values()))

    # 2. 真實照片一致性
    print("\n=== 2. 真實照片一致性：每張到該人中位數 LAB 的 ΔE00 ===")
    for m, fn in METHODS.items():
        spreads, per = [], []
        for name, paths in persons.items():
            labs = [x for x in (skin_lab(fn(images[p])) for p in paths) if x is not None]
            if len(labs) < 3:
                continue
            center = np.median(np.stack(labs), axis=0)
            d = [de(center, x) for x in labs]
            spreads += d
            per.append(f"{name}:{statistics.median(d):.2f}(n={len(labs)})")
        print(f"{m:<8} 中位數 {statistics.median(spreads):.2f}  p90 {pct(spreads, .9):.2f}  最大 {max(spreads):.2f}   " + "  ".join(per))
    print("\n參考：ΔE00 ≈ 1 肉眼勉強可辨；≈ 2–3 粉底色號相鄰一階；> 5 明顯不同色。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
