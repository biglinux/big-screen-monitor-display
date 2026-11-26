"""Touch interaction for panels with a touchscreen (FOSTON FS-707DC).

Touches never leave the service: they are recognised as gestures and drive
an interface drawn on the panel itself. Nothing is injected into the desktop
(no uinput, no XTest), so the main computer's keyboard focus, open menus and
mouse drags are never disturbed, on X11 and Wayland alike.

Single-point only: resistive panels report one contact, so there are no
multi-finger gestures. Gestures: tap, long press (0.7 s), swipe and drag.

Interface (Adwaita look, like the configuration window):

* control bar (tap): previous/next theme, brightness when the hardware has
  it, menu, close;
* menu (hold, swipe up or the grid button): Themes, Appearance of the current
  theme (colour schemes, Big Media Player skins, Kojiro looks, Brother Away
  stories), Orientation, Touch test, Calibrate, Exit to the device menu;
* galleries show real thumbnails of the themes, rendered in the background.

Choices made on the panel are kept as per-display overrides in the service
state directory. They are dropped as soon as the same setting is changed in
the configuration window, so the window always wins and the two never fight.
"""

import collections
import io
import json
import logging
import math
import os
import queue
import shutil
import subprocess
import threading
import time

from PIL import Image, ImageDraw, ImageFilter

from . import settings as settings_mod
from .i18n import _, N_

log = logging.getLogger("bsmd")

DOWN, MOVE, UP = 1, 2, 3          # same values as the FSP touch kinds
TAP_MAX_MOVE = 20                 # px
LONG_PRESS = 0.7                  # s
SWIPE_MIN = 100                   # px
SWIPE_MAX_TIME = 0.9              # s
OVERLAY_SECONDS = 6.0
MENU_SECONDS = 25.0
TEST_SECONDS = 60.0
RIPPLE_SECONDS = 0.45
ACTIVE_INTERVAL = 0.12            # s between frames while the overlay animates
QUIT_CONFIRM_SECONDS = 4.0        # second tap on "Exit" within this time closes the client
BRIGHTNESS_STEP = 10
THUMB_REFRESH = 600.0             # s before gallery thumbnails are rendered again
OVERRIDE_KEYS = ("theme", "brightness", "orientation", "std_scheme", "gk_theme_color", "planet_accent",
                 "oc_scheme", "bmp_skin", "kojiro",
                 # chosen in the Android app's own menu (per phone)
                 "performance_profile", "touch_media", "touch_enabled", "android_quality", "android_resolution",
                 "android_auto_rotate", "android_keep_screen_on", "android_burn_in")
# Big Media Player controls a touch panel may send to the media agent (MPRIS).
MEDIA_ACTIONS = ("play_pause", "next", "previous", "volume_up", "volume_down", "mute")
PAGES = ("bar", "menu", "themes", "style", "orientation", "test")

# Adwaita (dark) colours, as in the configuration window.
HEADER = (36, 36, 40, 250)
CARD = (54, 54, 60, 255)
CARD_PRESSED = (82, 82, 92, 255)
ACCENT = (53, 132, 228)
DANGER = (224, 27, 36)
SUCCESS = (46, 194, 126)
WARNING = (246, 211, 45)
TEXT = (255, 255, 255)
DIM = (178, 178, 188)
WELL = (68, 68, 76, 255)          # thumbnail placeholder inside a card


