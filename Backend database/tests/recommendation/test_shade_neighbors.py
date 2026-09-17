import random
import unittest
from unittest.mock import patch

import app as app_module
from shade_neighbors import ShadeNeighborIndex


def foundation(product_id, brand, lab, shade, series="series", name=None, undertone="",
               official=False, depth=None, ready=True):
    return {
        "id": product_id,
        "type": "foundations",
        "name": name or f"{brand} 粉底液 {shade}",
        "brand": brand,
        "shadeCode": shade,
        "shadeName": shade,
        "imageUrl": f"https://img.example/{product_id}.webp",
        "seriesId": f"{brand}::{series}",
        "depthIndex": depth,
        "depthIndexOfficial": official,
        "undertone": undertone,
        "lab": lab,
        "inStock": True,
        "status": "active",
        "reviewStatus": "approved",
        "recommendationReady": ready,
        "colorMatchReady": ready,
    }


def ids(entries):
    return [entry["id"] for entry in entries]


class NeighborRuleTests(unittest.TestCase):
    def setUp(self):
        self.index = ShadeNeighborIndex()

    def test_same_brand_lighter_and_darker_ignore_series(self):
        source = foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30", series="studio-fix")
        other_series_lighter = foundation(2, "MAC", [68.0, 9.5, 17.5], "NC25", series="face-and-body")
        other_series_darker = foundation(3, "MAC", [61.0, 10.5, 18.5], "NC35", series="studio-radiance")
        self.index.refresh([source, other_series_lighter, other_series_darker])

        payload = self.index.neighbors_payload(source)

        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["sameBrand"]["scope"], "same_brand_any_series")
        self.assertEqual(ids(payload["sameBrand"]["lighter"]), [2])
        self.assertEqual(ids(payload["sameBrand"]["darker"]), [3])
        self.assertEqual(payload["sameBrand"]["lighter"][0]["label"], "較淺相近色")
        self.assertIsNone(payload["officialSteps"])

    def test_paler_but_pinker_shade_is_not_a_lighter_neighbour(self):
        source = foundation(1, "MAC", [65.0, 8.0, 20.0], "NC30")
        pinker = foundation(2, "MAC", [68.0, 13.0, 14.0], "NW25")
        same_tone = foundation(3, "MAC", [69.5, 7.8, 19.5], "NC20")
        self.index.refresh([source, pinker, same_tone])

        payload = self.index.neighbors_payload(source)

        self.assertEqual(ids(payload["sameBrand"]["lighter"]), [3])
        self.assertIn(2, ids(payload["sameBrand"]["closest"]))

    def test_explicit_opposite_undertones_are_not_lighter_or_darker(self):
        source = foundation(1, "A", [65.0, 9.0, 18.0], "W30", undertone="warm")
        cool = foundation(2, "B", [68.0, 9.0, 18.0], "C25", undertone="cool")
        self.index.refresh([source, cool])

        payload = self.index.neighbors_payload(source)

        self.assertEqual(payload["crossBrand"]["lighter"], [])
        self.assertEqual(ids(payload["crossBrand"]["closest"]), [2])

    def test_official_steps_only_with_official_order(self):
        rows = [foundation(i, "YSL", [60.0 + i * 3, 9.0, 18.0], f"B{i}", official=True, depth=10 - i)
                for i in range(1, 4)]
        self.index.refresh(rows)

        payload = self.index.neighbors_payload(rows[1])

        self.assertEqual(payload["officialSteps"]["lighter"]["id"], 3)
        self.assertEqual(payload["officialSteps"]["lighter"]["label"], "淺一階")
        self.assertEqual(payload["officialSteps"]["darker"]["id"], 1)
        self.assertEqual(payload["officialSteps"]["darker"]["label"], "深一階")

    def test_concealer_is_not_a_foundation_substitute_and_forms_are_labelled(self):
        source = foundation(1, "A", [65.0, 9.0, 18.0], "01")
        concealer = foundation(2, "B", [65.0, 9.0, 18.0], "01", name="B 超持妝無瑕底妝點點筆 01")
        cushion = foundation(3, "C", [65.5, 9.0, 18.0], "21", name="C 氣墊粉餅 21")
        self.index.refresh([source, concealer, cushion])

        closest = self.index.neighbors_payload(source)["crossBrand"]["closest"]

        self.assertEqual(ids(closest), [3])
        self.assertFalse(closest[0]["sameProductForm"])
        self.assertIn("型態不同", closest[0]["formNote"])
        self.assertEqual(set(closest[0]), {
            "id", "brand", "shadeCode", "shadeName", "imageUrl", "productForm", "productFormLabel",
            "deltaE", "lightnessDifference", "sameProductForm", "formNote",
        })

    def test_untrusted_colour_is_unavailable_and_unknown_snapshot_is_pending(self):
        no_lab = {**foundation(1, "A", None, "01"), "colorMatchReady": False}
        self.assertEqual(self.index.neighbors_payload(no_lab)["status"], "unavailable")
        self.assertEqual(self.index.neighbors_payload(foundation(2, "A", [60.0, 9.0, 18.0], "02"))["status"],
                         "pending")

    def test_large_refresh_runs_in_background(self):
        rows = [foundation(i, "A", [50.0 + i * 0.1, 9.0, 18.0], str(i)) for i in range(40)]
        self.index.SYNC_WORK_LIMIT = 0
        self.assertEqual(self.index.refresh(rows), "pending")
        self.index._worker.join(timeout=10)
        self.assertEqual(self.index.neighbors_payload(rows[0])["status"], "ready")

    def test_repeated_requests_during_background_build_do_not_restart_it(self):
        import threading
        import shade_neighbors

        rows = [foundation(i, "A", [50.0 + i * 0.1, 9.0, 18.0], str(i)) for i in range(40)]
        newer = rows[:-1]
        release, builds = threading.Event(), []
        original = shade_neighbors._compute_lists

        def slow_compute(source, pool):
            if not builds or builds[-1] != len(pool):
                builds.append(len(pool))
            release.wait(timeout=10)
            return original(source, pool)

        self.index.SYNC_WORK_LIMIT = 0
        with patch.object(shade_neighbors, "_compute_lists", side_effect=slow_compute):
            self.assertEqual(self.index.refresh(rows), "pending")
            for _ in range(5):
                self.assertEqual(self.index.refresh(rows), "pending")
            self.assertEqual(self.index.refresh(newer), "pending")
            release.set()
            self.index._worker.join(timeout=10)

        self.assertEqual(builds, [40, 39])
        self.assertEqual(self.index.neighbors_payload(newer[0])["status"], "ready")
        self.assertEqual(self.index.neighbors_payload(rows[-1])["status"], "pending")


