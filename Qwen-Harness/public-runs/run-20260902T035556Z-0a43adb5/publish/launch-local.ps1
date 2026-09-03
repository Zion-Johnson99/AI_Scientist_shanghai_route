Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$productRoot = Join-Path $PSScriptRoot "local-product"
$indexPath = Join-Path $productRoot "web\index.html"
$apiRoot = Join-Path $PSScriptRoot "source\evaluation_model_qwen"
$apiProjectPath = Join-Path $apiRoot "pyproject.toml"
$apiHealthUrl = "http://127.0.0.1:8124/api/v1/health"
$apiProcess = $null
$apiServiceProcessId = $null

if (-not (Test-Path -LiteralPath $indexPath)) {
    throw "本地地图产品不完整: $indexPath"
}
if (-not (Test-Path -LiteralPath $apiProjectPath)) {
    throw "本轮生成的推荐服务缺少 pyproject.toml: $apiProjectPath；无法启动 uvicorn。"
}

function Test-ApiReady {
    try {
        $response = Invoke-WebRequest -Uri $apiHealthUrl -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

$apiReady = Test-ApiReady
try {
    if (-not $apiReady) {
        $uv = Get-Command uv -ErrorAction Stop
        $env:EVALUATION_MODEL_QWEN_OFFLINE = "1"
        $env:EVALUATION_MODEL_QWEN_ALLOWED_ORIGINS = "http://127.0.0.1:8130,http://localhost:8130"
        $env:EVALUATION_MODEL_QWEN_AUDIT_ROOT = Join-Path $apiRoot "runtime\recommendations"
        $stdoutLog = Join-Path $PSScriptRoot "checks\local-api.stdout.log"
        $stderrLog = Join-Path $PSScriptRoot "checks\local-api.stderr.log"
        $apiArgs = @(
            "run", "--project", "`"$apiRoot`"", "uvicorn", "evaluation_model_qwen.api:app",
            "--host", "127.0.0.1", "--port", "8124"
        )
        $apiProcess = Start-Process -FilePath $uv.Source -ArgumentList $apiArgs `
            -WorkingDirectory $apiRoot -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog
        for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
            if ($apiProcess.HasExited) {
                break
            }
            if (Test-ApiReady) {
                $apiReady = $true
                break
            }
            Start-Sleep -Milliseconds 500
        }
    }
    if ($apiReady) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort 8124 -ErrorAction Stop |
            Select-Object -First 1
        $apiServiceProcessId = $listener.OwningProcess
        Write-Host "本地推荐服务已就绪: $apiHealthUrl"
    }
    else {
        Write-Warning "本轮生成的推荐服务健康检查未就绪: $apiHealthUrl；网页继续以无推荐服务模式启动；查看 $stderrLog"
    }

    Write-Host "本地地图已就绪: http://127.0.0.1:8130/web/"
    Write-Host "按 Ctrl+C 停止服务。"
    python -m http.server 8130 --bind 127.0.0.1 --directory $productRoot
}
finally {
    if ($null -ne $apiServiceProcessId) {
        Stop-Process -Id $apiServiceProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($null -ne $apiProcess -and -not $apiProcess.HasExited) {
        Stop-Process -Id $apiProcess.Id -Force
    }
}
