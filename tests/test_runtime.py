"""End-to-end pipeline tests against the simulated panel with fault injection."""

import threading
import time

import pytest

from bsmd import drivers, health, runtime, settings


class FakeNotifier:
    def __init__(self, watchdog_usec=10_000_000):
        self.watchdog_usec = watchdog_usec
        self.pings = 0
        self.messages = []

    def watchdog(self):
        self.pings += 1

    def ready(self, status=None):
        self.messages.append("READY")

    def status(self, text):
        self.messages.append(text)

    def stopping(self):
        self.messages.append("STOPPING")


class FastRuntime(runtime.Runtime):
    PROGRESS_TIMEOUT = {"telemetry": 30.0, "render": 5.0, "transport": 5.0}
    OP_TIMEOUT = {"telemetry": 30.0, "render": 5.0, "transport": 1.0}
    ABSENT_POLL = 0.1
    SUPERVISE_EVERY = 0.1
    STATUS_EVERY = 0.3
    MAX_FAILED_ATTEMPTS = 4


def wait_for(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def env(tmp_path):
    config = tmp_path / "settings.json"
    settings.save({"theme": "dark", "brightness": 50}, str(config))
    started = []

    def start(panel=None, service=False, notifier=None, **overrides):
        panel = panel or drivers.SimulatedDisplay((320, 240))
        app = FastRuntime(settings.SettingsStore(str(config)), notifier=notifier or FakeNotifier(),
                          simulate=panel, service=service, status_file=str(tmp_path / "status.json"),
                          state_directory=str(tmp_path / "state"))
        app.backoff = health.Backoff(base=0.05, cap=0.2, jitter=0)
        for key, value in overrides.items():
            setattr(app, key, value)
        result = {}
        thread = threading.Thread(target=lambda: result.setdefault("code", app.run()), daemon=True)
        thread.start()
        started.append((app, thread))
        return app, panel, result

    yield start, config
    for app, thread in started:
        app.stop()
        thread.join(5)


def kinds(app):
    return [incident["kind"] for incident in app.incidents.recent(100)]


def test_connects_and_delivers_frames(env):
    start, _config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 2)
    assert app.link.state == health.HEALTHY
    assert panel.brightness == 50
    assert app.notifier.pings > 0


def test_recovers_from_usb_disconnect_during_transfer(env):
    """Root cause of the reported freeze: stale handle after re-enumeration."""
    start, _config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 1)
    panel.faults = [drivers.DISCONNECTED]
    assert wait_for(lambda: panel.opens >= 2 and app.link.state == health.HEALTHY)
    assert "transport_disconnected" in kinds(app) and "recovered" in kinds(app)
    full_before = panel.full_frames
    assert wait_for(lambda: panel.full_frames > full_before or panel.full_frames >= 2)
    assert app.recoveries >= 1


def test_transient_timeout_degrades_without_reopen(env):
    start, _config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 1)
    states = []
    app.link._on_change = lambda old, new, reason: states.append(new)
    panel.faults = [drivers.TIMEOUT]
    assert wait_for(lambda: health.DEGRADED in states and app.link.state == health.HEALTHY)
    assert panel.opens == 1


def test_unplug_and_replug(env):
    start, _config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 1)
    panel.connected = False
    assert wait_for(lambda: app.link.state == health.RETRYING)
    pings = app.notifier.pings
    assert wait_for(lambda: app.notifier.pings > pings + 3)   # waiting is healthy, not stalled
    panel.connected = True
    assert wait_for(lambda: app.link.state == health.HEALTHY and panel.opens >= 2)


def test_display_absent_at_start_waits_instead_of_exiting(env):
    start, _config = env
    panel = drivers.SimulatedDisplay((320, 240), connected=False)
    app, panel, result = start(panel)
    assert wait_for(lambda: app.link.state == health.RETRYING)
    time.sleep(0.3)
    assert "code" not in result
    panel.connected = True
    assert wait_for(lambda: panel.frames >= 1)


def test_hung_transfer_stops_watchdog_pings(env):
    start, _config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 1)
    panel.faults = [("hang", 2.5)]
    app.request("invalidate")   # force a non-empty transfer
    assert wait_for(lambda: app.stall_reported, timeout=6)
    pings = app.notifier.pings
    time.sleep(0.5)
    assert app.notifier.pings == pings       # no fake heartbeat while stuck
    assert "pipeline_stalled" in kinds(app)
    assert wait_for(lambda: not app.stall_reported, timeout=6)  # resumes after the hang
    assert app.notifier.pings > pings


def test_persistent_failure_exits_for_systemd_restart(env):
    start, _config = env
    panel = drivers.SimulatedDisplay((320, 240), fail_open=100)
    app, panel, result = start(panel, service=True)
    assert wait_for(lambda: "code" in result, timeout=10)
    assert result["code"] == 3
    assert "recovery_failed" in kinds(app)


def test_live_settings_changes(env):
    start, config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 1)
    settings.save({"theme": "neon", "brightness": 90, "orientation": "vertical"}, str(config))
    assert wait_for(lambda: panel.brightness == 90)
    assert wait_for(lambda: panel.last_image is not None and panel.last_image.size == (320, 240))
    assert panel.opens == 1    # applied without reconnecting


def test_broken_theme_falls_back(env, monkeypatch):
    from bsmd import themes
    original = themes.LegacyTheme.render

    def broken(self, *args):
        if self.info.id == "planet":
            raise RuntimeError("boom")
        return original(self, *args)

    monkeypatch.setattr(themes.LegacyTheme, "render", broken)
    start, config = env
    settings.save({"theme": "planet"}, str(config))
    app, panel, _ = start()
    assert wait_for(lambda: "theme_fallback" in kinds(app))
    frames = panel.frames
    assert wait_for(lambda: panel.frames > frames)


def test_status_file_is_written(env):
    start, _config = env
    app, panel, _ = start()
    assert wait_for(lambda: panel.frames >= 1)
    assert wait_for(lambda: (runtime.read_status(app.status_file) or {}).get("state") == "healthy")
    status = runtime.read_status(app.status_file)
    assert status["device"]["width"] == 320
    assert set(status["pipeline"]) == {"telemetry", "render", "transport"}
