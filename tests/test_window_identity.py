"""Window identity: docks and task bars must find the launcher (and its icon) of every window.

Big WindowMaker (big-wm-appicons), GNOME Shell and KDE Plasma look up
"<Wayland app_id>.desktop" first; X11 docks use WM_CLASS / StartupWMClass.
See docs/windowmaker/icon-windowmaker.md.
"""

import configparser
import os
import re

import pytest

from bsmd import APP_ID, APPLICATION_ID, DESKTOP_FILE

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APPS = os.path.join(ROOT, "usr", "share", "applications")
ICONS = os.path.join(ROOT, "usr", "share", "icons", "hicolor", "scalable", "apps")
APP_DIR = os.path.join(ROOT, "usr", "share", "big-screen-monitor-display")


def entry(name):
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    with open(os.path.join(APPS, name), encoding="utf-8") as handle:
        parser.read_file(handle)
    return parser["Desktop Entry"]


def test_configuration_window_launcher_is_named_after_the_application_id():
    # GTK 4 publishes the GApplication id as the Wayland app_id.
    assert DESKTOP_FILE == f"{APPLICATION_ID}.desktop"
    assert os.path.exists(os.path.join(APPS, DESKTOP_FILE))
    assert not os.path.exists(os.path.join(APPS, f"{APP_ID}.desktop"))   # no second menu entry


def test_configuration_window_launcher_matches_x11_and_icon():
    desktop = entry(DESKTOP_FILE)
    assert desktop["StartupWMClass"] == APP_ID                          # WM_CLASS = prgname
    assert desktop["Icon"] == APP_ID
    assert os.path.exists(os.path.join(ICONS, f"{APP_ID}.svg"))


def test_gui_uses_the_shared_ids_and_sets_the_window_icon():
    with open(os.path.join(APP_DIR, "config_gui.py"), encoding="utf-8") as handle:
        source = handle.read()
    assert "application_id=APPLICATION_ID" in source
    assert "GLib.set_prgname(APP_ID)" in source
    # Without a default icon name GTK 4 sets no _NET_WM_ICON on X11 (Window Maker shows a generic icon).
    assert "Gtk.Window.set_default_icon_name(APP_ID)" in source
    assert not re.search(r'application_id="', source)


@pytest.mark.parametrize("app_id", ["big-screen-monitor-tray", "big-screen-monitor-deepcool"])
def test_tray_apps_desktop_file_matches_their_qt_identity(app_id):
    # Qt: setDesktopFileName(app_id) is the Wayland app_id; the launcher carries the same name.
    desktop = entry(f"{app_id}.desktop")
    assert desktop["StartupWMClass"] == app_id
    assert desktop["Icon"] == app_id
    with open(os.path.join(APP_DIR, "traykit", "base.py"), encoding="utf-8") as handle:
        assert "app.setDesktopFileName(app_cls.app_id)" in handle.read()


def test_installers_handle_the_renamed_launcher():
    with open(os.path.join(ROOT, "install-system.sh"), encoding="utf-8") as handle:
        install = handle.read()
    with open(os.path.join(ROOT, "uninstall-system.sh"), encoding="utf-8") as handle:
        uninstall = handle.read()
    assert "usr/share/applications/${PKGNAME}.desktop" in install          # old name removed on upgrade
    assert f"usr/share/applications/{DESKTOP_FILE}" in uninstall
