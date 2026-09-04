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

import face_contributions
import face_corrections
import job_store
from basic_roi_shadow import PART_TO_FIELD

# 跟 basic_roi_shadow 讀同一個目錄。類別檔隨每次重訓更新，這裡不另外抄一份清單——
# 抄了就會有「模型已經合併類別、驗證還在擋舊類別」這種對不上的情況。
MODEL_DIR = Path(os.getenv("ROI_MODEL_DIR", "models/basic_features_roi"))

# PRO 的側臉鼻型是**另一顆模型、另一套分類法**（塌鼻／直挺鼻／翹鼻／蒜頭鼻／駝峰鼻），
# 跟 BASIC 的正面鼻型（寬鼻／標準鼻）不共用類別，也不共用模型目錄。
#
# 所以它必須是獨立欄位，不能借用「鼻型」：借用的話，使用者把「駝峰鼻」送進來會被
# validate() 擋掉（不在 BASIC 分類表裡），而且就算放行，重訓時兩套標籤混在同一欄
# 會直接汙染 BASIC 的訓練集——那正是 validate() 存在的理由。
PRO_MODEL_DIR = Path(os.getenv("PRO_MODEL_DIR", "models/pro_nose_side"))
PRO_NOSE_FIELD = "側臉鼻型"
PRO_NOSE_PART = "nose_shape_side"
PRO_NOSE_CLASSES_FILE = "nose_shape_side_classes.json"

FEEDBACK_COL = "face_feedback"

# 管理員對一筆修正能下的判斷。
#
# 只有 accepted 會被 training/import_feedback_samples.py 收進訓練集。沒有這個欄位的
# 舊文件視同 pending：欄位是 2026-08-24 才加的，在那之前的 108 筆沒有人覆核過，
# 把它們當成已採用等於讓「還沒做的事」看起來像做過了。
# accepted   使用者說的對，照用
# rejected   使用者說的不對，這個部位不進訓練集
# corrected  兩邊都不對，管理員給第三個答案（標籤存在 reviewLabels）
#
# corrected 是 2026-08-24 加的：管理員看得到影像，而使用者是憑印象改的，
# 所以很可能兩個都不對。少了這一個選項，遇到這種情況只能整筆退回，
# 等於把一張有影像、有人看過的樣本丟掉——那正是最貴的一種資料。
REVIEW_DECISIONS = {"accepted", "rejected", "corrected"}
REVIEW_PENDING = "pending"

# 線上準確率的量測用集合。跟 FEEDBACK_COL 分開，理由見 save() 的說明：
# 那一個是**訓練資料**，只收模型答錯的；這一個是**評分紀錄**，答對答錯都收，
# 但只存結果不存修正內容。混在一起的話，重訓時會被大量「模型答對了」淹沒。
EVAL_COL = "face_eval_events"

# 單筆修正最多五個部位，值就是類別字串。設上限是因為這是公開端點，
# 沒有上限就等於讓人塞任意大小的 JSON 進資料庫。
_MAX_FIELDS = len(PART_TO_FIELD) + 1   # +1 = PRO 的側臉鼻型
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
    sources = [(field, MODEL_DIR / f"{part}_classes.json")
               for part, field in PART_TO_FIELD.items()]
    # PRO 的側臉鼻型分類表在另一個模型目錄。BASIC 服務沒有這個目錄是正常的
    # （它根本沒有這顆模型），讀不到就讓這個欄位維持空集合＝擋下該欄位的修正，
    # 不影響其他五個部位——所以它不算 complete 的失敗條件。
    sources.append((PRO_NOSE_FIELD, PRO_MODEL_DIR / PRO_NOSE_CLASSES_FILE))

    for field, path in sources:
        try:
            table[field] = set(json.loads(path.read_text(encoding="utf-8"))["classes"])
        except Exception:
            if field == PRO_NOSE_FIELD:
                # 只記一行，不印堆疊：BASIC 服務每次啟動都會走到這裡。
                logging.info("沒有 %s，%s 的修正會被擋下（BASIC 服務屬正常）",
                             path, PRO_NOSE_FIELD)
                table[field] = set()
                continue
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


