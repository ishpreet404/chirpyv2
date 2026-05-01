import os
import time
import uuid

import serial

from api_client import BackendClient
from drift_correction import DriftCorrector
from path_tracker import PathTracker
from vision import VisionSystem, start_mjpeg_server


ESP32_PORT = os.getenv("ESP32_PORT", "/dev/ttyUSB0")
ESP32_BAUD = int(os.getenv("ESP32_BAUD", "115200"))
BACKEND_HTTP = os.getenv("BACKEND_HTTP", "http://localhost:8080")
BACKEND_WS = os.getenv("BACKEND_WS", "ws://localhost:8080/ws")
START_VISION = os.getenv("START_VISION", "1") == "1"
CAMERA_PORT = int(os.getenv("CAMERA_PORT", "8081"))


def parse_telemetry(line):
    if not line.startswith("$CHR"):
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 15:
        return None

    def to_float(val, default=0.0):
        try:
            return float(val)
        except Exception:
            return default

    def to_int(val, default=0):
        try:
            return int(val)
        except Exception:
            return default

    data = {
        "timestampMs": to_int(parts[1]),
        "rpm": to_float(parts[2]),
        "distCm": to_int(parts[3]),
        "accelY": to_float(parts[4]),
        "gyroZ": to_float(parts[5]),
        "x": to_float(parts[6]) / 100.0,
        "y": to_float(parts[7]) / 100.0,
        "heading": to_float(parts[8]),
        "distLapCm": to_float(parts[9]),
        "distTotalCm": to_float(parts[10]),
        "batteryV": to_float(parts[11]),
        "obstacle": to_int(parts[12]) == 1,
        "state": parts[13],
        "flags": parts[14],
        "lat": 0.0,
        "lon": 0.0,
        "gpsFix": False,
        "gpsHdop": 0.0,
    }

    if len(parts) >= 19:
        data["lat"] = to_float(parts[15])
        data["lon"] = to_float(parts[16])
        data["gpsFix"] = to_int(parts[17]) == 1
        data["gpsHdop"] = to_float(parts[18])

    return data


class VictimRegistry:
    def __init__(self, min_dist_m=2.0):
        self.min_dist_m = min_dist_m
        self.victims = []

    def add(self, x, y, lat, lon, confidence):
        for v in self.victims:
            dx = v["x"] - x
            dy = v["y"] - y
            if (dx * dx + dy * dy) ** 0.5 < self.min_dist_m:
                return None
        victim = {
            "id": str(uuid.uuid4())[:8],
            "x": x,
            "y": y,
            "lat": lat,
            "lon": lon,
            "confidence": confidence,
            "detectedAt": int(time.time() * 1000),
            "source": "vision",
            "notes": "person detected"
        }
        self.victims.append(victim)
        return victim


class RoverBridge:
    def __init__(self):
        self.serial = serial.Serial(ESP32_PORT, ESP32_BAUD, timeout=0.2)
        self.path_tracker = PathTracker()
        self.drift = DriftCorrector()
        self.victims = VictimRegistry()
        self.last_path_sent = 0
        self.last_telemetry_sent = 0
        self.current_pose = {"x": 0.0, "y": 0.0, "heading": 0.0}
        self.client = BackendClient(BACKEND_WS, BACKEND_HTTP, on_command=self._send_command, log_fn=self._log)
        self.client.start()

        self.vision = None
        if START_VISION:
            self.vision = VisionSystem(on_victim=self._on_victim, on_log=self._log)
            self.vision.start()
            start_mjpeg_server(self.vision, port=CAMERA_PORT)

    def _log(self, message):
        log_entry = {
            "level": "INFO",
            "message": message,
            "timestampMs": int(time.time() * 1000)
        }
        self.client.send("log", log_entry)

    def _send_command(self, cmd):
        try:
            self.serial.write((cmd + "\n").encode("ascii"))
        except Exception:
            pass

    def _on_victim(self, confidence):
        pose = self.current_pose
        victim = self.victims.add(pose["x"], pose["y"], pose.get("lat", 0.0), pose.get("lon", 0.0), confidence)
        if victim:
            self.client.send("victim", victim)
            alert = {
                "level": "ALERT",
                "message": "Victim detected",
                "timestampMs": int(time.time() * 1000)
            }
            self.client.send("alert", alert)

    def _handle_telemetry(self, data):
        corrected_x, corrected_y, gps_local = self.drift.update(
            data["x"],
            data["y"],
            data["lat"],
            data["lon"],
            data["gpsFix"],
        )

        data["x"] = corrected_x
        data["y"] = corrected_y

        self.current_pose = {
            "x": corrected_x,
            "y": corrected_y,
            "heading": data["heading"],
            "lat": data["lat"],
            "lon": data["lon"],
        }

        updated = self.path_tracker.update(corrected_x, corrected_y, data["heading"], data["timestampMs"])

        now = time.time()
        if now - self.last_telemetry_sent > 0.1:
            self.client.send("telemetry", data)
            self.last_telemetry_sent = now

        if updated and now - self.last_path_sent > 0.4:
            self.client.send("path", self.path_tracker.get_path())
            self.last_path_sent = now

        if data["obstacle"]:
            alert = {
                "level": "WARN",
                "message": "Obstacle detected",
                "timestampMs": int(time.time() * 1000)
            }
            self.client.send("alert", alert)

        if data["batteryV"] > 0 and data["batteryV"] <= 10.6:
            alert = {
                "level": "WARN",
                "message": "Battery low",
                "timestampMs": int(time.time() * 1000)
            }
            self.client.send("alert", alert)

    def loop(self):
        self._log("Rover bridge online")
        while True:
            try:
                raw = self.serial.readline().decode("ascii", errors="ignore").strip()
                if not raw:
                    continue
                if raw.startswith("$CHR"):
                    data = parse_telemetry(raw)
                    if data:
                        self._handle_telemetry(data)
                else:
                    self._log(raw)
            except KeyboardInterrupt:
                break
            except Exception:
                time.sleep(0.1)


if __name__ == "__main__":
    bridge = RoverBridge()
    bridge.loop()
