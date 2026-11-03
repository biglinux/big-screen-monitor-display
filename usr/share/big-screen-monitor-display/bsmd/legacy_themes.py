"""Planet and Old Computer renderers from the 3.x ``main.py``, plus shared
helpers (icons, distro logo, cached external commands).

Dark, Light, Neon and Cyberpunk became colour schemes of the Standard theme
(``dashboard.py``) and GKrellM was rebuilt in ``gkrellm.py``.

Changes compared with 3.x:
* external commands (docker, playerctl, amixer) go through
  :func:`cached_command`, which never blocks the render thread - a hung
  ``docker ps`` used to freeze the whole display loop;
* fonts are cached instead of being loaded from disk on every frame;
* bare ``except:`` clauses became ``except Exception:``.
"""

import functools
import io
import math
import os
import platform
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import psutil
from PIL import Image, ImageDraw, ImageFont

from .telemetry import (CPU_SYSTEM_HISTORY, CPU_TEMP_HISTORY, CPU_USAGE_HISTORY,  # noqa: F401
                        CPU_USER_HISTORY, DISK_IO_HISTORY, GPU_MEM_HISTORY, GPU_USAGE_HISTORY,
                        NET_RX_HISTORY, NET_TX_HISTORY, RAM_USAGE_HISTORY, SYSTEM_STATS)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@functools.lru_cache(maxsize=96)
def _cached_truetype(path, size):
    return _ORIGINAL_TRUETYPE(path, size)


_ORIGINAL_TRUETYPE = ImageFont.truetype


class _FontCache:
    """``ImageFont`` stand-in whose ``truetype`` is memoised."""

    @staticmethod
    def truetype(path, size):
        return _cached_truetype(path, size)

    load_default = staticmethod(ImageFont.load_default)


_COMMAND_CACHE = {}
_COMMAND_LOCK = threading.Lock()


def cached_command(argv, ttl=5.0, timeout=2.0):
    """Return the last stdout of ``argv`` without ever blocking the caller.

    Stale entries are refreshed by a short-lived background thread with a
    hard timeout. Failures yield an empty string.
    """
    key = tuple(argv)
    now = time.monotonic()
    with _COMMAND_LOCK:
        entry = _COMMAND_CACHE.setdefault(key, {"value": "", "at": -1e9, "running": False, "ok": None})
        if entry["running"] or now - entry["at"] < ttl:
            return entry["value"]
        entry["running"] = True

    def refresh():
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
            value, ok = result.stdout.strip(), result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            value, ok = "", False
        with _COMMAND_LOCK:
            entry.update(value=value, at=time.monotonic(), running=False, ok=ok)

    threading.Thread(target=refresh, name="cmd-cache", daemon=True).start()
    return entry["value"]


def cached_command_ok(argv):
    """Whether the last run of ``argv`` succeeded (None while unknown)."""
    with _COMMAND_LOCK:
        entry = _COMMAND_CACHE.get(tuple(argv))
        return None if entry is None else entry["ok"]

def get_theme_colors(theme_name):
    themes = {
        "dark": {
            "bg": (18, 18, 25), "panel_bg": (30, 30, 40), "text_main": (255, 255, 255),
            "text_muted": (180, 180, 200), "text_label": (200, 200, 220), "time": (77, 217, 255),
            "good": (77, 217, 112), "warn": (249, 217, 35), "crit": (255, 85, 85),
            "vram": (215, 120, 255), "swap": (77, 150, 255), "disk": (200, 200, 200),
            "temp_line": (249, 100, 35), "bar_bg": (40, 40, 50), "border": (60, 60, 80),
            "icon_color": (255, 255, 255)
        },
        "light": {
            "bg": (231, 239, 248), "panel_bg": (250, 252, 255), "text_main": (24, 35, 52),
            "text_muted": (83, 101, 124), "text_label": (42, 91, 138), "time": (0, 105, 192),
            "good": (24, 148, 91), "warn": (190, 119, 0), "crit": (198, 56, 79),
            "vram": (105, 76, 180), "swap": (25, 111, 190), "disk": (102, 119, 137),
            "temp_line": (214, 98, 28), "bar_bg": (215, 226, 238), "border": (184, 202, 222),
            "icon_color": (42, 82, 117)
        },
        "neon": {
            "bg": (10, 5, 20), "panel_bg": (20, 10, 40), "text_main": (255, 255, 255),
            "text_muted": (255, 105, 180), "text_label": (0, 255, 255), "time": (255, 0, 255),
            "good": (57, 255, 20), "warn": (255, 255, 0), "crit": (255, 49, 49),
            "vram": (157, 0, 255), "swap": (0, 255, 255), "disk": (200, 200, 200),
            "temp_line": (255, 165, 0), "bar_bg": (40, 20, 60), "border": (80, 40, 120),
            "icon_color": (255, 255, 255)
        },
        "cyberpunk": {
            "bg": (2, 2, 4), "panel_bg": (10, 10, 15), "text_main": (253, 237, 5),
            "text_muted": (153, 143, 3), "text_label": (255, 99, 146), "time": (0, 240, 255),
            "good": (22, 198, 12), "warn": (253, 237, 5), "crit": (255, 25, 76),
            "vram": (138, 43, 226), "swap": (0, 240, 255), "disk": (200, 200, 200),
            "temp_line": (255, 140, 0), "bar_bg": (20, 20, 30), "border": (253, 237, 5),
            "icon_color": (255, 255, 255)
        },
        "gkrellm": {
            "bg": (0, 0, 0), "panel_bg": (0, 0, 0), "text_main": (170, 255, 170),
            "text_muted": (85, 170, 85), "text_label": (85, 170, 85), "time": (170, 255, 170),
            "good": (170, 255, 170), "warn": (170, 255, 170), "crit": (170, 255, 170),
            "vram": (170, 255, 170), "swap": (170, 255, 170), "disk": (170, 255, 170),
            "temp_line": (170, 255, 170), "bar_bg": (0, 0, 0), "border": (85, 170, 85),
            "icon_color": (170, 255, 170)
        },
        "planet": {
            "bg": (3, 7, 18), "panel_bg": (7, 17, 36), "text_main": (229, 245, 255),
            "text_muted": (103, 157, 190), "text_label": (121, 211, 255), "time": (188, 239, 255),
            "good": (67, 231, 190), "warn": (255, 190, 84), "crit": (255, 91, 112),
            "vram": (169, 123, 255), "swap": (61, 157, 255), "disk": (120, 210, 235),
            "temp_line": (255, 129, 75), "bar_bg": (12, 38, 64), "border": (29, 107, 151),
            "icon_color": (125, 220, 255)
        },
        "old_computer": {
            "bg": (192, 192, 192), "panel_bg": (192, 192, 192), "text_main": (64, 64, 64),
            "text_muted": (64, 64, 64), "text_label": (0, 0, 128), "time": (0, 0, 128),
            "good": (0, 205, 0), "warn": (128, 128, 0), "crit": (180, 0, 0),
            "vram": (0, 0, 180), "swap": (0, 0, 128), "disk": (64, 64, 64),
            "temp_line": (0, 160, 0), "bar_bg": (0, 32, 0), "border": (0, 0, 128),
            "icon_color": (0, 0, 128)
        }
    }
    # Fallback default para temas customizados ou incompletos
    theme = themes.get(theme_name, themes["dark"])
    if "icon_color" not in theme:
        theme["icon_color"] = (255, 255, 255) if theme_name != "light" else (40, 40, 45)
    return theme

# Cache Global de Icones SVG 
ICON_CACHE = {}

_LOGO_CACHE = {}

def load_distro_logo(logo_name, size):
    """Load distro logo from /usr/share/pixmaps/, supporting PNG and SVG."""
    cache_key = f"{logo_name}_{size}"
    if cache_key in _LOGO_CACHE:
        return _LOGO_CACHE[cache_key]

    base = f"/usr/share/pixmaps/{logo_name}"
    for ext in (".png", ".svg"):
        path = base + ext
        if not os.path.exists(path):
            continue
        try:
            if ext == ".svg":
                p = subprocess.run(
                    ["rsvg-convert", "-w", str(size), "-h", str(size), path],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
                if p.returncode == 0:
                    logo = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
                    _LOGO_CACHE[cache_key] = logo
                    return logo
            else:
                logo = Image.open(path).convert("RGBA")
                try:
                    resamp = Image.Resampling.LANCZOS
                except AttributeError:
                    resamp = 1
                logo.thumbnail((size, size), resamp)
                _LOGO_CACHE[cache_key] = logo
                return logo
        except Exception:
            continue
    _LOGO_CACHE[cache_key] = None  # negative cache: do not spawn rsvg-convert every frame
    return None

def get_svg_icon(name, size, color=None):
    cache_key = f"{name}_{size}_{color}"
    if cache_key in ICON_CACHE:
        return ICON_CACHE[cache_key]
        
    path = os.path.join(BASE_DIR, "img", name)
    if os.path.exists(path):
        try:
            if color:
                with open(path, 'r') as f:
                    svg_data = f.read()
                
                # Converte tupla (R, G, B) para Hex
                c_hex = '#{:02x}{:02x}{:02x}'.format(*color) if isinstance(color, tuple) else color
                
                # Recolour white strokes/fills in one pass. (The former second
                # pass also matched the colour just inserted - "#ffff00" became
                # "#ffff0000" - and icons in yellowish colours disappeared.)
                svg_data = re.sub(r'#(?:[fF]{6}|[fF]{3})(?![0-9a-fA-F])', c_hex, svg_data)
                
                p = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size)], 
                                   input=svg_data.encode('utf-8'),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            else:
                p = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), path], 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            
            if p.returncode == 0:
                img = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
                ICON_CACHE[cache_key] = img
                return img
        except Exception:
            pass
    ICON_CACHE[cache_key] = None  # negative cache: do not spawn rsvg-convert every frame
    return None

def get_os_release():
    info = {"PRETTY_NAME": "Linux", "LOGO": ""}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except Exception:
        pass
    return info

def get_text_width(d, text, font):
    try:
        return int(d.textlength(text, font=font))
    except AttributeError:
        try:
            return int(d.textbbox((0, 0), text, font=font)[2])
        except AttributeError:
            return int(font.getsize(text)[0])


def fit_text_to_width(d, value, max_width, font):
    """Trim a label with an ellipsis so adjacent metrics never collide."""
    value = str(value)
    if max_width <= 0:
        return ""
    if get_text_width(d, value, font) <= max_width:
        return value
    ellipsis = "…"
    while value and get_text_width(d, value + ellipsis, font) > max_width:
        value = value[:-1]
    return (value + ellipsis) if value else ellipsis



