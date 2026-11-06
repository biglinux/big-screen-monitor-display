"""Big Media Player — Modern Collection: registry, every state and size, layout geometry,
palettes and contrast, animation levels, overlays, caches and regressions of the classic set."""

import time

import pytest
from PIL import Image

from bsmd import settings, themes
from bsmd.bigmedia import BigMediaPlayerTheme, Frame, layout, paint as P, skins
from bsmd.bigmedia.modern import base as B
from bsmd.media import model
from test_bigmedia import Ctx, make_view, render, values, wire

MODERN = skins.MODERN_IDS
SIZES = [(480, 320), (320, 480), (320, 240), (800, 480), (480, 800), (160, 80), (80, 160), (1920, 480),
         (480, 480), (1280, 400)]


@pytest.fixture(scope="module", autouse=True)
def stats():
    from bsmd import telemetry
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()


def playing(**extra):
    return make_view([wire(art="cover", **extra)], active="org.mpris.MediaPlayer2.spotify", art="cover")


# ---------------------------------------------------------------- registry

def test_fifteen_skins_in_two_collections():
    assert len(skins.CLASSIC_IDS) == 7 and len(MODERN) == 8 and len(skins.SKIN_IDS) == 15
    assert skins.SKIN_IDS == tuple(settings.BMP_SKINS) == tuple(skins.SKINS)
    assert settings.BMP_CLASSIC == skins.CLASSIC_IDS and settings.BMP_MODERN == MODERN
    assert {skins.SKINS[s].collection for s in skins.CLASSIC_IDS} == {"classic"}
    assert {skins.SKINS[s].collection for s in MODERN} == {"modern"}
    assert len({skins.SKINS[s].name for s in skins.SKIN_IDS}) == 15
    assert all(skins.SKINS[s].description for s in skins.SKIN_IDS)


def test_modern_skins_are_distinct_compositions_not_recolours():
    signature = set()
    for skin_id in MODERN:
        s = skins.SKINS[skin_id]
        signature.add((s.art_style, s.caption, s.disc > 0, tuple(r.name for r in s.rows),
                       tuple(r.name for r in s.footer), s.meta, s.tele_style, type(s).buttons.__qualname__))
    assert len(signature) == 8


def test_new_settings_are_validated():
    clean, problems = settings.validate({"bmp_skin": "big_stage", "bmp_palette": "nope", "bmp_modern_shadow": 900,
                                         "bmp_accent_color": "#ff8800", "bmp_animations": "fluid",
                                         "bmp_layout": "cinema", "bmp_night_skin": "big_pure",
                                         "bmp_pure_tone": "graphite"})
    assert clean["bmp_skin"] == "big_stage" and clean["bmp_palette"] == "skin"
    assert clean["bmp_modern_shadow"] == 100 and clean["bmp_accent_color"] == "#ff8800"
    assert clean["bmp_layout"] == "cinema" and clean["bmp_night_skin"] == "big_pure"
    assert len(problems) == 2
    # Old files keep working: nothing new is required and the classic default is unchanged.
    old, problems = settings.validate({"bmp_skin": "bigx", "bmp_layout": "party"})
    assert old["bmp_skin"] == "bigx" and not problems and settings.defaults()["bmp_skin"] == "bigamp"


# ---------------------------------------------------------------- rendering

@pytest.mark.parametrize("skin", MODERN)
@pytest.mark.parametrize("size", SIZES)
def test_every_modern_skin_every_size(skin, size):
    image, _theme = render(playing(), size, bmp_skin=skin)
    assert len(set(image.resize((32, 32)).getdata())) > 8


