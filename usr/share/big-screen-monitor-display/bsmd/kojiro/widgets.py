"""Kojiro widget renderers.

``render(widget, metric, size, theme, state)`` returns an RGBA layer and the
padding around the widget box (room for glow and shadow). Each widget is
drawn supersampled on two layers - an optional background panel and the
foreground - so only the foreground gets the neon glow. Text never goes
below ``draw.MIN_FONT``: when a box is too small, secondary lines are dropped
instead of shrinking them into unreadable pixels.
"""

import math

from PIL import Image, ImageDraw

from . import draw as d

WARN_RGB, CRIT_RGB = (255, 217, 74), (255, 71, 92)


def alert_color(base, level):
    """Gradual base -> yellow -> red as the alert level goes 0 -> 1 -> 2."""
    if level <= 0:
        return base
    if level <= 1:
        return d.mix(base, WARN_RGB, level)
    return d.mix(WARN_RGB, CRIT_RGB, level - 1)


class Painter:
    def __init__(self, widget, theme, size, ss, state):
        self.widget = widget
        self.theme = theme
        self.ss = ss
        self.w, self.h = size[0] * ss, size[1] * ss
        self.state = state
        self.fg = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.fg)
        level = state.get("alert", 0.0)
        self.color = (*alert_color(d.rgb(widget["color"]), level), 255)
        self.color2 = (*d.rgb(widget["color2"]), 255)
        self.text_color = (*d.rgb(widget["text_color"]), 255)
        self.muted = (*d.rgb(widget["text_color"]), 170)
        self.track = (*d.rgb(widget["color"])[:3], 48)
        self.family = d.resolve_family(widget.get("font", "default"), theme.get("font", "default"),
                                       widget.get("text_style", "normal"))
        self.style = widget.get("text_style", "normal")
        self.bold = widget.get("bold", True)
        self.scale = widget.get("font_scale", 100) / 100

    # -- text
    def px(self, value):
        return value * self.ss

    def size(self, nominal):
        """Font size in layer pixels; None when it would be unreadable."""
        size = nominal * self.scale
        return size if size >= d.MIN_FONT * self.ss else None

    def text(self, xy, text, nominal, color=None, anchor="la", max_width=None, bold=None, style=None):
        size = self.size(nominal)
        if size is None or not text:
            return 0
        return d.draw_text(self.fg, xy, text, size, color or self.text_color, self.family,
                           self.bold if bold is None else bold, style or self.style, anchor, max_width)

    def value_text(self, xy, text, nominal, color=None, anchor="la", max_width=None):
        """Big numbers: honour the digital style."""
        return self.text(xy, text, nominal, color, anchor, max_width)

    def icon(self, name, size, xy, color=None):
        if not self.widget.get("show_icon", True):
            return 0
        image = d.icon(name, size, color or self.color)
        if image is not None:
            self.fg.alpha_composite(image, (int(xy[0]), int(xy[1])))
            return image.width
        return 0

    def title_text(self, metric):
        if not self.widget.get("show_label", True):
            return ""
        return metric.title


ICONS = {"cpu": "cpu", "gpu": "gpu", "ram": "ram", "swap": "swap", "vram": "gpu", "disk": "disk",
         "encdec": "encdec", "net_down": "rx", "net_up": "tx", "processes": "process"}


# ---------------------------------------------------------------- circular

