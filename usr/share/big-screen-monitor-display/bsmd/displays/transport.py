"""Serial (CDC-ACM) transport shared by the serial display families.

Every write has a timeout (a panel holding CTS low can no longer block the
process forever), the port is opened exclusively (two programs never talk to
the same panel), and errors are classified into DisplayError kinds.
"""

import errno
import os

from .base import BUSY, DISCONNECTED, IO, PERMISSION, TIMEOUT, DisplayError


def classify_serial_error(error, port, what):
    if isinstance(error, DisplayError):
        return error
    name = type(error).__name__
    number = getattr(error, "errno", None)
    text = str(error).lower()
    if name == "SerialTimeoutException" or "timeout" in text:
        kind = TIMEOUT
    elif number in (errno.EACCES, errno.EPERM) or "permission denied" in text:
        kind = PERMISSION
    elif number in (errno.EBUSY, errno.EAGAIN) or "lock" in text or "busy" in text:
        kind = BUSY
    elif number in (errno.ENODEV, errno.ENOENT, errno.ENXIO, errno.EIO) or (port and not os.path.exists(port)):
        kind = DISCONNECTED
    else:
        kind = IO
    return DisplayError(kind, f"{what} failed on {port}", error)


class SerialTransport:
    CHUNK = 32 * 1024

    def __init__(self, port, baudrate=115200, rtscts=True, write_timeout=5.0, read_timeout=1.0,
                 serial_module=None):
        if serial_module is None:
            import serial as serial_module
        self.port = port
        self._serial_module = serial_module
        self._options = {"baudrate": baudrate, "rtscts": rtscts, "write_timeout": write_timeout,
                         "timeout": read_timeout}
        self.ser = None

    def open(self):
        try:
            self.ser = self._serial_module.Serial(self.port, exclusive=True, **self._options)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
        except Exception as error:
            self.close()
            raise classify_serial_error(error, self.port, "open")
        return self

    def close(self):
        ser, self.ser = self.ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001 - closing a vanished port may fail
                pass

    def write(self, data):
        if self.ser is None:
            raise DisplayError(DISCONNECTED, f"{self.port} is not open")
        view = memoryview(bytes(data) if not isinstance(data, (bytes, bytearray)) else data)
        try:
            for offset in range(0, len(view), self.CHUNK):
                chunk = view[offset:offset + self.CHUNK]
                written = self.ser.write(chunk)
                if written is not None and written != len(chunk):
                    raise DisplayError(IO, f"short write {written}/{len(chunk)} on {self.port}")
        except Exception as error:
            raise classify_serial_error(error, self.port, "write")
        return len(view)

    def read(self, size):
        if self.ser is None:
            raise DisplayError(DISCONNECTED, f"{self.port} is not open")
        try:
            return bytes(self.ser.read(size) or b"")
        except Exception as error:
            raise classify_serial_error(error, self.port, "read")

    def reset_input(self):
        if self.ser is not None:
            try:
                self.ser.reset_input_buffer()
            except Exception as error:
                raise classify_serial_error(error, self.port, "flush")

    def drain_input(self):
        """Discard whatever the panel already sent (non-blocking)."""
        if self.ser is None:
            return b""
        try:
            waiting = getattr(self.ser, "in_waiting", 0) or 0
            return bytes(self.ser.read(waiting)) if waiting else b""
        except Exception as error:
            raise classify_serial_error(error, self.port, "read")

    def alive(self):
        """Cheap liveness check: port node present and modem lines readable."""
        if self.ser is None or not os.path.exists(self.port):
            raise DisplayError(DISCONNECTED, f"{self.port} disappeared")
        try:
            _ = self.ser.cts
        except Exception as error:
            raise classify_serial_error(error, self.port, "probe")
