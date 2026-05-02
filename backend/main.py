"""
Disaster Rescue Rover — Backend Server
=======================================
FastAPI backend serving:
  - WebSocket endpoint for real-time telemetry from Pi bridge
  - WebSocket endpoint for React frontend dashboard
  - REST APIs for path, telemetry, alerts, mission control
  - Camera stream proxy (forwards from Pi bridge)
  - In-memory mission state with history

Run:  uvicorn main:app --host 0.0.0.0 --port 8000 --reload
Deps: pip install fastapi uvicorn websockets aiohttp python-dotenv
"""

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import aiohttp

# ─── Configuration ───────────────────────────────────────────────────────────

PI_BRIDGE_URL    = "http://raspberry-pi.local:8081"   # adjust to Pi IP
PI_BRIDGE_WS     = "ws://raspberry-pi.local:8081"     # if Pi has WS
MAX_TELEMETRY_HISTORY = 2000     # packets kept in memory
MAX_ALERTS       = 200

FIRMWARE_PROFILE = "chirpy_v2_legacy"
SUPPORTED_COMMANDS = ("F", "B", "L", "R", "S")
CAPABILITIES = {
    "profile": FIRMWARE_PROFILE,
    "commands": list(SUPPORTED_COMMANDS),
    "auto_mode": False,
    "ping": False,
    "victim_notify": False,
    "crc_seq": False,
}

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Rescue Rover Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Mission State ────────────────────────────────────────────────────────────

class MissionState:
    def __init__(self):
        self.telemetry_history : deque[dict] = deque(maxlen=MAX_TELEMETRY_HISTORY)
        self.latest_telemetry  : dict | None = None
        self.path_data         : dict        = {
            'session_id':    None,
            'segments':      [],
            'obstacles':     [],
            'victims':       [],
            'total_dist_cm': 0.0,
        }
        self.alerts            : deque[dict] = deque(maxlen=MAX_ALERTS)
        self.mission_active    = False
        self.mission_start_t   : float | None = None
        self.pi_connected      = False
        self.rover_state       = "UNKNOWN"   # STP/FWD/BCK/LFT/RGT
        self.auto_mode         = False
        self.obstacle_active   = False
        self.victim_count      = 0
        self._lock             = asyncio.Lock()

        # WebSocket clients: {'rover': [ws], 'dashboard': [ws]}
        self.ws_clients: dict[str, list[WebSocket]] = {
            'rover':     [],
            'dashboard': [],
        }

    def add_alert(self, level: str, msg: str, data: dict = None):
        alert = {
            'id':        len(self.alerts) + 1,
            'level':     level,    # info / warning / critical
            'message':   msg,
            'data':      data or {},
            'timestamp': datetime.now().isoformat(),
        }
        self.alerts.appendleft(alert)
        return alert

    async def broadcast(self, channel: str, msg: dict):
        dead = []
        for ws in self.ws_clients.get(channel, []):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self.ws_clients[channel].remove(ws)
            except ValueError:
                pass

    async def broadcast_all(self, msg: dict):
        await self.broadcast('dashboard', msg)

    def update_from_telemetry(self, data: dict, abs_x: float, abs_y: float):
        """Process a telemetry packet and update mission state."""
        self.latest_telemetry = {**data, 'abs_x': abs_x, 'abs_y': abs_y,
                                  'server_ts': time.time()}
        self.telemetry_history.append(self.latest_telemetry)
        self.rover_state     = data.get('state', 'STP')
        self.obstacle_active = bool(data.get('obstacle', 0))
        victims = data.get('victims')
        if isinstance(victims, int):
            self.victim_count = victims

        # Flags → alerts
        flags = data.get('flags', 'OK')
        if flags == 'W:BATT':
            self.add_alert('critical', f"Low battery: {data.get('estV', 0):.1f}V")
        elif flags == 'W:IMU':
            self.add_alert('warning', 'IMU sensor anomaly detected')
        elif flags == 'W:SONAR':
            self.add_alert('warning', 'Ultrasonic sensor spike detected')
        elif flags == 'W:MULTI':
            self.add_alert('critical', 'Multiple sensor warnings')

        if not self.mission_active:
            self.mission_active  = True
            self.mission_start_t = time.time()
            self.add_alert('info', 'Mission started')

    def update_path(self, path_data: dict):
        self.path_data = path_data

    def add_victim(self, x: float, y: float, confidence: float):
        self.victim_count += 1
        alert = self.add_alert(
            'critical',
            f"Victim #{self.victim_count} detected at ({x:.1f}, {y:.1f}) — conf {confidence:.0%}",
            {'x': x, 'y': y, 'confidence': confidence, 'victim_id': self.victim_count}
        )
        return alert


