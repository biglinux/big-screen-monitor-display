"""Ready-made Kojiro compositions.

Every preset is laid out on an 800x480 reference canvas; ``layout`` adapts it
to other panels (anchors keep corner widgets in their corners). Colours of
the Cyberpunk preset follow the reference palette: cyan #42E8FF, magenta
#F044DB, red #FF475C, green #83EF4C, yellow #FFD94A, soft white #E8F4FF.
"""

from ..i18n import N_
from .model import PALETTE, THEME, VERSION, WALLPAPER, new_widget

C, M, R, G, Y, W = (PALETTE[k] for k in ("cyan", "magenta", "red", "green", "yellow", "white"))

PRESETS = {
    "cyberpunk": (N_("Kojiro Cyberpunk"), N_("Neon HUD over a futuristic city, as in the reference design.")),
    "minimal": (N_("Kojiro Minimal"), N_("Few discreet elements and thin lines, made for photographs.")),
    "gamer": (N_("Kojiro Gamer"), N_("Big CPU and GPU gauges with temperatures, clocks and VRAM.")),
    "matrix": (N_("Kojiro Matrix"), N_("Green terminal look with monospaced text.")),
    "retro": (N_("Kojiro Retro"), N_("Old computer colours, segmented bars and pixel fonts.")),
    "glass": (N_("Kojiro Glass"), N_("Translucent frosted panels over the wallpaper.")),
    "industrial": (N_("Kojiro Industrial"), N_("Instrument gauges with needles and clear alerts.")),
}


def _base(preset, wallpaper=None, theme=None):
    config = {"version": VERSION, "preset": preset, "ref": [800, 480], "ref_portrait": [480, 800],
              "theme": {key: spec[2] for key, spec in THEME.items()},
              "wallpaper": {key: spec[2] for key, spec in WALLPAPER.items()},
              "layouts": {"landscape": [], "portrait": None}}
    config["wallpaper"].update(wallpaper or {})
    config["theme"].update(theme or {})
    return config


def _px(x, y, w, h):
    return {"x": x / 800, "y": y / 480, "w": w / 800, "h": h / 480}


def _w(widget_type, widget_id, box, **props):
    widget = new_widget(widget_type, widget_id)
    widget.update(_px(*box))
    opts = props.pop("opts", None)
    widget.update(props)
    if opts:
        widget["opts"].update(opts)
    return widget


def cyberpunk():
    config = _base("cyberpunk", {"source": "builtin:cyberpunk", "darken": 10, "vignette": 35})
    config["layouts"]["landscape"] = [
        _w("ram", "ram-1", (22, 18, 300, 54), color=C, color2=C),
        _w("swap", "swap-1", (22, 78, 300, 54), color=M, color2=M),
        _w("cpu", "cpu-1", (22, 146, 150, 150), color=R, color2=Y),
        _w("gpu", "gpu-1", (184, 146, 150, 150), color=G, color2=Y),
        _w("fan", "fan-1", (22, 322, 150, 64), color=C, align="left"),
        _w("encdec", "encdec-1", (22, 398, 170, 56), color=M),
        _w("disk", "disk-1", (578, 18, 200, 92), color=Y, color2=Y, anchor="tr"),
        _w("net_down", "net-down-1", (578, 124, 200, 48), color=C, anchor="tr"),
        _w("net_up", "net-up-1", (578, 176, 200, 48), color=M, anchor="tr"),
        _w("clock", "clock-1", (280, 386, 240, 78), color=C, text_color=W, anchor="bc", align="center"),
        _w("distro", "distro-1", (662, 330, 120, 134), color=C, text_color=W, anchor="br", align="center"),
    ]
    return config


