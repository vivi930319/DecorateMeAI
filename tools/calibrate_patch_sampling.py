"""雙頰取樣 vs 分塊共識取樣：同一批照片，結果差多少、門檻該落在哪。

換取樣區不是換一個函式而已。 這支程式要回答三件事，缺一件就不該切換預設：

  1. 膚色（LAB）往哪個方向移動了、移動多少
  2. 有多少人的四季型與膚色分級會因此改變
  3. 三組原本綁在雙頰上的門檻，在新取樣區上該設多少

第三點是關鍵。程式碼裡已經記過兩次教訓：SKIN_SPREAD_UNRELIABLE=9.5 是在頰部
校準的（乾淨照片 p95=9.55），換成整臉凸包之後同一個門檻誤報率從 5% 跳到 37.5%；
而 _classify_season 只是換了餵進去的遮罩，40 張裡就有 5 張四季型被改掉。
所以這裡把新取樣區上的分布直接印出來，讓門檻由量到的數字決定，不是猜。

為什麼一定要有真實照片
----------------------
生成臉（stylegan）構圖乾淨、幾乎沒有妝，只測它會得到「兩種取樣沒差別」的結論，
而那正是分塊派不上用場的情況。CelebA 是真人、有妝、光線雜——腮紅與修容要在
那裡才看得到。兩批都跑，分開報。

用法
----
    python tools/calibrate_patch_sampling.py                 # 每批各 40 張
    python tools/calibrate_patch_sampling.py --limit 150
    python tools/calibrate_patch_sampling.py --source celeba
"""
from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
for folder in ("face", "shared"):
    sys.path.insert(0, str(ROOT / folder))

SOURCES = {
    # 生成臉：乾淨、幾乎無妝。用來確認新取樣沒有把本來就對的弄壞。
    "generated": "data/kaggle_asian_faces/generated_yellow-stylegan2/*.png",
    # 真人、有妝、光線雜。腮紅與修容的影響只在這裡看得到。
    "celeba": "celeba_raw/img_align_celeba/img_align_celeba/*.jpg",
}


def _collect(source: str, limit: int) -> list[str]:
    return sorted(glob.glob(str(ROOT / SOURCES[source])))[:limit]


def _measure(path: str, analyzer_cls, patch_on: bool):
    """跑一次分析，回傳這張照片的一組數字。失敗回 None（照片不可用不是錯誤）。"""
    import cv2

    analyzer_cls.SKIN_PATCH_ENABLED = patch_on
    try:
        with open(path, "rb") as handle:
            a = analyzer_cls(handle.read(), strict_angle=False, require_insight=False)
        lip_L, lip_a, lip_b, season, shade, L, A, B = a.get_skin_color()
    except Exception:
        return None

    lab = cv2.cvtColor(a.frame, cv2.COLOR_BGR2Lab)
    cheek = cv2.bitwise_or(
        a._landmark_poly_mask([50, 101, 118, 117, 123, 205, 187, 147, 177, 137]),
        a._landmark_poly_mask([280, 330, 347, 346, 352, 425, 411, 376, 401, 366]),
    )
    # 可信度的尺：頰部 ROI 內 L 的 MAD。新舊都量同一塊，門檻才有可比性。
    l_vals = lab[:, :, 0][cheek > 0].astype(np.float32) / 2.55
    spread = float(np.median(np.abs(l_vals - np.median(l_vals)))) if l_vals.size >= 100 else None

    # 季型的五個判定特徵也要留下來。 只看「季型變了」沒有用——要知道是哪一個
    # 門檻被跨過去，才知道該調哪一個。_classify_season 用的就是這五個。
    # 顏色與離散度分開量，跟 _classify_season 現在的做法一致。
    spread_region = _season_mask(a, cv2)
    colour_region = a._patch_consensus_mask(lab, spread_region) if patch_on else spread_region
    hsv = cv2.cvtColor(a.frame, cv2.COLOR_BGR2HSV)
    _, s_mean, v_mean, _ = cv2.mean(hsv, mask=colour_region)
    mask_bool = spread_region.astype(bool)
    v_std = float(np.std(hsv[:, :, 2][mask_bool].astype(np.float32))) if np.any(mask_bool) else 0.0
    l_mean_lab, _a_axis, b_axis = a._lab_robust_from_mask(lab, colour_region)

    return {
        "L": L, "a": A, "b": B,
        "season": season, "shade": shade,
        "b_axis": float(b_axis), "l_cv": float(l_mean_lab) * 2.55,
        "s_mean": float(s_mean), "v_mean": float(v_mean), "v_std": v_std,
        "spread": spread,
        "patch_total": getattr(a, "skin_patch_total", 0),
        "patch_kept": getattr(a, "skin_patch_kept", 0),
        "source": getattr(a, "skin_mask_source", "?"),
    }