def _model_version() -> str:
    """這次判斷是哪一版模型做的。

    沒有這個欄位，線上分數就只能算出「所有時間、所有版本混在一起的一個數字」——
    而換模型之後最想知道的正是「換了之後有沒有比較好」，那需要把事件分成兩組。
    2026-08-26 查到既有的 126 筆全都沒有版本，所以那個比較目前做不了。

    版本取自 tools/face_models_manifest.json，那是部署時打包進映像、
    且 download_face_models.py 會逐檔驗證 sha256 的同一份清單，所以它跟映像裡的
    模型檔是對得起來的。只讀一次就快取：這是每次回饋都會走到的路徑。
    """
    if _MODEL_VERSION_CACHE["value"] is None:
        version = ""
        try:
            # 兩種佈局都要找得到：
            #   本機   <repo>/face/face_feedback.py  → 清單在 <repo>/tools/
            #   映像   /app/face_feedback.py          → 清單在 /app/tools/
            # Dockerfile 把 face/ 底下的檔案平鋪進 /app，所以層級少一層。
            # 寫死其中一種，另一種就會安靜地留下空版本——而空版本要到分析線上分數
            # 的時候才會發現，那時候資料已經收了幾個月。
            here = Path(__file__).resolve().parent
            candidates = [here / "tools" / "face_models_manifest.json",
                          here.parent / "tools" / "face_models_manifest.json"]
            manifest = next((p for p in candidates if p.is_file()), None)
            if manifest is None:
                raise FileNotFoundError(f"找不到模型清單，找過：{[str(p) for p in candidates]}")
            version = str(json.loads(manifest.read_text(encoding="utf-8")).get("version") or "")
        except Exception:
            # 讀不到就留空字串，不要讓量測把回饋弄壞。空字串本身也是有意義的：
            # 它代表「這一筆不知道是哪一版」，分組時要排除而不是猜。
            logging.exception("讀取模型版本失敗，線上評分事件將不帶版本")
        _MODEL_VERSION_CACHE["value"] = version
    return str(_MODEL_VERSION_CACHE["value"])


_MODEL_VERSION_CACHE: dict[str, str | None] = {"value": None}


def _record_eval_event(mode: str, job_id: str, predicted: dict, corrections: dict) -> None:
    """記一筆「模型這次答得如何」，給線上信任分數用。

    這是線上量測的**分母**來源。線下的固定保留集量的是「模型在我們蒐集的素材上
    學得如何」，這裡量的是「模型對真實使用者的照片管不管用」——兩批資料的分布不同
    （影劇截圖 vs 手機自拍），所以兩個數字要分開看，它們的差距本身就是結論。

    只記結果不記內容：哪些部位使用者接受、哪些被改。不存修正後的值（那在
    FEEDBACK_COL 裡，是訓練資料），不存 packageId 也不存任何身分。

    文件 id 用 job_id，跟 FEEDBACK_COL 一致：同一個 job 重送就覆蓋。使用者改完
    又改回去時不會被算成兩次，否則分母會被同一個人重送灌大。

    寫失敗不能影響使用者。 這是量測，不是功能——回饋已經收下了，不該因為
    統計寫不進去而讓使用者看到錯誤、再送一次。
    """
    try:
        fields = allowed_classes()
        asked = [f for f in fields if f in predicted]
        if not asked:
            return
        changed = [f for f in asked if f in corrections]
        job_store.create(EVAL_COL, job_id, {
            "jobId": job_id,
            "mode": mode,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            # 哪一版模型做的判斷。要回答「換了模型之後有沒有變好」就得靠它分組——
            # 少了它，所有事件混在一起，只算得出一個跨版本的平均值。
            "modelVersion": _model_version(),
            # 使用者接受的部位＝模型答對；被改的＝答錯。兩者相加就是分母。
            "agreed": [f for f in asked if f not in corrections],
            "corrected": changed,
            # 模型當時說什麼。留著才能算出「哪一類最常被改成哪一類」的混淆矩陣，
            # 那比單一準確率更有用——它會指出是哪兩類分不開。
            "predicted": {f: predicted[f] for f in asked},
        })
    except Exception:
        logging.exception("寫入線上評分紀錄失敗 job_id=%s（不影響使用者的回饋）", job_id)


