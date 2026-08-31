[CmdletBinding()]
param(
    [switch]$UseQwen
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repositoryRoot = $PSScriptRoot
$evaluationRoot = Join-Path $repositoryRoot "evaluation_model_qwen"
$routeRoot = Join-Path $repositoryRoot "xuhui_route_builder"
$weatherRoot = Join-Path $repositoryRoot "weather_api_data"
$apiExecutable = Join-Path $evaluationRoot ".venv\Scripts\evaluation-model-qwen-api.exe"
$routePython = Join-Path $routeRoot ".venv\Scripts\python.exe"
$weatherExecutable = Join-Path $weatherRoot ".venv\Scripts\weather-api-data.exe"
$weatherEnvFile = Join-Path $weatherRoot ".env"
$dashboardPath = Join-Path $routeRoot "data\web\environment_dashboard.json"
$runtimeRoot = Join-Path $evaluationRoot "runtime\local-app"
$apiHealthUrl = "http://127.0.0.1:8124/api/v1/health"
$webUrl = "http://127.0.0.1:8123/web/"
$startedProcesses = @()
$validTiers = @("weather", "hourly", "daily")
$startupCacheMaxAgeMinutes = 30

function Test-HttpReady {
    param([Parameter(Mandatory)][string]$Uri)

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Assert-PortAvailable {
    param(
        [Parameter(Mandatory)][int]$Port,
        [Parameter(Mandatory)][string]$ServiceName
    )

    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if ($listeners.Count -eq 0) {
        return
    }
    $processIds = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ", "
    throw "$ServiceName 启动失败：端口 $Port 已被进程 $processIds 占用。"
}

function Wait-ServiceReady {
    param(
        [Parameter(Mandatory)][string]$Uri,
        [Parameter(Mandatory)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory)][string]$ServiceName
    )

    for ($attempt = 0; $attempt -lt 30; $attempt += 1) {
        if ($Process.HasExited) {
            throw "$ServiceName 启动后提前退出，退出码为 $($Process.ExitCode)。"
        }
        if (Test-HttpReady -Uri $Uri) {
            return
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$ServiceName 在 15 秒内没有通过健康检查：$Uri"
}

function Convert-ToTimestamp {
    param($Value)

    if ($null -eq $Value) {
        return $null
    }
    $timestamp = [DateTimeOffset]::MinValue
    if ([DateTimeOffset]::TryParse([string]$Value, [ref]$timestamp)) {
        return $timestamp
    }
    return $null
}

function Format-EnvironmentUpdateTime {
    param($Value)

    $timestamp = Convert-ToTimestamp -Value $Value
    if ($null -eq $timestamp) {
        return [string]$Value
    }
    return $timestamp.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss")
}

function Test-RecordExpired {
    param(
        $Record,
        [Parameter(Mandatory)][DateTimeOffset]$Now,
        [int]$RefreshMarginMinutes = 0
    )

    if ($null -eq $Record) {
        return $true
    }
    $statusProperty = $Record.PSObject.Properties["status"]
    if ($null -ne $statusProperty -and [string]$statusProperty.Value -in @("stale", "no_data")) {
        return $true
    }
    $validityProperty = $Record.PSObject.Properties["valid_until"]
    if ($null -eq $validityProperty) {
        $validityProperty = $Record.PSObject.Properties["expires_at"]
    }
    $validityValue = if ($null -eq $validityProperty) { $null } else { $validityProperty.Value }
    $validUntil = Convert-ToTimestamp -Value $validityValue
    if ($null -ne $validUntil -and $validUntil -le $Now.AddMinutes($RefreshMarginMinutes)) {
        return $true
    }
    return $false
}

function Get-EnvironmentRefreshTier {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return "daily"
    }
    try {
        $dashboard = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return "daily"
    }

    $now = [DateTimeOffset]::Now
    $lifeIndices = @($dashboard.current.life_indices)
    $routes = @($dashboard.routes.items)
    if ($lifeIndices.Count -eq 0 -or $routes.Count -eq 0) {
        return "daily"
    }
    $lifeIndicesNeedHourlyRefresh = $false
    foreach ($indexRecord in $lifeIndices) {
        if (Test-RecordExpired -Record $indexRecord -Now $now -RefreshMarginMinutes 5) {
            $lifeIndicesNeedHourlyRefresh = $true
            break
        }
    }

    $routeSample = $routes[0]
    $noiseFetchedAt = Convert-ToTimestamp -Value $routeSample.noise.fetched_at
    $todayPollen = @(
        $routeSample.pollen_daily | Where-Object { $_.business_time -eq $now.ToString("yyyy-MM-dd") }
    )
    if (
        $null -eq $noiseFetchedAt `
        -or $noiseFetchedAt -le $now.AddHours(-24) `
        -or $todayPollen.Count -eq 0 `
        -or (Test-RecordExpired -Record $todayPollen[0] -Now $now)
    ) {
        return "daily"
    }

    $pm25Time = Convert-ToTimestamp -Value $routeSample.pm2_5.business_time
    if (
        $lifeIndicesNeedHourlyRefresh `
        -or (Test-RecordExpired -Record $dashboard.current.aqi -Now $now -RefreshMarginMinutes 5) `
        -or $null -eq $pm25Time `
        -or $pm25Time -le $now.AddHours(-1)
    ) {
        return "hourly"
    }
    if (Test-RecordExpired -Record $dashboard.current.weather -Now $now -RefreshMarginMinutes 5) {
        return "weather"
    }
    return $null
}

function Get-StartupEnvironmentRefreshTier {
    param(
        [AllowNull()][string]$Tier,
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][int]$MaxAgeMinutes
    )

    if (
        $null -eq $Tier `
        -and (Test-EnvironmentDashboardCacheFresh -Path $Path -MaxAgeMinutes $MaxAgeMinutes)
    ) {
        return $null
    }

    if ($Tier -eq "daily") {
        return "daily"
    }
    return "hourly"
}

function Test-EnvironmentDashboardCacheFresh {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][int]$MaxAgeMinutes
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    try {
        $dashboard = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return $false
    }
    $generatedAt = Convert-ToTimestamp -Value $dashboard.metadata.generated_at
    if ($null -eq $generatedAt) {
        return $false
    }
    $age = [DateTimeOffset]::Now - $generatedAt
    return $age.TotalMinutes -ge 0 -and $age.TotalMinutes -lt $MaxAgeMinutes
}

function Get-OptionalPropertyValue {
    param(
        $InputObject,
        [Parameter(Mandatory)][string]$Name
    )

    if ($null -eq $InputObject) {
        return $null
    }
    $property = $InputObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Format-EnvironmentNumber {
    param(
        $Value,
        [Parameter(Mandatory)][string]$Format
    )

    if ($null -eq $Value) {
        return "未知"
    }
    return ([double]$Value).ToString(
        $Format,
        [System.Globalization.CultureInfo]::InvariantCulture
    )
}

function Show-StationRefreshSummary {
    param(
        $RefreshReport,
        $Dashboard
    )

    if ($null -ne $Dashboard) {
        $metadata = Get-OptionalPropertyValue -InputObject $Dashboard -Name "metadata"
        $fusion = Get-OptionalPropertyValue -InputObject $metadata -Name "pm2_5_fusion"
    }
    else {
        $refresh = Get-OptionalPropertyValue -InputObject $RefreshReport -Name "refresh"
        $fusion = Get-OptionalPropertyValue -InputObject $refresh -Name "pm25_grid_fusion"
    }
    $stations = @(Get-OptionalPropertyValue -InputObject $fusion -Name "stations")
    if ($null -eq $fusion -or $stations.Count -eq 0) {
        Write-Warning "本轮未返回 PM2.5 站点时间与权重。"
        return
    }

    foreach ($station in $stations) {
        $stationId = [string](Get-OptionalPropertyValue -InputObject $station -Name "station_id")
        $observedAt = Format-EnvironmentUpdateTime -Value (
            Get-OptionalPropertyValue -InputObject $station -Name "observed_at"
        )
        $ageMinutesValue = Get-OptionalPropertyValue -InputObject $station -Name "age_minutes"
        $ageMinutes = [double]$ageMinutesValue
        $ageText = Format-EnvironmentNumber -Value $ageMinutes -Format "0"
        $temporalWeight = Format-EnvironmentNumber -Value (
            Get-OptionalPropertyValue -InputObject $station -Name "temporal_weight_factor"
        ) -Format "0.000"
        $gridWeightMin = Format-EnvironmentNumber -Value (
            Get-OptionalPropertyValue -InputObject $station -Name "grid_weight_min"
        ) -Format "0.000"
        $gridWeightMax = Format-EnvironmentNumber -Value (
            Get-OptionalPropertyValue -InputObject $station -Name "grid_weight_max"
        ) -Format "0.000"
        $included = [bool](Get-OptionalPropertyValue -InputObject $station -Name "included")

        Write-Host (
            "站点 $stationId：观测时间 $observedAt，滞后 $ageText 分钟，" +
            "时间权重 $temporalWeight，网格权重范围 $gridWeightMin-$gridWeightMax。"
        )
        if (-not $included) {
            Write-Warning "站点 $stationId 滞后已达 24 小时，本轮已剔除。"
        }
        elseif ($ageMinutes -gt 180) {
            Write-Warning "站点 $stationId 滞后超过 3 小时，本轮已降低融合权重。"
        }
    }
}

function Update-EnvironmentData {
    param([Parameter(Mandatory)][string]$Tier)

    if ($Tier -notin $validTiers) {
        throw "未知的数据刷新层级：$Tier"
    }
    if (-not (Test-Path -LiteralPath $weatherExecutable -PathType Leaf)) {
        throw "缺少环境数据服务，请先在 weather_api_data 目录完成依赖安装。"
    }
    if (-not (Test-Path -LiteralPath $weatherEnvFile -PathType Leaf)) {
        throw "缺少 weather_api_data/.env，无法更新环境数据。"
    }

    $refreshLogPath = Join-Path $runtimeRoot "environment-refresh.stdout.log"
    $refreshProcess = Start-Process `
        -FilePath $weatherExecutable `
        -ArgumentList @(
            "--root", $weatherRoot,
            "--env-file", $weatherEnvFile,
            "scheduled-refresh", "--tier", $Tier
        ) `
        -WorkingDirectory $weatherRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $refreshLogPath `
        -RedirectStandardError (Join-Path $runtimeRoot "environment-refresh.stderr.log") `
        -Wait `
        -PassThru
    if ($refreshProcess.ExitCode -ne 0) {
        throw "环境数据刷新失败，退出码为 $($refreshProcess.ExitCode)，日志目录：$runtimeRoot"
    }
    if (-not (Test-Path -LiteralPath $dashboardPath -PathType Leaf)) {
        throw "环境数据刷新结束后仍缺少网页数据包，日志目录：$runtimeRoot"
    }

    try {
        $refreshReport = Get-Content -LiteralPath $refreshLogPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        throw "环境数据刷新日志无法解析，日志目录：$runtimeRoot"
    }
    $updatedDashboard = Get-Content -LiteralPath $dashboardPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $updateTime = Format-EnvironmentUpdateTime -Value $updatedDashboard.metadata.generated_at
    $runStatus = [string](Get-OptionalPropertyValue -InputObject $refreshReport -Name "status")
    $publish = Get-OptionalPropertyValue -InputObject $refreshReport -Name "publish"
    $publishStatus = [string](Get-OptionalPropertyValue -InputObject $publish -Name "status")
    if ($publishStatus -eq "stale") {
        Write-Warning "环境数据未生成新快照，继续使用上次数据，更新时间：$updateTime。"
    }
    else {
        Write-Host "环境数据已发布，状态：$runStatus，更新时间：$updateTime。"
    }
    if ($runStatus -eq "partial") {
        Write-Warning "本轮部分环境数据源已降级，详情见下方站点摘要和刷新日志。"
    }
    Show-StationRefreshSummary -RefreshReport $refreshReport
}

if (-not (Test-Path -LiteralPath $apiExecutable -PathType Leaf)) {
    throw "缺少推荐服务，请先在 evaluation_model_qwen 目录运行 uv sync --extra dev。"
}
if (-not (Test-Path -LiteralPath $routePython -PathType Leaf)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $pythonCommand) {
        throw "缺少可用的 Python，无法启动静态网页服务。"
    }
    $routePython = $pythonCommand.Source
}

New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$refreshTier = Get-StartupEnvironmentRefreshTier -Tier (
    Get-EnvironmentRefreshTier -Path $dashboardPath
) -Path $dashboardPath -MaxAgeMinutes $startupCacheMaxAgeMinutes
if ($null -eq $refreshTier) {
    $currentDashboard = Get-Content -LiteralPath $dashboardPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $updateTime = Format-EnvironmentUpdateTime -Value $currentDashboard.metadata.generated_at
    Write-Host "环境数据缓存仍有效，更新时间：$updateTime。"
    Show-StationRefreshSummary -Dashboard $currentDashboard
}
else {
    Update-EnvironmentData -Tier $refreshTier
}
$offlineMode = if ($UseQwen) { "0" } else { "1" }
$modeLabel = if ($UseQwen) { "千问审核，异常时回退本地排序" } else { "本地 Python 排序" }

try {
    if (Test-HttpReady -Uri $apiHealthUrl) {
        $existingHealth = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 3
        $requestedOfflineMode = -not [bool]$UseQwen
        if ([bool]$existingHealth.qwen.offline -ne $requestedOfflineMode) {
            throw "推荐服务正在使用另一种运行模式，请先在原命令窗口按 Ctrl+C，再重新执行当前命令。"
        }
        Write-Host "推荐服务已运行，继续复用 8124 端口。"
    }
    else {
        Assert-PortAvailable -Port 8124 -ServiceName "推荐服务"
        $previousOfflineMode = $env:EVALUATION_MODEL_QWEN_OFFLINE
        $env:EVALUATION_MODEL_QWEN_OFFLINE = $offlineMode
        try {
            $apiProcess = Start-Process `
                -FilePath $apiExecutable `
                -ArgumentList @("--host", "127.0.0.1", "--port", "8124") `
                -WorkingDirectory $evaluationRoot `
                -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $runtimeRoot "api.stdout.log") `
                -RedirectStandardError (Join-Path $runtimeRoot "api.stderr.log") `
                -PassThru
        }
        finally {
            $env:EVALUATION_MODEL_QWEN_OFFLINE = $previousOfflineMode
        }
        $startedProcesses += $apiProcess
        Wait-ServiceReady -Uri $apiHealthUrl -Process $apiProcess -ServiceName "推荐服务"
        Write-Host "推荐服务已启动：$modeLabel"
    }

    if ($UseQwen) {
        $health = Invoke-RestMethod -Uri $apiHealthUrl -TimeoutSec 3
        if (-not $health.qwen.configured) {
            Write-Warning "千问配置尚未完成，当前请求会回退到本地 Python 排序。"
        }
    }

    if (Test-HttpReady -Uri $webUrl) {
        Write-Host "网页服务已运行，继续复用 8123 端口。"
    }
    else {
        Assert-PortAvailable -Port 8123 -ServiceName "网页服务"
        $webProcess = Start-Process `
            -FilePath $routePython `
            -ArgumentList @("-m", "http.server", "8123", "--bind", "127.0.0.1") `
            -WorkingDirectory $routeRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtimeRoot "web.stdout.log") `
            -RedirectStandardError (Join-Path $runtimeRoot "web.stderr.log") `
            -PassThru
        $startedProcesses += $webProcess
        Wait-ServiceReady -Uri $webUrl -Process $webProcess -ServiceName "网页服务"
        Write-Host "网页服务已启动。"
    }

    Write-Host "正在打开 $webUrl"
    Start-Process -FilePath $webUrl

    Write-Host "完整本地应用正在运行。按 Ctrl+C 统一停止本次启动的服务。"
    $nextEnvironmentCheck = [DateTimeOffset]::Now.AddMinutes(30)
    while ($true) {
        Start-Sleep -Seconds 1
        foreach ($process in $startedProcesses) {
            if ($process.HasExited) {
                throw "本地服务进程 $($process.Id) 已退出，日志目录：$runtimeRoot"
            }
        }

        $now = [DateTimeOffset]::Now
        if ($now -lt $nextEnvironmentCheck) {
            continue
        }
        $nextEnvironmentCheck = $now.AddMinutes(30)
        try {
            $continuousRefreshTier = Get-EnvironmentRefreshTier -Path $dashboardPath
            if ($null -ne $continuousRefreshTier) {
                Update-EnvironmentData -Tier $continuousRefreshTier
            }
        }
        catch {
            Write-Warning "运行期间环境数据刷新失败，继续使用上一份数据：$($_.Exception.Message)"
        }
    }
}
finally {
    foreach ($process in $startedProcesses) {
        if (-not $process.HasExited) {
            Stop-Process -Id $process.Id -ErrorAction SilentlyContinue
            Wait-Process -Id $process.Id -Timeout 5 -ErrorAction SilentlyContinue
        }
    }
    if ($startedProcesses.Count -gt 0) {
        Write-Host "本次启动的本地服务已停止。"
    }
}
