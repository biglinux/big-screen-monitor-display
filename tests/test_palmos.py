"""ZireMon (Palm OS): bridge Bluetooth SPP e o parser C do app no Palm.

O parser ``ParseTelemetryLine`` é compilado com o gcc do host sobre um shim das
APIs do Palm OS, para garantir que todo pacote da bridge é aceito pelo Palm.
"""

import importlib
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PALM = os.path.join(ROOT, "device-clients", "palmos")
sys.path.insert(0, os.path.join(PALM, "pc"))

bridge = importlib.import_module("bsmd_palm_bridge")
palm_bt = importlib.import_module("palm_bt")

LINE_BUF_SIZE = 256         # ziremon.c: buffer de linha do Palm (inclui o '\0')

SNAP = {
    "cpu_percent": 12.6, "cpu_temp": "61°C", "cpu_temp_value": 61.4, "cpu_freq_mhz": 4120,
    "gpus": [
        {"percent": 3.0, "usage_known": True, "temp": "41°C", "temp_value": 41, "mem_total_mb": 512},
        {"percent": 77.0, "usage_known": True, "temp": "66°C", "temp_value": 66, "mem_total_mb": 16368},
    ],
    "active_gpu_idx": 0,
    "ram_percent": 33.2, "ram_used_mb": 15872, "ram_total_mb": 47513,
    "disk_percent": 63.0, "net_rx_mbps": 1.25, "net_tx_mbps": 0.04, "hostname": "estacao",
}


def fields(line):
    assert line.endswith("\n")
    return line[:-1].split("|")


def test_packet_layout_and_values():
    f = fields(bridge.build_packet(SNAP, "Artista - Faixa"))
    assert len(f) == 14 and f[0] == "M"
    assert f[1:4] == ["13", "61", "4120"]
    assert f[4:6] == ["77", "66"]            # GPU dedicada (mais VRAM), não a ativa da rotação
    assert f[6:9] == ["33", "15.5", "46.4"]
    assert f[9:12] == ["63", "1.2", "0.0"] or f[9:12] == ["63", "1.3", "0.0"]
    assert f[12:] == ["estacao", "Artista - Faixa"]


def test_gpu_choice_is_stable_and_overridable():
    assert bridge.build_packet(dict(SNAP, active_gpu_idx=1)) == bridge.build_packet(SNAP)
    assert fields(bridge.build_packet(SNAP, gpu_index=0))[4:6] == ["3", "41"]
    assert fields(bridge.build_packet(SNAP, gpu_index=9))[4:6] == ["77", "66"]
    assert fields(bridge.build_packet(dict(SNAP, gpus=[])))[4:6] == ["-", "-"]


def test_gpu_temperature_falls_back_to_text():
    snap = dict(SNAP, gpus=[{"percent": 10, "usage_known": True, "temp": "58°C", "temp_value": None}])
    assert fields(bridge.build_packet(snap))[4:6] == ["10", "58"]
    snap = dict(SNAP, gpus=[{"percent": 10, "usage_known": True, "temp": "?°C", "temp_value": None}])
    assert fields(bridge.build_packet(snap))[5] == "-"


def test_gpu_without_usage_reporting_is_a_dash_not_zero():
    snap = dict(SNAP, gpus=[{"percent": 0.0, "usage_known": False, "temp_value": 50, "mem_total_mb": 8000}])
    assert fields(bridge.build_packet(snap))[4:6] == ["-", "50"]


def test_empty_snapshot_still_valid():
    f = fields(bridge.build_packet({}))
    assert len(f) == 14 and f[13] == "-" and f[12]


def test_text_fields_cannot_break_the_framing():
    snap = dict(SNAP, hostname="a|b\nc" + "x" * 80)
    f = fields(bridge.build_packet(snap, "Só|Eu\nTítulo\t" + "é" * 200))
    assert len(f) == 14
    data = bridge.encode_packet(bridge.build_packet(snap, "ação 🎵 " * 30))
    assert data.count(b"\n") == 1 and len(data) < LINE_BUF_SIZE
    assert "ação".encode("cp1252") in data            # acentos chegam ao Palm (Palm Latin ~ cp1252)
    assert len(f[12].encode("cp1252")) <= bridge.HOST_MAX
    assert len(f[13].encode("cp1252")) <= bridge.MEDIA_MAX


def test_media_text_from_playerctl(tmp_path):
    fake = tmp_path / "playerctl"
    fake.write_text("#!/bin/sh\nprintf 'Banda\\tMúsica | Ao vivo\\n'\n")
    fake.chmod(0o755)
    assert bridge.media_text(str(fake)) == "Banda - Música / Ao vivo"
    fake.write_text("#!/bin/sh\necho 'No players found' >&2\nexit 1\n")
    assert bridge.media_text(str(fake)) == "-"
    assert bridge.media_text(str(tmp_path / "missing")) == "-"


@pytest.mark.parametrize("line, argv0", [
    ("CMD|PLAY_PAUSE", "playerctl"), ("CMD|NEXT\r", "playerctl"), ("CMD|PREV", "playerctl"),
])
def test_media_commands(line, argv0):
    calls = []
    assert bridge.handle_palm_command(line, run=lambda argv, **kw: calls.append(argv))
    assert calls[0][0] == argv0