def _season_mask(a, cv2):
    """重建 _classify_season 實際吃到的那個遮罩，好在外面量它的特徵。"""
    import numpy as _np

    face_points = _np.array([a._pt(i) for i in range(len(a.lm))], dtype=_np.int32)
    face_mask = _np.zeros((a.h, a.w), dtype=_np.uint8)
    cv2.fillConvexPoly(face_mask, cv2.convexHull(face_points), 255)
    cheek = cv2.bitwise_or(
        a._landmark_poly_mask([50, 101, 118, 117, 123, 205, 187, 147, 177, 137]),
        a._landmark_poly_mask([280, 330, 347, 346, 352, 425, 411, 376, 401, 366]),
    )
    if a.SKIN_PATCH_ENABLED:
        below = a._below_forehead_mask()
        sample = below if cv2.countNonZero(below) >= 180 else cheek
    else:
        sample = cheek if cv2.countNonZero(cheek) >= 180 else face_mask.copy()
    for region in (a.mp_face_mesh.FACEMESH_LIPS, a.mp_face_mesh.FACEMESH_LEFT_EYE,
                   a.mp_face_mesh.FACEMESH_RIGHT_EYE):
        indices = a._collect_landmark_indices(region)
        if not indices:
            continue
        pts = _np.array([a._pt(i) for i in indices], dtype=_np.int32)
        cv2.fillConvexPoly(sample, cv2.convexHull(pts), 0)
    lab = cv2.cvtColor(a.frame, cv2.COLOR_BGR2Lab)
    hsv = cv2.cvtColor(a.frame, cv2.COLOR_BGR2HSV)
    ycrcb = cv2.cvtColor(a.frame, cv2.COLOR_BGR2YCrCb)
    lab_skin = cv2.inRange(lab, _np.array([35, 130, 124]), _np.array([235, 178, 184]))
    hsv_skin = cv2.inRange(hsv, _np.array([0, 12, 35]), _np.array([35, 175, 245]))
    ycc_skin = cv2.inRange(ycrcb, _np.array([35, 128, 72]), _np.array([245, 185, 142]))
    color_mask = cv2.bitwise_and(lab_skin, cv2.bitwise_or(hsv_skin, ycc_skin))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_OPEN, kernel)
    color_mask = cv2.morphologyEx(color_mask, cv2.MORPH_CLOSE, kernel)
    return cv2.bitwise_and(sample, color_mask)


def _pct(values, q):
    return float(np.percentile(values, q)) if values else float("nan")


