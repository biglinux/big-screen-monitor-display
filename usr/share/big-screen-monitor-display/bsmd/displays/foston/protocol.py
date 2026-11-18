"""FSP (Foston Screen Protocol) v1, host side.

Byte-exact counterpart of ``device-clients/wince/src/fsp.h``: a 16-byte
header (magic ``FS``, version, type, sequence, flags, payload length,
payload CRC, header CRC) followed by the payload, little endian. The CRC is
CRC-16/CCITT-FALSE (``binascii.crc_hqx`` seeded with 0xFFFF).

The host sends rectangles of RGB565 pixels (raw, RLE or zlib) and a
PRESENT marker per frame; the device answers PRESENTED once the frame is on
the glass, so at most one frame is ever in flight. The device reports touch
events as they happen.
"""

import binascii
import struct
import zlib
from dataclasses import dataclass, field

import numpy as np

MAGIC = b"FS"
VERSION = 1
HEADER = struct.Struct("<2sBBHHIHH")
HEADER_SIZE = HEADER.size            # 16
MAX_PAYLOAD = 1024 * 1024

# host -> device
HELLO, PING, RECT, FILL, PRESENT = 0x01, 0x02, 0x10, 0x11, 0x12
BRIGHTNESS, CALIBRATE, BYE, TOUCHCFG = 0x20, 0x21, 0x22, 0x23
# device -> host
HELLO_ACK, PRESENTED, PONG, NAK, CREDIT, TOUCH, KEY, LOG = 0x81, 0x82, 0x83, 0x84, 0x85, 0x90, 0x91, 0xA0

ENC_RAW, ENC_RLE, ENC_DEFLATE = 0, 1, 2
TOUCH_DOWN, TOUCH_MOVE, TOUCH_UP = 1, 2, 3
NAK_REASONS = {1: "crc", 2: "too_big", 3: "bad_rect", 4: "decode", 5: "unknown", 6: "resync"}

BYE_WAIT, BYE_QUIT = 0, 1


def crc16(data):
    return binascii.crc_hqx(bytes(data), 0xFFFF)


def message(kind, payload=b"", seq=0):
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large: {len(payload)}")
    head = struct.pack("<2sBBHHIH", MAGIC, VERSION, kind, seq & 0xFFFF, 0, len(payload), crc16(payload))
    return head + struct.pack("<H", crc16(head)) + payload


# ------------------------------------------------------------------ encoders

def hello(host_name=""):
    name = host_name.encode("utf-8", "replace")[:63]
    return struct.pack("<HH", VERSION, 0) + name


def present(frame_id):
    return struct.pack("<I", frame_id & 0xFFFFFFFF)


def fill(x, y, w, h, color):
    return struct.pack("<HHHHH", x, y, w, h, color)


def rle_encode(pixels):
    """RLE tokens (see fsp.h) for a flat uint16 array."""
    flat = np.ascontiguousarray(pixels, dtype="<u2").ravel()
    n = flat.size
    if n == 0:
        return b""
    starts = np.concatenate(([0], np.flatnonzero(flat[1:] != flat[:-1]) + 1))
    lengths = np.diff(np.concatenate((starts, [n])))
    out = bytearray()
    literal_start = None
    raw = flat.tobytes()

    def flush_literal(end):
        nonlocal literal_start
        pos = literal_start
        while pos < end:
            count = min(end - pos, 0x8000)
            out.extend(struct.pack("<H", count - 1))
            out.extend(raw[pos * 2:(pos + count) * 2])
            pos += count
        literal_start = None

    for start, length in zip(starts.tolist(), lengths.tolist()):
        if length >= 3:
            if literal_start is not None:
                flush_literal(start)
            pixel = raw[start * 2:start * 2 + 2]
            while length:
                count = min(length, 0x8000)
                out.extend(struct.pack("<H", 0x8000 | (count - 1)))
                out.extend(pixel)
                length -= count
        elif literal_start is None:
            literal_start = start
    if literal_start is not None:
        flush_literal(n)
    return bytes(out)


@dataclass
class EncodedRect:
    kind: int                 # RECT or FILL
    payload: bytes
    encoding: str             # raw, rle, deflate, fill
    raw_size: int


