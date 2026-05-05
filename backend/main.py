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

# Custom fallback localenv parser in case python-dotenv is missing
_custom_env_path = os.path.join(os.path.dirname(__file__), "..", "localenv")
if os.path.exists(_custom_env_path):
    with open(_custom_env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"\'')
                if k not in os.environ:
                    os.environ[k] = v

# ─── Configuration ───────────────────────────────────────────────────────────

PI_BRIDGE_URL    = os.getenv("PI_BRIDGE_URL", "http://192.168.1.11:8081").strip('"\'').rstrip("/")
PI_BRIDGE_WS     = os.getenv("PI_BRIDGE_WS", "ws://192.168.1.11:8081")
MAX_TELEMETRY_HISTORY = 2000     # packets kept in memory
MAX_ALERTS       = 200
ZONE_SIZE_CM = 100
ZONE_BLOCKED_OBS_MIN = 1
ZONE_HIGH_RISK_OBS_MIN = 2

FIRMWARE_PROFILE = "chirpy_v2_legacy"
SUPPORTED_COMMANDS = ("F", "B", "L", "R", "S")
SUPPORTED_MODES = (
    "square",
    "circle",
    "random",
    "follow-path",
    "search-grid",
    "return-to-home",
    "hold-position",
    "emergency-stop",
)

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
    "follow-path": {
        "pause_s": 0.1,
    },
    "search-grid": {
        "cell_cm": 60.0,
        "rows": 4,
        "cols": 4,
        "pause_s": 0.1,
    },
    "return-to-home": {
        "pause_s": 0.1,
    },
    "hold-position": {
        "pause_s": 0.1,
    },
    "emergency-stop": {
        "pause_s": 0.1,
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
            'route': {
                'waypoints': [],
                'status': 'idle',
                'paused': False,
                'active_index': 0,
                'name': None,
            },
            'annotations': [],
        }
        self.survivors         : list[dict]  = []  # List of {id, timestamp, responses, transcript}
        self.alerts            : deque[dict] = deque(maxlen=MAX_ALERTS)
        self.mission_active    = False
        self.mission_start_t   : float | None = None
        self.pi_connected      = False
        self.pi_last_seen      = 0.0
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
        self.pi_last_seen = time.time()
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

        self.update_zones()

    def update_path(self, path_data: dict):
        if not isinstance(path_data, dict):
            return

        merged = dict(self.path_data)
        merged.update({
            key: value
            for key, value in path_data.items()
            if key not in {"route", "annotations"}
        })

        route = merged.get('route') if isinstance(merged.get('route'), dict) else {}
        incoming_route = path_data.get('route') if isinstance(path_data.get('route'), dict) else {}
        merged['route'] = {
            'waypoints': incoming_route.get('waypoints', route.get('waypoints', [])),
            'status': incoming_route.get('status', route.get('status', 'idle')),
            'paused': bool(incoming_route.get('paused', route.get('paused', False))),
            'active_index': int(incoming_route.get('active_index', route.get('active_index', 0)) or 0),
            'name': incoming_route.get('name', route.get('name')),
        }

        annotations = path_data.get('annotations')
        if isinstance(annotations, list):
            merged['annotations'] = annotations
        elif not isinstance(merged.get('annotations'), list):
            merged['annotations'] = []

        self.path_data = merged

        self.update_zones()

    def update_route(self, route_data: dict):
        if not isinstance(route_data, dict):
            return

        current = self.path_data.get('route') if isinstance(self.path_data.get('route'), dict) else {}
        waypoints = route_data.get('waypoints')
        if not isinstance(waypoints, list):
            waypoints = current.get('waypoints', [])

        self.path_data['route'] = {
            'waypoints': waypoints,
            'status': route_data.get('status', current.get('status', 'idle')),
            'paused': bool(route_data.get('paused', current.get('paused', False))),
            'active_index': int(route_data.get('active_index', current.get('active_index', 0)) or 0),
            'name': route_data.get('name', current.get('name')),
        }

    def add_annotation(self, annotation: dict):
        if not isinstance(annotation, dict):
            return None

        annotations = self.path_data.setdefault('annotations', [])
        if not isinstance(annotations, list):
            annotations = []
            self.path_data['annotations'] = annotations

        entry = {
            'id': len(annotations) + 1,
            'kind': annotation.get('kind', 'note'),
            'text': annotation.get('text', ''),
            'x': annotation.get('x'),
            'y': annotation.get('y'),
            'heading': annotation.get('heading'),
            'timestamp': datetime.now().isoformat(),
            'meta': annotation.get('meta', {}),
        }
        annotations.append(entry)
        return entry

    def add_victim(self, x: float, y: float, confidence: float):
        self.victim_count += 1
        alert = self.add_alert(
            'critical',
            f"Victim #{self.victim_count} detected at ({x:.1f}, {y:.1f}) — conf {confidence:.0%}",
            {'x': x, 'y': y, 'confidence': confidence, 'victim_id': self.victim_count}
        )
        return alert

    def update_zones(self):
        """Compute zone intelligence from telemetry, obstacles, and victims."""
        size = ZONE_SIZE_CM

        def zone_key(x: float, y: float) -> tuple[int, int]:
            return (math.floor(x / size), math.floor(y / size))

        visited_counts: dict[tuple[int, int], int] = {}
        last_ts: dict[tuple[int, int], float] = {}
        for item in self.telemetry_history:
            x = item.get('abs_x')
            y = item.get('abs_y')
            if x is None or y is None:
                continue
            key = zone_key(x, y)
            visited_counts[key] = visited_counts.get(key, 0) + 1
            ts = item.get('server_ts') or time.time()
            last_ts[key] = max(last_ts.get(key, 0.0), ts)

        obstacle_counts: dict[tuple[int, int], int] = {}
        for obs in self.path_data.get('obstacles', []) or []:
            ox = obs.get('x')
            oy = obs.get('y')
            if ox is None or oy is None:
                continue
            key = zone_key(ox, oy)
            obstacle_counts[key] = obstacle_counts.get(key, 0) + 1

        victim_counts: dict[tuple[int, int], int] = {}
        for victim in self.path_data.get('victims', []) or []:
            vx = victim.get('x')
            vy = victim.get('y')
            if vx is None or vy is None:
                continue
            key = zone_key(vx, vy)
            victim_counts[key] = victim_counts.get(key, 0) + 1

        visited_keys = set(visited_counts.keys())
        blocked_keys = {k for k, c in obstacle_counts.items() if c >= ZONE_BLOCKED_OBS_MIN}
        high_risk_keys = {k for k, count in victim_counts.items() if count > 0}

        current = self.latest_telemetry or {}
        cur_x = current.get('abs_x')
        cur_y = current.get('abs_y')
        current_zone = zone_key(cur_x, cur_y) if cur_x is not None and cur_y is not None else None

        def neighbors(key: tuple[int, int]) -> list[tuple[int, int]]:
            return [
                (key[0] + 1, key[1]),
                (key[0] - 1, key[1]),
                (key[0], key[1] + 1),
                (key[0], key[1] - 1),
            ]

        frontier = set()
        for key in visited_keys:
            for nb in neighbors(key):
                if nb not in visited_keys and nb not in blocked_keys:
                    frontier.add(nb)

        suggested = None
        if current_zone and frontier:
            queue = deque([current_zone])
            seen = {current_zone}
            while queue:
                node = queue.popleft()
                if node in frontier:
                    suggested = node
                    break
                for nb in neighbors(node):
                    if nb in seen or nb in blocked_keys:
                        continue
                    seen.add(nb)
                    queue.append(nb)

        zones = {
            'size_cm': size,
            'current': {'x': current_zone[0], 'y': current_zone[1]} if current_zone else None,
            'visited': [
                {'x': k[0], 'y': k[1], 'count': visited_counts[k], 'last_ts': last_ts.get(k)}
                for k in visited_counts
            ],
            'blocked': [
                {'x': k[0], 'y': k[1], 'count': obstacle_counts.get(k, 0)}
                for k in blocked_keys
            ],
            'high_risk': [
                {
                    'x': k[0],
                    'y': k[1],
                    'obstacles': obstacle_counts.get(k, 0),
                    'victims': victim_counts.get(k, 0),
                }
                for k in high_risk_keys
            ],
            'frontier': [{'x': k[0], 'y': k[1]} for k in frontier],
            'suggested_next': {'x': suggested[0], 'y': suggested[1]} if suggested else None,
        }

        self.path_data['zones'] = zones


mission = MissionState()


def _pi_connected() -> bool:
    if mission.pi_last_seen <= 0:
        return False
    return (time.time() - mission.pi_last_seen) < 5.0


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
            # Break long side movements into small chunks so operation
            # remains stable in tight/obstructed spaces.
            side_cm = float(preset.get("side_cm", 60.0))
            turn_deg = float(preset.get("turn_deg", 90.0))
            pause_s = float(preset.get("pause_s", 0.2))
            chunk_cm = float(preset.get("chunk_cm", 10.0))

            # Number of forward chunks per side
            chunks = max(1, int(math.ceil(side_cm / chunk_cm)))
            single_dist = side_cm / chunks
            forward_time = single_dist / WHEEL_VELOCITY_CMS
            turn_time = turn_deg / PIVOT_RATE_DEGS

            for _ in range(4):
                for _c in range(chunks):
                    if await _command_for_duration("F", forward_time, cancel_event):
                        return
                    if await _sleep_with_cancel(0.05, cancel_event):
                        return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return
                if await _command_for_duration("R", turn_time, cancel_event):
                    return
                if await _sleep_with_cancel(pause_s, cancel_event):
                    return

        elif mode == "circle":
            # Use step_deg slices to approximate a circle. Break each slice
            # into small forward chunks for tight-area operation.
            radius_cm = float(preset.get("radius_cm", 30.0))
            step_deg = float(preset.get("step_deg", 10.0))
            pause_s = float(preset.get("pause_s", 0.05))
            chunk_cm = float(preset.get("chunk_cm", 5.0))

            steps = max(3, int(360.0 / step_deg))
            step_distance = 2.0 * math.pi * radius_cm * (step_deg / 360.0)
            # Break each step into smaller forward chunks
            subchunks = max(1, int(math.ceil(step_distance / chunk_cm)))
            single_dist = step_distance / subchunks
            forward_time = single_dist / WHEEL_VELOCITY_CMS
            turn_time = step_deg / PIVOT_RATE_DEGS

            for _ in range(steps):
                for _c in range(subchunks):
                    if await _command_for_duration("F", forward_time, cancel_event):
                        return
                    if await _sleep_with_cancel(0.03, cancel_event):
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
        elif mode in {"follow-path", "search-grid"}:
            route = mission.path_data.get("route") if isinstance(mission.path_data.get("route"), dict) else {}
            waypoints = route.get("waypoints", []) if isinstance(route.get("waypoints"), list) else []
            mission.path_data['route'] = {
                **route,
                'status': 'active',
                'paused': False,
                'active_index': 0,
            }
            mission.add_alert("info", f"{mode} mode armed with {len(waypoints)} waypoints")
            await mission.broadcast("dashboard", {
                "type": "route",
                "route": mission.path_data['route'],
            })
            while not cancel_event.is_set():
                await _sleep_with_cancel(0.5, cancel_event)
                if mode == "search-grid" and not waypoints:
                    break
                if mode == "follow-path" and not waypoints:
                    break
                break

        elif mode == "return-to-home":
            mission.path_data['route'] = {
                **(mission.path_data.get('route') if isinstance(mission.path_data.get('route'), dict) else {}),
                'status': 'returning-home',
                'paused': False,
            }
            mission.add_alert("info", "Return-to-home requested")
            await mission.broadcast("dashboard", {
                "type": "route",
                "route": mission.path_data['route'],
            })

        elif mode == "hold-position":
            mission.path_data['route'] = {
                **(mission.path_data.get('route') if isinstance(mission.path_data.get('route'), dict) else {}),
                'status': 'holding-position',
                'paused': True,
            }
            await _forward_command("S")
            mission.add_alert("info", "Hold-position engaged")
            await mission.broadcast("dashboard", {
                "type": "route",
                "route": mission.path_data['route'],
            })

        elif mode == "emergency-stop":
            mission.path_data['route'] = {
                **(mission.path_data.get('route') if isinstance(mission.path_data.get('route'), dict) else {}),
                'status': 'emergency-stop',
                'paused': True,
            }
            await _forward_command("S")
            mission.add_alert("critical", "Emergency stop engaged")
            await mission.broadcast("dashboard", {
                "type": "route",
                "route": mission.path_data['route'],
            })
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
                mission.pi_last_seen = time.time()

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
                mission.pi_last_seen = time.time()
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
            'pi_connected':    _pi_connected(),
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
    # Log the attempt
    log.info(f"Forwarding command '{cmd}' to Pi Bridge at {PI_BRIDGE_URL}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{PI_BRIDGE_URL}/command",
                json={'command': cmd},
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                if resp.status == 200:
                    log.info(f"Command '{cmd}' accepted by Pi Bridge")
                else:
                    text = await resp.text()
                    log.warning(f"Pi Bridge returned status {resp.status} for command '{cmd}': {text}")
    except Exception as e:
        log.warning(f"Command forward failed for '{cmd}': {e}")

# ─── REST API ─────────────────────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    mission_duration = None
    if mission.mission_start_t:
        mission_duration = round(time.time() - mission.mission_start_t, 1)

    return {
        'pi_connected':    _pi_connected(),
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


@app.post("/api/telemetry")
async def post_telemetry(body: dict):
    data  = body.get('data', {})
    abs_x = body.get('abs_x', 0.0)
    abs_y = body.get('abs_y', 0.0)
    path  = body.get('path', {})

    mission.update_from_telemetry(data, abs_x, abs_y)
    if path:
        mission.update_path(path)

    await mission.broadcast('dashboard', {
        'type':     'telemetry',
        'telemetry': mission.latest_telemetry,
        'path':     mission.path_data,
    })

    return {'ok': True}


@app.post("/api/event")
async def post_event(body: dict):
    event = body.get('event', '')
    raw   = body.get('raw', '')
    mission.pi_last_seen = time.time()

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

    return {'ok': True}


@app.post("/api/victim")
async def post_victim(body: dict):
    x    = body.get('x', 0.0)
    y    = body.get('y', 0.0)
    conf = body.get('confidence', 0.0)
    mission.pi_last_seen = time.time()
    alert = mission.add_victim(x, y, conf)

    await mission.broadcast('dashboard', {
        'type':    'victim',
        'x':       x,
        'y':       y,
        'confidence': conf,
        'count':   mission.victim_count,
        'alert':   alert,
    })

    return {'ok': True}


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


@app.get("/api/route")
async def get_route():
    route = mission.path_data.get('route') if isinstance(mission.path_data.get('route'), dict) else {}
    return {
        'route': route,
        'annotations': mission.path_data.get('annotations', []),
    }


@app.post("/api/route")
async def post_route(body: dict):
    action = body.get('action', 'set')
    route = body.get('route', {})

    if action == 'clear':
        mission.update_route({'waypoints': [], 'status': 'idle', 'paused': False, 'active_index': 0, 'name': None})
        mission.add_alert('info', 'Route cleared')
    else:
        mission.update_route(route)
        if action == 'set':
            mission.add_alert('info', f"Route loaded with {len(mission.path_data['route'].get('waypoints', []))} waypoints")
        elif action == 'start':
            mission.update_route({**route, 'status': 'active', 'paused': False, 'active_index': 0})
            mission.motion_active = True
            mission.motion_mode = 'follow-path'
            mission.add_alert('info', 'Route patrol started')
        elif action == 'pause':
            mission.update_route({**route, 'status': 'paused', 'paused': True})
            await _forward_command('S')
        elif action == 'resume':
            mission.update_route({**route, 'status': 'active', 'paused': False})
        elif action == 'skip':
            current = mission.path_data.get('route') if isinstance(mission.path_data.get('route'), dict) else {}
            active_index = int(current.get('active_index', 0) or 0) + 1
            mission.update_route({**route, 'status': 'active', 'paused': False, 'active_index': active_index})
        elif action == 'stop':
            mission.update_route({**route, 'status': 'idle', 'paused': False})
            mission.motion_active = False
            mission.motion_mode = None
            await _forward_command('S')
        else:
            raise HTTPException(status_code=400, detail=f'Invalid route action: {action}')

    await mission.broadcast('dashboard', {
        'type': 'route',
        'route': mission.path_data.get('route', {}),
        'annotations': mission.path_data.get('annotations', []),
    })
    return {'ok': True, 'route': mission.path_data.get('route', {}), 'annotations': mission.path_data.get('annotations', [])}


@app.post("/api/annotation")
async def post_annotation(body: dict):
    annotation = mission.add_annotation(body)
    if not annotation:
        raise HTTPException(status_code=400, detail='Invalid annotation')

    await mission.broadcast('dashboard', {
        'type': 'annotation',
        'annotation': annotation,
        'annotations': mission.path_data.get('annotations', []),
    })
    return {'ok': True, 'annotation': annotation}


# ─── Survivor Interaction APIs ────────────────────────────────────────────────

@app.get("/api/survivors")
async def get_survivors():
    return {"ok": True, "survivors": mission.survivors}


@app.post("/api/survivors/interaction")
async def post_interaction(body: dict):
    """
    Called by Pi when it detects a survivor or receives input.
    Can trigger LLM logic via OpenRouter if transcript is provided.
    """
    transcript = body.get("transcript", "")
    responses = body.get("responses", {})  # e.g., {"can_move": false, "conscious": true}
    
    # Store interaction
    entry = {
        "id": len(mission.survivors) + 1,
        "timestamp": datetime.now().isoformat(),
        "transcript": transcript,
        "responses": responses,
        "location": mission.latest_telemetry.get("abs_coords") if mission.latest_telemetry else None
    }
    mission.survivors.append(entry)
    mission.add_alert("info", f"Survivor interaction logged: {transcript[:30]}...")

    # If transcript contains "help" or "save", or if it's a generic query, we can use LLM
    llm_reply = None
    if transcript and os.getenv("OPENROUTER_API_KEY"):
        llm_reply = await get_llm_response(transcript)
    
    # Broadcast to dashboard
    await mission.broadcast("dashboard", {
        "type": "survivor_interaction",
        "data": entry,
        "llm_reply": llm_reply
    })

    return {"ok": True, "llm_reply": llm_reply, "entry": entry}


async def get_llm_response(user_text: str):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return "I am a rescue robot. Help is on the way."

    # Robot-specific strict prompt
    system_prompt = (
        "You are ChirpyV2, a specialized Disaster Rescue Rover. "
        "Your responses MUST be strictly bounded by your physical capabilities: "
        "1. You can navigate terrain and identify survivors. "
        "2. You can relay messages and GPS coordinates to human rescue teams. "
        "3. You can provide basic status updates (help is coming, teams are notified). "
        "NEVER claim you can perform medical procedures, move heavy debris, or provide food/water directly. "
        "Always introduce yourself as 'ChirpyV2, the rescue rover' if the conversation is starting. "
        "Keep responses under 3 sentences. Be calm and reassuming."
    )

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/chirpy-v2", # Recommended by OpenRouter
        "X-Title": "ChirpyV2 Rescue Rover"
    }
    payload = {
        "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text}
        ],
        "include_reasoning": True
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    choice = data['choices'][0]['message']
                    
                    # Log reasoning if available (sent by some models in 'reasoning' or 'content')
                    reasoning = choice.get("reasoning")
                    if reasoning:
                        log.info(f"Robot Reasoning: {reasoning}")
                        
                    usage = data.get("usage", {})
                    if "reasoning_tokens" in usage:
                        log.info(f"Reasoning tokens used: {usage['reasoning_tokens']}")

                    return choice['content']
    except Exception as e:
        log.error(f"LLM Error: {e}")
    
    return "I have recorded your status. Remain calm."


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
            # Always send heartbeat regardless of telemetry
            await mission.broadcast('dashboard', {
                'type':   'heartbeat',
                'status': {
                    'pi_connected':    _pi_connected(),
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
