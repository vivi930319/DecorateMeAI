param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$Repository = "beauty-backend",
    [string]$Tag = (Get-Date -Format "yyyyMMdd-HHmmss"),
    # 常駐執行個體數。預設 0＝沒有人用的時候整個縮回去，不計費。
    # 這裡刻意讓「省錢」當預設值：之前這個值寫死 1，兩支服務就以每天約 NT$492 的
    # 速度空轉，而實測 168 小時裡只有 21 小時真的有請求進來——其餘 87% 付的是
    # 「沒有人在等的那 15 秒冷啟動」。
    # Demo／口試要完全沒有冷啟動時用 -MinInstances 1 部署；結束後照平常方式部署就會
    # 回到 0。不必記得改回來——那正是把預設值設成 0 的用意，靠註解提醒是沒有用的。
    [ValidateRange(0, 10)]
    [int]$MinInstances = 0,
    # 每個執行個體的 vCPU。同樣讓省錢當預設：4 顆是舊值，而實測 99 百分位只用到
    # 0.85 顆。Demo 當天要 4 顆請用 tools/demo_scale.ps1 -Mode demo，它會連
    # min-instances 一起調，而且有對應的 -Mode restore。
    [ValidateSet("1", "2", "4", "8")]
    [string]$Cpu = "2"
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\tools\deploy_helpers.ps1"
$registry = "$Region-docker.pkg.dev/$ProjectId/$Repository"
$image = "$registry/backend:$Tag"

Write-Host "Verifying versioned face models..."
python tools/download_face_models.py

Write-Host "Building $image..."
# 2026-08-23：原始碼分成 face/ gateway/ render/ shared/ 之後，根目錄不再有 Dockerfile。
# `builds submit --tag` 只會去找根目錄那一個，所以改成跟 gateway／render 一樣用
# cloudbuild 設定明確指定 -f face/Dockerfile。三個服務現在是同一套做法。
& gcloud.cmd builds submit --project $ProjectId --config cloudbuild.face.yaml --substitutions "_IMAGE=$image" .
if ($LASTEXITCODE -ne 0) { Show-BuildFailure $ProjectId "face" }

$common = @(
    "--project", $ProjectId,
    "--region", $Region,
    "--platform", "managed",
    "--image", $image,
    # 4 顆是 2026-09-09 之前的值。實測尖峰只用到 0.85 顆（99 百分位），降到 2 顆
    # 仍有兩倍餘裕。Demo 要調回 4 請用 tools/demo_scale.ps1 -Mode demo，不要改這裡——
    # 寫死在部署腳本裡等於每次部署都替那個決定重新投一次票。
    "--cpu", "$Cpu",
    # 記憶體刻意維持 8 GiB。尖峰只用 2.7 GiB 看起來很浪費，但那是在幾乎沒有併發的
    # 週次量到的；而 CPU 不夠只是慢，記憶體不夠是整個容器被殺（使用者看到 503）。
    "--memory", "8Gi",
    "--concurrency", "6",
    "--timeout", "300s",
    # 這個值寫進的是 revision，不是 service。Cloud Console 的服務頂層會顯示
    # 「Autoscaling minimum = 0」——它讀的是 service 層另一個欄位，那個 0 是假的，
    # 真正生效的是這裡。要確認線上實際值，看 revision 的 autoscaling.knative.dev/minScale，
    # 或直接看計費：常駐一個 instance 的服務，billable_instance_time 會是每天 86400 秒。
    "--min-instances", "$MinInstances",
    "--max-instances", "10",
    # 預設的「只在處理請求時計費」。這一項改過一次來回，理由要留著：
    #
    # 原本是 --no-cpu-throttling，因為分析跑在 FastAPI 的 BackgroundTasks 裡，
    # 而那段程式在回應送出之後才執行——CPU 被節流的話它會停在那裡不動。
    # 代價是實例活著的每一秒都計費：face-basic 一週計費 99,576 秒，真正在運算的
    # 只有約 1,900 秒；face-pro 是 83,104 秒對不到 1%。
    #
    # 2026-09-10 把分析搬進請求裡（見 create_basic_job 的說明），所以節流可以開回來。
    # **兩者是綁在一起的**：要是哪天分析又被丟回背景執行，這裡就必須跟著改回
    # --no-cpu-throttling，否則工作會做不完；反過來，這裡改回去而分析仍是同步的，
    # 就是白白多付一筆閒置費用。
    "--cpu-throttling",
    "--cpu-boost",
    "--quiet"
)

