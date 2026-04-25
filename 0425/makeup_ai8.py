import requests
import json
import base64
import re

# 1. 專業妝容風格資料庫
makeup_database = {
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
        "custom_tip": "著重在下睫毛的根根分明，增加眼神的精緻度。"
    },
    "港風妝": {
        "description": "復古90年代明豔對比，成熟大氣。",
        "tone": "復古復古紅棕色與冷灰色",
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

# 2. 專業五官與四季膚色邏輯資料庫
face_logic = {"鵝蛋臉": "比例完美流暢", "菱形臉": "顴骨突出有神", "圓形臉": "雙頰圓潤飽滿", "長形臉": "比例顯得成熟", "正三角臉": "下顎線條分明", "方形臉": "輪廓英氣硬朗", "心形臉": "下巴精緻纖細", "梯形臉": "下顎厚實穩重"}
eyebrow_logic = {"標準眉": "眉頭眼頭垂直", "一字眉": "眉型平直無邪", "彎月眉": "弧度圓潤溫柔", "落尾眉": "眉尾優雅下落"}
eye_logic = {"圓眼": "眼神圓潤清澈", "長眼": "眼神嫵媚狹長", "雙眼皮": "褶皺層次分明", "單眼皮": "眼皮厚實有神"}
nose_logic = {"直鼻": "鼻樑高挺筆直", "朝天鼻": "鼻尖微翹俏皮", "歪斜鼻": "鼻樑具有個性", "駝峰鼻": "骨感英氣十足", "寬鼻": "鼻翼大氣飽滿", "短鼻": "山根小巧精緻", "蒜頭鼻": "鼻頭肉感親切", "鷹鈎鼻": "鼻尖深邃有型"}
lip_logic = {"M型唇": "唇峰稜角立體", "花瓣唇": "唇形飽滿豐盈", "微笑唇": "嘴角天然上揚", "厚唇": "唇部感性飽滿", "薄唇": "唇線俐落清秀"}
skin_logic = {"春季型": "適合亮暖黃系", "夏季型": "適合冷粉灰系", "秋季型": "適合深邃暖米", "冬季型": "適合對比冷青"}

# 專業手法敘述庫 (內部組合用)
face_method = {"鵝蛋臉": "輕掃下顎線；腮紅斜上暈染；打亮額頭鼻尖。", "菱形臉": "修容顴骨最高點；太陽穴打亮；腮紅銜接修容。", "圓形臉": "從耳際斜下刷修容；腮紅調高拉提；打亮下巴。", "長形臉": "修容額頭頂與下巴底；腮紅橫平刷；打亮眼下。", "正三角臉": "加強下顎陰影；太陽穴打亮擴張；腮紅斜向延伸。", "方形臉": "下頷稜角圓潤修容；蘋果肌打圈腮紅；打亮中心。", "心形臉": "顴骨下方向內收縮；下巴尖端打亮；腮紅斜掃顴骨。", "梯形臉": "下顎兩側收縮；額頭太陽穴打亮；腮紅向斜上延伸。"}
eyebrow_method = {"標準眉": "順原生毛流填補空隙。", "一字眉": "縮短中庭，眉尾拉平。", "彎月眉": "圓潤轉折，修飾硬朗。", "落尾眉": "眉峰後移，輕輕下撇。"}

# 3. 執行函式
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_makeup_advice_by_vision(image_path, style_name):
    style = makeup_database.get(style_name)
    if not style: return "找不到這個風格唷！"
    
    try:
        img_base64 = encode_image(image_path)
    except Exception as e:
        return f"找不到圖片：{e}"

    analysis_prompt = (
        "你是一位專業美容總監。請精準分析照片中人物特徵，並從以下清單選擇標籤回傳：\n"
        f"臉型：{list(face_logic.keys())}\n鼻型：{list(nose_logic.keys())}\n"
        f"眼型：{list(eye_logic.keys())}\n眉型：{list(eyebrow_logic.keys())}\n"
        f"唇型：{list(lip_logic.keys())}\n膚色類型：{list(skin_logic.keys())}\n"
        "回答格式必須是 JSON：{\"臉型\": \"...\", \"眉型\": \"...\", \"眼型\": \"...\", \"鼻型\": \"...\", \"唇型\": \"...\", \"膚色\": \"...\"}"
    )

    try:
        print(f" 顧問正在觀察您的五官與膚色...")
        res_vision = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llava",
                "messages": [{"role": "user", "content": analysis_prompt, "images": [img_base64]}],
                "stream": False
            }
        )
        
        full_text = res_vision.json().get('message', {}).get('content', '')
        match = re.search(r'\{.*\}', full_text, re.DOTALL)
        features = json.loads(match.group()) if match else {"臉型": "鵝蛋臉", "眉型": "標準眉", "眼型": "雙眼皮", "鼻型": "直鼻", "唇型": "微笑唇", "膚色": "春季型"}

        # --- 精確分析 + 條列妝容建議 ---
        system_instruction = (
            "你是一位彩妝總監。語氣專業、溫柔且不廢話。\n"
            "【嚴格輸出格式】：\n"
            "一、五官與膚色分析回饋：\n"
            "(條列式簡短描述辨識到的特徵)\n\n"
            "二、專屬妝容建議：\n"
            "底妝：內容\n"
            "眉毛：內容\n"
            "眼妝：內容\n"
            "腮紅/修容：內容\n"
            "唇妝：內容\n\n"
            "【規則】：全程繁體中文，禁止英文與贅字（首先、然後）。"
        )

        prompt_content = f"""
        根據辨識結果為這位女孩提供「{style_name}」的報告。
        
        【分析回饋素材】：
        臉型：{features['臉型']} ({face_logic.get(features['臉型'])})
        眉型：{features['眉型']} ({eyebrow_logic.get(features['眉型'])})
        鼻型：{features['鼻型']} ({nose_logic.get(features['鼻型'])})
        唇型：{features['唇型']} ({lip_logic.get(features['唇型'])})
        膚色：{features['膚色']} ({skin_logic.get(features['膚色'])})

        【妝容建議素材】：
        底妝：針對「{features['膚色']}」，選用「{style['tone']}」色調。打造「{style['base_detail']}」。
        眉毛：執行「{eyebrow_method.get(features['眉型'])}」。
        眼妝：步驟為「{style['eye_layers']}」。
        腮紅/修容：執行「{face_method.get(features['臉型'])}」。搭配腮紅手法「{style['blush_detail']}」。鼻影執行「{nose_logic.get(features['鼻型'])}」。
        唇妝：手法為「{style['lip_detail']}」。
        """

        res_text = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt_content}
                ],
                "stream": False,
                "options": {"temperature": 0.2} # 極低溫度確保格式穩定
            }
        )
        return res_text.json().get('message', {}).get('content', '再試一次。')

    except Exception as e:
        return f"發生錯誤：{e}"

if __name__ == "__main__":
    image_file = "/Users/liaolingya/Documents/GitHub/new_poject/0411/face6.jpg" 
    target_style = "韓系亞裔妝" 
    report = get_makeup_advice_by_vision(image_file, target_style)
    print("\n【專業美妝分析與建議回報】")
    print("-" * 50)
    print(report)