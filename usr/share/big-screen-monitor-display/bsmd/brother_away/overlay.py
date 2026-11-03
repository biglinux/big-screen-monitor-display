"""Native-resolution overlays: MangoHud-style telemetry HUD and speech bubbles.

Drawn after the nearest-neighbour upscale so text stays crisp. Values come
from the shared telemetry snapshot (no extra sensor queries); missing data is
shown as "--" instead of invented numbers.
"""

import textwrap
from datetime import datetime

from PIL import Image, ImageDraw

from ..themes import ui_font

LABEL_COLORS = {
    "CPU": (64, 196, 196),
    "RAM": (226, 148, 186),
    "DISK": (150, 180, 240),
    "GPU": (96, 206, 128),
}
VALUE = (245, 245, 245)
UNIT = (170, 176, 186)
CLOCK = (255, 255, 255)
WARN = (255, 200, 90)
CRIT = (255, 110, 110)


def _temp_color(value):
    if value is None:
        return UNIT
    if value >= 85:
        return CRIT
    if value >= 70:
        return WARN
    return VALUE


def _rows(stats, settings):
    rows = []
    if settings.get("overlay_show_cpu", True):
        temp = stats.get("cpu_temp_value")
        rows.append(("CPU", f"{stats.get('cpu_percent', 0):.0f}%" if stats.get("valid") else "--",
                     f"{temp:.0f}°C" if temp else "--°C", _temp_color(temp)))
    if settings.get("overlay_show_ram", True):
        total = stats.get("ram_total_mb", 0) / 1024
        used = stats.get("ram_used_mb", 0) / 1024
        rows.append(("RAM", f"{used:.1f}/{total:.0f}" if total else "--", "GB", UNIT))
    if settings.get("overlay_show_disk", True):
        percent = stats.get("disk_percent")
        rows.append(("DISK", f"{percent:.0f}%" if percent else "--", "", UNIT))
    if settings.get("overlay_show_gpu", True):
        gpus = stats.get("gpus") or []
        gpu = gpus[stats.get("active_gpu_idx", 0) % len(gpus)] if gpus else None
        if gpu and gpu.get("path"):
            temp = gpu.get("temp_value")
            rows.append(("GPU", f"{gpu.get('percent', 0):.0f}%", f"{temp:.0f}°C" if temp else "--°C",
                         _temp_color(temp)))
        else:
            rows.append(("GPU", "--", "", UNIT))
    return rows


def hud_rect(width, height, settings, stats, dim=False):
    """Compute the HUD rectangle (used to keep speech bubbles away from it)."""
    return _layout(width, height, settings, stats, dim)[0]


