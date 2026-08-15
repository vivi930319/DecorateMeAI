import os
import sys
import httpx
import logging
import json
import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Optional, Tuple, List
from fastapi import FastAPI, HTTPException, Request, status, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict
import uvicorn

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("ollama-suggestion")

app = FastAPI(title="Ollama 妝容真實個人化修飾服務", version="2026-08-15-Contour-Key-Fix")

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

# ----------------- 英文 Render Prompt 風格控制鏈 -----------------
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

def _deep_search_keys(data: Any, target_keys: set) -> dict:
    found = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if k in target_keys and v is not None and str(v).strip().lower() not in {"null", "none", "undefined", "未提供", ""}:
                found[k] = str(v).strip()
            if isinstance(v, (dict, list)):
                found.update(_deep_search_keys(v, target_keys))
    elif isinstance(data, list):
        for item in data:
            found.update(_deep_search_keys(item, target_keys))
    return found

def build_gemma3_json_prompts(payload_dict: dict, style: str, user_note: Optional[str], vision_feedback: str) -> Tuple[str, str, bool, List[str]]:
    search_keys = {
        "faceShape", "臉型",
        "browShape", "眉型",
        "eyeShape", "眼型",
        "noseFront", "noseSide", "noseShape", "鼻型",
        "lipShape", "嘴型", "唇型",
        "season", "level", "skinTone", "膚色", "四季型", "膚色分級"
    }

    extracted = _deep_search_keys(payload_dict, search_keys)
    logger.info(f"🔍 [五官提取結果]: {json.dumps(extracted, ensure_ascii=False)}")

    f_shape = extracted.get("faceShape") or extracted.get("臉型")
    b_shape = extracted.get("browShape") or extracted.get("眉型")
    e_shape = extracted.get("eyeShape") or extracted.get("眼型")
    n_shape = extracted.get("noseFront") or extracted.get("noseSide") or extracted.get("noseShape") or extracted.get("鼻型")
    l_shape = extracted.get("lipShape") or extracted.get("嘴型") or extracted.get("唇型")
    s_season = extracted.get("season") or extracted.get("四季型") or extracted.get("膚色")

    missing_fields = []
    if not f_shape: missing_fields.append("faceShape")
    if not b_shape: missing_fields.append("browShape")
    if not e_shape: missing_fields.append("eyeShape")
    if not n_shape: missing_fields.append("noseShape")
    if not l_shape: missing_fields.append("lipShape")
    if not s_season: missing_fields.append("skinTone.season")

    face_analysis_used = len(missing_fields) < 5

    f_str = f"臉型：{f_shape}" if f_shape else f"根據相片輪廓修飾臉型（搭配{style}）"
    b_str = f"眉型：{b_shape}" if b_shape else f"根據原生眉骨梳理眉型（搭配{style}）"
    e_str = f"眼型：{e_shape}" if e_shape else f"根據眼窩結構刻畫眼型（搭配{style}）"
    n_str = f"鼻型：{n_shape}" if n_shape else f"根據鼻樑山根修容鼻型（搭配{style}）"
    l_str = f"唇型：{l_shape}" if l_shape else f"根據唇形飽滿度優化唇妝（搭配{style}）"
    s_str = f"膚色季型：{s_season}" if s_season else f"根據原生膚色調配底妝（搭配{style}）"

    # 🚀【更新：在系統提示詞中嚴格規範 parts 必須包含 6 大部位（含 contour）】
    system_prompt = (
        "你是一位高階明星御用彩妝顧問。請根據傳入的使用者特徵與目標風格，輸出極具個人化、具體可執行的彩妝建議 JSON。\n\n"
        "【輸出規範與鐵律】\n"
        "1. 必須嚴格輸出合法的單一 JSON 物件，不得包含 any 思考過程或 Markdown 標籤。\n"
        "2. 嚴禁使用『寶寶』、『親愛的』等客套用語，語氣保持客觀、專業、技術導向。\n"
        "3. 嚴禁使用『資料不足』、『通用方式建議』這種字眼！請直接依據特徵數據與風格撰寫專業修飾手法。\n"
        "4. parts 欄位必須嚴格包含以下六個鍵：base, eyebrow, eyes, contour, cheeks, lips。\n"
        "5. analysis 欄位：明確寫出該部位的特徵分析與修飾目標。\n"
        "6. steps 欄位：給出具體、有技術細節的操作步驟（包含毫米 mm、彩妝色系、質地與暈染方向），每個步驟 25–45 字。\n"
        "7. 每個部位包含 2 個具體步驟，avoid 陣列包含 1 個明確避免事項。\n"
        "8. 嚴禁產生任何品牌名稱。\n\n"
        "【JSON 輸出結構範例】\n"
        "{\n"
        '  "overall": {\n'
        '    "summary": "針對原生骨相優化，打造高對比且極具質感的妝效。"\n'
        '  },\n'
        '  "parts": {\n'
        '    "base": {\n'
        '      "analysis": "臉型：鵝蛋臉（輪廓流暢，加強面中立體度）",\n'
        '      "steps": [\n'
        '        "選用高遮瑕霧面粉底液，由面中向外均勻拍開，建立無瑕底妝。",\n'
        '        "利用輕薄蜜粉按壓T字部位，維持全天清爽持妝。"\n'
        '      ],\n'
        '      "avoid": ["避免粉底色號過白產生面具感。"]\n'
        '    },\n'
        '    "eyebrow": {\n'
        '      "analysis": "眉型：彎月眉（弧度柔和，需拉長眉尾線條）",\n'
        '      "steps": [\n'
        '        "順著原生毛流使用深棕色眉筆補強眉峰結構，創造向上微挑英氣感。",\n'
        '        "眉尾拉長 2–3 mm 並收細，使用定型眉膠梳理出根根分明毛流。"\n'
        '      ],\n'
        '      "avoid": ["避免將眉頭填得過滿過黑，保持自然漸層感。"]\n'
        '    },\n'
        '    "eyes": {\n'
        '      "analysis": "眼型：圓眼（眼窩深邃，強化眼尾平拉）",\n'
        '      "steps": [\n'
        '        "用深棕色眼線液填滿上睫毛根部，眼尾順著眼型平拉延伸 3 mm 後微微上揚。",\n'
        '        "大地色眼影於眼窩重度暈染，眼尾三角區加深，打造深邃眼窩。"\n'
        '      ],\n'
        '      "avoid": ["避免畫過粗的下眼線，以免眼神顯得死板僵硬。"]\n'
        '    },\n'
        '    "contour": {\n'
        '      "analysis": "修容：針對面中與下顎線進行立體骨相收斂",\n'
        '      "steps": [\n'
        '        "使用灰棕色修容粉自山根向鼻尖兩側輕掃，縮窄鼻翼並拔高鼻樑。",\n'
        '        "由下顎角向內沿著下巴輪廓輕掃陰影，強化臉部俐落線條。"\n'
        '      ],\n'
        '      "avoid": ["避免使用偏紅棕色調修容，防止顯髒。"]\n'
        '    },\n'
        '    "cheeks": {\n'
        '      "analysis": "膚色季型：暖色調（需斜向提亮蘋果肌）",\n'
        '      "steps": [\n'
        '        "選擇低飽和陶土橘粉色腮紅，從顴骨最高點向太陽穴方向斜向暈染。",\n'
        '        "餘粉輕帶過鼻樑中段，增加整體妝容的和煦血色感。"\n'
        '      ],\n'
        '      "avoid": ["避免將腮紅打在低於鼻翼的位置，防止臉部視覺下垂。"]\n'
        '    },\n'
        '    "lips": {\n'
        '      "analysis": "唇型：薄唇（需擴畫唇峰增加豐滿度）",\n'
        '      "steps": [\n'
        '        "使用唇線筆稍微向外擴畫唇峰，打造豐滿飽滿的唇形。",\n'
        '        "填滿濃郁絨霧唇膏，邊緣用棉花棒微暈染呈現高級質感。"\n'
        '      ],\n'
        '      "avoid": ["避免使用過度黏膩厚重的唇蜜。"]\n'
        '    }\n'
        '  }\n'
        "}"
    )

    user_prompt = (
        f"目標風格：{style}\n"
        f"使用者偏好：{user_note if user_note else '無特別要求'}\n"
        f"已知分析特徵：\n"
        f"- {f_str}\n"
        f"- {b_str}\n"
        f"- {e_str}\n"
        f"- {n_str}\n"
        f"- {l_str}\n"
        f"- {s_str}\n\n"
        f"視覺提取細節：{vision_feedback}\n\n"
        f"請立刻輸出嚴格包含 base, eyebrow, eyes, contour, cheeks, lips 的純繁體中文 JSON 物件。"
    )

    return system_prompt, user_prompt, face_analysis_used, missing_fields

