[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'status', 'remove')]
    [string]$Command = 'status'
)

$ErrorActionPreference = 'Stop'
$taskPrefix = 'NewsPickInstagram'
$slots = @('07:00', '12:00', '17:00')
$legacyTaskNames = @('NewsPickInstagram-0500')
$preparationLead = New-TimeSpan -Minutes 30
$runner = (Resolve-Path (Join-Path $PSScriptRoot 'scheduled_runner.py')).Path
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$python = (Get-Command python.exe -ErrorAction Stop).Source
# 예약 작업은 콘솔 창 없이 돌도록 pythonw.exe로 실행한다. 창을 닫아 run이 죽는 일을 막는다.
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) {
    throw "pythonw.exe를 찾을 수 없다: $pythonw"
}
$claudeCommand = Get-Command claude.exe -ErrorAction SilentlyContinue
if ($null -eq $claudeCommand) {
    $fallback = Join-Path $env:USERPROFILE '.localin\claude.exe'
    if (-not (Test-Path $fallback)) {
        throw 'Claude Code CLI(claude.exe)를 찾을 수 없다. 설치 후 다시 실행한다.'
    }
    $claude = $fallback
} else {
    $claude = $claudeCommand.Source
}
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

function Get-NewsPickTaskRecords {
    $records = @()
    foreach ($slot in $slots) {
        $name = "$taskPrefix-$($slot.Replace(':', ''))"
        $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            $records += [pscustomobject]@{ task_name = $name; target_slot = $slot; installed = $false; state = $null; next_run = $null; last_run = $null; last_result = $null }
            continue
        }
        $info = Get-ScheduledTaskInfo -TaskName $name
        $records += [pscustomobject]@{
            task_name = $name
            target_slot = $slot
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
    $authText = & $claude auth status --json 2>$null | Out-String
    $auth = $null
    try { $auth = $authText | ConvertFrom-Json } catch { $auth = $null }
    if ($LASTEXITCODE -ne 0 -or $null -eq $auth -or -not $auth.loggedIn) {
        throw 'Claude Code CLI 로그인이 필요하다(claude auth login).'
    }
    $backupRoot = Join-Path $projectRoot ("output\scheduler\task-backups\" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    foreach ($slot in $slots) {
        $backupName = "$taskPrefix-$($slot.Replace(':', ''))"
        if (Get-ScheduledTask -TaskName $backupName -ErrorAction SilentlyContinue) {
            Export-ScheduledTask -TaskName $backupName | Set-Content -LiteralPath (Join-Path $backupRoot "$backupName.xml") -Encoding UTF8
        }
    }
    foreach ($legacyName in $legacyTaskNames) {
        if (Get-ScheduledTask -TaskName $legacyName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $legacyName -Confirm:$false
        }
    }
    foreach ($slot in $slots) {
        & $python $runner --slot $slot --dry-run | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "$slot 예약 dry-run이 실패했다."
        }
        $name = "$taskPrefix-$($slot.Replace(':', ''))"
        $arguments = "`"$runner`" --slot $slot"
        $action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $projectRoot
        $at = [datetime]::Today.Add([timespan]::Parse("$slot`:00")).Subtract($preparationLead)
        $trigger = New-ScheduledTaskTrigger -Daily -At $at
        $principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet `
            -WakeToRun `
            -RunOnlyIfNetworkAvailable `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -MultipleInstances IgnoreNew `
            -ExecutionTimeLimit (New-TimeSpan -Hours 3)
        # 기본 BelowNormal은 부하 중 시작을 분 단위로 지연시켰다. 실제 예약 환경에서 검증한 Normal로 고정한다.
        $settings.Priority = 5
        $task = New-ScheduledTask `
            -Action $action `
            -Trigger $trigger `
            -Principal $principal `
            -Settings $settings `
            -Description "News Pick Claude Code print-mode executor. Aside research; ego lite Instagram session. Start 30 minutes early for $slot KST. 07 entertainment, 12 hot news over 7 days, 17 hot news over 3 days."
        Register-ScheduledTask -TaskName $name -InputObject $task -Force | Out-Null
    }
} elseif ($Command -eq 'remove') {
    foreach ($legacyName in $legacyTaskNames) {
        if (Get-ScheduledTask -TaskName $legacyName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $legacyName -Confirm:$false
        }
    }
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
    executor = 'claude-code'
    claude = $claude
    timezone = (tzutil /g).Trim()
    user = $currentUser
    tasks = @(Get-NewsPickTaskRecords)
} | ConvertTo-Json -Depth 5
