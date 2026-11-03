"""WeAct Studio Display FS V1: 3.5" (A) and 0.96" (B).

Protocol as implemented by turing-smart-screen-python (Copyright (C) 2021
Matthieu Houdebine, GPL-3.0-or-later): short commands terminated by 0x0A,
orientation handled by the panel, RGB565 little-endian bitmaps. The 3.5"
model also reports room temperature and humidity when asked.
"""

import struct

from .. import frames
from .base import Capabilities, percent
from .turing_serial import LANDSCAPE, SerialDisplay

CMD_SET_ORIENTATION, CMD_SET_BRIGHTNESS, CMD_FULL, CMD_SET_BITMAP = 0x02, 0x03, 0x04, 0x05
CMD_HUMITURE_REPORT, CMD_FREE, CMD_SYSTEM_VERSION, CMD_END, CMD_READ = 0x06, 0x07, 0x42, 0x0A, 0x80


class WeActA(SerialDisplay):
    DRIVER = "weact_a"
    NATIVE = (320, 480)
    MODEL = "WeAct Studio Display FS V1 3.5\""
    TILE = (32, 16)
    MAX_RECTS = 16
    HAS_SENSORS = True

    def __init__(self, port=None, transport=None, options=None):
        super().__init__(port, transport, options)
        self.firmware = None
        self.room_temperature = None
        self.humidity = None
        self.capabilities = Capabilities(encoding="rgb565le", transport="serial",
                                         sensors=("room_temperature", "humidity") if self.HAS_SENSORS else ())

    def query_version(self):
        self.transport.drain_input()
        self.transport.write(bytes((CMD_SYSTEM_VERSION | CMD_READ, CMD_END)))
        response = self.transport.read(19)
        self.transport.reset_input()
        if len(response) == 19:
            self.firmware = response[1:9].decode("ascii", errors="replace").strip()
        return self.firmware

    def set_orientation(self, orientation):
        self.orientation = orientation
        self.transport.write(bytes((CMD_SET_ORIENTATION, orientation, CMD_END)))

    def set_brightness(self, level):
        value = int((percent(level) / 100) * 255)
        fade_ms = 1000
        self.transport.write(bytes((CMD_SET_BRIGHTNESS, value & 0xFF, fade_ms & 0xFF, fade_ms >> 8 & 0xFF, CMD_END)))

    def fill(self, rgb=(0, 0, 0)):
        value = struct.pack("<H", ((rgb[0] >> 3) << 11) | ((rgb[1] >> 2) << 5) | (rgb[2] >> 3))
        xe, ye = self.get_width(), self.get_height()
        self.transport.write(bytes((CMD_FULL, 0, 0, 0, 0, (xe - 1) & 0xFF, xe >> 8 & 0xFF, (ye - 1) & 0xFF,
                                    ye >> 8 & 0xFF, value[0], value[1], CMD_END)))

    def enable_sensor_report(self, interval_ms=1000):
        if self.HAS_SENSORS:
            self.transport.write(bytes((CMD_HUMITURE_REPORT, interval_ms & 0xFF, interval_ms >> 8 & 0xFF, CMD_END)))

    def read_sensors(self):
        """Parse pending humiture reports (never blocks)."""
        if not self.HAS_SENSORS or self.transport is None:
            return None
        data = self.transport.drain_input()
        index = 0
        while index + 6 <= len(data):   # frames: 0x86, temperature u16, humidity s16, 0x0A
            if data[index] == CMD_HUMITURE_REPORT | CMD_READ and data[index + 5] == CMD_END:
                temperature, humidity = struct.unpack("<Hh", data[index + 1:index + 5])
                self.room_temperature, self.humidity = temperature / 100, humidity / 100
                index += 6
            else:
                index += 1
        return self.room_temperature, self.humidity

    def display_image(self, image, x=0, y=0):
        width, height = self.get_width(), self.get_height()
        image_width, image_height = min(image.width, width), min(image.height, height)
        if (image_width, image_height) != image.size:
            image = image.crop((0, 0, image_width, image_height))
        x1, y1 = x + image_width - 1, y + image_height - 1
        self.transport.write(bytes((CMD_SET_BITMAP, x & 0xFF, x >> 8 & 0xFF, y & 0xFF, y >> 8 & 0xFF,
                                    x1 & 0xFF, x1 >> 8 & 0xFF, y1 & 0xFF, y1 >> 8 & 0xFF, CMD_END)))
        payload = frames.image_to_rgb565(image, "<").tobytes()
        for chunk in frames.chunked(payload, width * 4):
            self.transport.write(chunk)
        return len(payload)

    def probe(self):
        super().probe()
        self.read_sensors()

    def open(self):
        self._connect()
        self.query_version()
        self.set_orientation(LANDSCAPE)
        if self.options.get("sensors", True):
            self.enable_sensor_report()
        info = self._ready(self.MODEL)
        info.details["firmware"] = self.firmware
        return info

    def _blit(self, image, rect):
        return self.display_image(image.crop(rect), rect[0], rect[1])


class WeActB(WeActA):
    DRIVER = "weact_b"
    NATIVE = (80, 160)
    MODEL = "WeAct Studio Display FS V1 0.96\""
    TILE = (16, 16)
    MAX_RECTS = 8
    HAS_SENSORS = False
