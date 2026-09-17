"""粉底較淺／較深參考與跨品牌比色的規則測試（/recommend-products 側）。

商品頁 /api/products/<id> 與 /api/products/<id>/shade-matches 的索引與快取
行為在 test_shade_neighbors.py；這裡專門測推薦回應裡的 shadeRecommendation
與 foundationCrossBrandAlternatives。
"""

import time
import unittest

from recommendation import recommend_products


def foundation(product_id, brand, lab, shade, series="series", name=None, **extra):
    row = {
        "id": product_id,
        "type": "foundations",
        "category": "base",
        "candidateKey": f"foundations:{product_id}",
        "brand": brand,
        "name": name or f"{brand} 粉底液 {shade}",
        "shadeCode": shade,
        "shadeName": shade,
        "seriesId": f"{brand}::{series}",
        "lab": lab,
        "inStock": True,
    }
    row.update(extra)
    return row


def analyse(lab):
    return {"style": "richGirl",
            "faceAnalysis": {"skinTone": {"lab": lab, "labReliable": True}}}


class DepthReferenceScopeTests(unittest.TestCase):
    """同品牌不限系列；同品牌沒有該方向的色號時才跨品牌。"""

    def test_same_brand_other_series_is_a_valid_reference(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30", series="studio-fix"),
            foundation(2, "MAC", [68.0, 9.5, 17.5], "NC25", series="face-and-body"),
            foundation(3, "MAC", [61.0, 10.5, 18.5], "NC35", series="studio-radiance"),
        ]

        shades = recommend_products(analyse([65.0, 10.0, 18.0]), rows)["shadeRecommendation"]

        self.assertEqual(shades["anchor"]["shadeCode"], "NC30")
        self.assertEqual(shades["lighter"]["shadeCode"], "NC25")
        self.assertEqual(shades["darker"]["shadeCode"], "NC35")
        for direction in ("lighter", "darker"):
            self.assertEqual(shades[direction]["scope"], "same_brand_any_series")
            # 跨系列沒有共同的官方色階，不得冒稱品牌定義的一階。
            self.assertFalse(shades[direction]["officialShadeLadder"])
            self.assertEqual(shades[direction]["label"],
                             "較淺相近色" if direction == "lighter" else "較深相近色")
        self.assertIn("不代表品牌定義的淺一階或深一階", shades["disclaimer"])

    def test_nearest_same_brand_shade_wins_over_a_closer_other_brand(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            foundation(2, "MAC", [68.0, 10.0, 18.0], "NC25", series="other-line"),
            foundation(3, "YSL", [66.2, 10.0, 18.0], "B20"),
        ]

        shades = recommend_products(analyse([65.0, 10.0, 18.0]), rows)["shadeRecommendation"]

        self.assertEqual(shades["lighter"]["shadeCode"], "NC25")
        self.assertEqual(shades["lighter"]["scope"], "same_brand_any_series")

    def test_cross_brand_is_used_only_when_the_brand_has_no_shade_that_way(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            foundation(2, "YSL", [68.0, 10.0, 18.0], "B20"),
        ]

        shades = recommend_products(analyse([65.0, 10.0, 18.0]), rows)["shadeRecommendation"]

        self.assertEqual(shades["lighter"]["shadeCode"], "B20")
        self.assertEqual(shades["lighter"]["scope"], "cross_brand")
        self.assertIsNone(shades["darker"])
        self.assertEqual(shades["selectionScope"], "same_brand_any_series_then_cross_brand")
        self.assertEqual(shades["depthReferencePolicy"]["scopeOrder"],
                         ["same_brand_any_series", "cross_brand"])