def _planet_cpu_model():
    """Return a short CPU model name for the compact Planet panel."""
    cached = getattr(_planet_cpu_model, "cached", None)
    if cached:
        return cached

    model = platform.processor() or "CPU"
    try:
        with open("/proc/cpuinfo", "r") as cpuinfo:
            for line in cpuinfo:
                if line.lower().startswith("model name") and ":" in line:
                    model = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass

    model = re.sub(r"\s+", " ", model).strip()
    if len(model) > 25:
        model = model[:24].rstrip() + "…"
    _planet_cpu_model.cached = model or "CPU"
    return _planet_cpu_model.cached


_PLANET_LAST_GLOBE = []


def _planet_paths(settings, sun_path, moon_path):
    if not settings.get("planet_show_paths", True):
        return [], []
    return sun_path, (moon_path if settings.get("planet_show_moon", True) else [])


def _planet_globe_options(settings):
    return {"city_lights": settings.get("planet_city_lights", True), "night": settings.get("planet_night", True),
            "show_moon": settings.get("planet_show_moon", True)}


PLANET_ACCENTS = {"green": 85, "amber": 27, "violet": 195, "red": 251}   # target hue, 0..255


def planet_accent(image, accent):
    """Recolour the blue interface; the Earth itself is pasted back unchanged."""
    target = PLANET_ACCENTS.get(accent)
    if target is None:
        return image
    hsv = np.array(image.convert("HSV"))
    hue = hsv[..., 0].astype(np.int16)
    blue = (hsv[..., 1] > 45) & (hue >= 105) & (hue <= 180)
    hue[blue] = (hue[blue] - 142 + target) % 256
    hsv[..., 0] = hue.astype(np.uint8)
    result = Image.fromarray(hsv, "HSV").convert("RGB")
    if _PLANET_LAST_GLOBE:
        globe, position, mask = _PLANET_LAST_GLOBE
        result.paste(globe, position, mask)
    return result


def _planet_status_line():
    """Real data in place of the old fixed "SUNNY / WIND 3 / 22°C" text."""
    from .dashboard import format_uptime
    uptime = format_uptime(SYSTEM_STATS.get("boot_time")) or "--"
    return f"UP {uptime} / {SYSTEM_STATS.get('hostname', '')}".upper()


def _planet_gpu_clock(gpu):
    clock = gpu.get("clock_mhz") if gpu else None
    return f"{clock}M" if clock else "--"


def _planet_temperature(value):
    """Convert a sensor value such as '62°C' into a float or None."""
    try:
        return float(re.sub(r"[^0-9.+-]", "", str(value)))
    except (TypeError, ValueError):
        return None


def _planet_julian_day(when):
    """Convert an aware UTC datetime to a Julian day."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp() / 86400.0 + 2440587.5


def _planet_normalize_longitude(longitude):
    return ((longitude + 180.0) % 360.0) - 180.0


def _planet_sidereal_degrees(julian_day):
    """Greenwich apparent sidereal time, adequate for a display globe."""
    centuries = (julian_day - 2451545.0) / 36525.0
    sidereal = (280.46061837
                + 360.98564736629 * (julian_day - 2451545.0)
                + 0.000387933 * centuries * centuries
                - centuries * centuries * centuries / 38710000.0)
    return sidereal % 360.0


def _planet_sun_position(when):
    """Return the Sun's subsolar latitude/longitude in degrees.

    The longitude is the geographic point where the Sun is overhead. The
    low-order solar model is more than sufficient for a 3.5-inch telemetry
    display and keeps the feature fully offline.
    """
    jd = _planet_julian_day(when)
    days = jd - 2451545.0
    mean_longitude = math.radians((280.460 + 0.9856474 * days) % 360.0)
    mean_anomaly = math.radians((357.528 + 0.9856003 * days) % 360.0)
    ecliptic_longitude = (mean_longitude
                          + math.radians(1.915) * math.sin(mean_anomaly)
                          + math.radians(0.020) * math.sin(2.0 * mean_anomaly))
    obliquity = math.radians(23.439 - 0.0000004 * days)
    right_ascension = math.degrees(math.atan2(
        math.cos(obliquity) * math.sin(ecliptic_longitude),
        math.cos(ecliptic_longitude))) % 360.0
    declination = math.degrees(math.asin(
        math.sin(obliquity) * math.sin(ecliptic_longitude)))
    longitude = _planet_normalize_longitude(
        right_ascension - _planet_sidereal_degrees(jd))
    return declination, longitude


def _planet_moon_position(when):
    """Return the Moon's approximate sublunar latitude/longitude in degrees."""
    jd = _planet_julian_day(when)
    days = jd - 2451543.5
    ascending_node = math.radians((125.1228 - 0.0529538083 * days) % 360.0)
    inclination = math.radians(5.1454)
    argument = math.radians((318.0634 + 0.1643573223 * days) % 360.0)
    eccentricity = 0.054900
    mean_anomaly = math.radians((115.3654 + 13.0649929509 * days) % 360.0)

    eccentric_anomaly = math.degrees(mean_anomaly) + math.degrees(eccentricity) * math.sin(mean_anomaly) \
        * (1.0 + eccentricity * math.cos(mean_anomaly))
    eccentric_anomaly = math.radians(eccentric_anomaly)
    xv = 60.2666 * (math.cos(eccentric_anomaly) - eccentricity)
    yv = 60.2666 * math.sqrt(1.0 - eccentricity * eccentricity) * math.sin(eccentric_anomaly)
    true_anomaly = math.atan2(yv, xv)
    distance = math.hypot(xv, yv)
    longitude = true_anomaly + argument

    x_ecliptic = distance * (math.cos(ascending_node) * math.cos(longitude)
                             - math.sin(ascending_node) * math.sin(longitude) * math.cos(inclination))
    y_ecliptic = distance * (math.sin(ascending_node) * math.cos(longitude)
                             + math.cos(ascending_node) * math.sin(longitude) * math.cos(inclination))
    z_ecliptic = distance * math.sin(longitude) * math.sin(inclination)

    obliquity = math.radians(23.4393)
    x_equatorial = x_ecliptic
    y_equatorial = y_ecliptic * math.cos(obliquity) - z_ecliptic * math.sin(obliquity)
    z_equatorial = y_ecliptic * math.sin(obliquity) + z_ecliptic * math.cos(obliquity)
    right_ascension = math.degrees(math.atan2(y_equatorial, x_equatorial)) % 360.0
    declination = math.degrees(math.atan2(
        z_equatorial, math.hypot(x_equatorial, y_equatorial)))
    sublunar_longitude = _planet_normalize_longitude(
        right_ascension - _planet_sidereal_degrees(jd))
    return declination, sublunar_longitude


def _planet_path(position_function, when, hours_before=12, hours_after=12, step_minutes=60):
    path = []
    for minutes in range(-hours_before * 60, hours_after * 60 + 1, step_minutes):
        point_time = when + timedelta(minutes=minutes)
        path.append(position_function(point_time))
    return path


def _planet_texture():
    """Load the detailed equirectangular Earth texture once."""
    cached = getattr(_planet_texture, "cached", False)
    if cached is not False:
        return cached
    path = os.path.join(BASE_DIR, "img", "planet-earth-texture.png")
    try:
        _planet_texture.cached = np.asarray(Image.open(path).convert("RGB"))
    except Exception:
        _planet_texture.cached = None
    return _planet_texture.cached


