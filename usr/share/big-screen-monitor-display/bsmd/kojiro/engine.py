"""Kojiro layer engine.

Composition per frame:

    base (cached)   wallpaper + effects + frosted regions + contrast panels
    widget layers   one cached RGBA layer per widget, re-rendered only when
                    what it shows changes (rounded values, animation phase)
    final image     base copy + layers in z-order -> RGB for the driver

The drivers diff consecutive frames, so a static wallpaper costs nothing
after the first frame: only the rectangles whose numbers changed travel over
USB. Telemetry is shared; ``needs`` tells the collector which optional
sensors (fans, disks, processes...) the visible widgets use.
"""

import collections
import json
import math
import time

from PIL import Image, ImageDraw, ImageFilter

from .. import compact, telemetry
from . import data, layout, model, wallpaper, widgets
from .draw import luminance_stats, rgb

LAYER_CACHE = 192
GEOMETRY_KEYS = ("x", "y", "w", "h", "anchor", "locked", "group")
MICRO_PRIORITY = ("clock", "cpu", "gpu", "ram", "net_down", "disk", "swap", "net_up", "fan")


class AlertState:
    """Discrete alert level with hysteresis and cooldown (no flapping)."""

    def __init__(self):
        self.level = 0
        self.changed = -1e9
        self.entered_crit = -1e9

    def update(self, value, warn, crit, hysteresis, cooldown, now):
        if value is None or warn is None or crit is None:
            self.level = 0
            return 0
        target = 2 if value >= crit else (1 if value >= warn else 0)
        if target < self.level:
            # Only step down once clearly below the threshold and after the cooldown.
            threshold = crit if self.level == 2 else warn
            if value > threshold - hysteresis or now - self.changed < cooldown:
                target = self.level
        if target != self.level:
            if target == 2:
                self.entered_crit = now
            self.level = target
            self.changed = now
        return self.level


def continuous_level(value, warn, crit):
    """0..2 for the gradual colour (starts shifting 10 units before ``warn``)."""
    if value is None or warn is None or crit is None:
        return 0.0
    if value < warn:
        return max(0.0, (value - (warn - 10)) / 10) * 0.6
    if value < crit:
        return 1.0 + (value - warn) / max(1e-6, crit - warn)
    return 2.0


def _signature(widget):
    return json.dumps({k: v for k, v in widget.items() if k not in GEOMETRY_KEYS}, sort_keys=True)


def micro_layout(widgets_, size):
    """Up to three/four readable rows for tiny panels (80x160 and similar)."""
    width, height = size
    visible = {w["type"]: w for w in widgets_ if w.get("visible", True)}
    chosen = [visible[t] for t in MICRO_PRIORITY if t in visible][:4 if height > width else 3]
    if not chosen:
        return []
    rows = len(chosen)
    result = []
    for index, widget in enumerate(chosen):
        clone = dict(widget, opts=dict(widget.get("opts", {})))
        clone.update({"x": 0.04, "y": 0.03 + index * 0.94 / rows, "w": 0.92, "h": 0.94 / rows * 0.92,
                      "anchor": "tl", "rotation": 0, "glow": min(widget.get("glow", 0), 30)})
        if widget["type"] == "clock":
            clone["style"] = "plain"
            clone["opts"]["date"] = False
            clone["opts"]["weekday"] = False
        elif widget["type"] in ("cpu", "gpu", "ram", "swap", "disk"):
            clone["style"] = "bar"
            clone["show_icon"] = False
        else:
            clone["style"] = "text"
        result.append(clone)
    return result


