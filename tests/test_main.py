"""main.py: command line entry points that need no hardware and no running service."""

import importlib.util
import json
import os

import pytest
from PIL import Image

from bsmd import __version__

APP = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "usr", "share", "big-screen-monitor-display"))


@pytest.fixture(scope="module")
def main_module():
    spec = importlib.util.spec_from_file_location("bsmd_main_entry", os.path.join(APP, "main.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("BSM_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("BSM_STATUS", str(tmp_path / "no-status.json"))
    return tmp_path


def test_parse_size(main_module):
    assert main_module.parse_size("480x320") == (480, 320)
    assert main_module.parse_size("800X480") == (800, 480)
    with pytest.raises(ValueError):
        main_module.parse_size("480")


def test_parse_simulate(main_module):
    panels = main_module.parse_simulate("480x320, 480x480:round", latency_ms=20, throughput=1e6)
    assert [p.model for p in panels] == ["Simulated panel 480x320", "Simulated panel 480x480 (round)"]


def test_version(main_module, capsys):
    with pytest.raises(SystemExit) as stop:
        main_module.main(["--version"])
    assert stop.value.code == 0 and capsys.readouterr().out.strip() == __version__


def test_render_writes_a_frame(main_module, isolated, capsys):
    out = isolated / "frame.png"
    code = main_module.main(["--render", "standard", "--size", "320x240", "--out", str(out),
                             "--set", "std_scheme=neon", "--set", "nonsense_key=1"])
    assert code == 0 and capsys.readouterr().out.strip() == str(out)
    with Image.open(out) as image:
        assert image.size == (320, 240)


def test_render_vertical_swaps_the_size(main_module, isolated):
    out = isolated / "portrait.png"
    assert main_module.main(["--render", "standard", "--size", "480x320", "--orientation", "vertical",
                             "--out", str(out)]) == 0
    with Image.open(out) as image:
        assert image.size == (320, 480)


def test_status_without_service(main_module, isolated, capsys):
    assert main_module.main(["--status"]) == 1
    assert capsys.readouterr().err.strip()


def test_status_prints_the_service_file(main_module, isolated, monkeypatch, capsys):
    status = isolated / "status.json"
    status.write_text(json.dumps({"state": "healthy", "version": __version__}))
    monkeypatch.setenv("BSM_STATUS", str(status))
    assert main_module.main(["--status"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "healthy"


def test_list_displays_with_nothing_connected(main_module, isolated, monkeypatch, capsys):
    from bsmd.displays import discovery
    monkeypatch.setattr(discovery, "scan_usb", lambda: [])
    assert main_module.main(["--list-displays", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []
    assert main_module.main(["--list-displays"]) == 1
