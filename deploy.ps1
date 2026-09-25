# Decorate Me 前端部署腳本
# 用途：部署前自動把 index.html 裡本地 JS 的 ?v=... 版本號戳成當下時間戳，
#       再跑 firebase deploy。避免忘記手動 bump 版本、瀏覽器讀到舊 JS。
# 用法：在 web_frontend 目錄執行  ->  .\deploy.ps1

param(
    [switch]$AllowDirty,
    # 跳過「線上有、本機沒有」的比對。只在確實無法取得 gcloud 權杖、
    # 而且已經用別的方式確認過內容完整時才用——這一關擋的是靜默刪檔。
    [switch]$SkipLiveCheck,
    # 這次**刻意**要從線上移除的路徑，例如檔案改名或功能下架。
    #
    # 為什麼不是直接用 -SkipLiveCheck：那個會把整道檢查關掉，連不該刪的也一起放行。
    # 這個要逐一寫出路徑，所以「我知道這幾個會消失」跟「我沒在看」是兩件事——
    # 前者是決定，後者是疏忽，不該用同一個開關表達。
    #   .\deploy.ps1 -AllowDelete '/pages/makeup-bag.html'
    [string[]]$AllowDelete = @()
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$indexPath = Join-Path $PSScriptRoot "index.html"

# 底下每一個檢查都要**真的擋得住部署**，所以一律走這個函式，不要直接寫 `node ...`。
#
# `$ErrorActionPreference = "Stop"` 對 node 這種原生指令沒有作用：它只管 PowerShell 自己的
# cmdlet。原生指令失敗只會設 $LASTEXITCODE，腳本照樣往下跑到 `firebase deploy`。
# 2026-08-29 實測（PowerShell 7.6.5，`$PSNativeCommandUseErrorActionPreference` 是 False）：
# `node -e "process.exit(1)"` 之後的那一行**照印不誤**。
#
# 也就是說在這行註解寫下之前，這裡的每一個檢查都只是印訊息而已，從來沒有攔下任何一次部署——
# 紅字捲過去，壞掉的版本照樣上線。所以要看 $LASTEXITCODE，而且要自己 throw。
#
# node 的參數用**陣列**傳，不要靠 ValueFromRemainingArguments：`--check` 會被 PowerShell
# 當成參數名去比對（`-e` 更慘，會撞上 -ErrorAction 而報 ambiguous）。包成陣列就純粹是值。
function Invoke-DeployCheck {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string[]]$NodeArgs
    )
    & node @NodeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "部署中止：$Name 沒有通過（離開碼 $LASTEXITCODE）。修好再部署，不要用 -AllowDirty 繞過——那個開關只放行未提交的變更，不放行壞掉的程式碼。"
    }
}

