"""Turing Smart Screen serial families: revision A and revision C.

Protocols as implemented by turing-smart-screen-python
(https://github.com/mathoudebine/turing-smart-screen-python,
Copyright (C) 2021 Matthieu Houdebine, GPL-3.0-or-later), reimplemented on
the transport/driver contract of this project. Low-level methods keep the
reference command sequences so the byte streams can be compared with the
reference golden files (tests/test_display_protocols.py).
"""

import string
import time

from .. import frames
from .base import DISCONNECTED, NOT_FOUND, PROTOCOL, Capabilities, DeviceInfo, DisplayError, RasterDriver, percent
from .transport import SerialTransport

PORTRAIT, REVERSE_PORTRAIT, LANDSCAPE, REVERSE_LANDSCAPE = 0, 1, 2, 3


def oriented_size(native_portrait, orientation):
    width, height = native_portrait
    return (width, height) if orientation in (PORTRAIT, REVERSE_PORTRAIT) else (height, width)


class SerialDisplay(RasterDriver):
    """Common plumbing for serial panels (port resolution, transport)."""

    NATIVE = (320, 480)          # portrait panel size

    def __init__(self, port=None, transport=None, options=None):
        super().__init__()
        self.port = port
        self.transport = transport
        self.options = options or {}
        self.orientation = PORTRAIT
        self.display_width, self.display_height = self.NATIVE

    def _connect(self):
        if self.transport is None:
            if not self.port:
                raise DisplayError(NOT_FOUND, f"{self.DRIVER}: no serial port")
            self.transport = SerialTransport(self.port).open()

    def close(self):
        transport, self.transport = self.transport, None
        self._prev = None
        if transport is not None and hasattr(transport, "close"):
            transport.close()

    def probe(self):
        if self.transport is None:
            raise DisplayError(DISCONNECTED, f"{self.DRIVER} not open")
        if hasattr(self.transport, "alive"):
            self.transport.alive()

    def get_width(self):
        return oriented_size((self.display_width, self.display_height), self.orientation)[0]

    def get_height(self):
        return oriented_size((self.display_width, self.display_height), self.orientation)[1]

    def _ready(self, model):
        self.native_size = (max(self.display_width, self.display_height),
                            min(self.display_width, self.display_height))
        self.capabilities.native_size = self.native_size
        self.info = DeviceInfo(self.DRIVER, model, *self.native_size, location=self.port or "")
        self._prev = None
        return self.info


# ------------------------------------------------------------- revision A

class TuringRevA(SerialDisplay):
    """Turing Smart Screen 3.5" (rev. A) and UsbPCMonitor 3.5"/5"/7"."""

    DRIVER = "turing_rev_a"
    TILE = (48, 20)
    MAX_RECTS = 48
    TIGHT_RECTS = True            # ~190 KB/s link: every pixel not sent is time saved
    RESET, CLEAR, SCREEN_OFF, SCREEN_ON = 101, 102, 108, 109
    SET_BRIGHTNESS, SET_ORIENTATION, DISPLAY_BITMAP, HELLO = 110, 121, 197, 69
    SUB_REVISIONS = {bytes([1] * 6): ("UsbPCMonitor 3.5\"", (320, 480)),
                     bytes([2] * 6): ("UsbPCMonitor 5\"", (480, 800)),
                     bytes([3] * 6): ("UsbPCMonitor 7\"", (600, 1024))}

    def __init__(self, port=None, transport=None, options=None):
        super().__init__(port, transport, options)
        self.capabilities = Capabilities(encoding="rgb565le", transport="serial")
        self.model = "Turing Smart Screen 3.5\""

    @staticmethod
    def command(cmd, x=0, y=0, ex=0, ey=0):
        return bytes([x >> 2, ((x & 3) << 6) + (y >> 4), ((y & 15) << 4) + (ex >> 6),
                      ((ex & 63) << 2) + (ey >> 8), ey & 255, cmd])

    def hello(self):
        self.transport.write(bytes([self.HELLO] * 6))
        response = self.transport.read(6)
        self.transport.reset_input()
        # The original Turing 3.5" does not answer HELLO.
        self.model, (self.display_width, self.display_height) = self.SUB_REVISIONS.get(
            response, ("Turing Smart Screen 3.5\"", (320, 480)))

    def set_orientation(self, orientation):
        self.orientation = orientation
        width, height = self.get_width(), self.get_height()
        buffer = bytearray(16)
        buffer[5] = self.SET_ORIENTATION
        buffer[6] = orientation + 100
        buffer[7], buffer[8] = width >> 8, width & 255
        buffer[9], buffer[10] = height >> 8, height & 255
        self.transport.write(bytes(buffer))

    def set_brightness(self, level):
        level = percent(level)
        self.transport.write(self.command(self.SET_BRIGHTNESS, int(255 - ((level / 100) * 255))))

    def display_image(self, image, x=0, y=0):
        width, height = self.get_width(), self.get_height()
        image_width = min(image.width, width - x)
        image_height = min(image.height, height - y)
        if (image_width, image_height) != image.size:
            image = image.crop((0, 0, image_width, image_height))
        payload = frames.image_to_rgb565(image, "<").tobytes()
        self.transport.write(self.command(self.DISPLAY_BITMAP, x, y, x + image_width - 1, y + image_height - 1))
        for chunk in frames.chunked(payload, width * 8):
            self.transport.write(chunk)
        return len(payload)

    def open(self):
        self._connect()
        self.hello()
        self.set_orientation(LANDSCAPE)
        return self._ready(self.model)

    def _blit(self, image, rect):
        x0, y0, x1, y1 = rect
        return self.display_image(image.crop(rect), x0, y0)


