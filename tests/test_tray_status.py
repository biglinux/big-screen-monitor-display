"""Tray of the USB screens: symbolic icon, four-colour status dot and the display that receives the changes."""

import os
import re

from conftest import APP_DIR
from test_trays import AX206, SCREEN, make, qt_env  # noqa: F401 (qt_env is a fixture)


# ------------------------------------------------------------------ rules (no Qt)

def test_display_states_and_dot_rules():
    from screentray import states as S
    healthy = {"id": "a", "name": "A", "state": "healthy", "capabilities": {"brightness": True}}
    assert S.classify(healthy).state == S.CONNECTED and S.classify(healthy).colour == S.GREEN
    assert S.classify(healthy, {"brightness": 0}).state == S.SWITCHED_OFF                   # backlight off: red
    assert S.classify(dict(healthy, capabilities={}), {"brightness": 0}).state == S.CONNECTED  # cannot be off
    assert S.classify(dict(healthy, enabled=False)).state == S.SWITCHED_OFF
    for link, state in (("degraded", S.PROBLEM), ("recovering", S.RECONNECTING), ("retrying", S.RECONNECTING),
                        ("starting", S.RECONNECTING), ("disconnected", S.DISCONNECTED),
                        ("failed", S.DISCONNECTED)):
        assert S.classify(dict(healthy, state=link)).state == state, link
    assert S.classify(dict(healthy, state="retrying", attention="replug")).colour == S.RED
    assert S.classify({"id": "gone", "_absent": True}).state == S.UNAVAILABLE
    # A stopped service is grey everywhere, never "disconnected".
    assert S.classify(dict(healthy, state="disconnected"), service_running=False).state == S.SERVICE_STOPPED
    assert S.aggregate([S.classify(healthy)], service_running=False) == S.GREY
    assert S.aggregate([]) == S.RED
    ok = S.classify(healthy)
    bad = S.classify(dict(healthy, state="disconnected"))
    flaky = S.classify(dict(healthy, state="degraded"))
    assert S.aggregate([ok, flaky]) == S.YELLOW and S.aggregate([ok, flaky, bad]) == S.RED      # worst wins
    assert S.summary([ok, ok])[1] == "All displays working"
    assert S.summary([ok, bad])[1] == "Attention needed on a display"


def test_symbolic_svg_is_monochrome():
    path = os.path.join(APP_DIR, "..", "icons", "hicolor", "symbolic", "apps", "big-screen-monitor-tray-symbolic.svg")
    with open(path, encoding="utf-8") as handle:
        svg = handle.read()
    assert set(re.findall(r"#[0-9a-fA-F]{6}", svg)) == {"#2e3436"}      # recoloured by the icon theme


# ------------------------------------------------------------------ icon

def _count(image, colour, size):
    hits = 0
    for y in range(size):
        for x in range(size):
            px = image.pixelColor(x, y)
            if px.alpha() >= 200 and abs(px.red() - colour.red()) + abs(px.green() - colour.green()) + \
                    abs(px.blue() - colour.blue()) < 40:
                hits += 1
    return hits


def test_symbolic_monitor_is_monochrome_with_one_coloured_dot(qt_env):  # noqa: F811
    from traykit import icons
    QColor = qt_env.qt.QColor
    for dot, colour in icons.DOT_COLOURS.items():
        for foreground in (icons.DARK_FOREGROUND, icons.LIGHT_FOREGROUND):
            icon = icons.screen_icon(dot, foreground)
            for size in (16, 22, 24, 32):
                image = icon.pixmap(size, size).toImage()
                assert (image.width(), image.height()) == (size, size)
                assert _count(image, QColor(colour), size) >= 4, (dot, size)            # the status dot
                if dot != "grey":                                                     # grey dims the monitor
                    assert _count(image, QColor(foreground), size) >= size, (dot, size)  # panel text colour
                # nothing else is coloured: every opaque pixel is the foreground, the dot or its rim
                for y in range(size):
                    for x in range(size):
                        px = image.pixelColor(x, y)
                        if px.alpha() >= 250 and px.saturation() > 60:
                            allowed = [QColor(colour).hue(), QColor(foreground).hue()]
                            assert any(abs(px.hue() - hue) < 20 for hue in allowed) or \
                                QColor(colour).saturation() < 30, (dot, size, x, y)


def test_panel_foreground_follows_the_desktop(qt_env):  # noqa: F811
    from traykit import icons
    assert icons.panel_foreground(desktop="ubuntu:GNOME").name() == icons.LIGHT_FOREGROUND      # dark top bar
    assert icons.panel_foreground(desktop="KDE").name() in (icons.LIGHT_FOREGROUND, icons.DARK_FOREGROUND)


# ------------------------------------------------------------------ menu and selection

