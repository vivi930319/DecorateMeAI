import requests
import json

# 1. 妝容風格資料庫 
makeup_database = {
    "Soft baddie": {
        "description": "Baddie 的力量感結合 Soft Girl 的溫柔，更自然、更輕盈。",
        "eye": "重點在於濃密纖長的睫毛與乾淨但有深邃感的眼影。",
        "base": "精緻且帶有自然光澤的底妝，結合立體修容來雕塑五官。",
        "lip": "性感且邊界清晰的唇線，搭配裸色或肉桂色系唇釉。"
    },
    "千金妝": {
        "description": "高級感、五官立體且乾淨高級的氛圍。",
        "eye": "金屬感眼影點綴，濃密捲翹睫毛，根根分明的下睫毛增加靈動感，細長眼線勾勒深邃眼神。",
        "base": "無瑕的高級感光澤底妝，強調骨相的立體度與高級感。",
        "lip": "粉嫩感的水潤唇膏，營造優雅氣質。"
    },
    "泰系妝": {"description": "充滿異國風情的陽光感", "eye": "金橘色眼線疊加亮片", "base": "健康質感光澤立體", "lip": "玫瑰金潤澤唇釉"},
    "港風妝": {"description": "復古90年代成熟氣場", "eye": "大地色消腫眼影+深色包圍眼線", "base": "大氣無瑕霧面", "lip": "濃郁磚紅霧面唇膏"},
    "韓式白開水妝": {"description": "清透自然偽素顏", "eye": "低飽和杏色+極細內眼線", "base": "清透亮底妝", "lip": "嫩粉色光澤唇釉"},
    "病嬌妝": {"description": "日系原宿微醺憂鬱感", "eye": "桃粉色系暈染下眼瞼", "base": "偏白皙霧面", "lip": "酒紅色咬唇妝"},
    "Y2K辣妹妝": {"description": "未來感大膽色彩", "eye": "螢光色亮片+強烈眼線", "base": "高光感立體", "lip": "高飽和水光唇釉"}
}

# 2. 
face_logic = {
    "鵝蛋臉": {"feature": "面部飽滿、輪廓圓潤", "advice": "修容下顎線輕掃；腮紅笑肌向太陽穴暈染；打亮鼻尖額頭。"},
    "菱形臉": {"feature": "顴骨與太陽穴明顯、下頷骨突出", "advice": "修容顴骨最凸點，太陽穴凹陷處打亮柔和；腮紅蘋果肌銜接修容。"},
    "圓形臉": {"feature": "面部圓潤飽滿，下巴較短", "advice": "修容由臉側斜向上刷收縮；腮紅位置調高拉提；打亮下巴額頭拉長比例。"},
    "長形臉": {"feature": "臉型較瘦長、中庭較長", "advice": "修容額頭頂部與下巴底端縮短臉長；腮紅橫向刷法加寬視覺；打亮眼下三角區。"},
    "正三角臉": {"feature": "額頭較窄、下顎較寬", "advice": "加強下顎角陰影；加強額頭兩側與太陽穴打亮；腮紅斜向上刷。"},
    "方形臉": {"feature": "下頷角明顯，線條硬朗", "advice": "下頷角稜角轉折處柔和修容；腮紅打圈方式刷蘋果肌；打亮面部中心。"}
}

skin_logic = {
    "偏黃": "莓果色或紫粉色去黃提亮", "泛紅": "綠色校色，豆沙或奶茶色更溫柔", "偏黑": "暖橘色或金屬色打亮", "冷皮": "冷粉或冰藍色系透亮", "中性": "適應性強，可嘗試大膽色彩"
}

# 3. 核心
def get_customized_makeup_advice(style_name, face_shape, skin_detail):
    style = makeup_database.get(style_name)
    if not style: return "這個風格目前還在研發中！"

    face_data = face_logic.get(face_shape, {"feature": "", "advice": ""})
    
    # 修改：強化 System Instruction 的「聯想」與「範例」
    system_instruction = (
        "你是一位溫柔的台灣彩妝顧問。說話要有畫面感，像在面對面聊天。\n"
        "【核心任務】：\n"
        "1. 將我提供的『技術』不著痕跡地加進對話中。不要說『修容建議是...』，要說『親愛的，我們在修飾臉型時，可以輕輕把刷子從...』。\n"
        "2. 語氣要有情緒與讚美，多用助詞（喔、呢、唷、呀）。\n"
        "3. **絕對禁止出現任何英文**。術語必須正確（唇釉、腮紅、遮瑕）。\n"
        "4. **隨機開場**：每次回答的開頭都要不同，不要總是重複『妳好』。"
    )

   
    prompt_content = f"""
    以下是這位女孩的【專屬分析】，請妳用妳的創意把它們串成一段溫暖的建議：
    
    風格主題：{style_name} ({style['description']})
    用戶臉型：{face_shape} ({face_data['feature']})
    骨相修正技巧（請自然融入描述）：{face_data['advice']}
    色彩學關鍵：{skin_logic.get(skin_detail, "")}
    基礎底色參考：眼妝{style['eye']}，底妝{style['base']}，唇彩{style['lip']}。

    請開始妳的創作（250字內，充滿溫柔的畫面感）：
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
                    "temperature": 0.9,  
                    "num_predict": 400
                }
            }
        )
        return response.json()['message']['content']
    except Exception as e:
        return f"連線 Ollama 發生錯誤了：{e}"

if __name__ == "__main__":
    print("歡迎使用彩妝顧問 ！")
    print("-" * 50)
    
    # 測試
    result = get_customized_makeup_advice(
        style_name="Soft baddie",
        face_shape="長臉",
        skin_detail="偏黃"
    )
    
    print("\n【顧問建議回覆】：")
    print(result)