def _report(name: str, rows: list[tuple[dict, dict]]) -> None:
    if not rows:
        print(f"\n[{name}] 沒有可用的照片")
        return

    d_l = [new["L"] - old["L"] for old, new in rows]
    d_a = [new["a"] - old["a"] for old, new in rows]
    d_b = [new["b"] - old["b"] for old, new in rows]
    de = [float(np.sqrt((n["L"] - o["L"]) ** 2 + (n["a"] - o["a"]) ** 2 + (n["b"] - o["b"]) ** 2))
          for o, n in rows]
    season_flips = [(o["season"], n["season"]) for o, n in rows if o["season"] != n["season"]]
    shade_flips = [(o["shade"], n["shade"]) for o, n in rows if o["shade"] != n["shade"]]

    print(f"\n{'=' * 68}\n[{name}]  {len(rows)} 張")
    print(f"  ΔL* 中位 {np.median(d_l):+6.2f}   Δa* {np.median(d_a):+6.2f}   Δb* {np.median(d_b):+6.2f}")
    print(f"  ΔE   中位 {np.median(de):6.2f}   p95 {_pct(de, 95):6.2f}   最大 {max(de):6.2f}")
    print(f"  四季型改變 {len(season_flips):3d}/{len(rows)}  ({len(season_flips) / len(rows):.0%})")
    print(f"  膚色分級改變 {len(shade_flips):3d}/{len(rows)}  ({len(shade_flips) / len(rows):.0%})")

    if season_flips:
        counts = {}
        for pair in season_flips:
            counts[pair] = counts.get(pair, 0) + 1
        moves = "  ".join(f"{o}→{n}×{c}" for (o, n), c in sorted(counts.items(), key=lambda kv: -kv[1])[:6])
        print(f"    {moves}")

    # 門檻 1：可信度。頰部 MAD 在新舊之間應該幾乎不動（量的是同一塊），
    # 真正要看的是它還能不能分開「算對」與「算錯」——這裡先把分布報出來。
    spreads = [n["spread"] for _o, n in rows if n["spread"] is not None]
    if spreads:
        print(f"  頰部 MAD   p50 {_pct(spreads, 50):5.2f}   p95 {_pct(spreads, 95):5.2f}"
              f"   （現行門檻 9.5）")

    # 門檻 2：分塊存活率。太低代表門檻設得太嚴，等於大部分照片都退回整區。
    print("  季型判定特徵（舊 → 新，中位數）與現行門檻：")
    for key, label, thresh in (("b_axis", "b*  (暖>=12.0 冷<=8.5)", None),
                               ("l_cv", "L*  (bright>=158)", 158.0),
                               ("v_mean", "V   (bright>=168)", 168.0),
                               ("s_mean", "S   (soft<=110 clear>=125)", None),
                               ("v_std", "Vstd(clear>=18.0)", 18.0)):
        o = np.median([r[0][key] for r in rows])
        n = np.median([r[1][key] for r in rows])
        flag = ""
        if thresh is not None and (o >= thresh) != (n >= thresh):
            flag = "  <<< 中位數跨過門檻"
        print(f"    {label:28s} {o:7.2f} → {n:7.2f}  ({n - o:+.2f}){flag}")

    # 門檻對應：v_std 的 18.0 是在雙頰上訂的，而離散度量的區域換了，尺就要跟著換。
    #
    # 用「保持 clear 判定比例不變」來換算，不是用中位數的比例——季型是靠跨過門檻
    # 決定的，所以要對齊的是**有多少人在門檻的哪一邊**，不是分布中心移動了多少。
    old_vstd = np.array([o["v_std"] for o, _n in rows])
    new_vstd = np.array([n["v_std"] for _o, n in rows])
    old_clear_rate = float((old_vstd >= 18.0).mean())
    if 0.0 < old_clear_rate < 1.0:
        matched = float(np.percentile(new_vstd, (1.0 - old_clear_rate) * 100.0))
        print(f"  Vstd 門檻對應：舊 18.0 判定 {old_clear_rate:.0%} 為 clear；"
              f"新區域要維持同樣比例需要 {matched:.1f}")

    totals = [n["patch_total"] for _o, n in rows]
    kept = [n["patch_kept"] for _o, n in rows]
    fell_back = sum(1 for k in kept if k == 0)
    live = [k / t for k, t in zip(kept, totals) if t > 0 and k > 0]
    print(f"  分塊  平均切出 {np.mean(totals):5.1f} 塊   存活率中位 "
          f"{np.median(live) if live else float('nan'):.0%}"
          f"   退回整區 {fell_back}/{len(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=40, help="每個來源各取幾張")
    parser.add_argument("--source", choices=sorted(SOURCES), help="只跑其中一個來源")
    parser.add_argument("--dump", help="把逐張數據存成 JSON，之後調門檻不必重跑")
    args = parser.parse_args()

    from Face_analyzer_BASIC import FaceAnalyzer

    wanted = [args.source] if args.source else sorted(SOURCES)
    for name in wanted:
        paths = _collect(name, args.limit)
        if not paths:
            print(f"[{name}] 找不到照片：{SOURCES[name]}")
            continue
        rows = []
        for index, path in enumerate(paths, 1):
            old = _measure(path, FaceAnalyzer, patch_on=False)
            new = _measure(path, FaceAnalyzer, patch_on=True)
            if old and new:
                rows.append((old, new))
            if index % 20 == 0:
                print(f"  [{name}] {index}/{len(paths)}…", flush=True)
        _report(name, rows)
        if args.dump:
            import json
            out = Path(args.dump).with_suffix(f".{name}.json")
            out.write_text(json.dumps([{"old": o, "new": n} for o, n in rows],
                                      ensure_ascii=False), encoding="utf-8")
            print(f"  逐張數據已存到 {out}")

    FaceAnalyzer.SKIN_PATCH_ENABLED = True
    print("\n門檻要照上面的分布訂，不要沿用雙頰時代的數字。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