def _submenu(tray, prefix):
    return next(a.menu() for a in tray.menu.actions() if a.menu() and a.text().startswith(prefix))


def test_menu_selects_a_display_and_remembers_it(qt_env):  # noqa: F811
    from screentray.app import ScreenTray, _load_state
    qt_env.status([SCREEN, AX206])
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    assert tray.menu.actions()[0].text() == "Service running"
    choices = {a.text(): a for a in _submenu(tray, "Display:").actions() if a.isCheckable()}
    assert choices["All displays"].isChecked()
    choices["AX206 DPF — Connected"].trigger()
    assert tray.target_id == "usb-1-4" and _load_state()["target"] == "usb-1-4"
    tray.set_orientation("vertical")
    qt_env.wait(tray)
    assert qt_env.saved()["displays"] == {"usb-1-4": {"orientation": "vertical"}}    # only the chosen one
    sub = _submenu(tray, "Display:")
    assert sub.title() == "Display: AX206 DPF"
    assert [a.text() for a in sub.actions() if a.isChecked()] == ["AX206 DPF — Connected"]
    assert not _submenu(tray, "Brightness").isEnabled()             # the AX206 has no backlight control
    assert tray.window.target.currentData() == "usb-1-4"            # the window follows the menu
    again = make(qt_env, ScreenTray)                                # next session: same display
    assert again.target_id == "usb-1-4"


def test_unplugged_selection_stays_unavailable_and_nothing_is_redirected(qt_env):  # noqa: F811
    from screentray.app import ScreenTray
    qt_env.status([SCREEN, AX206])
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    tray.select_target("usb-1-4")
    qt_env.status([SCREEN])                                         # the AX206 was unplugged
    tray.poll()
    assert tray.target_id == "usb-1-4" and not tray.target_available()
    assert tray._icon_state() == "red" and tray.target_label() == "AX206 DPF"
    assert tray.window.target.currentData() == "usb-1-4"
    assert "Unavailable" in tray.window.target.currentText()
    assert tray.apply({"orientation": "vertical"}) is False and tray.apply({"brightness": 40}) is False
    qt_env.wait(tray)
    saved = qt_env.saved()
    assert not saved.get("displays") and saved["orientation"] == "horizontal"
    assert not _submenu(tray, "Orientation").isEnabled()
    tray.select_target("")                                          # the user picks another target
    assert tray.target_available() and tray._icon_state() == "green"


def test_all_displays_asks_before_replacing_individual_choices(qt_env, monkeypatch):  # noqa: F811
    from screentray.app import ScreenTray
    qt_env.status([SCREEN, AX206])
    qt_env.settings(displays={"usb-1-4": {"orientation": "vertical"}})
    tray = make(qt_env, ScreenTray)
    asked = []
    monkeypatch.setattr(tray, "confirm", lambda title, text: asked.append(text) or False)
    assert tray.apply({"orientation": "horizontal_flipped"}) is False                    # refused
    assert asked and "AX206 DPF" in asked[0]
    qt_env.wait(tray)
    assert qt_env.saved()["displays"] == {"usb-1-4": {"orientation": "vertical"}}
    monkeypatch.setattr(tray, "confirm", lambda title, text: True)
    assert tray.apply({"orientation": "horizontal_flipped"}) is True
    qt_env.wait(tray)
    assert not qt_env.saved().get("displays") and qt_env.saved()["orientation"] == "horizontal_flipped"


def test_all_displays_brightness_only_reaches_displays_with_a_backlight(qt_env):  # noqa: F811
    from screentray.app import ScreenTray
    qt_env.status([SCREEN, AX206])
    qt_env.settings(brightness=70)
    tray = make(qt_env, ScreenTray)
    tray.apply({"brightness": 40})
    qt_env.wait(tray)
    data = qt_env.saved()
    assert data["displays"] == {"usb-1-2": {"brightness": 40}} and data["brightness"] == 70


def test_display_without_capabilities_does_not_break_the_menu(qt_env):  # noqa: F811
    from screentray.app import ScreenTray
    phone = {"id": "android-1234", "name": "Phone", "state": "retrying", "capabilities": None, "settings": {}}
    qt_env.status([SCREEN, phone])
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    assert tray._icon_state() == "yellow"
    assert "Phone — Reconnecting…" in [a.text() for a in _submenu(tray, "Display:").actions()]


def test_stopped_service_is_grey_with_the_service_line_first(qt_env):  # noqa: F811
    from screentray.app import ScreenTray
    qt_env.status([SCREEN], age=60)
    qt_env.settings()
    tray = make(qt_env, ScreenTray)
    assert tray._icon_state() == "grey"
    assert tray.menu.actions()[0].text() == "Service stopped"
    assert "Turing 3.5\" — Service stopped" in [a.text() for a in tray.menu.actions()]
