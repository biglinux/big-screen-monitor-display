"""Kojiro: model, layout, data, rendering, alerts, wallpapers and the managed store."""

import io
import json
import os
import struct
import zipfile
import zlib

import pytest
from PIL import Image

from bsmd import settings, telemetry, themes
from bsmd.kojiro import data, engine, layout, model, presets, store, wallpaper, widgets
from bsmd.themes import REGISTRY


@pytest.fixture(scope="module", autouse=True)
def stats():
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()


def theme():
    return engine.KojiroTheme(REGISTRY["kojiro"])


class DemoCtx:
    demo = True
    target_fps = 8.0


# ------------------------------------------------------------------ model

def test_presets_are_valid_and_complete():
    for name in presets.names():
        config = presets.build(name)
        clean, problems = model.validate(config)
        assert problems == [], (name, problems)
        assert clean["layouts"]["landscape"], name


def test_cyberpunk_has_every_required_widget():
    types = {w["type"] for w in presets.build("cyberpunk")["layouts"]["landscape"]}
    assert {"ram", "swap", "cpu", "gpu", "fan", "encdec", "disk", "net_down", "net_up", "clock", "distro"} <= types


def test_validation_repairs_damaged_config():
    config = presets.build("cyberpunk")
    config["wallpaper"]["source"] = "../../etc/shadow"
    config["wallpaper"]["zoom"] = 9000
    config["theme"]["speed"] = "fast"
    widget = config["layouts"]["landscape"][0]
    widget["color"] = "red; rm -rf /"
    widget["style"] = "nonexistent"
    widget["opts"]["show_values"] = "yes"
    config["layouts"]["landscape"].append({"id": "x", "type": "virus"})
    config["layouts"]["landscape"].append({"id": "../bad", "type": "cpu"})
    clean, problems = model.validate(config)
    assert clean["wallpaper"]["source"] == "builtin:cyberpunk"
    assert clean["wallpaper"]["zoom"] == 400
    assert clean["theme"]["speed"] == 100
    first = clean["layouts"]["landscape"][0]
    assert first["color"] == model.COMMON["color"][2] and first["style"] == "bar_segmented"
    assert first["opts"]["show_values"] is True
    assert all(w["id"] != "../bad" and w["type"] != "virus" for w in clean["layouts"]["landscape"])
    assert len(problems) >= 6


def test_widget_limit_and_duplicate_ids():
    widgets_ = [model.new_widget("cpu", f"cpu-{i}") for i in range(model.MAX_WIDGETS + 10)]
    widgets_.append(model.new_widget("cpu", "cpu-1"))
    clean, problems = model.validate({"layouts": {"landscape": widgets_}})
    assert len(clean["layouts"]["landscape"]) == model.MAX_WIDGETS
    assert problems


def test_settings_carry_kojiro_and_per_display_override():
    clean, problems = settings.validate({"theme": "kojiro", "kojiro": presets.build("matrix"),
                                         "displays": {"usb-1-1": {"kojiro": presets.build("glass")}}})
    assert not problems
    assert clean["kojiro"]["preset"] == "matrix"
    merged = settings.merged(clean, "usb-1-1")
    assert merged["kojiro"]["preset"] == "glass"
    assert settings.merged(clean, "usb-9-9")["kojiro"]["preset"] == "matrix"


def test_settings_store_keeps_last_valid_file(tmp_path):
    path = tmp_path / "settings.json"
    settings.save({"theme": "kojiro", "brightness": 33}, str(path))
    store_ = settings.SettingsStore(str(path))
    path.write_text('{"theme": "kojiro", "brightn')        # truncated by hand / disk full
    os.utime(path, (1, 1))
    store_.refresh()
    assert store_.get()["brightness"] == 33 and "kept the last valid settings" in store_.problems
    settings.save({"theme": "kojiro", "brightness": 33}, str(path))
    settings.save({"theme": "kojiro", "brightness": 44}, str(path))   # .bak = 33
    path.write_text("{broken")
    settings.save({"theme": "planet"}, str(path))                    # broken file never replaces a good .bak
    assert settings.restore_backup(str(path))["brightness"] == 33


def test_migrate_handles_future_and_missing_versions():
    assert model.migrate({"version": 99})["version"] == model.VERSION
    assert model.migrate(None)["version"] == model.VERSION


# ------------------------------------------------------------------ layout

