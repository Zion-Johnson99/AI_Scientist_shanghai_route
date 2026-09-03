# launch-local.ps1
# 本地一键启动脚本：同步依赖、启动 HTTP 服务器服务地图网页、打开浏览器
# 用法: .\launch-local.ps1 [-Port 8000] [-NoBrowser]

param(
    [int]$Port = 8000,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

# 确定仓库根目录（脚本所在目录的上一级）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

Write-Host "=== Qwen-Harness 本地启动 ===" -ForegroundColor Cyan
Write-Host "仓库根目录: $RepoRoot"
Write-Host "服务端口: $Port"
Write-Host ""

# 1. 同步 evaluation_model_qwen 依赖
Write-Host "[1/4] 同步 evaluation_model_qwen 依赖..." -ForegroundColor Yellow
$EvalDir = Join-Path $RepoRoot "evaluation_model_qwen"
if (-not (Test-Path $EvalDir)) {
    Write-Error "错误: 未找到 evaluation_model_qwen 目录: $EvalDir"
    exit 2
}
try {
    Push-Location $EvalDir
    uv sync --frozen 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        uv sync 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "错误: evaluation_model_qwen 依赖同步失败"
            exit 2
        }
    }
    Write-Host "  evaluation_model_qwen 依赖同步完成" -ForegroundColor Green
} finally {
    Pop-Location
}

# 2. 同步 Qwen-Harness 依赖
Write-Host "[2/4] 同步 Qwen-Harness 依赖..." -ForegroundColor Yellow
$HarnessDir = Join-Path $RepoRoot "Qwen-Harness"
if (-not (Test-Path $HarnessDir)) {
    Write-Error "错误: 未找到 Qwen-Harness 目录: $HarnessDir"
    exit 2
}
try {
    Push-Location $HarnessDir
    uv sync --frozen 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        uv sync 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Error "错误: Qwen-Harness 依赖同步失败"
            exit 2
        }
    }
    Write-Host "  Qwen-Harness 依赖同步完成" -ForegroundColor Green
} finally {
    Pop-Location
}

# 3. 启动本地 HTTP 服务器服务地图网页目录
Write-Host "[3/4] 启动本地 HTTP 服务器 (端口 $Port)..." -ForegroundColor Yellow
$WebDir = Join-Path $RepoRoot "xuhui_route_builder\web"
if (-not (Test-Path $WebDir)) {
    Write-Error "错误: 未找到地图网页目录: $WebDir"
    exit 2
}

$HttpProcess = $null
try {
    $HttpProcess = Start-Process -FilePath "python" `
        -ArgumentList "-m", "http.server", $Port.ToString(), "--directory", $WebDir `
        -PassThru -NoNewWindow
} catch {
    Write-Error "错误: 启动 HTTP 服务器失败: $_"
    exit 4
}

# 等待服务就绪（最多 10 秒）
$MaxWait = 10
$Waited = 0
$ServiceReady = $false
while ($Waited -lt $MaxWait) {
    Start-Sleep -Seconds 1
    $Waited++
    try {
        $Response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/index.html" -TimeoutSec 2 -UseBasicParsing -ErrorAction SilentlyContinue
        if ($Response.StatusCode -eq 200) {
            $ServiceReady = $true
            break
        }
    } catch {
        # 服务尚未就绪，继续等待
    }
}

if (-not $ServiceReady) {
    Write-Warning "警告: HTTP 服务器未在 ${MaxWait} 秒内就绪，仍尝试打开页面..."
}
Write-Host "  HTTP 服务器已启动 (PID: $($HttpProcess.Id))" -ForegroundColor Green

# 4. 打开浏览器访问地图页面
Write-Host "[4/4] 打开浏览器..." -ForegroundColor Yellow
$MapUrl = "http://127.0.0.1:$Port/index.html"

if (-not $NoBrowser) {
    Start-Process $MapUrl
    Write-Host "  已在浏览器中打开地图页面: $MapUrl" -ForegroundColor Green
} else {
    Write-Host "  跳过浏览器打开（-NoBrowser）" -ForegroundColor Gray
}

Write-Host ""
Write-Host "=== 启动完成 ===" -ForegroundColor Cyan
Write-Host "地图页面: $MapUrl"
Write-Host ""
Write-Host "按 Ctrl+C 或关闭此窗口停止服务。" -ForegroundColor Gray

# 保持脚本运行，等待用户中断
try {
    while (-not $HttpProcess.HasExited) {
        Start-Sleep -Seconds 2
    }
} catch [System.Management.Automation.PipelineStoppedException] {
    # Ctrl+C 中断
} finally {
    if ($HttpProcess -and -not $HttpProcess.HasExited) {
        Write-Host "正在停止服务..." -ForegroundColor Yellow
        $HttpProcess.Kill()
        $HttpProcess.WaitForExit(5000)
        Write-Host "服务已停止。" -ForegroundColor Green
    }
}