STATES = {
    "paused": lambda: make_view([wire(status="Paused")]),
    "stopped": lambda: make_view([wire(status="Stopped", title="")]),
    "no_player": lambda: make_view([], volume={"available": False}),
    "no_agent": lambda: None,
    "no_art": lambda: make_view([wire()]),
    "long": lambda: playing(title="An extraordinarily long title that never fits " * 3,
                            album="A very long album name, deluxe remastered anniversary edition " * 2),
    "unicode": lambda: playing(title="Обещай — 夜に駆ける — أغنية", artist="Ünïcødé Ärtist ✓",
                               album="Ελληνικά"),
    "live": lambda: playing(length=None, position=None, title="Live radio"),
    "readonly": lambda: playing(can={k: False for k in model.CAPS}),
    "muted": lambda: make_view([wire()], volume={"available": True, "percent": 40, "muted": True, "output": "HDMI",
                                                "backend": "pulse"}),
    "loud": lambda: make_view([wire(shuffle=True, loop="Track")],
                              volume={"available": True, "percent": 150, "muted": False, "output": "Headset",
                                      "backend": "wpctl"}),
    "browser": lambda: make_view([wire("org.mpris.MediaPlayer2.firefox.instance_1", artist="", album="")]),
}


@pytest.mark.parametrize("skin", MODERN)
@pytest.mark.parametrize("state", list(STATES))
def test_states(skin, state):
    for size in ((480, 320), (320, 480), (160, 80)):
        render(STATES[state](), size, bmp_skin=skin, bmp_volume_max=150, bmp_show_output=True)


@pytest.mark.parametrize("skin", MODERN)
@pytest.mark.parametrize("tele", [dict(bmp_tele_mode="hidden"), dict(bmp_tele_mode="always"),
                                  dict(bmp_tele_mode="always", bmp_tele_position="top"),
                                  dict(bmp_tele_mode="always", bmp_tele_position="overlay")])
def test_telemetry_positions(skin, tele):
    for size in ((480, 320), (320, 480), (1920, 480)):
        render(playing(), size, bmp_skin=skin, **tele)


def test_gpu_without_sensors_and_no_telemetry_data(monkeypatch):
    from bsmd import telemetry
    monkeypatch.setattr(telemetry, "snapshot", lambda: {"valid": True, "cpu_percent": 5.0, "cpu_temp_value": None,
                                                         "ram_used_mb": 1000, "swap_total_mb": 0,
                                                         "disk_percent": 20, "gpus": [{"path": None}]})
    for skin in MODERN:
        render(playing(), bmp_skin=skin, bmp_tele_mode="always")
    monkeypatch.setattr(telemetry, "snapshot", lambda: {"valid": False})
    for skin in MODERN:
        render(playing(), bmp_skin=skin, bmp_tele_mode="always")


OPTIONS = [dict(bmp_palette="cover"), dict(bmp_palette="custom", bmp_accent_color="#22cc88"),
           dict(bmp_palette="custom", bmp_accent_color="not-a-colour"), dict(bmp_palette="mono"),
           dict(bmp_palette="contrast"), dict(bmp_adaptive_colors=True), dict(bmp_art_background=True),
           dict(bmp_modern_radius="square"), dict(bmp_modern_radius="round"), dict(bmp_modern_shadow=0),
           dict(bmp_modern_texture=0), dict(bmp_modern_disc="show"), dict(bmp_modern_disc="hide"),
           dict(bmp_modern_font="dejavu"), dict(bmp_modern_font="system"), dict(bmp_animations="off"),
           dict(bmp_animations="fluid"), dict(bmp_layout="cinema"), dict(bmp_layout="party"),
           dict(bmp_layout="compact"), dict(bmp_layout="info"), dict(bmp_glow=False),
           dict(bmp_show_controls=False, bmp_show_volume=False), dict(bmp_vinyl=True),
           dict(bmp_art_shape="circle"), dict(bmp_art_frame="neon", bmp_art_glow=True),
           dict(bmp_text_size="large", bmp_art_size="large"), dict(bmp_logo="none"),
           dict(bmp_logo_style="name"), dict(bmp_visualizer="off"), dict(bmp_track_banner=True)]


@pytest.mark.parametrize("option", OPTIONS, ids=lambda o: ",".join(f"{k}={v}" for k, v in o.items()))
def test_customisation_options(option):
    for skin in MODERN:
        render(playing(), (480, 320), bmp_skin=skin, **option)
        render(playing(), (320, 480), bmp_skin=skin, **option)


