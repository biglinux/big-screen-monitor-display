"""One connection to an Android app, whatever carries it.

A :class:`Link` owns its socket in a single I/O thread (non-blocking, with a
wake-up pipe): OpenSSL objects must not be read and written from two threads
at once, and a single thread also keeps a slow phone from blocking whoever
sends. Writers queue bytes (bounded, with backpressure); every decoded message
goes to ``handler(link, message)`` in the I/O thread, so handlers stay short.

PING is answered here, so a phone on a session that is busy encoding a frame
still sees the computer alive.
"""

import logging
import os
import select
import socket
import ssl
import threading
import time

from ..base import DISCONNECTED, TIMEOUT, DisplayError
from . import protocol as bsdp

log = logging.getLogger("bsmd")

OUTBOX_LIMIT = 4 * 1024 * 1024        # bytes queued before writers wait
BACKLOG = 64                          # messages kept until a handler is set


class Link:
    """``sock`` is connected (TLS already negotiated when ``tls`` is True)."""

    def __init__(self, sock, transport="wifi", address="", tls=False, clock=time.monotonic,
                 limit=bsdp.MAX_CLIENT_PAYLOAD, kinds=bsdp.CLIENT_KINDS, parser=None):
        self.sock = sock
        self.transport = transport
        self.address = address
        self.tls = tls
        self.clock = clock
        self.parser = parser or bsdp.Parser(limit=limit, kinds=kinds)
        self.bye_reason = None
        self.cond = threading.Condition()
        self.outbox = bytearray()
        self.backlog = []
        self.handler = None
        self.error = None
        self.closed = False
        self.hello = None                 # bsdp.Hello once known
        self.device_id = None
        self.created = clock()
        self.last_rx = clock()
        self.bytes_in = 0
        self.bytes_out = 0
        self._posted = []
        self._released = False
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        sock.setblocking(False)
        self.thread = threading.Thread(target=self._run, name=f"android-io:{address}", daemon=True)

    def start(self):
        self.thread.start()
        return self

    # ------------------------------------------------------------ public
    @property
    def alive(self):
        return not self.closed and self.error is None

    def set_handler(self, handler):
        """Deliver messages to ``handler``; queued ones first (in the I/O thread)."""
        with self.cond:
            self.handler = handler
            backlog, self.backlog = self.backlog, []
        if handler is not None and backlog:
            self._post(lambda: [self._deliver(msg) for msg in backlog])

    def send(self, data, timeout=5.0):
        """Queue ``data``; waits while the outbox is full. Raises DisplayError."""
        deadline = self.clock() + timeout
        with self.cond:
            while True:
                if self.error is not None:
                    raise self.error
                if self.closed:
                    raise DisplayError(DISCONNECTED, f"link to {self.address} closed")
                if not self.outbox or len(self.outbox) + len(data) <= OUTBOX_LIMIT:
                    break
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise DisplayError(TIMEOUT, f"{self.address} stopped reading")
                self.cond.wait(min(remaining, 0.25))
            self.outbox += data
        self._wake()
        return len(data)

    def flush(self, timeout=5.0):
        deadline = self.clock() + timeout
        with self.cond:
            while self.outbox and self.alive:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    return False
                self.cond.wait(min(remaining, 0.25))
            return not self.outbox

    def queued(self):
        with self.cond:
            return len(self.outbox)

    def close(self, reason=None, bye=None):
        """Close; ``bye`` (a reason string) is sent first when possible."""
        if self.closed:
            return
        if bye is not None and self.error is None:
            try:
                self.send(bsdp.json_message(bsdp.BYE, {"reason": bye}), timeout=0.5)
                self.flush(0.5)
            except DisplayError:
                pass
        with self.cond:
            self.closed = True
            if self.error is None:
                self.error = DisplayError(DISCONNECTED, reason or f"link to {self.address} closed")
            self.cond.notify_all()
        self._wake()
        if self.thread.is_alive() and self.thread is not threading.current_thread():
            self.thread.join(timeout=2.0)
        self._release()

    # ------------------------------------------------------------ I/O thread
    def _wake(self):
        try:
            os.write(self._wake_w, b"\0")
        except (BlockingIOError, OSError):
            pass

    def _post(self, func):
        with self.cond:
            self._posted.append(func)
        self._wake()

    def _fail(self, error):
        with self.cond:
            if self.error is None:
                self.error = error
            self.cond.notify_all()

    def _run(self):
        sock = self.sock
        try:
            while not self.closed and self.error is None:
                with self.cond:
                    want_write = bool(self.outbox)
                    posted, self._posted = self._posted, []
                for func in posted:
                    func()
                readable = self.tls and sock.pending()
                if not readable:
                    try:
                        r, w, _ = select.select([sock, self._wake_r], [sock] if want_write else [], [], 1.0)
                    except (OSError, ValueError) as error:
                        raise DisplayError(DISCONNECTED, "socket closed", error)
                    if self._wake_r in r:
                        try:
                            while os.read(self._wake_r, 512):
                                pass
                        except (BlockingIOError, OSError):
                            pass
                    readable = sock in r
                    if sock in w:
                        self._write()
                if readable:
                    self._read()
        except DisplayError as error:
            self._fail(error)
        except bsdp.ProtocolError as error:
            log.info("android %s: protocol error: %s", self.address, error)
            self._fail(DisplayError("protocol", f"protocol error from {self.address}: {error}"))
        except Exception as error:  # noqa: BLE001 - the link ends, the service goes on
            log.exception("android %s: link failed", self.address)
            self._fail(DisplayError("protocol", "link failed", error))
        finally:
            with self.cond:
                self.closed = True
                self.cond.notify_all()
            self._release()

    def _write(self):
        with self.cond:
            chunk = bytes(self.outbox[:65536])
        try:
            sent = self.sock.send(chunk)
        except (ssl.SSLWantWriteError, ssl.SSLWantReadError, BlockingIOError, InterruptedError):
            return
        except OSError as error:
            raise DisplayError(DISCONNECTED, f"write to {self.address} failed", error)
        with self.cond:
            del self.outbox[:sent]
            self.bytes_out += sent
            self.cond.notify_all()

    def _read(self):
        try:
            data = self.sock.recv(65536)
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError, BlockingIOError, InterruptedError):
            return
        except OSError as error:
            raise DisplayError(DISCONNECTED, f"read from {self.address} failed", error)
        if not data:
            raise DisplayError(DISCONNECTED, f"{self.address} closed the connection")
        self.bytes_in += len(data)
        self.last_rx = self.clock()
        for msg in self.parser.feed(data):
            self._deliver(msg)

    def _deliver(self, msg):
        if msg.kind == bsdp.PING:
            token = bsdp.parse_token(msg.payload)
            with self.cond:
                self.outbox += bsdp.message(bsdp.PONG, bsdp.TOKEN_BODY.pack(token))
            return
        if msg.kind == bsdp.BYE:
            try:
                reason = bsdp.text(msg.json().get("reason"), 40, "bye")
            except bsdp.ProtocolError:
                reason = "bye"
            self.bye_reason = reason
            raise DisplayError(DISCONNECTED, f"the peer closed the connection ({reason})")
        with self.cond:
            handler = self.handler
            if handler is None:
                if len(self.backlog) >= BACKLOG:
                    raise bsdp.ProtocolError("too many messages before the session started")
                self.backlog.append(msg)
                return
        handler(self, msg)

    def _release(self):
        with self.cond:
            if self._released:
                return
            self._released = True
            # -1 before closing: a late _wake() must never write into a reused descriptor.
            fds, self._wake_r, self._wake_w = (self._wake_r, self._wake_w), -1, -1
        for fd in fds:
            try:
                os.close(fd)
            except OSError:
                pass
        try:
            if self.tls:
                self.sock.close()
            else:
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.sock.close()
        except OSError:
            pass
