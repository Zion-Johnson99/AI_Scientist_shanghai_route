<#
.SYNOPSIS
    Launch the round-2 local web product with no external network dependency.

.DESCRIPTION
    Serves publish/local-product over 127.0.0.1 and opens the default browser.
    Requires Python 3.10 or newer on PATH. No API key is read or used.

.EXAMPLE
    pwsh -File launch-local.ps1
    pwsh -File launch-local.ps1 -Port 9000 -NoBrowser
#>

[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

$RunRoot = Split-Path -Parent $PSScriptRoot
$ProductRoot = Join-Path $PSScriptRoot 'local-product'
$SourceRoot = Join-Path $RunRoot 'workspace/source'
$IndexFile = Join-Path $ProductRoot 'index.html'

if (-not (Test-Path -LiteralPath $IndexFile)) {
    Write-Host "[launch] missing $IndexFile" -ForegroundColor Red
    Write-Host '[launch] run: python reproduce.py --stage web' -ForegroundColor Yellow
    exit 1
}

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    $Python = Get-Command py -ErrorAction SilentlyContinue
}
if (-not $Python) {
    Write-Host '[launch] python not found on PATH' -ForegroundColor Red
    exit 1
}

foreach ($Key in @('DASHSCOPE_API_KEY', 'OPENAI_API_KEY', 'BAILIAN_API_KEY')) {
    if (Test-Path "Env:$Key") { Remove-Item "Env:$Key" -Force }
}

$Url = "http://127.0.0.1:$Port/index.html"
Write-Host "[launch] product root : $ProductRoot"
Write-Host "[launch] source root  : $SourceRoot"
Write-Host "[launch] url          : $Url"
Write-Host '[launch] offline      : true (no CDN, no tile server, no LLM API)'

if (-not $NoBrowser) {
    Start-Process $Url
}

Push-Location $ProductRoot
try {
    & $Python.Source -m http.server $Port --bind 127.0.0.1
}
finally {
    Pop-Location
}
