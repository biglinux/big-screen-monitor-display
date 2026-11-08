"""Driver of the SmartMonitor 3.5" HID panel on the shared display contract.

Output kind ``telemetry``: the runtime asks the driver for a frame
(:meth:`SmartMonitorHid.build_frame`) instead of rendering a theme image, and
hands it back to :meth:`present` on the transport thread.

``present`` flashes the dashboard when its picture changed (about a minute,
reported through ``on_progress`` so the watchdog sees the work progress) and
then pushes the clock, the backlight and the live values (a few 64-byte
reports per second). What was flashed is remembered per USB port in the
service's state directory: the panel cannot be asked what it holds (units
share one serial number and have no read-back), so a fresh state means one
flash.
"""

import datetime
import glob
import json
import logging
import os
import time
from dataclasses import dataclass, field

from ..base import DISCONNECTED, NOT_FOUND, PROTOCOL, TIMEOUT, DeviceInfo, DisplayError, TelemetryDriver, Transfer
from ..deepcool.hid import Hidraw
from . import layout, protocol

log = logging.getLogger("bsmd.smartmonitor")

SYSFS_USB = "/sys/bus/usb/devices"
REENUMERATE_WAIT = 15.0       # the panel restarts after "reset" and after a flash
RESTART_VANISH = 5.0          # measured: the panel drops off USB ~1 s after the last block
ACK_TIMEOUT = 5.0
BLOCK_RETRIES = 5
UPLOAD_ATTEMPTS = 3


class _Hid(Hidraw):
    max_report = protocol.REPORT + 1


@dataclass
class Frame:
    """What the panel should show: the dashboard picture (by key) and the values."""
    key: str
    spec: dict
    values: dict
    brightness: int = 70
    created: float = field(default_factory=time.time)

    def describe(self):
        hints = {key: self.spec.get(key) for key in ("gpu", "gpu_name", "ram_total_gb", "host")}
        return {"layout": self.key, "fields": {str(k): v for k, v in sorted(self.values.items())},
                "brightness": self.brightness, "hints": hints}


def find_hidraw(usb_path, sysfs=SYSFS_USB):
    """``/dev/hidrawN`` of the panel on USB port ``usb_path`` (it changes after a restart)."""
    if not usb_path:
        return ""
    nodes = sorted(glob.glob(os.path.join(sysfs, usb_path, f"{usb_path}:*", "*", "hidraw", "hidraw*")))
    return "/dev/" + os.path.basename(nodes[0]) if nodes else ""


def state_dir():
    base = os.environ.get("STATE_DIRECTORY", "").split(":")[0]
    if not base:
        base = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                            "big-screen-monitor-display")
    return base


