"""Service runtime: discovery, one pipeline per display, recovery and supervision.

Threads
    telemetry      - bsmd.telemetry.Collector (1 s cadence), shared by every display
    render:<id>    - asks the display's theme for a frame, posts it to its mailbox
    transport:<id> - owns that display's driver: connect, present, brightness, recovery
    main           - supervisor: discovery (hot-plug), settings reload, watchdog,
                     status file, command spool

Each display is a :class:`DisplaySession` with its own link state machine,
backoff, theme and statistics, so a failing panel never stalls or resets the
others. Only a session's transport thread touches its device. The supervisor
pings the systemd watchdog only while every subsystem of every session keeps
making progress; a thread stuck inside a call stops the pings and systemd
restarts the process (WatchdogSec=).
"""

import collections
import copy
import json
import logging
import os
import queue
import signal
import threading
import time
from datetime import datetime

from PIL import Image, ImageDraw

from . import __version__, frames, health, i18n, patterns, settings as settings_mod, telemetry, themes
from .displays import discovery, registry
from .displays.ax206 import AX206
from .displays.base import DISCONNECTED as GONE, EXTERNAL_KINDS, FATAL_KINDS, IO, NOT_FOUND, PROTOCOL, TIMEOUT, DisplayError, Transfer
from .health import (DEGRADED, DISCONNECTED, FAILED, HEALTHY, RECOVERING, RETRYING, STARTING,
                     STOPPED)
from .settings import atomic_write_json

log = logging.getLogger("bsmd")

# Character poses are drawn "on twos" (8 drawings per second), so the automatic
# profile stops at 8 fps; "fluid" makes walking and weather smoother.
FPS_PROFILES = {"economy": 4.0, "balanced": 8.0, "fluid": 15.0, "auto": 8.0}
# Panels behind slow links get a lower automatic ceiling (whole frames over
# serial at 115200 baud-class throughput, or PNG/JPEG encoding per frame).
TRANSPORT_FPS_CAP = {"turing_rev_c": 4.0, "turing_usb": 6.0, "xuanfang_rev_b": 6.0}
LED_RGB = {"off": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 255, 0),
           "blue": (0, 0, 255), "cyan": (0, 255, 255), "magenta": (255, 0, 255), "yellow": (255, 255, 0),
           "orange": (255, 128, 0), "purple": (128, 0, 255)}
MAX_SPOOL_FILES = 32


def runtime_dir():
    base = os.environ.get("RUNTIME_DIRECTORY", "").split(":")[0]
    if not base:
        base = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/bsmd-{os.getuid()}",
                            "big-screen-monitor-display")
    return base


def state_dir():
    base = os.environ.get("STATE_DIRECTORY", "").split(":")[0]
    if not base:
        base = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                            "big-screen-monitor-display")
    return base


def status_path():
    return os.path.join(runtime_dir(), "status.json")


class RenderContext:
    """What a theme may know about the pipeline when drawing a frame."""

    def __init__(self, runtime=None, preview=False, session=None):
        self.runtime = runtime
        self.session = session
        self.preview = preview
        self.target_fps = 8.0
        self.state_dir = state_dir()
        self.on_battery = False
        self.shape = "rect"
        self.display_id = session.id if session else None

    def telemetry(self):
        return telemetry.snapshot()


# ---------------------------------------------------------------- sources

class SimulatedSource:
    """A SimulatedDisplay standing in for a USB panel (tests, --simulate)."""

    def __init__(self, panel):
        self.panel = panel
        self.profile = None

    def present(self):
        return self.panel.connected

    def create(self, _settings):
        return self.panel

    def describe(self):
        return {"profile": "simulated", "name": "Simulated panel", "confidence": "confirmed",
                "transport": "memory", "validation": "-", "ids": None, "port": None}


class UsbSource:
    """A physical port; the device behind it is looked up at every connection."""

    def __init__(self, runtime, display_id):
        self.runtime = runtime
        self.display_id = display_id
        self.profile = None

    def candidate(self):
        return self.runtime.candidates.get(self.display_id)

    def present(self):
        candidate = self.candidate()
        return candidate is not None and self.runtime.profile_for(candidate) is not None

    def create(self, settings):
        candidate = self.candidate()
        profile = self.runtime.profile_for(candidate) if candidate else None
        if profile is None:
            raise DisplayError(NOT_FOUND, "display not connected")
        self.profile = profile
        if candidate.asleep and profile.id == "turing_rev_c" and candidate.port:
            # Opening the port wakes the panel; it then re-enumerates on the
            # same USB port with a new identity, picked up by discovery.
            from .displays.turing_serial import wake_rev_c
            wake_rev_c(candidate.port)
            raise DisplayError(NOT_FOUND, "rev. C panel woken up, waiting for it to re-enumerate")
        return profile.create(candidate, discovery.driver_options(settings))

    def describe(self):
        candidate = self.candidate()
        profile = self.profile or (self.runtime.profile_for(candidate) if candidate else None)
        result = {"profile": profile.id if profile else None, "name": profile.name if profile else None,
                  "transport": profile.transport if profile else None,
                  "validation": profile.validation if profile else None,
                  "confidence": candidate.confidence if candidate else None,
                  "ids": candidate.device.ids if candidate else None,
                  "serial": candidate.device.serial if candidate else None,
                  "port": candidate.port if candidate else None,
                  "usb_path": candidate.device.path if candidate else None}
        return result


