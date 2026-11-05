"""Local IPC between the session media agent and the display service.

Transport: one AF_UNIX stream socket owned by the service
(``/run/big-screen-monitor-display/media.sock``; ``$XDG_RUNTIME_DIR/...``
for manual runs). Frames are a 4-byte big-endian length followed by a UTF-8
JSON object (see :mod:`bsmd.media.model`). Data flows one way, agent ->
service: the service never sends commands into the user session.

Authentication: the kernel reports the peer's uid (SO_PEERCRED). Only the
user of the active session on seat0 is rendered (``/run/systemd/seats``),
so on a shared computer one user's agent cannot paint over another user's
session; without logind the service's own uid and regular users are accepted.
Limits: frame size, number of connections, per-connection rate.
"""

import errno
import json
import logging
import os
import queue
import selectors
import socket
import struct
import threading
import time

log = logging.getLogger("bsmd.media")

SOCKET_NAME = "media.sock"
SYSTEM_SOCKET = "/run/big-screen-monitor-display/media.sock"
MAX_FRAME = 2 * 1024 * 1024
MAX_CLIENTS = 8
MAX_FRAMES_PER_SECOND = 60
HEADER = struct.Struct(">I")
SEATS_DIR = "/run/systemd/seats"


def encode(message):
    data = json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(data) > MAX_FRAME:
        raise ValueError("frame too large")
    return HEADER.pack(len(data)) + data


