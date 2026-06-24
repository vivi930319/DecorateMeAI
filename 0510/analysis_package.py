from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

MAKEUP_DATABASE = {
    "日常自然妝": { # 規格書預設風格
        "description": "充滿呼吸感的自然好氣色，強調透明感與溫潤的鄰家氛圍。",
        "tone": "暖杏蜜桃色系",
        "eye_layers": "先用霧面淺杏色在全眼皮輕盈打底，取帶有微細珠光的蜜桃色在眼窩中央點綴，最後用棕色眼影代替眼線，在眼尾淡淡拉出一道柔和的陰影。",
        "base_detail": "輕薄具緞面光澤的底妝，呈現透亮自然肌膚質感。",
        "lip_detail": "使用帶有水光的茶色調唇釉，疊加在唇部中央並向外暈染，打造澎潤且無邊界的透光唇效。",
        "blush_detail": "選用明亮的蜜桃粉色，大面積地從蘋果肌橫向刷至臉頰兩側。",
        "custom_tip": "著重在自然的毛流感眉毛與捲翹但根根分明的睫毛。"
    },
    "Soft baddie": {
        "description": "更鬆弛自然卻不失辣妹氣場，強調光澤感底妝與煙燻感眼妝。",
        "tone": "肉桂奶油與夢幻藍色系",
        "eye_layers": "先用霧面淺米色在大面積眼窩打底消腫，接著取咖啡棕色的眼影從眼尾向中心暈染三分之一營造深邃感，最後在眼頭點綴星空藍色的打亮，並用黑色眼影稍微加深睫毛根部。",
        "base_detail": "打造精緻的光澤奶油肌，在顴骨最高處點綴帶有藍色偏光的高光，增加金屬感。",
        "lip_detail": "先用肉桂色唇線筆勾勒出邊界清晰的飽滿唇形，再由中心向外疊加同色系霧面唇釉。",
        "blush_detail": "選擇嫩粉色在蘋果肌輕輕打圈。",
        "custom_tip": "利用藍色高光與暖色底妝的對比，創造出前衛且高級的立體光影感。"
    },
    "韓系亞裔妝": {
        "description": "融合韓式清透與亞裔俐落感，展現高級消腫與強調眼部神采的妝效。",
        "tone": "低飽和粉棕系",
        "eye_layers": "先使用灰感粉棕色在整個眼皮進行大面積消腫，接著取冷咖啡色眼影沿著眼尾拉出一條向上的倒三角陰影，眼頭使用霧面米白色提亮。",
        "base_detail": "柔焦感的輕霧面底妝，呈現勻稱精緻的膚色。",
        "lip_detail": "選擇霧面莫蘭迪粉色，先均勻塗抹全唇並模糊邊界，再取深一號色點在唇部中心並用指腹拍開。",
        "blush_detail": "與眼妝色調統一，斜向掃在顴骨下方。",
        "custom_tip": "強調太陽花般的放射狀睫毛與上揚眼線的連結，營造俐落的貓眼感。"
    },
    "日雜清透妝": {
        "description": "充滿呼吸感的自然好氣色，強調透明感與溫潤的鄰家氛圍。",
        "tone": "暖杏蜜桃色系",
        "eye_layers": "先用霧面淺杏色在全眼皮輕盈打底，取帶有微細珠光的蜜桃色在眼窩中央點綴，最後用棕色眼影代替眼線，在眼尾淡淡拉出一道柔和的陰影。",
        "base_detail": "強調清透的奶油肌質感，營造日系少女的微醺透明感。",
        "lip_detail": "使用帶有水光的茶色調唇釉，疊加在唇部中央並向外暈染，打造澎潤且無邊界的透光唇效。",
        "blush_detail": "選用明亮的蜜桃粉色，大面積地從蘋果肌橫向刷至臉頰兩側。",
        "custom_tip": "著重在自然的毛流感眉毛與捲翹但根根分明的睫毛。"
    },
    "千金妝": {
        "description": "高級感、五官立體且乾淨高級的氛圍。",
        "tone": "香檳粉金系",
        "eye_layers": "先以霧面裸粉色輕掃眼皮，再取香檳金珠光點綴在眼皮中央與眼褶，並用深可可色細細勾勒一條細長的上揚眼線，下睫毛處用銀色亮片點綴。",
        "base_detail": "強調無瑕的陶瓷光澤，在額頭、鼻樑與顴骨處疊加珍珠白色的細緻高光。",
        "lip_detail": "先用潤唇膏打底，疊加粉嫩感的水潤唇釉，營造溫柔優雅的水光嘟嘟唇質感。",
        "blush_detail": "選用膨脹色系櫻花粉，斜掃在笑肌上方提升靈動感。",
        "custom_tip": "着重在下睫毛的根根分明，增加眼神的精緻度。"
    },
    "港風妝": {
        "description": "復古90年代明豔對比，成熟大氣。",
        "tone": "復古紅棕色與冷灰色",
        "eye_layers": "先用淺灰色眼影在整個眼窩大範圍打底，再取炭咖啡色眼影沿著睫毛根部向上暈染出半包圍陰影，眼頭與鼻影銜接處要適度加深層次。",
        "base_detail": "陶瓷般的全霧面底妝，刻畫出明顯的立體輪廓。",
        "lip_detail": "先用唇筆精確畫出飽和的正紅色輪廓，填滿霧面大紅色唇膏，展現濃郁的復古氣場。",
        "blush_detail": "低飽和修容色兼作腮紅，銜接鬢角處暈染。",
        "custom_tip": "眉毛要強調濃郁的毛流感，與紅唇形成強烈的色彩視覺對比。"
    },
    "病嬌妝": {
        "description": "日系微醺憂鬱感，楚楚可憐的脆弱美。",
        "tone": "煙燻玫瑰色與淡粉紫色",
        "eye_layers": "先用淡粉色在眼周打底，接著取煙燻玫瑰色大面積暈染下眼瞼營造哭腫感，眼頭與瞳孔下方點綴濕亮感的透明珠光。",
        "base_detail": "追求極致白皙的霧面感，呈現出一種發燒般的微醺紅暈。",
        "lip_detail": "選用深酒紅色，從唇心中間向外進行「咬唇式」疊塗，模糊唇周邊界，展現頹廢質感。",
        "blush_detail": "位置要偏高，直接疊加在眼下位置。",
        "custom_tip": "強調睫毛的濕潤成束感，視覺上增加柔弱且迷人的氣息。"
    }
}

