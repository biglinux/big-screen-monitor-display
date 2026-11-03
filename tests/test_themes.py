"""Standard, GKrellM, Planet and Old Computer at every size and option."""

import itertools
import shutil

import pytest

from bsmd import dashboard, gkrellm, legacy_themes, runtime, settings, telemetry, themes

SIZES = [(320, 240), (480, 320), (800, 480), (240, 320), (320, 480), (480, 800), (1024, 600)]


@pytest.fixture(scope="module", autouse=True)
def sampled():
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()
    collector._sample_sensor_list()
    collector._sample_processes()


def render(theme, size, **options):
    values = settings.defaults()
    values.update(theme=theme, **options)
    values, problems = settings.validate(values)
    assert not problems
    image = themes.create(values["theme"], runtime.RenderContext(preview=True)).render(*size, values, None)
    assert image.size == size and image.mode == "RGB"
    return image


@pytest.mark.parametrize("theme", ["standard", "gkrellm", "planet", "old_computer"])
@pytest.mark.parametrize("size", SIZES)
def test_every_theme_at_every_size(theme, size):
    render(theme, size)


@pytest.mark.parametrize("scheme", list(dashboard.SCHEMES))
def test_standard_schemes(scheme):
    image = render("standard", (480, 320), std_scheme=scheme)
    assert image.getpixel((1, 1)) == dashboard.SCHEMES[scheme]["bg"]


@pytest.mark.parametrize("side,values,bars,size", list(itertools.product(
    ("processes", "graphs", "none"), ("absolute", "percent"), ("rounded", "flat", "segmented"),
    ((320, 240), (320, 480)))))
def test_standard_layout_options(side, values, bars, size):
    render("standard", size, std_side_panel=side, std_values=values, std_bar_style=bars)


def test_standard_with_everything_off_still_renders():
    off = {key: False for key, spec in settings.SCHEMA.items() if key.startswith("std_") and spec[0] == "bool"}
    render("standard", (480, 320), **off)
    render("standard", (320, 480), **off)


def test_fit_never_exceeds_width():
    font = themes.ui_font(14, bold=True)
    for width in (0, 5, 20, 60, 200):
        text = dashboard.fit("Radeon Vega Series very long marketing name", font, width)
        assert font.getlength(text) <= max(0, width)


def test_legacy_theme_ids_still_render():
    for old in ("dark", "light", "neon", "cyberpunk"):
        image = themes.create(old).render(480, 320, settings.defaults(), None)
        assert image.getpixel((1, 1)) == dashboard.SCHEMES[old]["bg"]


@pytest.mark.parametrize("columns", ["auto", "1", "2", "3", "4"])
def test_gkrellm_columns_and_sizes(columns):
    for size in ((320, 240), (800, 480)):
        render("gkrellm", size, gk_columns=columns, gk_text_size="large", gk_chart_height="large",
               gk_show_cores=True, gk_show_inet=True, gk_show_battery=True, gk_show_docker=True)


def test_gkrellm_meters_at_zero_percent(monkeypatch):
    """Regression: swap present but unused (0 %) drew an inverted bar and raised ValueError."""
    for key, value in {"swap_total_mb": 2048, "swap_used_mb": 0, "swap_percent": 0.0, "ram_percent": 0.0}.items():
        monkeypatch.setitem(telemetry.SYSTEM_STATS, key, value)
    for size in ((320, 240), (800, 480)):
        render("gkrellm", size)


def test_gkrellm_never_draws_invented_values():
    """The 3.x module showed fixed voltages when no sensor existed."""
    stats = {"sensors": [], "gpus": []}
    assert gkrellm._sys_rows(stats) == []
    assert all(value > 0 for _l, value in
               [(r[0], float(r[1].split()[0])) for r in gkrellm._sys_rows(
                   {"sensors": [("nct", "fan1", 0, "RPM"), ("nct", "fan2", 900, "RPM")], "gpus": []})])


@pytest.mark.parametrize("accent", ["blue", "green", "amber", "violet", "red"])
def test_planet_accents_keep_the_earth(accent):
    blue = render("planet", (800, 480))
    globe, (x, y), mask = legacy_themes._PLANET_LAST_GLOBE
    recoloured = render("planet", (800, 480), planet_accent=accent)
    centre = (x + globe.width // 2, y + globe.height // 2)
    assert recoloured.getpixel(centre) == blue.getpixel(centre)


def test_planet_options():
    render("planet", (800, 480), planet_show_paths=False, planet_show_moon=False, planet_night=False,
           planet_city_lights=False, planet_seconds=False)


def test_planet_no_fake_weather_or_volume():
    source = open(legacy_themes.__file__, encoding="utf-8").read()
    assert '"SUNNY / WIND 3 / 22°C", font_mono' not in source
    assert '"28%", 28' not in source


@pytest.mark.parametrize("scheme", ["classic", "slate", "amber", "plum"])
def test_old_computer_options_and_small_sizes(scheme):
    for size in ((240, 320), (320, 240), (480, 320)):
        render("old_computer", size, oc_scheme=scheme, oc_show_storage=True, oc_titlebar=False,
               oc_statusbar=False, oc_seconds=True)
        render("old_computer", size, oc_scheme=scheme, oc_show_gpu=False)


@pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="needs rsvg-convert (librsvg)")
def test_svg_icon_recolour_with_yellowish_colours():
    """Regression: '#ffff00' used to become '#ffff0000' and the icon vanished."""
    for colour in ((255, 255, 0), (255, 240, 120), (250, 204, 21)):
        icon = legacy_themes.get_svg_icon("cpu-symbolic.svg", 20, colour)
        assert icon is not None and icon.getbbox() is not None
