import os
import sys
import httpx
import logging
import json
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from fastapi import FastAPI, HTTPException, Request, status, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ollama-suggestion")

app = FastAPI(title="Ollama 妝容真實個人化修飾服務", version="2026-07-25-接入規格版")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. 對齊組長規格書：環境變數名稱必須為 SUGGESTION_API_KEY
SUGGESTION_API_KEY = os.getenv("SUGGESTION_API_KEY", "").strip()
SIGNING_SECRET = os.getenv("RENDER_PROMPT_SIGNING_SECRET", "").strip()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_TEXT = os.getenv("OLLAMA_MODEL", "gemma3")
MODEL_VISION = os.getenv("MODEL_VISION", "llava:latest")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120.0"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))
OLLAMA_SUGGESTION_PORT = int(os.getenv("OLLAMA_SUGGESTION_PORT", "8010"))

# 2. Fail Closed 機制：未設定 SUGGESTION_API_KEY 則拒絕啟動
def enforce_service_api_key():
    if not SUGGESTION_API_KEY:
        logger.critical("致命錯誤：環境變數未設定 SUGGESTION_API_KEY。服務啟動失敗 (Fail Closed)。")
        print("ERROR: SUGGESTION_API_KEY environment variable is required to run this service.")
        sys.exit(1)

VALID_STYLES = {"日常自然妝", "Soft baddie", "韓系亞裔妝", "日雜清透妝", "千金妝", "港風妝", "病嬌妝", "男士白開水"}

class SuggestRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    faceAnalysis: Optional[dict[str, Any]] = None
    analysisPackage: Optional[dict[str, Any]] = None
    style: str = "日常自然妝"
    language: str = "zh-TW"
    userNote: Optional[str] = None
    model: Optional[str] = None

def verify_api_key(x_api_key: Optional[str]) -> bool:
    """ 使用固定時間比較演算法驗證 API Key，防範時脈攻擊 """
    if not SUGGESTION_API_KEY or not x_api_key:
        return False
    return hmac.compare_digest(SUGGESTION_API_KEY.encode("utf-8"), x_api_key.encode("utf-8"))

def sign_render_prompt(render_prompt_en: str) -> Optional[str]:
    """ 使用 HMAC-SHA256 對英文渲染指令進行底層簽章 """
    if not SIGNING_SECRET:
        return None
    return hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        render_prompt_en.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

def build_luxury_rich_girl_prompt() -> str:
    """
    千金妝精純彩妝描述：不含性別詞彙、不含 identity lock 鎖定句
    """
    prompt = (
        "Apply a luxurious elegant makeup look to the face, as a photorealistic makeup-only retouch of the original photo.\n\n"
        "Eyes: highly visible, bold and significantly thickened jet-black eyeliner that dynamically extends straight and long past the outer corner of the eyes with a subtle elegant lift, "
        "vivid and heavy shading of medium-saturation warm dusty pink-apricot and soft rose-taupe tones heavily sweeping across the entire eye sockets and lower crease, "
        "a concentrated, rich dark brown shadow heavily packed right at the base of the lash roots for extreme depth, "
        "highly defined, hyper-plump and three-dimensional aegyosal (charming fat) carved with a soft shadow underline, with an intense, high-contrast crystalline white-gold diamond shimmer that strongly illuminates the inner eye corners and the exact center of the three-dimensional aegyosal, "
        "extremely long, perfectly curled, and sharply separated spiky mascaraed eyelashes creating a defined doll-like sunflower effect with long individual lash clusters extending from both upper and lower lash lines, slightly rounded inner eye corners.\n\n"
        "Brows: thin, straight, and elongated delicate brows softly filled with light brown powder and brow mascara.\n\n"
        "Face: dewy satin skin texture with refined light brown contouring along the nose bridge and jawline, honey-melon peach blush swept horizontally below the pupils towards the cheekbones, seamlessly layered with fig-toned blush on the apples of the cheeks blended outward; clear, hyper-reflective wet-shine dewy highlighters precisely dotted on the bridge of the nose, nose tip, highest points of the cheeks, cupid's bow, and chin.\n\n"
        "Lips: full lips defined with a lip liner to softly blur the outer boundaries, completely filled with a clear glossy peach-beige lip glaze over a concealed lip base."
    )
    return prompt

