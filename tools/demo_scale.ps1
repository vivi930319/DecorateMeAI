# Demo 當天的 Cloud Run 規模切換。
#
# 為什麼需要這支
# ----------------
# 平時的設定是省錢優先：三個服務都 min-instances=0，臉部分析降到 2 vCPU。那組設定
# 在「一次一個人用」的情況下綽綽有餘——實測一週 254 次 PRO 請求，尖峰 CPU 只用到
# 21%、記憶體 33%。
#
# 但 Demo 當天是七個人同時操作，會一次撞到三件事：
#
#   1. 冷啟動。min-instances=0 時機器是關的，第一個按下去的人要等它開。實測
#      face-basic 平均 15 秒（最慢 27 秒）、face-pro 平均 8 秒，數字來源見 warmup.ps1。
#   2. 併發稀釋 CPU。臉部服務每台同時收 6 個請求，2 vCPU 分給 6 個人是每人 0.33 顆。
#      平時量到的「尖峰只用 21%」是在**幾乎沒有併發**的情況下量的，不能拿來推估
#      七人同時的樣子——這是取樣的盲點，不是量錯。
#   3. 渲染排隊。replicate-render 每台只收 4 個並行，七個人同時按渲染需要兩台。
#
# 所以 Demo 前把規模開回去，結束後再降回來。多開那幾天大約 NT$100/天，
# 比 Demo 當場卡住便宜太多。
#
# 記憶體兩個模式都不動
# ----------------------
# 8 GiB 是刻意保留的。平時尖峰只用 2.4~2.7 GiB 看起來浪費，但那個數字同樣是在沒有
# 併發時量的；七個人同時上傳時是好幾份影像緩衝加推論同時存在，跟量到的不是同一回事。
# 而且 CPU 不夠只是慢，記憶體不夠是**整個容器被殺掉**（OOM，使用者看到 503）。
# 這支腳本因此不碰記憶體——列進來只會多一個手滑改錯的機會。
#
# 用法
# ------
#     .\tools\demo_scale.ps1 -Mode demo      # Demo 前一天執行
#     .\tools\demo_scale.ps1 -Mode restore   # Demo 結束後執行
#
# 執行完**還是要跑 warmup.ps1**。min-instances 保證「機器是開著的」，暖機保證
# 「模型已經載進記憶體」，那是兩件事：機器開著但沒載模型，第一個人一樣要等。

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("demo", "restore")]
    [string]$Mode,

    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1"
)

$ErrorActionPreference = "Stop"

# Cpu = $null 代表「這個服務不動 CPU」。replicate-render 只有 1 vCPU，本來就不是
# 瓶頸（它大部分時間在等 gpt-image-2 回應，那是網路等待不是運算），需要的是更多台
# 而不是更大台。
$plan = @{
    demo = @(
        @{ Service = "face-basic";       Cpu = "4";   MinInstances = "1" }
        @{ Service = "face-pro";         Cpu = "4";   MinInstances = "1" }
        @{ Service = "replicate-render"; Cpu = $null; MinInstances = "2" }
    )
    restore = @(
        @{ Service = "face-basic";       Cpu = "2";   MinInstances = "0" }
        @{ Service = "face-pro";         Cpu = "2";   MinInstances = "0" }
        @{ Service = "replicate-render"; Cpu = $null; MinInstances = "0" }
    )
}

function Get-RunningScale {
    param([string]$Service)

    # 讀**實際在跑的 revision**，不是 `services describe` 的 spec。後者顯示的是
    # 「最後一次送出去的設定」，送出去和真的上線是兩回事——這個專案在
    # 2026-09-04 就因為只看 describe 而誤判過一次部署成功。
    $revision = & gcloud.cmd run services describe $Service `
        --region $Region --project $ProjectId `
        --format="value(status.latestReadyRevisionName)" 2>$null
    if (-not $revision) { return $null }

    $row = & gcloud.cmd run revisions describe $revision.Trim() `
        --region $Region --project $ProjectId `
        --format="value(metadata.annotations['autoscaling.knative.dev/minScale'],spec.containers[0].resources.limits.cpu,spec.containers[0].resources.limits.memory)" 2>$null
    if (-not $row) { return $null }

    $parts = $row -split "`t"
    return [pscustomobject]@{
        Revision     = $revision.Trim()
        # minScale 沒設定時 gcloud 回空字串，那就是 0。空字串和 "0" 在畫面上差很多，
        # 但意思一樣，這裡統一成 0 免得對照時看起來像不一致。
        MinInstances = if ([string]::IsNullOrWhiteSpace($parts[0])) { "0" } else { $parts[0] }
        Cpu          = $parts[1]
        Memory       = $parts[2]
    }
}

