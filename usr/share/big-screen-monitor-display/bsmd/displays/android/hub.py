"""Where Android apps reach the service: listeners, handshake, pairing, links.

Network (opt-in, ``android_network``): TCP ``android_port`` (7717) with TLS
1.2+, and a UDP responder on the next port so apps find the computer on the
local network without mDNS. Nothing is listened on while the option is off.

USB: Android Open Accessory links (:mod:`.aoa`) are handed in by
:meth:`AndroidHub.adopt` and go through the same handshake (no TLS: the
cable is the channel, the device token still authenticates).

After the handshake an authenticated :class:`~.link.Link` waits in
``links`` until the display session of that device claims it
(:meth:`claim`). A device that connects again (Wi-Fi -> USB, a new app
start) replaces its previous link: the old one is closed, so frames and
touches of an earlier connection can never reach the new one, and the device
keeps one display (its id comes from the device, not the transport).
"""

import hmac
import ipaddress
import json
import logging
import queue
import secrets
import select
import socket
import ssl
import threading
import time

from ..base import DISCONNECTED, DisplayError
from . import protocol as bsdp
from .link import Link
from .security import DeviceStore, PairingWindow, ServerIdentity

log = logging.getLogger("bsmd")

DISCOVERY_REQUEST = b"BSMD?1"
HANDSHAKE_TIMEOUT = 10.0
MAX_HANDSHAKES = 8
MAX_LINKS = 16
FAILURES_BEFORE_BAN = 5
BAN_SECONDS = 60.0
DISCOVERY_PER_SECOND = 20