class FrameDecoder:
    """Incremental decoder; raises ValueError on a malformed or oversized frame."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer += data
        messages = []
        while len(self.buffer) >= HEADER.size:
            (length,) = HEADER.unpack_from(self.buffer)
            if length > MAX_FRAME:
                raise ValueError("frame too large")
            if len(self.buffer) < HEADER.size + length:
                if len(self.buffer) > MAX_FRAME + HEADER.size:
                    raise ValueError("buffer overflow")
                break
            payload = bytes(self.buffer[HEADER.size:HEADER.size + length])
            del self.buffer[:HEADER.size + length]
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as error:
                raise ValueError(f"bad frame: {error}") from None
            if isinstance(message, dict):
                messages.append(message)
        return messages


def peer_uid(sock):
    try:
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _pid, uid, _gid = struct.unpack("3i", creds)
        return uid
    except OSError:
        return None


def active_seat_uid(seats_dir=SEATS_DIR, seat="seat0"):
    """uid of the user in front of the computer (logind), or None when unknown."""
    try:
        with open(os.path.join(seats_dir, seat), encoding="utf-8") as handle:
            for line in handle:
                key, _, value = line.strip().partition("=")
                if key == "ACTIVE_UID" and value.isdigit():
                    return int(value)
    except OSError:
        return None
    return None


def default_authorize(uid, seats_dir=SEATS_DIR):
    if uid is None:
        return False
    active = active_seat_uid(seats_dir)
    if active is not None:
        return uid == active
    return uid == os.getuid() or uid >= 1000


def socket_candidates():
    """Where an agent finds services: the system one and a manual run of this user."""
    paths = [SYSTEM_SOCKET]
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        paths.append(os.path.join(runtime, "big-screen-monitor-display", SOCKET_NAME))
    return paths


# ---------------------------------------------------------------- service side

class Server:
    """Accepts agents and hands validated messages to ``on_message(uid, message)``.

    Runs in its own daemon thread (``start``); nothing here touches the render
    or transport threads, so a misbehaving agent cannot stall a panel.
    """

    def __init__(self, path, on_message, authorize=default_authorize, on_disconnect=None):
        self.path = path
        self.on_message = on_message
        self.on_disconnect = on_disconnect
        self.authorize = authorize
        self.selector = selectors.DefaultSelector()
        self.listener = None
        self.clients = {}
        self.stop_event = threading.Event()
        self.thread = None
        self.rejected = 0
        self.error = None

    def bind(self):
        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        try:
            if os.path.exists(self.path) and not os.path.isdir(self.path):
                os.unlink(self.path)
        except OSError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
        listener.bind(self.path)
        # Any local user may connect; the peer uid decides what is used.
        os.chmod(self.path, 0o666)
        listener.listen(MAX_CLIENTS)
        listener.setblocking(False)
        self.listener = listener
        self.selector.register(listener, selectors.EVENT_READ, None)

    def start(self):
        try:
            self.bind()
        except OSError as error:
            self.error = str(error)
            log.warning("media socket unavailable (%s): %s", self.path, error)
            return False
        self.thread = threading.Thread(target=self._loop, name="media-ipc", daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2.0)
        for sock in list(self.clients):
            self._drop(sock)
        if self.listener:
            try:
                self.selector.unregister(self.listener)
            except (KeyError, ValueError):
                pass
            self.listener.close()
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                events = self.selector.select(timeout=0.5)
            except OSError:
                time.sleep(0.5)
                continue
            for key, _mask in events:
                if key.data is None:
                    self._accept()
                else:
                    self._read(key.fileobj)

    def _accept(self):
        try:
            sock, _addr = self.listener.accept()
        except OSError:
            return
        uid = peer_uid(sock)
        if len(self.clients) >= MAX_CLIENTS or not self.authorize(uid):
            self.rejected += 1
            sock.close()
            return
        sock.setblocking(False)
        self.clients[sock] = {"uid": uid, "decoder": FrameDecoder(), "window": time.monotonic(), "count": 0}
        self.selector.register(sock, selectors.EVENT_READ, "client")

    def _read(self, sock):
        state = self.clients.get(sock)
        if state is None:
            return
        try:
            data = sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            self._drop(sock)
            return
        try:
            messages = state["decoder"].feed(data)
        except ValueError as error:
            log.debug("media agent uid %s: %s", state["uid"], error)
            self._drop(sock)
            return
        now = time.monotonic()
        if now - state["window"] >= 1.0:
            state["window"], state["count"] = now, 0
        for message in messages:
            state["count"] += 1
            if state["count"] > MAX_FRAMES_PER_SECOND:
                continue          # flood: drop silently, keep the connection
            # Re-check: the seat may have switched users since the connection was made.
            if not self.authorize(state["uid"]):
                continue
            try:
                self.on_message(state["uid"], message)
            except Exception:  # noqa: BLE001 - a bad message must never kill the server
                log.exception("media message handler failed")

    def _drop(self, sock):
        state = self.clients.pop(sock, None)
        try:
            self.selector.unregister(sock)
        except (KeyError, ValueError):
            pass
        sock.close()
        if state and self.on_disconnect:
            self.on_disconnect(state["uid"])


# ---------------------------------------------------------------- agent side

class Publisher:
    """Sends the latest snapshot (coalesced), art and spectrum frames to every
    reachable service socket from a worker thread, reconnecting with backoff."""

    RETRY = (1.0, 2.0, 5.0, 10.0)

    def __init__(self, paths=None):
        self.paths = paths or socket_candidates()
        self.queue = queue.Queue(maxsize=64)
        self.latest = {}
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.sockets = {}
        self.next_try = {}
        self.failures = {}
        self.connected = set()
        self.on_connect = None
        self.thread = threading.Thread(target=self._loop, name="media-publisher", daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        self.thread.join(timeout=2.0)
        for sock in self.sockets.values():
            sock.close()

    def publish(self, message, coalesce=None):
        """``coalesce`` (e.g. "snapshot") keeps only the newest message of that kind."""
        if coalesce:
            with self.lock:
                self.latest[coalesce] = message
        else:
            try:
                self.queue.put_nowait(message)
            except queue.Full:
                pass
        self.wake.set()

    def _loop(self):
        while not self.stop_event.is_set():
            self.wake.wait(1.0)
            self.wake.clear()
            self._connect()
            messages = []
            while True:
                try:
                    messages.append(self.queue.get_nowait())
                except queue.Empty:
                    break
            with self.lock:
                latest, self.latest = self.latest, {}
            messages += list(latest.values())
            if not messages:
                continue
            frames = []
            for message in messages:
                try:
                    frames.append(encode(message))
                except (ValueError, TypeError):
                    continue
            for path, sock in list(self.sockets.items()):
                try:
                    for frame in frames:
                        sock.sendall(frame)
                except OSError:
                    self._close(path)

    def _connect(self):
        now = time.monotonic()
        for path in self.paths:
            if path in self.sockets or now < self.next_try.get(path, 0):
                continue
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
            sock.settimeout(2.0)
            try:
                sock.connect(path)
            except OSError as error:
                sock.close()
                count = self.failures.get(path, 0)
                self.failures[path] = count + 1
                self.next_try[path] = now + self.RETRY[min(count, len(self.RETRY) - 1)]
                if error.errno not in (errno.ENOENT, errno.ECONNREFUSED):
                    log.debug("media socket %s: %s", path, error)
                continue
            self.sockets[path] = sock
            self.failures[path] = 0
            self.connected.add(path)
            if self.on_connect:
                self.on_connect(path)

    def _close(self, path):
        sock = self.sockets.pop(path, None)
        self.connected.discard(path)
        if sock:
            sock.close()
        self.next_try[path] = time.monotonic() + 1.0
