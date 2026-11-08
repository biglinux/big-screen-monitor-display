"""MPRIS client against real D-Bus traffic on a private bus.

A private ``dbus-daemon`` is started for the module, so the user's session is
never touched. The players are :mod:`tests.mpris_fake` servers (real D-Bus
objects); the code under test is the production client, core and IPC.
Skipped when PyGObject or dbus-daemon are missing (minimal CI images).
"""

import os
import shutil
import subprocess
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

if not shutil.which("dbus-daemon"):
    pytest.skip("dbus-daemon not installed", allow_module_level=True)

from bsmd import runtime, settings, themes  # noqa: E402
from bsmd.media import agent, hub, ipc, model, mpris, volume  # noqa: E402
from mpris_fake import FakePlayer  # noqa: E402


@pytest.fixture(scope="module")
def bus_address():
    proc = subprocess.Popen(["dbus-daemon", "--session", "--print-address", "--nofork", "--nopidfile"],
                            stdout=subprocess.PIPE, text=True)
    address = proc.stdout.readline().strip()
    yield address
    proc.terminate()
    proc.wait(timeout=5)


def connect(address):
    return Gio.DBusConnection.new_for_address_sync(
        address, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)


def spin(condition, timeout=3.0):
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def watcher(bus_address):
    events = []
    w = mpris.MprisWatcher(connect(bus_address), lambda bus, areas: events.append((bus, areas)))
    w.start()
    yield w, events
    w.stop()


@pytest.fixture
def player_conn(bus_address):
    return connect(bus_address)


def test_detects_player_and_reads_metadata(watcher, player_conn):
    w, _events = watcher
    fake = FakePlayer(player_conn, "fakeone", identity="Fake One")
    try:
        assert spin(lambda: w.players.get(fake.name) is not None and w.players[fake.name].ready)
        player = w.players[fake.name]
        assert player.identity == "Fake One"
        assert player.meta["title"] == "First Light"
        assert player.meta["artist"] == "Test Band"
        assert player.meta["length_us"] == 180_000_000
        assert player.can["next"] and player.can["seek"]
    finally:
        fake.close()


def test_signals_update_status_track_and_seek(watcher, player_conn):
    w, _events = watcher
    fake = FakePlayer(player_conn, "faketwo")
    try:
        assert spin(lambda: fake.name in w.players and w.players[fake.name].ready)
        fake.set_status("Playing")
        assert spin(lambda: w.players[fake.name].status == "Playing")
        assert w.players[fake.name].playing_since is not None
        fake.set_track(1)
        assert spin(lambda: w.players[fake.name].meta["title"] == "Second Wind")
        assert w.players[fake.name].meta["artist"] == "Test Band, Guest"
        fake.seek_to(90_000_000)
        assert spin(lambda: abs((w.players[fake.name].position_us or 0) - 90_000_000) < 1_000_000)
        fake.set_status("Paused")
        assert spin(lambda: w.players[fake.name].status == "Paused")
        frozen = w.players[fake.name].position_now()
        time.sleep(0.2)
        assert w.players[fake.name].position_now() == frozen      # paused: the bar stops
    finally:
        fake.close()


def test_commands_respect_capabilities(watcher, player_conn):
    w, _events = watcher
    fake = FakePlayer(player_conn, "fakethree", can_next=False)
    try:
        assert spin(lambda: fake.name in w.players and w.players[fake.name].ready)
        replies = []
        w.command(fake.name, "play_pause", lambda ok, msg: replies.append((ok, msg)))
        assert spin(lambda: fake.props["PlaybackStatus"] == "Playing")
        assert spin(lambda: replies and replies[0][0])
        replies.clear()
        assert w.command(fake.name, "next", lambda ok, msg: replies.append((ok, msg))) is False
        assert replies == [(False, "not supported by this player")]
        assert not any(call[0] == "Next" for call in fake.calls)       # refused locally, never sent
        w.set_property(fake.name, "Shuffle", GLib.Variant("b", True))
        assert spin(lambda: fake.props["Shuffle"] is True)
        assert spin(lambda: w.players[fake.name].shuffle is True)
        w.seek_to(fake.name, 30_000_000)
        assert spin(lambda: fake.props["Position"] == 30_000_000)
        assert ("SetPosition", ("/test/track/0", 30_000_000)) in fake.calls
    finally:
        fake.close()


def test_player_exit_is_detected(watcher, player_conn):
    w, events = watcher
    fake = FakePlayer(player_conn, "fakefour")
    assert spin(lambda: fake.name in w.players)
    fake.close()
    assert spin(lambda: fake.name not in w.players)
    assert any(bus == fake.name and "removed" in areas for bus, areas in events)


def test_unknown_length_stays_unknown(watcher, player_conn):
    w, _events = watcher
    fake = FakePlayer(player_conn, "fakelive", length=False)
    try:
        assert spin(lambda: fake.name in w.players and w.players[fake.name].ready)
        assert w.players[fake.name].meta["length_us"] is None
        snapshot = model.clean_player(w.players[fake.name].to_wire())
        assert model.is_live(snapshot)
    finally:
        fake.close()