class AndroidHub:
    def __init__(self, state_directory, on_link=None, clock=time.monotonic, host_name=None,
                 identity=None, store=None, usb=True):
        import os
        self.directory = os.path.join(state_directory, "android")
        self.identity = identity or ServerIdentity(self.directory, host_name)
        self.store = store
        self.pairing = PairingWindow(clock)
        self.on_link = on_link            # called (device id) when a link is ready to be claimed
        self.clock = clock
        self.lock = threading.Lock()
        self.links = {}                   # device id -> Link (authenticated)
        self.claimed = {}                 # device id -> Link handed to a session
        self.handshakes = threading.BoundedSemaphore(MAX_HANDSHAKES)
        self.failures = {}                # address -> (count, since)
        self.stop_event = threading.Event()
        self.listener = None
        self.udp = None
        self.port = None
        self.host = None
        self.thread = None
        self.error = None
        self.ready = False
        self.counters = {"accepted": 0, "rejected": 0, "paired": 0, "auth_failed": 0, "tls_failed": 0,
                         "discovery": 0}
        # Phones that switched to USB accessory mode (bsmd/displays/android/aoa.py).
        if usb:
            from .aoa import AccessoryWatcher
            self.aoa = AccessoryWatcher(self, clock=clock)
        else:
            self.aoa = None

    # ------------------------------------------------------------ lifecycle
    def prepare(self):
        """Load or create the identity and the paired-device store."""
        if self.ready:
            return True
        import os
        try:
            self.identity.load()
            if self.store is None:
                self.store = DeviceStore(os.path.join(self.directory, "paired.json"))
            self.ready = True
            self.error = None
        except Exception as error:  # noqa: BLE001 - reported in the status, never fatal
            self.error = f"identity: {error}"
            log.warning("android: %s", self.error)
        return self.ready

    def listen(self, port, host="0.0.0.0"):
        """Start (or move) the network listener; False when it cannot."""
        if not self.prepare():
            return False
        if self.listener is not None and self.port == port and self.host == host:
            return True
        self.stop_listening()
        try:
            tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
            tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            tcp.bind((host, port))
            tcp.listen(16)
            tcp.setblocking(False)
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
            udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            udp.bind((host, port + 1))
            udp.setblocking(False)
        except OSError as error:
            for sock in (locals().get("tcp"), locals().get("udp")):
                if sock is not None:
                    sock.close()
            self.error = f"cannot listen on port {port}: {error.strerror or error}"
            log.warning("android: %s", self.error)
            return False
        self.listener, self.udp, self.port, self.host = tcp, udp, port, host
        self.tls = self.identity.tls_context()
        self.stop_event.clear()
        self.error = None
        self.thread = threading.Thread(target=self._accept_loop, name="android-listen", daemon=True)
        self.thread.start()
        log.info("android: listening on %s TCP %d (TLS) and UDP %d (discovery)", host, port, port + 1)
        return True

    def stop_listening(self):
        self.stop_event.set()
        thread, self.thread = self.thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        for sock in (self.listener, self.udp):
            if sock is not None:
                sock.close()
        self.listener = self.udp = None
        self.port = self.host = None
        # Network links end with the listener; USB accessory links stay.
        for dev_id, link in self._all_links():
            if not link.transport.startswith("usb-accessory"):
                self._drop(dev_id, link, "network connections switched off")

    def stop(self):
        self.stop_listening()
        for dev_id, link in self._all_links():
            self._drop(dev_id, link, "service stopping", bye="shutdown")
        if self.aoa is not None:
            self.aoa.stop()

    def _all_links(self):
        with self.lock:
            return list(self.links.items()) + list(self.claimed.items())

    def _drop(self, dev_id, link, reason, bye=None):
        with self.lock:
            if self.links.get(dev_id) is link:
                del self.links[dev_id]
            if self.claimed.get(dev_id) is link:
                del self.claimed[dev_id]
        link.close(reason, bye=bye)

    # ------------------------------------------------------------ sessions
    def available(self, dev_id):
        """A live link (waiting or in use) exists for ``dev_id``."""
        with self.lock:
            link = self.links.get(dev_id) or self.claimed.get(dev_id)
        return link is not None and link.alive

    def devices(self):
        """Device ids with a live link (display sessions should exist for them)."""
        with self.lock:
            items = list(self.links.items()) + list(self.claimed.items())
        return sorted({dev_id for dev_id, link in items if link.alive})

    def claim(self, dev_id):
        """The waiting link of ``dev_id`` (now owned by the caller), or None."""
        with self.lock:
            link = self.links.pop(dev_id, None)
            if link is None or not link.alive:
                return None
            old = self.claimed.get(dev_id)
            self.claimed[dev_id] = link
        if old is not None and old is not link:
            old.close("replaced by a newer connection")
        return link

    def release(self, dev_id, link):
        with self.lock:
            if self.claimed.get(dev_id) is link:
                del self.claimed[dev_id]

    def disconnect(self, dev_id, reason):
        """Close every link of ``dev_id`` telling the app why (display switched off)."""
        for key, link in self._all_links():
            if key == dev_id:
                self._drop(key, link, f"display {reason}", bye=reason)

    def hello(self, dev_id):
        with self.lock:
            link = self.links.get(dev_id) or self.claimed.get(dev_id)
        return link.hello if link is not None else None

    # ------------------------------------------------------------ commands
    def open_pairing(self, ticket, secret, seconds):
        self.prepare()
        self.pairing.open(ticket, secret, seconds)
        log.info("android: pairing window open for %ds", seconds)

    def close_pairing(self):
        self.pairing.close()

    def decide(self, request_id, approved):
        return self.pairing.decide(request_id, approved)

    def revoke(self, display_id):
        if not self.prepare():
            return []
        victims = self.store.revoke(display_id)
        for dev_id in victims:
            for key, link in self._all_links():
                if key == dev_id:
                    self._drop(key, link, "pairing removed", bye=bsdp.R_REVOKED)
        if victims:
            log.info("android: pairing of %s removed", display_id)
        return victims

    # ------------------------------------------------------------ network
    def _accept_loop(self):
        while not self.stop_event.is_set():
            try:
                ready, _, _ = select.select([self.listener, self.udp], [], [], 0.5)
            except (OSError, ValueError):
                break
            if self.udp in ready:
                self._discovery()
            if self.listener in ready:
                try:
                    sock, addr = self.listener.accept()
                except OSError:
                    continue
                address = addr[0]
                if self._banned(address) or not self.handshakes.acquire(blocking=False):
                    self.counters["rejected"] += 1
                    sock.close()
                    continue
                self.counters["accepted"] += 1
                threading.Thread(target=self._serve_tcp, args=(sock, address), name=f"android-hs:{address}",
                                 daemon=True).start()

    def _discovery(self):
        try:
            data, addr = self.udp.recvfrom(512)
        except OSError:
            return
        if not data.startswith(DISCOVERY_REQUEST) or len(data) > 64:
            return
        now = self.clock()
        window = getattr(self, "_disc_window", (now, 0))
        if now - window[0] >= 1.0:
            window = (now, 0)
        if window[1] >= DISCOVERY_PER_SECOND:
            return
        self._disc_window = (now, window[1] + 1)
        self.counters["discovery"] += 1
        reply = {"proto": bsdp.VERSION, "server_id": self.identity.server_id, "name": self.identity.name,
                 "port": self.port, "fp": self.identity.fingerprint_b64, "pairing": self.pairing.is_open(),
                 "nonce": data[len(DISCOVERY_REQUEST):].decode("ascii", "replace")[:32]}
        try:
            self.udp.sendto(b"BSMD!1" + json.dumps(reply, separators=(",", ":")).encode("utf-8"), addr)
        except OSError:
            pass

    def _banned(self, address):
        entry = self.failures.get(address)
        if entry is None:
            return False
        count, since = entry
        if self.clock() - since > BAN_SECONDS:
            del self.failures[address]
            return False
        return count >= FAILURES_BEFORE_BAN

    def _failed(self, address):
        count, since = self.failures.get(address, (0, self.clock()))
        if self.clock() - since > BAN_SECONDS:
            count, since = 0, self.clock()
        self.failures[address] = (count + 1, since)
        if len(self.failures) > 256:
            self.failures.pop(next(iter(self.failures)))

    def _serve_tcp(self, sock, address):
        try:
            sock.settimeout(HANDSHAKE_TIMEOUT)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            try:
                tls_sock = self.tls.wrap_socket(sock, server_side=True)
            except (ssl.SSLError, OSError) as error:
                self.counters["tls_failed"] += 1
                self._failed(address)
                log.info("android %s: TLS handshake failed: %s", address, error)
                sock.close()
                return
            transport = "usb-adb" if ipaddress.ip_address(address).is_loopback else "network"
            link = Link(tls_sock, transport=transport, address=address, tls=True, clock=self.clock).start()
            self.handshake(link, self.identity.fingerprint)
        finally:
            self.handshakes.release()

    # ------------------------------------------------------------ handshake
    def adopt(self, link):
        """Run the handshake on a link made elsewhere (USB accessory) in a thread."""
        if not self.prepare():
            link.close("service identity unavailable")
            return
        threading.Thread(target=self.handshake, args=(link, b""), name=f"android-hs:{link.address}",
                         daemon=True).start()

    def handshake(self, link, cert_fp):
        inbox = queue.Queue(maxsize=16)

        def collect(_link, msg):
            try:
                inbox.put_nowait(msg)
            except queue.Full:
                raise bsdp.ProtocolError("too many messages during the handshake")
        link.set_handler(collect)
        try:
            ok = self._handshake(link, cert_fp, inbox)
        except bsdp.ProtocolError as error:
            log.info("android %s: handshake refused: %s", link.address, error)
            self._failed(link.address)
            ok = False
        except DisplayError as error:
            log.info("android %s: handshake ended: %s", link.address, error)
            ok = False
        if not ok:
            link.close("handshake failed")
            return
        link.set_handler(None)            # messages wait in the backlog for the session
        dev_id = link.device_id
        with self.lock:
            old = self.links.get(dev_id)
            self.links[dev_id] = link
            in_use = self.claimed.get(dev_id)
            if len(self.links) > MAX_LINKS:
                oldest = min(self.links, key=lambda key: self.links[key].created)
                victim = self.links.pop(oldest)
            else:
                victim = None
        for stale in (old, victim):
            if stale is not None and stale is not link:
                stale.close("replaced by a newer connection", bye=bsdp.R_REPLACED)
        if in_use is not None:
            # The session reconnects and claims this link (transport change, app restart).
            in_use.close("replaced by a newer connection", bye=bsdp.R_REPLACED)
        log.info("android %s: %s ready (%s)", link.address, link.hello.name, link.transport)
        if self.on_link is not None:
            self.on_link(dev_id)

    def _next(self, link, inbox, timeout, kinds):
        deadline = self.clock() + timeout
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise DisplayError("timeout", f"{link.address}: no answer during the handshake")
            if not link.alive:
                raise link.error or DisplayError(DISCONNECTED, "link closed")
            try:
                msg = inbox.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if msg.kind in (bsdp.STATS, bsdp.PONG):
                continue
            if msg.kind not in kinds:
                raise bsdp.ProtocolError(f"unexpected message 0x{msg.kind:02x} during the handshake")
            return msg

    def _reject(self, link, reason, message=""):
        try:
            link.send(bsdp.json_message(bsdp.REJECT, {"reason": reason, "message": message}), timeout=1.0)
            link.flush(1.0)
        except DisplayError:
            pass
        return False

    def _handshake(self, link, cert_fp, inbox):
        hello = bsdp.Hello.parse(self._next(link, inbox, HANDSHAKE_TIMEOUT, {bsdp.HELLO}).json())
        if link.transport == "network" and hello.transport in ("wifi", "ethernet", "usb-tether"):
            link.transport = hello.transport
        elif link.transport in ("network", "usb-adb") and hello.transport == "usb-adb":
            link.transport = "usb-adb"
        link.hello = hello
        known = self.store.get(hello.device_id)
        server_nonce = secrets.token_bytes(32)
        link.send(bsdp.json_message(bsdp.CHALLENGE, {
            "proto": bsdp.VERSION, "server_id": self.identity.server_id, "name": self.identity.name,
            "nonce": bsdp.b64e(server_nonce), "need": "auth" if known else "pair",
            "pairing": self.pairing.is_open(), "fp": bsdp.b64e(cert_fp) if cert_fp else ""}))
        msg = self._next(link, inbox, HANDSHAKE_TIMEOUT, {bsdp.AUTH, bsdp.PAIR})
        body = msg.json()
        token = None
        if msg.kind == bsdp.AUTH:
            if not known:
                self.counters["auth_failed"] += 1
                return self._reject(link, bsdp.R_UNKNOWN, "this device is not paired with the computer")
            expected = bsdp.auth_proof(self.store.token(hello.device_id), server_nonce, hello.nonce,
                                       hello.device_id)
            if not hmac.compare_digest(expected, bsdp.b64d(body.get("proof"), 64)):
                self.counters["auth_failed"] += 1
                self._failed(link.address)
                return self._reject(link, bsdp.R_AUTH)
        elif body.get("method") == "ticket":
            ticket = body.get("ticket")
            secret = self.pairing.peek(ticket)
            if secret is None:
                return self._reject(link, bsdp.R_EXPIRED, "the pairing code expired: show a new one")
            expected = bsdp.pair_proof(secret, server_nonce, hello.nonce, hello.device_id)
            if not hmac.compare_digest(expected, bsdp.b64d(body.get("proof"), 64)) or \
                    self.pairing.take(ticket) is None:
                self._failed(link.address)
                return self._reject(link, bsdp.R_AUTH)
            token = self.store.add(hello)
        elif body.get("method") == "confirm":
            code = bsdp.sas_code(cert_fp, server_nonce, hello.nonce, hello.device_id)
            request = self.pairing.request(hello, code, link.address, link.transport)
            if request is None:
                return self._reject(link, bsdp.R_BUSY, "too many pairing requests")
            link.send(bsdp.json_message(bsdp.PAIR_WAIT, {"code": code, "timeout": int(request.expires -
                                                                                     self.clock())}))
            log.info("android %s: %s asks to pair (code %s)", link.address, hello.name, code)
            try:
                while True:
                    decision = request.wait(0.5)
                    if decision is not None:
                        break
                    if self.clock() >= request.expires:
                        return self._reject(link, bsdp.R_EXPIRED, "nobody answered on the computer")
                    if not link.alive or self.stop_event.is_set() and link.transport == "network":
                        return False
                    self._drain(inbox)
            finally:
                self.pairing.forget(request)
            if not decision:
                return self._reject(link, bsdp.R_DENIED)
            token = self.store.add(hello)
        else:
            raise bsdp.ProtocolError("unknown pairing method")
        if token is not None:
            self.counters["paired"] += 1
            log.info("android %s: %s paired", link.address, hello.name)
        self.store.seen(hello.device_id, link.transport, hello.name, usb=getattr(link, "usb_hash", None))
        self.failures.pop(link.address, None)
        link.device_id = hello.device_id
        welcome = {"display_id": bsdp.display_id(hello.device_id), "server_id": self.identity.server_id,
                   "name": self.identity.name}
        if token is not None:
            welcome["token"] = bsdp.b64e(token)
            if cert_fp:
                welcome["fp"] = bsdp.b64e(cert_fp)
        link.send(bsdp.json_message(bsdp.WELCOME, welcome))
        return True

    @staticmethod
    def _drain(inbox):
        while True:
            try:
                msg = inbox.get_nowait()
            except queue.Empty:
                return
            if msg.kind not in (bsdp.STATS, bsdp.PONG, bsdp.VIEW):
                raise bsdp.ProtocolError("unexpected message while waiting for approval")

    # ------------------------------------------------------------ status
    def addresses(self):
        """Private IPv4 addresses of this computer (shown in the QR code and the window)."""
        try:
            import psutil
            result = []
            for name, addrs in psutil.net_if_addrs().items():
                if name == "lo" or name.startswith(("docker", "veth", "virbr", "br-")):
                    continue
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ip = ipaddress.ip_address(addr.address)
                        if ip.is_private and not ip.is_loopback:
                            result.append({"iface": name, "address": addr.address})
            return result[:8]
        except Exception:  # noqa: BLE001
            return []

    def status(self):
        with self.lock:
            links = [(dev_id, link, False) for dev_id, link in self.links.items()] + \
                    [(dev_id, link, True) for dev_id, link in self.claimed.items()]
        return {
            "ready": self.ready,
            "listening": self.listener is not None,
            "network": self.listener is not None and self.host != "127.0.0.1",
            "port": self.port,
            "error": self.error,
            "server_id": self.identity.server_id,
            "name": self.identity.name,
            "fingerprint": self.identity.fingerprint_b64 if self.ready else None,
            "addresses": self.addresses() if self.listener is not None and self.host != "127.0.0.1" else [],
            "pairing_open": self.pairing.is_open(),
            "requests": self.pairing.public(),
            "paired": self.store.public() if self.store is not None else [],
            "usb_error": self.aoa.error if self.aoa is not None else None,
            "connected": [{"display_id": bsdp.display_id(dev_id), "transport": link.transport,
                           "address": link.address, "in_use": in_use, "bytes_in": link.bytes_in,
                           "bytes_out": link.bytes_out}
                          for dev_id, link, in_use in links if link.alive],
            "counters": dict(self.counters),
        }
