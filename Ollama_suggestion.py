import json
import os
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from dev_server_utils import get_cors_origins, run_dev_server


app = FastAPI(title="Ollama Suggestion API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
# 輸出 token 上限。不設的話模型會用它自己的預設值，實測建議每次都在 900 中文字左右
# 斷在句子中間 —— 六段只生到第五段，「避免事項」「總結與建議」永遠出不來。
# prompt 要求 350~1050 中文字，中文一個字約 1~2 token，抓 4096 讓它足夠把六段寫完。
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))
SUGGESTION_API_KEY = os.getenv("SUGGESTION_API_KEY", "")


def require_api_key(x_api_key: str | None = Header(default=None)):
    if SUGGESTION_API_KEY and x_api_key != SUGGESTION_API_KEY:
        raise HTTPException(
            status_code=401,
            detail={"error": {"code": "FORBIDDEN", "message": "Invalid or missing API key.", "retryable": False}},
        )


# ═══ 妝容知識庫 ═══
MAKEUP_DATABASE = {
    "日常自然妝": {
        "description": "充滿呼吸感的自然好氣色，強調透明感與溫潤的鄰家氛圍。",
        "tone": "暖杏蜜桃色系",
        "eye_layers": "先用霧面淺杏色在全眼皮輕盈打底，取帶有微細珠光的蜜桃色在眼窩中央點綴，最後用棕色眼影代替眼線，在眼尾淡淡拉出一道柔和的陰影。",
        "base_detail": "輕薄具緞面光澤的底妝，呈現透亮自然肌膚質感。",
        "lip_detail": "使用帶有水光的茶色調唇釉，疊加在唇部中央並向外暈染，打造澎潤且無邊界的透光唇效。",
        "blush_detail": "選用明亮的蜜桃粉色，大面積地從蘋果肌橫向刷至臉頰兩側。",
        "custom_tip": "著重在自然的毛流感眉毛與捲翹但根根分明的睫毛。",
    },
    "Soft Baddie": {
        "description": "更鬆弛自然卻不失辣妹氣場，強調光澤感底妝與煙燻感眼妝。",
        "tone": "肉桂奶油與夢幻藍色系",
        "eye_layers": "先用霧面淺米色在大面積眼窩打底消腫，接著取咖啡棕色的眼影從眼尾向中心暈染三分之一營造深邃感，最後在眼頭點綴星空藍色的打亮，並用黑色眼影稍微加深睫毛根部。",
        "base_detail": "打造精緻的光澤奶油肌，在顴骨最高處點綴帶有藍色偏光的高光，增加金屬感。",
        "lip_detail": "先用肉桂色唇線筆勾勒出邊界清晰的飽滿唇形，再由中心向外疊加同色系霧面唇釉。",
        "blush_detail": "選擇嫩粉色在蘋果肌輕輕打圈。",
        "custom_tip": "利用藍色高光與暖色底妝的對比，創造出前衛且高級的立體光影感。",
    },
    "韓系亞裔": {
        "description": "融合韓式清透與亞裔俐落感，展現高級消腫與強調眼部神采的妝效。",
        "tone": "低飽和粉棕系",
        "eye_layers": "先使用灰感粉棕色在整個眼皮進行大面積消腫，接著取冷咖啡色眼影沿著眼尾拉出一條向上的倒三角陰影，眼頭使用霧面米白色提亮。",
        "base_detail": "柔焦感的輕霧面底妝，呈現勻稱精緻的膚色。",
        "lip_detail": "選擇霧面莫蘭迪粉色，先均勻塗抹全唇並模糊邊界，再取深一號色點在唇部中心並用指腹拍開。",
        "blush_detail": "與眼妝色調統一，斜向掃在顴骨下方。",
        "custom_tip": "強調太陽花般的放射狀睫毛與上揚眼線的連結，營造俐落的貓眼感。",
    },
    "日雜清透": {
        "description": "充滿呼吸感的自然好氣色，強調透明感與溫潤的鄰家氛圍。",
        "tone": "暖杏蜜桃色系",
        "eye_layers": "先用霧面淺杏色在全眼皮輕盈打底，取帶有微細珠光的蜜桃色在眼窩中央點綴，最後用棕色眼影代替眼線，在眼尾淡淡拉出一道柔和的陰影。",
        "base_detail": "強調清透的奶油肌質感，營造日系少女的微醺透明感。",
        "lip_detail": "使用帶有水光的茶色調唇釉，疊加在唇部中央並向外暈染，打造澎潤且無邊界的透光唇效。",
        "blush_detail": "選用明亮的蜜桃粉色，大面積地從蘋果肌橫向刷至臉頰兩側。",
        "custom_tip": "著重在自然的毛流感眉毛與捲翹但根根分明的睫毛。",
    },
    "千金": {
        "description": "高級感、五官立體且乾淨高級的氛圍。",
        "tone": "香檳粉金系",
        "eye_layers": "先以霧面裸粉色輕掃眼皮，再取香檳金珠光點綴在眼皮中央與眼褶，並用深可可色細細勾勒一條細長的上揚眼線，下睫毛處用銀色亮片點綴。",
        "base_detail": "強調無瑕的陶瓷光澤，在額頭、鼻樑與顴骨處疊加珍珠白色的細緻高光。",
        "lip_detail": "先用潤唇膏打底，疊加粉嫩感的水潤唇釉，營造溫柔優雅的水光嘟嘟唇質感。",
        "blush_detail": "選用膨脹色系櫻花粉，斜掃在笑肌上方提升靈動感。",
        "custom_tip": "著重在下睫毛的根根分明，增加眼神的精緻度。",
    },
    "港風": {
        "description": "復古90年代明豔對比，成熟大氣。",
        "tone": "復古紅棕色與冷灰色",
        "eye_layers": "先用淺灰色眼影在整個眼窩大範圍打底，再取炭咖啡色眼影沿著睫毛根部向上暈染出半包圍陰影，眼頭與鼻影銜接處要適度加深層次。",
        "base_detail": "陶瓷般的全霧面底妝，刻畫出明顯的立體輪廓。",
        "lip_detail": "先用唇筆精確畫出飽和的正紅色輪廓，填滿霧面大紅色唇膏，展現濃郁的復古氣場。",
        "blush_detail": "低飽和修容色兼作腮紅，銜接鬢角處暈染。",
        "custom_tip": "眉毛要強調濃郁的毛流感，與紅唇形成強烈的色彩視覺對比。",
    },
    "病嬌": {
        "description": "日系微醺憂鬱感，楚楚可憐的脆弱美。",
        "tone": "煙燻玫瑰色與淡粉紫色",
        "eye_layers": "先用淡粉色在眼周打底，接著取煙燻玫瑰色大面積暈染下眼瞼營造哭腫感，眼頭與瞳孔下方點綴濕亮感的透明珠光。",
        "base_detail": "追求極致白皙的霧面感，呈現出一種發燒般的微醺紅暈。",
        "lip_detail": "選用深酒紅色，從唇心中間向外進行「咬唇式」疊塗，模糊唇周邊界，展現頹廢質感。",
        "blush_detail": "位置要偏高，直接疊加在眼下位置。",
        "custom_tip": "強調睫毛的濕潤成束感，視覺上增加柔弱且迷人的氣息。",
    },
    "男士白開水": {
        "description": "保留男性原生輪廓與肌膚質感，以輕薄修飾、整潔眉型和低彩度唇色呈現乾淨清爽的白開水妝感。",
        "tone": "裸色系、低彩度杏棕",
        "eye_layers": "使用霧面淺棕輕掃眼窩與下眼尾，不堆疊珠光，避免明顯眼線。",
        "base_detail": "局部遮瑕並薄透均勻膚色，保留自然肌理，T 字輕微控油。",
        "lip_detail": "使用透明護唇或低彩度裸豆沙色，修飾唇色不製造明顯妝感。",
        "blush_detail": "以低飽和裸杏色少量修飾氣色，也可依膚況省略。",
        "custom_tip": "整體以不著妝為目標，修飾瑕疵但不強調任何妝感重點。",
    },
}

