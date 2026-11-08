"""Big Media Player data path: contract, selection policy, IPC, hub, art, volume parsers, spectrum.

Pure Python (no D-Bus): the D-Bus client is covered in test_media_dbus.py.
"""

import base64
import io
import json
import math
import os
import socket
import struct
import time

import pytest
from PIL import Image

from bsmd.media import artwork, hub, ipc, model, selection


def player(bus="org.mpris.MediaPlayer2.spotify", status="Playing", title="Song", length=200_000_000,
           position=10_000_000, since=None, active=0.0, **extra):
    data = {"bus": bus, "identity": bus.rsplit(".", 1)[-1].title(), "status": status, "title": title,
            "artist": "Artist", "album": "Album", "length_us": length, "position_us": position,
            "position_mono": 100.0, "rate": 1.0, "can": {k: True for k in model.CAPS},
            "last_active_mono": active, "playing_since_mono": since if since is not None else
            (active if status == "Playing" else None)}
    data.update(extra)
    return model.clean_player(data)


# ---------------------------------------------------------------- contract

def test_clean_player_never_invents_values():
    p = model.clean_player({"bus": "org.mpris.MediaPlayer2.vlc", "status": "Weird", "length_us": 0,
                            "position_us": "12", "title": "a\x00b\nc", "can": {"next": 1}})
    assert p["status"] == "Stopped"
    assert p["length_us"] is None and p["position_us"] is None
    assert p["title"] == "a b c"
    assert p["can"]["next"] is True and p["can"]["seek"] is False
    assert model.clean_player({"bus": "com.evil.Thing"}) is None


def test_snapshot_validation_limits_and_versions():
    raw = {"type": "snapshot", "v": 1, "players": [{"bus": f"org.mpris.MediaPlayer2.p{i}"} for i in range(40)],
           "active": "org.mpris.MediaPlayer2.p3", "volume": {"available": True, "percent": 500, "muted": 1}}
    snap = model.clean_snapshot(raw)
    assert len(snap["players"]) == model.MAX_PLAYERS
    assert snap["active"] == "org.mpris.MediaPlayer2.p3"
    assert snap["volume"]["percent"] == 200 and snap["volume"]["muted"] is True
    assert model.clean_snapshot(dict(raw, v=99)) is None
    assert model.clean_snapshot(dict(raw, active="org.mpris.MediaPlayer2.ghost"))["active"] is None


def test_art_message_must_match_its_size():
    rgb = base64.b64encode(bytes(4 * 4 * 3)).decode()
    assert model.clean_art({"type": "art", "id": "abc", "w": 4, "h": 4, "rgb": rgb})
    assert model.clean_art({"type": "art", "id": "abc", "w": 5, "h": 4, "rgb": rgb}) is None
    assert model.clean_art({"type": "art", "id": "../x", "w": 4, "h": 4, "rgb": rgb}) is None
    assert model.clean_art({"type": "art", "id": "a", "w": 4000, "h": 4, "rgb": rgb}) is None


def test_position_interpolates_only_while_playing():
    p = player(position=10_000_000, length=20_000_000)
    assert model.position_now(p, now=102.5) == 12_500_000
    assert model.position_now(p, now=1000.0) == 20_000_000            # clamped to the length
    paused = player(status="Paused", position=10_000_000)
    assert model.position_now(paused, now=150.0) == 10_000_000
    fast = player(rate=2.0, position=0)
    assert model.position_now(fast, now=101.0) == 2_000_000
    assert model.position_now(player(position=None), now=101.0) is None


def test_time_format_and_fallbacks():
    assert model.fmt_time(84_000_000) == "01:24"
    assert model.fmt_time(3_723_000_000) == "1:02:03"
    assert model.fmt_time(None) == "--:--"
    assert model.secondary_line({"description": "", "artist": "", "album": "X", "identity": "VLC"}) == "X"
    assert model.secondary_line({"identity": "VLC"}) == "VLC"
    assert model.is_live(player(length=None))
    assert not model.is_live(player())


# ---------------------------------------------------------------- selection

def test_auto_keeps_the_playing_player():
    m = selection.ActivePlayerManager()
    spotify = player(active=10.0)
    assert m.choose([spotify], 11.0) == spotify["bus"]
    tab = player("org.mpris.MediaPlayer2.firefox.instance_1", since=20.0, active=20.0)
    assert m.choose([spotify, tab], 30.0) == spotify["bus"]           # both playing: no stealing


def test_auto_switches_after_the_steal_delay():
    m = selection.ActivePlayerManager()
    m.current = "org.mpris.MediaPlayer2.spotify"
    spotify = player(status="Paused", active=10.0)
    tab = player("org.mpris.MediaPlayer2.firefox.instance_1", since=20.0, active=20.0)
    assert m.choose([spotify, tab], 21.0) == spotify["bus"]           # only 1 s: wait
    assert m.choose([spotify, tab], 22.5) == tab["bus"]


