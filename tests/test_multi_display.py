"""Multi-display runtime: independent sessions, hot-plug discovery, spool commands."""

import json
import os

import pytest
from PIL import Image

from bsmd import frames, health, patterns, runtime, settings
from bsmd.displays import registry
from bsmd.displays.discovery import UsbDevice
from bsmd.displays.simulated import SimulatedDisplay
from test_runtime import FakeNotifier, FastRuntime, kinds, wait_for


@pytest.fixture
def make(tmp_path):
    config = tmp_path / "settings.json"
    started = []

    def start(data=None, simulate=None, scan=None, service=False):
        settings.save(data or {"theme": "standard"}, str(config))
        app = FastRuntime(settings.SettingsStore(str(config)), notifier=FakeNotifier(), simulate=simulate,
                          service=service, status_file=str(tmp_path / "run" / "status.json"),
                          state_directory=str(tmp_path / "state"), scan=scan)
        app.DISCOVERY_EVERY = 0.1
        app.SESSION_LINGER = 0.5
        app.backoff = health.Backoff(base=0.05, cap=0.2, jitter=0)
        import threading
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("code", app.run()), daemon=True)
        thread.start()
        started.append((app, thread))
        return app, result

    yield start, config
    for app, thread in started:
        app.stop()
        thread.join(5)


def test_two_panels_have_independent_settings(make):
    big, tiny = SimulatedDisplay((480, 320)), SimulatedDisplay((160, 80), model="tiny")
    data = {"theme": "standard", "brightness": 40,
            "displays": {"simulated-1": {"theme": "gkrellm", "brightness": 90, "orientation": "vertical"}}}
    start, _config = make
    app, _ = start(data, simulate=[big, tiny])
    assert wait_for(lambda: big.frames >= 2 and tiny.frames >= 2)
    assert big.brightness == 40 and tiny.brightness == 90
    assert app.sessions["simulated"].theme.info.id == "standard"
    assert app.sessions["simulated-1"].theme.info.id == "gkrellm"
    assert tiny.last_image.size == (160, 80)
    status = None
    assert wait_for(lambda: len((runtime.read_status(app.status_file) or {}).get("displays", [])) == 2)
    status = runtime.read_status(app.status_file)
    assert [d["id"] for d in status["displays"]] == ["simulated", "simulated-1"]
    assert status["displays"][1]["settings"]["theme"] == "gkrellm"


def test_failing_panel_is_isolated(make):
    good, bad = SimulatedDisplay((320, 240)), SimulatedDisplay((320, 240), fail_open=1000)
    start, _config = make
    app, result = start(simulate=[good, bad], service=True)
    assert wait_for(lambda: app.sessions.get("simulated-1") is not None
                    and app.sessions["simulated-1"].link.state == health.FAILED, timeout=10)
    frames_before = good.frames
    assert wait_for(lambda: good.frames > frames_before + 2)
    assert app.sessions["simulated"].link.state == health.HEALTHY
    assert "code" not in result                  # one dead panel never restarts the others
    assert app.overall_state() == health.DEGRADED
    failed = [i for i in app.incidents.recent(100) if i["kind"] == "recovery_failed"]
    assert failed and all(i["display"] == "simulated-1" for i in failed)


def test_per_display_reconnect_only_touches_that_display(make):
    one, two = SimulatedDisplay((320, 240)), SimulatedDisplay((320, 240))
    start, _config = make
    app, _ = start(simulate=[one, two])
    assert wait_for(lambda: one.frames >= 1 and two.frames >= 1)
    app.request("reconnect", "test", display="simulated-1")
    assert wait_for(lambda: two.opens >= 2)
    assert one.opens == 1


def test_spool_pattern_is_shown_then_theme_restored(make):
    panel = SimulatedDisplay((320, 240))
    start, _config = make
    app, _ = start(simulate=[panel])
    assert wait_for(lambda: panel.frames >= 1)
    runtime.spool_command({"action": "pattern", "pattern": "white", "seconds": 2}, app.status_file)
    assert wait_for(lambda: panel.last_image is not None
                    and panel.last_image.getpixel((160, 120)) == (255, 255, 255))
    assert wait_for(lambda: app.sessions["simulated"].pattern is None, timeout=6)
    assert wait_for(lambda: panel.last_image.getpixel((160, 120)) != (255, 255, 255))
    assert not os.listdir(os.path.join(os.path.dirname(app.status_file), "commands"))


