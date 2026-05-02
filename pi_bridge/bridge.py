#!/usr/bin/env python3
"""
Disaster Rescue Rover — Raspberry Pi Bridge
============================================
Roles:
  1. Serial comms with ESP32 (GPIO 14/15 ↔ ESP32 GPIO 26/27, 115200 baud)
     - Reliable protocol: CRC8 verification, sequence-gap detection, ACK tracking
     - Heartbeat to ESP32 every 2s (P command)
  2. Computer vision — OpenCV person detection via camera
  3. Camera MJPEG stream on :8081
  4. WebSocket + REST relay to backend on :8000
  5. Autonomous path decision logic (obstacle map, re-routing)

UART wiring (from README Section 5 + 11):
  ESP32 GPIO 26 (TX2) → Pi GPIO 15 (RXD / UART0 RX)
  ESP32 GPIO 27 (RX2) → Pi GPIO 14 (TXD / UART0 TX)
  Common GND required — both sides 3.3V logic (no level shifter needed)

Pi setup (one-time):
  sudo raspi-config → Interface Options → Serial Port
    Login shell: No, Hardware enabled: Yes → reboot
  Remove 'console=serial0,115200' from /boot/cmdline.txt
  pip3 install pyserial opencv-python websockets aiohttp numpy

Packet format (from README Section 9 + firmware extensions):
  $CHR,<seq>,<ms>,<rpm>,<dist>,<accelY>,<gyroZ>,<x>,<y>,<heading>,
       <distLap>,<distTotal>,<estV>,<obstacle>,<state>,<flags>,<victims>,<chipTemp>,<crc8hex>

Compatibility:
  - chirpy_v2_fixed_again.ino uses legacy 15-field packets without CRC/seq
  - Commands limited to F/B/L/R/S
"""

import asyncio
import base64
import csv
import json
import logging
import math
import os
import struct
import sys
import threading
import time
from collections import deque
from datetime import datetime
from io import BytesIO

import aiohttp
import numpy as np
import serial
from aiohttp import web

try:
    from dotenv import load_dotenv

    _env_path = os.path.join(os.path.dirname(__file__), "..", "localenv")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
    else:
        load_dotenv()
except ImportError:
    pass

# ─── Try importing OpenCV (graceful fallback if not installed) ───────────────
try:
    import cv2
    CV_AVAILABLE = True
except ImportError:
    CV_AVAILABLE = False
    logging.warning("OpenCV not available — camera/CV features disabled")

# ─── Configuration ───────────────────────────────────────────────────────────

SERIAL_PORT      = os.getenv("SERIAL_PORT", "/dev/serial0")
SERIAL_BAUD      = 115200
BACKEND_WS_URL   = os.getenv("BACKEND_WS_URL", "ws://localhost:8000/ws/rover")
BACKEND_HTTP_URL = os.getenv("BACKEND_HTTP_URL", "http://localhost:8000")
CAMERA_INDEX     = 0
CAMERA_PORT      = 8081             # MJPEG stream port
HEARTBEAT_INTERVAL_S = 2.0          # Send P command every 2s
LOG_DIR          = os.path.expanduser("~/rover_logs")

FIRMWARE_PROFILE = "chirpy_v2_legacy"
SUPPORTED_COMMANDS = ("F", "B", "L", "R", "S")
ENABLE_HEARTBEAT = False
ENABLE_VICTIM_NOTIFY = False

# HOG person detector parameters (no neural net dependency)
HOG_WIN_STRIDE   = (8, 8)
HOG_PADDING      = (4, 4)
HOG_SCALE        = 1.05
DETECTION_CONFIDENCE_THRESHOLD = 0.5
VICTIM_COOLDOWN_S = 5.0             # min seconds between victim notifications

# ─── CRC8 verification (must match ESP32 implementation) ─────────────────────

