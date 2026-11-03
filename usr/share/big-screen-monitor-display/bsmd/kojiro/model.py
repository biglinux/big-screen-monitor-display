"""Kojiro configuration: widget catalog, schema, validation and migration.

Pure Python (no Pillow, no GTK): the root helper validates Kojiro settings
with this module before writing them, so it must stay dependency free.

Geometry is stored normalised (0..1) against a reference resolution
(``ref``) plus an anchor; ``bsmd.kojiro.layout`` turns it into pixels for any
panel, keeping circles round and text readable.
"""

import copy
import re

from ..i18n import N_

VERSION = 1
MAX_WIDGETS = 64
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
WIDGET_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
WALLPAPER_ID = re.compile(r"^[0-9a-f]{32}$")
ANCHORS = ("auto", "tl", "tc", "tr", "ml", "c", "mr", "bl", "bc", "br")
TEXT_STYLES = ("normal", "mono", "digital", "pixel")
FONT_FAMILY = re.compile(r"^[A-Za-z0-9 ._+-]{1,64}$")
BUILTIN_WALLPAPERS = ("cyberpunk", "neon_grid", "minimal", "matrix", "retro", "dark", "glass", "industrial")
FITS = ("cover", "contain", "stretch", "center", "tile", "original")

PALETTE = {"cyan": "#42E8FF", "magenta": "#F044DB", "red": "#FF475C", "green": "#83EF4C",
           "yellow": "#FFD94A", "white": "#E8F4FF"}

# type -> (label, styles, default style, default size (w, h) in reference pixels at 800x480,
#          default refresh seconds, metric for alerts or None)
WIDGET_TYPES = {
    "cpu": (N_("CPU"), ("ring", "semi", "arc", "double", "gauge", "bar", "bar_segmented", "bar_vertical",
                        "graph_line", "graph_area", "text", "hud"), "ring", (150, 150), 1.0, "temp"),
    "gpu": (N_("GPU"), ("ring", "semi", "arc", "double", "gauge", "bar", "bar_segmented", "bar_vertical",
                        "graph_line", "graph_area", "text", "hud"), "ring", (150, 150), 1.0, "temp"),
    "ram": (N_("RAM"), ("bar", "bar_segmented", "bar_gradient", "bar_vertical", "thermo", "ring", "semi",
                        "graph_area", "text"), "bar_segmented", (300, 56), 2.0, "usage"),
    "swap": (N_("SWAP"), ("bar", "bar_segmented", "bar_gradient", "bar_vertical", "ring", "semi", "text"),
             "bar_segmented", (300, 56), 5.0, "usage"),
    "vram": (N_("VRAM"), ("bar", "bar_segmented", "bar_gradient", "ring", "semi", "text"), "bar", (260, 56),
             2.0, "usage"),
    "fan": (N_("Fan"), ("icon", "ring", "text"), "icon", (150, 70), 2.0, None),
    "encdec": (N_("Video engine"), ("text", "bar", "ring"), "text", (170, 54), 2.0, None),
    "disk": (N_("Disk"), ("ring", "semi", "bar", "bar_segmented", "text", "hud"), "hud", (200, 90), 5.0, "usage"),
    "net_down": (N_("Download"), ("text", "graph_area", "graph_line", "graph_bars", "sparkline"), "text",
                 (200, 50), 1.0, None),
    "net_up": (N_("Upload"), ("text", "graph_area", "graph_line", "graph_bars", "sparkline"), "text",
               (200, 50), 1.0, None),
    "clock": (N_("Clock"), ("frame", "plain", "digital"), "frame", (240, 84), 1.0, None),
    "distro": (N_("Distribution logo"), ("logo_name", "logo", "name"), "logo_name", (120, 130), 3600.0, None),
    "cores": (N_("CPU cores"), ("bars", "grid"), "bars", (220, 90), 1.0, None),
    "uptime": (N_("Uptime"), ("text",), "text", (180, 40), 30.0, None),
    "hostname": (N_("Hostname"), ("text",), "text", (200, 40), 3600.0, None),
    "kernel": (N_("Kernel"), ("text",), "text", (220, 40), 3600.0, None),
    "ip": (N_("Local IP"), ("text",), "text", (220, 40), 30.0, None),
    "battery": (N_("Battery"), ("bar", "ring", "text"), "bar", (180, 50), 10.0, "usage"),
    "power": (N_("Power profile"), ("text",), "text", (180, 40), 30.0, None),
    "processes": (N_("Top processes"), ("list",), "list", (230, 130), 5.0, None),
    "text": (N_("Custom text"), ("text",), "text", (200, 40), 3600.0, None),
    "separator": (N_("Separator / light line"), ("line", "glow_line", "dots"), "glow_line", (300, 8), 3600.0, None),
    "frame": (N_("Frame"), ("corners", "box", "hud"), "corners", (200, 120), 3600.0, None),
}
STATIC_TYPES = {"text", "separator", "frame", "hostname", "kernel", "distro"}

