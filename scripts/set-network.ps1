param(
    [Parameter(Mandatory = $true)]
    [string]$PiIp,

    [Parameter(Mandatory = $true)]
    [string]$PcIp
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$localEnvPath = Join-Path $root "localenv"
$frontendDir = Join-Path $root "frontend"

$openRouterKey = "your_key_here"
$openRouterModel = "openai/gpt-4o-mini"
if (Test-Path $localEnvPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($localEnvPath)) {
        if ($line -match "^\s*OPENROUTER_API_KEY=(.*)$") {
            $openRouterKey = $Matches[1]
        }
        if ($line -match "^\s*OPENROUTER_MODEL=(.*)$") {
            $openRouterModel = $Matches[1]
        }
    }
}

$localEnv = @(
    "# Single source of truth for ChirpyV2 network addresses",
    "PI_IP=$PiIp",
    "PC_IP=$PcIp",
    "",
    "# Derived URLs used by backend, Pi bridge, and frontend",
    "PI_BRIDGE_URL=http://${PiIp}:8081",
    "PI_BRIDGE_WS=ws://${PiIp}:8081",
    "BACKEND_HTTP_URL=http://${PcIp}:8000",
    "BACKEND_WS_URL=ws://${PcIp}:8000/ws/rover",
    "",
    "# OpenRouter Configuration",
    "OPENROUTER_API_KEY=$openRouterKey",
    "OPENROUTER_MODEL=$openRouterModel"
)
[System.IO.File]::WriteAllLines($localEnvPath, $localEnv)

$frontendEnv = @(
    "REACT_APP_API_URL=http://${PcIp}:8000",
    "REACT_APP_WS_URL=ws://${PcIp}:8000",
    "REACT_APP_PI_BRIDGE_URL=http://${PiIp}:8081"
)

foreach ($name in ".env", ".env.development", ".env.local") {
    [System.IO.File]::WriteAllLines((Join-Path $frontendDir $name), $frontendEnv)
}

Write-Host "Updated network config:"
Write-Host "  PI_IP=$PiIp"
Write-Host "  PC_IP=$PcIp"
Write-Host "  Backend: http://${PcIp}:8000"
Write-Host "  Pi bridge: http://${PiIp}:8081"
