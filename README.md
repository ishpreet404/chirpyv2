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
*   **STT/TTS**: Offline Speech-to-Text via **Vosk** and Text-to-Speech via **espeak-ng** for high-reliability in field deployments.
*   **Conversation Log**: Full transcripts of robot-survivor interactions are streamed to the dashboard in real-time.

### 3. Precision Telemetry & Monitoring
*   **Multi-Sensor Data**: Tracks battery voltage, acceleration, gyro rates, ultrasonic distance, and thermal state at 20Hz.
*   **Odometry Tracking**: Real-time X/Y calculation converted to GPS coordinates via an adjustable `odomToLatLng` mapping.
*   **Mission Archive**: Automatic history logging with CSV and JSON export capabilities for post-mission analysis.
*   **Visual Trend View**: Interactive charts for battery health and sensor stability tracking over time.

### 4. Safety & Reliability
*   **Hard-Coded Obstacle Avoidance**: ESP32 firmware includes a "fail-safe" layer that overrides all commands to auto-reverse if an object is within 25cm.
*   **Watchdog Alerts**: Real-time notifications for battery levels, sensor anomalies, and connection drops.
*   **Robust Comms**: Serial CRC8 verification and sequence tracking between Pi and ESP32 to prevent packet corruption.

---

## 🛠 Tech Stack

| Component | Technology |
| :--- | :--- |
| **Firmware** | C++/Arduino (ESP32 DevKit V1), L298N, MPU6050, HC-SR04 |
| **Bridge** | Python 3, OpenCV (HOG), Vosk (STT), espeak-ng (TTS), aiohttp |
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
│   ├── survivor_module.py # STT/TTS and Triage sequence logic
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
Create or edit the `localenv` file in the root directory:
```env
PI_BRIDGE_URL=http://<PI_IP>:8081
BACKEND_HTTP_URL=http://<BACKEND_IP>:8000
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
# Ensure espeak-ng and portaudio19-dev are installed
python3 bridge.py
```

---

## 🚩 Disclaimer
*This project is intended for educational and research purposes in disaster robotics. Always ensure hardware is tested in a controlled environment before field deployment.*