def _planet_globe(radius, phase, sun_position, moon_position, sun_path, moon_path,
                  city_lights=True, night=True, show_moon=True):
    """Build the detailed Earth with clock-based illumination and tracks."""
    radius = max(12, int(radius))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    nx = xx / radius
    ny = yy / radius
    distance = nx * nx + ny * ny
    inside = distance <= 1.0
    nz = np.sqrt(np.clip(1.0 - distance, 0.0, 1.0))

    sun_latitude, sun_longitude = sun_position
    sun_lon_screen = math.radians(sun_longitude) + phase
    sun_lat_screen = math.radians(sun_latitude)
    sun_vector_x = math.cos(sun_lat_screen) * math.sin(sun_lon_screen)
    sun_vector_y = math.sin(sun_lat_screen)
    sun_vector_z = math.cos(sun_lat_screen) * math.cos(sun_lon_screen)
    # The terminator is driven by the actual subsolar point, not an animation.
    light = np.clip((nx * sun_vector_x) - (ny * sun_vector_y) + (nz * sun_vector_z), -1.0, 1.0)
    if not night:
        light = np.maximum(light, 0.55)    # option: whole globe lit
    day = np.clip(0.18 + (light * 0.82), 0.045, 1.0)
    texture = _planet_texture()
    if texture is not None:
        texture_height, texture_width = texture.shape[:2]
        screen_longitude = np.arctan2(nx, nz)
        world_longitude = screen_longitude - phase
        latitude = np.arcsin(np.clip(-ny, -1.0, 1.0))
        texture_x = ((world_longitude + math.pi) / (2.0 * math.pi) * texture_width).astype(int) % texture_width
        texture_y = ((math.pi / 2.0 - latitude) / math.pi * (texture_height - 1)).astype(int)
        pixels = texture[texture_y, texture_x].astype(np.float32)
        shade = np.where(light >= 0.0, 0.25 + 0.75 * light, 0.035 + 0.13 * (light + 1.0))
        city_glow = np.maximum(0.0, pixels[..., 0] - pixels[..., 2] * 0.72) / 255.0 * (1.0 if city_lights else 0.0)
        pixels = pixels * shade[..., None]
        pixels += city_glow[..., None] * np.clip(-light[..., None], 0.0, 1.0) * np.array([155.0, 91.0, 24.0])
        rim = np.clip((1.0 - nz) * 1.8, 0.0, 1.0)
        pixels += rim[..., None] * np.array([4.0, 32.0, 72.0])
        pixels = np.clip(pixels, 0, 255).astype(np.uint8)
    else:
        noise = (np.sin(xx * 0.23) + np.sin(yy * 0.17)) * 2.0
        red = np.clip((8 + 16 * day + noise), 0, 255)
        green = np.clip((31 + 72 * day + noise), 0, 255)
        blue = np.clip((82 + 125 * day + noise), 0, 255)
        pixels = np.dstack((red, green, blue)).astype(np.uint8)
    pixels[~inside] = 0
    globe = Image.fromarray(pixels, "RGB")
    draw = ImageDraw.Draw(globe, "RGBA")
    center = radius

    def project(longitude, latitude):
        lon = math.radians(longitude) + phase
        lat = math.radians(latitude)
        visible = math.cos(lat) * math.cos(lon) > -0.08
        x = center + radius * math.cos(lat) * math.sin(lon)
        y = center - radius * math.sin(lat)
        return x, y, visible

    # Keep the generated texture clean: the detailed coastlines and terrain
    # remain visible, while the astronomy tracks are the only overlays.
    cities = [(-74, 10), (-58, -15), (-3, 6), (31, 30), (37,  -1),
              (77, 28), (116, 40), (139, 36), (151, -33)]
    for longitude, latitude in (cities if city_lights else ()):
        x, y, visible = project(longitude, latitude)
        lon = math.radians(longitude) + phase
        lat = math.radians(latitude)
        city_light = math.cos(lat) * math.cos(lon) * 0.30 - math.sin(lat) * 0.20
        if visible and city_light < 0.02:
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(255, 208, 103, 190))

    def draw_path(path, color):
        segment = []
        path_width = max(1, radius // 55)
        for latitude, longitude in path:
            x, y, visible = project(longitude, latitude)
            if visible:
                segment.append((x, y))
            elif len(segment) > 1:
                draw.line(segment, fill=color, width=path_width)
                segment = []
        if len(segment) > 1:
            draw.line(segment, fill=color, width=path_width)

    # The two tracks show where the bodies have been and where they are going
    # over the surrounding 24 hours. The current markers are drawn brighter.
    draw_path(sun_path, (255, 181, 72, 145))
    draw_path(moon_path, (226, 237, 255, 110))

    moon_latitude, moon_longitude = moon_position
    sun_x, sun_y, sun_visible = project(sun_longitude, sun_latitude)
    if sun_visible:
        marker_radius = max(3, radius // 22)
        draw.ellipse((sun_x - marker_radius - 2, sun_y - marker_radius - 2,
                      sun_x + marker_radius + 2, sun_y + marker_radius + 2),
                     outline=(255, 224, 129, 180), width=1)
        draw.ellipse((sun_x - marker_radius, sun_y - marker_radius,
                      sun_x + marker_radius, sun_y + marker_radius),
                     fill=(255, 170, 48, 255), outline=(255, 245, 170, 255))
        draw.line((sun_x - marker_radius - 4, sun_y, sun_x + marker_radius + 4, sun_y),
                  fill=(255, 205, 87, 230), width=1)
        draw.line((sun_x, sun_y - marker_radius - 4, sun_x, sun_y + marker_radius + 4),
                  fill=(255, 205, 87, 230), width=1)

    moon_x, moon_y, moon_visible = project(moon_longitude, moon_latitude)
    if moon_visible and show_moon:
        marker_radius = max(3, radius // 27)
        draw.ellipse((moon_x - marker_radius, moon_y - marker_radius,
                      moon_x + marker_radius, moon_y + marker_radius),
                     fill=(214, 228, 238, 230), outline=(255, 255, 255, 240))
        draw.ellipse((moon_x - 1, moon_y - 2, moon_x + 1, moon_y), fill=(145, 170, 188, 220))

    return globe


def _planet_moon_icon(radius, phase_angle):
    """Return a small Moon sprite whose lit side follows the Sun angle."""
    radius = max(3, int(radius))
    yy, xx = np.mgrid[-radius:radius + 1, -radius:radius + 1]
    nx = xx / radius
    ny = yy / radius
    distance = nx * nx + ny * ny
    inside = distance <= 1.0
    nz = np.sqrt(np.clip(1.0 - distance, 0.0, 1.0))
    light = np.clip(
        nx * math.sin(phase_angle) + nz * math.cos(phase_angle), -1.0, 1.0)
    shade = np.clip(0.12 + 0.88 * light, 0.055, 1.0)
    crater_noise = (np.sin(xx * 1.7) + np.sin(yy * 1.35)) * 4.0
    gray = np.clip(42.0 + shade * 166.0 + crater_noise, 0.0, 255.0)
    pixels = np.dstack((gray * 0.88, gray, gray * 1.04)).clip(0, 255).astype(np.uint8)
    pixels[~inside] = 0
    sprite = Image.fromarray(pixels, "RGB")
    mask = Image.fromarray((inside.astype(np.uint8) * 255), "L")
    return sprite, mask


def render_dashboard_planet_portrait(width, height, settings):
    """Render Planet as one vertical column for portrait displays."""
    scale = max(0.75, min(width / 320.0, height / 480.0))
    colors = get_theme_colors("planet")
    img = Image.new("RGB", (width, height), colors["bg"])
    d = ImageDraw.Draw(img)
    font_dir = os.path.join(BASE_DIR, "fonts")

    def make_font(filename, size):
        try:
            return _FontCache.truetype(os.path.join(font_dir, filename), max(7, int(size)))
        except Exception:
            return _FontCache.load_default()

    font_title = make_font("DejaVuSans-Bold.ttf", 12 * scale)
    font_time = make_font("DejaVuSans-Bold.ttf", 23 * scale)
    font_medium = make_font("DejaVuSans-Bold.ttf", 10.2 * scale)
    font_small = make_font("DejaVuSans.ttf", 8.5 * scale)
    font_mono = make_font("DejaVuSans.ttf", 8.6 * scale)
    font_mono_bold = make_font("DejaVuSans-Bold.ttf", 8.6 * scale)
    line_width = max(1, int(scale))
    panel_radius = max(3, int(6 * scale))
    margin = max(5, int(6 * scale))
    inner_x = margin + max(5, int(7 * scale))
    inner_w = width - inner_x * 2

    def panel(x, y, w, h, fill=colors["panel_bg"]):
        d.rounded_rectangle((x, y, x + w, y + h), radius=panel_radius,
                            fill=fill, outline=colors["border"], width=line_width)

    def text(x, y, value, font=font_small, fill=colors["text_main"]):
        d.text((int(x), int(y)), str(value), font=font, fill=fill)

    def clipped(value, limit):
        value = str(value)
        return value if len(value) <= limit else value[:max(1, limit - 1)] + "…"

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)
    astronomy_utc = now_utc.replace(second=0, microsecond=0)
    julian_day = _planet_julian_day(astronomy_utc)
    sun_position = _planet_sun_position(astronomy_utc)
    moon_position = _planet_moon_position(astronomy_utc)
    sun_path = _planet_path(_planet_sun_position, astronomy_utc)
    moon_path = _planet_path(_planet_moon_position, astronomy_utc, step_minutes=120)
    earth_phase = math.radians(_planet_sidereal_degrees(julian_day))
    moon_elongation = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1]))
    moon_illumination = (1.0 - math.cos(moon_elongation)) / 2.0
    moon_light_phase = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1] + 180.0))

    # One uninterrupted portrait canvas: header, astronomical view and then
    # the complete hardware stack.
    panel(margin, margin, width - margin * 2, height - margin * 2, (2, 8, 22))
    text(inner_x, int(10 * scale), "PLANET", font_title, colors["text_label"])
    text(inner_x, int(27 * scale), "SYSTEM ORBIT // PORTRAIT", font_mono, colors["text_muted"])
    text(inner_x, int(39 * scale), now_local.strftime("%H:%M:%S" if settings.get("planet_seconds", True) else "%H:%M"), font_time, colors["time"])
    text(inner_x, int(65 * scale), now_local.strftime("%a, %Y-%m-%d"), font_small, colors["text_main"])
    text(inner_x, int(77 * scale), clipped(_planet_status_line(), 34), font_mono, colors["text_muted"])

    # Keep the astronomical readout beside the clock/date, leaving the
    # entire area above the globe visually clear for the orbital view.
    astro_x = inner_x + int(inner_w * 0.49)
    astro_y = int(25 * scale)
    astro_w = width - margin - astro_x
    astro_h = max(51, int(51 * scale))
    panel(astro_x, astro_y, astro_w, astro_h, (5, 14, 31))
    astro_text_w = max(10, astro_w - max(8, int(10 * scale)))
    text(astro_x + max(4, int(5 * scale)), astro_y + max(2, int(3 * scale)),
         fit_text_to_width(d, f"SUN {sun_position[0]:+.1f}° {sun_position[1]:+.1f}°",
                           astro_text_w, font_mono_bold),
         font_mono_bold, (255, 190, 84))
    text(astro_x + max(4, int(5 * scale)), astro_y + max(14, int(16 * scale)),
         fit_text_to_width(d, f"MOON {moon_position[0]:+.1f}° {moon_position[1]:+.1f}°",
                           astro_text_w, font_mono_bold),
         font_mono_bold, colors["text_main"])
    text(astro_x + max(4, int(5 * scale)), astro_y + max(27, int(29 * scale)),
         fit_text_to_width(d, f"MOON LIGHT {moon_illumination * 100:.0f}% · UTC",
                           astro_text_w, font_mono),
         font_mono, colors["text_muted"])

    planet_radius = max(32, int(min(width * 0.156, height * 0.105)))
    planet_cx = width // 2
    planet_cy = int(162 * scale)
    orbit_rx = planet_radius + max(8, int(10 * scale))
    orbit_ry = planet_radius + max(7, int(9 * scale))
    orbit_box = (planet_cx - orbit_rx, planet_cy - orbit_ry,
                 planet_cx + orbit_rx, planet_cy + orbit_ry)
    d.arc(orbit_box, 0, 360, fill=(31, 86, 126), width=line_width)
    moon_orbit_angle = math.radians(moon_position[1]) + earth_phase
    moon_orbit_x = planet_cx + orbit_rx * math.cos(moon_orbit_angle)
    moon_orbit_y = planet_cy + orbit_ry * math.sin(moon_orbit_angle)
    moon_arc = (179, 218, 238)
    if not settings.get("planet_show_moon", True):
        moon_orbit_x = moon_orbit_y = -1000      # sprite, outline and label fall outside the canvas
        moon_arc = (31, 86, 126)
    d.arc(orbit_box, math.degrees(moon_orbit_angle) - 22,
          math.degrees(moon_orbit_angle) + 22,
          fill=moon_arc, width=max(1, line_width + 1))
    d.ellipse((planet_cx - planet_radius - 4, planet_cy - planet_radius - 4,
               planet_cx + planet_radius + 4, planet_cy + planet_radius + 4),
              outline=(31, 120, 174), width=line_width)
    globe = _planet_globe(planet_radius, earth_phase, sun_position, moon_position,
                          *_planet_paths(settings, sun_path, moon_path), **_planet_globe_options(settings))
    mask = Image.new("L", globe.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, globe.width - 1, globe.height - 1), fill=255)
    img.paste(globe, (planet_cx - planet_radius, planet_cy - planet_radius), mask)
    _PLANET_LAST_GLOBE[:] = [globe, (planet_cx - planet_radius, planet_cy - planet_radius), mask]
    d = ImageDraw.Draw(img)
    d.ellipse((planet_cx - planet_radius, planet_cy - planet_radius,
               planet_cx + planet_radius, planet_cy + planet_radius),
              outline=(124, 222, 255), width=line_width)
    moon_radius = max(3, int(5 * scale))
    moon_sprite, moon_mask = _planet_moon_icon(moon_radius, moon_light_phase)
    img.paste(moon_sprite,
              (int(moon_orbit_x - moon_radius), int(moon_orbit_y - moon_radius)),
              moon_mask)
    d = ImageDraw.Draw(img)
    d.ellipse((moon_orbit_x - moon_radius - 1, moon_orbit_y - moon_radius - 1,
               moon_orbit_x + moon_radius + 1, moon_orbit_y + moon_radius + 1),
              outline=(235, 247, 255), width=line_width)
    moon_label_x = min(width - margin - get_text_width(d, "MOON", font_mono),
                       moon_orbit_x + moon_radius + 3)
    text(moon_label_x, moon_orbit_y - max(4, int(4 * scale)), "MOON",
         font_mono, (226, 237, 255))
    text(inner_x, int(226 * scale),
         "TERMINATOR LIVE  ·  MOON ORBIT",
         font_mono, (255, 190, 84))

    hardware_y = int(237 * scale)
    text(inner_x, hardware_y, "HARDWARE TELEMETRY", font_medium, colors["text_label"])
    gpu_list = SYSTEM_STATS.get("gpus", [])
    gpu_idx = min(SYSTEM_STATS.get("active_gpu_idx", 0), max(0, len(gpu_list) - 1))
    active_gpu = gpu_list[gpu_idx] if gpu_list else {}
    cpu_freq = None
    try:
        cpu_freq = psutil.cpu_freq().current
    except Exception:
        pass
    cpu_freq_text = f"{cpu_freq:.0f}M" if cpu_freq else "--"
    cpu_name = clipped(_planet_cpu_model(), 16)
    gpu_name = clipped(active_gpu.get("name", "GPU"), 16)
    gpu_usage = float(active_gpu.get("percent", 0.0) or 0.0)
    gpu_mem = float(active_gpu.get("mem_used_mb", 0) or 0)
    gpu_mem_total = float(active_gpu.get("mem_total_mb", 0) or 0)
    gpu_mem_percent = (gpu_mem / gpu_mem_total * 100.0) if gpu_mem_total else 0.0
    card_y = hardware_y + font_medium.getbbox("HT")[3] + max(3, int(4 * scale))
    card_h = max(23, int(23 * scale))

    def draw_hardware_row(y, label, model, temperature, load, accent):
        panel(inner_x, y, inner_w, card_h, (5, 14, 31))
        numeric = _planet_temperature(temperature)
        temp_text = f"{numeric:.0f}°" if numeric is not None else "--"
        temp_w = get_text_width(d, temp_text, font_mono_bold)
        temp_color = colors["crit"] if (numeric is not None and numeric >= 85) else (
            colors["warn"] if (numeric is not None and numeric >= 60) else colors["good"])
        label_x = inner_x + max(4, int(6 * scale))
        temp_x = inner_x + inner_w - temp_w - max(4, int(6 * scale))
        load_text = f"{load:.0f}%"
        load_w = get_text_width(d, load_text, font_mono_bold)
        load_x = temp_x - load_w - max(8, int(10 * scale))
        model_x = label_x + max(25, int(28 * scale))
        model_w = max(20, load_x - model_x - max(8, int(9 * scale)))
        text(label_x, y + max(2, int(2 * scale)), label, font_mono_bold, colors["text_label"])
        text(model_x, y + max(2, int(2 * scale)),
             fit_text_to_width(d, model, model_w, font_mono),
             font_mono, colors["text_main"])
        text(load_x, y + max(2, int(2 * scale)), load_text, font_mono_bold, colors["text_muted"])
        text(temp_x, y + max(2, int(2 * scale)), temp_text, font_mono_bold, temp_color)
        track_y = y + card_h - max(2, int(3 * scale))
        d.line((inner_x + 4, track_y, inner_x + inner_w - 4, track_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((inner_w - 8) * max(0.0, min(100.0, load)) / 100.0)
        if fill_w:
            d.line((inner_x + 4, track_y, inner_x + 4 + fill_w, track_y), fill=accent,
                   width=max(2, line_width + 1))

    draw_hardware_row(card_y, "CPU", cpu_name, SYSTEM_STATS.get("cpu_temp"),
                      SYSTEM_STATS.get("cpu_percent", 0), colors["good"])
    draw_hardware_row(card_y + card_h + max(3, int(3 * scale)), "GPU", gpu_name,
                      active_gpu.get("temp"), gpu_usage, colors["warn"])

    # Wider portrait panels (for example 480x800) have more vertical room.
    # Give that room to the telemetry graphs instead of leaving an empty
    # strip below the RAM card.
    extra_height = max(0, height - margin - int(474 * scale))
    metric_gap = max(3, int(3 * scale)) + extra_height // 24
    metric_y = int(301 * scale)
    metric_h = max(23, int(23 * scale)) + extra_height // 8
    metric_w = inner_w

    def draw_metric(x, y, label, value, percent, history, color):
        panel(x, y, metric_w, metric_h, (5, 14, 31))
        text(x + 4, y + 1, label, font_mono, colors["text_muted"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + metric_w - value_w - 4, y + 1, value, font_mono_bold, colors["text_main"])
        graph_y = y + metric_h - max(3, int(4 * scale))
        d.line((x + 4, graph_y, x + metric_w - 4, graph_y), fill=colors["bar_bg"], width=line_width)
        if history and len(history) > 1:
            maximum = max(1.0, max(abs(float(item)) for item in history))
            points = []
            for index, item in enumerate(history):
                px = x + 4 + (metric_w - 8) * index / (len(history) - 1)
                py = graph_y - min(1.0, abs(float(item)) / maximum) * max(3, int(8 * scale))
                points.append((px, py))
            d.line(points, fill=color, width=line_width)
        fill_w = int((metric_w - 8) * max(0.0, min(100.0, percent)) / 100.0)
        if fill_w:
            d.line((x + 4, graph_y, x + 4 + fill_w, graph_y), fill=color,
                   width=max(2, line_width + 1))

    metric_specs = [
        ("CPU", f"{SYSTEM_STATS.get('cpu_percent', 0):.0f}%", SYSTEM_STATS.get("cpu_percent", 0), CPU_USAGE_HISTORY, colors["good"]),
        ("FREQ", cpu_freq_text, min(100.0, (cpu_freq or 0) / 40.0), [], colors["text_label"]),
        ("GPU", f"{gpu_usage:.0f}%", gpu_usage, GPU_USAGE_HISTORY, colors["warn"]),
        ("CLOCK", _planet_gpu_clock(active_gpu), min(100.0, (active_gpu.get("clock_mhz") or 0) / 30.0), [],
         colors["vram"]),
        ("VRAM", f"{gpu_mem:.0f}M" if gpu_mem else "--", gpu_mem_percent, GPU_MEM_HISTORY, colors["vram"]),
    ]
    for index, (label, value, percent, history, color) in enumerate(metric_specs):
        draw_metric(inner_x, metric_y + index * (metric_h + metric_gap),
                    label, value, percent, history, color)

    metric_end = metric_y + len(metric_specs) * metric_h + (len(metric_specs) - 1) * metric_gap
    network_y = metric_end + max(3, int(4 * scale))
    network_h = max(20, int(20 * scale)) + extra_height // 16
    net_up = max(0.0, SYSTEM_STATS.get("net_tx_mbps", 0.0) * 125.0)
    net_down = max(0.0, SYSTEM_STATS.get("net_rx_mbps", 0.0) * 125.0)
    network_specs = [
        ("DISK", f"{SYSTEM_STATS.get('disk_percent', 0):.0f}%", SYSTEM_STATS.get("disk_percent", 0), colors["good"]),
        ("U", f"{net_up:.0f}K", min(100.0, net_up / 10.0), colors["text_label"]),
        ("D", f"{net_down:.0f}K", min(100.0, net_down / 10.0), colors["swap"]),
    ]
    network_gap = max(2, int(3 * scale))
    network_w = (inner_w - network_gap * 2) // 3
    for index, (label, value, percent, color) in enumerate(network_specs):
        x = inner_x + index * (network_w + network_gap)
        panel(x, network_y, network_w, network_h, (5, 14, 31))
        text(x + 3, network_y + 1, label, font_mono_bold, colors["text_label"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + network_w - value_w - 3, network_y + 1, value, font_mono_bold, colors["text_main"])
        line_y = network_y + network_h - max(3, int(4 * scale))
        d.line((x + 3, line_y, x + network_w - 3, line_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((network_w - 6) * percent / 100.0)
        if fill_w:
            d.line((x + 3, line_y, x + 3 + fill_w, line_y), fill=color,
                   width=max(2, line_width + 1))

    ram_y = network_y + network_h + max(3, int(4 * scale))
    ram_h = max(18, height - margin - ram_y)
    panel(inner_x, ram_y, inner_w, ram_h, (5, 14, 31))
    text(inner_x + 5, ram_y + max(2, int(2 * scale)), "RAM", font_mono_bold, colors["text_label"])
    ram_values = (f"{SYSTEM_STATS.get('ram_used_mb', 0) / 1024:.1f}G / "
                  f"{SYSTEM_STATS.get('ram_total_mb', 0) / 1024:.1f}G")
    ram_value_w = get_text_width(d, ram_values, font_mono)
    text(inner_x + inner_w - ram_value_w - max(34, int(40 * scale)),
         ram_y + max(2, int(2 * scale)), ram_values, font_mono, colors["text_main"])
    ram_donut_cx = inner_x + inner_w - max(14, int(17 * scale))
    ram_donut_cy = ram_y + ram_h // 2
    ram_donut_r = max(6, int(7 * scale))
    d.ellipse((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
               ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
              outline=colors["bar_bg"], width=max(2, int(3 * scale)))
    d.arc((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
           ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
          -90, -90 + int(360 * SYSTEM_STATS.get("ram_percent", 0) / 100),
          fill=colors["good"], width=max(2, int(3 * scale)))
    ram_graph_y = ram_y + ram_h - max(4, int(5 * scale))
    ram_graph_x2 = ram_donut_cx - ram_donut_r - max(4, int(5 * scale))
    d.line((inner_x + 5, ram_graph_y, ram_graph_x2, ram_graph_y),
           fill=colors["bar_bg"], width=line_width)
    ram_fill_w = int((ram_graph_x2 - inner_x - 5) *
                     max(0.0, min(100.0, SYSTEM_STATS.get("ram_percent", 0))) / 100.0)
    if ram_fill_w:
        d.line((inner_x + 5, ram_graph_y, inner_x + 5 + ram_fill_w, ram_graph_y),
               fill=colors["good"], width=max(2, line_width + 1))
    ram_usage_text = f"{SYSTEM_STATS.get('ram_percent', 0):.0f}%"
    ram_usage_w = get_text_width(d, ram_usage_text, font_mono)
    if ram_usage_w <= ram_donut_r * 1.6:      # never write over the ring
        text(ram_donut_cx - ram_usage_w / 2, ram_donut_cy - max(3, int(3 * scale)),
             ram_usage_text, font_mono, colors["text_main"])
    return img


def render_dashboard_planet(width, height, settings):
    """Render the Planet interface: orbital Earth plus compact telemetry."""
    if str(settings.get("orientation")).startswith("vertical") or height > width:
        # The main loop already swaps dimensions for portrait mode. This
        # fallback also handles direct callers that still pass landscape
        # dimensions together with orientation="vertical".
        portrait_width, portrait_height = ((width, height) if height >= width
                                            else (height, width))
        return render_dashboard_planet_portrait(portrait_width, portrait_height, settings)

    scale = max(0.58, min(width / 800.0, height / 480.0))
    colors = get_theme_colors("planet")
    img = Image.new("RGB", (width, height), colors["bg"])
    d = ImageDraw.Draw(img)
    font_dir = os.path.join(BASE_DIR, "fonts")

    def make_font(filename, size):
        try:
            return _FontCache.truetype(os.path.join(font_dir, filename), max(7, int(size)))
        except Exception:
            return _FontCache.load_default()

    font_title = make_font("DejaVuSans-Bold.ttf", 14 * scale)
    font_time = make_font("DejaVuSans-Bold.ttf", 29 * scale)
    font_medium = make_font("DejaVuSans-Bold.ttf", 14 * scale)
    font_small = make_font("DejaVuSans.ttf", 11 * scale)
    font_mono = make_font("DejaVuSans.ttf", 10 * scale)
    font_mono_bold = make_font("DejaVuSans-Bold.ttf", 10 * scale)

    line_width = max(1, int(scale))
    pad = max(5, int(8 * scale))
    radius = max(3, int(7 * scale))

    orbital_x = 7
    right_x = int(width * 0.56)
    right_w = width - right_x - 7
    orbital_w = right_x - orbital_x - 6
    left_x = orbital_x + pad
    # The former information and planet columns now share one uninterrupted
    # orbital canvas, allowing the globe to use almost all of its width.
    center_x = orbital_x
    center_w = orbital_w

    now_local = datetime.now()
    now_utc = datetime.now(timezone.utc)
    astronomy_utc = now_utc.replace(second=0, microsecond=0)
    julian_day = _planet_julian_day(astronomy_utc)
    sun_position = _planet_sun_position(astronomy_utc)
    moon_position = _planet_moon_position(astronomy_utc)
    sun_path = _planet_path(_planet_sun_position, astronomy_utc)
    moon_path = _planet_path(_planet_moon_position, astronomy_utc, step_minutes=120)
    # Earth rotation is tied to Greenwich sidereal time. It advances because
    # the clock advances, never because the renderer runs an animation timer.
    earth_phase = math.radians(_planet_sidereal_degrees(julian_day))
    moon_elongation = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1]))
    moon_illumination = (1.0 - math.cos(moon_elongation)) / 2.0
    # The icon helper expects zero to mean a fully sun-facing Moon.
    moon_light_phase = math.radians(
        _planet_normalize_longitude(moon_position[1] - sun_position[1] + 180.0))

    def panel(x, y, w, h, fill=colors["panel_bg"]):
        d.rounded_rectangle((x, y, x + w, y + h), radius=radius,
                            fill=fill, outline=colors["border"], width=line_width)

    def text(x, y, value, font=font_small, fill=colors["text_main"]):
        d.text((int(x), int(y)), str(value), font=font, fill=fill)

    def clipped(value, limit):
        value = str(value)
        return value if len(value) <= limit else value[:max(1, limit - 1)] + "…"

    def draw_line_bar(x, y, w, label, value, percent, history, color):
        bar_h = max(20, int(34 * scale))
        panel(x, y, w, bar_h, (5, 14, 31))
        text(x + 5, y + 3, label, font_mono_bold, colors["text_label"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + w - value_w - 5, y + 3, value, font_mono_bold, colors["text_main"])
        graph_y = y + bar_h - max(5, int(8 * scale))
        if history and len(history) > 1:
            max_value = max(1.0, max(abs(float(item)) for item in history))
            points = []
            for i, item in enumerate(history):
                px = x + 4 + ((w - 8) * i / (len(history) - 1))
                py = graph_y - min(1.0, abs(float(item)) / max_value) * max(3, int(7 * scale))
                points.append((px, py))
            d.line(points, fill=color, width=line_width)
        d.line((x + 5, graph_y, x + w - 5, graph_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((w - 10) * max(0.0, min(100.0, percent)) / 100.0)
        if fill_w:
            d.line((x + 5, graph_y, x + 5 + fill_w, graph_y), fill=color, width=max(2, line_width + 1))

    def metric_bar(x, y, w, label, value, percent, history, color):
        bar_h = max(30, int(58 * scale))
        panel(x, y, w, bar_h, (5, 14, 31))
        text(x + 5, y + 3, label, font_mono, colors["text_muted"])
        value_w = get_text_width(d, value, font_mono_bold)
        text(x + w - value_w - 5, y + 3, value, font_mono_bold, colors["text_main"])
        graph_top = y + int(bar_h * 0.53)
        graph_bottom = y + bar_h - 4
        d.line((x + 5, graph_bottom, x + w - 5, graph_bottom), fill=colors["bar_bg"], width=line_width)
        if history and len(history) > 1:
            maximum = max(1.0, max(abs(float(item)) for item in history))
            points = []
            for i, item in enumerate(history):
                px = x + 5 + ((w - 10) * i / (len(history) - 1))
                py = graph_bottom - (min(1.0, abs(float(item)) / maximum) * (graph_bottom - graph_top))
                points.append((px, py))
            d.line(points, fill=color, width=line_width)
        fill_w = int((w - 10) * max(0.0, min(100.0, percent)) / 100.0)
        if fill_w:
            d.line((x + 5, graph_bottom, x + 5 + fill_w, graph_bottom), fill=color, width=max(2, line_width + 1))

    def draw_temperature_gauge(x, y, w, h, label, value):
        panel(x, y, w, h, (5, 14, 31))
        numeric = _planet_temperature(value)
        ratio = max(0.0, min(1.0, (numeric or 0.0) / 100.0))
        track_x = x + w // 2 - max(2, int(3 * scale))
        track_top = y + int(h * 0.25)
        track_bottom = y + h - int(h * 0.15)
        d.rounded_rectangle((track_x - 2, track_top, track_x + max(4, int(6 * scale)), track_bottom),
                            radius=3, fill=colors["bar_bg"])
        fill_top = track_bottom - int((track_bottom - track_top) * ratio)
        if numeric is not None:
            temp_color = colors["crit"] if numeric >= 85 else (colors["warn"] if numeric >= 60 else colors["good"])
            d.rounded_rectangle((track_x - 2, fill_top, track_x + max(4, int(6 * scale)), track_bottom),
                                radius=3, fill=temp_color)
        value_text = f"{numeric:.0f}°" if numeric is not None else "--"
        value_w = get_text_width(d, value_text, font_medium)
        text(x + (w - value_w) // 2, y + 4, value_text, font_medium, colors["text_main"])
        label_w = get_text_width(d, label, font_mono)
        text(x + (w - label_w) // 2, y + h - int(13 * scale), label, font_mono, colors["text_muted"])

    # ORBITAL PANEL: information and the enlarged planet share one canvas.
    panel(orbital_x, 7, orbital_w, height - 14, (2, 8, 22))
    text(left_x, 11, "PLANET", font_title, colors["text_label"])
    text(left_x, 31, "SYSTEM ORBIT", font_mono, colors["text_muted"])
    time_y = max(30, int(50 * scale))
    date_y = max(52, int(87 * scale))
    weather_y = max(66, int(105 * scale))
    text(left_x, time_y, now_local.strftime("%H:%M:%S" if settings.get("planet_seconds", True) else "%H:%M"), font_time, colors["time"])
    text(left_x, date_y, now_local.strftime("%a, %Y-%m-%d"), font_small, colors["text_main"])
    text(left_x, weather_y, clipped(_planet_status_line(), 34), font_mono, colors["text_muted"])

    solar_x = orbital_x + int(orbital_w * 0.56)
    text(solar_x, 11, "SOLAR TRACK", font_medium, colors["text_label"])
    text(solar_x, 32, f"SUN  {sun_position[0]:+.1f}°  {sun_position[1]:+.1f}°", font_mono, (255, 190, 84))
    text(solar_x, 49, f"MOON {moon_position[0]:+.1f}°  {moon_position[1]:+.1f}°", font_mono, colors["text_main"])
    text(solar_x, 66, f"MOON LIGHT  {moon_illumination * 100:.0f}%", font_mono, colors["text_main"])

    # CENTER: stars, orbital rings and the clock-oriented Earth.
    star_top = max(int(weather_y + 14), int(80 * scale))
    star_bottom = int(height * 0.83)
    for index in range(42):
        sx = center_x + 8 + ((index * 47 + 19) % max(1, center_w - 16))
        sy = star_top + ((index * 31 + 11) % max(1, star_bottom - star_top))
        star_color = (42 + (index % 3) * 20, 91 + (index % 4) * 18, 132 + (index % 5) * 18)
        d.point((sx, sy), fill=star_color)

    planet_radius = int(min(center_w * 0.40, height * 0.30))
    planet_cx = center_x + center_w // 2
    planet_cy = int(height * 0.56)
    orbit_rx = planet_radius + max(12, int(16 * scale))
    orbit_ry = planet_radius + max(9, int(11 * scale))
    orbit_box = (planet_cx - orbit_rx, planet_cy - orbit_ry,
                 planet_cx + orbit_rx, planet_cy + orbit_ry)
    d.arc(orbit_box, 0, 360, fill=(31, 86, 126), width=line_width)
    moon_orbit_angle = math.radians(moon_position[1]) + earth_phase
    moon_orbit_x = planet_cx + orbit_rx * math.cos(moon_orbit_angle)
    moon_orbit_y = planet_cy + orbit_ry * math.sin(moon_orbit_angle)
    moon_arc = (179, 218, 238)
    if not settings.get("planet_show_moon", True):
        moon_orbit_x = moon_orbit_y = -1000      # sprite, outline and label fall outside the canvas
        moon_arc = (31, 86, 126)
    d.arc(orbit_box,
          math.degrees(moon_orbit_angle) - 22,
          math.degrees(moon_orbit_angle) + 22,
          fill=moon_arc, width=max(1, line_width + 1))
    d.ellipse((planet_cx - planet_radius - 5, planet_cy - planet_radius - 5,
               planet_cx + planet_radius + 5, planet_cy + planet_radius + 5),
              outline=(31, 120, 174), width=line_width)
    d.arc((planet_cx - planet_radius - 15, planet_cy - planet_radius // 2,
           planet_cx + planet_radius + 15, planet_cy + planet_radius // 2), 185, 355,
          fill=(66, 185, 241), width=line_width)
    globe = _planet_globe(planet_radius, earth_phase, sun_position, moon_position,
                          *_planet_paths(settings, sun_path, moon_path), **_planet_globe_options(settings))
    # Hide the square corners of the procedural globe with a circular mask.
    mask = Image.new("L", globe.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, globe.width - 1, globe.height - 1), fill=255)
    img.paste(globe, (planet_cx - planet_radius, planet_cy - planet_radius), mask)
    _PLANET_LAST_GLOBE[:] = [globe, (planet_cx - planet_radius, planet_cy - planet_radius), mask]
    d.ellipse((planet_cx - planet_radius, planet_cy - planet_radius,
               planet_cx + planet_radius, planet_cy + planet_radius),
              outline=(124, 222, 255), width=line_width)
    moon_radius = max(4, int(6 * scale))
    moon_sprite, moon_mask = _planet_moon_icon(moon_radius, moon_light_phase)
    img.paste(moon_sprite,
              (int(moon_orbit_x - moon_radius), int(moon_orbit_y - moon_radius)),
              moon_mask)
    d = ImageDraw.Draw(img)
    d.ellipse((moon_orbit_x - moon_radius - 1, moon_orbit_y - moon_radius - 1,
               moon_orbit_x + moon_radius + 1, moon_orbit_y + moon_radius + 1),
              outline=(235, 247, 255), width=line_width)
    moon_label = "MOON"
    moon_label_w = get_text_width(d, moon_label, font_mono)
    moon_label_x = moon_orbit_x + moon_radius + 3
    if moon_label_x + moon_label_w > center_x + center_w - pad:
        moon_label_x = moon_orbit_x - moon_radius - moon_label_w - 3
    text(moon_label_x, moon_orbit_y - 5, moon_label, font_mono, (226, 237, 255))
    orbital_footer_y = height - max(30, int(34 * scale))
    text(left_x, orbital_footer_y, f"SUN  {now_utc.strftime('%H:%M:%S')} UTC", font_mono_bold, (255, 190, 84))
    text(left_x, orbital_footer_y + max(13, int(16 * scale)),
         "TERMINATOR // LIVE  ·  MOON ORBIT", font_mono, colors["text_muted"])

    # RIGHT: telemetry is a dense, two-column dashboard so RAM, network and
    # all performance graphs use the full hardware panel.
    panel(right_x, 7, right_w, height - 14)
    gpu_list = SYSTEM_STATS.get("gpus", [])
    gpu_idx = min(SYSTEM_STATS.get("active_gpu_idx", 0), max(0, len(gpu_list) - 1))
    active_gpu = gpu_list[gpu_idx] if gpu_list else {}
    cpu_freq = None
    try:
        cpu_freq = psutil.cpu_freq().current
    except Exception:
        pass
    cpu_freq_text = f"{cpu_freq:.0f}M" if cpu_freq else "--"
    gpu_name = clipped(active_gpu.get("name", "GPU"), 20)
    cpu_name = clipped(_planet_cpu_model(), 20)
    gpu_usage = float(active_gpu.get("percent", 0.0) or 0.0)
    gpu_mem = float(active_gpu.get("mem_used_mb", 0) or 0)
    gpu_mem_total = float(active_gpu.get("mem_total_mb", 0) or 0)
    gpu_mem_percent = (gpu_mem / gpu_mem_total * 100.0) if gpu_mem_total else 0.0

    text(right_x + pad, 14, "HARDWARE TELEMETRY", font_title, colors["text_label"])
    hardware_x = right_x + pad
    hardware_w = right_w - pad * 2
    card_gap = max(4, int(6 * scale))
    card_w = max(45, (hardware_w - card_gap) // 2)
    card_h = max(44, int(70 * scale))
    cpu_card_y = max(30, int(41 * scale))
    gpu_card_x = hardware_x + card_w + card_gap

    def draw_hardware_card(x, y, label, model, temperature, load, accent):
        panel(x, y, card_w, card_h, (5, 14, 31))
        text(x + 7, y + 5, label, font_medium, colors["text_label"])
        numeric = _planet_temperature(temperature)
        temp_text = f"{numeric:.0f}°" if numeric is not None else "--"
        temp_w = get_text_width(d, temp_text, font_medium)
        temp_color = colors["crit"] if (numeric is not None and numeric >= 85) else (
            colors["warn"] if (numeric is not None and numeric >= 60) else colors["good"])
        text(x + card_w - temp_w - 7, y + 5, temp_text, font_medium, temp_color)
        model_limit = 20 if width >= 600 else 13
        text(x + 7, y + max(23, int(27 * scale)), clipped(model, model_limit),
             font_mono_bold, colors["text_main"])
        text(x + 7, y + card_h - max(17, int(20 * scale)),
             f"LOAD {load:.0f}%  ·  V  --  ·  P  --", font_mono, colors["text_muted"])
        track_y = y + card_h - max(5, int(7 * scale))
        d.line((x + 7, track_y, x + card_w - 7, track_y), fill=colors["bar_bg"], width=line_width)
        fill_w = int((card_w - 14) * max(0.0, min(100.0, load)) / 100.0)
        if fill_w:
            d.line((x + 7, track_y, x + 7 + fill_w, track_y), fill=accent,
                   width=max(2, line_width + 1))

    draw_hardware_card(hardware_x, cpu_card_y, "CPU", cpu_name,
                       SYSTEM_STATS.get("cpu_temp"), SYSTEM_STATS.get("cpu_percent", 0), colors["good"])
    draw_hardware_card(gpu_card_x, cpu_card_y, "GPU", gpu_name,
                       active_gpu.get("temp"), gpu_usage, colors["warn"])

    metric_gap = max(3, int(6 * scale))
    metric_cols = 2
    metric_w = max(30, (hardware_w - metric_gap) // metric_cols)
    metric_y = cpu_card_y + card_h + max(6, int(8 * scale))
    metric_h = max(34, int(66 * scale))
    metric_specs = [
        ("CPU USAGE", f"{SYSTEM_STATS.get('cpu_percent', 0):.0f}%", SYSTEM_STATS.get("cpu_percent", 0), CPU_USAGE_HISTORY, colors["good"]),
        ("CPU FREQ", cpu_freq_text, min(100.0, (cpu_freq or 0) / 40.0), [], colors["text_label"]),
        ("GPU USAGE", f"{gpu_usage:.0f}%", gpu_usage, GPU_USAGE_HISTORY, colors["warn"]),
        ("GPU CLOCK", _planet_gpu_clock(active_gpu), min(100.0, (active_gpu.get("clock_mhz") or 0) / 30.0), [],
         colors["vram"]),
        ("MEM USED", f"{gpu_mem:.0f}M" if gpu_mem else "--", gpu_mem_percent, GPU_MEM_HISTORY, colors["vram"]),
        ("RAM USAGE", f"{SYSTEM_STATS.get('ram_percent', 0):.0f}%",
         SYSTEM_STATS.get("ram_percent", 0), RAM_USAGE_HISTORY, colors["good"]),
    ]
    for index, (label, value, percent, history, color) in enumerate(metric_specs):
        metric_column = index % metric_cols
        metric_row = index // metric_cols
        metric_bar(hardware_x + metric_column * (metric_w + metric_gap),
                   metric_y + metric_row * (metric_h + metric_gap), metric_w,
                   label, value, percent, history, color)

    metric_rows = (len(metric_specs) + metric_cols - 1) // metric_cols
    network_y = metric_y + metric_rows * (metric_h + metric_gap) + max(4, int(6 * scale))
    net_up = max(0.0, SYSTEM_STATS.get("net_tx_mbps", 0.0) * 125.0)
    net_down = max(0.0, SYSTEM_STATS.get("net_rx_mbps", 0.0) * 125.0)
    def network_value(value):
        return f"{value:.0f}K" if width < 600 else f"{value:.0f} KB/s"
    network_specs = [
        ("DISK", f"{SYSTEM_STATS.get('disk_percent', 0):.0f}%", SYSTEM_STATS.get("disk_percent", 0), [],
         colors["good"]),
        ("NET/U", network_value(net_up), min(100.0, net_up / 10.0), NET_TX_HISTORY, colors["text_label"]),
        ("NET/D", network_value(net_down), min(100.0, net_down / 10.0), NET_RX_HISTORY, colors["swap"]),
    ]
    network_gap = max(3, int(5 * scale))
    network_w = (hardware_w - network_gap * 2) // 3
    for index, (label, value, percent, history, color) in enumerate(network_specs):
        draw_line_bar(hardware_x + index * (network_w + network_gap), network_y,
                      network_w, label, value, percent, history, color)

    # RAM is intentionally the last full-width card in Hardware Telemetry.
    network_h = max(20, int(34 * scale))
    ram_y = network_y + network_h + max(4, int(6 * scale))
    ram_h = max(43, int(64 * scale))
    panel(hardware_x, ram_y, hardware_w, ram_h, (5, 14, 31))
    text(hardware_x + 7, ram_y + 5, "RAM", font_medium, colors["text_label"])
    text(hardware_x + 7, ram_y + max(21, int(24 * scale)),
         f"{SYSTEM_STATS.get('ram_total_mb', 0) / 1024:.1f} GB TOTAL",
         font_mono, colors["text_main"])
    text(hardware_x + 7, ram_y + max(31, int(43 * scale)),
         f"{SYSTEM_STATS.get('ram_used_mb', 0) / 1024:.1f} G USED",
         font_mono_bold, colors["good"])
    ram_donut_cx = hardware_x + hardware_w - max(25, int(31 * scale))
    ram_donut_cy = ram_y + ram_h // 2
    ram_donut_r = max(10, int(20 * scale))
    d.ellipse((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
               ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
              outline=colors["bar_bg"], width=max(3, int(5 * scale)))
    d.arc((ram_donut_cx - ram_donut_r, ram_donut_cy - ram_donut_r,
           ram_donut_cx + ram_donut_r, ram_donut_cy + ram_donut_r),
          -90, -90 + int(360 * SYSTEM_STATS.get("ram_percent", 0) / 100),
          fill=colors["good"], width=max(3, int(5 * scale)))
    ram_usage_text = f"{SYSTEM_STATS.get('ram_percent', 0):.0f}%"
    ram_usage_w = get_text_width(d, ram_usage_text, font_mono_bold)
    text(ram_donut_cx - ram_usage_w / 2, ram_donut_cy - 4 * scale,
         ram_usage_text, font_mono_bold, colors["text_main"])

    return img


OC_PALETTES = {
    "classic": {"face": (192, 192, 192), "hilight": (255, 255, 255), "light": (224, 224, 224),
                "shadow": (128, 128, 128), "text": (64, 64, 64), "title": (0, 0, 128), "plot_bg": (0, 0, 0),
                "plot": (0, 205, 0), "grid": (0, 90, 0)},
    "slate": {"face": (56, 60, 68), "hilight": (100, 106, 118), "light": (78, 84, 96), "shadow": (30, 32, 38),
              "text": (214, 218, 226), "title": (70, 140, 220), "plot_bg": (6, 10, 14), "plot": (90, 210, 255),
              "grid": (18, 60, 80)},
    "amber": {"face": (214, 204, 180), "hilight": (250, 244, 228), "light": (232, 224, 204),
              "shadow": (150, 140, 118), "text": (62, 48, 34), "title": (128, 26, 24), "plot_bg": (16, 10, 4),
              "plot": (255, 176, 0), "grid": (90, 60, 0)},
    "plum": {"face": (200, 190, 214), "hilight": (242, 236, 250), "light": (222, 214, 234),
             "shadow": (130, 118, 150), "text": (54, 40, 72), "title": (94, 40, 130), "plot_bg": (10, 6, 16),
             "plot": (200, 120, 255), "grid": (60, 30, 90)},
}


def render_dashboard_old_computer(width, height, settings):
    """Render a functional mid-2000s desktop-monitor window.

    The layout intentionally uses the visual language of a classic gray
    system window: navy title bars, beveled borders, bitmap-like labels and
    black diagnostic plots with green traces. All values and traces come from
    the same live statistics used by the other themes.
    """
    if str(settings.get("orientation")).startswith("vertical") and width > height:
        width, height = height, width

    portrait = height > width
    if portrait:
        scale = max(0.72, min(width / 320.0, height / 480.0))
    else:
        scale = max(0.55, min(width / 1024.0, height / 480.0))

    colors = get_theme_colors("old_computer")
    os_info = get_os_release()
    distro_name = os_info.get("NAME") or os_info.get("PRETTY_NAME") or "Linux"
    gray = colors["bg"]
    white = (255, 255, 255)
    light_gray = (224, 224, 224)
    mid_gray = (128, 128, 128)
    dark_gray = (64, 64, 64)
    navy = colors["text_label"]
    black = (0, 0, 0)
    graph_green = colors["good"]
    graph_grid = (0, 90, 0)
    palette = OC_PALETTES.get(settings.get("oc_scheme", "classic"))
    if palette:
        gray, white, light_gray, mid_gray, dark_gray, navy, black, graph_green, graph_grid = (
            palette[key] for key in ("face", "hilight", "light", "shadow", "text", "title", "plot_bg", "plot",
                                     "grid"))

    img = Image.new("RGB", (width, height), gray)
    d = ImageDraw.Draw(img)
    font_dir = os.path.join(BASE_DIR, "fonts")

    def make_font(filename, size):
        try:
            return _FontCache.truetype(os.path.join(font_dir, filename), max(7, int(size)))
        except Exception:
            return _FontCache.load_default()

    if portrait:
        title_font = make_font("DejaVuSans-Bold.ttf", 18 * scale)
        percent_font = make_font("DejaVuSans-Bold.ttf", 24 * scale)
        model_font = make_font("DejaVuSans-Bold.ttf", 10 * scale)
        small_bold = make_font("DejaVuSans-Bold.ttf", 8.5 * scale)
        small_font = make_font("DejaVuSans.ttf", 8 * scale)
        header_font = make_font("DejaVuSans-Bold.ttf", 16 * scale)
        time_font = make_font("DejaVuSans-Bold.ttf", 21 * scale)
        titlebar_font = make_font("DejaVuSans-Bold.ttf", 10 * scale)
    else:
        title_font = make_font("DejaVuSans-Bold.ttf", 42 * scale)
        percent_font = make_font("DejaVuSans-Bold.ttf", 46 * scale)
        model_font = make_font("DejaVuSans-Bold.ttf", 19 * scale)
        small_bold = make_font("DejaVuSans-Bold.ttf", 15 * scale)
        small_font = make_font("DejaVuSans.ttf", 13 * scale)
        header_font = make_font("DejaVuSans-Bold.ttf", 27 * scale)
        time_font = make_font("DejaVuSans-Bold.ttf", 28 * scale)
        titlebar_font = make_font("DejaVuSans-Bold.ttf", 13 * scale)

    def text(x, y, value, font, fill=dark_gray):
        d.text((int(x), int(y)), str(value), font=font, fill=fill)

    def classic_frame(x, y, w, h, fill=gray):
        """Draw the raised gray bevel used by classic desktop windows."""
        x, y, w, h = int(x), int(y), int(w), int(h)
        d.rectangle((x, y, x + w, y + h), fill=fill, outline=dark_gray, width=1)
        if w > 3 and h > 3:
            d.line((x + 1, y + 1, x + w - 1, y + 1), fill=white, width=1)
            d.line((x + 1, y + 1, x + 1, y + h - 1), fill=white, width=1)
            d.line((x + w - 1, y + 2, x + w - 1, y + h - 1), fill=mid_gray, width=1)
            d.line((x + 2, y + h - 1, x + w - 1, y + h - 1), fill=mid_gray, width=1)

    def graph_frame(x, y, w, h, history, current, line_color=graph_green):
        """Draw a black monitor plot with live history and green grid lines."""
        classic_frame(x, y, w, h, black)
        left, top = x + 10, y + 8
        right, bottom = x + w - 10, y + h - 8
        if right <= left or bottom <= top:
            return
        for fraction in (0.25, 0.50, 0.75):
            gy = int(top + (bottom - top) * fraction)
            d.line((left, gy, right, gy), fill=graph_grid, width=1)

        values = [float(item) for item in list(history or [])[-30:]]
        if values:
            values.append(float(current or 0.0))
        else:
            values = [float(current or 0.0)]
        values = values[-31:]
        points = []
        for index, value in enumerate(values):
            normalized = max(0.0, min(100.0, value)) / 100.0
            px = left + (right - left) * index / max(1, len(values) - 1)
            py = bottom - normalized * (bottom - top)
            points.append((int(px), int(py)))
        if len(points) == 1:
            points = [(left, points[0][1]), (right, points[0][1])]
        d.line(points, fill=line_color, width=max(1, int(scale)))
        last_x, last_y = points[-1]
        marker = max(1, int(scale))
        d.rectangle((last_x - marker, last_y - marker, last_x + marker, last_y + marker),
                    fill=line_color)

    def draw_icon(kind, x, y, size):
        """Small pixel-style hardware icons matching the reference image."""
        size = max(22, int(size))   # the drawings use a few fixed insets; below 20 px they inverted
        x, y = int(x), int(y)
        shadow = (128, 128, 0)
        chip = (224, 224, 224)
        blue = (0, 0, 128)
        if kind == "cpu":
            for offset in range(4, size - 3, max(5, size // 5)):
                d.line((x + offset, y, x + offset, y - 5), fill=shadow, width=2)
                d.line((x + offset, y + size, x + offset, y + size + 5), fill=shadow, width=2)
                d.line((x, y + offset, x - 5, y + offset), fill=shadow, width=2)
                d.line((x + size, y + offset, x + size + 5, y + offset), fill=shadow, width=2)
            d.rectangle((x, y, x + size, y + size), fill=shadow, outline=black, width=1)
            # Insets scale with the icon (fixed 12 px insets crashed below 24 px).
            for inset, fill, outline in ((size // 7, chip, dark_gray), (size * 9 // 28, blue, black),
                                         (size * 3 // 7, (32, 32, 80), None)):
                if size - 2 * inset > 1:
                    d.rectangle((x + inset, y + inset, x + size - inset, y + size - inset), fill=fill,
                                outline=outline)
        elif kind == "ram":
            d.rectangle((x, y + size // 4, x + size + 8, y + size * 3 // 4), fill=shadow, outline=black)
            d.rectangle((x + 4, y + size // 4 + 3, x + size + 4, y + size * 3 // 4 - 3), fill=chip)
            for index in range(3):
                bx = x + 8 + index * max(5, size // 4)
                d.rectangle((bx, y + size // 4 + 5, bx + max(3, size // 7),
                             y + size * 3 // 4 - 5), fill=blue)
            d.line((x + 5, y + size * 3 // 4 + 3, x + size + 3, y + size * 3 // 4 + 3),
                   fill=shadow, width=2)
        elif kind == "gpu":
            d.rectangle((x, y + 3, x + size + 8, y + size - 2), fill=chip, outline=black)
            cx, cy = x + (size + 8) // 2, y + size // 2
            d.ellipse((cx - size // 3, cy - size // 3, cx + size // 3, cy + size // 3), fill=black)
            d.ellipse((cx - size // 8, cy - size // 8, cx + size // 8, cy + size // 8), fill=white)
            d.line((x + 4, y + size, x + size + 5, y + size), fill=shadow, width=2)
        elif kind == "disk":
            d.rectangle((x, y + size // 4, x + size + 6, y + size * 3 // 4 + 2), fill=chip, outline=black)
            d.line((x + 3, y + size // 2, x + size - 2, y + size // 2), fill=mid_gray, width=1)
            d.rectangle((x + size, y + size // 2 + 2, x + size + 3, y + size // 2 + 4), fill=graph_green)
        elif kind == "swap":
            mid = y + size // 2
            d.polygon([(x, mid - 2), (x + size // 2, y + 2), (x + size // 2, mid - 2)], fill=blue)
            d.rectangle((x + size // 2, mid - size // 6 - 2, x + size, mid - 2), fill=blue)
            d.polygon([(x + size + 4, mid + 2), (x + size // 2 + 4, y + size - 2), (x + size // 2 + 4, mid + 2)],
                      fill=shadow)
            d.rectangle((x + 4, mid + 2, x + size // 2 + 4, mid + size // 6 + 2), fill=shadow)
        else:  # VRAM
            for index in range(3):
                yy = y + index * max(5, size // 4)
                d.rectangle((x + 5, yy + 3, x + size, yy + max(7, size // 4)), fill=blue, outline=black)
            d.rectangle((x + 2, y + size - 2, x + size + 2, y + size + 3), fill=shadow, outline=black)

    def series_stats(history, current):
        values = [float(item) for item in list(history or []) if item is not None]
        if current is not None:
            values.append(float(current))
        values = values or [0.0]
        return sum(values) / len(values), max(values)

    def safe_temperature(value):
        numeric = _planet_temperature(value)
        return f"{numeric:.0f}C" if numeric is not None else "--C"

    def format_uptime():
        try:
            elapsed = max(0, int(time.time() - psutil.boot_time()))
            days, remainder = divmod(elapsed, 86400)
            hours, minutes = divmod(remainder, 3600)
            minutes //= 60
            return f"{days}d {hours:02d}:{minutes:02d}" if days else f"{hours:02d}:{minutes:02d}"
        except Exception:
            return "--:--"

    gpu_list = SYSTEM_STATS.get("gpus", [])
    gpu_index = min(SYSTEM_STATS.get("active_gpu_idx", 0), max(0, len(gpu_list) - 1))
    gpu = gpu_list[gpu_index] if gpu_list else {}
    cpu_usage = float(SYSTEM_STATS.get("cpu_percent", 0.0) or 0.0)
    ram_usage = float(SYSTEM_STATS.get("ram_percent", 0.0) or 0.0)
    gpu_usage = float(gpu.get("percent", 0.0) or 0.0)
    gpu_mem = float(gpu.get("mem_used_mb", 0.0) or 0.0)
    gpu_mem_total = float(gpu.get("mem_total_mb", 0.0) or 0.0)
    gpu_mem_percent = (gpu_mem / gpu_mem_total * 100.0) if gpu_mem_total else 0.0
    cpu_freq = None
    try:
        cpu_freq = psutil.cpu_freq().current
    except Exception:
        pass
    cpu_freq_text = f"{cpu_freq:.0f}MHz" if cpu_freq else "--MHz"
    cpu_model = _planet_cpu_model()
    gpu_model = str(gpu.get("name", "GPU"))
    ram_total_gb = SYSTEM_STATS.get("ram_total_mb", 0) / 1024.0
    ram_used_gb = SYSTEM_STATS.get("ram_used_mb", 0) / 1024.0
    vram_total_gb = gpu_mem_total / 1024.0
    vram_used_gb = gpu_mem / 1024.0
    cpu_avg, cpu_peak = series_stats(CPU_USAGE_HISTORY, cpu_usage)
    ram_avg, ram_peak = series_stats(RAM_USAGE_HISTORY, ram_usage)
    gpu_avg, gpu_peak = series_stats(GPU_USAGE_HISTORY, gpu_usage)
    vram_avg, vram_peak = series_stats(GPU_MEM_HISTORY, gpu_mem_percent)

    # Window chrome and header.
    titlebar_h = max(18, int(height * (0.045 if portrait else 0.052))) if settings.get("oc_titlebar", True) else 0
    if titlebar_h:
        d.rectangle((0, 0, width - 1, titlebar_h), fill=navy)
    titlebar_left = max(4, int(5 * scale))
    button_size = max(11, titlebar_h - 7)
    button_y = max(3, (titlebar_h - button_size) // 2)
    button_x = width - max(4, int(5 * scale)) - button_size
    first_button_x = button_x
    titlebar_name = fit_text_to_width(d, distro_name, max(24, first_button_x - titlebar_left - 6), titlebar_font)
    if titlebar_h:
        text(titlebar_left, max(2, int(3 * scale)), titlebar_name, titlebar_font, white)
    for symbol in (("X", "□", "—") if titlebar_h else ()):
        classic_frame(button_x, button_y, button_size, button_size, light_gray)
        symbol_w = get_text_width(d, symbol, titlebar_font)
        text(button_x + (button_size - symbol_w) // 2, button_y - 1, symbol, titlebar_font, black)
        button_x -= button_size + max(2, int(3 * scale))

    if portrait:
        content_pad = max(7, int(9 * scale))
        header_h = max(48, int(54 * scale))
        header_x = content_pad
        header_y = titlebar_h + max(5, int(5 * scale))
        header_title_y = header_y + 2
        header_subtitle_y = header_y + max(20, int(22 * scale))
        time_y = header_y + max(1, int(1 * scale))
        status_h = max(22, int(24 * scale))
    else:
        content_pad = max(12, int(width * 0.02))
        header_h = max(58, int(height * 0.17))
        header_x = max(content_pad * 3, int(width * 0.07))
        header_y = titlebar_h + max(10, int(height * 0.035))
        header_title_y = header_y
        header_subtitle_y = header_y + max(22, int(24 * scale))
        time_y = header_y + max(1, int(1 * scale))
        status_h = max(24, int(height * 0.06))

    if not settings.get("oc_statusbar", True):
        status_h = 0
    now = datetime.now()
    time_value = now.strftime("%H:%M:%S" if settings.get("oc_seconds", False) else "%H:%M")
    time_w = get_text_width(d, time_value, time_font)
    header_name_width = max(20, width - header_x - content_pad - time_w - max(8, int(10 * scale)))
    text(header_x, header_title_y, fit_text_to_width(d, distro_name, header_name_width, header_font), header_font, navy)
    subtitle = (f"KERNEL {SYSTEM_STATS.get('kernel', '--')}  |  "
                f"HOST {SYSTEM_STATS.get('hostname', '--')}  |  UPTIME {format_uptime()}")
    text(header_x, header_subtitle_y,
         fit_text_to_width(d, subtitle, max(20, width - header_x - content_pad), small_bold),
         small_bold, dark_gray)
    text(width - content_pad - time_w, time_y, time_value, time_font, navy)
    if not portrait:
        date_value = now.strftime("%Y-%m-%d")
        date_w = get_text_width(d, date_value, small_font)
        text(width - content_pad - date_w, time_y + max(29, int(31 * scale)), date_value, small_font, dark_gray)

    separator_y = titlebar_h + header_h
    d.line((content_pad, separator_y, width - content_pad, separator_y), fill=navy, width=max(1, int(scale)))

    graph_data = [
        ("CPU", cpu_usage, cpu_model, CPU_USAGE_HISTORY, f"CLOCK {cpu_freq_text}  |  AVG {cpu_avg:.0f}%  PEAK {cpu_peak:.0f}%", "cpu"),
        ("RAM", ram_usage, f"{ram_total_gb:.1f}GB DDR  MEMORY", RAM_USAGE_HISTORY,
         f"{ram_used_gb:.1f}/{ram_total_gb:.1f}GB  |  AVG {ram_avg:.0f}%  PEAK {ram_peak:.0f}%", "ram"),
    ]
    if settings.get("oc_show_gpu", True) and gpu.get("path"):
        gpu_clock = f"{gpu['clock_mhz']}MHz" if gpu.get("clock_mhz") else "--MHz"
        graph_data += [
            ("GPU", gpu_usage, gpu_model, GPU_USAGE_HISTORY,
             f"CLOCK {gpu_clock}  |  TEMP {safe_temperature(gpu.get('temp'))}  |  AVG {gpu_avg:.0f}%  PEAK {gpu_peak:.0f}%",
             "gpu"),
            ("VRAM", gpu_mem_percent, gpu_model, GPU_MEM_HISTORY,
             f"{vram_used_gb:.1f}/{vram_total_gb:.1f}GB  |  AVG {vram_avg:.0f}%  PEAK {vram_peak:.0f}%", "vram"),
        ]
    if settings.get("oc_show_storage", False):
        disk_percent = float(SYSTEM_STATS.get("disk_percent", 0.0) or 0.0)
        swap_percent = float(SYSTEM_STATS.get("swap_percent", 0.0) or 0.0)
        disk_used, disk_total = SYSTEM_STATS.get("disk_used_gb") or 0, SYSTEM_STATS.get("disk_total_gb") or 0
        graph_data += [
            ("DISK", disk_percent, "ROOT FILESYSTEM /", [disk_percent] * 30,
             f"{disk_used:.0f}/{disk_total:.0f}GB  |  I/O {SYSTEM_STATS.get('disk_io_kbs', 0) / 1024:.1f}MB/S", "disk"),
            ("SWAP", swap_percent, "VIRTUAL MEMORY", [swap_percent] * 30,
             f"{SYSTEM_STATS.get('swap_used_mb', 0) / 1024:.1f}/{SYSTEM_STATS.get('swap_total_mb', 0) / 1024:.1f}GB",
             "swap"),
        ]

    def draw_card(x, y, w, h, label, percent, model, history, footer, icon_kind):
        classic_frame(x, y, w, h, gray)
        if portrait:
            icon_size = max(18, min(27, int(h * 0.27)))
            head_h = max(32, int(h * 0.39))
            footer_h = max(13, int(15 * scale))
        else:
            icon_size = max(25, min(43, int(h * 0.25)))
            head_h = max(56, int(h * 0.43))
            footer_h = max(17, int(18 * scale))
        icon_x = x + max(8, int(12 * scale))
        icon_y = y + max(7, int(13 * scale))
        draw_icon(icon_kind, icon_x, icon_y, icon_size)
        title_x = icon_x + icon_size + max(8, int(12 * scale))
        text(title_x, y + max(4, int(7 * scale)), label, title_font, navy)
        percent_text = f"{percent:.0f}%"
        percent_w = get_text_width(d, percent_text, percent_font)
        text(x + w - percent_w - max(9, int(12 * scale)), y + max(4, int(6 * scale)), percent_text, percent_font, navy)
        graph_y = y + head_h
        if h - head_h - footer_h - max(5, int(7 * scale)) < 18:
            footer_h = 0          # short card: keep the graph, drop the footer line
        graph_h = max(8, h - head_h - footer_h - max(5, int(7 * scale)))
        model_text = fit_text_to_width(d, str(model).upper(), w - max(20, int(24 * scale)), model_font)
        model_box = d.textbbox((0, 0), model_text, font=model_font)
        model_h = max(7, model_box[3] - model_box[1])
        model_y = graph_y - model_h - max(2, int(4 * scale))
        title_bottom = y + max(4, int(7 * scale)) + title_font.getbbox(label)[3]
        if model_y >= title_bottom:        # only when it does not touch the title
            text(title_x, model_y, model_text, model_font, dark_gray)
        graph_frame(x + max(8, int(12 * scale)), graph_y,
                    w - max(16, int(24 * scale)), graph_h, history, percent)
        if footer_h:
            footer_text = fit_text_to_width(d, footer, w - max(18, int(24 * scale)), small_bold)
            text(x + max(10, int(13 * scale)), y + h - footer_h + max(1, int(1 * scale)), footer_text, small_bold,
                 dark_gray)

    status_y = height - status_h
    card_top = separator_y + max(5, int(6 * scale))
    card_bottom = status_y - max(5, int(6 * scale))
    columns = 1 if portrait else 2
    rows = -(-len(graph_data) // columns)
    card_gap = max(3, int(4 * scale)) if portrait else max(5, int(8 * scale))
    card_w = max(60, (width - content_pad * 2 - card_gap * (columns - 1)) // columns)
    card_h = max(40, (card_bottom - card_top - card_gap * (rows - 1)) // rows)
    for index, card in enumerate(graph_data):
        col, row = index % columns, index // columns
        draw_card(content_pad + col * (card_w + card_gap),
                  card_top + row * (card_h + card_gap), card_w, card_h, *card)

    try:
        process_count = len(psutil.pids())
    except Exception:
        process_count = len(SYSTEM_STATS.get("procs", []))
    sensor_ok = _planet_temperature(SYSTEM_STATS.get("cpu_temp")) is not None
    sensor_status = "OK" if sensor_ok else "CHECK"
    status = (f"GRAPH  |  POLL 1.0S  |  HISTORY 30S  |  SENSORS {sensor_status}  |  "
              f"PROCESSES {process_count}")
    if not status_h:
        return img
    d.rectangle((content_pad, status_y, width - content_pad, height - 1), fill=gray)
    d.line((content_pad, status_y, width - content_pad, status_y), fill=white, width=1)
    d.line((content_pad, height - 1, width - content_pad, height - 1), fill=mid_gray, width=1)
    text(content_pad + max(4, int(8 * scale)), status_y + max(3, int(4 * scale)),
         fit_text_to_width(d, status, width - content_pad * 2 - max(8, int(16 * scale)), small_bold),
         small_bold, navy)
    return img
