# Decorate Me 前端部署腳本
# 用途：部署前自動把 index.html 裡本地 JS 的 ?v=... 版本號戳成當下時間戳，
#       再跑 firebase deploy。避免忘記手動 bump 版本、瀏覽器讀到舊 JS。
# 用法：在 web_frontend 目錄執行  ->  .\deploy.ps1

param(
    [switch]$AllowDirty
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$indexPath = Join-Path $PSScriptRoot "index.html"

Write-Host "執行部署前語法、流程與秘密掃描..." -ForegroundColor Cyan
node --check "js/api.js"
node --check "js/router.js"
node "frontend_smoke_check.js"

$secretMatches = & rg -n --glob "*.js" --glob "*.html" --glob "*.json" `
    "(faceApiKey\s*:|renderApiKey\s*:|textSuggestionApiKey\s*:|https://[A-Za-z0-9-]+\.trycloudflare\.com)" . 2>$null
if ($LASTEXITCODE -eq 0 -and $secretMatches) {
    throw "部署中止：公開前端仍包含上游金鑰欄位或臨時 Tunnel 網址。`n$secretMatches"
}
if ($LASTEXITCODE -gt 1) {
    throw "部署中止：秘密掃描執行失敗。"
}

$gitChanges = git status --porcelain -- .
if ($gitChanges -and -not $AllowDirty) {
    throw "部署中止：工作目錄有尚未提交的變更。確認內容後使用 -AllowDirty 進行已授權的緊急部署。"
}

# 把所有 <script ... src="....js?v=xxx"> 的版本號換成同一個時間戳
#
# -Encoding UTF8 不能省。index.html 是無 BOM 的 UTF-8，PowerShell 5.1 的 Get-Content
# 在沒有 BOM 時會退回 ANSI（CP950）解讀，中文全變亂碼，接著被下一行以 UTF-8 寫回、
# 把亂碼固化。2026-07-20 就是這樣把進場動畫的「裝識你的美」寫壞並部署上線的。
# 寫回時維持不加 BOM（UTF8Encoding($false)），因為 HTML 由 <meta charset> 宣告編碼。
$content = Get-Content $indexPath -Raw -Encoding UTF8
$updated = [regex]::Replace($content, '\.js\?v=[^"]+"', ".js?v=$stamp`"")
[System.IO.File]::WriteAllText($indexPath, $updated, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "版本號已戳為 $stamp" -ForegroundColor Green
Write-Host "開始部署到 Firebase Hosting..." -ForegroundColor Cyan
firebase deploy --only hosting
if ($LASTEXITCODE -ne 0) {
    throw "Firebase Hosting 部署失敗（exit code $LASTEXITCODE）；不得顯示為部署完成。"
}

Write-Host "部署完成。使用者一般重新整理即可拿到最新版（版本號已更新）。" -ForegroundColor Green