def test_core_snapshot_to_hub_to_theme(bus_address, player_conn, monkeypatch, tmp_path):
    """Agent core -> wire messages -> service hub -> rendered frame, all real code."""
    monkeypatch.setattr(volume, "BACKENDS", ())          # never touch the real audio server in tests
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    art = tmp_path / "cover.png"
    from PIL import Image
    Image.new("RGB", (64, 64), (200, 30, 30)).save(art)
    service_hub = hub.MediaHub()
    received = []

    def sink(message, coalesce=None):
        received.append(message["type"])
        service_hub.on_message(1000, message)

    values = dict(settings.defaults(), theme="big_media_player")
    core = agent.MediaCore(connect(bus_address), values, sink=sink)
    core.start()
    spotify = FakePlayer(player_conn, "spotifytest", identity="Spotify Test", art_url=f"file://{art}")
    browser = FakePlayer(connect(bus_address), "firefoxtest.instance_1", identity="Browser Test")
    try:
        spotify.set_status("Playing")
        assert spin(lambda: service_hub.view().snapshot is not None and
                    service_hub.view().snapshot.get("active") == spotify.name, 4)
        assert spin(lambda: "art" in received, 4)
        view = service_hub.view()
        player = next(p for p in view.players if p["bus"] == spotify.name)
        assert player["art"] and view.art(player["art"]).getpixel((5, 5))[0] > 150
        # A browser tab starting to play must not steal the display while Spotify plays.
        browser.set_status("Playing")
        spin(lambda: False, 0.3)
        assert service_hub.view().snapshot["active"] == spotify.name

        class Ctx(runtime.RenderContext):
            def media(self):
                return service_hub.view()
        ctx = Ctx(preview=False)
        theme = themes.create("big_media_player", ctx)
        image = theme.render(480, 320, dict(values, bmp_visualizer="off"), ctx)
        assert image.size == (480, 320)
        # Commands through the core reach the player.
        replies = []
        core.command("play_pause", "", 0, lambda ok, msg: replies.append(ok))
        assert spin(lambda: spotify.props["PlaybackStatus"] == "Paused")
        # Paused Spotify + browser playing for a while -> the browser takes over (auto mode).
        assert spin(lambda: service_hub.view().snapshot["active"] == browser.name, 5)
    finally:
        spotify.close()
        browser.close()
        core.stop()


def test_agent_control_interface_single_instance(bus_address, monkeypatch, tmp_path):
    monkeypatch.setattr(volume, "BACKENDS", ())
    config = tmp_path / "settings.json"
    settings.save(dict(settings.defaults(), theme="big_media_player"), str(config))
    env = dict(os.environ, DBUS_SESSION_BUS_ADDRESS=bus_address, BSM_CONFIG=str(config),
               XDG_RUNTIME_DIR=str(tmp_path), XDG_CACHE_HOME=str(tmp_path))
    main = os.path.join(os.path.dirname(__file__), "..", "usr", "share", "big-screen-monitor-display", "main.py")
    proc = subprocess.Popen(["python3", main, "--media-agent"], env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        conn = connect(bus_address)
        assert spin(lambda: agent.agent_running(conn), 8)
        state = agent.agent_state(conn)
        assert state["type"] == "snapshot" and state["players"] == []
        ok, message = agent.call_agent(conn, "next")
        assert not ok and message == "no media player"
        second = subprocess.run(["python3", main, "--media-agent"], env=env, timeout=15, capture_output=True)
        assert second.returncode == 0          # already running: exits at once
        assert proc.poll() is None
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_agent_goes_dormant_and_wakes_up_with_the_theme(bus_address, monkeypatch, tmp_path):
    """The agent used to exit when the theme was unused; if the theme came back
    any other way than the window's Apply (or that launch failed), nothing fed the
    display until the next login. Now it sleeps and wakes up by itself."""
    monkeypatch.setattr(volume, "BACKENDS", ())
    monkeypatch.setattr(ipc, "socket_candidates", lambda: [str(tmp_path / "media.sock")])
    config = tmp_path / "settings.json"
    monkeypatch.setenv("BSM_CONFIG", str(config))
    settings.save(dict(settings.defaults(), theme="standard"), str(config))
    probe = connect(bus_address)
    first = agent.Agent()
    first.conn = connect(bus_address)
    second = agent.Agent()
    second.conn = connect(bus_address)
    try:
        assert first._check_settings() is True and not first.active      # dormant, but alive
        assert not agent.agent_running(probe)
        settings.save(dict(settings.defaults(), theme="big_media_player", bmp_skin="bigamp"), str(config))
        assert first._check_settings() is True and first.active
        assert spin(lambda: agent.agent_running(probe))
        # Theme switched away for longer than the grace period: back to sleep, name released.
        monkeypatch.setattr(agent, "IDLE_EXIT_AFTER", -1.0)
        settings.save(dict(settings.defaults(), theme="standard"), str(config))
        assert first._check_settings() is True and not first.active
        assert spin(lambda: not agent.agent_running(probe))
        # Another agent became active meanwhile (the window started one): the dormant one leaves.
        assert second._activate()
        settings.save(dict(settings.defaults(), theme="big_media_player"), str(config))
        assert first._check_settings() is False and not first.active
        assert agent.agent_running(probe) and second.active
    finally:
        first._deactivate()
        second._deactivate()
