# 共用入口：.\update-db-endpoints.ps1 https://shared.trycloudflare.com
# 分開入口：.\update-db-endpoints.ps1 https://member.trycloudflare.com -ProductUrl https://product.trycloudflare.com
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$NewUrl,
    [string]$ProductUrl = '',
    [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
function Normalize-DatabaseUrl([string]$Value) {
    $parsed = $null
    if (-not [Uri]::TryCreate($Value.Trim().TrimEnd('/'), [UriKind]::Absolute, [ref]$parsed) -or
        $parsed.Scheme -ne 'https' -or -not $parsed.IsDefaultPort -or
        $parsed.UserInfo -or $parsed.Query -or $parsed.Fragment -or $parsed.AbsolutePath -ne '/' -or
        $parsed.Host -notmatch '^[a-z0-9-]+\.trycloudflare\.com$') {
        throw '請提供 https://名稱.trycloudflare.com 根網址，不含帳密、路徑或查詢參數。'
    }
    return $parsed.GetLeftPart([UriPartial]::Authority)
}
function Invoke-CloudCommand([string[]]$Arguments) {
    # 避免 gcloud.ps1 將 stderr 進度輸出判為終止錯誤，仍須檢查原生 exit code。
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & gcloud.cmd @Arguments
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    if ($code -ne 0) { throw 'gcloud 失敗，更新可能已部分生效，請查 revision；不要假設網址完全沒變。' }
    return ($result -join "`n")
}
function Read-JsonEndpoint([string]$Url) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 30 -MaximumRedirection 0
    if ([int]$response.StatusCode -ne 200 -or
        [string]$response.Headers['Content-Type'] -notmatch '(?i)application/(?:[\w.+-]+\+)?json') {
        throw '端點必須回 HTTP 200 及 JSON Content-Type。'
    }
    $data = $response.Content | ConvertFrom-Json
    if ($null -eq $data -or $data -is [string]) { throw '無效的 JSON 物件。' }
    return $data
}
$memberUrl = Normalize-DatabaseUrl $NewUrl
$productBaseUrl = if ($ProductUrl.Trim()) { Normalize-DatabaseUrl $ProductUrl } else { $memberUrl }
$settings = "MEMBER_DATABASE_URL=$memberUrl,PRODUCT_DATABASE_URL=$productBaseUrl"
Write-Host "MEMBER_DATABASE_URL=$memberUrl"
Write-Host "PRODUCT_DATABASE_URL=$productBaseUrl"
if ($DryRun) { Write-Host 'DRY RUN：不連網、不更新、不部署。'; return }

$memberHealth = Read-JsonEndpoint "$memberUrl/health"
$productHealth = if ($memberUrl -eq $productBaseUrl) { $memberHealth } else { Read-JsonEndpoint "$productBaseUrl/health" }
if (-not $memberHealth.service -or -not $productHealth.service) { throw 'health 缺少 service，停止更新。' }
# 共用 Flask 的 health 可以叫 member-database，不能據此推論缺少商品路線。
# 商品能力以下方 /api/products 實際回應驗證；會員登入仍另行驗收。
if ($memberUrl -ne $productBaseUrl -and
    ($memberHealth.service -ne 'member-database' -or $productHealth.service -ne 'product-db')) {
    throw '會員 health 應為 member-database，商品應為 product-db；對應不符，停止更新。'
}
$products = Read-JsonEndpoint "$productBaseUrl/api/products?limit=1"
if ($null -eq $products.products -and $null -eq $products.items) { throw '商品缺少 products/items，停止更新。' }
$scope = @('--region=asia-east1', '--project=decorate-me', '--format=json')
$before = (Invoke-CloudCommand (@('run','services','describe','ai-gateway') + $scope)) | ConvertFrom-Json
$previousRevision = $before.status.latestReadyRevisionName
$active = @($before.status.traffic | Where-Object { $_.percent -gt 0 })
if ($active.Count -ne 1 -or $active[0].percent -ne 100 -or $active[0].revisionName -ne $previousRevision) {
    throw '目前分流或流量不在最新就緒版本，停止更新，避免影響既有發布安排。'
}
Write-Host "更新前 revision：$previousRevision"
Invoke-CloudCommand (@('run','services','update','ai-gateway',"--update-env-vars=$settings",'--quiet') + $scope) | Out-Null
$after = (Invoke-CloudCommand (@('run','services','describe','ai-gateway') + $scope)) | ConvertFrom-Json
$ready = $after.status.latestReadyRevisionName
$active = @($after.status.traffic | Where-Object { $_.percent -gt 0 })
if ($ready -ne $after.status.latestCreatedRevisionName -or $active.Count -ne 1 -or
    $active[0].percent -ne 100 -or $active[0].revisionName -ne $ready) {
    throw '設定已提交，但新 revision 尚未承接全部流量，不可宣稱完成。'
}
$revision = (Invoke-CloudCommand (@('run','revisions','describe',$ready) + $scope)) | ConvertFrom-Json
foreach ($pair in @(@('MEMBER_DATABASE_URL',$memberUrl), @('PRODUCT_DATABASE_URL',$productBaseUrl))) {
    $row = @($revision.spec.containers[0].env | Where-Object { $_.name -eq $pair[0] })
    if ($row.Count -ne 1 -or $row[0].value -ne $pair[1]) { throw "實際 revision 的 $($pair[0]) 不符。" }
}
Write-Host "兩個網址已同步至 100% 流量 revision：$ready" -ForegroundColor Green
# 只探商品那一條。`health` 是 2026-08-28（commit 958eed5）**單獨為商品上游開的**驗收入口，
# member-database 的 allowed_paths 從來沒有過 health——它只放行 api/members*、api/favorites/toggle
# 那幾條，而那些全部要會員 session。所以 /member-database/health 一定回 Gateway 自己的
# 404 NOT_FOUND，不是權限攔截，也不是這次更新改壞的。
#
# 原本這裡把那個 404 當成「驗證未完成」而 throw，於是每一次成功的更新都以紅字結束。
# 而同一句話又叫人不要重複部署——兩者衝突的結果，就是下一個人會再推一輪沒有必要的 revision。
$incomplete = $false
try {
    $body = Read-JsonEndpoint 'https://decorate-me.web.app/product-api/health'
    if ($body.service -ne [string]$productHealth.service) { throw 'service 與上游預檢不符。' }
    Write-Host "/product-api/health：200 JSON，service=$($body.service)" -ForegroundColor Green
} catch {
    $incomplete = $true
    Write-Warning '/product-api/health：未通過。請查 Gateway 日誌，不要直接重推。'
}
if ($incomplete) { throw "網址已更新（$ready），商品路線驗證未通過。先查日誌，不要盲目重複部署。" }

if ($memberUrl -eq $productBaseUrl) {
    # 同一台主機，商品那一條已經證明 Gateway 連得到它。
    Write-Host '會員與商品同一個上游，連通性已由上面那條證明。' -ForegroundColor Green
} else {
    # 不同主機時，Gateway 沒有任何一條不需要登入就能打到 member-database 的路徑（設計如此）。
    # 腳本開頭的 Read-JsonEndpoint "$memberUrl/health" 已經直接驗過那台主機活著，
    # 剩下「Gateway 打不打得到它」只能靠帶憑證的請求，交給測試帳號。
    Write-Host '會員上游是另一台：主機本身已在更新前驗過；Gateway 到它那一段要用測試帳號登入才驗得到。' -ForegroundColor Yellow
}
Write-Host '網址已更新，商品路線已驗證；前端不用部署。登入／權限讀寫仍須測試帳號驗收。'
