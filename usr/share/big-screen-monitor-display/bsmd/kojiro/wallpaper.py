"""Wallpaper layer: built-in procedural art, imported images, fit and adjustments.

Built-in wallpapers are generated (original artwork, no third-party files)
at the panel's aspect ratio, so they never need cropping. Imported images
live in the managed store (``bsmd.kojiro.store``), never in a home folder
the service cannot read. Everything is cached per (settings, size); the
service re-processes the wallpaper only when something about it changes.
"""

import collections
import functools
import math
import random

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .draw import font, rgb

_CACHE = collections.OrderedDict()
CACHE_SIZE = 4


def _cached(key, build):
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    value = build()
    _CACHE[key] = value
    while len(_CACHE) > CACHE_SIZE:
        _CACHE.popitem(last=False)
    return value


def clear_cache():
    _CACHE.clear()
    _generated.cache_clear()
    _user_image.cache_clear()


# ---------------------------------------------------------------- helpers

def _gradient(width, height, stops, vertical=True):
    """Multi-stop linear gradient [(position 0..1, (r, g, b))]."""
    length = height if vertical else width
    t = np.linspace(0, 1, length)
    channels = []
    positions = [p for p, _c in stops]
    for c in range(3):
        channels.append(np.interp(t, positions, [col[c] for _p, col in stops]))
    line = np.stack(channels, axis=1).astype(np.uint8)
    if vertical:
        array = np.repeat(line[:, None, :], width, axis=1)
    else:
        array = np.repeat(line[None, :, :], height, axis=0)
    return Image.fromarray(array, "RGB")


def _noise(width, height, amount, seed):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.normal(128, amount, (height, width)).clip(0, 255).astype(np.uint8), "L")


def _add_noise(image, amount, seed):
    noise = _noise(image.width, image.height, amount, seed).convert("RGB")
    return ImageChops.add(image, ImageChops.subtract(noise, Image.new("RGB", image.size, (128, 128, 128))), 1, 0)