# 規格合約與舊代碼對照表
MAP_FACE = {"oval": "鵝蛋臉", "round": "圓形臉", "square": "方形臉", "oblong": "長形臉", "heart": "心形臉", "diamond": "菱形臉", "trapezoid": "正三角臉", "unknown": "未知臉型"}
MAP_BROW = {"straight": "一字眉", "curved": "彎月眉", "drooping_tail": "落尾眉", "standard": "標準眉", "unknown": "未知眉型"}
MAP_EYE = {"narrow": "長眼", "downturned": "長眼", "round": "圓眼", "slender_phoenix": "長眼", "phoenix": "長眼", "slender": "長眼", "peach_blossom": "雙眼皮", "almond": "雙眼皮", "round_almond": "雙眼皮", "unknown": "未知眼型"}
MAP_NOSE = {"standard": "直鼻", "wide": "寬鼻", "narrow": "短鼻", "unknown": "未知鼻型"}
MAP_LIP = {"full": "厚唇", "thin": "薄唇", "m_shape": "M型唇", "smile": "微笑唇", "petal": "花瓣唇", "unknown": "未知唇型"}
MAP_SEASON = {"spring": "春季型", "summer": "夏季型", "autumn": "秋季型", "winter": "冬季型", "unknown": "未知膚色屬性"}

FACE_LOGIC = {"鵝蛋臉": "比例完美流暢", "菱形臉": "顴骨突出有神", "圓形臉": "雙頰圓潤飽滿", "長形臉": "比例顯得成熟", "正三角臉": "下顎線條分明", "方形臉": "輪廓英氣硬朗", "心形臉": "下巴精緻纖細", "梯形臉": "下顎厚實穩重"}
EYEBROW_LOGIC = {"標準眉": "眉頭眼頭垂直", "一字眉": "眉型平直無邪", "彎月眉": "弧度圓潤溫柔", "落尾眉": "眉尾優雅下落"}
EYE_LOGIC = {"圓眼": "眼神圓潤清澈", "長眼": "眼神嫵媚狹長", "雙眼皮": "褶皺層次分明", "單眼皮": "眼皮厚實有神"}
NOSE_LOGIC = {"直鼻": "鼻樑高挺筆直", "朝天鼻": "鼻尖微翹俏皮", "歪斜鼻": "鼻樑具有個性", "駝峰鼻": "骨感英氣十足", "寬鼻": "鼻翼大氣飽滿", "短鼻": "山根小巧精緻", "蒜頭鼻": "鼻頭肉感親切", "鷹鈎鼻": "鼻尖深邃有型", "未知鼻型": "依照鼻型自然修飾"}
LIP_LOGIC = {"M型唇": "唇峰稜角立體", "花瓣唇": "唇形飽滿豐盈", "微笑唇": "嘴角天然上揚", "厚唇": "唇部感性飽滿", "薄唇": "唇線俐落清秀"}
SKIN_LOGIC = {"春季型": "適合亮暖黃系", "夏季型": "適合冷粉灰系", "秋季型": "適合深邃暖米", "冬季型": "適合對比冷青"}

