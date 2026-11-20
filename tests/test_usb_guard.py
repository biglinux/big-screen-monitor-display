"""bsm-usb-guard: SmartMonitor panels parked before sleep (fake sysfs)."""

import importlib.machinery
import importlib.util
import os

import pytest

GUARD = os.path.join(os.path.dirname(__file__), "..", "usr", "lib", "big-screen-monitor-display", "bsm-usb-guard")


@pytest.fixture
def guard(tmp_path, monkeypatch):
    loader = importlib.machinery.SourceFileLoader("bsm_usb_guard", GUARD)
    spec = importlib.util.spec_from_loader("bsm_usb_guard", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "SYSFS", str(tmp_path))
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    return module


def device(root, name, vendor, product, authorized="1"):
    path = root / name
    path.mkdir()
    for attr, value in (("idVendor", vendor), ("idProduct", product), ("authorized", authorized),
                        ("busnum", "1"), ("devnum", "7")):
        (path / attr).write_text(value + "\n")
    return path


def test_only_smartmonitor_panels_are_considered(guard, tmp_path):
    device(tmp_path, "1-2", "0483", "0065")
    device(tmp_path, "1-3", "0483", "5750")          # another STMicro device
    device(tmp_path, "5-1.1", "320f", "5000")
    (tmp_path / "1-2:1.0").mkdir()                    # interfaces and root hubs are not devices
    device(tmp_path, "usb1", "1d6b", "0002")
    assert guard.panels() == ["1-2"]


def test_unpark_authorizes_parked_panels_only(guard, tmp_path):
    parked = device(tmp_path, "1-2", "0483", "0065", authorized="0")
    other = device(tmp_path, "1-3", "046d", "0825", authorized="0")
    assert guard.main(["unpark"]) == 0
    assert (parked / "authorized").read_text() == "1"
    assert (other / "authorized").read_text().strip() == "0"     # never another device


def test_restarts_are_not_handled_here(guard):
    assert guard.main(["stop"]) == 2 and guard.main(["start"]) == 2       # only sleep / wake


def test_sleep_without_a_panel_touches_nothing(guard, tmp_path, monkeypatch):
    device(tmp_path, "5-1.1", "320f", "5000")
    monkeypatch.setattr(guard.subprocess, "run", lambda *a, **k: pytest.fail("no service stop without a panel"))
    monkeypatch.setattr(guard, "park_all", lambda: pytest.fail("nothing to park"))
    assert guard.main(["sleep"]) == 0


def test_a_panel_already_parked_is_left_alone(guard, tmp_path):
    device(tmp_path, "1-2", "0483", "0065", authorized="0")
    assert guard.park("1-2", protocol=None) is True


def test_unknown_verbs_and_non_root_are_refused(guard, monkeypatch):
    assert guard.main(["rm", "-rf"]) == 2
    monkeypatch.setattr(guard.os, "geteuid", lambda: 1000)
    assert guard.main(["park"]) == 2