def circular(p, m, style):
    w, h = p.w, p.h
    side_layout = w >= h * 1.45
    side = min(h, w * 0.5) if side_layout else min(w, h)
    left = 0 if side_layout else (w - side) / 2
    top = (h - side) / 2
    cx, cy = left + side / 2, top + side / 2
    thickness = side * (0.07 if style == "double" else 0.085)
    radius = side / 2 - thickness / 2 - p.px(2)
    if style == "semi":
        cy = top + side * 0.66
        radius = min(side / 2 - thickness, side * 0.6 - thickness) * 0.98
    fraction = m.fraction if m.available else 0.0
    d.ring(p.draw, (cx, cy), radius + thickness / 2, thickness, fraction, p.color, style, p.track,
           m.fraction2, p.color2)
    if style == "gauge":
        d.gauge_ticks(p.draw, (cx, cy), radius - thickness * 1.3, (*p.color[:3], 150), width=max(1, int(p.px(1.5))))
        if m.available:
            d.needle(p.draw, (cx, cy), radius - thickness * 1.6, fraction, p.text_color, width=max(2, p.px(2)))
    title = p.title_text(m)
    inner = radius - thickness
    big_size = inner * (0.5 if style != "gauge" else 0.36)
    lines = list(m.lines)
    if side_layout:
        tx = left + side + p.px(8)
        avail = w - tx
        y = top + side * 0.12
        if title:
            p.text((tx, y), title, side * 0.17, p.color, max_width=avail)
            y += side * 0.22
        p.value_text((tx, y), m.big if m.available else "—", side * 0.26, p.text_color, max_width=avail)
        y += side * 0.32
        for index, (_name, value) in enumerate(lines[:3]):
            p.text((tx, y), value, side * 0.14, p.color2 if index == 0 else p.muted, bold=False, max_width=avail)
            y += side * 0.17
        return
    if style == "gauge":
        p.value_text((cx, cy + inner * 0.42), m.big if m.available else "—", big_size, p.text_color, "mm",
                     max_width=inner * 1.3)
        if title:
            p.text((cx, cy - inner * 0.36), title, inner * 0.2, p.color, "mm", max_width=inner * 1.2)
        if lines:
            p.text((cx, cy + inner * 0.78), lines[0][1], inner * 0.17, p.color2, "mm", bold=False,
                   max_width=inner * 1.4)
        return
    if style == "semi":
        p.value_text((cx, cy - inner * 0.18), m.big if m.available else "—", big_size * 0.9, p.text_color, "ms",
                     max_width=inner * 1.6)
        if title:
            p.text((cx, cy - inner * 0.72), title, inner * 0.2, p.color, "mm", max_width=inner * 1.4)
        y = cy + inner * 0.08
        for index, (_name, value) in enumerate(lines[:2]):
            p.text((cx, y), value, inner * 0.18, p.color2 if index == 0 else p.muted, "ma", bold=False,
                   max_width=side * 0.9)
            y += inner * 0.24
        return
    # ring / arc / double: title, value and lines stacked in the centre
    rows = []
    if title:
        rows.append((title, inner * 0.22, p.color, True))
    rows.append((m.big if m.available else "—", big_size, p.text_color, True))
    for index, (_name, value) in enumerate(lines[:2]):
        rows.append((value, inner * 0.2, p.color2 if index == 0 else p.muted, False))
    visible = [r for r in rows if p.size(r[1])]
    total = sum(r[1] * 1.12 for r in visible)
    y = cy - total / 2
    for text, size, color, bold in visible:
        p.text((cx, y + size * 0.56), text, size, color, "mm", max_width=inner * 1.6, bold=bold)
        y += size * 1.12
    extra = lines[2:3] if len(lines) > 2 else []
    if extra and h > side * 1.05:
        p.text((cx, top + side + p.px(2)), extra[0][1], side * 0.11, p.muted, "ma", bold=False, max_width=w)


# ---------------------------------------------------------------- linear

def linear(p, m, style):
    w, h = p.w, p.h
    title = p.title_text(m)
    row_h = min(h * 0.42, w * 0.085)
    bar_h = min(h * 0.3, row_h * 0.85)
    block = row_h + bar_h + row_h * 0.25
    top = max(0, (h - block) / 2)
    x = 0
    icon_name = ICONS.get(p.widget["type"])
    mid = top + row_h * 0.5
    if icon_name and p.widget.get("show_icon", True) and row_h >= p.px(10):
        x += p.icon(icon_name, row_h * 0.95, (0, top + row_h * 0.02)) + p.px(5)
    if title:
        x += p.text((x, mid), title, row_h * 0.86, p.color, "lm") + p.px(8)
    right = m.big if m.available else "—"
    right_w = p.text((w, mid), right, row_h * 0.86, p.text_color, "rm") if right else 0
    if m.lines and m.available:
        p.text((x, mid), m.lines[0][1], row_h * 0.62, p.muted, "lm", bold=False,
               max_width=max(0, w - x - right_w - p.px(8)))
    if not m.available and m.extra.get("no_swap"):
        return
    bar_top = top + row_h * 1.25
    box = (0, bar_top, w, bar_top + bar_h)
    d.bar_h(p.draw, box, m.fraction if m.available else 0, p.color, style, p.track, p.color2)


