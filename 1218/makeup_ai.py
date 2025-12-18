import requests
import json

# --- 第一步：定義妝容風格字典 ---
makeup_database = {
    "泰系妝": {
        "base": "光澤立體底妝",
        "eye": "金橘色眼影疊加亮片，強調下睫毛的毛茸感與濃密度",
        "lip": "玫瑰金或橘棕色的潤澤唇釉",
        "keywords": "異國感、艷麗、陽光"
    },
    "港風妝": {
        "base": "霧面無瑕底妝",
        "eye": "大地色消腫眼影，搭配深色包圍式眼線，強調眼神故事感",
        "lip": "濃郁磚紅色或正紅色的霧面唇膏",
        "keywords": "復古、90年代、氣場"
    },
    "韓式白開水妝": {
        "base": "清透自然偽素顏，像原生肌膚般透亮",
        "eye": "低飽和杏色打底，搭配極細內眼線",
        "lip": "嫩粉色或冷粉色的光澤唇釉",
        "keywords": "乾淨、清純、低飽和"
    },
    "病嬌妝": {
        "base": "偏白皙的霧面底妝",
        "eye": "桃粉色或紅色系眼影暈染至下眼瞼，營造微醺哭過感",
        "lip": "酒紅色或深紅色的咬唇妝",
        "keywords": "日系原宿、微醺、憂鬱美"
    },
    "Y2K辣妹妝": {
        "base": "高光感立體底妝",
        "eye": "飽和度高的螢光色或銀色亮片，線條感強烈的眼線",
        "lip": "高飽和色的水光唇釉",
        "keywords": "辣妹風、未來感、大膽"
    }
}

# --- 第二步：定義呼叫 Ollama 的函式 ---
def get_ai_makeup_advice(style_name, user_skin_tone="一般膚色"):
    # 1. 檢查風格是否存在
    style_info = makeup_database.get(style_name)
    if not style_info:
        return f"抱歉親愛的，『{style_name}』目前還在研發中，敬請期待喔！"

    # 2. 【核心修改】：動態換色邏輯
    # 先抓取資料庫預設唇色
    current_lip_color = style_info['lip']
    
    # 強制判斷：如果是偏黃膚色且要透亮感，直接在程式層面更換建議產品
    if "膚色偏黃" in user_skin_tone and "透亮" in user_skin_tone:
        current_lip_color = "莓果色系的光澤唇釉 (因為莓果色帶點紫調，能有效中和黃皮膚的暗沈，讓臉部瞬間提亮、顯白喔！)"

    # 3. 設定 Ollama API 位址
    url = "http://localhost:11434/api/chat"
    
    # 4. 這是經過 LM Studio 驗證過的「穩定版人格設定」
    system_instruction = (
        "你是一位台灣資深專櫃彩妝顧問。說話溫柔、親切且專業。"
        "請根據提供的產品資訊，為用戶寫一段有畫面感的妝容推薦。"
        "語氣規則：1.多用『親愛的』、『喔』、『呢』。 2.正確使用『唇釉』一詞。"
        "3.禁止提到服裝、場合或出去玩，專注在臉部妝容建議。 4.一律繁體中文。"
    )

    # 5. 組合 Prompt（傳入已經修正過的唇色）
    prompt_content = f"""
    請針對以下資訊生成建議：
    【目標風格】：{style_name} (特點：{style_info['keywords']})
    【用戶特徵】：{user_skin_tone}
    【底妝建議】：{style_info['base']}
    【眼妝重點】：{style_info['eye']}
    【專業推薦唇色】：{current_lip_color}
    """

    payload = {
        "model": "llama3", 
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": prompt_content}
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,  # 稍微降低一點，讓回答更穩定
            "num_predict": 400
        }
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json()['message']['content']
    except Exception as e:
        return f"系統繁忙中，請稍後再試（錯誤：{str(e)}）"

# --- 第三步：主程式執行 ---
if __name__ == "__main__":
    print("✨ 歡迎使用 MacBook M3 專業妝容顧問系統 ✨")
    print("-" * 40)
    
    # 測試情境
    selected_style = "韓式白開水妝"
    detected_tone = "膚色偏黃但追求透亮感的女孩"
    
    # 取得建議
    print(f"正在為您分析『{selected_style}』...")
    result = get_ai_makeup_advice(selected_style, detected_tone)
    
    print("\n【彩妝大師建議回覆】：")
    print("-" * 40)
    print(result)