def _glow_layer(size, draw_fn, blur):
    """Draw on a half-size layer, blur it and scale back (cheap large glows)."""
    w, h = max(1, size[0] // 2), max(1, size[1] // 2)
    layer = Image.new("RGB", (w, h), (0, 0, 0))
    draw_fn(ImageDraw.Draw(layer), 0.5)
    return layer.filter(ImageFilter.GaussianBlur(max(1, blur / 2))).resize(size, Image.Resampling.BILINEAR)


def _windows(draw, x0, x1, top, bottom, rng, palette, density, scale):
    step = max(3, int(7 * scale))
    for wx in range(int(x0) + step // 2, int(x1) - step // 2, step):
        for wy in range(int(top) + step, int(bottom) - step, step):
            if rng.random() < density:
                color = rng.choice(palette)
                draw.rectangle((wx, wy, wx + max(1, step // 3), wy + max(1, step // 3)), fill=color)


# ---------------------------------------------------------------- built-in art

def cyberpunk(width, height, seed=7):
    rng = random.Random(seed)
    s = height / 480
    horizon = int(height * 0.64)
    image = _gradient(width, height, [(0, (6, 3, 22)), (0.45, (32, 9, 58)), (0.64, (18, 26, 70)),
                                       (0.65, (10, 6, 26)), (1, (4, 3, 12))])
    # Distant glow on the horizon and the portal halo.
    cx, cy, radius = width * 0.5, height * 0.42, height * 0.24

    def halo(draw, f):
        draw.ellipse(((cx - radius * 1.25) * f, (cy - radius * 1.25) * f, (cx + radius * 1.25) * f,
                      (cy + radius * 1.25) * f), outline=(240, 68, 219), width=int(26 * s * f))
        draw.ellipse(((cx - radius) * f, (cy - radius) * f, (cx + radius) * f, (cy + radius) * f),
                     outline=(66, 232, 255), width=int(18 * s * f))
        draw.rectangle((0, (horizon - 30 * s) * f, width * f, (horizon + 8 * s) * f), fill=(150, 40, 170))
    image = ImageChops.add(image, _glow_layer(image.size, halo, 40 * s))
    draw = ImageDraw.Draw(image)
    # Far skyline.
    x = 0
    while x < width:
        bw = rng.randint(int(18 * s), int(46 * s))
        bh = rng.randint(int(30 * s), int(120 * s))
        draw.rectangle((x, horizon - bh, x + bw, horizon), fill=(22, 14, 44))
        _windows(draw, x, x + bw, horizon - bh, horizon, rng, [(70, 60, 130), (120, 60, 140)], 0.18, s)
        x += bw + rng.randint(0, int(6 * s))
    # Portal: crisp rings and a central tower.
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=(150, 245, 255), width=max(2, int(4 * s)))
    r2 = radius * 1.25
    draw.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), outline=(255, 140, 240), width=max(1, int(2 * s)))
    tower_w = radius * 0.32
    draw.polygon([(cx - tower_w, horizon), (cx - tower_w * 0.45, cy - radius * 0.9), (cx + tower_w * 0.45,
                                                                                         cy - radius * 0.9),
                  (cx + tower_w, horizon)], fill=(14, 10, 30))
    for i in range(9):
        y = cy - radius * 0.8 + i * (horizon - cy + radius * 0.8) / 9
        span = tower_w * (0.45 + 0.55 * (y - (cy - radius * 0.9)) / (horizon - cy + radius * 0.9))
        draw.line((cx - span * 0.8, y, cx + span * 0.8, y), fill=(66, 232, 255) if i % 2 else (240, 68, 219),
                  width=max(1, int(2 * s)))
    # Near buildings, taller at the sides (frame the centre).
    x = 0
    while x < width:
        edge = min(x, width - x) / (width / 2)
        bw = rng.randint(int(30 * s), int(70 * s))
        bh = int((1 - edge) * rng.randint(int(150 * s), int(260 * s)) + rng.randint(int(20 * s), int(60 * s)))
        top = horizon - bh
        draw.rectangle((x, top, x + bw, horizon), fill=(9, 7, 20))
        draw.line((x, top, x + bw, top), fill=(66, 232, 255) if rng.random() < 0.5 else (240, 68, 219), width=1)
        _windows(draw, x + 2, x + bw - 2, top, horizon, rng,
                 [(66, 232, 255), (240, 68, 219), (255, 217, 74), (40, 60, 90)], 0.22, s)
        x += bw
    # Metal beams from the corners.
    for side in (0, 1):
        x0 = 0 if side == 0 else width
        for k in range(3):
            y0 = height * (0.08 + 0.1 * k)
            x1 = width * (0.22 if side == 0 else 0.78)
            draw.line((x0, y0, x1, y0 + height * 0.05), fill=(40, 44, 70), width=max(2, int(5 * s)))
            draw.line((x0, y0 - 2 * s, x1, y0 + height * 0.05 - 2 * s), fill=(90, 100, 140), width=1)
    # Perspective floor grid.
    floor = Image.new("RGB", image.size, (0, 0, 0))
    fdraw = ImageDraw.Draw(floor)
    for i in range(-14, 15):
        fdraw.line((cx + i * width * 0.02, horizon, cx + i * width * 0.16, height), fill=(150, 40, 170), width=1)
    y, gap = horizon, 4 * s
    while y < height:
        fdraw.line((0, y, width, y), fill=(40, 150, 190), width=1)
        gap *= 1.35
        y += gap
    image = ImageChops.add(image, floor.filter(ImageFilter.GaussianBlur(0.6)))
    image = ImageChops.add(image, floor.filter(ImageFilter.GaussianBlur(4 * s)))
    # Light streaks.
    for _ in range(5):
        y = rng.uniform(height * 0.1, horizon - 20 * s)
        x0 = rng.uniform(0, width * 0.7)
        draw = ImageDraw.Draw(image)
        draw.line((x0, y, x0 + rng.uniform(40, 160) * s, y), fill=rng.choice([(66, 232, 255), (240, 68, 219)]), width=1)
    return _add_noise(image, 6, seed)


def neon_grid(width, height, seed=3):
    s = height / 480
    horizon = int(height * 0.58)
    image = _gradient(width, height, [(0, (12, 4, 32)), (0.4, (60, 12, 80)), (0.58, (230, 90, 120)),
                                       (0.581, (12, 4, 28)), (1, (4, 2, 10))])
    draw = ImageDraw.Draw(image)
    cx, radius = width / 2, height * 0.22
    sun = _gradient(int(radius * 2), int(radius * 2), [(0, (255, 225, 90)), (1, (240, 60, 170))])
    mask = Image.new("L", sun.size, 0)
    mdraw = ImageDraw.Draw(mask)
    mdraw.ellipse((0, 0, sun.width - 1, sun.height - 1), fill=255)
    for i in range(6):
        y = sun.height * (0.55 + i * 0.075)
        mdraw.rectangle((0, y, sun.width, y + sun.height * 0.012 * (i + 1)), fill=0)
    image.paste(sun, (int(cx - radius), int(horizon - radius * 1.55)), mask)
    rng = random.Random(seed)
    points, x = [(0, horizon)], 0
    while x < width:
        x += rng.uniform(30, 90) * s
        points.append((x, horizon - rng.uniform(10, 70) * s * (1.4 - abs(x - cx) / width)))
    points += [(width, horizon)]
    draw.polygon(points, fill=(30, 8, 50))
    grid = Image.new("RGB", image.size, (0, 0, 0))
    gdraw = ImageDraw.Draw(grid)
    for i in range(-20, 21):
        gdraw.line((cx + i * width * 0.015, horizon, cx + i * width * 0.12, height), fill=(240, 68, 219), width=1)
    y, gap = horizon, 3 * s
    while y < height:
        gdraw.line((0, y, width, y), fill=(240, 68, 219), width=1)
        gap *= 1.3
        y += gap
    image = ImageChops.add(image, grid)
    image = ImageChops.add(image, grid.filter(ImageFilter.GaussianBlur(5 * s)))
    return _add_noise(image, 5, seed)


def minimal(width, height, seed=11):
    image = _gradient(width, height, [(0, (27, 39, 53)), (1, (9, 10, 15))])

    def blobs(draw, f):
        rng = random.Random(seed)
        for color in ((60, 90, 140), (40, 70, 90), (90, 70, 120)):
            r = rng.uniform(0.25, 0.45) * height
            x, y = rng.uniform(0, width), rng.uniform(0, height)
            draw.ellipse(((x - r) * f, (y - r) * f, (x + r) * f, (y + r) * f), fill=color)
    image = Image.blend(image, ImageChops.lighter(image, _glow_layer(image.size, blobs, height * 0.25)), 0.5)
    return _add_noise(image, 4, seed)


def matrix(width, height, seed=5):
    rng = random.Random(seed)
    image = Image.new("RGB", (width, height), (0, 6, 2))
    size = max(8, int(height / 34))
    fnt = font("mono", size, True)
    draw = ImageDraw.Draw(image)
    chars = "0123456789ABCDEFXZ$#%&+=<>*:"     # glyphs the bundled mono font has
    for column in range(0, width, int(size * 0.9)):
        length = rng.randint(6, 30)
        head = rng.randint(0, height // size + 10)
        for k in range(length):
            row = head - k
            if 0 <= row * size < height:
                level = max(0.1, 1 - k / length)
                color = (180, 255, 200) if k == 0 else (0, int(70 + 170 * level), int(30 + 40 * level))
                draw.text((column, row * size), rng.choice(chars), font=fnt, fill=color)
    glow = image.filter(ImageFilter.GaussianBlur(size * 0.6))
    return ImageChops.add(image, glow)


def retro(width, height, seed=9):
    image = _gradient(width, height, [(0, (8, 16, 40)), (1, (2, 6, 16))])
    draw = ImageDraw.Draw(image)
    band_colors = [(255, 176, 0), (255, 120, 0), (220, 60, 40), (160, 30, 90)]
    stripe = max(4, height // 40)
    top = int(height * 0.72)
    for i, color in enumerate(band_colors):
        y = top + i * stripe * 1.6
        draw.rectangle((0, y, width, y + stripe), fill=color)
    step = max(4, height // 60)
    for x in range(0, width, step * 4):
        draw.line((x, 0, x, top - step), fill=(14, 26, 60))
    for y in range(0, top - step, step * 4):
        draw.line((0, y, width, y), fill=(14, 26, 60))
    return _add_noise(image, 5, seed)


def dark(width, height, seed=13):
    image = _gradient(width, height, [(0, (18, 20, 28)), (1, (4, 5, 8))])
    draw = ImageDraw.Draw(image)
    size = height / 9
    for row in range(-1, 12):
        for col in range(-1, int(width / size) + 2):
            x = col * size * 1.5
            y = row * size * math.sqrt(3) + (size * math.sqrt(3) / 2 if col % 2 else 0)
            points = [(x + size * math.cos(math.radians(a)), y + size * math.sin(math.radians(a)))
                      for a in range(0, 360, 60)]
            draw.polygon(points, outline=(26, 29, 40))
    return _add_noise(image, 4, seed)


def glass(width, height, seed=17):
    image = Image.new("RGB", (width, height), (10, 12, 28))

    def aurora(draw, f):
        rng = random.Random(seed)
        for color in ((40, 110, 255), (150, 60, 230), (0, 200, 190), (240, 80, 170), (60, 220, 255)):
            r = rng.uniform(0.3, 0.55) * height
            x, y = rng.uniform(-0.1, 1.1) * width, rng.uniform(0, 1) * height
            draw.ellipse(((x - r) * f, (y - r) * f, (x + r) * f, (y + r) * f), fill=color)
    image = ImageChops.lighter(image, _glow_layer(image.size, aurora, height * 0.3))
    return _add_noise(image, 5, seed)


def industrial(width, height, seed=21):
    rng = np.random.default_rng(seed)
    run = max(8, width // 20)                      # horizontal box blur = brushed streaks
    noise = rng.normal(0, 1, (height, width + run + 1))
    summed = np.cumsum(noise, axis=1)
    streaks = (summed[:, run:] - summed[:, :-run])[:, :width] / math.sqrt(run)
    base = (72 + streaks * 16 + rng.normal(0, 3, (height, width))).clip(0, 255).astype(np.uint8)
    metal = Image.fromarray(base, "L")
    image = Image.merge("RGB", (metal, metal.point(lambda v: v + 4), metal.point(lambda v: v + 10)))
    shade = _gradient(width, height, [(0, (40, 44, 50)), (1, (10, 11, 13))])
    image = ImageChops.multiply(image, ImageOps.autocontrast(shade))
    draw = ImageDraw.Draw(image)
    s = height / 480
    for x in (width * 0.33, width * 0.66):
        draw.line((x, 0, x, height), fill=(20, 22, 26), width=max(1, int(2 * s)))
        draw.line((x + 2 * s, 0, x + 2 * s, height), fill=(90, 96, 104), width=1)
    for (x, y) in ((14, 14), (width - 14, 14), (14, height - 14), (width - 14, height - 14)):
        r = 5 * s
        draw.ellipse((x - r, y - r, x + r, y + r), fill=(120, 126, 134), outline=(30, 32, 36))
    stripe = 26 * s
    band_top = height - 30 * s
    for i in range(-2, int(width * 0.3 / stripe) + 2):
        x = i * stripe
        draw.polygon([(x, height), (x + stripe / 2, band_top), (x + stripe, band_top), (x + stripe / 2, height)],
                     fill=(255, 182, 39))
    return image


GENERATORS = {"cyberpunk": cyberpunk, "neon_grid": neon_grid, "minimal": minimal, "matrix": matrix,
              "retro": retro, "dark": dark, "glass": glass, "industrial": industrial}


@functools.lru_cache(maxsize=6)
def _generated(name, width, height):
    return GENERATORS.get(name, cyberpunk)(width, height)


@functools.lru_cache(maxsize=3)
def _user_image(path, mtime):
    with Image.open(path) as image:
        image.load()
        return image.convert("RGB")


# ---------------------------------------------------------------- pipeline

def source_image(settings, size, store_dir=None):
    """The unadjusted source for ``settings``; None means 'generate at size'."""
    source = settings.get("source", "builtin:cyberpunk")
    if source.startswith("user:"):
        from . import store
        path = store.wallpaper_path(source[5:], store_dir)
        if path:
            import os
            try:
                return _user_image(path, os.path.getmtime(path))
            except OSError:
                pass
        return None          # missing file: fall back to a built-in
    return None


def _fit(image, size, settings, background):
    width, height = size
    zoom = settings.get("zoom", 100) / 100
    fit = settings.get("fit", "cover")
    ox, oy = settings.get("offset_x", 0) / 100, settings.get("offset_y", 0) / 100
    canvas = Image.new("RGB", size, background)
    iw, ih = image.size
    if fit == "tile":
        tile = image.resize((max(1, int(iw * zoom)), max(1, int(ih * zoom))), Image.Resampling.LANCZOS)
        shift_x, shift_y = int(ox * tile.width), int(oy * tile.height)
        for x in range(-tile.width + shift_x % tile.width, width, tile.width):
            for y in range(-tile.height + shift_y % tile.height, height, tile.height):
                canvas.paste(tile, (x, y))
        return canvas
    if fit == "cover":
        factor = max(width / iw, height / ih) * zoom
    elif fit == "contain":
        factor = min(width / iw, height / ih) * zoom
    elif fit == "stretch":
        resized = image.resize((max(1, int(width * zoom)), max(1, int(height * zoom))), Image.Resampling.LANCZOS)
        factor = None
    else:            # center / original: 1:1
        factor = zoom
    if factor is not None:
        resized = image.resize((max(1, int(iw * factor)), max(1, int(ih * factor))), Image.Resampling.LANCZOS)
    rw, rh = resized.size
    if fit == "original":
        x, y = int(ox * width / 2), int(oy * height / 2)
    else:
        x = int((width - rw) / 2 + ox * abs(width - rw) / 2) if fit != "contain" else int((width - rw) / 2 + ox * width / 2)
        y = int((height - rh) / 2 + oy * abs(height - rh) / 2) if fit != "contain" else int((height - rh) / 2 + oy * height / 2)
    canvas.paste(resized, (x, y))
    return canvas


@functools.lru_cache(maxsize=8)
def _vignette_mask(width, height, strength):
    y, x = np.ogrid[:height, :width]
    cx, cy = (width - 1) / 2, (height - 1) / 2
    d = np.sqrt(((x - cx) / cx) ** 2 + ((y - cy) / cy) ** 2) / math.sqrt(2)
    mask = 1 - strength * np.clip((d - 0.35) / 0.65, 0, 1) ** 1.6
    return Image.fromarray((mask * 255).astype(np.uint8), "L")


def _protect_mask(width, height, side, strength):
    ramp = np.linspace(0, 1, 256) ** 1.5
    mask = Image.new("L", (width, height), 0)
    sides = ("bottom", "top") if side == "both" else (side,)
    for one in sides:
        if one in ("bottom", "top"):
            span = int(height * 0.45)
            column = (ramp[np.linspace(0, 255, span).astype(int)] * 255 * strength).astype(np.uint8)
            if one == "top":
                column = column[::-1]
            strip = Image.fromarray(np.repeat(column[:, None], width, axis=1), "L")
            mask.paste(ImageChops.lighter(mask.crop((0, height - span if one == "bottom" else 0, width,
                                                     height if one == "bottom" else span)), strip),
                       (0, height - span if one == "bottom" else 0))
        else:
            span = int(width * 0.45)
            row = (ramp[np.linspace(0, 255, span).astype(int)] * 255 * strength).astype(np.uint8)
            if one == "left":
                row = row[::-1]
            strip = Image.fromarray(np.repeat(row[None, :], height, axis=0), "L")
            x = width - span if one == "right" else 0
            mask.paste(ImageChops.lighter(mask.crop((x, 0, x + span, height)), strip), (x, 0))
    return mask


def adjust(image, settings):
    width, height = image.size
    if settings.get("brightness", 100) != 100:
        image = ImageEnhance.Brightness(image).enhance(settings["brightness"] / 100)
    if settings.get("contrast", 100) != 100:
        image = ImageEnhance.Contrast(image).enhance(settings["contrast"] / 100)
    if settings.get("saturation", 100) != 100:
        image = ImageEnhance.Color(image).enhance(settings["saturation"] / 100)
    if settings.get("gamma", 100) != 100:
        gamma = 100 / settings["gamma"]
        lut = [int(255 * (i / 255) ** gamma) for i in range(256)] * 3
        image = image.point(lut)
    if settings.get("blur", 0):
        image = image.filter(ImageFilter.GaussianBlur(settings["blur"] * height / 480))
    if settings.get("tint_strength", 0):
        image = Image.blend(image, Image.new("RGB", image.size, rgb(settings.get("tint", "#000000"))),
                            settings["tint_strength"] / 100 * 0.7)
    if settings.get("darken", 0):
        image = Image.blend(image, Image.new("RGB", image.size, (0, 0, 0)), settings["darken"] / 100)
    if settings.get("vignette", 0):
        black = Image.new("RGB", image.size, (0, 0, 0))
        image = Image.composite(image, black, _vignette_mask(width, height, settings["vignette"] / 100))
    if settings.get("protect", 0):
        black = Image.new("RGB", image.size, (0, 0, 0))
        image = Image.composite(black, image, _protect_mask(width, height, settings.get("protect_side", "bottom"),
                                                            settings["protect"] / 100 * 0.85))
    return image


def effect_overlay(image, theme):
    effect = theme.get("bg_effect", "none")
    strength = theme.get("bg_effect_strength", 25) / 100
    if effect == "none" or strength <= 0:
        return image
    width, height = image.size
    color = (*rgb(theme.get("bg_effect_color", "#42E8FF")), int(255 * strength * 0.5))
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    step = max(3, height // 160)
    if effect == "scanlines":
        for y in range(0, height, step):
            draw.line((0, y, width, y), fill=color)
    elif effect == "grid":
        cell = max(12, height // 20)
        for x in range(0, width, cell):
            draw.line((x, 0, x, height), fill=color)
        for y in range(0, height, cell):
            draw.line((0, y, width, y), fill=color)
    elif effect == "dots":
        cell = max(8, height // 30)
        r = max(1, cell // 8)
        for x in range(cell // 2, width, cell):
            for y in range(cell // 2, height, cell):
                draw.ellipse((x - r, y - r, x + r, y + r), fill=color)
    base = image.convert("RGBA")
    base.alpha_composite(overlay)
    return base.convert("RGB")


def render(settings, theme, size, store_dir=None):
    """Processed wallpaper (RGB) for one panel size; cached."""
    key = (tuple(sorted(settings.items())), theme.get("bg_effect"), theme.get("bg_effect_strength"),
           theme.get("bg_effect_color"), size, store_dir)
    return _cached(key, lambda: _render(settings, theme, size, store_dir))


def _transform(image, settings):
    rotation = settings.get("rotation", 0)
    if rotation:
        image = image.rotate(-rotation, expand=True)
    if settings.get("mirror"):
        image = ImageOps.mirror(image)
    if settings.get("flip"):
        image = ImageOps.flip(image)
    return image


def _render(settings, theme, size, store_dir):
    width, height = size
    source = settings.get("source", "builtin:cyberpunk")
    background = rgb(settings.get("color", "#0B1020"))
    if source == "color":
        image = Image.new("RGB", size, background)
    elif source == "gradient":
        angle = math.radians(settings.get("angle", 135))
        y, x = np.mgrid[0:height, 0:width]
        t = ((x - width / 2) * math.cos(angle) + (y - height / 2) * math.sin(angle))
        t = (t - t.min()) / max(1e-6, t.max() - t.min())
        a, b = np.array(background), np.array(rgb(settings.get("color2", "#3A1450")))
        image = Image.fromarray((a + (b - a) * t[..., None]).astype(np.uint8), "RGB")
    else:
        user = source_image(settings, size, store_dir)
        if user is not None:
            image = _fit(_transform(user, settings), size, settings, background)
        else:
            name = source[8:] if source.startswith("builtin:") else "cyberpunk"
            zoom = settings.get("zoom", 100) / 100
            portrait = settings.get("rotation", 0) in (90, 270)
            gw, gh = (height, width) if portrait else (width, height)
            generated = _generated(name, max(16, int(gw * zoom)), max(16, int(gh * zoom)))
            image = _fit(_transform(generated, settings), size, dict(settings, fit="cover", zoom=100), background)
    image = adjust(image, settings)
    return effect_overlay(image, theme)


def thumbnail(source, size=(160, 96), store_dir=None):
    """Small preview of a wallpaper source for the gallery."""
    settings = {"source": source, "fit": "cover"}
    return _render(settings, {}, size, store_dir)
