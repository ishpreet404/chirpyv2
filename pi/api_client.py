import json
import threading
import time

import requests
import websocket


class BackendClient:
    def __init__(self, ws_url, http_url, on_command=None, log_fn=None):
        self.ws_url = ws_url
        self.http_url = http_url.rstrip("/")
        self.on_command = on_command
        self.log_fn = log_fn or (lambda *args, **kwargs: None)
        self.ws = None
        self.connected = threading.Event()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()

    def start(self):
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self.stop_event.set()
        if self.ws:
            self.ws.close()

    def _run(self):
        while not self.stop_event.is_set():
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
            )
            self.ws.run_forever(ping_interval=20, ping_timeout=10)
            time.sleep(2)

    def _on_open(self, _ws):
        self.connected.set()
        self.log_fn("WS connected")

    def _on_close(self, _ws, *_args):
        self.connected.clear()
        self.log_fn("WS disconnected")

    def _on_error(self, _ws, error):
        self.connected.clear()
        self.log_fn(f"WS error: {error}")

    def _on_message(self, _ws, message):
        try:
            msg = json.loads(message)
            if msg.get("type") == "command":
                cmd = msg.get("data", {}).get("command")
                if cmd and self.on_command:
                    self.on_command(cmd)
        except Exception as exc:
            self.log_fn(f"WS parse error: {exc}")

    def send(self, msg_type, data):
        payload = json.dumps({"type": msg_type, "data": data})
        with self.lock:
            if self.ws and self.connected.is_set():
                try:
                    self.ws.send(payload)
                    return True
                except Exception:
                    return False
        return False

    def post_telemetry(self, envelope):
        try:
            url = f"{self.http_url}/api/telemetry"
            requests.post(url, json=envelope, timeout=2)
            return True
        except Exception:
            return False
