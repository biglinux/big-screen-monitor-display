"""Software model of the bsmd-ce client: a transport that behaves like the device.

Used by the test-suite and by ``main.py --foston-demo`` to exercise the
driver, the runtime and the touch layer without the navigator. It decodes
FSP exactly like ``device-clients/wince/src/fsp.c`` (the C core is checked
against the same streams in tests/test_foston.py), keeps a framebuffer and
can inject touches. It is a model, not evidence that the hardware works.
"""

import queue
import struct
import threading
import zlib

import numpy as np

from ..base import DISCONNECTED, DisplayError
from . import protocol as fsp


def decode_rect(fb, kind, payload):
    """Apply a RECT or FILL payload to ``fb`` ((h, w) uint16). Returns (x, y, w, h)."""
    x, y, w, h = struct.unpack_from("<HHHH", payload)
    height, width = fb.shape
    if w <= 0 or h <= 0 or x + w > width or y + h > height:
        raise ValueError("bad rect")
    if kind == fsp.FILL:
        fb[y:y + h, x:x + w] = struct.unpack_from("<H", payload, 8)[0]
        return x, y, w, h
    encoding, data = payload[8], payload[14:]
    if encoding == fsp.ENC_RAW:
        pixels = np.frombuffer(data, dtype="<u2")
    elif encoding == fsp.ENC_DEFLATE:
        pixels = np.frombuffer(zlib.decompress(data), dtype="<u2")
    elif encoding == fsp.ENC_RLE:
        out, pos = [], 0
        while pos < len(data):
            token = struct.unpack_from("<H", data, pos)[0]
            pos += 2
            count = (token & 0x7FFF) + 1
            if token & 0x8000:
                out.append(np.full(count, struct.unpack_from("<H", data, pos)[0], dtype="<u2"))
                pos += 2
            else:
                out.append(np.frombuffer(data[pos:pos + count * 2], dtype="<u2"))
                pos += count * 2
        pixels = np.concatenate(out) if out else np.zeros(0, dtype="<u2")
    else:
        raise ValueError("bad encoding")
    if pixels.size != w * h:
        raise ValueError("size mismatch")
    fb[y:y + h, x:x + w] = pixels.reshape(h, w)
    return x, y, w, h


class EmulatedDevice:
    """Transport-compatible fake of the device (write/read/alive/close)."""

    def __init__(self, width=800, height=480, brightness=True, silent=False, client="bsmd-ce 1.0.0 (emulated)"):
        self.fb = np.zeros((height, width), dtype=np.uint16)
        self.width, self.height = width, height
        self.brightness_support = brightness
        self.brightness = None
        self.silent = silent              # never answers (client not running)
        self.client = client
        self.parser = _HostStreamParser()
        self.out = queue.Queue()
        self.presented = []
        self.calibrations = 0
        self.quit = False
        self.closed = False
        self.drop_present = False         # simulate a hung device
        self.nak_next = False
        self.late_nak = False
        self.messages = []
        self.credits = True               # bsmd-ce >= 1.1 flow control
        self.withhold_credit = False      # simulate a device that stopped reading
        self.consumed = 0
        self._seq = 0
        self._lock = threading.Lock()

    # transport API -------------------------------------------------------
    def write(self, data):
        if self.closed:
            raise DisplayError(DISCONNECTED, "emulated device unplugged")
        with self._lock:
            for msg in self.parser.feed(data):
                self.messages.append(msg.kind)
                if not self.silent:
                    self._handle(msg)
        return len(data)

    def read(self, size):
        if self.closed:
            raise DisplayError(DISCONNECTED, "emulated device unplugged")
        try:
            return self.out.get(timeout=0.05)
        except queue.Empty:
            return b""

    def alive(self):
        if self.closed:
            raise DisplayError(DISCONNECTED, "emulated device unplugged")

    def close(self):
        pass

    def unplug(self):
        self.closed = True

    # device behaviour ----------------------------------------------------
    def _reply(self, kind, payload):
        self.out.put(fsp.message(kind, payload, self._seq))
        self._seq += 1

    def touch(self, kind, x, y, tick=0):
        self._reply(fsp.TOUCH, struct.pack("<BBHHHI", kind, 0, x, y, 0, tick))

    def tap(self, x, y):
        self.touch(fsp.TOUCH_DOWN, x, y, 0)
        self.touch(fsp.TOUCH_UP, x, y, 80)

    def _handle(self, msg):
        if msg.kind != fsp.HELLO:
            self.consumed += fsp.HEADER_SIZE + len(msg.payload)
        self._handle_one(msg)
        if self.credits and msg.kind != fsp.HELLO and not self.withhold_credit:
            self._reply(fsp.CREDIT, struct.pack("<I", self.consumed))

    def _handle_one(self, msg):
        if self.nak_next and msg.kind in (fsp.RECT, fsp.FILL):
            self.nak_next = False
            self._reply(fsp.NAK, struct.pack("<HB", msg.seq, 4))
            self.late_nak = True
            return
        if msg.kind == fsp.HELLO and self.late_nak:
            # a NAK of the damaged frame still in flight when the repair HELLO arrives
            self.late_nak = False
            self._reply(fsp.NAK, struct.pack("<HB", 0xFFFF, 6))
        if msg.kind == fsp.HELLO:
            strings = b"\0".join(s.encode() for s in (self.client, "Emulated", "FOSTON emulator", "COM9:",
                                                      "Mass_Storage_Class")) + b"\0"
            head = struct.pack("<HHHHIIIII", fsp.VERSION, self.width, self.height, 16, 5, 0, 1400, 61440, 30000)
            self.consumed = 0
            flags = 1 | (2 if self.credits else 0)
            self._reply(fsp.HELLO_ACK, head + bytes([1 if self.brightness_support else 0, 80, 1, flags]) + strings)
            return
        elif msg.kind == fsp.PING:
            self._reply(fsp.PONG, msg.payload[:4] + b"\0\0\0\0")
        elif msg.kind in (fsp.RECT, fsp.FILL):
            try:
                decode_rect(self.fb, msg.kind, msg.payload)
            except (ValueError, zlib.error, struct.error):
                self._reply(fsp.NAK, struct.pack("<HB", msg.seq, 4))
        elif msg.kind == fsp.PRESENT:
            if not self.drop_present:
                self.presented.append(struct.unpack_from("<I", msg.payload)[0])
                self._reply(fsp.PRESENTED, msg.payload[:4] + struct.pack("<II", 3, 1))
        elif msg.kind == fsp.BRIGHTNESS:
            self.brightness = msg.payload[0]
        elif msg.kind == fsp.CALIBRATE:
            self.calibrations += 1
        elif msg.kind == fsp.BYE and msg.payload[:1] == bytes([fsp.BYE_QUIT]):
            # the real client closes its window, restores USB storage and says BYE
            self.quit = True
            self._reply(fsp.BYE, bytes([fsp.BYE_QUIT]))

    def image(self):
        """Framebuffer as an RGB PIL image (RGB565 expanded)."""
        from PIL import Image
        fb = self.fb.astype(np.uint32)
        r = ((fb >> 11) & 0x1F) * 255 // 31
        g = ((fb >> 5) & 0x3F) * 255 // 63
        b = (fb & 0x1F) * 255 // 31
        return Image.fromarray(np.dstack((r, g, b)).astype(np.uint8), "RGB")


class _HostStreamParser(fsp.Parser):
    """Same framing in the other direction (host -> device)."""
