"""Drawing primitives for Kojiro widgets (Pillow only).

Shapes are drawn on supersampled RGBA layers and reduced once, which gives
antialiased arcs without Cairo. Glow is a blurred, single-colour copy of the
layer's alpha placed underneath (blurring the RGBA layer itself would darken
the halo with the transparent black pixels).
"""

import functools
import math
import os
import subprocess

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from ..themes import FONT_DIR

MIN_FONT = 8
SEGMENTS = {   # seven segments a..g for the digital style
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg",
    "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g", " ": "", "A": "abcefg", "P": "abefg", "M": "abcef",
}


def rgb(color):
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgba(color, alpha=255):
    return (*rgb(color), int(max(0, min(255, alpha))))


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def hexcolor(color):
    return "#{:02X}{:02X}{:02X}".format(*color[:3])


# ---------------------------------------------------------------- fonts

BUNDLED = {("default", False): "DejaVuSans.ttf", ("default", True): "DejaVuSans-Bold.ttf",
           ("mono", False): "DejaVuSansMono.ttf", ("mono", True): "DejaVuSansMono-Bold.ttf"}


@functools.lru_cache(maxsize=64)
def font_file(family, bold):
    """Path of a font: bundled DejaVu, or a system family resolved by fontconfig (once)."""
    if (family, bold) in BUNDLED:
        return os.path.join(FONT_DIR, BUNDLED[(family, bold)])
    try:
        pattern = f"{family}:style={'Bold' if bold else 'Regular'}"
        result = subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True,
                                timeout=2, check=False)
        path = result.stdout.strip()
        if result.returncode == 0 and path.lower().endswith((".ttf", ".otf", ".ttc")) and os.path.exists(path):
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.join(FONT_DIR, BUNDLED[("default", bold)])


@functools.lru_cache(maxsize=256)
def font(family, size, bold=False):
    size = max(1, int(size))
    try:
        return ImageFont.truetype(font_file(family, bold), size)
    except OSError:
        return ImageFont.truetype(os.path.join(FONT_DIR, BUNDLED[("default", bold)]), size)


def resolve_family(widget_family, theme_family, text_style):
    family = widget_family if widget_family != "default" else theme_family
    if text_style in ("mono", "digital", "pixel") and family == "default":
        return "mono"
    return family


def text_size(draw, text, fnt):
    if not text:
        return 0, 0
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0], box[3] - box[1]


def fit_font(draw, text, family, size, bold, max_width, minimum=MIN_FONT):
    """Largest font <= size whose text fits max_width (never below ``minimum``)."""
    size = int(size)
    while size > minimum:
        fnt = font(family, size, bold)
        if draw.textlength(text, font=fnt) <= max_width:
            return fnt
        size -= max(1, size // 10)
    return font(family, minimum, bold)


def ellipsize(draw, text, fnt, max_width):
    if draw.textlength(text, font=fnt) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=fnt) > max_width:
        text = text[:-1]
    return text + "…" if text else ""


def draw_text(layer, xy, text, size, color, family="default", bold=True, style="normal", anchor="la",
              max_width=None):
    """Text in one of the Kojiro styles. Returns the width used."""
    text = " ".join(str(text).split()) if text else ""      # sensor names may carry newlines/tabs
    if not text:
        return 0
    draw = ImageDraw.Draw(layer)
    size = max(MIN_FONT, int(size))
    if style == "digital" and all(ch in SEGMENTS or ch in ":.;" for ch in text.upper()):
        return seven_segment(layer, xy, text.upper(), size, color, anchor)
    if style == "pixel":
        factor = 3 if size >= 18 else 2
        small = max(4, size // factor)
        fnt = font("mono", small, False)
        width, height = text_size(draw, text, fnt)
        if max_width:
            while width * factor > max_width and small > 4:
                small -= 1
                fnt = font("mono", small, False)
                width, height = text_size(draw, text, fnt)
        tile = Image.new("L", (int(width) + 2, int(small * 1.3) + 2), 0)
        ImageDraw.Draw(tile).text((1, 0), text, font=fnt, fill=255)
        tile = tile.point(lambda v: 255 if v > 110 else 0).resize((tile.width * factor, tile.height * factor),
                                                                  Image.Resampling.NEAREST)
        x, y = _anchored(xy, tile.size, anchor)
        layer.paste(Image.new("RGBA", tile.size, color), (int(x), int(y)), tile)
        return tile.width
    fnt = font(family, size, bold)
    if max_width:
        fnt = fit_font(draw, text, family, size, bold, max_width)
        text = ellipsize(draw, text, fnt, max_width)
    draw.text(xy, text, font=fnt, fill=color, anchor=anchor)
    return draw.textlength(text, font=fnt)


def _anchored(xy, size, anchor):
    x, y = xy
    width, height = size
    if anchor[0] == "m":
        x -= width / 2
    elif anchor[0] == "r":
        x -= width
    if anchor[1] == "m":
        y -= height / 2
    elif anchor[1] in ("b", "d"):
        y -= height
    return x, y


def seven_segment(layer, xy, text, size, color, anchor="la"):
    """Digital clock digits drawn as segments (no font needed)."""
    height = size
    width = height * 0.52
    thick = max(2, height * 0.11)
    gap = height * 0.16
    advance = []
    for ch in text:
        advance.append(thick * 2.2 if ch in ":.;" else width + gap)
    total = sum(advance) - gap
    x, y = _anchored(xy, (total, height), anchor)
    draw = ImageDraw.Draw(layer)
    dim = (*color[:3], 28)
    for ch, step in zip(text, advance):
        if ch in ":.;":
            r = thick * 0.6
            cx = x + thick
            dots = (y + height * 0.32, y + height * 0.72) if ch in ":;" else (y + height - r,)
            for cy in dots:      # ";" = colon switched off (blink) without moving the digits
                draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=dim if ch == ";" else color)
        else:
            lit = SEGMENTS.get(ch, "")
            for seg, (x0, y0, x1, y1) in _segment_boxes(x, y, width, height, thick).items():
                draw.polygon(_hexagon(x0, y0, x1, y1), fill=color if seg in lit else dim)
        x += step
    return total


