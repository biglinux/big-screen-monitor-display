"""Configuration window: real GTK sessions driven by tests/gui_driver.py, plus
the helper/persistence paths that need no display.

The window tests need a graphical session (DISPLAY or WAYLAND_DISPLAY),
PyGObject with libadwaita and dbus-run-session; they are skipped otherwise
(minimal CI images). Each one runs in its own private D-Bus session with a
temporary settings file and a fake service status, so the desktop, /etc and
the running service are never touched.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import time

import pytest

from bsmd import settings

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.abspath(os.path.join(HERE, "..", "usr", "share", "big-screen-monitor-display"))


def gui_available():
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False
    if not shutil.which("dbus-run-session"):
        return False
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


needs_gui = pytest.mark.skipif(not gui_available(), reason="needs a graphical session with GTK4/libadwaita")


def fake_status(path, displays, extra=None):
    status = {"version": "test", "state": "healthy", "uptime_s": 60, "stalled": False, "recoveries": 0,
              "device": displays[0]["device"] if displays else None, "displays": displays, "pending": [],
              "incidents": [], "stats": {"fps": 8.0, "target_fps": 8}, "process": {"cpu_percent": 1.0,
                                                                                       "rss_mb": 80}}
    status.update(extra or {})
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(status, handle)
    os.utime(path, (time.time(), time.time()))


def simulated(display_id, size):
    return {"id": display_id, "name": None, "connected": True, "state": "healthy", "state_since_s": 30,
            "device": {"model": f"Simulated {size[0]}x{size[1]}", "width": size[0], "height": size[1]},
            "source": {"profile": "simulated", "name": "Simulated panel", "transport": "memory"},
            "capabilities": {"brightness": True, "partial_update": True, "encoding": "rgb565"},
            "stats": {"fps": 8.0, "frames_sent": 10, "transfer_ms": 3.0}, "settings": {"theme": "standard"},
            "recoveries": 0}


def drive(tmp_path, scenario, displays=None, extra=None):
    config = tmp_path / "settings.json"
    settings.save(settings.defaults(), str(config))
    status = tmp_path / "status.json"
    if displays is not None:
        fake_status(status, displays, extra)
    env = dict(os.environ, BSM_CONFIG=str(config), BSM_STATUS=str(status), GSETTINGS_BACKEND="memory",
               XDG_CONFIG_HOME=str(tmp_path / "config"), XDG_CACHE_HOME=str(tmp_path / "cache"),
               XDG_STATE_HOME=str(tmp_path / "state"), XDG_RUNTIME_DIR=str(tmp_path / "run"), LANGUAGE="en",
               BSM_PREVIEW_ALWAYS="1", BSM_NO_TRAY_START="1", BSM_SYSFS=str(tmp_path / "sysfs"))
    os.makedirs(tmp_path / "run", mode=0o700, exist_ok=True)
    os.makedirs(tmp_path / "sysfs", exist_ok=True)       # no USB devices: the PC's own never leak in
    proc = subprocess.run(["dbus-run-session", "--", sys.executable, os.path.join(HERE, "gui_driver.py"), APP,
                           scenario], env=env, capture_output=True, text=True, timeout=240)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, proc.stdout[-2000:] + proc.stderr[-3000:]
    result = json.loads(line[7:])
    assert result["errors"] == [], "\n".join(result["errors"])
    return result["checks"]


@needs_gui
def test_window_flows(tmp_path):
    checks = drive(tmp_path, "main", [simulated("simulated", (480, 320)), simulated("simulated-1", (320, 480))])
    assert checks["sections"] == ["home", "displays", "themes", "kojiro", "big_media_player", "brother_away",
                                  "performance", "diagnostics", "preferences"]
    for name in ("all_sections_built", "unfocused_preview_still", "visible_preview_renders", "hidden_previews_idle",
                 "renderers_inactive",
                 "bar_hidden_initially", "bar_shown_after_edit", "apply_enabled", "applied_value_saved",
                 "bar_hidden_after_apply", "discard_restores", "brightness_synced", "restore_loads_defaults",
                 "restore_not_saved", "use_theme_selects", "search_filters", "story_queued", "skin_selected",
                 "media_options_page", "display_cards_include_status", "display_detail_open", "display_override",
                 "dashboard_selector_visible", "dashboard_state_hidden", "kojiro_active", "kojiro_inactive",
                 "profile_card_sets_value", "profile_card_reverted", "renderers_stopped", "status_timer_removed",
                 "tray_switches", "tray_switch_follows_window_open",
                 "tray_offer_follows_new_device", "tray_switch_is_a_choice", "tray_switch_off_while_starting"):
        assert checks[name] is True, name
    assert checks["collapsed_at_default_width"] is False
    assert checks["brightness_controls"] >= 2
    assert checks["theme_cards"] == sorted(["standard", "gkrellm", "planet", "old_computer", "brother_away",
                                            "kojiro", "big_media_player"])
    assert checks["theme_thumbnails"] == 7            # real renders, not placeholders
    assert checks["story_cards"] == 14
    assert checks["story_thumbnails"] == 14
    assert checks["skin_cards"] == 15


def cooler(display_id):
    return {"id": display_id, "name": None, "connected": True, "state": "healthy", "state_since_s": 12,
            "device": {"model": "AK620 DIGITAL PRO", "width": 0, "height": 0,
                       "details": {"family": "AK500/AK620 DIGITAL PRO", "hidraw": "/dev/hidraw9"}},
            "source": {"profile": "deepcool_ak_pro", "name": "AK500/AK620 DIGITAL PRO", "transport": "hid"},
            "capabilities": {"output": "telemetry", "display": "segment", "brightness": False,
                             "partial_update": False, "encoding": "metrics"},
            "stats": {"fps": 1.0, "frames_sent": 30, "transfer_ms": 0.4}, "settings": {"theme": "standard"},
            "recoveries": 0,
            "metrics": {"family": "deepcool_ak_pro", "fields": {"power": None, "temp": 61.5, "usage": 37.0,
                                                                 "freq": 4525.0},
                        "main": None, "alarm": False, "fahrenheit": False, "missing": ["power"],
                        "preset": "essentials", "source_theme": "standard", "updated": time.time(),
                        "reasons": {"power": "no permission to read the CPU energy counter (the package's udev "
                                             "rule grants it to the service)"},
                        "temp_source": "k10temp Tctl", "power_source": "intel-rapl:0",
                        "power_status": "permission"}}


@needs_gui
def test_deepcool_cooler_pages(tmp_path):
    checks = drive(tmp_path, "deepcool", [simulated("simulated", (480, 320)), cooler("usb-3-2")])
    for name in ("cooler_card", "cooler_card_thumbnail", "cooler_detail", "cooler_override", "cooler_diagnostics",
                 "panel_detail_still_raster", "dashboard_face"):
        assert checks[name] is True, name
    assert "Numeric display" in checks["cooler_card_text"] and "CPU Essentials" in checks["cooler_card_text"]
    assert checks["cooler_live_badge"] == "Live"
    assert "CPU temperature: 62 °C" in checks["cooler_values"] and "CPU power: —" in checks["cooler_values"]
    assert "permission" in checks["cooler_missing"] and "Sent as 0" in checks["cooler_missing"]
    assert checks["dashboard_resolution"].startswith("Numeric display")


@needs_gui
def test_service_stopped_states(tmp_path):
    checks = drive(tmp_path, "stopped", None)
    assert checks["state_card_visible"] is True
    assert "not running" in checks["state_card_title"]
    assert checks["sidebar_status"] == "Service stopped"
    assert "not running" in checks["diag_card_title"]


@needs_gui
def test_narrow_window_collapses(tmp_path):
    checks = drive(tmp_path, "narrow", [simulated("simulated", (480, 320))])
    if checks["width"] > 420:
        # Some compositors (wlmaker, the Big WindowMaker Wayland session) place new windows
        # at their own size: the narrow layout cannot be reached, so there is nothing to check.
        pytest.skip(f"the compositor ignored the requested 400 px width (got {checks['width']} px)")
    assert checks["collapsed"] is True
    assert checks["adaptive_narrow"] is True
    assert checks["min_width_fits"] is True


# ---------------------------------------------------------------- no display needed

@pytest.fixture
def config_gui(monkeypatch):
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
    except ValueError:
        pytest.skip("GTK4/libadwaita not installed")
    sys.path.insert(0, APP)
    import config_gui as module
    from bsmd import i18n
    i18n.set_language("en")
    yield module
    i18n.set_language("auto")


def fake_pkexec(tmp_path, monkeypatch, code, stdout=""):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "pkexec"
    script.write_text(f"#!/bin/sh\necho '{stdout}'\nexit {code}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    helper = tmp_path / "bsm-helper"
    helper.write_text("")


def test_polkit_cancel_is_reported(config_gui, tmp_path, monkeypatch):
    fake_pkexec(tmp_path, monkeypatch, 126)
    monkeypatch.setattr(config_gui, "HELPER", str(tmp_path / "bsm-helper"))
    ok, message = config_gui.run_helper(["service", "start"])
    assert not ok and message == "Authorization was cancelled or denied."


def test_helper_errors_and_success(config_gui, tmp_path, monkeypatch):
    fake_pkexec(tmp_path, monkeypatch, 0, json.dumps({"ok": True, "problems": ["brightness corrected"]}))
    monkeypatch.setattr(config_gui, "HELPER", str(tmp_path / "bsm-helper"))
    assert config_gui.run_helper(["apply-settings"], "{}") == (True, "brightness corrected")
    monkeypatch.setattr(config_gui, "HELPER", str(tmp_path / "missing"))
    ok, message = config_gui.run_helper(["recover"])
    assert not ok and "not installed" in message


def test_save_settings_validates_invalid_values(config_gui, tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    monkeypatch.setenv("BSM_CONFIG", str(path))
    values = dict(settings.defaults(), brightness=999, theme="no-such-theme", std_scheme=["bad"])
    ok, problems = config_gui.save_settings(values)
    assert ok and problems
    data = json.loads(path.read_text())
    assert data["brightness"] == 100 and data["theme"] == "standard" and data["std_scheme"] == "dark"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o644


def test_gui_preferences_are_per_user(config_gui, tmp_path, monkeypatch):
    from gui import preferences_page
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert preferences_page.load_gui_settings() == {}
    preferences_page.save_gui_settings({"style": "dark"})
    assert preferences_page.load_gui_settings() == {"style": "dark"}
    (tmp_path / "big-screen-monitor-display" / "gui.json").write_text("not json")
    assert preferences_page.load_gui_settings() == {}


def test_pairing_code_carries_the_vpn_address(config_gui):
    import urllib.parse
    from gui.android_page import pairing_url
    status = {"server_id": "a" * 32, "name": "PC", "fingerprint": "fp", "port": 7717,
              "addresses": [{"iface": "enp7s0", "address": "192.168.0.235", "kind": "lan"},
                            {"iface": "tailscale0", "address": "100.109.119.104", "kind": "vpn"},
                            {"iface": "enp10s0u4", "address": "192.168.7.1", "kind": "lan"},
                            {"iface": "zt0", "address": "172.29.133.40", "kind": "vpn"},
                            {"iface": "zt1", "address": "192.168.193.137", "kind": "vpn"}]}
    query = urllib.parse.parse_qs(urllib.parse.urlparse(pairing_url(status, "t" * 16, "s")).query)
    assert query["a"][0].split(",")[:2] == ["192.168.0.235", "100.109.119.104"]
    assert len(query["a"][0].split(",")) == 5


def test_add_android_option_opens_the_pairing_code(config_gui, monkeypatch):
    seen = {}

    class App:                       # the real one sets the GLib application name once per process
        def __init__(self, screenshot=None, page=None, add_android=False):
            seen.update(add=add_android, page=page)

        def run(self, argv):
            seen["argv"] = argv
            return 0
    monkeypatch.setattr(config_gui, "ConfigApp", App)
    assert config_gui.main(["prog", "--add-android"]) == 0
    assert seen == {"add": True, "page": None, "argv": ["prog"]}
    assert config_gui.main(["prog", "--page", "displays"]) == 0
    assert seen == {"add": False, "page": "displays", "argv": ["prog"]}


@pytest.mark.parametrize("libadwaita", ["1.6", "1.7+"])
def test_kojiro_inspector_builds_on_every_supported_libadwaita(config_gui, monkeypatch, libadwaita):
    """Adw.InlineViewSwitcher only exists from libadwaita 1.7; the package asks for 1.6."""
    # Gtk.init_check() can report success without a display and the widgets then
    # crash the whole run (segfault), so the environment is checked first.
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        pytest.skip("no display for GTK")
    import kojiro_page
    from gi.repository import Adw, Gtk
    if not Gtk.init_check():
        pytest.skip("no display for GTK")

    class Adw16:
        def __getattr__(self, name):
            if name.startswith("InlineViewSwitcher"):
                raise AttributeError(name)
            return getattr(Adw, name)
    if libadwaita == "1.6":
        monkeypatch.setattr(kojiro_page, "Adw", Adw16())
    page = kojiro_page.KojiroPage.__new__(kojiro_page.KojiroPage)
    page._refresh_advanced = lambda: None
    box = page._inspector()
    switcher = box.get_first_child()
    expected = "ViewSwitcher" if libadwaita == "1.6" else "InlineViewSwitcher"
    assert type(switcher).__name__ == expected
    assert page.inspector.get_pages().get_n_items() == 6


def test_theme_signature_follows_only_relevant_keys(config_gui):
    from bsmd import themes
    from gui.theme_gallery import theme_signature
    values = settings.defaults()
    info = themes.REGISTRY["planet"]
    base = theme_signature(values, info)
    assert theme_signature(dict(values, std_scheme="nord"), info) == base       # another theme's option
    assert theme_signature(dict(values, planet_accent="red"), info) != base


ANDROID_STATUS = {"android": {
    "ready": True, "listening": True, "network": True, "port": 7717, "error": None,
    "server_id": "0123456789abcdef0123456789abcdef", "name": "Test PC", "fingerprint": "A" * 43,
    "addresses": [{"iface": "eth0", "address": "192.168.1.20"}], "pairing_open": False,
    "requests": [{"request": "0011223344556677", "name": "Tablet", "model": "Lenovo Tab", "code": "123456",
                  "transport": "wifi", "address": "192.168.1.30", "expires_in_s": 90}],
    "paired": [{"display_id": "android-0123456789ab", "name": "Galaxy S24", "model": "SM-S921B",
                "manufacturer": "samsung", "paired_at": 1, "last_seen": time.time(), "last_transport": "wifi"}],
    "connected": [{"display_id": "android-0123456789ab", "transport": "wifi", "address": "192.168.1.31",
                   "in_use": True, "bytes_in": 10, "bytes_out": 2000}],
    "counters": {}}}


def android_display():
    entry = simulated("android-0123456789ab", (1280, 576))
    entry["settings"] = {"theme": "kojiro"}         # chosen on the phone (touch), not in settings.json
    entry.update(name="Galaxy S24", source={"profile": "android", "name": "Galaxy S24", "transport": "android"},
                 device={"driver": "android", "model": "samsung SM-S921B", "width": 1280, "height": 576,
                         "location": "wifi 192.168.1.31",
                         "details": {"android": "14", "app": "1.0.0", "screen": "2340x1080", "density_dpi": 450,
                                     "transport": "wifi", "address": "192.168.1.31", "tls": True}},
                 capabilities={"brightness": True, "partial_update": True, "encoding": "rgb888+zlib/jpeg",
                               "orientation": "device", "touch": "single"})
    return entry


@needs_gui
def test_android_in_my_displays(tmp_path):
    pytest.importorskip("qrcode")
    checks = drive(tmp_path, "android", [simulated("simulated", (480, 320)), android_display()], ANDROID_STATUS)
    assert checks["android_group"] is True and checks["android_card"] is True
    assert checks["android_card_title"] == "Galaxy S24"
    assert "Kojiro" in checks["android_card_subtitle"]        # the theme the phone really shows
    assert checks["android_request_rows"] == 2              # one request + one paired phone
    assert "192.168.1.20" in checks["android_state"]
    assert checks["android_approve_sent"] == ["android_approve"]
    assert checks["android_detail"] is True
    assert "Wi-Fi" in checks["android_connection"] and "TLS" in checks["android_protocol"]
    assert checks["android_qr"] is True and "192.168.1.20:7717" in checks["android_address"]
    assert checks["android_pair_open"] is True and checks["android_secret_not_in_status"] is True
    assert checks["android_pair_closed"] is True
    assert "releases/latest/download/big-screen-monitor-display.apk" in checks["android_steps"]
    assert 0 < checks["android_steps_width"] <= 560 - 48


def test_report_text_has_version_checks_and_journal(config_gui, monkeypatch, tmp_path):
    from bsmd import __version__
    monkeypatch.setattr(config_gui.diagnostics, "run_checks",
                        lambda: {"checks": [], "status": {"state": "healthy"}})
    monkeypatch.setattr(config_gui.diagnostics, "format_report", lambda report: "CHECKS")
    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="journal line\n")
    monkeypatch.setattr(config_gui.subprocess, "run", fake_run)
    text = config_gui.ConfigWindow._report_text(journal_lines=80)
    assert text.startswith(f"Big Screen Monitor Display {__version__}")
    assert "CHECKS" in text and '"state": "healthy"' in text and "journal line" in text
    assert calls[0][:5] == ["journalctl", "-u", config_gui.SERVICE_NAME, "-n", "80"]


def test_issue_links_point_to_the_project():
    from bsmd import ISSUES_NEW_URL, PROJECT_URL
    assert ISSUES_NEW_URL == PROJECT_URL + "/issues/new/choose"
    templates = os.path.join(HERE, "..", ".github", "ISSUE_TEMPLATE")
    assert {"1-hardware.yml", "2-bug.yml", "3-feature.yml", "config.yml"} <= set(os.listdir(templates))
