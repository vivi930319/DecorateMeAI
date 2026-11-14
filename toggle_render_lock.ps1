# 試妝實驗：開關 staging 渲染副本（replicate-render-lock）的渲染端身分鎖定。
#
#   .\toggle_render_lock.ps1 on      # 開：staging 網站試妝會在指令最後加三句身分鎖定（實驗 S2）
#   .\toggle_render_lock.ps1 off     # 關：跟正式站一樣（其他設定）
#   .\toggle_render_lock.ps1         # 只看目前狀態
#
# 只動副本，正式站的 replicate-render 不受影響。staging Gateway 由 deploy_gateway_staging.ps1
# 自動接到這個副本；實驗做完刪掉副本、再跑一次 deploy_gateway_staging.ps1 -SyncOnly 就接回正式的。
param([ValidateSet("on", "off", "")][string]$State = "")

$ErrorActionPreference = "Stop"
$Service = "replicate-render-lock"
$Region = "asia-east1"
$ProjectId = "decorate-me"

function Show-State {
    $rev = (& gcloud.cmd run services describe $Service --project $ProjectId --region $Region --format="value(status.latestReadyRevisionName)").Trim()
    $envJson = & gcloud.cmd run revisions describe $rev --project $ProjectId --region $Region --format="json(spec.containers[0].env)" | Out-String | ConvertFrom-Json
    $lock = ($envJson.spec.containers[0].env | Where-Object { $_.name -eq "RENDER_IDENTITY_LOCK" }).value
    $label = if ($lock -and $lock -ne "0") { "開（S2）" } else { "關" }
    Write-Host "$Service 實際在跑 $rev：渲染端身分鎖定 = $label" -ForegroundColor Cyan
    return $lock
}

if ($State -eq "") { Show-State | Out-Null; exit 0 }

$value = if ($State -eq "on") { "1" } else { "0" }
& gcloud.cmd run services update $Service --project $ProjectId --region $Region --update-env-vars "RENDER_IDENTITY_LOCK=$value" --quiet
if ($LASTEXITCODE -ne 0) { throw "更新失敗" }

$actual = Show-State
if ("$actual" -ne $value) { throw "實際在跑的 revision 不是 RENDER_IDENTITY_LOCK=$value，請再檢查" }
Write-Host "完成。通知她可以開始做這個設定的試妝。" -ForegroundColor Green
