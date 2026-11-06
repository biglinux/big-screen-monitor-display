"""Minimal hidraw writer (no hidapi needed).

``write()`` on a hidraw node sends an output report exactly like hidapi's
Linux hidraw backend (which the reference projects use): byte 0 is the
report id. Before anything is written, the node's identity is checked with
HIDIOCGRAWINFO, so a node number reused by another device after a replug is
never written to. Writes are non-blocking with a timeout.
"""

import errno
import fcntl
import os
import select
import struct
import time

from ..base import BUSY, DISCONNECTED, IO, NOT_FOUND, PERMISSION, TIMEOUT, DisplayError

# _IOR('H', 0x03, struct hidraw_devinfo { __u32 bustype; __s16 vendor; __s16 product; })
HIDIOCGRAWINFO = 0x80084803
MAX_REPORT = 64
WRITE_TIMEOUT = 1.0


def _error(error, what):
    code = getattr(error, "errno", None)
    if code in (errno.ENOENT, errno.ENXIO):
        return DisplayError(NOT_FOUND, f"{what}: device node not found", error)
    if code in (errno.EACCES, errno.EPERM):
        return DisplayError(PERMISSION, f"{what}: no permission for the HID device", error)
    if code == errno.EBUSY:
        return DisplayError(BUSY, f"{what}: device busy", error)
    if code in (errno.ENODEV, errno.ESHUTDOWN, errno.EIO):
        return DisplayError(DISCONNECTED, f"{what}: device gone", error)
    return DisplayError(IO, f"{what}: {error}", error)


def hidraw_identity(fd):
    raw = fcntl.ioctl(fd, HIDIOCGRAWINFO, bytes(8))
    _bus, vendor, product = struct.unpack("Ihh", raw)
    return vendor & 0xFFFF, product & 0xFFFF


class Hidraw:
    def __init__(self, path, vid, pid):
        self.path = path
        self.vid = vid
        self.pid = pid
        self.fd = None

    def open(self):
        if not self.path:
            raise DisplayError(NOT_FOUND, "no HID interface bound for this device")
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK | os.O_CLOEXEC)
        except OSError as error:
            raise _error(error, "open") from None
        try:
            identity = hidraw_identity(fd)
        except OSError as error:
            os.close(fd)
            raise _error(error, "identify") from None
        if identity != (self.vid, self.pid):
            os.close(fd)
            raise DisplayError(NOT_FOUND, f"{self.path} is now {identity[0]:04x}:{identity[1]:04x}, not "
                                          f"{self.vid:04x}:{self.pid:04x}")
        try:
            # Advisory lock: two copies of this program never drive the same cooler.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise DisplayError(BUSY, "another copy of Big Screen Monitor is using this cooler") from None
        self.fd = fd

    def write(self, data, timeout=WRITE_TIMEOUT):
        if self.fd is None:
            raise DisplayError(DISCONNECTED, "not open")
        if not 1 <= len(data) <= MAX_REPORT:
            raise ValueError("report size out of range")
        deadline = time.monotonic() + timeout
        while True:
            try:
                written = os.write(self.fd, data)
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DisplayError(TIMEOUT, "write timed out") from None
                select.select([], [self.fd], [], remaining)
            except OSError as error:
                raise _error(error, "write") from None
        if written != len(data):
            raise DisplayError(IO, f"short write ({written}/{len(data)})")
        return written

    def alive(self):
        return self.fd is not None and os.path.exists(self.path)

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
