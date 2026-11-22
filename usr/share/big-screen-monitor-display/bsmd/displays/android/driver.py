"""AndroidDisplay: a phone or tablet running the Big Screen Monitor Display app.

The themes are drawn here, by the same renderer as every USB panel; the app
only decodes rectangles and shows them (one implementation of every theme,
so Kojiro layouts, Brother Away stories and Big Media Player skins look the
same on a phone as on a panel).

* Size: the app reports its usable area; frames are drawn at that aspect,
  scaled down to ``android_resolution`` (or the performance profile) and
  scaled up on the phone with filtering. The phone rotates itself
  (``capabilities.orientation == "device"``): the runtime never rotates
  frames for it, it asks the phone to lock or follow the sensor instead.
* Frames: dirty rectangles (fill, RGB+zlib, JPEG for photographic areas),
  then PRESENT; the next frame waits for the phone's PRESENTED of the
  previous one, so at most one frame is in flight and nothing goes stale.
* Input: touches arrive from the link's I/O thread and are handed to
  ``on_input`` (the session's touch interface); commands from the app's own
  menu go to ``on_command`` (an explicit list, validated by the session).
"""

import collections
import logging
import threading
import time

from ..base import DISCONNECTED, NOT_FOUND, TIMEOUT, Capabilities, DeviceInfo, DisplayError, \
    RasterDriver, percent
from . import protocol as bsdp

log = logging.getLogger("bsmd")

RESOLUTION_LIMITS = {"economy": 960, "balanced": 1280, "auto": 1280, "fluid": 1920}
NATIVE_LIMIT = 2560
ORIENTATION_LOCKS = {"horizontal": "landscape", "vertical": "portrait",
                     "horizontal_flipped": "reverse_landscape", "vertical_flipped": "reverse_portrait"}
COMMANDS = ("menu", "theme_next", "theme_prev", "set", "media", "close_overlay")
MAX_COMMANDS_PER_SECOND = 20
MAX_EVENTS = 256


def render_size(view, settings):
    """Size the themes draw at for a view of ``view`` (w, h) pixels."""
    w, h = view
    choice = settings.get("android_resolution", "auto")
    if choice == "native":
        limit = NATIVE_LIMIT
    elif choice.isdigit():
        limit = int(choice)
    else:
        limit = RESOLUTION_LIMITS.get(settings.get("performance_profile", "auto"), 1280)
    scale = min(1.0, limit / max(w, h))
    return max(64, int(round(w * scale))), max(64, int(round(h * scale)))