def _store_contribution(mode: str, job_id: str, payload: dict, corrections: dict,
                        owner_id: str | None) -> bool:
    """使用者同意時，保存被修正部位的 ROI 裁切當訓練樣本。

    三個條件缺一不可：明確同意、有修正、有照片。少任何一個就什麼都不存——
    這裡刻意不做「合理推測」，同意這件事不能靠推論。

    照片由前端在同意時一併重傳（分析當下的 bytes 早就釋放了）。不同意就不會傳，
    所以「未同意不保存」是結構保證，不是後端自律。

    owner_id 一定要從 **job 文件**取，不能從請求 payload。payload 是客戶端送的，
    讓它自稱擁有者等於誰都能把樣本掛到別人名下——而那個欄位正是刪除時的依據。
    第一版寫成 payload.get("ownerId")，而 FeedbackIn 根本沒有那個欄位，
    所以每一筆的 ownerId 都是空的：存得下、刪不掉。

    失敗只記 log。使用者的修正已經收下了，不該因為加值功能失敗而讓他重送一次。
    """
    if not payload.get("allowTrainingUse") or not corrections:
        return False
    data_url = payload.get("imageDataUrl")
    side_data_url = payload.get("sideImageDataUrl")
    if not data_url and not side_data_url:
        return False

    def _decode(url: str | None, what: str) -> bytes | None:
        if not url:
            return None
        try:
            # 用 face_contributions 自己那支，不要 import replicate_render——
            # 那是渲染服務的模組，face 映像裡沒有（部署後才會發現）。
            return face_contributions.data_url_to_image_bytes(url)
        except Exception:
            logging.exception("貢獻樣本解析影像失敗 job_id=%s（%s）", job_id, what)
            return None

    image_bytes = _decode(data_url, "正面照")
    # 側臉鼻型那顆模型吃的是整張側臉圖，不是 ROI 裁切，所以它要的是**另一張照片**。
    # 沒有側面照時，側臉鼻型的修正就只會留下標籤（進 FEEDBACK_COL），不產生影像樣本。
    side_bytes = _decode(side_data_url, "側面照")
    if image_bytes is None and side_bytes is None:
        return False
    try:
        # store() 回傳的是**實際存了幾張**，一定要看。它在好幾種情況下會回 0 而不拋例外：
        # FACE_CONTRIB_ENABLED 沒開、連不上 GCS、圖太大、landmark 抽不出來所以裁不出 ROI。
        # 早先這裡把回傳值丟掉、一律回 True，於是文件寫著 contributed=true 但 GCS 上
        # 一張都沒有——後台會顯示「看樣本影像」卻打開一片空白，而送訓時那一筆會被算進
        # 批次，等到匯入才發現沒有東西可訓練，整批失敗。
        saved = face_contributions.store(
            job_id, image_bytes, corrections,
            owner_id=owner_id,
            mode=mode,
            field_to_part={
                **{v: k for k, v in PART_TO_FIELD.items()},
                PRO_NOSE_FIELD: PRO_NOSE_PART,
            },
            side_image_bytes=side_bytes,
            # 這兩個部位存整張圖，其餘存 ROI 裁切。臉型用正面照、側臉鼻型用側面照。
            # 臉型之所以不存裁切：它的 ROI 是外框 +8%，本來就接近整張臉，而原圖不留
            # 就永遠無法在改了裁切規格之後重裁——臉型正是最可能要改裁切範圍的一項。
            whole_image_parts={"face_shape": "front", PRO_NOSE_PART: "side"},
        )
    except Exception:
        logging.exception("貢獻樣本保存失敗 job_id=%s", job_id)
        return False
    return saved > 0


