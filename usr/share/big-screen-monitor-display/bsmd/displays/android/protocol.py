"""BSDP (Big Screen Display Protocol) v1 - computer side.

The Android app (``android/app/src/main/java/.../Protocol.kt``) is the other
end; ``tests/data/bsdp-vectors.json`` holds byte-exact vectors both test
suites check, so the two implementations cannot drift apart.

Framing (big endian, over TLS on the network, plain over a USB accessory)::

    "BS"  u8 version  u8 type  u32 payload length  | payload

Streams are reliable (TCP, USB bulk), so a bad header is a protocol violation
and ends the connection instead of a resynchronisation. Control messages carry
a UTF-8 JSON object; frames, touches and acknowledgements are binary.

Session
    app -> HELLO (who it is, screen, formats, client nonce)
    pc  -> CHALLENGE (server id/name, server nonce, "auth" or "pair")
    app -> AUTH (HMAC of the device token)       - known device
           PAIR (ticket from the QR code, or "confirm" with a code shown on
           both screens and approved on the computer)
    pc  -> PAIR_WAIT (the code, while the computer decides)
    pc  -> WELCOME (display id, settings for the app; the token once, on pairing)
           or REJECT
    then frames (RECT... PRESENT -> PRESENTED), touches, commands, pings.
"""

import base64
import hashlib
import hmac
import io
import json
import struct
import zlib
from dataclasses import dataclass

MAGIC = b"BS"
VERSION = 1
HEADER = struct.Struct(">2sBBI")
HEADER_SIZE = HEADER.size                 # 8
MAX_PAYLOAD = 8 * 1024 * 1024             # a whole lossless frame of a large tablet
MAX_CLIENT_PAYLOAD = 64 * 1024            # what an app may send in one message
MAX_JSON = 64 * 1024

# app -> computer
HELLO, AUTH, PAIR, VIEW, PRESENTED, TOUCH, COMMAND, STATS = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08
# both ways
PING, PONG, BYE = 0x09, 0x0A, 0x0B
# computer -> app
CHALLENGE, PAIR_WAIT, WELCOME, REJECT, CONFIG, RECT, PRESENT, BRIGHTNESS = (0x41, 0x42, 0x43, 0x44, 0x45, 0x50,
                                                                         0x51, 0x52)

CLIENT_KINDS = {HELLO, AUTH, PAIR, VIEW, PRESENTED, TOUCH, COMMAND, STATS, PING, PONG, BYE}
JSON_KINDS = {HELLO, AUTH, PAIR, VIEW, COMMAND, STATS, BYE, CHALLENGE, PAIR_WAIT, WELCOME, REJECT, CONFIG}

# RECT formats
FMT_FILL, FMT_RGB_ZLIB, FMT_JPEG, FMT_PNG, FMT_WEBP = 0, 1, 2, 3, 4
FORMAT_NAMES = {FMT_FILL: "fill", FMT_RGB_ZLIB: "rgb-zlib", FMT_JPEG: "jpeg", FMT_PNG: "png", FMT_WEBP: "webp"}
RECT_HEADER = struct.Struct(">HHHHHHBB")  # x, y, w, h, canvas w, canvas h, format, flags
PRESENT_BODY = struct.Struct(">IHH")      # frame id, canvas w, canvas h
PRESENTED_BODY = struct.Struct(">IHH")    # frame id, decode ms, queued frames
TOUCH_BODY = struct.Struct(">BBHHHI")     # kind, pointer, x, y, reserved, time ms
TOKEN_BODY = struct.Struct(">I")          # PING / PONG

TOUCH_DOWN, TOUCH_MOVE, TOUCH_UP, TOUCH_CANCEL = 1, 2, 3, 4

# REJECT reasons (the app shows its own text for each)
R_VERSION, R_UNKNOWN, R_AUTH, R_DENIED, R_EXPIRED, R_BUSY, R_RATE, R_REVOKED, R_DISABLED, R_REPLACED = (
    "version", "unknown_device", "auth_failed", "denied", "expired", "busy", "rate_limited", "revoked",
    "disabled", "replaced")

AUTH_LABEL = b"bsmd-auth-v1"
PAIR_LABEL = b"bsmd-pair-v1"
SAS_LABEL = b"bsmd-sas-v1"


class ProtocolError(Exception):
    """The peer broke the protocol: the connection must be closed."""


def b64e(data):
    return base64.urlsafe_b64encode(bytes(data)).rstrip(b"=").decode("ascii")


def b64d(text, limit=256):
    if not isinstance(text, str) or len(text) > limit:
        raise ProtocolError("bad base64 field")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as error:
        raise ProtocolError("bad base64 field") from error


# ------------------------------------------------------------------ framing

def message(kind, payload=b""):
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"payload too large: {len(payload)}")
    return HEADER.pack(MAGIC, VERSION, kind, len(payload)) + payload


def json_message(kind, obj):
    data = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_JSON:
        raise ValueError("control message too large")
    return message(kind, data)