# ---------------------------------------------------------------- session

class DisplaySession:
    """One panel: render and transport threads, link state, recovery, stats."""

    def __init__(self, runtime, display_id, source):
        self.runtime = runtime
        self.id = display_id
        self.source = source
        clock = self.clock = runtime.clock
        self.hb = {name: health.Heartbeat(f"{display_id}/{name}", clock) for name in ("render", "transport")}
        self.link = health.LinkStateMachine(clock, self._on_link_change)
        self.mailbox = frames.FrameMailbox()
        self.commands = queue.Queue()
        self.stop_event = threading.Event()
        self.wake_render = threading.Event()
        self.backoff = copy.deepcopy(runtime.backoff)
        self.backoff.reset()
        self.ctx = RenderContext(runtime, session=self)
        self.driver = None
        self.device_info = None
        self.failed_attempts = 0
        self.recoveries = 0
        self.recovery_started = None
        self.next_attempt = 0.0
        self.last_io = clock()
        self.last_full = clock()
        self.last_sensors = 0.0
        self.intro_shown = False
        self.theme = None
        self.pattern = None            # (name, until) while a test pattern is shown
        self.sensors = {}
        self.stats = {"frames_sent": 0, "full_frames": 0, "bytes_sent": 0, "unchanged": 0,
                      "last_transfer_wall": None, "fps": 0.0, "transfer_ms": 0.0}
        self._threads = []
        self._theme_failures = 0
        self._sent_times = collections.deque(maxlen=256)
        self._applied = None

    # ------------------------------------------------------------ helpers
    def _on_link_change(self, old, new, reason):
        log.info("[%s] link state %s -> %s%s", self.id, old, new, f" ({reason})" if reason else "")
        self.runtime._notify_status()

    def record(self, kind, severity, message, **fields):
        return self.runtime.incidents.record(kind, severity, message, display=self.id, **fields)

    def settings(self):
        return settings_mod.merged(self.runtime.store.get(), self.id)

    def name(self):
        name = self.settings().get("name")
        if name:
            return name
        if self.device_info:
            return self.device_info.model
        return self.source.describe().get("name") or self.id

    def _render_size(self, settings):
        if not self.device_info:
            return None
        native = self.driver.native_size if self.driver else (self.device_info.width, self.device_info.height)
        return frames.render_size(native, settings.get("orientation"))

    def _model_name(self):
        return self.device_info.model if self.device_info else None

    def request(self, command, *args):
        self.commands.put((command, *args))

    def apply_settings(self):
        """Compare the effective settings with the last applied ones."""
        new = self.settings()
        old, self._applied = self._applied, new
        if old is None:
            return
        if new.get("brightness") != old.get("brightness"):
            self.request("brightness", new["brightness"])
        if any(new.get(key) != old.get(key) for key in ("profile", "model", "rev_c_size")):
            self.request("reconnect", "display model changed")
        if new.get("led_color") != old.get("led_color"):
            self.request("leds", new.get("led_color"))
        if new.get("orientation") != old.get("orientation"):
            self.request("invalidate")
        self.wake_render.set()

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self._applied = self.settings()
        for name, target in (("render", self._render_loop), ("transport", self._transport_loop)):
            thread = threading.Thread(target=self._guarded(name, target), name=f"{name}:{self.id}", daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self):
        self.stop_event.set()
        self.wake_render.set()

    def join(self, timeout):
        for thread in self._threads:
            thread.join(timeout=timeout)

    def dead_threads(self):
        return [t.name for t in self._threads if not t.is_alive()]

    def _guarded(self, name, target):
        def runner():
            try:
                target()
            except Exception as error:  # noqa: BLE001
                # A dead pipeline thread must never look healthy: report it
                # and let the supervisor stop the watchdog pings.
                log.exception("[%s] %s thread crashed", self.id, name)
                self.record("thread_crash", health.SEVERITY_CRITICAL, f"{name} thread crashed: {error!r}",
                            thread=name)
                self.hb[name].last_progress = -1e9
        return runner

    def stalled_reasons(self):
        runtime = self.runtime
        reasons = []
        for name, beat in self.hb.items():
            reason = beat.stalled(runtime.PROGRESS_TIMEOUT[name], runtime.OP_TIMEOUT[name])
            if reason:
                reasons.append(f"[{self.id}] {reason}")
        dead = self.dead_threads()
        if dead and not self.stop_event.is_set():
            reasons.append(f"threads not running: {', '.join(dead)}")
        return reasons

    # ------------------------------------------------------------ render
    def _target_fps(self, settings):
        profile = settings.get("performance_profile", "auto")
        cap = FPS_PROFILES.get(profile, FPS_PROFILES["auto"])
        if profile == "auto":
            if telemetry.SYSTEM_STATS.get("on_battery"):
                cap = min(cap, FPS_PROFILES["economy"])
            driver_id = getattr(self.driver, "DRIVER", None)
            cap = min(cap, TRANSPORT_FPS_CAP.get(driver_id, cap))
            cost = self.hb["render"].avg_duration + self.stats["transfer_ms"] / 1000.0
            if cost > 0:
                # Keep the pipeline at most ~60 % busy.
                cap = min(cap, max(2.0, 0.6 / cost))
        return cap

    def _render_pattern(self, size):
        name, until = self.pattern
        if self.clock() >= until:
            self.pattern = None
            self.request("invalidate")      # restore the theme with a full frame
            return None
        return patterns.render(name, size[0], size[1], label=self.name(), display_id=self.id,
                               shape=self.ctx.shape)

    def _render_loop(self):
        beat = self.hb["render"]
        theme = None
        theme_key = None
        while not self.stop_event.is_set():
            settings = self.settings()
            size = self._render_size(settings) if self.driver else None
            if size is None:
                beat.progress()
                self.wake_render.wait(0.5)
                self.wake_render.clear()
                continue
            if self.pattern is not None:
                image = self._render_pattern(size)
                if image is not None:
                    beat.progress()
                    self.mailbox.put(image)
                    self.mailbox.wait_consumed(timeout=2.0)
                    self.wake_render.wait(0.5)
                    self.wake_render.clear()
                    continue
            key = (settings.get("theme"), size)
            if key != theme_key:
                if theme:
                    theme.close()
                theme = themes.create(settings.get("theme"), self.ctx)
                theme_key = key
                self.theme = theme
                self._theme_failures = 0
                self.runtime.wake_collector_needs()
            self.ctx.target_fps = self._target_fps(settings)
            self.ctx.on_battery = bool(telemetry.SYSTEM_STATS.get("on_battery"))
            started = self.clock()
            beat.begin("render")
            try:
                image = themes.render_for_panel(theme, size[0], size[1], settings, self.ctx)
            except Exception as error:  # noqa: BLE001 - a theme bug must not stop the panel
                beat.end(False, repr(error))
                self._theme_failures += 1
                log.exception("[%s] theme %s failed", self.id, theme.info.id)
                if self._theme_failures in (1, 3):
                    self.record("render_error", health.SEVERITY_ERROR, f"theme {theme.info.id}: {error!r}",
                                attempts=self._theme_failures)
                if self._theme_failures >= 3 and theme.info.id != themes.FALLBACK:
                    theme.close()
                    theme = themes.create(themes.FALLBACK, self.ctx)
                    self.theme = theme
                    self.record("theme_fallback", health.SEVERITY_WARNING,
                                f"switched to '{themes.FALLBACK}' after repeated failures")
                self.stop_event.wait(1.0)
                continue
            beat.end(True)
            self.mailbox.put(image)
            interval = theme.frame_interval(settings, self.ctx)
            deadline = started + interval
            # Backpressure: never render further ahead than one frame.
            self.mailbox.wait_consumed(timeout=2.0)
            remaining = deadline - self.clock()
            if remaining > 0:
                self.wake_render.wait(remaining)
            self.wake_render.clear()
        if theme:
            theme.close()

    # ------------------------------------------------------------ transport
    def _transport_loop(self):
        beat = self.hb["transport"]
        while not self.stop_event.is_set():
            self._drain_commands()
            if self.driver is None:
                self._connect_step()
                continue
            frame = self.mailbox.take(timeout=0.5)
            now = self.clock()
            if frame is None:
                if now - self.last_io > self.runtime.IDLE_PROBE_AFTER:
                    self._io("probe", self.driver.probe)
                else:
                    beat.progress()
                continue
            if now - self.last_full > self.runtime.FULL_REFRESH_EVERY:
                self.driver.invalidate()
                self.last_full = now
            if self.driver.capabilities.sensors and now - self.last_sensors > 5.0:
                self.last_sensors = now
                self._read_sensors()
            image = frames.to_native(frame, self.driver.native_size, self.settings().get("orientation"))
            self._io("present", lambda: self.driver.present(image))
        self._close_display()

    def _read_sensors(self):
        values = self._io("sensors", self.driver.read_sensors)
        if values:
            self.sensors = {name: value for name, value in zip(self.driver.capabilities.sensors, values)
                            if value is not None}

    def _drain_commands(self):
        while True:
            try:
                command, *args = self.commands.get_nowait()
            except queue.Empty:
                return
            if command == "pattern":
                self.pattern = (args[0], self.clock() + (args[1] if len(args) > 1 else 10.0))
                self.wake_render.set()
                if self.driver is not None:
                    self.driver.invalidate()
            elif command == "clear_pattern":
                if self.pattern is not None:
                    self.pattern = (self.pattern[0], 0.0)
                self.wake_render.set()
            elif self.driver is None:
                continue
            elif command == "brightness":
                self._io("brightness", lambda value=args[0]: self.driver.set_brightness(value))
            elif command == "leds":
                self._apply_leds(args[0])
            elif command == "invalidate":
                self.driver.invalidate()
            elif command in ("reconnect", "recover"):
                self.record("recovery_requested", health.SEVERITY_INFO, args[0], model=self._model_name())
                self._begin_recovery(args[0])

    def _apply_leds(self, color):
        if self.driver is not None and self.driver.capabilities.leds and hasattr(self.driver, "set_leds"):
            self._io("leds", lambda: self.driver.set_leds(LED_RGB.get(color, (0, 0, 0))))

    def _io(self, op, func):
        beat = self.hb["transport"]
        beat.begin(op)
        try:
            result = func()
        except DisplayError as error:
            beat.end(False, str(error))
            self._handle_error(error, op)
            return None
        except Exception as error:  # noqa: BLE001 - unexpected driver bug: recover, don't die
            beat.end(False, repr(error))
            log.exception("[%s] unexpected error during %s", self.id, op)
            self._handle_error(DisplayError(PROTOCOL, f"unexpected {op} error", error), op)
            return None
        beat.end(True)
        self.last_io = self.clock()
        if self.link.state == DEGRADED:
            self.link.to(HEALTHY, f"{op} succeeded")
        if isinstance(result, Transfer):
            self._account(result)
        return result

    def _account(self, transfer):
        if not transfer.bytes:
            self.stats["unchanged"] += 1
            return
        self.stats["frames_sent"] += 1
        self.stats["full_frames"] += int(transfer.full)
        self.stats["bytes_sent"] += transfer.bytes
        self.stats["last_transfer_wall"] = time.time()
        now = self.clock()
        self._sent_times.append(now)
        while self._sent_times and now - self._sent_times[0] > 5.0:
            self._sent_times.popleft()
        span = now - self._sent_times[0]
        self.stats["fps"] = (len(self._sent_times) - 1) / span if span > 0 else 0.0
        ms = transfer.duration * 1000
        self.stats["transfer_ms"] = ms if not self.stats["transfer_ms"] else self.stats["transfer_ms"] * 0.8 + ms * 0.2

    def _handle_error(self, error, op):
        beat = self.hb["transport"]
        severity = health.SEVERITY_ERROR if error.kind in FATAL_KINDS else health.SEVERITY_WARNING
        self.record(f"transport_{error.kind}", severity, str(error), operation=op, model=self._model_name(),
                    attempts=beat.consecutive_errors, duration_ms=round(beat.last_duration * 1000, 1))
        if error.kind in FATAL_KINDS or beat.consecutive_errors >= 2:
            self._begin_recovery(f"{op}: {error.kind}")
        else:
            if self.link.state == HEALTHY:
                self.link.to(DEGRADED, f"{op}: {error.kind}")
            if self.driver:
                self.driver.invalidate()

    def _close_display(self):
        driver, self.driver = self.driver, None
        if driver is not None:
            if self.stop_event.is_set() and self.link.state in (HEALTHY, DEGRADED):
                try:
                    settings = self.settings()
                    driver.present(frames.to_native(stopped_frame(*frames.render_size(
                        driver.native_size, settings.get("orientation"))), driver.native_size,
                        settings.get("orientation")))
                except Exception:  # noqa: BLE001 - best effort on shutdown
                    pass
            driver.close()
        if self.link.state != STOPPED and self.stop_event.is_set():
            try:
                self.link.to(STOPPED, "session stopped")
            except health.InvalidTransition:
                pass

    def _begin_recovery(self, reason):
        if self.link.state in (HEALTHY, DEGRADED):
            self.link.to(RECOVERING, reason)
        self.recovery_started = self.clock()
        driver, self.driver = self.driver, None
        self.mailbox.clear()
        if driver is not None:
            driver.close()
        self.next_attempt = 0.0

    def _wait_until(self, deadline):
        remaining = deadline - self.clock()
        if remaining > 0:
            self.stop_event.wait(min(0.5, remaining))
        self.hb["transport"].progress()

    def _connect_step(self):
        beat = self.hb["transport"]
        now = self.clock()
        if now < self.next_attempt:
            self._wait_until(self.next_attempt)
            return
        settings = self.settings()
        if not self.source.present():
            if self.link.state in (STARTING, RECOVERING):
                self.link.to(DISCONNECTED, "display not found")
                self.record("device_absent", health.SEVERITY_WARNING, "display not connected",
                            action="waiting for it")
            if self.link.state == DISCONNECTED:
                self.link.to(RETRYING, "polling for the display")
            self.next_attempt = now + self.runtime.ABSENT_POLL
            beat.progress()
            return
        if self.link.state in (STARTING, FAILED):
            self.link.to(RECOVERING, "display found")
        elif self.link.state == RETRYING:
            self.link.to(RECOVERING, "retrying connection")
        elif self.link.state == DISCONNECTED:
            self.link.to(RETRYING, "display found")
            self.link.to(RECOVERING, "connecting")
        driver = None
        beat.begin("open")
        try:
            driver = self.source.create(settings)
            info = driver.open()
            driver.set_brightness(settings.get("brightness", 70))
            driver.invalidate()
        except DisplayError as error:
            beat.end(False, str(error))
            if driver is not None:
                driver.close()
            self._connect_failed(error, driver)
            return
        except Exception as error:  # noqa: BLE001
            beat.end(False, repr(error))
            log.exception("[%s] unexpected error while opening the display", self.id)
            if driver is not None:
                driver.close()
            self._connect_failed(DisplayError(IO, "unexpected open error", error), driver)
            return
        beat.end(True)
        first = self.device_info is None
        self.driver = driver
        self.device_info = info
        self.ctx.shape = getattr(driver.capabilities, "shape", "rect")
        self.last_io = self.last_full = self.clock()
        took = None if self.recovery_started is None else round(self.clock() - self.recovery_started, 2)
        self.link.to(HEALTHY, "display ready")
        if not first or self.recovery_started is not None:
            self.recoveries += 1
            self.record("recovered", health.SEVERITY_INFO, "display communication restored",
                        model=info.model, attempts=self.failed_attempts + 1, recovery_s=took)
        else:
            log.info("[%s] display ready: %s %dx%d at %s", self.id, info.model, info.width, info.height,
                     info.location)
        self.failed_attempts = 0
        self.backoff.reset()
        self.recovery_started = None
        self._apply_leds(settings.get("led_color", "off"))
        if not self.intro_shown:
            self.intro_shown = True
            self._show_intro(settings)
        self.wake_render.set()

    def _show_intro(self, settings):
        size = self._render_size(settings)
        image = themes.intro_frame(size[0], size[1], settings)
        if image is not None and self.driver is not None:
            self._io("intro", lambda: self.driver.present(
                frames.to_native(image, self.driver.native_size, settings.get("orientation"))))
            self.stop_event.wait(0.6)

    def _connect_failed(self, error, driver):
        runtime = self.runtime
        now = self.clock()
        self.failed_attempts += 1
        if self.recovery_started is None:
            self.recovery_started = now
        self.record(f"connect_{error.kind}", health.SEVERITY_ERROR, str(error), operation="open",
                    attempts=self.failed_attempts, strategy="close + reopen + backoff")
        if error.kind in (NOT_FOUND, GONE):
            # The device went away (or is re-enumerating): poll for it at the
            # absent cadence instead of backing off exponentially.
            if self.link.state == RECOVERING:
                self.link.to(DISCONNECTED, "display vanished")
            self.next_attempt = now + runtime.ABSENT_POLL
            return
        if self.link.state == RECOVERING:
            self.link.to(RETRYING, f"open failed: {error.kind}")
        if (self.failed_attempts == runtime.RESET_PORT_AFTER and isinstance(driver, AX206)
                and error.kind in (TIMEOUT, IO, PROTOCOL)):
            # Escalation: targeted USB reset of this display only (VID/PID and
            # bus/address checked); other USB devices are never touched.
            if self._reset_ax206(driver):
                self.record("usb_reset", health.SEVERITY_WARNING, "USB reset of the display device",
                            attempts=self.failed_attempts)
        if error.kind not in EXTERNAL_KINDS and self.failed_attempts >= runtime.MAX_FAILED_ATTEMPTS:
            self.link.to(FAILED, f"{self.failed_attempts} failed attempts")
            self.record("recovery_failed", health.SEVERITY_CRITICAL, "display present but not responding",
                        attempts=self.failed_attempts,
                        action="process restart by systemd" if runtime.service else "slow retry")
            self.next_attempt = now + 60.0
            return
        delay = self.backoff.next_delay()
        if error.kind in EXTERNAL_KINDS:
            delay = max(delay, 10.0)
        self.next_attempt = now + delay

    @staticmethod
    def _reset_ax206(driver):
        try:
            match = {} if driver.bus is None else {
                "custom_match": lambda d: (d.bus, d.address) == (driver.bus, driver.address)}
            driver.dev = driver._usb.core.find(idVendor=driver.VID, idProduct=driver.PID, **match)
            return driver.reset_port()
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------ status
    def status(self):
        settings = self.settings()
        now = self.clock()
        info = self.device_info
        last_wall = self.stats["last_transfer_wall"]
        driver = self.driver
        return {
            "id": self.id,
            "name": self.name(),
            "enabled": settings.get("enabled", True),
            "state": self.link.state,
            "state_since_s": round(now - self.link.since, 1),
            "connected": driver is not None,
            "source": self.source.describe(),
            "device": None if not info else {"driver": info.driver, "model": info.model, "width": info.width,
                                             "height": info.height, "location": info.location,
                                             "details": {k: v for k, v in info.details.items()
                                                         if isinstance(v, (str, int, float, bool, type(None)))}},
            "capabilities": driver.capabilities.as_dict() if driver is not None else None,
            "settings": {key: settings.get(key) for key in ("theme", "orientation", "brightness",
                                                            "performance_profile", "profile", "led_color")},
            "pipeline": {name: beat.snapshot() for name, beat in self.hb.items()},
            "stats": dict(self.stats, frames_dropped=self.mailbox.dropped,
                          last_transfer_age_s=None if last_wall is None else round(time.time() - last_wall, 1),
                          target_fps=round(self.ctx.target_fps, 1)),
            "recoveries": self.recoveries,
            "failed_attempts": self.failed_attempts,
            "sensors": dict(self.sensors),
            "pattern": self.pattern[0] if self.pattern else None,
            "incidents": [entry for entry in self.runtime.incidents.recent(60)
                          if entry.get("display") == self.id][-15:],
        }


