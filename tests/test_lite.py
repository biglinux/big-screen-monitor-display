"""BSMD-lite: the protocol for home-made clients, its bridge and the reference client."""

import importlib
import os
import socket
import subprocess
import sys
import threading

import pytest

from bsmd import lite

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "device-clients", "lite"))
bridge = importlib.import_module("bsmd_lite_bridge")
client = importlib.import_module("lite_client")

SNAP = {
    "cpu_percent": 12.6, "cpu_temp": "61°C", "cpu_temp_value": 61.4, "cpu_freq_mhz": 4120,
    "gpus": [{"percent": 3.0, "usage_known": True, "temp_value": 41, "mem_total_mb": 512},
             {"percent": 77.0, "usage_known": True, "temp_value": 66, "mem_total_mb": 16368, "clock_mhz": 2400}],
    "ram_percent": 33.2, "ram_used_mb": 15872, "ram_total_mb": 47513,
    "disk_percent": 63.0, "net_rx_mbps": 1.25, "net_tx_mbps": 0.04, "hostname": "estacao",
}


def test_round_trip():
    line = lite.encode(lite.metrics(SNAP), "Banda - Música")
    assert line.endswith("\n") and line.startswith("BSMD1|")
    fields = lite.decode(line)
    assert fields == client.parse(line)                         # the reference client agrees
    assert fields["cpu"] == "13" and fields["cpu_t"] == "61" and fields["gpu"] == "77"
    assert fields["gpu_mhz"] == "2400" and fields["ram_used"] == "15.5" and fields["host"] == "estacao"
    assert fields["media"] == "Banda - Música"


def test_unknown_is_a_dash_never_zero():
    snap = dict(SNAP, gpus=[{"percent": 0.0, "usage_known": False, "mem_total_mb": 8000}], cpu_temp_value=None,
                cpu_temp="?°C")
    fields = lite.decode(lite.encode(lite.metrics(snap)))
    assert fields["gpu"] == "-" and fields["gpu_t"] == "-" and fields["cpu_t"] == "-"
    assert client.number(fields, "gpu") is None
    empty = lite.decode(lite.encode(lite.metrics({})))
    assert empty["cpu"] == "-" and empty["host"] == "-"


def test_text_cannot_break_the_framing_or_the_size():
    snap = dict(SNAP, hostname="a|b=c\nd" + "x" * 80)
    line = lite.encode(lite.metrics(snap), "Só|Eu=Nós\t" + "ção 🎵 " * 80)
    raw = line.encode("cp1252")
    assert raw.count(b"\n") == 1 and len(raw) <= lite.MAX_LINE
    fields = lite.decode(line)
    assert "|" not in fields["host"] and "=" not in fields["media"]
    assert len(fields["host"].encode("cp1252")) <= lite.TEXT_LIMITS["host"]


def test_line_never_cuts_a_field():
    values = dict(lite.metrics(SNAP), **{f"extra{i}": 123456.0 for i in range(40)})
    line = lite.encode(values)
    assert len(line.encode("cp1252")) <= lite.MAX_LINE
    assert all("=" in part for part in line.rstrip("\n").split("|")[1:])


def test_other_versions_and_garbage_are_rejected():
    assert lite.decode("BSMD2|cpu=1\n") is None and client.parse("M|1|2\n") is None
    assert lite.decode("BSMD1|cpu=5|novo_campo=x|semvalor\n") == {"cpu": "5", "novo_campo": "x"}


def test_commands_are_a_closed_list():
    calls = []
    run = lambda argv, **kw: calls.append(argv)  # noqa: E731
    assert lite.handle_command("CMD|NEXT\r", run=run, log=lambda *_: None) == "NEXT"
    assert calls == [["playerctl", "next"]]
    assert lite.handle_command("CMD|rm -rf /", run=run, log=lambda *_: None) is None
    assert lite.handle_command("BSMD1|cpu=1", run=run, log=lambda *_: None) is None
    assert len(calls) == 1


def test_line_reader_splits_and_bounds_the_buffer():
    seen = []
    reader = bridge.LineReader(handle=seen.append)
    reader.feed(b"CMD|NE")
    reader.feed(b"XT\nCMD|PREV\n")
    assert seen == ["CMD|NEXT", "CMD|PREV"]
    reader.feed(b"x" * 600)
    assert reader.buffer == b""


class FixedSampler:
    interval = 0.05

    def __init__(self):
        self._line = lite.encode(lite.metrics(SNAP), "Banda - Música")

    def line(self):
        return self._line


def test_tcp_bridge_and_reference_client_end_to_end(capsys, monkeypatch):
    commands = []
    monkeypatch.setattr(lite, "handle_command", lambda line, **kw: commands.append(line.strip()))
    monkeypatch.setattr(bridge.LineReader.__init__, "__defaults__", (lite.handle_command,))
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    stop = threading.Event()
    server = threading.Thread(target=bridge.run_tcp, args=(FixedSampler(), stop, port, "127.0.0.1"), daemon=True)
    server.start()
    try:
        for _ in range(50):                     # wait until it listens
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                stop.wait(0.05)
        assert client.main(["127.0.0.1", str(port), "--once"]) == 0
        out = capsys.readouterr().out
        assert "estacao" in out and "CPU" in out and "77%" in out and "Banda - Música" in out
        with socket.create_connection(("127.0.0.1", port), timeout=2) as conn:
            conn.sendall(b"CMD|PLAY_PAUSE\n")
            assert conn.recv(512).startswith(b"BSMD1|")
            for _ in range(40):
                if commands:
                    break
                stop.wait(0.05)
        assert commands == ["CMD|PLAY_PAUSE"]
    finally:
        stop.set()
        server.join(timeout=3)


def test_stdout_mode_with_real_telemetry():
    result = subprocess.run([sys.executable, os.path.join(ROOT, "device-clients", "lite", "bsmd_lite_bridge.py"),
                             "--stdout", "--count", "1", "--no-media", "--interval", "0.2"],
                            capture_output=True, text=True, encoding="cp1252", timeout=60, check=True)
    fields = lite.decode(result.stdout.splitlines()[0])
    assert fields is not None and {"cpu", "ram", "disk", "host"} <= fields.keys()


@pytest.mark.parametrize("value, expected", [(None, None), (5, 5.0), ("61°C", 61.0), ("?°C", None), (True, None)])
def test_number_parsing(value, expected):
    assert lite._number(value) == expected