def test_short_clips_never_steal():
    m = selection.ActivePlayerManager()
    m.current = "org.mpris.MediaPlayer2.spotify"
    spotify = player(status="Paused", active=10.0)
    ding = player("org.mpris.MediaPlayer2.chromium.instance9", since=20.0, active=20.0, length=3_000_000)
    assert m.choose([spotify, ding], 40.0) == spotify["bus"]


def test_last_mode_follows_recent_activity():
    m = selection.ActivePlayerManager("last")
    spotify = player(active=10.0)
    tab = player("org.mpris.MediaPlayer2.firefox.instance_1", since=20.0, active=20.0)
    assert m.choose([spotify, tab], 20.1) == tab["bus"]


def test_fixed_and_ignored_players():
    m = selection.ActivePlayerManager("fixed", fixed="vlc")
    spotify = player(active=10.0)
    vlc = player("org.mpris.MediaPlayer2.vlc", status="Paused", active=1.0)
    assert m.choose([spotify, vlc], 11.0) == vlc["bus"]
    assert m.choose([spotify], 12.0) == spotify["bus"]                # fixed player absent: automatic
    ignoring = selection.ActivePlayerManager(ignore=["spotify"])
    assert ignoring.choose([spotify, vlc], 13.0) == vlc["bus"]
    assert ignoring.choose([spotify], 13.0) is None


def test_player_gone_picks_another_and_auto_switch_off_holds():
    m = selection.ActivePlayerManager(auto_switch=False)
    m.current = "org.mpris.MediaPlayer2.spotify"
    spotify = player(status="Paused")
    tab = player("org.mpris.MediaPlayer2.firefox.instance_1", since=1.0, active=1.0)
    assert m.choose([spotify, tab], 50.0) == spotify["bus"]
    assert m.choose([tab], 51.0) == tab["bus"]


def test_settings_patterns():
    assert model.split_patterns("chromium; kdeconnect , ,x") == ["chromium", "kdeconnect", "x"]
    m = selection.ActivePlayerManager.from_settings({"bmp_player_mode": "fixed", "bmp_player_fixed": "Spot",
                                                     "bmp_player_ignore": "chrome"})
    assert m.mode == "fixed" and m.fixed == "Spot" and m.ignore == ["chrome"]


# ---------------------------------------------------------------- IPC

def test_frame_decoder_rejects_garbage():
    decoder = ipc.FrameDecoder()
    frame = ipc.encode({"type": "snapshot"})
    assert decoder.feed(frame[:3]) == []
    assert decoder.feed(frame[3:] + frame) == [{"type": "snapshot"}, {"type": "snapshot"}]
    with pytest.raises(ValueError):
        ipc.FrameDecoder().feed(struct.pack(">I", ipc.MAX_FRAME + 1))
    with pytest.raises(ValueError):
        ipc.FrameDecoder().feed(struct.pack(">I", 3) + b"{x}")


def test_active_seat_uid(tmp_path):
    (tmp_path / "seat0").write_text("ACTIVE=c2\nACTIVE_UID=1001\n")
    assert ipc.active_seat_uid(str(tmp_path)) == 1001
    assert ipc.default_authorize(1001, str(tmp_path))
    assert not ipc.default_authorize(1002, str(tmp_path))       # another user's agent is ignored
    assert ipc.active_seat_uid(str(tmp_path / "none")) is None


