# Decorate Me 前端部署腳本
# 用途：部署前自動把 index.html 裡本地 JS 的 ?v=... 版本號戳成當下時間戳，
#       再跑 firebase deploy。避免忘記手動 bump 版本、瀏覽器讀到舊 JS。
# 用法：在 web_frontend 目錄執行  ->  .\deploy.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$indexPath = Join-Path $PSScriptRoot "index.html"

# 把所有 <script ... src="....js?v=xxx"> 的版本號換成同一個時間戳
$content = Get-Content $indexPath -Raw
$updated = [regex]::Replace($content, '\.js\?v=[^"]+"', ".js?v=$stamp`"")
[System.IO.File]::WriteAllText($indexPath, $updated, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "版本號已戳為 $stamp" -ForegroundColor Green
Write-Host "開始部署到 Firebase Hosting..." -ForegroundColor Cyan
firebase deploy --only hosting

Write-Host "部署完成。使用者一般重新整理即可拿到最新版（版本號已更新）。" -ForegroundColor Green
