@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: 找不到 .venv\Scripts\python.exe
    echo 請先建立後端 .venv 並安裝 requirements.txt
    exit /b 1
)

set "FRONTEND_DIR=C:\Users\isach\OneDrive\桌面\web_frontend"

if not exist "%FRONTEND_DIR%\index.html" (
    echo ERROR: 找不到前端 index.html
    echo 目前設定的前端路徑：%FRONTEND_DIR%
    exit /b 1
)

echo 啟動前端 http://127.0.0.1:5500
start "DecorateMe Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && python -m http.server 5500"

echo 啟動後端 BASIC / PRO / suggestion
start "Face BASIC" cmd /k "cd /d "%~dp0" && set FRONTEND_URL=http://127.0.0.1:5500 && .venv\Scripts\python.exe Face_analyzer_BASIC.py"
start "Face PRO" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe Face_analyzer_PRO.py"
start "Ollama Suggestion" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe Ollama_suggestion.py"
