"""Theme registry.

A theme is an object with ``info`` (:class:`ThemeInfo`), ``render(width,
height, settings, ctx) -> PIL.Image`` and ``frame_interval(settings, ctx)``.
Themes never talk to drivers: the runtime hands their frames to the
transport, and the configuration window uses the very same objects for the
live preview.
"""

import functools
import io
import math
import os
import subprocess
import time
from dataclasses import dataclass, field

from PIL import Image, ImageFont

from .i18n import N_

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(BASE_DIR, "fonts")
FALLBACK = "standard"


@dataclass(frozen=True)
class ThemeInfo:
    id: str
    name: str
    description: str
    author: str = "BigLinux Team"
    animated: bool = False
    orientations: tuple = ("horizontal", "vertical")
    resolutions: str = N_("any")
    features: tuple = field(default_factory=tuple)
    preferences: tuple = field(default_factory=tuple)


# Render period of static dashboards relative to their base period, per
# performance profile. Never above 1 s, so clocks with seconds stay exact.
STATIC_PERIOD_FACTOR = {"economy": 2.0, "balanced": 1.0, "auto": 1.0, "fluid": 0.5}


def static_period(settings, ctx, base=0.5):
    """Seconds between renders of a theme that only changes with data, never
    faster than the frame rate the runtime allows for the panel."""
    factor = STATIC_PERIOD_FACTOR.get(settings.get("performance_profile", "auto"), 1.0)
    period = min(1.0, base * factor)
    fps = getattr(ctx, "target_fps", 0) if ctx is not None else 0
    if fps:
        period = max(period, 1.0 / fps)
    return period


def static_interval(settings, ctx, base=0.5):
    """Seconds until the next render, aligned to the wall clock so the clock
    never lags visibly."""
    period = static_period(settings, ctx, base)
    return period - (time.time() % period) + 0.01


@functools.lru_cache(maxsize=32)
def ui_font(size, bold=False):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), int(size))
    except OSError:
        return ImageFont.load_default()


class LegacyTheme:
    """Adapter for the 3.x dashboard renderers (data refreshes at 1 Hz)."""

    def __init__(self, info, ctx=None):
        self.info = info

    # Smallest scale each hand-tuned layout was designed for. Below it the
    # 3.x renderers overlapped text (and Old Computer crashed at 240x320), so
    # they are drawn at that scale and reduced proportionally instead.
    MIN_SCALE = {
        "planet": lambda w, h: 0.58 / min(w / 800, h / 480) if w >= h else 0.75 / min(w / 320, h / 480),
        "old_computer": lambda w, h: 0.55 / min(w / 1024, h / 480) if w >= h else 0.72 / min(w / 320, h / 480),
    }

    def render(self, width, height, settings, ctx):
        from . import legacy_themes
        settings = dict(settings, theme=self.info.id)
        if self.info.id == "gkrellm":
            from . import gkrellm
            return gkrellm.render(width, height, settings)
        factor = self.MIN_SCALE[self.info.id](width, height)
        draw_w, draw_h = (width, height) if factor <= 1.0 else (math.ceil(width * factor), math.ceil(height * factor))
        if self.info.id == "planet":
            image = legacy_themes.render_dashboard_planet(draw_w, draw_h, settings)
            image = legacy_themes.planet_accent(image, settings.get("planet_accent", "blue"))
        else:
            image = legacy_themes.render_dashboard_old_computer(draw_w, draw_h, settings)
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        return image

    def frame_interval(self, settings, ctx):
        return static_interval(settings, ctx)

    def close(self):
        pass


STANDARD = ThemeInfo(
    "standard", N_("Standard"),
    N_("Clean dashboard with CPU, memory, disk, GPU, network and processes. Eight colour schemes."),
    preferences=("std_*",))

LEGACY = [
    ThemeInfo("gkrellm", N_("GKrellM"), N_("Tribute to the classic GKrellM monitor, with modules."),
              preferences=("gk_*",)),
    ThemeInfo("planet", N_("Planet"), N_("Orbital view with real Sun and Moon positions."),
              preferences=("planet_*",)),
    ThemeInfo("old_computer", N_("Old Computer"), N_("Retro desktop window look."), preferences=("oc_*",)),
]

BROTHER_AWAY = ThemeInfo(
    "brother_away", N_("Brother Away — The Perplexed Castaway!"),
    N_("Animated tropical island with stories, weather, day/night cycle and a telemetry overlay."),
    author="BigLinux Team", animated=True, resolutions=N_("any (pixel art scaled by integer factors)"),
    features=("animation", "narrative", "overlay", "persistence"), preferences=("ba_*", "overlay_*"))

