"""Touch interaction for panels with a touchscreen (FOSTON FS-707DC).

Touches never leave the service: they are recognised as gestures and drive
an interface drawn on the panel itself (a control bar, a menu with the theme
gallery, a touch test). Nothing is injected into the desktop (no uinput, no
XTest), so the main computer's keyboard focus, open menus and mouse drags
are never disturbed, on X11 and Wayland alike.

Single-point only: resistive panels report one contact, so there are no
multi-finger gestures. Gestures: tap, long press (0.7 s), swipe and drag.

Choices made on the panel (theme, brightness) are kept as per-display
overrides in the service state directory. They are dropped as soon as the
same setting is changed in the configuration window, so the window always
wins and the two never fight.
"""

import json
import logging
import math
import os
import threading
import time

from PIL import ImageDraw

from . import settings as settings_mod
from .i18n import _, N_

log = logging.getLogger("bsmd")

DOWN, MOVE, UP = 1, 2, 3          # same values as the FSP touch kinds
TAP_MAX_MOVE = 20                 # px
LONG_PRESS = 0.7                  # s
SWIPE_MIN = 100                   # px
SWIPE_MAX_TIME = 0.9              # s
OVERLAY_SECONDS = 6.0
MENU_SECONDS = 20.0
TEST_SECONDS = 60.0
RIPPLE_SECONDS = 0.45
ACTIVE_INTERVAL = 0.12            # s between frames while the overlay animates
OVERRIDE_KEYS = ("theme", "brightness")
BRIGHTNESS_STEP = 10

THEME_LABELS = {"standard": N_("Standard"), "gkrellm": N_("GKrellM"), "planet": N_("Planet"),
                "old_computer": N_("Old Computer"), "brother_away": N_("Brother Away"), "kojiro": N_("Kojiro"),
                "big_media_player": N_("Big Media Player")}


def native_to_render(x, y, native_size, orientation):
    """Map a touch on the landscape panel to the coordinates themes draw in.

    Inverse of :func:`bsmd.frames.to_native` (PIL ROTATE_90 is
    counter-clockwise; tests check this against real transposes)."""
    width, height = native_size
    x = min(max(int(x), 0), width - 1)
    y = min(max(int(y), 0), height - 1)
    if orientation == "vertical":                 # render (h x w) rotated 90 deg CCW
        return height - 1 - y, x
    if orientation == "vertical_flipped":         # rotated 270 deg CCW
        return y, width - 1 - x
    if orientation == "horizontal_flipped":
        return width - 1 - x, height - 1 - y
    return x, y


class GestureRecognizer:
    def __init__(self):
        self.start = None             # (x, y, t)
        self.last = None
        self.moved = False
        self.long_fired = False

    def feed(self, kind, x, y, now):
        out = []
        if kind == DOWN or (kind == MOVE and self.start is None):
            self.start, self.last, self.moved, self.long_fired = (x, y, now), (x, y), False, False
            out.append(("press", x, y))
            return out
        if self.start is None:
            return out
        sx, sy, st = self.start
        self.last = (x, y)
        if math.hypot(x - sx, y - sy) > TAP_MAX_MOVE:
            self.moved = True
        if kind == MOVE:
            if self.moved:
                out.append(("drag", x, y))
            return out
        # UP
        dx, dy, dt = x - sx, y - sy, now - st
        if not self.moved:
            if dt >= LONG_PRESS:
                if not self.long_fired:
                    out.append(("long_press", sx, sy))
            else:
                out.append(("tap", sx, sy))
        elif dt <= SWIPE_MAX_TIME and max(abs(dx), abs(dy)) >= SWIPE_MIN:
            if abs(dx) >= 1.5 * abs(dy):
                out.append(("swipe_left" if dx < 0 else "swipe_right", sx, sy))
            elif abs(dy) >= 1.5 * abs(dx):
                out.append(("swipe_up" if dy < 0 else "swipe_down", sx, sy))
        out.append(("release", x, y))
        self.start = None
        return out

    def tick(self, now):
        if self.start and not self.moved and not self.long_fired and now - self.start[2] >= LONG_PRESS:
            self.long_fired = True
            return [("long_press", self.start[0], self.start[1])]
        return []


