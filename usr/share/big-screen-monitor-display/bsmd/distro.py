"""Which Linux distribution family this is, from /etc/os-release.

Families are recognised by ``ID`` and ``ID_LIKE`` (never just by finding
``zypper`` or ``pacman`` in PATH): Arch, Manjaro and BigLinux are "arch";
openSUSE Tumbleweed/Leap/Slowroll and Regata OS are "suse"; Debian and Ubuntu
"debian"; Fedora "fedora". Used for the messages that name a missing package
and by the tests of install-system.sh, which carries the same table in shell.
"""

import os
import sys

FAMILIES = {
    "arch": ("arch", "manjaro", "biglinux", "bigcommunity", "endeavouros", "garuda", "cachyos", "artix"),
    "suse": ("opensuse", "opensuse-tumbleweed", "opensuse-leap", "opensuse-slowroll", "regataos", "suse", "sles",
             "sled"),
    "debian": ("debian", "ubuntu", "linuxmint", "pop", "elementary", "zorin"),
    "fedora": ("fedora", "rhel", "centos", "rocky", "almalinux", "nobara"),
}
PACKAGE_MANAGER = {"arch": "pacman", "suse": "zypper", "debian": "apt-get", "fedora": "dnf"}


def read_os_release(path=None):
    """Key/value pairs of os-release (``/etc/os-release``, else ``/usr/lib/os-release``)."""
    paths = [path] if path else ["/etc/os-release", "/usr/lib/os-release"]
    for candidate in paths:
        try:
            with open(candidate, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        data = {}
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _sep, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            data[key.strip()] = value
        return data
    return {}


def family(info=None):
    """``"arch"``, ``"suse"``, ``"debian"``, ``"fedora"`` or ``""`` (unknown)."""
    info = read_os_release() if info is None else info
    ids = [info.get("ID", "").lower()] + info.get("ID_LIKE", "").lower().split()
    for name, members in FAMILIES.items():
        if any(item in members or any(item.startswith(m + "-") for m in members) for item in ids if item):
            return name
    return ""


def python_suffix(version=None):
    """``"313"`` for Python 3.13: openSUSE names its Python packages after the interpreter."""
    major, minor = (version or sys.version_info)[:2]
    return f"{major}{minor}"


def packages(name, info=None, version=None):
    """Distribution package that provides a Python module or tool, or ``""``."""
    fam = family(info)
    suffix = python_suffix(version)
    table = {
        "pyqt": {"arch": "python-pyqt6", "suse": f"python{suffix}-PyQt6", "debian": "python3-pyqt6",
                 "fedora": "python3-pyqt6"},
        "psutil": {"arch": "python-psutil", "suse": f"python{suffix}-psutil", "debian": "python3-psutil",
                   "fedora": "python3-psutil"},
        "openrgb": {"arch": "openrgb", "suse": "OpenRGB", "debian": "openrgb", "fedora": "openrgb"},
    }
    return table.get(name, {}).get(fam, "")


def install_hint(name, info=None):
    """``sudo pacman -S python-pyqt6`` style command, or ``""`` when unknown."""
    fam = family(info)
    package = packages(name, info)
    if not package:
        return ""
    command = {"arch": "sudo pacman -S", "suse": "sudo zypper install", "debian": "sudo apt install",
               "fedora": "sudo dnf install"}[fam]
    return f"{command} {package}"


def describe(info=None):
    info = read_os_release() if info is None else info
    return info.get("PRETTY_NAME") or info.get("NAME") or os.uname().sysname
