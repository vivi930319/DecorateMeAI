# 建立／更新 Windows 工作排程「DecorateMe 訓練機」。
#
# 為什麼要有這支：排程設定原本只活在這台機器的工作排程器裡。換機器、重灌、
# 或不小心刪掉工作，就得靠記憶重建——而其中兩個設定是實測出來的，不是查文件
# 查得到的（見下面的觸發器說明）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\setup_training_task.ps1
#   powershell -ExecutionPolicy Bypass -File tools\setup_training_task.ps1 -WhatIf

param([switch]$WhatIf, [switch]$Boot)

$ErrorActionPreference = 'Stop'
$TaskName = 'DecorateMe 訓練機'
$Root = Split-Path -Parent $PSScriptRoot
$Script = Join-Path $Root 'tools\start_training_worker.ps1'

if (-not (Test-Path $Script)) { throw "找不到 $Script" }

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $Script + '"')

# 觸發器有兩個，缺一不可：
#
# 1) 登入時觸發——開機登入就把訓練機帶起來。
# 2) 每 5 分鐘的看門狗。**這個不能寫成「在登入觸發器上加 Repetition」**：
#    2026-08-26 實測過，工作被停掉之後那種寫法完全不補跑（150 秒、300 秒
#    LastRunTime 都沒動，NextRunTime 也算不出來）。要用獨立的 Once 觸發器，
#    它的重複綁在明確時刻上，跟登入事件無關。
#    實測有效：21:54 殺掉 → 22:00:01 自動拉起 → 22:00:46 心跳恢復。
#
# 沒有看門狗的後果是實際發生過的：2026-08-26 訓練機因一次 DNS 失敗死掉，
# Task Scheduler 的失敗重試用完之後就沒有任何東西會再拉它，躺了十一個小時。
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
# 注意：RepetitionDuration 不要填 [TimeSpan]::MaxValue，會被判「超出範圍」而讓整個
# Set-ScheduledTask 失敗。無限期在 Task Scheduler 的 XML 裡就是 Duration 留空。