@pytest.mark.parametrize("anchor", list(layout.ANCHOR_PARTS) + ["auto"])
@pytest.mark.parametrize("target", [(800, 480), (480, 320), (1920, 480), (480, 800), (160, 80)])
def test_pixels_roundtrip(anchor, target):
    widget = dict(model.new_widget("cpu", "cpu-1"), x=0.6, y=0.2, anchor=anchor)
    box = layout.to_pixels(widget, target, (800, 480))
    back = layout.from_pixels(widget, box, target, (800, 480))
    for key in ("x", "y", "w", "h"):
        assert back[key] == pytest.approx(widget[key], abs=1e-9)


def test_anchors_keep_corners_on_ultrawide():
    tr = dict(model.new_widget("disk", "disk-1"), x=0.72, y=0.04, anchor="tr")
    x, y, w, h = layout.to_pixels(tr, (1920, 480), (800, 480))
    assert x + w == pytest.approx(1920 - 0.04 * 800 * 1.0 - (1 - 0.72 - tr["w"] - 0.04) * 800, abs=1)
    assert w == pytest.approx(tr["w"] * 800)          # uniform scale: circles stay round
    centre = dict(tr, anchor="c", x=0.5 - tr["w"] / 2)
    cx = layout.to_pixels(centre, (1920, 480), (800, 480))
    assert cx[0] + cx[2] / 2 == pytest.approx(960)


def test_same_aspect_scales_proportionally():
    widget = dict(model.new_widget("cpu", "cpu-1"), x=0.3, y=0.3, anchor="br")
    small = layout.to_pixels(widget, (400, 240), (800, 480))
    big = layout.to_pixels(widget, (800, 480), (800, 480))
    assert small == pytest.approx(tuple(v / 2 for v in big))


def test_portrait_reflow_fits_and_keeps_order():
    landscape = presets.build("cyberpunk")["layouts"]["landscape"]
    portrait = layout.reflow_portrait(landscape, (800, 480), (480, 800))
    assert [w["id"] for w in portrait] == [w["id"] for w in landscape]
    for widget in portrait:
        assert -0.01 <= widget["x"] and widget["x"] + widget["w"] <= 1.01
        assert widget["y"] + widget["h"] <= 1.01


def test_align_distribute_snap():
    boxes = {"a": (10, 10, 50, 20), "b": (100, 40, 30, 30), "c": (300, 5, 40, 40)}
    left = layout.align(boxes, "left")
    assert {b[0] for b in left.values()} == {10}
    spread = layout.distribute(boxes, "h")
    gaps = sorted(spread.values())
    assert gaps[1][0] - (gaps[0][0] + gaps[0][2]) == pytest.approx(gaps[2][0] - (gaps[1][0] + gaps[1][2]))
    snapped, guides = layout.snap_box((397, 100, 20, 20), [], (800, 480), threshold=6)
    assert snapped[0] == 400 and ("v", 400) in guides     # left edge 3 px from the canvas centre line
    assert layout.overlaps((0, 0, 10, 10), [(5, 5, 10, 10), (20, 20, 5, 5)]) == [0]


# ------------------------------------------------------------------ data

def test_missing_hardware_is_unavailable_not_invented():
    widget = model.new_widget("fan", "fan-1")
    assert data.metric(widget, {"fans": []}).available is False
    assert data.metric(model.new_widget("encdec", "e"), {"gpus": [{"path": "x", "name": "Intel"}]}).available is False
    swap = data.metric(model.new_widget("swap", "s"), {"swap_total_mb": 0})
    assert swap.available is False and swap.extra.get("no_swap")
    assert data.metric(model.new_widget("gpu", "g"), {"gpus": []}).available is False
    disk = data.metric(dict(model.new_widget("disk", "d"), opts={"mount": "/nope"}), {"disks": {}})
    assert disk.available is False


def test_fan_percent_only_from_pwm():
    fan = data.metric(model.new_widget("fan", "f"), {"fans": [{"id": "c/fan1", "label": "fan1", "rpm": 1200,
                                                               "percent": None}]})
    assert fan.available and fan.big == "1200" and fan.extra["pwm"] is False


def test_gpu_auto_prefers_dedicated_card():
    stats = {"gpus": [{"path": "a", "name": "iGPU", "mem_total_mb": 512, "percent": 1},
                      {"path": "b", "name": "dGPU", "mem_total_mb": 16000, "percent": 50}]}
    metric = data.metric(dict(model.new_widget("gpu", "g"), opts={"index": -1, "show_name": True}), stats)
    assert ("name", "dGPU") in metric.lines
    metric = data.metric(dict(model.new_widget("gpu", "g"), opts={"index": 0, "show_name": True}), stats)
    assert ("name", "iGPU") in metric.lines


