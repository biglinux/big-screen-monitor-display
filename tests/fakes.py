"""Fake USB (pyusb) and serial (pyserial) modules for driver tests."""

import errno
import struct
import types


class USBError(IOError):
    def __init__(self, strerror, error_code=None, errno_=None):
        super().__init__(errno_, strerror)
        self.backend_error_code = error_code


class USBTimeoutError(USBError):
    pass


class FakeAX206Device:
    idVendor, idProduct, bus, address = 0x1908, 0x0102, 5, 13

    def __init__(self, width=480, height=320):
        self.width, self.height = width, height
        self.writes = []          # (endpoint, bytes)
        self.blits = []           # (x0, y0, x1, y1, payload_len)
        self.faults = []          # exceptions raised by the next operations
        self.brightness = None
        self._pending = None
        self._tag = 0
        self.reset_called = False

    def _maybe_fail(self):
        if self.faults:
            fault = self.faults.pop(0)
            if fault:
                raise fault

    def is_kernel_driver_active(self, interface):
        return False

    def set_configuration(self):
        pass

    def reset(self):
        self.reset_called = True

    def write(self, endpoint, data, timeout=None):
        self._maybe_fail()
        data = bytes(data)
        self.writes.append((endpoint, data))
        if data[:4] == b"USBC":
            self._tag = struct.unpack("<I", data[4:8])[0]
            cmd = data[15:31]
            self._pending = cmd
            if cmd[5] == 6 and cmd[6] == 0x01:
                self.brightness = cmd[9]
        elif self._pending is not None and self._pending[6] == 0x12:
            c = self._pending
            x0, y0 = c[7] | c[8] << 8, c[9] | c[10] << 8
            x1, y1 = (c[11] | c[12] << 8) + 1, (c[13] | c[14] << 8) + 1
            assert len(data) == (x1 - x0) * (y1 - y0) * 2
            self.blits.append((x0, y0, x1, y1, len(data)))
        return len(data)

    def read(self, endpoint, length, timeout=None):
        self._maybe_fail()
        if length == 5:
            return bytes([self.width & 255, self.width >> 8, self.height & 255, self.height >> 8, 0])
        return b"USBS" + struct.pack("<I", self._tag) + b"\0\0\0\0" + b"\0"


def fake_usb(device):
    holder = {"device": device}
    core = types.SimpleNamespace(find=lambda **_kw: holder["device"], USBError=USBError)
    util = types.SimpleNamespace(claim_interface=lambda *_a: None, release_interface=lambda *_a: None,
                                 dispose_resources=lambda *_a: None)
    module = types.SimpleNamespace(core=core, util=util, holder=holder)
    return module


class SerialTimeoutException(Exception):
    pass


class FakeSerial:
    instances = []

    def __init__(self, port, baudrate, timeout=None, write_timeout=None, rtscts=False, exclusive=False):
        self.port, self.write_timeout, self.rtscts, self.exclusive = port, write_timeout, rtscts, exclusive
        self.data = bytearray()
        self.faults = []
        self.is_open = True
        self.cts = True
        FakeSerial.instances.append(self)

    def write(self, data):
        if self.faults:
            fault = self.faults.pop(0)
            if fault:
                raise fault
        self.data += bytes(data)
        return len(data)

    def read(self, size):
        return b""  # the original 3.5" model does not answer HELLO

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        self.is_open = False


def fake_serial_module():
    return types.SimpleNamespace(Serial=FakeSerial, SerialTimeoutException=SerialTimeoutException)


def fake_comports(device="/dev/null"):
    port = types.SimpleNamespace(device=device, serial_number="USB35INCHIPSV2", vid=0x1A86, pid=0x5722)
    return lambda: [port]


ENODEV = USBError("No such device (it may have been disconnected)", -4, errno.ENODEV)
ETIMEDOUT = USBTimeoutError("Operation timed out", -7, errno.ETIMEDOUT)
EIO = USBError("Input/Output Error", -1, errno.EIO)