UNITS = {"net_down": ("auto_bytes", "KB/s", "MB/s", "Mbps", "Gbps"),
         "net_up": ("auto_bytes", "KB/s", "MB/s", "Mbps", "Gbps"),
         "cpu": ("c", "f"), "gpu": ("c", "f"), "disk": ("c", "f")}

# Per-type options: key -> (kind, constraint, default). Kinds: bool, choice, int, text.
OPTIONS = {
    "cpu": {"show_temp": ("bool", None, True), "show_freq": ("bool", None, True),
            "show_model": ("bool", None, False), "temp_sensor": ("text", 64, "auto")},
    "gpu": {"index": ("int", (-1, 7), -1), "show_name": ("bool", None, False), "show_temp": ("bool", None, True), "show_clock": ("bool", None, True),
            "show_vram": ("bool", None, False), "show_power": ("bool", None, False)},
    "ram": {"show_values": ("bool", None, True), "show_percent": ("bool", None, True)},
    "swap": {"show_values": ("bool", None, True), "show_percent": ("bool", None, True),
             "hide_when_none": ("bool", None, False)},
    "vram": {"index": ("int", (-1, 7), -1)},
    "fan": {"fan": ("text", 64, "auto"), "spin": ("bool", None, True), "show_rpm": ("bool", None, True)},
    "encdec": {"index": ("int", (-1, 7), -1)},
    "disk": {"mount": ("text", 128, "/"), "show_temp": ("bool", None, True), "show_io": ("bool", None, False),
             "show_space": ("bool", None, True)},
    "net_down": {"iface": ("text", 32, "auto")},
    "net_up": {"iface": ("text", 32, "auto")},
    "clock": {"h24": ("bool", None, True), "seconds": ("bool", None, False), "date": ("bool", None, True),
              "weekday": ("bool", None, True), "blink": ("bool", None, True),
              "date_format": ("choice", ("auto", "dmy", "mdy", "ymd"), "auto")},
    "distro": {"logo": ("choice", ("auto", "none"), "auto"), "name": ("text", 40, ""),
               "show_name": ("bool", None, True), "circle": ("bool", None, True)},
    "cores": {"max": ("int", (2, 64), 16)},
    "ip": {"iface": ("text", 32, "auto")},
    "processes": {"count": ("int", (1, 8), 4), "sort": ("choice", ("cpu", "memory"), "cpu")},
    "text": {"text": ("text", 80, "Kojiro")},
}

# Common widget properties: key -> (kind, constraint, default)
COMMON = {
    "visible": ("bool", None, True),
    "locked": ("bool", None, False),
    "group": ("text", 24, ""),
    "anchor": ("choice", ANCHORS, "auto"),
    "rotation": ("int", (-180, 180), 0),
    "color": ("color", None, PALETTE["cyan"]),
    "color2": ("color", None, PALETTE["magenta"]),
    "text_color": ("color", None, PALETTE["white"]),
    "bg": ("color", None, "#0A0E1A"),
    "bg_opacity": ("int", (0, 100), 0),
    "frost": ("int", (0, 20), 0),              # blur of the wallpaper behind the widget (glass look)
    "border": ("int", (0, 8), 0),
    "border_color": ("color", None, PALETTE["cyan"]),
    "radius": ("int", (0, 50), 12),
    "opacity": ("int", (10, 100), 100),
    "glow": ("int", (0, 100), 55),
    "shadow": ("bool", None, True),
    "font": ("font", None, "default"),
    "bold": ("bool", None, True),
    "font_scale": ("int", (50, 200), 100),
    "text_style": ("choice", TEXT_STYLES, "normal"),
    "align": ("choice", ("left", "center", "right"), "left"),
    "label": ("text", 24, ""),
    "show_label": ("bool", None, True),
    "show_icon": ("bool", None, True),
    "decimals": ("int", (0, 2), 0),
    "unit": ("text", 12, ""),
    "refresh": ("float", (0.0, 60.0), 0.0),     # 0 = type default
    "hide_unavailable": ("bool", None, False),
    "smooth": ("bool", None, True),
    "alerts": ("bool", None, True),
    "warn": ("float", (0.0, 200.0), 0.0),       # 0 = automatic (hardware limits)
    "crit": ("float", (0.0, 200.0), 0.0),
    "blink_critical": ("bool", None, True),
}