async def call_gemma3_generate_json(system_instruction: str, user_prompt: str) -> dict:
    url = f"{OLLAMA_BASE_URL}/api/generate"
    full_combined_prompt = f"{system_instruction}\n\n[Current Request]:\n{user_prompt}"

    payload = {
        "model": MODEL_TEXT,
        "prompt": full_combined_prompt,
        "format": "json",
        "stream": False,
        "options": {
            "num_predict": OLLAMA_NUM_PREDICT,
            "temperature": 0.3,
            "top_p": 0.85
        }
    }

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        get_res = await client.post(url, json=payload)
        if get_res.status_code != 200:
            raise RuntimeError(f"{MODEL_TEXT} Server 異常: {get_res.status_code}")

        raw_response = get_res.json().get("response", "").strip()
        try:
            parsed = json.loads(raw_response)
        except json.JSONDecodeError:
            clean_str = raw_response.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean_str)

        # 🚀【防呆安全保護】：確保 parts 物件下 6 個 key 絕對存在
        if not isinstance(parsed, dict):
            parsed = {}
        if "overall" not in parsed:
            parsed["overall"] = {"summary": "針對原生特徵與骨相進行客製化修飾。"}
        if "parts" not in parsed or not isinstance(parsed.get("parts"), dict):
            parsed["parts"] = {}

        parts = parsed["parts"]
        required_parts = {
            "base": ("底妝修飾", "打造服貼薄透底妝，均勻全臉膚色。"),
            "eyebrow": ("眉型修飾", "順著原生毛流描繪自然眉型。"),
            "eyes": ("眼妝修飾", "加深眼尾陰影，搭配細緻內眼線放大雙眼。"),
            "contour": ("輪廓修容", "於山根及下顎線輕掃灰棕色陰影修飾輪廓。"),
            "cheeks": ("腮紅修飾", "於蘋果肌輕掃提亮腮紅增加自然氣色。"),
            "lips": ("唇部修飾", "塗抹水潤唇膏並微暈染唇周邊界。")
        }

        for key, (default_analysis, default_step) in required_parts.items():
            if key not in parts or not isinstance(parts[key], dict):
                parts[key] = {
                    "analysis": default_analysis,
                    "steps": [default_step],
                    "avoid": ["避免手法過重導致妝感不均。"]
                }

        return parsed

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
        "ollama": {"reachable": ollama_reachable, "model": MODEL_TEXT},
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

    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        res = await client.post(url, json=payload)
        if res.status_code != 200:
            raise RuntimeError(f"Llava Vision Server 異常: {res.status_code}")
        return res.json().get("response", "").strip()

