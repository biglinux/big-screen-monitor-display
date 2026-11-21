"""Tray apps (screen and DeepCool), their shared control layer and helpers.

The Qt tests run headless (QT_QPA_PLATFORM=offscreen) with PyQt6 or PyQt5 and
are skipped when neither binding is installed. Devices come from a fake service
status file, settings from a temporary file: nothing touches /etc, USB or the
desktop session.
"""

import json
import os
import subprocess
import sys
import time

import pytest

from bsmd import control, distro, settings
from conftest import APP_DIR

# ------------------------------------------------------------------ control layer


def test_set_global_clears_per_display_overrides():
    values = dict(settings.defaults(), displays={"usb-1": {"theme": "planet", "brightness": 30},
                                                 "usb-2": {"theme": "kojiro"}})
    result = control.set_global(values, "theme", "standard")
    assert result["theme"] == "standard"
    assert result["displays"] == {"usb-1": {"brightness": 30}}       # emptied entries are dropped
    assert values["displays"]["usb-1"]["theme"] == "planet"           # input untouched (copy)
    kept = control.set_global(values, "theme", "gkrellm", clear_overrides=False)
    assert kept["displays"]["usb-2"]["theme"] == "kojiro"


def test_set_display_overrides_and_removes():
    values = settings.defaults()
    one = control.set_display(values, "usb-1", "dc_main", "usage")
    assert one["displays"] == {"usb-1": {"dc_main": "usage"}}
    assert control.set_display(one, "usb-1", "dc_main", None)["displays"] == {}
    assert control.effective(one, "usb-1")["dc_main"] == "usage"


def test_save_settings_direct_when_bsm_config(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("BSM_CONFIG", str(path))
    ok, problems = control.save_settings(dict(settings.defaults(), brightness=999))
    assert ok and "brightness" in problems
    assert json.loads(path.read_text())["brightness"] == 100


def test_status_states(tmp_path, monkeypatch):
    status = tmp_path / "status.json"
    assert control.read_status(str(tmp_path / "missing.json")).state == "missing"
    status.write_text(json.dumps({"displays": [{"id": "usb-1", "source": {"profile": "deepcool_ak"}}]}))
    fresh = control.read_status(str(status))
    assert fresh.state == "running" and fresh.display("usb-1")
    old = time.time() - 60
    os.utime(status, (old, old))
    assert control.read_status(str(status)).state == "stale"


def test_display_kinds():
    assert control.is_deepcool({"source": {"profile": "deepcool_ag"}})
    assert not control.is_screen({"source": {"profile": "deepcool_ag"}})
    assert control.is_screen({"source": {"profile": "turing_rev_a"}, "capabilities": {"output": "raster"}})
    assert control.profile_of({"settings": {"profile": "auto"}}) == ""


def test_runtime_reexports_light_status_module():
    from bsmd import runtime, statusfile
    assert runtime.find_status_file is statusfile.find_status_file
    assert runtime.SYSTEM_STATUS == statusfile.SYSTEM_STATUS


def test_control_does_not_import_heavy_modules():
    code = ("import sys; sys.path.insert(0, %r); from bsmd import control; "
            "print(int(any(m in sys.modules for m in ('PIL', 'numpy', 'bsmd.themes', 'bsmd.runtime'))))" % APP_DIR)
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          check=True).stdout.strip() == "0"


# ------------------------------------------------------------------ distributions

OS_RELEASE = {
    "arch": ({"ID": "arch"}, "arch"),
    "manjaro": ({"ID": "manjaro", "ID_LIKE": "arch"}, "arch"),
    "biglinux": ({"ID": "biglinux", "ID_LIKE": "manjaro arch"}, "arch"),
    "tumbleweed": ({"ID": "opensuse-tumbleweed", "ID_LIKE": "opensuse suse"}, "suse"),
    "leap": ({"ID": "opensuse-leap", "ID_LIKE": "suse opensuse"}, "suse"),
    "regata": ({"ID": "regataos", "ID_LIKE": "opensuse suse"}, "suse"),
    "ubuntu": ({"ID": "ubuntu", "ID_LIKE": "debian"}, "debian"),
    "fedora": ({"ID": "fedora"}, "fedora"),
    "unknown": ({"ID": "plan9"}, ""),
}


@pytest.mark.parametrize("name", sorted(OS_RELEASE))
def test_distro_family(name):
    info, expected = OS_RELEASE[name]
    assert distro.family(info) == expected