def encode_rect(pixels, x, y, encoding="auto", level=1):
    """Payload for a (h, w) RGB565 uint16 array placed at (x, y).

    ``auto`` sends a FILL for uniform areas, zlib when it saves at least 10 %,
    raw otherwise. ``rle`` forces the RLE encoding (no compression library
    needed on the device side; kept as a fallback and for tests).
    """
    h, w = pixels.shape
    raw_size = w * h * 2
    flat = np.ascontiguousarray(pixels, dtype="<u2")
    if encoding in ("auto", "fill") and (flat == flat.flat[0]).all():
        return EncodedRect(FILL, fill(x, y, w, h, int(flat.flat[0])), "fill", raw_size)
    raw = flat.tobytes()

    def rect(enc, data):
        # x, y, w, h, encoding, reserved u8, reserved u16, reserved u16 (14 bytes, see fsp.c)
        return struct.pack("<HHHHBBHH", x, y, w, h, enc, 0, 0, 0) + data
    if encoding == "rle":
        return EncodedRect(RECT, rect(ENC_RLE, rle_encode(flat)), "rle", raw_size)
    if encoding in ("auto", "deflate"):
        packed = zlib.compress(raw, level)
        if encoding == "deflate" or len(packed) < raw_size * 0.9:
            return EncodedRect(RECT, rect(ENC_DEFLATE, packed), "deflate", raw_size)
    return EncodedRect(RECT, rect(ENC_RAW, raw), "raw", raw_size)


# ------------------------------------------------------------------ decoders

@dataclass
class Message:
    kind: int
    seq: int
    payload: bytes


@dataclass
class HelloAck:
    protocol: int
    width: int
    height: int
    bpp: int
    os_version: tuple
    memory_total_kb: int
    memory_free_kb: int
    brightness: int           # 0 none, 1 experimental (registry backlight)
    brightness_level: int     # 0-100, 255 unknown
    touch: bool
    usb_switched: bool
    credits: bool             # flow control (FSP_CREDIT), bsmd-ce >= 1.1
    strings: dict = field(default_factory=dict)

    @classmethod
    def parse(cls, payload):
        if len(payload) < 32:
            raise ValueError("short HELLO_ACK")
        proto, width, height, bpp, major, minor, build, total, free = struct.unpack_from("<HHHHIIIII", payload)
        bright, level, touch, flags = payload[28:32]
        names = ("client", "platform", "oem", "port", "usb_previous")
        values = payload[32:].split(b"\0")
        strings = {name: value.decode("utf-8", "replace") for name, value in zip(names, values)}
        return cls(proto, width, height, bpp, (major, minor, build), total, free, bright, level, bool(touch),
                   bool(flags & 1), bool(flags & 2), strings)


@dataclass
class TouchEvent:
    kind: int                 # TOUCH_DOWN, TOUCH_MOVE, TOUCH_UP
    x: int
    y: int
    tick: int                 # device milliseconds (GetTickCount)
    received: float = 0.0     # host monotonic time

    @classmethod
    def parse(cls, payload, received=0.0):
        kind, _, x, y, _, tick = struct.unpack_from("<BBHHHI", payload)
        return cls(kind, x, y, tick, received)


class Parser:
    """Incremental parser of device -> host messages, resynchronising on garbage."""

    def __init__(self):
        self.buffer = bytearray()
        self.dropped = 0
        self.crc_errors = 0

    def feed(self, data):
        self.buffer.extend(data)
        out = []
        buf = self.buffer
        while True:
            if len(buf) < HEADER_SIZE:
                index = buf.find(MAGIC[:1])
                if index < 0:
                    self.dropped += len(buf)
                    buf.clear()
                elif index:
                    self.dropped += index
                    del buf[:index]
                break
            magic, version, kind, seq, _flags, length, pcrc, hcrc = HEADER.unpack_from(buf)
            if magic != MAGIC or version != VERSION or length > MAX_PAYLOAD or hcrc != crc16(buf[:14]):
                index = buf.find(MAGIC[:1], 1)
                skip = index if index > 0 else len(buf)
                self.dropped += skip
                del buf[:skip]
                continue
            if len(buf) < HEADER_SIZE + length:
                break
            payload = bytes(buf[HEADER_SIZE:HEADER_SIZE + length])
            del buf[:HEADER_SIZE + length]
            if crc16(payload) != pcrc:
                self.crc_errors += 1
                continue
            out.append(Message(kind, seq, payload))
        return out