Write-Host "執行部署前語法、流程與秘密掃描..." -ForegroundColor Cyan
Invoke-DeployCheck "api.js 語法"             @('--check', 'js/api.js')
Invoke-DeployCheck "router.js 語法"          @('--check', 'js/router.js')
Invoke-DeployCheck "makeup-contract.js 語法" @('--check', 'js/makeup-contract.js')
Invoke-DeployCheck "makeup-flow.js 語法"     @('--check', 'js/makeup-flow.js')
Invoke-DeployCheck "前端冒煙測試"             @('frontend_smoke_check.js')
# 用到不存在的變數：語法完全合法，node --check 過得了，只有跑到那一行才炸。
# 2026-08-28 有一個藏在覆核清單重畫裡，讓訓練批次整整一天載不出來。
Invoke-DeployCheck "未定義的名字"             @('tests/undefined_names_check.js', '.')
# 名字存在、但在初始化前就被用到（TDZ）：上面那支用的是 eslint no-undef，看的是
# 「有沒有宣告」，這種名字有宣告，所以它放行。2026-08-29 商品推薦頁整片全白就是這樣
# 溜過去的——它拋在 innerHTML 賦值之前，連空狀態都畫不出來。這支直接把每個頁面跑一次。
Invoke-DeployCheck "每頁都畫得出東西"         @('tests/page_dispatch_tdz_check.js', '.')
# 商品被後台清空後，空清單不能被當成「還沒載入」——那會無限重打商品 API，
# 畫面永遠停在「商品載入中」。2026-08-29 使用者回報。
Invoke-DeployCheck "商品清空後的狀態"         @('tests/product_catalog_empty_check.js', '.')
# 選擇器清單被切斷：大括號依然平衡，CSS 也不報錯，只有畫面知道。
Invoke-DeployCheck "CSS 結構"                @('tests/css_structure_check.js', '.')
# 送去建議服務的季型欄位。缺了或送成它不認得的值，那支服務照樣回 200、照樣生建議，
# 只是底妝那段跟使用者的膚色無關——畫面完全正常，沒有任何錯誤訊息。
Invoke-DeployCheck "季型契約"                @('tests/suggest_season_contract_check.js', '.')
# 選了品牌之後要翻完所有游標頁，而且每頁都要重送 brand（游標只帶位移不帶篩選條件）。
# 少了分頁就只顯示第一頁、其餘安靜消失；翻頁掉了 brand 則會從第二頁混進別的品牌。
# 兩種都不會報錯，看起來就像資料庫裡只有這些商品。2026-09-23 使用者回報 MAC 只出現 50 筆。
Invoke-DeployCheck "品牌清單分頁"            @('tests/brand_catalog_pagination_check.js', '.')
# 規劃方式分岔把既有的選風格視窗包了一層。包壞了不會報錯，只會讓使用者走到錯的地方：
# 該問的時候沒問、選了系統推薦卻跑去反推、或化妝包空了卻卡在反推視窗出不來。
Invoke-DeployCheck "妝容規劃分岔"            @('tests/makeup_plan_fork_check.js', '.')
# 新頁面的權限登記。allowedPages 由後台勾選，新頁面預設不在裡面——漏了就會讓一般會員
# 看到「此帳號目前沒有使用此功能的權限，請聯繫管理員」，像被停權一樣。
# 2026-08-29（關於我們）與 2026-09-25（我的化妝包）各踩過一次。
Invoke-DeployCheck "新頁面權限登記"          @('tests/page_access_registration_check.js', '.')
# 頁面檔名要跟代號一字不差。對不上時 fetch 回 404，程式安靜掉到備援模板——
# 不報錯、不當機，只是畫面少一半。2026-09-25 化妝包取名 makeup-bag.html 就是這樣。
Invoke-DeployCheck "頁面模板檔名"            @('tests/page_template_naming_check.js', '.')

$firebaseConfig = Get-Content (Join-Path $PSScriptRoot "firebase.json") -Raw | ConvertFrom-Json
if ($firebaseConfig.hosting.ignore -notcontains "config.local.js") {
    throw "部署中止：firebase.json 必須排除只供本機使用的 config.local.js。"
}

