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
MEDIA_REFLASH_MIN = 120.0     # flashes caused by players starting and stopping
MEDIA_TRACK_MIN = 25.0        # with "cover and title of every song": skipping songs updates quickly
RESTART_VANISH = 5.0          # measured: the panel drops off USB ~1 s after the last block
ACK_TIMEOUT = 5.0
BLOCK_RETRIES = 5
UPLOAD_ATTEMPTS = 3


class _Hid(Hidraw):
    max_report = protocol.REPORT + 1


@dataclass
class Frame:
    """What the panel should show: the picture (by spec key) and the telemetry it
    is filled from. Values are computed on the transport thread, once the picture
    (and its bindings) is ready."""
    key: str
    spec: dict
    settings: dict
    stats: dict
    values: dict = field(default_factory=dict)
    brightness: int = 70
    created: float = field(default_factory=time.time)

    def describe(self):
        return {"layout": self.key, "theme": self.spec.get("theme", "dashboard"),
                "fields": {str(k): v for k, v in sorted(self.values.items())}, "brightness": self.brightness}


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
        self.picture = None            # layout.Compiled being shown
        self.last_flash = -1e9
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
        frame = Frame(layout.key(theme_spec), theme_spec, dict(settings), dict(stats),
                      brightness=int(settings.get("brightness", 70)))
        picture = self.picture
        if picture is not None and picture.source_key == frame.key:
            frame.values = layout.values(picture, stats, now)
        return frame

    def frame_interval(self, _settings):
        return 1.0

    def _adapt(self, frame):
        """The compiled picture for a frame (a theme capture can take a few seconds)."""
        picture = self.picture
        if picture is not None and picture.source_key == frame.key:
            return picture
        following = bool(((frame.spec.get("media") or {}).get("track")))
        appeared = (frame.spec.get("media") or {}).get("present") and \
            not ((picture.source_spec or {}).get("media") or {}).get("present") if picture is not None else False
        # A song starting (or every song, when followed) shows the player quickly; players
        # coming and going otherwise are held back so a flapping one does not flash all day.
        wait = MEDIA_TRACK_MIN if following or appeared else MEDIA_REFLASH_MIN
        if picture is not None and self._media_only_change(picture, frame) and \
                time.monotonic() - self.last_flash < wait:
            return picture        # songs / players changing: not more than one flash per interval

        def progress():
            callback = self.on_progress
            return bool(callback is not None and callback("adapting the theme"))
        picture = layout.compiled(frame.spec, frame.settings, frame.stats, progress)
        picture.source_key = frame.key
        picture.source_spec = frame.spec
        self.picture = picture
        return picture

    @staticmethod
    def _media_only_change(picture, frame):
        old, new = dict(picture.source_spec or {}), dict(frame.spec)
        return old.pop("media", None) != new.pop("media", None) and old == new

    def present(self, frame):
        start = time.monotonic()
        sent = 0
        picture = self._adapt(frame)
        if picture.key != self.flashed:
            sent += self.flash(picture)
        if not frame.values:
            frame.values = layout.values(picture, frame.stats)
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

    def _ask_ymodem(self, timeout):
        """``True`` when the panel answers "ymodem" with ``06 43``; ``False`` on NAK or silence."""
        try:
            self.hid.drain()
            self.hid.write(protocol.report(protocol.YMODEM))
            return self._expect(protocol.ACK_MORE, "ymodem", timeout=timeout)
        except DisplayError as error:
            if error.kind not in (DISCONNECTED, NOT_FOUND, TIMEOUT):
                raise
            return False

    def _close_open_transfer(self):
        """Finish a YMODEM session left open (upload cut by a crash, a replug or a
        stop): EOT, then the empty block 0. Measured: the panel then leaves the
        transfer and restarts. While a transfer is open it reads "reset" (byte 0
        is 0x01 = SOH) and "ymodem" as broken blocks and NAKs them."""
        try:
            self.hid.write(protocol.report(bytes([protocol.EOT])))
            self.hid.read(1.5)
            for packet in protocol.metadata_block("", 0):
                self.hid.write(packet)
            self.hid.read(1.5)
        except DisplayError as error:
            if error.kind not in (DISCONNECTED, NOT_FOUND, TIMEOUT):
                raise

    def _enter_ymodem(self):
        self.hid.drain()
        try:
            self.hid.write(protocol.report(protocol.RESET))
            time.sleep(0.2)
        except DisplayError as error:
            if error.kind not in (DISCONNECTED, NOT_FOUND):
                raise
        if self._ask_ymodem(3.0):
            return
        # Either the unit restarted on "reset" (follow it) or a previous upload left a
        # transfer open (close it; the panel restarts). Then ask again.
        if self.hid.fd is not None and os.path.exists(self.hid.path or ""):
            self._close_open_transfer()
        self._await_restart(vanish_within=3.0)
        if self._ask_ymodem(ACK_TIMEOUT):
            return
        raise DisplayError(PROTOCOL, "the panel refused the upload mode")

    def flash(self, picture):
        """Upload a :class:`layout.Compiled` picture. Returns the bytes sent."""
        data = picture.data
        if not protocol.THEME_MIN <= len(data) <= protocol.THEME_MAX:
            raise DisplayError(PROTOCOL, f"compiled theme of {len(data)} bytes is out of range")
        log.info("flashing SmartMonitor picture %s (%s, %d bytes, %d blocks) on usb %s", picture.key,
                 picture.spec.get("theme", "dashboard"), len(data), (len(data) + protocol.BLOCK - 1) // protocol.BLOCK,
                 self.usb_path)
        started = time.monotonic()
        sent = self.upload(data)
        self.uploads += 1
        self.last_flash = time.monotonic()
        self._save_state(picture.key, len(data))
        log.info("SmartMonitor picture flashed in %.1f s", time.monotonic() - started)
        self._await_restart()
        if self.info is not None:
            self.info.details["flashed_layout"] = picture.key
            self.info.details["hidraw"] = self.hid.path
        return sent

    def upload(self, data):
        """Upload ``img.dat`` bytes, recovering from a transfer left open or refused."""
        for attempt in range(1, UPLOAD_ATTEMPTS + 1):
            try:
                return self._upload(data)
            except DisplayError as error:
                if "interrupted" in str(error) or attempt == UPLOAD_ATTEMPTS:
                    raise
                log.warning("SmartMonitor upload attempt %d failed: %s; retrying", attempt, error)
                self._recover_transfer()
        raise DisplayError(PROTOCOL, "upload failed")

    def _recover_transfer(self):
        """After a refused or broken upload: end whatever transfer the panel still
        has open and wait for its restart (a panel with nothing open only gets
        reopened)."""
        try:
            if self.hid.fd is None:
                self._reopen()
            self._close_open_transfer()
        except DisplayError as error:
            if error.kind not in (DISCONNECTED, NOT_FOUND, TIMEOUT):
                raise
        self._await_restart(vanish_within=3.0)

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