class UndertoneGuardTests(unittest.TestCase):
    """先限制合理色相冷暖，再比明度。"""

    def test_paler_but_pinker_shade_is_not_a_lighter_reference(self):
        rows = [
            foundation(1, "MAC", [65.0, 8.0, 20.0], "NC30"),
            foundation(2, "MAC", [68.0, 13.0, 14.0], "NW25"),
            foundation(3, "MAC", [69.5, 7.8, 19.5], "NC20"),
        ]

        result = recommend_products(analyse([65.0, 8.0, 20.0]), rows)

        # 偏粉的 NW25 雖然比 NC20 更接近錨點明度，但底調換邊，不是較淺參考。
        self.assertEqual(result["shadeRecommendation"]["lighter"]["shadeCode"], "NC20")

    def test_same_lightness_sibling_is_not_reported_as_another_step(self):
        rows = [
            foundation(1, "Demo", [65.0, 8.0, 14.0], "Main"),
            foundation(2, "Demo", [65.4, 8.0, 14.0], "Twin"),
        ]

        shades = recommend_products(analyse([65.0, 8.0, 14.0]), rows)["shadeRecommendation"]

        self.assertIsNone(shades["lighter"])
        self.assertIsNone(shades["darker"])

    def test_policy_thresholds_are_disclosed(self):
        rows = [foundation(1, "Demo", [65.0, 8.0, 14.0], "Main"),
                foundation(2, "Demo", [68.0, 8.0, 14.0], "Light")]

        policy = recommend_products(analyse([65.0, 8.0, 14.0]), rows)[
            "shadeRecommendation"]["depthReferencePolicy"]

        self.assertFalse(policy["officialShadeLadder"])
        self.assertEqual(policy["method"], "lab_lightness_within_tone_guard")
        for field in ("minLightnessStep", "toneMaxDeltaE", "stepMaxDeltaE"):
            self.assertIsInstance(policy[field], float)


class ConcealerSeparationTests(unittest.TestCase):
    def test_concealer_is_never_a_lighter_darker_or_cross_brand_substitute(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            foundation(2, "MAC", [68.0, 10.0, 18.0], "NC25", name="MAC 遮瑕液 NC25"),
            foundation(3, "YSL", [65.1, 10.0, 18.0], "B20", name="YSL 遮瑕膏 B20"),
            foundation(4, "YSL", [66.8, 10.0, 18.0], "B25"),
        ]

        result = recommend_products(analyse([65.0, 10.0, 18.0]), rows)
        shades = result["shadeRecommendation"]

        # 同品牌唯一的較淺色號是遮瑕，因此較淺要退到跨品牌的粉底，而不是遮瑕。
        self.assertEqual(shades["lighter"]["shadeCode"], "B25")
        self.assertEqual(shades["lighter"]["scope"], "cross_brand")
        cross_brand = result["foundationCrossBrandAlternatives"]
        self.assertEqual([item["shadeCode"] for item in cross_brand], ["B25"])


class ColorEvidenceGateTests(unittest.TestCase):
    """不得繞過 colorMatchReady，也不得由未驗證的 HEX 偽造色彩證據。"""

    def test_hex_only_shade_never_becomes_a_reference_or_cross_brand_option(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            {**foundation(2, "MAC", None, "NC25"), "lab": None, "hex_primary": "#e8c4a6"},
            {**foundation(3, "YSL", None, "B20"), "lab": None, "hex": "#e8c4a6"},
        ]

        result = recommend_products(analyse([65.0, 10.0, 18.0]), rows)

        self.assertIsNone(result["shadeRecommendation"]["lighter"])
        self.assertIsNone(result["shadeRecommendation"]["darker"])
        self.assertEqual(result["foundationCrossBrandAlternatives"], [])

    def test_unverified_colour_is_excluded_even_when_a_lab_value_is_present(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            foundation(2, "YSL", [66.5, 10.0, 18.0], "B20", colorMatchReady=False),
        ]

        result = recommend_products(analyse([65.0, 10.0, 18.0]), rows)

        self.assertEqual(result["foundationCrossBrandAlternatives"], [])
        self.assertIsNone(result["shadeRecommendation"]["lighter"])

    def test_cross_brand_options_always_declare_verified_evidence(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            foundation(2, "YSL", [66.5, 10.0, 18.0], "B20"),
        ]

        cross_brand = recommend_products(
            analyse([65.0, 10.0, 18.0]), rows)["foundationCrossBrandAlternatives"]

        self.assertEqual(len(cross_brand), 1)
        self.assertTrue(cross_brand[0]["colorMatchVerified"])
        self.assertEqual(cross_brand[0]["colorEvidenceStatus"], "verified_official_numeric")
        self.assertEqual(cross_brand[0]["comparisonScope"], "cross_brand_any_series")


