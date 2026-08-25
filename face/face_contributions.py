"""使用者同意提供的訓練樣本：只留部位裁切，不留原圖。

為什麼要有這個
--------------
線上信任分數（`tools/online_trust_score.py`）只告訴你「哪個部位不準」，
但要改善模型需要**樣本**，而系統刻意不保存使用者的照片——分析用的 bytes
用完就釋放，Firestore 裡只有 SHA-256 雜湊。所以修正的資訊價值原本是浪費掉的：
知道「這張應該是圓眼」，卻拿不回那張照片。

這個模組補上那一段，但守住三條線：

1. **只在使用者明確同意時才存。** 沒勾選就什麼都不寫——不是先存起來再判斷，
   是根本不會產生。照片由前端在送出修正時一併重傳，同意才傳。
2. **只存部位 ROI，不存原圖。** 訓練本來吃的就是 96×96／128×128 的裁切
   （見 face_roi.ROI_SPECS），所以這不是縮水的資料，是訓練實際用的形式。
3. **存得下就刪得掉。** 每筆帶 ownerId，會員刪除時要能一併清除。

⚠️ ROI 仍然是臉部資料
---------------------
「只存裁切」降低可辨識性，但沒有消除它。特別是：

  face_shape  臉部外框 + 8% 邊距 → **實質上就是一張低解析度的臉照**
  eye/brow    雙側合併 + 35% 邊距 → 帶到相當範圍的眼周

所以這些一律當臉部資料處理：私有 bucket、明確同意、可刪除、有保留期限。
不要因為「只是裁切」就降低保護標準。

⚠️ 裁切規格改變就對不起來
-------------------------
存的是已裁切的影像，原圖不留，所以 `ROI_SPECS` 改了之後這些樣本**無法重裁**。
每筆都記 `face_roi.specs_version()`，之後才分得出哪些是舊規格。
混用而不自知，就是 identity_map 那種靜默失效。
"""
import base64
import binascii
import io
import json
import logging
import os
from datetime import datetime, timezone

import cv2
import numpy as np

import face_roi

# 私有 bucket，跟訓練資料集同一個，但另開前綴以便區分來源與套用不同保留政策。
BUCKET = os.getenv("FACE_CONTRIB_BUCKET", "decorate-me-datasets")
PREFIX = os.getenv("FACE_CONTRIB_PREFIX", "user_contributed")

# 沒設就整個功能關閉。預設關閉是刻意的：這是會存臉部資料的路徑，
# 應該由部署時明確開啟，而不是因為程式碼上線就自動生效。
ENABLED = os.getenv("FACE_CONTRIB_ENABLED", "0") == "1"

_MAX_IMAGE_BYTES = 12 * 1024 * 1024



def data_url_to_image_bytes(data_url: str) -> bytes:
    """把 data URL 拆成驗過、去掉 EXIF 的影像位元組。

    刻意不 import replicate_render 的同名函式——那是渲染服務的模組，不在 face 映像裡。
    第一版就是這樣寫的，本機測全過（檔案都在磁碟上），部署後直接 ModuleNotFoundError，
    而且因為失敗被吞掉，只有翻 Cloud Run 日誌才看得出來。三份白名單那條註解講的
    就是這種錯：本機跟映像的可見範圍不一樣。

    驗證沿用 `image_safety`（face 映像本來就有）：magic bytes 白名單、偽 MIME、
    解壓縮炸彈、移除中繼資料。這條路徑吃的是使用者上傳的影像，驗證不能省——
    而且我們要存下來，EXIF 裡的拍攝地點與機身序號更不該留著。
    """
    from image_safety import ImageRejected, sanitize_image_bytes

    if not data_url.startswith("data:") or ";base64," not in data_url:
        raise ValueError("需要 base64 data URL")
    header, encoded = data_url.split(",", 1)
    content_type = (header[5:].split(";", 1)[0] or "image/png").lower()
    if content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise ValueError("只接受 JPEG／PNG／WebP")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("data URL 的 base64 不合法") from exc
    try:
        cleaned, detected = sanitize_image_bytes(
            raw, max_bytes=_MAX_IMAGE_BYTES, label="貢獻樣本")
    except ImageRejected as exc:
        raise ValueError(exc.detail["error"]["message"]) from exc
    if detected != content_type:
        raise ValueError("宣告的格式與實際內容不符")
    return cleaned