def test_volume_and_unknown_commands(monkeypatch):
    calls = []
    run = lambda argv, **kw: calls.append(argv)  # noqa: E731
    monkeypatch.setattr(bridge.lite.shutil, "which", lambda name: "/usr/bin/" + name if name == "wpctl" else None)
    assert bridge.handle_palm_command("CMD|VOL_UP", run=run) == "VOL_UP"
    assert calls[-1] == ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "5%+"]
    monkeypatch.setattr(bridge.lite.shutil, "which", lambda name: "/usr/bin/" + name)
    bridge.handle_palm_command("CMD|VOL_DOWN", run=run)
    assert calls[-1] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"]
    n = len(calls)
    assert bridge.handle_palm_command("CMD|rm -rf /", run=run) is None
    assert bridge.handle_palm_command("lixo", run=run) is None
    assert len(calls) == n


def test_sdp_channel_parse():
    resp = bytes.fromhex("07000200") + b"\x35\x0c\x35\x03\x19\x01\x00\x35\x05\x19\x00\x03\x08\x05"
    assert bridge.parse_sdp_rfcomm_channel(resp) == 5
    assert bridge.parse_sdp_rfcomm_channel(b"\x07\x00\x02") is None


def test_palm_autodetect():
    assert palm_bt.pick_palm([("AA", "Fone"), ("BB", "Palm Zire72")]) == "BB"
    assert palm_bt.pick_palm([("AA", "Tungsten T3"), ("BB", "Zire 72")]) is None     # ambíguo
    assert palm_bt.pick_palm([("AA", "Fone")]) is None
    assert palm_bt.resolve_palm("11:22", devices=[]) == "11:22"
    assert palm_bt.resolve_palm(devices=[("CC", "zire72")]) == "CC"
    with pytest.raises(SystemExit, match="Fone"):
        palm_bt.resolve_palm(devices=[("AA", "Fone")])


SHIM = r"""
#include <stdio.h>
#include <string.h>
typedef char Char; typedef short Int16; typedef unsigned short UInt16;
typedef unsigned char UInt8; typedef unsigned char Boolean;
#define true 1
#define false 0
#define MemMove(d, s, n) memmove((d), (s), (n))
#define MemSet(p, n, v) memset((p), (v), (n))
#define StrCopy strcpy
#define HIST_LEN 48
"""

MAIN = r"""
int main(void) {
    static char line[1024];
    size_t n = fread(line, 1, sizeof(line) - 1, stdin);
    line[n] = 0;
    if (n && line[n - 1] == '\n') line[n - 1] = 0;
    if (!ParseTelemetryLine(line)) { puts("REJECT"); return 0; }
    printf("%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n", gData.cpuPct, gData.cpuTemp, gData.cpuMhz,
           gData.gpuPct, gData.gpuTemp, gData.ramPct, gData.ramUsed, gData.ramTotal, gData.diskPct,
           gData.netRx, gData.netTx, gData.host, gData.media);
    printf("%d %d %d %d %d\n", gData.cpuVal, gData.gpuVal, gData.ramVal, gData.diskVal, gData.netVal);
    return 0;
}
"""


@pytest.fixture(scope="module")
def palm_parser(tmp_path_factory):
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("sem compilador C no host")
    with open(os.path.join(PALM, "palm", "ziremon.c"), encoding="latin-1") as fh:
        src = fh.read()
    struct = src[src.index("typedef struct {\n    Boolean valid;"):src.index("typedef struct {\n    Boolean hasAddr;")]
    body = src[src.index("static Int16 ParseIntSimple"):src.index("/* --- Drawing --- */")]
    hist = "static UInt8 gHistCpu[HIST_LEN];\nstatic UInt8 gHistGpu[HIST_LEN];\nstatic UInt8 gHistNet[HIST_LEN];\n"
    out = tmp_path_factory.mktemp("palm")
    (out / "parse.c").write_text(SHIM + struct + "static TelemetryData gData;\n" + hist + body + MAIN,
                                 encoding="latin-1")
    exe = out / "parse"
    subprocess.run([cc, "-std=c99", "-Wall", "-Wno-unused-function", "-o", str(exe), str(out / "parse.c")],
                   check=True)
    return lambda data: subprocess.run([str(exe)], input=data, capture_output=True, check=True).stdout


def test_palm_parses_bridge_packet(palm_parser):
    line = bridge.build_packet(SNAP, "Artista - Faixa")
    got = palm_parser(bridge.encode_packet(line)).decode("cp1252").splitlines()
    assert got[0] == "|".join(fields(line)[1:])
    assert got[1] == "13 77 33 63 2"


def test_palm_accepts_worst_case_packet(palm_parser):
    snap = dict(SNAP, hostname="h" * 90, net_rx_mbps=99999.9, net_tx_mbps=99999.9, cpu_freq_mhz=99999)
    line = bridge.build_packet(snap, "Ç" * 300)
    got = palm_parser(bridge.encode_packet(line)).decode("cp1252").splitlines()
    assert got[0] != "REJECT"
    assert got[0].split("|")[-1] == "Ç" * bridge.MEDIA_MAX


def test_palm_rejects_garbage(palm_parser):
    assert palm_parser(b"CMD|NEXT\n").strip() == b"REJECT"
    assert palm_parser(b"M|1|2|3\n").strip() == b"REJECT"
