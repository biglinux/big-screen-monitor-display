"""install-system.sh / uninstall-system.sh in a staging directory (no root).

Covers a clean install, a repeated install (idempotent), an upgrade over the
files of the first tray apps (pull request #11), settings preservation and
backup, rollback to the previous settings, removal, and the dependency lists
per distribution family.
"""

import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INSTALL = os.path.join(ROOT, "install-system.sh")
UNINSTALL = os.path.join(ROOT, "uninstall-system.sh")
MANIFEST = "usr/lib/big-screen-monitor-display/install-manifest"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")


def run(script, *args, env=None):
    result = subprocess.run(["bash", script, *args], capture_output=True, text=True, timeout=120, check=False,
                            env=dict(os.environ, **(env or {})))
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def manifest(dest):
    return (dest / MANIFEST).read_text().split()


def test_clean_install_and_idempotent_reinstall(tmp_path):
    dest = tmp_path / "root"
    run(INSTALL, "--destdir", str(dest))
    files = manifest(dest)
    for wanted in ("/usr/bin/big-screen-monitor-tray", "/usr/bin/big-screen-monitor-deepcool",
                   "/usr/share/applications/big-screen-monitor-tray.desktop",
                   "/usr/share/applications/br.com.biglinux.BigScreenMonitorDisplay.desktop",
                   "/usr/share/applications/big-screen-monitor-deepcool.desktop",
                   "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-deepcool.svg",
                   "/usr/share/big-screen-monitor-display/traykit/base.py",
                   "/usr/share/big-screen-monitor-display/bsmd/control.py",
                   "/usr/lib/systemd/system/big-screen-monitor-display.service",
                   "/usr/lib/udev/rules.d/70-big-screen-monitor-display.rules",
                   "/etc/xdg/autostart/big-screen-monitor-media.desktop"):
        assert wanted in files, wanted
        assert (dest / wanted.lstrip("/")).exists() or (dest / wanted.lstrip("/")).is_symlink()
    assert os.access(dest / "usr/bin/big-screen-monitor-tray", os.X_OK)
    assert not any("__pycache__" in f for f in files)
    assert not (dest / "etc/big-screen-monitor-display").exists()      # settings are never shipped
    run(INSTALL, "--destdir", str(dest))
    assert manifest(dest) == files


def test_upgrade_keeps_settings_and_cleans_first_tray_version(tmp_path):
    dest = tmp_path / "root"
    settings = dest / "etc/big-screen-monitor-display/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "planet", "brightness": 33}\n')
    bin_dir = dest / "usr/bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "deepcool-digital.sh").write_text(
        "#!/bin/bash\nexec python3 /usr/share/big-screen-monitor-display/tray/main.py\n")
    (bin_dir / "deepcool-digital").symlink_to("/usr/bin/deepcool-digital.sh")
    (bin_dir / "screen-monitor-tray").write_text("#!/bin/bash\necho another program\n")   # not ours
    old_app = dest / "usr/share/big-screen-monitor-display/tray"
    old_app.mkdir(parents=True)
    (old_app / "app.py").write_text("# old module\n")
    output = run(INSTALL, "--destdir", str(dest))
    assert json.loads(settings.read_text()) == {"theme": "planet", "brightness": 33}
    backups = list(settings.parent.glob("settings.json.pre-install-*"))
    assert len(backups) == 1 and backups[0].read_text() == settings.read_text()
    assert not (bin_dir / "deepcool-digital.sh").exists() and not (bin_dir / "deepcool-digital").is_symlink()
    assert (bin_dir / "screen-monitor-tray").exists()
    assert not old_app.exists()                                       # removed modules do not linger
    assert "removed old usr/bin/deepcool-digital.sh" in output


def test_changed_conffile_is_kept(tmp_path):
    dest = tmp_path / "root"
    run(INSTALL, "--destdir", str(dest))
    conffile = dest / "etc/xdg/autostart/big-screen-monitor-media.desktop"
    conffile.write_text("[Desktop Entry]\nHidden=true\n")
    run(INSTALL, "--destdir", str(dest))
    assert conffile.read_text() == "[Desktop Entry]\nHidden=true\n"
    assert (dest / "etc/xdg/autostart/big-screen-monitor-media.desktop.new").exists()


