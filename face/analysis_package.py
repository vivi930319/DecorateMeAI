"""臉部分析資料包格式。

這個模組只負責整理資料，不執行圖片分析，也不會自行呼叫其他服務。

這裡有兩個部分，用途不同，不要混在一起讀
--------------------------------------------
**一、標籤字典——線上路徑，會執行。**

`canonical_label`、`normalize_face_analysis`、`_code`，以及六張 `*_CODES` 對照表與
`LABEL_ALIASES`。`face_corrections` 直接依賴 `canonical_label`，多支訓練與驗證工具
依賴 `normalize_face_analysis`。

這半邊出錯的後果是靜默的：2026-08-24 眉型加第四類「挑眉」時，模型與
`brow_shape_classes.json` 都更新了，只有 `BROW_SHAPE_CODES` 沒跟上，於是 `_code()`
查不到、回 `"unknown"`——線上一萬張裡有 964 張（10%）模型判對了卻被丟掉答案，
而且沒有任何錯誤訊息。`tests/analysis_package_test.py` 現在守著這件事。

**二、`reference_` 開頭的四個函式——參考實作，不會執行。**

`reference_build_analysis_package`、`reference_build_image_info`、
`reference_set_suggestion`、`reference_set_render_result`，以及只被它們用到的
`SCHEMA_VERSION`。

它們是 2026-07-13《演算法端接口規格書》的可執行定義，對象是四個端（臉部分析、
Ollama 文字建議、商品推薦、商品資料庫）。**整個 repo 沒有任何呼叫端**，加上
`reference_` 前綴就是為了讓這件事在讀到函式名的當下就成立，不必先去搜尋。

為什麼留著不刪：規格說「後端組裝好整包給前端」，但實際架構是四個獨立服務，
沒有任何一個擁有這包資料，於是組裝落到了唯一同時看得到四個結果的地方——瀏覽器
（`web_frontend/js/api.js` 的 `AnalysisPackage`）。要把架構修回規格的樣子時，
這四個函式就是起點；刪掉的話，四端談好的格式就只剩一份 Markdown，沒有可執行、
可被測試檢查的定義。

兩份實作目前已經分歧（例如 id：這裡用隨機 uuid4，前端用時間戳＋隨機），
所以**不要拿這裡的程式碼推論線上行為**。
"""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any #可以是任何型別 更方便穿梭
from uuid import uuid4


# 格式版本標記。它是給**消費端**用的，不是給我自己備忘的：
# Ollama、商品推薦、渲染三端收到資料包時，靠這個字串判斷自己拿到的是哪一版格式。
# 少了它，對方分不出「沒有這個欄位」是舊版本本來就沒有，還是新版本漏送了——
# 這兩種情況要做的處理完全不同。所以欄位有增減時，這個版本號必須跟著動。
SCHEMA_VERSION = "2026-08-v2"

# 以下是為了避免出現 pull在其他比較界舊SERVER上有可能讀不了中文的不便利性，選擇全部正規化成英文，在後續OLLAMA取的臉部分析資料作英文 prompt也有很大幫助
#
# 補充另外兩個理由：欄位名用英文是跨團隊 API 的通例，而這份資料包的對象有四個端
# （臉部分析、Ollama、商品推薦、商品資料庫），其中商品推薦與 iOS 都不在本 repo；
# 中文鍵名在各語言的序列化、log 與除錯工具上都比較容易出問題。
# 這裡的 unknown 是為了以後如果增加型別不會被擋下來，我可以緩存一個空間不會直接報錯卡住一整套 flow。
#
# 但這個取捨的代價要講清楚：錯誤會變成**靜默**的。2026-08-24 眉型加第四類「挑眉」時，
# 模型與 brow_shape_classes.json 都更新了，只有這張表沒跟上，於是 _code() 查不到、
# 全部落成 unknown——線上一萬張裡有 964 張（10%）模型判對了卻被丟掉答案，
# 而且沒有任何錯誤訊息。選擇不中斷流程，就必須有別的東西來擋，
# 那個東西是 tests/analysis_package_test.py：它比對這幾張表與 *_classes.json 是否一致。
FACE_SHAPE_CODES = {
    "鵝蛋臉": "oval",
    "圓形臉": "round",
    "方形臉": "square",
    "長形臉": "oblong",
    "心形臉": "heart",
    "未知": "unknown",
}

