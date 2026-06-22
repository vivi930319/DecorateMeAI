@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "FRONTEND_DIR=%%D\web_frontend"

if not exist "%PY%" (
    echo ERROR: .venv\Scripts\python.exe was not found.
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\index.html" (
    echo ERROR: Frontend index.html was not found.
    pause
    exit /b 1
)

echo Starting frontend and backend services...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$py='%PY%'; $root='%~dp0'; $front='%FRONTEND_DIR%';" ^
  "function Start-LocalService($port,$arguments,$dir){" ^
  "  if(-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)){" ^
  "    Start-Process -FilePath $py -ArgumentList $arguments -WorkingDirectory $dir -WindowStyle Hidden" ^
  "  }" ^
  "};" ^
  "Start-LocalService 5500 @('-m','http.server','5500','--bind','127.0.0.1') $front;" ^
  "Start-LocalService 8001 @('Face_analyzer_BASIC.py') $root;" ^
  "Start-LocalService 8002 @('Face_analyzer_PRO.py') $root;" ^
  "Start-LocalService 8010 @('Ollama_suggestion.py') $root;" ^
  "$ports=5500,8001,8002,8010; $end=(Get-Date).AddSeconds(45);" ^
  "do { Start-Sleep -Milliseconds 700; $ready=($ports | Where-Object { -not (Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue) }).Count -eq 0 } until($ready -or (Get-Date)-gt $end);" ^
  "if(-not $ready){ exit 1 }"

if errorlevel 1 (
    echo ERROR: Services did not start within 45 seconds.
    pause
    exit /b 1
)

echo Services are ready. Opening http://127.0.0.1:5500
start "" "http://127.0.0.1:5500/?v=local-stack#dashboard"
exit /b 0