class TouchOverrides:
    """Theme/brightness chosen on the panel, persisted per display."""

    def __init__(self, path):
        self.path = path
        self.values = {}              # key -> {"value": v, "base": value in settings when chosen}
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.values = {key: entry for key, entry in data.items()
                           if key in OVERRIDE_KEYS and isinstance(entry, dict) and "value" in entry}

    def _save(self):
        if not self.path:
            return
        try:
            settings_mod.atomic_write_json(self.path, self.values, mode=0o600)
        except OSError as error:
            log.warning("cannot save touch choices to %s: %s", self.path, error)

    def set(self, key, value, base):
        self.values[key] = {"value": value, "base": base}
        self._save()

    def apply(self, settings):
        """Settings with the panel's choices; stale ones (changed in the window) are dropped."""
        result = dict(settings)
        stale = [key for key, entry in self.values.items() if settings.get(key) != entry.get("base")]
        for key in stale:
            del self.values[key]
        if stale:
            self._save()
        for key, entry in self.values.items():
            value = entry["value"]
            if key == "theme" and value not in settings_mod.THEME_IDS:
                continue
            if key == "brightness" and not (isinstance(value, int) and 0 <= value <= 100):
                continue
            result[key] = value
        return result


class TouchUI:
    """Gestures -> actions, and the overlay drawn on top of each frame.

    ``host`` provides: ``base_settings()`` (settings without the panel's
    choices), ``request(command, *args)`` (session commands), ``wake()``,
    ``name()`` and ``state()`` (connection label)."""

    def __init__(self, host, state_path=None, clock=time.monotonic):
        self.host = host
        self.clock = clock
        self.overrides = TouchOverrides(state_path)
        self.recognizer = GestureRecognizer()
        self.lock = threading.RLock()         # decorate() asks the host for its name, which reads settings
        self.page = None              # None, "bar", "menu", "test"
        self.until = 0.0
        self.ripples = []             # (x, y, t)
        self.trail = []               # touch test points
        self.buttons = []             # (box, action, arg) of the last drawn overlay
        self.pressed = None           # button box under the finger
        self.toast = None             # (text, until)
        self.last_event = None
        self.events = 0

    # ------------------------------------------------------------ input
    def handle(self, kind, x, y):
        now = self.clock()
        with self.lock:
            self.events += 1
            self.last_event = now
            gestures = self.recognizer.feed(kind, x, y, now)
            for gesture in gestures:
                self._gesture(gesture, now)
        self.host.wake()

    def tick(self):
        now = self.clock()
        with self.lock:
            for gesture in self.recognizer.tick(now):
                self._gesture(gesture, now)
            if self.page and now >= self.until:
                self.page = None
            if self.toast and now >= self.toast[1]:
                self.toast = None
            self.ripples = [r for r in self.ripples if now - r[2] < RIPPLE_SECONDS]

    def _button_at(self, x, y):
        for box, action, arg in self.buttons:
            if box[0] <= x < box[2] and box[1] <= y < box[3]:
                return box, action, arg
        return None

    def _gesture(self, gesture, now):
        name, x, y = gesture
        if name == "press":
            self.ripples.append((x, y, now))
            hit = self._button_at(x, y) if self.page else None
            self.pressed = hit[0] if hit else None
            if self.page == "test":
                self.trail.append((x, y, now, True))
            return
        if name == "drag":
            self.pressed = None
            if self.page == "test":
                self.trail.append((x, y, now, False))
                self.trail = self.trail[-400:]
            return
        if name == "release":
            self.pressed = None
            return
        if self.page == "test":
            self.until = now + TEST_SECONDS
            if name == "long_press":
                self._open(None, now)
            return
        if name == "tap":
            hit = self._button_at(x, y) if self.page else None
            if hit:
                self._action(hit[1], hit[2], now)
            elif self.page == "menu":
                self._open(None, now)
            elif self.page == "bar":
                self.until = now + OVERLAY_SECONDS
            else:
                self._open("bar", now)
        elif name == "long_press":
            self._open("menu", now)
        elif name in ("swipe_left", "swipe_right"):
            self._cycle_theme(1 if name == "swipe_left" else -1, now)
        elif name == "swipe_up":
            self._open("menu", now)
        elif name == "swipe_down":
            self._open(None, now)

    def _open(self, page, now):
        self.page = page
        self.until = now + {"bar": OVERLAY_SECONDS, "menu": MENU_SECONDS, "test": TEST_SECONDS}.get(page, 0)
        if page == "test":
            self.trail = []

    def _settings(self):
        return self.overrides.apply(self.host.base_settings())

    def _set(self, key, value):
        base = self.host.base_settings().get(key)
        self.overrides.set(key, value, base)

    def _cycle_theme(self, step, now):
        themes = list(settings_mod.THEME_IDS)
        current = self._settings().get("theme")
        index = themes.index(current) if current in themes else 0
        theme = themes[(index + step) % len(themes)]
        self._set("theme", theme)
        self.toast = (_(THEME_LABELS.get(theme, theme)), now + 1.6)
        if self.page == "bar":
            self.until = now + OVERLAY_SECONDS
        self.host.request("invalidate")

    def _action(self, action, arg, now):
        if action == "theme_prev":
            self._cycle_theme(-1, now)
        elif action == "theme_next":
            self._cycle_theme(1, now)
        elif action == "theme":
            self._set("theme", arg)
            self.toast = (_(THEME_LABELS.get(arg, arg)), now + 1.6)
            self._open(None, now)
            self.host.request("invalidate")
        elif action == "brightness":
            if not getattr(self.host, "brightness_supported", lambda: True)():
                return
            value = max(10, min(100, int(self._settings().get("brightness", 80)) + arg))
            self._set("brightness", value)
            self.host.request("brightness", value)
            self.toast = (_("Brightness {value}%").format(value=value), now + 1.2)
            self.until = now + OVERLAY_SECONDS
        elif action == "menu":
            self._open("menu", now)
        elif action == "close":
            self._open(None, now)
        elif action == "test":
            self._open("test", now)
        elif action == "calibrate":
            self._open(None, now)
            self.host.request("calibrate")

    def start_test(self):
        with self.lock:
            self._open("test", self.clock())
        self.host.wake()

    def apply(self, settings):
        with self.lock:
            return self.overrides.apply(settings)

    def active(self):
        """True while something on the overlay animates (render faster)."""
        with self.lock:
            return bool(self.page or self.ripples or self.toast or self.recognizer.start)

    # ------------------------------------------------------------ drawing
    def decorate(self, image, settings):
        self.tick()
        with self.lock:
            if not (self.page or self.ripples or self.toast):
                self.buttons = []
                return image
            image = image.convert("RGB") if image.mode != "RGB" else image.copy()
            draw = ImageDraw.Draw(image, "RGBA")
            width, height = image.size
            self.buttons = []
            if self.page == "test":
                self._draw_test(draw, width, height)
            elif self.page == "menu":
                self._draw_menu(draw, width, height, settings)
            elif self.page == "bar":
                self._draw_header(draw, width, height, settings)
                self._draw_bar(draw, width, height, settings)
            if self.toast:
                self._draw_toast(draw, width, height, self.toast[0])
            now = self.clock()
            for x, y, t in self.ripples:
                age = (now - t) / RIPPLE_SECONDS
                radius = 10 + age * min(width, height) * 0.09
                alpha = int(200 * (1 - age))
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), outline=(255, 255, 255, alpha),
                             width=max(2, int(4 * (1 - age)) + 1))
            return image

    @staticmethod
    def _font(size, bold=False):
        from .bigmedia.paint import font
        return font(size, bold)

    def _text(self, draw, box, text, size, fill=(255, 255, 255, 255), bold=False):
        font = self._font(size, bold)
        while size > 8 and draw.textlength(text, font=font) > box[2] - box[0] - 8:
            size -= 1
            font = self._font(size, bold)
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font=font, fill=fill, anchor="mm")

    def _draw_header(self, draw, width, height, settings):
        bar = max(30, height // 12)
        draw.rectangle((0, 0, width, bar), fill=(10, 14, 22, 215))
        now = time.localtime()
        size = int(bar * 0.55)
        draw.text((12, bar / 2), time.strftime("%H:%M", now), font=self._font(size, True), fill=(255, 255, 255),
                  anchor="lm")
        date = time.strftime("%d/%m/%Y", now)
        draw.text((12 + size * 3.2, bar / 2), date, font=self._font(int(size * 0.8)), fill=(190, 200, 215),
                  anchor="lm")
        state = self.host.state()
        dot = (46, 194, 126) if state == "healthy" else (246, 211, 45)
        label = self.host.name()
        right = width - 12
        draw.text((right, bar / 2), label, font=self._font(int(size * 0.8)), fill=(220, 226, 235), anchor="rm")
        lw = draw.textlength(label, font=self._font(int(size * 0.8)))
        cx = right - lw - 14
        draw.ellipse((cx - 6, bar / 2 - 6, cx + 6, bar / 2 + 6), fill=dot)

    def _button(self, draw, box, action, arg=None, accent=False):
        pressed = self.pressed == box
        color = (53, 132, 228, 235) if accent else (40, 48, 62, 225)
        if pressed:
            color = (98, 160, 234, 245)
        draw.rounded_rectangle(box, radius=max(6, (box[3] - box[1]) // 5), fill=color,
                               outline=(255, 255, 255, 40), width=1)
        self.buttons.append((box, action, arg))

    @staticmethod
    def _icon(draw, kind, cx, cy, s, fill=(255, 255, 255, 255)):
        if kind == "prev":
            draw.polygon(((cx + s * 0.45, cy - s * 0.6), (cx - s * 0.55, cy), (cx + s * 0.45, cy + s * 0.6)), fill=fill)
        elif kind == "next":
            draw.polygon(((cx - s * 0.45, cy - s * 0.6), (cx + s * 0.55, cy), (cx - s * 0.45, cy + s * 0.6)), fill=fill)
        elif kind in ("sun_minus", "sun_plus"):
            r = s * 0.28
            draw.ellipse((cx - r - s * 0.25, cy - r, cx + r - s * 0.25, cy + r), fill=fill)
            for i in range(8):
                a = i * math.pi / 4
                x0, y0 = cx - s * 0.25 + math.cos(a) * r * 1.4, cy + math.sin(a) * r * 1.4
                x1, y1 = cx - s * 0.25 + math.cos(a) * r * 1.9, cy + math.sin(a) * r * 1.9
                draw.line((x0, y0, x1, y1), fill=fill, width=max(2, int(s * 0.08)))
            w = max(3, int(s * 0.12))
            draw.line((cx + s * 0.35, cy, cx + s * 0.75, cy), fill=fill, width=w)
            if kind == "sun_plus":
                draw.line((cx + s * 0.55, cy - s * 0.2, cx + s * 0.55, cy + s * 0.2), fill=fill, width=w)
        elif kind == "menu":
            q = s * 0.26
            for dx in (-1, 1):
                for dy in (-1, 1):
                    x, y = cx + dx * q * 1.15, cy + dy * q * 1.15
                    draw.rounded_rectangle((x - q, y - q, x + q, y + q), radius=max(2, int(q / 3)), fill=fill)
        elif kind == "close":
            w = max(3, int(s * 0.12))
            draw.line((cx - s * 0.4, cy - s * 0.4, cx + s * 0.4, cy + s * 0.4), fill=fill, width=w)
            draw.line((cx - s * 0.4, cy + s * 0.4, cx + s * 0.4, cy - s * 0.4), fill=fill, width=w)

    def _draw_bar(self, draw, width, height, settings):
        bar = max(64, int(height * 0.18))
        top = height - bar
        draw.rectangle((0, top, width, height), fill=(10, 14, 22, 215))
        pad = max(6, bar // 9)
        theme = settings.get("theme")
        label = _(THEME_LABELS.get(theme, theme or ""))
        layout = [("prev", "theme_prev", None, 1), ("label", None, None, 2.6), ("next", "theme_next", None, 1),
                  ("sun_minus", "brightness", -BRIGHTNESS_STEP, 1), ("sun_plus", "brightness", BRIGHTNESS_STEP, 1),
                  ("menu", "menu", None, 1), ("close", "close", None, 1)]
        if not getattr(self.host, "brightness_supported", lambda: True)():
            # Only what the hardware really does: no backlight control on the FS-707DC firmware.
            layout = [entry for entry in layout if entry[1] != "brightness"]
        if width < height:          # portrait: fewer, larger buttons
            layout = [entry for entry in layout if entry[0] != "label"]
        units = sum(entry[3] for entry in layout)
        unit = (width - pad * (len(layout) + 1)) / units
        x = pad
        for icon, action, arg, span in layout:
            w = unit * span
            box = (int(x), top + pad, int(x + w), height - pad)
            if icon == "label":
                self._text(draw, box, label, int(bar * 0.3), bold=True)
            else:
                self._button(draw, box, action, arg, accent=action == "menu")
                self._icon(draw, icon, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, min(w, bar - 2 * pad) * 0.55)
            x += w + pad

    def _draw_menu(self, draw, width, height, settings):
        draw.rectangle((0, 0, width, height), fill=(8, 11, 18, 228))
        title_h = max(36, height // 9)
        self._text(draw, (0, 0, width, title_h), _("Themes"), int(title_h * 0.5), bold=True)
        current = settings.get("theme")
        items = [("theme", theme, _(THEME_LABELS.get(theme, theme))) for theme in settings_mod.THEME_IDS]
        items += [("test", None, _("Touch test")), ("calibrate", None, _("Calibrate")), ("close", None, _("Close"))]
        cols = 4 if width >= height else 2
        rows = math.ceil(len(items) / cols)
        pad = max(8, width // 80)
        cell_w = (width - pad * (cols + 1)) / cols
        cell_h = (height - title_h - pad * (rows + 1)) / rows
        for index, (action, arg, label) in enumerate(items):
            col, row = index % cols, index // cols
            box = (int(pad + col * (cell_w + pad)), int(title_h + pad + row * (cell_h + pad)),
                   int(pad + col * (cell_w + pad) + cell_w), int(title_h + pad + row * (cell_h + pad) + cell_h))
            self._button(draw, box, action, arg, accent=action == "theme" and arg == current)
            self._text(draw, box, label, int(min(cell_h * 0.22, cell_w * 0.12)), bold=arg == current)

    def _draw_test(self, draw, width, height):
        draw.rectangle((0, 0, width, height), fill=(6, 8, 12, 245))
        step = max(40, min(width, height) // 6)
        for x in range(0, width, step):
            draw.line((x, 0, x, height), fill=(255, 255, 255, 28))
        for y in range(0, height, step):
            draw.line((0, y, width, y), fill=(255, 255, 255, 28))
        self._text(draw, (0, 0, width, max(30, height // 10)), _("Touch test - hold to leave"), max(14, height // 26))
        previous = None
        for x, y, _t, start in self.trail:
            if previous and not start:
                draw.line((previous[0], previous[1], x, y), fill=(98, 160, 234, 255), width=4)
            previous = (x, y)
        if self.trail:
            x, y = self.trail[-1][:2]
            draw.line((x - 18, y, x + 18, y), fill=(255, 80, 80, 255), width=2)
            draw.line((x, y - 18, x, y + 18), fill=(255, 80, 80, 255), width=2)
            draw.text((width - 10, height - 10), f"x={x} y={y}", font=self._font(max(14, height // 24)),
                      fill=(255, 255, 255), anchor="rd")

    def _draw_toast(self, draw, width, height, text):
        font = self._font(max(16, height // 18), True)
        tw = draw.textlength(text, font=font)
        h = max(36, height // 10)
        box = (int((width - tw) / 2 - 24), int(height * 0.38), int((width + tw) / 2 + 24), int(height * 0.38 + h))
        draw.rounded_rectangle(box, radius=h // 2, fill=(10, 14, 22, 220))
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font=font, fill=(255, 255, 255), anchor="mm")


def state_path(state_dir, display_id):
    if not state_dir:
        return None
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in display_id)
    return os.path.join(state_dir, f"touch-{safe}.json")
