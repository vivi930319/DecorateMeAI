@echo off
setlocal
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
rem 服務缺金鑰就拒絕啟動（P0-7）。這支是本機開發腳本，明確打開免驗證旗標；
rem 該旗標在 APP_ENV=production 下一律失效，不影響正式站。
set ALLOW_INSECURE_LOCAL_DEV=1
rem Gateway 沒有 session secret 會拒絕啟動；本機開發用一個固定的長字串就好。
if "%GATEWAY_SESSION_SECRET%"=="" set "GATEWAY_SESSION_SECRET=local-dev-session-secret-at-least-32-bytes"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "FRONTEND_DIR=%%D\web_frontend"

if not exist "%PY%" (
    echo ERROR: .venv\Scripts\python.exe was not found.
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\index.html" (
    echo ERROR: Frontend index.html was not found at "%FRONTEND_DIR%".
    pause
    exit /b 1
)

if not exist "%FRONTEND_DIR%\dev_server.py" (
    echo ERROR: Frontend dev_server.py was not found at "%FRONTEND_DIR%".
    pause
    exit /b 1
)

echo Starting frontend, gateway, and backend services...
rem 端口對應各服務 run_dev_server 的預設值：
rem   5500 前端  8015 Gateway  8001 BASIC  8002 PRO  8010 Ollama
rem 先前這支沒有啟動 Gateway——但前端現在所有 API（登入、會員、渲染）都只走 Gateway，
rem 少了它，本機開站連登入都做不了。這是「舊路徑」殘留：腳本停在 Gateway 上線之前。
rem
rem 就緒判斷改用 /health（HTTP 200）而不是「port 有沒有在聽」：port 一 bind 就會 listen，
rem 但那時服務可能還在載模型、還沒真的能服務。健康檢查才代表真的可用。
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$py='%PY%'; $root='%~dp0'; $front='%FRONTEND_DIR%';" ^
  "$env:ALLOW_INSECURE_LOCAL_DEV='1'; $env:GATEWAY_SESSION_SECRET='%GATEWAY_SESSION_SECRET%';" ^
  "function Start-LocalService($port,$arguments,$dir){" ^
  "  if(-not (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)){" ^
  "    Start-Process -FilePath $py -ArgumentList $arguments -WorkingDirectory $dir -WindowStyle Hidden" ^
  "  }" ^
  "};" ^
  "function Test-Health($port){ try { (Invoke-WebRequest -Uri ('http://127.0.0.1:{0}/health' -f $port) -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $false } };" ^
  "Start-LocalService 5500 @('dev_server.py') $front;" ^
  "Start-LocalService 8015 @('ai_gateway.py') $root;" ^
  "Start-LocalService 8001 @('Face_analyzer_BASIC.py') $root;" ^
  "Start-LocalService 8002 @('Face_analyzer_PRO.py') $root;" ^
  "Start-LocalService 8010 @('Ollama_suggestion.py') $root;" ^
  "$httpPorts=8015,8001,8002,8010; $end=(Get-Date).AddSeconds(60);" ^
  "do { Start-Sleep -Milliseconds 800;" ^
  "  $frontUp=[bool](Get-NetTCPConnection -LocalPort 5500 -State Listen -ErrorAction SilentlyContinue);" ^
  "  $ready=$frontUp -and (($httpPorts | Where-Object { -not (Test-Health $_) }).Count -eq 0)" ^
  "} until($ready -or (Get-Date)-gt $end);" ^
  "if(-not $ready){ exit 1 }"

if errorlevel 1 (
    echo ERROR: Services did not pass health checks within 60 seconds.
    echo Check that the venv has all backend dependencies installed.
    pause
    exit /b 1
)

echo Services are ready. Opening http://127.0.0.1:5500
start "" "http://127.0.0.1:5500/?v=local-stack#dashboard"
exit /b 0
