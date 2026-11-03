"""Standard dashboard ("Padrão"): one layout, several colour schemes.

Replaces the former Dark, Light, Neon and Cyberpunk themes, which were the
same drawing with different colours and overlapped text at several sizes.

Every element is measured before it is drawn: labels shrink with an ellipsis,
optional pieces (temperature chips, footer items, process rows) are dropped
by priority, and font sizes derive from the space actually available. Nothing
can overlap by construction.
"""

import time
from datetime import datetime

from PIL import Image, ImageDraw

from . import legacy_themes as legacy
from .i18n import N_, _
from .telemetry import (CPU_USAGE_HISTORY, CPU_SYSTEM_HISTORY, GPU_MEM_HISTORY, GPU_USAGE_HISTORY,
                        NET_RX_HISTORY, NET_TX_HISTORY, RAM_USAGE_HISTORY, STATS_LOCK, SYSTEM_STATS)
from .themes import ui_font

# Palette keys: bg, panel, border, text, muted, accent (clock), cpu, ram, swap,
# disk, gpu, vram, rx, tx, warn, crit, bar_bg, plus panel style.
SCHEMES = {
    "dark": {
        "name": N_("Dark"), "bg": (18, 18, 25), "panel": (30, 30, 40), "border": (48, 48, 64),
        "text": (244, 245, 250), "muted": (160, 164, 186), "accent": (77, 217, 255),
        "cpu": (250, 204, 21), "ram": (77, 217, 112), "swap": (77, 150, 255), "disk": (200, 200, 210),
        "gpu": (255, 140, 80), "vram": (215, 120, 255), "rx": (77, 217, 112), "tx": (77, 150, 255),
        "warn": (249, 180, 35), "crit": (255, 85, 85), "bar_bg": (46, 46, 60), "radius": 0.035,
        "border_w": 0, "style": "round",
    },
    "light": {
        "name": N_("Light"), "bg": (231, 239, 248), "panel": (250, 252, 255), "border": (196, 210, 228),
        "text": (24, 35, 52), "muted": (88, 104, 126), "accent": (0, 105, 192),
        "cpu": (214, 134, 0), "ram": (24, 148, 91), "swap": (25, 111, 190), "disk": (102, 119, 137),
        "gpu": (214, 98, 28), "vram": (105, 76, 180), "rx": (24, 148, 91), "tx": (25, 111, 190),
        "warn": (196, 120, 0), "crit": (198, 40, 64), "bar_bg": (218, 228, 240), "radius": 0.035,
        "border_w": 1, "style": "round",
    },
    "neon": {
        "name": N_("Neon"), "bg": (10, 5, 20), "panel": (22, 10, 42), "border": (120, 50, 190),
        "text": (255, 255, 255), "muted": (255, 130, 200), "accent": (255, 0, 255),
        "cpu": (255, 255, 0), "ram": (57, 255, 20), "swap": (0, 255, 255), "disk": (190, 190, 255),
        "gpu": (255, 110, 0), "vram": (170, 60, 255), "rx": (57, 255, 20), "tx": (0, 255, 255),
        "warn": (255, 220, 0), "crit": (255, 49, 90), "bar_bg": (44, 22, 70), "radius": 0.035,
        "border_w": 1, "style": "round",
    },
    "cyberpunk": {
        "name": N_("Cyberpunk"), "bg": (4, 4, 8), "panel": (14, 14, 22), "border": (253, 237, 5),
        "text": (253, 237, 5), "muted": (160, 150, 40), "accent": (0, 240, 255),
        "cpu": (253, 237, 5), "ram": (22, 230, 120), "swap": (0, 240, 255), "disk": (200, 200, 210),
        "gpu": (255, 99, 146), "vram": (190, 80, 255), "rx": (22, 230, 120), "tx": (0, 240, 255),
        "warn": (255, 160, 0), "crit": (255, 25, 76), "bar_bg": (30, 30, 42), "radius": 0,
        "border_w": 1, "style": "cut",
    },
    "nord": {
        "name": N_("Nord"), "bg": (46, 52, 64), "panel": (59, 66, 82), "border": (67, 76, 94),
        "text": (236, 239, 244), "muted": (163, 175, 196), "accent": (136, 192, 208),
        "cpu": (235, 203, 139), "ram": (163, 190, 140), "swap": (129, 161, 193), "disk": (216, 222, 233),
        "gpu": (208, 135, 112), "vram": (180, 142, 173), "rx": (163, 190, 140), "tx": (129, 161, 193),
        "warn": (235, 203, 139), "crit": (191, 97, 106), "bar_bg": (76, 86, 106), "radius": 0.03,
        "border_w": 0, "style": "round",
    },
    "dracula": {
        "name": N_("Dracula"), "bg": (40, 42, 54), "panel": (54, 56, 74), "border": (68, 71, 90),
        "text": (248, 248, 242), "muted": (160, 168, 205), "accent": (139, 233, 253),
        "cpu": (241, 250, 140), "ram": (80, 250, 123), "swap": (139, 233, 253), "disk": (189, 147, 249),
        "gpu": (255, 184, 108), "vram": (255, 121, 198), "rx": (80, 250, 123), "tx": (139, 233, 253),
        "warn": (255, 184, 108), "crit": (255, 85, 85), "bar_bg": (68, 71, 90), "radius": 0.035,
        "border_w": 0, "style": "round",
    },
    "solarized": {
        "name": N_("Solarized"), "bg": (0, 43, 54), "panel": (7, 54, 66), "border": (21, 74, 88),
        "text": (238, 232, 213), "muted": (147, 161, 161), "accent": (42, 161, 152),
        "cpu": (181, 137, 0), "ram": (133, 153, 0), "swap": (38, 139, 210), "disk": (147, 161, 161),
        "gpu": (203, 75, 22), "vram": (108, 113, 196), "rx": (133, 153, 0), "tx": (38, 139, 210),
        "warn": (181, 137, 0), "crit": (220, 50, 47), "bar_bg": (21, 74, 88), "radius": 0.025,
        "border_w": 0, "style": "round",
    },
    "high_contrast": {
        "name": N_("High contrast"), "bg": (0, 0, 0), "panel": (0, 0, 0), "border": (255, 255, 255),
        "text": (255, 255, 255), "muted": (230, 230, 230), "accent": (255, 255, 0),
        "cpu": (255, 255, 0), "ram": (0, 255, 0), "swap": (0, 200, 255), "disk": (255, 255, 255),
        "gpu": (255, 160, 0), "vram": (255, 0, 255), "rx": (0, 255, 0), "tx": (0, 200, 255),
        "warn": (255, 200, 0), "crit": (255, 60, 60), "bar_bg": (70, 70, 70), "radius": 0,
        "border_w": 2, "style": "square",
    },
}
LEGACY_SCHEMES = ("dark", "light", "neon", "cyberpunk")