@pytest.mark.parametrize("tone", ["white", "beige", "grey", "graphite"])
def test_pure_tones(tone):
    image, _t = render(playing(), bmp_skin="big_pure", bmp_pure_tone=tone)
    corner = image.getpixel((2, 2))
    assert (sum(corner) > 450) == (tone != "graphite")


@pytest.mark.parametrize("mode", ["clock", "telemetry", "rest", "screen", "last_art"])
def test_idle_screens(mode):
    for skin in MODERN:
        view = make_view([wire(status="Paused")])
        ctx = Ctx(view)
        theme = themes.create("big_media_player", ctx)
        s = values(bmp_skin=skin, bmp_idle_mode=mode, bmp_idle_after=5)
        themes.render_for_panel(theme, 480, 320, s, ctx)
        theme.inactive_since = time.monotonic() - 10
        themes.render_for_panel(theme, 480, 320, s, ctx)


# ---------------------------------------------------------------- geometry

AREAS = ("art", "info", "progress", "times", "buttons", "volume", "vis")
EXTRAS = ("eyebrow", "chip", "chip_volume", "header", "caption")


def _boxes(L):
    boxes = {name: getattr(L, name) for name in AREAS if getattr(L, name)}
    boxes.update({name: L.extras[name] for name in EXTRAS if L.extras.get(name)})
    if L.extras.get("caption"):
        boxes.pop("info", None)                     # the caption is the info area
    if L.tele and not L.tele_overlay:
        boxes["tele"] = L.tele
    return boxes


def _overlap(a, b):
    return min(a[2], b[2]) - max(a[0], b[0]) > 1 and min(a[3], b[3]) - max(a[1], b[1]) > 1


@pytest.mark.parametrize("skin", MODERN)
@pytest.mark.parametrize("tele", ["bottom", "top", None])
def test_layout_inside_without_overlap_and_readable(skin, tele):
    s = skins.SKINS[skin]
    for size in SIZES:
        if layout.is_micro(*size):
            continue
        for variant in ("full", "compact", "party", "info", "cinema"):
            L = s.compute_layout(size[0], size[1], {"tele": tele, "vis": True, "controls": True, "volume": True,
                                                    "variant": variant, "badge_w": 30})
            boxes = _boxes(L)
            for name, box in boxes.items():
                assert 0 <= box[0] <= box[2] <= size[0] and 0 <= box[1] <= box[3] <= size[1], (size, name, box)
            names = list(boxes)
            for i, a in enumerate(names):
                for b in names[i + 1:]:
                    if {a, b} == {"progress", "times"} and L.extras.get("times_below") is None and \
                            L.extras.get("times_inline") is None:
                        continue
                    assert not _overlap(boxes[a], boxes[b]), (skin, size, variant, a, boxes[a], b, boxes[b])
            assert L.font >= 10                                        # never below a readable size
            assert L.progress is not None                              # the essentials never disappear
            if s.art_style != "bleed" and variant != "cinema":
                assert abs(layout_mod_w(L.art) - layout_mod_h(L.art)) <= 1        # covers are never deformed
            if L.extras.get("badge"):
                for name in ("info", "eyebrow", "header"):
                    box = boxes.get(name)
                    if box and name != "info":
                        assert not _overlap(box, L.extras["badge"]), (skin, size, name)


def layout_mod_w(box):
    return box[2] - box[0]


def layout_mod_h(box):
    return box[3] - box[1]


# ---------------------------------------------------------------- palettes

@pytest.mark.parametrize("skin", MODERN)
@pytest.mark.parametrize("mode", ["skin", "cover", "custom", "mono", "contrast"])
def test_palette_text_contrast(skin, mode):
    s = skins.SKINS[skin]
    for cover in ((255, 240, 0), (250, 250, 250), (10, 10, 10), (200, 20, 160)):
        image = Image.new("RGB", (32, 32), cover)
        pal = s.palette(mode, (255, 255, 0) if mode == "custom" else None, B.cover_colors(image), "white")
        assert P.contrast(pal["text"], pal["bg"]) >= 7 - 0.01
        assert P.contrast(pal["text2"], pal["bg"]) >= 4.5 - 0.01
        for key in ("lcd_bg", "lcd_fg", "lcd_hi", "fill", "tele_bg", "body", "stops", "mute"):
            assert key in pal


