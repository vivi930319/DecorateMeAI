param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$ServiceName = "replicate-render",
    [string]$Repository = "beauty-backend",
    [string]$ImageName = "replicate-render",
    [string]$Tag = "latest",
    [string]$GcsBucketName = "",
    # 測試壞掉還是要硬上（只在緊急回復時用，而且要自己知道在做什麼）
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"

# ── 部署門檻：測試沒過就不准上 production ──────────────────────────────
# 「等一下再修」在部署腳本裡永遠不會發生。紅燈就停在這裡，比上線後才發現便宜太多。
if (-not $SkipTests) {
    Write-Host "Running backend tests before deploying..." -ForegroundColor Cyan
    $python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
    $env:GATEWAY_SESSION_SECRET = "local-deploy-check-secret-at-least-32-bytes"
    $env:GATEWAY_FACE_API_KEY = "local-deploy-check"
    $env:GATEWAY_RENDER_API_KEY = "local-deploy-check"
    & $python -m unittest ai_gateway_test.py render_api_test.py image_safety_test.py
    if ($LASTEXITCODE -ne 0) {
        throw "部署中止：後端測試沒有通過。修好再部署，或在確認過的緊急情況下加 -SkipTests。"
    }
    Write-Host "Tests passed." -ForegroundColor Green
}

$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:$Tag"

Write-Host "Building image: $image"
gcloud builds submit `
  --project=$ProjectId `
  --config=cloudbuild.render.yaml `
  --substitutions=_IMAGE=$image `
  .
if ($LASTEXITCODE -ne 0) { throw "部署中止：映像建置失敗。" }

Write-Host "Deploying service: $ServiceName"
# --no-allow-unauthenticated：Render 服務只接受 Gateway 的 service account（P0-7）。
# 這裡原本是 --allow-unauthenticated——只要有人跑過一次這支腳本，就會把 Cloud Run 上
# 已經移除的 allUsers 綁回去，把匿名直連的洞重新打開。
gcloud run deploy $ServiceName `
  --project=$ProjectId `
  --region=$Region `
  --image=$image `
  --platform=managed `
  --timeout=300s `
  --concurrency=4 `
  --no-allow-unauthenticated
if ($LASTEXITCODE -ne 0) { throw "部署中止：Cloud Run 部署失敗。" }

Write-Host "Deployment finished. Checking health..."
$serviceUrl = gcloud run services describe $ServiceName --project=$ProjectId --region=$Region --format="value(status.url)"
Write-Host "Service URL: $serviceUrl"
# 服務不對外開放，所以健康檢查要帶自己的 identity token；直接 GET 會拿到 403，
# 那是「設定正確」的樣子，不是故障。
$token = gcloud auth print-identity-token
try {
    $health = Invoke-WebRequest -Uri "$serviceUrl/health" -UseBasicParsing -Headers @{ Authorization = "Bearer $token" }
    Write-Host $health.Content
} catch {
    throw "部署後健康檢查失敗：$($_.Exception.Message)"
}

if ($GcsBucketName) {
    Write-Host "Applying GCS lifecycle policy to gs://$GcsBucketName"
    gcloud storage buckets update "gs://$GcsBucketName" --lifecycle-file=gcs-lifecycle.json
}
