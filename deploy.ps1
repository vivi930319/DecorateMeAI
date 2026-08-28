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
node --check "js/makeup-contract.js"
node --check "js/makeup-flow.js"
node "frontend_smoke_check.js"

$firebaseConfig = Get-Content (Join-Path $PSScriptRoot "firebase.json") -Raw | ConvertFrom-Json
if ($firebaseConfig.hosting.ignore -notcontains "config.local.js") {
    throw "部署中止：firebase.json 必須排除只供本機使用的 config.local.js。"
}

# 秘密掃描。rg 比較快，但它不一定在 PATH 上——2026-08-28 就因為這樣讓整個
# deploy.ps1 在第一步中止，於是改用 `firebase deploy` 直接部署，跳過了底下的
# 版本號 bump：`?v=` 從 8/25 卡到 8/28，瀏覽器一直拿舊的 JS 與 CSS，
# 改好的東西看起來像沒上線。
#
# 掃描本身不能因為工具缺席就跳過（那等於把金鑰檢查關掉），所以沒有 rg 時
# 改用 PowerShell 自己的 Select-String 走同一組樣式與同一組檔案。
$secretPattern = "(faceApiKey\s*:|renderApiKey\s*:|textSuggestionApiKey\s*:|https://[A-Za-z0-9-]+\.trycloudflare\.com)"
$rg = Get-Command rg -ErrorAction SilentlyContinue
if ($rg) {
    $secretMatches = & rg -n --glob "*.js" --glob "!config.local.js" --glob "*.html" --glob "*.json" `
        $secretPattern . 2>$null
    if ($LASTEXITCODE -gt 1) {
        throw "部署中止：秘密掃描執行失敗。"
    }
} else {
    Write-Host "  找不到 rg，改用 Select-String 掃描" -ForegroundColor DarkGray
    # rg 預設會照 .gitignore 跳過檔案，Select-String 不會——不排除的話會掃到
    # .claude\settings.local.json 這種只存在於本機、根本不會部署的檔，
    # 掃出一堆歷史 tunnel 網址然後把部署擋下來。
    # 只掃真的會被上傳的東西：排掉點開頭的目錄與 node_modules。
    $skip = "\\.(claude|git|firebase|vscode|idea)\\|\\node_modules\\"
    $secretMatches = Get-ChildItem -Recurse -File -Include *.js, *.html, *.json |
        Where-Object { $_.Name -ne "config.local.js" -and $_.FullName -notmatch $skip } |
        Select-String -Pattern $secretPattern |
        ForEach-Object { "{0}:{1}:{2}" -f $_.Path, $_.LineNumber, $_.Line.Trim() }
}
if ($secretMatches) {
    throw "部署中止：公開前端仍包含上游金鑰欄位或臨時 Tunnel 網址。`n$($secretMatches -join "`n")"
}

$gitChanges = git status --porcelain -- .
if ($gitChanges -and -not $AllowDirty) {
    throw "部署中止：工作目錄有尚未提交的變更。確認內容後使用 -AllowDirty 進行已授權的緊急部署。"
}

# 把所有 <script src="....js?v=xxx"> 與 <link href="....css?v=xxx"> 的版本號換成同一個時間戳。
#
# 原本這裡只認 .js，於是 main.css 的版本號一直停在某次手動寫進去的字串
# （20260727-clear-dropdown），每次部署 JS 都換、CSS 都不換。沒有立刻出事是因為
# firebase.json 對 js|css|html 設了 no-cache，瀏覽器每次都回源驗證；但那樣一來
# 這個版本號就只剩誤導作用——顯示的日期跟實際內容無關。兩種都戳，才對得起它的用途。
#
# -Encoding UTF8 不能省。index.html 是無 BOM 的 UTF-8，PowerShell 5.1 的 Get-Content
# 在沒有 BOM 時會退回 ANSI（CP950）解讀，中文全變亂碼，接著被下一行以 UTF-8 寫回、
# 把亂碼固化。2026-07-20 就是這樣把進場動畫的「裝識你的美」寫壞並部署上線的。
# 寫回時維持不加 BOM（UTF8Encoding($false)），因為 HTML 由 <meta charset> 宣告編碼。
$content = Get-Content $indexPath -Raw -Encoding UTF8
$updated = [regex]::Replace($content, '\.(js|css)\?v=[^"]+"', ".`$1?v=$stamp`"")
[System.IO.File]::WriteAllText($indexPath, $updated, (New-Object System.Text.UTF8Encoding($false)))

Write-Host "版本號已戳為 $stamp" -ForegroundColor Green
Write-Host "開始部署到 Firebase Hosting..." -ForegroundColor Cyan
firebase deploy --only hosting
if ($LASTEXITCODE -ne 0) {
    throw "Firebase Hosting 部署失敗（exit code $LASTEXITCODE）；不得顯示為部署完成。"
}

Write-Host "部署完成。使用者一般重新整理即可拿到最新版（版本號已更新）。" -ForegroundColor Green
