"""Standard, GKrellM, Planet and Old Computer at every size and option."""

import itertools
import shutil
from types import SimpleNamespace

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


def _fake_mounts(monkeypatch, mounts):
    parts = [SimpleNamespace(device=dev, mountpoint=mount, fstype=fstype, opts=opts)
             for dev, mount, fstype, opts in mounts]
    usage = SimpleNamespace(total=100 * 1024 ** 3, used=40 * 1024 ** 3, free=60 * 1024 ** 3, percent=40.0)
    monkeypatch.setattr(gkrellm.psutil, "disk_partitions", lambda all=False: parts)
    monkeypatch.setattr(gkrellm.psutil, "disk_usage", lambda mount: usage)
    gkrellm._CACHE.pop("partitions", None)


def test_gkrellm_partitions_on_btrfs_inside_the_service_sandbox(monkeypatch):
    """Regression: only "/" was listed, whatever "Partitions listed" said."""
    btrfs = "rw,compress=zstd:3,subvolid={},subvol=/{}"
    _fake_mounts(monkeypatch, [
        ("/dev/nvme0n1p2", "/", "btrfs", btrfs.format(256, "@")),
        ("/dev/nvme0n1p2", "/swapfile", "btrfs", btrfs.format(258, "@swapfile")),
        ("/dev/nvme0n1p1", "/boot/efi", "vfat", "rw"),
        ("/dev/nvme0n1p2", "/var/lib/private/big-screen-monitor-display", "btrfs", btrfs.format(256, "@")),
        ("/dev/nvme0n1p2", "/var/tmp", "btrfs", btrfs.format(256, "@")),
        ("/dev/nvme0n1p2", "/home", "btrfs", btrfs.format(257, "@home")),
        ("/dev/sda1", "/run/media/user/USB", "ext4", "rw"),
    ])
    assert [p[0] for p in gkrellm.partitions()] == ["/", "/home", "/run/media/user/USB", "/boot/efi"]
    assert [p[0] for p in gkrellm._fs_list({"gk_disk_count": "3"})] == ["/", "/home", "/run/media/user/USB"]


def test_gkrellm_disk_module_shrinks_instead_of_vanishing(monkeypatch):
    _fake_mounts(monkeypatch, [(f"/dev/sd{c}1", f"/mnt/{c}", "ext4", "rw") for c in "abcd"])
    drawn = []
    monkeypatch.setattr(gkrellm, "_fs_draw", lambda cv, x, y, w, stats, s: drawn.append(len(gkrellm._fs_list(s))))
    monkeypatch.setattr(gkrellm, "MODULES", [(k, m, gkrellm._fs_draw if k == "gk_show_disk" else d)
                                             for k, m, d in gkrellm.MODULES])
    only_disks = {key: key == "gk_show_disk" for key, _m, _d in gkrellm.MODULES if key != "clock"}
    render("gkrellm", (320, 140), gk_disk_count="4", gk_columns="1", **only_disks)
    assert drawn and 1 <= drawn[0] < 4


@pytest.mark.parametrize("profile,base,expected", [
    ("economy", 0.5, 1.0), ("auto", 0.5, 0.5), ("balanced", 0.5, 0.5), ("fluid", 0.5, 0.25),
    ("economy", 1.0, 1.0), ("fluid", 1.0, 0.5)])
def test_static_themes_follow_the_performance_profile(monkeypatch, profile, base, expected):
    monkeypatch.setattr(themes.time, "time", lambda: 1000.0)       # on a period boundary
    ctx = runtime.RenderContext(preview=True)
    ctx.target_fps = 15.0
    assert themes.static_interval({"performance_profile": profile}, ctx, base) == pytest.approx(expected + 0.01)
    ctx.target_fps = 2.0                                            # a slow panel still wins
    assert themes.static_interval({"performance_profile": profile}, ctx, base) == pytest.approx(
        max(expected, 0.5) + 0.01)


def test_link_stats_without_sockets(tmp_path):
    """psutil.net_if_stats() fails with EAFNOSUPPORT under RestrictAddressFamilies."""
    for name, flags, speed in (("enp3s0", "0x1003", "1000"), ("wlan0", "0x1002", None)):
        (tmp_path / name).mkdir()
        (tmp_path / name / "flags").write_text(flags + "\n")
        if speed:
            (tmp_path / name / "speed").write_text(speed + "\n")
    assert telemetry.link_stats(str(tmp_path)) == {"enp3s0": (True, 1000), "wlan0": (False, 0)}


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
