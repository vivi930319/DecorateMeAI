# 建立／更新 Windows 工作排程「DecorateMe 訓練機」。
#
# 為什麼要有這支：排程設定原本只活在這台機器的工作排程器裡。換機器、重灌、
# 或不小心刪掉工作，就得靠記憶重建——而其中兩個設定是實測出來的，不是查文件
# 查得到的（見下面的觸發器說明）。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File tools\setup_training_task.ps1
#   powershell -ExecutionPolicy Bypass -File tools\setup_training_task.ps1 -WhatIf

param([switch]$WhatIf)

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
Write-Output ''
Write-Output ('注意：這個工作以「' + $env:USERNAME + '」身分、登入後才執行。')
Write-Output '電腦關機或停在登入畫面時訓練機不會跑——這是預期行為，'
Write-Output '雲端的「訓練機失聯」告警會在 15 分鐘後通知你。'