# 英文 enum → 中文標籤對照
MAP_FACE   = {"oval": "鵝蛋臉", "round": "圓形臉", "square": "方形臉", "oblong": "長形臉", "heart": "心形臉", "unknown": "未知臉型"}
MAP_BROW   = {"straight": "一字眉", "curved": "彎月眉", "drooping_tail": "落尾眉", "unknown": "未知眉型"}
MAP_EYE    = {"narrow": "瞇縫眼", "downturned": "下垂眼", "round": "圓眼", "phoenix": "丹鳳眼", "slender": "細長眼", "peach_blossom": "桃花眼", "almond": "杏仁眼", "unknown": "未知眼型"}
MAP_NOSE   = {"standard": "直鼻", "wide": "寬鼻", "narrow": "短鼻", "unknown": "未知鼻型"}
MAP_LIP    = {"full": "厚唇", "thin": "薄唇", "m_shape": "M型唇", "smile": "微笑唇", "petal": "花瓣唇", "unknown": "未知唇型"}
MAP_SEASON = {"spring": "春季型", "summer": "夏季型", "autumn": "秋季型", "winter": "冬季型", "unknown": "未知膚色屬性"}

# 特徵描述邏輯
FACE_LOGIC     = {"鵝蛋臉": "比例完美流暢", "圓形臉": "雙頰圓潤飽滿", "長形臉": "比例顯得成熟", "方形臉": "輪廓英氣硬朗", "心形臉": "下巴精緻纖細"}
EYEBROW_LOGIC  = {"一字眉": "眉型平直無邪", "彎月眉": "弧度圓潤溫柔", "落尾眉": "眉尾優雅下落"}
EYE_LOGIC      = {"圓眼": "眼神圓潤清澈", "瞇縫眼": "眼型細窄有神", "下垂眼": "眼尾柔和下垂", "丹鳳眼": "眼尾俐落上揚", "細長眼": "眼神嫵媚狹長", "桃花眼": "眼神柔亮有魅力", "杏仁眼": "眼型均衡柔和"}
NOSE_LOGIC     = {"直鼻": "鼻樑高挺筆直", "寬鼻": "鼻翼大氣飽滿", "短鼻": "山根小巧精緻", "未知鼻型": "依照鼻型自然修飾"}
LIP_LOGIC      = {"M型唇": "唇峰稜角立體", "花瓣唇": "唇形飽滿豐盈", "微笑唇": "嘴角天然上揚", "厚唇": "唇部感性飽滿", "薄唇": "唇線俐落清秀"}
SKIN_LOGIC     = {"春季型": "適合亮暖黃系", "夏季型": "適合冷粉灰系", "秋季型": "適合深邃暖米", "冬季型": "適合對比冷青"}