BROW_SHAPE_CODES = {
    "一字眉": "straight",
    "彎月眉": "curved",
    "挑眉": "arched",
    "落尾眉": "drooping_tail",
    "未知": "unknown",

}

EYE_SHAPE_CODES = {
    "桃杏眼": "peach_almond",
    "圓眼": "round",
    "鳳眼": "phoenix",
    "下垂眼": "downturned",
    "未知": "unknown",
}

NOSE_SHAPE_CODES = {
    "標準鼻": "standard",
    "寬鼻": "wide",
    "未知": "unknown",
}

LIP_SHAPE_CODES = {
    "厚唇": "full",
    "薄唇": "thin",
    "微笑唇": "smile",
    "花瓣唇": "petal",
    "未知": "unknown",
}
SEASON_CODES = {
    "春季": "spring",
    "夏季": "summer",
    "秋季": "autumn",
    "冬季": "winter",
}

#我們途中合併許多類型，舊資料依然存在不可能讓使用者放著不管，進來就先正規化，也避免前端未及時更新導致流程卡住的風險
# 這張表要跟 prepare_roi_cache.py 的 LABEL_ALIASES 一致——那是訓練側的同一組合併決定。
LABEL_ALIASES = {

    "丹鳳眼": "鳳眼",
    "瞇縫眼": "鳳眼",
    "細長眼": "鳳眼",
    "杏仁眼": "桃杏眼",
    "桃花眼": "桃杏眼",

    "窄鼻": "標準鼻",
    "蒜頭鼻": "寬鼻",

    "M型唇": "花瓣唇",
}


def canonical_label(label: Any) -> Any:
    """把已淘汰的標籤換成合併後的現行標籤；其餘原樣回傳。"""
    return LABEL_ALIASES.get(label, label) if isinstance(label, str) else label


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _code(mapping: dict[str, str], label: Any) -> str:
    """查代碼前先把已淘汰的標籤換成現行標籤。

    上面幾張表只列現行類別，所以舊值必須在這裡就被換掉，否則會落成 "unknown"。
    這是舊標籤進入系統的其中一個入口（另一個是 face_corrections.apply）。
    """
    return mapping.get(canonical_label(str(label)), "unknown")


def normalize_face_analysis(raw_result: dict[str, Any]) -> dict[str, Any]:
    #把 FaceAnalyzer 的中文輸出轉成前後端共用欄位。
    #這步讓 Ollama、推薦端提取更方便
    raw = deepcopy(raw_result)
    skin = raw.get("膚色") or {}
    version = str(raw.get("分析版本") or "BASIC").upper()

    normalized = {
        "version": version,
        "faceShape": _code(FACE_SHAPE_CODES, raw.get("臉型")),
        "browShape": _code(BROW_SHAPE_CODES, raw.get("眉型")),
        "eyeShape": _code(EYE_SHAPE_CODES, raw.get("眼型")),
        "noseFront": _code(NOSE_SHAPE_CODES, raw.get("鼻型")),
        "lipShape": _code(LIP_SHAPE_CODES, raw.get("嘴型")),
        "skinTone": {
            "season": _code(SEASON_CODES, skin.get("四季型")),
            "level": skin.get("膚色分級"),
            "lab": deepcopy(skin.get("LAB")),
            "labSource": skin.get("LAB來源", "正面照"),
            # 頭髮或陰影蓋住臉頰時膚色會算錯，而且不會報錯。推薦端拿 lab 去比色號之前
            # 要看這個旗標——缺欄位時視為可信，維持既有行為。
            # 它量的是臉頰取樣區的亮度離散度（MAD），不是直接偵測頭髮——
            # 離散大代表混進了非皮膚的像素，可能是頭髮、陰影或別的東西，程式分不出來。
            # 只量臉頰是因為門檻 9.5 在頰部校準；換成整臉，乾淨照片誤報率會從 5% 跳到 37.5%。
            "labReliable": bool((skin.get("可信度") or {}).get("reliable", True)),
            "labReliability": deepcopy(skin.get("可信度")),
        },
        "lipLab": deepcopy(raw.get("嘴唇_LAB")),
        "symmetry": deepcopy(raw.get("臉部對稱性")),
        "noseSide": None,
        # 側面照不再參與膚色，所以不能再從 LAB來源 反推。BASIC 沒有這個鍵，預設 False。
        "sidePhotoUsed": bool(raw.get("側面照已使用")),
        "proStatus": deepcopy(raw.get("精細分析狀態")),
        "raw": raw,
    }
    return normalized

