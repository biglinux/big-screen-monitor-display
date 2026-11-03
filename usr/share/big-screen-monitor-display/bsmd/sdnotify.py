"""Minimal, dependency free implementation of the sd_notify(3) protocol."""

import os
import socket


class Notifier:
    def __init__(self, environ=None):
        environ = os.environ if environ is None else environ
        address = environ.get("NOTIFY_SOCKET", "")
        if address.startswith("@"):
            address = "\0" + address[1:]
        self.address = address or None
        self.watchdog_usec = 0
        try:
            usec = int(environ.get("WATCHDOG_USEC", "0"))
            pid = environ.get("WATCHDOG_PID")
            if usec > 0 and (pid is None or int(pid) == os.getpid()):
                self.watchdog_usec = usec
        except ValueError:
            self.watchdog_usec = 0
        self._sock = None

    @property
    def enabled(self):
        return self.address is not None

    @property
    def watchdog_interval(self):
        """Seconds between pings recommended by sd_watchdog_enabled(3) (half)."""
        return self.watchdog_usec / 2_000_000 if self.watchdog_usec else None

    def notify(self, *fields):
        if not self.address:
            return False
        try:
            if self._sock is None:
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
            self._sock.sendto("\n".join(fields).encode("utf-8"), self.address)
            return True
        except OSError:
            return False

    def ready(self, status=None):
        return self.notify("READY=1", *( [f"STATUS={status}"] if status else []))

    def status(self, text):
        return self.notify(f"STATUS={text}")

    def watchdog(self):
        return self.notify("WATCHDOG=1")

    def stopping(self):
        return self.notify("STOPPING=1")