def minimal():
    config = _base("minimal", {"source": "builtin:minimal"}, {"animations": False, "contrast_assist": "auto"})
    soft = "#DDE6F0"
    common = {"glow": 0, "shadow": True, "bold": False, "color": soft, "text_color": soft}
    config["layouts"]["landscape"] = [
        _w("clock", "clock-1", (34, 28, 320, 110), style="plain", opts={"date": True, "weekday": True}, **common),
        _w("cpu", "cpu-1", (40, 330, 180, 46), style="text", show_icon=False, opts={"show_freq": False}, **common),
        _w("ram", "ram-1", (40, 380, 300, 40), style="bar", show_icon=False, **common),
        _w("net_down", "net-down-1", (560, 400, 200, 34), anchor="br", show_icon=False, **common),
        _w("net_up", "net-up-1", (560, 432, 200, 34), anchor="br", show_icon=False, **common),
        _w("separator", "separator-1", (40, 318, 300, 6), style="line", **common),
    ]
    return config


def gamer():
    config = _base("gamer", {"source": "builtin:neon_grid", "darken": 15})
    orange = "#FF8A3D"
    config["layouts"]["landscape"] = [
        _w("cpu", "cpu-1", (40, 70, 230, 230), style="gauge", color=R, color2=orange,
           opts={"show_model": False}),
        _w("gpu", "gpu-1", (530, 70, 230, 230), style="gauge", color=G, color2=Y, anchor="tr",
           opts={"show_vram": False, "show_power": True}),
        _w("vram", "vram-1", (300, 120, 200, 54), color=M, anchor="tc"),
        _w("ram", "ram-1", (300, 186, 200, 54), color=C, anchor="tc"),
        _w("fan", "fan-1", (325, 250, 150, 64), color=C, anchor="c"),
        _w("cores", "cores-1", (40, 330, 300, 100), color=R, anchor="bl"),
        _w("clock", "clock-1", (280, 18, 240, 70), style="digital", color=orange, anchor="tc", align="center",
           opts={"date": False}),
        _w("net_down", "net-down-1", (560, 340, 200, 48), style="graph_area", color=C, anchor="br"),
        _w("net_up", "net-up-1", (560, 394, 200, 48), style="graph_area", color=M, anchor="br"),
    ]
    return config


def matrix():
    green, dim = "#33FF77", "#1E8F47"
    config = _base("matrix", {"source": "builtin:matrix"}, {"bg_effect": "scanlines", "bg_effect_color": green,
                                                              "font": "default"})
    common = {"color": green, "color2": dim, "text_color": green, "text_style": "mono", "glow": 35,
              "bg": "#000A03", "bg_opacity": 55, "radius": 0, "border": 1, "border_color": dim}
    config["layouts"]["landscape"] = [
        _w("hostname", "hostname-1", (24, 20, 300, 36), **common),
        _w("kernel", "kernel-1", (24, 60, 300, 36), **common),
        _w("cpu", "cpu-1", (24, 112, 360, 110), style="graph_line", **common),
        _w("ram", "ram-1", (24, 236, 360, 52), style="bar_segmented", **common),
        _w("swap", "swap-1", (24, 296, 360, 52), style="bar_segmented", **common),
        _w("processes", "processes-1", (420, 112, 356, 176), anchor="tr", **common),
        _w("net_down", "net-down-1", (420, 300, 172, 48), anchor="tr", **common),
        _w("net_up", "net-up-1", (604, 300, 172, 48), anchor="tr", **common),
        _w("clock", "clock-1", (24, 380, 300, 80), style="plain", anchor="bl", **common),
        _w("uptime", "uptime-1", (476, 412, 300, 44), anchor="br", align="right", **common),
    ]
    return config


