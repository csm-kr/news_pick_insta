[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'status', 'remove')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$taskName = 'NewsPickInstagram-DailyStory-1900'
$legacyTaskNames = @('NewsPickInstagram-DailyStory-2100')
$runner = (Resolve-Path (Join-Path $PSScriptRoot 'scheduled_story_runner.py')).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
# 예약 작업은 콘솔 창 없이 돌도록 pythonw.exe로 실행한다. 창을 닫아 run이 죽는 일을 막는다.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe를 찾을 수 없다: $pythonw"
}
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Get-NewsPickStoryTaskRecord {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return [pscustomobject]@{
            task_name = $taskName
            target_time = '19:00'
            installed = $false
            state = $null
            next_run = $null
            last_run = $null
            last_result = $null
        }
    }
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    return [pscustomobject]@{
        task_name = $taskName
        target_time = '19:00'
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
    & $python $runner --dry-run | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw '19:00 Story 예약 dry-run이 실패했다.'
    }
    $arguments = "`"$runner`""
    $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(19))
    $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet `
        -WakeToRun `
        -RunOnlyIfNetworkAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1)
    $task = New-ScheduledTask `
        -Action $action `
        -Trigger $trigger `
        -Principal $principal `
        -Settings $settings `
        -Description 'News Pick ego lite. Publish and verify three separate 07/12/17 edition Stories at 19:00 KST.'
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
    foreach ($legacyName in $legacyTaskNames) {
        if (Get-ScheduledTask -TaskName $legacyName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $legacyName -Confirm:$false
        }
    }
} elseif ($Command -eq 'remove') {
    foreach ($name in @($taskName) + $legacyTaskNames) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
        }
    }
}

[pscustomobject]@{
    ok = $true
    command = $Command
    timezone = (tzutil /g).Trim()
    user = $currentUser
    task = Get-NewsPickStoryTaskRecord
} | ConvertTo-Json -Depth 5
