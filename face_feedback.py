"""五官判斷回饋：收下使用者對模型輸出的修正，留給重訓用。

前端那份回饋選項本來就是照 `models/basic_features_roi/*_classes.json` 排的，所以每一筆
修正都是已經對齊模型類別的人工標註——正是 issue #24 缺的那種資料。該 issue 的表裡
眼型只有 603 張、macro 0.387，而眼型也是使用者最看得出來不對、最會動手去改的一項。

兩個設計決定，都寫在這裡免得日後有人以為是隨手寫的：

1. 存進獨立集合，不寫回 job。 job 一小時就會被 `FACE_JOB_RETENTION_SECONDS` 清掉，
   標註卻要活到下一次重訓。綁在 job 上等於一小時後全部消失。

2. 只收類別字串，永遠不碰照片。 前端在畫面上就是這樣對使用者說的
   （「這一步不會上傳你的照片，只送出判斷結果與你的修正」），這裡必須守住同一句話。
   日後若重訓真的需要影像，那要另外設計並重新取得同意，不能從這條路悄悄加進來。
"""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Header, HTTPException, Query
from pydantic import BaseModel, Field

import face_corrections
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

    讀失敗就回空的：驗證會因此擋掉那個部位的全部修正，而不是放行全部。
    這個端點的產物是訓練資料，寧可少收一筆，不要收進一筆不知道哪來的標籤。

    失敗不快取。 只有全部部位都讀成功才存起來——把失敗記住的話，一次暫時性的
    讀取錯誤就會讓端點在整個 process 生命週期都拒絕所有修正，而且從外面看不出原因。
    """
    global _allowed_cache
    if _allowed_cache is not None:
        return _allowed_cache

    table: dict[str, set[str]] = {}
    complete = True
    for part, field in PART_TO_FIELD.items():
        path = MODEL_DIR / f"{part}_classes.json"
        try:
            table[field] = set(json.loads(path.read_text(encoding="utf-8"))["classes"])
        except Exception:
            logging.exception("讀不到分類表 %s，這個部位的修正會被擋下", path)
            table[field] = set()
            complete = False
    if complete:
        _allowed_cache = table
    return table


def validate(corrections: dict) -> None:
    """擋掉不是出自目前分類表的東西。

    髒標籤的代價不是「多一筆沒用的資料」，而是重訓時的分數變得不可信——
    你會分不出模型是真的變差，還是訓練集裡混進了模型沒有的類別。
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
    """存下一筆修正，回傳文件 id。沒有修正時刪掉既有紀錄並回 None。

    兩種情況會走到「沒有修正」：使用者按了「判斷正確」（confirmed），或是他把舊版改過的
    欄位又改了回去（corrections 變空）。兩者都代表「模型這次是對的」。

    必須刪除，不能只是不寫。 使用者改完送出、再改回判斷正確重送時，如果這裡只是
    早退，那筆已經寫進去的錯誤修正就會永遠留在訓練集裡——而且無聲無息。前端寫著
    「已送出，可再修改」，那句話必須在資料層也成立。

    confirmed 的不另存一筆，是產品決定：重訓要的是答錯的那些，全部留著只會被大量
    「模型答對了」塞滿。代價是算不出準確率的分母（總共問了幾次、對了幾次），
    所以這個集合的筆數不能拿來估線上準確率——那是有偏樣本。想要分母就在這裡
    改成也存一筆精簡計數。

    文件 id 用 job_id：同一個 job 重送就覆蓋，不會累積成好幾筆互相矛盾的標註。
    """
    corrections = payload.get("corrections") or {}
    if payload.get("confirmed") or not corrections:
        job_store.delete(FEEDBACK_COL, job_id)
        return None

    validate(corrections)

    predicted = payload.get("predicted") or {}
    fields = allowed_classes()
    doc = {
        # 跟文件 id 一樣用 job_id 衍生。先前每次覆寫都給新的 uuid，等於同一份紀錄在
        # 穩定的 key 底下有一個會變的身分，對得上才怪。
        "feedbackId": f"FB-{job_id}",
        "jobId": job_id,
        "mode": mode,                                  # basic / pro
        "packageId": payload.get("packageId"),
        # predicted 與 corrections 併看就是「模型錯在哪」，兩個都要留。
        "predicted": {k: v for k, v in predicted.items() if k in fields},
        "corrections": corrections,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    job_store.create(FEEDBACK_COL, job_id, doc)
    return doc["feedbackId"]


class FeedbackIn(BaseModel):
    packageId: str | None = None
    predicted: dict = Field(default_factory=dict)
    corrections: dict = Field(default_factory=dict)
    # 前端在送出當下就判定好，不要在這裡用 corrections 是否為空去反推——
    # 語意留在產生它的那一刻，接收端不做推論。
    confirmed: bool = False


def register_route(app, *, mode: str, jobs_collection: str, verify_job_token) -> None:
    """把 POST /v1/face/jobs/{job_id}/feedback 掛到 app 上。

    BASIC 與 PRO 是兩個獨立部署，但這條路由的內容一模一樣。舊版兩邊各抄一份，
    結果註解已經開始分歧（BASIC 的 confirmed 說明多一句、PRO 那份掉了）——
    再放著就會變成邏輯也分歧。job 集合與 token 驗證由呼叫端傳進來，那才是兩邊真正不同的地方。
    """

    @app.post("/v1/face/jobs/{job_id}/feedback", status_code=204)
    async def submit_job_feedback(  # noqa: ANN202  (FastAPI 由裝飾器接手)
        job_id: str,
        payload: FeedbackIn,
        x_job_token: str | None = Header(default=None),
        result_token: str | None = Query(default=None),
    ):
        """收下使用者對這個 job 的五官修正。

        驗證與其他 job 路由同一套：要帶得出建 job 時發的 token，才算得上這個 job 的主人。
        少了它，任何人都能對別人的 jobId 灌標籤，而這批資料是要拿去重訓的。
        """
        job = job_store.get(jobs_collection, job_id)
        if not job:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "JOB_NOT_FOUND", "message": "找不到 job"}},
            )
        verify_job_token(job, x_job_token=x_job_token, result_token=result_token)
        try:
            data = payload.model_dump()
            save(mode, job_id, data)
            # 記到這張臉上，下次同一張照片就會顯示使用者的答案。
            # 這一份是「給人看的」，跟上面存進 face_feedback 的訓練資料是兩回事：
            # 前者可以被覆蓋、被收回，後者是模型錯在哪的紀錄。
            face_corrections.remember(
                job.get("imageHash"),
                data.get("corrections"),
                owner_id=job.get("ownerId"),
            )
        except FeedbackRejected as exc:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "INVALID_FEEDBACK", "message": str(exc)}},
            )
