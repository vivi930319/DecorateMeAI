import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import product_image_mirror

SOURCE = "https://www.lancome.com.tw/dw/image/v2/AARM_PRD/on/demandware.static/a.jpg"


class ProductImageMirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manifest = Path(self.tmp.name) / "product_image_mirror.json"
        patcher = patch.object(product_image_mirror, "MANIFEST_PATH", self.manifest)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        product_image_mirror._state.update(mtime=None, base="", images={})

    def write(self, images):
        self.manifest.write_text(json.dumps({"base": "https://decorate-me.web.app/", "images": images}), "utf-8")

    def test_without_manifest_original_url_is_kept(self):
        self.assertEqual(product_image_mirror.mirrored_image_url(SOURCE), SOURCE)

    def test_published_image_uses_same_origin_copy(self):
        self.write({SOURCE: "/product-images/abc.webp"})
        self.assertEqual(product_image_mirror.mirrored_image_url(SOURCE),
                         "https://decorate-me.web.app/product-images/abc.webp")
        self.assertEqual(product_image_mirror.mirrored_image_url("https://other/x.jpg"), "https://other/x.jpg")
        self.assertEqual(product_image_mirror.mirrored_image_url(""), "")

    def test_manifest_changes_are_picked_up_and_can_be_disabled(self):
        self.write({})
        self.assertEqual(product_image_mirror.mirrored_image_url(SOURCE), SOURCE)
        self.write({SOURCE: "/product-images/new.webp"})
        os.utime(self.manifest, (1, 1))
        self.assertTrue(product_image_mirror.mirrored_image_url(SOURCE).endswith("/new.webp"))
        with patch.dict(os.environ, {"PRODUCT_IMAGE_MIRROR_DISABLED": "1"}):
            self.assertEqual(product_image_mirror.mirrored_image_url(SOURCE), SOURCE)

    def test_catalog_payload_exposes_mirror_and_keeps_source(self):
        import app as app_module

        self.write({SOURCE: "/product-images/abc.webp"})
        row = {
            "global_id": 1, "source_id": 2, "product_type": "lipsticks", "name": "蘭蔻唇膏", "brand": "LANCOME",
            "price": 1000, "currency": "TWD", "description": "d", "image_url": SOURCE,
            "source_url": "https://www.lancome.com.tw/p", "source_site": "lancome", "source_product_id": "x",
            "sku": "A02311", "sale_page_id": "1", "category": "唇彩", "shades": None, "season_tags": [],
            "undertone": "", "shade_code": "277", "shade_name": "277", "series_id": None, "depth_index": None,
            "version": 1, "hex_primary": "#aa3344", "lab": None, "palette_colors": [],
            "palette_image_url": None, "color_evidence": {}, "in_stock": True, "status": "active",
            "review_status": "approved", "recommendation_ready": True,
        }
        payload = app_module._catalog_payload(row)
        mirrored = "https://decorate-me.web.app/product-images/abc.webp"
        self.assertEqual((payload["imageUrl"], payload["image_url"], payload["image_src"]),
                         (mirrored, mirrored, mirrored))
        self.assertEqual(payload["sourceImageUrl"], SOURCE)


class MirrorKeyTests(unittest.TestCase):
    def test_key_is_stable_and_path_safe(self):
        key = product_image_mirror.mirror_key(SOURCE)
        self.assertEqual(key, product_image_mirror.mirror_key(f"  {SOURCE} "))
        self.assertRegex(key, r"^[0-9a-f]{32}$")


if __name__ == "__main__":
    unittest.main()
