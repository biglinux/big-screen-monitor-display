"""FOSTON FS-707DC Touch Display (and other Windows CE devices running bsmd-ce).

The navigator keeps its original firmware. The bsmd-ce client
(``device-clients/wince``) runs on it, switches the USB function to the
Windows CE serial class (``045e:00ce``, ``ipaq`` driver, ``/dev/ttyUSB*``)
and speaks FSP (:mod:`.protocol`) with this driver:

* frames go out as dirty rectangles (fill / zlib / raw RGB565) followed by
  PRESENT; the device answers PRESENTED when the frame is on the glass, so
  at most one frame is in flight and the device never queues stale frames;
* touches come back as DOWN/MOVE/UP events in panel coordinates and are
  handed to ``on_input`` (set by the runtime) from the reader thread;
* the panel size, brightness support and client version come from the
  device's HELLO_ACK, never from guesses.
"""

import collections
import logging
import os
import socket
import threading
import time

from ... import frames
from ..base import DISCONNECTED, NOT_FOUND, PROTOCOL, TIMEOUT, Capabilities, DeviceInfo, DisplayError, \
    RasterDriver, percent
from ..transport import SerialTransport
from . import protocol as fsp

log = logging.getLogger("bsmd")

MODEL = "FOSTON FS-707DC Touch Display"