def retro():
    amber, dark = "#FFB000", "#5A3A00"
    config = _base("retro", {"source": "builtin:retro"}, {"bg_effect": "scanlines", "bg_effect_strength": 35,
                                                            "bg_effect_color": "#000000"})
    common = {"color": amber, "color2": dark, "text_color": amber, "text_style": "pixel", "glow": 20, "radius": 0,
              "bg": "#1A1000", "bg_opacity": 70, "border": 2, "border_color": amber}
    config["layouts"]["landscape"] = [
        _w("clock", "clock-1", (24, 20, 300, 80), style="plain", opts={"weekday": False}, **common),
        _w("cpu", "cpu-1", (24, 116, 360, 60), style="bar_segmented", **common),
        _w("gpu", "gpu-1", (24, 186, 360, 60), style="bar_segmented", **common),
        _w("ram", "ram-1", (24, 256, 360, 60), **common),
        _w("disk", "disk-1", (24, 326, 360, 60), style="bar_segmented", **common),
        _w("cores", "cores-1", (420, 116, 356, 130), anchor="tr", **common),
        _w("net_down", "net-down-1", (420, 256, 356, 60), anchor="tr", **common),
        _w("net_up", "net-up-1", (420, 326, 356, 60), anchor="tr", **common),
        _w("distro", "distro-1", (420, 396, 356, 64), style="name", anchor="br", align="right", **common),
    ]
    return config


def glass():
    config = _base("glass", {"source": "builtin:glass"}, {"contrast_assist": "off"})
    common = {"bg": "#FFFFFF", "bg_opacity": 14, "frost": 8, "border": 1, "border_color": "#FFFFFF", "radius": 18,
              "glow": 10, "text_color": "#F4F8FF", "shadow": True}
    config["layouts"]["landscape"] = [
        _w("clock", "clock-1", (30, 30, 340, 120), style="plain", color="#FFFFFF", align="left", **common),
        _w("cpu", "cpu-1", (30, 180, 160, 160), style="ring", color="#7FD6FF", color2="#FFD27F", **common),
        _w("gpu", "gpu-1", (210, 180, 160, 160), style="ring", color="#9CFFB4", color2="#FFD27F", **common),
        _w("ram", "ram-1", (30, 360, 340, 54), style="bar", color="#7FD6FF", **common),
        _w("net_down", "net-down-1", (570, 30, 200, 52), anchor="tr", color="#7FD6FF", **common),
        _w("net_up", "net-up-1", (570, 92, 200, 52), anchor="tr", color="#FF9BE8", **common),
        _w("disk", "disk-1", (570, 160, 200, 96), anchor="tr", color="#FFD27F", **common),
        _w("distro", "distro-1", (650, 320, 120, 130), anchor="br", color="#FFFFFF", align="center", **common),
    ]
    return config


def industrial():
    steel, warn = "#C8D0D8", "#FFB627"
    config = _base("industrial", {"source": "builtin:industrial"}, {"bg_effect": "none"})
    common = {"color": warn, "color2": "#FF5A36", "text_color": steel, "glow": 15, "bg": "#15181C",
              "bg_opacity": 75, "border": 2, "border_color": "#596370", "radius": 6}
    config["layouts"]["landscape"] = [
        _w("cpu", "cpu-1", (24, 24, 220, 220), style="gauge", **common),
        _w("gpu", "gpu-1", (264, 24, 220, 220), style="gauge", **common),
        _w("fan", "fan-1", (504, 24, 272, 104), anchor="tr", **common),
        _w("disk", "disk-1", (504, 140, 272, 104), anchor="tr", style="bar_segmented", **common),
        _w("ram", "ram-1", (24, 262, 460, 60), style="bar_segmented", **common),
        _w("swap", "swap-1", (24, 332, 460, 60), style="bar_segmented", **common),
        _w("clock", "clock-1", (504, 262, 272, 130), style="digital", anchor="br", align="center", **common),
        _w("frame", "frame-1", (12, 12, 776, 400), style="corners", color=warn, glow=0),
        _w("text", "text-1", (24, 414, 460, 44), anchor="bl", opts={"text": "KOJIRO // INDUSTRIAL"},
           text_style="mono", **{k: v for k, v in common.items() if k not in ("bg_opacity",)}),
    ]
    return config


BUILDERS = {"cyberpunk": cyberpunk, "minimal": minimal, "gamer": gamer, "matrix": matrix, "retro": retro,
            "glass": glass, "industrial": industrial}


def build(name):
    return BUILDERS.get(name, cyberpunk)()


def names():
    return list(BUILDERS)
