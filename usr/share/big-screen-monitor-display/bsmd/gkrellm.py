"""GKrellM tribute theme, rebuilt as measured modules.

The 3.x version used fixed font sizes and fixed offsets, so values collided
with labels whenever a column was narrower than 800x480/4, and several
modules (PPP, VLAN, inet, sys) drew invented data. Here every module reports
its height for the column width, fonts follow the column width, text is
fitted, modules that do not fit are skipped, and unavailable data is shown as
such.
"""

import os
import time
from datetime import datetime

import psutil
from PIL import Image, ImageDraw, ImageFont

from . import legacy_themes as legacy
from .dashboard import MONTHS, WEEKDAYS, fit, format_uptime, text_height
from .i18n import _
from .telemetry import (CPU_SYSTEM_HISTORY, CPU_USAGE_HISTORY, DISK_IO_HISTORY, GPU_MEM_HISTORY, STATS_LOCK,
                        SYSTEM_STATS)

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
STYLES = {
    "urlicht": {"text": (220, 220, 230), "accent": (80, 130, 255), "dim": (130, 130, 145),
                "bevel_hi": (80, 80, 92), "bevel_lo": (30, 30, 40), "chart_top": (0, 0, 46), "chart_bottom": (0, 0, 6),
                "title_bg": (16, 16, 22), "led_off": (40, 40, 50), "hot": (255, 70, 60)},
    "classic": {"text": (170, 255, 170), "accent": (85, 200, 85), "dim": (85, 160, 85),
                "bevel_hi": (85, 170, 85), "bevel_lo": (30, 70, 30), "chart_top": (0, 34, 0), "chart_bottom": (0, 6, 0),
                "title_bg": (10, 26, 10), "led_off": (25, 50, 25), "hot": (255, 230, 120)},
    "cyber_red": {"text": (255, 190, 190), "accent": (255, 60, 60), "dim": (170, 110, 110),
                  "bevel_hi": (120, 50, 50), "bevel_lo": (50, 20, 20), "chart_top": (46, 0, 6), "chart_bottom": (8, 0, 0),
                  "title_bg": (26, 10, 10), "led_off": (60, 25, 25), "hot": (255, 230, 120)},
}
TEXT_SCALE = {"small": 0.87, "normal": 1.0, "large": 1.15}
CHART_LINES = {"small": 1.6, "normal": 2.4, "large": 3.3}

_CACHE = {}


def cached(key, ttl, producer):
    now = time.monotonic()
    entry = _CACHE.get(key)
    if entry is None or now - entry[0] > ttl:
        try:
            value = producer()
        except Exception:  # noqa: BLE001 - a missing source just shows "unavailable"
            value = None
        _CACHE[key] = entry = (now, value)
    return entry[1]


def mono_font(size, bold=False):
    names = ("DejaVuSansMono-Bold.ttf",) if bold else ("DejaVuSansMono.ttf",)
    for name in names:
        try:
            return _mono_cache(os.path.join(FONT_DIR, name), int(size))
        except OSError:
            continue
    return ImageFont.load_default()


_FONTS = {}


def _mono_cache(path, size):
    key = (path, size)
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(path, size)
    return _FONTS[key]


def human_rate(kbs):
    if kbs >= 1024:
        return f"{kbs / 1024:.1f}M"
    return f"{kbs:.0f}K"


def human_mbps(mbps):
    return f"{mbps:.1f}M" if mbps >= 1 else f"{mbps * 1000:.0f}K"


def partitions():
    seen, result = set(), []
    for part in psutil.disk_partitions(all=False):
        if part.device in seen or part.mountpoint.startswith(("/snap", "/var/lib/docker", "/boot/efi")):
            continue
        seen.add(part.device)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        result.append((part.mountpoint, usage.percent, usage.used / 1024 ** 3, usage.total / 1024 ** 3))
    result.sort(key=lambda item: (item[0] != "/", item[0]))
    return result


def removable_mounts():
    return [os.path.basename(part.mountpoint) or part.mountpoint
            for part in psutil.disk_partitions(all=False)
            if part.mountpoint.startswith(("/media/", "/run/media/", "/mnt/"))]


