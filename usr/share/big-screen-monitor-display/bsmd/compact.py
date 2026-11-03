"""Compact layout for tiny panels (WeAct 0.96" 80x160 and similar).

Below ~128 px on the short side the full dashboards cannot keep text
readable, so every theme (except the pixel-art Brother Away scene) switches
to this layout: clock plus three or four big metrics, coloured with the
theme's own palette.
"""

import time

from PIL import Image, ImageDraw

from . import telemetry
from .i18n import _
from .themes import ui_font

COMPACT_MIN_SIDE = 128
COMPACT_MAX_AREA = 36000
PLANET_ACCENTS = {"blue": (90, 170, 255), "green": (90, 230, 150), "amber": (255, 190, 70),
                  "violet": (190, 130, 255), "red": (255, 100, 100)}
OC_PALETTES = {"classic": ((192, 192, 192), (0, 0, 128)), "slate": ((120, 134, 150), (32, 48, 80)),
               "amber": ((40, 28, 6), (255, 176, 0)), "plum": ((170, 150, 180), (80, 30, 90))}


def needed(width, height):
    return min(width, height) < COMPACT_MIN_SIDE or width * height < COMPACT_MAX_AREA


def palette(theme_id, settings):
    if theme_id == "gkrellm":
        return {"bg": (12, 18, 14), "text": (200, 240, 200), "muted": (110, 150, 115), "accent": (120, 230, 120),
                "bar_bg": (34, 48, 36), "cpu": (120, 230, 120), "ram": (90, 200, 220), "gpu": (230, 200, 90),
                "disk": (180, 190, 180), "warn": (240, 190, 60), "crit": (255, 90, 80)}
    if theme_id == "planet":
        accent = PLANET_ACCENTS.get(settings.get("planet_accent"), PLANET_ACCENTS["blue"])
        return {"bg": (4, 10, 22), "text": (220, 235, 255), "muted": (110, 135, 170), "accent": accent,
                "bar_bg": (18, 30, 52), "cpu": accent, "ram": accent, "gpu": accent, "disk": accent,
                "warn": (255, 190, 70), "crit": (255, 90, 90)}
    if theme_id == "old_computer":
        bg, ink = OC_PALETTES.get(settings.get("oc_scheme"), OC_PALETTES["classic"])
        dark = sum(bg) < 300
        text = (255, 220, 120) if dark else (0, 0, 0)
        return {"bg": bg, "text": text, "muted": ink, "accent": ink, "bar_bg": tuple(max(0, c - 40) for c in bg),
                "cpu": (0, 128, 0), "ram": (0, 0, 160), "gpu": (128, 0, 128), "disk": (90, 90, 90),
                "warn": (190, 120, 0), "crit": (200, 0, 0)}
    from .dashboard import SCHEMES
    scheme = SCHEMES.get(settings.get("std_scheme"), SCHEMES["dark"])
    return {key: scheme[key] for key in ("bg", "text", "muted", "accent", "bar_bg", "cpu", "ram", "gpu", "disk",
                                         "warn", "crit")}


def _metrics(stats):
    gpus = stats.get("gpus") or []
    items = [("CPU", stats.get("cpu_percent", 0.0), "cpu"), ("RAM", stats.get("ram_percent", 0.0), "ram")]
    if gpus and gpus[0].get("path"):
        items.append(("GPU", gpus[0].get("percent") or 0.0, "gpu"))
    items.append((_("DISK"), stats.get("disk_percent", 0.0), "disk"))
    return items


def _bar_color(colors, key, value):
    return colors["crit"] if value >= 90 else colors["warn"] if value >= 75 else colors[key]


def render(width, height, settings, theme_id="standard", stats=None):
    stats = stats if stats is not None else telemetry.snapshot()
    colors = palette(theme_id, settings)
    image = Image.new("RGB", (width, height), colors["bg"])
    draw = ImageDraw.Draw(image)
    clock = time.strftime("%H:%M")
    portrait = height > width
    metrics = _metrics(stats)[:4 if portrait else 3]
    pad = max(2, min(width, height) // 24)
    clock_h = int(height * (0.2 if portrait else 0.34))
    font = ui_font(max(9, int(clock_h * 0.86)), bold=True)
    while font.size > 9 and draw.textlength(clock, font=font) > width - 2 * pad:
        font = ui_font(font.size - 1, bold=True)
    draw.text(((width - draw.textlength(clock, font=font)) / 2, pad // 2), clock, font=font, fill=colors["accent"])
    temp = stats.get("cpu_temp_value")
    top = pad // 2 + clock_h + pad // 2
    rows = len(metrics)
    row_h = max(10, (height - top - pad) // rows)
    label_font = ui_font(max(8, min(int(row_h * (0.42 if portrait else 0.62)), 22)), bold=True)
    for index, (label, value, key) in enumerate(metrics):
        y = top + index * row_h
        value = max(0.0, min(100.0, float(value or 0)))
        text = f"{value:.0f}%"
        if key == "cpu" and temp is not None and not portrait:
            text = f"{value:.0f}% {temp:.0f}°"
        if portrait:
            draw.text((pad, y), label, font=label_font, fill=colors["text"])
            draw.text((width - pad - draw.textlength(text, font=label_font), y), text, font=label_font,
                      fill=colors["text"])
            bar_y = y + label_font.size + 2
            bar_h = max(3, row_h - label_font.size - 5)
            bar_x0, bar_x1 = pad, width - pad
        else:
            label_w = draw.textlength("RAM ", font=label_font)
            text_w = draw.textlength("100% 99°", font=label_font) if key == "cpu" and temp is not None else \
                draw.textlength("100%", font=label_font)
            draw.text((pad, y), label, font=label_font, fill=colors["text"])
            draw.text((width - pad - draw.textlength(text, font=label_font), y), text, font=label_font,
                      fill=colors["text"])
            bar_x0, bar_x1 = pad + label_w, width - pad - text_w - pad
            bar_h = max(3, int(row_h * 0.5))
            bar_y = y + (label_font.size - bar_h) // 2 + 1
        if bar_x1 - bar_x0 > 4:
            draw.rectangle((bar_x0, bar_y, bar_x1, bar_y + bar_h), fill=colors["bar_bg"])
            fill_x = bar_x0 + int((bar_x1 - bar_x0) * value / 100)
            if fill_x > bar_x0:
                draw.rectangle((bar_x0, bar_y, fill_x, bar_y + bar_h), fill=_bar_color(colors, key, value))
    return image
