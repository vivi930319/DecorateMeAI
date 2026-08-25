# 開機（登入）時啟動訓練機。由 Windows 工作排程器呼叫，不必手動執行。
#
# 為什麼要有這一層而不是直接叫 python：
#   1. 工作排程器的工作目錄不一定是專案根目錄，而訓練腳本用的是相對路徑；
#   2. 沒有視窗就沒有地方看訊息，所以要把輸出接到記錄檔；
#   3. 記錄檔會一直長，順手做輪替——不然跑幾個月之後它會比模型還大。
#
# 手動測試：
#   powershell -ExecutionPolicy Bypass -File tools\start_training_worker.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "training_worker.log"

# 超過 5 MB 就把舊的留成 .1，重新開一個。只留一份備份就夠追前一次啟動發生什麼事。
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
    Move-Item $log "$log.1" -Force
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$env:PYTHONIOENCODING = "utf-8"
# Python 用 UTF-8 印出來，但 Windows PowerShell 預設用 cp950 解讀管線內容，
# 中文會整段變成亂碼——而記錄檔看不懂，等於沒有記錄。兩個都要設：
# OutputEncoding 管「怎麼讀子行程的輸出」，$OutputEncoding 管「怎麼寫出去」。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
"=== 啟動 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File $log -Append -Encoding utf8

# 2>&1 讓 Python 的錯誤也進同一個檔：訓練失敗的原因多半印在 stderr，
# 分成兩個檔的話，看記錄的人會先看到「什麼都沒有」。
& $python tools\training_worker.py *>&1 | Out-File $log -Append -Encoding utf8
