"""Turing Smart Screen native USB family (VID 0x1cbe): 2.8" round, 4.6",
5.2", 8.0", 8.8", 9.2" and 12.3".

Protocol as implemented by turing-smart-screen-python (Copyright (C) 2021
Matthieu Houdebine, GPL-3.0-or-later): a 500-byte command header encrypted
with DES-CBC (fixed key), padded to 512 bytes, followed by a PNG or JPEG
frame on the bulk OUT endpoint of interface 0; the panel answers on bulk IN.
Only still images are used here; video playback and on-device storage
commands are deliberately not implemented.
"""

import errno
import io
import struct
import time

from PIL import Image

from .base import (BUSY, DISCONNECTED, IO, NOT_FOUND, PERMISSION, PROTOCOL, TIMEOUT, Capabilities, DeviceInfo,
                   DisplayError, RasterDriver, percent)
from . import des

VENDOR_ID = 0x1CBE
MODELS = {   # PID -> (name, native portrait size, shape)
    0x0028: ("Turing Smart Screen 2.8\" round", (480, 480), "round"),
    0x0046: ("Turing Smart Screen 4.6\"", (320, 960), "rect"),
    0x0050: ("Turing Smart Screen 5.2\"", (720, 1280), "rect"),
    0x0080: ("Turing Smart Screen 8.0\"", (800, 1280), "rect"),
    0x0088: ("Turing Smart Screen 8.8\"", (480, 1920), "rect"),
    0x0092: ("Turing Smart Screen 9.2\"", (462, 1920), "rect"),
    0x0123: ("Turing Smart Screen 12.3\"", (720, 1920), "rect"),
}
DES_KEY = b"slv3tuzx"
MAX_PAYLOAD = 1024 * 1024        # larger transfers time out on the panel
CMD_SYNC, CMD_RESTART, CMD_BRIGHTNESS, CMD_UPLOAD_JPEG, CMD_UPLOAD_PNG = 10, 11, 14, 101, 102


def _fast_des():
    try:
        try:
            from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
        except ImportError:
            from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
        from cryptography.hazmat.primitives.ciphers import Cipher, modes

        def encrypt(data):
            encryptor = Cipher(TripleDES(DES_KEY * 3), modes.CBC(DES_KEY)).encryptor()   # K1=K2=K3 is DES
            return encryptor.update(data + b"\x00" * (-len(data) % 8)) + encryptor.finalize()
        return encrypt
    except Exception:  # noqa: BLE001 - optional accelerator
        return None


_ENCRYPT = _fast_des() or (lambda data: des.encrypt_cbc(DES_KEY, DES_KEY, data))


def command_header(cmd, now=None):
    """500-byte header: command, magic 0x1A6D, milliseconds since local midnight."""
    packet = bytearray(500)
    packet[0] = cmd
    packet[2], packet[3] = 0x1A, 0x6D
    now = time.time() if now is None else now
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    packet[4:8] = struct.pack("<I", int((now - midnight) * 1000) & 0xFFFFFFFF)
    return packet


def encrypt_header(packet):
    encrypted = _ENCRYPT(bytes(packet))
    final = bytearray(512)
    final[:len(encrypted)] = encrypted
    final[510], final[511] = 161, 26
    return bytes(final)


def response_ok(response):
    return bool(response) and (len(response) > 1 and response[1] == 0xC8 or len(response) > 8 and response[8] == 0xC8)


def encode_frame(image, max_bytes=MAX_PAYLOAD):
    """PNG when it fits (lossless, sharp text), otherwise the best JPEG that fits."""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=1)
    data = buffer.getvalue()
    if len(data) <= max_bytes:
        return CMD_UPLOAD_PNG, data
    rgb = image.convert("RGB")
    for quality in (92, 85, 75, 60, 45):
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=quality, subsampling=0 if quality >= 85 else 2)
        if len(buffer.getvalue()) <= max_bytes:
            return CMD_UPLOAD_JPEG, buffer.getvalue()
    raise DisplayError(PROTOCOL, "frame does not fit the panel payload limit")