def _segment_boxes(x, y, w, h, t):
    half = h / 2
    return {"a": (x + t * 0.6, y, x + w - t * 0.6, y + t), "g": (x + t * 0.6, y + half - t / 2, x + w - t * 0.6,
                                                                 y + half + t / 2),
            "d": (x + t * 0.6, y + h - t, x + w - t * 0.6, y + h),
            "f": (x, y + t * 0.6, x + t, y + half - t * 0.4), "b": (x + w - t, y + t * 0.6, x + w, y + half - t * 0.4),
            "e": (x, y + half + t * 0.4, x + t, y + h - t * 0.6),
            "c": (x + w - t, y + half + t * 0.4, x + w, y + h - t * 0.6)}


def _hexagon(x0, y0, x1, y1):
    if x1 - x0 >= y1 - y0:
        m = (y1 - y0) / 2
        return [(x0, y0 + m), (x0 + m, y0), (x1 - m, y0), (x1, y0 + m), (x1 - m, y1), (x0 + m, y1)]
    m = (x1 - x0) / 2
    return [(x0 + m, y0), (x1, y0 + m), (x1, y1 - m), (x0 + m, y1), (x0, y1 - m), (x0, y0 + m)]


# ---------------------------------------------------------------- effects

def glow(layer, color, strength, radius):
    """Layer with a neon halo of ``color`` under it."""
    if strength <= 0 or radius <= 0:
        return layer
    alpha = layer.getchannel("A")
    halo_alpha = alpha.filter(ImageFilter.GaussianBlur(radius))
    halo_alpha = halo_alpha.point(lambda v: min(255, int(v * (0.6 + strength * 2.2))))
    halo = Image.new("RGBA", layer.size, (*color[:3], 0))
    halo.putalpha(halo_alpha)
    return Image.alpha_composite(halo, layer)


