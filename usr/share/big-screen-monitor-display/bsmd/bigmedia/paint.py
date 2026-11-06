"""Drawing primitives for the Big Media Player skins (Pillow + NumPy only).

Every material (chrome, brushed metal, bevels, LCD wells, glyphs) is drawn
procedurally here: no bitmap, sprite or font from the historical players is
used. Expensive pieces are cached by their parameters; text is rasterised
once into masks so a scrolling title only costs a crop and a paste.
"""

import collections
import math

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from ..kojiro.draw import SEGMENTS, _hexagon, _segment_boxes, font as _font

Box = tuple


def clamp(value, low=0, high=255):
    return max(low, min(high, int(value)))


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def shade(color, factor):
    if factor >= 1:
        return mix(color, (255, 255, 255), factor - 1)
    return mix((0, 0, 0), color, factor)


def luminance(color):
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in color[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def ensure_contrast(color, background, ratio=4.5):
    """Lighten/darken ``color`` until it reads on ``background``."""
    toward = (255, 255, 255) if luminance(background) < 0.4 else (0, 0, 0)
    for step in range(11):
        candidate = mix(color, toward, step / 10)
        if contrast(candidate, background) >= ratio:
            return candidate
    return toward


def font(size, bold=False, mono=False):
    """``mono``: False (bundled sans), True (bundled mono) or a font family name
    (modern skins, e.g. "Lato"; resolved by fontconfig with a DejaVu fallback)."""
    if isinstance(mono, str):
        return _font(mono, max(6, int(size)), bold)
    return _font("mono" if mono else "default", max(6, int(size)), bold)


def inset(box, dx, dy=None):
    dy = dx if dy is None else dy
    return (box[0] + dx, box[1] + dy, box[2] - dx, box[3] - dy)


def width(box):
    return box[2] - box[0]


def height(box):
    return box[3] - box[1]


def ibox(box):
    return tuple(int(round(v)) for v in box)


# ---------------------------------------------------------------- fills

def vgrad(img, box, top, bottom, stops=None):
    """Vertical gradient; ``stops`` = [(t, color), ...] for multi-stop chrome."""
    x0, y0, x1, y1 = ibox(box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    stops = stops or [(0.0, top), (1.0, bottom)]
    t = np.linspace(0, 1, h)[:, None]
    positions = np.array([s[0] for s in stops])
    colors = np.array([s[1][:3] for s in stops], dtype=np.float64)
    column = np.stack([np.interp(t[:, 0], positions, colors[:, c]) for c in range(3)], axis=1)
    strip = np.repeat(column[:, None, :], w, axis=1).astype(np.uint8)
    img.paste(Image.fromarray(strip, "RGB"), (x0, y0))


def hgrad(img, box, left, right):
    x0, y0, x1, y1 = ibox(box)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    t = np.linspace(0, 1, w)
    row = np.stack([left[c] + (right[c] - left[c]) * t for c in range(3)], axis=1)
    strip = np.repeat(row[None, :, :], h, axis=0).astype(np.uint8)
    img.paste(Image.fromarray(strip, "RGB"), (x0, y0))


def brushed(img, box, strength=10, seed=7, vertical=False):
    """Brushed-metal streaks over what is already in ``box``."""
    x0, y0, x1, y1 = ibox(box)
    w, h = x1 - x0, y1 - y0
    if w <= 1 or h <= 1:
        return
    rng = np.random.default_rng(seed + w * 31 + h)
    if vertical:
        streak = rng.normal(0, strength, (1, w)).repeat(h, axis=0)
    else:
        streak = rng.normal(0, strength, (h, 1)).repeat(w, axis=1)
    streak += rng.normal(0, strength * 0.35, (h, w))
    region = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.int16)
    region = np.clip(region + streak[:, :, None], 0, 255).astype(np.uint8)
    img.paste(Image.fromarray(region, "RGB"), (x0, y0))


def scanlines(img, box, strength=0.18, every=2):
    x0, y0, x1, y1 = ibox(box)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return
    region = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.float32)
    region[::every] *= (1 - strength)
    img.paste(Image.fromarray(region.astype(np.uint8), "RGB"), (x0, y0))


