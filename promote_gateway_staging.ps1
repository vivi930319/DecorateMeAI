# 把 staging Gateway 正在跑的 image，原封不動放上正式的 ai-gateway。說明書（SIT 契約書）：https://claude.ai/code/artifact/3d1acf29-4f86-4a29-9c78-a9c500831d73
#
# 用法（SIT 通過之後才跑）：
#   .\promote_gateway_staging.ps1
#
# 為什麼不重新建置：重建出來的 image 就不是 SIT 驗過的那一個了——相依套件可能升版、
# 工作目錄可能多了沒測過的修改。上線的東西必須跟測過的東西是同一個 digest。
#
# 這支只換 image，不碰正式環境的環境變數與密鑰（gcloud run deploy 沒給 env 參數時沿用原值），
# 所以 staging 專用的設定（staging_ 前綴、staging 的 session 密鑰）不會跟著過去。

param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1"
)

$ErrorActionPreference = "Stop"

$image = (& gcloud.cmd run services describe ai-gateway-staging --project $ProjectId --region $Region --format="value(spec.template.spec.containers[0].image)").Trim()
if (-not $image) { throw "讀不到 ai-gateway-staging 的 image" }
$digest = (& gcloud.cmd artifacts docker images describe $image --format="value(image_summary.digest)").Trim()
if (-not $digest) { throw "解析不出 $image 的 digest" }
$current = (& gcloud.cmd run services describe ai-gateway --project $ProjectId --region $Region --format="value(spec.template.spec.containers[0].image)").Trim()

Write-Host "正式環境目前：$current"
Write-Host "要換成      ：$image"
Write-Host "             $digest"

# 參數與 deploy_gateway_cloudrun.ps1 相同，只是不建置。
& gcloud.cmd run deploy ai-gateway `
    --project $ProjectId --region $Region --platform managed `
    --image $image `
    --cpu 1 --memory 512Mi --concurrency 40 --timeout 600s `
    --max-instances 5 --cpu-boost `
    --quiet
if ($LASTEXITCODE -ne 0) { throw "正式 Gateway 部署失敗，線上維持 $current" }

$revision = (& gcloud.cmd run services describe ai-gateway --project $ProjectId --region $Region --format="value(status.latestReadyRevisionName)").Trim()
$running = (& gcloud.cmd run revisions describe $revision --project $ProjectId --region $Region --format="value(spec.containers[0].image)").Trim()
if ($running -ne $image -and -not $running.EndsWith("@$digest")) {
    throw "正式環境實際在跑的是 $running，不是 staging 驗過的 $image"
}
$url = (& gcloud.cmd run services describe ai-gateway --project $ProjectId --region $Region --format="value(status.url)").Trim()
$health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 60
if ($health.status -ne "ok") { throw "正式 Gateway health 是 '$($health.status)'" }

Write-Host ""
Write-Host "正式 Gateway 已換成 staging 驗過的版本" -ForegroundColor Green
Write-Host "  revision : $revision"
Write-Host "  image    : $image"
Write-Host "  要退回   : gcloud run services update-traffic ai-gateway --region $Region --to-revisions <上一個 revision>=100"
