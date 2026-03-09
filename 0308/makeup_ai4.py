import requests
import json

# 1. 妝容風格資料庫
makeup_database = {
    "Soft baddie": {"description": "Baddie 的力量感結合 Soft Girl 的溫柔，更自然、更輕盈。", "eye": "濃密纖長睫毛與深邃眼影。", "base": "自然光澤底妝與立體修容。", "lip": "清晰唇線搭配裸色或肉桂色系唇釉。"},
    "千金妝": {"description": "高級感、五官立體且乾淨高級的氛圍。", "eye": "金屬感眼影、濃密捲翹睫毛與細長眼線。", "base": "無瑕高級感光澤底妝。", "lip": "粉嫩感水潤唇膏。"},
    "泰系妝": {"description": "充滿異國風情的陽光感", "eye": "金橘色眼線疊加亮片", "base": "健康質感光澤立體", "lip": "玫瑰金潤澤唇釉"},
    "港風妝": {"description": "復古90年代成熟氣場", "eye": "大地色消腫眼影+深色包圍眼線", "base": "大氣無瑕霧面", "lip": "濃郁磚紅霧面唇膏"},
    "韓式白開水妝": {"description": "清透自然偽素顏", "eye": "低飽和杏色+極細內眼線", "base": "清透亮底妝", "lip": "嫩粉色光澤唇釉"},
    "病嬌妝": {"description": "日系原宿微醺憂鬱感", "eye": "桃粉色系暈染下眼瞼", "base": "偏白皙霧面", "lip": "酒紅色咬唇妝"},
    "Y2K辣妹妝": {"description": "未來感大膽色彩", "eye": "螢光色亮片+強烈眼線", "base": "高光感立體", "lip": "高飽和水光唇釉"}
}

# 2. 五官邏輯資料庫
face_logic = {
    "鵝蛋臉": "面部飽滿圓潤。建議修容輕掃下顎，腮紅笑肌向太陽穴暈染，打亮鼻尖額頭。",
    "菱形臉": "顴骨與太陽穴明顯。修容著重顴骨最凸點，太陽穴打亮柔和，腮紅銜接修容。",
    "圓形臉": "圓潤飽滿下巴短。修容臉側斜向上刷，腮紅位置調高拉提，打亮下巴額頭。",
    "長形臉": "臉型較瘦長、中庭較長。修容額頭頂與下巴底，腮紅橫向刷法，打亮眼下三角區。",
    "正三角臉": "額頭窄下顎寬。加強下顎角陰影，額頭兩側與太陽穴打亮，腮紅斜向上刷。",
    "方形臉": "下頷角明顯線條硬朗。下頷稜角柔和修容，腮紅打圈刷蘋果肌，打亮面部中心。"
}


eyebrow_logic = {
    "標準眉": "適合幾乎所有臉型。眉頭較粗，眉尾逐漸變細，線條自然流暢。建議順著原生毛流輕補色塊，維持大眾好感度的自然感。",
    "一字眉": "適合長臉、瓜子臉。線條簡潔大方，能視覺上縮短臉部比例，帶來平穩與穩重的氣息。",
    "彎月眉": "適合圓臉、方圓臉。眉峰圓潤、眉尾自然下垂，能柔和臉部線條，為圓臉增加靈動感，為方臉增添溫柔美。",
    "落尾眉": "適合橢圓臉、長臉。眉型細長如柳葉且微下落，展現優雅且富有女人味的精緻氣質。"
}

eye_logic = {
    "圓眼": "眼型圓潤。建議眼線向後平拉延伸增加長度。",
    "長眼": "眼型細長。建議加強眼部中段的縱向放大，平衡比例。",
    "雙眼皮": "層次感強。適合疊加漸層色眼影展現深邃魅力。",
    "單眼皮": "眼皮厚實。建議使用霧面深色眼影在根部消腫，搭配捲翹睫毛。"
}

