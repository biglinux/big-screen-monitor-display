"""sd_notify(3): what the service tells systemd (readiness, status, watchdog).

A real AF_UNIX datagram socket plays systemd. A broken watchdog ping makes
systemd restart the service every WatchdogSec (30 s), so this path matters.
"""

import os
import socket

import pytest

from bsmd.sdnotify import Notifier


@pytest.fixture
def systemd(tmp_path):
    path = str(tmp_path / "notify")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(path)
    sock.settimeout(2)
    yield path, sock
    sock.close()


def received(sock):
    return sock.recv(4096).decode().split("\n")


def test_messages_reach_systemd(systemd):
    path, sock = systemd
    n = Notifier({"NOTIFY_SOCKET": path})
    try:
        assert n.enabled
        assert n.ready("healthy: AX206 800x480")
        assert received(sock) == ["READY=1", "STATUS=healthy: AX206 800x480"]
        assert n.ready()
        assert received(sock) == ["READY=1"]
        assert n.status("waiting for a display") and received(sock) == ["STATUS=waiting for a display"]
        assert n.watchdog() and received(sock) == ["WATCHDOG=1"]
        assert n.stopping() and received(sock) == ["STOPPING=1"]
    finally:
        n.close()
    n.close()                                         # idempotent


def test_abstract_socket_address():
    name = f"bsmd-test-{os.getpid()}"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind("\0" + name)
    sock.settimeout(2)
    n = Notifier({"NOTIFY_SOCKET": "@" + name})
    try:
        assert n.address == "\0" + name
        assert n.watchdog() and received(sock) == ["WATCHDOG=1"]
    finally:
        n.close()
        sock.close()


def test_without_systemd_everything_is_a_quiet_no():
    n = Notifier({})
    assert not n.enabled and n.watchdog_interval is None
    assert n.ready() is False and n.watchdog() is False


def test_send_failure_is_reported_not_raised(tmp_path):
    n = Notifier({"NOTIFY_SOCKET": str(tmp_path / "gone")})
    try:
        assert n.watchdog() is False
    finally:
        n.close()


@pytest.mark.parametrize("env, interval", [
    ({"WATCHDOG_USEC": "30000000"}, 15.0),                              # half of WatchdogSec
    ({"WATCHDOG_USEC": "30000000", "WATCHDOG_PID": str(os.getpid())}, 15.0),
    ({"WATCHDOG_USEC": "30000000", "WATCHDOG_PID": "1"}, None),        # meant for another process
    ({"WATCHDOG_USEC": "0"}, None),
    ({"WATCHDOG_USEC": "abc"}, None),
    ({"WATCHDOG_USEC": "30000000", "WATCHDOG_PID": "x"}, None),
])
def test_watchdog_interval(env, interval):
    assert Notifier(env).watchdog_interval == interval