def test_rollback_restores_previous_settings(tmp_path):
    """An upgrade leaves a verified copy; putting it back restores the old settings."""
    dest = tmp_path / "root"
    settings = dest / "etc/big-screen-monitor-display/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"theme": "gkrellm"}\n')
    run(INSTALL, "--destdir", str(dest))
    settings.write_text('{"theme": "kojiro"}\n')                      # changed after the upgrade
    backup = next(settings.parent.glob("settings.json.pre-install-*"))
    shutil.copy2(backup, settings)
    assert json.loads(settings.read_text()) == {"theme": "gkrellm"}


def test_uninstall_removes_only_installed_files(tmp_path):
    dest = tmp_path / "root"
    settings = dest / "etc/big-screen-monitor-display/settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n")
    foreign = dest / "usr/share/applications/someone-else.desktop"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("[Desktop Entry]\n")
    run(INSTALL, "--destdir", str(dest))
    files = manifest(dest)
    run(UNINSTALL, "--destdir", str(dest))
    for file in files:
        assert not (dest / file.lstrip("/")).exists(), file
    assert foreign.exists() and settings.exists()
    run(UNINSTALL, "--destdir", str(dest), "--purge")
    assert not settings.parent.exists()
    assert list((dest / "var/backups").glob("big-screen-monitor-display-*.tar.gz"))


@pytest.mark.parametrize("os_release,family,needles", [
    ('ID=manjaro\nID_LIKE=arch\n', "arch", ("python-pyqt6", "python-psutil", "gtk4")),
    ('ID=biglinux\nID_LIKE="manjaro arch"\n', "arch", ("python-pyqt6",)),
    ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "suse", ("-psutil", "-PyQt6", "typelib-1_0-Gtk-4_0")),
    ('ID="regataos"\nID_LIKE="opensuse suse"\n', "suse", ("-psutil", "-PyQt6")),
    ('ID=ubuntu\nID_LIKE=debian\n', "debian", ("python3-psutil", "python3-pyqt6")),
])
def test_dependency_lists(tmp_path, os_release, family, needles):
    path = tmp_path / "os-release"
    path.write_text(os_release)
    output = run(INSTALL, "--print-deps", env={"BSM_OS_RELEASE": str(path)})
    assert f"family: {family}" in output
    for needle in needles:
        assert needle in output, needle
    assert "tailscale" in output.split("optional:", 1)[1]          # remote access to Android displays


def test_pkgbuild_declares_tray_dependencies():
    with open(os.path.join(ROOT, "pkgbuild", "PKGBUILD"), encoding="utf-8") as handle:
        text = handle.read()
    assert "'python-pyqt6'" in text
    assert "screentray/main.py" in text and "deepcooltray/main.py" in text


def test_pkgbuild_declares_minimum_versions_and_remote_access():
    """GLibUnix needs GLib 2.80, Adw.Spinner libadwaita 1.6; Tailscale gives the Android display
    remote access (100.64.0.0/10 is allowed by the service unit)."""
    srcinfo = subprocess.run(["bash", "-c", 'source PKGBUILD; printf "%s\\n" "${depends[@]}" "${optdepends[@]}"'],
                             cwd=os.path.join(ROOT, "pkgbuild"), capture_output=True, text=True, check=True).stdout
    lines = srcinfo.splitlines()
    for wanted in ("python>=3.10", "glib2>=2.80", "libadwaita>=1.6", "openssl", "python-gobject", "python-psutil"):
        assert wanted in lines, wanted
    assert any(line.startswith("tailscale: ") for line in lines)
    assert any(line.startswith("python-qrcode: ") for line in lines)


def test_upgrade_replaces_the_launcher_renamed_after_the_application_id(tmp_path):
    dest = tmp_path / "root"
    apps = dest / "usr/share/applications"
    apps.mkdir(parents=True)
    old = apps / "big-screen-monitor-display.desktop"
    old.write_text("[Desktop Entry]\nName=Big Screen Monitor Display\nExec=/usr/bin/big-screen-monitor-config.sh\n")
    run(INSTALL, "--destdir", str(dest))
    assert not old.exists()                                     # no second menu entry after an upgrade
    assert (apps / "br.com.biglinux.BigScreenMonitorDisplay.desktop").exists()
