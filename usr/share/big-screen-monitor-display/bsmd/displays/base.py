"""Common types for display drivers.

Driver contract (every family):

* ``open()`` connects, runs the family handshake and leaves the panel ready
  for frames of ``native_size`` (always landscape, width >= height). The
  runtime rotates frames for portrait or upside-down mounting, so drivers
  never need a software orientation of their own.
* ``present(image)`` sends one frame and returns a :class:`Transfer`.
* ``set_brightness(percent)``, ``probe()``, ``invalidate()``, ``close()``.
* ``capabilities`` describes what the hardware offers; the GUI only shows
  what a device really supports.

Failures always raise :class:`DisplayError` with a kind the recovery state
machine understands. Panels never confirm what they show: a successful
transfer means the device accepted the data.
"""

import time
from dataclasses import dataclass, field

from .. import frames

NOT_FOUND = "not_found"
PERMISSION = "permission"
DISCONNECTED = "disconnected"
TIMEOUT = "timeout"
IO = "io"
PROTOCOL = "protocol"
BUSY = "busy"            # another program holds the device

FATAL_KINDS = {NOT_FOUND, PERMISSION, DISCONNECTED, BUSY}
# Conditions a process restart cannot fix: retry slowly, never escalate to FAILED.
EXTERNAL_KINDS = {PERMISSION, BUSY}


class DisplayError(Exception):
    def __init__(self, kind, message, cause=None):
        super().__init__(message)
        self.kind = kind
        self.cause = cause

    def __str__(self):
        text = super().__str__()
        return f"{self.kind}: {text}" + (f" ({self.cause})" if self.cause else "")


@dataclass
class Transfer:
    bytes: int = 0
    rects: int = 0
    full: bool = False
    duration: float = 0.0


@dataclass
class Capabilities:
    native_size: tuple = (0, 0)          # landscape frame size accepted by present()
    encoding: str = "rgb565le"           # rgb565le, rgb565be, bgr, bgra, png/jpeg
    brightness: bool = True
    brightness_steps: int = 101          # 2 = on/off only
    partial_update: bool = True
    leds: bool = False                   # backplate RGB LEDs
    sensors: tuple = ()                  # e.g. ("room_temperature", "humidity")
    shape: str = "rect"                  # rect or round
    transport: str = "serial"            # serial or usb
    max_payload: int = 0                 # bytes per transfer, 0 = unlimited
    notes: tuple = ()

    def as_dict(self):
        return {key: (list(value) if isinstance(value, tuple) else value)
                for key, value in self.__dict__.items()}


@dataclass
class DeviceInfo:
    driver: str
    model: str
    width: int
    height: int
    location: str = ""
    details: dict = field(default_factory=dict)


def percent(value):
    return max(0, min(100, int(value)))


class RasterDriver:
    """Partial-update logic shared by drivers that accept rectangles.

    Subclasses implement ``_blit(image, rect)`` (send the region of a full
    frame) and may tune the tile grid. Changes are detected on packed RGB888
    values, so colours finer than RGB565 are not lost for true-colour panels.
    """

    TILE = (32, 16)
    MAX_RECTS = 16
    FULL_REFRESH_RATIO = 0.6
    DRIVER = "raster"

    def __init__(self):
        self.native_size = (0, 0)
        self.capabilities = Capabilities()
        self.info = None
        self._prev = None

    def invalidate(self):
        self._prev = None

    def _blit(self, image, rect):
        raise NotImplementedError

    def _blit_full(self, image):
        return self._blit(image, (0, 0, *self.native_size))

    def present(self, image):
        if image.size != self.native_size:
            raise ValueError(f"frame {image.size} != panel {self.native_size}")
        start = time.monotonic()
        key = frames.image_key(image)
        width, height = self.native_size
        rects = None
        if self.capabilities.partial_update:
            rects = frames.plan_rects(key, self._prev, *self.TILE, self.MAX_RECTS)
        elif self._prev is not None and self._prev.shape == key.shape and not (key != self._prev).any():
            rects = []
        if rects == []:
            return Transfer(duration=time.monotonic() - start)
        if rects is not None and sum(map(frames.rect_area, rects)) > width * height * self.FULL_REFRESH_RATIO:
            rects = None
        try:
            if rects is None:
                sent, count = self._blit_full(image), 1
            else:
                sent, count = sum(self._blit(image, rect) for rect in rects), len(rects)
        except BaseException:
            self._prev = None
            raise
        self._prev = key
        return Transfer(sent, count, rects is None, time.monotonic() - start)