def mix(a, b, t):
    """Opaque blend of two colours (drawing on an RGBA layer replaces pixels, it does not blend)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)) + (255,)


def frosted(image):
    """The frame behind a menu page: blurred and darkened, like a GNOME dialog backdrop."""
    small = image.convert("RGB").resize((max(1, image.width // 4), max(1, image.height // 4)),
                                        Image.Resampling.BILINEAR)
    small = small.filter(ImageFilter.GaussianBlur(3))
    dark = Image.new("RGB", small.size, (18, 18, 22))
    return Image.blend(small, dark, 0.72).resize(image.size, Image.Resampling.BILINEAR)

THEME_LABELS = {"standard": N_("Standard"), "gkrellm": N_("GKrellM"), "planet": N_("Planet"),
                "old_computer": N_("Old Computer"), "brother_away": N_("Brother Away"), "kojiro": N_("Kojiro"),
                "big_media_player": N_("Big Media Player")}
ORIENTATIONS = (("horizontal", N_("Horizontal"), "orientation-landscape"),
                ("vertical", N_("Vertical"), "orientation-portrait-left"),
                ("horizontal_flipped", N_("Horizontal (upside down)"), "orientation-landscape-inverse"),
                ("vertical_flipped", N_("Vertical (upside down)"), "orientation-portrait-right"))
MEDIA_LABELS = {"play_pause": N_("Play / pause"), "next": N_("Next track"), "previous": N_("Previous track"),
                "volume_up": N_("Volume up"), "volume_down": N_("Volume down"), "mute": N_("Mute")}
STORIES = (("coconut_tree", N_("The coconut tree")), ("philosopher", N_("The philosopher")),
           ("shark", N_("The shark")), ("raft", N_("The raft")), ("ufo", N_("The UFO")),
           ("crab_glasses", N_("The crab with glasses")), ("gull_lunch", N_("The seagull's lunch")),
           ("message_bottle", N_("Message in a bottle")), ("ship_asleep", N_("The ship that passed by")),
           ("mermaid", N_("The mermaid")), ("treasure", N_("The treasure")), ("stars_night", N_("Starry night")),
           ("rain_complaint", N_("Rain again")), ("fish_bait", N_("Gone fishing")))

APP_ICON = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "icons", "hicolor", "scalable",
                                        "apps", "big-screen-monitor-display.svg"))
SYMBOLIC_DIRS = ("/usr/share/icons/Adwaita/symbolic",)


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


def style_options(theme):
    """(setting, title, [(value, label)]) the panel offers for ``theme``, or None."""
    if theme == "standard":
        from .dashboard import SCHEMES
        return "std_scheme", N_("Colour scheme"), [(key, scheme["name"]) for key, scheme in SCHEMES.items()]
    if theme == "gkrellm":
        return "gk_theme_color", N_("Visual style"), [("urlicht", "Urlicht (Neon Blue)"),
                                                     ("classic", N_("Classic (green phosphor)")),
                                                     ("cyber_red", "Cyber-Red")]
    if theme == "planet":
        return "planet_accent", N_("Accent colour"), [("blue", N_("Blue")), ("green", N_("Green")),
                                                     ("amber", N_("Amber")), ("violet", N_("Violet")),
                                                     ("red", N_("Red"))]
    if theme == "old_computer":
        return "oc_scheme", N_("Colour scheme"), [("classic", N_("Classic grey")), ("slate", N_("Slate (dark)")),
                                                 ("amber", N_("Amber")), ("plum", N_("Plum"))]
    if theme == "big_media_player":
        from .bigmedia import skins
        return "bmp_skin", N_("Skin"), [(skin, skins.SKINS[skin].name) for skin in settings_mod.BMP_SKINS
                                        if skin in skins.SKINS]
    if theme == "kojiro":
        from .kojiro import presets
        return "kojiro", N_("Appearance"), [(name, presets.PRESETS[name][0]) for name in presets.PRESETS]
    if theme == "brother_away":
        return "story", N_("Stories"), list(STORIES)
    return None


# ---------------------------------------------------------------- icons

_ICON_CACHE = {}
_ICON_INDEX = None
_ICON_LOCK = threading.Lock()


def _svg_to_image(path, size):
    if not shutil.which("rsvg-convert"):
        return None
    try:
        result = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), path],
                                capture_output=True, timeout=3, check=False)
        if result.returncode == 0:
            return Image.open(io.BytesIO(result.stdout)).convert("RGBA")
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return None


def symbolic_icon(name, size, color=TEXT):
    """An Adwaita symbolic icon tinted with ``color``; None when unavailable."""
    global _ICON_INDEX
    key = (name, int(size), tuple(color[:3]))
    with _ICON_LOCK:
        if key in _ICON_CACHE:
            return _ICON_CACHE[key]
        if _ICON_INDEX is None:
            _ICON_INDEX = {}
            for base in SYMBOLIC_DIRS:
                for root, _dirs, files in os.walk(base):
                    for file in files:
                        if file.endswith("-symbolic.svg"):
                            _ICON_INDEX.setdefault(file[:-len("-symbolic.svg")], os.path.join(root, file))
        path = _ICON_INDEX.get(name)
    image = _svg_to_image(path, int(size)) if path else None
    if image is not None:
        tinted = Image.new("RGBA", image.size, (*color[:3], 255))
        tinted.putalpha(image.getchannel("A"))
        image = tinted
    with _ICON_LOCK:
        _ICON_CACHE[key] = image
    return image


def app_icon(size):
    key = ("@app", int(size))
    with _ICON_LOCK:
        if key in _ICON_CACHE:
            return _ICON_CACHE[key]
    image = _svg_to_image(APP_ICON, int(size)) if os.path.exists(APP_ICON) else None
    with _ICON_LOCK:
        _ICON_CACHE[key] = image
    return image


# ---------------------------------------------------------------- thumbnails

class Thumbnailer:
    """Renders gallery thumbnails one at a time in a background thread."""

    MAX = 64

    def __init__(self, on_ready):
        self.on_ready = on_ready
        self.done = collections.OrderedDict()
        self.pending = set()
        self.jobs = queue.Queue()
        self.lock = threading.Lock()
        self.thread = None

    def get(self, key, work):
        with self.lock:
            if key in self.done:
                self.done.move_to_end(key)
                return self.done[key]
            if key not in self.pending:
                self.pending.add(key)
                self.jobs.put((key, work))
                if self.thread is None or not self.thread.is_alive():
                    self.thread = threading.Thread(target=self._run, name="touch-thumbnails", daemon=True)
                    self.thread.start()
        return None

    def _run(self):
        while True:
            try:
                key, work = self.jobs.get(timeout=30)
            except queue.Empty:
                return
            try:
                image = work()
            except Exception:  # noqa: BLE001 - a theme failing in a preview must not matter
                log.debug("thumbnail %s failed", key, exc_info=True)
                image = None
            with self.lock:
                self.pending.discard(key)
                self.done[key] = image
                while len(self.done) > self.MAX:
                    self.done.popitem(last=False)
            self.on_ready()


def render_thumbnail(theme_id, settings, size, box_size, prepare=None):
    """``theme_id`` rendered with ``settings`` at ``size``, fitted in ``box_size``.
    ``prepare(theme)`` may set the theme up first (e.g. start a Brother Away story)."""
    from . import themes
    from .runtime import RenderContext
    ctx = RenderContext(preview=True)
    theme = themes.create(theme_id, ctx)
    try:
        if prepare is not None:
            prepare(theme)
        image = themes.render_for_panel(theme, size[0], size[1], dict(settings, theme=theme_id), ctx)
    finally:
        theme.close()
    image = image.convert("RGB")
    image.thumbnail(box_size, Image.Resampling.LANCZOS)
    return image


# ---------------------------------------------------------------- gestures

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


# ---------------------------------------------------------------- overrides

class TouchOverrides:
    """Settings chosen on the panel, persisted per display."""

    def __init__(self, path):
        self.path = path
        self.values = {}              # key -> {"value": v, "base": value in settings when chosen, "meta": ...}
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

    def set(self, key, value, base, meta=None):
        self.values[key] = {"value": value, "base": base, **({"meta": meta} if meta is not None else {})}
        self._save()

    def meta(self, key):
        return (self.values.get(key) or {}).get("meta")

    @staticmethod
    def _valid(key, value):
        if key == "theme":
            return value in settings_mod.THEME_IDS
        if key == "brightness":
            return isinstance(value, int) and 0 <= value <= 100
        if key == "kojiro":
            return isinstance(value, dict)
        if key in settings_mod.SCHEMA:
            return settings_mod._coerce(key, value)[1]
        if key in settings_mod.DISPLAY_SCHEMA and settings_mod.DISPLAY_SCHEMA[key][0] != "text":
            return settings_mod._coerce_spec(key, value, settings_mod.DISPLAY_SCHEMA[key])[1]
        return False

    def valid(self, key, value):
        return key in OVERRIDE_KEYS and self._valid(key, value)

    def apply(self, settings):
        """Settings with the panel's choices; stale ones (changed in the window) are dropped."""
        result = dict(settings)
        stale = [key for key, entry in self.values.items() if settings.get(key) != entry.get("base")]
        for key in stale:
            del self.values[key]
        if stale:
            self._save()
        for key, entry in self.values.items():
            if self._valid(key, entry["value"]):
                result[key] = entry["value"]
        return result


