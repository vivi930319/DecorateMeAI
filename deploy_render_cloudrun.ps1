param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$ServiceName = "replicate-render",
    [string]$Repository = "beauty-backend",
    [string]$ImageName = "replicate-render",
    [string]$Tag = "latest",
    [string]$GcsBucketName = "",
    # 必須指向和 Gateway 使用同一個 Ollama 建議服務；不要把會變動的 tunnel 網址寫死在腳本。
    [string]$SuggestionServiceUrl = $env:SUGGESTION_SERVICE_URL,
    # 測試壞掉還是要硬上（只在緊急回復時用，而且要自己知道在做什麼）
    [switch]$SkipTests
)

# gcloud 把 InsecureRequestWarning 寫到 stderr，而 PowerShell 5.1 在 Stop 之下會把原生指令的
# stderr 包成 NativeCommandError 並中斷——即使 gcloud 其實成功（exit code 0）。
# 這支腳本本來就每一步都檢查 $LASTEXITCODE，所以改用 Continue，讓 exit code 說了算。
$ErrorActionPreference = "Continue"

if ([string]::IsNullOrWhiteSpace($SuggestionServiceUrl) -or $SuggestionServiceUrl -notmatch '^https://[^/]+') {
    throw "部署中止：請先提供目前可用的 SUGGESTION_SERVICE_URL（https://...），而且必須和 ai-gateway 的 TEXT_SUGGESTION_URL 相同。"
}

# Tunnel 會變動，不能只檢查參數「有填」；直接讀目前 Gateway 的非秘密環境值，
# 把兩個上游不一致的情況在建置前攔下來。API key 只存在 Secret，不在這裡讀取。
$gatewayConfig = gcloud run services describe ai-gateway `
  --project=$ProjectId `
  --region=$Region `
  --format=json 2>$null
if ($LASTEXITCODE -ne 0 -or -not $gatewayConfig) {
    throw "部署中止：無法讀取 ai-gateway 的 TEXT_SUGGESTION_URL，不能確認 Ollama 上游是否一致。"
}
$gatewayObject = $gatewayConfig | ConvertFrom-Json
$gatewaySuggestionUrl = [string](
    @($gatewayObject.spec.template.spec.containers[0].env | Where-Object name -eq "TEXT_SUGGESTION_URL" | Select-Object -First 1).value
)
if ([string]::IsNullOrWhiteSpace($gatewaySuggestionUrl) -or
    $gatewaySuggestionUrl.TrimEnd('/') -ne $SuggestionServiceUrl.TrimEnd('/')) {
    $gatewayHost = if ($gatewaySuggestionUrl) { try { ([uri]$gatewaySuggestionUrl).Host } catch { 'invalid-url' } } else { 'empty' }
    $renderHost = try { ([uri]$SuggestionServiceUrl).Host } catch { 'invalid-url' }
    throw "部署中止：Render 與 Gateway 的 Ollama 上游不同（Gateway=$gatewayHost；Render=$renderHost）。"
}

# ── 部署門檻：測試沒過就不准上 production ──────────────────────────────
# 「等一下再修」在部署腳本裡永遠不會發生。紅燈就停在這裡，比上線後才發現便宜太多。
if (-not $SkipTests) {
    Write-Host "Running backend tests before deploying..." -ForegroundColor Cyan
    $python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
    $env:GATEWAY_SESSION_SECRET = "local-deploy-check-secret-at-least-32-bytes"
    $env:GATEWAY_FACE_API_KEY = "local-deploy-check"
    $env:GATEWAY_RENDER_API_KEY = "local-deploy-check"
    & $python -m pytest tests/ai_gateway_test.py tests/render_api_test.py tests/image_safety_test.py
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
  --ignore-file=.gcloudignore.render `
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
  --min-instances=1 `
  --no-cpu-throttling `
  --no-allow-unauthenticated `
  --update-env-vars "SUGGESTION_SERVICE_URL=$SuggestionServiceUrl,REQUIRE_PERSONALIZED_RENDER_PROMPT=1"
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