WEEKDAYS = (N_("Mon"), N_("Tue"), N_("Wed"), N_("Thu"), N_("Fri"), N_("Sat"), N_("Sun"))
MONTHS = (N_("Jan"), N_("Feb"), N_("Mar"), N_("Apr"), N_("May"), N_("Jun"), N_("Jul"), N_("Aug"),
          N_("Sep"), N_("Oct"), N_("Nov"), N_("Dec"))
TEXT_SCALE = {"small": 0.88, "normal": 1.0, "large": 1.14}


# ---------------------------------------------------------------- helpers

def fit(text, font, width):
    """``text`` shortened with an ellipsis so that it fits ``width``."""
    text = str(text)
    if width <= 0:
        return ""
    if font.getlength(text) <= width:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if font.getlength(text[:middle] + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…" if low else ""


def text_height(font):
    ascent, descent = font.getmetrics()
    return ascent + descent


def mix(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def temperature(value, unit):
    if value is None:
        return None
    return f"{value * 9 / 5 + 32:.0f}°F" if unit == "f" else f"{value:.0f}°C"


def gigabytes(mb):
    return mb / 1024


class Painter:
    """Shared drawing primitives with the scheme's look."""

    def __init__(self, image, scheme, base):
        self.image = image
        self.d = ImageDraw.Draw(image)
        self.overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        self.od = ImageDraw.Draw(self.overlay)
        self.c = scheme
        self.radius = int(round(scheme["radius"] * base))
        self.border = max(scheme["border_w"], int(scheme["border_w"] * base / 320))

    def panel(self, box):
        x0, y0, x1, y1 = box
        c = self.c
        if c["style"] == "cut":
            cut = max(4, (y1 - y0) // 10)
            points = [(x0, y0), (x1 - cut, y0), (x1, y0 + cut), (x1, y1), (x0 + cut, y1), (x0, y1 - cut)]
            self.d.polygon(points, fill=c["panel"], outline=c["border"])
            if self.border > 1:
                self.d.line(points + [points[0]], fill=c["border"], width=self.border)
        else:
            radius = 0 if c["style"] == "square" else self.radius
            self.d.rounded_rectangle(box, radius=radius, fill=c["panel"],
                                     outline=c["border"] if self.border else None, width=self.border)

    def bar(self, box, percent, color, style):
        x0, y0, x1, y1 = box
        if x1 - x0 < 4 or y1 - y0 < 1:
            return
        percent = max(0.0, min(100.0, percent or 0.0))
        bg = self.c["bar_bg"]
        if style == "segmented":
            count = max(6, min(30, (x1 - x0) // 9))
            gap = max(1, (x1 - x0) // (count * 6))
            width = (x1 - x0 - gap * (count - 1)) / count
            lit = round(count * percent / 100)
            for index in range(count):
                sx = x0 + index * (width + gap)
                self.d.rectangle((round(sx), y0, round(sx + width) - 1, y1),
                                 fill=color if index < lit else bg)
            return
        radius = (y1 - y0) // 2 if style == "rounded" else 0
        self.d.rounded_rectangle(box, radius=radius, fill=bg)
        filled = x0 + (x1 - x0) * percent / 100
        if filled - x0 >= max(2, radius):
            self.d.rounded_rectangle((x0, y0, round(filled), y1), radius=radius, fill=color)

    def history(self, box, values, color, maximum=100.0, alpha=70):
        """Translucent area chart (drawn on the overlay)."""
        x0, y0, x1, y1 = box
        values = list(values)
        if len(values) < 2 or x1 - x0 < 8 or y1 - y0 < 4 or max(values) < maximum * 0.01:
            return   # nothing to show (an all-zero history would look like a separator line)
        peak = max(maximum, max(values) or 1)
        step = (x1 - x0) / (len(values) - 1)
        points = [(x0 + i * step, y1 - (y1 - y0) * min(1.0, v / peak)) for i, v in enumerate(values)]
        self.od.polygon(points + [(x1, y1), (x0, y1)], fill=(*color, alpha // 2))
        self.od.line(points, fill=(*color, alpha + 60), width=1)

    def icon(self, name, size, color, xy):
        icon = legacy.get_svg_icon(name, int(size), color)
        if icon is not None:
            self.image.paste(icon, (int(xy[0]), int(xy[1])), icon)
            return True
        return False

    def finish(self):
        """Blend the translucent layer, only over the area actually drawn on."""
        box = self.overlay.getbbox()
        if box:
            base = self.image.crop(box).convert("RGBA")
            self.image.paste(Image.alpha_composite(base, self.overlay.crop(box)).convert("RGB"), box[:2])


# ---------------------------------------------------------------- data

def metric_rows(s):
    """The metric rows enabled in the settings, with live values."""
    unit = s.get("std_temp_unit", "c")
    absolute = s.get("std_values", "absolute") == "absolute"
    rows = []
    with STATS_LOCK:
        stats = dict(SYSTEM_STATS)
        cpu_history = list(CPU_USAGE_HISTORY)
        ram_history = list(RAM_USAGE_HISTORY)
        rx_history, tx_history = list(NET_RX_HISTORY), list(NET_TX_HISTORY)
        gpu_history, vram_history = list(GPU_USAGE_HISTORY), list(GPU_MEM_HISTORY)
        system_history = list(CPU_SYSTEM_HISTORY)
    valid = stats.get("valid")
    if s.get("std_show_cpu", True):
        percent = stats.get("cpu_percent", 0.0)
        rows.append({"key": "cpu", "icon": "cpu-symbolic.svg", "label": "CPU",
                     "value": f"{percent:.0f}%" if valid else "--", "percent": percent,
                     "chip": temperature(stats.get("cpu_temp_value"), unit),
                     "chip_value": stats.get("cpu_temp_value"), "history": cpu_history,
                     "history2": system_history})
    if s.get("std_show_ram", True):
        total = stats.get("ram_total_mb", 0)
        used = stats.get("ram_used_mb", 0)
        value = (f"{gigabytes(used):.1f} / {gigabytes(total):.1f} GB" if absolute and total
                 else f"{stats.get('ram_percent', 0):.0f}%")
        rows.append({"key": "ram", "icon": "ram-symbolic.svg", "label": "RAM", "value": value if valid else "--",
                     "percent": stats.get("ram_percent", 0.0), "history": ram_history})
    if s.get("std_show_swap", True) and stats.get("swap_total_mb"):
        total, used = stats.get("swap_total_mb", 0), stats.get("swap_used_mb", 0)
        value = (f"{gigabytes(used):.1f} / {gigabytes(total):.1f} GB" if absolute
                 else f"{stats.get('swap_percent', 0):.0f}%")
        rows.append({"key": "swap", "icon": "swap-symbolic.svg", "label": "SWAP", "value": value,
                     "percent": stats.get("swap_percent", 0.0)})
    if s.get("std_show_disk", True):
        used, total = stats.get("disk_used_gb"), stats.get("disk_total_gb")
        percent = stats.get("disk_percent", 0.0)
        value = f"{used:.0f} / {total:.0f} GB" if absolute and total else f"{percent:.0f}%"
        rows.append({"key": "disk", "icon": "disk-symbolic.svg", "label": _("Disk").upper() + " /",
                     "value": value if total or percent else "--", "percent": percent})
    all_gpus = stats.get("gpus") or []
    gpus = [g for g in all_gpus if g.get("path")]
    if s.get("std_show_gpu", True) and gpus:
        gpu = all_gpus[stats.get("active_gpu_idx", 0) % len(all_gpus)]
        if not gpu.get("path"):
            gpu = gpus[0]
        name = gpu.get("name", "GPU")
        if len(gpus) > 1:
            name = f"{name} ({gpus.index(gpu) + 1}/{len(gpus)})"
        rows.append({"key": "gpu", "icon": "gpu-symbolic.svg", "label": name,
                     "value": f"{gpu.get('percent', 0):.0f}%", "percent": gpu.get("percent", 0.0),
                     "chip": temperature(gpu.get("temp_value"), unit), "chip_value": gpu.get("temp_value"),
                     "history": list(gpu.get("usage_history") or gpu_history)})
        if s.get("std_gpu_details", True) and gpu.get("mem_total_mb"):
            used, total = gpu.get("mem_used_mb", 0), gpu.get("mem_total_mb", 0)
            percent = used / total * 100 if total else 0
            value = (f"{gigabytes(used):.1f} / {gigabytes(total):.1f} GB" if absolute else f"{percent:.0f}%")
            enc = gpu.get("enc_percent")
            rows.append({"key": "vram", "icon": "encdec-symbolic.svg", "label": "VRAM", "value": value,
                         "percent": percent, "chip": f"ENC {enc:.0f}%" if enc else None,
                         "history": list(gpu.get("mem_history") or vram_history)})
    if s.get("std_network", True):
        rx, tx = stats.get("net_rx_mbps", 0.0), stats.get("net_tx_mbps", 0.0)
        rows.append({"key": "net", "icon": "rx-symbolic.svg", "label": _("Network").upper(),
                     "value": f"↓{format_rate(rx)}  ↑{format_rate(tx)}", "percent": None,
                     "history": rx_history, "history2": tx_history, "net": True})
    return rows, stats


def format_rate(mbps):
    if mbps >= 100:
        return f"{mbps:.0f} Mb/s"
    if mbps >= 1:
        return f"{mbps:.1f} Mb/s"
    return f"{mbps * 1000:.0f} kb/s"


def format_uptime(boot_time):
    if not boot_time:
        return None
    seconds = max(0, int(time.time() - boot_time))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return f"{days}d {hours:02d}:{minutes:02d}" if days else f"{hours:02d}:{minutes:02d}"


# ---------------------------------------------------------------- drawing

class Layout:
    def __init__(self, width, height, settings):
        self.w, self.h = width, height
        self.portrait = height > width
        self.base = min(width, height)
        self.ts = TEXT_SCALE.get(settings.get("std_text_size", "normal"), 1.0)
        self.margin = max(3, round(self.base * 0.025))
        self.gap = self.margin

    def font(self, px, bold=False):
        return ui_font(max(8, int(px * self.ts)), bold=bold)


def draw_header(p, lay, box, s, stats):
    c = p.c
    p.panel(box)
    x0, y0, x1, y1 = box
    height = y1 - y0
    pad = max(3, round(height * 0.14))
    now = datetime.now()
    seconds = s.get("std_seconds", False)
    if s.get("std_clock_24h", True):
        clock = now.strftime("%H:%M:%S" if seconds else "%H:%M")
    else:
        clock = now.strftime("%I:%M:%S" if seconds else "%I:%M").lstrip("0") + (" AM" if now.hour < 12 else " PM")
    show_date = s.get("std_date", True)
    clock_font = lay.font(height * (0.46 if show_date else 0.6), bold=True)
    small_font = lay.font(height * 0.22)
    date_text = f"{_(WEEKDAYS[now.weekday()])}, {now.day} {_(MONTHS[now.month - 1])}"
    clock_w = clock_font.getlength(clock)
    date_w = small_font.getlength(date_text) if show_date else 0
    right_w = max(clock_w, date_w)
    right_x = x1 - pad - right_w
    block_h = text_height(clock_font) + (text_height(small_font) if show_date else 0)
    cy = y0 + (height - block_h) // 2
    p.d.text((x1 - pad - clock_w, cy - clock_font.size * 0.08), clock, font=clock_font, fill=c["accent"])
    if show_date:
        p.d.text((x1 - pad - date_w, cy + text_height(clock_font) - 1), date_text, font=small_font, fill=c["muted"])

    tx = x0 + pad
    if s.get("std_logo", True):
        logo_size = height - pad * 2
        logo = legacy.load_distro_logo(legacy.get_os_release().get("LOGO", ""), logo_size)
        if logo is not None:
            p.image.paste(logo, (tx, y0 + (height - logo.height) // 2), logo)
            tx += logo.width + pad
    text_w = right_x - tx - pad
    title_font = lay.font(height * 0.3, bold=True)
    title = legacy.get_os_release().get("PRETTY_NAME", "Linux")
    lines = [(fit(title, title_font, text_w), title_font, c["text"])]
    if s.get("std_host_line", True):
        sub_font = lay.font(height * 0.21)
        sub = f"{stats.get('hostname', '')} · {stats.get('kernel', '')}"
        lines.append((fit(sub, sub_font, text_w), sub_font, c["muted"]))
    total = sum(text_height(font) for _t, font, _c in lines)
    ty = y0 + (height - total) // 2
    for text, font, color in lines:
        if text:
            p.d.text((tx, ty), text, font=font, fill=color)
        ty += text_height(font)


def bar_color(row, s, c):
    color = c.get(row["key"], c["accent"])
    if s.get("std_alert_colors", True) and row.get("percent") is not None:
        if row["percent"] >= 90:
            return c["crit"]
        if row["percent"] >= 75:
            return mix(color, c["warn"], 0.7)
    return color


def chip_color(value, c):
    if value is None:
        return c["muted"]
    if value >= 85:
        return c["crit"]
    if value >= 70:
        return c["warn"]
    return c["muted"]


def draw_rows(p, lay, box, rows, s):
    c = p.c
    p.panel(box)
    x0, y0, x1, y1 = box
    if not rows:
        return
    inner = max(3, round(lay.base * 0.02))
    row_h = (y1 - y0 - inner * 2) / len(rows)
    font = lay.font(min(row_h * 0.40, lay.base * 0.08), bold=True)
    font_h = text_height(font)
    bar_h = max(3, min(int(row_h * 0.14), int(lay.base * 0.028)))
    style = s.get("std_bar_style", "rounded")
    show_history = s.get("std_history", True)
    for index, row in enumerate(rows):
        top = y0 + inner + index * row_h
        bottom = top + row_h
        left, right = x0 + inner, x1 - inner
        content_h = font_h + (bar_h + max(2, row_h * 0.08) if row.get("percent") is not None else 0)
        ty = top + (row_h - content_h) / 2
        color = bar_color(row, s, c)
        if show_history and row.get("history"):
            area = (left, top + row_h * 0.1, right, bottom - row_h * 0.06)
            maximum = 1.0 if row.get("net") else 100.0
            p.history(area, row["history"], c.get(row["key"], c["accent"]) if not row.get("net") else c["rx"],
                      maximum, alpha=50)
            if row.get("history2") and row.get("net"):
                p.history(area, row["history2"], c["tx"], maximum, alpha=40)
        icon_size = int(font_h * 0.92)
        lx = left
        icon_color = c["rx"] if row.get("net") else c.get(row["key"], c["text"])
        if p.icon(row["icon"], icon_size, icon_color, (lx, ty + (font_h - icon_size) / 2)):
            lx += icon_size + max(3, icon_size // 3)
        value_w = font.getlength(row["value"])
        p.d.text((right - value_w, ty), row["value"], font=font, fill=c["text"])
        space = right - value_w - lx - max(4, font.size // 2)
        chip = row.get("chip")
        chip_font = lay.font(font.size * 0.82 / lay.ts, bold=True)
        chip_w = chip_font.getlength(chip) + font.size * 0.5 if chip else 0
        label_full = font.getlength(row["label"])
        if chip and label_full + chip_w > space:
            if font.getlength(row["label"][:6] + "…") + chip_w > space:
                chip, chip_w = None, 0
        label = fit(row["label"], font, space - chip_w)
        color_key = "rx" if row.get("net") else row["key"]
        label_color = c.get(color_key, c["text"]) if s.get("std_colored_labels", True) else c["text"]
        p.d.text((lx, ty), label, font=font, fill=label_color)
        if chip:
            cx = lx + font.getlength(label) + font.size * 0.45
            p.d.text((cx, ty + (font_h - text_height(chip_font)) / 2), chip, font=chip_font,
                     fill=chip_color(row.get("chip_value"), c))
        if row.get("percent") is not None:
            by = ty + font_h + max(2, row_h * 0.08)
            p.bar((left, round(by), right, round(by + bar_h)), row["percent"], color, style)


def draw_processes(p, lay, box, s, stats):
    c = p.c
    p.panel(box)
    x0, y0, x1, y1 = box
    pad = max(3, round(lay.base * 0.022))
    by_memory = s.get("std_process_sort", "cpu") == "memory"
    procs = list(stats.get("procs_mem" if by_memory else "procs") or [])
    head_font = lay.font(lay.base * 0.05, bold=True)
    head_h = text_height(head_font)
    title = _("Processes").upper()
    mem_label, cpu_label = "MEM", "CPU"
    available = y1 - y0 - pad * 3 - head_h
    wanted = int(s.get("std_process_count", "8"))
    rows = max(1, min(wanted, int(available / max(10, lay.base * 0.05)) if available > 0 else 1))
    row_h = available / rows if rows else 0
    font = lay.font(min(row_h * 0.62, lay.base * 0.066))
    col_font = lay.font(lay.base * 0.042, bold=True)
    num_w = max(font.getlength("100.0%"), col_font.getlength(cpu_label), col_font.getlength(mem_label)) + pad
    x_mem = x1 - pad
    x_cpu = x_mem - num_w
    title_space = x_cpu - col_font.getlength(cpu_label) - x0 - pad * 3
    if head_font.getlength(title) > title_space:
        title = "TOP"
    p.d.text((x0 + pad, y0 + pad), fit(title, head_font, title_space), font=head_font, fill=c["accent"])
    for label, xr in ((cpu_label, x_cpu), (mem_label, x_mem)):
        p.d.text((xr - col_font.getlength(label), y0 + pad + (head_h - text_height(col_font)) / 2), label,
                 font=col_font, fill=c["muted"])
    line_y = y0 + pad * 2 + head_h
    p.d.line((x0 + pad, line_y - pad // 2, x1 - pad, line_y - pad // 2), fill=c["border"] if c["border"] != c["panel"]
             else c["bar_bg"], width=1)
    cores = max(1, len(stats.get("cpu_cores_percent") or []) or 1)
    if not procs:
        p.d.text((x0 + pad, line_y), fit(_("Collecting..."), font, x1 - x0 - pad * 2), font=font, fill=c["muted"])
        return
    for index, proc in enumerate(procs[:rows]):
        ty = line_y + index * row_h + (row_h - text_height(font)) / 2
        if index % 2:
            p.d.rectangle((x0 + pad // 2, line_y + index * row_h, x1 - pad // 2, line_y + (index + 1) * row_h),
                          fill=mix(c["panel"], c["text"], 0.04))
        cpu = (proc.get("cpu_percent") or 0.0) / cores   # share of the whole CPU, like the CPU row
        mem = proc.get("memory_percent") or 0.0
        cpu_text, mem_text = f"{cpu:.1f}%", f"{mem:.1f}%"
        name = fit(proc.get("name") or "?", font, x_cpu - num_w - x0 - pad * 2 + pad)
        p.d.text((x0 + pad, ty), name, font=font, fill=c["text"])
        cpu_fill = c["crit"] if cpu >= 25 else (c["warn"] if cpu >= 8 else c["muted"])
        mem_fill = c["crit"] if mem >= 25 else (c["warn"] if mem >= 8 else c["muted"])
        p.d.text((x_cpu - font.getlength(cpu_text), ty), cpu_text, font=font, fill=cpu_fill)
        p.d.text((x_mem - font.getlength(mem_text), ty), mem_text, font=font, fill=mem_fill)


def draw_graphs(p, lay, box, s, stats):
    """Side panel alternative: CPU, network and GPU history charts."""
    c = p.c
    x0, y0, x1, y1 = box
    with STATS_LOCK:
        charts = [("CPU", f"{stats.get('cpu_percent', 0):.0f}%", [(list(CPU_USAGE_HISTORY), c["cpu"])], 100.0)]
        charts.append((_("Network").upper(),
                       f"↓{format_rate(stats.get('net_rx_mbps', 0))} ↑{format_rate(stats.get('net_tx_mbps', 0))}",
                       [(list(NET_RX_HISTORY), c["rx"]), (list(NET_TX_HISTORY), c["tx"])], 1.0))
        if any(g.get("path") for g in stats.get("gpus") or []):
            charts.append(("GPU", f"{(stats.get('gpus') or [{}])[0].get('percent', 0):.0f}%",
                           [(list(GPU_USAGE_HISTORY), c["gpu"])], 100.0))
    gap = lay.gap
    height = (y1 - y0 - gap * (len(charts) - 1)) / len(charts)
    if height < 34 and len(charts) > 2:
        charts = charts[:2]
        height = (y1 - y0 - gap) / 2
    font = lay.font(min(height * 0.2, lay.base * 0.055), bold=True)
    for index, (title, value, series, maximum) in enumerate(charts):
        top = round(y0 + index * (height + gap))
        bottom = round(top + height)
        p.panel((x0, top, x1, bottom))
        pad = max(3, round(lay.base * 0.02))
        value_font = font
        while (value_font.size > 8 and
               font.getlength(title) + value_font.getlength(value) + pad * 3 > x1 - x0):
            value_font = ui_font(value_font.size - 1, bold=True)
        value_w = value_font.getlength(value)
        p.d.text((x1 - pad - value_w, top + pad + text_height(font) - text_height(value_font)), value,
                 font=value_font, fill=c["text"])
        p.d.text((x0 + pad, top + pad), fit(title, font, x1 - x0 - pad * 3 - value_w), font=font,
                 fill=c["accent"])
        area = (x0 + pad, top + pad * 2 + text_height(font), x1 - pad, bottom - pad)
        for fraction in (0.25, 0.5, 0.75):
            gy = area[1] + (area[3] - area[1]) * fraction
            p.od.line((area[0], gy, area[2], gy), fill=(*c["muted"], 30))
        peak = max([maximum] + [max(values) for values, _color in series if values])
        for values, color in series:
            p.history(area, values, color, peak, alpha=110)


def draw_footer(p, lay, box, s, stats):
    c = p.c
    x0, y0, x1, y1 = box
    font = lay.font((y1 - y0) * 0.72)
    parts = []
    uptime = format_uptime(stats.get("boot_time"))
    if uptime:
        parts.append(_("up {time}").format(time=uptime))
    load = stats.get("load_avg") or (0, 0, 0)
    parts.append(_("load {a:.2f} {b:.2f} {c:.2f}").format(a=load[0], b=load[1], c=load[2]))
    if stats.get("proc_count"):
        parts.append(_("{count} processes").format(count=stats["proc_count"]))
    if stats.get("power_profile"):
        parts.append(stats["power_profile"])
    separator = "  ·  "
    while parts and font.getlength(separator.join(parts)) > x1 - x0:
        parts.pop()
    text = separator.join(parts)
    p.d.text((x0 + (x1 - x0 - font.getlength(text)) / 2, y0 + (y1 - y0 - text_height(font)) / 2), text,
             font=font, fill=c["muted"])


def render(width, height, s):
    scheme = SCHEMES.get(s.get("std_scheme", "dark"), SCHEMES["dark"])
    lay = Layout(width, height, s)
    image = Image.new("RGB", (width, height), scheme["bg"])
    p = Painter(image, scheme, lay.base)
    rows, stats = metric_rows(s)
    m, gap = lay.margin, lay.gap
    top, bottom = m, height - m
    if s.get("std_header", True):
        header_h = max(28, min(round(lay.base * (0.17 if lay.portrait else 0.18)), 96))
        draw_header(p, lay, (m, top, width - m, top + header_h), s, stats)
        top += header_h + gap
    if s.get("std_footer", True):
        footer_h = max(11, round(lay.base * 0.055 * lay.ts))
        draw_footer(p, lay, (m, bottom - footer_h, width - m, bottom), s, stats)
        bottom -= footer_h + max(2, gap // 2)
    side = s.get("std_side_panel", "processes")
    body_w = width - 2 * m
    if not lay.portrait:
        if side != "none" and body_w >= 300 and rows:
            split = m + round(body_w * 0.53)
            draw_rows(p, lay, (m, top, split, bottom), rows, s)
            side_box = (split + gap, top, width - m, bottom)
        elif rows:
            draw_rows(p, lay, (m, top, width - m, bottom), rows, s)
            side_box = None
        else:
            side_box = (m, top, width - m, bottom)
    else:
        available = bottom - top
        ideal = max(26, min(round(lay.base * 0.15), 74)) * max(1, len(rows))
        if side == "none" or not rows:
            rows_h = available if rows else 0
        else:
            rows_h = min(ideal, round(available * 0.62))
        if rows:
            draw_rows(p, lay, (m, top, width - m, top + rows_h), rows, s)
        side_box = (m, top + rows_h + gap, width - m, bottom) if available - rows_h - gap >= 50 else None
        if side == "none" and rows:
            side_box = None
    if side_box:
        if side == "graphs" or (side == "none" and not rows):
            draw_graphs(p, lay, side_box, s, stats)
        else:
            draw_processes(p, lay, side_box, s, stats)
    p.finish()
    return image


class StandardTheme:
    def __init__(self, info, ctx=None, scheme=None):
        self.info = info
        self.scheme = scheme       # legacy ids (dark, neon...) force their scheme

    def render(self, width, height, settings, ctx):
        if self.scheme:
            settings = dict(settings, std_scheme=self.scheme)
        return render(width, height, settings)

    def frame_interval(self, settings, ctx):
        return 0.5 - (time.time() % 0.5) + 0.01

    def close(self):
        pass