def test_distro_reads_quoted_os_release(tmp_path):
    path = tmp_path / "os-release"
    path.write_text('NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n# c\n')
    info = distro.read_os_release(str(path))
    assert info["ID"] == "opensuse-tumbleweed" and distro.family(info) == "suse"


def test_distro_package_names_follow_python_version():
    suse = OS_RELEASE["tumbleweed"][0]
    assert distro.packages("psutil", suse, (3, 13)) == "python313-psutil"
    assert distro.packages("pyqt", suse, (3, 11)) == "python311-PyQt6"
    assert distro.packages("pyqt", OS_RELEASE["manjaro"][0]) == "python-pyqt6"
    assert distro.install_hint("pyqt", OS_RELEASE["ubuntu"][0]) == "sudo apt install python3-pyqt6"
    assert distro.install_hint("pyqt", OS_RELEASE["unknown"][0]) == ""


def test_install_script_knows_the_same_families():
    with open(os.path.join(APP_DIR, "..", "..", "..", "install-system.sh"), encoding="utf-8") as handle:
        script = handle.read()
    for members in distro.FAMILIES.values():
        assert members[0] in script


# ------------------------------------------------------------------ catalog


def test_catalog_matches_real_themes_and_schema():
    from bsmd import dashboard, themes
    from screentray import catalog
    assert [key for key, _name in catalog.STD_SCHEMES] == list(dashboard.SCHEMES)
    assert [name for _key, name in catalog.STD_SCHEMES] == [s["name"] for s in dashboard.SCHEMES.values()]
    assert {t.id for t in catalog.THEMES} == set(settings.THEME_IDS) == set(themes.REGISTRY)
    for theme in catalog.THEMES:
        assert set(theme.preferences) == set(themes.REGISTRY[theme.id].preferences), theme.id
        for variant in theme.variants:
            for key, value in variant.values.items():
                assert value in settings.SCHEMA[key][1], (key, value)
    assert [key for key, _n in catalog.ORIENTATIONS] == list(settings.ORIENTATIONS)
    for name in catalog.PLACEHOLDERS.values():
        assert os.path.exists(os.path.join(APP_DIR, "screentray", "thumbnails", name)), name


def test_theme_values_apply_the_clicked_variant():
    from screentray import catalog
    assert catalog.theme_values("standard", "neon") == {"theme": "standard", "std_scheme": "neon"}
    assert catalog.theme_values("kojiro") == {"theme": "kojiro"}           # layouts are never replaced


def test_thumbnail_renderer(tmp_path, monkeypatch):
    monkeypatch.setenv("BSM_CONFIG", str(tmp_path / "settings.json"))
    job = {"size": [480, 320], "out": str(tmp_path / "thumbs"),
           "items": [{"key": "a", "theme": "standard", "values": {"std_scheme": "nord"}},
                     {"key": "b", "theme": "planet", "values": {}}]}
    env = dict(os.environ, PYTHONPATH=APP_DIR)
    result = subprocess.run([sys.executable, "-m", "traykit.thumbs"], input=json.dumps(job), text=True,
                            capture_output=True, cwd=APP_DIR, env=env, timeout=120, check=False)
    assert result.stdout.split() == ["done", "a", "done", "b"], result.stderr
    from PIL import Image
    assert Image.open(tmp_path / "thumbs" / "a.png").size == (240, 160)


# ------------------------------------------------------------------ OpenRGB

LIST = """0: ASUS ROG STRIX B550-F GAMING (WI-FI)
  Type:           Motherboard
  Modes: [Direct] Off Static Breathing 'Spectrum Cycle' Rainbow
1: Corsair Vengeance Pro RGB
  Type: DRAM
  Modes: [Direct] Static 'Color Shift'
"""


def test_openrgb_parse():
    from deepcooltray import openrgb
    devices = openrgb.parse_devices(LIST)
    assert [(d.index, d.name, d.kind) for d in devices] == [(0, "ASUS ROG STRIX B550-F GAMING (WI-FI)",
                                                              "Motherboard"), (1, "Corsair Vengeance Pro RGB", "DRAM")]
    assert devices[0].mode(openrgb.RAINBOW_MODES) == "Rainbow"
    assert devices[1].mode(openrgb.RAINBOW_MODES) is None


