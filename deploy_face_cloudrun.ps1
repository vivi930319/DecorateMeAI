param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$Repository = "beauty-backend",
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmmss")
)

$ErrorActionPreference = "Stop"
$registry = "$Region-docker.pkg.dev/$ProjectId/$Repository"
$image = "$registry/backend:$Tag"

Write-Host "Verifying versioned face models..."
python tools/download_face_models.py

Write-Host "Building $image..."
& gcloud.cmd builds submit --project $ProjectId --tag $image .
if ($LASTEXITCODE -ne 0) { throw "Cloud Build failed" }

$common = @(
    "--project", $ProjectId,
    "--region", $Region,
    "--platform", "managed",
    "--image", $image,
    "--cpu", "4",
    "--memory", "8Gi",
    "--concurrency", "6",
    "--timeout", "300s",
    "--min-instances", "1",
    "--max-instances", "10",
    "--no-cpu-throttling",
    "--cpu-boost",
    "--quiet"
)

Write-Host "Deploying face-basic..."
& gcloud.cmd run deploy face-basic @common --update-env-vars "SERVICE_NAME=basic,ROI_MODEL_FIRST=1"
if ($LASTEXITCODE -ne 0) { throw "face-basic deployment failed" }

Write-Host "Deploying face-pro..."
& gcloud.cmd run deploy face-pro @common --update-env-vars "SERVICE_NAME=pro,ROI_MODEL_FIRST=1,PRO_NOSE_SIDE_ENABLED=1"
if ($LASTEXITCODE -ne 0) { throw "face-pro deployment failed" }

foreach ($service in @("face-basic", "face-pro")) {
    $url = (& gcloud.cmd run services describe $service --project $ProjectId --region $Region --format="value(status.url)").Trim()
    $health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 60
    if ($health.status -ne "ok") {
        throw "$service health is '$($health.status)'"
    }
    Write-Host "$service OK: $url ($($health.models | ConvertTo-Json -Compress))"
}

Write-Host "Face services deployed with image $image"