nose_logic = {
    "直鼻": "鼻樑到鼻尖呈直線，鼻頭圓潤。建議強調側影深邃感，並在鼻尖點綴高光。",
    "朝天鼻": "鼻尖短、鼻翼退縮。建議在鼻尖下方勾勒較深陰影，視覺上延長鼻小柱。",
    "歪斜鼻": "鼻梁歪斜。建議在歪斜反向加強修容，垂直打亮鼻心校正。",
    "駝峰鼻": "鼻背隆起。建議修容避開隆起處，在隆起上下方微調陰影。",
    "寬鼻": "鼻底寬。建議加強鼻翼兩側陰影收縮，提升精緻感。",
    "短鼻": "比例不足。建議打亮點上移並延伸至鼻尖，視覺拉長。",
    "蒜頭鼻": "鼻頭圓頓。建議在鼻頭勾勒小V型修容，縮小肉感。",
    "鷹鈎鼻": "鼻尖下旋。建議縮短打亮範圍，改用腮紅柔和氣場。"
}

lip_logic = {
    "M型唇": "唇峰立體。建議強化唇峰高光，突顯精緻度。",
    "花瓣唇": "上M下W。建議在下唇W處疊加透明唇釉增加層次感。",
    "微笑唇": "嘴角上揚。適合勾勒唇角線條，強化親和力。",
    "厚唇": "飽滿豐厚。適合模糊唇周邊界，營造彈潤質感。",
    "薄唇": "線條利落。建議稍微外擴唇線，用亮面質地增加澎潤度。"
}

skin_logic = {
    "偏黃": "莓果色或紫粉色去黃提亮", "泛紅": "綠色校色搭配豆沙色系", "偏黑": "暖橘或金屬光打亮", "冷皮": "冷粉冰藍系透亮", "中性": "各種色調皆可駕馭"
}


def get_customized_makeup_advice(style_name, face_shape, eyebrow_shape, eye_shape, nose_shape, lip_shape, skin_detail):
    style = makeup_database.get(style_name)
    if not style: return "這個風格目前還在研發中！"

    system_instruction = (
        "你是一位溫柔的台灣專櫃彩妝顧問。說話要有畫面感，像在面對面聊天。\n"
        "規則：\n"
        "1. 將臉型、眉型、眼型、鼻型與唇型的修正技巧自然融合。語氣要像資深老師般流暢且具備針對性。\n"
        "2. 絕對禁止出現任何英文單字。術語必須正確（唇釉、修容、打亮、毛流、山根）。\n"
        "3. 多用動詞：勾勒、填補、暈染、提拉。語氣多用助詞（喔、呢、呀、囉）。"
    )

    prompt_content = f"""
    請根據以下素材，為女孩寫一段純文字建議（約 280 字）：
    
    風格主題：{style_name}
    臉型建議：{face_shape} - {face_logic.get(face_shape, "")}
    眉部修飾：{eyebrow_shape} - {eyebrow_logic.get(eyebrow_shape, "")}
    眼部修正：{eye_shape} - {eye_logic.get(eye_shape, "")}
    鼻型修正：{nose_shape} - {nose_logic.get(nose_shape, "")}
    唇形重點：{lip_shape} - {lip_logic.get(lip_shape, "")}
    膚色關鍵：{skin_detail} - {skin_logic.get(skin_detail, "")}
    基礎產品：眼妝{style['eye']}，底妝{style['base']}，唇彩{style['lip']}。
    """

    try:
        response = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3", 
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt_content}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.85, 
                    "num_predict": 550
                }
            }
        )
        return response.json()['message']['content']
    except Exception as e:
        return f"連線 Ollama 發生錯誤了：{e}"


if __name__ == "__main__":
    print("歡迎使用專業彩妝顧問系統")
    print("-" * 50)
   
    result = get_customized_makeup_advice(
        style_name="港風妝",
        face_shape="長形臉",
        eyebrow_shape="落尾眉",
        eye_shape="長眼",
        nose_shape="直鼻",
        lip_shape="微笑唇",
        skin_detail="偏黃"
    )
    
    print("\n顧問專屬建議回覆：")
    print(result)