# staging 的 Gateway（ai-gateway-staging）。說明書（SIT 契約書）：https://claude.ai/code/artifact/3d1acf29-4f86-4a29-9c78-a9c500831d73
#
# 用法
#   .\deploy_gateway_staging.ps1                 用目前的程式碼建新 image，部署到 staging
#   .\deploy_gateway_staging.ps1 -Image <完整 image 名>   不建置，直接把現成的 image 放上 staging
#   .\deploy_gateway_staging.ps1 -SyncOnly       不換 image，只把正式環境的上游網址重新抄一次
#                                                （組員的 tunnel 換網址之後跑這個）
#
# staging 跟正式環境的差別，全部集中在這支腳本裡（下面 $overrides 那一段）：
#   - 自己的 session 密鑰：staging 簽的登入狀態拿到正式環境不能用，反之亦然。
#   - CORS 只放行 staging 的前端網址。
#   - 自己的 Firestore 集合（staging_ 前綴）：登入限流、訪客試用、後台稽核、訓練與換上線請求。
#     最後一項最重要：本機的訓練機只看正式的集合，所以在 staging 後台按「換上線」不會真的部署。
# 其餘設定（上游網址、金鑰、逾時）每次部署都從正式的 ai-gateway 抄過來，兩邊不會漂移。

param(
    [string]$ProjectId = "decorate-me",
    [string]$Region = "asia-east1",
    [string]$Repository = "beauty-backend",
    [string]$Image = "",
    [switch]$SyncOnly,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\tools\deploy_helpers.ps1"

$ProdService = "ai-gateway"
$StagingService = "ai-gateway-staging"
$ServiceAccount = "ai-gateway@$ProjectId.iam.gserviceaccount.com"
$SessionSecret = "decorate-me-gateway-session-secret-staging"
$StagingOrigins = "https://decorate-me-staging.web.app,https://decorate-me-staging.firebaseapp.com"

# ── 1. 讀正式環境的設定 ─────────────────────────────────────────────
$prod = (& gcloud.cmd run services describe $ProdService --project $ProjectId --region $Region --format=json) | Out-String | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $prod) { throw "讀不到正式的 $ProdService 設定" }
$plain = [ordered]@{}
$secretRefs = [ordered]@{}
foreach ($e in $prod.spec.template.spec.containers[0].env) {
    if ($null -ne $e.valueFrom) {
        $secretRefs[$e.name] = "{0}:{1}" -f $e.valueFrom.secretKeyRef.name, $e.valueFrom.secretKeyRef.key
    } else {
        $plain[$e.name] = $e.value
    }
}
# 這兩個只是「上次手動輪替的時間」標記，沒有程式在讀，不抄。
$plain.Remove("SECRET_REFRESHED_AT")
$plain.Remove("IAM_REFRESHED_AT")

# ── 2. 決定 image ─────────────────────────────────────────────────
if ($SyncOnly) {
    $Image = (& gcloud.cmd run services describe $StagingService --project $ProjectId --region $Region --format="value(spec.template.spec.containers[0].image)").Trim()
    if (-not $Image) { throw "$StagingService 還不存在，第一次請不要加 -SyncOnly" }
} elseif (-not $Image) {
    if (-not $SkipTests) {
        $python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }
        $env:GATEWAY_SESSION_SECRET = "local-deploy-check-secret-at-least-32-bytes"
        $env:GATEWAY_FACE_API_KEY = "local-deploy-check"
        $env:GATEWAY_RENDER_API_KEY = "local-deploy-check"
        & $python -m pytest -p no:warnings tests/ai_gateway_test.py tests/api_errors_test.py tests/render_api_test.py tests/image_safety_test.py tests/gateway_collection_prefix_test.py
        if ($LASTEXITCODE -ne 0) { throw "測試沒過，不部署。" }
    }
    $Image = "{0}-docker.pkg.dev/{1}/{2}/ai-gateway:{3}" -f $Region, $ProjectId, $Repository, (Get-Date -Format "yyyyMMdd-HHmmss")
    & gcloud.cmd builds submit --project $ProjectId --config cloudbuild.gateway.yaml --ignore-file .gcloudignore.gateway --substitutions "_IMAGE=$Image" .
    if ($LASTEXITCODE -ne 0) { Show-BuildFailure $ProjectId "gateway (staging)" }
}

