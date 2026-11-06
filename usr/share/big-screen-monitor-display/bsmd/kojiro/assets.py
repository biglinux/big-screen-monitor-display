"""System name and logo: the distribution (os-release) or, when the graphical
session in front of the panel belongs to a desktop that has its own identity,
that desktop's name and logo.

Desktop identity files (``/usr/share/desktop-identity/*.conf``, os-release
syntax) are installed by a desktop that presents itself under its own name on
top of a base distribution, eg. Big WindowMaker on BigCommunity::

    NAME="Big WindowMaker"
    LOGO=big-wm
    LOGO_FILE=/usr/share/icons/hicolor/scalable/apps/big-wm.svg
    DESKTOP_NAMES=WindowMaker;wlmaker

The active session of seat0 and its desktop are read the way sd-login does it,
from logind's runtime files: no D-Bus, no process, nothing to keep running. The
distribution itself (ID, ID_LIKE) is never replaced.
"""

import functools
import glob
import io
import os
import subprocess
import time

from PIL import Image

OS_RELEASE = ("/etc/os-release", "/usr/lib/os-release")
IDENTITY_DIRS = ("/etc/desktop-identity", "/usr/share/desktop-identity")
LOGIND_DIR = "/run/systemd"
IDENTITY_TTL = 15.0           # s; a login or a session switch shows up within this
_identity_cache = [None, -1e9]


def _parse(path):
    info = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if sep:
                info[key.strip()] = value.strip().strip('"').strip("'")
    return info


@functools.lru_cache(maxsize=1)
def os_release():
    for path in OS_RELEASE:
        try:
            return _parse(path)
        except OSError:
            continue
    return {}


def active_desktop(logind_dir=None):
    """Desktop names (XDG_SESSION_DESKTOP, ":"-separated) of seat0's active session, or ()."""
    base = logind_dir or os.environ.get("BSMD_LOGIND_DIR") or LOGIND_DIR
    try:
        session = _parse(os.path.join(base, "seats", "seat0")).get("ACTIVE", "")
        if not session or "/" in session:
            return ()
        info = _parse(os.path.join(base, "sessions", session))
    except (OSError, UnicodeDecodeError):
        return ()
    if info.get("CLASS", "user") != "user":
        return ()               # greeter, lock screen of the display manager
    return tuple(n for n in info.get("DESKTOP", "").split(":") if n)


def desktop_identity(desktops, dirs=None):
    """The identity file whose DESKTOP_NAMES matches one of ``desktops``, or None."""
    if not desktops:
        return None
    wanted = {d.casefold() for d in desktops}
    for directory in dirs or (os.environ["BSMD_IDENTITY_DIR"].split(":") if os.environ.get("BSMD_IDENTITY_DIR")
                              else IDENTITY_DIRS):
        for path in sorted(glob.glob(os.path.join(directory, "*.conf"))):
            try:
                info = _parse(path)
            except (OSError, UnicodeDecodeError):
                continue
            names = {n.strip().casefold() for n in info.get("DESKTOP_NAMES", "").split(";") if n.strip()}
            if info.get("NAME") and names & wanted:
                return info
    return None


def identity(now=None):
    """os-release, with NAME/PRETTY_NAME/LOGO of the active desktop's identity when it has one.

    Keys added: ``BASE_NAME`` (the distribution's own name) and ``LOGO_FILE``."""
    now = time.monotonic() if now is None else now
    if _identity_cache[0] is not None and now - _identity_cache[1] < IDENTITY_TTL:
        return _identity_cache[0]
    info = dict(os_release())
    info["BASE_NAME"] = info.get("NAME") or info.get("PRETTY_NAME") or "Linux"
    desk = desktop_identity(active_desktop())
    if desk:
        info["NAME"] = info["PRETTY_NAME"] = desk["NAME"]
        info["LOGO"] = desk.get("LOGO", "")
        info["LOGO_FILE"] = desk.get("LOGO_FILE", "")
    _identity_cache[0], _identity_cache[1] = info, now
    return info


def reset_identity():
    _identity_cache[0] = None


def logo_path(name):
    """Best file for an icon name: pixmaps first, then the largest hicolor icon."""
    if not name or "/" in name:
        return None
    for ext in (".svg", ".png"):
        path = f"/usr/share/pixmaps/{name}{ext}"
        if os.path.exists(path):
            return path
    candidates = glob.glob(f"/usr/share/icons/hicolor/*/apps/{name}.svg") + \
        glob.glob(f"/usr/share/icons/hicolor/*/apps/{name}.png")

    def size_of(path):
        part = path.split("/")[5]
        if part == "scalable":
            return 10000
        try:
            return int(part.split("x")[0])
        except ValueError:
            return 0
    return max(candidates, key=size_of) if candidates else None


def distro_info():
    info = identity()
    return _distro_info(info.get("NAME") or info.get("PRETTY_NAME") or "Linux", info.get("PRETTY_NAME", ""),
                        info.get("LOGO", ""), info.get("LOGO_FILE", ""), info.get("ID", "linux"))


@functools.lru_cache(maxsize=4)
def _distro_info(name, pretty, logo_name, logo_file, distro_id):
    # "BigLinux based on Manjaro Linux" -> "BigLinux": the widget shows a short name.
    short = name.split(" based on ")[0].split(" GNU/Linux")[0].strip() or name
    logo = None
    for candidate in (logo_name, distro_id, f"distributor-logo-{distro_id}", "distributor-logo"):
        logo = logo_path(candidate)
        if logo:
            break
        if candidate == logo_name and logo_file and os.path.isfile(logo_file):
            logo = logo_file
            break
    return {"name": short, "full_name": name, "pretty": pretty or name, "id": distro_id, "logo": logo}


@functools.lru_cache(maxsize=16)
def load_logo(path, size):
    """RGBA logo of ``size`` px (SVG through rsvg-convert), or None."""
    if not path:
        return None
    try:
        if path.endswith(".svg"):
            result = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), "--keep-aspect-ratio", path],
                                    capture_output=True, timeout=3, check=False)
            if result.returncode != 0:
                return None
            image = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
        else:
            image = Image.open(path).convert("RGBA")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
        return image
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def fallback_logo(size, color):
    """Tux-free generic mark: a ring with an L, used when no logo is installed."""
    from PIL import ImageDraw
    from .draw import font
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = max(2, size // 14)
    draw.ellipse((width, width, size - width, size - width), outline=color, width=width)
    draw.text((size / 2, size / 2), "L", font=font("default", int(size * 0.5), True), fill=color, anchor="mm")
    return image