# ---------------------------------------------------------------- runtime

class Runtime:
    PROGRESS_TIMEOUT = {"telemetry": 20.0, "render": 30.0, "transport": 30.0}
    OP_TIMEOUT = {"telemetry": 20.0, "render": 20.0, "transport": 30.0}
    FULL_REFRESH_EVERY = 300.0     # heal panel-side corruption the diff cannot see
    IDLE_PROBE_AFTER = 15.0        # liveness check when a static theme sends nothing
    ABSENT_POLL = 2.0
    DISCOVERY_EVERY = 2.0          # sysfs scan for hot-plugged panels
    SESSION_LINGER = 45.0          # forget a session whose device has been gone this long
    MAX_FAILED_ATTEMPTS = 8
    RESET_PORT_AFTER = 4
    SELF_EXIT_AFTER_STALL = 90.0   # when systemd's watchdog is not configured
    STATUS_EVERY = 2.0
    SUPERVISE_EVERY = 1.0

    def __init__(self, store, notifier=None, simulate=None, service=False,
                 status_file=None, state_directory=None, clock=time.monotonic, scan=None):
        self.store = store
        self.notifier = notifier
        if simulate is not None and not isinstance(simulate, (list, tuple)):
            simulate = [simulate]
        self.simulate = simulate
        self.service = service
        self.clock = clock
        self.scan = scan or discovery.scan_usb
        self.status_file = status_file or status_path()
        self.spool_dir = os.path.join(os.path.dirname(self.status_file), "commands")
        self.state_directory = state_directory or state_dir()
        self.started = clock()
        self.hb = {"telemetry": health.Heartbeat("telemetry", clock)}
        self.idle_link = health.LinkStateMachine(clock, lambda *_: self._notify_status())
        try:
            os.makedirs(self.state_directory, exist_ok=True)
        except OSError:
            pass
        self.incidents = health.IncidentLog(os.path.join(self.state_directory, "incidents.jsonl")
                                            if os.path.isdir(self.state_directory) else None, logger=log)
        self.stop_event = threading.Event()
        self.backoff = health.Backoff(base=1.0, cap=30.0)
        self.collector = telemetry.Collector(self.hb["telemetry"])
        self.sessions = {}              # display id -> DisplaySession (insertion order = primary first)
        self.candidates = {}            # display id -> discovery.Candidate (latest scan)
        self.pending = []               # candidates that need a manual family choice
        self.last_seen = {}
        self.exit_code = 0
        self.stalled_since = None
        self.stall_reported = False
        self._last_discovery = -1e9
        self._last_status_text = None
        self._proc = None
        self._removed_recoveries = 0

    # ------------------------------------------------------------ compatibility
    @property
    def primary(self):
        return next(iter(self.sessions.values()), None)

    @property
    def link(self):
        primary = self.primary
        return primary.link if primary else self.idle_link

    @property
    def driver(self):
        primary = self.primary
        return primary.driver if primary else None

    @property
    def device_info(self):
        primary = self.primary
        return primary.device_info if primary else None

    @property
    def recoveries(self):
        return self._removed_recoveries + sum(s.recoveries for s in list(self.sessions.values()))

    @property
    def theme(self):
        primary = self.primary
        return primary.theme if primary else None

    # ------------------------------------------------------------ helpers
    def _settings(self):
        return self.store.get()

    def overall_state(self):
        sessions = list(self.sessions.values())
        if not sessions:
            return self.idle_link.state
        states = [s.link.state for s in sessions]
        if all(state == HEALTHY for state in states):
            return HEALTHY
        if any(state in (HEALTHY, DEGRADED) for state in states):
            return DEGRADED
        return states[0]

    def _status_text(self):
        sessions = [s for s in list(self.sessions.values()) if s.device_info and s.driver]
        state = self.overall_state()
        if state in (HEALTHY, DEGRADED) and len(sessions) == 1:
            session = sessions[0]
            info = session.device_info
            return (f"{state}: {info.model} {info.width}x{info.height}, "
                    f"theme {session.settings().get('theme')}, {session.stats['fps']:.1f} fps")
        if state in (HEALTHY, DEGRADED) and sessions:
            names = ", ".join(f"{s.device_info.model} {s.device_info.width}x{s.device_info.height}"
                              for s in sessions)
            return f"{state}: {len(sessions)} displays ({names})"
        if state in (DISCONNECTED, RETRYING):
            return f"{state}: waiting for a supported display"
        return state

    def _notify_status(self):
        if self.notifier:
            text = self._status_text()
            if text != self._last_status_text:
                self._last_status_text = text
                self.notifier.status(text)

    def request(self, command, *args, display=None):
        """Queue a command for one display (``display``) or all of them."""
        if command == "reload":
            self.store.refresh(force=True)
            self._apply_settings(set(self._settings()))
            return
        for session in list(self.sessions.values()):
            if display in (None, "*", session.id):
                session.request(command, *args)

    def profile_for(self, candidate):
        """Family to drive ``candidate`` with, or None (needs a manual choice)."""
        settings = self._settings()
        entry = settings_mod.merged(settings, candidate.id)
        override = entry.get("profile", "auto")
        if override != "auto":
            return discovery.choose_profile(candidate, override)
        model = settings.get("model", "auto")
        if model != "auto":
            wanted = registry.get(model)
            return wanted if any(m.profile.id == wanted.id for m in candidate.matches) else None
        return candidate.auto_profile()

    def wake_collector_needs(self):
        sessions = [s for s in list(self.sessions.values()) if s.theme is not None]
        ids = {s.theme.info.id for s in sessions}
        needs = [s.theme.needs for s in sessions if isinstance(getattr(s.theme, "needs", None), dict)]
        collector = self.collector
        collector.want_processes = bool(ids & {"standard", "gkrellm", "old_computer"}) or any(
            n["processes"] for n in needs)
        collector.want_sensors = "gkrellm" in ids or any(n["sensors"] for n in needs)
        collector.want_fans = any(n["fans"] for n in needs)
        collector.want_disks = set().union(*(n["disks"] for n in needs)) if needs else set()
        collector.want_addrs = any(n["addrs"] for n in needs)

    # ------------------------------------------------------------ lifecycle
    def install_signal_handlers(self):
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGUSR1, lambda *_: self.request("recover", "SIGUSR1 (user request)"))
        signal.signal(signal.SIGHUP, lambda *_: self.request("reload"))

    def stop(self):
        self.stop_event.set()
        for session in list(self.sessions.values()):
            session.stop()

    def start_threads(self):
        try:
            os.makedirs(self.spool_dir, mode=0o700, exist_ok=True)
        except OSError:
            pass
        self.collector.start()
        if self.simulate:
            for index, panel in enumerate(self.simulate):
                self._add_session("simulated" if index == 0 else f"simulated-{index}", SimulatedSource(panel))

    def _add_session(self, display_id, source):
        session = DisplaySession(self, display_id, source)
        self.sessions[display_id] = session
        session.start()
        log.info("[%s] display session started", display_id)
        return session

    def _remove_session(self, display_id, reason):
        session = self.sessions.pop(display_id, None)
        if session is None:
            return
        self._removed_recoveries += session.recoveries
        session.stop()
        self.incidents.record("display_removed", health.SEVERITY_INFO, reason, display=display_id)
        self.wake_collector_needs()

    def run(self):
        """Blocking supervisor loop. Returns the process exit code."""
        self.start_threads()
        if self.notifier:
            self.notifier.ready(self._status_text())
        last_status = -1e9
        while not self.stop_event.is_set():
            self._supervise()
            now = self.clock()
            if now - last_status >= self.STATUS_EVERY:
                last_status = now
                self.write_status()
            self.stop_event.wait(self.SUPERVISE_EVERY)
        self._shutdown()
        return self.exit_code

    def _shutdown(self):
        if self.notifier:
            self.notifier.stopping()
        self.collector.stop()
        sessions = list(self.sessions.values())
        for session in sessions:
            session.stop()
            session.mailbox.clear()
        for session in sessions:
            session.join(timeout=4.0)
        if self.idle_link.state != STOPPED:
            try:
                self.idle_link.to(STOPPED, "shutdown")
            except health.InvalidTransition:
                pass
        self.write_status()

    # ------------------------------------------------------------ discovery
    def discover(self):
        devices = self.scan()
        assigned = {display_id for display_id, entry in (self._settings().get("displays") or {}).items()
                    if entry.get("profile", "auto") != "auto"}
        found = discovery.discover(devices, assigned)
        self.candidates = {candidate.id: candidate for candidate in found}
        now = self.clock()
        settings = self._settings()
        pending = []
        for candidate in found:
            self.last_seen[candidate.id] = now
            entry = settings_mod.merged(settings, candidate.id)
            if not entry.get("enabled", True):
                if candidate.id in self.sessions:
                    self._remove_session(candidate.id, "display disabled in the settings")
                continue
            if self.profile_for(candidate) is None:
                pending.append(candidate)
                continue
            if candidate.id not in self.sessions:
                self._add_session(candidate.id, UsbSource(self, candidate.id))
        self.pending = pending
        for display_id in list(self.sessions):
            if (display_id not in self.candidates
                    and now - self.last_seen.get(display_id, now) > self.SESSION_LINGER):
                self._remove_session(display_id, "display unplugged")
        if not self.sessions:
            if self.idle_link.state == STARTING:
                self.idle_link.to(DISCONNECTED, "no supported display connected")
                self.incidents.record("device_absent", health.SEVERITY_WARNING,
                                      "no supported display connected", action="waiting for it")
            if self.idle_link.state == DISCONNECTED:
                self.idle_link.to(RETRYING, "polling for displays")

    # ------------------------------------------------------------ supervisor
    def _supervise(self):
        changed = self.store.refresh()
        if changed:
            self._apply_settings(changed)
        now = self.clock()
        if self.simulate is None and now - self._last_discovery >= self.DISCOVERY_EVERY:
            self._last_discovery = now
            try:
                self.discover()
            except Exception as error:  # noqa: BLE001 - never let discovery stop the supervisor
                log.exception("discovery failed")
                self.incidents.record("discovery_error", health.SEVERITY_WARNING, repr(error))
        self._read_spool()
        self.wake_collector_needs()       # Kojiro widgets can change what must be sampled
        reasons = []
        beat = self.hb["telemetry"]
        reason = beat.stalled(self.PROGRESS_TIMEOUT["telemetry"], self.OP_TIMEOUT["telemetry"])
        if reason:
            reasons.append(reason)
        for session in list(self.sessions.values()):
            reasons += session.stalled_reasons()
        if not reasons:
            if self.stall_reported:
                self.incidents.record("pipeline_resumed", health.SEVERITY_INFO, "pipeline progressing again")
            self.stalled_since = None
            self.stall_reported = False
            if self.notifier:
                self.notifier.watchdog()
        else:
            if self.stalled_since is None:
                self.stalled_since = now
            if not self.stall_reported:
                self.stall_reported = True
                self.incidents.record("pipeline_stalled", health.SEVERITY_CRITICAL,
                                      "; ".join(reasons), action="watchdog pings suspended")
            no_watchdog = not (self.notifier and self.notifier.watchdog_usec)
            if self.service and no_watchdog and now - self.stalled_since > self.SELF_EXIT_AFTER_STALL:
                log.critical("pipeline stalled for %.0fs without systemd watchdog; exiting",
                             now - self.stalled_since)
                self.write_status()
                os._exit(4)
        sessions = list(self.sessions.values())
        if self.service and sessions and all(s.link.state == FAILED for s in sessions):
            # Every panel is present but unresponsive: a fresh process (and a
            # fresh libusb/serial state) is the next escalation step.
            self.exit_code = 3
            self.stop()
        self._notify_status()

    def _apply_settings(self, changed):
        settings = self._settings()
        log.info("settings changed: %s", ", ".join(sorted(changed)))
        for problem in self.store.problems:
            self.incidents.record("settings_invalid", health.SEVERITY_WARNING, problem)
        if "language" in changed:
            i18n.set_language(settings.get("language"))
        if self.simulate is None and changed & {"displays", "model"}:
            self._last_discovery = -1e9     # re-evaluate enabled displays and families now
        for session in list(self.sessions.values()):
            session.apply_settings()

    def _read_spool(self):
        """Per-display commands dropped by the GUI (through bsm-helper for the service)."""
        try:
            names = sorted(os.listdir(self.spool_dir))[:MAX_SPOOL_FILES]
        except OSError:
            return
        for name in names:
            path = os.path.join(self.spool_dir, name)
            try:
                if name.startswith(".") or not name.endswith(".json") or os.path.getsize(path) > 4096:
                    raise ValueError("ignored")
                with open(path, encoding="utf-8") as handle:
                    command = json.load(handle)
            except (OSError, ValueError):
                command = None
            try:
                os.unlink(path)
            except OSError:
                pass
            if isinstance(command, dict):
                self._spool_command(command)

    def _spool_command(self, command):
        command = settings_mod.validate_command(command)
        if command is None:
            return
        action, display = command["action"], command["display"]
        if action == "reconnect":
            self.request("reconnect", "requested from the configuration window", display=display)
        elif action == "identify":
            self.request("pattern", "identify", 8.0, display=display)
        elif action == "clear_pattern":
            self.request("clear_pattern", display=display)
        else:
            self.request("pattern", command["pattern"], float(command["seconds"]), display=display)

    # ------------------------------------------------------------ status
    def status(self):
        if self._proc is None:
            import psutil
            self._proc = psutil.Process()
            self._proc.cpu_percent(None)
        with self._proc.oneshot():
            cpu = self._proc.cpu_percent(None)
            rss = self._proc.memory_info().rss / 1048576
            threads = self._proc.num_threads()
        settings = self._settings()
        now = self.clock()
        sessions = list(self.sessions.values())
        displays = [session.status() for session in sessions]
        primary = displays[0] if displays else None
        link = self.link
        return {
            "version": __version__,
            "pid": os.getpid(),
            "service": self.service,
            "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "uptime_s": round(now - self.started, 1),
            "state": self.overall_state(),
            "state_since_s": round(now - link.since, 1),
            "connected": any(s.driver is not None for s in sessions),
            # Top-level device/stats/pipeline describe the first display (3.x/4.0 readers).
            "device": primary["device"] if primary else None,
            "settings": {key: settings.get(key) for key in
                         ("theme", "orientation", "brightness", "model", "performance_profile")},
            "settings_problems": list(self.store.problems),
            "pipeline": dict({"telemetry": self.hb["telemetry"].snapshot()},
                             **(primary["pipeline"] if primary else {})),
            "stats": primary["stats"] if primary else {},
            "recoveries": self.recoveries,
            "displays": displays,
            "pending": [dict(candidate.describe(), reason="needs a manual family choice")
                        for candidate in self.pending],
            "sensor_errors": dict(self.collector.sensor_errors),
            "process": {"cpu_percent": round(cpu, 1), "rss_mb": round(rss, 1), "threads": threads},
            "watchdog": bool(self.notifier and self.notifier.watchdog_usec),
            "stalled": self.stall_reported,
            "incidents": self.incidents.recent(30),
            "sound_events": next((list(s.theme.sound_events) for s in sessions
                                  if getattr(s.theme, "sound_events", None)), []),
        }

    def write_status(self):
        try:
            atomic_write_json(self.status_file, self.status())
        except OSError as error:
            log.debug("cannot write status file: %s", error)


