"""SmartMonitor 3.5" HID panel (0483:0065): wire format, theme compiler,
dashboard layout and the driver's flash + live-values flow against a fake panel
that answers YMODEM like the firmware."""

import datetime
import json
import time

import pytest
from bsmd import runtime, settings, telemetry
from bsmd.displays import discovery, registry
from bsmd.displays.base import TELEMETRY, DisplayError
from bsmd.displays.smartmonitor import driver as sm_driver
from bsmd.displays.smartmonitor import imgdat, layout, protocol

# ---------------------------------------------------------------- protocol

def test_reports_are_report_id_plus_64_bytes():
    packet = protocol.report(b"\x02\x01")
    assert len(packet) == 65 and packet[0] == 0 and packet[1:3] == b"\x02\x01"
    with pytest.raises(ValueError):
        protocol.report(bytes(65))


def test_sensor_reports_split_at_20_pairs_and_clamp():
    values = {channel: channel * 10 for channel in range(1, 23)}
    values[5] = -3
    values[6] = 70000
    reports = protocol.sensor_reports(values)
    assert len(reports) == 2
    first = reports[0][1:]
    assert first[0] == protocol.SENSOR and first[1] == 20
    assert first[2:5] == bytes([1]) + (10).to_bytes(2, "big")
    pairs = {first[2 + 3 * i]: int.from_bytes(first[3 + 3 * i:5 + 3 * i], "big") for i in range(20)}
    assert pairs[5] == 0 and pairs[6] == 0xFFFF
    assert reports[1][1:3] == bytes([protocol.SENSOR, 2])


def test_datetime_report_carries_the_backlight():
    when = datetime.datetime(2026, 11, 8, 14, 5, 9)
    packet = protocol.datetime_report(when, brightness=0)[1:]
    assert list(packet[:11]) == [3, 1, 0x15, 26, 11, 8, 14, 5, 9, 0, 1]      # brightness floor is 1
    assert protocol.datetime_report(when, brightness=250)[11] == 100


def test_ymodem_blocks():
    assert protocol.crc16_xmodem(b"123456789") == 0x31C3          # CRC-16/XMODEM check value
    reports = protocol.ymodem_block(protocol.STX, 1, b"abc", 1024)
    block = b"".join(r[1:] for r in reports)
    assert len(reports) == 17 and block[:3] == bytes([2, 1, 0xFE])
    assert block[3:6] == b"abc" and block[6] == 0x1A
    body = block[3:3 + 1024]
    assert int.from_bytes(block[1027:1029], "big") == protocol.crc16_xmodem(body)
    meta = b"".join(r[1:] for r in protocol.metadata_block("img.dat", 4096))
    assert meta[3:3 + 13] == b"img.dat\x004096\x00"
    blocks = list(protocol.data_blocks(bytes(2500)))
    assert [want for _r, want in blocks] == [protocol.ACK_MORE, protocol.ACK_MORE, protocol.ACK_DONE]


# ---------------------------------------------------------------- theme

@pytest.fixture(scope="module")
def stats():
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()
    return telemetry.snapshot()


def test_dashboard_fits_the_firmware_budget_and_round_trips(stats):
    for gpu in (True, False):
        snap = dict(stats, gpus=[{"path": "/x", "name": "GPU", "percent": 40.0, "temp_value": 61.0,
                                  "mem_used_mb": 2048, "mem_total_mb": 8192}] if gpu else [])
        spec = layout.spec(dict(settings.defaults(), name="Second"), snap)
        theme = layout.build(spec)
        assert theme.check() == []
        assert len(theme.numbers) <= imgdat.MAX_NUMBERS
        assert len(theme.numbers) + len(theme.bars) <= imgdat.MAX_WIDGETS
        _key, data = layout.compiled(spec)
        assert protocol.THEME_MIN <= len(data) <= protocol.THEME_MAX
        assert int.from_bytes(data[:4], "little") == imgdat.HEADER_SLOT_COUNT
        records = imgdat.parse(data)
        assert records[0]["type"] == imgdat.BACKGROUND and records[0]["box"] == (0, 0, 480, 320)
        channels = {r["channel"] for r in records if r["type"] in (imgdat.NUMBER, imgdat.PROGRESS)}
        assert len(channels) <= imgdat.MAX_CHANNELS
        values = layout.values(spec, snap, datetime.datetime(2026, 11, 8, 9, 5))
        assert set(values) == channels
        assert [values[c] for c in layout.CLOCK] == [0, 9, 0, 5]          # leading zeros kept
        # The preview is decoded back out of the compiled bytes.
        assert imgdat.render(data, values).size == (480, 320)