# 特定技法
FACE_METHOD    = {"鵝蛋臉": "輕掃下顎線；腮紅斜上暈染；打亮額頭鼻尖。", "圓形臉": "從耳際斜下刷修容；腮紅調高拉提；打亮下巴。", "長形臉": "修容額頭頂與下巴底；腮紅橫平刷；打亮眼下。", "方形臉": "下頷稜角圓潤修容；蘋果肌打圈腮紅；打亮中心。", "心形臉": "顴骨下方向內收縮；下巴尖端打亮；腮紅斜掃顴骨。"}
EYEBROW_METHOD = {"一字眉": "縮短中庭，眉尾拉平。", "彎月眉": "圓潤轉折，修飾硬朗。", "落尾眉": "眉峰後移，輕輕下撇。"}


# ═══ Request Schema ═══
class SuggestRequest(BaseModel):
    analysisPackage: dict[str, Any] | None = None
    faceAnalysis: dict[str, Any] | None = None
    style: str | None = Field(default="日常自然妝")
    language: str | None = Field(default="zh-TW")
    userNote: str | None = None
    model: str | None = None


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _extract_face_analysis(payload: SuggestRequest) -> dict[str, Any]:
    if payload.faceAnalysis:
        return payload.faceAnalysis
    if payload.analysisPackage:
        return payload.analysisPackage.get("faceAnalysis") or {}
    return {}