def spin_until(condition, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def test_server_and_publisher_roundtrip(tmp_path):
    path = str(tmp_path / "media.sock")
    got = []
    server = ipc.Server(path, lambda uid, message: got.append((uid, message)), authorize=lambda uid: True)
    assert server.start()
    assert oct(os.stat(path).st_mode & 0o777) == "0o666"
    publisher = ipc.Publisher([path])
    publisher.start()
    try:
        publisher.publish({"type": "snapshot", "n": 1}, coalesce="snapshot")
        publisher.publish({"type": "snapshot", "n": 2}, coalesce="snapshot")
        publisher.publish({"type": "art", "id": "a"})
        assert spin_until(lambda: any(m.get("type") == "art" for _u, m in got))
        assert all(uid == os.getuid() for uid, _m in got)
        assert spin_until(lambda: any(m.get("n") == 2 for _u, m in got))
    finally:
        publisher.stop()
        server.stop()
    assert not os.path.exists(path)


def test_server_drops_bad_and_unauthorised_clients(tmp_path):
    path = str(tmp_path / "media.sock")
    got = []
    server = ipc.Server(path, lambda uid, message: got.append(message), authorize=lambda uid: False)
    server.start()
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
        try:
            sock.sendall(ipc.encode({"type": "snapshot"}))
        except OSError:
            pass
        assert spin_until(lambda: server.rejected == 1)
        sock.close()
        server.authorize = lambda uid: True
        bad = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bad.connect(path)
        bad.sendall(struct.pack(">I", ipc.MAX_FRAME + 10))
        assert spin_until(lambda: not server.clients)
        assert got == []
        bad.close()
    finally:
        server.stop()


# ---------------------------------------------------------------- hub

def snapshot_message(players, volume=None, active=None):
    return {"type": "snapshot", "v": 1, "players": players, "active": active,
            "volume": volume or {"available": True, "percent": 35, "muted": False, "backend": "pulse"}}


def test_hub_view_art_spectrum_and_stale():
    clock = [1000.0]
    changes = []
    h = hub.MediaHub(on_change=lambda: changes.append(1), clock=lambda: clock[0])
    assert h.view().players == [] and not h.view().connected
    h.on_message(1000, snapshot_message([dict(player(), art="cover1")], active="org.mpris.MediaPlayer2.spotify"))
    rgb = base64.b64encode(bytes([255, 0, 0]) * 4).decode()
    h.on_message(1000, {"type": "art", "id": "cover1", "w": 2, "h": 2, "rgb": rgb})
    h.on_message(1000, {"type": "spectrum", "bands": [0.5] * 24, "mono": 999.9})
    view = h.view()
    assert view.connected and view.volume["percent"] == 35
    assert view.art("cover1").getpixel((0, 0)) == (255, 0, 0)
    assert view.spectrum_bands(now=1000.0) == [0.5] * 24
    assert view.spectrum_bands(now=1010.0) is None
    assert changes
    h.on_message(1000, {"type": "nonsense"})
    assert h.invalid == 1
    clock[0] += hub.STALE_AFTER + 1          # agent silent (logout, crash)
    stale = h.view()
    assert stale.stale and stale.players == [] and not stale.volume["available"]


def test_hub_prefers_the_active_seat_user(monkeypatch):
    h = hub.MediaHub()
    h.on_message(1000, snapshot_message([player(title="Mine")]))
    h.on_message(1001, snapshot_message([player(title="Theirs")]))
    monkeypatch.setattr(ipc, "active_seat_uid", lambda *a: 1000)
    assert h.view().players[0]["title"] == "Mine"


def test_heartbeat_is_not_a_significant_change():
    h = hub.MediaHub()
    calls = []
    h.on_change = lambda: calls.append(1)
    h.on_message(1, snapshot_message([player()]))
    h.on_message(1, snapshot_message([player()]))
    assert len(calls) == 1


# ---------------------------------------------------------------- artwork

def png_bytes(size=(50, 30), color=(10, 200, 30), fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, fmt)
    return buffer.getvalue()


def test_remote_urls_reject_private_and_odd_targets():
    public = lambda host: True    # noqa: E731
    private = lambda host: False  # noqa: E731
    artwork.check_remote_url("https://i.scdn.co/image/abc", public)
    with pytest.raises(artwork.ArtError):
        artwork.check_remote_url("http://127.0.0.1:631/", private)
    with pytest.raises(artwork.ArtError):
        artwork.check_remote_url("ftp://x/y.png", public)
    with pytest.raises(artwork.ArtError):
        artwork.check_remote_url("https://user:pw@host/x.png", public)
    assert artwork._public_host("localhost") is False
    assert artwork._public_host("10.1.2.3") is False


def test_local_and_data_sources(tmp_path):
    path = tmp_path / "c.png"
    path.write_bytes(png_bytes())
    assert artwork.fetch(f"file://{path}") == path.read_bytes()
    with pytest.raises(artwork.ArtError):
        artwork.fetch(f"file://{tmp_path}")                       # a directory
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes()).decode()
    assert artwork.normalize(artwork.fetch(data_url)).size == (50, 30)
    with pytest.raises(artwork.ArtError):
        artwork.fetch("javascript:alert(1)")


def test_normalize_limits_and_formats():
    image = artwork.normalize(png_bytes((1000, 500)))
    assert max(image.size) == artwork.MAX_SIDE and image.mode == "RGB"
    with pytest.raises(artwork.ArtError):
        artwork.normalize(b"not an image")
    tiff = io.BytesIO()
    Image.new("RGB", (8, 8)).save(tiff, "TIFF")
    with pytest.raises(artwork.ArtError):
        artwork.normalize(tiff.getvalue())