KOJIRO = ThemeInfo(
    "kojiro", N_("Kojiro — Custom Wallpaper & Hardware Overlay"),
    N_("Your wallpaper with freely placed hardware widgets: rings, bars, graphs, clock and distro logo."),
    animated=True, resolutions=N_("any (layout adapts with anchors)"),
    features=("wallpaper", "editor", "widgets", "presets"), preferences=("kojiro",))

REGISTRY = {info.id: info for info in [STANDARD] + LEGACY + [BROTHER_AWAY, KOJIRO]}
# 3.x theme ids, now colour schemes of the Standard theme.
LEGACY_ALIASES = ("dark", "light", "neon", "cyberpunk")


def available():
    return list(REGISTRY.values())


def create(theme_id, ctx=None):
    """Instantiate a theme; unknown or broken themes fall back to Standard."""
    from .dashboard import StandardTheme
    if theme_id in LEGACY_ALIASES:
        return StandardTheme(REGISTRY["standard"], ctx, scheme=theme_id)
    info = REGISTRY.get(theme_id) or REGISTRY[FALLBACK]
    if info.id == "brother_away":
        try:
            from .brother_away import BrotherAwayTheme
            return BrotherAwayTheme(info, ctx)
        except Exception:  # noqa: BLE001 - never leave the panel without a theme
            import logging
            logging.getLogger("bsmd").exception("Brother Away failed to load; using %s", FALLBACK)
            info = REGISTRY[FALLBACK]
    if info.id == "standard":
        return StandardTheme(info, ctx)
    if info.id == "kojiro":
        from .kojiro.engine import KojiroTheme
        return KojiroTheme(info, ctx)
    return LegacyTheme(info, ctx)


ROUND_SAFE = 0.70      # inscribed square of a circle is 1/sqrt(2) = 0.707 of its diameter


def render_for_panel(theme, width, height, settings, ctx):
    """Render ``theme`` adapted to the panel: compact layout on tiny panels,
    safe area on round ones. Used by the runtime and by the GUI preview."""
    if getattr(ctx, "shape", "rect") == "round":
        side = int(min(width, height) * ROUND_SAFE)
        inner = _render_rect(theme, side, side, settings, ctx)
        image = Image.new("RGB", (width, height), inner.getpixel((0, 0)))
        image.paste(inner, ((width - side) // 2, (height - side) // 2))
        return image
    return _render_rect(theme, width, height, settings, ctx)


def _render_rect(theme, width, height, settings, ctx):
    from . import compact
    if compact.needed(width, height) and theme.info.id != "kojiro":    # Kojiro has its own micro layout
        if theme.info.id != "brother_away":
            return compact.render(width, height, settings, theme.info.id)
        settings = dict(settings, overlay_size="compact")   # the scene scales, the overlay must shrink
    return theme.render(width, height, settings, ctx)


def background_color(settings):
    """Main background colour of the configured theme (splash screens)."""
    if settings.get("theme") == "kojiro":
        return (8, 10, 20)
    if settings.get("theme") in ("standard", *LEGACY_ALIASES):
        from .dashboard import SCHEMES
        scheme = settings.get("std_scheme") if settings.get("theme") == "standard" else settings.get("theme")
        return SCHEMES.get(scheme, SCHEMES["dark"])["bg"]
    from .legacy_themes import get_theme_colors
    return get_theme_colors(settings.get("theme", "dark"))["bg"]


_INTRO_LOGO = {}


def intro_frame(width, height, settings):
    """Splash with the application logo (shown once after the first connect)."""
    background = background_color(settings)
    max_h = int(height * (0.3 if height > width else 0.5))
    if max_h not in _INTRO_LOGO:
        logo = None
        for path in (os.path.join(BASE_DIR, "..", "icons", "hicolor", "scalable", "apps",
                                  "big-screen-monitor-display.svg"),
                     "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg"):
            if not os.path.exists(path):
                continue
            try:
                result = subprocess.run(["rsvg-convert", "-h", str(max_h), path],
                                        capture_output=True, timeout=5, check=False)
                if result.returncode == 0:
                    logo = Image.open(io.BytesIO(result.stdout)).convert("RGBA")
                    break
            except (OSError, subprocess.SubprocessError):
                continue
        _INTRO_LOGO[max_h] = logo
    logo = _INTRO_LOGO[max_h]
    image = Image.new("RGB", (width, height), background)
    if logo is not None:
        image.paste(logo, ((width - logo.width) // 2, (height - logo.height) // 2), logo)
    return image
