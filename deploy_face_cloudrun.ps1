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
    # 用 filter 挑 Ready 這個條件，不要用 conditions[0]：那是位置索引，Cloud Run 沒有保證
    # Ready 一定排第一個，順序一變就會拿到別的條件（例如 ConfigurationsReady）當成結論。
    #
    # 比對子要用 `=` 不能用 `:`：`:` 是「包含」，`type:Ready` 會同時命中 Ready、
    # ConfigurationsReady 與 RoutesReady，實測回傳 "True;True;True"，跟 "True" 比一定不等，
    # 於是每次部署都被判成失敗——又繞回這段程式要修的那個毛病。
    $ready = & gcloud.cmd @describe --format="value(status.conditions.filter(`"type=Ready`").firstof(status))"
    if ($LASTEXITCODE -ne 0) { throw "$service 狀態查詢失敗（gcloud 結束碼 $LASTEXITCODE）" }
    $revision = & gcloud.cmd @describe --format="value(status.latestReadyRevisionName)"
    if ($LASTEXITCODE -ne 0) { throw "$service 修訂版查詢失敗（gcloud 結束碼 $LASTEXITCODE）" }
    $ready = "$ready".Trim(); $revision = "$revision".Trim()
    # 查詢本身失敗時要說「查不到」，不要說「沒 Ready」——否則一次暫時性的 API 失誤
    # 就會把一次成功的部署報成失敗，正是這段程式當初要修掉的毛病。
    if (-not $ready) { throw "$service 讀不到 Ready 狀態，無法確認部署結果" }
    if ($ready -ne "True") {
        throw "$service 的修訂版 $revision 未進入 Ready 狀態（Ready=$ready）"
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
    # 取 token 這一步**必須**擋住 $ErrorActionPreference = "Stop"。
    # PowerShell 5.1 對原生命令做 stderr 重導（`2>$null`）時，會把每一行 stderr 包成
    # NativeCommandError；在 Stop 模式下那是終止性錯誤，腳本會死在這一行，**根本跑不到
    # 下面那個 $LASTEXITCODE 判斷**——防呆寫了等於沒寫，實測就是這樣掛的。
    # 所以改成 try/finally 暫時放寬，並且不要重導 stderr。
    $token = $null
    $previousEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $token = & gcloud.cmd auth print-identity-token --audiences=$url
    } catch {
        $token = $null
    } finally {
        $ErrorActionPreference = $previousEap
    }
    if (-not $token) {
        # 使用者帳號憑證產不出指定 audience 的 ID token（gcloud 直接回 "Requires valid
        # service account."）。這是憑證類型的限制，不是部署有問題，所以只提示不失敗。
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
