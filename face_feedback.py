"""五官判斷回饋：收下使用者對模型輸出的修正，留給重訓用。

前端那份回饋選項本來就是照 `models/basic_features_roi/*_classes.json` 排的，所以每一筆
修正都是**已經對齊模型類別的人工標註**——正是 issue #24 缺的那種資料。該 issue 的表裡
眼型只有 603 張、macro 0.387，而眼型也是使用者最看得出來不對、最會動手去改的一項。

兩個設計決定，都寫在這裡免得日後有人以為是隨手寫的：

1. **存進獨立集合，不寫回 job。** job 一小時就會被 `FACE_JOB_RETENTION_SECONDS` 清掉，
   標註卻要活到下一次重訓。綁在 job 上等於一小時後全部消失。

2. **只收類別字串，永遠不碰照片。** 前端在畫面上就是這樣對使用者說的
   （「這一步不會上傳你的照片，只送出判斷結果與你的修正」），這裡必須守住同一句話。
   日後若重訓真的需要影像，那要另外設計並重新取得同意，不能從這條路悄悄加進來。
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import job_store
from basic_roi_shadow import PART_TO_FIELD

# 跟 basic_roi_shadow 讀同一個目錄。類別檔隨每次重訓更新，這裡不另外抄一份清單——
# 抄了就會有「模型已經合併類別、驗證還在擋舊類別」這種對不上的情況。
MODEL_DIR = Path(os.getenv("ROI_MODEL_DIR", "models/basic_features_roi"))

FEEDBACK_COL = "face_feedback"

# 單筆修正最多五個部位，值就是類別字串。設上限是因為這是公開端點，
# 沒有上限就等於讓人塞任意大小的 JSON 進資料庫。
_MAX_FIELDS = len(PART_TO_FIELD)
_MAX_VALUE_LEN = 40

_allowed_cache: dict[str, set[str]] | None = None


class FeedbackRejected(ValueError):
    """回饋內容不合法。訊息會直接回給呼叫端，所以要寫成看得懂的話。"""


def allowed_classes() -> dict[str, set[str]]:
    """中文欄位名 -> 該部位目前的合法類別集合。

    讀失敗就回空的：驗證會因此擋掉全部修正，而不是放行全部。
    這個端點的產物是訓練資料，寧可少收一筆，不要收進一筆不知道哪來的標籤。
    """
    global _allowed_cache
    if _allowed_cache is not None:
        return _allowed_cache

    table: dict[str, set[str]] = {}
    for part, field in PART_TO_FIELD.items():
        path = MODEL_DIR / f"{part}_classes.json"
        try:
            table[field] = set(json.loads(path.read_text(encoding="utf-8"))["classes"])
        except Exception:
            table[field] = set()
    _allowed_cache = table
    return table


def validate(corrections: dict) -> None:
    """擋掉不是出自目前分類表的東西。

    髒標籤的代價不是「多一筆沒用的資料」，而是重訓時的分數變得不可信——
    你會分不出模型是真的變差，還是訓練集裡混進了模型根本沒有的類別。
    """
    if not isinstance(corrections, dict):
        raise FeedbackRejected("corrections 必須是物件")
    if len(corrections) > _MAX_FIELDS:
        raise FeedbackRejected(f"corrections 最多 {_MAX_FIELDS} 個部位")

    table = allowed_classes()
    for field, value in corrections.items():
        if field not in table:
            raise FeedbackRejected(f"不認識的部位：{field}")
        if not isinstance(value, str) or len(value) > _MAX_VALUE_LEN:
            raise FeedbackRejected(f"{field} 的值格式不正確")
        if value not in table[field]:
            # 這通常不是使用者亂填，而是前端選項與類別檔沒跟上同一次合併。
            # 訊息要講得夠具體，看 log 的人才知道該去對哪一邊。
            raise FeedbackRejected(f"{field} 沒有「{value}」這個類別，前端選項可能與模型分類表不同步")


def save(mode: str, job_id: str, payload: dict) -> str | None:
    """存下一筆修正，回傳文件 id；`confirmed` 的那些不存，回 None。

    使用者說判斷正確的紀錄核對完就沒有保存價值——重訓要的是答錯的那些。
    不存也代表**算不出準確率的分母**（總共問了幾次、對了幾次）。目前依產品決定
    以省空間為優先；日後想要那個分母，就在這裡改成也存一筆精簡的計數。

    文件 id 用 job_id：使用者可以改完再改（前端寫著「已送出，可再修改」），
    同一個 job 重送就覆蓋，不會累積成好幾筆互相矛盾的標註。
    """
    corrections = payload.get("corrections") or {}
    if payload.get("confirmed") or not corrections:
        return None

    validate(corrections)

    predicted = payload.get("predicted") or {}
    doc = {
        "feedbackId": f"FB-{uuid.uuid4().hex[:12]}",
        "jobId": job_id,
        "mode": mode,                                  # basic / pro
        "packageId": payload.get("packageId"),
        # predicted 與 corrections 併看就是「模型錯在哪」，兩個都要留。
        "predicted": {k: v for k, v in predicted.items() if k in allowed_classes()},
        "corrections": corrections,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    job_store.create(FEEDBACK_COL, job_id, doc)
    return doc["feedbackId"]
