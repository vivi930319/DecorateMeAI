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

app = FastAPI(title="Ollama 妝容真實個人化修飾服務", version="2026-08-06-JSON-Structured")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUGGESTION_API_KEY = os.getenv("SUGGESTION_API_KEY", "").strip()
SIGNING_SECRET = os.getenv("RENDER_PROMPT_SIGNING_SECRET", "").strip()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"

if IS_PRODUCTION and not SUGGESTION_API_KEY:
    logger.error("正式環境（ENVIRONMENT=production）未設定 SUGGESTION_API_KEY，服務拒絕啟動。")
    sys.exit(1)

if IS_PRODUCTION:
    ALLOWED_KEYS = {SUGGESTION_API_KEY}
else:
    ALLOWED_KEYS = {
        SUGGESTION_API_KEY,
        "tku_im_makeup_secret_2026",
        "my_super_secret_ollama_key_2026_tku_im"
    }
ALLOWED_KEYS = {k for k in ALLOWED_KEYS if k}

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
MODEL_TEXT = os.getenv("OLLAMA_MODEL", "gemma3")
MODEL_VISION = os.getenv("MODEL_VISION", "llava:latest")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120.0"))
OLLAMA_NUM_PREDICT = int(os.getenv("OLLAMA_NUM_PREDICT", "4096"))
OLLAMA_SUGGESTION_PORT = int(os.getenv("OLLAMA_SUGGESTION_PORT", "8010"))

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
    if not x_api_key:
        logger.warning("Gateway 送來請求，但未帶 X-API-Key Header。")
        return False

    for valid_key in ALLOWED_KEYS:
        if hmac.compare_digest(valid_key.encode("utf-8"), x_api_key.encode("utf-8")):
            return True

    logger.warning("傳入的 X-API-Key 不在允許清單中，拒絕請求。")
    return False

