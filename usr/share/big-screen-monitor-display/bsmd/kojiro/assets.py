"""Distribution name and logo, detected from os-release and the installed icons."""

import functools
import glob
import io
import os
import subprocess

from PIL import Image

OS_RELEASE = ("/etc/os-release", "/usr/lib/os-release")


@functools.lru_cache(maxsize=1)
def os_release():
    info = {}
    for path in OS_RELEASE:
        try:
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    key, sep, value = line.strip().partition("=")
                    if sep:
                        info[key] = value.strip().strip('"').strip("'")
            break
        except OSError:
            continue
    return info


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


@functools.lru_cache(maxsize=1)
def distro_info():
    info = os_release()
    name = info.get("NAME") or info.get("PRETTY_NAME") or "Linux"
    # "BigLinux based on Manjaro Linux" -> "BigLinux": the widget shows a short name.
    short = name.split(" based on ")[0].split(" GNU/Linux")[0].strip() or name
    logo = None
    for candidate in (info.get("LOGO"), info.get("ID"), f"distributor-logo-{info.get('ID', '')}", "distributor-logo"):
        logo = logo_path(candidate)
        if logo:
            break
    return {"name": short, "full_name": name, "pretty": info.get("PRETTY_NAME", name), "id": info.get("ID", "linux"), "logo": logo}


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
