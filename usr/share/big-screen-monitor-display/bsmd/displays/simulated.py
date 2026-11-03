"""In-memory panel with fault injection, for tests, ``--simulate`` and previews."""

import time

from .. import frames
from .base import DISCONNECTED, IO, NOT_FOUND, Capabilities, DeviceInfo, DisplayError, Transfer


class SimulatedDisplay:
    """In-memory panel with fault injection, for tests and ``--simulate``.

    ``faults`` is a list consumed in order by each operation; entries are
    ``None`` (success), a DisplayError kind (raise it) or ``("hang", s)``.
    ``latency`` (seconds per transfer) and ``throughput`` (bytes/s) emulate a
    real link, e.g. ~1 MB/s for a CDC-ACM serial panel.
    """

    DRIVER = "simulated"

    def __init__(self, size=(480, 320), connected=True, fail_open=0, shape="rect", latency=0.0, throughput=None,
                 model="Simulated panel"):
        self.size = size
        self.latency, self.throughput, self.model = latency, throughput, model
        self.capabilities = Capabilities(native_size=size, encoding="rgb888", transport="memory", shape=shape)
        self.native_size = (0, 0)
        self.connected = connected
        self.fail_open = fail_open
        self.faults = []
        self.is_open = False
        self.frames = 0
        self.full_frames = 0
        self.last_image = None
        self.brightness = None
        self.opens = 0
        self.info = None
        self._prev = None

    def _maybe_fail(self, what):
        if not self.connected:
            self.is_open = False
            raise DisplayError(DISCONNECTED, f"simulated {what}: unplugged")
        if self.faults:
            fault = self.faults.pop(0)
            if isinstance(fault, tuple) and fault[0] == "hang":
                time.sleep(fault[1])
            elif fault:
                self._prev = None
                raise DisplayError(fault, f"simulated {what} fault")

    def open(self):
        if not self.connected:
            raise DisplayError(NOT_FOUND, "simulated display unplugged")
        if self.fail_open > 0:
            self.fail_open -= 1
            raise DisplayError(IO, "simulated open failure")
        self.opens += 1
        self.is_open = True
        self.native_size = self.size
        self._prev = None
        self.info = DeviceInfo(self.DRIVER, self.model, *self.size, location="memory")
        return self.info

    def close(self):
        self.is_open = False
        self._prev = None

    def probe(self):
        self._maybe_fail("probe")

    def set_brightness(self, percent):
        self._maybe_fail("brightness")
        self.brightness = percent

    def invalidate(self):
        self._prev = None

    def present(self, image):
        if not self.is_open:
            raise DisplayError(DISCONNECTED, "simulated display not open")
        if image.size != self.native_size:
            raise ValueError(f"frame {image.size} != panel {self.native_size}")
        self._maybe_fail("present")
        pixels = frames.image_to_rgb565(image)
        rects = frames.plan_rects(pixels, self._prev, 32, 16, 64)
        if rects == []:
            return Transfer()
        full = rects is None
        self._prev = pixels
        self.frames += 1
        self.full_frames += int(full)
        self.last_image = image.copy()
        area = image.size[0] * image.size[1] if full else sum(map(frames.rect_area, rects))
        delay = self.latency + (area * 2 / self.throughput if self.throughput else 0.0)
        if delay:
            time.sleep(delay)
        return Transfer(area * 2, 1 if full else len(rects), full, delay)


