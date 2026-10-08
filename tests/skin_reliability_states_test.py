"""膚色可信度的三種狀態：量了可信、量了不可信、沒量。

頰部樣本不足時，可信度以前回報成「可信」，下游分不出「量過沒問題」與「根本沒量」。
這一支守住：沒量就是 reliable=None，而且推薦端的布林旗標 labReliable 維持放行
（只有量了而且超標才擋比色），行為不因三態而改變。
"""
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "face"))
sys.path.insert(0, str(ROOT / "shared"))

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402
from analysis_package import normalize_face_analysis  # noqa: E402


def _stub():
    return FaceAnalyzer.__new__(FaceAnalyzer)


def _lab(l_values):
    """一列像素的 OpenCV Lab 影像，L 用 0~100 的尺度給。"""
    lab = np.full((1, len(l_values), 3), 128, dtype=np.uint8)
    lab[0, :, 0] = np.clip(np.round(np.asarray(l_values) * 2.55), 0, 255).astype(np.uint8)
    return lab


class ReliabilityStatesTest(unittest.TestCase):
    def test_too_few_pixels_is_unmeasured_not_reliable(self):
        lab = _lab([60.0] * 50)
        rel = _stub()._skin_sample_reliability(lab, np.full((1, 50), 255, np.uint8))
        self.assertFalse(rel["measured"])
        self.assertIsNone(rel["reliable"])
        self.assertIn("threshold", rel, "契約測試要求可信度一定帶 threshold")

    def test_uniform_cheek_is_reliable(self):
        lab = _lab([60.0] * 400)
        rel = _stub()._skin_sample_reliability(lab, np.full((1, 400), 255, np.uint8))
        self.assertTrue(rel["measured"])
        self.assertIs(rel["reliable"], True)

    def test_scattered_cheek_is_unreliable(self):
        # 30~90 均勻散布，MAD 約 15，超過門檻 9.5。不能用兩個值各半：那樣過半像素
        # 等於中位數，MAD 是 0，反而判成可信。
        lab = _lab(np.linspace(30.0, 90.0, 400))
        rel = _stub()._skin_sample_reliability(lab, np.full((1, 400), 255, np.uint8))
        self.assertTrue(rel["measured"])
        self.assertIs(rel["reliable"], False)
        self.assertTrue(rel["hint"])


class LabReliableFlagTest(unittest.TestCase):
    def _flag(self, reliability):
        raw = {"膚色": {"LAB": {"L": 60, "a": 10, "b": 15}, "可信度": reliability}}
        return normalize_face_analysis(raw)["skinTone"]["labReliable"]

    def test_unmeasured_still_allows_shade_matching(self):
        self.assertIs(self._flag({"measured": False, "reliable": None}), True)

    def test_measured_reliable(self):
        self.assertIs(self._flag({"measured": True, "reliable": True}), True)

    def test_measured_unreliable_blocks_shade_matching(self):
        self.assertIs(self._flag({"measured": True, "reliable": False}), False)

    def test_missing_reliability_keeps_old_behaviour(self):
        self.assertIs(self._flag(None), True)


if __name__ == "__main__":
    unittest.main()
