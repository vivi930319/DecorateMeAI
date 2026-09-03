# 開機（登入）時啟動換模型 worker。由 Windows 工作排程器呼叫，不必手動執行。
#
# 這支跟 start_training_worker.ps1 是同一套做法，理由也相同：
#   1. 工作排程器的工作目錄不一定是專案根目錄，而底下的腳本用的是相對路徑；
#   2. 沒有視窗就沒有地方看訊息，所以要把輸出接到記錄檔；
#   3. 記錄檔會一直長，順手做輪替。
#
# 為什麼換模型也需要常駐：
#   後台按下「換上線」只是把決定寫進 Firestore，實際的複製、上傳與部署都在這台
#   機器上。沒有人守著的話，那筆請求會一直停在 queued——而後台顯示的是「已登記」，
#   看起來像正在處理。訓練那邊已經踩過這個坑（見 training_worker 的說明）。
#
# 手動測試：
#   powershell -ExecutionPolicy Bypass -File tools\start_promotion_worker.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "promotion_worker.log"

# 超過 5 MB 就把舊的留成 .1，重新開一個。
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
    Move-Item $log "$log.1" -Force
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$env:PYTHONIOENCODING = "utf-8"
# Python 用 UTF-8 印出來，但 Windows PowerShell 預設用 cp950 解讀管線內容，
# 中文會整段變成亂碼。OutputEncoding 管「怎麼讀子行程的輸出」，
# $OutputEncoding 管「怎麼寫出去」，兩個都要設。
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
"=== 啟動 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" | Out-File $log -Append -Encoding utf8

# 掛掉就重開，用指數退避。
#
# 這支比訓練那支更需要它：換一次模型會跑 build 與 Cloud Run 部署，中間任何一段
# 網路中斷都會讓整個程序結束。固定間隔重試在永久性失敗時會變成每秒寫一次記錄檔。
$delay = 15
while ($true) {
    # 2>&1 讓 Python 的錯誤也進同一個檔：部署失敗的原因多半印在 stderr，
    # 分成兩個檔的話，看記錄的人會先看到「什麼都沒有」。
    # -u 關掉輸出緩衝。少了它，這個迴圈裡的訊息會卡在 Python 的 4KB 緩衝區，
    # 而守候型程式不會結束，所以記錄檔永遠停在「啟動」那一行——真正需要看
    # 記錄的時候（換模型失敗、部署卡住）那裡什麼都沒有。
    & $python -u tools\promotion_worker.py *>&1 | Out-File $log -Append -Encoding utf8
    $code = $LASTEXITCODE

    # 130 = 使用者按了 Ctrl+C。那是明確的「停下來」，不要跟他作對。
    if ($code -eq 130) {
        "=== 手動停止 $(Get-Date -Format 'HH:mm:ss') ===" | Out-File $log -Append -Encoding utf8
        break
    }

    "=== worker 結束（結束碼 $code），$delay 秒後重啟 $(Get-Date -Format 'HH:mm:ss') ===" |
        Out-File $log -Append -Encoding utf8
    Start-Sleep -Seconds $delay
    $delay = [math]::Min($delay * 2, 300)

    if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
        Move-Item $log "$log.1" -Force
    }
}
