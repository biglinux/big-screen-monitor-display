"""Drawings of a DeepCool cooler's display face for the configuration window.

These images are *representations* of what the firmware draws from the
values in a :class:`metrics.Frame` - they are never sent to a cooler (the
numeric models have no framebuffer). The layout follows the field order of
each family; exact fonts and spacing of the real hardware are not imitated.
"""

from PIL import Image, ImageDraw

from ...i18n import _
from ...kojiro.draw import font, seven_segment
from .models import FREQ, GPU_TEMP, POWER, RAM, TEMP, USAGE

BG = (14, 15, 18)
FACE = (24, 26, 31)
LIT = (232, 240, 255)
DIM = (52, 56, 66)
ACCENT = (64, 170, 255)
ALARM = (255, 70, 60)
LABEL = (150, 160, 178)
SHORT = {TEMP: "TEMP", USAGE: "USAGE", POWER: "POWER", FREQ: "FREQ", RAM: "RAM", GPU_TEMP: "GPU"}


def _number(metric, value, frame, digits=3):
    if value is None:
        return "-" * digits
    if metric == FREQ:
        return f"{int(round(value)):4d}"[-4:]
    limit = 10 ** digits - 1
    return f"{min(limit, max(0, int(round(value)))):{digits}d}"


def _digits(image, xy, text, size, color):
    """Segment digits; unlit segments are translucent, so they go on an overlay."""
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    seven_segment(layer, xy, text, size, color, anchor="mm")
    image.paste(layer, (0, 0), layer)


def _unit(metric, frame):
    if metric == TEMP:
        return "°F" if frame.fahrenheit else "°C"
    return {USAGE: "%", POWER: "W", FREQ: "MHz", RAM: "%", GPU_TEMP: "°C"}.get(metric, "")


def render(family, frame, size=(480, 300), demo=False):
    width, height = size
    image = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(image)
    pad = max(6, width // 30)
    draw.rounded_rectangle((pad, pad, width - pad, height - pad), radius=max(8, width // 22), fill=FACE)
    if family.display == "lcd":
        _render_lcd(image, family, frame, (pad * 2, pad * 2, width - pad * 2, height - pad * 2))
    elif family.layout == "single":
        _render_single(image, family, frame, (pad * 2, pad * 2, width - pad * 2, height - pad * 2))
    else:
        _render_fixed(image, family, frame, (pad * 2, pad * 2, width - pad * 2, height - pad * 2))
    if demo:
        label = _("DEMO")
        small = font("default", max(10, height // 16), True)
        box = draw.textbbox((0, 0), label, font=small)
        x, y = width - pad * 2 - (box[2] - box[0]) - 12, pad * 2
        draw.rounded_rectangle((x - 8, y - 2, x + box[2] - box[0] + 8, y + box[3] - box[1] + 8), radius=8,
                               fill=(214, 150, 20))
        draw.text((x, y), label, font=small, fill=(20, 20, 20))
    return image


def _render_single(image, family, frame, box):
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    main = frame.main
    value = frame.fields.get(main) if main else None
    text = _number(main, value, frame, family.digits)
    size = int(min(h * 0.5, w / (family.digits * 0.9 + 1.2)))
    cx, cy = x0 + w * 0.46, y0 + h * 0.42
    _digits(image, (cx, cy), text, size, LIT)
    label_font = font("default", max(10, int(size * 0.24)), True)
    labels = list(family.main_choices)
    lx = x0 + w * 0.84
    for index, metric in enumerate(labels):
        on = metric == main
        ly = y0 + h * (0.22 + index * 0.22)
        draw.text((lx, ly), _unit(metric, frame) if metric != USAGE else "%", font=label_font,
                  fill=ACCENT if on else DIM, anchor="mm")
        draw.text((lx, ly + size * 0.2), SHORT[metric], font=font("default", max(8, int(size * 0.13)), False),
                  fill=LABEL if on else DIM, anchor="mm")
    if family.status_bar:
        usage = frame.fields.get(USAGE + "_bar") or 0
        lit = 1 if usage < 15 else max(1, min(10, int(usage / 10 + 0.5)))
        bw = w * 0.8 / 10
        by = y0 + h * 0.82
        for i in range(10):
            bx = x0 + w * 0.06 + i * bw
            draw.rounded_rectangle((bx + 2, by, bx + bw - 3, by + h * 0.07), radius=3,
                                   fill=ACCENT if i < lit else DIM)
    if family.software_alarm:
        lamp = (x1 - w * 0.06, y0 + h * 0.86)
        r = max(5, h * 0.04)
        draw.ellipse((lamp[0] - r, lamp[1] - r, lamp[0] + r, lamp[1] + r), fill=ALARM if frame.alarm else DIM)


def _render_fixed(image, family, frame, box):
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    metrics_ = family.fields
    columns = 2 if len(metrics_) == 4 else len(metrics_)
    rows = (len(metrics_) + columns - 1) // columns
    cw, ch = w / columns, h / rows
    for index, metric in enumerate(metrics_):
        cx = x0 + (index % columns + 0.5) * cw
        cy = y0 + (index // columns + 0.42) * ch
        value = frame.fields.get(metric)
        digits = 4 if metric == FREQ else 3
        size = int(min(ch * 0.46, cw / (digits * 0.95 + 0.6)))
        missing = metric in frame.missing
        _digits(image, (cx, cy), _number(metric, 0 if missing else value, frame, digits), size,
                DIM if missing else LIT)
        caption = f"{SHORT[metric]} {_unit(metric, frame)}"
        draw.text((cx, cy + size * 0.78), caption, font=font("default", max(9, int(size * 0.24)), True),
                  fill=ALARM if missing else LABEL, anchor="mm")


def _render_lcd(image, family, frame, box):
    """MYSTIQUE information screen (approximation of the firmware's own layout)."""
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    panel_h = h
    panel_w = panel_h * 3 / 4
    px0 = x0 + (w - panel_w) / 2
    draw.rounded_rectangle((px0, y0, px0 + panel_w, y1), radius=10, fill=(8, 9, 12), outline=DIM)
    rows = ((TEMP, "CPU"), (USAGE, "CPU"), (FREQ, "CPU"), (RAM, "RAM"), (GPU_TEMP, "GPU"))
    line = panel_h / (len(rows) + 0.6)
    big = font("default", max(10, int(line * 0.46)), True)
    small = font("default", max(8, int(line * 0.22)), False)
    for index, (metric, label) in enumerate(rows):
        y = y0 + line * (index + 0.8)
        value = frame.fields.get(metric)
        missing = metric in frame.missing
        if metric == FREQ:
            text = "--" if value is None else f"{value / 1000:.2f}"
            unit = "GHz"
        else:
            text = "--" if value is None or missing else f"{int(round(value))}"
            unit = _unit(metric, frame)
        draw.text((px0 + panel_w * 0.1, y), label, font=small, fill=LABEL, anchor="lm")
        draw.text((px0 + panel_w * 0.62, y), text, font=big, fill=ALARM if missing else LIT, anchor="rm")
        draw.text((px0 + panel_w * 0.66, y), unit, font=small, fill=ACCENT, anchor="lm")