def test_openrgb_touches_only_the_chosen_device(monkeypatch):
    from deepcooltray import openrgb
    calls = []

    def fake_run(args):
        calls.append(args)
        return (True, LIST) if args == ["--list-devices"] else (True, "")

    monkeypatch.setattr(openrgb, "_run", fake_run)
    assert openrgb.apply("#00ccff", "") == (False, "no OpenRGB device chosen")
    assert calls == []
    assert openrgb.apply("#00ccff", "Corsair Vengeance Pro RGB")[0]
    assert calls[-1] == ["--device", "1", "--mode", "Static", "--color", "00CCFF"]
    assert openrgb.apply("rainbow", "ASUS ROG STRIX B550-F GAMING (WI-FI)")[0]
    assert calls[-1] == ["--device", "0", "--mode", "Rainbow"]
    assert not openrgb.apply("rainbow", "Corsair Vengeance Pro RGB")[0]     # no such effect: nothing sent
    assert not openrgb.apply("#00ccff", "Gone device")[0]
    assert not openrgb.apply("not-a-colour", "Corsair Vengeance Pro RGB")[0]
    assert all("-sz" not in c and "--size" not in c and "--noautoconnect" not in c for c in calls)


# ------------------------------------------------------------------ autostart


def test_autostart_enable_disable_and_legacy(tmp_path, monkeypatch):
    from traykit import autostart
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    autostart.enable("big-screen-monitor-tray")
    text = (tmp_path / "autostart" / "big-screen-monitor-tray.desktop").read_text()
    assert "--autostart" in text and "Exec=" in text
    autostart.disable("big-screen-monitor-tray")
    assert not autostart.is_enabled("big-screen-monitor-tray")
    legacy = tmp_path / "autostart" / "deepcool-digital.desktop"
    legacy.write_text("[Desktop Entry]\nExec=/usr/bin/other-program\n")
    assert not autostart.migrate_legacy("big-screen-monitor-deepcool") and legacy.exists()   # not ours
    legacy.write_text("[Desktop Entry]\nExec=/usr/bin/deepcool-digital.sh\n")
    assert autostart.migrate_legacy("big-screen-monitor-deepcool")
    assert not legacy.exists() and autostart.is_enabled("big-screen-monitor-deepcool")


# ------------------------------------------------------------------ Qt apps

SCREEN = {"id": "usb-1-2", "name": "Turing 3.5\"", "state": "healthy", "source": {"profile": "turing_rev_a"},
          "capabilities": {"brightness": True, "output": "raster"}, "device": {"width": 480, "height": 320},
          "settings": {}}
AX206 = {"id": "usb-1-4", "name": "AX206 DPF", "state": "healthy", "source": {"profile": "ax206"},
         "capabilities": {"brightness": False, "output": "raster"}, "device": {"width": 800, "height": 480},
         "settings": {}}


def cooler(profile="deepcool_ak", alarm=False, temp=51.0, display_id="usb-1-3"):
    return {"id": display_id, "name": "AK620", "state": "healthy", "source": {"profile": profile},
            "capabilities": {"output": "segment"}, "device": {"model": "AK620 DIGITAL"}, "settings": {},
            "metrics": {"family": profile, "fields": {"temp": temp, "usage": 12.0}, "main": "temp",
                        "alarm": alarm, "fahrenheit": False, "missing": [], "updated": time.time()}}


@pytest.fixture
def qt_env(tmp_path, monkeypatch):
    qt = pytest.importorskip("traykit.qt")
    for key, value in {"BSM_CONFIG": tmp_path / "settings.json", "BSM_STATUS": tmp_path / "status.json",
                       "XDG_CONFIG_HOME": tmp_path / "cfg", "XDG_CACHE_HOME": tmp_path / "cache",
                       "XDG_STATE_HOME": tmp_path / "state", "QT_QPA_PLATFORM": "offscreen",
                       "XDG_CURRENT_DESKTOP": "KDE", "LANGUAGE": "en", "LC_ALL": "C.UTF-8"}.items():
        monkeypatch.setenv(key, str(value))
    app = qt.QApplication.instance() or qt.QApplication([])
    made = []

    class Env:
        path = tmp_path

        def status(self, displays, age=0):
            path = tmp_path / "status.json"
            path.write_text(json.dumps({"state": "healthy", "displays": displays}))
            stamp = time.time() - age
            os.utime(path, (stamp, stamp))

        def settings(self, **values):
            settings.save(dict(settings.defaults(), **values), str(tmp_path / "settings.json"))

        def saved(self):
            return json.loads((tmp_path / "settings.json").read_text())

        def wait(self, tray, seconds=3.0):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                app.processEvents()
                if not tray._busy:
                    break
                time.sleep(0.01)
            app.processEvents()

    env = Env()
    env.app = app
    env.qt = qt
    env.made = made
    yield env
    for tray in made:
        tray.shutdown()
        if tray.window is not None:
            tray.window.hide()
    from bsmd import i18n
    i18n.set_language("auto")


