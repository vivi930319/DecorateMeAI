"""同一批照片，分割取樣 vs 紋理取樣：膚色到底差多少。

換掉取樣方式之後，最該回答的問題不是「程式跑得動嗎」，而是「結果變了嗎、往哪個方向變」。
這支對每張照片跑兩次 get_skin_color()——一次開分割、一次強制走紋理——把兩者的 LAB、
四季型與膚色分級並排印出來。

為什麼要看 b* 特別仔細
----------------------
頭髮（尤其深色髮）混進取樣區會把 L* 拉低。而分割把那些像素剔掉之後，L* 應該回升。
如果分割版本的 L* 普遍比紋理版本高，就是頭髮確實被排掉了。

用法
----
    python tools/compare_skin_sampling.py            # 預設抓 12 張
    python tools/compare_skin_sampling.py --limit 40
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in ("face", "shared"):
    sys.path.insert(0, str(ROOT / folder))

PATTERNS = (
    "data/kaggle_asian_faces/generated_yellow-stylegan2/*.png",
    "data/basic_usable/raw_images/*.jpg",
    "data/pro_full/grouped/nose_shape_side/*/*.jpg",
)


def _collect(limit: int) -> list[str]:
    """每個來源各取一些，不要讓第一個資料夾把名額吃光。

    生成臉那批構圖乾淨、頭髮不會垂到臉頰，只測它會得到「兩種取樣沒有差別」的結論——
    而那正是分割派不上用場的情況。側臉與真實照片才看得出差異。
    """
    per_source = max(1, limit // len(PATTERNS))
    found: list[str] = []
    for pattern in PATTERNS:
        found += sorted(glob.glob(str(ROOT / pattern)))[:per_source]
    return found[:limit]


def _measure(path: str, use_segmentation: bool):
    """跑一次完整的膚色流程。回傳 None 代表這張照片本身不能用。"""
    from Face_analyzer_BASIC import FaceAnalyzer

    # 開關與快取都要重設：segmenter 快取在類別上，不清掉的話第二次跑會沿用第一次的。
    FaceAnalyzer.SKIN_SEGMENTATION_ENABLED = use_segmentation
    FaceAnalyzer._skin_segmenter = None
    try:
        analyzer = FaceAnalyzer(path, strict_angle=False, require_insight=False)
        lip_l, lip_a, lip_b, season, shade, L, a, b = analyzer.get_skin_color()
    except Exception as exc:
        return {"error": f"{type(exc).__name__}"}
    return {
        "L": L, "a": a, "b": b,
        "season": season,
        "shade": shade,
        "source": getattr(analyzer, "skin_mask_source", "?"),
        "reliable": (getattr(analyzer, "skin_reliability", {}) or {}).get("reliable"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    paths = _collect(args.limit)
    if not paths:
        print("找不到測試照片。")
        return 1
    print(f"{len(paths)} 張照片，每張跑兩次\n")
    print(f"{'照片':<26}{'取樣':<15}{'L*':>7}{'a*':>7}{'b*':>7}  {'四季型':<6}{'分級':<14}可信")
    print("-" * 96)

    deltas = []
    changed_season = changed_shade = 0
    for path in paths:
        name = os.path.basename(path)[:24]
        seg = _measure(path, True)
        tex = _measure(path, False)
        if "error" in seg or "error" in tex:
            print(f"{name:<26}跳過（{seg.get('error') or tex.get('error')}）")
            continue
        for label, row in (("分割", seg), ("紋理", tex)):
            flag = "" if row["reliable"] else "✗"
            print(f"{name if label == '分割' else '':<26}"
                  f"{label}({row['source']}){'':<3}"
                  f"{row['L']:>7.1f}{row['a']:>7.1f}{row['b']:>7.1f}  "
                  f"{row['season']:<6}{row['shade']:<14}{flag}")
        deltas.append((seg["L"] - tex["L"], seg["a"] - tex["a"], seg["b"] - tex["b"]))
        changed_season += seg["season"] != tex["season"]
        changed_shade += seg["shade"] != tex["shade"]
        print()

    if not deltas:
        print("沒有任何一張跑得完。")
        return 1

    n = len(deltas)
    print("=" * 96)
    print(f"比較 {n} 張（分割 − 紋理）")
    for index, axis in enumerate("Lab"):
        values = sorted(d[index] for d in deltas)
        mean = sum(values) / n
        median = values[n // 2]
        print(f"  {axis}*  平均 {mean:+.2f}   中位數 {median:+.2f}   "
              f"範圍 {values[0]:+.2f} ~ {values[-1]:+.2f}")
    print(f"  四季型被改變：{changed_season}/{n}")
    print(f"  膚色分級被改變：{changed_shade}/{n}")
    print()
    print("L* 若普遍為正，代表分割把拉低亮度的頭髮像素排掉了——那正是這次要修的東西。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
