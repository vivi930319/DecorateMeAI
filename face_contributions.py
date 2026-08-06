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


def _client():
    from google.cloud import storage

    return storage.Client()


def _decode(image_bytes: bytes):
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("無法解碼影像")
    return frame


def store(job_id: str, image_bytes: bytes, corrections: dict, *,
          owner_id: str | None, mode: str, field_to_part: dict) -> int:
    """把使用者修正過的部位裁切存起來，回傳存了幾張。

    只處理**被修正的部位**：使用者沒改的代表模型答對了，那些不缺樣本。
    這也讓儲存量跟資訊量成正比——存的每一張都是模型答錯的例子。

    任何一步失敗都只記 log 不拋出。這是加值功能，不能讓使用者的修正因此送不出去。
    """
    if not ENABLED:
        return 0
    if not corrections or not image_bytes:
        return 0
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        logging.warning("貢獻樣本過大，略過 job_id=%s size=%d", job_id, len(image_bytes))
        return 0

    try:
        from Face_analyzer_BASIC import FaceAnalyzer

        frame = _decode(image_bytes)
        analyzer = FaceAnalyzer(image_bytes, strict_angle=False, require_insight=False)
        points = np.array([analyzer._pt(i) for i in range(len(analyzer.lm))])
    except Exception:
        logging.exception("貢獻樣本取 landmark 失敗 job_id=%s", job_id)
        return 0

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
        if not part or part not in face_roi.ROI_SPECS:
            continue
        try:
            crop = face_roi.crop_roi(frame, points, part)
            ok, buf = cv2.imencode(".png", crop)
            if not ok:
                continue
            # 路徑本身就帶著「哪個規格、哪個部位、標成哪一類」，不必開檔就分得出來。
            blob = bucket.blob(f"{PREFIX}/{version}/{part}/{label}/{job_id}.png")
            blob.metadata = {
                "jobId": job_id,
                "mode": mode,
                "part": part,
                "label": label,
                "roiSpecsVersion": version,
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
