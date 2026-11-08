"""Big Media Player theme: every skin, size and state renders; nothing is invented."""

import base64
import time

import pytest
from PIL import Image

from bsmd import runtime, settings, telemetry, themes
from bsmd.bigmedia import BigMediaPlayerTheme, layout, logo_candidates, skins
from bsmd.media import hub, model

SIZES = [(480, 320), (320, 480), (320, 240), (800, 480), (160, 80), (80, 160), (1920, 480), (480, 480),
         (1280, 720)]


class Ctx(runtime.RenderContext):
    def __init__(self, view=None, preview=False):
        super().__init__(preview=preview)
        self.view = view

    def media(self):
        return self.view


def make_view(players, active=None, volume=None, art=None, spectrum=None):
    h = hub.MediaHub()
    h.on_message(1000, {"type": "snapshot", "v": 1, "players": players, "active": active,
                        "volume": volume or {"available": True, "percent": 35, "muted": False, "output": "Speakers",
                                             "backend": "pulse"}})
    if art:
        image = Image.new("RGB", (40, 40), (200, 40, 40))
        h.on_message(1000, {"type": "art", "id": art, "w": 40, "h": 40,
                            "rgb": base64.b64encode(image.tobytes()).decode()})
    if spectrum:
        h.on_message(1000, {"type": "spectrum", "bands": spectrum, "mono": time.monotonic()})
    return h.view()


def wire(bus="org.mpris.MediaPlayer2.spotify", status="Playing", title="A Song", length=200_000_000,
         position=50_000_000, **extra):
    data = {"bus": bus, "identity": bus.split(".")[3].title(), "status": status, "title": title, "artist": "An Artist",
            "album": "An Album", "length_us": length, "position_us": position, "position_mono": time.monotonic(),
            "rate": 1.0, "can": {k: True for k in model.CAPS}, "last_active_mono": time.monotonic(),
            "playing_since_mono": time.monotonic() - 10 if status == "Playing" else None}
    data.update(extra)
    return data


def values(**overrides):
    return dict(settings.defaults(), theme="big_media_player", **overrides)


def render(view, size=(480, 320), preview=False, theme=None, **overrides):
    ctx = Ctx(view, preview)
    theme = theme or themes.create("big_media_player", ctx)
    image = themes.render_for_panel(theme, size[0], size[1], values(**overrides), ctx)
    assert image.size == size and image.mode == "RGB"
    return image, theme


@pytest.fixture(scope="module", autouse=True)
def stats():
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()


def test_registry_and_settings_agree():
    assert "big_media_player" in themes.REGISTRY and "big_media_player" in settings.THEME_IDS
    assert tuple(settings.BMP_SKINS) == skins.SKIN_IDS == tuple(skins.SKINS)
    assert isinstance(themes.create("big_media_player"), BigMediaPlayerTheme)


@pytest.mark.parametrize("skin", skins.SKIN_IDS)
@pytest.mark.parametrize("size", SIZES)
def test_every_skin_every_size_playing(skin, size):
    view = make_view([wire(art="cover")], active="org.mpris.MediaPlayer2.spotify", art="cover")
    image, _theme = render(view, size, bmp_skin=skin)
    assert len(set(image.resize((32, 32)).getdata())) > 8          # not a blank frame


@pytest.mark.parametrize("skin", skins.SKIN_IDS)
def test_states_paused_no_art_live_and_no_media(skin):
    states = [
        make_view([wire(status="Paused")]),
        make_view([wire(length=None, position=None, title="Live radio")]),            # stream
        make_view([wire(can={k: False for k in model.CAPS})]),                         # read-only player
        make_view([], volume={"available": False}),                                    # nothing playing
        None,                                                                          # agent missing
    ]
    for view in states:
        for size in ((480, 320), (160, 80)):
            render(view, size, bmp_skin=skin)


def test_unknown_duration_is_never_invented():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    view = make_view([wire(length=None, position=None, title="Stream")])
    from bsmd.bigmedia import Frame
    d = Frame(theme, values(), time.monotonic())
    p = view.players[0]
    theme._fill_media(d, values(), view, view.snapshot, p, False, time.monotonic(), False)
    assert d.fraction is None and d.live
    from bsmd.i18n import _
    assert d.elapsed_text == "--:--" and d.total_text == _("LIVE")
    d2 = Frame(theme, values(), time.monotonic())
    theme._fill_media(d2, values(bmp_time_mode="remaining"), view, view.snapshot,
                      make_view([wire(position=50_000_000, length=200_000_000)]).players[0], False,
                      time.monotonic(), False)
    assert d2.total_text in ("-02:30", "-02:29")


