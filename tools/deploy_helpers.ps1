# 部署腳本共用的錯誤處理。用 dot-source 引入：
#     . "$PSScriptRoot\tools\deploy_helpers.ps1"
#
# 為什麼要有這一支
# ----------------
# 三支部署腳本原本都寫 `if ($LASTEXITCODE -ne 0) { throw "Cloud Build failed" }`。
# 那句話只說「失敗了」，沒說**為什麼**——而 gcloud 的實際錯誤已經被沖到螢幕上方
# 幾百行之外，或根本在 Cloud Build 那邊。2026-08-26 就因此花了額外的時間去
# `gcloud builds list` 再 `gcloud builds log` 才知道發生什麼事。
#
# 一個只會說「失敗」的錯誤訊息，等於把診斷工作丟回給人做。

function Show-BuildFailure {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectId,
        [Parameter(Mandatory = $true)][string]$What
    )

    Write-Host ""
    Write-Host "════ $What 的 Cloud Build 失敗 ════" -ForegroundColor Red

    # 抓最近一次 build 的狀態與日誌尾巴。查不到就說查不到，不要假裝有診斷——
    # 「拿不到日誌」跟「日誌是空的」是不同的情況，混在一起會讓人往錯的方向找。
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $row = & gcloud.cmd builds list --project $ProjectId --limit 1 `
            --format="value(id,status,createTime)" 2>$null
        if (-not $row) {
            Write-Host "  查不到任何 build 紀錄。" -ForegroundColor Yellow
            Write-Host "  最可能的原因是**還沒送進 Cloud Build 就失敗了**：" -ForegroundColor Yellow
            Write-Host "    - 上傳來源太慢或中斷（models/ 有好幾百 MB，看 .gcloudignore 有沒有把它排除）"
            Write-Host "    - gcloud 憑證過期：gcloud auth login"
            Write-Host "    - 專案或權限不對：gcloud config get-value project"
        } else {
            $parts = $row -split "`t"
            Write-Host ("  最近一次 build：{0}　狀態 {1}　{2}" -f $parts[0], $parts[1], $parts[2])
            Write-Host "  ── 日誌尾巴 ──"
            $log = & gcloud.cmd builds log $parts[0] --project $ProjectId 2>$null
            if ($log) {
                $log | Select-Object -Last 25 | ForEach-Object { "    $_" }
            } else {
                Write-Host "    （讀不到日誌，用瀏覽器看：" -NoNewline
                Write-Host "https://console.cloud.google.com/cloud-build/builds?project=$ProjectId)"
            }
        }
    } catch {
        Write-Host "  取得診斷資訊時本身也失敗了：$($_.Exception.Message)" -ForegroundColor Yellow
    } finally {
        $ErrorActionPreference = $previous
    }

    Write-Host "════════════════════════════════" -ForegroundColor Red
    throw "$What 的 Cloud Build 失敗（詳情見上方）"
}