class AndroidDisplay(RasterDriver):
    DRIVER = "android"
    TILE = (32, 32)
    MAX_RECTS = 24
    TIGHT_RECTS = True
    FULL_REFRESH_RATIO = 0.6
    PRESENT_TIMEOUT = 6.0
    PING_TIMEOUT = 4.0

    def __init__(self, link, settings=None, clock=time.monotonic, release=None):
        super().__init__()
        if link is None:
            raise DisplayError(NOT_FOUND, "the phone is not connected")
        self.link = link
        self.hello = link.hello
        self.settings = dict(settings or {})
        self.clock = clock
        self.release = release            # called on close (hands the device id back to the hub)
        self.on_input = None              # callable(TouchEvent) - the session's touch interface
        self.on_command = None            # callable(name, body) - commands from the app's own menu
        self.on_wake = None               # callable() - render again (the phone rotated)
        self.events = collections.deque(maxlen=MAX_EVENTS)
        self.view = self.hello.view
        self._pending_view = None
        self.cond = threading.Condition()
        self._frame_id = 0
        self._awaiting = None             # frame id sent, not yet presented
        self._presented_at = {}
        self._cmd_window = (0.0, 0)
        self._config_sent = None
        self.device_stats = {}
        self.stats = {"presented": 0, "decode_ms": 0, "round_trip_ms": 0.0, "touch_events": 0, "bytes": 0,
                      "formats": collections.Counter(), "commands": 0, "dropped_commands": 0}
        self.capabilities = Capabilities(encoding="rgb888+zlib/jpeg", brightness=self.hello.brightness,
                                         brightness_steps=101, partial_update=True,
                                         transport="usb" if link.transport.startswith("usb") else "network",
                                         touch="single" if self.hello.touch else "", orientation="device")

    # ------------------------------------------------------------ contract
    def open(self):
        if not self.link.alive:
            raise DisplayError(DISCONNECTED, "the phone disconnected")
        self.native_size = render_size(self.view, self.settings)
        self.capabilities.native_size = self.native_size
        hello = self.hello
        model = " ".join(part for part in (hello.manufacturer, hello.model) if part) or "Android"
        details = {"android": hello.android, "sdk": hello.sdk, "app": hello.app_version,
                   "screen": f"{hello.screen[0]}x{hello.screen[1]}", "density_dpi": hello.density,
                   "transport": self.link.transport, "address": self.link.address,
                   "tls": self.link.tls, "touch": "single" if hello.touch else "none"}
        self.info = DeviceInfo(self.DRIVER, model, *self.native_size,
                               location=f"{self.link.transport} {self.link.address}".strip(), details=details)
        self._prev = None
        self.link.set_handler(self._on_message)
        self.apply_settings(self.settings, force=True)
        log.info("[android] %s (%s, Android %s) %dx%d view, drawing %dx%d over %s", hello.name, model,
                 hello.android, *self.view, *self.native_size, self.link.transport)
        return self.info

    def close(self):
        link, self.link = self.link, None
        if link is not None:
            link.set_handler(None)
            link.close("display closed", bye="closed")
            if self.release is not None:
                self.release(link)
        with self.cond:
            self.cond.notify_all()
        self._prev = None

    def _check(self):
        link = self.link
        if link is None:
            raise DisplayError(DISCONNECTED, "android display not open")
        if not link.alive:
            raise link.error or DisplayError(DISCONNECTED, "the phone disconnected")
        return link

    def apply_settings(self, settings, force=False):
        """Send what the app needs to know (orientation, screen options) and
        pick a new drawing size when the resolution choice changed."""
        self.settings = dict(settings)
        size = render_size(self._pending_view or self.view, self.settings)
        if size != self.native_size and self.native_size != (0, 0):
            self._resize(self._pending_view or self.view)
        orientation = "auto" if settings.get("android_auto_rotate") else \
            ORIENTATION_LOCKS.get(settings.get("orientation"), "landscape")
        config = {"display_id": self.settings.get("display_id", ""), "name": self.settings.get("name") or "",
                  "orientation": orientation, "keep_screen_on": bool(settings.get("android_keep_screen_on", True)),
                  "burn_in": bool(settings.get("android_burn_in", True)),
                  "touch": bool(settings.get("touch_enabled", True)), "theme": settings.get("theme", ""),
                  "quality": settings.get("android_quality", "auto"),
                  "profile": settings.get("performance_profile", "auto"),
                  "resolution": settings.get("android_resolution", "auto"),
                  "canvas": list(self.native_size)}
        if force or config != self._config_sent:
            self._config_sent = config
            self._check().send(bsdp.json_message(bsdp.CONFIG, config))

    def _resize(self, view):
        self.view = view
        self.native_size = render_size(view, self.settings)
        self.capabilities.native_size = self.native_size
        if self.info is not None:
            self.info.width, self.info.height = self.native_size
        self._prev = None

    def _quality(self):
        choice = self.settings.get("android_quality", "auto")
        if choice != "auto":
            return choice
        if self.link is not None and self.link.transport.startswith("usb"):
            return "lossless"             # the cable has bandwidth to spare
        return {"economy": "economy", "fluid": "balanced"}.get(self.settings.get("performance_profile"),
                                                               "balanced")

    def _blit(self, image, rect):
        link = self._check()
        encoded = bsdp.encode_rect(image, rect, self.native_size, self._quality(), self.hello.formats)
        self.stats["formats"][bsdp.FORMAT_NAMES[encoded.fmt]] += 1
        sent = link.send(bsdp.message(bsdp.RECT, encoded.payload), timeout=self.PRESENT_TIMEOUT)
        self.stats["bytes"] += sent
        return sent

    def present(self, image):
        link = self._check()
        if self._pending_view is not None:
            view, self._pending_view = self._pending_view, None
            self._resize(view)
            self.apply_settings(self.settings)
        if image.size != self.native_size:
            image = image.resize(self.native_size)
        self._wait_presented()
        transfer = super().present(image)
        if not transfer.rects:
            return transfer
        start = self.clock()
        with self.cond:
            self._frame_id = (self._frame_id + 1) & 0xFFFFFFFF
            frame_id = self._frame_id
            self._awaiting = frame_id
            self._presented_at[frame_id] = start
        try:
            link.send(bsdp.present(frame_id, self.native_size), timeout=self.PRESENT_TIMEOUT)
        except BaseException:
            self._prev = None
            raise
        transfer.duration += self.clock() - start
        return transfer

    def _wait_presented(self):
        """At most one frame in flight: wait for the phone to show the previous one."""
        deadline = self.clock() + self.PRESENT_TIMEOUT
        with self.cond:
            while self._awaiting is not None:
                link = self.link
                if link is None or not link.alive:
                    self._prev = None
                    raise (link.error if link is not None and link.error else
                           DisplayError(DISCONNECTED, "the phone disconnected"))
                remaining = deadline - self.clock()
                if remaining <= 0:
                    self._awaiting = None
                    self._prev = None
                    raise DisplayError(TIMEOUT, "the phone stopped showing frames")
                self.cond.wait(min(remaining, 0.25))

    def set_brightness(self, value):
        if self.link is None or not self.capabilities.brightness:
            return
        self._check().send(bsdp.message(bsdp.BRIGHTNESS, bytes([percent(value)])))

    def probe(self):
        link = self._check()
        token = int(self.clock() * 1000) & 0xFFFFFFFF
        with self.cond:
            self._pong = None
        link.send(bsdp.message(bsdp.PING, bsdp.TOKEN_BODY.pack(token)))
        deadline = self.clock() + self.PING_TIMEOUT
        with self.cond:
            while getattr(self, "_pong", None) != token:
                self._check()
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DisplayError(TIMEOUT, "the phone does not answer")
                self.cond.wait(min(remaining, 0.25))

    def poll_input(self):
        events = []
        while self.events:
            events.append(self.events.popleft())
        return events

    # ------------------------------------------------------------ incoming (link I/O thread)
    def _on_message(self, _link, msg):
        kind = msg.kind
        if kind == bsdp.TOUCH:
            event = bsdp.TouchEvent.parse(msg.payload, self.clock())
            if event.kind == bsdp.TOUCH_CANCEL:
                event.kind = bsdp.TOUCH_UP
            self.stats["touch_events"] += 1
            width, height = self.native_size
            event.x, event.y = min(event.x, width - 1), min(event.y, height - 1)
            callback = self.on_input
            if callback is None:
                self.events.append(event)
                return
            try:
                callback(event)
            except Exception:  # noqa: BLE001 - a UI bug must not end the link
                log.exception("[android] touch handler failed")
        elif kind == bsdp.PRESENTED:
            frame_id, decode_ms, _queued = bsdp.parse_presented(msg.payload)
            with self.cond:
                started = self._presented_at.pop(frame_id, None)
                if frame_id == self._awaiting:
                    self._awaiting = None
                if len(self._presented_at) > 8:
                    self._presented_at.clear()
                self.cond.notify_all()
            self.stats["presented"] += 1
            self.stats["decode_ms"] = decode_ms
            if started is not None:
                self.stats["round_trip_ms"] = round((self.clock() - started) * 1000.0, 1)
        elif kind == bsdp.PONG:
            with self.cond:
                self._pong = bsdp.parse_token(msg.payload)
                self.cond.notify_all()
        elif kind == bsdp.VIEW:
            view = bsdp.parse_view(msg.json())
            if view != self.view:
                self._pending_view = view
                wake = self.on_wake
                if wake is not None:
                    wake()
        elif kind == bsdp.STATS:
            body = msg.json()
            self.device_stats = {key: body[key] for key in ("fps", "decode_ms", "dropped", "battery", "charging",
                                                            "temperature", "rx_kbps", "uptime_s", "screen_on")
                                 if isinstance(body.get(key), (int, float, bool))}
        elif kind == bsdp.COMMAND:
            self._command(msg.json())
        elif kind in (bsdp.HELLO, bsdp.AUTH, bsdp.PAIR):
            raise bsdp.ProtocolError("handshake message after the handshake")

    def _command(self, body):
        now = self.clock()
        start, count = self._cmd_window
        if now - start >= 1.0:
            start, count = now, 0
        self._cmd_window = (start, count + 1)
        name = body.get("cmd")
        if count >= MAX_COMMANDS_PER_SECOND or name not in COMMANDS:
            self.stats["dropped_commands"] += 1
            return
        self.stats["commands"] += 1
        callback = self.on_command
        if callback is not None:
            try:
                callback(name, body)
            except Exception:  # noqa: BLE001
                log.exception("[android] command %s failed", name)
