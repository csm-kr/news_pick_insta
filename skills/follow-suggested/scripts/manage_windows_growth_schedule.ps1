[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'status', 'remove')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$followScript = (Resolve-Path (Join-Path $PSScriptRoot 'follow_suggested.py')).Path
$unfollowScript = (Resolve-Path (Join-Path $PSScriptRoot '..\..\unfollow-non-followers\scripts\unfollow_non_followers.py')).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
# 예약 작업은 콘솔 창 없이 돌도록 pythonw.exe로 실행한다. 출력은 스크립트가 output/ 아래 로그 파일로 돌린다.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe를 찾을 수 없다: $pythonw"
}
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# 팔로우는 오전·오후·저녁 구간마다 작업 스케줄러가 시작 시각을 매일 무작위로 정한다(게시 회차 시간대는 피한다).
# 그날 몇 명을 몇 구간에 나눌지는 follow_suggested.py --session이 정한다. 맞팔 아닌 계정 정리는 매주 월요일 00:30
$tasks = @(
    @{ name = 'NewsPickFollow-Morning'; target = 'daily 08:00-10:50 random'; arguments = "`"$followScript`" --session morning"
       trigger = { New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(8)) -RandomDelay (New-TimeSpan -Hours 2 -Minutes 50) }; limit = New-TimeSpan -Hours 2 },
    @{ name = 'NewsPickFollow-Afternoon'; target = 'daily 13:00-15:30 random'; arguments = "`"$followScript`" --session afternoon"
       trigger = { New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(13)) -RandomDelay (New-TimeSpan -Hours 2 -Minutes 30) }; limit = New-TimeSpan -Hours 2 },
    @{ name = 'NewsPickFollow-Evening'; target = 'daily 20:00-23:00 random'; arguments = "`"$followScript`" --session evening"
       trigger = { New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(20)) -RandomDelay (New-TimeSpan -Hours 3) }; limit = New-TimeSpan -Hours 2 },
    @{ name = 'NewsPickUnfollow-Weekly'; target = 'Monday 00:30'; arguments = "`"$unfollowScript`" --auto"
       trigger = { New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At ([datetime]::Today.AddMinutes(30)) }; limit = New-TimeSpan -Hours 6 }
)
# 예전의 고정 시각 팔로우 작업. install·remove 때 지운다
$legacyTaskNames = @('NewsPickFollow-1000', 'NewsPickFollow-2100')

function Get-GrowthTaskRecord($spec) {
    $task = Get-ScheduledTask -TaskName $spec.name -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return [pscustomobject]@{ task_name = $spec.name; target = $spec.target; installed = $false; state = $null; next_run = $null; last_run = $null; last_result = $null }
    }
    $info = Get-ScheduledTaskInfo -TaskName $spec.name
    return [pscustomobject]@{
        task_name = $spec.name
        target = $spec.target
        installed = $true
        state = [string]$task.State
        next_run = $info.NextRunTime.ToString('o')
        last_run = if ($info.LastRunTime -gt [datetime]'2000-01-01') { $info.LastRunTime.ToString('o') } else { $null }
        last_result = $info.LastTaskResult
    }
}

if ($Command -eq 'install') {
    $timezone = (tzutil /g).Trim()
    if ($timezone -ne 'Korea Standard Time') {
        throw "Windows timezone이 Korea Standard Time이 아니다: $timezone"
    }
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    foreach ($spec in $tasks) {
        $action = New-ScheduledTaskAction -Execute $pythonw -Argument $spec.arguments -WorkingDirectory $projectRoot
        $settings = New-ScheduledTaskSettingsSet `
            -WakeToRun `
            -RunOnlyIfNetworkAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit $spec.limit
        $task = New-ScheduledTask `
            -Action $action `
            -Trigger (& $spec.trigger) `
            -Principal $principal `
            -Settings $settings `
            -Description 'News Pick ego lite (newspick-growth). Follow suggested accounts / unfollow non-followers, avoiding scheduled publish runs.'
        Register-ScheduledTask -TaskName $spec.name -InputObject $task -Force | Out-Null
    }
}
if ($Command -in 'install', 'remove') {
    foreach ($name in $legacyTaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
    }
}
if ($Command -eq 'remove') {
    foreach ($spec in $tasks) {
        if (Get-ScheduledTask -TaskName $spec.name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $spec.name -Confirm:$false
        }
    }
}

[pscustomobject]@{
    ok = $true
    command = $Command
    timezone = (tzutil /g).Trim()
    user = $currentUser
    tasks = @($tasks | ForEach-Object { Get-GrowthTaskRecord $_ })
} | ConvertTo-Json -Depth 5
