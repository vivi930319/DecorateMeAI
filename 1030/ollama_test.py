import subprocess

def call_ollama_interactive(prompt_text, model="llama3:latest"):
    process = subprocess.Popen(
        ['ollama', 'run', model],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    out, err = process.communicate(prompt_text + "\n")
    return out

advice = "請幫我整理成一句適合美妝app的短推薦說明"

response = call_ollama_interactive(advice)
print("Ollama生成結果:")
print(response)