def test_capabilities_reach_the_frame():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    from bsmd.bigmedia import Frame
    caps = dict({k: True for k in model.CAPS}, next=False)
    view = make_view([wire(can=caps)])
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(), view, view.snapshot, view.players[0], False, time.monotonic(), False)
    kinds = {kind: enabled for kind, enabled, _a in skins.get("bigamp").button_set(d)}
    assert kinds["next"] is False and kinds["pause"] is True


def test_system_volume_is_the_default_and_player_volume_is_labelled():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    from bsmd.bigmedia import Frame
    view = make_view([wire(volume=0.5)], volume={"available": True, "percent": 120, "muted": True,
                                                 "backend": "pulse"})
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(), view, view.snapshot, view.players[0], False, time.monotonic(), False)
    assert (d.vol_percent, d.vol_muted, d.vol_label, d.vol_scale) == (120, True, "SYS", 120)
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(bmp_volume_source="player"), view, view.snapshot, view.players[0], False,
                      time.monotonic(), False)
    assert (d.vol_percent, d.vol_label) == (50, "APP")


def test_preview_without_players_uses_labelled_demo_but_service_never_does():
    _img, theme = render(None, preview=True)
    snapshot = model.demo_snapshot()
    assert snapshot["players"][0]["identity"] == "DEMO" and "demo" in snapshot["players"][0]["title"]
    state, snap, demo = theme._media(Ctx(None, preview=False), values())
    assert snap is None and not demo
    state, snap, demo = theme._media(Ctx(None, preview=True), values(bmp_preview_demo=False))
    assert snap is None


@pytest.mark.parametrize("mode", ["screen", "last_art", "clock", "telemetry", "rest"])
def test_idle_modes(mode):
    view = make_view([wire(status="Paused")])
    ctx = Ctx(view)
    theme = themes.create("big_media_player", ctx)
    themes.render_for_panel(theme, 480, 320, values(bmp_idle_mode=mode, bmp_idle_after=5), ctx)
    theme.inactive_since = time.monotonic() - 10                   # paused for a while
    image = themes.render_for_panel(theme, 480, 320, values(bmp_idle_mode=mode, bmp_idle_after=5), ctx)
    if mode == "rest":
        assert max(max(px) for px in image.resize((40, 40)).getdata()) < 120


def test_idle_hands_over_to_another_theme_and_comes_back():
    view = make_view([])
    ctx = Ctx(view)
    theme = themes.create("big_media_player", ctx)
    settings_ = values(bmp_idle_mode="theme", bmp_idle_theme="standard")
    themes.render_for_panel(theme, 480, 320, settings_, ctx)
    assert theme.idle_theme is not None and theme.idle_theme.info.id == "standard"
    ctx.view = make_view([wire()])
    themes.render_for_panel(theme, 480, 320, settings_, ctx)
    assert theme.idle_theme is None
    assert settings_["theme"] == "big_media_player"                 # the preference itself never changes


def test_idle_theme_telemetry_needs_reach_the_collector():
    """The Standard theme shown as idle screen lists processes: the collector must
    sample them although the session theme is big_media_player."""
    ctx = Ctx(make_view([wire()]))
    theme = themes.create("big_media_player", ctx)
    themes.render_for_panel(theme, 480, 320, values(bmp_idle_mode="screen"), ctx)
    assert not theme.needs["processes"] and not theme.needs["sensors"]
    # Armed as soon as the idle mode is configured, before the panel switches over.
    themes.render_for_panel(theme, 480, 320, values(bmp_idle_mode="theme", bmp_idle_theme="standard"), ctx)
    assert theme.idle_theme is None and theme.needs["processes"]
    themes.render_for_panel(theme, 480, 320, values(bmp_idle_mode="theme", bmp_idle_theme="gkrellm"), ctx)
    assert theme.needs["processes"] and theme.needs["sensors"]
    themes.render_for_panel(theme, 480, 320, values(bmp_idle_mode="theme", bmp_idle_theme="planet"), ctx)
    assert not theme.needs["processes"]


