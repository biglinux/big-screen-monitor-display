#!/usr/bin/env python3
"""Android launcher icons and in-app logo from the official SVG (rsvg-convert + Pillow).

Run from the repository root after the icon changes:  python3 tools/android-icons.py
"""
import io
import os
import subprocess

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG = os.path.join(ROOT, "usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg")
RES = os.path.join(ROOT, "android/app/src/main/res")
DENSITIES = {"mdpi": 1.0, "hdpi": 1.5, "xhdpi": 2.0, "xxhdpi": 3.0, "xxxhdpi": 4.0}


def render(size):
    png = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), SVG], check=True,
                         capture_output=True).stdout
    return Image.open(io.BytesIO(png)).convert("RGBA")


def save(image, *parts):
    path = os.path.join(RES, *parts)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    image.save(path, optimize=True)


for name, scale in DENSITIES.items():
    save(render(round(48 * scale)), f"mipmap-{name}", "ic_launcher.png")
    canvas = round(108 * scale)                 # adaptive icon: 108 dp, safe zone 66 dp
    foreground = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    icon = render(round(72 * scale))
    offset = (canvas - icon.width) // 2
    foreground.alpha_composite(icon, (offset, offset))
    save(foreground, f"mipmap-{name}", "ic_launcher_foreground.png")
save(render(384), "drawable-nodpi", "logo.png")
print("icons written to", RES)
