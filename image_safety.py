"""上傳圖片的共用安全處理（P0-9／P1「圖片與媒體安全」）。

四個服務（Face BASIC／PRO、Render、未來的頭像上傳）本來各自寫一份「檢查大小 →
解碼看看 → 丟給模型」，每一份都少做一兩件事。本程式把該做的事收成一個地方：

1. 分段讀取：超過上限就當場停止，不先把整份塞進記憶體再回頭嫌它太大。
2. magic bytes 白名單：只認 JPEG／PNG／WebP 的實際檔頭，不信 `content_type`
   （那是用戶端說了算的欄位），也不信副檔名。
3. 實際解碼驗證：檔頭對不代表解得開；解不開、或解出來的格式跟檔頭不符
   （偽 MIME）一律擋。
4. 像素上限：先讀檔頭拿尺寸再決定要不要解碼，這是擋解壓縮炸彈的關鍵——
   一張 200KB 的 PNG 可以解成好幾 GB 的點陣圖，等到解完才檢查就已經太遲。
5. 移除 EXIF／GPS：照片的 EXIF 帶著拍攝地點、機身序號、原始時間。這些不該
   跟著臉部照片流到第三方渲染服務，也不該被我們自己存下來。

刻意保留「沒有中繼資料就原封不動回傳」這條捷徑：前端上傳前已經用 canvas 壓過一輪
（canvas 不會帶 EXIF），所以常見情況不需要重新編碼，省下一次無謂的畫質損失。
"""

from __future__ import annotations

import asyncio
import io
import os

from fastapi import HTTPException

from api_errors import error_payload

# ── 限額（可用環境變數覆寫，預設與 Face BASIC 既有設定一致）───────────────────
DEFAULT_MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
DEFAULT_MAX_IMAGE_PIXELS = max(1, int(os.getenv("MAX_IMAGE_PIXELS", "16000000")))
# 解碼的牆鐘上限。像素上限已經把工作量框住了，這條是最後一道保險：真的碰到病態
# 檔案時讓請求有辦法結束，而不是把 worker 卡死。
DEFAULT_DECODE_TIMEOUT_SECONDS = float(os.getenv("IMAGE_DECODE_TIMEOUT_SECONDS", "20"))
_READ_CHUNK_BYTES = 256 * 1024

# 只允許這三種。GIF／BMP／TIFF／SVG 都不在名單內：前端不會送、模型也不需要，
# 多開一種格式就多一組解碼器的攻擊面。
ALLOWED_IMAGE_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}

_MAGIC_PREFIXES = (
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
)


class ImageRejected(HTTPException):
    """圖片被擋下來時丟出的 HTTPException，帶標準 error envelope。"""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(
            status_code=status_code,
            detail=error_payload(code, message, retryable=False),
        )
        self.code = code


def _too_many_pixels(label: str, max_pixels: int) -> "ImageRejected":
    """解壓縮炸彈／超大圖統一回這個 413。四個地方（讀檔頭、尺寸檢查、load、重編碼）
    都會遇到，收成一個 helper 免得四份訊息各自漂移。"""
    return ImageRejected(413, "IMAGE_DIMENSIONS_TOO_LARGE", f"{label}的像素數超過上限 {max_pixels}。")


# 會夾帶中繼資料、需要清掉的 info 鍵。XMP（Adobe 的中繼資料容器）可以塞經緯度，
# 而且分兩種鍵：JPEG 走 Pillow 的 `xmp`，PNG 走 `XML:com.adobe.xmp`——兩個都要認，
# 否則一張「GPS 只藏在 XMP、沒有 EXIF」的 JPEG 會走快速路徑，原封不動送到第三方。
_METADATA_INFO_KEYS = ("exif", "xmp", "comment", "Comment", "XML:com.adobe.xmp", "icc_profile")


def sniff_image_format(data: bytes) -> str | None:
    """只看前幾個位元組判斷格式，回傳 `JPEG`／`PNG`／`WEBP`，都不是就 None。"""
    for prefix, name in _MAGIC_PREFIXES:
        if data.startswith(prefix):
            return name
    # WebP 的檔頭是 RIFF 容器：`RIFF` + 4 bytes 長度 + `WEBP`
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "WEBP"
    return None