@app.post("/suggest")
async def suggest(request: Request, payload: SuggestRequest, x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    if not verify_api_key(x_api_key):
        return make_error_response(401, "UNAUTHORIZED", "Invalid or missing API key", False)

    try:
        raw_body = await request.json()
    except Exception:
        raw_body = payload.model_dump()

    analysis_pkg = payload.analysisPackage or {}
    images_obj = analysis_pkg.get("images", {})
    front_image_obj = images_obj.get("front", {})
    base64_image_url = front_image_obj.get("compressedDataUrl")

    if not base64_image_url:
        vision_feedback = "No image context provided. Rely solely on structured parameters."
    else:
        try:
            vision_feedback = await extract_image_features_with_llava(base64_image_url)
        except Exception:
            vision_feedback = "Vision analysis timed out."

    normalized_style = payload.style.strip()
    if normalized_style in {"韓系亞裔", "日雜清透", "千金", "港風", "病嬌", "男士白開水"}:
        if not normalized_style.endswith("妝") and normalized_style != "男士白開水":
            normalized_style = f"{normalized_style}妝"
    elif normalized_style in {"Soft Baddie", "Soft baddie"}:
        normalized_style = "Soft baddie"

    try:
        # 1. 產生包含 contour 在內的完整 6 大部位建議 JSON
        sys_zh, usr_zh, face_analysis_used, missing_fields = build_gemma3_json_prompts(
            raw_body, normalized_style, payload.userNote, vision_feedback
        )
        suggestion_json = await call_gemma3_generate_json(sys_zh, usr_zh)

        # 2. 匹配專屬風格英文 Prompt 控制鏈
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

        logger.info(f"推理完成！回傳包含 6 大部位 (含 contour) 之建議與英文簽章 (faceAnalysisUsed={face_analysis_used})。")

        return {
            "status": "completed",
            "provider": "ollama",
            "model": MODEL_TEXT,
            "fallbackUsed": False,
            "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "faceAnalysisUsed": face_analysis_used,
            "missingFields": missing_fields,
            "suggestion": suggestion_json,
            "renderPromptEn": flux_prompt_part,
            "fluxPromptEn": flux_prompt_part,
            "promptSignature": signature
        }
    except Exception as exc:
        logger.error(f"推理失敗: {str(exc)}")
        return make_error_response(502, "OLLAMA_UNAVAILABLE", f"文字建議服務目前無法連線，請稍後再試: {str(exc)}", True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=OLLAMA_SUGGESTION_PORT)