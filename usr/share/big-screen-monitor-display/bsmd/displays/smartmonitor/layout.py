"""What this project flashes to the SmartMonitor HID panel.

Every theme is adapted by :mod:`.capture` (the theme's own drawing, with its
values turned into live widgets); this module decides *when* that picture
changes (:func:`spec` / :func:`key`), compiles and caches it (:func:`compiled`)
and computes the live values (:func:`values`). When a theme cannot be captured
(no adaptation, or the capture fails) the panel falls back to the built-in
dashboard below.

The dashboard is split in two:

* :func:`spec` - everything that changes the *picture* (palette, labels,
  hardware present, host name, rotation). Its :func:`key` decides when the
  theme must be compiled and flashed again (about a minute, so only on real
  changes, never per frame);
* :func:`values` - the live numbers, pushed every second on channels.

Labels are baked into the background (static text costs no widget); every
number is a number widget with a monospaced digit atlas, so values do not
jump around; the network units are *word* atlases selected by a channel
("KB/s" = 0, "MB/s" = 1). The clock is four single-digit widgets so hours and
minutes keep their leading zero.

Budget: 22 number widgets + 4 bars on 22 channels (panel limits: 28 numbers,
40 widgets, 26 channels; see :mod:`.imgdat`).
"""

import datetime
import hashlib
import json
import os
import time

from PIL import Image, ImageDraw, ImageFont

from ...i18n import _
from . import imgdat

LAYOUT_VERSION = 1
SIZE = (480, 320)

CPU, CPU_TEMP, CPU_MHZ = 1, 2, 3
GPU, GPU_TEMP, GPU_MEM = 4, 5, 6          # without a GPU: load %, uptime hours, disk MB/s
RAM, RAM_GB, SWAP = 7, 8, 9
DISK, DOWN, DOWN_UNIT, UP, UP_UNIT = 10, 11, 12, 13, 14
CLOCK = (15, 16, 17, 18)                  # h h : m m
DATE = (19, 20, 21, 22)                   # d d / m m
BARS = (CPU, GPU, RAM, DISK)

FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))), "fonts")
SANS_BOLD = "DejaVuSans-Bold.ttf"
SANS = "DejaVuSans.ttf"
MONO_BOLD = "DejaVuSansMono-Bold.ttf"
UNITS = ("KB/s", "MB/s")


def _font(name, size):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        return ImageFont.load_default()


def _palette(settings):
    from ... import dashboard
    scheme = dashboard.SCHEMES.get(settings.get("std_scheme", "dark")) or dashboard.SCHEMES["dark"]
    keys = ("bg", "panel", "border", "text", "muted", "accent", "cpu", "ram", "swap", "disk", "gpu", "vram", "rx",
            "tx", "bar_bg")
    return {key: tuple(scheme[key]) for key in keys} | {"border_w": scheme.get("border_w", 0)}


def _has_gpu(stats):
    gpus = [g for g in stats.get("gpus") or [] if g.get("path")]
    return bool(gpus)


def _gpu(stats):
    gpus = [g for g in stats.get("gpus") or [] if g.get("path")]
    if not gpus:
        return None
    index = stats.get("active_gpu_idx", 0)
    return gpus[index] if 0 <= index < len(gpus) else gpus[0]


def dashboard_spec(settings, stats):
    """Inputs of the built-in dashboard's picture (a JSON-able dict)."""
    total_gb = round((stats.get("ram_total_mb") or 0) / 1024)
    rotation = 180 if settings.get("orientation") in ("horizontal_flipped", "vertical_flipped") else 0
    gpu = _gpu(stats)
    return {
        "v": LAYOUT_VERSION,
        "kind": "dashboard",
        "palette": _palette(settings),
        "fahrenheit": settings.get("std_temp_unit", "c") == "f",
        "gpu": bool(gpu),
        "gpu_name": (gpu or {}).get("name", "")[:18],
        "ram_total_gb": total_gb,
        "host": (stats.get("hostname") or "")[:22],
        "name": (settings.get("name") or "").strip()[:22],
        "rotation": rotation,
        "labels": {
            "cpu": "CPU", "gpu": "GPU", "system": _("SYSTEM"), "memory": _("MEMORY"), "network": _("NETWORK"),
            "usage": _("USAGE %"), "temp": _("TEMP °F") if settings.get("std_temp_unit") == "f" else _("TEMP °C"),
            "vram": "VRAM %", "used": _("USED GB"), "swap": "SWAP %", "uptime": _("UPTIME h"),
            "load": _("LOAD %"), "io": _("DISK MB/s"), "down": _("DOWN"), "up": _("UP"), "disk": _("DISK %"), "of": _("of"),
        },
    }