def test_cover_palette_is_computed_once_per_cover():
    view = playing()
    ctx = Ctx(view)
    theme = themes.create("big_media_player", ctx)
    calls = []
    real = B.cover_colors
    B.cover_colors = lambda image: calls.append(1) or real(image)
    try:
        for _ in range(4):
            themes.render_for_panel(theme, 480, 320, values(bmp_skin="big_flow", bmp_palette="cover"), ctx)
    finally:
        B.cover_colors = real
    assert len(calls) == 1 and len(theme.cover_palettes) == 1


def test_parse_hex():
    assert B.parse_hex("#A0b1C2") == (160, 177, 194) and B.parse_hex("a0b1c2") == (160, 177, 194)
    assert B.parse_hex("#12") is None and B.parse_hex("") is None and B.parse_hex(None) is None


# ---------------------------------------------------------------- functional parity

def test_same_frame_data_for_every_skin():
    """The look changes, the data does not: capabilities, times and volume are shared."""
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    caps = dict({k: True for k in model.CAPS}, next=False)
    view = make_view([wire(can=caps, shuffle=True, loop="Playlist")],
                     volume={"available": True, "percent": 120, "muted": False, "output": "USB DAC",
                             "backend": "pulse"})
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(bmp_show_output=True), view, view.snapshot, view.players[0], False,
                      time.monotonic(), False)
    assert d.output == "USB DAC" and d.app == "Spotify" and d.remaining_text.startswith("-")
    for skin_id in MODERN:
        d.pal = skins.SKINS[skin_id].palette()
        items = {kind: (enabled, role) for kind, enabled, _a, role in skins.SKINS[skin_id].transport(d)}
        nxt = skins.SKINS[skin_id].next_glyph
        assert items[nxt] == (False, "side") and items["pause"] == (True, "main")
        assert items["shuffle"][1] == "toggle" and items["repeat"][1] == "toggle"


def test_toggles_only_when_the_player_reports_them():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    view = make_view([wire()])                             # no Shuffle/LoopStatus in the wire data
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(), view, view.snapshot, view.players[0], False, time.monotonic(), False)
    for skin_id in MODERN:
        kinds = [kind for kind, *_r in skins.SKINS[skin_id].transport(d)]
        assert "shuffle" not in kinds and "repeat" not in kinds


def test_output_name_is_never_invented():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    view = make_view([wire()], volume={"available": True, "percent": 30, "muted": False, "backend": "pulse"})
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(bmp_show_output=True), view, view.snapshot, view.players[0], False,
                      time.monotonic(), False)
    assert d.output == ""
    d = Frame(theme, values(), time.monotonic())
    theme._fill_media(d, values(bmp_show_output=False), playing(), playing().snapshot, playing().players[0], False,
                      time.monotonic(), False)
    assert d.output == ""


def test_per_app_and_night_mapping_accept_modern_ids():
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    p = model.clean_player(wire("org.mpris.MediaPlayer2.spotify"))
    assert theme._skin_id(values(bmp_app_skins="spotify=big_flow, vlc=big_ember"), p, 0) == "big_flow"
    s = values(bmp_night=True, bmp_night_start=0, bmp_night_end=0, bmp_night_skin="big_lounge")
    assert theme._skin_id(s, p, 0) == "bigamp"                    # start == end: never night


# ---------------------------------------------------------------- motion, overlays, caches

