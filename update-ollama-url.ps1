# 更新 Ollama 文字建議服務網址（Cloudflare Quick Tunnel 每次重啟都會換一組）
#
# 用法：
#   .\update-ollama-url.ps1 https://xxxx-xxxx-xxxx.trycloudflare.com
#
# 為什麼要有這一支：**同一個 Ollama 服務被兩個地方各記一份網址。**
#
#   ai-gateway       TEXT_SUGGESTION_URL      使用者按「生成 Ollama 建議」走這條
#   replicate-render SUGGESTION_SERVICE_URL   渲染時去要個人化 prompt 走這條
#
# 2026-07-29 實際踩到：對方換了網址，只更新了 Gateway，Render 那條指向已死的通道。
# 症狀非常隱蔽——渲染不會報錯，因為 build_personalized_render_prompt 拿不到 prompt 時
# 會**安靜地**退回 styleId 白名單的固定句子，結果只是「妝變得比較泛用」，沒有人會發現。
# 所以這兩個一定要一起改，不能只改想得到的那一個。

param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$NewUrl
)

# gcloud 會把 InsecureRequestWarning 寫到 stderr，而 PowerShell 5.1 在
# ErrorActionPreference=Stop 之下會把原生指令的 stderr 包成 NativeCommandError 並中斷——
# 即使 gcloud 其實是成功的（exit code 0）。所以呼叫 gcloud 的區段一律用 Continue，
# 成敗改看 $LASTEXITCODE。
$ErrorActionPreference = "Continue"
$project = "decorate-me"
$region  = "asia-east1"

# 去掉結尾斜線，避免組出 https://x.com//suggest
$NewUrl = $NewUrl.TrimEnd('/')

if ($NewUrl -notmatch '^https://') {
    Write-Host "網址必須以 https:// 開頭：$NewUrl" -ForegroundColor Red
    exit 1
}

# 先確認新網址活著，不要把壞網址推上去
Write-Host "檢查新網址..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri "$NewUrl/health" -TimeoutSec 25 | Out-Null
    Write-Host "  /health ok" -ForegroundColor Green
} catch {
    Write-Host "  /health 連不上：$NewUrl" -ForegroundColor Red
    Write-Host "  請確認 Ollama 端的 cloudflared 正在執行、網址無誤，再重試。" -ForegroundColor Red
    exit 1
}

# 兩個服務一起更新。這裡刻意不過濾 gcloud 的輸出——
# 2026-07-29 用 Select-String 過濾時把失敗訊息一起濾掉了，然後看 `services describe`
# （那是**期望狀態**，不是實際在跑的 revision）就以為成功，其實新 revision 根本沒起來。
Write-Host "更新 ai-gateway（TEXT_SUGGESTION_URL）..." -ForegroundColor Cyan
gcloud run services update ai-gateway --region=$region --project=$project `
    --update-env-vars="TEXT_SUGGESTION_URL=$NewUrl" --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "ai-gateway 更新失敗。" -ForegroundColor Red; exit 1 }

Write-Host "更新 replicate-render（SUGGESTION_SERVICE_URL）..." -ForegroundColor Cyan
gcloud run services update replicate-render --region=$region --project=$project `
    --update-env-vars="SUGGESTION_SERVICE_URL=$NewUrl" --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "replicate-render 更新失敗（ai-gateway 已更新，兩邊現在不一致）。" -ForegroundColor Red; exit 1 }

# 驗證看的是「實際在跑的 revision」，不是 services describe 的期望狀態。
Write-Host "驗證..." -ForegroundColor Cyan
$ok = $true
foreach ($pair in @(@("ai-gateway", "TEXT_SUGGESTION_URL"), @("replicate-render", "SUGGESTION_SERVICE_URL"))) {
    $svc = $pair[0]; $key = $pair[1]
    $rev = gcloud run services describe $svc --region=$region --project=$project --format="value(status.latestReadyRevisionName)"
    $env = gcloud run revisions describe $rev --region=$region --project=$project --format="value(spec.containers[0].env)"
    if ($env -match [regex]::Escape($NewUrl)) {
        Write-Host "  $svc ($rev) $key 已更新" -ForegroundColor Green
    } else {
        Write-Host "  $svc ($rev) $key 沒有生效，請檢查" -ForegroundColor Red
        $ok = $false
    }
}

if ($ok) {
    Write-Host ""
    Write-Host "完成。兩個服務都指向新網址，前端不需要重新部署。" -ForegroundColor Green
} else {
    exit 1
}