def test_art_cache_and_message(tmp_path, monkeypatch):
    monkeypatch.setattr(artwork, "DISK_FILES", 3)
    cache = artwork.ArtCache(str(tmp_path))
    for index in range(5):
        cache.put(f"id{index}", Image.new("RGB", (8, 8), (index, 0, 0)))
    assert cache.usage()[0] == 3
    assert artwork.ArtCache(str(tmp_path)).get("id4").getpixel((0, 0)) == (4, 0, 0)
    message = artwork.to_message("id4", Image.new("RGB", (8, 6)))
    assert model.clean_art(message)[1:3] == (8, 6)


def test_loader_reports_failures(tmp_path):
    results = []
    loader = artwork.ArtLoader(lambda *args: results.append(args), cache=artwork.ArtCache(str(tmp_path)),
                               schedule=lambda func, *args: func(*args))
    good = tmp_path / "ok.png"
    good.write_bytes(png_bytes())
    loader.request(f"file://{good}")
    loader.request(f"file://{tmp_path}/missing.png")
    assert spin_until(lambda: len(results) == 2)
    by_ok = {bool(image): error for _id, image, error in results}
    assert by_ok[True] == "" and "cannot read" in by_ok[False]


# ---------------------------------------------------------------- volume parsers

PACTL_JSON = json.dumps([
    {"name": "alsa_output.usb-0d8c_USB_Sound_Device-00.analog-stereo", "description": "(null)", "mute": False,
     "volume": {"front-left": {"value": 12633, "value_percent": "19%"},
                "front-right": {"value": 13106, "value_percent": "20%"}}},
    {"name": "alsa_output.hdmi", "description": "HDMI", "mute": True,
     "volume": {"front-left": {"value": 98304, "value_percent": "150%"}}}])


def test_pactl_json_with_broken_descriptions():
    pytest.importorskip("gi")
    from bsmd.media import volume
    state = volume.parse_pactl_sinks(PACTL_JSON, "alsa_output.usb-0d8c_USB_Sound_Device-00.analog-stereo")
    assert state["percent"] == 20 and state["muted"] is False
    assert state["output"] == ""                    # "(null)" is never shown
    amplified = volume.parse_pactl_sinks(PACTL_JSON, "x", wanted="alsa_output.hdmi")
    assert amplified["percent"] == 150 and amplified["muted"] is True and amplified["output"] == "HDMI"
    text = "Sink #60\n\tName: alsa_output.usb-0d8c\n\tDescription: CM106 Estéreo analógico\n"
    assert volume.parse_pactl_descriptions(text) == {"alsa_output.usb-0d8c": "CM106 Estéreo analógico"}


def test_wpctl_and_amixer_parsers():
    pytest.importorskip("gi")
    from bsmd.media import volume
    assert volume.parse_wpctl("Volume: 0.35") == {"available": True, "percent": 35, "muted": False}
    assert volume.parse_wpctl("Volume: 1.20 [MUTED]")["muted"] is True
    assert volume.parse_wpctl_description('  * node.description = "Headset"') == "Headset"
    amixer = "  Front Left: Playback 12633 [19%] [off]\n  Front Right: Playback 13106 [20%] [off]"
    assert volume.parse_amixer(amixer) == {"available": True, "percent": 20, "muted": True}
    assert volume.parse_pactl_text("Volume: front-left: 42597 /  65% / -11 dB", "Mute: no")["percent"] == 65
    with pytest.raises(ValueError):
        volume.parse_wpctl("nothing")


# ---------------------------------------------------------------- spectrum

def test_spectrum_peaks_in_the_right_band():
    np = pytest.importorskip("numpy")
    from bsmd.media import spectrum
    t = np.arange(spectrum.CHUNK) / spectrum.RATE
    tone = (np.sin(2 * math.pi * 1000 * t) * 12000).astype(np.int16)
    levels = spectrum.compute_bands(tone)
    edges = np.geomspace(spectrum.LOW_HZ, spectrum.HIGH_HZ, spectrum.BANDS + 1)
    expected = int(np.searchsorted(edges, 1000) - 1)
    assert abs(int(np.argmax(levels)) - expected) <= 1
    silence = spectrum.compute_bands(np.zeros(spectrum.CHUNK, dtype=np.int16))
    assert max(silence) == 0.0


def test_pulse_backend_stop_does_not_respawn_pactl(monkeypatch):
    """Cancelling the ``pactl subscribe`` read on stop() used to look like a lost
    audio server and spawned a new pactl a moment later (one leaked per reload)."""
    from gi.repository import GLib
    scheduled = []
    monkeypatch.setattr(GLib, "timeout_add_seconds", lambda *args: scheduled.append(args) or 1)

    class CancelledStream:
        def read_line_finish_utf8(self, _result):
            raise GLib.Error("Operation was cancelled")

    from bsmd.media import volume
    backend = volume.PulseBackend(lambda: None)
    backend.stop()
    backend._on_line(CancelledStream(), None)
    assert scheduled == [] and backend.proc is None
    assert backend._restart() is False and backend.proc is None
