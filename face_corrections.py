"""修正快取：同一張臉再上傳時，套用這張臉舊版被修正過的答案。

用途

模型是靜態分類器，同一張圖永遠回同一個答案——這是必要的，否則無法重測、無法比較分數。
但對使用者來說，「我明明改過了，下次上傳還是同一個錯答案」等於他的回饋沒有意義。
這一層就是補那個落差：模型不變，但這張臉的顯示結果會記住使用者的修正。

它守住的那條線

套用修正之後，畫面顯示的是使用者的答案。如果回饋面板接著把那個值當成「模型的判斷」
送回 `face_feedback`，訓練資料就變成模型在確認自己——集合會慢慢被自我循環的假資料
填滿，而且從外面完全看不出來，重訓分數會憑空變好。

所以分析結果同時帶兩份：

  result[部位]              套用修正後的值（使用者看到的）
  result["_modelRaw"]       模型的原始輸出（回饋一律回報這一份）

`face_feedback` 存的永遠是原始那份，訓練訊號不會被自己污染。

代價（設計時就知道，不是疏漏）

- 線上準確率不能再從使用者看到的結果推估：他看到的可能是快取，不是模型。
  要量模型真實表現，看 `_modelRaw` 或直接跑離線評估。
- 要存影像雜湊：SHA-256，不可逆，不是影像本身；但它仍是一個可用來辨識
  「同一張照片又出現了」的識別碼。
- 想關掉就設 `FACE_CORRECTION_CACHE_ENABLED=0`，模型的原始輸出會直接顯示。
"""
import hashlib
import logging
import os
from datetime import datetime, timezone

import job_store
from analysis_package import canonical_label
from basic_roi_shadow import PART_TO_FIELD

CORRECTIONS_COL = "face_corrections"

# demo 之後想量模型真實表現時可以關掉。預設開著——使用者的回饋要看得到效果。
ENABLED = os.getenv("FACE_CORRECTION_CACHE_ENABLED", "1").strip().lower() not in {"0", "false", "no"}

# 原始模型輸出放在結果裡的哪個 key。底線開頭，跟中文部位名不會撞。
RAW_KEY = "_modelRaw"


def image_hash(contents: bytes) -> str:
    """同一張照片的穩定識別碼。只存雜湊，不存影像。"""
    return hashlib.sha256(contents).hexdigest()


def _cache_key(img_hash: str, owner_id: str | None) -> str | None:
    """Scope a correction to one verified member without exposing that member id."""
    owner = str(owner_id or "").strip()
    if not img_hash or not owner:
        return None
    return hashlib.sha256(f"{owner}:{img_hash}".encode("utf-8")).hexdigest()


def apply(result: dict, img_hash: str, *, owner_id: str | None = None) -> dict:
    """把這張臉舊版的修正套進分析結果，並把模型原始輸出保留在 RAW_KEY。

    找不到修正就只補 RAW_KEY——這樣回饋面板永遠有一份可信的 predicted 可用，
    不必去分辨「這次到底有沒有被快取動過」。
    """
    if not isinstance(result, dict):
        return result

    fields = set(PART_TO_FIELD.values())
    raw = {k: v for k, v in result.items() if k in fields}
    result[RAW_KEY] = raw

    key = _cache_key(img_hash, owner_id)
    if not ENABLED or key is None:
        return result

    try:
        doc = job_store.get(CORRECTIONS_COL, key)
    except Exception:
        logging.exception("讀取修正快取失敗 hash=%s，改用模型原始輸出", img_hash[:12])
        return result

    corrections = (doc or {}).get("corrections") or {}
    for field, value in corrections.items():
        if field in fields and value:
            # 正規化成現行分類表的名稱。這裡存的是使用者當初送出時的標籤，
            # 而分類表後來合併過（M型唇→花瓣唇、杏仁眼/桃花眼→桃杏眼…）。
            # 不換的話，一個已經不存在的類別會被寫進結果，然後一路流到
            # 建議 prompt 與渲染 prompt——那些對照表只認得現行類別，
            # 查不到就整句略過，不報錯（見發展歷程規格書 §7.8）。
            result[field] = canonical_label(value)
    return result


def remember(img_hash: str, corrections: dict, *, owner_id: str | None = None) -> None:
    """記住這張臉的修正；修正被收回（空的）就刪掉整筆。

    刪除而不是留空：留著一筆空的修正，下次讀到會以為「這張臉被確認過是對的」，
    但實際上使用者只是把答案改了回去。
    """
    key = _cache_key(img_hash, owner_id)
    if not ENABLED or key is None:
        return
    fields = set(PART_TO_FIELD.values())
    clean = {k: v for k, v in (corrections or {}).items() if k in fields and v}
    try:
        if not clean:
            job_store.delete(CORRECTIONS_COL, key)
            return
        job_store.create(CORRECTIONS_COL, key, {
            "imageHash": img_hash,
            "corrections": clean,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        # 快取寫不進去不該讓回饋整支失敗——face_feedback 那一筆才是要留的訓練資料。
        logging.exception("寫入修正快取失敗 hash=%s", img_hash[:12])