def main_interface(ifaces):
    """Interface of the default route, else the busiest one."""
    try:
        with open("/proc/net/route") as handle:
            for line in handle.readlines()[1:]:
                fields = line.split()
                if len(fields) > 1 and fields[1] == "00000000" and fields[0] in ifaces:
                    return fields[0]
    except OSError:
        pass
    if not ifaces:
        return None
    return max(ifaces, key=lambda name: ifaces[name].get("rx_total", 0) + ifaces[name].get("tx_total", 0))


class Canvas:
    def __init__(self, image, style, font_px, chart_lines):
        self.image = image
        self.d = ImageDraw.Draw(image)
        self.c = style
        self.font = mono_font(font_px)
        self.bold = mono_font(font_px, bold=True)
        self.big = mono_font(font_px * 1.6, bold=True)
        self.small = mono_font(max(8, font_px * 0.82))
        self.line = text_height(self.font)
        self.pad = max(2, font_px // 3)
        self.chart_h = max(10, int(self.line * chart_lines))

    # -- primitives
    def title(self, x, y, w, text, leds=None):
        c, d = self.c, self.d
        h = self.line + 4
        d.line((x, y, x + w, y), fill=c["bevel_hi"])
        d.rectangle((x, y + 1, x + w, y + h), fill=c["title_bg"])
        d.line((x, y + h + 1, x + w, y + h + 1), fill=c["bevel_lo"])
        reserve = 0
        if leds is not None:
            size = max(4, self.line // 2)
            for index, on in enumerate(leds):
                lx = x + w - self.pad - (len(leds) - index) * (size + 3)
                d.rectangle((lx, y + 2 + (h - size) // 2, lx + size, y + 2 + (h - size) // 2 + size),
                            fill=c["accent"] if on else c["led_off"], outline=c["bevel_hi"])
            reserve = len(leds) * (size + 3) + self.pad
        label = fit(text, self.bold, w - self.pad * 2 - reserve * 2)
        tw = self.bold.getlength(label)
        d.text((x + (w - tw) / 2, y + 2), label, font=self.bold, fill=c["text"])
        return y + h + 3

    @staticmethod
    def title_height(canvas):
        return canvas.line + 7

    def pair(self, x, y, w, left, right, left_color=None, right_color=None, font=None):
        font = font or self.font
        right_w = font.getlength(right)
        self.d.text((x + w - self.pad - right_w, y), right, font=font, fill=right_color or self.c["text"])
        self.d.text((x + self.pad, y), fit(left, font, w - self.pad * 3 - right_w), font=font,
                    fill=left_color or self.c["accent"])
        return y + text_height(font)

    def chart(self, x, y, w, values, maximum=100.0, values2=None, current=None):
        c, d = self.c, self.d
        h = self.chart_h
        x0, x1 = x + self.pad, x + w - self.pad
        for row in range(h):
            t = row / max(1, h - 1)
            color = tuple(int(a + (b - a) * t) for a, b in zip(c["chart_top"], c["chart_bottom"]))
            d.line((x0, y + row, x1, y + row), fill=color)
        values = list(values or [])
        peak = max([maximum] + values + list(values2 or []))
        if len(values) > 1:
            step = (x1 - x0) / (len(values) - 1)
            dim = tuple(v // 3 for v in c["accent"])
            points = []
            for index, value in enumerate(values):
                px = x0 + index * step
                py = y + h - (h - 1) * min(1.0, value / peak)
                d.line((px, py, px, y + h), fill=dim)
                points.append((px, py))
            d.line(points, fill=c["accent"])
        if values2 and len(values2) > 1:
            step = (x1 - x0) / (len(values2) - 1)
            d.line([(x0 + i * step, y + h - (h - 1) * min(1.0, v / peak)) for i, v in enumerate(values2)],
                   fill=c["hot"])
        d.line((x0, y + h, x1, y + h), fill=c["bevel_hi"])
        krell_h = max(2, self.line // 6)
        d.rectangle((x0, y + h + 1, x1, y + h + krell_h), fill=c["bevel_lo"])
        if current is not None:
            filled = x0 + (x1 - x0) * min(1.0, max(0.0, current / peak))
            d.rectangle((x0, y + h + 1, filled, y + h + krell_h), fill=c["accent"])
        return y + h + krell_h + 3

    def chart_height(self):
        return self.chart_h + max(2, self.line // 6) + 3

    def meter(self, x, y, w, percent, text):
        c, d = self.c, self.d
        h = self.line + 2
        x0, x1 = x + self.pad, x + w - self.pad
        d.rectangle((x0, y, x1, y + h), fill=c["chart_bottom"], outline=c["bevel_lo"])
        filled = x0 + (x1 - x0) * min(1.0, max(0.0, percent / 100))
        if filled >= x0 + 1:    # nothing to fill at 0 % (e.g. swap present but unused)
            d.rectangle((x0 + 1, y + 1, filled, y + h - 1), fill=tuple(v // 2 for v in c["accent"]))
        label = fit(text, self.font, x1 - x0 - self.pad * 2)
        d.text((x0 + self.pad, y + 1), label, font=self.font, fill=c["text"])
        return y + h + 3

    def thermal(self, value):
        """Accent -> hot colour between 30 and 90 °C."""
        t = max(0.0, min(1.0, ((value or 30) - 30) / 60))
        return tuple(int(a + (b - a) * t) for a, b in zip(self.c["accent"], self.c["hot"]))


# ---------------------------------------------------------------- modules
# Each module: (key, height(canvas, w, stats, s) -> int | None, draw(canvas, x, y, w, stats, s))

def _host_height(cv, w, stats, s):
    return cv.line * 2 + text_height(cv.big) - cv.line + cv.pad * 2 + min(48, int(w * 0.22))


def _host_draw(cv, x, y, w, stats, s):
    logo_size = min(48, int(w * 0.22))
    logo = legacy.load_distro_logo(legacy.get_os_release().get("LOGO", ""), logo_size)
    if logo is not None:
        cv.image.paste(logo, (int(x + (w - logo.width) / 2), int(y + cv.pad)), logo)
    y += logo_size + cv.pad
    host = fit(stats.get("hostname", ""), cv.big, w - cv.pad * 2)
    cv.d.text((x + (w - cv.big.getlength(host)) / 2, y), host, font=cv.big, fill=cv.c["dim"])
    y += text_height(cv.big)
    kernel = fit(stats.get("kernel", ""), cv.small, w - cv.pad * 2)
    cv.d.text((x + (w - cv.small.getlength(kernel)) / 2, y), kernel, font=cv.small, fill=cv.c["text"])


def _clock_height(cv, w, stats, s):
    lines = 0
    if s.get("gk_show_date", True):
        lines += cv.line
    if s.get("gk_show_time", True):
        lines += text_height(cv.big)
    return lines + cv.pad if lines else None


def _clock_draw(cv, x, y, w, stats, s):
    now = datetime.now()
    if s.get("gk_show_date", True):
        parts = [(_(WEEKDAYS[now.weekday()]) + " ", cv.c["text"]), (f"{now.day:02d}", cv.c["accent"]),
                 (" " + _(MONTHS[now.month - 1]), cv.c["text"])]
        total = sum(cv.font.getlength(t) for t, _c in parts)
        cx = x + (w - total) / 2
        for text, color in parts:
            cv.d.text((cx, y), text, font=cv.font, fill=color)
            cx += cv.font.getlength(text)
        y += cv.line
    if s.get("gk_show_time", True):
        hm, sec = now.strftime("%H:%M"), now.strftime(" %S")
        total = cv.big.getlength(hm) + cv.font.getlength(sec)
        cx = x + (w - total) / 2
        cv.d.text((cx, y), hm, font=cv.big, fill=cv.c["text"])
        cv.d.text((cx + cv.big.getlength(hm), y + text_height(cv.big) - cv.line - 2), sec, font=cv.font,
                  fill=cv.c["accent"])


def _uptime_height(cv, w, stats, s):
    return cv.line + cv.pad


def _uptime_draw(cv, x, y, w, stats, s):
    uptime = format_uptime(stats.get("boot_time")) or "--"
    text = fit(_("up {time}").format(time=uptime), cv.font, w - cv.pad * 2)
    cv.d.text((x + (w - cv.font.getlength(text)) / 2, y), text, font=cv.font, fill=cv.c["text"])


def _cpu_height(cv, w, stats, s):
    return Canvas.title_height(cv) + cv.chart_height() + cv.line


def _cpu_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "CPU")
    with STATS_LOCK:
        total, system = list(CPU_USAGE_HISTORY), list(CPU_SYSTEM_HISTORY)
    y = cv.chart(x, y, w, total, 100, system, stats.get("cpu_percent", 0))
    temp = stats.get("cpu_temp_value")
    left = f"u {stats.get('cpu_user', 0):.0f}% s {stats.get('cpu_system', 0):.0f}%"
    cv.pair(x, y, w, left, f"{temp:.0f}°C" if temp else "--", cv.c["text"], cv.thermal(temp))


def _cores_height(cv, w, stats, s):
    return cv.line * 3 + cv.pad if stats.get("cpu_cores_percent") else None


def _cores_draw(cv, x, y, w, stats, s):
    cores = stats.get("cpu_cores_percent") or []
    x0, x1 = x + cv.pad, x + w - cv.pad
    h = cv.line * 2
    width = (x1 - x0) / max(1, len(cores))
    for index, value in enumerate(cores):
        bx = x0 + index * width
        cv.d.rectangle((bx + 1, y, bx + width - 1, y + h), fill=cv.c["chart_bottom"], outline=cv.c["bevel_lo"])
        top = y + h - h * min(1.0, value / 100)
        cv.d.rectangle((bx + 1, top, bx + width - 1, y + h), fill=cv.c["accent"])
    peak = max(cores) if cores else 0
    cv.pair(x, y + h + 1, w, _("{count} cores").format(count=len(cores)), _("max {value:.0f}%").format(value=peak),
            cv.c["dim"], cv.c["text"], cv.small)


def _proc_height(cv, w, stats, s):
    return Canvas.title_height(cv) + cv.chart_height() + cv.line


def _proc_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "Proc")
    load = stats.get("load_avg") or (0, 0, 0)
    cores = max(1, len(stats.get("cpu_cores_percent") or []))
    y = cv.chart(x, y, w, list(stats.get("load_history") or []), float(cores), current=load[0])
    count = stats.get("proc_count")
    cv.pair(x, y, w, _("{count} procs").format(count=count) if count else "-- procs",
            f"{load[0]:.2f} {load[1]:.2f}", cv.c["text"], cv.c["dim"])


def _temps(stats):
    rows = []
    if stats.get("cpu_temp_value"):
        rows.append(("CPU", stats["cpu_temp_value"]))
    for index, gpu in enumerate(g for g in stats.get("gpus") or [] if g.get("path")):
        for label in ("edge", "junc", "mem"):
            value = gpu.get(label)
            if value:
                try:
                    rows.append((f"gpu{index} {label}", float(str(value).replace("°C", ""))))
                except ValueError:
                    pass
    for group, label, value, unit in stats.get("sensors") or []:
        if unit == "°C" and group.startswith(("nvme", "acpitz", "nct", "it87")) and len(rows) < 10:
            rows.append((label if label != group else group, value))
    return rows


def _temp_height(cv, w, stats, s):
    rows = _temps(stats)
    return Canvas.title_height(cv) + max(1, len(rows)) * (cv.line + 3) if rows else Canvas.title_height(cv) + cv.line


def _temp_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, _("Sensors"))
    rows = _temps(stats)
    if not rows:
        cv.pair(x, y, w, _("no sensors"), "", cv.c["dim"])
        return
    for label, value in rows:
        cv.pair(x, y, w, label, f"{value:.1f}°C", cv.c["accent"], cv.thermal(value))
        y += cv.line
        bar = (w - cv.pad * 2) * max(0.0, min(1.0, (value - 30) / 60))
        cv.d.line((x + cv.pad, y + 1, x + cv.pad + bar, y + 1), fill=cv.thermal(value), width=2)
        y += 3


def _hda_height(cv, w, stats, s):
    return Canvas.title_height(cv) + cv.chart_height() + cv.line


def _hda_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, _("Disk I/O"))
    with STATS_LOCK:
        history = list(DISK_IO_HISTORY)
    io = stats.get("disk_io_kbs", 0.0)
    y = cv.chart(x, y, w, history, 512.0, current=io)
    cv.pair(x, y, w, "r+w", f"{human_rate(io)}/s", cv.c["dim"], cv.c["text"])


def _net_entries(stats, main=True):
    ifaces = stats.get("net_ifaces") or {}
    primary = main_interface(ifaces)
    if main:
        return [(primary, ifaces[primary])] if primary else []
    return [(name, data) for name, data in sorted(ifaces.items()) if name != primary][:4]


def _net_height(cv, w, stats, s):
    entries = _net_entries(stats)
    return (Canvas.title_height(cv) + cv.chart_height() + cv.line) if entries else Canvas.title_height(cv) + cv.line


def _net_draw(cv, x, y, w, stats, s):
    entries = _net_entries(stats)
    if not entries:
        y = cv.title(x, y, w, _("Network"))
        cv.pair(x, y, w, _("no connection"), "", cv.c["dim"])
        return
    name, data = entries[0]
    blink = int(time.time() * 2) % 2 == 0
    y = cv.title(x, y, w, name, leds=[data.get("rx", 0) > 0.01 and blink, data.get("tx", 0) > 0.01 and not blink])
    y = cv.chart(x, y, w, data.get("rx_history"), 1.0, data.get("tx_history"), data.get("rx", 0))
    cv.pair(x, y, w, f"rx {human_mbps(data.get('rx', 0))}", f"tx {human_mbps(data.get('tx', 0))}",
            cv.c["accent"], cv.c["hot"])


def _inet_height(cv, w, stats, s):
    entries = _net_entries(stats, main=False)
    return len(entries) * (Canvas.title_height(cv) + cv.line + 2) if entries else None


def _inet_draw(cv, x, y, w, stats, s):
    for name, data in _net_entries(stats, main=False):
        y = cv.title(x, y, w, name, leds=[data.get("rx", 0) > 0.01, data.get("tx", 0) > 0.01])
        y = cv.pair(x, y, w, f"rx {human_mbps(data.get('rx', 0))}", f"tx {human_mbps(data.get('tx', 0))}",
                    cv.c["text"], cv.c["text"]) + 2


def _meter_height(cv, w, stats, s):
    return Canvas.title_height(cv) + cv.line + 5


def _mem_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "Mem")
    used, total = stats.get("ram_used_mb", 0) / 1024, stats.get("ram_total_mb", 0) / 1024
    cv.meter(x, y, w, stats.get("ram_percent", 0), f"{stats.get('ram_percent', 0):.0f}%  {used:.1f}/{total:.1f}G")


def _swap_height(cv, w, stats, s):
    return _meter_height(cv, w, stats, s) if stats.get("swap_total_mb") else None


def _swap_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "Swap")
    used, total = stats.get("swap_used_mb", 0) / 1024, stats.get("swap_total_mb", 0) / 1024
    cv.meter(x, y, w, stats.get("swap_percent", 0), f"{stats.get('swap_percent', 0):.0f}%  {used:.1f}/{total:.1f}G")


def _fs_list(s):
    return (cached("partitions", 30, partitions) or [])[:int(s.get("gk_disk_count", "2"))]


def _fs_height(cv, w, stats, s):
    parts = _fs_list(s)
    return Canvas.title_height(cv) + len(parts) * (cv.line * 2 + 6) if parts else None


def _fs_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, _("Disks"))
    for mount, percent, used, total in _fs_list(s):
        y = cv.pair(x, y, w, mount, f"{used:.0f}/{total:.0f}G", cv.c["accent"], cv.c["dim"], cv.small) + 1
        y = cv.meter(x, y, w, percent, f"{percent:.0f}%")


def _gpu_list(stats):
    return [g for g in stats.get("gpus") or [] if g.get("path")]


def _gpu_height(cv, w, stats, s):
    gpus = _gpu_list(stats)
    return len(gpus) * (Canvas.title_height(cv) + cv.chart_height() + cv.line * 2) if gpus else None


def _gpu_draw(cv, x, y, w, stats, s):
    for index, gpu in enumerate(_gpu_list(stats)):
        y = cv.title(x, y, w, f"GPU {index}")
        y = cv.pair(x, y, w, gpu.get("name", "GPU"), "", cv.c["dim"], font=cv.small)
        with STATS_LOCK:
            history = list(gpu.get("usage_history") or [])
            mem_history = list(gpu.get("mem_history") or GPU_MEM_HISTORY)
        y = cv.chart(x, y, w, history, 100, mem_history, gpu.get("percent", 0))
        temp = gpu.get("temp_value")
        mem = f"VRAM {gpu.get('mem_used_mb', 0) / 1024:.1f}G" if gpu.get("mem_total_mb") else ""
        y = cv.pair(x, y, w, f"{gpu.get('percent', 0):.0f}% {mem}", f"{temp:.0f}°C" if temp else "--",
                    cv.c["text"], cv.thermal(temp))


def _battery_height(cv, w, stats, s):
    return Canvas.title_height(cv) + cv.line + 5


def _battery_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "bat0")
    battery = stats.get("battery")
    if not battery:
        cv.pair(x, y, w, _("no battery"), "", cv.c["dim"])
        return
    source = "AC" if battery["plugged"] else "BAT"
    cv.meter(x, y, w, battery["percent"], f"{battery['percent']:.0f}% {source}")


