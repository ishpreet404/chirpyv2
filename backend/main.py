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
import math
import os
import random
import time
from collections import deque
from datetime import datetime
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import aiohttp

try:
    from dotenv import load_dotenv

    _env_path = os.path.join(os.path.dirname(__file__), "..", "localenv")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    else:
        load_dotenv()
except ImportError:
    pass

# ─── Configuration ───────────────────────────────────────────────────────────

PI_BRIDGE_URL    = os.getenv("PI_BRIDGE_URL", "http://raspberry-pi.local:8081")
PI_BRIDGE_WS     = os.getenv("PI_BRIDGE_WS", "ws://raspberry-pi.local:8081")
MAX_TELEMETRY_HISTORY = 2000     # packets kept in memory
MAX_ALERTS       = 200

FIRMWARE_PROFILE = "chirpy_v2_legacy"
SUPPORTED_COMMANDS = ("F", "B", "L", "R", "S")
SUPPORTED_MODES = ("square", "circle", "random")

WHEEL_VELOCITY_CMS = 20.0
PIVOT_RATE_DEGS = 286.4

MODE_PRESETS = {
    "square": {
        "side_cm": 60.0,
        "turn_deg": 90.0,
        "pause_s": 0.2,
    },
    "circle": {
        "radius_cm": 30.0,
        "step_deg": 10.0,
        "pause_s": 0.05,
    },
    "random": {
        "steps": 20,
        "pause_s": 0.2,
    },
}
CAPABILITIES = {
    "profile": FIRMWARE_PROFILE,
    "commands": list(SUPPORTED_COMMANDS),
    "modes": list(SUPPORTED_MODES),
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
        self.motion_active     = False
        self.motion_mode       : str | None = None
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

mode_task: asyncio.Task | None = None
mode_cancel: asyncio.Event | None = None


async def _sleep_with_cancel(seconds: float, cancel_event: asyncio.Event) -> bool:
    try:
        await asyncio.wait_for(cancel_event.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def _command_for_duration(cmd: str, duration_s: float, cancel_event: asyncio.Event) -> bool:
    await _forward_command(cmd)
    if await _sleep_with_cancel(duration_s, cancel_event):
        return True
    await _forward_command("S")
    return await _sleep_with_cancel(0.15, cancel_event)


async def _stop_motion_mode(reason: str = "stopped"):
    global mode_task, mode_cancel

    if mode_cancel:
        mode_cancel.set()

    if mode_task:
        try:
            await mode_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning(f"Motion mode error: {exc}")

    mode_task = None
    mode_cancel = None

    if mission.motion_active or mission.motion_mode:
        mission.motion_active = False
        mission.motion_mode = None
        mission.add_alert("info", f"Motion mode {reason}")
        await mission.broadcast("dashboard", {
            "type": "mode",
            "status": {
                "motion_active": False,
                "motion_mode": None,
            },
        })

    await _forward_command("S")


async def _run_motion_mode(mode: str, cancel_event: asyncio.Event):
    preset = MODE_PRESETS.get(mode, {})
    try:
        if mode == "square":
            side_cm = float(preset.get("side_cm", 60.0))
            turn_deg = float(preset.get("turn_deg", 90.0))
            pause_s = float(preset.get("pause_s", 0.2))
            forward_time = side_cm / WHEEL_VELOCITY_CMS
            turn_time = turn_deg / PIVOT_RATE_DEGS

            for _ in range(4):
                if await _command_for_duration("F", forward_time, cancel_event):
                    return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return
                if await _command_for_duration("R", turn_time, cancel_event):
                    return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return

        elif mode == "circle":
            radius_cm = float(preset.get("radius_cm", 30.0))
            step_deg = float(preset.get("step_deg", 10.0))
            pause_s = float(preset.get("pause_s", 0.05))
            steps = max(3, int(360.0 / step_deg))
            step_distance = 2.0 * math.pi * radius_cm * (step_deg / 360.0)
            forward_time = step_distance / WHEEL_VELOCITY_CMS
            turn_time = step_deg / PIVOT_RATE_DEGS

            for _ in range(steps):
                if await _command_for_duration("F", forward_time, cancel_event):
                    return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return
                if await _command_for_duration("R", turn_time, cancel_event):
                    return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return

        elif mode == "random":
            steps = int(preset.get("steps", 20))
            pause_s = float(preset.get("pause_s", 0.2))
            choices = ["F", "F", "F", "L", "R", "B"]

            for _ in range(steps):
                cmd = random.choice(choices)
                if cmd in ("L", "R"):
                    duration = random.uniform(0.2, 0.6)
                else:
                    duration = random.uniform(0.4, 1.2)

                if await _command_for_duration(cmd, duration, cancel_event):
                    return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return
    finally:
        mission.motion_active = False
        mission.motion_mode = None
        await mission.broadcast("dashboard", {
            "type": "mode",
            "status": {
                "motion_active": False,
                "motion_mode": None,
            },
        })
        await _forward_command("S")


async def _start_motion_mode(mode: str):
    global mode_task, mode_cancel

    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unknown mode: {mode}")

    await _stop_motion_mode("cancelled")

    mode_cancel = asyncio.Event()
    mission.motion_active = True
    mission.motion_mode = mode
    mission.add_alert("info", f"Motion mode started: {mode}")

    await mission.broadcast("dashboard", {
        "type": "mode",
        "status": {
            "motion_active": True,
            "motion_mode": mode,
        },
    })

    mode_task = asyncio.create_task(_run_motion_mode(mode, mode_cancel))

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
            'motion_active':   mission.motion_active,
            'motion_mode':     mission.motion_mode,
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
            elif msg.get('type') == 'mode':
                action = msg.get('action', 'start')
                mode = msg.get('mode', '')
                if action == 'stop':
                    await _stop_motion_mode("stopped")
                    await websocket.send_json({'type': 'mode', 'status': {'motion_active': False, 'motion_mode': None}})
                else:
                    try:
                        await _start_motion_mode(mode)
                        await websocket.send_json({'type': 'mode', 'status': {'motion_active': True, 'motion_mode': mode}})
                    except ValueError as exc:
                        await websocket.send_json({'type': 'mode_error', 'error': str(exc)})

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
        'motion_active':   mission.motion_active,
        'motion_mode':     mission.motion_mode,
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


@app.post("/api/mode")
async def post_mode(body: dict):
    action = body.get('action', 'start')
    mode = body.get('mode', '')

    if action == 'stop':
        await _stop_motion_mode("stopped")
        return {'motion_active': False, 'motion_mode': None}

    if mode not in SUPPORTED_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {mode}")

    await _start_motion_mode(mode)
    return {'motion_active': True, 'motion_mode': mode}


@app.post("/api/mission/start")
async def start_mission():
    mission.mission_active  = True
    mission.mission_start_t = time.time()
    mission.add_alert('info', 'Mission started via API')
    return {'status': 'started'}


@app.post("/api/mission/stop")
async def stop_mission():
    mission.mission_active = False
    await _stop_motion_mode("stopped")
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
                        'motion_active':   mission.motion_active,
                        'motion_mode':     mission.motion_mode,
                        'server_ts':       time.time(),
                        'capabilities':    CAPABILITIES,
                    },
                })
    asyncio.create_task(_broadcast_loop())
