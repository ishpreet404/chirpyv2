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
$audioPlayer = "mpg123"
$audioOutputDevice = ""
$oledEnabled = "1"
$oledI2cBus = "1"
$oledI2cAddress = "0x3C"
$oledWidth = "128"
$oledHeight = "64"
if (Test-Path $localEnvPath) {
    foreach ($line in [System.IO.File]::ReadAllLines($localEnvPath)) {
        if ($line -match "^\s*OPENROUTER_API_KEY=(.*)$") {
            $openRouterKey = $Matches[1]
        }
        if ($line -match "^\s*OPENROUTER_MODEL=(.*)$") {
            $openRouterModel = $Matches[1]
        }
        if ($line -match "^\s*AUDIO_PLAYER=(.*)$") { $audioPlayer = $Matches[1] }
        if ($line -match "^\s*AUDIO_OUTPUT_DEVICE=(.*)$") { $audioOutputDevice = $Matches[1] }
        if ($line -match "^\s*OLED_ENABLED=(.*)$") { $oledEnabled = $Matches[1] }
        if ($line -match "^\s*OLED_I2C_BUS=(.*)$") { $oledI2cBus = $Matches[1] }
        if ($line -match "^\s*OLED_I2C_ADDRESS=(.*)$") { $oledI2cAddress = $Matches[1] }
        if ($line -match "^\s*OLED_WIDTH=(.*)$") { $oledWidth = $Matches[1] }
        if ($line -match "^\s*OLED_HEIGHT=(.*)$") { $oledHeight = $Matches[1] }
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
    "# Audio / OLED configuration for Raspberry Pi",
    "# Leave AUDIO_OUTPUT_DEVICE blank to use the Pi default Bluetooth output.",
    "AUDIO_PLAYER=$audioPlayer",
    "AUDIO_OUTPUT_DEVICE=$audioOutputDevice",
    "OLED_ENABLED=$oledEnabled",
    "OLED_I2C_BUS=$oledI2cBus",
    "OLED_I2C_ADDRESS=$oledI2cAddress",
    "OLED_WIDTH=$oledWidth",
    "OLED_HEIGHT=$oledHeight",
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