# ── 3. staging 專用的 session 密鑰（沒有就建一個）──────────────────
$previousEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& gcloud.cmd secrets describe $SessionSecret --project $ProjectId --format="value(name)" *> $null
$secretExists = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $previousEap
if (-not $secretExists) {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tmp, [Convert]::ToBase64String($bytes))
        & gcloud.cmd secrets create $SessionSecret --project $ProjectId --replication-policy automatic --data-file $tmp
        if ($LASTEXITCODE -ne 0) { throw "建立 $SessionSecret 失敗" }
    } finally {
        Remove-Item $tmp -Force
    }
}
& gcloud.cmd secrets add-iam-policy-binding $SessionSecret --project $ProjectId `
    --member "serviceAccount:$ServiceAccount" --role roles/secretmanager.secretAccessor --quiet | Out-Null
if ($LASTEXITCODE -ne 0) { throw "無法讓 $ServiceAccount 讀取 $SessionSecret" }

# ── 4. staging 跟正式環境不同的地方 ─────────────────────────────────
$overrides = [ordered]@{
    "CORS_ORIGINS"                    = $StagingOrigins
    "GATEWAY_COLLECTION_PREFIX"       = "staging_"
    "GATEWAY_LOGIN_LIMIT_COLLECTION"  = "staging_gateway_login_limits"
    "GATEWAY_GUEST_TRIAL_COLLECTION"  = "staging_gateway_guest_trials"
    "GATEWAY_GUEST_TICKET_COLLECTION" = "staging_gateway_guest_tickets"
    "ADMIN_AUDIT_COLLECTION"          = "staging_admin_audit_events"
}
foreach ($k in $overrides.Keys) { $plain[$k] = $overrides[$k] }
$secretRefs["GATEWAY_SESSION_SECRET"] = "${SessionSecret}:latest"

# 環境變數用檔案傳，不用 --set-env-vars。CORS_ORIGINS 的值有逗號，得用 gcloud 的
# 自訂分隔符；但 gcloud.cmd 會經過 cmd.exe，`|` 被當成管線、`^` 被當成跳脫字元，
# 實測 `^|^` 讓 cmd 把 CORS_ORIGINS 當成一個指令去執行。JSON 是合法的 YAML，檔案裡沒有這些問題。
$envFile = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllText($envFile, ($plain | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
$secretArg = ($secretRefs.Keys | ForEach-Object { "$_=$($secretRefs[$_])" }) -join ","

# ── 5. 部署 ───────────────────────────────────────────────────────
try {
    & gcloud.cmd run deploy $StagingService `
        --project $ProjectId --region $Region --platform managed `
        --image $Image `
        --service-account $ServiceAccount `
        --env-vars-file $envFile `
        --set-secrets $secretArg `
        --cpu 1 --memory 512Mi --concurrency 40 --timeout 600s `
        --min-instances 0 --max-instances 2 --cpu-boost `
        --allow-unauthenticated `
        --quiet
    $deployExit = $LASTEXITCODE
} finally {
    Remove-Item $envFile -Force -ErrorAction SilentlyContinue
}
if ($deployExit -ne 0) { throw "$StagingService 部署失敗" }

# ── 6. 驗證：實際在跑的 revision 用的是不是這個 image ───────────────
# 不看 services describe 的 spec（那是「期望狀態」），看 latestReadyRevision 本身。
$revision = (& gcloud.cmd run services describe $StagingService --project $ProjectId --region $Region --format="value(status.latestReadyRevisionName)").Trim()
# revision 記的是 digest（…@sha256:xxx），不是 tag，所以把 tag 解析成 digest 再比。
$running = (& gcloud.cmd run revisions describe $revision --project $ProjectId --region $Region --format="value(spec.containers[0].image)").Trim()
$digest = (& gcloud.cmd artifacts docker images describe $Image --format="value(image_summary.digest)").Trim()
if (-not $digest) { throw "解析不出 $Image 的 digest，無法確認 staging 在跑哪個版本" }
if ($running -ne $Image -and -not $running.EndsWith("@$digest")) {
    throw "staging 實際在跑的是 $running，不是剛部署的 $Image（$digest）"
}
$url = (& gcloud.cmd run services describe $StagingService --project $ProjectId --region $Region --format="value(status.url)").Trim()
$health = Invoke-RestMethod -Uri "$url/health" -TimeoutSec 60
if ($health.status -ne "ok") { throw "staging health 是 '$($health.status)'" }

Write-Host ""
Write-Host "staging Gateway 就緒" -ForegroundColor Green
Write-Host "  revision : $revision"
Write-Host "  image    : $Image"
Write-Host "  網址     : $url"
Write-Host "  上游     : 會員 $($plain['MEMBER_DATABASE_URL'])"
Write-Host "             Ollama $($plain['TEXT_SUGGESTION_URL'])"
