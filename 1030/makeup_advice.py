import json
import subprocess

# 讀取妝容規則資料
with open("makeup_rules.json", "r", encoding="utf-8") as f:
    rules = json.load(f)

def get_makeup_advice(style):
    if style in rules["makeup_styles"]:
        info = rules["makeup_styles"][style]
        advice = f"""
風格名稱：{style}
主打色：{", ".join(info["main_colors"])}
風格關鍵字：{", ".join(info["keywords"])}
建議眼妝：{info["suggested_use"]["eye"]}
建議腮紅：{info["suggested_use"]["cheek"]}
建議唇色：{info["suggested_use"]["lip"]}
"""
        return advice
    else:
        return "目前尚未支援此妝容風格，敬請期待！"

def call_ollama_interactive(prompt_text, model="llama3:latest"):
    # 呼叫 ollama CLI 並輸入 prompt_text
    process = subprocess.Popen(
        ['ollama', 'run', model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    out, err = process.communicate(prompt_text + "\n")
    return out

def main():
    print("歡迎使用妝容建議系統!")
    style = input("請輸入想分析的妝容風格（如：日系妝，韓系妝，歐美妝，泰系妝）：").strip()
    print(get_makeup_advice(style))
    advice_text = get_makeup_advice(style)
    print("妝容規則建議內容：")
    print(advice_text)

    print("正在呼叫 Ollama 來優化文字建議...")
    ollama_response = call_ollama_interactive(
        advice_text + "\n\n請幫我整理成一句適合美妝app的短推薦說明。"
    )
    print("Ollama 生成的優化推薦：")
    print(ollama_response)

if __name__ == "__main__":
    main()