def test_temperature_limits_come_from_hardware():
    widget = model.new_widget("cpu", "c")
    metric = data.metric(widget, {"cpu_percent": 10, "cpu_temp_value": 60, "cpu_temp_crit": 100})
    assert metric.crit == 100 and metric.warn == 85
    metric = data.metric(widget, {"cpu_percent": 10, "cpu_temp_value": 60, "cpu_temp_crit": None})
    assert metric.crit == data.DEFAULT_TEMP_CRIT["cpu"]
    custom = data.metric(dict(widget, warn=70, crit=80), {"cpu_percent": 1, "cpu_temp_value": 60})
    assert (custom.warn, custom.crit) == (70, 80)


@pytest.mark.parametrize("unit,expected", [("Mbps", "8.0 Mbps"), ("Gbps", "0.01 Gbps"), ("MB/s", "1.0 MB/s"),
                                           ("KB/s", "977 KB/s"), ("auto_bytes", "977 KB/s")])
def test_rates_never_mix_bits_and_bytes(unit, expected):
    assert data.rate_text(8.0, unit) == expected


def test_needs_follow_visible_widgets():
    widgets_ = [model.new_widget("fan", "f"), dict(model.new_widget("disk", "d"), opts={"mount": "/home"}),
                dict(model.new_widget("processes", "p"), visible=False)]
    needs = data.needs(widgets_)
    assert needs["fans"] and needs["disks"] == {"/home"} and not needs["processes"]


# ------------------------------------------------------------------ alerts

def test_alert_hysteresis_and_cooldown():
    alert = engine.AlertState()
    assert alert.update(70, 80, 90, 3, 5, now=0) == 0
    assert alert.update(91, 80, 90, 3, 5, now=1) == 2
    assert alert.update(89, 80, 90, 3, 5, now=10) == 2         # within hysteresis
    assert alert.update(85, 80, 90, 3, 5, now=11) == 1         # clearly below crit, cooldown elapsed
    assert alert.update(70, 80, 90, 3, 5, now=12) == 1         # cooldown: no flapping
    assert alert.update(70, 80, 90, 3, 5, now=20) == 0


def test_alert_colour_is_gradual():
    base = (0, 255, 0)
    assert widgets.alert_color(base, 0) == base
    assert widgets.alert_color(base, 1) == widgets.WARN_RGB
    assert widgets.alert_color(base, 2) == widgets.CRIT_RGB
    assert engine.continuous_level(65, 80, 90) == 0
    assert 0 < engine.continuous_level(75, 80, 90) < 1


# ------------------------------------------------------------------ rendering

SIZES = [(800, 480), (480, 320), (1920, 480), (480, 800), (480, 480), (1280, 720), (160, 80), (80, 160)]


@pytest.mark.parametrize("preset", presets.names())
@pytest.mark.parametrize("size", SIZES)
def test_presets_render_everywhere(preset, size):
    image = theme().render(size[0], size[1], {"kojiro": presets.build(preset)}, DemoCtx())
    assert image.size == size and image.mode == "RGB"
    assert len(image.resize((24, 24)).getcolors(4096)) > 8


def test_every_widget_type_and_style_renders():
    for widget_type, spec in model.WIDGET_TYPES.items():
        for style in spec[1]:
            widget = dict(model.new_widget(widget_type, "w-1"), style=style)
            metric = data.metric(widget, data.demo_stats(0))
            layer, pad = widgets.render(widget, metric, (220, 120), {"font": "default"}, {})
            assert layer.mode == "RGBA" and layer.width >= 220 and pad[0] >= 0, (widget_type, style)
            assert layer.getbbox() is not None, (widget_type, style)


def test_unavailable_widgets_render_a_dash_or_hide():
    config = model.validate({"layouts": {"landscape": [
        dict(model.new_widget("fan", "fan-1"), x=0.1, y=0.1),
        dict(model.new_widget("fan", "fan-2"), x=0.5, y=0.1, hide_unavailable=True)]}})[0]
    kt = theme()
    kt.render(400, 240, {"kojiro": config}, type("C", (), {"demo": False, "telemetry": staticmethod(
        lambda: {"fans": []})})())