def _client():
    from google.cloud import storage

    return storage.Client()


def _decode(image_bytes: bytes):
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("無法解碼影像")
    return frame


def store(job_id: str, image_bytes: bytes | None, corrections: dict, *,
          owner_id: str | None, mode: str, field_to_part: dict,
          side_image_bytes: bytes | None = None,
          whole_image_parts: dict[str, str] | None = None) -> int:
    """把使用者修正過的部位存起來，回傳存了幾張。

    只處理**被修正的部位**：使用者沒改的代表模型答對了，那些不缺樣本。
    這也讓儲存量跟資訊量成正比——存的每一張都是模型答錯的例子。

    兩種樣本，來源與形式都不同
    --------------------------
    ROI 部位（眉／眼／鼻／嘴）    正面照 → landmark → 裁切成訓練用的 96²
    whole_image_parts             整張圖，不裁切。`{部位: "front" | "side"}` 指定用哪張照片

        nose_shape_side → side   側臉鼻型模型線上吃的就是整張側臉圖（側臉 FaceMesh
                                 只認得 73.5%，失敗率還依類別偏斜，裁切會扭曲類別分布）
        face_shape      → front  臉型要看整張臉的長寬比例與下顎輪廓。128² 的裁切
                                 事後**無法重裁**（原圖不留），而臉型正是最可能需要
                                 改裁切範圍的一項——留原圖才留得住重做的可能

    但整張圖的可辨識性比 ROI 高得多——**它就是一張人臉照片**。所以這些部位只在
    使用者對著「會上傳完整照片」那句話明確同意時才會送到這裡；
    同意文案與這個參數必須一起改，不能只改一邊。

    任何一步失敗都只記 log 不拋出。這是加值功能，不能讓使用者的修正因此送不出去。
    """
    if not ENABLED:
        return 0
    if not corrections:
        return 0
    whole_image_parts = whole_image_parts or {}
    sources = {"front": image_bytes, "side": side_image_bytes}
    for label, payload in (("正面照", image_bytes), ("側面照", side_image_bytes)):
        if payload and len(payload) > _MAX_IMAGE_BYTES:
            logging.warning("貢獻樣本過大，略過 job_id=%s %s size=%d",
                            job_id, label, len(payload))
            return 0

    # landmark 只有 ROI 裁切需要，而且只在正面照上算。整張圖的部位（側臉鼻型）
    # 不需要它——先前是無條件先算 landmark，於是「只修正了側臉鼻型、沒有正面照」
    # 的情況會在這裡直接 return，樣本一張都存不到。
    frame = None
    points = None
    needs_roi = any(field_to_part.get(f) not in whole_image_parts for f in corrections)
    if needs_roi and image_bytes:
        try:
            from Face_analyzer_BASIC import FaceAnalyzer

            frame = _decode(image_bytes)
            analyzer = FaceAnalyzer(image_bytes, strict_angle=False, require_insight=False)
            points = np.array([analyzer._pt(i) for i in range(len(analyzer.lm))])
        except Exception:
            logging.exception("貢獻樣本取 landmark 失敗 job_id=%s", job_id)

    version = face_roi.specs_version()
    stamp = datetime.now(timezone.utc)
    saved = 0
    try:
        bucket = _client().bucket(BUCKET)
    except Exception:
        logging.exception("連不上 GCS，貢獻樣本略過 job_id=%s", job_id)
        return 0

    for field, label in corrections.items():
        part = field_to_part.get(field)
        if not part:
            continue
        whole_source = whole_image_parts.get(part)
        whole = whole_source is not None
        if not whole and (part not in face_roi.ROI_SPECS or points is None):
            continue
        raw_bytes = sources.get(whole_source) if whole else None
        if whole and not raw_bytes:
            continue
        try:
            if whole:
                # 不裁切、不縮放：線上推論自己會縮到模型的輸入尺寸，
                # 這裡留原圖才有機會在換輸入尺寸或改裁切規格後重用。
                image = _decode(raw_bytes)
            else:
                image = face_roi.crop_roi(frame, points, part)
            ok, buf = cv2.imencode(".png", image)
            if not ok:
                continue
            # 路徑本身就帶著「哪個規格、哪個部位、標成哪一類」，不必開檔就分得出來。
            blob = bucket.blob(f"{PREFIX}/{version}/{part}/{label}/{job_id}.png")
            blob.metadata = {
                "jobId": job_id,
                "mode": mode,
                "part": part,
                "label": label,
                # 整張圖的樣本不受 ROI_SPECS 影響，標成 whole_image 免得日後
                # 被當成某個版本的裁切去重裁——它根本沒有裁切規格可言。
                "roiSpecsVersion": "whole_image" if whole else version,
                # 可辨識性差很多，保留政策與審查標準可能不同，要能一眼分出來。
                "sampleForm": f"whole_{whole_source}_image" if whole else "roi_crop",
                # 刪除會員時要靠這個找到並清除。沒有它就變成刪不掉的臉部資料。
                "ownerId": str(owner_id or ""),
                "contributedAt": stamp.isoformat(),
            }
            blob.upload_from_string(buf.tobytes(), content_type="image/png")
            saved += 1
        except Exception:
            logging.exception("貢獻樣本上傳失敗 job_id=%s part=%s", job_id, part)

    if saved:
        logging.info("使用者貢獻 %d 張 ROI（規格 %s）job_id=%s", saved, version, job_id)
    return saved