def vertical(p, m, style):
    w, h = p.w, p.h
    title = p.title_text(m)
    bar_w = min(w * 0.3, h * 0.22)
    label_h = h * 0.16
    box = (p.px(2), label_h * 1.2 if title else 0, p.px(2) + bar_w, h - label_h * 1.3)
    d.bar_v(p.draw, box, m.fraction if m.available else 0, p.color, style, p.track)
    tx = box[2] + p.px(8)
    if title:
        p.text((0, 0), title, label_h, p.color)
    p.value_text((tx, h * 0.35), m.big if m.available else "—", h * 0.2, p.text_color, max_width=w - tx)
    y = h * 0.6
    for _name, value in m.lines[:2]:
        p.text((tx, y), value, h * 0.12, p.muted, bold=False, max_width=w - tx)
        y += h * 0.15
    p.text((w / 2, h), "", 1)


def graph_style(p, m, style):
    w, h = p.w, p.h
    title = p.title_text(m)
    head = h * 0.32
    x = 0
    if p.widget["type"] in ("net_down", "net_up"):
        d.arrow(p.draw, (0, head * 0.1, head * 0.7, head * 0.95), p.color, up=p.widget["type"] == "net_up")
        x = head * 0.85
    if title:
        x += p.text((x, head * 0.5), title, head * 0.78, p.color, "lm") + p.px(8)
    p.value_text((w, head * 0.5), m.big if m.available else "—", head * 0.78, p.text_color, "rm",
                 max_width=w - x)
    if m.history:
        d.graph(p.draw, (0, head + p.px(4), w, h - p.px(1)), m.history, p.color, style, m.history_max,
                width=max(1, int(p.px(1.6))))
    else:
        p.draw.line((0, h - p.px(1), w, h - p.px(1)), fill=p.track, width=max(1, int(p.px(1))))


def text_style(p, m, _style=None):
    w, h = p.w, p.h
    title = p.title_text(m)
    align = p.widget.get("align", "left")
    anchor_x = {"left": 0, "center": w / 2, "right": w}[align]
    anchor = {"left": "l", "center": "m", "right": "r"}[align]
    lines = [value for _name, value in m.lines] if m.available else []
    is_net = p.widget["type"] in ("net_down", "net_up")
    if lines and h < w * 0.3 and not is_net:
        # Wide, short box: everything on one row.
        x, mid = 0, h / 2
        if ICONS.get(p.widget["type"]) and p.widget.get("show_icon", True):
            x += p.icon(ICONS[p.widget["type"]], h * 0.7, (0, h * 0.15)) + p.px(6)
        if title:
            x += p.text((x, mid), title, h * 0.5, p.color, "lm") + p.px(8)
        x += p.value_text((x, mid), m.big if m.available else "—", h * 0.58, p.text_color, "lm") + p.px(10)
        for index, value in enumerate(lines[:2]):
            if x >= w - p.px(10):
                break
            x += p.text((x, mid), value, h * 0.4, p.color2 if index == 0 else p.muted, "lm", bold=False,
                        max_width=w - x) + p.px(10)
        return
    if is_net or (title and not lines and h < w * 0.45):
        # One row: [arrow/icon] TITLE value
        x = 0
        mid = h / 2
        if is_net:
            d.arrow(p.draw, (0, h * 0.15, h * 0.62, h * 0.85), p.color, up=p.widget["type"] == "net_up")
            x = h * 0.78
        elif ICONS.get(p.widget["type"]) and p.widget.get("show_icon", True):
            x += p.icon(ICONS[p.widget["type"]], h * 0.7, (0, h * 0.15)) + p.px(6)
        if title:
            x += p.text((x, mid), title, h * 0.5, p.color, "lm") + p.px(8)
        value = m.big if m.available else "—"
        if align == "right" or is_net:
            p.value_text((w, mid), value, h * 0.55, p.text_color, "rm", max_width=w - x)
        else:
            p.value_text((x, mid), value, h * 0.55, p.text_color, "lm", max_width=w - x)
        return
    rows = []
    if title:
        rows.append((title, 0.26, p.color, True))
    rows.append((m.big if m.available else "—", 0.42 if lines else 0.6, p.text_color, True))
    for index, value in enumerate(lines[:3]):
        rows.append((value, 0.2, p.color2 if index == 0 else p.muted, False))
    weights = sum(r[1] for r in rows)
    unit = h / max(weights * 1.12, 1e-6)
    y = 0
    for text, weight, color, bold in rows:
        size = unit * weight
        if p.size(size):
            p.text((anchor_x, y + size * 0.56), text, size, color, anchor + "m", max_width=w, bold=bold)
        y += size * 1.12