def _sys_rows(stats):
    # Fans reporting 0 RPM are empty motherboard headers, not information.
    rows = [(label[:10], f"{value:.0f} RPM") for _g, label, value, unit in stats.get("sensors") or []
            if unit == "RPM" and value > 0]
    for gpu in _gpu_list(stats):
        if gpu.get("ppt"):
            rows.append(("GPU power", gpu["ppt"]))
    if stats.get("power_profile"):
        rows.append((_("profile"), stats["power_profile"]))
    return rows[:8]


def _sys_height(cv, w, stats, s):
    return Canvas.title_height(cv) + max(1, len(_sys_rows(stats))) * cv.line + 2


def _sys_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "sys")
    rows = _sys_rows(stats)
    if not rows:
        cv.pair(x, y, w, _("no fan or power sensors"), "", cv.c["dim"])
    for label, value in rows:
        y = cv.pair(x, y, w, label, value, cv.c["text"], cv.c["text"])


def _single_line_height(cv, w, stats, s):
    return Canvas.title_height(cv) + cv.line + 2


def _docker_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, "docker")
    argv = ["docker", "ps", "-q"]
    output = legacy.cached_command(argv, ttl=10)
    ok = legacy.cached_command_ok(argv)
    if ok is False:
        text = _("unavailable")
    elif ok is None:
        text = "..."
    else:
        text = _("{count} containers").format(count=len(output.splitlines()))
    cv.pair(x, y, w, text, "", cv.c["text"])