def test_collector_resamples_processes_when_turned_back_on():
    collector = telemetry.Collector()
    collector.prime()
    collector.want_processes = False
    assert telemetry.SYSTEM_STATS["procs"] == []            # never a stale list from long ago
    collector.sample_once(1000.0)
    assert telemetry.SYSTEM_STATS["procs"] == []
    collector.want_processes = True
    collector.sample_once(1001.0)                            # at once, not up to 5 s later
    assert telemetry.SYSTEM_STATS["procs"]
    assert collector._last["processes"] == 1001.0 - 4        # CPU% baseline: resample 1 s later


@pytest.mark.parametrize("mode", ["auto", "always", "hidden", "intermittent", "alternate", "paused", "idle",
                                  "alerts"])
@pytest.mark.parametrize("position", ["bottom", "top", "overlay"])
def test_telemetry_modes_render(mode, position):
    render(make_view([wire()]), bmp_tele_mode=mode, bmp_tele_position=position)


def test_telemetry_visibility_rules():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    playing = model.clean_player(wire())
    paused = model.clean_player(wire(status="Paused"))
    now = time.monotonic()
    assert theme._tele_visible("hidden", values(), playing, False, now, 0) is None
    assert theme._tele_visible("always", values(), playing, False, now, 0) == "tele"
    assert theme._tele_visible("paused", values(), playing, False, now, 0) == "media"
    assert theme._tele_visible("paused", values(), paused, False, now, 0) == "tele"
    s = values(bmp_tele_every=30, bmp_tele_duration=8)
    assert theme._tele_visible("intermittent", s, playing, False, now, 1000 * 30 + 2) == "tele"
    assert theme._tele_visible("intermittent", s, playing, False, now, 1000 * 30 + 20) == "media"
    assert theme._alerts(values(bmp_tele_alert_cpu=90), {"cpu_percent": 95})
    assert not theme._alerts(values(), {"cpu_percent": 10, "cpu_temp_value": 40})


def test_telemetry_items_never_invent_sensors():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    items = theme._tele_items(values(), {"valid": True, "cpu_percent": 12.0, "cpu_temp_value": None,
                                         "ram_used_mb": 2048, "swap_total_mb": 0, "disk_percent": 40,
                                         "gpus": [{"path": None, "name": "GPU"}]}, 0)
    labels = {label for _i, label, _v, _a in items}
    assert labels == {"", "CPU", "RAM", "DISK"}                     # no swap device, no real GPU
    cpu = next(v for _i, label, v, _a in items if label == "CPU")
    assert "°C" not in cpu


def test_visualizer_labels_decorative_and_real():
    view = make_view([wire()], spectrum=[0.7] * 24)
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    from bsmd.bigmedia import Frame
    d = Frame(theme, values(), time.monotonic())
    theme._fill_bands(d, values(bmp_visualizer="spectrum"), view, view.players[0], time.monotonic())
    assert d.vis_label == "FFT" and d.bands == [0.7] * 24
    d = Frame(theme, values(), time.monotonic())
    theme._fill_bands(d, values(bmp_visualizer="decorative"), view, view.players[0], time.monotonic())
    assert d.vis_label == "DECO"
    paused = make_view([wire(status="Paused")]).players[0]
    theme._fill_bands(d, values(bmp_visualizer="decorative"), view, paused, time.monotonic())
    assert max(d.bands) < 0.1                                      # no motion without playback


@pytest.mark.parametrize("option", [dict(bmp_vinyl=True), dict(bmp_adaptive_colors=True),
                                    dict(bmp_art_background=True), dict(bmp_art_glow=True, bmp_art_frame="neon"),
                                    dict(bmp_art_shape="circle"), dict(bmp_layout="party"),
                                    dict(bmp_layout="info"), dict(bmp_layout="compact"),
                                    dict(bmp_layout="low_power"), dict(bmp_vis_style="led"),
                                    dict(bmp_vis_style="vu"), dict(bmp_vis_style="scope"),
                                    dict(bmp_text_size="large", bmp_art_size="large"),
                                    dict(bmp_logo="none"), dict(bmp_logo_style="name"),
                                    dict(bmp_show_output=True, bmp_show_percent=True),
                                    dict(bmp_show_controls=False, bmp_show_volume=False)])
def test_appearance_options(option):
    view = make_view([wire(art="c")], art="c")
    for skin in ("bigamp", "bigmediaplayer"):
        render(view, (480, 320), **dict(option, bmp_skin=skin))
        render(view, (320, 480), **dict(option, bmp_skin=skin))