# 這支只打包單張圖片的「描述資料」：檔名、型別、原始大小、壓縮後的網址與尺寸。
# 注意它**不產生任何 id**——七個回傳欄位裡沒有識別碼。圖片是靠「屬於哪一包資料包、
# 放在 front 還是 side」來定位的，所以同一張圖要重複使用時，靠的是資料包的 id，
# 不是圖片自己的編號。
#
# 為什麼在意重複使用：一次臉部分析就是一次 Cloud Run 的運算費用。
# 補充一個 2026-09-10 才成立的前提——在那之前分析跑在 BackgroundTasks（回應送出後才
# 執行），必須開 --no-cpu-throttling，於是實例活著的每一秒都計費：實測一週計費
# 99,576 秒、真正在運算的只有約 1,900 秒，98% 付給閒置。分析搬進請求裡之後，
# 計費時間才真的等於運算時間，「省一次分析就省一次錢」從那時起才完全成立。
def reference_build_image_info(
    original_name: str,
    content_type: str,
    size: int,
    *,
    width: int | None = None,
    height: int | None = None,
    image_url: str | None = None,
    data_url: str | None = None,
) -> dict[str, Any]:
    """建立單張圖片的描述資料；圖片本身可用 URL 或 data URL 傳遞。"""
    if size < 0:
        raise ValueError("圖片大小不能小於 0")
    return {
        "originalName": original_name,
        "originalType": content_type,
        "originalSize": size,
        "compressedImageUrl": image_url,
        "compressedDataUrl": data_url,
        "compressedWidth": width,
        "compressedHeight": height,
    }

# reference 前綴的函式：四端共用格式的參考實作，整個 repo 沒有呼叫端。
# 方向不要弄反——它先於前端存在（2026-06-25），前端是另外照規格自己實作一份，
# 兩份現在已經分歧（例如 id 產生方式）。留著當後續優化的起點。
def reference_build_analysis_package(
    raw_result: dict[str, Any],
    front_image: dict[str, Any],
    *,
    client: str = "web",
    user_id: str | int | None = None,
    side_image: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """建立一份完整、可直接轉成 JSON 的 analysisPackage。"""
    if client not in {"web", "ios"}:
        raise ValueError("client 只接受 web 或 ios")

    now = _now_iso()
    mode = str(raw_result.get("分析版本") or "BASIC").upper()
    images = {"front": deepcopy(front_image)}
    if side_image is not None:
        images["side"] = deepcopy(side_image)

    return {
        "id": f"AN-{uuid4().hex[:12]}",
        "schemaVersion": SCHEMA_VERSION,
        "mode": mode,
        "client": client,
        "userId": user_id,
        "status": "completed",
        "createdAt": now,
        "updatedAt": now,
        "images": images,
        "faceAnalysis": normalize_face_analysis(raw_result),
        "generativeText": {
            "status": "pending",
            "provider": "ollama",
            "model": None,
            "suggestion": None,
            "renderPromptEn": None,
            "error": None,
        },
        "render": {
            "status": "pending",
            "provider": "replicate",
            "replicateTempUrl": None,
            "afterImageUrl": None,
            "savedImageId": None,
            "error": None,
        },
        "recommendations": {"products": [], "tips": [], "ads": []},
    }


def reference_set_suggestion(
    package: dict[str, Any],
    suggestion: str,
    *,
    model: str,
    provider: str = "ollama",
    render_prompt_en: str | None = None,
) -> dict[str, Any]:
    """把中文建議與英文渲染指令寫回資料包，不改動傳入物件。"""
    result = deepcopy(package)
    result["generativeText"] = {
        "status": "completed",
        "provider": provider,
        "model": model,
        "suggestion": suggestion,
        "renderPromptEn": render_prompt_en,
        "error": None,
    }
    result["updatedAt"] = _now_iso()
    return result


def reference_set_render_result(
    package: dict[str, Any],
    after_image_url: str,
    *,
    temporary_url: str | None = None,
    saved_image_id: str | None = None,
) -> dict[str, Any]:
    """把妝後圖片結果寫回資料包。"""
    result = deepcopy(package)
    result["render"] = {
        "status": "completed",
        "provider": "replicate",
        "replicateTempUrl": temporary_url,
        "afterImageUrl": after_image_url,
        "savedImageId": saved_image_id,
        "error": None,
    }
    result["updatedAt"] = _now_iso()
    return result
