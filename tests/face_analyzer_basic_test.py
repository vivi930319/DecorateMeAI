# -*- coding: utf-8 -*-
"""Face_analyzer_BASIC 的純函式單元測試。

這個檔案裡的東西不需要模型、不需要網路、不需要容器——只要 numpy 和一組數字。
建立它的理由是 `補充文件md檔案/單元測試規格_2026-08-23.md` §2 指出的缺口：
Face_analyzer_BASIC 是整個產品的核心，裡面有大量純計算，卻一個單元測試都沒有。
這類錯誤不會讓服務掛掉，只會讓「膚色判斷怪怪的」，所以特別需要測試盯著。
"""
import math
import unittest

import numpy as np

from Face_analyzer_BASIC import FaceAnalyzer, delta_e_ciede2000, pose_guidance


class Ciede2000Test(unittest.TestCase):
    """CIEDE2000 的正確性。

    這是 2026-08-23 從 CIE76 換過來的，換的目的就是「算得對」，
    所以它必須對著公開的參考值驗，不能只驗「有回傳一個數字」。
    """

    # Sharma, Wu & Dalal (2005) 的官方測試資料。這組值專門用來抓實作錯誤：
    # 前六組跨越藍色區（R_T 旋轉項），第 7–9 組跨越 0/360 度的色相接縫，
    # 這兩處是 CIEDE2000 最容易寫錯的地方。
    SHARMA = [
        ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
        ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
        ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
        ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
        ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
        ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
        ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
        ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
        ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
        ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
        ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
        ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
        ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
        ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
        ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
        ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
    ]

    def test_matches_sharma_reference_vectors(self):
        for lab1, lab2, expected in self.SHARMA:
            with self.subTest(lab1=lab1, lab2=lab2):
                # 參考值只給到小數第 4 位，所以容差取 1e-4 而不是更嚴。
                self.assertAlmostEqual(delta_e_ciede2000(lab1, lab2), expected, delta=1e-4)

    def test_identical_colours_are_zero(self):
        self.assertEqual(delta_e_ciede2000((60.0, 8.0, 20.0), (60.0, 8.0, 20.0)), 0.0)

    def test_is_symmetric(self):
        # ΔE00 對調兩色的結果必須相同。這條抓的是「把 1 和 2 寫反」這種錯誤——
        # 它在多數輸入下看起來完全正常。
        a, b = (65.0, 9.0, 18.0), (72.0, 4.0, 25.0)
        self.assertAlmostEqual(delta_e_ciede2000(a, b), delta_e_ciede2000(b, a), places=10)

    def test_hue_seam_does_not_produce_huge_value(self):
        # 色相 359° 與 1° 只差 2 度。若接縫沒處理，會算成差 358 度而得到巨大的值。
        near_zero = (50.0, 10.0, -0.2)
        near_360 = (50.0, 10.0, 0.2)
        self.assertLess(delta_e_ciede2000(near_zero, near_360), 1.0)

    def test_grey_axis_is_handled(self):
        # a*=b*=0 時色相未定義，實作必須不除以零、不回 NaN。
        v = delta_e_ciede2000((50.0, 0.0, 0.0), (60.0, 0.0, 0.0))
        self.assertTrue(math.isfinite(v))
        self.assertGreater(v, 0.0)

    def test_agrees_with_skimage_when_available(self):
        # skimage 不在 requirements.txt 裡（是傳遞相依），所以產品碼不用它，
        # 但它裝得到的時候拿來當第二個參考實作很有價值。
        try:
            from skimage.color import deltaE_ciede2000 as sk_de
        except ImportError:
            self.skipTest("skimage 未安裝")
        rng = np.random.default_rng(0)
        n = 500
        p = np.stack([rng.uniform(40, 95, n), rng.uniform(-5, 30, n), rng.uniform(-5, 40, n)], -1)
        q = np.stack([rng.uniform(40, 95, n), rng.uniform(-5, 30, n), rng.uniform(-5, 40, n)], -1)
        ref = sk_de(p, q)
        mine = np.array([delta_e_ciede2000(p[i], q[i]) for i in range(n)])
        self.assertLess(float(np.abs(ref - mine).max()), 1e-6)


