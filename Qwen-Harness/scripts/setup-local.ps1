[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$HarnessRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$ExampleEnv = Join-Path $HarnessRoot ".env.example"
$LocalEnv = Join-Path $HarnessRoot ".env"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "未检测到 uv。请先安装稳定版 uv：https://docs.astral.sh/uv/getting-started/installation/"
}

if (-not (Test-Path -LiteralPath $ExampleEnv -PathType Leaf)) {
    throw "缺少环境模板：$ExampleEnv"
}

Push-Location $HarnessRoot
try {
    Write-Host "[1/3] 安装锁定的运行与开发依赖"
    uv sync --all-extras --frozen
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync 执行失败，退出码：$LASTEXITCODE"
    }

    if (Test-Path -LiteralPath $LocalEnv -PathType Leaf) {
        Write-Host "[2/3] 保留已有 .env，未覆盖本地配置"
    }
    else {
        Copy-Item -LiteralPath $ExampleEnv -Destination $LocalEnv
        Write-Host "[2/3] 已从 .env.example 创建 .env；请填写 DASHSCOPE_API_KEY 与真实 Workspace 地址"
    }

    Write-Host "[3/3] 校验离线配置契约"
    uv run qwen-harness validate --scope config
    if ($LASTEXITCODE -ne 0) {
        throw "Qwen-Harness 配置校验失败，退出码：$LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Host "本地环境准备完成。真实 Key 仅填写在 Qwen-Harness/.env；运行结果只写入 Qwen-Harness/runtime。"