@dataclass
class Message:
    kind: int
    payload: bytes

    def json(self):
        if self.kind not in JSON_KINDS:
            raise ProtocolError(f"message 0x{self.kind:02x} carries no JSON")
        if len(self.payload) > MAX_JSON:
            raise ProtocolError("control message too large")
        try:
            value = json.loads(self.payload.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise ProtocolError("invalid JSON") from error
        if not isinstance(value, dict):
            raise ProtocolError("JSON message is not an object")
        return value


class Parser:
    """Incremental decoder. ``limit`` caps one payload (the computer only
    accepts small messages from an app); ``kinds`` lists acceptable types."""

    def __init__(self, limit=MAX_PAYLOAD, kinds=None):
        self.buffer = bytearray()
        self.limit = limit
        self.kinds = kinds

    def feed(self, data):
        self.buffer.extend(data)
        out = []
        buf = self.buffer
        while len(buf) >= HEADER_SIZE:
            magic, version, kind, length = HEADER.unpack_from(buf)
            if magic != MAGIC:
                raise ProtocolError("bad magic")
            if version != VERSION:
                raise ProtocolError(f"unsupported version {version}")
            if self.kinds is not None and kind not in self.kinds:
                raise ProtocolError(f"unexpected message 0x{kind:02x}")
            if length > self.limit:
                raise ProtocolError(f"message too large ({length} bytes)")
            if len(buf) < HEADER_SIZE + length:
                break
            out.append(Message(kind, bytes(buf[HEADER_SIZE:HEADER_SIZE + length])))
            del buf[:HEADER_SIZE + length]
        return out


# ------------------------------------------------------------------ fields

def text(value, limit=80, default=""):
    """A printable string from untrusted JSON, trimmed to ``limit``."""
    if not isinstance(value, str):
        return default
    value = "".join(ch for ch in value if ch.isprintable())[:limit].strip()
    return value or default


def integer(value, low, high, default=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    value = int(value)
    return value if low <= value <= high else default


def device_id(value):
    """The app's random installation id (UUID-like, lowercase hex and dashes)."""
    if not isinstance(value, str) or not 16 <= len(value) <= 64 or \
            any(ch not in "0123456789abcdef-" for ch in value):
        raise ProtocolError("invalid device id")
    return value


def display_id(dev_id):
    return "android-" + hashlib.sha256(dev_id.encode("ascii")).hexdigest()[:12]


@dataclass
class Hello:
    device_id: str
    name: str
    model: str
    manufacturer: str
    android: str
    sdk: int
    app_version: str
    screen: tuple                 # physical pixels (w, h) in the current rotation
    view: tuple                   # usable area for the picture (w, h)
    density: int
    formats: tuple
    touch: bool
    brightness: bool
    transport: str                # wifi, ethernet, vpn, usb-accessory, usb-tether, usb-adb, other
    nonce: bytes
    battery: bool

    TRANSPORTS = ("wifi", "ethernet", "vpn", "usb-accessory", "usb-tether", "usb-adb", "other")

    @classmethod
    def parse(cls, obj):
        if integer(obj.get("proto"), 0, 255) != VERSION:
            raise ProtocolError("unsupported protocol")
        dev = device_id(obj.get("device_id"))
        nonce = b64d(obj.get("nonce"), 64)
        if len(nonce) < 16:
            raise ProtocolError("short nonce")
        screen = obj.get("screen") if isinstance(obj.get("screen"), dict) else {}
        view = obj.get("view") if isinstance(obj.get("view"), dict) else {}
        sw, sh = integer(screen.get("w"), 64, 16384), integer(screen.get("h"), 64, 16384)
        vw, vh = integer(view.get("w"), 64, 16384), integer(view.get("h"), 64, 16384)
        if not (sw and sh and vw and vh):
            raise ProtocolError("invalid screen size")
        formats = obj.get("formats") if isinstance(obj.get("formats"), list) else []
        known = {name: fmt for fmt, name in FORMAT_NAMES.items()}
        transport = obj.get("transport") if obj.get("transport") in cls.TRANSPORTS else "other"
        return cls(dev, text(obj.get("name"), 40, "Android"), text(obj.get("model"), 60),
                   text(obj.get("manufacturer"), 40), text(obj.get("android"), 16),
                   integer(obj.get("sdk"), 1, 1000, 0), text(obj.get("app_version"), 24),
                   (sw, sh), (vw, vh), integer(obj.get("density"), 50, 2000, 160),
                   tuple(known[name] for name in formats if name in known) or (FMT_FILL, FMT_RGB_ZLIB),
                   bool(obj.get("touch", True)), bool(obj.get("brightness", True)), transport, nonce,
                   bool(obj.get("battery", True)))


def parse_view(obj):
    w, h = integer(obj.get("w"), 64, 16384), integer(obj.get("h"), 64, 16384)
    if not (w and h):
        raise ProtocolError("invalid view size")
    return w, h


@dataclass
class TouchEvent:
    kind: int
    x: int
    y: int
    tick: int
    received: float = 0.0
    pointer: int = 0

    @classmethod
    def parse(cls, payload, received=0.0):
        if len(payload) != TOUCH_BODY.size:
            raise ProtocolError("bad TOUCH")
        kind, pointer, x, y, _reserved, tick = TOUCH_BODY.unpack(payload)
        if kind not in (TOUCH_DOWN, TOUCH_MOVE, TOUCH_UP, TOUCH_CANCEL):
            raise ProtocolError("bad touch kind")
        return cls(kind, x, y, tick, received, pointer)


def touch(kind, x, y, tick, pointer=0):
    return message(TOUCH, TOUCH_BODY.pack(kind, pointer, x, y, 0, tick & 0xFFFFFFFF))


def parse_presented(payload):
    if len(payload) != PRESENTED_BODY.size:
        raise ProtocolError("bad PRESENTED")
    return PRESENTED_BODY.unpack(payload)


def parse_token(payload):
    if len(payload) != TOKEN_BODY.size:
        raise ProtocolError("bad PING/PONG")
    return TOKEN_BODY.unpack(payload)[0]


# ------------------------------------------------------------------ crypto helpers

def _mac(key, label, *parts):
    mac = hmac.new(key, label, hashlib.sha256)
    for part in parts:
        part = part.encode("utf-8") if isinstance(part, str) else bytes(part)
        mac.update(struct.pack(">I", len(part)))
        mac.update(part)
    return mac.digest()


def auth_proof(token, server_nonce, client_nonce, dev_id):
    return _mac(token, AUTH_LABEL, server_nonce, client_nonce, dev_id)


def pair_proof(secret, server_nonce, client_nonce, dev_id):
    return _mac(secret, PAIR_LABEL, server_nonce, client_nonce, dev_id)


def sas_code(cert_fingerprint, server_nonce, client_nonce, dev_id):
    """Six digits both screens show while pairing by confirmation. They cover
    the computer's certificate as the app saw it, so a machine in the middle
    produces two different codes."""
    digest = hashlib.sha256(SAS_LABEL + bytes(cert_fingerprint) + bytes(server_nonce) + bytes(client_nonce)
                            + dev_id.encode("ascii")).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


# ------------------------------------------------------------------ frames

@dataclass
class EncodedRect:
    payload: bytes
    fmt: int
    raw_size: int


def rect(x, y, w, h, canvas, fmt, data, flags=0):
    return RECT_HEADER.pack(x, y, w, h, canvas[0], canvas[1], fmt, flags) + bytes(data)


def encode_rect(image, box, canvas, quality="balanced", formats=(FMT_FILL, FMT_RGB_ZLIB, FMT_JPEG)):
    """Encode ``image.crop(box)`` (RGB) for the app.

    * uniform area -> FILL (3 bytes);
    * ``lossless`` -> RGB + zlib (fast, exact: text, charts and icons stay sharp);
    * ``balanced`` -> zlib unless the area is photographic (compresses badly),
      then JPEG 88; ``economy`` -> JPEG 72 for any larger area.
    """
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    part = image if (x0, y0, x1, y1) == (0, 0, *image.size) else image.crop(box)
    if part.mode != "RGB":
        part = part.convert("RGB")
    raw = part.tobytes()
    raw_size = len(raw)
    if FMT_FILL in formats:
        first = raw[:3]
        if raw == first * (w * h):
            return EncodedRect(rect(x0, y0, w, h, canvas, FMT_FILL, first), FMT_FILL, raw_size)
    jpeg_ok = FMT_JPEG in formats and w >= 16 and h >= 16
    if quality == "economy" and jpeg_ok and w * h >= 64 * 64:
        return _jpeg(part, x0, y0, canvas, 72, raw_size)
    packed = zlib.compress(raw, 1)
    if quality != "lossless" and jpeg_ok and w * h >= 96 * 96 and len(packed) > raw_size * 0.35:
        jpeg = _jpeg(part, x0, y0, canvas, 88 if quality != "economy" else 72, raw_size)
        if len(jpeg.payload) < len(packed):
            return jpeg
    return EncodedRect(rect(x0, y0, w, h, canvas, FMT_RGB_ZLIB, packed), FMT_RGB_ZLIB, raw_size)


def _jpeg(part, x0, y0, canvas, quality, raw_size):
    out = io.BytesIO()
    part.save(out, "JPEG", quality=quality, optimize=False, subsampling=0 if quality >= 85 else 2)
    w, h = part.size
    return EncodedRect(rect(x0, y0, w, h, canvas, FMT_JPEG, out.getvalue()), FMT_JPEG, raw_size)


def present(frame_id, canvas):
    return message(PRESENT, PRESENT_BODY.pack(frame_id & 0xFFFFFFFF, canvas[0], canvas[1]))
