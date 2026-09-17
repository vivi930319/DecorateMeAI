"""Color evidence contract. Website sRGB is not a physical pigment measurement."""
import math
import re

VERSION = 'srgb-d65-2026-09-v1'

def lab_from_hex(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', str(value or '')):
        return None
    return lab_from_rgb(*[int(value[i:i+2],16) for i in (1,3,5)])

def lab_from_rgb(red,green,blue):
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or not 0<=v<=255 for v in (red,green,blue)):
        raise ValueError('sRGB channels must be finite values in 0..255')
    rgb=[v/255 for v in (red,green,blue)]
    r,g,b=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in rgb]
    xyz=((r*.4124564+g*.3575761+b*.1804375)/.95047,
         r*.2126729+g*.7151522+b*.0721750,
         (r*.0193339+g*.1191920+b*.9503041)/1.08883)
    d=6/29
    x,y,z=[v**(1/3) if v>d**3 else v/(3*d*d)+4/29 for v in xyz]
    return [round(116*y-16,6),round(500*(x-y),6),round(200*(y-z),6)]

def delta_e(lab1, lab2):
    """Return CIEDE2000 ΔE (not the older CIE76 Euclidean distance).

    比色是色彩契約的一部分，因此和 sRGB→CIELAB 轉換放在同一個模組；
    推薦與商品 API 都從這裡取用同一份實作，避免兩邊各算各的。
    """
    if not lab1 or not lab2:
        return None
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1 = math.hypot(a1, b1)
    c2 = math.hypot(a2, b2)
    c_bar = (c1 + c2) / 2.0
    g = 0.5 * (1.0 - math.sqrt((c_bar ** 7) / (c_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1.0 + g) * a1, (1.0 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)

    def hue(a, b):
        return math.degrees(math.atan2(b, a)) % 360.0 if a or b else 0.0

    h1p, h2p = hue(a1p, b1), hue(a2p, b2)
    delta_lp, delta_cp = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        delta_hp = 0.0
    else:
        delta_h = h2p - h1p
        if delta_h > 180:
            delta_h -= 360
        elif delta_h < -180:
            delta_h += 360
        delta_hp = 2.0 * math.sqrt(c1p * c2p) * math.sin(math.radians(delta_h / 2.0))

    l_bar, cp_bar = (l1 + l2) / 2.0, (c1p + c2p) / 2.0
    if c1p * c2p == 0:
        hp_bar = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hp_bar = (h1p + h2p) / 2.0
    elif h1p + h2p < 360:
        hp_bar = (h1p + h2p + 360) / 2.0
    else:
        hp_bar = (h1p + h2p - 360) / 2.0
    t = (1 - 0.17 * math.cos(math.radians(hp_bar - 30))
         + 0.24 * math.cos(math.radians(2 * hp_bar))
         + 0.32 * math.cos(math.radians(3 * hp_bar + 6))
         - 0.20 * math.cos(math.radians(4 * hp_bar - 63)))
    delta_theta = 30 * math.exp(-((hp_bar - 275) / 25) ** 2)
    rc = 2 * math.sqrt((cp_bar ** 7) / (cp_bar ** 7 + 25.0 ** 7))
    sl = 1 + (0.015 * (l_bar - 50) ** 2) / math.sqrt(20 + (l_bar - 50) ** 2)
    sc = 1 + 0.045 * cp_bar
    sh = 1 + 0.015 * cp_bar * t
    rt = -math.sin(math.radians(2 * delta_theta)) * rc
    return math.sqrt((delta_lp / sl) ** 2 + (delta_cp / sc) ** 2 + (delta_hp / sh) ** 2
                     + rt * (delta_cp / sc) * (delta_hp / sh))


def is_transparent(shade):
    return bool(re.search(r'透明|無色|\bclear\b|\btransparent\b',str(shade or ''),re.I))

def palette_size(name):
    match=re.search(r'(雙|三|四|五|六|九|十二|十六|十|\d+)色.{0,8}(?:盤|眼影)',str(name or ''))
    if match:
        return {'雙':2,'三':3,'四':4,'五':5,'六':6,'九':9,'十':10,'十二':12,'十六':16}.get(match[1], int(match[1]) if match[1].isdigit() else 0)
    return 0

def color_warning(representation, valid, palette_complete):
    """未通過數值驗證的理由各不相同，警語要講對，不能一律說「尚未驗證」。"""
    if valid:
        return None
    if representation == 'transparent':
        # 透明商品不是還沒驗證，是本來就沒有顏色。
        return None
    if representation == 'palette':
        return None if palette_complete else '色盤尚有格子未取得官方色值。'
    if representation == 'official_name_only':
        return '官方未公布數值色碼，僅提供官方色號名稱。'
    return '色彩尚未完成官方數值驗證；不可視為實體試色結果。'


def color_payload(row):
    evidence=row.get('color_evidence') or {}
    palette=row.get('palette_colors') or []
    hx=row.get('hex_primary')
    transparent=is_transparent(row.get('shade_name'))
    multi=bool(palette) or bool(palette_size(row.get('name')))
    status=evidence.get('status','unverified')
    valid=(status=='verified_official_numeric' and str(evidence.get('hex','')).lower()==str(hx or '').lower()
           and str(evidence.get('sku') or '')==str(row.get('sku') or '')
           and evidence.get('sourceUrl')==row.get('source_url') and bool(evidence.get('sha256'))
           and lab_from_hex(hx) is not None and not transparent and not multi)
    # A stored single-shade HEX is still a useful *catalogue swatch
    # reference*.  Convert it with exactly the same sRGB→CIELAB formula as a
    # verified swatch, but retain its lower evidence grade.  This makes all
    # existing brands comparable without falsely calling their website colour
    # a laboratory or officially numeric measurement.
    reference_ready=bool(lab_from_hex(hx) is not None and not transparent and not multi)
    representation=('transparent' if transparent else 'palette' if multi else 'single' if hx else 'official_name_only')
    image_url=str(row.get('image_url') or row.get('image_webp_url') or '')
    image_sku=re.search(r'packshot[^/]*?-(\d{6})-\d+\.',image_url)
    wrong_image=(str(row.get('brand') or '').upper()=='CHANEL' and image_sku is not None
                 and image_sku[1]!=str(row.get('sku') or ''))
    # 一格要算完成，必須有可用的官方色值，而且沒有被明確標為未驗證。
    # 只有名稱、色值是 None 的格子不算完成，否則四色盤會謊報自己資料齊全。
    palette_complete=bool(palette and all(
        p.get('verified') is not False and lab_from_hex(p.get('hex')) is not None for p in palette))
    result = {'colorRepresentation':representation,'colorEvidence':evidence,'colorVerificationStatus':status,
            'colorSource':evidence.get('method','unknown'),'labConversionVersion':VERSION,
            'colorMatchReady':bool(valid),
            'colorReferenceReady':reference_ready,
            'colorReferenceLevel':'verified_official_numeric' if valid else ('catalog_hex_reference' if reference_ready else 'unavailable'),
            'colorEstimated':bool(hx and not valid),
            'colorWarning':color_warning(representation,valid,palette_complete),
            'paletteComplete':palette_complete,
            'hex':None if transparent or multi else hx,'hex_primary':None if transparent or multi else hx,
            'lab':lab_from_hex(hx) if reference_ready else None,
            'paletteColors':palette,'paletteImageUrl':row.get('palette_image_url'),
            'imageIdentityStatus':'mismatch' if wrong_image else 'not_revalidated',
            'imageWarning':'圖片所屬色號不符，待官方圖片核對。' if wrong_image else None}
    if wrong_image:
        result.update(imageUrl='',image_url='',image_src='',imageUrls=[])
    return result