def load_for_job(job_id: str, *, max_bytes: int = 2_000_000) -> list[dict]:
    """取出某一次分析留下的樣本影像，給管理端覆核時對照用。

    為什麼需要看圖：覆核的人要判斷「使用者說這是落尾眉」對不對，光看兩個詞
    是判斷不了的——眉型、唇型這種本來就要看到形狀才有辦法談。看不到圖的覆核
    等於在猜，那比不覆核更糟，因為它會給出「已經有人看過」的假象。

    回傳 data URL 而不是簽名網址：這些是臉部影像，簽名網址一旦產生就是一段時間內
    誰拿到誰能看，而且會離開我們的存取控制。走 data URL 的話，每一次讀取都還是
    經過端點自己的管理員驗證。圖是部位 ROI（96×96 PNG，通常 5~20KB），
    一次分析最多五個部位，總量比一張商品圖還小。

    max_bytes 是保險絲：臉型與側臉鼻型存的是整張照片而不是 ROI 裁切
    （見 store 的 whole_image_parts），單張可能到幾百 KB。超過就跳過那一張
    並在結果裡註明，不要讓一次覆核請求拖著幾 MB 回應。
    """
    client = _client()
    if client is None:
        return []
    want = f"{job_id}.png"
    out: list[dict] = []
    total = 0
    try:
        # 用前綴掃描而不是猜路徑：路徑裡有 ROI 規格版本（見 store），
        # 那個版本會隨裁切規格改變，寫死在這裡遲早對不上。
        for blob in client.list_blobs(BUCKET, prefix=f"{PREFIX}/"):
            if not blob.name.endswith(want):
                continue
            parts = blob.name.split("/")
            if len(parts) < 4:
                continue
            size = int(blob.size or 0)
            if total + size > max_bytes:
                out.append({"part": parts[-3], "label": parts[-2],
                            "skipped": "圖片太大，未載入"})
                continue
            data = blob.download_as_bytes()
            total += len(data)
            out.append({
                "part": parts[-3],
                "label": parts[-2],
                "dataUrl": "data:image/png;base64," + base64.b64encode(data).decode("ascii"),
                "bytes": len(data),
            })
    except Exception:
        logging.exception("讀取貢獻樣本失敗 job_id=%s", job_id)
        return []
    return out


def delete_for_owner(owner_id: str) -> int:
    """刪掉某個會員貢獻的全部樣本，回傳刪除數。會員刪除流程要呼叫這個。

    用 metadata 過濾而不是路徑：路徑刻意不含 ownerId（那會讓 bucket 的檔名洩漏
    誰貢獻了什麼），所以只能逐一檢查 metadata。樣本量不大，這個代價可以接受。
    """
    if not owner_id:
        return 0
    removed = 0
    try:
        client = _client()
        for blob in client.list_blobs(BUCKET, prefix=f"{PREFIX}/"):
            if (blob.metadata or {}).get("ownerId") == str(owner_id):
                blob.delete()
                removed += 1
    except Exception:
        logging.exception("刪除會員貢獻樣本失敗 owner=%s", owner_id)
    return removed