def stopped_frame(width, height):
    image = Image.new("RGB", (width, height), (16, 18, 24))
    draw = ImageDraw.Draw(image)
    font = themes.ui_font(max(12, height // 14), bold=True)
    small = themes.ui_font(max(10, height // 22))
    title = "Big Screen Monitor"
    note = i18n._("Monitoring stopped")
    for text, font_, y, color in ((title, font, height // 2 - height // 10, (235, 240, 255)),
                                  (note, small, height // 2 + height // 40, (150, 160, 185))):
        width_ = draw.textlength(text, font=font_)
        draw.text(((width - width_) / 2, y), text, font=font_, fill=color)
    return image


SYSTEM_STATUS = "/run/big-screen-monitor-display/status.json"


def find_status_file():
    """BSM_STATUS when set (development), else the freshest of system service and manual run."""
    if os.environ.get("BSM_STATUS"):
        return os.environ["BSM_STATUS"] if os.path.exists(os.environ["BSM_STATUS"]) else None
    candidates = [SYSTEM_STATUS, status_path()]
    best, best_mtime = None, -1.0
    for path in filter(None, candidates):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best


def read_status(path=None):
    path = path or find_status_file()
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def spool_command(command, status_file=None):
    """Drop a per-display command where a runtime started by this user reads it."""
    directory = os.path.join(os.path.dirname(status_file or status_path()), "commands")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    name = f"{time.time_ns()}-{os.getpid()}.json"
    atomic_write_json(os.path.join(directory, name), command, mode=0o600)
    return name
