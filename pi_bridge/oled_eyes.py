#!/usr/bin/env python3
import logging
import math
import os
import random
import threading
import time

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw
except ImportError:
    i2c = None
    ssd1306 = None
    Image = None
    ImageDraw = None


class OledEyes:
    def __init__(self):
        self.enabled = os.getenv("OLED_ENABLED", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        self.port = int(os.getenv("OLED_I2C_BUS", "1"))
        self.address = int(os.getenv("OLED_I2C_ADDRESS", "0x3C"), 0)
        self.width = int(os.getenv("OLED_WIDTH", "128"))
        self.height = int(os.getenv("OLED_HEIGHT", "64"))
        self.fps = max(2, int(os.getenv("OLED_FPS", "8")))
        self.retry_delay_s = max(0.2, float(os.getenv("OLED_RETRY_DELAY_S", "1.0")))
        self._stop = threading.Event()
        self._thread = None
        self._device = None

    def start(self):
        if not self.enabled:
            logging.info("OLED eyes disabled")
            return
        if i2c is None or ssd1306 is None or Image is None or ImageDraw is None:
            logging.warning("OLED eyes unavailable. Install luma.oled and pillow.")
            return

        if not self._init_device():
            return

        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
        logging.info("OLED eyes started on I2C bus %s address 0x%02X", self.port, self.address)

    def stop(self):
        self._stop.set()

    def _init_device(self) -> bool:
        try:
            serial = i2c(port=self.port, address=self.address)
            self._device = ssd1306(serial, width=self.width, height=self.height)
            return True
        except Exception as exc:
            logging.warning(
                "OLED init failed on I2C bus %s address 0x%02X: %s: %r",
                self.port,
                self.address,
                type(exc).__name__,
                exc,
            )
            self._device = None
            return False

    def _animate(self):
        frame = 0
        failures = 0
        target_x = 0
        target_y = 0
        gaze_x = 0.0
        gaze_y = 0.0

        while not self._stop.is_set():
            image = Image.new("1", (self.width, self.height), 0)
            draw = ImageDraw.Draw(image)

            t = frame / self.fps
            if frame % max(1, self.fps) == 0:
                target_x = random.randint(-10, 10)
                target_y = random.randint(-4, 4)
            gaze_x += (target_x - gaze_x) * 0.18
            gaze_y += (target_y - gaze_y) * 0.18

            idle_sway_x = math.sin(t * 2.4) * 3
            idle_sway_y = math.sin(t * 1.7) * 2
            eye_x = int(gaze_x + idle_sway_x)
            eye_y = int(gaze_y + idle_sway_y)
            blink_phase = (frame % (self.fps * 4)) / (self.fps * 4)
            blink = blink_phase > 0.9

            self._draw_eye(draw, 38, 32, eye_x, eye_y, blink)
            self._draw_eye(draw, 90, 32, eye_x, eye_y, blink)

            try:
                self._device.display(image)
                failures = 0
            except Exception as exc:
                failures += 1
                logging.warning(
                    "OLED display update failed (%s consecutive): %s: %r",
                    failures,
                    type(exc).__name__,
                    exc,
                )
                time.sleep(self.retry_delay_s)
                self._init_device()
                continue

            frame += 1
            time.sleep(1 / self.fps)

    def _draw_eye(self, draw, cx, cy, gaze_x, gaze_y, blink):
        eye_w = 38
        eye_h = 30
        left = cx - eye_w // 2
        top = cy - eye_h // 2
        right = cx + eye_w // 2
        bottom = cy + eye_h // 2

        if blink:
            draw.rounded_rectangle((left, cy - 2, right, cy + 2), radius=2, fill=1)
            return

        draw.rounded_rectangle((left, top, right, bottom), radius=8, outline=1, fill=0)
        pupil_r = 7
        px = cx + gaze_x
        py = cy + gaze_y
        draw.ellipse((px - pupil_r, py - pupil_r, px + pupil_r, py + pupil_r), fill=1)
        draw.ellipse((px - 3, py - 4, px, py - 1), fill=0)