# 常駐是要付錢的，所以它必須在部署當下被看見，而不是等到月底看帳單才發現。
# 這一則只在有人明確要求常駐時出現，平常（預設 0）安靜。
if ($MinInstances -gt 0) {
    Write-Host "注意：--min-instances=$MinInstances，face-basic 與 face-pro 會 24/7 常駐計費（每支每天約 NT`$246）。Demo 結束後用預設值重新部署即可回到 0。" -ForegroundColor Yellow
}

# FACE_CONTRIB_ENABLED=1：開啟「使用者同意提供的五官裁切」保存（見 face_contributions）。
# 這條路徑會保存臉部資料，所以刻意做成部署時明確開啟，程式碼上線不等於功能生效。
# 要關掉就把值改成 0 重新部署——不要只改程式碼，那樣舊修訂版還在跑。
Write-Host "Deploying face-basic..."
& gcloud.cmd run deploy face-basic @common --update-env-vars "SERVICE_NAME=basic,ROI_MODEL_FIRST=1,FACE_CONTRIB_ENABLED=1"
if ($LASTEXITCODE -ne 0) { throw "face-basic deployment failed" }

Write-Host "Deploying face-pro..."
& gcloud.cmd run deploy face-pro @common --update-env-vars "SERVICE_NAME=pro,ROI_MODEL_FIRST=1,PRO_NOSE_SIDE_ENABLED=1,FACE_CONTRIB_ENABLED=1"
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

    # 再打一次 /health 拿模型清單。這兩個服務只允許 Gateway／專案成員呼叫，所以要帶 ID token。
    #
    # 2026-08-17 實測修正：這裡原本只用 `--audiences=$url` 簽 token，而使用者帳號憑證產不出
    # 指定 audience 的 ID token（gcloud 直接回 "Requires valid service account."）。結果每次
    # 部署都掉進下面的「略過」分支——健康檢查形同不存在，模型清單從來沒有真的被驗過。
    # 這比沒有檢查更危險：它每次都印一行看起來有在做事的黃字。
    #
    # 改成先試**不帶** --audiences。舊註解斷言那種 token「必定 401」，但實測不成立：
    # 2026-08-17 用使用者帳號對 face-basic /health 實測回 200（同一個做法也修好了 warmup.ps1，
    # 那支之前不帶 token，三個網址全部 403，等於從來沒暖到機）。
    # 服務帳號憑證兩種都簽得出來，所以保留 --audiences 當後備，CI 換成服務帳號時仍然可用。
    #
    # 取 token 這一步**必須**擋住 $ErrorActionPreference = "Stop"。
    # PowerShell 5.1 對原生命令做 stderr 重導（`2>$null`）時，會把每一行 stderr 包成
    # NativeCommandError；在 Stop 模式下那是終止性錯誤，腳本會死在這一行，**根本跑不到
    # 下面那個 $LASTEXITCODE 判斷**——防呆寫了等於沒寫，實測就是這樣掛的。
    # 所以改成 try/finally 暫時放寬，並且不要重導 stderr。
    $token = $null
    $previousEap = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $token = & gcloud.cmd auth print-identity-token
        if (-not $token) { $token = & gcloud.cmd auth print-identity-token --audiences=$url }
    } catch {
        $token = $null
    } finally {
        $ErrorActionPreference = $previousEap
    }
    if (-not $token) {
        # 兩種簽法都拿不到（多半是沒有 gcloud 登入）。這是憑證問題，不是部署有問題，
        # 所以只提示不失敗——部署成不成功由上面的 Ready 判定，這裡只是加碼資訊。
        Write-Host "$service Ready（修訂版 $revision）；/health 略過：簽不出 ID token（先確認 gcloud auth login）" -ForegroundColor Yellow
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