class LabConversionTest(unittest.TestCase):
    """_bgr_mean_to_lab 的定錨點。

    這些是 LAB 的定義而不是實作細節，所以可以拿來抓「縮放寫錯」這類問題——
    除以 2.55 或減 128 少寫一個，程式不會崩，只會讓所有色差悄悄偏掉。
    """

    def setUp(self):
        # 只用到不依賴實例狀態的方法，所以不跑 __init__（那需要一張真的臉）。
        self.fa = FaceAnalyzer.__new__(FaceAnalyzer)

    def test_pure_white(self):
        L, a, b = self.fa._bgr_mean_to_lab((255, 255, 255))
        self.assertAlmostEqual(L, 100.0, delta=1.0)
        self.assertAlmostEqual(a, 0.0, delta=2.0)
        self.assertAlmostEqual(b, 0.0, delta=2.0)

    def test_pure_black(self):
        L, a, b = self.fa._bgr_mean_to_lab((0, 0, 0))
        self.assertAlmostEqual(L, 0.0, delta=1.0)

    def test_L_stays_in_range_for_all_inputs(self):
        for bgr in [(0, 0, 0), (255, 255, 255), (0, 0, 255), (255, 0, 0),
                    (0, 255, 0), (128, 64, 32), (200, 180, 170)]:
            with self.subTest(bgr=bgr):
                L, a, b = self.fa._bgr_mean_to_lab(bgr)
                self.assertGreaterEqual(L, 0.0)
                self.assertLessEqual(L, 100.0)
                self.assertGreaterEqual(a, -128.0)
                self.assertLessEqual(a, 128.0)

    def test_skin_tone_is_warm_positive(self):
        # 典型膚色的 a* 與 b* 都應該是正的（偏紅、偏黃）。
        # 若某天座標軸被寫反，這條會抓到。
        L, a, b = self.fa._bgr_mean_to_lab((170, 190, 220))  # BGR 的淺膚色
        self.assertGreater(a, 0.0)
        self.assertGreater(b, 0.0)


class LabRobustMeanTest(unittest.TestCase):
    """_lab_robust_from_mask —— 膚色取樣用它而不用 cv2.mean，就是為了擋反光。"""

    def setUp(self):
        self.fa = FaceAnalyzer.__new__(FaceAnalyzer)

    def _lab_image(self, base_L, highlight_L, highlight_frac):
        """造一塊大部分是 base、少部分是高光的 LAB 影像（OpenCV 的 0–255 編碼）。"""
        h = w = 40
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:, :, 0] = int(base_L * 2.55)
        img[:, :, 1] = 128 + 10          # a* = +10
        img[:, :, 2] = 128 + 20          # b* = +20
        n_hi = int(h * w * highlight_frac)
        flat = img.reshape(-1, 3)
        flat[:n_hi, 0] = int(highlight_L * 2.55)
        return img

    def test_highlights_do_not_drag_the_mean_up(self):
        img = self._lab_image(base_L=60.0, highlight_L=100.0, highlight_frac=0.15)
        mask = np.full(img.shape[:2], 255, dtype=np.uint8)
        robust_L, _, _ = self.fa._lab_robust_from_mask(img, mask)
        plain_L = float(np.mean(img[:, :, 0])) / 2.55
        # 穩健版必須比單純平均更接近 60（也就是更不受那 15% 高光影響）。
        self.assertLess(abs(robust_L - 60.0), abs(plain_L - 60.0))

    def test_empty_mask_does_not_raise(self):
        # 空遮罩會發生在臉頰被完全遮住的照片上。必須退回 _lab_mean_from_mask，
        # 不能拋例外——那會讓整張照片的分析失敗，而不是只讓膚色不可信。
        img = self._lab_image(60.0, 60.0, 0.0)
        empty = np.zeros(img.shape[:2], dtype=np.uint8)
        result = self.fa._lab_robust_from_mask(img, empty)
        self.assertEqual(len(result), 3)
        self.assertTrue(all(math.isfinite(v) for v in result))


