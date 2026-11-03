"""AX206 digital photo frame with the dpf-ax hacked firmware (SCSI over bulk).

Protocol reference: lcd4linux ``dpflib`` (wrap_scsi / dpf_screen_blit) and
https://github.com/dreamlayers/dpf-ax. Validated on real hardware (800x480).
"""

import errno
import struct
import time

from .. import frames
from .base import (BUSY, DISCONNECTED, FATAL_KINDS, IO, NOT_FOUND, PERMISSION, PROTOCOL, TIMEOUT, Capabilities,
                   DeviceInfo, DisplayError, Transfer)


def brightness_to_ax206(percent):
    """Map 0..100 % to the AX206 backlight scale 0..7 (0 = off)."""
    percent = max(0, min(100, int(percent)))
    if percent == 0:
        return 0
    return max(1, min(7, int(1 + (percent - 10) * 6 / 90)))


class AX206:
    """AX206 digital photo frame with the dpf-ax hacked firmware (SCSI over bulk).

    Protocol reference: lcd4linux ``dpflib`` (wrap_scsi / dpf_screen_blit).
    The blit command accepts a sub-rectangle, so only changed regions are sent.
    """

    VID, PID = 0x1908, 0x0102
    EP_OUT, EP_IN = 0x01, 0x81
    TILE = (32, 16)
    MAX_RECTS = 24           # each blit costs ~0.3 ms of SCSI overhead
    FULL_REFRESH_RATIO = 0.6   # send a full frame when more than this changed
    DRIVER = "ax206"

    def __init__(self, usb_module=None, bus=None, address=None):
        if usb_module is None:
            import usb.core
            import usb.util
            usb_module = usb
        self._usb = usb_module
        self.bus, self.address = bus, address    # pin one frame when several are plugged in
        self.dev = None
        self.native_size = (0, 0)
        self.info = None
        self._prev = None
        self._tag = 0
        self.capabilities = Capabilities(encoding="rgb565be", transport="usb", brightness_steps=8)

    # -- discovery
    @classmethod
    def is_connected(cls, usb_module=None):
        if usb_module is None:
            import usb.core as core
        else:
            core = usb_module.core
        try:
            return core.find(idVendor=cls.VID, idProduct=cls.PID) is not None
        except Exception:  # backend missing, permissions on /dev/bus/usb...
            return False

    def _classify(self, error, what):
        if isinstance(error, DisplayError):
            return error
        number = getattr(error, "errno", None) or getattr(error, "backend_error_code", None)
        name = type(error).__name__
        text = str(error).lower()
        if name == "USBTimeoutError" or number in (errno.ETIMEDOUT, -7) or "timed out" in text:
            kind = TIMEOUT
        elif number in (errno.ENODEV, errno.ENOENT, -4) or "no such device" in text:
            kind = DISCONNECTED
        elif number in (errno.EACCES, errno.EPERM, -3) or "access denied" in text:
            kind = PERMISSION
        elif number in (errno.EBUSY, -6) or "resource busy" in text:
            kind = BUSY
        elif number in (errno.EPIPE, -9):
            kind = PROTOCOL
        else:
            kind = IO
        return DisplayError(kind, f"AX206 {what} failed", error)

    def open(self):
        core, util = self._usb.core, self._usb.util
        try:
            if self.bus is None:
                dev = core.find(idVendor=self.VID, idProduct=self.PID)
            else:
                dev = core.find(idVendor=self.VID, idProduct=self.PID,
                                custom_match=lambda d: (d.bus, d.address) == (self.bus, self.address))
        except Exception as error:
            raise DisplayError(NOT_FOUND, "USB backend unavailable", error)
        if dev is None:
            raise DisplayError(NOT_FOUND, "AX206 not connected")
        if dev.idVendor != self.VID or dev.idProduct != self.PID:
            raise DisplayError(PROTOCOL, "unexpected device")
        self.dev = dev
        try:
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)
            except NotImplementedError:
                pass
            try:
                dev.set_configuration()
            except self._usb.core.USBError as error:
                # EBUSY: already configured by a previous instance - fine.
                if getattr(error, "errno", None) != errno.EBUSY:
                    raise
            util.claim_interface(dev, 0)
            time.sleep(0.05)
            width, height = 0, 0
            for _attempt in range(3):
                width, height = self._get_dimensions()
                if width > 0 and height > 0:
                    break
                time.sleep(0.1)
        except Exception as error:
            classified = self._classify(error, "open")
            self.close()
            raise classified
        if not (0 < width <= 2048 and 0 < height <= 2048):
            self.close()
            raise DisplayError(PROTOCOL, f"AX206 reported invalid size {width}x{height}")
        self.native_size = (width, height)
        self.capabilities.native_size = self.native_size
        self._prev = None
        self.info = DeviceInfo(self.DRIVER, "AX206 DPF", width, height,
                               location=f"usb bus {dev.bus} addr {dev.address}")
        return self.info

    def close(self):
        dev, self.dev = self.dev, None
        self._prev = None
        if dev is None:
            return
        try:
            self._usb.util.release_interface(dev, 0)
        except Exception:
            pass
        try:
            self._usb.util.dispose_resources(dev)
        except Exception:
            pass

    def reset_port(self):
        """USB reset of *this* device only (validated by VID/PID)."""
        dev = self.dev
        if dev is None or dev.idVendor != self.VID or dev.idProduct != self.PID:
            return False
        try:
            dev.reset()
            return True
        except Exception:
            return False
        finally:
            self.close()

    # -- SCSI transport
    def _scsi(self, cmd, data_out=None, read_len=0):
        if self.dev is None:
            raise DisplayError(DISCONNECTED, "AX206 not open")
        self._tag = (self._tag + 1) & 0xFFFFFFFF
        length = len(data_out) if data_out is not None else read_len
        flags = 0x00 if read_len == 0 else 0x80
        cbw = struct.pack("<4sIIBBB16s", b"USBC", self._tag, length, flags, 0,
                          len(cmd), bytes(cmd).ljust(16, b"\0"))
        response = None
        try:
            self.dev.write(self.EP_OUT, cbw, timeout=1000)
            if data_out is not None and len(data_out):
                # ~4 MB/s worst case observed on these frames, plus margin.
                timeout = 1500 + len(data_out) // 1500
                self.dev.write(self.EP_OUT, data_out, timeout=timeout)
            elif read_len:
                response = bytes(self.dev.read(self.EP_IN, read_len, timeout=2000))
            csw = bytes(self.dev.read(self.EP_IN, 13, timeout=3000))
        except Exception as error:
            self._prev = None
            raise self._classify(error, "transfer")
        if len(csw) != 13 or csw[:4] != b"USBS":
            self._prev = None
            raise DisplayError(PROTOCOL, f"AX206 bad CSW {csw[:4]!r} len={len(csw)}")
        status = csw[12]
        if status != 0:
            self._prev = None
            raise DisplayError(PROTOCOL, f"AX206 command status {status}")
        return response

    def _get_dimensions(self):
        cmd = bytes([0xCD, 0, 0, 0, 0, 2] + [0] * 10)
        try:
            response = self._scsi(cmd, read_len=5)
        except DisplayError as error:
            if error.kind in FATAL_KINDS:
                raise
            return 0, 0
        if not response or len(response) < 4:
            return 0, 0
        return response[0] | (response[1] << 8), response[2] | (response[3] << 8)

    def probe(self):
        width, height = self._get_dimensions()
        if (width, height) != self.native_size:
            raise DisplayError(PROTOCOL, f"AX206 probe returned {width}x{height}")

    def set_brightness(self, percent):
        level = brightness_to_ax206(percent)
        cmd = bytes([0xCD, 0, 0, 0, 0, 6, 0x01, 0x01, 0x00, level, 0x00, 0, 0, 0, 0, 0])
        self._scsi(cmd)

    def invalidate(self):
        self._prev = None

    def _blit(self, pixels, rect):
        x0, y0, x1, y1 = rect
        payload = pixels[y0:y1, x0:x1].tobytes()
        cmd = bytes([0xCD, 0, 0, 0, 0, 6, 0x12,
                     x0 & 0xFF, x0 >> 8, y0 & 0xFF, y0 >> 8,
                     (x1 - 1) & 0xFF, (x1 - 1) >> 8, (y1 - 1) & 0xFF, (y1 - 1) >> 8, 0])
        self._scsi(cmd, data_out=payload)
        return len(payload)

    def present(self, image):
        if image.size != self.native_size:
            raise ValueError(f"frame {image.size} != panel {self.native_size}")
        start = time.monotonic()
        pixels = frames.image_to_rgb565(image, ">")
        width, height = self.native_size
        rects = frames.plan_rects(pixels, self._prev, *self.TILE, self.MAX_RECTS)
        if rects == []:
            return Transfer(duration=time.monotonic() - start)
        if rects is not None and sum(map(frames.rect_area, rects)) > width * height * self.FULL_REFRESH_RATIO:
            rects = None
        full = rects is None
        rects = [(0, 0, width, height)] if full else rects
        sent = sum(self._blit(pixels, rect) for rect in rects)
        self._prev = pixels
        return Transfer(sent, len(rects), full, time.monotonic() - start)