def sign_render_prompt(render_prompt_en: str) -> Optional[str]:
    if not SIGNING_SECRET:
        return None
    return hmac.new(
        SIGNING_SECRET.encode("utf-8"),
        render_prompt_en.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

# ----------------- 英文 Render Prompt 風格函式組 -----------------
def build_luxury_rich_girl_prompt() -> str:
    return (
        "Apply a luxurious elegant makeup look to the face, as a photorealistic makeup-only retouch of the original photo.\n\n"
        "Eyes: highly visible, bold and significantly thickened jet-black eyeliner that dynamically extends straight and long past the outer corner of the eyes with a subtle elegant lift, "
        "vivid and heavy shading of romantic sakura pink-apricot and soft rose-taupe tones heavily sweeping across the entire eye sockets and lower crease, "
        "a concentrated, rich dark cherry-brown shadow heavily packed right at the base of the lash roots for extreme depth, "
        "highly defined, hyper-plump and three-dimensional aegyosal (charming fat) carved with a soft shadow underline, with an intense, high-contrast crystalline pink-diamond champagne shimmer that strongly illuminates the inner eye corners and the exact center of the three-dimensional aegyosal, "
        "extremely long, perfectly curled, and sharply separated spiky mascaraed eyelashes creating a defined doll-like sunflower effect with long individual lash clusters extending from both upper and lower lash lines, slightly rounded inner eye corners.\n\n"
        "Brows: thin, straight, and elongated delicate brows softly filled with light brown powder and brow mascara.\n\n"
        "Face: dewy satin skin texture with refined light brown contouring along the nose bridge and jawline, prominent, highly pigmented soft pastel pink and vivid sakura-pink blush heavily swept horizontally across the cheeks below the pupils towards the cheekbones, seamlessly layered with vivid strawberry-pink blush boldly on the apples of the cheeks creating an intensely romantic rosy-pink flush; clear, hyper-reflective wet-shine dewy highlighters precisely dotted on the bridge of the nose, nose tip, highest points of the cheeks, cupid's bow, and chin.\n\n"
        "Lips: full lips defined with a lip liner to softly blur the outer boundaries, completely filled with a clear glossy vibrant pink glass lip glaze over a concealed lip base."
    )

def build_hong_kong_glam_prompt() -> str:
    return (
        "Apply a classic 1990s Hong Kong cinema glam makeup look to the face, as a photorealistic makeup-only retouch of the original photo.\n\n"
        "Face: ultra-clean, flawless matte velvet skin texture with smooth porcelain clarity and zero unwanted shine, softly carved with sophisticated warm dark brown contouring along the nose bridge, cheekbones, and jawline, subtle warm terracotta blush seamlessly diffused into the cheek contours.\n\n"
        "Eyes: deep smoky earth-tone brown eyeshadow heavily blended across the eye sockets and lower crease for intense structural depth, a sharp, clean jet-black retro eyeliner drawn tight along the lash line and softly winging upward at the outer corners, fluttery dense black mascaraed eyelashes defining both lash lines.\n\n"
        "Brows: dark, dense, and naturally sculpted dark brown-black eyebrows with clear hair-like texture and defined arches.\n\n"
        "Lips: richly pigmented, full classic vintage red lips with a smooth velvet-matte finish and soft blurred lip contours."
    )

def build_korean_abg_prompt() -> str:
    return (
        "Apply a trendy Korean Asian Baby Girl (ABG) instagram-style makeup look to the face, as a photorealistic makeup-only retouch of the original photo.\n\n"
        "Brows: sharply arched and lifted dark brown eyebrows with voluminous, feathery hair-like strokes highlighting high brow bones.\n\n"
        "Eyes: almond-shaped feline eye structure with delicate inner corner detailing, shaded with soft light brown and warm taupe eyeshadow framing the lower crease, "
        "an ultra-sleek, razor-thin liquid jet-black eyeliner precisely drawn ultra-thin along the upper lash line and dynamically extended long, sharp, and straight past the outer eye corners with a fierce elegant upward flick, "
        "elongated, sharply separated spiky manga-style eyelashes defining both lash lines to accentuate the dramatically lengthened eyes.\n\n"
        "Face: sun-kissed soft matte skin with glowing highlights, precise subtle nose contouring under the brow bones, "
        "warm nude-apricot and peach-pink blush swept diagonally upward along the cheekbones towards the temples for a lifted face structure; clear wet-shine highlighter accenting the nose bridge, nose tip, and inner eye corners.\n\n"
        "Lips: plump, juicy, full lips softly overlined with a nude-pink liner, completely filled with a clear glossy peachy-nude water lip gloss."
    )

def build_men_clean_water_prompt() -> str:
    return (
        "Apply a ultra-clean no-makeup natural groom look for men to the face, as a photorealistic natural retouch of the original photo.\n\n"
        "Face: ultra-clean, flawless natural matte masculine skin texture with refined smoothness, zero unwanted shine, subtle healthy skin glow, and microscopic skin detail; delicate, invisible contouring along the nose bridge and jawline for structural masculine depth.\n\n"
        "Brows: naturally full, neat, and well-groomed dark male eyebrows with distinct, clear hair strokes and masculine straight arches.\n\n"
        "Eyes: completely clean and natural eyes, strictly zero eyeshadow, zero eyeliner, and zero visible eye cosmetics, leaving pure realistic eyes with natural lash lines.\n\n"
        "Lips: healthy natural nude male lips with soft hydrated texture, subtle lip moisture, strictly zero visible lipstick or lip gloss color."
    )

def build_sick_cute_yandere_prompt() -> str:
    return (
        "Apply a subtle sick-cute yandere e-girl style makeup look to the face, as a photorealistic makeup-only retouch of the original photo.\n\n"
        "Eyes: a prominent, continuous jet-black full-encircling eyeliner precisely tightlining both upper lash line and lower waterline, "
        "with a sharply defined, downward-pointing inner corner eyeliner flick extending the eyes, "
        "heavy shading of muted smoky dusty-rose, warm terracotta-brown, and dried-rose tones sweeping across the lower eyelids and lower crease for a melancholic flushed shadow, "
        "defined spiky lower lash clusters framing the dark encircled eyes.\n\n"
        "Face: pale porcelain smooth skin with a clear fair complexion, soft muted dusty-rose blush heavily diffused directly under the lower eyes blending into the cheekbones.\n\n"
        "Brows: soft, thin, straight dark brown-black delicate eyebrows.\n\n"
        "Lips: full lips completely filled with a watery clear glossy dusty-rose glass lip glaze, creating a high-shine reflective wet lip finish with softly blurred outer lip boundaries."
    )

def build_japanese_translucent_prompt() -> str:
    return (
        "Apply a Japanese magazine model beauty style makeup look to the face, as a photorealistic makeup-only retouch of the original photo.\n\n"
        "Eyes: defined, highly visible jet-black upper eyeliner extending slightly at the outer corners, long, dramatically curled, and sharply separated spiky mascaraed eyelashes defining both lash lines, bright crystalline champagne shimmer strongly illuminating the inner corners and plump three-dimensional aegyosal (charming fat), soft peach-coral eyeshadow shading the eye sockets.\n\n"
        "Face: dewy porcelain skin with high-shine wet glass highlights, heavy Igari-style fresh strawberry-pink and vibrant coral blush boldly swept horizontally directly across the under-eye area, cheekbones, and nose bridge creating a vivid flushed aesthetic.\n\n"
        "Brows: neatly defined, feathery, dark brown eyebrows with distinct upward-groomed hair texture.\n\n"
        "Lips: plump, juicy strawberry-nude lips completely coated in a thick, clear high-shine water-gloss glass lip glaze."
    )

def make_error_response(http_code: int, code: str, message: str, retryable: bool):
    return JSONResponse(
        status_code=http_code,
        content={"error": {"code": code, "message": message, "retryable": retryable}}
    )

@app.middleware("http")
async def limit_payload_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        return make_error_response(413, "PAYLOAD_TOO_LARGE", "上傳的資料過大，請縮小檔案後再試。", False)
    return await call_next(request)

if not IS_PRODUCTION:
    @app.middleware("http")
    async def log_incoming_headers(request: Request, call_next):
        if request.url.path == "/suggest":
            header_names = list(request.headers.keys())
            logger.info(f"[DEBUG 偵測] /suggest 收到的所有 Header 名稱: {header_names}")
            for possible_name in ["x-api-key", "x_api_key", "apikey", "api-key", "authorization"]:
                if possible_name in [h.lower() for h in header_names]:
                    logger.info(f"[DEBUG 偵測] 發現疑似金鑰相關 Header: '{possible_name}'（但可能非標準名稱 X-API-Key）")
        return await call_next(request)

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
        "api_key_required": True,
        "api_key_configured": bool(SUGGESTION_API_KEY)
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

def build_gemma3_json_prompts(face_analysis: dict, style: str, user_note: Optional[str], vision_feedback: str) -> Tuple[str, str]:
    """
    依照組長規範建立全 JSON 結構化 Prompt
    要點：
    1. 不提及「寶寶」、無贅字、無浮誇詞彙（如重塑、整形）。
    2. 無資料時顯式寫出「資料不足」。
    3. 禁止產生商業品牌名稱。
    4. 回傳格式嚴格為 JSON。
    """
    def is_valid_value(val: Any) -> bool:
        if not val:
            return False
        val_str = str(val).strip()
        return val_str not in {"", "未提供", "None", "null", "undefined"}

    f_shape = face_analysis.get('臉型') if is_valid_value(face_analysis.get('臉型')) else "資料不足"
    b_shape = face_analysis.get('眉型') if is_valid_value(face_analysis.get('眉型')) else "資料不足"
    e_shape = face_analysis.get('眼型') if is_valid_value(face_analysis.get('眼型')) else "資料不足"
    n_front = face_analysis.get('鼻型') if is_valid_value(face_analysis.get('鼻型')) else "資料不足"
    l_shape = face_analysis.get('嘴型') if is_valid_value(face_analysis.get('嘴型')) else "資料不足"

    s_season = "資料不足"
    skin_obj = face_analysis.get('膚色')
    if isinstance(skin_obj, dict):
        if is_valid_value(skin_obj.get('四季型')):
            s_season = str(skin_obj.get('四季型')).strip()
    elif is_valid_value(skin_obj):
        s_season = str(skin_obj).strip()

    system_prompt = (
        "你是一位專業彩妝顧問。請根據傳入的使用者特徵資料與目標風格，輸出結構化的繁體中文彩妝建議 JSON。\n\n"
        "【輸出規範與鐵律】\n"
        "1. 必須嚴格輸出合法的單一 JSON 物件，不得包含 any 思考過程、開頭結尾客套話或 Markdown 標籤。\n"
        "2. 嚴禁使用『寶寶』、『親愛的』等客套用語，語氣保持客觀、專業、可執行。\n"
        "3. 嚴禁使用『整形』、『徹底重塑』等誇張詞彙。\n"
        "4. 嚴禁產生任何彩妝商品品牌名稱（如 1028、KATE、SOFINA 等）。\n"
        "5. 若部位資料為『資料不足』，請於 analysis 欄位顯式說明『目前[部位]資料不足，以[目標風格]的通用方式建議。』\n"
        "6. 步驟（steps）必須為可執行的具體動作，每個步驟控制在 20–45 字。\n"
        "7. 每個部位的 steps 陣列包含 2–3 個步驟，avoid 陣列包含 1–2 個避免事項。\n\n"
        "【JSON 輸出範例結構】\n"
        "{\n"
        '  "overall": {\n'
        '    "summary": "風格整體概述（約 30 字）"\n'
        '  },\n'
        '  "parts": {\n'
        '    "base": {\n'
        '      "analysis": "臉型：圓臉；鼻型：資料不足",\n'
        '      "steps": [\n'
        '        "底妝採用輕薄霧面粉底，均勻塗抹於全臉。",\n'
        '        "修容餅掃於兩頰外側與下巴輪廓線，打造收斂效果。"\n'
        '      ],\n'
        '      "avoid": ["避免過度使用亮面高光提亮全臉。"]\n'
        '    },\n'
        '    "eyebrow": {\n'
        '      "analysis": "眉型資料不足，以通用方式建議",\n'
        '      "steps": [\n'
        '        "使用眉粉填補眉毛空隙，順著毛流梳理。",\n'
        '        "眉尾適度拉長，維持自然弧度。"\n'
        '      ],\n'
        '      "avoid": ["避免畫成線條僵硬的粗平眉。"]\n'
        '    },\n'
        '    "eyes": {\n'
        '      "analysis": "眼型：杏眼",\n'
        '      "steps": [\n'
        '        "眼線填滿睫毛根部，眼尾平拉微微上揚 2 mm。",\n'
        '        "深色眼影集中在眼尾斜上方暈染。"\n'
        '      ],\n'
        '      "avoid": ["避免眼尾向下延伸，以免眼神疲憊。"]\n'
        '    },\n'
        '    "cheeks": {\n'
        '      "analysis": "膚色季型：暖色調",\n'
        '      "steps": [\n'
        '        "腮紅從蘋果肌向顴骨斜上方大面積輕掃。",\n'
        '        "餘粉微量刷於鼻頭增加氣色。"\n'
        '      ],\n'
        '      "avoid": ["避免腮紅位置低於鼻翼下緣。"]\n'
        '    },\n'
        '    "lips": {\n'
        '      "analysis": "唇型：薄唇",\n'
        '      "steps": [\n'
        '        "使用唇線筆微幅向外擴畫唇形邊界。",\n'
        '        "塗抹水光唇釉於唇心並向外暈染。"\n'
        '      ],\n'
        '      "avoid": ["避免使用深色霧面唇膏讓唇部顯薄。"]\n'
        '    }\n'
        '  }\n'
        "}"
    )

    user_prompt = (
        f"目標妝容風格：{style}\n"
        f"偏好與備註：{user_note if user_note else '無特別要求'}\n"
        f"已知分析數據：\n"
        f"- 臉型：{f_shape}\n"
        f"- 眉型：{b_shape}\n"
        f"- 眼型：{e_shape}\n"
        f"- 鼻型：{n_front}\n"
        f"- 唇型：{l_shape}\n"
        f"- 膚色：{s_season}\n\n"
        f"相片視覺提取細節：{vision_feedback}\n\n"
        f"請立刻輸出符合上述結構與限制條件的純繁體中文 JSON 物件。"
    )

    return system_prompt, user_prompt

async def call_gemma3_generate_json(system_instruction: str, user_prompt: str) -> dict:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    full_combined_prompt = f"{system_instruction}\n\n[Current Request]:\n{user_prompt}"

    payload = {
        "model": MODEL_TEXT,
        "prompt": full_combined_prompt,
        "format": "json",  # 強制 Ollama 開啟 JSON Mode
        "stream": False,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": 0.2,
            "top_p": 0.8
        }
    }

    logger.info(f"呼叫 {MODEL_TEXT} 進行 JSON 結構化彩妝推理...")
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        get_res = await client.post(url, json=payload)
        if get_res.status_code != 200:
            raise RuntimeError(f"{MODEL_TEXT} Server 異常: {get_res.status_code}")
        
        raw_response = get_res.json().get("response", "").strip()
        try:
            # 嘗試解析 JSON，確保回傳合法的 JSON 物件
            return json.loads(raw_response)
        except json.JSONDecodeError:
            logger.warning("模型回傳含有額外字串，執行清理...")
            clean_str = raw_response.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_str)

