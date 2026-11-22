"""Serial (CDC-ACM) and TCP transports of the display families.

Every write has a timeout (a panel holding CTS low can no longer block the
process forever), the port is opened exclusively (two programs never talk to
the same panel), and errors are classified into DisplayError kinds.
"""

import errno
import os
import select
import socket

from .base import BUSY, DISCONNECTED, IO, NOT_FOUND, PERMISSION, TIMEOUT, DisplayError


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


class TcpTransport:
    """The serial transport's interface over a TCP connection.

    Used by devices that run Linux and reach the PC over a USB network
    (the FOSTON FS-707DC with BigFoston OS). Reads wait with select() so a
    reader thread never blocks the writer; writes have a timeout."""

    CHUNK = 64 * 1024

    def __init__(self, host, port, connect_timeout=3.0, write_timeout=5.0, read_timeout=1.0):
        self.host, self.tcp_port = host, port
        self.port = f"tcp://{host}:{port}"
        self._connect_timeout = connect_timeout
        self._write_timeout = write_timeout
        self._read_timeout = read_timeout
        self.sock = None

    def open(self):
        try:
            sock = socket.create_connection((self.host, self.tcp_port), timeout=self._connect_timeout)
        except socket.timeout as error:
            raise DisplayError(TIMEOUT, f"no answer from {self.port}", error)
        except ConnectionRefusedError as error:
            raise DisplayError(NOT_FOUND, f"nothing listening on {self.port}", error)
        except OSError as error:
            kind = NOT_FOUND if error.errno in (errno.EHOSTUNREACH, errno.ENETUNREACH) else IO
            raise DisplayError(kind, f"cannot connect to {self.port}", error)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self._write_timeout)          # affects sendall only; reads use select
        self.sock = sock
        return self

    def close(self):
        sock, self.sock = self.sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _check(self):
        if self.sock is None:
            raise DisplayError(DISCONNECTED, f"{self.port} is not open")
        return self.sock

    def write(self, data):
        sock = self._check()
        view = memoryview(bytes(data) if not isinstance(data, (bytes, bytearray)) else data)
        try:
            sock.sendall(view)
        except socket.timeout as error:
            raise DisplayError(TIMEOUT, f"write timed out on {self.port}", error)
        except OSError as error:
            raise DisplayError(DISCONNECTED, f"write failed on {self.port}", error)
        return len(view)

    def _recv(self, size, timeout):
        sock = self._check()
        try:
            ready, _, _ = select.select([sock], [], [], timeout)
            if not ready:
                return b""
            data = sock.recv(size)
        except (OSError, ValueError) as error:
            raise DisplayError(DISCONNECTED, f"read failed on {self.port}", error)
        if not data:
            raise DisplayError(DISCONNECTED, f"{self.port} closed the connection")
        return data

    def read(self, size):
        return self._recv(size, self._read_timeout)

    def reset_input(self):
        self.drain_input()

    def drain_input(self):
        """Whatever the device already sent (non-blocking)."""
        out = b""
        while self.sock is not None:
            data = self._recv(self.CHUNK, 0)
            if not data:
                break
            out += data
        return out

    def alive(self):
        self._check()