def make_error_response(http_code: int, code: str, message: str, retryable: bool):
    return JSONResponse(
        status_code=http_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.error(f"校驗失敗: {exc.errors()}")
    return make_error_response(status.HTTP_422_UNPROCESSABLE_ENTITY, "VALIDATION_ERROR", "欄位型別、結構或不支援的系統特徵代碼", False)

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP 異常: 狀態碼 {exc.status_code} - 原因: {exc.detail}")
    return make_error_response(exc.status_code, "HTTP_EXCEPTION", exc.detail, False)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未捕捉的系統例外: {str(exc)}")
    return make_error_response(500, "INTERNAL_SERVER_ERROR", f"後端崩潰或例外錯誤: {str(exc)}", True)

# 3. 對齊組長規格書 2.2 與 3.2 節：GET /health 不需要金鑰，並回傳精確結構
@app.get("/health")
async def health_check():
    ollama_reachable = False
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            if res.status_code == 200:
                ollama_reachable = True
    except Exception as e:
        logger.warning(f"Ollama 本體連線測試失敗: {str(e)}")

    return {
        "status": "ok",
        "service": "ollama-suggestion",
        "ollama": {
            "reachable": ollama_reachable,
            "model": MODEL_TEXT
        },
        "api_key_required": bool(SUGGESTION_API_KEY)
    }

async def extract_image_features_with_llava(base64_image_url: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    pure_base64 = base64_image_url.split(",")[1] if "," in base64_image_url else base64_image_url

    prompt = "Analyze this person's facial features, skin texture, tone, eye shape, and facial symmetry in detail for makeup application planning. Output a descriptive English paragraph under 100 words."
    
    payload = {
        "model": MODEL_VISION,
        "prompt": prompt,
        "images": [pure_base64],
        "stream": False,
        "options": {"num_predict": 150, "temperature": 0.2}
    }
    
    logger.info("啟動 Llava 視覺分析...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            raise RuntimeError(f"Llava Vision Server 異常: {res.status_code}")
        return res.json().get("response", "").strip()

def build_gemma3_prompts(face_analysis: dict, style: str, user_note: Optional[str], vision_feedback: str) -> Tuple[str, str]:
    f_shape = face_analysis.get('臉型', '未提供')
    b_shape = face_analysis.get('眉型', '未提供')
    e_shape = face_analysis.get('眼型', '未提供')
    n_front = face_analysis.get('鼻型', '未提供')
    l_shape = face_analysis.get('嘴型', '未提供') or "標準比例唇（偏向柔和輪廓）"
        
    skin_obj = face_analysis.get('膚色', {})
    if isinstance(skin_obj, dict):
        s_season = skin_obj.get('四季型', '未提供')
        s_level = skin_obj.get('膚色分級', '未提供')
    else:
        s_season = '暖色調'
        s_level = str(skin_obj)

    system_prompt_zh = (
        "你是明星御用高端彩妝顧問。你的任務是結合寶寶的原生五官數據與指定妝容風格，產生繁體中文客製化修容與彩妝手法建議，並搭配推薦具體開架商品（給寶寶看）。\n\n"
        "【核心任務：視覺骨相微調與整形修飾】\n"
        "妳的建議必須死死咬住寶寶原生的五官結構進行針對性『視覺骨相微調與整形修飾』！\n"
        f"1. 底妝與腮紅修容：必須針對寶寶天生的【{f_shape}】與【{n_front}】設計。說明如何利用高光與立體陰影交錯，在視覺上重塑天生【{f_shape}】的輪廓線條，達到向內收縮 or 流暢臉型的骨相改變，並讓【{n_front}】在視覺上骨幹拔高。\n"
        f"2. 眉眼妝建議：必須針對寶寶天生的【{e_shape}】與【{b_shape}】。詳細指導如何利用眼影暈染邊界、眼線延伸、倒影與臥蠶刻畫，在視覺上『徹底重塑並改變』原本的【{e_shape}】限制，達到眼型放大、下至 or 微整形矯正的視覺震撼效果。\n"
        f"3. 唇妝建議：必須針對寶寶天生的【{l_shape}】。不論原生數據多寡，必須詳細說明如何利用唇線模糊與擴唇手法，在視覺上重塑並優化【{l_shape}】的厚薄比例與嘴角弧度，打造微翹的性感嘟嘟唇妝效。\n\n"
        "妳的輸出必須嚴格分為以下七個段落，標題獨立佔一行，不加 any Markdown 符號。請提供具體實用的手法操作與彩妝細節說明，不限制每段字數上限：\n"
        "1. 整體妝容方向\n"
        "2. 底妝建議\n"
        "3. 眉眼妝建議\n"
        "4. 腮紅修容\n"
        "5. 唇妝建議\n"
        "6. 避免事項\n"
        "7. 總結與建議\n\n"
        "【共通死命令】\n"
        "1. 推薦品牌僅限康是美有賣：SOFINA蘇菲娜、1028、CLIO珂莉奧、KATE凱婷、IMMEME、KISSME奇士美、Maybelline媚比琳、PONYEFFECT、Za、Excel。\n"
        "2. 中文部分一律親切叫對方為「寶寶」！用溫柔閨蜜語氣。\n"
        "3. 全文嚴禁使用 any Markdown 符號（如 *、#、** 等），一律使用純文字輸出。"
    )

    user_prompt_zh = f"【當前寶寶真實特徵與需求數據】\n- 目標妝容風格：{style}\n- 使用者偏好與備註：{user_note if user_note else '無特別要求'}\n- 臉型：{f_shape}\n- 眉型：{b_shape}\n- eye型：{e_shape}\n- 正面鼻型：n_front\n- 唇型：{l_shape}\n- 膚色季型：{s_season}\n- 膚色級別：{s_level}\n\n【AI 視覺照片提取細節】\n{vision_feedback}\n\n請立刻執行最高排版鐵律，產生溫柔親切、富含具體操作步驟與推薦開架彩妝商品的七段純繁中建議。"

    return system_prompt_zh, user_prompt_zh

async def call_gemma3_generate(system_instruction: str, user_prompt: str) -> str:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    full_combined_prompt = f"{system_instruction}\n\n[Current Request]:\n{user_prompt}"
    
    payload = {
        "model": MODEL_TEXT, 
        "prompt": full_combined_prompt, 
        "stream": False,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT, # 對齊組長規格書 4.2 節：設定為 4096 防止截斷
            "temperature": 0.3,
            "top_p": 0.8
        }
    }
    
    logger.info(f"呼叫 {MODEL_TEXT} 進行繁中彩妝建議推理...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        get_res = await client.post(url, json=payload)
        if get_res.status_code != 200:
            raise RuntimeError(f"{MODEL_TEXT} Server 異常: {get_res.status_code}")
        return get_res.json().get("response", "").strip()

@app.post("/suggest")
async def suggest(payload: SuggestRequest, x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    # 4. 對齊組長規格書 3.1 節：金鑰驗證失敗回傳 401
    if not verify_api_key(x_api_key):
        logger.warning("攔截到未授權或無效 Key 的 /suggest 請求")
        return make_error_response(401, "UNAUTHORIZED", "Unauthorized: Invalid or missing API Key.", False)

    logger.info("驗證成功，執行彩妝推理流水線...")
    
    face_analysis = payload.faceAnalysis or (payload.analysisPackage.get("faceAnalysis") if payload.analysisPackage else None)
    analysis_pkg = payload.analysisPackage or {}
    
    if not face_analysis:
        return make_error_response(400, "MISSING_FACE_ANALYSIS", "缺少有效 analysisPackage 內部的分析資料包", False)
    
    images_obj = analysis_pkg.get("images", {})
    front_image_obj = images_obj.get("front", {})
    base64_image_url = front_image_obj.get("compressedDataUrl")
    
    if not base64_image_url:
        vision_feedback = "No image context provided. Rely solely on structured JSON parameters."
    else:
        try:
            vision_feedback = await extract_image_features_with_llava(base64_image_url)
        except Exception as ve:
            logger.error(f"Llava 看圖失敗: {str(ve)}，自動降級。")
            vision_feedback = "Vision analysis failed or timed out. Rely on JSON metrics."

    normalized_style = payload.style.strip()
    if normalized_style in {"韓系亞裔", "日雜清透", "千金", "港風", "病嬌", "男士白開水"}:
        if not normalized_style.endswith("妝") and normalized_style != "男士白開水":
            normalized_style = f"{normalized_style}妝"
    elif normalized_style in {"Soft Baddie", "Soft baddie"}:
        normalized_style = "Soft baddie"

    if normalized_style not in VALID_STYLES:
        return make_error_response(422, "VALIDATION_ERROR", f"不支援的妝容風格: '{payload.style}'", False)
    
    try:
        sys_zh, usr_zh = build_gemma3_prompts(face_analysis, normalized_style, payload.userNote, vision_feedback)
        suggestion_part = await call_gemma3_generate(sys_zh, usr_zh)
        
        suggestion_part = suggestion_part.replace("```json", "").replace("```text", "").replace("```", "").strip()
        suggestion_part = suggestion_part.replace("*", "").replace("#", "")

        if "日常自然" in normalized_style:
            flux_prompt_part = (
                "Apply a clean no-makeup makeup look to this person, as a photorealistic makeup-only retouch of the original photo. "
                "Eyes: seamlessly blended soft brown eyeshadow, tight invisible black eyeliner along upper lash roots, defined natural lashes. "
                "Face: flawless natural skin texture with a subtle healthy glow, soft natural blush. "
                "Lips: natural nude pink lips with blurred edges and a slight satin finish."
            )
        elif "Soft baddie" in normalized_style:
            flux_prompt_part = (
                "Apply a soft baddie makeup look to this person, as a photorealistic makeup-only retouch of the original photo.\n\n"
                "Eyes: intense smoky soft brown and dark espresso eyeshadow heavily blended outward, prominent black bold winged cat-eyeliner sharply extended outward and lifted upward at a dramatic angle at the outer corners, warm bronze shimmer on the lid center, bright micro-pearl champagne silver shimmer precisely applied to the inner corners and aegyosal, defined fluttery dense lashes. Brows: cleanly groomed and brushed up, softly filled, polished.\n\n"
                "Face: soft matte skin with a radiant inner glow, subtle warm contour along the cheekbones and jaw, prominent, richly pigmented sun-kissed rosy-mauve blush swept high onto the cheeks and blended intensely towards the temples, an intense, high-shine dewy glass highlighter beaming on the cheekbones and nose bridge.\n\n"
                "Lips: glossy rosy-nude and dusty pink lips with a soft warm undertone, styled with a soft overlined-looking fullness and a heavy wet-shine water-gloss overlay."
            )
        elif "千金" in normalized_style:
            flux_prompt_part = build_luxury_rich_girl_prompt()
        else:
            flux_prompt_part = f"high quality professional {normalized_style} makeup, flawless skin texture, natural soft diffused cosmetics rendering, seamlessly blended edges, highly realistic"

        signature = sign_render_prompt(flux_prompt_part)

        # 對齊組長規格書：不在 Log 印出完整 Prompt，確保資安不外洩
        logger.info("推理完成，順利產生提示詞與簽章。")

        # 5. 對齊組長規格書 3.3 節：回傳標準 JSON 格式
        return {
            "status": "completed",
            "provider": "ollama",
            "model": MODEL_TEXT,
            "fallbackUsed": False,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "suggestion": suggestion_part,
            "fluxPromptEn": flux_prompt_part,
            "renderPromptEn": flux_prompt_part,
            "promptSignature": signature
        }
    except Exception as exc:
        logger.error(f"推理失敗: {str(exc)}")
        return make_error_response(502, "OLLAMA_UNAVAILABLE", f"雙模型推理服務暫時無法使用: {str(exc)}", True)

if __name__ == "__main__":
    enforce_service_api_key()
    uvicorn.run(app, host="0.0.0.0", port=OLLAMA_SUGGESTION_PORT)