def _pick(face_analysis: dict[str, Any], english_key: str, chinese_key: str, default: str = "未提供") -> Any:
    if english_key in face_analysis:
        return face_analysis.get(english_key) or default
    if chinese_key in face_analysis:
        return face_analysis.get(chinese_key) or default
    raw = face_analysis.get("raw") or {}
    return raw.get(chinese_key) or default


def _map_or_raw(value: str, mapping: dict) -> str:
    """英文 enum 優先查表，查不到則直接用原值（已是中文標籤）。"""
    if not value or value == "未提供":
        return value
    return mapping.get(value, value)


def build_prompt(payload: SuggestRequest) -> str:
    face_analysis = _extract_face_analysis(payload)
    style = payload.style or "日常自然妝"
    user_note = payload.userNote or "無"

    style_cfg = MAKEUP_DATABASE.get(style, MAKEUP_DATABASE["日常自然妝"])

    face_shape_raw = _pick(face_analysis, "faceShape", "臉型")
    brow_shape_raw = _pick(face_analysis, "browShape", "眉型")
    eye_shape_raw  = _pick(face_analysis, "eyeShape",  "眼型")
    nose_front_raw = _pick(face_analysis, "noseFront", "鼻型")
    lip_shape_raw  = _pick(face_analysis, "lipShape",  "嘴型")
    skin_tone      = face_analysis.get("skinTone") or face_analysis.get("膚色") or {}

    c_face = _map_or_raw(face_shape_raw, MAP_FACE)
    c_brow = _map_or_raw(brow_shape_raw, MAP_BROW)
    c_eye  = _map_or_raw(eye_shape_raw,  MAP_EYE)
    c_nose = _map_or_raw(nose_front_raw, MAP_NOSE)
    c_lip  = _map_or_raw(lip_shape_raw,  MAP_LIP)

    season_raw = skin_tone.get("season") if isinstance(skin_tone, dict) else None
    c_skin = _map_or_raw(season_raw, MAP_SEASON) if season_raw else str(skin_tone)

    analysis_text = (
        f"臉型：{c_face}（{FACE_LOGIC.get(c_face, '')}）、"
        f"眉型：{c_brow}（{EYEBROW_LOGIC.get(c_brow, '')}）、"
        f"眼型：{c_eye}（{EYE_LOGIC.get(c_eye, '')}）、"
        f"鼻型：{c_nose}（{NOSE_LOGIC.get(c_nose, '依照鼻型自然修飾')}）、"
        f"唇型：{c_lip}（{LIP_LOGIC.get(c_lip, '')}）、"
        f"膚色：{c_skin}（{SKIN_LOGIC.get(c_skin, '')}）"
    )

    return f"""你是一位專業的彩妝整體造型總監。請根據特徵分析與目標風格，編寫一份流暢的繁體中文妝容建議報告。
[五官膚色特徵摘要]: {analysis_text}
[目標風格設定]: {style}（風格特點：{style_cfg['description']}；推薦色彩方案：{style_cfg['tone']}）
[使用者需求備註]: {user_note}

【專屬技法融合指引】:
- 底妝：針對 {c_skin} 特性，打造 {style_cfg['base_detail']}
- 眉毛：執行 {EYEBROW_METHOD.get(c_brow, '順原生毛流填補空隙')}
- 眼妝：步驟為 {style_cfg['eye_layers']}
- 腮紅/修容：{FACE_METHOD.get(c_face, '適度修飾輪廓')} 腮紅手法搭配 {style_cfg['blush_detail']}；鼻部修飾執行 {NOSE_LOGIC.get(c_nose, '依照鼻型自然修飾')}
- 唇妝：手法為 {style_cfg['lip_detail']}

【硬性格式限制】:
1. 必須且只能分為以下六個段落，並明確寫出標題，全程嚴禁使用星號「*」或任何 Markdown 符號標記：
   1. 整體妝容方向
   2. 底妝建議
   3. 眉眼妝建議
   4. 唇妝建議
   5. 避免事項
   6. 總結與建議
2. 語氣像真的化妝師在提醒使用者，客觀自然，不宣稱分析結果 100% 精準。
3. 絕對不可自行編造側面鼻型、特定品牌或特定商品色號。
4. 禁止輸出任何 Markdown 程式碼區塊或內部思考鏈區塊（如 <think>）。
5. 總字數限制在 350 ~ 1050 中文字。"""