def drop_shadow(layer, offset=2, blur=2, opacity=150):
    alpha = layer.getchannel("A").filter(ImageFilter.GaussianBlur(blur)).point(lambda v: v * opacity // 255)
    shadow = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    shadow.putalpha(alpha)
    result = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    result.alpha_composite(shadow, (offset, offset))
    return Image.alpha_composite(result, layer)


def with_opacity(layer, opacity):
    if opacity >= 100:
        return layer
    alpha = layer.getchannel("A").point(lambda v: v * opacity // 100)
    layer = layer.copy()
    layer.putalpha(alpha)
    return layer


def multiply_alpha(layer, factor):
    alpha = layer.getchannel("A").point(lambda v: int(v * factor))
    layer = layer.copy()
    layer.putalpha(alpha)
    return layer


# ---------------------------------------------------------------- shapes

def panel(draw, box, radius, fill=None, outline=None, width=1, cut=False):
    x0, y0, x1, y1 = box
    if x1 <= x0 or y1 <= y0:
        return
    if cut:      # HUD panel with cut corners
        c = max(2, min(x1 - x0, y1 - y0) * 0.18)
        points = [(x0 + c, y0), (x1, y0), (x1, y1 - c), (x1 - c, y1), (x0, y1), (x0, y0 + c)]
        draw.polygon(points, fill=fill, outline=outline, width=width if outline else 0)
        return
    radius = max(0, min(radius, (x1 - x0) / 2, (y1 - y0) / 2))
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width if outline else 0)


def bar_h(draw, box, fraction, color, style="bar", track=None, color2=None):
    """Horizontal bar: bar, bar_segmented, bar_gradient (neon look comes from the glow)."""
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 2 or height <= 1:
        return
    fraction = max(0.0, min(1.0, fraction))
    track = track or (*color[:3], 45)
    if style == "bar_segmented":
        count = max(6, min(40, int(width / max(4, height * 0.9))))
        gap = max(1, width / count * 0.28)
        seg = (width - gap * (count - 1)) / count
        lit = fraction * count
        for i in range(count):
            sx = x0 + i * (seg + gap)
            on = i < int(lit) or (i < lit and lit - i > 0.5)
            draw.rectangle((sx, y0, sx + seg, y1), fill=color if on else track)
        return
    radius = height / 2 if style != "bar_flat" else 0
    draw.rounded_rectangle(box, radius=radius, fill=track)
    fill_x = x0 + width * fraction
    if fill_x - x0 < 1:
        return
    if style == "bar_gradient" and color2:
        steps = max(1, int(fill_x - x0))
        for i in range(steps):
            draw.line((x0 + i, y0, x0 + i, y1), fill=(*mix(color, color2, i / max(1, width)), color[3]
                                                      if len(color) > 3 else 255))
        return
    draw.rounded_rectangle((x0, y0, max(fill_x, x0 + height), y1), radius=radius, fill=color)


def bar_v(draw, box, fraction, color, style="bar_vertical", track=None):
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if width <= 1 or height <= 2:
        return
    fraction = max(0.0, min(1.0, fraction))
    track = track or (*color[:3], 45)
    if style == "thermo":
        r = width / 2
        bulb = min(width * 1.6, height * 0.3)
        draw.rounded_rectangle((x0 + width * 0.2, y0, x1 - width * 0.2, y1 - bulb * 0.6), radius=r, fill=track)
        top = y0 + (y1 - bulb * 0.6 - y0) * (1 - fraction)
        draw.rounded_rectangle((x0 + width * 0.32, top, x1 - width * 0.32, y1 - bulb * 0.5), radius=r, fill=color)
        cx = (x0 + x1) / 2
        draw.ellipse((cx - bulb / 2, y1 - bulb, cx + bulb / 2, y1), fill=color)
        return
    if style == "bar_segmented":
        count = max(5, min(30, int(height / max(4, width * 0.45))))
        gap = max(1, height / count * 0.25)
        seg = (height - gap * (count - 1)) / count
        lit = round(fraction * count)
        for i in range(count):
            sy = y1 - (i + 1) * seg - i * gap
            draw.rectangle((x0, sy, x1, sy + seg), fill=color if i < lit else track)
        return
    draw.rounded_rectangle(box, radius=width / 3, fill=track)
    top = y1 - height * fraction
    if y1 - top >= 1:
        draw.rounded_rectangle((x0, top, x1, y1), radius=width / 3, fill=color)


def ring(draw, center, radius, thickness, fraction, color, style="ring", track=None, fraction2=None,
         color2=None):
    """Circular indicators: ring, semi, arc, double, gauge (needle drawn separately)."""
    cx, cy = center
    track = track or (*color[:3], 50)
    fraction = max(0.0, min(1.0, fraction))
    spans = {"ring": (-90, 270), "double": (-90, 270), "semi": (180, 360), "arc": (135, 405), "gauge": (150, 390)}
    start, end = spans.get(style, (-90, 270))
    box = (cx - radius, cy - radius, cx + radius, cy + radius)
    width = max(1, int(thickness))
    draw.arc(box, start, end, fill=track, width=width)
    if fraction > 0:
        draw.arc(box, start, start + (end - start) * fraction, fill=color, width=width)
        # Round caps
        for angle in (start, start + (end - start) * fraction):
            a = math.radians(angle)
            r = radius - thickness / 2
            px, py = cx + r * math.cos(a), cy + r * math.sin(a)
            draw.ellipse((px - thickness / 2, py - thickness / 2, px + thickness / 2, py + thickness / 2),
                         fill=color)
    if style == "double" and fraction2 is not None:
        inner = radius - thickness * 1.6
        if inner > thickness:
            ibox = (cx - inner, cy - inner, cx + inner, cy + inner)
            iw = max(1, int(thickness * 0.55))
            c2 = color2 or color
            draw.arc(ibox, start, end, fill=(*c2[:3], 40), width=iw)
            if fraction2 > 0:
                draw.arc(ibox, start, start + (end - start) * max(0.0, min(1.0, fraction2)), fill=c2, width=iw)
    return start, end


def gauge_ticks(draw, center, radius, color, start=150, end=390, count=11, length=0.12, width=2):
    cx, cy = center
    for i in range(count):
        a = math.radians(start + (end - start) * i / (count - 1))
        major = i % 2 == 0
        r0 = radius * (1 - (length if major else length * 0.6))
        draw.line((cx + r0 * math.cos(a), cy + r0 * math.sin(a), cx + radius * math.cos(a), cy + radius * math.sin(a)),
                  fill=color, width=width if major else max(1, width // 2))


def needle(draw, center, radius, fraction, color, start=150, end=390, width=3):
    cx, cy = center
    a = math.radians(start + (end - start) * max(0.0, min(1.0, fraction)))
    tip = (cx + radius * math.cos(a), cy + radius * math.sin(a))
    back = (cx - radius * 0.15 * math.cos(a), cy - radius * 0.15 * math.sin(a))
    side = math.radians(90)
    w = width
    p1 = (cx + w * math.cos(a + side), cy + w * math.sin(a + side))
    p2 = (cx + w * math.cos(a - side), cy + w * math.sin(a - side))
    draw.polygon([tip, p1, back, p2], fill=color)
    draw.ellipse((cx - w * 1.6, cy - w * 1.6, cx + w * 1.6, cy + w * 1.6), fill=color)


def graph(draw, box, values, color, style="graph_line", maximum=None, width=2):
    x0, y0, x1, y1 = box
    values = [v for v in values if v is not None]
    if len(values) < 2 or x1 - x0 < 4 or y1 - y0 < 4:
        return
    top = maximum if maximum else max(values) or 1.0
    top = max(top, 1e-6)
    step = (x1 - x0) / (len(values) - 1)
    points = [(x0 + i * step, y1 - (y1 - y0) * max(0.0, min(1.0, v / top))) for i, v in enumerate(values)]
    if style == "graph_bars":
        bw = max(1, step * 0.7)
        for (px, py) in points:
            draw.rectangle((px - bw / 2, py, px + bw / 2, y1), fill=color)
        return
    if style in ("graph_area", "sparkline"):
        area = (*color[:3], 70 if style == "graph_area" else 35)
        draw.polygon(points + [(x1, y1), (x0, y1)], fill=area)
    draw.line(points, fill=color, width=width, joint="curve")
    if style == "sparkline":
        px, py = points[-1]
        r = width * 1.4
        draw.ellipse((px - r, py - r, px + r, py + r), fill=color)


@functools.lru_cache(maxsize=64)
def fan_blades(size, color, blades=5):
    """One fan drawing (rotated by the caller)."""
    ss = 3
    big = size * ss
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    c = big / 2
    r = big * 0.47
    draw.ellipse((c - r, c - r, c + r, c + r), outline=color, width=max(2, big // 22))
    hub = big * 0.12
    for i in range(blades):
        a = math.radians(i * 360 / blades)
        points = []
        for t in range(0, 11):
            frac = t / 10
            ang = a + frac * 0.9
            rr = hub + (r * 0.86 - hub) * frac
            points.append((c + rr * math.cos(ang), c + rr * math.sin(ang)))
        for t in range(10, -1, -1):
            frac = t / 10
            ang = a + 0.55 + frac * 0.6
            rr = hub + (r * 0.86 - hub) * frac
            points.append((c + rr * math.cos(ang), c + rr * math.sin(ang)))
        draw.polygon(points, fill=(*color[:3], 220))
    draw.ellipse((c - hub, c - hub, c + hub, c + hub), fill=color)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def fan_icon(size, color, angle=0.0):
    image = fan_blades(max(4, int(size)), tuple(color))
    return image.rotate(-angle, resample=Image.Resampling.BICUBIC) if angle else image


def arrow(draw, box, color, up=True):
    x0, y0, x1, y1 = box
    cx = (x0 + x1) / 2
    w = x1 - x0
    head = (y1 - y0) * 0.5
    if up:
        draw.polygon([(cx, y0), (x1, y0 + head), (cx + w * 0.18, y0 + head), (cx + w * 0.18, y1),
                      (cx - w * 0.18, y1), (cx - w * 0.18, y0 + head), (x0, y0 + head)], fill=color)
    else:
        draw.polygon([(cx, y1), (x1, y1 - head), (cx + w * 0.18, y1 - head), (cx + w * 0.18, y0),
                      (cx - w * 0.18, y0), (cx - w * 0.18, y1 - head), (x0, y1 - head)], fill=color)


def icon(name, size, color):
    """Bundled symbolic icon recoloured (cached by the legacy loader)."""
    from ..legacy_themes import get_svg_icon
    return get_svg_icon(f"{name}-symbolic.svg", max(6, int(size)), tuple(color[:3]))


def circle_mask(size):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    return mask


def luminance_stats(image):
    """(mean luminance 0..1, spread 0..1) of an RGB(A) image, for contrast assist."""
    from PIL import ImageStat
    stat = ImageStat.Stat(image.convert("L"))
    return stat.mean[0] / 255, stat.stddev[0] / 128


def screen(a, b):
    return ImageChops.screen(a, b)