THEME = {
    "font": ("font", None, "default"),
    "animations": ("bool", None, True),
    "reduce_motion": ("bool", None, False),
    "speed": ("int", (25, 300), 100),
    "pulse": ("bool", None, True),
    "alerts": ("bool", None, True),
    "hysteresis": ("float", (0.0, 20.0), 3.0),
    "cooldown": ("float", (0.0, 120.0), 5.0),
    "contrast_assist": ("choice", ("auto", "off", "always"), "auto"),
    "bg_effect": ("choice", ("none", "scanlines", "grid", "dots"), "none"),
    "bg_effect_strength": ("int", (0, 100), 25),
    "bg_effect_color": ("color", None, PALETTE["cyan"]),
    "demo": ("bool", None, False),
}

WALLPAPER = {
    "source": ("wallpaper", None, "builtin:cyberpunk"),
    "color": ("color", None, "#0B1020"),
    "color2": ("color", None, "#3A1450"),
    "angle": ("int", (0, 359), 135),
    "fit": ("choice", FITS, "cover"),
    "zoom": ("int", (100, 400), 100),
    "offset_x": ("int", (-100, 100), 0),
    "offset_y": ("int", (-100, 100), 0),
    "rotation": ("choice", (0, 90, 180, 270), 0),
    "mirror": ("bool", None, False),
    "flip": ("bool", None, False),
    "brightness": ("int", (0, 200), 100),
    "contrast": ("int", (0, 200), 100),
    "saturation": ("int", (0, 200), 100),
    "gamma": ("int", (50, 200), 100),
    "blur": ("int", (0, 20), 0),
    "darken": ("int", (0, 90), 0),
    "tint": ("color", None, "#000000"),
    "tint_strength": ("int", (0, 100), 0),
    "vignette": ("int", (0, 100), 0),
    "protect": ("int", (0, 100), 0),
    "protect_side": ("choice", ("bottom", "top", "left", "right", "both"), "bottom"),
}


def widget_types():
    return list(WIDGET_TYPES)


def type_label(widget_type):
    return WIDGET_TYPES[widget_type][0]


def default_refresh(widget_type):
    return WIDGET_TYPES[widget_type][4]


def _coerce(spec, value):
    """(clean value, ok)."""
    kind, constraint, default = spec
    if kind == "bool":
        return (value, True) if isinstance(value, bool) else (default, False)
    if kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
            return default, False
        low, high = constraint
        clamped = max(low, min(high, value))
        clamped = int(round(clamped)) if kind == "int" else float(clamped)
        return clamped, low <= value <= high
    if kind == "choice":
        return (value, True) if value in constraint else (default, False)
    if kind == "color":
        return (value.upper(), True) if isinstance(value, str) and COLOR.match(value) else (default, False)
    if kind == "text":
        if isinstance(value, str) and value.isprintable() and len(value) <= constraint:
            return value, True
        return default, False
    if kind == "font":
        if value == "default" or (isinstance(value, str) and FONT_FAMILY.match(value)):
            return value, True
        return default, False
    if kind == "wallpaper":
        if isinstance(value, str) and (value in ("color", "gradient")
                                       or (value.startswith("builtin:") and value[8:] in BUILTIN_WALLPAPERS)
                                       or (value.startswith("user:") and WALLPAPER_ID.match(value[5:]))):
            return value, True
        return default, False
    return default, False


def _section(data, schema, prefix, problems):
    result = {key: spec[2] for key, spec in schema.items()}
    if not isinstance(data, dict):
        if data is not None:
            problems.append(f"{prefix} is not an object")
        return result
    for key, value in data.items():
        if key in schema:
            result[key], ok = _coerce(schema[key], value)
            if not ok:
                problems.append(f"{prefix}.{key}={value!r} invalid, using {result[key]!r}")
    return result


def _geometry(value, default):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return default
    return float(max(-0.5, min(1.5, value)))


def new_widget(widget_type, widget_id, x=0.1, y=0.1, ref=(800, 480), **overrides):
    """A widget of ``widget_type`` with default size and options."""
    label, _styles, style, (w, h), _refresh, _metric = WIDGET_TYPES[widget_type]
    widget = {key: spec[2] for key, spec in COMMON.items()}
    widget.update({"id": widget_id, "type": widget_type, "style": style, "x": x, "y": y,
                   "w": w / ref[0], "h": h / ref[1],
                   "opts": {key: spec[2] for key, spec in OPTIONS.get(widget_type, {}).items()}})
    opts = overrides.pop("opts", None)
    widget.update(overrides)
    if opts:
        widget["opts"].update(opts)
    return widget