def save(mode: str, job_id: str, payload: dict, owner_id: str | None = None) -> str | None:
    """存下一筆修正，回傳文件 id。沒有修正時刪掉既有紀錄並回 None。

    兩種情況會走到「沒有修正」：使用者按了「判斷正確」（confirmed），或是他把舊版改過的
    欄位又改了回去（corrections 變空）。兩者都代表「模型這次是對的」。

    必須刪除，不能只是不寫。 使用者改完送出、再改回判斷正確重送時，如果這裡只是
    早退，那筆已經寫進去的錯誤修正就會永遠留在訓練集裡——而且無聲無息。前端寫著
    「已送出，可再修改」，那句話必須在資料層也成立。

    confirmed 的不另存進 FEEDBACK_COL，是產品決定：重訓要的是答錯的那些，
    全部留著只會被大量「模型答對了」塞滿。

    但那樣就算不出分母（總共問了幾次、對了幾次），FEEDBACK_COL 的筆數因此
    **不能**拿來估線上準確率——那是有偏樣本。所以 2026-08-06 起同時往 EVAL_COL
    寫一筆精簡計數：答對答錯都寫，只記「哪些部位使用者接受、哪些被改」，
    不記修正後的值也不記任何身分。線上信任分數由那個集合算，見
    tools/online_trust_score.py。

    文件 id 用 job_id：同一個 job 重送就覆蓋，不會累積成好幾筆互相矛盾的標註。

    驗證要排在**所有**寫入之前。 這裡原本先寫評分事件、先存貢獻影像，最後才驗
    corrections——於是一個不認識的類別會先被 face_contributions.store() 接去組成
    GCS 物件路徑（``<prefix>/<版本>/<部位>/<類別>/<job_id>.png``，那支自己完全不驗
    類別），然後才回 400。擋下來的請求照樣在訓練集裡留下一個用髒標籤命名的資料夾，
    而 validate() 的存在理由正是不讓那件事發生。回應碼對了、資料卻已經髒了。
    """
    corrections = payload.get("corrections") or {}
    predicted = payload.get("predicted") or {}
    confidence = payload.get("predictionConfidence") or {}

    # confirmed 也要驗：那條路徑一樣會拿 corrections 去寫評分事件與貢獻影像，
    # 只是不寫 FEEDBACK_COL。少驗它等於留著同一個洞的另一半。
    validate(corrections)

    _record_eval_event(mode, job_id, predicted, corrections)
    contributed = _store_contribution(mode, job_id, payload, corrections, owner_id)

    if payload.get("confirmed") or not corrections:
        job_store.delete(FEEDBACK_COL, job_id)
        return None

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
        "predictionConfidence": {
            k: round(float(v), 4) for k, v in confidence.items()
            if k in fields and isinstance(v, (int, float)) and 0 <= float(v) <= 1
        },
        "corrections": corrections,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        # 覆核的人要知道這筆能不能調得出影像來對照——只有勾了同意的才有。
        # 存在 GCS 的 user_contributed/<版本>/<部位>/<類別>/<job_id>.png。
        "contributed": contributed,
    }
    job_store.create(FEEDBACK_COL, job_id, doc)
    return doc["feedbackId"]


