"""眼型幾何特徵：旋正與比例量測。

這一組數字是規則樹的輸入，也是訓練時用的同一份定義。壞掉的樣子是
**分類悄悄變差**——不會有錯誤訊息，只會有人覺得「最近判得不太準」。

最要緊的是 `align_points`：它用兩眼中心連線把臉旋正，讓角度與縱向量測
不受頭歪影響。少了它，同一張臉歪著拍就會量出不同的眼型。
"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "face"))

import eye_features as ef


def synthetic_face(rotation_deg=0.0, scale=1.0):
    """造一組 478 點的假 landmark。

    只要求索引存在且左右對稱，數值不必像真臉——這裡測的是幾何運算本身，
    不是模型準不準。
    """
    rng = np.random.default_rng(42)
    pts = rng.normal(0, 1, size=(478, 2)).astype(np.float32) * 0.01
    # 臉寬的兩個點
    pts[234] = (-100, 0)
    pts[454] = (100, 0)
    # 左眼（內 133 外 33）與右眼（內 362 外 263）
    pts[33], pts[133] = (-60, 0), (-30, 0)
    pts[263], pts[362] = (60, 0), (30, 0)
    pts[145], pts[159] = (-45, 6), (-45, -6)     # 左眼上下
    pts[374], pts[386] = (45, 6), (45, -6)       # 右眼上下
    for e in ef._EYES:
        cx = -45 if e["outer"] == 33 else 45
        # 眼瞼要有弧度。全部放同一個高度的話，apex_x 取的 argmin 會落在
        # 一堆並列的點上，選到哪一個由浮點誤差決定——那會讓旋轉不變性的測試
        # 抓到一個不存在的問題（真實的眼瞼是弧形的）。
        n_up = len(e["upper"])
        for i, idx in enumerate(e["upper"]):
            t = (i + 0.5) / n_up
            pts[idx] = (cx - 8 + i * (16 / max(1, n_up - 1)), -6 - 3 * np.sin(np.pi * t))
        n_lo = len(e["lower"])
        for i, idx in enumerate(e["lower"]):
            t = (i + 0.5) / n_lo
            pts[idx] = (cx - 8 + i * (16 / max(1, n_lo - 1)), 6 + 3 * np.sin(np.pi * t))
        pts[e["iris_c"]] = (cx, 0)
        for i, idx in enumerate(e["iris_r"]):
            ang = i * np.pi / 2
            pts[idx] = (cx + 5 * np.cos(ang), 5 * np.sin(ang))
    pts = pts * scale
    if rotation_deg:
        a = np.radians(rotation_deg)
        R = np.array([[np.cos(a), -np.sin(a)],
                      [np.sin(a),  np.cos(a)]], dtype=np.float32)
        pts = pts @ R.T
    return pts


class AlignTest(unittest.TestCase):
    def test_alignment_makes_the_eye_line_horizontal(self):
        """旋正之後兩眼中心應該等高，否則角度特徵會被頭歪污染。"""
        P = ef.align_points(synthetic_face(rotation_deg=25))
        lc = P[[33, 133, 145, 159]].mean(0)
        rc = P[[263, 362, 374, 386]].mean(0)
        self.assertAlmostEqual(float(lc[1]), float(rc[1]), places=3)

    def test_alignment_is_centred(self):
        P = ef.align_points(synthetic_face())
        self.assertAlmostEqual(float(np.abs(P.mean(0)).max()), 0.0, places=3)


class FeatureTest(unittest.TestCase):
    def test_all_declared_features_are_returned(self):
        feats = ef.eye_features_from_points(synthetic_face())
        self.assertEqual(set(feats), set(ef.EYE_FUSION_FEATURES))
        self.assertTrue(all(isinstance(v, float) for v in feats.values()))

    def test_no_feature_is_nan_or_inf(self):
        """NaN 一路傳到規則樹會變成無法解釋的分類結果。"""
        feats = ef.eye_features_from_points(synthetic_face())
        for k, v in feats.items():
            self.assertTrue(np.isfinite(v), f"{k} 不是有限數字：{v}")

    def test_a_tilted_head_gives_the_same_features(self):
        """同一張臉歪著拍，量出來的眼型不該改變——這正是 align_points 的用途。"""
        straight = ef.eye_features_from_points(synthetic_face())
        tilted = ef.eye_features_from_points(synthetic_face(rotation_deg=18))
        for k in straight:
            self.assertAlmostEqual(straight[k], tilted[k], places=2,
                                   msg=f"{k} 受到頭部傾斜影響")

    def test_features_are_scale_invariant(self):
        """離鏡頭遠近不該改變眼型判斷：所有量測都除以臉寬或眼寬。"""
        near = ef.eye_features_from_points(synthetic_face(scale=1.0))
        far = ef.eye_features_from_points(synthetic_face(scale=0.4))
        for k in near:
            self.assertAlmostEqual(near[k], far[k], places=2,
                                   msg=f"{k} 受到臉部大小影響")

    def test_too_few_points_raises_rather_than_returning_garbage(self):
        """少於 478 點代表沒開 refine_landmarks，抓不到虹膜索引。
        安靜地回一組錯的數字比丟例外糟得多。"""
        with self.assertRaises(IndexError):
            ef.eye_features_from_points(np.zeros((468, 2), dtype=np.float32))


if __name__ == "__main__":
    unittest.main()