class ResponseCompatibilityTests(unittest.TestCase):
    """既有前端讀得到的欄位一個都不能少。"""

    shade_fields = {
        "method", "seriesId", "selectionScope", "alternativeMaxDeltaE", "matchTier",
        "strictAnchorAvailable", "disclaimer", "anchor", "lighter", "darker",
    }
    choice_fields = {
        "relation", "label", "description", "shadeCode", "depthIndex", "anchorDeltaE",
        "lightnessDifference", "matchScore", "matchPercent", "colorMatchVerified",
        "withinAlternativeCap", "product",
    }
    cross_brand_fields = {
        "brand", "shadeCode", "anchorDeltaE", "colorMatchVerified", "colorEvidenceStatus",
        "product", "comparisonAnchor", "disclaimer",
    }

    def test_existing_fields_are_all_still_present(self):
        rows = [
            foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30"),
            foundation(2, "MAC", [68.0, 10.0, 18.0], "NC25", series="other"),
            foundation(3, "MAC", [62.0, 10.0, 18.0], "NC35", series="other"),
            foundation(4, "YSL", [66.5, 10.0, 18.0], "B20"),
        ]

        result = recommend_products(analyse([65.0, 10.0, 18.0]), rows)
        shades = result["shadeRecommendation"]

        self.assertLessEqual(self.shade_fields, set(shades))
        for direction in ("anchor", "lighter", "darker"):
            self.assertLessEqual(self.choice_fields, set(shades[direction]))
        self.assertLessEqual(self.cross_brand_fields, set(result["foundationCrossBrandAlternatives"][0]))
        self.assertEqual(result["colorDifferencePolicy"]["shadeAlternative"]["maxInclusive"], 5.0)

    def test_official_brand_ladder_still_uses_the_official_wording(self):
        rows = [
            foundation(11, "Brand A", [69.0, 8.0, 14.0], "10", depthIndex=10, depthIndexOfficial=True),
            foundation(12, "Brand A", [65.0, 8.0, 14.0], "20", depthIndex=20, depthIndexOfficial=True),
            foundation(13, "Brand A", [61.0, 8.0, 14.0], "30", depthIndex=30, depthIndexOfficial=True),
        ]

        shades = recommend_products(analyse([65.0, 8.0, 14.0]), rows)["shadeRecommendation"]

        self.assertEqual(shades["method"], "official_depth_index")
        self.assertEqual(shades["selectionScope"], "same_brand_same_series")
        self.assertIsNone(shades["depthReferencePolicy"])
        self.assertEqual(shades["lighter"]["label"], "淺一階")
        self.assertTrue(shades["lighter"]["officialShadeLadder"])
        self.assertEqual(shades["lighter"]["scope"], "same_brand_same_series")


class PerformanceTests(unittest.TestCase):
    """比較邏輯放寬後，單次推薦仍必須是一次線性掃描，不是每支色號掃全庫。"""

    def build_catalog(self, count):
        brands = ("MAC", "YSL", "CHANEL", "NARS", "Dior")
        return [foundation(i, brands[i % len(brands)],
                           [40.0 + (i % 400) * 0.1, 8.0 + (i % 5) * 0.4, 14.0 + (i % 7) * 0.3],
                           f"S{i}", series=f"line-{i % 6}")
                for i in range(1, count + 1)]

    def test_shade_reference_cost_grows_linearly_with_the_catalogue(self):
        small, large = self.build_catalog(150), self.build_catalog(1200)
        package = analyse([60.0, 9.0, 16.0])

        def measure(rows):
            recommend_products(package, rows, limit=12)
            started = time.perf_counter()
            for _ in range(3):
                recommend_products(package, rows, limit=12)
            return (time.perf_counter() - started) / 3

        small_seconds, large_seconds = measure(small), measure(large)
        print(f"\nrecommend_products: {len(small)} 筆 {small_seconds * 1000:.1f} ms / "
              f"{len(large)} 筆 {large_seconds * 1000:.1f} ms")
        # 8 倍資料量若呈平方成長會是 64 倍；放寬到 24 倍仍足以擋住 O(n²)。
        self.assertLess(large_seconds, max(small_seconds * 24, 0.05))


if __name__ == "__main__":
    unittest.main()