@app.post("/suggest")
async def suggest(payload: SuggestRequest, x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if not verify_api_key(x_api_key):
        logger.warning("驗證失敗：拒絕 /suggest 請求 (HTTP 401)")
        return make_error_response(401, "UNAUTHORIZED", "Invalid or missing API key", False)

    logger.info("金鑰驗證成功！開始執行彩妝推理流水線...")

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
        # 1. 產生 JSON 結構化中文建議
        sys_zh, usr_zh = build_gemma3_json_prompts(face_analysis, normalized_style, payload.userNote, vision_feedback)
        suggestion_json = await call_gemma3_generate_json(sys_zh, usr_zh)

        # 2. 匹配專屬風格之英文 Render Prompt
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
        elif "港風" in normalized_style:
            flux_prompt_part = build_hong_kong_glam_prompt()
        elif "韓系" in normalized_style or "韓式亞裔" in normalized_style:
            flux_prompt_part = build_korean_abg_prompt()
        elif "男士白開水" in normalized_style:
            flux_prompt_part = build_men_clean_water_prompt()
        elif "病嬌" in normalized_style:
            flux_prompt_part = build_sick_cute_yandere_prompt()
        elif "日雜清透" in normalized_style:
            flux_prompt_part = build_japanese_translucent_prompt()
        else:
            flux_prompt_part = f"high quality professional {normalized_style} makeup, flawless skin texture, natural soft diffused cosmetics rendering, seamlessly blended edges, highly realistic"

        signature = sign_render_prompt(flux_prompt_part)

        logger.info("推理完成，順利產生 JSON 結構化建議與簽章。")

        return {
            "status": "completed",
            "provider": "ollama",
            "model": MODEL_TEXT,
            "fallbackUsed": False,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "suggestion": suggestion_json,  # 直接回傳結構化 JSON，前端可零代價轉換卡片
            "renderPromptEn": flux_prompt_part,
            "fluxPromptEn": flux_prompt_part,
            "promptSignature": signature
        }
    except Exception as exc:
        logger.error(f"推理失敗: {str(exc)}")
        return make_error_response(502, "OLLAMA_UNAVAILABLE", f"文字建議服務目前無法連線，請稍後再試: {str(exc)}", True)

if __name__ == "__main__":
    if not IS_PRODUCTION and not SUGGESTION_API_KEY:
        logger.warning("開發模式：未設定 SUGGESTION_API_KEY，啟用內建相容金鑰清單。正式環境部署時必須設定此變數，否則服務會拒絕啟動。")
    uvicorn.run(app, host="0.0.0.0", port=OLLAMA_SUGGESTION_PORT)