# 內容完整性：本機有沒有「線上該有的東西」。
#
# firebase.json 的 public 是 "."，所以 `firebase deploy` 是**整份取代**不是增量更新——
# 本機少了哪個目錄，線上那個目錄就被刪掉。
#
# 2026-09-23：從一台沒有 product-images/ 的機器部署了兩次，線上 2592 張商品圖
# 被整批刪除（4208 檔 → 1645 檔），全站商品圖 404，只能靠 Hosting 回滾救回。
# 那些圖不在 git、不在任何 GCS bucket，只存在於 Hosting 的部署內容裡——
# 回滾晚一步碰上版本清理，就是真的沒了。
#
# 上面那些檢查看的都是「檔案內容對不對」（語法、TDZ、秘密、CSS 結構），
# 沒有任何一道在意「檔案在不在」。這一道補的就是那個洞。
$requiredPathsFile = Join-Path $PSScriptRoot "deploy_required_paths.json"
if (-not (Test-Path $requiredPathsFile)) {
    throw "部署中止：找不到 deploy_required_paths.json，無法驗證本機內容是否完整。"
}
$requiredPaths = Get-Content $requiredPathsFile -Raw -Encoding UTF8 | ConvertFrom-Json
$contentGaps = @()
foreach ($entry in $requiredPaths.PSObject.Properties) {
    if ($entry.Name.StartsWith("_")) { continue }   # _why 之類的說明欄位
    $dir = Join-Path $PSScriptRoot $entry.Name
    $min = [int]$entry.Value.minFiles
    if (-not (Test-Path $dir)) {
        $contentGaps += "  $($entry.Name)/ 不存在（應有至少 $min 個檔案）。$($entry.Value.note)"
        continue
    }
    $count = @(Get-ChildItem -Path $dir -Recurse -File -ErrorAction SilentlyContinue).Count
    if ($count -lt $min) {
        $contentGaps += "  $($entry.Name)/ 只有 $count 個檔案，應有至少 $min 個。$($entry.Value.note)"
    }
}
if ($contentGaps) {
    throw "部署中止：本機內容不完整，這次部署會刪掉線上既有的檔案。`n$($contentGaps -join "`n")`n`n先把缺少的內容補齊再部署。不要用 -AllowDirty 或手動 firebase deploy 繞過這一關。"
}

# 上面那份 minFiles 是寫死的下限，只能擋「整個目錄不見」這種大洞。
# 2026-09-24 實證它不夠：本機 2592 張圖、線上 3095 張，門檻 2500 照樣放行，
# 部署下去就是安靜刪掉 503 張。寫死的數字永遠追不上線上實際狀態。
#
# 所以真正的比較對象是**線上目前服務的那份清單**，不是任何寫在檔案裡的數字。
$liveToken = $null
try { $liveToken = (& gcloud auth print-access-token 2>$null) } catch { $liveToken = $null }
if (-not $liveToken) {
    throw "部署中止：拿不到 gcloud 存取權杖，無法比對線上檔案清單。`n先執行 gcloud auth login，或在確認過內容後加上 -SkipLiveCheck。"
}
if (-not $SkipLiveCheck) {
    Write-Host "比對線上檔案清單..." -ForegroundColor DarkGray
    $headers = @{ Authorization = "Bearer $liveToken"; "x-goog-user-project" = "decorate-me" }
    $rel = Invoke-RestMethod -Headers $headers -Method Get `
        -Uri "https://firebasehosting.googleapis.com/v1beta1/sites/decorate-me/releases?pageSize=1"
    $liveVersion = ($rel.releases[0].version.name -split "/")[-1]

    $livePaths = New-Object System.Collections.Generic.HashSet[string]
    $pageToken = $null
    do {
        $uri = "https://firebasehosting.googleapis.com/v1beta1/sites/decorate-me/versions/$liveVersion/files?pageSize=1000"
        if ($pageToken) { $uri += "&pageToken=$pageToken" }
        $page = Invoke-RestMethod -Headers $headers -Method Get -Uri $uri
        foreach ($f in $page.files) { [void]$livePaths.Add($f.path) }
        $pageToken = $page.nextPageToken
    } while ($pageToken)

    # 線上有、本機沒有 = 這次部署會刪掉它。firebase.json 的 ignore 名單本來就不會上傳，
    # 不算缺少，所以先排除掉。
    $ignoreLeaf = @($firebaseConfig.hosting.ignore | ForEach-Object { $_ -replace '\*\*/', '' -replace '/\*\*', '' })
    $wouldDelete = @()
    foreach ($p in $livePaths) {
        # /__/ 底下是 Firebase 自己注入的保留路徑（firebase/init.js 等），
        # 不是從本機上傳的，本機永遠不會有——不排除的話每次部署都誤報。
        if ($p.StartsWith("/__/")) { continue }
        $localPath = Join-Path $PSScriptRoot ($p.TrimStart('/'))
        if (Test-Path $localPath) { continue }
        $leaf = Split-Path $p -Leaf
        if ($ignoreLeaf -contains $leaf) { continue }
        if ($AllowDelete -contains $p) {
            Write-Host "  將移除（已宣告）：$p" -ForegroundColor DarkYellow
            continue
        }
        $wouldDelete += $p
    }

    if ($wouldDelete.Count -gt 0) {
        $byDir = $wouldDelete | Group-Object { ($_ -split '/')[1] } |
            Sort-Object Count -Descending |
            ForEach-Object { "  $($_.Name)/  缺 $($_.Count) 個檔案" }
        $sample = ($wouldDelete | Select-Object -First 5) -join "`n    "
        throw ("部署中止：線上有 $($wouldDelete.Count) 個檔案在本機不存在，這次部署會把它們刪掉。`n" +
               ($byDir -join "`n") + "`n`n  例如：`n    $sample`n`n" +
               "線上版本 $liveVersion。`n`n" +
               "補齊後再部署。product-images 的取得方式見 docs/product-images-recovery.md。`n" +
               "若某些檔案是**刻意**要移除的（改名、功能下架），逐一宣告：`n" +
               "  .\deploy.ps1 -AllowDelete '/pages/old-name.html'")
    }
    Write-Host "  線上 $($livePaths.Count) 個檔案，本機都有" -ForegroundColor DarkGray
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
