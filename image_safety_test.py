"""`image_safety` 的驗收測試（P0-10）。

三件事非測不可，因為它們都是「看起來會過、實際上不會過」的檢查：
偽 MIME、解壓縮炸彈、EXIF 清除。前兩者失效時服務照常回 200，沒有測試就不會有人發現。
"""

import asyncio
import io
import unittest

from PIL import Image

import image_safety
from image_safety import (
    ImageRejected,
    read_upload_within_limit,
    sanitize_image_bytes,
    sniff_image_format,
)


def _png_bytes(width: int = 8, height: int = 8) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 150, 120)).save(buffer, format="PNG")
    return buffer.getvalue()


def _jpeg_with_gps() -> bytes:
    """一張帶 GPS 座標與機身型號的 JPEG——手機直出照片的縮影。"""
    from PIL.TiffImagePlugin import IFDRational

    exif = Image.Exif()
    exif[0x010F] = "TestPhone"  # Make
    exif[0x8825] = {  # GPSInfo
        1: "N",
        2: (IFDRational(25, 1), IFDRational(2, 1), IFDRational(0, 1)),
    }
    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 20, 30)).save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


class _FakeUpload:
    """最小的 UploadFile 替身：只要有 async read(size) 就夠用。"""

    def __init__(self, data: bytes):
        self._stream = io.BytesIO(data)

    async def read(self, size: int = -1) -> bytes:
        return self._stream.read(size if size and size > 0 else None)


class SniffTest(unittest.TestCase):
    def test_recognises_the_three_allowed_formats(self):
        self.assertEqual(sniff_image_format(_png_bytes()), "PNG")
        jpeg = io.BytesIO()
        Image.new("RGB", (4, 4)).save(jpeg, format="JPEG")
        self.assertEqual(sniff_image_format(jpeg.getvalue()), "JPEG")
        webp = io.BytesIO()
        Image.new("RGB", (4, 4)).save(webp, format="WEBP")
        self.assertEqual(sniff_image_format(webp.getvalue()), "WEBP")

    def test_rejects_everything_else(self):
        self.assertIsNone(sniff_image_format(b"GIF89a\x01\x00"))
        self.assertIsNone(sniff_image_format(b"<svg xmlns='http://www.w3.org/2000/svg'/>"))
        self.assertIsNone(sniff_image_format(b"%PDF-1.7"))
        self.assertIsNone(sniff_image_format(b""))


class SanitizeTest(unittest.TestCase):
    def test_accepts_a_plain_png_without_reencoding(self):
        data = _png_bytes()
        cleaned, mime = sanitize_image_bytes(data)
        self.assertEqual(mime, "image/png")
        # 沒有中繼資料要清就不該重新編碼——重編一次是白白損失一次畫質。
        self.assertEqual(cleaned, data)

    def test_rejects_a_gif_even_though_pillow_can_read_it(self):
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buffer, format="GIF")
        with self.assertRaises(ImageRejected) as caught:
            sanitize_image_bytes(buffer.getvalue())
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_IMAGE_TYPE")

    def test_rejects_a_script_renamed_as_an_image(self):
        """偽造的上傳：內容是文字，只是宣稱自己是 .jpg。"""
        with self.assertRaises(ImageRejected) as caught:
            sanitize_image_bytes(b"<?php system($_GET['c']); ?>" * 10)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_IMAGE_TYPE")

    def test_rejects_a_jpeg_header_glued_onto_png_data(self):
        """偽 MIME：檔頭說 JPEG，實際內容是 PNG。

        這是最容易漏掉的一種——只看 magic bytes 會過（開頭真的是 FFD8FF），
        只看 Pillow 解出來的格式也會過（真的解得出 PNG）。要兩邊比對才擋得下來。
        """
        forged = b"\xff\xd8\xff\xe0" + _png_bytes()
        with self.assertRaises(ImageRejected) as caught:
            sanitize_image_bytes(forged)
        self.assertIn(caught.exception.code, {"IMAGE_TYPE_MISMATCH", "INVALID_IMAGE"})

    def test_rejects_a_decompression_bomb_before_decoding_it(self):
        """一張小小的 PNG 可以宣告成天文數字的尺寸，解開就是好幾 GB 的點陣圖。

        關鍵是「在解碼之前」擋下來：等解完再檢查像素數，記憶體早就吃光了。
        """
        bomb = io.BytesIO()
        Image.new("L", (12000, 12000)).save(bomb, format="PNG")
        payload = bomb.getvalue()
        with self.assertRaises(ImageRejected) as caught:
            sanitize_image_bytes(payload, max_pixels=1_000_000, max_bytes=50 * 1024 * 1024)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.code, "IMAGE_DIMENSIONS_TOO_LARGE")

    def test_rejects_oversized_payload(self):
        with self.assertRaises(ImageRejected) as caught:
            sanitize_image_bytes(_png_bytes(), max_bytes=10)
        self.assertEqual(caught.exception.status_code, 413)
        self.assertEqual(caught.exception.code, "PAYLOAD_TOO_LARGE")

    def test_rejects_empty_upload(self):
        with self.assertRaises(ImageRejected) as caught:
            sanitize_image_bytes(b"")
        self.assertEqual(caught.exception.status_code, 400)


class ExifTest(unittest.TestCase):
    def test_strips_gps_and_camera_metadata(self):
        original = _jpeg_with_gps()
        self.assertTrue(Image.open(io.BytesIO(original)).info.get("exif"), "測試素材本身要帶 EXIF")

        cleaned, mime = sanitize_image_bytes(original)
        self.assertEqual(mime, "image/jpeg")
        with Image.open(io.BytesIO(cleaned)) as image:
            self.assertFalse(image.info.get("exif"))
            self.assertIsNone(image._getexif())
        self.assertNotIn(b"TestPhone", cleaned)


class ReadUploadTest(unittest.TestCase):
    def test_stops_reading_once_the_limit_is_passed(self):
        upload = _FakeUpload(b"x" * (2 * 1024 * 1024))
        with self.assertRaises(ImageRejected) as caught:
            asyncio.run(read_upload_within_limit(upload, max_bytes=1024))
        self.assertEqual(caught.exception.status_code, 413)

    def test_rejects_an_empty_stream(self):
        with self.assertRaises(ImageRejected) as caught:
            asyncio.run(read_upload_within_limit(_FakeUpload(b"")))
        self.assertEqual(caught.exception.code, "EMPTY_UPLOAD")

    def test_reads_a_small_file_whole(self):
        data = _png_bytes()
        self.assertEqual(asyncio.run(read_upload_within_limit(_FakeUpload(data))), data)

    def test_sanitize_upload_returns_cleaned_bytes(self):
        data = _png_bytes()
        cleaned, mime = asyncio.run(image_safety.sanitize_upload(_FakeUpload(data)))
        self.assertEqual(mime, "image/png")
        self.assertEqual(cleaned, data)


if __name__ == "__main__":
    unittest.main()
