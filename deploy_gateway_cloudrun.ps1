param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$ServiceName = "ai-gateway",
    [string]$Repository = "beauty-backend",
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmmss"),
    [switch]$SkipTests
)

$ErrorActionPreference = "Continue"
$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

if (-not $SkipTests) {
    $env:GATEWAY_SESSION_SECRET = "local-deploy-check-secret-at-least-32-bytes"
    $env:GATEWAY_FACE_API_KEY = "local-deploy-check"
    $env:GATEWAY_RENDER_API_KEY = "local-deploy-check"
    & $python -m pytest tests/ai_gateway_test.py tests/api_errors_test.py tests/render_api_test.py tests/image_safety_test.py
    if ($LASTEXITCODE -ne 0) { throw "Deployment stopped: backend tests failed." }
}

$image = "{0}-docker.pkg.dev/{1}/{2}/ai-gateway:{3}" -f $Region, $ProjectId, $Repository, $Tag
& gcloud.cmd builds submit `
    --project $ProjectId `
    --config cloudbuild.gateway.yaml `
    --ignore-file .gcloudignore.gateway `
    --substitutions "_IMAGE=$image" `
    .
if ($LASTEXITCODE -ne 0) { throw "Gateway image build failed." }

& gcloud.cmd run deploy $ServiceName `
    --project $ProjectId `
    --region $Region `
    --platform managed `
    --image $image `
    --cpu 1 `
    --memory 512Mi `
    --concurrency 40 `
    --timeout 600s `
    --max-instances 5 `
    --cpu-boost `
    --quiet
if ($LASTEXITCODE -ne 0) { throw "Gateway Cloud Run deployment failed." }

$url = (& gcloud.cmd run services describe $ServiceName --project $ProjectId --region $Region --format="value(status.url)").Trim()
$token = (& gcloud.cmd auth print-identity-token).Trim()
$health = Invoke-RestMethod -Uri "$url/health" -Headers @{ Authorization = "Bearer $token" } -TimeoutSec 60
if ($health.status -ne "ok") { throw "Gateway health is '$($health.status)'" }
Write-Host "Gateway deployed: $url ($image)"
