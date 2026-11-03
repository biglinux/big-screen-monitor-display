"""XuanFang 3.5" revision B and "flagship" (with backplate RGB LEDs).

Protocol as implemented by turing-smart-screen-python (Copyright (C) 2021
Matthieu Houdebine, GPL-3.0-or-later): 10-byte frames ``cmd + 8 bytes +
cmd``, RGB565 big-endian bitmaps, sub-revision reported by HELLO.
"""

import time

from .. import frames
from .base import PROTOCOL, Capabilities, DisplayError, percent
from .turing_serial import LANDSCAPE, PORTRAIT, REVERSE_LANDSCAPE, REVERSE_PORTRAIT, SerialDisplay

HELLO, SET_ORIENTATION, DISPLAY_BITMAP, SET_LIGHTING, SET_BRIGHTNESS = 0xCA, 0xCB, 0xCC, 0xCD, 0xCE
# sub-revision -> (flagship with LEDs, brightness range 0-255)
SUB_REVISIONS = {0x01: ("A01", False, False), 0x02: ("A02", True, False),
                 0x11: ("A11", False, True), 0x12: ("A12", True, True)}


class XuanFangRevB(SerialDisplay):
    DRIVER = "xuanfang_rev_b"
    TILE = (48, 20)
    MAX_RECTS = 6                 # each bitmap needs a 50 ms cool-down
    COOLDOWN = 0.05

    def __init__(self, port=None, transport=None, options=None):
        super().__init__(port, transport, options)
        self.sub_revision = "A01"
        self.flagship = False
        self.brightness_range = False
        self.capabilities = Capabilities(encoding="rgb565be", transport="serial", brightness_steps=2)

    @staticmethod
    def frame(cmd, payload=None):
        payload = list(payload or [])[:8]
        return bytes([cmd] + payload + [0] * (8 - len(payload)) + [cmd])

    def hello(self):
        hello = [ord(c) for c in "HELLO"]
        self.transport.write(self.frame(HELLO, hello))
        response = self.transport.read(10)
        self.transport.reset_input()
        if len(response) != 10 or response[0] != HELLO or response[-1] != HELLO or list(response[1:6]) != hello:
            raise DisplayError(PROTOCOL, f"XuanFang HELLO not recognised ({response.hex() or 'no answer'})")
        if response[6] == 0x0A and response[7] in SUB_REVISIONS:
            self.sub_revision, self.flagship, self.brightness_range = SUB_REVISIONS[response[7]]
        self.capabilities.leds = self.flagship
        self.capabilities.brightness_steps = 256 if self.brightness_range else 2

    def set_orientation(self, orientation):
        self.orientation = orientation
        landscape = orientation in (LANDSCAPE, REVERSE_LANDSCAPE)
        self.transport.write(self.frame(SET_ORIENTATION, [1 if landscape else 0]))

    def set_brightness(self, level):
        level = percent(level)
        value = int((level / 100) * 255) if self.brightness_range else (1 if level == 0 else 0)
        self.transport.write(self.frame(SET_BRIGHTNESS, [value]))

    def set_leds(self, rgb):
        """Backplate LEDs (flagship sub-revisions only)."""
        if self.flagship:
            self.transport.write(self.frame(SET_LIGHTING, list(rgb)[:3]))
            return True
        return False

    def display_image(self, image, x=0, y=0):
        width, height = self.get_width(), self.get_height()
        image_width = min(image.width, width)
        image_height = min(image.height, height)
        if self.orientation in (PORTRAIT, LANDSCAPE):
            x0, y0, x1, y1 = x, y, x + image_width - 1, y + image_height - 1
        else:   # reverse orientations are done in software
            x0, y0 = width - x - image_width, height - y - image_height
            x1, y1 = width - x - 1, height - y - 1
        self.transport.write(self.frame(DISPLAY_BITMAP, [x0 >> 8 & 255, x0 & 255, y0 >> 8 & 255, y0 & 255,
                                                         x1 >> 8 & 255, x1 & 255, y1 >> 8 & 255, y1 & 255]))
        if (image.width, image.height) != (image_width, image_height):
            image = image.crop((0, 0, image_width, image_height))
        if self.orientation in (REVERSE_PORTRAIT, REVERSE_LANDSCAPE):
            image = image.rotate(180)
        payload = frames.image_to_rgb565(image, ">").tobytes()
        for chunk in frames.chunked(payload, width * 8):
            self.transport.write(chunk)
        time.sleep(self.COOLDOWN)   # no ack: a short pause avoids corrupted bitmaps
        return len(payload)

    def open(self):
        self._connect()
        self.hello()
        self.set_orientation(LANDSCAPE)
        model = "XuanFang 3.5\" flagship" if self.flagship else "XuanFang 3.5\" rev. B"
        info = self._ready(model)
        info.details["sub_revision"] = self.sub_revision
        return info

    def _blit(self, image, rect):
        return self.display_image(image.crop(rect), rect[0], rect[1])