def make(env, cls, autostarted=False):
    tray = cls(env.app, autostarted=autostarted)
    env.made.append(tray)
    tray.start()
    return tray


def test_screen_tray_theme_clears_overrides(qt_env):
    from screentray.app import ScreenTray
    qt_env.status([SCREEN])
    qt_env.settings(displays={"usb-1-2": {"theme": "planet"}})
    tray = make(qt_env, ScreenTray)
    assert tray.window.cards["planet"].isChecked()              # the display's real theme is shown
    tray.choose_theme("standard", "dracula")
    qt_env.wait(tray)
    data = qt_env.saved()
    assert (data["theme"], data["std_scheme"]) == ("standard", "dracula") and data["displays"] == {}
    # Clicking a card keeps that theme's current variant.
    tray.choose_theme("old_computer", "plum")
    qt_env.wait(tray)
    tray.choose_theme("old_computer")
    qt_env.wait(tray)
    assert qt_env.saved()["oc_scheme"] == "plum"


def test_screen_tray_per_display_target_and_capabilities(qt_env):
    from screentray.app import ScreenTray
    qt_env.status([SCREEN, AX206])
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    assert tray.window.target_row.isVisibleTo(tray.window)
    tray.window.target.setCurrentIndex(tray.window.target.findData("usb-1-4"))
    assert tray.target_id == "usb-1-4"
    assert not tray.window.slider.isEnabled()                   # AX206 here: no backlight control
    tray.set_orientation("vertical")
    qt_env.wait(tray)
    data = qt_env.saved()
    assert data["displays"] == {"usb-1-4": {"orientation": "vertical"}} and data["orientation"] == "horizontal"
    tray.window.target.setCurrentIndex(tray.window.target.findData("usb-1-2"))
    assert tray.window.slider.isEnabled()


def test_screen_tray_brightness_power_and_hotplug(qt_env):
    from screentray.app import ScreenTray
    qt_env.status([SCREEN])
    qt_env.settings(brightness=80)
    tray = make(qt_env, ScreenTray)
    tray.toggle_power()
    qt_env.wait(tray)
    assert qt_env.saved()["brightness"] == 0
    tray.toggle_power()
    qt_env.wait(tray)
    assert qt_env.saved()["brightness"] == 80
    tray.set_brightness(3)                                       # below the minimum: clamped
    qt_env.wait(tray)
    assert qt_env.saved()["brightness"] == 10
    # Unplugged: the service drops the display; the tray follows without opening any device.
    qt_env.status([])
    tray.poll()
    assert tray._state_text()[1] == "No display connected" and tray._icon_state() == "off"
    qt_env.status([SCREEN])
    tray.poll()
    assert tray._icon_state() == "ok"
    qt_env.status([SCREEN], age=60)                              # service stopped refreshing
    tray.poll()
    assert tray._state_text()[0] == "error"


def test_screen_tray_menu_not_rebuilt_without_changes(qt_env):
    from screentray.app import ScreenTray
    qt_env.status([SCREEN])
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    first = tray.menu.actions()[0]
    tray.poll(force=True)
    assert tray.menu.actions()[0] is first


def test_deepcool_tray_per_family_options(qt_env):
    from deepcooltray.app import DeepCoolTray
    qt_env.status([cooler("deepcool_ag")])
    qt_env.settings()
    tray = make(qt_env, DeepCoolTray)
    assert [k for k, _l in tray.mode_choices(tray.family())] == ["theme", "temp", "usage", "auto"]
    assert not tray.window.unit_host.isEnabled()               # AG: Celsius only
    qt_env.status([cooler("deepcool_ls")])
    tray.poll()
    assert [k for k, _l in tray.mode_choices(tray.family())] == ["theme", "temp", "power", "auto"]
    qt_env.status([cooler("deepcool_ak_pro")])
    tray.poll()
    assert tray.mode_choices(tray.family()) == [] and not tray.window.alarm.isEnabled()
    assert "firmware" in tray.window.mode_note.text() or tray.window.alarm_note.text()


