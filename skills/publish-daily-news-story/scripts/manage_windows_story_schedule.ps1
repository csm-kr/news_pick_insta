[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'status', 'remove')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$taskName = 'NewsPickInstagram-DailyStory-2100'
$runner = (Resolve-Path (Join-Path $PSScriptRoot 'scheduled_story_runner.py')).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Get-NewsPickStoryTaskRecord {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -eq $task) {
        return [pscustomobject]@{
            task_name = $taskName
            target_time = '21:00'
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
        target_time = '21:00'
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
        throw '21:00 Story 예약 dry-run이 실패했다.'
    }
    $arguments = "`"$runner`""
    $action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At ([datetime]::Today.AddHours(21))
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
        -Description '매일 21:00 KST에 당일 공개 검증된 뉴스픽 전부의 첫 카드로 6초 Story를 만들고 게시·검증.'
    Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Out-Null
} elseif ($Command -eq 'remove') {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
}

[pscustomobject]@{
    ok = $true
    command = $Command
    timezone = (tzutil /g).Trim()
    user = $currentUser
    task = Get-NewsPickStoryTaskRecord
} | ConvertTo-Json -Depth 5