def hud(p, m, _style=None):
    w, h = p.w, p.h
    d.panel(p.draw, (p.px(1), p.px(1), w - p.px(1), h - p.px(1)), 0, None, (*p.color[:3], 210),
            max(1, int(p.px(1.5))), cut=True)
    title = p.title_text(m)
    pad = min(w, h) * 0.12
    y = pad * 0.7
    if title:
        p.text((pad, y), title, h * 0.18, p.color)
    p.value_text((w - pad, y), m.big if m.available else "—", h * 0.3, p.text_color, "ra", max_width=w * 0.6)
    ly = y + h * 0.36
    for _name, value in m.lines[:2]:
        p.text((pad, ly), value, h * 0.14, p.muted, bold=False, max_width=w - 2 * pad)
        ly += h * 0.17
    bar = (pad, h - pad * 0.9 - h * 0.07, w - pad, h - pad * 0.9)
    d.bar_h(p.draw, bar, m.fraction if m.available else 0, p.color, "bar", p.track)


# ---------------------------------------------------------------- special widgets

def fan(p, m, style):
    if style == "ring":
        return circular(p, m, "ring")
    if style == "text":
        return text_style(p, m)
    w, h = p.w, p.h
    side = min(h, w * 0.45)
    spin = p.widget.get("opts", {}).get("spin", True)
    angle = p.state.get("fan_angle", 0.0) if spin else 0.0
    if p.widget.get("show_icon", True):
        icon = d.fan_icon(int(side), p.color, angle)
        p.fg.alpha_composite(icon, (0, int((h - side) / 2)))
    tx = side + p.px(8) if p.widget.get("show_icon", True) else 0
    title = p.title_text(m)
    y = h * 0.08
    if title:
        p.text((tx, y), title, h * 0.26, p.color, max_width=w - tx)
        y += h * 0.32
    p.value_text((tx, y), m.big if m.available else "—", h * 0.32, p.text_color, max_width=w - tx)
    y += h * 0.38
    if m.lines and m.available:
        p.text((tx, y), m.lines[0][1], h * 0.2, p.muted, bold=False, max_width=w - tx)