# ---------------------------------------------------------------- interface

class TouchUI:
    """Gestures -> actions, and the overlay drawn on top of each frame.

    ``host`` provides: ``base_settings()`` (settings without the panel's
    choices), ``request(command, *args)`` (session commands), ``wake()``,
    ``name()``, ``state()`` (link state) and optionally ``can_quit()``,
    ``brightness_supported()`` and ``panel_size()``."""

    def __init__(self, host, state_path=None, clock=time.monotonic, thumbnails=True):
        self.host = host
        self.clock = clock
        self.overrides = TouchOverrides(state_path)
        self.recognizer = GestureRecognizer()
        self.lock = threading.RLock()         # decorate() asks the host for its name, which reads settings
        self.page = None
        self.until = 0.0
        self.ripples = []             # (x, y, t)
        self.trail = []               # touch test points
        self.buttons = []             # (box, action, arg) of the last drawn overlay
        self.pressed = None           # button box under the finger
        self.toast = None             # (text, until)
        self.quit_armed_until = 0.0   # "Exit to the device menu" waits for a confirming tap
        self.last_event = None
        self.events = 0
        self.thumbs = Thumbnailer(host.wake) if thumbnails else None

    # ------------------------------------------------------------ input
    def handle(self, kind, x, y):
        now = self.clock()
        with self.lock:
            self.events += 1
            self.last_event = now
            for gesture in self.recognizer.feed(kind, x, y, now):
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
        for box, action, arg in reversed(self.buttons):
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
                self._open("menu", now)
            return
        if name == "tap":
            hit = self._button_at(x, y) if self.page else None
            if hit:
                self._action(hit[1], hit[2], now)
            elif self.page in (None, "bar"):
                self._open("bar", now)
            else:
                self.until = now + MENU_SECONDS
        elif name == "long_press":
            self._open("menu", now)
        elif name in ("swipe_left", "swipe_right") and self.page in (None, "bar"):
            self._cycle_theme(1 if name == "swipe_left" else -1, now)
        elif name == "swipe_up" and self.page in (None, "bar"):
            self._open("menu", now)
        elif name == "swipe_down":
            self._open(None, now)

    def _open(self, page, now):
        self.page = page
        self.until = now + {"bar": OVERLAY_SECONDS, "test": TEST_SECONDS}.get(page, MENU_SECONDS if page else 0)
        if page == "test":
            self.trail = []

    def _settings(self):
        return self.overrides.apply(self.host.base_settings())

    def _set(self, key, value, meta=None):
        self.overrides.set(key, value, self.host.base_settings().get(key), meta)

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
        elif action == "page":
            self._open(arg, now)
        elif action == "back":
            self._open("menu" if self.page not in ("menu", "bar") else None, now)
        elif action == "theme":
            self._set("theme", arg)
            self.toast = (_(THEME_LABELS.get(arg, arg)), now + 1.6)
            self._open(None, now)
            self.host.request("invalidate")
        elif action == "style":
            self._apply_style(arg, now)
        elif action == "media":
            if arg in MEDIA_ACTIONS and getattr(self.host, "media_command", None) is not None:
                ok = self.host.media_command(arg)
                self.toast = (_(MEDIA_LABELS.get(arg, arg)) if ok else _("No media player"), now + 1.2)
                if self.page == "bar":
                    self.until = now + OVERLAY_SECONDS
        elif action == "orientation":
            if arg == "auto":
                self._set("android_auto_rotate", True)
                self.toast = (_("Automatic"), now + 1.6)
                self._open(None, now)
                self.host.request("invalidate")
                return
            self._set("orientation", arg)
            if self._device_oriented():
                self._set("android_auto_rotate", False)
            label = next((label for value, label, _icon in ORIENTATIONS if value == arg), arg)
            self.toast = (_(label), now + 1.6)
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
        elif action == "close":
            self._open(None, now)
        elif action == "test":
            self._open("test", now)
        elif action == "calibrate":
            self._open(None, now)
            self.host.request("calibrate")
        elif action == "quit":
            if now < self.quit_armed_until:
                self.quit_armed_until = 0.0
                self._open(None, now)
                self.toast = (_("Closing…"), now + 3.0)
                self.host.request("quit_client")
            else:
                # Leaving ends the panel until the client is started again: ask for a second tap.
                self.quit_armed_until = now + QUIT_CONFIRM_SECONDS
                self.until = max(self.until, now + QUIT_CONFIRM_SECONDS + 1)
                self.toast = (_("Tap again to exit"), now + QUIT_CONFIRM_SECONDS)

    def _apply_style(self, value, now):
        settings = self._settings()
        options = style_options(settings.get("theme"))
        if not options:
            return
        key, _title, choices = options
        label = _(next((label for choice, label in choices if choice == value), value))
        if key == "story":
            self.host.request("ba_story", value)
        elif key == "kojiro":
            from .kojiro import presets
            self._set("kojiro", presets.build(value), meta=value)
        else:
            self._set(key, value)
        self.toast = (label, now + 1.6)
        self._open(None, now)
        self.host.request("invalidate")

    def start_test(self):
        with self.lock:
            self._open("test", self.clock())
        self.host.wake()

    def set_override(self, key, value):
        """A choice made outside the overlay (the Android app's own menu)."""
        with self.lock:
            self._set(key, value)
            if key == "orientation" and self._device_oriented():
                self._set("android_auto_rotate", False)
        self.host.wake()

    def command(self, name):
        """Open the menu or change theme from a button outside the frame (Android app)."""
        now = self.clock()
        with self.lock:
            if name == "menu":
                self._open("menu", now)
            elif name == "theme_next":
                self._cycle_theme(1, now)
            elif name == "theme_prev":
                self._cycle_theme(-1, now)
            elif name == "close_overlay":
                self._open(None, now)
        self.host.wake()

    def _device_oriented(self):
        return bool(getattr(self.host, "device_oriented", lambda: False)())

    def _media_player(self):
        """(snapshot, active player) when the Big Media Player controls apply, else (None, None)."""
        media = getattr(self.host, "media", None)
        snapshot = media() if media is not None else None
        if not snapshot or not snapshot.get("players"):
            return None, None
        players = snapshot["players"]
        player = next((p for p in players if p.get("bus") == snapshot.get("active")), None) or players[0]
        return snapshot, player

    def apply(self, settings):
        with self.lock:
            return self.overrides.apply(settings)

    def active(self):
        """True while something on the overlay animates (render faster)."""
        with self.lock:
            return bool(self.page or self.ripples or self.toast or self.recognizer.start)

    def _current_style(self, settings):
        options = style_options(settings.get("theme"))
        if not options:
            return None, None
        key, _title, choices = options
        if key == "story":
            return None, None
        current = self.overrides.meta("kojiro") if key == "kojiro" and "kojiro" in self.overrides.values \
            else settings.get(key)
        label = next((label for choice, label in choices if choice == current), None)
        return current, (_(label) if label else None)

    # ------------------------------------------------------------ drawing
    def decorate(self, image, settings):
        self.tick()
        with self.lock:
            if not (self.page or self.ripples or self.toast):
                self.buttons = []
                return image
            image = image.convert("RGB") if image.mode != "RGB" else image.copy()
            layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
            draw = ImageDraw.Draw(layer)
            width, height = image.size
            self.buttons = []
            page = self.page
            if page == "test":
                self._draw_test(layer, draw, width, height)
            elif page == "bar":
                self._draw_status(layer, draw, width, height)
                self._draw_bar(layer, draw, width, height, settings)
            elif page in ("menu", "themes", "style", "orientation"):
                image = frosted(image)
                area = self._draw_header(layer, draw, width, height, page, settings)
                getattr(self, f"_page_{page}")(layer, draw, area, settings)
            if self.toast:
                self._draw_toast(draw, width, height, self.toast[0])
            now = self.clock()
            for x, y, t in self.ripples:
                age = (now - t) / RIPPLE_SECONDS
                radius = 10 + age * min(width, height) * 0.09
                draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                             outline=(255, 255, 255, int(200 * (1 - age))), width=max(2, int(4 * (1 - age)) + 1))
            return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")

    # helpers -------------------------------------------------------------
    @staticmethod
    def _font(size, bold=False):
        from .bigmedia.paint import font
        return font(max(8, int(size)), bold)

    def _text(self, draw, xy, text, size, fill=TEXT, bold=False, anchor="mm", max_width=None):
        font = self._font(size, bold)
        if max_width:
            while size > 9 and draw.textlength(text, font=font) > max_width:
                size -= 1
                font = self._font(size, bold)
            if draw.textlength(text, font=font) > max_width:
                while text and draw.textlength(text + "…", font=font) > max_width:
                    text = text[:-1]
                text += "…"
        draw.text(xy, text, font=font, fill=fill, anchor=anchor)

    def _paste_icon(self, layer, name, center, size, color=TEXT):
        icon = symbolic_icon(name, size, color)
        if icon is None:
            return False
        layer.alpha_composite(icon, (int(center[0] - icon.width / 2), int(center[1] - icon.height / 2)))
        return True

    def _card(self, draw, box, action, arg=None, selected=False, color=CARD, radius=None):
        radius = radius or max(8, min(box[2] - box[0], box[3] - box[1]) // 7)
        fill = CARD_PRESSED if self.pressed == box else color
        draw.rounded_rectangle(box, radius=radius, fill=fill)
        if selected:
            draw.rounded_rectangle(box, radius=radius, outline=(*ACCENT, 255), width=3)
        self.buttons.append((box, action, arg))
        return radius

    def _check_badge(self, layer, draw, box):
        r = max(9, min(16, (box[3] - box[1]) // 9, (box[2] - box[0]) // 9))
        cx, cy = box[2] - r - 6, box[1] + r + 6
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*ACCENT, 255))
        if not self._paste_icon(layer, "object-select", (cx, cy), int(r * 1.3)):
            draw.line((cx - r * .45, cy, cx - r * .1, cy + r * .4, cx + r * .5, cy - r * .35), fill=TEXT,
                      width=max(2, r // 4))

    @staticmethod
    def _grid(area, count, cols, gap):
        rows = max(1, math.ceil(count / cols))
        x0, y0, x1, y1 = area
        cw = (x1 - x0 - gap * (cols - 1)) / cols
        ch = (y1 - y0 - gap * (rows - 1)) / rows
        return [(int(x0 + (i % cols) * (cw + gap)), int(y0 + (i // cols) * (ch + gap)),
                 int(x0 + (i % cols) * (cw + gap) + cw), int(y0 + (i // cols) * (ch + gap) + ch))
                for i in range(count)]

    def _cols(self, width, height, landscape, portrait):
        return landscape if width >= height else portrait

    # header and status -----------------------------------------------------
    def _draw_header(self, layer, draw, width, height, page, settings):
        hh = max(44, height // 9)
        draw.rectangle((0, 0, width, hh), fill=HEADER)
        draw.line((0, hh, width, hh), fill=(255, 255, 255, 28))
        pad = max(8, hh // 5)
        if page == "menu":
            icon = app_icon(hh - 2 * pad)
            if icon is not None:
                layer.alpha_composite(icon, (pad, pad))
            title_x = pad * 2 + hh - 2 * pad
            title = "Big Screen Monitor"
        else:
            box = (pad // 2, pad // 2, pad // 2 + hh - pad, hh - pad // 2)
            self._card(draw, box, "back", color=mix(HEADER, TEXT, 0.08), radius=(hh - pad) // 3)
            if not self._paste_icon(layer, "go-previous", ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
                                    int(hh * 0.45)):
                self._text(draw, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), "<", hh * 0.5, bold=True)
            title_x = box[2] + pad
            theme = settings.get("theme")
            title = {"themes": _("Themes"), "orientation": _("Orientation"),
                     "style": "%s · %s" % (_(THEME_LABELS.get(theme, theme or "")),
                                           _((style_options(theme) or ("", N_("Appearance")))[1]))}[page]
        clock = time.strftime("%H:%M")
        right = width - pad
        cw = draw.textlength(clock, font=self._font(hh * 0.42, True))
        self._text(draw, (right, hh / 2), clock, hh * 0.42, bold=True, anchor="rm")
        state = self.host.state()
        dot = SUCCESS if state == "healthy" else WARNING
        dx = right - cw - pad
        draw.ellipse((dx - 5, hh / 2 - 5, dx + 5, hh / 2 + 5), fill=(*dot, 255))
        name = self.host.name()
        nx = dx - 10
        name_room = max(0, nx - title_x - width * 0.35)
        if name_room > 40:
            self._text(draw, (nx, hh / 2), name, hh * 0.32, fill=DIM, anchor="rm", max_width=name_room)
        self._text(draw, (title_x, hh / 2), title, hh * 0.42, bold=True, anchor="lm",
                   max_width=max(60, width * 0.55 - title_x))
        return (pad, hh + pad, width - pad, height - pad)

    def _draw_status(self, layer, draw, width, height):
        bar = max(30, height // 12)
        draw.rectangle((0, 0, width, bar), fill=(20, 20, 24, 250))   # opaque: the theme's own clock must not ghost
        now = time.localtime()
        size = bar * 0.55
        self._text(draw, (12, bar / 2), time.strftime("%H:%M", now), size, bold=True, anchor="lm")
        self._text(draw, (12 + size * 3.3, bar / 2), time.strftime("%d/%m/%Y", now), size * 0.8, fill=DIM,
                   anchor="lm")
        dot = SUCCESS if self.host.state() == "healthy" else WARNING
        name = self.host.name()
        font = self._font(size * 0.8)
        right = width - 12
        self._text(draw, (right, bar / 2), name, size * 0.8, fill=(220, 226, 235), anchor="rm")
        cx = right - draw.textlength(name, font=font) - 14
        draw.ellipse((cx - 6, bar / 2 - 6, cx + 6, bar / 2 + 6), fill=(*dot, 255))

    # bar -------------------------------------------------------------------
    def _draw_bar(self, layer, draw, width, height, settings):
        bar = max(64, int(height * 0.18))
        top = height - bar
        draw.rectangle((0, top, width, height), fill=(20, 20, 24, 248))
        draw.line((0, top, width, top), fill=(255, 255, 255, 30))
        pad = max(6, bar // 9)
        theme = settings.get("theme")
        layout = [("go-previous", "theme_prev", None, 1), ("label", None, None, 2.6),
                  ("go-next", "theme_next", None, 1),
                  ("bright-", "brightness", -BRIGHTNESS_STEP, 1), ("bright+", "brightness", BRIGHTNESS_STEP, 1),
                  ("view-app-grid", "page", "menu", 1), ("window-close", "close", None, 1)]
        if not getattr(self.host, "brightness_supported", lambda: True)():
            # Only what the hardware really does: no backlight control on the FS-707DC firmware.
            layout = [entry for entry in layout if entry[1] != "brightness"]
        media = self._media_layout(settings)
        if media:
            layout = media
        if width < height:          # portrait: fewer, larger buttons
            layout = [entry for entry in layout if entry[0] not in ("label", "track")]
        units = sum(entry[3] for entry in layout)
        unit = (width - pad * (len(layout) + 1)) / units
        x = pad
        for icon, action, arg, span in layout:
            w = unit * span
            box = (int(x), top + pad, int(x + w), height - pad)
            center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            if icon == "label":
                self._text(draw, center, _(THEME_LABELS.get(theme, theme or "")), bar * 0.28, bold=True,
                           max_width=w - 8)
            elif icon == "track":
                self._text(draw, (center[0], center[1] - bar * 0.12), arg[0], bar * 0.22, bold=True,
                           max_width=w - 8)
                self._text(draw, (center[0], center[1] + bar * 0.17), arg[1], bar * 0.17, fill=DIM,
                           max_width=w - 8)
            else:
                self._card(draw, box, action, arg, color=(*ACCENT, 240) if arg == "menu" else CARD)
                size = int(min(w, bar - 2 * pad) * 0.5)
                if icon.startswith("bright"):
                    self._paste_icon(layer, "display-brightness", (center[0] - size * 0.25, center[1]), size)
                    self._text(draw, (center[0] + size * 0.55, center[1]), "+" if icon.endswith("+") else "−",
                               size * 0.8, bold=True)
                elif not self._paste_icon(layer, icon, center, size):
                    self._text(draw, center, {"go-previous": "◀", "go-next": "▶", "view-app-grid": "▦",
                                              "window-close": "✕", "media-skip-backward": "⏮",
                                              "media-skip-forward": "⏭", "media-playback-start": "▶",
                                              "media-playback-pause": "⏸", "audio-volume-low": "−",
                                              "audio-volume-high": "+", "audio-volume-muted": "🔇"}.get(icon, "?"),
                               size, bold=True)
            x += w + pad

    def _media_layout(self, settings):
        """Bar buttons for the Big Media Player: only what the player and the
        volume control really offer (no button that would do nothing)."""
        if settings.get("theme") != "big_media_player" or not settings.get("touch_media", True):
            return None
        snapshot, player = self._media_player()
        if player is None:
            return None
        can = player.get("can") or {}
        playing = player.get("status") == "Playing"
        layout = []
        if can.get("previous"):
            layout.append(("media-skip-backward", "media", "previous", 1))
        if can.get("pause" if playing else "play") or can.get("control"):
            layout.append(("media-playback-pause" if playing else "media-playback-start", "media", "play_pause",
                           1.2))
        if can.get("next"):
            layout.append(("media-skip-forward", "media", "next", 1))
        title = player.get("title") or player.get("identity") or ""
        layout.append(("track", None, (title, player.get("artist") or player.get("identity") or ""), 2.4))
        if (snapshot.get("volume") or {}).get("available"):
            layout += [("audio-volume-low", "media", "volume_down", 1), ("audio-volume-high", "media", "volume_up", 1),
                       ("audio-volume-muted", "media", "mute", 1)]
        layout += [("view-app-grid", "page", "menu", 1), ("window-close", "close", None, 1)]
        return layout

    # pages -----------------------------------------------------------------
    def _page_menu(self, layer, draw, area, settings):
        width, height = area[2] + area[0], area[3]
        theme = settings.get("theme")
        style_value, style_label = self._current_style(settings)
        options = style_options(theme)
        orientation = settings.get("orientation", "horizontal")
        o_label = next((label for value, label, _icon in ORIENTATIONS if value == orientation), orientation)
        if self._device_oriented() and settings.get("android_auto_rotate"):
            o_label = N_("Automatic")
        armed = self.clock() < self.quit_armed_until
        tiles = [("view-grid", _("Themes"), _(THEME_LABELS.get(theme, theme or "")), "page", "themes", ACCENT),
                 ("media-playback-start" if theme == "brother_away" else "color-select",
                  _((options or ("", N_("Appearance")))[1]) if options else _("Appearance"),
                  style_label or (_("Choose a story") if theme == "brother_away" else "—"),
                  "page", "style", (192, 97, 203)),
                 ("rotation-allowed", _("Orientation"), _(o_label), "page", "orientation", (38, 162, 105)),
                 ("input-touchpad", _("Touch test"), _("Draw with your finger"), "test", None, (229, 165, 10))]
        if getattr(self.host, "can_calibrate", lambda: True)():
            tiles.append(("find-location", _("Calibrate"), _("Device calibration"), "calibrate", None,
                          (98, 160, 234)))
        if getattr(self.host, "can_quit", lambda: False)():
            tiles.append(("system-shutdown", _("Tap again to exit") if armed else _("Exit to the device menu"),
                          _("Back to the GPS main menu"), "quit", None, DANGER))
        cols = self._cols(width, height, 3, 2)
        gap = max(8, (area[2] - area[0]) // 70)
        boxes = self._grid(area, len(tiles), cols, gap)
        for box, (icon, title, subtitle, action, arg, color) in zip(boxes, tiles, strict=False):
            danger = action == "quit"
            card_color = (*DANGER, 255) if danger and armed else (mix(CARD, DANGER, 0.35) if danger else CARD)
            self._card(draw, box, action, arg, color=card_color)
            bw, bh = box[2] - box[0], box[3] - box[1]
            r = int(min(bw * 0.17, bh * 0.22))
            cx, cy = box[0] + bw / 2, box[1] + bh * 0.36
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*color, 255) if danger else mix(CARD, color, 0.28))
            if not self._paste_icon(layer, icon, (cx, cy), int(r * 1.1), TEXT if danger else color):
                draw.ellipse((cx - r / 3, cy - r / 3, cx + r / 3, cy + r / 3), fill=(*color, 255))
            self._text(draw, (cx, box[1] + bh * 0.70), title, bh * 0.13, bold=True, max_width=bw - 12)
            self._text(draw, (cx, box[1] + bh * 0.86), subtitle, bh * 0.095, fill=DIM, max_width=bw - 12)

    def _thumb_tile(self, layer, draw, box, action, arg, label, selected, key, work, fallback_icon=None):
        radius = self._card(draw, box, action, arg, selected=selected)
        bw, bh = box[2] - box[0], box[3] - box[1]
        label_h = max(22, int(bh * 0.24))
        inner = (box[0] + 6, box[1] + 6, box[2] - 6, box[3] - label_h)
        thumb = self.thumbs.get(key, work) if (self.thumbs is not None and work is not None) else None
        if thumb is not None:
            tx = inner[0] + ((inner[2] - inner[0]) - thumb.width) // 2
            ty = inner[1] + ((inner[3] - inner[1]) - thumb.height) // 2
            mask = Image.new("L", thumb.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, thumb.width - 1, thumb.height - 1),
                                                   radius=max(4, radius - 4), fill=255)
            layer.paste(thumb.convert("RGBA"), (tx, ty), mask)
        else:
            draw.rounded_rectangle(inner, radius=max(4, radius - 4), fill=WELL)
            self._paste_icon(layer, fallback_icon or "image-loading", ((inner[0] + inner[2]) / 2,
                                                                        (inner[1] + inner[3]) / 2),
                             int(min(inner[2] - inner[0], inner[3] - inner[1]) * 0.4), DIM)
        self._text(draw, ((box[0] + box[2]) / 2, box[3] - label_h / 2 - 2), label, label_h * 0.5,
                   bold=selected, max_width=bw - 10)
        if selected:
            self._check_badge(layer, draw, box)

    def _thumb_size(self, box):
        return (max(16, box[2] - box[0] - 12), max(16, int((box[3] - box[1]) * 0.76) - 12))

    def _render_size(self):
        size = getattr(self.host, "panel_size", lambda: None)() or (800, 480)
        return (max(160, size[0] // 2), max(96, size[1] // 2))

    def _page_themes(self, layer, draw, area, settings):
        width, height = area[2] + area[0], area[3]
        ids = list(settings_mod.THEME_IDS)
        cols = self._cols(width, height, 4, 2)
        gap = max(8, (area[2] - area[0]) // 70)
        bucket = int(time.time() // THUMB_REFRESH)
        size = self._render_size()
        base = dict(settings)
        for box, theme in zip(self._grid(area, len(ids), cols, gap), ids, strict=False):
            tsize = self._thumb_size(box)
            def work(t=theme, s=tsize):
                return render_thumbnail(t, base, size, s)
            self._thumb_tile(layer, draw, box, "theme", theme, _(THEME_LABELS[theme]), theme == settings.get("theme"),
                             ("theme", theme, size, tsize, bucket), work, "view-grid")

    def _page_style(self, layer, draw, area, settings):
        width, height = area[2] + area[0], area[3]
        theme = settings.get("theme")
        options = style_options(theme)
        if not options:
            self._text(draw, ((area[0] + area[2]) / 2, (area[1] + area[3]) / 2),
                       _("This theme has no options here."), (area[3] - area[1]) * 0.07, fill=DIM)
            return
        key, _title, choices = options
        current, _label = self._current_style(settings)
        n = len(choices)
        cols = self._cols(width, height, 5 if n > 8 else 4, 3 if n > 8 else 2)
        gap = max(6, (area[2] - area[0]) // 90)
        bucket = int(time.time() // THUMB_REFRESH)
        size = self._render_size()
        base = dict(settings)
        for box, (value, label) in zip(self._grid(area, n, cols, gap), choices, strict=False):
            tsize = self._thumb_size(box)
            if key == "story":
                def work(v=value, s=tsize):
                    # the scene a few seconds into the story (same helper as the project screenshots)
                    def seek(theme_obj):
                        if hasattr(theme_obj, "debug_seek"):
                            theme_obj.debug_seek(6, story=v, hour=21 if v in ("ufo", "stars_night") else 11)
                    return render_thumbnail(theme, base, size, s, prepare=seek)
            elif key == "kojiro":
                def work(v=value, s=tsize):
                    from .kojiro import presets
                    return render_thumbnail(theme, dict(base, kojiro=presets.build(v)), size, s)
            else:
                def work(v=value, s=tsize, k=key):
                    return render_thumbnail(theme, dict(base, **{k: v}), size, s)
            self._thumb_tile(layer, draw, box, "style", value, _(label), value == current,
                             ("style", theme, key, value, size, tsize, bucket), work,
                             "media-playback-start" if key == "story" else "color-select")

    def _page_orientation(self, layer, draw, area, settings):
        width, height = area[2] + area[0], area[3]
        current = settings.get("orientation", "horizontal")
        choices = ORIENTATIONS
        if self._device_oriented():
            # A phone or tablet can also follow its own sensor.
            choices = (("auto", N_("Automatic"), "rotation-allowed"),) + ORIENTATIONS
            if settings.get("android_auto_rotate"):
                current = "auto"
        cols = self._cols(width, height, len(choices) if len(choices) <= 4 else 3, 2)
        gap = max(8, (area[2] - area[0]) // 60)
        for box, (value, label, icon) in zip(self._grid(area, len(choices), cols, gap), choices, strict=False):
            selected = value == current
            self._card(draw, box, "orientation", value, selected=selected)
            bw, bh = box[2] - box[0], box[3] - box[1]
            if value == "auto":
                size = int(min(bw * 0.5, bh * 0.4))
                if not self._paste_icon(layer, icon, (box[0] + bw / 2, box[1] + bh * 0.42), size,
                                        ACCENT if selected else TEXT):
                    self._text(draw, (box[0] + bw / 2, box[1] + bh * 0.42), "⟳", size, bold=True)
            else:
                self._screen_glyph(draw, (box[0] + bw / 2, box[1] + bh * 0.42), min(bw * 0.62, bh * 0.5), value,
                                   ACCENT if selected else TEXT)
            self._text(draw, (box[0] + bw / 2, box[1] + bh * 0.84), _(label), min(bh * 0.065, 22),
                       bold=selected, max_width=bw - 12)
            if selected:
                self._check_badge(layer, draw, box)

    @staticmethod
    def _screen_glyph(draw, center, size, orientation, color):
        """A little screen as the viewer will see it; its title bar marks the top of the content."""
        cx, cy = center
        portrait = orientation.startswith("vertical")
        w, h = (size * 0.62, size) if portrait else (size, size * 0.62)
        box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        line = max(3, int(size / 22))
        draw.rounded_rectangle(box, radius=max(4, int(size / 12)), outline=(*color[:3], 255), width=line)
        strip = max(5, int(size / 9))
        inset = line + 3
        if orientation.endswith("_flipped"):      # upside down: the title bar ends at the bottom
            bar = (box[0] + inset, box[3] - inset - strip, box[2] - inset, box[3] - inset)
        else:
            bar = (box[0] + inset, box[1] + inset, box[2] - inset, box[1] + inset + strip)
        draw.rectangle(bar, fill=(*color[:3], 255))

    def _draw_test(self, layer, draw, width, height):
        draw.rectangle((0, 0, width, height), fill=(10, 10, 14, 250))
        step = max(40, min(width, height) // 6)
        for x in range(0, width, step):
            draw.line((x, 0, x, height), fill=(255, 255, 255, 26))
        for y in range(0, height, step):
            draw.line((0, y, width, y), fill=(255, 255, 255, 26))
        bar = max(30, height // 10)
        draw.rectangle((0, 0, width, bar), fill=HEADER)
        self._paste_icon(layer, "input-touchpad", (bar * 0.6, bar / 2), int(bar * 0.55), (229, 165, 10))
        self._text(draw, (bar * 1.2, bar / 2), _("Touch test - hold to leave"), bar * 0.42, bold=True, anchor="lm")
        previous = None
        for x, y, _t, start in self.trail:
            if previous and not start:
                draw.line((previous[0], previous[1], x, y), fill=(*ACCENT, 255), width=4)
            previous = (x, y)
        if self.trail:
            x, y = self.trail[-1][:2]
            draw.ellipse((x - 14, y - 14, x + 14, y + 14), outline=(*DANGER, 255), width=3)
            draw.line((x - 22, y, x + 22, y), fill=(*DANGER, 255), width=2)
            draw.line((x, y - 22, x, y + 22), fill=(*DANGER, 255), width=2)
            self._text(draw, (width - 12, height - 12), f"x={x}  y={y}", max(14, height // 24), fill=DIM,
                       anchor="rd")

    def _draw_toast(self, draw, width, height, text):
        size = max(16, height // 18)
        font = self._font(size, True)
        tw = draw.textlength(text, font=font)
        h = max(38, height // 10)
        box = (int((width - tw) / 2 - 26), int(height * 0.40), int((width + tw) / 2 + 26), int(height * 0.40 + h))
        draw.rounded_rectangle(box, radius=h // 2, fill=(20, 20, 24, 235), outline=(255, 255, 255, 40))
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), text, font=font, fill=TEXT, anchor="mm")


def state_path(state_dir, display_id):
    if not state_dir:
        return None
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in display_id)
    return os.path.join(state_dir, f"touch-{safe}.json")
