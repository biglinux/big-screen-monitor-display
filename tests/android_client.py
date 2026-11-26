"""Reference BSDP client: what the Android app does, in Python, for the tests.

It connects (TLS like the app, or a plain socket pair standing in for the USB
accessory), pairs or authenticates, composes RECT messages onto a canvas,
acknowledges each PRESENT, answers PINGs and can send touches, views and
commands. Messages it does not handle are kept in ``self.other``.
"""

import hashlib
import io
import json
import socket
import ssl
import struct
import threading
import time
import uuid
import zlib

from PIL import Image

from bsmd.displays.android import protocol as bsdp
from bsmd.displays.android.link import Link


class Client:
    def __init__(self, port=None, host="127.0.0.1", device_id=None, name="Pixel Test", transport="wifi",
                 view=(1280, 720), token=None, pinned=None, sock=None, formats=("fill", "rgb-zlib", "jpeg")):
        self.host, self.port = host, port
        self.device_id = device_id or str(uuid.uuid4())
        self.name = name
        self.transport = transport
        self.view = view
        self.token = token
        self.pinned = pinned
        self.formats = list(formats)
        self.sock = sock
        self.tls = sock is None
        self.parser = bsdp.Parser()
        self.cert_fp = b""
        self.challenge = None
        self.welcome = None
        self.reject = None
        self.pair_wait = None
        self.config = None
        self.canvas = None
        self.frames = 0
        self.presented = []
        self.rects = []
        self.brightness = None
        self.bye = None
        self.other = []
        self.lock = threading.Lock()
        self.reader = None
        self.running = False
        self.nonce = bsdp.b64e(bytes(range(24)) if device_id == "fixed" else uuid.uuid4().bytes + b"nonce123")
        self.hold_presented = False       # simulate a phone that stopped drawing
        self.link = None

    # ------------------------------------------------------------ connection
    def connect(self, timeout=5.0):
        if self.sock is None:
            raw = socket.create_connection((self.host, self.port), timeout=timeout)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE        # the app pins the certificate instead
            self.sock = context.wrap_socket(raw)
            self.cert_fp = hashlib.sha256(self.sock.getpeercert(binary_form=True)).digest()
            if self.pinned is not None and self.cert_fp != self.pinned:
                self.sock.close()
                raise ssl.SSLError("pinned certificate mismatch")
        self.sock.settimeout(timeout)
        return self

    def send(self, data):
        if self.link is not None:
            self.link.send(data)
            return
        with self.lock:
            self.sock.sendall(data)

    def send_json(self, kind, obj):
        self.send(bsdp.json_message(kind, obj))

    def recv(self, timeout=5.0):
        deadline = time.monotonic() + timeout
        while True:
            pending = getattr(self, "_pending", [])
            if pending:
                return pending.pop(0)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no message")
            self.sock.settimeout(remaining)
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("closed")
            self._pending = pending + self.parser.feed(data)

    def hello(self, extra=None):
        body = {"proto": 1, "device_id": self.device_id, "name": self.name, "model": "Test 7",
                "manufacturer": "Google", "android": "14", "sdk": 34, "app_version": "1.0.0",
                "screen": {"w": self.view[0], "h": self.view[1]}, "view": {"w": self.view[0], "h": self.view[1]},
                "density": 420, "formats": self.formats, "touch": True, "brightness": True,
                "transport": self.transport, "nonce": self.nonce}
        body.update(extra or {})
        self.send_json(bsdp.HELLO, body)
        msg = self.recv()
        if msg.kind == bsdp.REJECT:
            self.reject = msg.json()
            return None
        assert msg.kind == bsdp.CHALLENGE, hex(msg.kind)
        self.challenge = msg.json()
        return self.challenge

    def _server_nonce(self):
        return bsdp.b64d(self.challenge["nonce"])

    def _client_nonce(self):
        return bsdp.b64d(self.nonce)

    def auth(self):
        proof = bsdp.auth_proof(self.token, self._server_nonce(), self._client_nonce(), self.device_id)
        self.send_json(bsdp.AUTH, {"proof": bsdp.b64e(proof)})
        return self._finish()

    def pair_ticket(self, ticket, secret):
        proof = bsdp.pair_proof(bsdp.b64d(secret), self._server_nonce(), self._client_nonce(), self.device_id)
        self.send_json(bsdp.PAIR, {"method": "ticket", "ticket": ticket, "proof": bsdp.b64e(proof)})
        return self._finish()

    def pair_confirm(self, timeout=10.0):
        self.send_json(bsdp.PAIR, {"method": "confirm"})
        msg = self.recv()
        if msg.kind == bsdp.REJECT:
            self.reject = msg.json()
            return False
        assert msg.kind == bsdp.PAIR_WAIT
        self.pair_wait = msg.json()
        expected = bsdp.sas_code(self.cert_fp, self._server_nonce(), self._client_nonce(), self.device_id)
        assert self.pair_wait["code"] == expected
        return self._finish(timeout)

    def _finish(self, timeout=5.0):
        msg = self.recv(timeout)
        if msg.kind == bsdp.REJECT:
            self.reject = msg.json()
            return False
        assert msg.kind == bsdp.WELCOME, hex(msg.kind)
        self.welcome = msg.json()
        if "token" in self.welcome:
            self.token = bsdp.b64d(self.welcome["token"])
        return True

    def login(self, ticket=None, secret=None):
        """HELLO + AUTH (known token) or PAIR (ticket); starts the reader."""
        try:
            self.connect()
            ok = self.hello() is not None and (
                self.auth() if self.token is not None else self.pair_ticket(ticket, secret))
        except BaseException:
            self.close()
            raise
        if ok:
            self.start()
        else:
            self.close()
        return ok

    # ------------------------------------------------------------ session
    def start(self):
        """After the handshake, one I/O thread owns the socket (an SSL socket
        must not be read and written from two threads at once)."""
        self.running = True
        pending, self._pending = getattr(self, "_pending", []), []
        self.link = Link(self.sock, transport="client", address="server", tls=self.tls, kinds=None,
                         limit=bsdp.MAX_PAYLOAD, parser=self.parser)
        for msg in pending:
            self._handle(msg)
        self.link.set_handler(lambda _link, msg: self._handle(msg))
        self.link.start()
        self.reader = threading.Thread(target=self._watch, daemon=True)
        self.reader.start()
        return self

    def _watch(self):
        while self.running and self.link.alive:
            time.sleep(0.05)
        if self.link.bye_reason is not None and self.bye is None:
            self.bye = {"reason": self.link.bye_reason}
        self.running = False

    def _handle(self, msg):
        kind = msg.kind
        if kind == bsdp.RECT:
            x, y, w, h, cw, ch, fmt, _flags = bsdp.RECT_HEADER.unpack_from(msg.payload)
            data = msg.payload[bsdp.RECT_HEADER.size:]
            if self.canvas is None or self.canvas.size != (cw, ch):
                self.canvas = Image.new("RGB", (cw, ch))
            self.canvas.paste(decode(fmt, w, h, data), (x, y))
            self.rects.append(fmt)
        elif kind == bsdp.PRESENT:
            frame_id, _cw, _ch = bsdp.PRESENT_BODY.unpack(msg.payload)
            self.frames += 1
            self.presented.append(frame_id)
            if not self.hold_presented:
                self.send(bsdp.message(bsdp.PRESENTED, bsdp.PRESENTED_BODY.pack(frame_id, 3, 0)))
        elif kind == bsdp.PING:
            self.send(bsdp.message(bsdp.PONG, msg.payload))
        elif kind == bsdp.CONFIG:
            self.config = msg.json()
        elif kind == bsdp.BRIGHTNESS:
            self.brightness = msg.payload[0]
        elif kind == bsdp.BYE:
            self.bye = msg.json()
            self.running = False
        else:
            self.other.append(msg)

    def touch(self, kind, x, y):
        self.send(bsdp.touch(kind, x, y, int(time.monotonic() * 1000)))

    def swipe(self, x0, y0, x1, y1, steps=6, duration=0.2):
        self.touch(bsdp.TOUCH_DOWN, x0, y0)
        for i in range(1, steps + 1):
            time.sleep(duration / steps)
            self.touch(bsdp.TOUCH_MOVE, int(x0 + (x1 - x0) * i / steps), int(y0 + (y1 - y0) * i / steps))
        self.touch(bsdp.TOUCH_UP, x1, y1)

    def set_view(self, w, h):
        self.view = (w, h)
        self.send_json(bsdp.VIEW, {"w": w, "h": h})

    def command(self, body):
        self.send_json(bsdp.COMMAND, body)

    def close(self):
        self.running = False
        if self.link is not None:
            self.link.close("test client closed")
            if self.link.bye_reason is not None and self.bye is None:
                self.bye = {"reason": self.link.bye_reason}
            if self.reader is not None and self.reader is not threading.current_thread():
                self.reader.join(2.0)
            return
        try:
            if self.sock is not None:
                self.sock.close()
        except OSError:
            pass
        if self.reader is not None and self.reader is not threading.current_thread():
            self.reader.join(2.0)


def decode(fmt, w, h, data):
    if fmt == bsdp.FMT_FILL:
        return Image.new("RGB", (w, h), tuple(data[:3]))
    if fmt == bsdp.FMT_RGB_ZLIB:
        return Image.frombytes("RGB", (w, h), zlib.decompress(data))
    if fmt in (bsdp.FMT_JPEG, bsdp.FMT_PNG, bsdp.FMT_WEBP):
        with Image.open(io.BytesIO(data)) as image:
            return image.convert("RGB")
    raise ValueError(f"format {fmt}")


def discover(port, timeout=1.0, address="127.0.0.1"):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(b"BSMD?1abc123", (address, port + 1))
        data, _addr = sock.recvfrom(2048)
    finally:
        sock.close()
    assert data.startswith(b"BSMD!1")
    return json.loads(data[6:])


def free_port_pair():
    """A TCP port whose UDP neighbour is free too."""
    for _ in range(50):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        if port >= 65535:
            continue
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            udp.bind(("0.0.0.0", port + 1))
        except OSError:
            continue
        finally:
            udp.close()
        return port
    raise RuntimeError("no free port pair")


__all__ = ["Client", "decode", "discover", "free_port_pair", "struct"]