def _devices_height(cv, w, stats, s):
    return Canvas.title_height(cv) + max(1, len(cached("removable", 10, removable_mounts) or [])) * cv.line + 2


def _devices_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, _("Devices"))
    mounts = cached("removable", 10, removable_mounts) or []
    if not mounts:
        cv.pair(x, y, w, _("no removable media"), "", cv.c["dim"])
    for name in mounts[:4]:
        size = max(4, cv.line // 2)
        cv.d.rectangle((x + cv.pad, y + (cv.line - size) // 2, x + cv.pad + size, y + (cv.line - size) // 2 + size),
                       fill=cv.c["accent"])
        cv.d.text((x + cv.pad * 2 + size, y), fit(name, cv.font, w - cv.pad * 3 - size), font=cv.font,
                  fill=cv.c["text"])
        y += cv.line


def _media_draw(cv, x, y, w, stats, s):
    y = cv.title(x, y, w, _("Media"))
    status = legacy.cached_command(["playerctl", "status"])
    if legacy.cached_command_ok(["playerctl", "status"]) is False or not status:
        cv.pair(x, y, w, _("no player"), "", cv.c["dim"])
        return
    title = legacy.cached_command(["playerctl", "metadata", "title"]) if "Playing" in status else ""
    icon = {"Playing": "(>)", "Paused": "(II)"}.get(status, "( )")
    cv.pair(x, y, w, title or status, icon, cv.c["text"], cv.c["accent"])


MODULES = [
    ("gk_show_host", _host_height, _host_draw),
    ("clock", _clock_height, _clock_draw),
    ("gk_show_uptime", _uptime_height, _uptime_draw),
    ("gk_show_cpu", _cpu_height, _cpu_draw),
    ("gk_show_cores", _cores_height, _cores_draw),
    ("gk_show_proc", _proc_height, _proc_draw),
    ("gk_show_temp", _temp_height, _temp_draw),
    ("gk_show_hda", _hda_height, _hda_draw),
    ("gk_show_eth0", _net_height, _net_draw),
    ("gk_show_inet", _inet_height, _inet_draw),
    ("gk_show_mem", _meter_height, _mem_draw),
    ("gk_show_swap", _swap_height, _swap_draw),
    ("gk_show_disk", _fs_height, _fs_draw),
    ("gk_show_gpu", _gpu_height, _gpu_draw),
    ("gk_show_battery", _battery_height, _battery_draw),
    ("gk_show_sys", _sys_height, _sys_draw),
    ("gk_show_docker", _single_line_height, _docker_draw),
    ("gk_show_devices", _devices_height, _devices_draw),
    ("gk_show_media", _single_line_height, _media_draw),
]


def column_count(width, height, s):
    choice = s.get("gk_columns", "auto")
    if choice != "auto":
        return int(choice)
    return max(1, min(4, round(width / 200)))


def render(width, height, s):
    style = STYLES.get(s.get("gk_theme_color", "urlicht"), STYLES["urlicht"])
    image = Image.new("RGB", (width, height), (0, 0, 0))
    cols = column_count(width, height, s)
    col_w = width // cols
    font_px = max(8, min(18, int(col_w / (21 * 0.6) * TEXT_SCALE.get(s.get("gk_text_size", "normal"), 1.0))))
    font_px = min(font_px, max(8, height // 16))
    cv = Canvas(image, style, font_px, CHART_LINES.get(s.get("gk_chart_height", "normal"), 2.4))
    with STATS_LOCK:
        stats = dict(SYSTEM_STATS)
    for index in range(1, cols):
        x = index * col_w
        cv.d.line((x - 1, 0, x - 1, height), fill=style["bevel_lo"], width=2)
        cv.d.line((x - 3, 0, x - 3, height), fill=style["bevel_hi"])
    column, y = 0, 2
    gap = max(2, cv.pad)
    for key, measure, draw in MODULES:
        if key != "clock" and not s.get(key, key not in ("gk_show_cores", "gk_show_docker", "gk_show_inet",
                                                           "gk_show_battery")):
            continue
        x = column * col_w
        w = col_w - (4 if column < cols - 1 else 0)
        height_needed = measure(cv, w, stats, s)
        if height_needed is None:
            continue
        if y + height_needed > height - 2:
            if column + 1 >= cols:
                continue            # does not fit anywhere: skip instead of overlapping
            column, y = column + 1, 2
            x = column * col_w
            w = col_w - (4 if column < cols - 1 else 0)
            if y + height_needed > height - 2:
                continue
        draw(cv, x, y, w, stats, s)
        y += height_needed + gap
    cv.d.line((0, height - 2, width, height - 2), fill=style["bevel_lo"], width=2)
    return image
