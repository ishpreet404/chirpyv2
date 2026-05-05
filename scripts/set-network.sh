#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: bash scripts/set-network.sh <PI_IP> <PC_IP>"
  exit 1
fi

PI_IP="$1"
PC_IP="$2"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCALENV="$ROOT/localenv"
FRONTEND_DIR="$ROOT/frontend"

OPENROUTER_API_KEY="your_key_here"
OPENROUTER_MODEL="openai/gpt-4o-mini"
AUDIO_PLAYER="mpg123"
AUDIO_OUTPUT_DEVICE=""
OLED_ENABLED="1"
OLED_I2C_BUS="1"
OLED_I2C_ADDRESS="0x3C"
OLED_WIDTH="128"
OLED_HEIGHT="64"
OLED_FPS="8"
OLED_RETRY_DELAY_S="1.0"
CAMERA_INDEX="0"
DETECTION_CONFIDENCE_THRESHOLD="0.35"

if [ -f "$LOCALENV" ]; then
  existing_key="$(grep -E '^OPENROUTER_API_KEY=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_model="$(grep -E '^OPENROUTER_MODEL=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  [ -n "$existing_key" ] && OPENROUTER_API_KEY="$existing_key"
  [ -n "$existing_model" ] && OPENROUTER_MODEL="$existing_model"
  existing_audio_player="$(grep -E '^AUDIO_PLAYER=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_audio_output="$(grep -E '^AUDIO_OUTPUT_DEVICE=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_enabled="$(grep -E '^OLED_ENABLED=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_bus="$(grep -E '^OLED_I2C_BUS=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_address="$(grep -E '^OLED_I2C_ADDRESS=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_width="$(grep -E '^OLED_WIDTH=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_height="$(grep -E '^OLED_HEIGHT=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_fps="$(grep -E '^OLED_FPS=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_oled_retry_delay="$(grep -E '^OLED_RETRY_DELAY_S=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_camera_index="$(grep -E '^CAMERA_INDEX=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_detection_threshold="$(grep -E '^DETECTION_CONFIDENCE_THRESHOLD=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  [ -n "$existing_audio_player" ] && AUDIO_PLAYER="$existing_audio_player"
  AUDIO_OUTPUT_DEVICE="$existing_audio_output"
  [ -n "$existing_oled_enabled" ] && OLED_ENABLED="$existing_oled_enabled"
  [ -n "$existing_oled_bus" ] && OLED_I2C_BUS="$existing_oled_bus"
  [ -n "$existing_oled_address" ] && OLED_I2C_ADDRESS="$existing_oled_address"
  [ -n "$existing_oled_width" ] && OLED_WIDTH="$existing_oled_width"
  [ -n "$existing_oled_height" ] && OLED_HEIGHT="$existing_oled_height"
  [ -n "$existing_oled_fps" ] && OLED_FPS="$existing_oled_fps"
  [ -n "$existing_oled_retry_delay" ] && OLED_RETRY_DELAY_S="$existing_oled_retry_delay"
  [ -n "$existing_camera_index" ] && CAMERA_INDEX="$existing_camera_index"
  [ -n "$existing_detection_threshold" ] && DETECTION_CONFIDENCE_THRESHOLD="$existing_detection_threshold"
fi

cat > "$LOCALENV" <<EOF
# Single source of truth for ChirpyV2 network addresses
PI_IP=$PI_IP
PC_IP=$PC_IP

# Derived URLs used by backend, Pi bridge, and frontend
PI_BRIDGE_URL=http://$PI_IP:8081
PI_BRIDGE_WS=ws://$PI_IP:8081
BACKEND_HTTP_URL=http://$PC_IP:8000
BACKEND_WS_URL=ws://$PC_IP:8000/ws/rover

# Audio / OLED configuration for Raspberry Pi
# Leave AUDIO_OUTPUT_DEVICE blank to use the Pi default Bluetooth output.
AUDIO_PLAYER=$AUDIO_PLAYER
AUDIO_OUTPUT_DEVICE=$AUDIO_OUTPUT_DEVICE
OLED_ENABLED=$OLED_ENABLED
OLED_I2C_BUS=$OLED_I2C_BUS
OLED_I2C_ADDRESS=$OLED_I2C_ADDRESS
OLED_WIDTH=$OLED_WIDTH
OLED_HEIGHT=$OLED_HEIGHT
OLED_FPS=$OLED_FPS
OLED_RETRY_DELAY_S=$OLED_RETRY_DELAY_S
CAMERA_INDEX=$CAMERA_INDEX
DETECTION_CONFIDENCE_THRESHOLD=$DETECTION_CONFIDENCE_THRESHOLD

# OpenRouter Configuration
OPENROUTER_API_KEY=$OPENROUTER_API_KEY
OPENROUTER_MODEL=$OPENROUTER_MODEL
EOF

for name in .env .env.development .env.local; do
  cat > "$FRONTEND_DIR/$name" <<EOF
REACT_APP_API_URL=http://$PC_IP:8000
REACT_APP_WS_URL=ws://$PC_IP:8000
REACT_APP_PI_BRIDGE_URL=http://$PI_IP:8081
EOF
done

echo "Updated network config:"
echo "  PI_IP=$PI_IP"
echo "  PC_IP=$PC_IP"
echo "  Backend: http://$PC_IP:8000"
echo "  Pi bridge: http://$PI_IP:8081"
