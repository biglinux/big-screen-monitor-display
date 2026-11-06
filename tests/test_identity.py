"""System identity: the distribution, or the desktop of the active session when it
has an identity file (Big WindowMaker on BigCommunity)."""

import os

import pytest

from bsmd import legacy_themes
from bsmd.bigmedia import distro_logo_path
from bsmd.kojiro import assets

BIG_WM = 'NAME="Big WindowMaker"\nLOGO=big-wm\nLOGO_FILE={logo}\nDESKTOP_NAMES=WindowMaker;wlmaker\n'
OS_RELEASE = {"NAME": "BigCommunity, based in BigLinux", "PRETTY_NAME": "BigCommunity, based in BigLinux",
              "ID": "bigcommunity", "ID_LIKE": "arch", "LOGO": "comm-menu"}


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fake logind (/run/systemd) and identity directory, and a fixed os-release."""
    logind = tmp_path / "run"
    (logind / "seats").mkdir(parents=True)
    (logind / "sessions").mkdir()
    ident = tmp_path / "identity"
    ident.mkdir()
    logo = tmp_path / "big-wm.svg"
    logo.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>')
    (ident / "big-wm.conf").write_text(BIG_WM.format(logo=logo))
    monkeypatch.setenv("BSMD_LOGIND_DIR", str(logind))
    monkeypatch.setenv("BSMD_IDENTITY_DIR", str(ident))
    monkeypatch.setattr(assets, "os_release", lambda: dict(OS_RELEASE))
    assets.reset_identity()
    yield logind, logo

    assets.reset_identity()


def login(logind, desktop, cls="user", session="3"):
    (logind / "seats" / "seat0").write_text(f"ACTIVE={session}\nSESSIONS={session}\n")
    (logind / "sessions" / session).write_text(f"STATE=active\nTYPE=x11\nCLASS={cls}\nDESKTOP={desktop}\n")
    assets.reset_identity()


@pytest.mark.parametrize("desktop", ["WindowMaker", "wlmaker"])
def test_big_windowmaker_session_shows_its_own_name_and_logo(world, desktop):
    logind, logo = world
    login(logind, desktop)
    info = assets.identity()
    assert info["NAME"] == info["PRETTY_NAME"] == "Big WindowMaker"
    # The base distribution is still known.
    assert info["ID"] == "bigcommunity" and info["BASE_NAME"].startswith("BigCommunity")
    assert assets.distro_info()["name"] == "Big WindowMaker"
    assert legacy_themes.get_os_release()["NAME"] == "Big WindowMaker"
    # The big-wm icon of the icon theme when installed, else the identity's own file.
    installed = assets.logo_path("big-wm")
    assert distro_logo_path() == (installed or str(logo))
    assert distro_logo_path().endswith("big-wm.svg")


def test_logo_file_is_used_without_the_icon(world, tmp_path):
    logind, logo = world
    (tmp_path / "identity" / "big-wm.conf").write_text(
        BIG_WM.format(logo=logo).replace("LOGO=big-wm", "LOGO=no-such-icon-for-the-test"))
    login(logind, "WindowMaker")
    assert distro_logo_path() == str(logo)
    assert assets.distro_info()["logo"] == str(logo)


def test_other_desktop_keeps_the_distribution(world):
    logind, _logo = world
    login(logind, "KDE")
    assert assets.identity()["NAME"] == "BigCommunity, based in BigLinux"
    assert assets.distro_info()["name"].startswith("BigCommunity")


def test_greeter_and_no_session_keep_the_distribution(world):
    logind, _logo = world
    login(logind, "WindowMaker", cls="greeter")
    assert assets.identity()["NAME"].startswith("BigCommunity")
    (logind / "seats" / "seat0").unlink()
    assets.reset_identity()
    assert assets.identity()["NAME"].startswith("BigCommunity")


def test_session_switch_is_seen_after_the_cache(world):
    logind, _logo = world
    login(logind, "KDE")
    assert assets.identity(now=100.0)["NAME"].startswith("BigCommunity")
    (logind / "sessions" / "3").write_text("CLASS=user\nDESKTOP=WindowMaker\n")
    # Cached for a few seconds (no file reads every frame), then refreshed.
    assert assets.identity(now=101.0)["NAME"].startswith("BigCommunity")
    assert assets.identity(now=100.0 + assets.IDENTITY_TTL + 1)["NAME"] == "Big WindowMaker"


def test_malformed_files_are_ignored(world, tmp_path):
    logind, _logo = world
    (logind / "seats" / "seat0").write_text("ACTIVE=../../etc\n")
    assets.reset_identity()
    assert assets.identity()["NAME"].startswith("BigCommunity")
    bad = tmp_path / "identity" / "broken.conf"
    bad.write_bytes(b"\xff\xfe NAME")
    login(logind, "WindowMaker")
    assert assets.identity()["NAME"] == "Big WindowMaker"


def test_real_logind_files_parse():
    """On a machine with logind, reading the real files never raises."""
    assert isinstance(assets.active_desktop(), tuple)
    assert os.path.isabs(assets.LOGIND_DIR)