mission = MissionState()

# ─── WebSocket: Pi Bridge → Backend ─────────────────────────────────────────

@app.websocket("/ws/rover")
async def ws_rover(websocket: WebSocket):
    """
    Receives JSON messages from Pi bridge:
      {'type': 'telemetry', 'data': {...}, 'abs_x': ..., 'abs_y': ..., 'path': {...}}
      {'type': 'event',     'event': 'obstacle'|'clear'|'ack'|..., 'raw': str}
      {'type': 'victim_detected', 'x': ..., 'y': ..., 'confidence': ..., ...}
    """
    await websocket.accept()
    mission.ws_clients['rover'].append(websocket)
    mission.pi_connected = True
    log.info("Pi bridge connected via WS")
    mission.add_alert('info', 'Pi bridge connected')

    try:
        async for raw_msg in websocket.iter_text():
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get('type')

            if msg_type == 'telemetry':
                data  = msg.get('data', {})
                abs_x = msg.get('abs_x', 0.0)
                abs_y = msg.get('abs_y', 0.0)
                path  = msg.get('path', {})

                mission.update_from_telemetry(data, abs_x, abs_y)
                if path:
                    mission.update_path(path)

                # Forward to all dashboard clients
                await mission.broadcast('dashboard', {
                    'type':     'telemetry',
                    'telemetry': mission.latest_telemetry,
                    'path':     mission.path_data,
                })

            elif msg_type == 'event':
                event = msg.get('event', '')
                raw   = msg.get('raw', '')

                if event == 'obstacle':
                    mission.obstacle_active = True
                    mission.add_alert('warning', 'Obstacle detected — auto-reversing')
                elif event == 'clear':
                    mission.obstacle_active = False
                elif event == 'watchdog':
                    mission.add_alert('critical', 'ESP32 watchdog: Pi heartbeat missed')
                elif event == 'ready':
                    mission.add_alert('info', 'ESP32 rover ready')

                await mission.broadcast('dashboard', {
                    'type':  'event',
                    'event': event,
                    'raw':   raw,
                    'alert': mission.alerts[0] if mission.alerts else None,
                })

            elif msg_type == 'victim_detected':
                x    = msg.get('x', 0.0)
                y    = msg.get('y', 0.0)
                conf = msg.get('confidence', 0.0)
                alert = mission.add_victim(x, y, conf)

                await mission.broadcast('dashboard', {
                    'type':    'victim',
                    'x':       x,
                    'y':       y,
                    'confidence': conf,
                    'count':   mission.victim_count,
                    'alert':   alert,
                })

    except WebSocketDisconnect:
        log.info("Pi bridge WS disconnected")
    finally:
        try:
            mission.ws_clients['rover'].remove(websocket)
        except ValueError:
            pass
        mission.pi_connected = False
        mission.add_alert('warning', 'Pi bridge disconnected')


# ─── WebSocket: Backend → Dashboard ─────────────────────────────────────────

@app.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """
    Real-time feed for React dashboard.
    Sends initial state on connect, then streams updates.
    """
    await websocket.accept()
    mission.ws_clients['dashboard'].append(websocket)
    log.info("Dashboard client connected")

    # Send full current state on connect
    await websocket.send_json({
        'type':      'init',
        'telemetry': mission.latest_telemetry,
        'path':      mission.path_data,
        'alerts':    list(mission.alerts)[:20],
        'status': {
            'pi_connected':    mission.pi_connected,
            'mission_active':  mission.mission_active,
            'rover_state':     mission.rover_state,
            'auto_mode':       mission.auto_mode,
            'obstacle_active': mission.obstacle_active,
            'victim_count':    mission.victim_count,
            'capabilities':    CAPABILITIES,
        },
    })

    try:
        async for raw_msg in websocket.iter_text():
            # Dashboard can send commands: {"command": "F"} etc.
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            if msg.get('type') == 'command':
                cmd = msg.get('command', '').upper()
                if cmd in SUPPORTED_COMMANDS:
                    # Forward to Pi bridge via HTTP
                    asyncio.create_task(_forward_command(cmd))
                    await websocket.send_json({'type': 'cmd_sent', 'command': cmd})

    except WebSocketDisconnect:
        log.info("Dashboard client disconnected")
    finally:
        try:
            mission.ws_clients['dashboard'].remove(websocket)
        except ValueError:
            pass