class FeedbackIn(BaseModel):
    packageId: str | None = None
    predicted: dict = Field(default_factory=dict)
    # ConvNeXt 的 top-1 softmax 信心；只作管理端對照，不作自動採用依據。
    # 信心未校準且可能與正確率反向，因此資料層保留原值，但訓練資格只看人工答案。
    predictionConfidence: dict = Field(default_factory=dict)
    corrections: dict = Field(default_factory=dict)
    # 前端在送出當下就判定好，不要在這裡用 corrections 是否為空去反推——
    # 語意留在產生它的那一刻，接收端不做推論。
    confirmed: bool = False
    # 使用者是否同意把這次的部位裁切用於改善模型。**預設 False**：
    # 沒有明確表示就是不同意，不能用「沒反對」當同意。
    allowTrainingUse: bool = False
    # 同意時前端一併重傳照片；不同意就不會有這個欄位，後端也就無從保存。
    # 「未同意時什麼都不存」因此是結構上保證的，不是靠後端自律。
    imageDataUrl: str | None = None
    # PRO 才會有：側臉鼻型模型吃的是整張側臉圖，正面照對它沒有訓練價值。
    # 同意文案必須分開講清楚這一張是「整張側臉照」而不是局部裁切——
    # 兩種樣本的可辨識性差很多，用同一句話帶過就是不實陳述。
    sideImageDataUrl: str | None = None


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
            save(mode, job_id, data, owner_id=job.get("ownerId"))
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

    @app.get("/v1/face/feedback")
    async def list_feedback(  # noqa: ANN202
        limit: int = Query(default=50, ge=1, le=200),
        x_admin_request: str | None = Header(default=None),
    ):
        """列出最近的使用者修正，給管理端做第二次人工檢查。

        為什麼需要這條：修正會直接變成重訓的標籤，但寫進去之前**沒有任何人看過**。
        使用者可能誤點、可能自己也判斷錯——尤其眉型、唇型這種本來就主觀的部位。
        一筆錯的標籤進了訓練集，之後分數變差還很難查回來是哪來的。

        只回管理員。這裡面是「某次分析的模型答案與使用者的修正」，雖然不含 email，
        但一筆一筆看下去仍然是行為資料，不該公開。

        **不回任何身分欄位**：FEEDBACK_COL 的文件本來就不存 email、不存 ownerId
        （見 save() 的說明），這裡也不去別的地方湊。要對照影像請走 GCS 的
        user_contributed 前綴，那邊才有同意過的樣本。
        """
        if str(x_admin_request or "").strip() != "1":
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "ADMIN_REQUIRED", "message": "只有管理員可以檢視修正紀錄"}},
            )
        rows = job_store.all_jobs(FEEDBACK_COL, limit=limit,
                                  order_by="createdAt", descending=True)
        items = []
        for row in rows:
            predicted = row.get("predicted") or {}
            corrections = row.get("corrections") or {}
            items.append({
                "feedbackId": row.get("feedbackId"),
                "jobId": row.get("jobId"),
                "mode": row.get("mode"),
                "createdAt": row.get("createdAt"),
                # 沒有這個欄位的是 2026-08-24 之前的舊資料，一律當待覆核。
                "reviewStatus": row.get("reviewStatus") or REVIEW_PENDING,
                "reviewedAt": row.get("reviewedAt"),
                "reviewNote": row.get("reviewNote") or "",
                # 這一筆進過哪一次訓練批次。有值代表「已經送去訓練過」——後台靠它
                # 分辨「採用了但還沒送訓」與「已經在某一批裡」，不然採用完的資料
                # 會每一批都被重送一次。
                "trainingRunId": row.get("trainingRunId") or "",
                # 退回時影像是真的被刪掉的，把時間留給畫面說明，避免管理員以為
                # 只是被隱藏起來。
                "samplesDeletedAt": row.get("samplesDeletedAt") or "",
                "predictionConfidence": row.get("predictionConfidence") or {},
                # 有沒有影像樣本決定覆核的人能不能真的判斷對錯：只有勾了同意的
                # 才會存 ROI 到 GCS，沒存的那些只能看標籤字串。
                "hasSample": bool(row.get("contributed")),
                # 把「模型答什麼、使用者改成什麼」併成一筆一筆的差異，
                # 讓前端不必自己對照兩個字典——那種對照最容易在畫面上顯示錯邊。
                "changes": [
                    {"field": field,
                     "predicted": predicted.get(field),
                     "corrected": value}
                    for field, value in corrections.items()
                ],
            })
        return {"status": "ok", "count": len(items), "items": items}

    @app.get("/v1/face/feedback/{feedback_id}/samples")
    async def feedback_samples(  # noqa: ANN202
        feedback_id: str,
        x_admin_request: str | None = Header(default=None),
    ):
        """取出這一筆修正對應的樣本影像，給管理端覆核時對照。

        沒有圖就沒辦法真的覆核：眉型、唇型要看到形狀才有辦法判斷使用者說得對不對。
        看不到圖還按「採用」，等於給了「有人看過」的假象，比不覆核更糟。

        只有勾過「同意提供影像」的才有圖，其餘回空陣列——那是結構上的結果，
        不是錯誤，前端要能分辨這兩者。
        """
        if str(x_admin_request or "").strip() != "1":
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "ADMIN_REQUIRED", "message": "只有管理員可以檢視樣本影像"}},
            )
        job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
        # 先確認這一筆回饋真的存在，再去拿圖。
        #
        # job_id 直接來自網址，是外部輸入。少了這道檢查，任何一個字串都會被拿去
        # 掃 bucket——而覆核的人看到的東西會被標成「這一筆的樣本」。
        # 檔名比對本身已經加了分隔線（見 load_for_job），這裡是第二道：
        # 兩道都在，才是「只有存在的紀錄才拿得到它自己的圖」。
        if not job_store.get(FEEDBACK_COL, job_id):
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "FEEDBACK_NOT_FOUND", "message": "找不到這筆修正紀錄"}},
            )
        samples = face_contributions.load_for_job(job_id)
        return {"status": "ok", "jobId": job_id, "count": len(samples), "samples": samples}

    @app.patch("/v1/face/feedback/{feedback_id}/review")
    async def review_feedback(  # noqa: ANN202
        feedback_id: str,
        body: dict,
        x_admin_request: str | None = Header(default=None),
    ):
        """管理員對一筆修正下判斷，**可以逐部位決定**。

        為什麼要有這一步：使用者的修正是免費但**未經查核**的標籤。光看不做決定的話，
        重訓時只能全收或全不收，兩個都不對——使用者會誤點，眉型唇型這種也本來就主觀。

        為什麼要逐部位：一次分析會同時修正好幾個部位，而它們的對錯是獨立的。
        管理員很可能覺得「嘴型改得對、眼型改錯了」，那就該只採用嘴型。
        第一版做成整筆一個狀態，等於逼人在「全收一個錯的」與「連對的一起丟掉」
        之間選，兩個都會讓訓練集變差。

        body 支援兩種形狀，舊的那種留著是為了不讓已經送出的請求突然失敗：
            {"decisions": {"眉型": "accepted", "眼型": "rejected"}}   逐部位（現在的做法）
            {"decision": "accepted"}                                  整筆一次（舊版）

        reviewStatus 變成**摘要**，由各部位的決定推出來：全採用是 accepted、
        全退回是 rejected、有採有退是 partial。真正決定哪些資料進訓練集的是
        reviewDecisions，`training/import_feedback_samples.py` 讀的是那個。

        沒有 reviewStatus 的舊資料一律當 pending——沒人看過的東西不該因為
        欄位還沒加就自動獲得信任。
        """
        if str(x_admin_request or "").strip() != "1":
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "ADMIN_REQUIRED", "message": "只有管理員可以覆核修正紀錄"}},
            )
        # feedbackId 是 FB-<jobId>，但文件 id 用的是 jobId（見 save()）。
        # 前端兩種都可能送過來，這裡統一剝掉前綴，不要讓呼叫端記這個細節。
        job_id = feedback_id[3:] if feedback_id.startswith("FB-") else feedback_id
        doc = job_store.get(FEEDBACK_COL, job_id)
        if doc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": {"code": "FEEDBACK_NOT_FOUND", "message": "找不到這筆修正紀錄"}},
            )

        raw = (body or {}).get("decisions")
        if isinstance(raw, dict) and raw:
            # 只能對「這筆真的改過的部位」下決定。放行未修正的部位會在文件裡留下
            # 一個沒有對應資料的決定，之後匯入時對不到東西。
            corrected = set((doc.get("corrections") or {}).keys())
            decisions: dict[str, str] = {}
            for field, value in raw.items():
                if field not in corrected:
                    raise HTTPException(
                        status_code=422,
                        detail={"error": {"code": "FIELD_NOT_CORRECTED",
                                          "message": f"這筆修正沒有動到「{field}」"}},
                    )
                if value not in REVIEW_DECISIONS:
                    raise HTTPException(
                        status_code=422,
                        detail={"error": {"code": "INVALID_DECISION",
                                          "message": f"{field} 的決定只能是 {sorted(REVIEW_DECISIONS)}"}},
                    )
                decisions[field] = value
            # 保留先前已經下過、這次沒送的決定：前端一次只送改動的那一項，
            # 整份覆蓋會把管理員上一輪的判斷清掉。
            merged = {**(doc.get("reviewDecisions") or {}), **decisions}

            # corrected 要附上管理員給的標籤，而且那個標籤一樣要通過分類表驗證。
            # 管理員也可能打錯字或用了已合併的舊類別——放行的話會在訓練集裡留下
            # 一個模型沒有的標籤，那正是 validate() 存在的理由。
            labels = {**(doc.get("reviewLabels") or {})}
            raw_labels = (body or {}).get("labels")
            if isinstance(raw_labels, dict):
                table = allowed_classes()
                for field, label in raw_labels.items():
                    if merged.get(field) != "corrected":
                        raise HTTPException(
                            status_code=422,
                            detail={"error": {"code": "LABEL_WITHOUT_CORRECTION",
                                              "message": f"「{field}」不是 corrected，不該帶標籤"}},
                        )
                    if not isinstance(label, str) or label not in table.get(field, set()):
                        raise HTTPException(
                            status_code=422,
                            detail={"error": {"code": "INVALID_LABEL",
                                              "message": f"「{field}」沒有「{label}」這個類別"}},
                        )
                    labels[field] = label
            # corrected 卻沒有標籤是不完整的決定，存下去之後匯入時對不到東西。
            missing = [f for f, v in merged.items() if v == "corrected" and not labels.get(f)]
            if missing:
                raise HTTPException(
                    status_code=422,
                    detail={"error": {"code": "LABEL_REQUIRED",
                                      "message": f"改判時要指定正確類別：{'、'.join(missing)}"}},
                )
            # 從 corrected 改回 accepted／rejected 時，舊標籤要清掉，
            # 否則會留下一個沒有人在看、卻仍然會被匯入讀到的值。
            labels = {f: l for f, l in labels.items() if merged.get(f) == "corrected"}
        else:
            decision = str((body or {}).get("decision") or "").strip()
            if decision not in REVIEW_DECISIONS:
                raise HTTPException(
                    status_code=422,
                    detail={"error": {"code": "INVALID_DECISION",
                                      "message": f"decision 只能是 {sorted(REVIEW_DECISIONS)}"}},
                )
            if decision == "corrected":
                # 整筆改判沒有意義：每個部位的正確答案不一樣，沒辦法用一個值表示。
                raise HTTPException(
                    status_code=422,
                    detail={"error": {"code": "CORRECTED_NEEDS_FIELDS",
                                      "message": "改判要逐部位指定，不能整筆一次"}},
                )
            previous = doc.get("reviewDecisions") or {}
            previous_labels = doc.get("reviewLabels") or {}
            fields = doc.get("corrections") or {}
            if decision == "accepted":
                # 「全部送訓」的意思是「其餘也都送訓」，不是「把我剛才的改判撤掉」。
                # 先前這裡直接用 decision 蓋掉每一個欄位、labels 一律清空，於是
                # 管理員逐部位改判之後再按一次全部送訓，那些改判的標籤會靜靜消失，
                # 訓練集收到的是使用者原本填的（可能就是錯的）那個答案。
                merged = {f: ("corrected" if previous.get(f) == "corrected" else decision)
                          for f in fields} or {"_all": decision}
                labels = {f: l for f, l in previous_labels.items() if merged.get(f) == "corrected"}
            else:
                # 「排除這張」是對**照片**的判定（沒對到臉、戴口罩、糊掉），
                # 那種情況下每個部位的標籤都用不了，所以蓋掉全部才是對的。
                merged = {f: decision for f in fields} or {"_all": decision}
                labels = {}

        # 每一個被修正的部位都判過了嗎。這個判斷要在算 status 之前做——
        #
        # merged 只含**已經判過**的那些。改了眉型與眼型、管理員只先退回眉型時，
        # merged == {眉型: rejected}，值的集合是 {rejected}，整筆就被記成 rejected。
        # 而 tools/purge_orphan_contributions.py 是直接讀 reviewStatus 的：它看到
        # rejected 就認定「影像早該刪了」，--apply 會把這個 job 的**每一個**物件刪掉，
        # 包含還沒有人看過的眼型 ROI。那是不可逆的，而且跟那支腳本自己的說明
        # （「partial 不刪」）正好相反。
        #
        # 後台清單也一樣：顯示成整筆退回，眼型就再也不會被人看到。
        all_fields = set(doc.get("corrections") or {})
        fully_decided = bool(all_fields) and all_fields.issubset(set(merged))

        values = set(merged.values())
        if not fully_decided:
            # 還有部位沒判過，就還不是最終狀態。partial 的意思正是「處理到一半」。
            status = "partial"
        else:
            status = ("accepted" if values == {"accepted"}
                      else "rejected" if values == {"rejected"}
                      else "partial")
        note = str((body or {}).get("note") or "").strip()[:500]
        updates = {
            "reviewDecisions": merged,
            "reviewLabels": labels,
            "reviewStatus": status,
            "reviewedAt": datetime.now(timezone.utc).isoformat(),
            "reviewNote": note,
        }

        # 整筆退回 = 樣本影像真的從 GCS 刪掉，不是改個旗標。
        #
        # 那些影像唯一的用途就是當訓練標籤。判定不採用之後它們不會再被任何流程讀到，
        # 留著只是在佔空間，而且是**臉部影像**——沒有用途的臉部資料留著，風險比刪掉大。
        #
        # 只在整筆 rejected 時刪。partial 代表還有部位要進訓練集，而同一次分析的五個
        # 部位共用一個 job_id、存在同一組物件裡，刪掉會把還要用的那幾張一起帶走。
        # 同一次分析的五個部位共用一個 job_id、存在同一組物件裡，所以刪除是**整筆**的，
        # 沒有辦法只刪一個部位。因此條件必須是「每一個被修正的部位都判過，而且全部退回」。
        #
        # 只看 merged 是不夠的：merged 只含**已經判過**的那些。改了眉型與眼型、
        # 管理員只先退回眉型的時候，merged == {眉型: rejected}，值的集合就是 {rejected}，
        # 於是整筆被當成退回，連還沒有人看過的眼型影像也一起刪掉——而刪除是不可逆的。
        # fully_decided 在上面算 status 時就求好了，這裡直接用同一個值——
        # 算兩次的風險是兩邊哪天走鐘，而「刪不刪圖」與「狀態怎麼寫」必須一致。
        deleted = None
        if status == "rejected" and fully_decided and doc.get("contributed"):
            try:
                deleted = face_contributions.delete_for_job(job_id)
            except Exception:
                # 刪不掉就不要宣稱刪掉了：contributed 維持原狀，讓它下次還能被清理工具
                # 掃到。這裡不讓覆核整個失敗——決定本身是有效的，該記下來。
                logging.exception("退回時刪除樣本影像失敗 job_id=%s", job_id)
                updates["samplesDeleteError"] = datetime.now(timezone.utc).isoformat()
            else:
                updates["contributed"] = False
                updates["samplesDeletedAt"] = datetime.now(timezone.utc).isoformat()
                updates["samplesDeletedCount"] = deleted

        job_store.patch(FEEDBACK_COL, job_id, updates)
        return {"status": "ok", "feedbackId": f"FB-{job_id}", "reviewStatus": status,
                "reviewDecisions": merged, "reviewLabels": labels,
                "samplesDeleted": deleted}

    @app.delete("/v1/face/users/{owner_id}")
    async def delete_member_face_data(  # noqa: ANN202
        owner_id: str,
        x_user_id: str | None = Header(default=None),
        x_admin_request: str | None = Header(default=None),
    ):
        """刪除這個會員留在臉部服務的資料。會員刪除流程必須呼叫這一條。

        目前只有一種：使用者同意提供的部位 ROI（見 face_contributions）。
        分析用的照片本來就不保存，job 文件會自己過期，所以沒有別的要清。

        鏡射 render 服務的 `DELETE /render/users/{owner_id}`：本人或管理員才能刪。
        少了這條端點，那些 ROI 就變成刪不掉的臉部資料——存得下卻刪不掉，
        比一開始就不存更糟。

        回傳刪了幾筆。呼叫端據此判斷要不要重試，也讓稽核看得出實際影響範圍。
        """
        is_admin = str(x_admin_request or "").strip() == "1"
        if not is_admin and str(x_user_id or "").strip() != owner_id:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "FORBIDDEN",
                                  "message": "只能刪除自己的資料"}},
            )
        removed = face_contributions.delete_for_owner(owner_id)
        logging.info("刪除會員臉部貢獻樣本 owner=%s removed=%d", owner_id, removed)
        return {"status": "deleted", "contributions": removed}
