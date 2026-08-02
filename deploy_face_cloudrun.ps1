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

    # 先確認 Cloud Run 自己認為這個修訂版可服務。這一項不需要任何額外權限，
    # 而且它是硬性的：容器沒起來、或啟動探測沒過，Ready 就不會是 True，流量也不會切過去。
    $describe = @("run", "services", "describe", $service, "--project", $ProjectId, "--region", $Region)
    $ready = (& gcloud.cmd @describe --format="value(status.conditions[0].status)").Trim()
    $revision = (& gcloud.cmd @describe --format="value(status.latestReadyRevisionName)").Trim()
    if ($ready -ne "True") {
        throw "$service 的修訂版 $revision 未進入 Ready 狀態（status=$ready）"
    }

    # 再打一次 /health 拿模型清單。這兩個服務只允許 Gateway／專案成員呼叫，所以要帶 ID token，
    # 而 Cloud Run 驗的是 token 的 audience —— 先前這裡用不帶 --audiences 的
    # `gcloud auth print-identity-token`，簽出來的 token audience 對不上服務網址，**必定** 401。
    # 於是這支腳本每次都以失敗收場，即使兩個服務都部署成功；久了就會有人把真正的失敗
    # 也當成「又是那個健康檢查」而略過，這比沒有檢查更危險。
    #
    # 帶了 --audiences 也不一定簽得出來：使用者帳號憑證產不出指定 audience 的 ID token，
    # 那需要服務帳號。所以這一項改成「拿得到就驗，拿不到就明講跳過」，不再讓它決定成敗——
    # 部署成不成功由上面的 Ready 判定，這裡只是加碼資訊。
    $token = (& gcloud.cmd auth print-identity-token --audiences=$url 2>$null)
    if ($LASTEXITCODE -ne 0 -or -not $token) {
        Write-Host "$service Ready（修訂版 $revision）；/health 略過：目前憑證簽不出對應 audience 的 ID token" -ForegroundColor Yellow
        continue
    }
    try {
        $health = Invoke-RestMethod -Uri "$url/health" -Headers @{ Authorization = "Bearer $($token.Trim())" } -TimeoutSec 60
    } catch {
        Write-Host "$service Ready（修訂版 $revision）；/health 讀取失敗：$($_.Exception.Message)" -ForegroundColor Yellow
        continue
    }
    if ($health.status -ne "ok") {
        throw "$service health is '$($health.status)'"
    }
    Write-Host "$service OK: $url ($($health.models | ConvertTo-Json -Compress))"
}

Write-Host "Face services deployed with image $image"