async def _forward_command(cmd: str):
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{PI_BRIDGE_URL}/command",
                json={'command': cmd},
                timeout=aiohttp.ClientTimeout(total=2),
            )
    except Exception as e:
        log.warning(f"Command forward failed: {e}")

# ─── REST API ─────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    mission_duration = None
    if mission.mission_start_t:
        mission_duration = round(time.time() - mission.mission_start_t, 1)

    return {
        'pi_connected':    mission.pi_connected,
        'mission_active':  mission.mission_active,
        'mission_duration_s': mission_duration,
        'rover_state':     mission.rover_state,
        'auto_mode':       mission.auto_mode,
        'obstacle_active': mission.obstacle_active,
        'victim_count':    mission.victim_count,
        'total_dist_cm':   mission.path_data.get('total_dist_cm', 0),
        'latest_telemetry': mission.latest_telemetry,
        'capabilities':    CAPABILITIES,
    }


@app.get("/api/telemetry/history")
async def get_telemetry_history(limit: int = 100):
    history = list(mission.telemetry_history)
    return {'telemetry': history[-limit:], 'total': len(history)}


@app.get("/api/path")
async def get_path():
    return mission.path_data


@app.get("/api/alerts")
async def get_alerts(limit: int = 50):
    return {'alerts': list(mission.alerts)[:limit]}


@app.get("/api/victims")
async def get_victims():
    return {
        'count':   mission.victim_count,
        'victims': mission.path_data.get('victims', []),
    }


@app.post("/api/command")
async def post_command(body: dict):
    cmd = body.get('command', '').upper()
    if cmd not in SUPPORTED_COMMANDS:
        raise HTTPException(status_code=400, detail=f"Invalid command: {cmd}")

    await _forward_command(cmd)

    await mission.broadcast('dashboard', {
        'type':    'cmd_sent',
        'command': cmd,
        'auto_mode': mission.auto_mode,
    })

    return {'sent': cmd, 'auto_mode': mission.auto_mode}


@app.post("/api/mission/start")
async def start_mission():
    mission.mission_active  = True
    mission.mission_start_t = time.time()
    mission.add_alert('info', 'Mission started via API')
    return {'status': 'started'}


@app.post("/api/mission/stop")
async def stop_mission():
    mission.mission_active = False
    await _forward_command('S')
    mission.add_alert('info', 'Mission stopped via API')
    return {'status': 'stopped'}


@app.get("/api/camera/stream")
async def camera_stream():
    """Proxy the MJPEG stream from Pi bridge."""
    async def generate():
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{PI_BRIDGE_URL}/camera.mjpeg",
                    timeout=aiohttp.ClientTimeout(total=None)
                ) as resp:
                    async for chunk in resp.content.iter_any():
                        yield chunk
            except Exception as e:
                log.warning(f"Camera stream error: {e}")

    return StreamingResponse(
        generate(),
        media_type='multipart/x-mixed-replace; boundary=frame',
        headers={'Access-Control-Allow-Origin': '*'},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "ts": time.time()}


# ─── Periodic broadcast for always-connected dashboards ──────────────────────

@app.on_event("startup")
async def start_periodic_broadcast():
    async def _broadcast_loop():
        while True:
            await asyncio.sleep(1)
            if mission.latest_telemetry:
                await mission.broadcast('dashboard', {
                    'type':   'heartbeat',
                    'status': {
                        'pi_connected':    mission.pi_connected,
                        'mission_active':  mission.mission_active,
                        'rover_state':     mission.rover_state,
                        'auto_mode':       mission.auto_mode,
                        'obstacle_active': mission.obstacle_active,
                        'victim_count':    mission.victim_count,
                        'server_ts':       time.time(),
                        'capabilities':    CAPABILITIES,
                    },
                })
    asyncio.create_task(_broadcast_loop())