# ------------------------------------------------------------- revision C

REV_C_SIZES = {"2.1": (480, 480), "2.8": (480, 480), "5": (480, 800), "8.8": (480, 1920)}
REV_C_HINTS = {"21": "2.1", "28": "2.8", "5": "5", "50": "5", "88": "8.8"}


class TuringRevC(SerialDisplay):
    """Turing Smart Screen 2.1"/2.8"/5"/8.8" (rev. C, serial).

    The panel sleeps until its port is opened, then re-enumerates with a new
    identity; discovery handles that wake-up before ``open()``.
    """

    DRIVER = "turing_rev_c"
    TILE = (48, 24)
    MAX_RECTS = 4                 # every partial update waits for a status read
    FULL_REFRESH_RATIO = 0.4
    HELLO = bytes((0x01, 0xef, 0x69, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0xc5, 0xd3))
    OPTIONS = bytes((0x7d, 0xef, 0x69, 0x00, 0x00, 0x00, 0x05, 0x00, 0x00, 0x00, 0x2d))
    SET_BRIGHTNESS = bytes((0x7b, 0xef, 0x69, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00))
    QUERY_STATUS = bytes((0xcf, 0xef, 0x69, 0x00, 0x00, 0x00, 0x01))
    START_DISPLAY_BITMAP = bytes((0x2c,))
    PRE_UPDATE_BITMAP = bytes((0x86, 0xef, 0x69, 0x00, 0x00, 0x00, 0x01))
    UPDATE_BITMAP = bytes((0xcc, 0xef, 0x69, 0x00))
    DISPLAY_BITMAP = {"2": bytes((0xc8, 0xef, 0x69, 0x00, 0x0E, 0x10)),
                      "5": bytes((0xc8, 0xef, 0x69, 0x00, 0x17, 0x70)),
                      "8": bytes((0xc8, 0xef, 0x69, 0x00, 0x38, 0x40))}
    HELLO_ATTEMPTS = 5

    def __init__(self, port=None, transport=None, options=None):
        super().__init__(port, transport, options)
        size = (options or {}).get("size", "5")
        self.size_name = size if size in REV_C_SIZES else "5"
        self.display_width, self.display_height = REV_C_SIZES[self.size_name]
        self.rom_version = 87
        self.count = 0
        self.capabilities = Capabilities(encoding="bgra", transport="serial", max_payload=0,
                                         notes=("partial updates wait for a status reply",))

    @property
    def sub_revision(self):
        return {"2.1": "2", "2.8": "2", "5": "5", "8.8": "8"}[self.size_name]

    def send(self, cmd, payload=None, padding=b"\x00", readsize=None):
        message = bytearray(cmd or b"")
        if payload:
            message.extend(payload)
        if len(message) % 250:
            message += padding * (250 - len(message) % 250)
        self.transport.write(bytes(message))
        if readsize:
            self.transport.read(readsize)

    def hello(self):
        response = ""
        for attempt in range(self.HELLO_ATTEMPTS):
            self.transport.reset_input()
            self.send(self.HELLO)
            raw = self.transport.read(23)
            self.transport.reset_input()
            response = "".join(ch for ch in raw.decode(errors="ignore") if ch in string.printable)
            if response.startswith("chs_"):
                break
            time.sleep(1 if attempt < self.HELLO_ATTEMPTS - 1 else 0)
        else:
            raise DisplayError(PROTOCOL, f"rev. C handshake failed (got {response!r})")
        self.firmware = response
        hint = response[4:].split("inch")[0] if "inch" in response else ""
        if self.options.get("size", "auto") == "auto" and REV_C_HINTS.get(hint):
            self.size_name = REV_C_HINTS[hint]
            self.display_width, self.display_height = REV_C_SIZES[self.size_name]
        try:
            self.rom_version = int(response.split(".")[2])
            if not 80 <= self.rom_version <= 100:
                self.rom_version = 87
        except (IndexError, ValueError):
            self.rom_version = 87

    def set_orientation(self, orientation):
        self.orientation = orientation
        self.send(self.OPTIONS, payload=b"\x00\x00\x00\x00")   # default start mode, no flip, no sleep

    def set_brightness(self, level):
        self.send(self.SET_BRIGHTNESS, payload=bytes((int(percent(level) / 100 * 255),)))

    def _rotated_full(self, image):
        o = self.orientation
        if self.sub_revision == "8":
            angle = {LANDSCAPE: 270, REVERSE_LANDSCAPE: 90, PORTRAIT: 180}.get(o)
            return image.rotate(angle, expand=True) if angle else image
        if o == PORTRAIT:
            return image.rotate(90, expand=True)
        if o == REVERSE_PORTRAIT:
            return image.rotate(270, expand=True)
        if o == REVERSE_LANDSCAPE:
            return image.rotate(180)
        return image

    def _full_image(self, image):
        data = frames.image_to_bgra(self._rotated_full(image))
        return b"\x00".join(frames.chunked(data, 249))

    def _update_image(self, image, x, y):
        x0, y0 = x, y
        o = self.orientation
        width, height = self.get_width(), self.get_height()
        if self.sub_revision == "8":
            if o == LANDSCAPE:
                image = image.rotate(270, expand=True)
                y0 = height - y - image.width
            elif o == REVERSE_LANDSCAPE:
                image = image.rotate(90, expand=True)
                x0 = width - x - image.height
            elif o == PORTRAIT:
                image = image.rotate(180, expand=True)
                x0 = height - y - image.height
                y0 = height - x - image.width
            else:
                x0, y0 = y, x
        else:
            if o == PORTRAIT:
                image = image.rotate(90, expand=True)
                x0 = width - x - image.height
            elif o == REVERSE_PORTRAIT:
                image = image.rotate(270, expand=True)
                y0 = height - y - image.width
            elif o == REVERSE_LANDSCAPE:
                image = image.rotate(180)
                y0 = width - x - image.width
                x0 = height - y - image.height
            else:
                x0, y0 = y, x
        bgra = self.sub_revision != "2" and self.rom_version > 88
        data = frames.image_to_bgra(image) if bgra else frames.image_to_bgr(image)
        pixel = 4 if bgra else 3
        stride = self.display_width if self.sub_revision == "8" else self.display_height
        raw = bytearray()
        for row, line in enumerate(frames.chunked(data, image.width * pixel)):
            raw += int((x0 + row) * stride + y0).to_bytes(3, "big")
            raw += int(image.width).to_bytes(2, "big")
            raw += line
        header = bytearray(self.UPDATE_BITMAP) + int(len(raw) + 2).to_bytes(3, "big") + b"\x00" * 3
        header += self.count.to_bytes(4, "big")
        if len(raw) > 250:
            raw = bytearray(b"\x00".join(frames.chunked(bytes(raw), 249)))
        raw += b"\xef\x69"
        return bytes(raw), bytes(header)

    def display_image(self, image, x=0, y=0):
        width, height = self.get_width(), self.get_height()
        image_width, image_height = min(image.width, width), min(image.height, height)
        if (image_width, image_height) != image.size:
            image = image.crop((0, 0, image_width, image_height))
        if x == 0 and y == 0 and image.size == (width, height):
            self.send(self.PRE_UPDATE_BITMAP)
            self.send(self.START_DISPLAY_BITMAP, padding=b"\x2c")
            self.send(self.DISPLAY_BITMAP[self.sub_revision],
                      payload=int(self.display_width * self.display_width / 64).to_bytes(2, "big"))
            payload = self._full_image(image)
            self.send(None, payload=payload, readsize=1024)
            self.send(self.QUERY_STATUS, readsize=1024)
            return len(payload)
        raw, header = self._update_image(image, x, y)
        self.send(None, payload=header)
        self.send(None, payload=raw)
        self.send(self.QUERY_STATUS, readsize=1024)
        self.count += 1
        return len(raw)

    def open(self):
        self._connect()
        self.hello()
        self.set_orientation(LANDSCAPE)
        return self._ready(f"Turing Smart Screen {self.size_name}\" (rev. C)")

    def _blit(self, image, rect):
        if rect == (0, 0, *self.native_size):
            return self.display_image(image)
        return self.display_image(image.crop(rect), rect[0], rect[1])


def wake_rev_c(port, serial_module=None):
    """Opening the sleeping port wakes a rev. C panel (no data is written)."""
    try:
        SerialTransport(port, serial_module=serial_module).open().close()
    except DisplayError:
        pass    # the port may vanish while the panel re-enumerates

