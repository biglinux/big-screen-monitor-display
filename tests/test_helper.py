"""The polkit helper accepts only validated settings and fixed verbs."""

import importlib.machinery
import importlib.util
import io
import json
import os
import types

import pytest

from bsmd import settings

HELPER = os.path.join(os.path.dirname(__file__), "..", "usr", "lib", "big-screen-monitor-display", "bsm-helper")


@pytest.fixture
def helper(monkeypatch, tmp_path, capsys):
    loader = importlib.machinery.SourceFileLoader("bsm_helper", HELPER)
    spec = importlib.util.spec_from_loader("bsm_helper", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "APP_DIR", os.path.join(os.path.dirname(HELPER), "..", "..", "share",
                                                        "big-screen-monitor-display"))
    target = tmp_path / "etc" / "settings.json"
    monkeypatch.setattr(settings, "SYSTEM_CONFIG", str(target))
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    def run(argv, stdin=b""):
        monkeypatch.setattr(module.sys, "stdin", types.SimpleNamespace(buffer=io.BytesIO(stdin)))
        try:
            code = module.main(argv)
        except SystemExit as exit_:
            code = exit_.code
        out = capsys.readouterr().out.strip().splitlines()
        return code, json.loads(out[-1]) if out else {}

    run.target = target
    run.calls = calls
    run.module = module
    return run


def test_apply_settings_validates_and_writes(helper):
    code, reply = helper(["apply-settings"], json.dumps({"theme": "planet", "brightness": 999,
                                                          "evil": "rm -rf /"}).encode())
    assert code == 0 and reply["ok"]
    written = json.loads(helper.target.read_text())
    assert written["theme"] == "planet" and written["brightness"] == 100 and "evil" not in written
    assert reply["problems"]


def test_invalid_json_is_rejected(helper):
    code, reply = helper(["apply-settings"], b"{nope")
    assert code == 2 and not reply["ok"]
    assert not helper.target.exists()


def test_oversized_input_is_rejected(helper):
    code, reply = helper(["apply-settings"], b" " * (helper.module.MAX_INPUT + 1))
    assert code == 2 and "large" in reply["error"]


@pytest.mark.parametrize("argv", [["service", "mask"], ["service"], ["service", "restart", "x"],
                                  ["shell", "id"], ["apply-settings", "extra"], []])
def test_only_fixed_verbs(helper, argv):
    code, reply = helper(argv)
    assert code == 2 and not reply["ok"]
    assert helper.calls == []


def test_service_verbs_target_only_this_unit(helper):
    for verb in ("start", "stop", "restart", "enable", "disable"):
        code, reply = helper(["service", verb])
        assert code == 0 and reply["ok"]
    assert all(call[0] == "/usr/bin/systemctl" and call[-1] == "big-screen-monitor-display.service"
               for call in helper.calls)
    assert ["/usr/bin/systemctl", "enable", "--now", "big-screen-monitor-display.service"] in helper.calls


def test_recover_sends_sigusr1(helper):
    code, _reply = helper(["recover"])
    assert code == 0
    assert helper.calls[-1] == ["/usr/bin/systemctl", "kill", "--signal=SIGUSR1", "--kill-whom=main",
                                "big-screen-monitor-display.service"]


def test_display_command_goes_to_the_spool(helper, tmp_path, monkeypatch):
    spool = tmp_path / "run" / "commands"
    monkeypatch.setattr(helper.module, "SPOOL_DIR", str(spool))
    code, reply = helper(["display-command"], b'{"action": "pattern", "pattern": "bars", "display": "usb-1-2"}')
    assert code == 2 and "not running" in reply["error"]        # no spool: service down
    spool.mkdir(parents=True)
    code, reply = helper(["display-command"], b'{"action": "pattern", "pattern": "bars", "display": "usb-1-2",'
                                              b' "seconds": 999, "extra": "x"}')
    assert code == 0 and reply["ok"]
    (written,) = spool.iterdir()
    assert json.loads(written.read_text()) == {"action": "pattern", "pattern": "bars", "display": "usb-1-2",
                                               "seconds": 60}


@pytest.mark.parametrize("payload", [b'{"action": "flash"}', b'{"action": "pattern", "pattern": "../x"}',
                                     b'{"action": "reconnect", "display": "../../etc"}', b"not json",
                                     b'{"action": "reconnect", "display": "' + b"a" * 5000 + b'"}'])
def test_display_command_rejects_bad_input(helper, tmp_path, monkeypatch, payload):
    spool = tmp_path / "commands"
    spool.mkdir()
    monkeypatch.setattr(helper.module, "SPOOL_DIR", str(spool))
    code, reply = helper(["display-command"], payload)
    assert code == 2 and not reply["ok"] and not list(spool.iterdir())


def test_display_command_refuses_symlinked_spool(helper, tmp_path, monkeypatch):
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "commands"
    link.symlink_to(target)
    monkeypatch.setattr(helper.module, "SPOOL_DIR", str(link))
    code, _reply = helper(["display-command"], b'{"action": "reconnect"}')
    assert code == 2 and not list(target.iterdir())


def _png():
    import io
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (1, 2, 3)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_wallpaper_import_and_removal(helper, tmp_path):
    code, reply = helper(["import-wallpaper"], _png())
    assert code == 0 and reply["ok"]
    stored = helper.target.parent / "wallpapers" / f"{reply['id']}.png"
    assert stored.exists() and oct(stored.stat().st_mode & 0o777) == "0o644"
    code, reply2 = helper(["remove-wallpaper", reply["id"]])
    assert code == 0 and not stored.exists()


@pytest.mark.parametrize("payload", [b"not an image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, b"GIF89a....."])
def test_wallpaper_import_rejects_non_png(helper, payload):
    code, reply = helper(["import-wallpaper"], payload)
    assert code == 2 and not reply["ok"]
    assert not (helper.target.parent / "wallpapers").exists() or not list((helper.target.parent / "wallpapers").iterdir())


@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "x" * 32, ""])
def test_wallpaper_removal_rejects_bad_ids(helper, bad_id):
    code, reply = helper(["remove-wallpaper", bad_id])
    assert code == 2 and not reply["ok"]