def test_animation_levels_drive_the_frame_rate(monkeypatch):
    view = playing()
    ctx = Ctx(view)
    ctx.target_fps = 30
    theme = themes.create("big_media_player", ctx)
    s = values(bmp_skin="big_vinyl", bmp_visualizer="off", bmp_marquee=False)
    themes.render_for_panel(theme, 480, 320, s, ctx)
    assert theme.animating                                    # the record turns while playing
    assert theme.frame_interval(s, ctx) == pytest.approx(0.1)
    assert theme.frame_interval(dict(s, bmp_animations="fluid"), ctx) == pytest.approx(0.05)
    assert theme.frame_interval(dict(s, bmp_animations="economy"), ctx) == pytest.approx(0.25)
    off = dict(s, bmp_animations="off")
    theme2 = themes.create("big_media_player", ctx)
    themes.render_for_panel(theme2, 480, 320, off, ctx)
    monkeypatch.setattr(themes.time, "time", lambda: 1000.0)           # on a static-period boundary
    assert not theme2.animating and theme2.frame_interval(off, ctx) >= 0.5
    assert BigMediaPlayerTheme.motion(values(performance_profile="economy")) == "off"     # 4.3 behaviour
    assert BigMediaPlayerTheme.motion(values(bmp_layout="low_power", bmp_animations="fluid")) == "off"


def test_paused_record_is_still():
    view = make_view([wire(status="Paused", title="Short")])
    _img, theme = render(view, bmp_skin="big_groove", bmp_visualizer="off", bmp_marquee=False)
    assert theme.animating is False


def test_volume_osd_appears_after_a_change_and_goes_away():
    ctx = Ctx(make_view([wire()]))
    theme = themes.create("big_media_player", ctx)
    s = values(bmp_skin="big_lounge", bmp_tele_mode="hidden")
    first = themes.render_for_panel(theme, 480, 320, s, ctx)
    assert theme._vol_changed < 0
    ctx.view = make_view([wire()], volume={"available": True, "percent": 80, "muted": False, "backend": "pulse"})
    shown = themes.render_for_panel(theme, 480, 320, s, ctx)
    assert time.monotonic() - theme._vol_changed < 1
    centre = (240, 160)
    assert shown.getpixel(centre) != first.getpixel(centre)
    theme._vol_changed -= 10
    themes.render_for_panel(theme, 480, 320, dict(s, bmp_volume_osd="off"), ctx)


def test_volume_osd_can_include_classic_skins_but_not_by_default():
    ctx = Ctx(make_view([wire()]))
    theme = themes.create("big_media_player", ctx)
    themes.render_for_panel(theme, 480, 320, values(bmp_skin="bigamp"), ctx)
    ctx.view = make_view([wire()], volume={"available": True, "percent": 90, "muted": False, "backend": "pulse"})
    themes.render_for_panel(theme, 480, 320, values(bmp_skin="bigamp", bmp_volume_osd="all"), ctx)


def test_caches_stay_bounded():
    ctx = Ctx(None)
    theme = themes.create("big_media_player", ctx)
    for i in range(40):
        ctx.view = make_view([wire(title=f"Track {i}", art=f"a{i}")], art=f"a{i}")
        for skin in MODERN:
            themes.render_for_panel(theme, 320 + i, 240, values(bmp_skin=skin, bmp_palette="cover",
                                                                bmp_visualizer="decorative"), ctx)
    assert B.cache_size() <= B.CACHE_SIZE
    assert len(theme.palettes) <= 16 and len(theme.cover_palettes) <= 16 and len(theme.shapes) <= 8
    assert len(theme.chromes) <= 6 and len(theme.art_tiles) <= 40


def test_decorative_waveform_is_labelled_and_stable_per_track():
    a, b = B.track_shape("x|Song|Artist"), B.track_shape("x|Song|Artist")
    assert a == b and B.track_shape("x|Other|Artist") != a
    view = playing()
    theme = BigMediaPlayerTheme(themes.REGISTRY["big_media_player"])
    d = Frame(theme, values(), time.monotonic())
    theme._fill_bands(d, values(bmp_visualizer="decorative"), view, view.players[0], time.monotonic())
    assert d.vis_label == "DECO"


def test_modern_render_cost_is_reasonable():
    for skin in MODERN:
        view = playing()
        ctx = Ctx(view)
        theme = themes.create("big_media_player", ctx)
        s = values(bmp_skin=skin)
        themes.render_for_panel(theme, 480, 320, s, ctx)
        start = time.perf_counter()
        for _ in range(5):
            themes.render_for_panel(theme, 480, 320, s, ctx)
        assert (time.perf_counter() - start) / 5 < 0.25, skin
