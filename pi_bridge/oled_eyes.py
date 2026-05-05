#!/usr/bin/env python3
import logging
import math
import os
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
        self.fps = max(2, int(os.getenv("OLED_FPS", "12")))
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

        try:
            serial = i2c(port=self.port, address=self.address)
            self._device = ssd1306(serial, width=self.width, height=self.height)
        except Exception:
            logging.exception(
                "OLED init failed on I2C bus %s address 0x%02X",
                self.port,
                self.address,
            )
            return

        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()
        logging.info("OLED eyes started on I2C bus %s address 0x%02X", self.port, self.address)

    def stop(self):
        self._stop.set()

    def _animate(self):
        frame = 0
        while not self._stop.is_set():
            image = Image.new("1", (self.width, self.height), 0)
            draw = ImageDraw.Draw(image)

            t = frame / self.fps
            gaze_x = int(math.sin(t * 1.4) * 8)
            gaze_y = int(math.sin(t * 0.9) * 3)
            blink_phase = (frame % (self.fps * 5)) / (self.fps * 5)
            blink = blink_phase > 0.92

            self._draw_eye(draw, 38, 32, gaze_x, gaze_y, blink)
            self._draw_eye(draw, 90, 32, gaze_x, gaze_y, blink)

            try:
                self._device.display(image)
            except Exception:
                logging.exception("OLED display update failed")
                return

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
