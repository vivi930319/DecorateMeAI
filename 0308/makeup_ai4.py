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

# 2. 專業資料庫
face_logic = {
    "鵝蛋臉": "面部飽滿圓潤。建議修容輕掃下顎，腮紅笑肌向太陽穴暈染，打亮鼻尖額頭。",
    "菱形臉": "顴骨與太陽穴明顯。修容著重顴骨最凸點，太陽穴凹陷打亮，腮紅銜接修容。",
    "圓形臉": "圓潤飽滿下巴短。修容臉側斜向上刷，腮紅位置調高拉提，打亮下巴額頭。",
    "長形臉": "臉型較瘦長、中庭較長。修容額頭頂與下巴底，腮紅橫向刷法，打亮眼下三角區。",
    "正三角臉": "額頭窄下顎寬。加強下顎角陰影，額頭兩側與太陽穴打亮，腮紅斜向上刷。",
    "方形臉": "下頷角明顯線條硬朗。下頷稜角柔和修容，腮紅打圈刷蘋果肌，打亮面部中心。"
}

nose_logic = {
    "直鼻": "鼻樑到鼻尖呈直線，山根高，鼻頭圓潤。建議強調鼻樑側影的深邃感，並在鼻尖輕點高光，放大這種俐落優雅的骨相優勢。",
    "朝天鼻": "鼻尖短、鼻翼退縮。建議在鼻尖下方勾勒較深的陰影，並將打亮點稍微調低，視覺上收縮鼻孔並延長鼻小柱。",
    "歪斜鼻": "鼻梁歪斜。建議在鼻梁歪斜的反向加強修容，並垂直打亮鼻心來視覺校正直線。",
    "駝峰鼻": "鼻背異常隆起。建議修容避開隆起處，在隆起上下方微調陰影，減弱線條生硬感。",
    "寬鼻": "鼻底寬。建議加強鼻翼兩側的陰影收縮，縮窄鼻底視覺寬度，提升精緻感。",
    "短鼻": "比例不足。建議將山根打亮點上移，鼻尖打亮點下移，視覺上拉長鼻部比例。",
    "蒜頭鼻": "鼻頭圓頓肥厚。建議在鼻頭勾勒小V型修容，縮小肉感，讓鼻頭顯得精緻俐落。",
    "鷹鈎鼻": "鼻尖下旋凌厲。建議縮短鼻梁打亮的範圍，避免加長鼻部，改用腮紅橫掃鼻樑柔和氣場。"
}

lip_logic = {
    "M型唇": "上唇M字明顯、唇峰立體。建議強化唇峰的高光，突顯菱角分明的精緻感。",
    "花瓣唇": "上M下W，飽滿立體。建議在下唇W處疊加透明唇釉，打造層次感。",
    "微笑唇": "嘴角自然上揚。適合勾勒唇角上揚線條，強化親和力。",
    "厚唇（嘟嘟唇）": "上下唇飽滿豐厚。適合模糊唇周邊界，打造彈潤飽滿的質感。",
    "薄唇": "線條利落氣質清冷。建議稍微外擴唇線，再用亮面質地增加視覺澎潤度。"
}

skin_logic = {
    "偏黃": "莓果色或紫粉色去黃提亮", "泛紅": "綠色校色，豆沙或奶茶色更溫柔", "偏黑": "暖橘色或金屬色打亮", "冷皮": "冷粉或冰藍色系透亮", "中性": "各種色調都能輕鬆駕馭"
}

# 3. 
def get_customized_makeup_advice(style_name, face_shape, nose_shape, lip_shape, skin_detail):
    style = makeup_database.get(style_name)
    if not style: return "這個風格目前還在研發中！"

    system_instruction = (
        "你是一位溫柔的台灣專櫃彩妝顧問。說話要有畫面感，像在面對面聊天。\n"
        "【情境導引任務】：\n"
        "1. 將臉型、鼻型與唇型的修正技巧自然融合。不要死板地讀出技巧，要讓建議聽起來流暢且專業。\n"
        "2. **絕對禁止出現任何英文單字**。術語必須正確（唇釉、修容、打亮、腮紅、鼻小柱、山根）。\n"
        "3. 多用動詞：勾勒、暈染、輕觸、點綴。語氣多用助詞（喔、呢、囉、呀）。"
    )

    prompt_content = f"""
    請根據以下素材，為女孩寫一段純文字的客製化建議：
    
    
    【風格】：{style_name} ({style['description']})
    【臉型建議】：{face_shape} — {face_logic.get(face_shape, "")}
    【鼻型修正】：{nose_shape} — {nose_logic.get(nose_shape, "")}
    【唇形重點】：{lip_shape} — {lip_logic.get(lip_shape, "")}
    【膚色關鍵】：{skin_logic.get(skin_detail, "")}
    【基礎參考】：眼妝{style['eye']}，底妝{style['base']}，唇彩建議{style['lip']}。

    請寫出一篇約 250 字的純文字建議：
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
                    "temperature": 0.8, 
                    "num_predict": 450
                }
            }
        )
        return response.json()['message']['content']
    except Exception as e:
        return f"連線 Ollama 發生錯誤了：{e}"

if __name__ == "__main__":
    print("歡迎使用彩妝顧問系統")
    print("-" * 50)
    
    # 測試：
    result = get_customized_makeup_advice(
        style_name="千金妝",
        face_shape="方形臉",
        nose_shape="直鼻",
        lip_shape="薄唇",
        skin_detail="偏白"
    )
    
    print("\n顧問大師建議回覆：")
    print(result)