class KojiroTheme:
    def __init__(self, info, ctx=None):
        self.info = info
        self.layers = collections.OrderedDict()
        self.metrics = {}
        self.alerts = {}
        self.smoothed = {}
        self.fan_angles = {}
        self.needs = data.needs([])
        self.animating = False
        self.clock_seconds = False
        self._base_key = None
        self._base = None
        self._panels = {}
        self._last = time.monotonic()
        self.boxes = {}                 # id -> pixel box of the last frame (editor hit-testing)
        self.render_ms = 0.0

    # ------------------------------------------------------------ helpers
    def _config(self, settings):
        config = settings.get("kojiro")
        if not isinstance(config, dict) or "layouts" not in config:
            config, _problems = model.validate(config)
        return config

    def _base_image(self, config, size, visible, boxes, store_dir):
        theme = config["theme"]
        frosted = tuple((w["id"], boxes[w["id"]], w["frost"], w.get("radius", 12)) for w in visible
                        if w.get("frost", 0) > 0)
        assist = theme.get("contrast_assist", "auto")
        assisted = tuple((w["id"], boxes[w["id"]]) for w in visible
                         if w.get("bg_opacity", 0) == 0 and assist != "off"
                         and w["type"] not in ("separator", "frame", "distro"))
        key = (json.dumps(config["wallpaper"], sort_keys=True), theme.get("bg_effect"),
               theme.get("bg_effect_strength"), theme.get("bg_effect_color"), size, frosted, assisted, assist,
               store_dir)
        if key == self._base_key:
            return self._base
        image = wallpaper.render(config["wallpaper"], theme, size, store_dir).convert("RGBA")
        scale = min(size) / 480
        for _id, (x, y, w, h), frost, radius in frosted:
            region = image.crop((x, y, x + w, y + h)).filter(ImageFilter.GaussianBlur(frost * scale * 1.5))
            mask = Image.new("L", region.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=min(w, h) * radius / 100, fill=255)
            image.paste(region, (x, y), mask)
        panels = {}
        for widget_id, (x, y, w, h) in assisted:
            region = image.crop((max(0, x), max(0, y), min(size[0], x + w), min(size[1], y + h)))
            if region.width < 2 or region.height < 2:
                continue
            mean, spread = luminance_stats(region)
            if assist == "always" or mean > 0.5 or spread > 0.42:
                strength = 0.55 if assist == "always" else min(0.7, 0.35 + max(mean - 0.5, spread - 0.42))
                panels[widget_id] = ((6, 8, 16), strength)
        self._base_key, self._base, self._panels = key, image, panels
        return image

    def _metric(self, widget, stats, now, demo):
        refresh = widget.get("refresh") or model.default_refresh(widget["type"])
        cached = self.metrics.get(widget["id"])
        signature = (widget["type"], json.dumps(widget.get("opts", {}), sort_keys=True), widget.get("label"),
                     widget.get("unit"), widget.get("decimals"), widget.get("warn"), widget.get("crit"), demo)
        if widget["type"] == "clock" or cached is None or cached[2] != signature or now - cached[0] >= refresh:
            metric = data.metric(widget, stats, now)
            self.metrics[widget["id"]] = (now, metric, signature)
            return metric
        return cached[1]

    def _state(self, widget, metric, theme, now, dt):
        state = {}
        animations = theme.get("animations", True) and not theme.get("reduce_motion", False)
        speed = theme.get("speed", 100) / 100
        wid = widget["id"]
        if theme.get("alerts", True) and widget.get("alerts", True) and metric.alert_value is not None:
            alert = self.alerts.setdefault(wid, AlertState())
            level = alert.update(metric.alert_value, metric.warn, metric.crit, theme.get("hysteresis", 3.0),
                                 theme.get("cooldown", 5.0), now)
            state["alert"] = round(continuous_level(metric.alert_value, metric.warn, metric.crit), 2)
            if level >= 1 and widget["type"] == "disk":
                state["attention"] = True
            if level == 2 and animations and now - alert.entered_crit < 8.0:
                phase = 0.5 + 0.5 * math.sin((now - alert.entered_crit) * 2 * math.pi / 1.2 * speed)
                if theme.get("pulse", True):
                    state["glow_boost"] = round(1 + 0.8 * phase, 1)
                if widget.get("blink_critical", True):
                    state["alpha"] = round(0.6 + 0.4 * phase, 1)
                self.animating = True
        if widget["type"] in ("net_down", "net_up"):
            state["glow_boost"] = round(1 + 0.8 * metric.extra.get("intensity", 0), 1)
        if widget["type"] == "fan" and metric.available and metric.rpm and widget.get("opts", {}).get("spin", True):
            if animations:
                angle = self.fan_angles.get(wid, 0.0) + min(540.0, metric.rpm * 0.25) * speed * dt
                self.fan_angles[wid] = angle % 360
                state["fan_angle"] = int(self.fan_angles[wid] / 6) * 6      # 60 cached poses
                self.animating = True
        if animations and widget.get("smooth", True) and metric.available:
            current = self.smoothed.get(wid, metric.fraction)
            target = metric.fraction
            if abs(target - current) > 0.004:
                current += (target - current) * min(1.0, dt * 6 * speed)
                self.animating = True
            else:
                current = target
            self.smoothed[wid] = current
            if current != metric.fraction:
                metric = _with_fraction(metric, current)
        return state, metric

    def _layer(self, widget, metric, size, theme, state):
        panel = self._panels.get(widget["id"])
        key = (widget["id"], _signature(widget), metric.key(), size, tuple(sorted(state.items())), panel,
               theme.get("font"))
        layer = self.layers.get(key)
        if layer is not None:
            self.layers.move_to_end(key)
            return layer
        layer = widgets.render(widget, metric, size, theme, state, panel)
        self.layers[key] = layer
        while len(self.layers) > LAYER_CACHE:
            self.layers.popitem(last=False)
        return layer

    # ------------------------------------------------------------ theme API
    def render(self, width, height, settings, ctx=None, store_dir=None, only=None):
        started = time.perf_counter()
        now = time.time()
        monotonic = time.monotonic()
        dt = min(1.0, max(0.0, monotonic - self._last))
        self._last = monotonic
        config = self._config(settings)
        theme = config["theme"]
        size = (width, height)
        widget_list, ref = model.layout_for(config, height > width)
        if compact.needed(width, height):
            widget_list, ref = micro_layout(widget_list, size), size
        demo = theme.get("demo") or bool(getattr(ctx, "demo", False))
        stats = data.demo_stats(now) if demo else (ctx.telemetry() if ctx is not None and hasattr(ctx, "telemetry")
                                                   else telemetry.snapshot())
        visible = [w for w in widget_list if w.get("visible", True) and (only is None or w["id"] in only)]
        boxes = {w["id"]: layout.int_box(layout.to_pixels(w, size, ref)) for w in widget_list}
        self.boxes = boxes
        frame = self._base_image(config, size, visible, boxes, store_dir).copy()
        self.animating = False
        self.clock_seconds = False
        for widget in visible:
            metric = self._metric(widget, stats, now, demo)
            hide = widget.get("hide_unavailable") or (widget["type"] == "swap"
                                                      and widget.get("opts", {}).get("hide_when_none"))
            if not metric.available and hide:
                continue
            if widget["type"] == "clock":
                opts = widget.get("opts", {})
                self.clock_seconds = self.clock_seconds or opts.get("seconds") or opts.get("blink", True)
            state, metric = self._state(widget, metric, theme, now, dt)
            x, y, w, h = boxes[widget["id"]]
            (layer, (pad_x, pad_y)) = self._layer(widget, metric, (w, h), theme, state)
            _composite(frame, layer, x - pad_x, y - pad_y)
        self.needs = data.needs(widget_list)
        self.render_ms = (time.perf_counter() - started) * 1000
        return frame.convert("RGB")

    def frame_interval(self, settings, ctx):
        if self.animating:
            return 1.0 / max(1.0, getattr(ctx, "target_fps", 8.0) if ctx is not None else 8.0)
        # Static content: wake on the next wall-clock second (clock digits stay
        # exact), twice per second with the fluid profile.
        from ..themes import static_interval
        return static_interval(settings, ctx, base=1.0)

    def close(self):
        self.layers.clear()
        self.metrics.clear()


def _with_fraction(metric, fraction):
    import dataclasses
    return dataclasses.replace(metric, fraction=round(fraction, 3))


def _composite(frame, layer, x, y):
    """alpha_composite that tolerates layers partly outside the frame."""
    x, y = int(x), int(y)
    left, top = max(0, -x), max(0, -y)
    right = min(layer.width, frame.width - x)
    bottom = min(layer.height, frame.height - y)
    if right <= left or bottom <= top:
        return
    if (left, top, right, bottom) != (0, 0, layer.width, layer.height):
        layer = layer.crop((left, top, right, bottom))
    frame.alpha_composite(layer, (x + left, y + top))


def wallpaper_rgb(hex_color):
    return rgb(hex_color)
