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

if [ -f "$LOCALENV" ]; then
  existing_key="$(grep -E '^OPENROUTER_API_KEY=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  existing_model="$(grep -E '^OPENROUTER_MODEL=' "$LOCALENV" | tail -n 1 | cut -d= -f2- || true)"
  [ -n "$existing_key" ] && OPENROUTER_API_KEY="$existing_key"
  [ -n "$existing_model" ] && OPENROUTER_MODEL="$existing_model"
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
