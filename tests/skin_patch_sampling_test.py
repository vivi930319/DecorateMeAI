"""分塊共識取樣：擋得住一整片妝，而且不能把離散度一起濾掉。

取樣區原本只有雙頰——而雙頰正是腮紅、修容與遮瑕的位置。選頰部的理由（避開頭髮、
陰影、髮際）全是遮蔽物，那份考量裡沒有化妝。

這一支守兩件事：

  1. 一整片同調的偏色（腮紅就長這樣）要被丟掉。像素層級的百分位修剪做不到這件事，
     那是這個機制存在的唯一理由——測不到這一項，整個分塊就是白做的。
  2. 季型的 v_std 不能量在共識後的遮罩上。分塊共識的工作**就是**剔除高變異的塊，
     拿它去量離散度等於先刪掉要量的東西：實測 v_std 中位數 36.55 → 17.99，剛好
     跌破 18.0 的門檻，60 張裡 23 張從春季被改判成秋季。
     2026-08 已經用紋理過濾踩過同一個坑，所以這裡要有測試而不只是註解。
"""
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "face"))
sys.path.insert(0, str(ROOT / "shared"))

from Face_analyzer_BASIC import FaceAnalyzer  # noqa: E402


def _stub(h=200, w=200):
    """只帶尺寸的空殼。這兩個方法用不到 landmark，不需要真的跑一次臉部偵測。"""
    a = FaceAnalyzer.__new__(FaceAnalyzer)
    a.h, a.w = h, w
    return a


def _lab_of(bgr_image):
    return cv2.cvtColor(bgr_image, cv2.COLOR_BGR2Lab)


class PatchConsensusTest(unittest.TestCase):
    def setUp(self):
        self.a = _stub()
        # 一張均勻的「皮膚」，加一點雜訊——完全純色會讓塊內標準差是 0，
        # 那不是任何一張真實照片的樣子。
        rng = np.random.default_rng(7)
        base = np.full((200, 200, 3), (150, 170, 200), dtype=np.uint8)
        noise = rng.normal(0, 1.5, base.shape)
        self.skin = np.clip(base.astype(np.float32) + noise, 0, 255).astype(np.uint8)
        self.region = np.full((200, 200), 255, dtype=np.uint8)

    def test_a_solid_patch_of_blush_is_rejected(self):
        """一整片同調的偏色要整塊丟掉。

        這正是像素層級修剪做不到的：腮紅不是雜訊，它的像素數量夠多、彼此夠一致，
        百分位修剪削的是分布兩端，削不掉一個第二眾數。
        """
        image = self.skin.copy()
        # 左上角一塊明顯偏紅，占整個區域約 16%——腮紅在頰部取樣區裡就是這個量級。
        image[20:100, 20:100, 2] = 245
        image[20:100, 20:100, 0] = 110

        kept = self.a._patch_consensus_mask(_lab_of(image), self.region)

        blush = kept[30:90, 30:90]
        clean = kept[120:190, 120:190]
        self.assertLess(int(np.count_nonzero(blush)) / blush.size, 0.15,
                        "偏色那一片幾乎應該整塊被丟掉")
        self.assertGreater(int(np.count_nonzero(clean)) / clean.size, 0.85,
                           "沒有妝的皮膚不該被一起丟掉")

    def test_uniform_skin_keeps_almost_everything(self):
        """乾淨的臉不該被這個機制削掉——那會讓樣本白白變少。"""
        kept = self.a._patch_consensus_mask(_lab_of(self.skin), self.region)
        ratio = int(np.count_nonzero(kept)) / int(np.count_nonzero(self.region))
        self.assertGreater(ratio, 0.85, f"乾淨皮膚只留下 {ratio:.0%}，門檻太嚴")

    def test_too_few_patches_falls_back_to_the_whole_region(self):
        """塊數不足時要退回整區。三塊算出來的中位數不是共識，是巧合。"""
        # 塊大小下限是 SKIN_PATCH_MIN_PX（6），所以要小於 6*sqrt(8)≈17 才切不出
        # 8 塊。18x18 會切出 3x3=9 塊，剛好過關——第一版測試就是這樣寫錯的。
        tiny = np.zeros((200, 200), dtype=np.uint8)
        tiny[100:112, 100:112] = 255
        kept = self.a._patch_consensus_mask(_lab_of(self.skin), tiny)
        self.assertEqual(int(np.count_nonzero(kept)), int(np.count_nonzero(tiny)))
        self.assertEqual(self.a.skin_patch_kept, 0, "退回整區要記錄下來，不能靜默")

    def test_an_empty_region_is_returned_unchanged(self):
        empty = np.zeros((200, 200), dtype=np.uint8)
        kept = self.a._patch_consensus_mask(_lab_of(self.skin), empty)
        self.assertEqual(int(np.count_nonzero(kept)), 0)


class SeasonUsesTwoMasksTest(unittest.TestCase):
    """季型的顏色與離散度必須取自不同的遮罩。"""

    def setUp(self):
        self.a = _stub()
        rng = np.random.default_rng(11)
        # 左半邊亮、右半邊暗：整體離散度高，但任一半自己都很均勻。
        # 分塊共識會把其中一半判成離群，於是「共識後」的離散度遠低於原本。
        image = np.zeros((200, 200, 3), dtype=np.uint8)
        image[:, :100] = (150, 170, 205)
        image[:, 100:] = (95, 110, 135)
        self.image = np.clip(image.astype(np.float32) + rng.normal(0, 1.5, image.shape),
                             0, 255).astype(np.uint8)
        self.region = np.full((200, 200), 255, dtype=np.uint8)

    def test_spread_is_measured_before_the_consensus_filter(self):
        """v_std 要量在共識**前**的遮罩上。

        共識後的遮罩是「已經把高變異剔掉」的結果，拿它量離散度必然偏低，而 18.0
        那個門檻是為未過濾資料校準的。實測這個錯誤讓 60 張裡的 23 張季型翻邊。
        """
        lab = _lab_of(self.image)
        hsv = cv2.cvtColor(self.image, cv2.COLOR_BGR2HSV)
        consensus = self.a._patch_consensus_mask(lab, self.region)

        def v_std(mask):
            vals = hsv[:, :, 2][mask.astype(bool)].astype(np.float32)
            return float(np.std(vals))

        self.assertLess(v_std(consensus), v_std(self.region),
                        "前提不成立的話這個測試沒有意義：共識後的離散度本來就該比較低")

        # 同一張圖，只差在 spread_mask 給哪一個。
        with_region = self.a._classify_season(lab, hsv, consensus, self.region)
        with_consensus = self.a._classify_season(lab, hsv, consensus, consensus)
        self.assertNotEqual(
            with_region, with_consensus,
            "兩者算出同一個季型的話，這張測試圖沒有跨過 clear 門檻，換一張")

    def test_omitting_the_spread_mask_keeps_the_old_single_mask_behaviour(self):
        """不給第四個參數時要跟舊行為一致，呼叫端才能逐一遷移。"""
        lab = _lab_of(self.image)
        hsv = cv2.cvtColor(self.image, cv2.COLOR_BGR2HSV)
        self.assertEqual(
            self.a._classify_season(lab, hsv, self.region),
            self.a._classify_season(lab, hsv, self.region, self.region),
        )


if __name__ == "__main__":
    unittest.main()
