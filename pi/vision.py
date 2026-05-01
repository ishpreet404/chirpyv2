import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2


class VisionSystem:
    def __init__(self, camera_index=0, model_dir="models", confidence=0.5, on_victim=None, on_log=None):
        self.camera_index = camera_index
        self.model_dir = model_dir
        self.confidence = confidence
        self.on_victim = on_victim
        self.on_log = on_log or (lambda *args, **kwargs: None)
        self.running = False
        self.latest_jpeg = None
        self.lock = threading.Lock()
        self.net = None
        self.classes = [
            "background",
            "aeroplane",
            "bicycle",
            "bird",
            "boat",
            "bottle",
            "bus",
            "car",
            "cat",
            "chair",
            "cow",
            "diningtable",
            "dog",
            "horse",
            "motorbike",
            "person",
            "pottedplant",
            "sheep",
            "sofa",
            "train",
            "tvmonitor",
        ]
        self.last_detect_ms = 0

    def start(self):
        self.running = True
        self._load_model()
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def stop(self):
        self.running = False

    def _load_model(self):
        prototxt = f"{self.model_dir}/MobileNetSSD_deploy.prototxt"
        weights = f"{self.model_dir}/MobileNetSSD_deploy.caffemodel"
        try:
            self.net = cv2.dnn.readNetFromCaffe(prototxt, weights)
            self.on_log("Vision model loaded")
        except Exception as exc:
            self.net = None
            self.on_log(f"Vision model not loaded: {exc}")

    def _run(self):
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            self.on_log("Camera not available")
            return

        frame_count = 0
        while self.running:
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            frame_count += 1
            if self.net and frame_count % 5 == 0:
                self._detect_people(frame)

            ret, jpeg = cv2.imencode(".jpg", frame)
            if ret:
                with self.lock:
                    self.latest_jpeg = jpeg.tobytes()

        cap.release()

    def _detect_people(self, frame):
        now_ms = int(time.time() * 1000)
        if now_ms - self.last_detect_ms < 1200:
            return

        blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        detections = self.net.forward()

        for i in range(detections.shape[2]):
            confidence = float(detections[0, 0, i, 2])
            if confidence < self.confidence:
                continue
            class_id = int(detections[0, 0, i, 1])
            label = self.classes[class_id] if class_id < len(self.classes) else "unknown"
            if label == "person":
                self.last_detect_ms = now_ms
                if self.on_victim:
                    self.on_victim(confidence)
                break

    def get_latest_jpeg(self):
        with self.lock:
            return self.latest_jpeg


def start_mjpeg_server(vision, host="0.0.0.0", port=8081):
    class MJPEGHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/stream":
                self.send_response(404)
                self.end_headers()
                return

            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()

            while True:
                frame = vision.get_latest_jpeg()
                if frame is None:
                    time.sleep(0.05)
                    continue
                try:
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                except Exception:
                    break

        def log_message(self, format, *args):
            return

    server = HTTPServer((host, port), MJPEGHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


if __name__ == "__main__":
    def _log(msg):
        print(msg)

    vision = VisionSystem(on_log=_log)
    vision.start()
    start_mjpeg_server(vision)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        vision.stop()