def test_word_atlas_and_number_cells():
    atlas = layout.word_atlas(layout.UNITS, 12)
    assert len(set(atlas.widths)) == 1 and len(atlas.data) == sum(atlas.widths) * atlas.height
    digits = layout.digit_atlas(20)
    assert len(set(digits.widths)) == 1            # monospaced: values never shift


def test_theme_check_refuses_what_the_panel_cannot_serve():
    from PIL import Image
    atlas = layout.digit_atlas(12)
    numbers = [imgdat.Number(c, (0, 0, 10, 10), (255, 255, 255), atlas) for c in range(1, 30)]
    theme = imgdat.Theme((480, 320), Image.new("RGB", (480, 320)), numbers)
    assert any("number widgets" in p for p in theme.check())
    with pytest.raises(ValueError):
        imgdat.compile_theme(theme)


def test_layout_key_follows_the_look_not_the_values(stats):
    base = dict(settings.defaults())
    spec = layout.spec(base, stats)
    assert layout.key(spec) == layout.key(layout.spec(base, dict(stats, cpu_percent=99)))
    assert layout.key(spec) != layout.key(layout.spec(dict(base, std_scheme="nord"), stats))
    assert layout.spec(dict(base, orientation="horizontal_flipped"), stats)["rotation"] == 180
    _key, data = layout.compiled(layout.spec(dict(base, orientation="horizontal_flipped"), stats))
    assert any(r["type"] == imgdat.ROTATE and r["rotation"] == 2 for r in imgdat.parse(data))


def test_rates_switch_units():
    assert layout._rate(0.8) == (100, 0)                       # 0.8 Mbit/s = 100 KB/s
    assert layout._rate(800) == (100, 1)                       # 800 Mbit/s = 100 MB/s


# ---------------------------------------------------------------- driver vs a fake panel

class FakePanel:
    """Answers like the firmware: ACK 06 43 / 06 00, optional NAK and restart on reset."""

    def __init__(self, nak_block=None, restart_on_reset=False):
        self.path = "/dev/hidraw-fake"
        self.fd = None
        self.inbox = []
        self.writes = []
        self.buffer = b""
        self.received = bytearray()
        self.expected = None
        self.nak_block = nak_block
        self.restart_on_reset = restart_on_reset
        self.restarts = 0
        self.state = "theme"
        self.opens = 0

    # Hidraw interface
    def open(self):
        self.fd = 3
        self.opens += 1

    def close(self):
        self.fd = None

    def alive(self):
        return self.fd is not None

    def drain(self):
        self.inbox.clear()

    def read(self, _timeout):
        return self.inbox.pop(0) if self.inbox else b""

    def write(self, data):
        if self.fd is None:
            raise DisplayError("disconnected", "closed")
        assert len(data) == 65 and data[0] == 0
        payload = data[1:]
        self.writes.append(payload)
        self._handle(payload)
        return len(data)

    def _ack(self, value):
        self.inbox.append(bytes([protocol.ACK, value]) + bytes(62))

    def _handle(self, payload):
        if self.state != "ymodem":
            if payload.startswith(protocol.RESET):
                if self.restart_on_reset:
                    self.restarts += 1
                    self.fd = None          # the next write fails: re-enumerated
                return
            if payload.startswith(protocol.YMODEM):
                self.state = "ymodem"
                self._ack(protocol.ACK_MORE)
            return
        if not self.buffer and payload[0] == protocol.EOT:
            self._ack(protocol.ACK_MORE)
            return
        if not self.buffer:
            self.expected = 128 if payload[0] == protocol.SOH else 1024
        self.buffer += payload
        size = 3 + self.expected + 2
        if len(self.buffer) >= size:
            block, self.buffer = self.buffer[:size], b""
            kind, seq = block[0], block[1]
            body = block[3:3 + self.expected]
            assert block[2] == (~seq) & 0xFF
            assert int.from_bytes(block[3 + self.expected:size], "big") == protocol.crc16_xmodem(body)
            if kind == protocol.STX and seq == self.nak_block:
                self.nak_block = None
                self.inbox.append(bytes([protocol.NAK]) + bytes(63))
                return
            if kind == protocol.SOH and seq == 0:
                name, _, rest = body.partition(b"\x00")
                if name:
                    self.size = int(rest.split(b"\x00")[0])
                    self._ack(protocol.ACK_MORE)
                else:
                    self.state = "theme"
                    self._ack(protocol.ACK_DONE)
                return
            self.received += body
            done = len(self.received) >= self.size
            self._ack(protocol.ACK_DONE if done else protocol.ACK_MORE)