FACE_METHOD = {"鵝蛋臉": "輕掃下顎線；腮紅斜上暈染；打亮額頭鼻尖。", "菱形臉": "修容顴骨最高點；太陽穴打亮；腮紅銜接修容。", "圓形臉": "從耳際斜下刷修容；腮紅調高拉提；打亮下巴。", "長形臉": "修容額頭頂與下巴底；腮紅橫平刷；打亮眼下。", "正三角臉": "加強下顎陰影；太陽穴打亮擴張；腮紅斜向延伸。", "方形臉": "下頷稜角圓潤修容；蘋果肌打圈腮紅；打亮中心。", "心形臉": "顴骨下方向內收縮；下巴尖端打亮；腮紅斜掃顴骨。", "梯形臉": "下顎兩側收縮；額頭太陽穴打亮；腮紅向斜上延伸。"}
EYEBROW_METHOD = {"標準眉": "順原生毛流填補空隙。", "一字眉": "縮短中庭，眉尾拉平。", "彎月眉": "圓潤轉折，修飾硬朗。", "落尾眉": "眉峰後移，輕輕下撇。"}


class ImageInfo(BaseModel):
    originalName: str
    originalType: str
    originalSize: int
    compressedImageUrl: Optional[str] = None
    compressedDataUrl: Optional[str] = None
    compressedWidth: int
    compressedHeight: int

class LabColor(BaseModel):
    L: float
    a: float
    b: float

class SkinTone(BaseModel):
    season: Literal["spring", "summer", "autumn", "winter", "unknown"]
    level: Optional[str] = None
    lab: Optional[LabColor] = None
    labSource: Optional[str] = None

class Symmetry(BaseModel):
    score: int = Field(..., ge=0, le=100)
    eyeOpenRatio: float
    noseDeviation: float
    mouthSymmetry: float

class FaceAnalysis(BaseModel):
    version: Literal["BASIC", "PRO"]
    faceShape: Literal["oval", "round", "square", "oblong", "heart", "diamond", "trapezoid", "unknown"]
    browShape: Literal["straight", "curved", "drooping_tail", "standard", "unknown"]
    eyeShape: Literal["narrow", "downturned", "round", "slender_phoenix", "phoenix", "slender", "peach_blossom", "almond", "round_almond", "unknown"]
    noseFront: Literal["standard", "wide", "narrow", "unknown"]
    lipShape: Literal["full", "thin", "m_shape", "smile", "petal", "unknown"]
    skinTone: SkinTone
    lipLab: Optional[LabColor] = None
    symmetry: Optional[Symmetry] = None
    noseSide: Optional[str] = None
    sidePhotoUsed: bool = False
    proStatus: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

class GenerativeText(BaseModel):
    status: str = "pending"
    provider: Optional[str] = None
    model: Optional[str] = None
    suggestion: Optional[str] = None
    renderPromptEn: Optional[str] = None
    error: Optional[str] = None

class AnalysisPackage(BaseModel):
    id: str = Field(..., pattern=r"^AN-[a-zA-Z0-9]+$")
    schemaVersion: Literal["2026-06-v1"]
    mode: Literal["BASIC", "PRO"]
    client: Literal["web", "ios"]
    userId: Optional[Any] = None
    status: str
    createdAt: datetime
    updatedAt: datetime
    images: Dict[str, ImageInfo]
    faceAnalysis: FaceAnalysis
    generativeText: GenerativeText
    render: Optional[Dict[str, Any]] = Field(default_factory=dict)
    recommendations: Optional[Dict[str, Any]] = Field(default_factory=dict)

class SuggestRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=()) # 預防 Pydantic 誤判 model 欄位保護區
    analysisPackage: Optional[AnalysisPackage] = None
    faceAnalysis: Optional[FaceAnalysis] = None
    style: str = "日常自然妝"
    language: str = "zh-TW"
    userNote: Optional[str] = None
    model: Optional[str] = None