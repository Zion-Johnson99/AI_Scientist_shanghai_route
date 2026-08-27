[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [ValidateSet("Install", "Status", "Uninstall")]
    [string] $Action = "Install",

    [string] $WeatherRoot = (Split-Path -Parent $PSScriptRoot)
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$taskDefinitions = @(
    [pscustomobject]@{
        Name = "XuhuiEnvironmentRefresh-Weather"
        Tier = "weather"
        Description = "Refresh Xuhui weather and alerts every 15 minutes"
    },
    [pscustomobject]@{
        Name = "XuhuiEnvironmentRefresh-Hourly"
        Tier = "hourly"
        Description = "Refresh Xuhui air quality at minute 2 of every hour"
    },
    [pscustomobject]@{
        Name = "XuhuiEnvironmentRefresh-Daily"
        Tier = "daily"
        Description = "Refresh all Xuhui environment data daily at 06:07"
    }
)

function New-RefreshTrigger {
    param([Parameter(Mandatory = $true)][string] $Tier)

    $now = Get-Date
    switch ($Tier) {
        "weather" {
            $start = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day `
                -Hour $now.Hour -Minute 0 -Second 0
            while ($start -le $now) {
                $start = $start.AddMinutes(15)
            }
            return New-ScheduledTaskTrigger -Once -At $start `
                -RepetitionInterval (New-TimeSpan -Minutes 15)
        }
        "hourly" {
            $start = Get-Date -Year $now.Year -Month $now.Month -Day $now.Day `
                -Hour $now.Hour -Minute 2 -Second 0
            if ($start -le $now) {
                $start = $start.AddHours(1)
            }
            return New-ScheduledTaskTrigger -Once -At $start `
                -RepetitionInterval (New-TimeSpan -Hours 1)
        }
        "daily" {
            return New-ScheduledTaskTrigger -Daily -At "06:07"
        }
        default {
            throw "Unknown refresh tier: $Tier"
        }
    }
}

function Get-RefreshArguments {
    param(
        [Parameter(Mandatory = $true)][string] $Tier,
        [Parameter(Mandatory = $true)][string] $ResolvedRoot
    )

    switch ($Tier) {
        "weather" {
            return "--root `"$resolvedRoot`" scheduled-refresh --tier weather"
        }
        "hourly" {
            return "--root `"$resolvedRoot`" scheduled-refresh --tier hourly"
        }
        "daily" {
            return "--root `"$resolvedRoot`" scheduled-refresh --tier daily"
        }
        default {
            throw "Unknown refresh tier: $Tier"
        }
    }
}

if ($Action -eq "Status") {
    foreach ($definition in $taskDefinitions) {
        $task = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
        if ($null -eq $task) {
            [pscustomobject]@{
                TaskName = $definition.Name
                Installed = $false
                State = "Missing"
                LastRunTime = $null
                NextRunTime = $null
            }
            continue
        }
        $info = Get-ScheduledTaskInfo -TaskName $definition.Name
        [pscustomobject]@{
            TaskName = $definition.Name
            Installed = $true
            State = $task.State
            LastRunTime = $info.LastRunTime
            NextRunTime = $info.NextRunTime
        }
    }
    return
}

if ($Action -eq "Uninstall") {
    foreach ($definition in $taskDefinitions) {
        $task = Get-ScheduledTask -TaskName $definition.Name -ErrorAction SilentlyContinue
        if ($null -ne $task -and $PSCmdlet.ShouldProcess($definition.Name, "Uninstall task")) {
            Unregister-ScheduledTask -TaskName $definition.Name -Confirm:$false
        }
    }
    return
}

$isDriveRelative = $WeatherRoot -match "^[A-Za-z]:[^\\/]"
if (-not [IO.Path]::IsPathRooted($WeatherRoot) -or $isDriveRelative) {
    throw "WeatherRoot must be an absolute path: $WeatherRoot"
}
if (-not (Test-Path -LiteralPath $WeatherRoot -PathType Container)) {
    throw "WeatherRoot does not exist: $WeatherRoot"
}

$resolvedRoot = (Resolve-Path -LiteralPath $WeatherRoot).Path
$executable = Join-Path $resolvedRoot ".venv\Scripts\weather-api-data.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Virtual environment executable does not exist: $executable"
}

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

foreach ($definition in $taskDefinitions) {
    $arguments = Get-RefreshArguments -Tier $definition.Tier -ResolvedRoot $resolvedRoot
    $taskAction = New-ScheduledTaskAction `
        -Execute $executable `
        -Argument $arguments `
        -WorkingDirectory $resolvedRoot
    $trigger = New-RefreshTrigger -Tier $definition.Tier

    if ($PSCmdlet.ShouldProcess($definition.Name, "Register or update task")) {
        Register-ScheduledTask `
            -TaskName $definition.Name `
            -Action $taskAction `
            -Trigger $trigger `
            -Settings $settings `
            -Description $definition.Description `
            -Force | Out-Null
    }
}