def test_spool_rejects_unknown_actions(make, tmp_path):
    panel = SimulatedDisplay((320, 240))
    start, _config = make
    app, _ = start(simulate=[panel])
    assert wait_for(lambda: panel.frames >= 1)
    spool = os.path.join(os.path.dirname(app.status_file), "commands")
    os.makedirs(spool, exist_ok=True)
    with open(os.path.join(spool, "1.json"), "w") as handle:
        json.dump({"action": "flash_firmware", "display": "*"}, handle)
    with open(os.path.join(spool, "2.json"), "w") as handle:
        handle.write("{not json")
    assert wait_for(lambda: not os.listdir(spool))
    assert app.sessions["simulated"].pattern is None and panel.opens == 1


class FakeBus:
    """sysfs stand-in: a list of UsbDevice the test can change."""

    def __init__(self, *devices):
        self.devices = list(devices)

    def __call__(self):
        return list(self.devices)


AX206_DEV = UsbDevice("5-1.4.4", 0x1908, 0x0102, bus=5, address=13)
WEACT_TINY = UsbDevice("3-2", 0x1A86, 0xFE0C, serial="AD123", ttys=("/dev/ttyACM9",))
AMBIGUOUS_CH340 = UsbDevice("3-3", 0x1A86, 0x5722, serial="", ttys=("/dev/ttyACM8",))
UNKNOWN_FTDI = UsbDevice("4-1", 0x0403, 0x6001, serial="A9XYZ", ttys=("/dev/ttyUSB0",))


@pytest.fixture
def fake_panels(monkeypatch):
    created = {}

    def create(self, _settings):
        candidate = self.candidate()
        if candidate is None or self.runtime.profile_for(candidate) is None:
            from bsmd.displays.base import NOT_FOUND, DisplayError
            raise DisplayError(NOT_FOUND, "gone")
        self.profile = self.runtime.profile_for(candidate)
        panel = created.get(self.display_id)
        if panel is None:
            size = (160, 80) if self.profile.id == "weact_b" else (480, 320)
            panel = created[self.display_id] = SimulatedDisplay(size, model=self.profile.id)
        return panel

    monkeypatch.setattr(runtime.UsbSource, "create", create)
    return created


def test_hotplug_adds_and_removes_sessions(make, fake_panels):
    bus = FakeBus(AX206_DEV)
    start, _config = make
    app, _ = start(scan=bus)
    assert wait_for(lambda: "usb-5-1.4.4" in fake_panels and fake_panels["usb-5-1.4.4"].frames >= 1)
    bus.devices.append(WEACT_TINY)
    assert wait_for(lambda: "usb-3-2" in fake_panels and fake_panels["usb-3-2"].frames >= 1)
    assert fake_panels["usb-3-2"].last_image.size == (160, 80)
    bus.devices.remove(WEACT_TINY)
    fake_panels["usb-3-2"].connected = False
    assert wait_for(lambda: "usb-3-2" not in app.sessions, timeout=6)
    assert "display_removed" in kinds(app)
    assert app.sessions["usb-5-1.4.4"].link.state == health.HEALTHY


def test_shared_ids_default_to_rev_a_and_can_be_reassigned(make, fake_panels):
    """1a86:5722 without a known serial: rev. A (as every earlier version), XuanFang on request."""
    bus = FakeBus(AMBIGUOUS_CH340)
    start, config = make
    app, _ = start(scan=bus)
    assert wait_for(lambda: "usb-3-3" in fake_panels and fake_panels["usb-3-3"].frames >= 1)
    assert app.sessions["usb-3-3"].source.profile.id == "turing_rev_a"
    settings.save({"displays": {"usb-3-3": {"profile": "xuanfang_rev_b"}}}, str(config))
    assert wait_for(lambda: fake_panels["usb-3-3"].opens >= 2)
    assert wait_for(lambda: app.sessions["usb-3-3"].source.profile.id == "xuanfang_rev_b")


def test_unknown_serial_device_needs_manual_assignment(make, fake_panels):
    bus = FakeBus(UNKNOWN_FTDI)
    start, config = make
    app, _ = start(scan=bus)
    assert wait_for(lambda: app.link.state == health.RETRYING)
    assert not app.sessions and not app.pending          # never opened, never probed
    settings.save({"displays": {"usb-4-1": {"profile": "weact_a"}}}, str(config))
    assert wait_for(lambda: "usb-4-1" in fake_panels and fake_panels["usb-4-1"].frames >= 1)