def test_per_display_fixed_player_and_ignore():
    spotify = wire()
    vlc = wire("org.mpris.MediaPlayer2.vlc", status="Paused", title="Film")
    view = make_view([spotify, vlc], active=spotify["bus"])
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    now = time.monotonic()
    assert theme._choose(view.snapshot, values(), now)["title"] == "A Song"
    assert theme._choose(view.snapshot, values(bmp_player_mode="fixed", bmp_player_fixed="vlc"), now)["title"] == \
        "Film"
    assert theme._choose(view.snapshot, values(bmp_player_ignore="spotify"), now)["title"] == "Film"


def test_app_skin_mapping_and_night_skin():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    p = model.clean_player(wire("org.mpris.MediaPlayer2.firefox.instance_3"))
    assert theme._skin_id(values(bmp_app_skins="spotify=bigamp, firefox=bigmatch"), p, 0) == "bigmatch"
    assert theme._skin_id(values(bmp_app_skins="firefox=nonsense"), p, 0) == "bigamp"
    night = values(bmp_night=True, bmp_night_start=0, bmp_night_end=23, bmp_night_skin="bigx")
    assert theme._night(night, time.time()) in (True, False)
    assert theme._night(values(bmp_night=True, bmp_night_start=5, bmp_night_end=5), 0) is False


def test_frame_interval_is_static_when_nothing_moves(monkeypatch):
    view = make_view([wire(status="Paused", title="Short")])
    _img, theme = render(view, bmp_visualizer="off", bmp_marquee=False)
    assert theme.animating is False                      # wall-clock aligned static period
    assert theme.frame_interval(values(), Ctx(view)) > 0
    view = make_view([wire(title="A very long title that certainly needs to scroll across the panel " * 2)])
    _img, theme = render(view)
    assert theme.frame_interval(values(), Ctx(view)) <= 0.2
    assert theme.animating
    monkeypatch.setattr(themes.time, "time", lambda: 1000.0)       # on a period boundary
    assert theme.frame_interval(values(bmp_layout="low_power"), Ctx(view)) == pytest.approx(1.01)


def test_layout_areas_never_overlap_and_stay_inside():
    for size in SIZES:
        for skin_id in skins.SKIN_IDS:
            L = layout.compute(size[0], size[1], skins.SKINS[skin_id],
                               {"tele": "bottom", "vis": True, "controls": True, "volume": True})
            boxes = [b for b in (L.art, L.info, L.progress, L.buttons, L.volume, L.tele) if b]
            for box in boxes:
                assert 0 <= box[0] <= box[2] <= size[0] and 0 <= box[1] <= box[3] <= size[1], (size, skin_id, box)
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    overlap = min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1
                    assert not overlap, (size, skin_id, a, b)


def test_text_settings_are_validated():
    clean, problems = settings.validate({"bmp_player_ignore": "x" * 500, "bmp_player_fixed": " vlc ",
                                         "bmp_app_skins": "a\nb"})
    assert clean["bmp_player_ignore"] == "" and clean["bmp_player_fixed"] == "vlc"
    assert clean["bmp_app_skins"] == "" and len(problems) == 2
    per_display, _p = settings.validate({"displays": {"usb-1-2": {"theme": "big_media_player",
                                                                  "bmp_player_fixed": "spotify"}}})
    assert settings.merged(per_display, "usb-1-2")["bmp_player_fixed"] == "spotify"


def test_logo_candidates_follow_os_release():
    names = logo_candidates({"LOGO": "comm-menu", "ID": "bigcommunity", "NAME": "BigCommunity, based in BigLinux",
                             "ID_LIKE": "arch"})
    assert names[:3] == ["comm-menu", "bigcommunity", "distributor-logo-bigcommunity"]
    assert "biglinux" in names and "distributor-logo-arch" in names and names[-1] == "distributor-logo"


def test_render_cost_is_reasonable():
    view = make_view([wire(art="c")], art="c")
    ctx = Ctx(view)
    theme = themes.create("big_media_player", ctx)
    themes.render_for_panel(theme, 480, 320, values(), ctx)
    start = time.perf_counter()
    for _ in range(5):
        themes.render_for_panel(theme, 480, 320, values(), ctx)
    assert (time.perf_counter() - start) / 5 < 0.25        # generous: CI machines are slow
