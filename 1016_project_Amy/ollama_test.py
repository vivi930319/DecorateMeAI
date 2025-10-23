import requests
import json

# 使用者輸入文字
user_input = input("請輸入要問 Ollama 的問題：")

# 向本地 Ollama 發送請求
response = requests.post(
    "http://localhost:11434/api/generate",
    json={"model": "llama3", "prompt": user_input}
)

# 處理並輸出回傳結果
for line in response.iter_lines():
    if line:
        data = json.loads(line.decode("utf-8"))
        # 顯示完整 JSON 回傳（方便看格式）
        print("\n🟢 JSON回傳：", data)

        # 若回傳已完成，顯示最終文字結果
        if data.get("done"):
            print("\n💬 模型回覆：", data.get("response"))
