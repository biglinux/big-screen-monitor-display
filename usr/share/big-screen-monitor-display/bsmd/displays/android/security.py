"""The computer's identity, paired Android devices and pairing state.

Everything lives in the service's private state directory
(``/var/lib/big-screen-monitor-display/android``, mode 0700, files 0600):

* ``server.key`` / ``server.crt`` - self-signed P-256 certificate made once
  with ``openssl``; apps pin its SHA-256 at pairing time;
* ``server.json`` - random server id (stable across restarts, no hardware id);
* ``paired.json`` - one entry per device: a 256-bit token (the HMAC key of
  its challenge-response), names and when/how it was last seen.

Pairing tickets (QR code) and confirmation requests are kept in memory only:
a restart cancels them.
"""

import hashlib
import json
import logging
import os
import secrets
import ssl
import subprocess
import threading
import time

from ...settings import atomic_write_json
from . import protocol as bsdp

log = logging.getLogger("bsmd")

MAX_PAIRED = 32
MAX_PENDING = 4
PENDING_SECONDS = 120.0


class IdentityError(Exception):
    pass


class ServerIdentity:
    def __init__(self, directory, name=None):
        self.directory = directory
        self.key_path = os.path.join(directory, "server.key")
        self.cert_path = os.path.join(directory, "server.crt")
        self.info_path = os.path.join(directory, "server.json")
        self.name = name or _host_name()
        self.server_id = None
        self.fingerprint = b""         # SHA-256 of the DER certificate

    def load(self):
        os.makedirs(self.directory, mode=0o700, exist_ok=True)
        try:
            with open(self.info_path, encoding="utf-8") as handle:
                info = json.load(handle)
            server_id = info.get("server_id") if isinstance(info, dict) else None
        except (OSError, ValueError):
            server_id = None
        if not (isinstance(server_id, str) and len(server_id) == 32 and
                all(ch in "0123456789abcdef" for ch in server_id)):
            server_id = secrets.token_hex(16)
            atomic_write_json(self.info_path, {"server_id": server_id}, mode=0o600)
        self.server_id = server_id
        if not (os.path.exists(self.key_path) and os.path.exists(self.cert_path)):
            self._generate()
        self.fingerprint = cert_fingerprint(self.cert_path)
        return self

    def _generate(self):
        old_umask = os.umask(0o077)
        try:
            result = subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                 "-keyout", self.key_path, "-out", self.cert_path, "-days", "3650", "-sha256",
                 "-subj", f"/CN=Big Screen Monitor Display {self.server_id[:8]}"],
                capture_output=True, text=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise IdentityError(f"openssl unavailable: {error}") from error
        finally:
            os.umask(old_umask)
        if result.returncode != 0:
            raise IdentityError(f"openssl failed: {result.stderr.strip()[:300]}")
        log.info("android: created the computer's certificate (%s)", self.cert_path)

    def tls_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(self.cert_path, self.key_path)
        return context

    @property
    def fingerprint_b64(self):
        return bsdp.b64e(self.fingerprint)


def cert_fingerprint(path):
    with open(path, encoding="ascii") as handle:
        der = ssl.PEM_cert_to_DER_cert(handle.read())
    return hashlib.sha256(der).digest()


def _host_name():
    try:
        with open("/etc/hostname", encoding="utf-8") as handle:
            name = handle.read().strip()
    except OSError:
        name = ""
    if not name:
        import socket
        name = socket.gethostname()
    pretty = _pretty_host_name()
    return (pretty or name or "Linux")[:40]


