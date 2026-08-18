[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'status', 'remove')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$taskPrefix = 'NewsPickInstagram'
$slots = @('07:00', '12:00', '17:00')
$runner = (Resolve-Path (Join-Path $PSScriptRoot 'scheduled_runner.py')).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
$codex = (Get-Command codex.exe -ErrorAction Stop).Source
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Get-NewsPickTaskRecords {
    $records = @()
    foreach ($slot in $slots) {
        $name = "$taskPrefix-$($slot.Replace(':', ''))"
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            $records += [pscustomobject]@{ task_name = $name; installed = $false; state = $null; next_run = $null; last_run = $null; last_result = $null }
            continue
        }
        $info = Get-ScheduledTaskInfo -TaskName $name
        $records += [pscustomobject]@{
            task_name = $name
            installed = $true
            state = [string]$task.State
            next_run = $info.NextRunTime.ToString('o')
            last_run = if ($info.LastRunTime -gt [datetime]'2000-01-01') { $info.LastRunTime.ToString('o') } else { $null }
            last_result = $info.LastTaskResult
        }
    }
    return $records
}

if ($Command -eq 'install') {
    $timezone = (tzutil /g).Trim()
    if ($timezone -ne 'Korea Standard Time') {
        throw "Windows timezone이 Korea Standard Time이 아니다: $timezone"
    }
    & $codex login status | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw 'Codex CLI 로그인이 필요하다.'
    }
    foreach ($slot in $slots) {
        & $python $runner --slot $slot --dry-run | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "$slot 예약 dry-run이 실패했다."
        }
        $name = "$taskPrefix-$($slot.Replace(':', ''))"
        $arguments = "`"$runner`" --slot $slot"
        $action = New-ScheduledTaskAction -Execute $python -Argument $arguments -WorkingDirectory $projectRoot
        $at = [datetime]::Today.Add([timespan]::Parse("$slot`:00"))
        $trigger = New-ScheduledTaskTrigger -Daily -At $at
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet `
            -WakeToRun `
            -RunOnlyIfNetworkAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Hours 3)
        $task = New-ScheduledTask `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description "뉴스픽 $slot KST 자동 생성·Instagram 게시. 로그인된 사용자 세션에서만 실행."
        Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null
    }
} elseif ($Command -eq 'remove') {
    foreach ($slot in $slots) {
        $name = "$taskPrefix-$($slot.Replace(':', ''))"
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
    tasks = @(Get-NewsPickTaskRecords)
} | ConvertTo-Json -Depth 5