class IncrementalRefreshTests(unittest.TestCase):
    def random_catalog(self, rng, count):
        brands = ["MAC", "YSL", "CHANEL", "NARS"]
        return {i: foundation(i, rng.choice(brands),
                              [rng.uniform(40, 80), rng.uniform(4, 14), rng.uniform(10, 24)],
                              f"S{i}", name=rng.choice(["粉底液", "氣墊", "遮瑕液"]) + f" {i}")
                for i in range(1, count + 1)}

    def test_incremental_updates_match_full_rebuild(self):
        rng = random.Random(7)
        catalog = self.random_catalog(rng, 60)
        incremental = ShadeNeighborIndex()
        incremental.refresh(list(catalog.values()))
        next_id = 61
        modes = set()
        for _ in range(40):
            action = rng.random()
            if action < 0.35 and len(catalog) > 5:
                del catalog[rng.choice(list(catalog))]
            elif action < 0.7:
                pid = rng.choice(list(catalog))
                catalog[pid] = {**catalog[pid], "lab": [rng.uniform(40, 80), rng.uniform(4, 14),
                                                        rng.uniform(10, 24)]}
            else:
                catalog[next_id] = foundation(next_id, "NARS", [rng.uniform(40, 80), 9.0, 17.0], f"N{next_id}")
                next_id += 1
            incremental.refresh(list(catalog.values()))
            modes.add(incremental.last_refresh["mode"])

            fresh = ShadeNeighborIndex()
            fresh.refresh(list(catalog.values()))
            for item in catalog.values():
                self.assertEqual(incremental.neighbors_payload(item), fresh.neighbors_payload(item))
                self.assertEqual(incremental.cross_brand_ranking(item, 20), fresh.cross_brand_ranking(item, 20))
        self.assertIn("incremental", modes)

    def test_single_edit_does_not_recompute_every_source(self):
        rows = [foundation(i, "MAC" if i % 2 else "YSL", [40.0 + i * 2, 9.0, 18.0], str(i)) for i in range(1, 21)]
        index = ShadeNeighborIndex()
        index.refresh(rows)
        rows[0] = {**rows[0], "imageUrl": "https://img.example/new.webp"}

        index.refresh(rows)

        self.assertLess(index.last_refresh["recomputedSources"], len(rows))
        self.assertEqual(index.refresh(rows), "ready")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_precomputed_shade_matches_equal_on_demand_results(self):
        rng = random.Random(3)
        rows = [foundation(i, rng.choice(["MAC", "YSL", "CHANEL"]),
                           [rng.uniform(45, 75), rng.uniform(5, 13), rng.uniform(12, 22)], f"S{i}")
                for i in range(1, 41)]
        by_id = {row["id"]: row for row in rows}
        with patch.object(app_module, "_catalog_rows", return_value=rows), \
                patch.object(app_module, "_catalog_item_by_id", side_effect=lambda pid, **_: by_id.get(pid)), \
                patch.object(app_module, "shade_neighbor_index", ShadeNeighborIndex()):
            for pid in (1, 7, 22):
                pre = self.client.get(f"/api/products/{pid}/shade-matches?limit=10").get_json()
                self.assertTrue(pre["precomputed"])
                with patch.object(app_module.shade_neighbor_index, "cross_brand_ranking", return_value=None), \
                        patch.object(app_module, "_refresh_shade_neighbor_index", return_value="pending"):
                    live = self.client.get(f"/api/products/{pid}/shade-matches?limit=10").get_json()
                self.assertFalse(live["precomputed"])
                for body in (pre, live):
                    body.pop("precomputed")
                self.assertEqual(pre, live)

    def test_product_detail_embeds_precomputed_neighbours(self):
        source = foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30")
        rows = [source, foundation(2, "YSL", [66.5, 10.0, 18.0], "B20")]
        with patch.object(app_module, "_catalog_rows", return_value=rows), \
                patch.object(app_module, "_catalog_item_by_id", return_value=dict(source)), \
                patch.object(app_module, "shade_neighbor_index", ShadeNeighborIndex()):
            body = self.client.get("/api/products/1").get_json()

        self.assertEqual(body["shadeCode"], "NC30")
        self.assertEqual(body["shadeNeighbors"]["status"], "ready")
        self.assertEqual(ids(body["shadeNeighbors"]["crossBrand"]["lighter"]), [2])
        # 商品詳情頁的 SPA 使用 foundationCrossBrand；它必須拿到完整商品，
        # 不能只拿到預計算索引的 ID，否則資料存在卻不會被畫出來。
        cross_brand = body["foundationCrossBrand"]
        self.assertEqual(cross_brand["status"], "ready")
        # 選單包含來源品牌，才能在從其他品牌返回 MAC 時取得 MAC 自己的
        # 三色階；跨品牌候選仍然只有 YSL。
        self.assertEqual(cross_brand["availableTargetBrands"], ["MAC", "YSL"])
        self.assertEqual(cross_brand["items"][0]["brand"], "YSL")
        self.assertEqual(cross_brand["items"][0]["product"]["id"], 2)
        self.assertEqual(cross_brand["items"][0]["product"]["shadeCode"], "B20")

    def test_product_detail_does_not_wait_for_background_rebuild(self):
        source = foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30")
        with patch.object(app_module, "_catalog_rows", return_value=[source]), \
                patch.object(app_module, "_catalog_item_by_id", return_value=dict(source)), \
                patch.object(app_module, "_refresh_shade_neighbor_index", return_value="pending"), \
                patch.object(app_module, "shade_neighbor_index", ShadeNeighborIndex()):
            response = self.client.get("/api/products/1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["shadeNeighbors"]["status"], "pending")

    def test_product_detail_returns_cross_brand_matches_during_cold_index_build(self):
        source = foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30")
        candidate = foundation(2, "NARS", [66.0, 10.0, 18.0], "Deauville")
        with patch.object(app_module, "_catalog_rows", return_value=[source, candidate]), \
                patch.object(app_module, "_catalog_item_by_id", return_value=dict(source)), \
                patch.object(app_module, "_refresh_shade_neighbor_index", return_value="pending"), \
                patch.object(app_module, "shade_neighbor_index", ShadeNeighborIndex()):
            body = self.client.get("/api/products/1").get_json()

        self.assertEqual(body["shadeNeighbors"]["status"], "pending")
        cross_brand = body["foundationCrossBrand"]
        self.assertFalse(cross_brand["precomputed"])
        self.assertEqual(cross_brand["availableTargetBrands"], ["MAC", "NARS"])
        self.assertEqual(cross_brand["items"][0]["product"]["id"], 2)

    def test_explicit_source_brand_returns_three_colour_ladder(self):
        source = foundation(1, "MAC", [65.0, 10.0, 18.0], "NC30")
        lighter = foundation(2, "MAC", [68.0, 10.2, 18.1], "NC25")
        darker = foundation(3, "MAC", [62.0, 9.8, 18.1], "NC35")
        other = foundation(4, "NARS", [65.5, 10.0, 18.0], "Deauville")
        rows = [source, lighter, darker, other]
        with patch.object(app_module, "_catalog_rows", return_value=rows), \
                patch.object(app_module, "_catalog_item_by_id", return_value=dict(source)), \
                patch.object(app_module, "shade_neighbor_index", ShadeNeighborIndex()):
            body = self.client.get("/api/products/1/shade-matches?targetBrand=MAC&limit=5").get_json()

        self.assertEqual(body["targetBrand"], "MAC")
        self.assertEqual([item["shadeMatch"]["relation"] for item in body["shadeLadder"]],
                         ["lighter", "closest", "darker"])
        self.assertEqual([item["shadeCode"] for item in body["shadeLadder"]],
                         ["NC25", "NC30", "NC35"])


if __name__ == "__main__":
    unittest.main()