def test_zorder_later_widgets_on_top():
    red = dict(model.new_widget("frame", "a"), style="box", color="#FF0000", x=0.1, y=0.1, w=0.5, h=0.5, glow=0,
               shadow=False, bg="#FF0000", bg_opacity=100)
    blue = dict(red, id="b", color="#0000FF", bg="#0000FF")
    config = presets.build("minimal")
    config["layouts"]["landscape"] = [red, blue]
    config["theme"]["contrast_assist"] = "off"
    image = theme().render(800, 480, {"kojiro": config}, DemoCtx())
    assert image.getpixel((240, 160))[2] > 200            # blue drawn last
    config["layouts"]["landscape"] = [blue, red]
    image = theme().render(800, 480, {"kojiro": config}, DemoCtx())
    assert image.getpixel((240, 160))[0] > 200


def test_steady_frames_reuse_cached_layers():
    kt = theme()
    config = presets.build("cyberpunk")
    config["theme"]["animations"] = False
    kt.render(800, 480, {"kojiro": config}, DemoCtx())
    cached = len(kt.layers)
    kt.render(800, 480, {"kojiro": config}, DemoCtx())
    assert len(kt.layers) <= cached + 6        # only widgets whose values moved
    assert kt.render_ms < 500


def test_round_shape_and_micro_layout():
    micro = engine.micro_layout(presets.build("cyberpunk")["layouts"]["landscape"], (160, 80))
    assert 1 <= len(micro) <= 3 and micro[0]["type"] == "clock"


def test_kojiro_registered_and_selectable():
    assert "kojiro" in settings.THEME_IDS and "kojiro" in themes.REGISTRY
    created = themes.create("kojiro")
    assert isinstance(created, engine.KojiroTheme)


# ------------------------------------------------------------------ wallpapers

@pytest.mark.parametrize("name", model.BUILTIN_WALLPAPERS)
def test_builtin_wallpapers(name):
    image = wallpaper.render({"source": f"builtin:{name}"}, {}, (320, 200))
    assert image.size == (320, 200)


@pytest.mark.parametrize("fit", model.FITS)
def test_wallpaper_fits_and_adjustments(tmp_path, fit):
    png = _png_bytes((300, 100), (200, 50, 50))
    image_id = store.save_wallpaper(png, str(tmp_path))
    settings_ = {key: spec[2] for key, spec in model.WALLPAPER.items()}
    settings_.update({"source": f"user:{image_id}", "fit": fit, "brightness": 120, "blur": 2, "vignette": 40,
                      "protect": 50, "tint_strength": 20, "gamma": 120, "rotation": 90, "mirror": True})
    wallpaper.clear_cache()
    image = wallpaper.render(settings_, {"bg_effect": "scanlines"}, (200, 120), str(tmp_path))
    assert image.size == (200, 120)


def test_missing_user_wallpaper_falls_back(tmp_path):
    wallpaper.clear_cache()
    image = wallpaper.render({"source": "user:" + "0" * 32}, {}, (100, 60), str(tmp_path))
    assert image.size == (100, 60)


# ------------------------------------------------------------------ store