@pytest.fixture
def make_driver(tmp_path, monkeypatch):
    monkeypatch.setattr(sm_driver, "find_hidraw", lambda _path, sysfs=None: "/dev/hidraw-fake")
    monkeypatch.setattr(sm_driver.time, "sleep", lambda _s: None)
    monkeypatch.setattr(sm_driver, "RESTART_VANISH", 0.0)
    monkeypatch.setattr(sm_driver.os.path, "exists", lambda _p: True)

    def make(panel):
        drv = sm_driver.SmartMonitorHid("/dev/hidraw-fake", "1-1", state_path=str(tmp_path / "state.json"))
        drv.hid = panel
        drv.open()
        return drv
    return make


def test_driver_flashes_once_then_pushes_values(make_driver, stats):
    panel = FakePanel(nak_block=3)
    drv = make_driver(panel)
    assert drv.capabilities.output == TELEMETRY and drv.capabilities.brightness
    steps = []
    drv.on_progress = lambda what: steps.append(what) and False
    frame = drv.build_frame(dict(settings.defaults(), brightness=40), stats)
    drv.present(frame)
    _key, data = layout.compiled(frame.spec)
    assert bytes(panel.received[:len(data)]) == data                 # NAKed block 3 was resent
    assert any(s.startswith("block ") for s in steps)
    with open(drv.state_path, encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["layout"] == frame.key and saved["bytes"] == len(data)
    sensors = [w for w in panel.writes if w[0] == protocol.SENSOR]
    stamp = [w for w in panel.writes if w[0] == protocol.DATETIME][-1]
    assert sensors and stamp[10] == 40
    # Same look: no second flash, only values.
    count = len(panel.writes)
    drv.present(drv.build_frame(dict(settings.defaults(), brightness=40), dict(stats, cpu_percent=77)))
    new = panel.writes[count:]
    assert all(w[0] in (protocol.SENSOR, protocol.DATETIME) for w in new)
    # A new driver (service restart) trusts the remembered layout.
    again = make_driver(FakePanel())
    assert again.flashed == frame.key


def test_driver_follows_a_panel_that_restarts_on_reset(make_driver, stats):
    panel = FakePanel(restart_on_reset=True)
    drv = make_driver(panel)
    drv.present(drv.build_frame(dict(settings.defaults()), stats))
    assert panel.restarts == 1 and panel.opens >= 3                  # reopened after reset and after the flash
    assert drv.uploads == 1


def test_driver_flash_stops_when_the_service_stops(make_driver, stats):
    drv = make_driver(FakePanel())
    drv.on_progress = lambda what: what.startswith("block 2")
    with pytest.raises(DisplayError, match="interrupted"):
        drv.present(drv.build_frame(dict(settings.defaults()), stats))
    assert drv.flashed is None                                        # nothing remembered: flash again later


# ---------------------------------------------------------------- identification

def test_registry_and_discovery_pick_the_panel():
    profile = registry.get("smartmonitor_hid")
    assert profile.transport == "hid"
    device = discovery.UsbDevice("1-1", 0x0483, 0x0065, serial="2022100600", manufacturer="llhmi.com",
                                 product="llTechCo.,Ltd", bus=1, address=4, hidraws=("/dev/hidraw6",))
    found = discovery.discover([device])
    assert found and found[0].best.profile.id == "smartmonitor_hid" and found[0].confidence == registry.CONFIRMED
    drv = profile.create(found[0])
    assert isinstance(drv, sm_driver.SmartMonitorHid) and drv.hid.path == "/dev/hidraw6"


def test_runtime_feeds_the_driver_its_own_frames(tmp_path, stats):
    class Drv(sm_driver.SmartMonitorHid):
        def __init__(self):
            super().__init__("/dev/x", "1-1", state_path=str(tmp_path / "s.json"))
            self.frames = []

        def present(self, frame):
            self.frames.append(frame)

    session = runtime.DisplaySession.__new__(runtime.DisplaySession)
    session.driver = Drv()
    session.id = "usb-1-1"
    session.clock = time.monotonic
    session.hb = {"render": runtime.health.Heartbeat("render"), "transport": runtime.health.Heartbeat("transport")}

    class Box:
        def __init__(self):
            self.items = []

        def put(self, item):
            self.items.append(item)

        def wait_consumed(self, timeout):
            return True
    session.mailbox = Box()
    import threading
    session.wake_render = threading.Event()
    session.wake_render.set()
    session.stop_event = threading.Event()
    session._telemetry_step(dict(settings.defaults()), session.hb["render"])
    frame = session.mailbox.items[0]
    assert isinstance(frame, sm_driver.Frame) and frame.values
    assert session.last_metrics["layout"] == frame.key
    # Progress during a flash keeps the transport heartbeat fresh and honours stop.
    beat = session.hb["transport"]
    beat.begin("present")
    beat.op_started -= 100
    assert session._driver_progress("block 1/2") is False and beat.stalled(30, 30) is None
    session.stop_event.set()
    assert session._driver_progress("block 2/2") is True