def clock(p, m, style):
    w, h = p.w, p.h
    has_date = bool(m.lines)
    time_h = h * (0.5 if has_date else 0.66)
    align = p.widget.get("align", "center")
    cx = {"left": p.px(4), "center": w / 2, "right": w - p.px(4)}[align]
    anchor = {"left": "l", "center": "m", "right": "r"}[align]
    if style == "frame":
        inset = p.px(2)
        t = max(1, int(p.px(1.6)))
        c = h * 0.22
        points = [(inset + c, inset), (w - inset - c, inset), (w - inset, inset + c), (w - inset, h - inset - c),
                  (w - inset - c, h - inset), (inset + c, h - inset), (inset, h - inset - c), (inset, inset + c),
                  (inset + c, inset)]
        p.draw.line(points, fill=p.color, width=t, joint="curve")
        tick = w * 0.12
        p.draw.line((w / 2 - tick, inset + t * 2.5, w / 2 + tick, inset + t * 2.5), fill=p.color, width=t)
        p.draw.line((w / 2 - tick, h - inset - t * 2.5, w / 2 + tick, h - inset - t * 2.5), fill=p.color, width=t)
        time_h *= 0.86
    text = m.big
    colon_on = m.extra.get("colon", True)
    style_name = "digital" if style == "digital" else p.style
    ty = h * (0.42 if has_date else 0.5)
    size = p.size(time_h)
    if size:
        max_w = w * 0.86
        if style_name == "digital":
            d.draw_text(p.fg, (cx, ty), text if colon_on else text.replace(":", ";"), size, p.text_color, p.family,
                        p.bold, style_name, anchor + "m", max_w)
        elif colon_on:
            d.draw_text(p.fg, (cx, ty), text, size, p.text_color, p.family, p.bold, style_name, anchor + "m", max_w)
        else:
            # Same layout as with the colon (digits never jump), colon drawn faint.
            layer = Image.new("RGBA", p.fg.size, (0, 0, 0, 0))
            d.draw_text(layer, (cx, ty), text, size, p.text_color, p.family, p.bold, style_name, anchor + "m", max_w)
            faint = Image.new("RGBA", p.fg.size, (0, 0, 0, 0))
            d.draw_text(faint, (cx, ty), "".join(ch if ch == ":" else " " for ch in text), size, p.text_color,
                        p.family, p.bold, style_name, anchor + "m", max_w)
            # Remove the colon from the full text where the faint copy has it.
            from PIL import ImageChops
            mask = faint.getchannel("A")
            layer.putalpha(ImageChops.subtract(layer.getchannel("A"), mask.point(lambda v: v * 3 // 4)))
            p.fg.alpha_composite(layer)
    if has_date:
        p.text((cx, h * 0.8), m.lines[0][1], h * 0.17, p.color, anchor + "m", bold=False, max_width=w * 0.86)


def distro(p, m, style):
    from .assets import fallback_logo, load_logo
    w, h = p.w, p.h
    opts = p.widget.get("opts", {})
    show_name = style != "logo" and opts.get("show_name", True)
    show_logo = style != "name" and opts.get("logo", "auto") != "none"
    name_h = h * 0.2 if show_name and show_logo else (h * 0.6 if show_name else 0)
    if show_logo:
        side = int(min(w, h - name_h * 1.25))
        if side > 4:
            left, top = int((w - side) / 2), 0
            if opts.get("circle", True):
                ring_w = max(1, int(side * 0.035))
                p.draw.ellipse((left, top, left + side, top + side), fill=(10, 14, 26, 170), outline=p.color,
                               width=ring_w)
                inner = int(side * 0.66)
            else:
                inner = side
            logo = load_logo(m.extra.get("logo"), inner) or fallback_logo(inner, p.color)
            p.fg.alpha_composite(logo, (int(left + (side - logo.width) / 2), int(top + (side - logo.height) / 2)))
    if show_name:
        y = h - name_h * 0.55 if show_logo else h / 2
        align = p.widget.get("align", "center")
        x = {"left": 0, "center": w / 2, "right": w}[align]
        p.text((x, y), m.big, name_h * 0.8, p.text_color, {"left": "l", "center": "m", "right": "r"}[align] + "m",
               max_width=w)


def cores(p, m, style):
    w, h = p.w, p.h
    title = p.title_text(m)
    top = h * 0.24 if title else 0
    if title:
        p.text((0, 0), title, h * 0.18, p.color)
    values = m.extra.get("cores", ())
    if not values:
        p.text((0, top), "—", h * 0.3, p.muted)
        return
    if style == "grid":
        cols = math.ceil(math.sqrt(len(values) * w / max(1, h - top)))
        rows = math.ceil(len(values) / cols)
        cw, ch = w / cols, (h - top) / rows
        for i, value in enumerate(values):
            x, y = (i % cols) * cw, top + (i // cols) * ch
            color = (*d.mix(p.color2[:3], p.color[:3], value / 100), 255)
            p.draw.rectangle((x + p.px(1), y + p.px(1), x + cw - p.px(1), y + ch - p.px(1)), fill=color)
        return
    gap = max(1, w / len(values) * 0.25)
    bw = (w - gap * (len(values) - 1)) / len(values)
    for i, value in enumerate(values):
        x = i * (bw + gap)
        d.bar_v(p.draw, (x, top, x + bw, h), value / 100, p.color, "bar_vertical", p.track)


def processes(p, m, _style):
    w, h = p.w, p.h
    rows = m.extra.get("rows", ())
    title = p.title_text(m)
    count = max(1, len(rows) + (1 if title else 0))
    row_h = h / max(count, 3)
    y = 0
    if title:
        p.text((0, y + row_h / 2), title, row_h * 0.7, p.color, "lm")
        y += row_h
    for name, value in rows:
        p.text((w, y + row_h / 2), value, row_h * 0.62, p.color2, "rm", bold=False)
        p.text((0, y + row_h / 2), name, row_h * 0.62, p.text_color, "lm", bold=False, max_width=w * 0.72)
        y += row_h


def separator(p, m, style):
    w, h = p.w, p.h
    vertical = h > w
    t = max(1, int(min(w, h) * (0.35 if style == "glow_line" else 0.25)))
    if style == "dots":
        step = max(t * 3, p.px(6))
        length = h if vertical else w
        for i in range(int(length / step) + 1):
            c = i * step + step / 2
            x, y = (w / 2, c) if vertical else (c, h / 2)
            p.draw.ellipse((x - t / 2, y - t / 2, x + t / 2, y + t / 2), fill=p.color)
        return
    if vertical:
        p.draw.line((w / 2, 0, w / 2, h), fill=p.color, width=t)
    else:
        p.draw.line((0, h / 2, w, h / 2), fill=p.color, width=t)


def frame(p, m, style):
    w, h = p.w, p.h
    t = max(1, int(p.px(1.6)))
    inset = t
    if style == "box":
        d.panel(p.draw, (inset, inset, w - inset, h - inset), p.px(p.widget.get("radius", 12)), None, p.color, t)
        return
    if style == "hud":
        d.panel(p.draw, (inset, inset, w - inset, h - inset), 0, None, p.color, t, cut=True)
        for i in range(1, 6):
            x = w * 0.3 + i * p.px(6)
            p.draw.line((x, inset + t * 2, x, inset + t * 6), fill=p.color, width=t)
        return
    arm = min(w, h) * 0.18
    for (x, y, sx, sy) in ((inset, inset, 1, 1), (w - inset, inset, -1, 1), (inset, h - inset, 1, -1),
                           (w - inset, h - inset, -1, -1)):
        p.draw.line((x, y, x + arm * sx, y), fill=p.color, width=t * 2)
        p.draw.line((x, y, x, y + arm * sy), fill=p.color, width=t * 2)


def generic(p, m, style):
    if style in ("ring", "semi", "arc", "double", "gauge"):
        return circular(p, m, style)
    if style in ("bar", "bar_segmented", "bar_gradient"):
        return linear(p, m, style)
    if style in ("bar_vertical", "thermo"):
        return vertical(p, m, style)
    if style in ("graph_line", "graph_area", "graph_bars", "sparkline"):
        return graph_style(p, m, style)
    if style == "hud":
        return hud(p, m)
    return text_style(p, m)


SPECIAL = {"fan": fan, "clock": clock, "distro": distro, "cores": cores, "processes": processes,
           "separator": separator, "frame": frame}


# ---------------------------------------------------------------- composition

def glow_radius(widget, size):
    return max(1.5, min(size) * 0.05) * (widget.get("glow", 0) / 100) * 1.6


def render(widget, metric, size, theme, state, panel=None):
    """(RGBA layer, (pad_x, pad_y)). ``panel``: forced background (contrast assist)."""
    w, h = max(1, int(size[0])), max(1, int(size[1]))
    ss = 2 if w * h <= 220_000 else 1
    painter = Painter(widget, theme, (w, h), ss, state)
    SPECIAL.get(widget["type"], generic)(painter, metric, widget.get("style", ""))
    fg = painter.fg if ss == 1 else painter.fg.resize((w, h), Image.Resampling.LANCZOS)
    glow_strength = widget.get("glow", 0) / 100 * state.get("glow_boost", 1.0)
    radius = glow_radius(widget, (w, h))
    pad = int(math.ceil(radius * 2.2 + 3))
    layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    bg_opacity = widget.get("bg_opacity", 0)
    bg_color, bg_alpha = d.rgb(widget.get("bg", "#0A0E1A")), bg_opacity / 100
    if panel is not None and bg_opacity == 0:
        bg_color, bg_alpha = panel
    border = widget.get("border", 0)
    attention = state.get("attention", False)
    if bg_alpha > 0 or border or attention:
        bg = ImageDraw.Draw(layer)
        radius_px = min(w, h) * widget.get("radius", 12) / 100
        fill = (*bg_color, int(255 * bg_alpha)) if bg_alpha > 0 else None
        outline_color = (*alert_color(d.rgb(widget.get("border_color", "#42E8FF")), 0), 220)
        width = max(1, border)
        if attention:
            outline_color, width = (*WARN_RGB, 255), max(2, border)
        bg.rounded_rectangle((pad, pad, pad + w - 1, pad + h - 1), radius=radius_px, fill=fill,
                             outline=outline_color if (border or attention) else None, width=width)
    fg_padded = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    fg_padded.alpha_composite(fg, (pad, pad))
    if glow_strength > 0:
        fg_padded = d.glow(fg_padded, painter.color[:3], glow_strength, radius)
    if widget.get("shadow", True):
        fg_padded = d.drop_shadow(fg_padded, offset=max(1, int(min(w, h) * 0.012)), blur=max(1, int(min(w, h) * 0.015)))
    layer.alpha_composite(fg_padded)
    opacity = widget.get("opacity", 100) * state.get("alpha", 1.0)
    if opacity < 100:
        layer = d.with_opacity(layer, int(opacity))
    pad_x = pad_y = pad
    rotation = widget.get("rotation", 0)
    if rotation:
        before = layer.size
        layer = layer.rotate(-rotation, resample=Image.Resampling.BICUBIC, expand=True)
        pad_x += (layer.size[0] - before[0]) // 2      # keep the centre in place
        pad_y += (layer.size[1] - before[1]) // 2
    return layer, (pad_x, pad_y)
