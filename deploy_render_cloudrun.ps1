param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$ServiceName = "replicate-render",
    [string]$Repository = "beauty-backend",
    [string]$ImageName = "replicate-render",
    [string]$Tag = "latest",
    [string]$GcsBucketName = ""
)

$ErrorActionPreference = "Stop"

$image = "$Region-docker.pkg.dev/$ProjectId/$Repository/$ImageName`:$Tag"

Write-Host "Building image: $image"
gcloud builds submit `
  --project=$ProjectId `
  --config=cloudbuild.render.yaml `
  --substitutions=_IMAGE=$image `
  .

Write-Host "Deploying service: $ServiceName"
gcloud run deploy $ServiceName `
  --project=$ProjectId `
  --region=$Region `
  --image=$image `
  --platform=managed `
  --timeout=300s `
  --concurrency=4 `
  --allow-unauthenticated

Write-Host "Deployment finished. Checking health..."
$serviceUrl = gcloud run services describe $ServiceName --project=$ProjectId --region=$Region --format="value(status.url)"
Write-Host "Service URL: $serviceUrl"
Invoke-WebRequest -Uri "$serviceUrl/health" -UseBasicParsing | Select-Object -ExpandProperty Content

if ($GcsBucketName) {
    Write-Host "Applying GCS lifecycle policy to gs://$GcsBucketName"
    gcloud storage buckets update "gs://$GcsBucketName" --lifecycle-file=gcs-lifecycle.json
}