def test_deepcool_tray_writes_only_the_coolers_keys(qt_env):
    from deepcooltray.app import DeepCoolTray
    qt_env.status([SCREEN, cooler()])
    qt_env.settings(displays={"usb-1-2": {"led_color": "blue"}})
    tray = make(qt_env, DeepCoolTray)
    tray.set_mode("usage")
    tray.set_unit("f")
    tray.set_alarm(80)
    qt_env.wait(tray)
    data = qt_env.saved()
    assert data["displays"]["usb-1-3"] == {"dc_preset": "custom", "dc_main": "usage", "dc_temp_unit": "f",
                                           "dc_alarm_temp": 80}
    assert data["displays"]["usb-1-2"] == {"led_color": "blue"}  # the screen's LEDs are not touched
    tray.set_mode("theme")
    tray.set_alarm(0)
    qt_env.wait(tray)
    assert qt_env.saved()["displays"]["usb-1-3"] == {"dc_temp_unit": "f", "dc_alarm_temp": 80, "dc_alarm": False}


def test_deepcool_tray_never_invents_a_temperature(qt_env, monkeypatch):
    from deepcooltray import app as dc
    qt_env.status([cooler()])
    qt_env.settings()
    tray = make(qt_env, dc.DeepCoolTray)
    tray.cpu.path = None
    monkeypatch.setattr(dc.psutil, "sensors_temperatures", lambda: {}, raising=False)
    tray.poll()
    assert tray.temp_c is None and tray.window.temp.text() == "—"
    assert "35" not in tray.window.temp.text()


def test_deepcool_alarm_notifies_once(qt_env):
    from deepcooltray.app import DeepCoolTray
    qt_env.status([cooler()])
    qt_env.settings()
    tray = make(qt_env, DeepCoolTray)
    seen = []
    tray.notify = lambda title, message, error=False: seen.append(title)
    for _ in range(3):
        qt_env.status([cooler(alarm=True, temp=91)])
        tray.poll()
    assert seen == ["CPU temperature alarm"]
    qt_env.status([cooler(alarm=False)])
    tray.poll()
    qt_env.status([cooler(alarm=True, temp=92)])
    tray.poll()
    assert len(seen) == 2


def test_without_tray_host_window_is_shown_or_autostart_exits(qt_env, monkeypatch):
    from screentray.app import ScreenTray
    from traykit import base
    monkeypatch.setattr(base.QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    qt_env.status([SCREEN])
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    assert tray.tray is None and tray.window.isVisible()
    assert "AppIndicator" in tray.window.host_note.label.text()
    tray.window.hide()
    quits = []
    monkeypatch.setattr(base, "HOST_WAIT_S", 0)
    auto = ScreenTray(qt_env.app, autostarted=True)
    auto.app = type("A", (), {"quit": lambda self: quits.append(1)})()
    auto._host_deadline = 0
    auto.start()
    assert quits == [1] and not auto.window.isVisible()


def test_rapid_changes_never_lose_the_newest_value(qt_env, monkeypatch):
    """A slow first write must not land after the newer ones (writes are serialised)."""
    from deepcooltray.app import DeepCoolTray
    from traykit import base
    qt_env.status([cooler()])
    qt_env.settings()
    tray = make(qt_env, DeepCoolTray)
    real = base.control.save_settings
    calls = []

    def slow_first(values, helper=None):
        calls.append(values)
        if len(calls) == 1:
            time.sleep(0.4)
        return real(values, helper)

    monkeypatch.setattr(base.control, "save_settings", slow_first)
    tray.set_mode("usage")
    tray.set_unit("f")
    tray.set_alarm(75)
    qt_env.wait(tray, 5)
    assert len(calls) == 2                                  # the two later changes were merged into one write
    assert qt_env.saved()["displays"]["usb-1-3"] == {"dc_preset": "custom", "dc_main": "usage",
                                                     "dc_temp_unit": "f", "dc_alarm_temp": 75}


def test_failed_save_shows_the_saved_value_again(qt_env, monkeypatch):
    """No pkexec / authorization denied: the card goes back to the theme really in use."""
    from screentray.app import ScreenTray
    from traykit import base
    qt_env.status([SCREEN])
    qt_env.settings(theme="gkrellm")
    tray = make(qt_env, ScreenTray)
    seen = []
    tray.notify = lambda title, message, error=False: seen.append((title, message))
    monkeypatch.setattr(base.control, "save_settings",
                        lambda values, helper=None: (False, "[Errno 2] No such file or directory: 'pkexec'"))
    tray.choose_theme("planet")
    assert tray.window.cards["planet"].isChecked()          # optimistic while saving
    qt_env.wait(tray)
    assert tray.window.cards["gkrellm"].isChecked() and not tray.window.cards["planet"].isChecked()
    assert seen and seen[0][0] == "Could not save the settings"