class FostonDisplay(RasterDriver):
    DRIVER = "foston_fs707dc"
    TILE = (32, 16)
    MAX_RECTS = 24
    TIGHT_RECTS = True            # the client accepts any rectangle
    FULL_REFRESH_RATIO = 0.7
    HELLO_TIMEOUT = 4.0
    PRESENT_TIMEOUT = 5.0
    PING_TIMEOUT = 2.5
    READ_SIZE = 4096
    MAX_EVENTS = 256
    # Bytes in flight before the device confirms them (FSP_CREDIT). The client
    # buffers 2 MiB; the Serial_Class driver of the FS-707DC itself drops data
    # beyond ~1 KB when nobody reads, which is why the client drains it in a
    # dedicated thread and the host never runs ahead of it.
    WINDOW = 64 * 1024                # measured on the FS-707DC: 256 KiB lost data under sustained load
    MAX_RAW = 16 * 1024               # raw bytes per RECT message before compression
    HELLO_ATTEMPTS = 2

    def __init__(self, port=None, transport=None, options=None, clock=time.monotonic, host_name=None):
        super().__init__()
        self.port = port
        self.transport = transport
        self.options = options or {}
        self.clock = clock
        self.host_name = host_name if host_name is not None else socket.gethostname()
        self.hello = None
        self.on_input = None              # callable(TouchEvent), called from the reader thread
        self.events = collections.deque(maxlen=self.MAX_EVENTS)
        self.stats = {"presented": 0, "naks": 0, "touch_events": 0, "decode_ms": 0, "blit_ms": 0,
                      "round_trip_ms": 0.0, "bytes": 0, "encodings": collections.Counter()}
        self._cond = threading.Condition()
        self._replies = {}                # kind -> latest Message
        self._error = None
        self._reader = None
        self._running = False
        self._seq = 0
        self._frame_id = 0
        self._credits = False
        self._sent = 0                    # bytes of messages sent since HELLO
        self._credited = 0
        self._write_lock = threading.Lock()
        self.capabilities = Capabilities(encoding="rgb565le+zlib", brightness=False, brightness_steps=101,
                                         partial_update=True, transport="serial")

    # ------------------------------------------------------------ plumbing
    def _send(self, kind, payload=b""):
        with self._write_lock:
            data = fsp.message(kind, payload, self._seq)
            if kind == fsp.HELLO:
                with self._cond:
                    self._sent = self._credited = 0
            elif self._credits:
                self._wait_window(len(data))
            self._seq = (self._seq + 1) & 0xFFFF
            self.transport.write(data)
            if kind != fsp.HELLO:
                self._sent += len(data)
            return len(data)

    def _wait_window(self, size):
        deadline = self.clock() + self.PRESENT_TIMEOUT
        with self._cond:
            while self._sent - self._credited > 0 and self._sent - self._credited + size > self.WINDOW:
                if self._error is not None:
                    raise self._error
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DisplayError(TIMEOUT, f"device stopped consuming data on {self.port}")
                self._cond.wait(min(remaining, 0.25))

    def _read_loop(self):
        parser = fsp.Parser()
        transport = self.transport
        while self._running:
            try:
                # One blocking byte, then whatever is already waiting: a plain
                # read(READ_SIZE) would hold every short reply for the whole timeout.
                data = transport.read(1)
                if data and hasattr(transport, "drain_input"):
                    data += transport.drain_input()
            except DisplayError as error:
                self._fail(error)
                return
            except Exception as error:  # noqa: BLE001 - any reader failure ends the link
                self._fail(DisplayError(PROTOCOL, "reader failed", error))
                return
            if not data:
                continue
            now = self.clock()
            for msg in parser.feed(data):
                self._dispatch(msg, now)

    def _dispatch(self, msg, now):
        if msg.kind == fsp.TOUCH:
            event = fsp.TouchEvent.parse(msg.payload, now)
            self.stats["touch_events"] += 1
            callback = self.on_input
            if callback is None:
                self.events.append(event)     # nobody listening: keep the latest for poll_input()
            else:
                try:
                    callback(event)
                except Exception:  # noqa: BLE001 - a UI bug must not kill the link
                    log.exception("touch handler failed")
            return
        if msg.kind == fsp.LOG:
            log.info("[%s] device: %s", self.port, msg.payload.decode("utf-8", "replace")[:300])
            return
        if msg.kind == fsp.BYE:
            self._fail(DisplayError(DISCONNECTED, "the client on the device was closed"))
            return
        if msg.kind == fsp.CREDIT:
            with self._cond:
                self._credited = int.from_bytes(msg.payload[:4], "little")
                self._cond.notify_all()
            return
        if msg.kind == fsp.NAK:
            self.stats["naks"] += 1
        with self._cond:
            self._replies[msg.kind] = msg
            self._cond.notify_all()

    def _fail(self, error):
        with self._cond:
            if self._error is None:
                self._error = error
            self._cond.notify_all()

    def _wait(self, kinds, timeout, what, accept=None, ignore_nak=False):
        deadline = self.clock() + timeout
        with self._cond:
            while True:
                if self._error is not None:
                    raise self._error
                nak = self._replies.pop(fsp.NAK, None)
                if nak is not None and not ignore_nak:
                    reason = fsp.NAK_REASONS.get(nak.payload[2] if len(nak.payload) > 2 else 0, "?")
                    raise DisplayError(PROTOCOL, f"device rejected a message during {what} ({reason})")
                for kind in kinds:
                    msg = self._replies.get(kind)
                    if msg is not None and (accept is None or accept(msg)):
                        del self._replies[kind]
                        return msg
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DisplayError(TIMEOUT, f"no answer to {what} from {self.port}")
                self._cond.wait(min(remaining, 0.25))

    # ------------------------------------------------------------ contract
    def open(self):
        if self.transport is None:
            if not self.port:
                raise DisplayError(NOT_FOUND, f"{self.DRIVER}: no serial port")
            # USB serial function of Windows CE: no RTS/CTS, the device paces itself.
            self.transport = SerialTransport(self.port, rtscts=False, read_timeout=0.2).open()
        self._error = None
        self._replies.clear()
        self._running = True
        self._reader = threading.Thread(target=self._read_loop, name=f"foston-rx:{self.port}", daemon=True)
        self._reader.start()
        self._credits = False
        try:
            for attempt in range(self.HELLO_ATTEMPTS):
                # A second HELLO after the client discarded a stalled partial message (1 s).
                self._send(fsp.HELLO, fsp.hello(self.host_name))
                try:
                    msg = self._wait((fsp.HELLO_ACK,), self.HELLO_TIMEOUT / self.HELLO_ATTEMPTS, "HELLO")
                    break
                except DisplayError as error:
                    if error.kind != TIMEOUT or attempt == self.HELLO_ATTEMPTS - 1:
                        raise
                    with self._cond:
                        self._replies.pop(fsp.NAK, None)
            ack = fsp.HelloAck.parse(msg.payload)
        except DisplayError as error:
            self.close()
            if error.kind == TIMEOUT:
                raise DisplayError(TIMEOUT, "the bsmd-ce client is not running on the device "
                                            "(start it from the navigator menu)") from error
            raise
        except ValueError as error:
            self.close()
            raise DisplayError(PROTOCOL, "invalid HELLO_ACK", error) from error
        if not ack.credits:
            self.close()
            raise DisplayError(PROTOCOL, f"bsmd-ce client {ack.strings.get('client', '?')} is too old: "
                                         "copy the bsmd-ce.exe of this version to the device")
        if ack.protocol != fsp.VERSION or ack.width < 64 or ack.height < 64 or ack.bpp != 16:
            self.close()
            raise DisplayError(PROTOCOL, f"unsupported client: protocol {ack.protocol}, "
                                         f"{ack.width}x{ack.height}x{ack.bpp}")
        self.hello = ack
        self._credits = True
        width, height = max(ack.width, ack.height), min(ack.width, ack.height)
        if (width, height) != (ack.width, ack.height):
            # Portrait-native devices are not known yet; refuse rather than draw sideways.
            self.close()
            raise DisplayError(PROTOCOL, f"portrait panel {ack.width}x{ack.height} is not supported")
        self.native_size = (width, height)
        self.capabilities.native_size = self.native_size
        self.capabilities.brightness = bool(ack.brightness)
        self.capabilities.touch = "single" if ack.touch else ""
        self.capabilities.notes = ("Windows CE client " + ack.strings.get("client", "?"),)
        details = {"client": ack.strings.get("client", ""), "platform": ack.strings.get("platform", ""),
                   "oem": ack.strings.get("oem", ""), "device_port": ack.strings.get("port", ""),
                   "windows_ce": ".".join(str(v) for v in ack.os_version),
                   "memory_kb": f"{ack.memory_free_kb}/{ack.memory_total_kb}",
                   "usb_previous_client": ack.strings.get("usb_previous", ""),
                   "touch": "single" if ack.touch else "none",
                   "brightness": "registry backlight (experimental)" if ack.brightness else "not supported"}
        self.info = DeviceInfo(self.DRIVER, MODEL, width, height, location=self.port or "", details=details)
        self._prev = None
        log.info("[%s] %s: %s, WinCE %s, %dx%d, %s", self.port, MODEL, details["client"], details["windows_ce"],
                 width, height, details["oem"] or "?")
        return self.info

    def close(self):
        self._running = False
        transport, self.transport = self.transport, None
        if transport is not None:
            if self.hello is not None:
                try:
                    with self._write_lock:
                        transport.write(fsp.message(fsp.BYE, bytes([fsp.BYE_WAIT])))
                except Exception:  # noqa: BLE001 - the device may already be gone
                    pass
            if hasattr(transport, "close"):
                transport.close()
        reader, self._reader = self._reader, None
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=1.0)
        self.hello = None
        self._prev = None

    def _blit(self, image, rect):
        x0, y0, x1, y1 = rect
        pixels = frames.image_to_rgb565(image.crop(rect) if rect != (0, 0, *image.size) else image, "<")
        encoding = self.options.get("encoding", "auto")
        # Bands of at most MAX_RAW raw bytes: small messages keep every burst
        # within what the device drains between two credits.
        width = x1 - x0
        cols = max(1, min(width, self.MAX_RAW // 2))
        rows = max(1, self.MAX_RAW // (2 * min(width, cols)))
        sent = 0
        for top in range(0, y1 - y0, rows):
            for left in range(0, width, cols):
                band = pixels[top:top + rows, left:left + cols]
                encoded = fsp.encode_rect(band, x0 + left, y0 + top, encoding)
                self.stats["encodings"][encoded.encoding] += 1
                sent += self._send(encoded.kind, encoded.payload)
        self.stats["bytes"] += sent
        return sent

    def present(self, image):
        """Send a frame; a frame damaged on the link is repaired once in place.

        The Windows CE serial driver of the FS-707DC occasionally drops bytes
        when the client cannot read for a moment (measured: a few per thousand
        frames under full-frame load). The damaged message fails its CRC; the
        driver then re-handshakes (credit counters reset on both sides) and
        sends the whole frame again instead of dropping the session."""
        try:
            return self._present_once(image)
        except DisplayError as error:
            if error.kind not in (PROTOCOL, TIMEOUT) or self.transport is None:
                raise
            log.info("[%s] frame damaged on the link (%s): resynchronising", self.port, error)
            self.stats["resyncs"] = self.stats.get("resyncs", 0) + 1
            self._resync()
            return self._present_once(image)

    def _resync(self):
        with self._cond:
            self._replies.clear()
        self._send(fsp.HELLO, fsp.hello(self.host_name))
        # NAKs for the damaged frame may still arrive after the HELLO went out (seen on the device).
        self._wait((fsp.HELLO_ACK,), self.HELLO_TIMEOUT, "HELLO", ignore_nak=True)
        with self._cond:
            self._replies.clear()
        self._prev = None

    def _present_once(self, image):
        if self.transport is None:
            raise DisplayError(DISCONNECTED, f"{self.DRIVER} not open")
        with self._cond:
            if self._error is not None:
                raise self._error
        transfer = super().present(image)
        if not transfer.rects:
            return transfer
        self._frame_id = (self._frame_id + 1) & 0xFFFFFFFF
        frame_id = self._frame_id
        start = self.clock()
        try:
            self._send(fsp.PRESENT, fsp.present(frame_id))
            msg = self._wait((fsp.PRESENTED,), self.PRESENT_TIMEOUT, "PRESENT",
                             accept=lambda m: int.from_bytes(m.payload[:4], "little") == frame_id)
        except BaseException:
            self._prev = None             # resend everything after a failed frame
            raise
        decode_ms = int.from_bytes(msg.payload[4:8], "little")
        blit_ms = int.from_bytes(msg.payload[8:12], "little")
        self.stats["presented"] += 1
        self.stats["decode_ms"], self.stats["blit_ms"] = decode_ms, blit_ms
        self.stats["round_trip_ms"] = (self.clock() - start) * 1000.0
        transfer.duration += self.clock() - start
        return transfer

    def set_brightness(self, value):
        if self.transport is None or not self.capabilities.brightness:
            return
        self._send(fsp.BRIGHTNESS, bytes([percent(value)]))

    def probe(self):
        if self.transport is None:
            raise DisplayError(DISCONNECTED, f"{self.DRIVER} not open")
        # No transport.alive(): it reads the modem lines (TIOCMGET), which the
        # kernel's ipaq driver does not implement (ENOTTY). PING proves more anyway.
        if isinstance(self.transport, SerialTransport) and not os.path.exists(self.port):
            raise DisplayError(DISCONNECTED, f"{self.port} disappeared")
        token = int(self.clock() * 1000) & 0xFFFFFFFF
        self._send(fsp.PING, token.to_bytes(4, "little"))
        self._wait((fsp.PONG,), self.PING_TIMEOUT, "PING",
                   accept=lambda m: int.from_bytes(m.payload[:4], "little") == token)

    # ------------------------------------------------------------ extras
    def calibrate(self):
        """Open the device's own touch calibration (Windows CE TouchCalibrate)."""
        if self.transport is not None:
            self._send(fsp.CALIBRATE)
            self._prev = None

    def set_touch(self, enabled):
        if self.transport is not None:
            self._send(fsp.TOUCHCFG, bytes([1 if enabled else 0, 0]))

    def quit_client(self):
        """Close the client on the device (it restores USB mass storage)."""
        if self.transport is not None:
            self._send(fsp.BYE, bytes([fsp.BYE_QUIT]))

    def poll_input(self):
        events = []
        while self.events:
            events.append(self.events.popleft())
        return events
