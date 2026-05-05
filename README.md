# ChirpyV2: Disaster Rescue Rover Mission Control

ChirpyV2 is a sophisticated, full-stack disaster response robotics platform. It combines a highly responsive ESP32-based hardware controller with a Raspberry Pi vision/interaction bridge, a FastAPI mission-tracking backend, and a modern React satellite-mapped mission control dashboard.

---

## 🚀 Key Features

### 1. Autonomous & Assisted Mission Control
*   **Satellite Mapping**: Real-time projection of rover odometry onto high-resolution satellite maps using Leaflet.
*   **Route Planner**: Click-to-create waypoints for patrol routes. Support for "Save", "Start Patrol", "Pause", and "Resume".
*   **Autonomy Modes**: Dedicated UI for triggering specialized motion modes (Follow-Path, Search-Grid, Return-to-Home, etc.).
*   **Manual Overrides**: Low-latency keyboard and UI-based controls (F, B, L, R, S) for direct intervention.

### 2. Survivor Interaction Module (SIM)
*   **CV Victim Detection**: HOG-based person detection runs on the Raspberry Pi; automatically identifies survivors.
*   **Autonomous Triage**: Upon detection, the rover initiates a timed speech sequence to identify itself and gather vital triage data (Injuries, Mobility).
*   **Advanced AI (OpenRouter)**: Integrated with OpenRouter (GPT-4o/Gemini) to provide context-aware, calm, and bounded responses to survivors.
*   **Voice Interaction**: Offline Speech-to-Text via **Vosk** with prerecorded MP3 voice prompts for field deployments.
*   **Conversation Log**: Full transcripts of robot-survivor interactions are streamed to the dashboard in real-time.

### 3. Precision Telemetry & Monitoring
*   **Multi-Sensor Data**: Tracks battery voltage, acceleration, gyro rates, ultrasonic distance, and thermal state at 20Hz.
*   **Odometry Tracking**: Real-time X/Y calculation converted to GPS coordinates via an adjustable `odomToLatLng` mapping.
*   **Mission Archive**: Automatic history logging with CSV and JSON export capabilities for post-mission analysis.
*   **Visual Trend View**: Interactive charts for battery health and sensor stability tracking over time.

### 4. Path Intelligence (Zone-Based Risk Mapping)
*   **Zone Aggregation**: Aggregates rover odometry, obstacle hits, and victim detections into a 1m grid of zones.
*   **Risk Metrics**: Each zone tracks visit counts and timestamps; zones with multiple obstacles or any victim are automatically flagged as high‑risk.
*   **Frontier Search**: Employs a BFS-based frontier search to suggest the next reachable unexplored zone while avoiding blocked areas.
*   **Visual Risk Overlay**: The UI renders high‑risk zones directly on the satellite map as circular overlays, allowing field teams to see risk concentration at a glance.

### 5. Safety & Reliability
*   **Hard-Coded Obstacle Avoidance**: ESP32 firmware includes a "fail-safe" layer that overrides all commands to auto-reverse if an object is within 25cm.
*   **Watchdog Alerts**: Real-time notifications for battery levels, sensor anomalies, and connection drops.
*   **Robust Comms**: Serial CRC8 verification and sequence tracking between Pi and ESP32 to prevent packet corruption.

---

## 🛠 Tech Stack

| Component | Technology |
| :--- | :--- |
| **Firmware** | C++/Arduino (ESP32 DevKit V1), L298N, MPU6050, HC-SR04 |
| **Bridge** | Python 3, OpenCV (HOG), Vosk (STT), MP3 playback, aiohttp |
| **Backend** | Python, FastAPI, WebSockets, OpenRouter SDK |
| **Frontend** | React, Leaflet (Maps), Chart.js, Styled Components |

---

## 📂 Project Structure

```bash
chirpy_v2/
├── esp32/                 # Arduino/ESP32 core firmware
│   └── chirpy_v2_fixed_again.ino
├── pi_bridge/             # Raspberry Pi Vision & Interaction layer
│   ├── bridge.py          # Main Serial-to-Backend relay & CV logic
│   ├── survivor_module.py # STT and prerecorded triage audio flow
│   └── model/             # (Not provided) Download Vosk model here
├── backend/               # Mission control API & State management
│   └── main.py            # FastAPI server with WebSocket relays
└── frontend/              # Mission Control Dashboard
    ├── src/App.js         # Unified UI (Landing, Dashboard, Map, Survivor, Archive)
    └── public/            # Static assets
```

---

## ⚙️ Quick Start

### 1. Environment Configuration
Set the PC and Raspberry Pi addresses with one command from the repo root:
```powershell
powershell -ExecutionPolicy Bypass -File scripts\set-network.ps1 -PiIp 10.109.36.26 -PcIp 10.109.36.236
```

On the Raspberry Pi or any Bash shell, use:
```bash
bash scripts/set-network.sh 10.109.36.26 10.109.36.236
```

This updates `localenv` and the React `.env*` files. The root `localenv` keeps only the two machine IPs as the source of truth, then stores the derived URLs used by the backend, Pi bridge, and frontend:
```env
PI_IP=10.109.36.26
PC_IP=10.109.36.236
PI_BRIDGE_URL=http://10.109.36.26:8081
BACKEND_HTTP_URL=http://10.109.36.236:8000
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-4o-mini
```

### 2. Start Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. Start Frontend
```bash
cd frontend
npm install
npm start
```

### 4. Start Pi Bridge
```bash
cd pi_bridge
# Ensure portaudio19-dev and mpg123 are installed for Bluetooth mic/audio playback
python3 bridge.py
```

For Bluetooth audio, pair/connect the speaker in Raspberry Pi OS and make it the default output/input. The MP3 voice flow uses `AUDIO_PLAYER=mpg123` by default. If playback is silent because the Bluetooth speaker is not the default ALSA device, set `AUDIO_OUTPUT_DEVICE` in `localenv`, for example:
```env
AUDIO_PLAYER=mpg123
AUDIO_OUTPUT_DEVICE=bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp
```

For the I2C OLED eyes display, enable I2C and install the Pi bridge requirements. The default display is SSD1306 at address `0x3C` on I2C bus `1`:
```env
OLED_ENABLED=1
OLED_I2C_BUS=1
OLED_I2C_ADDRESS=0x3C
OLED_WIDTH=128
OLED_HEIGHT=64
```

---

## 🚩 Disclaimer
*This project is intended for educational and research purposes in disaster robotics. Always ensure hardware is tested in a controlled environment before field deployment.*