def _pretty_host_name():
    try:
        with open("/etc/machine-info", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("PRETTY_HOSTNAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


class DeviceStore:
    """Paired devices. Thread safe; written atomically (0600)."""

    def __init__(self, path, clock=time.time):
        self.path = path
        self.clock = clock
        self.lock = threading.Lock()
        self.devices = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        devices = data.get("devices") if isinstance(data, dict) else None
        if not isinstance(devices, dict):
            return
        for dev_id, entry in list(devices.items())[:MAX_PAIRED]:
            try:
                bsdp.device_id(dev_id)
                token = bsdp.b64d(entry.get("token"), 64)
            except (bsdp.ProtocolError, AttributeError):
                continue
            if len(token) != 32:
                continue
            self.devices[dev_id] = dict(entry, display_id=bsdp.display_id(dev_id))

    def _save(self):
        try:
            atomic_write_json(self.path, {"version": 1, "devices": self.devices}, mode=0o600)
        except OSError as error:
            log.warning("android: cannot save paired devices: %s", error)

    def get(self, dev_id):
        with self.lock:
            entry = self.devices.get(dev_id)
            return dict(entry) if entry else None

    def token(self, dev_id):
        entry = self.get(dev_id)
        return bsdp.b64d(entry["token"], 64) if entry else None

    def add(self, hello):
        """Pair ``hello``'s device; returns its new token."""
        token = secrets.token_bytes(32)
        now = self.clock()
        with self.lock:
            if hello.device_id not in self.devices and len(self.devices) >= MAX_PAIRED:
                oldest = min(self.devices, key=lambda key: self.devices[key].get("last_seen", 0))
                del self.devices[oldest]
            self.devices[hello.device_id] = {
                "display_id": bsdp.display_id(hello.device_id), "token": bsdp.b64e(token),
                "name": hello.name, "model": hello.model, "manufacturer": hello.manufacturer,
                "paired_at": now, "last_seen": now, "last_transport": hello.transport}
            self._save()
        return token

    def seen(self, dev_id, transport, name=None):
        with self.lock:
            entry = self.devices.get(dev_id)
            if entry is None:
                return
            entry["last_seen"] = self.clock()
            entry["last_transport"] = transport
            if name:
                entry["name"] = name
            self._save()

    def revoke(self, display_id):
        with self.lock:
            victims = [key for key, entry in self.devices.items() if entry.get("display_id") == display_id]
            for key in victims:
                del self.devices[key]
            if victims:
                self._save()
        return victims

    def public(self):
        """What the status file may show (no tokens)."""
        with self.lock:
            return [{"display_id": entry["display_id"], "name": entry.get("name", ""),
                     "model": entry.get("model", ""), "manufacturer": entry.get("manufacturer", ""),
                     "paired_at": entry.get("paired_at"), "last_seen": entry.get("last_seen"),
                     "last_transport": entry.get("last_transport", "")}
                    for entry in self.devices.values()]


class PairingWindow:
    """QR-code tickets (single use, short lived) and confirmation requests."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.tickets = {}             # ticket id -> (secret, expires)
        self.pending = {}             # request id -> PendingRequest

    # tickets ---------------------------------------------------------------
    def open(self, ticket, secret, seconds):
        with self.lock:
            self.tickets = {ticket: (bsdp.b64d(secret, 64), self.clock() + seconds)}

    def close(self):
        with self.lock:
            self.tickets.clear()

    def is_open(self):
        with self.lock:
            now = self.clock()
            return any(expires > now for _secret, expires in self.tickets.values())

    def take(self, ticket):
        """The secret of a valid ticket, consumed; None when unknown or expired."""
        with self.lock:
            entry = self.tickets.pop(ticket, None) if isinstance(ticket, str) else None
        if entry is None or entry[1] <= self.clock():
            return None
        return entry[0]

    def peek(self, ticket):
        with self.lock:
            entry = self.tickets.get(ticket) if isinstance(ticket, str) else None
        if entry is None or entry[1] <= self.clock():
            return None
        return entry[0]

    # confirmation ----------------------------------------------------------
    def request(self, hello, code, address, transport):
        with self.lock:
            now = self.clock()
            self.pending = {key: req for key, req in self.pending.items() if req.expires > now and not req.done}
            for req in self.pending.values():
                if req.device_id == hello.device_id:
                    req.decide(False)          # a newer request replaces it
            if len(self.pending) >= MAX_PENDING:
                return None
            req = PendingRequest(secrets.token_hex(8), hello, code, address, transport, now + PENDING_SECONDS)
            self.pending[req.id] = req
            return req

    def decide(self, request_id, approved):
        with self.lock:
            req = self.pending.get(request_id)
        if req is None:
            return False
        req.decide(approved)
        return True

    def public(self):
        with self.lock:
            now = self.clock()
            return [{"request": req.id, "name": req.name, "model": req.model, "code": req.code,
                     "transport": req.transport, "address": req.address,
                     "expires_in_s": round(req.expires - now)}
                    for req in self.pending.values() if req.expires > now and not req.done]

    def forget(self, req):
        with self.lock:
            self.pending.pop(req.id, None)


class PendingRequest:
    def __init__(self, request_id, hello, code, address, transport, expires):
        self.id = request_id
        self.device_id = hello.device_id
        self.name = hello.name
        self.model = " ".join(part for part in (hello.manufacturer, hello.model) if part)
        self.code = code
        self.address = address
        self.transport = transport
        self.expires = expires
        self.event = threading.Event()
        self.approved = False
        self.done = False

    def decide(self, approved):
        if not self.done:
            self.approved = bool(approved)
            self.done = True
            self.event.set()

    def wait(self, timeout):
        self.event.wait(timeout)
        return self.approved if self.done else None