$targets = $plan[$Mode]

Write-Host ""
Write-Host "════ 模式：$Mode　專案 $ProjectId／$Region ════" -ForegroundColor Cyan
Write-Host ""
Write-Host "── 目前狀態 ──"
foreach ($t in $targets) {
    $now = Get-RunningScale -Service $t.Service
    if ($now) {
        Write-Host ("  {0,-18} min={1}  cpu={2}  mem={3}  ({4})" -f `
            $t.Service, $now.MinInstances, $now.Cpu, $now.Memory, $now.Revision)
    } else {
        Write-Host ("  {0,-18} 讀不到（服務不存在或沒有權限）" -f $t.Service) -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "── 套用 ──"
$failed = @()
foreach ($t in $targets) {
    # 不要叫 $args——那是 PowerShell 的自動變數，覆寫它在某些呼叫情境下會出意外。
    $cmdArgs = @("run", "services", "update", $t.Service,
                 "--region", $Region, "--project", $ProjectId,
                 "--min-instances", $t.MinInstances)
    if ($t.Cpu) { $cmdArgs += @("--cpu", $t.Cpu) }

    $what = "min=$($t.MinInstances)" + $(if ($t.Cpu) { "  cpu=$($t.Cpu)" } else { "" })
    Write-Host ("  {0,-18} -> {1}" -f $t.Service, $what)

    # 一個服務失敗不該讓其餘的停在半途。Demo 前最怕的就是「跑到一半掛掉，
    # 現在到底哪些改了哪些沒改」——所以全部跑完，最後一次講清楚。
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & gcloud.cmd @cmdArgs 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $failed += $t.Service }
    } finally {
        $ErrorActionPreference = $previous
    }
}

Write-Host ""
Write-Host "── 核對（讀實際在跑的 revision）──"
$mismatch = @()
foreach ($t in $targets) {
    $now = Get-RunningScale -Service $t.Service
    if (-not $now) {
        Write-Host ("  {0,-18} 讀不到，無法確認" -f $t.Service) -ForegroundColor Red
        $mismatch += $t.Service
        continue
    }

    $okMin = $now.MinInstances -eq $t.MinInstances
    $okCpu = (-not $t.Cpu) -or ($now.Cpu -eq $t.Cpu)
    $line = "  {0,-18} min={1}  cpu={2}  mem={3}" -f $t.Service, $now.MinInstances, $now.Cpu, $now.Memory
    if ($okMin -and $okCpu) {
        Write-Host $line -ForegroundColor Green
    } else {
        Write-Host ($line + "　← 與預期不符") -ForegroundColor Red
        $mismatch += $t.Service
    }
}

Write-Host ""
if ($failed.Count -gt 0 -or $mismatch.Count -gt 0) {
    if ($failed.Count -gt 0) {
        Write-Host ("更新指令失敗：{0}" -f ($failed -join "、")) -ForegroundColor Red
    }
    if ($mismatch.Count -gt 0) {
        Write-Host ("套用後仍與預期不符：{0}" -f ($mismatch -join "、")) -ForegroundColor Red
    }
    Write-Host "請先處理上面這些再繼續，不要當成已完成。" -ForegroundColor Red
    exit 1
}

if ($Mode -eq "demo") {
    Write-Host "規模已開到 Demo 設定。" -ForegroundColor Green
    Write-Host ""
    Write-Host "還沒完成的兩件事：" -ForegroundColor Yellow
    Write-Host "  1. Demo 前 2~3 分鐘跑 .\warmup.ps1 —— 機器開著不等於模型載好了。"
    Write-Host "  2. Demo 結束後跑 .\tools\demo_scale.ps1 -Mode restore —— 忘了的話"
    Write-Host "     每個月會多付大約 NT$2,600。"
} else {
    Write-Host "規模已降回省錢設定。" -ForegroundColor Green
    Write-Host "第一位使用者會遇到冷啟動（face-basic 約 15 秒），這是預期行為。"
}
Write-Host ""