async def read_upload_within_limit(
    file,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    label: str = "上傳檔案",
) -> bytes:
    """分段讀取上傳檔案，一超過上限立刻停止並回 413。

    重點是「立刻」：`await file.read()` 會先把整份內容讀進來，等於讓沒通過驗證的
    請求先決定我們要花多少記憶體與磁碟。這裡改成一塊一塊讀，累計超標的當下就
    放棄，後面的位元組完全不碰。
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_READ_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ImageRejected(
                413,
                "PAYLOAD_TOO_LARGE",
                f"{label}過大，上限 {max_bytes // (1024 * 1024)} MB。",
            )
        chunks.append(chunk)
    if total == 0:
        raise ImageRejected(400, "EMPTY_UPLOAD", f"{label}是空的。")
    return b"".join(chunks)


def sanitize_image_bytes(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
    label: str = "上傳檔案",
) -> tuple[bytes, str]:
    """驗證圖片並回傳「去掉中繼資料後的位元組, MIME type」。

    這是同步版本；FastAPI 端點請用 `sanitize_upload`，它會把這段丟到執行緒並套上
    解碼逾時。
    """
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data:
        raise ImageRejected(400, "EMPTY_UPLOAD", f"{label}是空的。")
    if len(data) > max_bytes:
        raise ImageRejected(
            413,
            "PAYLOAD_TOO_LARGE",
            f"{label}過大，上限 {max_bytes // (1024 * 1024)} MB。",
        )

    sniffed = sniff_image_format(data)
    if sniffed is None:
        raise ImageRejected(
            400,
            "UNSUPPORTED_IMAGE_TYPE",
            f"{label}只接受 JPEG／PNG／WebP。",
        )

    # Pillow 自己的解壓縮炸彈警戒線。設成我們的上限，比它預設的 8900 萬像素嚴格，
    # 而且是在「解碼之前」就會擋下來。
    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        try:
            with Image.open(io.BytesIO(data)) as probe:
                declared_format = probe.format
                width, height = probe.size
                has_exif = bool(probe.info.get("exif")) or bool(getattr(probe, "_getexif", lambda: None)())
                # EXIF 之外還有 XMP（JPEG 的 GPS 可能只藏在這裡）與 PNG 的 tEXt／iTXt。
                # 任一存在就代表有中繼資料要清，走重編碼那條路。
                has_metadata = has_exif or any(
                    probe.info.get(key) for key in _METADATA_INFO_KEYS
                ) or bool(getattr(probe, "text", None))
        except UnidentifiedImageError as exc:
            raise ImageRejected(400, "INVALID_IMAGE", f"{label}不是有效的圖片。") from exc
        except Image.DecompressionBombError as exc:
            raise _too_many_pixels(label, max_pixels) from exc
        except OSError as exc:
            raise ImageRejected(400, "INVALID_IMAGE", f"{label}不是有效的圖片。") from exc

        # 偽 MIME：檔頭說是 A、實際解出來是 B。兩者不一致就是刻意包裝過的檔案。
        if declared_format != sniffed:
            raise ImageRejected(
                400,
                "IMAGE_TYPE_MISMATCH",
                f"{label}的檔頭與實際圖片格式不符。",
            )
        if declared_format not in ALLOWED_IMAGE_FORMATS:
            raise ImageRejected(
                400,
                "UNSUPPORTED_IMAGE_TYPE",
                f"{label}只接受 JPEG／PNG／WebP。",
            )
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise _too_many_pixels(label, max_pixels)

        mime = ALLOWED_IMAGE_FORMATS[declared_format]
        if not has_metadata:
            # 沒有中繼資料可清，就別重新編碼——重編一次是白白損失一次畫質。
            # 但仍要確認真的解得開（前面只讀了檔頭）。
            try:
                with Image.open(io.BytesIO(data)) as image:
                    image.load()
            except Image.DecompressionBombError as exc:
                raise _too_many_pixels(label, max_pixels) from exc
            except Exception as exc:  # noqa: BLE001 - Pillow 解碼失敗的例外型別很雜
                raise ImageRejected(400, "INVALID_IMAGE", f"{label}無法解碼。") from exc
            return data, mime

        # 有 EXIF／文字區塊：重新編碼一份乾淨的。
        try:
            with Image.open(io.BytesIO(data)) as image:
                # 先套用 EXIF 方向再丟掉 EXIF。少了這一步，直接刪 EXIF 會讓直式手機
                # 照片變成躺著的——OpenCV 解碼時本來會自己讀 EXIF 轉正，我們把那個
                # 資訊拿掉就得自己補上，否則整張臉是橫的，分析必然失準。
                image = ImageOps.exif_transpose(image)
                image.load()
                buffer = io.BytesIO()
                if declared_format == "PNG":
                    image.save(buffer, format="PNG", optimize=False)
                elif declared_format == "WEBP":
                    image.save(buffer, format="WEBP", quality=95, method=4)
                else:
                    image.convert("RGB").save(
                        buffer, format="JPEG", quality=95, subsampling=0, optimize=True
                    )
        except Image.DecompressionBombError as exc:
            raise _too_many_pixels(label, max_pixels) from exc
        except ImageRejected:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ImageRejected(400, "INVALID_IMAGE", f"{label}無法解碼。") from exc

        cleaned = buffer.getvalue()
        if len(cleaned) > max_bytes:
            # 去中繼資料後反而變大（例如原圖壓得很兇的 PNG）。這不是攻擊，但也不該
            # 讓它突破上限往後送。
            raise ImageRejected(
                413,
                "PAYLOAD_TOO_LARGE",
                f"{label}過大，上限 {max_bytes // (1024 * 1024)} MB。",
            )
        return cleaned, mime
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit


async def sanitize_upload(
    file,
    *,
    max_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
    max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
    timeout_seconds: float = DEFAULT_DECODE_TIMEOUT_SECONDS,
    label: str = "上傳檔案",
) -> tuple[bytes, str]:
    """FastAPI 端點用的一站式入口：分段讀取 → 驗證 → 去中繼資料。

    解碼跑在執行緒裡並套 `wait_for`：逾時的話請求會拿到 504，事件迴圈不會被 CPU
    密集的解碼卡住。（`wait_for` 無法中止已經在跑的執行緒，所以真正把工作量框住的
    仍是像素上限；這條逾時是讓「卡住」變成「回錯誤」的最後保險。）
    """
    data = await read_upload_within_limit(file, max_bytes=max_bytes, label=label)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                sanitize_image_bytes,
                data,
                max_bytes=max_bytes,
                max_pixels=max_pixels,
                label=label,
            ),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        raise ImageRejected(
            504,
            "IMAGE_DECODE_TIMEOUT",
            f"{label}解碼逾時，請改用較小的圖片。",
        ) from exc