def _layout(width, height, settings, stats, dim):
    compact = settings.get("overlay_size") == "compact" or dim
    base = min(width, height)
    margin = max(4, base // 60)
    rows = _rows(stats, settings)
    size = max(8, int(base / (26 if compact else 21)))
    while True:
        # Shrink until the HUD fits the panel; on tiny panels drop the unit
        # column (temperatures) before going below a readable size.
        layout = _measure(size, compact, rows, settings)
        if layout[0] <= width - 2 * margin:
            break
        if size > 7:
            size -= 1
        elif any(unit for _, _, unit, _ in rows):
            rows = [(label, value, "", color) for label, value, _unit, color in rows]
        else:
            break
    w, h, font, clock_font, pad, line_h, label_w, value_w, clock_h = layout
    position = settings.get("overlay_position", "top_left")
    x = margin if position.endswith("left") else width - w - margin
    y = margin if position.startswith("top") else height - h - margin
    return (x, y, x + w, y + h), font, clock_font, rows, pad, line_h, label_w, value_w, clock_h


def _measure(size, compact, rows, settings):
    font = ui_font(size, bold=True)
    clock_font = ui_font(int(size * (1.1 if compact else 1.35)), bold=True)
    pad = max(3, size // 3)
    line_h = size + max(1, size // 4)
    label_w = max((font.getlength(label) for label, *_ in rows), default=0) + pad
    value_w = max((font.getlength(value) for _, value, *_ in rows), default=0) + pad
    unit_w = max((font.getlength(unit) for _, _, unit, _ in rows), default=0)
    show_clock = settings.get("overlay_show_clock", True)
    clock_h = int(clock_font.size * 1.15) if show_clock else 0
    clock_w = clock_font.getlength("00:00:00") if show_clock else 0
    w = int(max(label_w + value_w + unit_w, clock_w) + pad * 2)
    h = int(clock_h + line_h * len(rows) + pad * 2 - (max(1, size // 4) if rows else 0))
    return w, h, font, clock_font, pad, line_h, label_w, value_w, clock_h


def draw_hud(image, settings, stats, now=None, dim=False):
    if not settings.get("overlay_enabled", True):
        return None
    width, height = image.size
    rect, font, clock_font, rows, pad, line_h, label_w, value_w, clock_h = _layout(width, height, settings,
                                                                                  stats, dim)
    opacity = settings.get("overlay_opacity", 72) / 100
    if dim:
        opacity *= 0.55
    x0, y0, x1, y1 = rect
    if opacity > 0:
        region = image.crop(rect).convert("RGBA")
        shade = Image.new("RGBA", region.size, (0, 0, 0, 0))
        ImageDraw.Draw(shade).rounded_rectangle((0, 0, region.width - 1, region.height - 1),
                                                radius=max(2, pad), fill=(8, 10, 16, int(255 * opacity)))
        image.paste(Image.alpha_composite(region, shade).convert("RGB"), rect[:2])
    d = ImageDraw.Draw(image)
    y = y0 + pad
    if settings.get("overlay_show_clock", True):
        d.text((x0 + pad, y - max(1, clock_font.size // 10)), (now or datetime.now()).strftime("%H:%M:%S"),
               font=clock_font, fill=CLOCK)
        y += clock_h
    for label, value, unit, unit_color in rows:
        d.text((x0 + pad, y), label, font=font, fill=LABEL_COLORS[label])
        d.text((x0 + pad + label_w, y), value, font=font, fill=VALUE)
        if unit:
            d.text((x0 + pad + label_w + value_w, y), unit, font=font, fill=unit_color)
        y += line_h
    return rect


def _overlap(a, b):
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def draw_bubble(image, text, anchor, avoid=None, scale=2, tail=True, color=(255, 255, 255)):
    """Speech bubble pointing at ``anchor`` (native coordinates)."""
    width, height = image.size
    size = max(10, int(min(width, height) / 22))
    while True:
        font = ui_font(size, bold=True)
        pad = max(4, size // 2) if width >= 160 else max(2, size // 3)
        max_chars = max(14, int(width * 0.42 / (size * 0.58))) if width >= 240 else \
            max(5, int((width - 8 - pad * 2) / (size * 0.62)))
        lines = textwrap.wrap(text, max_chars) or [text]
        text_w = max(font.getlength(line) for line in lines)
        if text_w + pad * 2 <= width - 8 or size <= 7:
            break
        size -= 1      # narrow panels (WeAct 0.96"): smaller type instead of a clipped bubble
    line_h = size + size // 4
    bw, bh = int(text_w + pad * 2), int(line_h * len(lines) + pad * 2 - size // 4)
    ax, ay = anchor
    gap = max(6, scale * 4)
    x = int(min(max(4, ax - bw // 2), width - bw - 4))
    y = int(ay - bh - gap)
    if y < 4:
        y = 4
    rect = (x, y, x + bw, y + bh)
    if avoid and _overlap(rect, avoid):
        # Prefer sliding right of the HUD, otherwise below it.
        alt_x = avoid[2] + 6
        if alt_x + bw <= width - 4:
            x = alt_x
        else:
            y = avoid[3] + 6
        rect = (x, y, x + bw, y + bh)
    d = ImageDraw.Draw(image)
    outline = (20, 16, 14)
    border = max(1, scale // 2)
    d.rounded_rectangle(rect, radius=pad, fill=color, outline=outline, width=border)
    if tail and ay > rect[3]:
        tx = min(max(ax, rect[0] + pad * 2), rect[2] - pad * 2)
        d.polygon([(tx - pad // 2 - 2, rect[3] - border), (tx + pad // 2 + 2, rect[3] - border),
                   (ax, min(ay - 2, rect[3] + gap))], fill=color)
        d.line([(tx - pad // 2 - 2, rect[3]), (ax, min(ay - 2, rect[3] + gap)),
                (tx + pad // 2 + 2, rect[3])], fill=outline, width=border)
    ty = rect[1] + pad - max(1, size // 8)
    for line in lines:
        lw = font.getlength(line)
        d.text((rect[0] + (bw - lw) / 2, ty), line, font=font, fill=(24, 20, 18))
        ty += line_h
    return rect


def draw_floater(image, text, center, scale, color=(255, 255, 255)):
    """Small outlined text above the scene ("z", "!!", "HA HA")."""
    size = max(10, int(min(image.size) / 20))
    font = ui_font(size, bold=True)
    d = ImageDraw.Draw(image)
    w = font.getlength(text)
    x, y = center[0] - w / 2, center[1] - size
    stroke = max(1, scale // 2)
    d.text((x, y), text, font=font, fill=color, stroke_width=stroke, stroke_fill=(20, 16, 14))