def test_disabled_display_is_not_driven(make, fake_panels):
    bus = FakeBus(AX206_DEV, WEACT_TINY)
    start, config = make
    app, _ = start({"displays": {"usb-3-2": {"enabled": False}}}, scan=bus)
    assert wait_for(lambda: "usb-5-1.4.4" in fake_panels and fake_panels["usb-5-1.4.4"].frames >= 1)
    assert "usb-3-2" not in app.sessions
    settings.save({"displays": {"usb-3-2": {"enabled": True}}}, str(config))
    assert wait_for(lambda: "usb-3-2" in app.sessions)
    settings.save({"displays": {"usb-3-2": {"enabled": False}}}, str(config))
    assert wait_for(lambda: "usb-3-2" not in app.sessions)


def test_legacy_model_setting_limits_families(make, fake_panels):
    bus = FakeBus(AX206_DEV, WEACT_TINY)
    start, _config = make
    app, _ = start({"model": "ax206"}, scan=bus)
    assert wait_for(lambda: "usb-5-1.4.4" in app.sessions)
    assert wait_for(lambda: any(c.id == "usb-3-2" for c in app.pending))
    assert "usb-3-2" not in app.sessions


# ------------------------------------------------------------------ settings

def test_display_settings_validation():
    clean, problems = settings.validate({"displays": {
        "usb-1-2": {"theme": "neon", "brightness": 500, "model": "ax206", "language": "en", "name": "x" * 99,
                    "profile": "weact_b", "led_color": "rainbow", "orientation": "vertical_flipped"},
        "../../etc/passwd": {}, "usb-3": "nope"}})
    entry = clean["displays"]["usb-1-2"]
    assert entry["theme"] == "standard" and entry["std_scheme"] == "neon"
    assert entry["brightness"] == 100 and entry["name"] == "" and entry["led_color"] == "off"
    assert entry["profile"] == "weact_b" and entry["orientation"] == "vertical_flipped"
    assert "model" not in entry and "language" not in entry          # global-only keys
    assert "../../etc/passwd" not in clean["displays"]
    assert clean["displays"]["usb-3"] == {}
    assert len(problems) >= 4


def test_too_many_displays_are_capped():
    data = {"displays": {f"usb-1-{i}": {} for i in range(40)}}
    clean, problems = settings.validate(data)
    assert len(clean["displays"]) == settings.MAX_DISPLAYS and problems


def test_merged_settings_override_globals():
    clean, _ = settings.validate({"theme": "planet", "brightness": 20,
                                  "displays": {"usb-1-1": {"brightness": 80}}})
    merged = settings.merged(clean, "usb-1-1")
    assert merged["theme"] == "planet" and merged["brightness"] == 80 and merged["enabled"] is True
    assert settings.merged(clean, "usb-9-9")["brightness"] == 20


def test_settings_profile_ids_match_registry():
    assert set(settings.PROFILE_IDS) == set(registry.BY_ID)
    assert set(settings.DISPLAY_SCHEMA["led_color"][1]) == set(runtime.LED_RGB)


# ------------------------------------------------------------------ frames / patterns

@pytest.mark.parametrize("orientation,expected", [
    ("horizontal", (0, 0)), ("horizontal_flipped", (479, 319)), ("vertical", (0, 319)),
    ("vertical_flipped", (479, 0))])
def test_orientations_map_top_left_corner(orientation, expected):
    width, height = frames.render_size((480, 320), orientation)
    image = Image.new("RGB", (width, height))
    image.putpixel((0, 0), (255, 0, 0))
    native = frames.to_native(image, (480, 320), orientation)
    assert native.size == (480, 320)
    assert native.getpixel(expected) == (255, 0, 0)


def test_square_panel_still_rotates():
    image = Image.new("RGB", (480, 480))
    image.putpixel((0, 0), (255, 0, 0))
    assert frames.to_native(image, (480, 480), "vertical").getpixel((0, 479)) == (255, 0, 0)


@pytest.mark.parametrize("name", patterns.NAMES)
@pytest.mark.parametrize("size", [(80, 160), (160, 80), (480, 480), (1920, 480)])
def test_patterns_render_everywhere(name, size):
    image = patterns.render(name, *size, label="Panel", display_id="usb-1-1", shape="round")
    assert image.size == size