def validate_widget(data, problems, prefix="widget"):
    if not isinstance(data, dict) or data.get("type") not in WIDGET_TYPES:
        problems.append(f"{prefix}: unknown widget type {data.get('type') if isinstance(data, dict) else data!r}")
        return None
    widget_type = data["type"]
    widget_id = data.get("id")
    if not isinstance(widget_id, str) or not WIDGET_ID.match(widget_id):
        problems.append(f"{prefix}: invalid id {widget_id!r}")
        return None
    clean = _section(data, COMMON, f"{prefix}.{widget_id}", problems)
    styles = WIDGET_TYPES[widget_type][1]
    clean.update({"id": widget_id, "type": widget_type,
                  "style": data.get("style") if data.get("style") in styles else WIDGET_TYPES[widget_type][2]})
    default_w, default_h = WIDGET_TYPES[widget_type][3]
    clean["x"] = _geometry(data.get("x"), 0.1)
    clean["y"] = _geometry(data.get("y"), 0.1)
    clean["w"] = max(0.01, min(1.5, _geometry(data.get("w"), default_w / 800)))
    clean["h"] = max(0.01, min(1.5, _geometry(data.get("h"), default_h / 480)))
    clean["opts"] = _section(data.get("opts"), OPTIONS.get(widget_type, {}), f"{prefix}.{widget_id}.opts",
                             problems)
    return clean


def validate_layout(data, problems, prefix):
    if data is None:
        return None
    if not isinstance(data, list):
        problems.append(f"{prefix} is not a list")
        return []
    result, seen = [], set()
    for item in data[:MAX_WIDGETS]:
        widget = validate_widget(item, problems, prefix)
        if widget is not None and widget["id"] not in seen:
            seen.add(widget["id"])
            result.append(widget)
    if len(data) > MAX_WIDGETS:
        problems.append(f"{prefix}: more than {MAX_WIDGETS} widgets, extra ignored")
    return result


def _ref(value, default):
    if (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) and 16 <= v <= 4096 for v in value)):
        return [value[0], value[1]]
    return list(default)


def migrate(data):
    """Bring older Kojiro configurations to the current version (in place copy)."""
    data = copy.deepcopy(data) if isinstance(data, dict) else {}
    version = data.get("version", VERSION)
    if not isinstance(version, int) or version > VERSION:
        version = VERSION
    # Version 1 is the first one: nothing to convert yet. Future versions add steps here.
    data["version"] = VERSION
    return data


def validate(data):
    """(clean config, problems). Never raises; damaged parts fall back to defaults."""
    problems = []
    if data is None:
        return defaults(), problems
    if not isinstance(data, dict):
        return defaults(), ["kojiro is not an object"]
    data = migrate(data)
    clean = {"version": VERSION}
    clean["preset"] = data.get("preset") if isinstance(data.get("preset"), str) and \
        len(data.get("preset")) <= 40 and data["preset"].isprintable() else "custom"
    clean["theme"] = _section(data.get("theme"), THEME, "kojiro.theme", problems)
    clean["wallpaper"] = _section(data.get("wallpaper"), WALLPAPER, "kojiro.wallpaper", problems)
    clean["ref"] = _ref(data.get("ref"), (800, 480))
    clean["ref_portrait"] = _ref(data.get("ref_portrait"), (clean["ref"][1], clean["ref"][0]))
    layouts = data.get("layouts") if isinstance(data.get("layouts"), dict) else {}
    landscape = validate_layout(layouts.get("landscape"), problems, "kojiro.layouts.landscape")
    clean["layouts"] = {
        "landscape": landscape if landscape is not None else defaults()["layouts"]["landscape"],
        "portrait": validate_layout(layouts.get("portrait"), problems, "kojiro.layouts.portrait"),
    }
    return clean, problems


def defaults():
    from .presets import build
    return build("cyberpunk")


def layout_for(config, portrait):
    """(widgets, reference size) for an orientation; portrait may be generated."""
    if portrait:
        widgets = config["layouts"].get("portrait")
        if widgets is not None:
            return widgets, tuple(config["ref_portrait"])
        from .layout import reflow_portrait
        return reflow_portrait(config["layouts"]["landscape"], tuple(config["ref"]),
                               tuple(config["ref_portrait"])), tuple(config["ref_portrait"])
    return config["layouts"]["landscape"], tuple(config["ref"])


def next_id(widgets, widget_type):
    used = {w["id"] for w in widgets}
    base = widget_type.replace("_", "-")
    index = 1
    while f"{base}-{index}" in used:
        index += 1
    return f"{base}-{index}"


def uses_user_wallpaper(config):
    source = (config or {}).get("wallpaper", {}).get("source", "")
    return source[5:] if isinstance(source, str) and source.startswith("user:") else None
