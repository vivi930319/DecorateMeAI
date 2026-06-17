@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: 找不到 .venv\Scripts\python.exe
    echo 請先在專案根目錄建立 venv，並安裝 requirements.txt
    exit /b 1
)

echo 使用 .venv 啟動 BASIC / PRO / suggestion...
start "Face BASIC" cmd /k ".venv\Scripts\python.exe Face_analyzer_BASIC.py"
start "Face PRO" cmd /k ".venv\Scripts\python.exe Face_analyzer_PRO.py"
start "Ollama Suggestion" cmd /k ".venv\Scripts\python.exe Ollama_suggestion.py"