def _png_bytes(size=(64, 32), color=(10, 20, 30)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_check_png_rejects_garbage_and_tampering():
    good = _png_bytes()
    assert store.check_png(good) == (64, 32)
    with pytest.raises(store.StoreError):
        store.check_png(b"GIF89a" + good)
    tampered = bytearray(good)
    tampered[20] ^= 0xFF                                  # inside IHDR: CRC no longer matches
    with pytest.raises(store.StoreError):
        store.check_png(bytes(tampered))
    with pytest.raises(store.StoreError):
        store.check_png(good[:-12])                       # no IEND
    huge = store.PNG_SIGNATURE + struct.pack(">I4s", 13, b"IHDR") + struct.pack(">IIBBBBB", 9000, 9000, 8, 2, 0, 0, 0)
    huge += struct.pack(">I", zlib.crc32(huge[12:]) & 0xFFFFFFFF) + b"\x00\x00\x00\x00IEND\xaeB`\x82"
    with pytest.raises(store.StoreError):
        store.check_png(huge)


def test_save_wallpaper_dedupes_and_limits(tmp_path, monkeypatch):
    png = _png_bytes()
    first = store.save_wallpaper(png, str(tmp_path))
    assert store.save_wallpaper(png, str(tmp_path)) == first
    assert oct(os.stat(store.wallpaper_path(first, str(tmp_path))).st_mode & 0o777) == "0o644"
    monkeypatch.setattr(store, "MAX_WALLPAPERS", 1)
    with pytest.raises(store.StoreError):
        store.save_wallpaper(_png_bytes(color=(1, 2, 3)), str(tmp_path))
    store.delete_wallpaper(first, str(tmp_path))
    assert store.list_wallpapers(str(tmp_path)) == []
    with pytest.raises(store.StoreError):
        store.delete_wallpaper("../../etc/passwd", str(tmp_path))


def test_normalize_image_formats_and_limits(tmp_path):
    for fmt, mode in (("JPEG", "RGB"), ("WEBP", "RGB"), ("BMP", "RGB"), ("GIF", "P"), ("PNG", "RGBA")):
        path = tmp_path / f"image.{fmt.lower()}"
        Image.new(mode, (3000, 1000)).save(path, format=fmt)
        data_ = store.normalize_image(str(path))
        width, height = store.check_png(data_)
        assert max(width, height) <= store.MAX_LONG_SIDE
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"\x89PNG not really")
    with pytest.raises(store.StoreError):
        store.normalize_image(str(fake))
    text = tmp_path / "notes.jpg"
    text.write_text("hello")
    with pytest.raises(store.StoreError):
        store.normalize_image(str(text))


def test_user_presets_and_json_export(tmp_path):
    path = store.save_user_preset("Meu Layout", presets.build("glass"), str(tmp_path))
    listed = store.list_user_presets(str(tmp_path))
    assert listed and listed[0][0] == "Meu Layout"
    config = presets.build("glass")
    config["wallpaper"]["source"] = "user:" + "a" * 32
    out = tmp_path / "export.json"
    store.export_json(config, str(out), "Shared")
    name, clean, problems = store.load_preset_file(str(out))
    assert name == "Shared" and not problems
    assert clean["wallpaper"]["source"] == "builtin:cyberpunk"     # personal image not referenced
    store.delete_user_preset(path, str(tmp_path))
    with pytest.raises(store.StoreError):
        store.delete_user_preset("/etc/passwd", str(tmp_path))


def test_package_roundtrip_and_hostile_archives(tmp_path):
    wall_dir = tmp_path / "walls"
    image_id = store.save_wallpaper(_png_bytes(), str(wall_dir))
    config = presets.build("cyberpunk")
    config["wallpaper"]["source"] = f"user:{image_id}"
    package = tmp_path / "share.kojiro.zip"
    store.export_package(config, str(package), "Neon", _png_bytes((40, 24)), include_wallpaper=True,
                         store_dir=str(wall_dir))
    loaded = store.read_package(str(package))
    assert loaded["name"] == "Neon" and loaded["wallpaper"] and not loaded["problems"]
    no_wall = tmp_path / "private.kojiro.zip"
    store.export_package(config, str(no_wall), "Private", store_dir=str(wall_dir))
    assert store.read_package(str(no_wall))["wallpaper"] is None
    for name, payload in (("../../evil.sh", b"x"), ("config.json/../x", b"{}")):
        bad = tmp_path / "bad.zip"
        with zipfile.ZipFile(bad, "w") as archive:
            archive.writestr("config.json", json.dumps(presets.build("minimal")))
            archive.writestr(name, payload)
        with pytest.raises(store.StoreError):
            store.read_package(str(bad))
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("config.json", b" " * 400_000)
    with pytest.raises(store.StoreError):
        store.read_package(str(bomb))


def test_runtime_collects_only_what_kojiro_needs(tmp_path):
    from bsmd import runtime
    store_ = settings.SettingsStore(str(tmp_path / "s.json"))
    app = runtime.Runtime(store_, simulate=None, status_file=str(tmp_path / "run" / "status.json"),
                          state_directory=str(tmp_path / "state"), scan=lambda: [])

    class FakeSession:
        theme = type("T", (), {"info": REGISTRY["kojiro"], "needs": data.needs([
            model.new_widget("fan", "f"), dict(model.new_widget("disk", "d"), opts={"mount": "/data"})])})()

        @staticmethod
        def settings():
            return {"performance_profile": "fluid"}
    app.sessions["usb-1-1"] = FakeSession()
    app.wake_collector_needs()
    assert app.collector.want_fans and app.collector.want_disks == {"/data"} and not app.collector.want_addrs
    assert app.collector.interval == 0.5