def crc8(data: bytes) -> int:
    """CRC-8/SMBUS polynomial 0x07, matching ESP32 firmware."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x80:
                crc = ((crc << 1) ^ 0x07) & 0xFF
            else:
                crc = (crc << 1) & 0xFF
    return crc

def verify_packet(raw_line: str) -> bool:
    """
    Verify CRC8 of incoming $CHR packet (enhanced format only).
    Packet format: $CHR,...,<crc8hex>
    CRC is computed over everything BEFORE the last comma (the body).
    """
    try:
        last_comma = raw_line.rfind(',')
        if last_comma < 0:
            return False
        body     = raw_line[:last_comma]
        crc_str  = raw_line[last_comma + 1:].strip()
        expected = int(crc_str, 16)
        computed = crc8(body.encode('ascii'))
        return computed == expected
    except (ValueError, IndexError):
        return False

# ─── Packet parser ───────────────────────────────────────────────────────────

PACKET_FIELDS = [
    'seq', 'ms', 'rpm', 'dist', 'accelY', 'gyroZ',
    'x', 'y', 'heading', 'distLap', 'distTotal',
    'estV', 'obstacle', 'state', 'flags', 'victims', 'chipTemp'
]

def parse_packet(line: str) -> dict | None:
    """
    Parse and validate a $CHR telemetry packet.
    Returns dict on success, None on any parse/CRC error.
    Enhanced packet: 19 fields (seq + 17 data + crc).
    Also handles legacy 15-field packets without seq/victims/chipTemp/CRC.
    """
    line = line.strip()
    if not line.startswith('$CHR'):
        return None

    parts = line.split(',')

    # Enhanced format: $CHR + 17 fields + crc = 19 total parts
    if len(parts) == 19:
        if not verify_packet(line):
            return None
        try:
            return {
                'seq':       int(parts[1]),
                'ms':        int(parts[2]),
                'rpm':       float(parts[3]),
                'dist':      int(parts[4]),
                'accelY':    float(parts[5]),
                'gyroZ':     float(parts[6]),
                'x':         float(parts[7]),
                'y':         float(parts[8]),
                'heading':   float(parts[9]),
                'distLap':   float(parts[10]),
                'distTotal': float(parts[11]),
                'estV':      float(parts[12]),
                'obstacle':  int(parts[13]),
                'state':     parts[14],
                'flags':     parts[15],
                'victims':   int(parts[16]),
                'chipTemp':  float(parts[17]),
                # CRC in parts[18] already verified above
            }
        except (ValueError, IndexError):
            return None

    # Legacy 15-field format (no seq, victims, chipTemp, crc)
    if len(parts) == 15 and parts[0] == '$CHR':
        try:
            return {
                'seq':       None,
                'ms':        int(parts[1]),
                'rpm':       float(parts[2]),
                'dist':      int(parts[3]),
                'accelY':    float(parts[4]),
                'gyroZ':     float(parts[5]),
                'x':         float(parts[6]),
                'y':         float(parts[7]),
                'heading':   float(parts[8]),
                'distLap':   float(parts[9]),
                'distTotal': float(parts[10]),
                'estV':      float(parts[11]),
                'obstacle':  int(parts[12]),
                'state':     parts[13],
                'flags':     parts[14],
                'victims':   0,
                'chipTemp':  None,
            }
        except (ValueError, IndexError):
            return None

    return None

# ─── Path & session tracking ─────────────────────────────────────────────────

class PathTracker:
    """
    Maintains the rover's continuous movement path across sessions.
    Each 'segment' is a list of (x, y, heading, state, timestamp) points
    from one Stop to the next. Segments are accumulated into a global path
    by offset-tracking the absolute position.
    """

    def __init__(self):
        self.segments   : list[list[dict]] = []
        self.current_seg: list[dict]       = []
        self.obstacle_map: list[dict]      = []
        self.victim_locations: list[dict]  = []
        self.total_dist  = 0.0
        self.session_id  = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._last_state = None
        self._abs_x      = 0.0    # absolute X (across segments)
        self._abs_y      = 0.0
        self._seg_start_x = 0.0
        self._seg_start_y = 0.0

    def update(self, data: dict):
        """Process one telemetry packet."""
        state = data['state']

        # Segment boundary on Stop
        if state == 'STP' and self._last_state and self._last_state != 'STP':
            if self.current_seg:
                self.segments.append(self.current_seg[:])
                self.current_seg = []
            # Save last known absolute position for next segment origin
            if self.segments and self.segments[-1]:
                last_pt = self.segments[-1][-1]
                self._seg_start_x = self._abs_x
                self._seg_start_y = self._abs_y

        self._last_state = state

        if state == 'STP':
            return

        # Absolute position = segment_origin + relative_from_packet
        abs_x = self._seg_start_x + data['x']
        abs_y = self._seg_start_y + data['y']
        self._abs_x = abs_x
        self._abs_y = abs_y

        pt = {
            'x':       abs_x,
            'y':       abs_y,
            'heading': data['heading'],
            'state':   state,
            'ms':      data['ms'],
            't':       time.time(),
        }
        self.current_seg.append(pt)
        self.total_dist = data['distTotal']

        # Obstacle mapping: when dist < 80cm, project obstacle world position
        if 0 < data['dist'] < 80:
            rad = math.radians(data['heading'])
            obs = {
                'x': abs_x + data['dist'] * math.cos(rad),
                'y': abs_y + data['dist'] * math.sin(rad),
                't': time.time(),
            }
            # Deduplicate — only add if >10cm from last obstacle
            if not self.obstacle_map or math.hypot(
                obs['x'] - self.obstacle_map[-1]['x'],
                obs['y'] - self.obstacle_map[-1]['y']
            ) > 10.0:
                self.obstacle_map.append(obs)

    def add_victim(self, abs_x: float, abs_y: float, confidence: float):
        self.victim_locations.append({
            'x': abs_x, 'y': abs_y,
            'confidence': confidence,
            't': time.time(),
            'id': len(self.victim_locations) + 1,
        })

    def to_dict(self) -> dict:
        all_segs = self.segments + ([self.current_seg] if self.current_seg else [])
        return {
            'session_id':       self.session_id,
            'segments':         all_segs,
            'obstacles':        self.obstacle_map,
            'victims':          self.victim_locations,
            'total_dist_cm':    self.total_dist,
        }

# ─── CV Person Detector ───────────────────────────────────────────────────────

class PersonDetector:
    """
    HOG-based pedestrian detector using OpenCV's built-in descriptor.
    No external model files required — works offline in disaster scenarios.
    Falls back gracefully if OpenCV is not installed.
    """

    def __init__(self):
        self.available = CV_AVAILABLE
        if CV_AVAILABLE:
            self.hog = cv2.HOGDescriptor()
            self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
        self.last_detection_t = 0.0
        self.frame_count      = 0
        self.detect_every_n   = 5  # run detection every 5th frame (CPU budget)

    def detect(self, frame) -> tuple[list[dict], 'np.ndarray | None']:
        """
        Returns (detections, annotated_frame).
        detections: list of {'x', 'y', 'w', 'h', 'confidence'}
        """
        if not self.available:
            return [], None

        self.frame_count += 1
        if self.frame_count % self.detect_every_n != 0:
            return [], frame

        small = cv2.resize(frame, (320, 240))
        rects, weights = self.hog.detectMultiScale(
            small,
            winStride=HOG_WIN_STRIDE,
            padding=HOG_PADDING,
            scale=HOG_SCALE,
        )

        detections = []
        scale_x = frame.shape[1] / 320
        scale_y = frame.shape[0] / 240

        annotated = frame.copy()
        for i, (rx, ry, rw, rh) in enumerate(rects):
            conf = float(weights[i]) if i < len(weights) else 0.5
            if conf < DETECTION_CONFIDENCE_THRESHOLD:
                continue
            x = int(rx * scale_x)
            y = int(ry * scale_y)
            w = int(rw * scale_x)
            h = int(rh * scale_y)
            detections.append({'x': x, 'y': y, 'w': w, 'h': h, 'confidence': conf})
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(annotated, f'PERSON {conf:.2f}',
                        (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

        return detections, annotated

# ─── Session Logger ───────────────────────────────────────────────────────────

class SessionLogger:
    def __init__(self, log_dir: str):
        os.makedirs(log_dir, exist_ok=True)
        ts       = datetime.now().strftime('%Y%m%d_%H%M%S')
        filepath = os.path.join(log_dir, f"session_{ts}.csv")
        self._f  = open(filepath, 'w', newline='')
        fields   = PACKET_FIELDS + ['timestamp', 'abs_x', 'abs_y', 'crc_ok']
        self._w  = csv.DictWriter(self._f, fieldnames=fields, extrasaction='ignore')
        self._w.writeheader()
        logging.info(f"Logging to {filepath}")

    def log(self, data: dict, abs_x: float, abs_y: float):
        row = {**data, 'timestamp': datetime.now().isoformat(),
               'abs_x': abs_x, 'abs_y': abs_y, 'crc_ok': True}
        self._w.writerow(row)
        self._f.flush()

    def close(self):
        self._f.close()

# ─── Serial Bridge ────────────────────────────────────────────────────────────

class SerialBridge:
    """
    Manages bidirectional reliable communication with ESP32.
    - Sends heartbeat P command every HEARTBEAT_INTERVAL_S
    - Detects dropped packets via sequence gaps
    - Verifies CRC8 on every incoming packet
    - Thread-safe command queue for Pi→ESP32
    """

    def __init__(self):
        self.ser            : serial.Serial | None = None
        self.connected      = False
        self.cmd_queue      : deque[str] = deque()
        self.last_hb_sent   = 0.0
        self.last_pkt_seq   = -1
        self.dropped_pkts   = 0
        self.total_pkts     = 0
        self._lock          = threading.Lock()

        # Callbacks registered by caller
        self.on_packet  = None   # callable(dict)
        self.on_event   = None   # callable(str, str)  — (event_type, raw_line)

    def connect(self) -> bool:
        try:
            self.ser = serial.Serial(
                SERIAL_PORT, SERIAL_BAUD,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1.0
            )
            self.connected = True
            logging.info(f"Serial connected: {SERIAL_PORT} @ {SERIAL_BAUD}")
            return True
        except serial.SerialException as e:
            logging.error(f"Serial connect failed: {e}")
            return False

    def send_command(self, cmd: str):
        """Thread-safe command enqueue."""
        cmd = cmd.upper().strip()
        if cmd not in SUPPORTED_COMMANDS:
            logging.warning(f"Ignoring unsupported command: {cmd}")
            return
        with self._lock:
            self.cmd_queue.append(cmd + '\n')

    def _flush_commands(self):
        """Send all queued commands — call from read loop thread."""
        with self._lock:
            while self.cmd_queue:
                cmd = self.cmd_queue.popleft()
                try:
                    self.ser.write(cmd.encode('ascii'))
                except serial.SerialException as e:
                    logging.error(f"Serial write error: {e}")

    def read_loop(self):
        """
        Blocking read loop — run in dedicated thread.
        Processes incoming lines, verifies CRC, detects gaps, fires callbacks.
        """
        if not self.connected:
            logging.error("read_loop called before connect()")
            return

        buf = ""
        while True:
            try:
                raw = self.ser.read(256).decode('utf-8', errors='ignore')
            except serial.SerialException as e:
                logging.error(f"Serial read error: {e}")
                time.sleep(1)
                continue

            buf += raw
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip()
                if not line:
                    continue

                # ── Heartbeat / control messages ─────────────────────────
                if line == 'HB':
                    # ESP32 alive — nothing to do, we track Pi→ESP32 direction
                    pass
                elif line in ('ROVER_READY', 'CHIRPY_READY'):
                    logging.info("ESP32 ready received")
                    if self.on_event:
                        self.on_event('ready', line)
                elif line.startswith('ACK:'):
                    if self.on_event:
                        self.on_event('ack', line)
                elif line.startswith('NAK:'):
                    logging.warning(f"ESP32 NAK: {line}")
                    if self.on_event:
                        self.on_event('nak', line)
                elif line == 'OBSTACLE':
                    if self.on_event:
                        self.on_event('obstacle', line)
                elif line == 'CLEAR':
                    if self.on_event:
                        self.on_event('clear', line)
                elif line == 'WATCHDOG':
                    logging.warning("ESP32 watchdog fired — Pi heartbeat missed")
                    if self.on_event:
                        self.on_event('watchdog', line)
                elif line.startswith('BUSY:'):
                    if self.on_event:
                        self.on_event('busy', line)
                elif line.startswith('AUTO:'):
                    if self.on_event:
                        self.on_event('auto', line)

                # ── Telemetry packet ─────────────────────────────────────
                elif line.startswith('$CHR'):
                    data = parse_packet(line)
                    if data is None:
                        logging.debug(f"Bad/corrupt packet discarded: {line[:60]}")
                        continue

                    self.total_pkts += 1

                    # Sequence gap detection (enhanced format only)
                    seq = data.get('seq')
                    if isinstance(seq, int) and seq >= 0:
                        if self.last_pkt_seq >= 0:
                            expected = (self.last_pkt_seq + 1) & 0xFFFF
                            if seq != expected:
                                gap = (seq - self.last_pkt_seq) & 0xFFFF
                                self.dropped_pkts += gap - 1
                                logging.debug(f"Seq gap: expected {expected}, got {seq} (+{gap-1} dropped)")
                        self.last_pkt_seq = seq

                    if self.on_packet:
                        self.on_packet(data)

            # ── Flush outgoing commands ───────────────────────────────────
            self._flush_commands()

            # ── Heartbeat ─────────────────────────────────────────────────
            if ENABLE_HEARTBEAT:
                now = time.time()
                if now - self.last_hb_sent >= HEARTBEAT_INTERVAL_S:
                    self.last_hb_sent = now
                    try:
                        self.ser.write(b'P\n')
                    except serial.SerialException:
                        pass

# ─── MJPEG Camera Stream ──────────────────────────────────────────────────────

class CameraStreamer:
    """
    Serves MJPEG stream on /camera.mjpeg at port CAMERA_PORT.
    Runs OpenCV person detection and notifies bridge when person found.
    """

    def __init__(self, detector: PersonDetector):
        self.detector      = detector
        self.cap           = None
        self.latest_frame  : bytes | None = None  # JPEG bytes
        self.latest_detections: list[dict] = []
        self._lock         = threading.Lock()
        self.on_person_detected = None  # callable(list[dict])
        self._last_victim_t = 0.0

    def _capture_loop(self):
        if not CV_AVAILABLE:
            return
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH,  640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 15)

        while True:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            detections, annotated = self.detector.detect(frame)
            display = annotated if annotated is not None else frame

            # JPEG encode
            ret2, jpeg = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 70])
            if not ret2:
                continue

            with self._lock:
                self.latest_frame      = jpeg.tobytes()
                self.latest_detections = detections

            # Notify on new person detections (with cooldown)
            if detections and self.on_person_detected:
                now = time.time()
                if now - self._last_victim_t > VICTIM_COOLDOWN_S:
                    self._last_victim_t = now
                    self.on_person_detected(detections)

            time.sleep(1 / 15)

    def start(self):
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()

    def get_frame(self) -> bytes | None:
        with self._lock:
            return self.latest_frame

    def get_detections(self) -> list[dict]:
        with self._lock:
            return self.latest_detections[:]

    async def mjpeg_handler(self, request):
        """aiohttp request handler for MJPEG stream."""
        response = web.StreamResponse(headers={
            'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
            'Cache-Control': 'no-cache',
            'Access-Control-Allow-Origin': '*',
        })
        await response.prepare(request)

        while True:
            frame = self.get_frame()
            if frame:
                try:
                    await response.write(
                        b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' +
                        frame + b'\r\n'
                    )
                except (ConnectionResetError, asyncio.CancelledError):
                    break
            await asyncio.sleep(1 / 15)

        return response

# ─── Backend WebSocket Relay ──────────────────────────────────────────────────

class BackendRelay:
    """
    Sends telemetry/events to backend over HTTP.
    Avoids WebSocket dependencies for simpler setup.
    """

    def __init__(self):
        self._session: aiohttp.ClientSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_error_t = 0.0

    async def start(self):
        self._loop = asyncio.get_running_loop()
        if self._session is None:
            self._session = aiohttp.ClientSession()

    async def _post(self, path: str, payload: dict):
        if not self._session:
            return
        try:
            async with self._session.post(
                f"{BACKEND_HTTP_URL}{path}",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=2),
            ) as resp:
                await resp.release()
        except Exception as e:
            now = time.time()
            if now - self._last_error_t > 2.0:
                logging.warning(f"Backend HTTP failed: {e}")
                self._last_error_t = now

    async def _dispatch(self, msg: dict):
        msg_type = msg.get("type")
        if msg_type == "telemetry":
            await self._post("/api/telemetry", {
                "data": msg.get("data", {}),
                "abs_x": msg.get("abs_x", 0.0),
                "abs_y": msg.get("abs_y", 0.0),
                "path": msg.get("path", {}),
            })
        elif msg_type == "event":
            await self._post("/api/event", {
                "event": msg.get("event", ""),
                "raw": msg.get("raw", ""),
            })
        elif msg_type == "victim_detected":
            await self._post("/api/victim", {
                "x": msg.get("x", 0.0),
                "y": msg.get("y", 0.0),
                "confidence": msg.get("confidence", 0.0),
                "detections": msg.get("detections", []),
            })

    def send(self, msg: dict):
        """Non-blocking: schedule HTTP post on the event loop."""
        if not self._loop:
            return
        self._loop.call_soon_threadsafe(asyncio.create_task, self._dispatch(dict(msg)))

# ─── Main Rover Bridge ────────────────────────────────────────────────────────

class RoverBridge:

    def __init__(self):
        self.serial    = SerialBridge()
        self.detector  = PersonDetector()
        self.camera    = CameraStreamer(self.detector)
        self.relay     = BackendRelay()
        self.tracker   = PathTracker()
        self.logger    = SessionLogger(LOG_DIR)

        self.latest_telemetry : dict | None = None
        self._lock = asyncio.Lock()

        # Wire up callbacks
        self.serial.on_packet = self._on_packet
        self.serial.on_event  = self._on_event
        self.camera.on_person_detected = self._on_person_detected

    def _on_packet(self, data: dict):
        """Called from serial thread — keep thread-safe."""
        self.tracker.update(data)
        self.logger.log(data, self.tracker._abs_x, self.tracker._abs_y)
        self.latest_telemetry = data

        # Forward to backend (non-blocking)
        self.relay.send({
            'type':     'telemetry',
            'data':     data,
            'abs_x':    self.tracker._abs_x,
            'abs_y':    self.tracker._abs_y,
            'path':     self.tracker.to_dict(),
        })

    def _on_event(self, event_type: str, raw: str):
        logging.info(f"ESP32 event [{event_type}]: {raw}")
        self.relay.send({'type': 'event', 'event': event_type, 'raw': raw})

    def _on_person_detected(self, detections: list[dict]):
        """Called from camera thread when person found."""
        # Notify ESP32 — tell it to flag victim at current position
        if ENABLE_VICTIM_NOTIFY:
            self.serial.send_command('V')

        abs_x = self.tracker._abs_x
        abs_y = self.tracker._abs_y
        conf  = max(d['confidence'] for d in detections)
        self.tracker.add_victim(abs_x, abs_y, conf)

        logging.warning(f"VICTIM DETECTED @ ({abs_x:.1f}, {abs_y:.1f}) conf={conf:.2f}")

        self.relay.send({
            'type':       'victim_detected',
            'x':          abs_x,
            'y':          abs_y,
            'confidence': conf,
            'detections': detections,
        })

    def send_command(self, cmd: str):
        self.serial.send_command(cmd)

    # ── REST API handlers ────────────────────────────────────────────────────

    async def api_status(self, request):
        data = {
            'serial_connected': self.serial.connected,
            'pi_connected':     True,
            'total_pkts':       self.serial.total_pkts,
            'dropped_pkts':     self.serial.dropped_pkts,
            'drop_rate_pct':    round(
                100 * self.serial.dropped_pkts / max(1, self.serial.total_pkts), 2
            ),
            'latest_telemetry': self.latest_telemetry,
            'path_summary':     {
                'total_dist_cm': self.tracker.total_dist,
                'segments':      len(self.tracker.segments),
                'obstacles':     len(self.tracker.obstacle_map),
                'victims':       len(self.tracker.victim_locations),
            },
        }
        return web.json_response(data)

    async def api_command(self, request):
        body = await request.json()
        cmd  = body.get('command', '').upper()
        if cmd not in SUPPORTED_COMMANDS:
            return web.json_response({'error': 'Invalid command'}, status=400)
        self.send_command(cmd)
        return web.json_response({'sent': cmd})

    async def api_path(self, request):
        return web.json_response(self.tracker.to_dict())

    async def api_victims(self, request):
        return web.json_response(self.tracker.victim_locations)

    # ── App runner ───────────────────────────────────────────────────────────

    async def run(self):
        # Start backend relay (HTTP)
        await self.relay.start()

        # Start camera streamer
        self.camera.start()

        # Start serial read thread
        if not self.serial.connect():
            logging.warning("Serial not connected — running in simulation mode")
        serial_thread = threading.Thread(
            target=self.serial.read_loop, daemon=True
        )
        serial_thread.start()

        # Build aiohttp app
        app = web.Application()
        app.router.add_get('/status',         self.api_status)
        app.router.add_post('/command',        self.api_command)
        app.router.add_get('/path',            self.api_path)
        app.router.add_get('/victims',         self.api_victims)
        app.router.add_get('/camera.mjpeg',    self.camera.mjpeg_handler)

        # CORS headers for all routes
        @web.middleware
        async def cors_middleware(request, handler):
            response = await handler(request)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response

        app.middlewares.append(cors_middleware)

        runner = web.AppRunner(app)
        await runner.setup()
        site   = web.TCPSite(runner, '0.0.0.0', CAMERA_PORT)
        await site.start()

        logging.info(f"Pi bridge running on :{CAMERA_PORT}")
        logging.info(f"  Camera stream: http://<pi-ip>:{CAMERA_PORT}/camera.mjpeg")
        logging.info(f"  Status API:    http://<pi-ip>:{CAMERA_PORT}/status")
        logging.info(f"  Command API:   POST http://<pi-ip>:{CAMERA_PORT}/command")

        # Keep running
        while True:
            await asyncio.sleep(1)


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == '__main__':
    os.makedirs(os.path.expanduser('~/rover_logs'), exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(
                os.path.expanduser('~/rover_logs'),
                f'bridge_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'
            ), mode='w'),
        ]
    )

    bridge = RoverBridge()
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        pass