class TuringUSB(RasterDriver):
    DRIVER = "turing_usb"
    WRITE_TIMEOUT_MS = 3000

    def __init__(self, usb_module=None, pid=None, bus=None, address=None, options=None):
        super().__init__()
        if usb_module is None:
            import usb.core
            import usb.util
            usb_module = usb
        self._usb = usb_module
        self.pid, self.bus, self.address = pid, bus, address
        self.options = options or {}
        self.dev = None
        self.ep_out = self.ep_in = None
        self.native_portrait = (480, 1920)
        self.capabilities = Capabilities(encoding="png/jpeg", transport="usb", partial_update=False,
                                         max_payload=MAX_PAYLOAD)

    def _classify(self, error, what):
        if isinstance(error, DisplayError):
            return error
        number = getattr(error, "errno", None) or getattr(error, "backend_error_code", None)
        text = str(error).lower()
        if type(error).__name__ == "USBTimeoutError" or number in (errno.ETIMEDOUT, -7) or "timed out" in text:
            kind = TIMEOUT
        elif number in (errno.ENODEV, errno.ENOENT, -4) or "no such device" in text:
            kind = DISCONNECTED
        elif number in (errno.EACCES, errno.EPERM, -3) or "access denied" in text:
            kind = PERMISSION
        elif number in (errno.EBUSY, -6) or "busy" in text:
            kind = BUSY
        else:
            kind = IO
        return DisplayError(kind, f"Turing USB {what} failed", error)

    def _find(self):
        def match(dev):
            return (dev.idVendor == VENDOR_ID and dev.idProduct in MODELS
                    and (self.pid is None or dev.idProduct == self.pid)
                    and (self.bus is None or (dev.bus, dev.address) == (self.bus, self.address)))
        try:
            return self._usb.core.find(custom_match=match)
        except Exception as error:  # noqa: BLE001
            raise DisplayError(NOT_FOUND, "USB backend unavailable", error)

    def open(self):
        dev = self._find()
        if dev is None:
            raise DisplayError(NOT_FOUND, "Turing USB panel not connected")
        name, self.native_portrait, shape = MODELS[dev.idProduct]
        self.dev = dev
        try:
            try:
                if dev.is_kernel_driver_active(0):
                    dev.detach_kernel_driver(0)     # interface 0 of this vendor device only
            except NotImplementedError:
                pass
            try:
                dev.set_configuration()
            except self._usb.core.USBError as error:
                if getattr(error, "errno", None) != errno.EBUSY:
                    raise
            interface = dev.get_active_configuration()[(0, 0)]
            util = self._usb.util
            self.ep_out = util.find_descriptor(interface, custom_match=lambda e: util.endpoint_direction(
                e.bEndpointAddress) == util.ENDPOINT_OUT)
            self.ep_in = util.find_descriptor(interface, custom_match=lambda e: util.endpoint_direction(
                e.bEndpointAddress) == util.ENDPOINT_IN)
            if self.ep_out is None or self.ep_in is None:
                raise DisplayError(PROTOCOL, "Turing USB endpoints not found")
            util.claim_interface(dev, 0)
            response = self.command(CMD_SYNC)
        except Exception as error:
            classified = self._classify(error, "open")
            self.close()
            raise classified
        width, height = self.native_portrait
        self.native_size = (height, width) if height > width else (width, height)
        self.capabilities.native_size = self.native_size
        self.capabilities.shape = shape
        self.info = DeviceInfo(self.DRIVER, name, *self.native_size, location=f"usb bus {dev.bus} addr {dev.address}",
                               details={"sync_ok": response_ok(response)})
        self._prev = None
        return self.info

    def close(self):
        dev, self.dev = self.dev, None
        self._prev = None
        if dev is not None:
            for call in (lambda: self._usb.util.release_interface(dev, 0),
                         lambda: self._usb.util.dispose_resources(dev)):
                try:
                    call()
                except Exception:  # noqa: BLE001
                    pass

    def transfer(self, data, timeout_ms=None):
        if self.dev is None:
            raise DisplayError(DISCONNECTED, "Turing USB not open")
        timeout_ms = timeout_ms or self.WRITE_TIMEOUT_MS + len(data) // 2000
        try:
            self.ep_out.write(data, timeout_ms)
            response = bytes(self.ep_in.read(512, timeout_ms))
        except Exception as error:
            self._prev = None
            raise self._classify(error, "transfer")
        try:   # flush any extra status packets
            for _ in range(4):
                self.ep_in.read(512, 50)
        except Exception:  # noqa: BLE001 - timeout means the IN endpoint is empty
            pass
        return response

    def command(self, cmd, payload=b"", fields=None):
        header = command_header(cmd)
        for offset, value in (fields or {}).items():
            header[offset] = value
        return self.transfer(encrypt_header(header) + payload)

    def set_brightness(self, level):
        self.command(CMD_BRIGHTNESS, fields={8: int(percent(level) / 100 * 102)})

    def probe(self):
        self.command(CMD_SYNC)

    def _send(self, image):
        # The panel takes portrait frames; ROTATE_270 is the reference "landscape".
        image = image.transpose(Image.Transpose.ROTATE_270)
        cmd, data = encode_frame(image)
        size = len(data)
        self.command(cmd, data, fields={8: size >> 24 & 0xFF, 9: size >> 16 & 0xFF, 10: size >> 8 & 0xFF,
                                        11: size & 0xFF})
        return size

    def _blit_full(self, image):
        return self._send(image)

    def _blit(self, image, rect):
        return self._send(image)