def dither_dots(img, box, color, alpha=0.08, pitch=3):
    """LCD pixel grid."""
    x0, y0, x1, y1 = ibox(box)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return
    region = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.float32)
    mask = np.zeros(region.shape[:2], dtype=bool)
    mask[::pitch, :] = True
    mask[:, ::pitch] = True
    region[mask] = region[mask] * (1 - alpha) + np.array(color[:3]) * alpha
    img.paste(Image.fromarray(region.astype(np.uint8), "RGB"), (x0, y0))


# ---------------------------------------------------------------- frames

def bevel(draw, box, hi, lo, depth=1, inset_=False):
    """Classic 3D border: light top/left, dark bottom/right (swapped when sunken)."""
    x0, y0, x1, y1 = ibox(box)
    if inset_:
        hi, lo = lo, hi
    for i in range(depth):
        draw.line((x0 + i, y1 - 1 - i, x0 + i, y0 + i, x1 - 1 - i, y0 + i), fill=hi)
        draw.line((x0 + i, y1 - 1 - i, x1 - 1 - i, y1 - 1 - i, x1 - 1 - i, y0 + i), fill=lo)


def win_bevel(draw, box, face, sunken=False):
    """Windows 9x two-tone bevel (white/light, dark grey/black)."""
    x0, y0, x1, y1 = ibox(box)
    if face is not None:
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=face)
    if sunken:
        bevel(draw, (x0, y0, x1, y1), (128, 128, 128), (255, 255, 255))
        bevel(draw, (x0 + 1, y0 + 1, x1 - 1, y1 - 1), (64, 64, 64), (223, 223, 223))
    else:
        bevel(draw, (x0, y0, x1, y1), (255, 255, 255), (64, 64, 64))
        bevel(draw, (x0 + 1, y0 + 1, x1 - 1, y1 - 1), (223, 223, 223), (128, 128, 128))


def rounded_mask(size, radius, scale=3):
    w, h = size
    big = Image.new("L", (max(1, w * scale), max(1, h * scale)), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, w * scale - 1, h * scale - 1), radius=radius * scale, fill=255)
    return big.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)


def circle_mask(size, scale=3):
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * scale - 1, size * scale - 1), fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)


def paste_masked(img, tile, xy, mask):
    img.paste(tile, (int(xy[0]), int(xy[1])), mask)


def chrome_panel(img, box, radius, stops, outline=None, gloss=0.35, seed=3, brushed_strength=0):
    """Rounded metallic slab: multi-stop gradient, optional brushing, gloss and outline."""
    x0, y0, x1, y1 = ibox(box)
    w, h = x1 - x0, y1 - y0
    if w <= 2 or h <= 2:
        return
    tile = Image.new("RGB", (w, h))
    vgrad(tile, (0, 0, w, h), None, None, stops)
    if brushed_strength:
        brushed(tile, (0, 0, w, h), brushed_strength, seed)
    if gloss:
        highlight = Image.new("L", (w, h), 0)
        ImageDraw.Draw(highlight).rounded_rectangle((2, 1, w - 3, h // 2), radius=max(1, radius - 1),
                                                    fill=int(255 * gloss))
        highlight = highlight.filter(ImageFilter.GaussianBlur(max(1, h // 30)))
        tile = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), tile, highlight)
    mask = rounded_mask((w, h), radius)
    img.paste(tile, (x0, y0), mask)
    if outline:
        ImageDraw.Draw(img).rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius, outline=outline, width=1)


def lcd_well(img, box, bg, radius=0, rim_hi=None, rim_lo=None, inner_shadow=True):
    """Recessed display: dark fill, inner shadow at the top/left, optional rim."""
    x0, y0, x1, y1 = ibox(box)
    draw = ImageDraw.Draw(img)
    if radius:
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius, fill=bg)
    else:
        draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=bg)
    if inner_shadow and x1 - x0 > 6 and y1 - y0 > 6:
        shadow = shade(bg, 0.45)
        draw.line((x0 + 1, y0 + 1, x1 - 2, y0 + 1), fill=shadow)
        draw.line((x0 + 1, y0 + 1, x0 + 1, y1 - 2), fill=shadow)
    if rim_hi and rim_lo:
        if radius:
            draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=radius, outline=rim_lo, width=1)
        else:
            bevel(draw, (x0 - 1, y0 - 1, x1 + 1, y1 + 1), rim_lo, rim_hi)


def screw(draw, center, r, color):
    cx, cy = center
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=shade(color, 0.85), outline=shade(color, 0.5))
    draw.line((cx - r * 0.6, cy - r * 0.6, cx + r * 0.6, cy + r * 0.6), fill=shade(color, 0.45),
              width=max(1, int(r / 3)))