class SmartMonitorHid(TelemetryDriver):
    DRIVER = "smartmonitor_hid"
    MODEL = "SmartMonitor 3.5\" (HID)"

    def __init__(self, hidraw, usb_path="", product="", options=None, state_path=None):
        super().__init__()
        self.usb_path = usb_path
        self.product = product
        self.options = dict(options or {})
        self.hid = _Hid(hidraw or find_hidraw(usb_path), protocol.VENDOR, protocol.PRODUCT, label="panel")
        self.native_size = layout.SIZE
        caps = self.capabilities
        caps.brightness = True
        caps.brightness_steps = 100
        caps.display = "lcd"
        caps.transport = "hid"
        caps.native_size = layout.SIZE
        caps.metrics = ("cpu", "gpu", "ram", "disk", "network", "clock")
        caps.notes = ("Draws a dashboard flashed into the panel; live values are pushed every second.",)
        self.min_interval = 1.0
        self.brightness = 70
        safe = (usb_path or "default").replace("/", "_")
        self.state_path = state_path or os.path.join(state_dir(), f"smartmonitor-{safe}.json")
        self.flashed = self._load_state()
        self.on_progress = None        # set by the runtime: called per block, returns True to abort
        self.last_frame = None
        self.uploads = 0

    # ------------------------------------------------------------ state
    def _load_state(self):
        try:
            with open(self.state_path, encoding="utf-8") as handle:
                return json.load(handle).get("layout")
        except (OSError, ValueError, AttributeError):
            return None

    def _save_state(self, key, size):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({"layout": key, "bytes": size, "flashed": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, handle)
            os.replace(tmp, self.state_path)
        except OSError as error:
            log.warning("could not remember the flashed SmartMonitor layout: %s", error)
        self.flashed = key

    # ------------------------------------------------------------ contract
    def open(self):
        if not self.hid.path:
            self.hid.path = find_hidraw(self.usb_path)
        self.hid.open()
        self.info = DeviceInfo(self.DRIVER, self.MODEL, *layout.SIZE, f"usb {self.usb_path}",
                               {"hidraw": self.hid.path, "product": self.product, "flashed_layout": self.flashed or "",
                                "protocol": "SmartMonitor HID (img.dat + channels)"})
        return self.info

    def build_frame(self, settings, stats, now=None):
        theme_spec = layout.spec(settings, stats)
        return Frame(layout.key(theme_spec), theme_spec, layout.values(theme_spec, stats, now),
                     int(settings.get("brightness", 70)))

    def frame_interval(self, _settings):
        return 1.0

    def present(self, frame):
        start = time.monotonic()
        sent = 0
        if frame.key != self.flashed:
            sent += self.flash(frame.spec)
        self.brightness = frame.brightness
        sent += self.hid.write(protocol.datetime_report(datetime.datetime.now(), self.brightness))
        for packet in protocol.sensor_reports(frame.values):
            sent += self.hid.write(packet)
        self.last_frame = frame
        return Transfer(sent, 1, True, time.monotonic() - start)

    def set_brightness(self, percent):
        self.brightness = max(0, min(100, int(percent)))
        if self.hid.fd is not None:
            self.hid.write(protocol.datetime_report(datetime.datetime.now(), self.brightness))

    def probe(self):
        if not self.hid.alive():
            raise DisplayError(DISCONNECTED, "HID node vanished")
        return True

    def close(self):
        self.hid.close()

    # ------------------------------------------------------------ flashing
    def _progress(self, what):
        callback = self.on_progress
        if callback is not None and callback(what):
            raise DisplayError(PROTOCOL, "theme upload interrupted (service stopping)")

    def _reopen(self, wait=REENUMERATE_WAIT):
        """Close and open the panel again, following it to a new hidraw node."""
        self.hid.close()
        deadline = time.monotonic() + wait
        last = None
        time.sleep(0.5)
        while time.monotonic() < deadline:
            self._progress("waiting for the panel")
            path = find_hidraw(self.usb_path) or self.hid.path
            if path and os.path.exists(path):
                self.hid.path = path
                try:
                    self.hid.open()
                    return
                except DisplayError as error:
                    last = error
            time.sleep(0.5)
        raise last or DisplayError(NOT_FOUND, "panel did not come back after restarting")

    def _await_restart(self, vanish_within=None):
        """After a flash the panel restarts (USB disconnect ~1 s later) to load the
        theme. Wait for it to go and come back instead of writing into a node that
        is about to vanish; a unit that does not restart is simply reopened."""
        path = self.hid.path
        self.hid.close()
        deadline = time.monotonic() + (RESTART_VANISH if vanish_within is None else vanish_within)
        while time.monotonic() < deadline and path and os.path.exists(path):
            self._progress("waiting for the panel to restart")
            time.sleep(0.1)
        self._reopen()

    def _expect(self, want, what, timeout=ACK_TIMEOUT):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DisplayError(TIMEOUT, f"{what}: no acknowledgement")
            kind, value = protocol.parse_ack(self.hid.read(remaining))
            if kind == "nak":
                return False
            if kind == "ack":
                if want is not None and value != want:
                    raise DisplayError(PROTOCOL, f"{what}: acknowledgement {value!r}, expected {want:#04x}")
                return True

    def _send(self, reports, want, what):
        for _attempt in range(BLOCK_RETRIES):
            for packet in reports:
                self.hid.write(packet)
            if self._expect(want, what):
                return sum(len(p) for p in reports)
        raise DisplayError(PROTOCOL, f"{what}: refused {BLOCK_RETRIES} times")

    def _enter_ymodem(self):
        self.hid.drain()
        self.hid.write(protocol.report(protocol.RESET))
        time.sleep(0.2)
        try:
            self.hid.write(protocol.report(protocol.YMODEM))
            if self._expect(protocol.ACK_MORE, "ymodem", timeout=3.0):
                return
        except DisplayError as error:
            if error.kind not in (DISCONNECTED, NOT_FOUND, TIMEOUT):
                raise
        # Some units restart (and re-enumerate) on "reset": follow them, then ask again.
        self._reopen()
        self.hid.drain()
        self.hid.write(protocol.report(protocol.YMODEM))
        if not self._expect(protocol.ACK_MORE, "ymodem"):
            raise DisplayError(PROTOCOL, "the panel refused the upload mode")

    def flash(self, theme_spec):
        """Compile and upload the dashboard. Returns the bytes sent."""
        key, data = layout.compiled(theme_spec)
        if not protocol.THEME_MIN <= len(data) <= protocol.THEME_MAX:
            raise DisplayError(PROTOCOL, f"compiled theme of {len(data)} bytes is out of range")
        log.info("flashing the SmartMonitor dashboard %s (%d bytes, %d blocks) on usb %s", key, len(data),
                 (len(data) + protocol.BLOCK - 1) // protocol.BLOCK, self.usb_path)
        started = time.monotonic()
        last_error = None
        for attempt in range(1, UPLOAD_ATTEMPTS + 1):
            try:
                sent = self._upload(data)
                break
            except DisplayError as error:
                last_error = error
                if "interrupted" in str(error) or attempt == UPLOAD_ATTEMPTS:
                    raise
                log.warning("SmartMonitor upload attempt %d failed: %s; retrying", attempt, error)
                self._reopen()
        else:
            raise last_error
        self.uploads += 1
        self._save_state(key, len(data))
        log.info("SmartMonitor dashboard flashed in %.1f s", time.monotonic() - started)
        self._await_restart()
        if self.info is not None:
            self.info.details["flashed_layout"] = key
            self.info.details["hidraw"] = self.hid.path
        return sent

    def _upload(self, data):
        self._progress("entering upload mode")
        self._enter_ymodem()
        sent = self._send(protocol.metadata_block("img.dat", len(data)), protocol.ACK_MORE, "metadata")
        total = (len(data) + protocol.BLOCK - 1) // protocol.BLOCK
        for index, (reports, want) in enumerate(protocol.data_blocks(data), start=1):
            sent += self._send(reports, want, f"block {index}/{total}")
            self._progress(f"block {index}/{total}")
        self.hid.write(protocol.report(bytes([protocol.EOT])))
        if not self._expect(protocol.ACK_MORE, "end of file"):
            raise DisplayError(PROTOCOL, "end of file refused")
        sent += self._send(protocol.metadata_block("", 0), protocol.ACK_DONE, "end of session")
        return sent


def create(device, options=None):
    """Driver for a discovered USB device (bsmd.displays.discovery.UsbDevice)."""
    hidraw = device.hidraws[0] if getattr(device, "hidraws", ()) else ""
    return SmartMonitorHid(hidraw, device.path, getattr(device, "product", ""), options)