def call_ollama(prompt: str, model: str) -> str:
    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": OLLAMA_NUM_PREDICT},
        },
        timeout=OLLAMA_TIMEOUT,
    )
    try:
        data = response.json()
    except Exception:
        data = {"raw": response.text}

    if not response.ok:
        raise RuntimeError(f"Ollama 回應失敗：{response.status_code} {data}")

    suggestion = data.get("response")
    if not suggestion:
        raise RuntimeError("Ollama 回應沒有 response 欄位")
    return suggestion.strip()


@app.get("/health")
async def health():
    reachable = False
    error = None
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        reachable = response.ok
        if not response.ok:
            error = f"HTTP {response.status_code}"
    except Exception as exc:
        error = str(exc)

    return {
        "status": "ok",
        "service": "ollama-suggestion",
        "ollama": {
            "baseUrl": OLLAMA_BASE_URL,
            "model": OLLAMA_MODEL,
            "reachable": reachable,
            "error": error,
        },
        "fallbackEnabled": False,
        "api_key_required": bool(SUGGESTION_API_KEY),
    }


@app.post("/suggest")
async def suggest(payload: SuggestRequest, _=Depends(require_api_key)):
    face_analysis = _extract_face_analysis(payload)
    if not face_analysis:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "缺少 faceAnalysis 或 analysisPackage.faceAnalysis"}},
        )

    model = payload.model or OLLAMA_MODEL
    prompt = build_prompt(payload)
    try:
        suggestion = call_ollama(prompt, model)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "OLLAMA_UNAVAILABLE",
                    "message": str(exc),
                    "retryable": True,
                }
            },
        ) from exc

    return {
        "status": "completed",
        "provider": "ollama",
        "model": model,
        "fallbackUsed": False,
        "createdAt": _now_iso(),
        "suggestion": suggestion,
    }


@app.post("/suggest/stream")
async def suggest_stream(payload: SuggestRequest, _=Depends(require_api_key)):
    face_analysis = _extract_face_analysis(payload)
    if not face_analysis:
        raise HTTPException(
            status_code=400,
            detail={"error": {"message": "缺少 faceAnalysis 或 analysisPackage.faceAnalysis"}},
        )

    model = payload.model or OLLAMA_MODEL
    prompt = build_prompt(payload)

    def generate():
        try:
            resp = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"num_predict": OLLAMA_NUM_PREDICT},
                },
                timeout=OLLAMA_TIMEOUT,
                stream=True,
            )
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        if not resp.ok:
            yield f"data: {json.dumps({'error': f'Ollama HTTP {resp.status_code}'})}\n\n"
            return

        full_text = ""
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                token = chunk.get("response", "")
                if token:
                    full_text += token
                    yield f"data: {json.dumps({'token': token})}\n\n"
                if chunk.get("done"):
                    break
            except Exception:
                continue

        yield f"data: {json.dumps({'done': True, 'suggestion': full_text.strip(), 'model': model})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    run_dev_server(app, service_name="Ollama Suggestion API", env_prefix="OLLAMA_SUGGESTION", default_port=8010)