class ShadeClassificationTest(unittest.TestCase):
    """膚色分級的 fallback 行為。

    實測 51 張照片有 50 張走 fallback（見膚色分級落點診斷），
    所以這條「例外路徑」其實是主要路徑，值得測。
    """

    def setUp(self):
        self.fa = FaceAnalyzer.__new__(FaceAnalyzer)
        self.ranges = FaceAnalyzer._MAC_SHADE_RANGES

    def test_every_range_has_a_valid_box(self):
        # MIN 必須小於 MAX，否則那個分級永遠不可能被精確命中，
        # 而且它的「中心」會落在框外——這種錯誤不會有任何症狀。
        for name, r in self.ranges.items():
            with self.subTest(shade=name):
                self.assertLess(r["L_MIN"], r["L_MAX"])
                self.assertLess(r["A_MIN"], r["A_MAX"])
                self.assertLess(r["B_MIN"], r["B_MAX"])

    def test_centre_of_each_box_classifies_as_itself(self):
        # 一個分級的中心點，理應被判成那個分級。做不到就代表框有重疊或包含關係，
        # 使得某些分級被別人整個蓋掉。
        for name, r in self.ranges.items():
            with self.subTest(shade=name):
                lc = (r["L_MIN"] + r["L_MAX"]) / 2
                ac = (r["A_MIN"] + r["A_MAX"]) / 2
                bc = (r["B_MIN"] + r["B_MAX"]) / 2
                nearest = min(
                    self.ranges,
                    key=lambda n: delta_e_ciede2000(
                        (lc, ac, bc),
                        ((self.ranges[n]["L_MIN"] + self.ranges[n]["L_MAX"]) / 2,
                         (self.ranges[n]["A_MIN"] + self.ranges[n]["A_MAX"]) / 2,
                         (self.ranges[n]["B_MIN"] + self.ranges[n]["B_MAX"]) / 2)))
                self.assertEqual(nearest, name)


class PoseGuidanceTest(unittest.TestCase):
    """重拍指引不能要使用者做左右判斷。

    自拍預覽是鏡像的（transform: scaleX(-1)）。第二版寫「你現在露出的是左臉，
    請把頭轉向你的左邊」，等於要人先判斷那個「左」是誰的左、在鏡像畫面裡換算、
    再決定頭往哪轉——三步推理，每一步都可能反過來，而做錯的代價是角度更偏、
    再重拍一次。當時是靠註解擔保「萬一慣例反了使用者能自行修正」，那不是保證。

    改成對稱線索之後，方向由使用者自己收斂，鏡不鏡像都成立。
    """

    LIMITS = (15.0, 15.0)

    def _all_messages(self):
        return [
            pose_guidance(-20.0, 2.0, *self.LIMITS),   # 一邊偏
            pose_guidance(20.0, 2.0, *self.LIMITS),    # 另一邊偏
            pose_guidance(2.0, 24.0, *self.LIMITS),    # 抬頭低頭
            pose_guidance(-20.0, 24.0, *self.LIMITS),  # 兩個都偏
            pose_guidance(1.0, 1.0, *self.LIMITS),     # 都沒超標
        ]

    def test_no_message_asks_the_user_to_tell_left_from_right(self):
        for message in self._all_messages():
            self.assertNotIn("左", message, message)
            self.assertNotIn("右", message, message)

    def test_turning_the_head_either_way_reads_the_same(self):
        """左偏與右偏給同一句話——因為使用者要做的動作就是同一件事：轉到對稱為止。

        兩邊給不同的話，就代表訊息又依賴左右慣例了。
        """
        self.assertEqual(pose_guidance(-20.0, 2.0, *self.LIMITS),
                         pose_guidance(20.0, 2.0, *self.LIMITS))

    def test_each_axis_gets_its_own_actionable_sentence(self):
        yaw_only = pose_guidance(-20.0, 2.0, *self.LIMITS)
        pitch_only = pose_guidance(2.0, 24.0, *self.LIMITS)
        both = pose_guidance(-20.0, 24.0, *self.LIMITS)

        self.assertNotEqual(yaw_only, pitch_only, "兩個軸不能給一樣的指引")
        # 兩個都超標時兩句都要出現，否則使用者修好一個還是過不了。
        self.assertIn(yaw_only.rstrip("。"), both)
        self.assertIn(pitch_only.rstrip("。"), both)

    def test_there_is_always_something_to_do(self):
        for message in self._all_messages():
            self.assertTrue(message.strip())
            self.assertTrue(message.endswith("。"), message)


if __name__ == "__main__":
    unittest.main()