def led(draw, center, r, color, lit):
    cx, cy = center
    face = color if lit else shade(color, 0.28)
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=face, outline=shade(color, 0.2))
    if lit and r >= 2:
        draw.ellipse((cx - r * 0.45, cy - r * 0.6, cx, cy - r * 0.1), fill=mix(color, (255, 255, 255), 0.7))


def glow_layer(img, layer, color, radius, strength=1.2):
    """Composite RGBA ``layer`` onto ``img`` with a soft halo (neon / LCD bloom)."""
    alpha = layer.getchannel("A")
    halo = alpha.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(255, int(v * strength)))
    glow = Image.new("RGBA", layer.size, (*color[:3], 0))
    glow.putalpha(halo)
    base = img.convert("RGBA")
    base.alpha_composite(glow)
    base.alpha_composite(layer)
    return base.convert("RGB")


# ---------------------------------------------------------------- glyphs

GLYPHS = ("previous", "play", "pause", "next", "stop", "shuffle", "repeat", "repeat_one", "speaker", "mute",
          "eject", "rewind", "forward")


def glyph(draw, kind, box, color, weight=None):
    """Transport symbols drawn as polygons (no font, no sprite)."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    s = min(w, h)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = s / 2
    bar = max(1.0, s * 0.14) if weight is None else weight

    def tri(left, right, pointing_right=True):
        if pointing_right:
            return [(left, cy - half), (right, cy), (left, cy + half)]
        return [(right, cy - half), (left, cy), (right, cy + half)]

    if kind == "play":
        draw.polygon([(cx - half * 0.75, cy - half), (cx + half * 0.95, cy), (cx - half * 0.75, cy + half)], fill=color)
    elif kind == "pause":
        gap = s * 0.16
        draw.rectangle((cx - gap - bar * 1.6, cy - half, cx - gap, cy + half), fill=color)
        draw.rectangle((cx + gap, cy - half, cx + gap + bar * 1.6, cy + half), fill=color)
    elif kind == "stop":
        draw.rectangle((cx - half * 0.85, cy - half * 0.85, cx + half * 0.85, cy + half * 0.85), fill=color)
    elif kind in ("next", "forward"):
        draw.polygon(tri(cx - half, cx), fill=color)
        draw.polygon(tri(cx - half * 0.15, cx + half * 0.85 if kind == "next" else cx + half), fill=color)
        if kind == "next":
            draw.rectangle((cx + half * 0.82, cy - half, cx + half * 0.82 + bar, cy + half), fill=color)
    elif kind in ("previous", "rewind"):
        draw.polygon(tri(cx, cx + half, False), fill=color)
        draw.polygon(tri(cx - half * 0.85 if kind == "previous" else cx - half, cx + half * 0.15, False), fill=color)
        if kind == "previous":
            draw.rectangle((cx - half * 0.82 - bar, cy - half, cx - half * 0.82, cy + half), fill=color)
    elif kind == "eject":
        draw.polygon([(cx - half, cy + half * 0.15), (cx, cy - half), (cx + half, cy + half * 0.15)], fill=color)
        draw.rectangle((cx - half, cy + half * 0.45, cx + half, cy + half * 0.45 + bar * 1.4), fill=color)
    elif kind == "shuffle":
        lw = max(1, int(bar))
        draw.line((cx - half, cy - half * 0.6, cx - half * 0.3, cy - half * 0.6, cx + half * 0.3, cy + half * 0.6,
                   cx + half * 0.75, cy + half * 0.6), fill=color, width=lw)
        draw.line((cx - half, cy + half * 0.6, cx - half * 0.3, cy + half * 0.6, cx + half * 0.3, cy - half * 0.6,
                   cx + half * 0.75, cy - half * 0.6), fill=color, width=lw)
        for yy in (cy - half * 0.6, cy + half * 0.6):
            draw.polygon([(cx + half * 0.6, yy - half * 0.35), (cx + half, yy), (cx + half * 0.6, yy + half * 0.35)],
                         fill=color)
    elif kind in ("repeat", "repeat_one"):
        lw = max(1, int(bar))
        draw.rounded_rectangle((cx - half, cy - half * 0.6, cx + half * 0.9, cy + half * 0.6),
                               radius=max(1, int(half * 0.4)), outline=color, width=lw)
        draw.polygon([(cx + half * 0.05, cy - half * 0.95), (cx + half * 0.45, cy - half * 0.6),
                      (cx + half * 0.05, cy - half * 0.25)], fill=color)
        if kind == "repeat_one" and s >= 9:
            draw.text((cx - half * 0.05, cy + half * 0.05), "1", font=font(max(6, s * 0.55), True), fill=color,
                      anchor="mm")
    elif kind in ("speaker", "mute"):
        body = [(cx - half, cy - half * 0.35), (cx - half * 0.45, cy - half * 0.35), (cx, cy - half * 0.85),
                (cx, cy + half * 0.85), (cx - half * 0.45, cy + half * 0.35), (cx - half, cy + half * 0.35)]
        draw.polygon(body, fill=color)
        lw = max(1, int(bar * 0.8))
        if kind == "mute":
            draw.line((cx + half * 0.25, cy - half * 0.45, cx + half, cy + half * 0.45), fill=color, width=lw)
            draw.line((cx + half * 0.25, cy + half * 0.45, cx + half, cy - half * 0.45), fill=color, width=lw)
        else:
            for k, r in enumerate((0.45, 0.8)):
                draw.arc((cx - half * r, cy - half * r, cx + half * r, cy + half * r), -45, 45, fill=color,
                         width=lw)
                if s < 12 and k == 0:
                    break


# ---------------------------------------------------------------- text

_TEXT_CACHE = collections.OrderedDict()
TEXT_CACHE_SIZE = 96


def text_mask(text, size, bold=False, mono=False, pixel=False):
    """('L' mask, ascent offset) of ``text`` rendered once and cached."""
    key = (text, int(size), bold, mono, pixel)
    hit = _TEXT_CACHE.get(key)
    if hit is not None:
        _TEXT_CACHE.move_to_end(key)
        return hit
    if pixel:
        # Chunky bitmap look: a small mono font, thresholded and scaled up 2x.
        small = max(5, int(size) // 2)
        fnt = font(small, False, True)
        bbox = fnt.getbbox(text or " ")
        tile = Image.new("L", (max(1, bbox[2] + 2), max(1, int(small * 1.25) + 2)), 0)
        ImageDraw.Draw(tile).text((1, 0), text, font=fnt, fill=255)
        tile = tile.point(lambda v: 255 if v > 100 else 0)
        mask = tile.resize((tile.width * 2, tile.height * 2), Image.Resampling.NEAREST)
    else:
        fnt = font(size, bold, mono)
        ascent, descent = fnt.getmetrics()
        length = int(math.ceil(fnt.getlength(text or " "))) + 2
        mask = Image.new("L", (max(1, length), ascent + descent + 2), 0)
        ImageDraw.Draw(mask).text((1, 1), text, font=fnt, fill=255)
    _TEXT_CACHE[key] = mask
    while len(_TEXT_CACHE) > TEXT_CACHE_SIZE:
        _TEXT_CACHE.popitem(last=False)
    return mask


def text_width(text, size, bold=False, mono=False, pixel=False):
    return text_mask(text, size, bold, mono, pixel).width


def fit_size(text, size, max_width, bold=False, mono=False, minimum=7):
    size = int(size)
    while size > minimum and font(size, bold, mono).getlength(text) > max_width:
        size -= max(1, size // 12)
    return max(minimum, size)


def ellipsize(text, size, max_width, bold=False, mono=False):
    fnt = font(size, bold, mono)
    if fnt.getlength(text) <= max_width:
        return text
    while text and fnt.getlength(text + "…") > max_width:
        text = text[:-1]
    return (text + "…") if text else ""


def put_text(img, xy, text, size, color, bold=False, mono=False, anchor="lm", pixel=False):
    """Draw cached text. ``anchor``: l/m/r + t/m/b. Returns the drawn width."""
    if not text:
        return 0
    mask = text_mask(text, size, bold, mono, pixel)
    x, y = xy
    if anchor[0] == "m":
        x -= mask.width / 2
    elif anchor[0] == "r":
        x -= mask.width
    if anchor[1] == "m":
        y -= mask.height / 2
    elif anchor[1] == "b":
        y -= mask.height
    img.paste(Image.new("RGB", mask.size, color[:3]), (int(round(x)), int(round(y))), mask)
    return mask.width


def marquee(img, box, text, size, color, offset, bold=False, mono=False, pixel=False, gap_text="   ***   ",
            loop=False, align="l"):
    """Scroll ``text`` inside ``box``. ``offset`` in px (caller animates it).

    Returns True when the text is wider than the box (i.e. it moves)."""
    x0, y0, x1, y1 = ibox(box)
    w = x1 - x0
    if w <= 2 or not text:
        return False
    mask = text_mask(text, size, bold, mono, pixel)
    y = y0 + (y1 - y0 - mask.height) / 2
    if mask.width <= w:
        x = x0 if align == "l" else (x0 + (w - mask.width) / 2 if align == "m" else x1 - mask.width)
        img.paste(Image.new("RGB", mask.size, color[:3]), (int(x), int(round(y))), mask)
        return False
    if loop:
        strip = text_mask(text + gap_text, size, bold, mono, pixel)
        period = strip.width
        shift = int(offset) % period
        canvas = Image.new("L", (w, strip.height), 0)
        canvas.paste(strip, (-shift, 0))
        canvas.paste(strip, (period - shift, 0))
    else:
        travel = mask.width - w
        shift = int(max(0, min(travel, offset)))
        canvas = mask.crop((shift, 0, shift + w, mask.height))
    img.paste(Image.new("RGB", canvas.size, color[:3]), (x0, int(round(y))), canvas)
    return True


def seven_seg(img, xy, text, size, color, dim_alpha=0.12, anchor="la", bg=None):
    """Seven-segment readout with faint unlit segments (LCD ghosting)."""
    height_ = size
    width_ = height_ * 0.52
    thick = max(1.5, height_ * 0.12)
    gap = height_ * 0.18
    advance = [thick * 2.2 if ch in ":." else width_ + gap for ch in text]
    total = sum(advance) - gap
    x, y = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    if anchor[1] == "m":
        y -= height_ / 2
    elif anchor[1] == "b":
        y -= height_
    draw = ImageDraw.Draw(img)
    dim = mix(bg, color, dim_alpha) if bg is not None else shade(color, 0.18)
    for ch, step in zip(text, advance, strict=True):
        if ch in ":.":
            r = thick * 0.55
            cx = x + thick
            for cy in ((y + height_ * 0.3, y + height_ * 0.72) if ch == ":" else (y + height_ - r,)):
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
        else:
            lit = SEGMENTS.get(ch.upper(), "")
            for seg, (sx0, sy0, sx1, sy1) in _segment_boxes(x, y, width_, height_, thick).items():
                draw.polygon(_hexagon(sx0, sy0, sx1, sy1), fill=color if seg in lit else dim)
        x += step
    return total


def seven_seg_width(text, size):
    width_ = size * 0.52
    thick = max(1.5, size * 0.12)
    gap = size * 0.18
    return sum(thick * 2.2 if ch in ":." else width_ + gap for ch in text) - gap


# ---------------------------------------------------------------- images

def cover_fit(image, size):
    """Scale and centre-crop ``image`` to exactly ``size`` (square album art)."""
    w, h = size
    scale = max(w / image.width, h / image.height)
    resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                           Image.Resampling.LANCZOS)
    left = (resized.width - w) // 2
    top = (resized.height - h) // 2
    return resized.crop((left, top, left + w, top + h))


def contain_fit(image, size, background):
    """Scale ``image`` inside ``size`` keeping proportions (video thumbnails)."""
    w, h = size
    scale = min(w / image.width, h / image.height)
    resized = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                           Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (w, h), background)
    canvas.paste(resized, ((w - resized.width) // 2, (h - resized.height) // 2))
    return canvas


def dominant_color(image):
    """A saturated, mid-light colour representative of ``image`` (adaptive palette)."""
    small = image.convert("RGB").resize((24, 24), Image.Resampling.BILINEAR)
    data = np.asarray(small, dtype=np.float32).reshape(-1, 3) / 255
    maxc, minc = data.max(axis=1), data.min(axis=1)
    saturation = np.where(maxc > 0, (maxc - minc) / np.maximum(maxc, 1e-6), 0)
    score = saturation * (0.35 + maxc) * (maxc > 0.18)
    if score.max() < 0.12:
        return None
    best = data[np.argsort(score)[-24:]].mean(axis=0)
    return tuple(int(v * 255) for v in best)


def darken(image, factor):
    if factor >= 1:
        return image
    return ImageChops.multiply(image, Image.new("RGB", image.size, (int(255 * factor),) * 3))
