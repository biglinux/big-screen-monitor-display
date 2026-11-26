"""Tray launcher: without PyQt the user is told which package to install (no silent failure)."""

import sys
import types

import pytest

from traykit import launch


@pytest.fixture(autouse=True)
def english():
    from bsmd import i18n
    i18n.set_language("en")
    yield
    i18n.set_language("auto")


def test_without_qt_the_package_is_named(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "traykit.qt", None)          # "import traykit.qt" raises ImportError
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    from bsmd import distro
    monkeypatch.setattr(distro, "install_hint", lambda what: "sudo pacman -S python-pyqt6")
    assert launch.main("screentray.app", "ScreenTray", "Big Screen Monitor Tray") == 2
    err = capsys.readouterr().err
    assert "Big Screen Monitor Tray" in err and "PyQt6 or PyQt5" in err and "sudo pacman -S python-pyqt6" in err


def test_hint_falls_back_to_the_package_name(monkeypatch, capsys):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    from bsmd import distro
    monkeypatch.setattr(distro, "install_hint", lambda what: "")
    launch._missing_qt("DeepCool Digital")
    assert capsys.readouterr().err.rstrip().endswith("PyQt6")


def test_with_qt_the_tray_class_is_run(monkeypatch):
    pytest.importorskip("traykit.qt", exc_type=ImportError)
    ran = []
    fake_app = types.ModuleType("fake_tray_app")
    fake_app.FakeTray = object
    monkeypatch.setitem(sys.modules, "fake_tray_app", fake_app)
    import traykit.base
    monkeypatch.setattr(traykit.base, "run", lambda cls: ran.append(cls) or 0)
    assert launch.main("fake_tray_app", "FakeTray", "Fake") == 0
    assert ran == [object]
