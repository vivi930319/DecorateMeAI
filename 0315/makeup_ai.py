import requests
import json
import base64
import re

# 1. 妝容風格資料庫
makeup_database = {
    "Soft baddie": {"tone": "肉桂裸色系", "eye": "暖棕色系暈染與纖長翹睫", "base": "絲絨半霧面", "lip": "飽和裸色唇釉"},
    "千金妝": {"tone": "香檳粉金系", "eye": "細緻珠光點綴與隱形內眼線", "base": "高級感光澤奶油肌", "lip": "嫩粉色水光唇膏"},
    "日雜清透妝": {"tone": "蜜桃杏色系", "eye": "單色眼影大面積暈染與毛流感眉毛", "base": "呼吸感透明底妝", "lip": "亮面潤唇蜜"},
    "港風妝": {"tone": "復古紅棕系", "eye": "全包圍式消腫陰影與俐落眉峰", "base": "大氣無瑕霧面", "lip": "經典正紅色"},
    "韓式白開水妝": {"tone": "冷淡裸粉系", "eye": "低飽和修容色與臥蠶提亮", "base": "清透亮底妝", "lip": "淡粉色唇凍"},
    "病嬌妝": {"tone": "煙燻玫瑰系", "eye": "下眼影倒三角暈染與微醺腮紅", "base": "冷白偏霧感", "lip": "酒紅色咬唇"},
    "Y2K辣妹妝": {"tone": "繽紛撞色系", "eye": "偏光亮片與上揚貓眼線", "base": "高光感立體肌", "lip": "高飽和鏡面唇釉"}
}

# 2. 五官邏輯資料庫
face_logic = {"鵝蛋臉": "比例勻稱流暢", "菱形臉": "顴骨線條明顯", "圓形臉": "雙頰圓潤飽滿", "長形臉": "中庭比例較長", "正三角臉": "視覺重心在下頷", "方形臉": "輪廓硬朗有神"}
nose_logic = {"直鼻": "鼻樑高挺", "朝天鼻": "鼻尖微翹俏皮", "歪斜鼻": "鼻樑線條柔和", "駝峰鼻": "骨相感強", "寬鼻": "鼻翼飽滿", "短鼻": "山根精巧", "蒜頭鼻": "鼻頭圓潤親切", "鷹鈎鼻": "鼻尖深邃"}

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def get_makeup_advice_by_vision(image_path, style_name):
    style = makeup_database.get(style_name)
    try:
        img_base64 = encode_image(image_path)
    except Exception as e:
        return f"找不到圖片：{e}"

   
    analysis_prompt = (
        "請分析這張照片，精準判斷五官，並嚴格以 JSON 回傳，不可有廢話：\n"
        "{\"臉型\": \"...\", \"眉型\": \"...\", \"眼型\": \"...\", \"鼻型\": \"...\", \"唇型\": \"...\", \"膚色\": \"...\"}"
    )

    try:
        print("顧問正在細看妳的五官優勢...")
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
        features = json.loads(match.group()) if match else {"臉型": "鵝蛋臉", "眉型": "標準眉", "眼型": "雙眼皮", "鼻型": "直鼻", "唇型": "微笑唇", "膚色": "中性"}

      
        system_instruction = (
            "你是一位在台灣百貨公司服務的專業彩妝總監。說話要溫柔、專業，充滿對美的讚賞。\n"
            "【嚴格規則】：\n"
            "1. 必須全程使用繁體中文，禁止出現任何英文單字（包含妝容名稱）。\n"
            "2. 禁止使用任何表情符號、數字、或是特殊符號。\n"
            "3. 開頭先針對辨識出的五官進行優點反饋（例如：妳的臉型很精緻）。\n"
            "4. 分別詳細說明：底妝修容位置、眼影疊加層次、唇彩塗抹技巧。"
        )

        prompt_content = f"""
        現在請妳以彩妝總監的身分，針對一位擁有「{features['臉型']}」、「{features['鼻型']}」與「{features['眼型']}」的女孩，
        設計一套「{style_name}」。
        
        請依照以下細節撰寫：
        一、稱讚她的五官優勢。
        二、說明為何選擇「{style['tone']}」來搭配她的「{features['膚色']}」。
        三、詳細教學「{style['base']}」的修容手法。
        四、詳細教學「{style['eye']}」的疊加順序。
        五、詳細教學「{style['lip']}」的塗抹位置。
        
        請注意，整篇文章絕對不准出現任何英文。
        """

        print(f" 正在為妳產出【{style_name}】教學報告...")
        res_text = requests.post(
            "http://localhost:11434/api/chat",
            json={
                "model": "llama3",
                "messages": [
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt_content}
                ],
                "stream": False,
                "options": {
                    "temperature": 0.7, 
                    "top_p": 0.9
                }
            }
        )
        return res_text.json().get('message', {}).get('content', '連線稍微不穩定，再試一次看看呀。')

    except Exception as e:
        return f"發生錯誤：{e}"

if __name__ == "__main__":
    image_file = "/Users/liaolingya/Documents/GitHub/new_poject/0315/face.jpg" 
    target_style = "千金妝" 
    report = get_makeup_advice_by_vision(image_file, target_style)
    print("\n【大師級美妝客製報告】：")
    print("-" * 50)
    print(report)