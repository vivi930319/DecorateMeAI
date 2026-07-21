# 更新資料庫網址（Cloudflare Quick Tunnel 每次重啟都會換一組）
#
# 用法：
#   .\update-db-url.ps1 https://xxxx-xxxx-xxxx.trycloudflare.com
#
# 只需要改 AI Gateway 一個地方。前端啟動時會向 Gateway 的 /public-config 拿網址，
# 所以不必修改任何前端檔案，也不必重新部署 Firebase —— 使用者重新整理就會用到新網址。

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$NewUrl
)

$ErrorActionPreference = "Stop"
$project = "decorate-me"
$region  = "asia-east1"

# 去掉結尾斜線，避免組出 https://x.com//api/login 這種網址
$NewUrl = $NewUrl.TrimEnd('/')

if ($NewUrl -notmatch '^https://') {
    Write-Host "網址必須以 https:// 開頭：$NewUrl" -ForegroundColor Red
    exit 1
}

# 先確認新網址真的活著，不要把壞網址推上去
Write-Host "檢查新網址..." -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "$NewUrl/health" -TimeoutSec 20
    Write-Host "  /health  ok（$($health.service)）" -ForegroundColor Green
} catch {
    Write-Host "  /health 連不上：$NewUrl" -ForegroundColor Red
    Write-Host "  請確認 cloudflared 正在執行、網址無誤，再重試。" -ForegroundColor Red
    exit 1
}

try {
    $products = Invoke-RestMethod -Uri "$NewUrl/api/products" -TimeoutSec 30
    $count = if ($products.products) { $products.products.Count } elseif ($products.items) { $products.items.Count } else { 0 }
    Write-Host "  商品數 $count" -ForegroundColor Green
} catch {
    Write-Host "  /api/products 讀取失敗，仍會繼續更新（商品服務可能另外處理）" -ForegroundColor Yellow
}

# 如果這一步噴 SSLError / CERTIFICATE_VERIFY_FAILED，那是 Avast 攔截 TLS、而 gcloud
# 自帶的 CA 不認它（Avast 憑證輪替後就會發生，2026-07-21 遇過一次）。
# 兩個解法：
#   1. 重新產生 CA bundle 並設定：gcloud config set core/custom_ca_certs_file <路徑>
#   2. 繞過 gcloud，直接呼叫 Cloud Run Admin API——PowerShell 走 Windows 憑證存放區，
#      認得 Avast，所以不受影響：
#        GET/PUT https://asia-east1-run.googleapis.com/apis/serving.knative.dev/v1/namespaces/decorate-me/services/ai-gateway
#        標頭 Authorization: Bearer $(gcloud auth print-access-token)
#        只改 spec.template.spec.containers[0].env 裡的兩個 *_DATABASE_URL，其餘原樣送回。
Write-Host "更新 AI Gateway..." -ForegroundColor Cyan
gcloud run services update ai-gateway `
    --region=$region --project=$project `
    --update-env-vars="MEMBER_DATABASE_URL=$NewUrl,PRODUCT_DATABASE_URL=$NewUrl" `
    --quiet | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Gateway 更新失敗，網址未變更。" -ForegroundColor Red
    exit 1
}

# 確認新網址真的生效。
#
# 注意：不要用 /public-config 比對網址。它回的是同源相對路徑（/member-database、
# /product-api），不是資料庫網址——前端刻意不知道資料庫在哪。拿它比對完整網址
# 永遠不會相等，就算部署成功也會誤報失敗。
#
# 正確做法是實際打一條會穿透到資料庫的路由：通得過就代表 Gateway 連得上新網址。
Write-Host "驗證..." -ForegroundColor Cyan
Start-Sleep -Seconds 8
try {
    $probe = Invoke-WebRequest -Uri "https://decorate-me.web.app/product-api/api/products?limit=1" -TimeoutSec 60
    if ($probe.StatusCode -eq 200) {
        Write-Host "  商品代理 200，Gateway 已連上新網址" -ForegroundColor Green
        Write-Host ""
        Write-Host "完成。使用者重新整理頁面即可，前端不需要重新部署。" -ForegroundColor Green
    } else {
        Write-Host "  商品代理回 $($probe.StatusCode)，請稍等 30 秒再重試" -ForegroundColor Yellow
    }
} catch {
    $code = if ($_.Exception.Response) { $_.Exception.Response.StatusCode.value__ } else { '連線失敗' }
    Write-Host "  商品代理回 $code" -ForegroundColor Yellow
    Write-Host "  503 代表 Gateway 連不到資料庫；可能還在部署，稍等 30 秒重試。" -ForegroundColor Yellow
}