$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 5) -RestartCount 3 `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
# IgnoreNew：worker 還在跑時看門狗的觸發是空動作，不會開出第二個。
# ExecutionTimeLimit 0：訓練會跑一兩個小時，有上限就會被砍在半路。
# 電池那兩個：預設會在拔掉電源時停掉工作，訓練跑到一半就沒了。

if ($WhatIf) {
    Write-Output ('（預演）會建立／更新工作：' + $TaskName)
    Write-Output ('  動作 : ' + $action.Execute + ' ' + $action.Arguments)
    Write-Output '  觸發 : 登入時 ＋ 每 5 分鐘看門狗'
    return
}

# ── -Boot：讓訓練機在「開機但沒有人登入」時也會跑 ────────────────────────
#
# 需要系統管理員權限：加開機觸發器與改執行身分都會被一般權限擋下（存取被拒）。
#
# 風險是實際存在的，所以這段做完會自己驗證再決定要不要留下：
# gcloud 的憑證放在 C:\Users\<你>\AppData\Roaming\gcloud，而 S4U 是「不載入
# 使用者設定檔、也沒有網路憑證」的執行方式。如果在那個環境下
# `gcloud auth print-access-token` 拿不到 token，訓練機會**啟動但每次都失敗**——
# 那比「沒登入就不跑」更難查，因為畫面上看起來是活的。
#
# 所以：改完 → 實際啟動 → 看它有沒有成功跟 Firestore 講到話 → 沒有就自動改回去。
function Set-BootStart {
    param($TaskName, $Logon, $Watchdog, $Settings, $Action, $Root)

    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
            [Security.Principal.WindowsBuiltInRole]::Administrator)) {
        # 用訊息而不是 throw：throw 會把這句話包進一團例外堆疊裡，
        # 而看到它的人需要的是「怎麼辦」，不是呼叫堆疊。
        Write-Output ''
        Write-Output '[需要管理員權限] 加開機觸發器與改執行身分都會被一般權限擋下。'
        Write-Output '請以系統管理員身分開啟 PowerShell，再執行：'
        Write-Output ('  powershell -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" -Boot')
        Write-Output ''
        Write-Output '（現有的「登入時執行 ＋ 每 5 分鐘看門狗」不受影響，仍在運作。）'
        return $false
    }

    $before = Get-ScheduledTask -TaskName $TaskName
    $beforePrincipal = $before.Principal
    $beforeTriggers = $before.Triggers

    $boot = New-ScheduledTaskTrigger -AtStartup
    # 仍然以目前這個使用者身分跑：gcloud 憑證在這個人的設定檔底下，
    # 換成 SYSTEM 就讀不到了。S4U＝不論是否登入都執行，且不必儲存密碼。
    $principal = New-ScheduledTaskPrincipal -UserId ($env:USERDOMAIN + [char]92 + $env:USERNAME) `
        -LogonType S4U -RunLevel Limited
    Set-ScheduledTask -TaskName $TaskName -Trigger @($boot, $Logon, $Watchdog) `
        -Principal $principal -Settings $Settings -Action $Action | Out-Null
    Write-Output '已改為「開機即執行、不需登入」，正在驗證 gcloud 憑證…'

    # 驗證：重啟工作，看 log 有沒有出現拿不到 token 的錯誤。
    $log = Join-Path $Root 'logs\training_worker.log'
    $mark = if (Test-Path $log) { (Get-Item $log).Length } else { 0 }
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 45

    $fresh = if (Test-Path $log) {
        $all = Get-Content $log -Raw -ErrorAction SilentlyContinue
        if ($all.Length -gt $mark) { $all.Substring($mark) } else { '' }
    } else { '' }

    $tokenBroken = $fresh -match 'print-access-token|取得 token 失敗|credentials|Reauthentication|HTTP 401'
    $started = $fresh -match '訓練機 .* 啟動'

    if ($tokenBroken -or -not $started) {
        Write-Output ''
        Write-Output '[驗證失敗] 在不登入的執行環境下訓練機沒有正常起來。log 尾巴：'
        ($fresh -split "`n" | Select-Object -Last 8) | ForEach-Object { '    ' + $_ }
        Set-ScheduledTask -TaskName $TaskName -Trigger $beforeTriggers `
            -Principal $beforePrincipal -Settings $Settings -Action $Action | Out-Null
        Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
        Start-ScheduledTask -TaskName $TaskName
        Write-Output ''
        Write-Output '已自動改回原本的「登入時執行」，訓練機重新啟動中。'
        Write-Output '結論：這台機器不能用免登入模式，請改用「開機自動登入」那條路。'
        return $false
    }

    Write-Output '[驗證通過] 免登入模式下訓練機正常啟動並取得憑證。'
    return $true
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($logon, $watchdog) -Settings $settings | Out-Null
    Write-Output ('已更新工作：' + $TaskName)
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action `
        -Trigger @($logon, $watchdog) -Settings $settings `
        -Description '五官分類重訓的本機訓練機。後台按下送訓的批次會在這裡執行。' | Out-Null
    Write-Output ('已建立工作：' + $TaskName)
}

$t = Get-ScheduledTask -TaskName $TaskName
$i = $t | Get-ScheduledTaskInfo
Write-Output ('狀態     : ' + $t.State)
Write-Output ('下次執行 : ' + $i.NextRunTime + '  （空的話代表看門狗沒設成功，請重跑一次）')

if ($Boot) {
    $ok = Set-BootStart -TaskName $TaskName -Logon $logon -Watchdog $watchdog `
        -Settings $settings -Action $action -Root $Root
    if ($ok) {
        Write-Output ''
        Write-Output '訓練機現在只要電腦開著就會跑，不需要登入。'
    }
    return
}

Write-Output ''
Write-Output ('注意：這個工作以「' + $env:USERNAME + '」身分、登入後才執行。')
Write-Output '電腦關機或停在登入畫面時訓練機不會跑——這是預期行為，'
Write-Output '雲端的「訓練機失聯」告警會在 15 分鐘後通知你。'
Write-Output ''
Write-Output '要讓它「開機就跑、不必登入」，用管理員身分再跑一次並加 -Boot：'
Write-Output '  powershell -ExecutionPolicy Bypass -File tools\setup_training_task.ps1 -Boot'
Write-Output '（那個模式會自己驗證 gcloud 憑證，拿不到就自動改回來。）'
