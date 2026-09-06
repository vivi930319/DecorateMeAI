import json
import unittest

from crawler_preview import parse_product_preview


def product_html(product):
    return (
        '<html><head><script type="application/ld+json">'
        + json.dumps(product)
        + '</script></head><body></body></html>'
    )


class OfficialBrandCrawlerPreviewTests(unittest.TestCase):
    def test_maybelline_taiwan_profile_normalizes_brand_and_category(self):
        preview = parse_product_preview(product_html({
            "@type": "Product",
            "name": "Super Stay Lumi-Matte",
            "brand": {"@type": "Brand", "name": "Maybelline 媚比琳"},
            "image": "https://www.maybelline.com.tw/image.jpg",
            "offers": {"@type": "Offer", "price": "569", "priceCurrency": "TWD"},
        }), "https://www.maybelline.com.tw/all-products/face-makeup/liquid-foundation/superstay")

        self.assertEqual(preview["brand"], "MAYBELLINE")
        self.assertEqual(preview["category"], "foundations")
        self.assertEqual(preview["displayPrice"], "NT$569")
        self.assertFalse(preview["priceConverted"])
        self.assertNotIn("category", preview["missingFields"])

    def test_bobbi_brown_us_profile_discloses_twd_conversion(self):
        preview = parse_product_preview(product_html({
            "@type": "Product",
            "name": "Weightless Skin Foundation",
            "brand": "Bobbi Brown Cosmetics",
            "category": "Foundation",
            "image": "https://www.bobbibrowncosmetics.com/image.jpg",
            "offers": {"@type": "Offer", "price": "58.00", "priceCurrency": "USD"},
        }), "https://www.bobbibrowncosmetics.com/product/weightless-skin-foundation")

        self.assertEqual(preview["brand"], "BOBBI BROWN")
        self.assertEqual(preview["category"], "foundations")
        self.assertEqual(preview["displayPrice"], "NT$1,838")
        self.assertTrue(preview["priceConverted"])
        self.assertEqual(
            preview["priceConversion"]["calculation"],
            "US$58.00 × 31.685 = NT$1,838",
        )


if __name__ == "__main__":
    unittest.main()