def key(theme_spec):
    return hashlib.sha256(json.dumps(theme_spec, sort_keys=True).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- atlases

def digit_atlas(size):
    font = _font(MONO_BOLD, size)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    width = max(1, round(font.getlength("0")))
    data = bytearray()
    for glyph in imgdat.GLYPHS:
        cell = Image.new("L", (width, height), 0)
        ImageDraw.Draw(cell).text((0, 0), glyph, font=font, fill=255)
        data += cell.tobytes()
    return imgdat.Atlas((width,) * len(imgdat.GLYPHS), height, bytes(data))


def word_atlas(words, size):
    """Cells 0..n-1 hold ``words``; the rest are blank. All cells equally wide."""
    font = _font(SANS_BOLD, size)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    width = max(round(font.getlength(word)) for word in words) + 2
    data = bytearray()
    for index in range(len(imgdat.GLYPHS)):
        cell = Image.new("L", (width, height), 0)
        if index < len(words):
            ImageDraw.Draw(cell).text((0, 0), words[index], font=font, fill=255)
        data += cell.tobytes()
    return imgdat.Atlas((width,) * len(imgdat.GLYPHS), height, bytes(data))


# ---------------------------------------------------------------- theme

def build(theme_spec):
    """The :class:`imgdat.Theme` for a spec (background, widgets)."""
    pal = theme_spec["palette"]
    labels = theme_spec["labels"]
    width, height = SIZE
    image = Image.new("RGB", SIZE, pal["bg"])
    draw = ImageDraw.Draw(image)
    numbers, bars = [], []
    big, mid, small = digit_atlas(34), digit_atlas(17), digit_atlas(14)
    units = word_atlas(UNITS, 12)
    caption = _font(SANS_BOLD, 11)
    title_font = _font(SANS_BOLD, 15)

    def number(channel, x, y, digits, color, atlas):
        box = (int(x), int(y), atlas.widths[0] * digits, atlas.height)
        numbers.append(imgdat.Number(channel, box, color, atlas))
        return box

    def text(x, y, value, font, color):
        draw.text((x, y), value, font=font, fill=color)
        return draw.textlength(value, font=font)

    # Header: name on the left, date and clock on the right.
    draw.rectangle((0, 0, width, 43), fill=pal["panel"])
    draw.rectangle((0, 43, width, 44), fill=pal["accent"])
    draw.ellipse((12, 15, 24, 27), fill=pal["accent"])
    title = theme_spec["name"] or theme_spec["host"] or "Big Screen Monitor"
    text(32, 11, title, _font(SANS_BOLD, 18), pal["text"])
    clock = digit_atlas(28)
    clock_w = clock.widths[0]
    colon_w = 12
    x = width - 12 - clock_w * 4 - colon_w
    y = (43 - clock.height) // 2 + 1
    for index, channel in enumerate(CLOCK):
        if index == 2:
            # Drawn, not typed: the font's colon sits on the baseline, too low for the digits.
            middle = y + clock.height // 2
            for dy in (-7, 4):
                draw.rectangle((x + 4, middle + dy, x + 7, middle + dy + 3), fill=pal["accent"])
            x += colon_w
        number(channel, x, y, 1, pal["text"], clock)
        x += clock_w
    date_w = small.widths[0]
    slash = _font(MONO_BOLD, 14)
    slash_w = round(draw.textlength("/", font=slash))
    x = width - 12 - clock_w * 4 - colon_w - 18 - date_w * 4 - slash_w
    y = (43 - small.height) // 2 + 1
    for index, channel in enumerate(DATE):
        if index == 2:
            text(x, y, "/", slash, pal["muted"])
            x += slash_w
        number(channel, x, y, 1, pal["muted"], small)
        x += date_w

    margin, gap, top = 8, 8, 52
    card_w = (width - margin * 2 - gap) // 2
    card_h = (height - top - margin - gap) // 2

    def card(col, row, title_text, color):
        x0 = margin + col * (card_w + gap)
        y0 = top + row * (card_h + gap)
        draw.rounded_rectangle((x0, y0, x0 + card_w, y0 + card_h), radius=10, fill=pal["panel"],
                               outline=pal["border"] if pal["border_w"] else None, width=pal["border_w"] or 0)
        draw.rounded_rectangle((x0, y0 + 10, x0 + 4, y0 + 28), radius=2, fill=color)
        text(x0 + 12, y0 + 9, title_text, title_font, color)
        return x0, y0

    def metric_pair(x0, y0, left, right, color):
        """Two captions with a big value under each (channels left[0], right[0])."""
        for (label, channel, digits), dx in ((left, 12), (right, card_w // 2 + 6)):
            text(x0 + dx, y0 + 34, label, caption, pal["muted"])
            number(channel, x0 + dx, y0 + 48, digits, color, big)

    def bar(channel, x0, y0, color):
        box = (x0 + 12, y0 + card_h - 20, card_w - 24, 9)
        bars.append(imgdat.Bar(channel, box, color, pal["bar_bg"], pal["bar_bg"]))

    def corner(x0, y0, label, channel, digits, color, suffix=""):
        """Small value at the top right of a card: "LABEL 1234 suffix"."""
        right = x0 + card_w - 12
        suffix_w = round(draw.textlength(suffix, font=caption)) + (4 if suffix else 0)
        box_x = right - suffix_w - mid.widths[0] * digits
        label_w = round(draw.textlength(label, font=caption))
        text(box_x - 6 - label_w, y0 + 13, label, caption, pal["muted"])
        number(channel, box_x, y0 + 8, digits, color, mid)
        if suffix:
            text(right - suffix_w + 4, y0 + 13, suffix, caption, pal["muted"])

    # CPU
    x0, y0 = card(0, 0, labels["cpu"], pal["cpu"])
    metric_pair(x0, y0, (labels["usage"], CPU, 3), (labels["temp"], CPU_TEMP, 3), pal["cpu"])
    corner(x0, y0, "", CPU_MHZ, 4, pal["text"], "MHz")
    bar(CPU, x0, y0, pal["cpu"])
    # GPU, or system figures without a GPU
    if theme_spec["gpu"]:
        x0, y0 = card(1, 0, labels["gpu"], pal["gpu"])
        metric_pair(x0, y0, (labels["usage"], GPU, 3), (labels["temp"], GPU_TEMP, 3), pal["gpu"])
        corner(x0, y0, labels["vram"], GPU_MEM, 3, pal["vram"])
    else:
        x0, y0 = card(1, 0, labels["system"], pal["swap"])
        metric_pair(x0, y0, (labels["load"], GPU, 3), (labels["uptime"], GPU_TEMP, 5), pal["swap"])
        corner(x0, y0, labels["io"], GPU_MEM, 4, pal["text"])
    bar(GPU, x0, y0, pal["gpu"] if theme_spec["gpu"] else pal["swap"])
    # Memory
    x0, y0 = card(0, 1, labels["memory"], pal["ram"])
    metric_pair(x0, y0, (labels["usage"], RAM, 3), (labels["used"], RAM_GB, 3), pal["ram"])
    corner(x0, y0, labels["swap"], SWAP, 3, pal["swap"])
    total = theme_spec["ram_total_gb"]
    if total:
        text(x0 + card_w // 2 + 6 + big.widths[0] * 3 + 6, y0 + 66, f"/ {total}", caption, pal["muted"])
    bar(RAM, x0, y0, pal["ram"])
    # Network + disk
    x0, y0 = card(1, 1, labels["network"], pal["rx"])
    for (label, channel, unit, color), dx in (((labels["down"], DOWN, DOWN_UNIT, pal["rx"]), 12),
                                              ((labels["up"], UP, UP_UNIT, pal["tx"]), card_w // 2 + 6)):
        label_w = text(x0 + dx, y0 + 34, label, caption, pal["muted"])
        number(unit, x0 + dx + label_w + 5, y0 + 33, 1, pal["muted"], units)
        number(channel, x0 + dx, y0 + 48, 4, color, big)
    corner(x0, y0, labels["disk"], DISK, 3, pal["disk"])
    bar(DISK, x0, y0, pal["disk"])

    return imgdat.Theme(SIZE, image, numbers, bars, rotation=theme_spec["rotation"])


_CACHE = {}


def dashboard_compiled(theme_spec):
    """``(key, img.dat bytes)`` of the built-in dashboard, cached."""
    theme_key = key(theme_spec)
    if theme_key not in _CACHE:
        _CACHE.clear()
        _CACHE[theme_key] = imgdat.compile_theme(build(theme_spec))
    return theme_key, _CACHE[theme_key]


# ---------------------------------------------------------------- live values

def _temp(value, fahrenheit):
    if value is None:
        return 0
    return value * 9 / 5 + 32 if fahrenheit else value


def _rate(mbps):
    """(value, unit index) for a rate in Mbit/s: KB/s below 10000 KB/s, else MB/s."""
    kbs = max(0.0, float(mbps or 0)) * 1e6 / 8 / 1000
    if kbs < 10000:
        return round(kbs), 0
    return min(9999, round(kbs / 1000)), 1


def dashboard_values(theme_spec, stats, now=None):
    """``{channel: int}`` for the built-in dashboard's live figures."""
    now = now or datetime.datetime.now()
    fahrenheit = theme_spec["fahrenheit"]
    result = {
        CPU: stats.get("cpu_percent") or 0,
        CPU_TEMP: _temp(stats.get("cpu_temp_value"), fahrenheit),
        CPU_MHZ: stats.get("cpu_freq_mhz") or 0,
        RAM: stats.get("ram_percent") or 0,
        RAM_GB: (stats.get("ram_used_mb") or 0) / 1024,
        SWAP: stats.get("swap_percent") or 0,
        DISK: stats.get("disk_percent") or 0,
    }
    result[DOWN], result[DOWN_UNIT] = _rate(stats.get("net_rx_mbps"))
    result[UP], result[UP_UNIT] = _rate(stats.get("net_tx_mbps"))
    if theme_spec["gpu"]:
        gpu = _gpu(stats) or {}
        result[GPU] = gpu.get("percent") or 0
        result[GPU_TEMP] = _temp(gpu.get("temp_value"), fahrenheit)
        total = gpu.get("mem_total_mb") or 0
        result[GPU_MEM] = 100 * (gpu.get("mem_used_mb") or 0) / total if total else 0
    else:
        boot = stats.get("boot_time")
        cores = (stats.get("cpu_cores") or (None, None))[1] or os.cpu_count() or 1
        result[GPU] = 100 * (stats.get("load_avg") or (0,))[0] / cores
        result[GPU_TEMP] = (time.time() - boot) / 3600 if boot else 0
        result[GPU_MEM] = (stats.get("disk_io_kbs") or 0) / 1000
    for channels, number in ((CLOCK[:2], now.hour), (CLOCK[2:], now.minute), (DATE[:2], now.day),
                             (DATE[2:], now.month)):
        result[channels[0]], result[channels[1]] = divmod(number, 10)
    for channel in (CPU, RAM, DISK, GPU, SWAP) + ((GPU_MEM,) if theme_spec["gpu"] else ()):
        result[channel] = max(0, min(100, result[channel]))
    return {channel: max(0, min(0xFFFF, round(value))) for channel, value in result.items()}


# ---------------------------------------------------------------- previews (configuration window)

DEMO = {CPU: 23, CPU_TEMP: 52, CPU_MHZ: 3600, GPU: 41, GPU_TEMP: 58, GPU_MEM: 35, RAM: 38, RAM_GB: 6, SWAP: 2,
        DISK: 61, DOWN: 1240, DOWN_UNIT: 0, UP: 86, UP_UNIT: 0}


def dashboard_preview(settings, metrics=None, now=None):
    """The built-in dashboard for the configuration window: the service's last frame
    (``metrics`` = status ``metrics``) or sample values, decoded from the compiled theme."""
    metrics = metrics or {}
    hints = metrics.get("hints") or {}
    stats = {"hostname": hints.get("host") or os.uname().nodename,
             "ram_total_mb": (hints.get("ram_total_gb") or 16) * 1024,
             "gpus": [{"path": "gpu", "name": hints.get("gpu_name", "GPU")}] if hints.get("gpu", True) else []}
    theme_spec = dashboard_spec(settings, stats)
    _key, data = dashboard_compiled(theme_spec)
    fields = {int(k): v for k, v in (metrics.get("fields") or {}).items() if str(k).isdigit()}
    if not fields:
        now = now or datetime.datetime.now()
        fields = dict(DEMO)
        for channels, number in ((CLOCK[:2], now.hour), (CLOCK[2:], now.minute), (DATE[:2], now.day),
                                 (DATE[2:], now.month)):
            fields[channels[0]], fields[channels[1]] = divmod(number, 10)
    image = imgdat.render(data, fields)
    if theme_spec["rotation"] == 180:
        image = image.rotate(180)
    return image


# ---------------------------------------------------------------- every theme (capture)

CAPTURE_VERSION = 3
COMMON_KEYS = ("theme", "language", "name", "orientation", "std_temp_unit")
THEME_KEYS = {"standard": ("std_",), "gkrellm": ("gk_",), "planet": ("planet_",), "old_computer": ("oc_",),
              "brother_away": ("ba_", "overlay_"), "kojiro": ("kojiro",), "big_media_player": ("bmp_",)}
# Scenes that follow the time of day are captured again when the period changes,
# drawn at a representative hour (chosen so no clock component collides with the
# date used by the capture, see fields.T0).
BROTHER_AWAY_PERIODS = ((4.5, 7), (11.0, 13), (17.5, 18), (20.5, 23))     # (from hour, captured at)
PLANET_HOURS = (1, 4, 7, 10, 13, 16, 19, 22)
CAPTURE_TIMEOUT = 150.0
CACHE_KEEP = 6


def _epoch(theme_id, settings, now):
    hour = now.hour + now.minute / 60
    if theme_id == "brother_away" and settings.get("ba_day_night", True):
        chosen = BROTHER_AWAY_PERIODS[-1][1]
        for start, captured in BROTHER_AWAY_PERIODS:
            if hour >= start:
                chosen = captured
        return chosen
    if theme_id == "planet":
        return PLANET_HOURS[min(len(PLANET_HOURS) - 1, int(hour // 3))]
    return None


def _hardware(stats):
    """What themes print as fixed text (names, totals): a change means a new picture."""
    gpus = [(g.get("name", ""), round((g.get("mem_total_mb") or 0) / 256)) for g in stats.get("gpus") or []]
    return {"host": stats.get("hostname", ""), "kernel": stats.get("kernel", ""), "cpu": stats.get("cpu_model", ""),
            "ram": round((stats.get("ram_total_mb") or 0) / 512), "swap": round((stats.get("swap_total_mb") or 0) / 512),
            "disk": round(stats.get("disk_total_gb") or 0), "gpus": gpus, "cores": list(stats.get("cpu_cores") or ())}


def spec(settings, stats, now=None):
    """Inputs of the picture for a display (a JSON-able dict): its key changes only
    when what the panel must show changes (theme, its options, hardware names,
    time-of-day scene), never with the live values."""
    from . import capture
    theme_id = settings.get("theme", "standard")
    if theme_id not in capture.THEME_OPTIONS:
        return dashboard_spec(settings, stats)
    prefixes = THEME_KEYS.get(theme_id, ())
    subset = {k: v for k, v in settings.items()
              if k in COMMON_KEYS or (prefixes and k.startswith(prefixes))}
    now = now or datetime.datetime.now()
    rotation = 180 if settings.get("orientation") in ("horizontal_flipped", "vertical_flipped") else 0
    result = {"v": CAPTURE_VERSION, "kind": "capture", "theme": theme_id, "settings": subset,
              "hw": _hardware(stats), "hour": _epoch(theme_id, settings, now), "rotation": rotation}
    if theme_id == "big_media_player":
        media = stats.get("media") if isinstance(stats.get("media"), dict) else {}
        result["media"] = {"present": bool(media.get("present"))}
        if media.get("present") and settings.get("sm_bmp_track_refresh"):
            # Cover and title flashed with the picture: a new song is a new picture.
            result["media"]["track"] = [media.get("title", ""), media.get("artist", ""), media.get("album", ""),
                                        media.get("art") or ""]
    return result


class Compiled:
    """A picture ready to flash: ``key``, ``data`` (img.dat), ``bindings`` (None for
    the built-in dashboard) and the spec it came from."""

    def __init__(self, key_, data, bindings, theme_spec, report=None):
        self.key, self.data, self.bindings, self.spec = key_, data, bindings, theme_spec
        self.report = report or {}
        self.source_key = None        # key of the spec it was made for (a fallback has another key)
        self.source_spec = None

    @property
    def channels(self):
        return sorted(int(c) for c in self.bindings) if self.bindings is not None else None


def cache_dir():
    from .driver import state_dir
    return os.path.join(state_dir(), "smartmonitor-cache")


def _from_cache(key_, theme_spec):
    base = os.path.join(cache_dir(), key_)
    try:
        with open(base + ".json", encoding="utf-8") as handle:
            report = json.load(handle)
        with open(base + ".dat", "rb") as handle:
            data = handle.read()
    except (OSError, ValueError):
        return None
    if report.get("bytes") != len(data) or "bindings" not in report:
        return None
    return Compiled(key_, data, report["bindings"], theme_spec, report)


def _prune_cache():
    try:
        entries = sorted((os.path.getmtime(os.path.join(cache_dir(), name)), name)
                         for name in os.listdir(cache_dir()) if name.endswith(".json"))
    except OSError:
        return
    for _mtime, name in entries[:-CACHE_KEEP]:
        for suffix in (".json", ".dat"):
            try:
                os.unlink(os.path.join(cache_dir(), name[:-5] + suffix))
            except OSError:
                pass


def _jsonable(value):
    return json.loads(json.dumps(value, default=lambda o: list(o) if isinstance(o, (tuple, set)) else str(o)))


_MEMORY = {}
_MEMORY_KEEP = 6
_LOCK = __import__("threading").Lock()       # one capture at a time (window threads, several displays)


def _remember(key_, result):
    _MEMORY.pop(key_, None)
    _MEMORY[key_] = result
    while len(_MEMORY) > _MEMORY_KEEP:
        _MEMORY.pop(next(iter(_MEMORY)))


def compiled(theme_spec, settings, stats, progress=None):
    with _LOCK:
        return _compiled(theme_spec, settings, stats, progress)


def _compiled(theme_spec, settings, stats, progress=None):
    """The :class:`Compiled` picture for ``theme_spec``: memory cache, disk cache,
    or a capture run in a worker process (``progress()`` is called while it runs
    and may return True to stop). Falls back to the built-in dashboard."""
    import logging
    import subprocess
    import sys
    log = logging.getLogger("bsmd.smartmonitor")
    key_ = key(theme_spec)
    if key_ in _MEMORY:
        return _MEMORY[key_]
    if theme_spec.get("kind") != "capture":
        dash_key, data = dashboard_compiled(theme_spec)
        result = Compiled(dash_key, data, None, theme_spec)
        _remember(key_, result)
        return result
    result = _from_cache(key_, theme_spec)
    if result is None:
        os.makedirs(cache_dir(), exist_ok=True)
        out = os.path.join(cache_dir(), key_)
        stats = dict(stats)
        media = dict(stats.get("media") or {})
        art = media.pop("art_image", None)
        stats["media"] = media
        request = {"theme": theme_spec["theme"], "settings": _jsonable(settings), "stats": _jsonable(stats),
                   "hour": theme_spec.get("hour"), "rotation": theme_spec.get("rotation", 0), "out": out}
        if art is not None and settings.get("sm_bmp_track_refresh"):
            import base64
            import io
            buffer = io.BytesIO()
            art.convert("RGB").save(buffer, "PNG")
            request["art_png"] = base64.b64encode(buffer.getvalue()).decode("ascii")
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
        started = time.monotonic()
        try:
            proc = subprocess.Popen([sys.executable, "-I", worker], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True)
            proc.stdin.write(json.dumps(request))
            proc.stdin.close()
            while proc.poll() is None:
                if progress is not None and progress():
                    proc.kill()
                    raise TimeoutError("capture stopped")
                if time.monotonic() - started > CAPTURE_TIMEOUT:
                    proc.kill()
                    raise TimeoutError("capture took too long")
                time.sleep(0.2)
            error = proc.stderr.read()
            if proc.returncode != 0:
                raise RuntimeError(error.strip().splitlines()[-1] if error.strip() else f"exit {proc.returncode}")
        except (OSError, RuntimeError, TimeoutError) as error:
            log.warning("SmartMonitor: theme %s could not be adapted (%s); showing the built-in dashboard",
                        theme_spec["theme"], error)
            dash = dashboard_spec(settings, stats)
            dash_key, data = dashboard_compiled(dash)
            result = Compiled(dash_key, data, None, dash, {"fallback": str(error)})
            _remember(key_, result)
            return result
        result = _from_cache(key_, theme_spec)
        if result is None:
            dash = dashboard_spec(settings, stats)
            dash_key, data = dashboard_compiled(dash)
            return Compiled(dash_key, data, None, dash, {"fallback": "capture wrote nothing"})
        log.info("SmartMonitor: theme %s adapted in %.1f s (%d values, %d bars, %d frames, %d bytes)",
                 theme_spec["theme"], time.monotonic() - started, result.report.get("numbers", 0),
                 result.report.get("bars", 0), result.report.get("frames", 1), len(result.data))
        _prune_cache()
    _remember(key_, result)
    return result


def values(picture, stats, now=None):
    """``{channel: int}`` for a :class:`Compiled` picture."""
    if picture.bindings is None:
        return dashboard_values(picture.spec, stats, now)
    from . import fields
    stamp = now.timestamp() if isinstance(now, datetime.datetime) else now
    return {int(channel): fields.binding_value(binding, stats, stamp) for channel, binding in picture.bindings.items()}


def preview(settings, metrics=None, stats=None, now=None):
    """What the panel shows, for the configuration window, decoded from the same
    compiled picture the service flashes (sample values without the service)."""
    from ... import telemetry
    stats = stats or telemetry.snapshot()
    theme_spec = spec(settings, stats, now)
    picture = compiled(theme_spec, settings, stats)
    metrics = metrics or {}
    fields_ = {int(k): v for k, v in (metrics.get("fields") or {}).items() if str(k).isdigit()} \
        if metrics.get("layout") == key(theme_spec) else {}
    if not fields_:
        fields_ = values(picture, stats, now) if picture.bindings is not None else None
    if fields_ is None:
        return dashboard_preview(settings, metrics, now)
    image = imgdat.render(picture.data, fields_)
    if theme_spec.get("rotation") == 180:
        image = image.rotate(180)
    return image
