"""Modern Collection: shared base, responsive layout and anti-aliased painters.

The eight modern skins reuse the whole Big Media Player engine (media
snapshot, art tiles, telemetry, idle screens, chrome cache); they only bring
their own geometry (:meth:`ModernSkin.compute_layout`) and materials. Every
shape that has to look smooth (knobs, round keys, pills, icons, shadows) is
drawn supersampled once and kept in a small LRU (:func:`cached`), so a frame
costs pastes, not rasterisation.

Geometry is described per skin with *rows* stacked in a column next to the
art (landscape), under the art (portrait) or split in two columns
(ultrawide); rows are dropped in a fixed priority order when space runs out,
so nothing overlaps and text never shrinks below a readable size.
"""

import collections
import math
import re
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from ...i18n import _
from .. import layout as layout_mod, paint as P
from ..skins import Skin

CACHE_SIZE = 160
_CACHE = collections.OrderedDict()
HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
RADIUS_SCALE = {"skin": 1.0, "square": 0.0, "soft": 0.6, "round": 1.6}
FACES = {"system": "sans-serif", "dejavu": False}


def cached(key, make):
    """Small shared LRU for supersampled masks, tiles and gradients."""
    hit = _CACHE.get(key)
    if hit is None:
        hit = make()
        _CACHE[key] = hit
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    else:
        _CACHE.move_to_end(key)
    return hit


def cache_size():
    return len(_CACHE)


def parse_hex(text):
    match = HEX.match((text or "").strip())
    if not match:
        return None
    value = match.group(1)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


# ---------------------------------------------------------------- masks and shapes

def _ss(size, scale=4):
    return Image.new("L", (max(1, int(size[0] * scale)), max(1, int(size[1] * scale))), 0)


def rrect_mask(w, h, r):
    w, h, r = max(1, int(w)), max(1, int(h)), max(0, int(r))
    return cached(("rr", w, h, r), lambda: P.rounded_mask((w, h), min(r, w // 2, h // 2)) if r else
                  Image.new("L", (w, h), 255))


def circle_mask(d):
    d = max(1, int(d))
    return cached(("ci", d), lambda: P.circle_mask(d))


def ring_mask(d, width):
    d, width = max(2, int(d)), max(1.0, float(width))

    def make():
        big = _ss((d, d))
        draw = ImageDraw.Draw(big)
        s = big.width
        draw.ellipse((0, 0, s - 1, s - 1), fill=255)
        inner = width * 4
        draw.ellipse((inner, inner, s - 1 - inner, s - 1 - inner), fill=0)
        return big.resize((d, d), Image.Resampling.LANCZOS)
    return cached(("ring", d, round(width, 1)), make)


def solid(size, color):
    return Image.new("RGB", (max(1, int(size[0])), max(1, int(size[1]))), tuple(color[:3]))


def fill_rrect(img, box, r, color):
    x0, y0, x1, y1 = P.ibox(box)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return
    img.paste(solid((x1 - x0, y1 - y0), color), (x0, y0), rrect_mask(x1 - x0, y1 - y0, r))


def fill_circle(img, cx, cy, r, color):
    d = max(1, int(round(r * 2)))
    img.paste(solid((d, d), color), (int(round(cx - d / 2)), int(round(cy - d / 2))), circle_mask(d))


def ring(img, cx, cy, r, width, color):
    d = max(2, int(round(r * 2)))
    img.paste(solid((d, d), color), (int(round(cx - d / 2)), int(round(cy - d / 2))), ring_mask(d, width))


def fill_pill(img, x0, x1, cy, t, color):
    """Horizontal capsule from x0 to x1 (thickness t), round caps, cheap at any length."""
    t = max(1.0, t)
    if x1 - x0 < t:
        x1 = x0 + t
    top = int(round(cy - t / 2))
    bottom = top + max(1, int(round(t)))
    if t < 3:
        ImageDraw.Draw(img).rectangle((int(x0), top, int(x1) - 1, bottom - 1), fill=tuple(color[:3]))
        return
    r = (bottom - top) / 2
    if int(round(x1 - r)) >= int(round(x0 + r)):
        ImageDraw.Draw(img).rectangle((int(round(x0 + r)), top, int(round(x1 - r)), bottom - 1),
                                      fill=tuple(color[:3]))
    fill_circle(img, x0 + r, top + r, r, color)
    fill_circle(img, x1 - r, top + r, r, color)


def shadow(img, box, radius, blur, alpha, offset=(0, 0), color=(0, 0, 0), shape="rect"):
    """Soft drop shadow under ``box`` (cached blurred mask)."""
    if alpha <= 0.01 or blur <= 0:
        return
    x0, y0, x1, y1 = P.ibox(box)
    w, h = x1 - x0, y1 - y0
    if w < 2 or h < 2:
        return
    blur = max(1, int(blur))
    m = blur * 2 + 2

    def make():
        mask = Image.new("L", (w + m * 2, h + m * 2), 0)
        draw = ImageDraw.Draw(mask)
        level = int(255 * min(1.0, alpha))
        if shape == "circle":
            draw.ellipse((m, m, m + w - 1, m + h - 1), fill=level)
        else:
            draw.rounded_rectangle((m, m, m + w - 1, m + h - 1), radius=max(0, int(radius)), fill=level)
        return mask.filter(ImageFilter.GaussianBlur(blur / 1.6))
    mask = cached(("sh", w, h, int(radius), blur, round(alpha, 2), shape), make)
    img.paste(solid(mask.size, color), (x0 - m + int(offset[0]), y0 - m + int(offset[1])), mask)


def gradient_tile(w, h, stops, horizontal=True):
    """Cached RGB gradient strip ``stops`` = [(t, colour), ...]."""
    w, h = max(1, int(w)), max(1, int(h))
    key = ("gr", w, h, tuple((round(t, 3), tuple(c[:3])) for t, c in stops), horizontal)

    def make():
        n = w if horizontal else h
        t = np.linspace(0, 1, n)
        pos = np.array([s[0] for s in stops])
        cols = np.array([s[1][:3] for s in stops], dtype=np.float64)
        line = np.stack([np.interp(t, pos, cols[:, c]) for c in range(3)], axis=1).astype(np.uint8)
        if horizontal:
            arr = np.repeat(line[None, :, :], h, axis=0)
        else:
            arr = np.repeat(line[:, None, :], w, axis=1)
        return Image.fromarray(arr, "RGB")
    return cached(key, make)


def ramp(stops, t):
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(stops, stops[1:], strict=False):
        if t <= t1:
            return P.mix(c0, c1, 0 if t1 == t0 else (t - t0) / (t1 - t0))
    return stops[-1][1]


def noise_tile(w, h, strength, seed=1, scale=1.6):
    """Grain/pebble texture (signed offsets, cached) for leather and matte finishes."""
    w, h = max(1, int(w)), max(1, int(h))

    def make():
        rng = np.random.default_rng(seed)
        base = rng.normal(0, 1, (h, w)).astype(np.float32)
        img = Image.fromarray(np.clip(base * 40 + 128, 0, 255).astype(np.uint8), "L")
        img = img.filter(ImageFilter.GaussianBlur(scale))
        arr = (np.asarray(img, dtype=np.float32) - 128) / 40
        # Emboss: light from the top-left makes the pebbles readable as relief.
        relief = arr - np.roll(np.roll(arr, 1, axis=0), 1, axis=1)
        return relief
    relief = cached(("nz", w, h, seed, scale), make)
    return relief * strength


def apply_texture(img, box, strength, seed=1, scale=1.6):
    if strength <= 0.5:
        return
    x0, y0, x1, y1 = P.ibox(box)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    region = np.asarray(img.crop((x0, y0, x1, y1)), dtype=np.float32)
    region += noise_tile(x1 - x0, y1 - y0, strength, seed, scale)[:, :, None]
    img.paste(Image.fromarray(np.clip(region, 0, 255).astype(np.uint8), "RGB"), (x0, y0))


# ---------------------------------------------------------------- icons

def _draw_icon(draw, kind, S, weight):
    """Modern transport icons on an S x S supersampled canvas."""
    lw = max(2, int(S * 0.075 * weight))

    def poly(points):
        draw.polygon([(x * S, y * S) for x, y in points], fill=255)
        # Rounded corners: a thin round-joined outline of the same polygon.
        pts = [(x * S, y * S) for x, y in points]
        draw.line(pts + [pts[0]], fill=255, width=max(1, int(S * 0.05)), joint="curve")

    def cap(x, y, w):
        draw.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=255)

    def path(points, width=None):
        width = width or lw
        pts = [(x * S, y * S) for x, y in points]
        draw.line(pts, fill=255, width=width, joint="curve")
        cap(*pts[0], width)
        cap(*pts[-1], width)

    if kind == "play":
        poly([(0.26, 0.15), (0.84, 0.5), (0.26, 0.85)])
    elif kind == "pause":
        r = S * 0.05
        draw.rounded_rectangle((S * 0.22, S * 0.15, S * 0.41, S * 0.85), radius=r, fill=255)
        draw.rounded_rectangle((S * 0.59, S * 0.15, S * 0.78, S * 0.85), radius=r, fill=255)
    elif kind == "stop":
        draw.rounded_rectangle((S * 0.2, S * 0.2, S * 0.8, S * 0.8), radius=S * 0.08, fill=255)
    elif kind == "next":
        poly([(0.18, 0.18), (0.68, 0.5), (0.18, 0.82)])
        draw.rounded_rectangle((S * 0.7, S * 0.18, S * 0.82, S * 0.82), radius=S * 0.04, fill=255)
    elif kind == "forward":
        poly([(0.06, 0.24), (0.48, 0.5), (0.06, 0.76)])
        poly([(0.5, 0.24), (0.94, 0.5), (0.5, 0.76)])
    elif kind in ("shuffle",):
        path([(0.1, 0.3), (0.3, 0.3), (0.62, 0.7), (0.82, 0.7)])
        path([(0.1, 0.7), (0.3, 0.7), (0.62, 0.3), (0.82, 0.3)])
        for y in (0.3, 0.7):
            poly([(0.76, y - 0.12), (0.93, y), (0.76, y + 0.12)])
    elif kind in ("repeat", "repeat_one"):
        path([(0.2, 0.62), (0.2, 0.32), (0.8, 0.32)])
        path([(0.8, 0.38), (0.8, 0.68), (0.2, 0.68)])
        poly([(0.72, 0.2), (0.86, 0.32), (0.72, 0.44)])
        poly([(0.28, 0.56), (0.14, 0.68), (0.28, 0.8)])
        if kind == "repeat_one":
            draw.rounded_rectangle((S * 0.46, S * 0.4, S * 0.55, S * 0.6), radius=S * 0.02, fill=255)
    elif kind in ("speaker", "vol_low", "vol_high", "mute"):
        poly([(0.08, 0.38), (0.26, 0.38), (0.46, 0.18), (0.46, 0.82), (0.26, 0.62), (0.08, 0.62)])
        if kind == "mute":
            path([(0.62, 0.36), (0.88, 0.64)])
            path([(0.62, 0.64), (0.88, 0.36)])
        else:
            arcs = (0.18,) if kind == "vol_low" else ((0.18, 0.32) if kind == "speaker" else (0.18, 0.31, 0.44))
            for r in arcs:
                box = (S * (0.46 - r), S * (0.5 - r), S * (0.46 + r), S * (0.5 + r))
                draw.arc(box, -48, 48, fill=255, width=max(2, int(lw * 0.8)))
    elif kind == "output":
        draw.rounded_rectangle((S * 0.24, S * 0.06, S * 0.76, S * 0.94), radius=S * 0.1, outline=255, width=lw)
        draw.ellipse((S * 0.36, S * 0.42, S * 0.64, S * 0.7), outline=255, width=lw)
        draw.ellipse((S * 0.45, S * 0.17, S * 0.55, S * 0.27), fill=255)
    elif kind == "note":
        draw.ellipse((S * 0.16, S * 0.6, S * 0.44, S * 0.84), fill=255)
        draw.rectangle((S * 0.38, S * 0.14, S * 0.44, S * 0.72), fill=255)
        poly([(0.4, 0.12), (0.8, 0.24), (0.8, 0.38), (0.4, 0.26)])
    elif kind == "app":
        draw.rounded_rectangle((S * 0.1, S * 0.18, S * 0.9, S * 0.74), radius=S * 0.06, outline=255, width=lw)
        draw.rectangle((S * 0.34, S * 0.82, S * 0.66, S * 0.88), fill=255)
    else:
        draw.ellipse((S * 0.3, S * 0.3, S * 0.7, S * 0.7), fill=255)


MIRRORED = {"previous": "next", "rewind": "forward"}


def icon_mask(kind, size, weight=1.0):
    size = max(4, int(size))

    def make():
        if kind in MIRRORED:
            return ImageOps.mirror(icon_mask(MIRRORED[kind], size, weight))
        S = size * 4
        big = Image.new("L", (S, S), 0)
        _draw_icon(ImageDraw.Draw(big), kind, S, weight)
        return big.resize((size, size), Image.Resampling.LANCZOS)
    return cached(("ic", kind, size, round(weight, 2)), make)


def icon(img, kind, cx, cy, size, color, weight=1.0):
    mask = icon_mask(kind, size, weight)
    img.paste(solid(mask.size, color), (int(round(cx - mask.width / 2)), int(round(cy - mask.height / 2))), mask)


# ---------------------------------------------------------------- layout

class Row:
    __slots__ = ("name", "h", "flex", "drop")

    def __init__(self, name, h, flex=0.0, drop=0):
        self.name, self.h, self.flex, self.drop = name, h, flex, drop


def stack(box, rows, base, gap, valign=0.5):
    """Place ``rows`` top to bottom inside ``box``; drop optional ones that do not fit."""
    x0, y0, x1, y1 = box
    avail = y1 - y0
    rows = list(rows)

    def need(items, scale=1.0):
        return sum(r.h * base * scale for r in items) + gap * max(0, len(items) - 1)
    while need(rows) > avail and any(r.drop for r in rows):
        victim = max((r for r in rows if r.drop), key=lambda r: (r.drop, rows.index(r)))
        rows.remove(victim)
    scale = 1.0
    fixed = sum(r.h * base for r in rows)
    if need(rows) > avail and fixed > 0:
        scale = max(0.55, (avail - gap * max(0, len(rows) - 1)) / fixed)
    extra = avail - need(rows, scale)
    flex_total = sum(r.flex for r in rows)
    y = y0
    if flex_total <= 0 and extra > 0:
        y += extra * valign
    out = {}
    for r in rows:
        h = r.h * base * scale + (extra * r.flex / flex_total if flex_total > 0 and extra > 0 else 0)
        out[r.name] = (x0, y, x1, y + h)
        y += h + gap
    return out, scale


def _r(box):
    return tuple(int(round(v)) for v in box) if box else None


# ---------------------------------------------------------------- the base skin

class ModernSkin(Skin):
    """Common behaviour of the Modern Collection (see the module docstring)."""

    modern = True
    collection = "modern"
    time_inline = True
    has_readout = False
    title_h = 0
    mono = "Lato"                 # face handed to the text helpers; resolved per frame (d.face)
    faces = ("Lato", "Noto Sans")
    art_shape = "rounded"
    art_round = 0.06              # art corner radius, fraction of its side
    art_fit = "auto"
    card_margin = 0.0             # free space around the card (fraction of the short side)
    card_round = 0.05             # card corner radius (fraction of the short side)
    pad_frac = 0.055
    gap_frac = 0.022
    art_frac = 0.42               # landscape: max art width / content width
    art_style = "square"          # square | bleed | captioned
    disc = 0.0                    # vinyl disc peeking out of the art (fraction of the art side)
    portrait_art = 0.46           # portrait: max art height / content height
    rows = ()                     # landscape column rows
    portrait_rows = None
    footer = ()                   # full-width rows under everything (landscape)
    meta = (("title", 1.4, True), ("artist", 1.05, False))
    meta_align = "l"
    caption = False               # captioned art: meta under the art
    light = False
    base_pal = {}
    tint_from_cover = False
    ambient = False               # blurred cover as the card background (bmp_art_background forces it)
    tele_style = "band"
    tele_radius = 0.5
    buttons_style = "icons"
    badge = "logo"                # logo | output | none
    remaining = False             # right time shows the remaining time by default

    # ------------------------------------------------------------ palette
    def palette(self, mode="skin", custom=None, cover=None, tone=None):
        pal = dict(self.base_palette(tone))
        if mode == "contrast":
            if pal.get("light"):
                pal.update(bg=(255, 255, 255), bg2=(255, 255, 255), outer=(225, 225, 225), surface=(240, 240, 240),
                           text=(0, 0, 0), text2=(20, 20, 20), text3=(50, 50, 50), accent=(0, 70, 200),
                           accent2=(0, 40, 140), track=(150, 150, 150), icon=(0, 0, 0), icon_off=(140, 140, 140),
                           knob=(0, 0, 0))
            else:
                pal.update(bg=(0, 0, 0), bg2=(0, 0, 0), outer=(0, 0, 0), surface=(28, 28, 28), text=(255, 255, 255),
                           text2=(240, 240, 240), text3=(210, 210, 210), accent=(255, 214, 0), accent2=(255, 170, 0),
                           track=(95, 95, 95), icon=(255, 255, 255), icon_off=(110, 110, 110), knob=(255, 255, 255))
            pal["stops"] = ((0, pal["accent2"]), (1, pal["accent"]))
            pal["contrast"] = True
        elif mode == "mono":
            grey = P.mix(pal["text2"], pal["text"], 0.5)
            pal.update(accent=grey, accent2=P.shade(grey, 0.75))
            pal["stops"] = ((0, pal["accent2"]), (1, pal["accent"]))
        elif mode == "custom" and custom:
            pal.update(accent=custom, accent2=P.shade(custom, 0.7))
            pal["stops"] = ((0, pal["accent2"]), (1, pal["accent"]))
        elif mode == "cover" and cover:
            vibrant, deep = cover
            if deep is not None and self.tint_from_cover and not pal.get("light"):
                pal["bg"] = deep
                pal["bg2"] = P.shade(deep, 0.6)
                pal["surface"] = P.mix(deep, (255, 255, 255), 0.1)
                pal["track"] = P.mix(deep, (255, 255, 255), 0.22)
            if vibrant is not None:
                accent = P.ensure_contrast(vibrant, pal["bg"], 3.0)
                pal.update(accent=accent, accent2=P.shade(accent, 0.7))
                pal["stops"] = ((0, pal["accent2"]), (1, pal["accent"]))
        if mode != "contrast":
            for key, ratio in (("text", 7.0), ("text2", 4.5), ("text3", 3.0)):
                pal[key] = P.ensure_contrast(pal[key], pal["bg"], ratio)
        pal.setdefault("stops", ((0, pal["accent2"]), (1, pal["accent"])))
        pal.setdefault("mute", (235, 80, 70))
        # Keys the shared engine paths use (micro panels, idle screens, LCD helpers).
        pal.update(body=pal["outer"], lcd_bg=pal["bg"], lcd_fg=pal["text2"], lcd_hi=pal["text"],
                   lcd_dim2=pal["text3"], fill=pal["accent"], time_fg=pal["text3"], btn_glyph=pal["icon"],
                   btn_off=pal["icon_off"], btn_face=pal["surface"], vis_bg=pal["bg"],
                   vis=(pal["accent2"], pal["accent"], P.shade(pal["accent"], 1.3)),
                   tele_bg=pal.get("tele_bg", P.mix(pal["bg"], (0, 0, 0), 0.35)),
                   tele_fg=pal.get("tele_fg", pal["text2"]), tele_accent=pal.get("tele_accent", pal["accent"]),
                   title_bg=pal["bg"], title_fg=pal["text"])
        return pal

    def base_palette(self, tone=None):
        return self.base_pal

    @property
    def pal(self):
        return self._static_pal()

    def _static_pal(self):
        key = ("pal", self.id)
        return cached(key, lambda: self.palette())

    # ------------------------------------------------------------ chrome key
    def chrome_key(self, d):
        return (d.pal_key, d.style_key, d.face, d.art_key if d.ambient else None)

    # ------------------------------------------------------------ layout
    def compute_layout(self, W, H, opts):
        if layout_mod.is_micro(W, H):
            return layout_mod.compute(W, H, self, opts)
        text_scale = layout_mod.TEXT_SCALE.get(opts.get("text_size"), 1.0)
        variant = opts.get("variant", "full")
        aspect = W / H
        mode = "ultrawide" if aspect >= layout_mod.ULTRAWIDE else ("portrait" if H > W * 1.15 else "landscape")
        short = min(W, H)
        if mode == "portrait":
            base = W / (300 / 13)
        elif mode == "ultrawide":
            base = H / 13
        else:
            base = min(H / (300 / 13), W / (440 / 13))
        base = max(10.0, min(28.0, base * text_scale))
        L = layout_mod.Layout(W, H, mode, short / 320, base)
        margin = round(short * self.card_margin)
        card = (margin, margin, W - margin, H - margin)
        L.body = _r(card)
        L.extras["card"] = L.body
        pad = max(4, round(short * self.pad_frac))
        gap = max(3, round(short * self.gap_frac))
        cx0, cy0, cx1, cy1 = card
        x0, y0, x1, y1 = cx0 + pad, cy0 + pad, cx1 - pad, cy1 - pad
        tele = opts.get("tele")
        tele_h = max(13, round(base * 1.45))
        art_scale = layout_mod.ART_SCALE.get(opts.get("art_size"), 1.0)
        if variant == "party":
            art_scale *= 1.15
        if variant == "info":
            art_scale *= 0.8
        cinema = variant == "cinema"
        bleed = self.art_style == "bleed" or (cinema and mode != "ultrawide")
        rows = self._rows(opts, mode, variant)
        footer = [r for r in self.footer if self._row_enabled(r, opts, variant)] if mode == "landscape" else []
        if bleed and footer:
            rows, footer = rows + footer, []          # the picture takes the full height: no full-width footer

        # Telemetry band inside the card (top/bottom); overlay goes over the art later.
        if tele in ("top", "bottom"):
            if tele == "top":
                L.tele = _r((x0, y0, x1, y0 + tele_h))
                y0 += tele_h + gap
            else:
                L.tele = _r((x0, y1 - tele_h, x1, y1))
                y1 -= tele_h + gap
        if footer:
            fh = sum(r.h for r in footer) * base + gap * (len(footer) - 1)
            fbox = (x0, y1 - fh, x1, y1)
            placed, _s = stack(fbox, footer, base, gap)
            self._assign(L, placed, base)
            y1 -= fh + gap

        caption_h = 0
        if self.caption and mode != "ultrawide":
            caption_h = sum(size for _r_, size, _b in self.meta) * base * 1.28 + gap
        if mode == "landscape":
            if bleed:
                aw = (cx1 - cx0) * min(0.5, self.art_frac * art_scale * (1.08 if cinema else 1.0))
                L.art = _r((cx0, cy0, cx0 + aw, cy1))
                if L.tele:
                    # Cinematic: the strip floats over the picture and the stage (semi-transparent).
                    L.tele = _r((cx0 + pad, L.tele[1], x1, L.tele[3]))
                    L.tele_overlay = True
                col = (cx0 + aw + pad, cy0 + pad + (tele_h + gap if tele == "top" else 0), x1,
                       cy1 - pad - (tele_h + gap if tele == "bottom" else 0))
            else:
                avail_h = y1 - y0 - caption_h
                side = min(avail_h, (x1 - x0) * self.art_frac * art_scale / (1 + self.disc * 0.9))
                side = max(24, side)
                ay = y0 + (avail_h - side) / 2 if not self.caption else y0
                L.art = _r((x0, ay, x0 + side, ay + side))
                right = x0 + side
                if self._disc_on(opts):
                    L.extras["disc"] = self._disc_box(L.art)
                    right = L.extras["disc"][2]
                if self.caption:
                    L.extras["caption"] = _r((x0 - gap, ay + side + gap, right + gap, y1))
                col = (right + gap * 2.2, y0, x1, y1)
            placed, scale = stack(col, rows, base, gap, valign=0.5)
            self._assign(L, placed, base * scale)
        elif mode == "portrait":
            if bleed:
                ah = (cy1 - cy0) * min(0.5, self.portrait_art * art_scale)
                L.art = _r((cx0, cy0, cx1, cy0 + ah))
                top = cy0 + ah + gap
                if tele == "top":
                    L.tele = _r((cx0 + pad, cy0 + pad, cx1 - pad, cy0 + pad + tele_h))
                    L.tele_overlay = True                # floats over the picture
                    y0 -= tele_h + gap
            else:
                bw = opts.get("badge_w", 0)
                if bw and self.badge != "none":
                    strip = base * 1.3
                    L.extras["badge"] = _r((x1 - min(bw, (x1 - x0) * 0.5), y0, x1, y0 + strip))
                    y0 += strip + gap * 0.5
                avail = (y1 - y0) * self.portrait_art * art_scale
                side = min((x1 - x0) * 0.8 / (1 + self.disc * 0.6), avail)
                shift = side * self.disc * 0.3 if self._disc_on(opts) else 0
                ax = (x0 + x1) / 2 - side / 2 - shift
                L.art = _r((ax, y0, ax + side, y0 + side))
                if self._disc_on(opts):
                    L.extras["disc"] = self._disc_box(L.art, portrait=True)
                top = y0 + side + gap
                if self.caption:
                    L.extras["caption"] = None
            prow = self._rows(opts, mode, variant, portrait=True)
            placed, scale = stack((x0, top, x1, y1), prow, base, gap, valign=0.0)
            self._assign(L, placed, base * scale)
        else:  # ultrawide
            if bleed:
                aw = (cy1 - cy0) * 1.35
                L.art = _r((cx0, cy0, cx0 + aw, cy1))
                left = cx0 + aw + pad
            else:
                side = y1 - y0
                L.art = _r((x0, y0, x0 + side, y0 + side))
                left = x0 + side + gap * 2
                if self._disc_on(opts):
                    L.extras["disc"] = self._disc_box(L.art)
                    left = L.extras["disc"][2] + gap * 2
            mid_names = {"eyebrow", "meta", "vis", "header"}
            mid = [r for r in rows if r.name in mid_names]
            if self.caption and not any(r.name == "meta" for r in mid):
                mid.insert(0, Row("meta", sum(size for _r_, size, _b in self.meta) * 1.28, 0, 0))
            rest = [r for r in rows if r.name not in mid_names] + [
                r for r in self.footer if self._row_enabled(r, opts, variant)]
            split = left + (x1 - left) * 0.48
            placed, scale = stack((left, y0, split - gap * 2, y1), mid, base, gap)
            self._assign(L, placed, base * scale)
            placed, scale2 = stack((split, y0, x1, y1), rest, base, gap)
            self._assign(L, placed, base * scale2)
            if L.tele:
                L.tele = _r((left, L.tele[1], x1, L.tele[3]))

        self._reserve_badge(L, opts, base)
        if tele == "overlay" and L.art:
            ax0, ay0, ax1, ay1 = L.art
            inset_ = 0 if bleed else max(2, round(base * 0.25))
            L.tele = _r((ax0 + inset_, ay1 - tele_h - inset_, ax1 - inset_, ay1 - inset_))
            L.tele_overlay = True
        if L.info is None:
            L.info = L.extras.get("caption") or _r((x0, y0, x0 + 1, y0 + 1))
            L.extras["text"] = L.info
        if self.caption and L.extras.get("caption"):
            L.info = L.extras["text"] = L.extras["caption"]
        L.lines = max(1, len(self.meta))
        return L

    def _reserve_badge(self, L, opts, base):
        """Room for the distribution logo/name at the top right of the text column."""
        width = opts.get("badge_w", 0)
        if self.badge == "none" or not width or L.extras.get("badge"):
            return
        names = ("header", "eyebrow", "meta") if not self.caption else ("header", "eyebrow", "vis")
        boxes = [(name, L.extras.get(name) if name not in ("meta", "vis") else (L.info if name == "meta" else L.vis))
                 for name in names]
        boxes = [(n, b) for n, b in boxes if b and (n != "meta" or L.extras.get("text") == L.info)]
        if not boxes:
            return
        name, box = min(boxes, key=lambda item: item[1][1])
        x0, y0, x1, y1 = box
        w = min(width, (x1 - x0) * 0.42)
        h = min(base * 1.4, y1 - y0)
        L.extras["badge"] = _r((x1 - w, y0, x1, y0 + h))
        if name == "meta":
            L.extras["badge_cut"] = _r((x1 - w - base * 0.5, y0, x1, y0 + h))
        elif name == "vis":
            L.vis = _r((x0, y0 + h + base * 0.3, x1, y1)) if (y1 - y0) > h * 2.5 else L.vis
        else:
            L.extras[name] = _r((x0, y0, x1 - w - base * 0.5, y1))

    def _row_enabled(self, row, opts, variant):
        name = row.name
        if name in ("controls", "controls_volume") and not opts.get("controls", True):
            if name == "controls_volume" and opts.get("volume", True):
                return True
            return False
        if name in ("volume", "chip_volume") and not opts.get("volume", True):
            return False
        if name == "vis" and not opts.get("vis"):
            return False
        if variant == "compact" and name in ("eyebrow", "chip", "vis", "header"):
            return False
        if variant == "cinema" and name in ("vis", "eyebrow"):
            return False
        if variant == "info" and name == "vis":
            return False
        return True

    def _rows(self, opts, mode, variant, portrait=False):
        source = (self.portrait_rows or (self.rows + tuple(self.footer))) if portrait else self.rows
        rows = []
        for row in source:
            if not self._row_enabled(row, opts, variant):
                continue
            if row.name == "meta":
                h = sum(size for _r_, size, _b in self.meta) * 1.28
                row = Row("meta", max(row.h, h), row.flex, row.drop)
            if row.name == "vis" and variant == "party":
                row = Row("vis", row.h * 1.4, row.flex * 2, row.drop)
            rows.append(row)
        return rows

    def _assign(self, L, placed, base):
        for name, box in placed.items():
            box = _r(box)
            x0, y0, x1, y1 = box
            if name == "meta":
                L.info = box
                L.extras["text"] = box
            elif name == "vis":
                L.vis = box
            elif name == "progress":
                L.progress = box
            elif name == "times":
                L.times = box
            elif name == "progress_times":
                h = y1 - y0
                L.progress = _r((x0, y0, x1, y0 + h * 0.48))
                L.times = _r((x0, y0 + h * 0.5, x1, y1))
                L.extras["times_below"] = True
            elif name == "progress_inline":
                tw = base * 7.0
                L.progress = _r((x0, y0, x1 - tw, y1))
                L.times = _r((x1 - tw + base * 0.6, y0, x1, y1))
                L.extras["times_inline"] = True
            elif name == "controls":
                L.buttons = box
            elif name == "controls_volume":
                split = x0 + (x1 - x0) * 0.6
                L.buttons = _r((x0, y0, split - base * 0.4, y1))
                L.volume = _r((split + base * 0.4, y0, x1, y1))
            elif name == "volume":
                L.volume = box
            else:
                L.extras[name] = box

    def _disc_on(self, opts):
        mode = opts.get("disc", "skin")
        if mode == "hide":
            return False
        return self.disc > 0 or (mode == "show" and self.art_style == "square")

    def _disc_box(self, art, portrait=False):
        x0, y0, x1, y1 = art
        side = x1 - x0
        reach = side * max(self.disc, 0.28)
        d = side * 0.94
        cx = x1 - side / 2 + reach
        cy = (y0 + y1) / 2
        return _r((cx - d / 2, cy - d / 2, cx + d / 2, cy + d / 2))

    # ------------------------------------------------------------ chrome
    def chrome(self, img, L, d):
        pal = d.pal or self.pal
        img.paste(solid((L.W, L.H), pal["outer"]), (0, 0))
        card = L.extras.get("card") or (0, 0, L.W, L.H)
        r = self.card_radius(L, d)
        if self.card_margin and d.shadow:
            short = min(L.W, L.H)
            shadow(img, card, r, max(2, short * 0.03), 0.45 * d.shadow * (0.6 if pal.get("light") else 1.0),
                   offset=(0, short * 0.012))
        self.card_fill(img, card, r, L, d)
        if L.title:
            self.title_text(img, L.title, d, pal["text2"], size=P.height(L.title) * 0.5)

    def card_radius(self, L, d):
        return int(min(L.W, L.H) * self.card_round * d.radius_scale)

    def card_fill(self, img, card, r, L, d):
        pal = d.pal
        w, h = P.width(card), P.height(card)
        if d.ambient and d.art_image is not None:
            tile = ambient_tile(d.art_image, w, h, pal)
        else:
            tile = gradient_tile(w, h, ((0, pal["bg"]), (1, pal["bg2"])), horizontal=False)
        img.paste(tile, card[:2], rrect_mask(w, h, r))

    # ------------------------------------------------------------ art
    def art_radius(self, box, d):
        shape = d.art_shape if d.art_shape != "skin" else self.art_shape
        side = min(P.width(box), P.height(box))
        if shape == "circle":
            return side // 2, "circle"
        if shape == "square":
            return 0, "square"
        scale = getattr(d, "radius_scale", 1.0)
        return max(0, int(side * self.art_round * scale)), "rounded" if scale else "square"

    def art(self, img, box, tile, d):
        radius, shape = self.art_radius(box, d)
        if d.shadow and self.art_style != "bleed":
            side = min(P.width(box), P.height(box))
            shadow(img, box, radius, max(2, side * 0.06), 0.55 * d.shadow, offset=(0, side * 0.03),
                   shape="circle" if shape == "circle" else "rect")
        if d.art_glow:
            d.halo(img, box, radius, shape, d.pal["accent"], 7, filled=True)
        img.paste(tile[0], box[:2], tile[1])
        if d.art_frame not in ("skin", "none"):
            self._art_frame(img, box, radius, shape, d)

    def before_art(self, img, L, d):
        if L.extras.get("disc"):
            self.paint_disc(img, L.extras["disc"], L, d)

    # ------------------------------------------------------------ vinyl disc
    disc_colors = ((14, 14, 16), (30, 30, 34), (60, 60, 66))

    def paint_disc(self, img, box, L, d):
        x0, y0, x1, y1 = box
        art = L.art
        side = P.width(box)
        # The disc slides out while playing and back in when paused (eased by the engine).
        reach = (x1 - P.width(art) / 2 - side / 2) - (art[2] - P.width(art) / 2)
        offset = -reach * (1 - d.play_t) * 0.55
        cx = (x0 + x1) / 2 + offset
        cy = (y0 + y1) / 2
        base, groove, sheen = self.disc_colors
        disc = cached(("disc", side, base, groove, sheen), lambda: _disc_tile(side, base, groove, sheen))
        if d.shadow:
            shadow(img, (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2), side // 2, max(2, side * 0.05),
                   0.6 * d.shadow, offset=(side * 0.01, side * 0.03), shape="circle")
        img.paste(disc, (int(round(cx - side / 2)), int(round(cy - side / 2))), circle_mask(side))
        # Label: the cover itself (or the accent) printed on the record, turning while playing.
        label_d = int(side * 0.36)
        label = cached(("label", d.art_key, label_d, d.disc_angle, d.pal["accent"]),
                       lambda: _label_tile(d.art_image, label_d, d.disc_angle, d.pal["accent"]))
        img.paste(label, (int(round(cx - label_d / 2)), int(round(cy - label_d / 2))), circle_mask(label_d))
        fill_circle(img, cx, cy, max(1.5, side * 0.018), P.shade(base, 0.4))

    # ------------------------------------------------------------ text
    def meta_lines(self, d, idle=False):
        """[(text, size factor, bold, role)] following ``self.meta`` and the visibility switches."""
        out = []
        for role, size, bold in self.meta:
            text = self.meta_text(role, d)
            if text:
                out.append((text, size, bold, role))
        return out

    def meta_text(self, role, d):
        show = d.show
        artist = d.artist if show["artist"] else ""
        album = d.album if show["album"] else ""
        if role == "title":
            return (d.title or _("Unknown title")) if show["title"] else ""
        if role == "artist":
            return artist or (d.description if show["description"] else "") or (d.app if show["source"] else "")
        if role == "album":
            return album
        if role == "artist_album":
            parts = [p for p in (artist, album) if p]
            return " — ".join(parts) or (d.app if show["source"] else "")
        if role == "artist_dot_album":
            parts = [p for p in (artist, album) if p]
            return " • ".join(parts) or (d.app if show["source"] else "")
        if role == "album_dot_artist_caps":
            parts = [p for p in (album, artist) if p]
            return (" • ".join(parts) or (d.app if show["source"] else "")).upper()
        if role == "source":
            return d.app if show["source"] else ""
        return ""

    def role_color(self, role, d):
        pal = d.pal
        return {"title": pal["text"], "source": pal["text3"]}.get(role, pal["text2"])

    def info(self, img, L, d):
        box = L.extras.get("text") or L.info
        if not box:
            return
        x0, y0, x1, y1 = box
        lines = self.meta_lines(d)
        if L.mode == "portrait" or self.caption:
            align = "m"
        else:
            align = self.meta_align
        self.draw_lines(img, (x0, y0, x1, y1), lines, L.font, d, align, cut=L.extras.get("badge_cut"))

    def draw_lines(self, img, box, lines, base, d, align="l", valign=0.5, cut=None):
        x0, y0, x1, y1 = box
        if not lines:
            return
        total = sum(size * base * 1.28 for _t, size, _b, _r_ in lines)
        while total > (y1 - y0) + 1 and len(lines) > 1:
            lines = lines[:-1]
            total = sum(size * base * 1.28 for _t, size, _b, _r_ in lines)
        scale = min(1.0, (y1 - y0) / total) if total else 1.0
        y = y0 + max(0, ((y1 - y0) - total * scale) * valign)
        face = d.face
        for text, size, bold, role in lines:
            s = max(9, size * base * scale)
            lh = s * 1.28
            color = self.role_color(role, d)
            x1 = box[2] if not (cut and y < cut[3] and y + lh > cut[1]) else cut[0]
            if role == "title" and d.marquee:
                P.marquee(img, (x0, y, x1, y + lh), text, s, color, d.scroll(text, s, x1 - x0, bold, face, False,
                                                                             False),
                          bold=bold, mono=face, align=align)
            else:
                shown = P.ellipsize(text, s, x1 - x0, bold, face)
                x = x0 if align == "l" else ((x0 + x1) / 2 if align == "m" else x1)
                P.put_text(img, (x, y + lh / 2), shown, s, color, bold=bold, mono=face, anchor=align + "m")
            y += lh

    def text(self, img, xy, text, size, color, d, bold=False, anchor="lm"):
        return P.put_text(img, xy, text, max(7, size), color, bold=bold, mono=d.face, anchor=anchor)

    # ------------------------------------------------------------ times
    def times(self, img, box, d):
        x0, y0, x1, y1 = box
        size = max(8, min((y1 - y0) * 0.78, d.base * 0.9))
        cy = (y0 + y1) / 2
        right = d.remaining_text if (self.remaining and d.remaining_text) else d.total_text
        color = d.pal["text3"]
        self.text(img, (x0, cy), d.elapsed_text, size, color, d)
        self.text(img, (x1, cy), right, size, color, d, anchor="rm")

    # ------------------------------------------------------------ progress
    def progress(self, img, box, d):
        self.bar(img, box, d.fraction, d, thickness=max(2, P.height(box) * 0.22))

    def bar(self, img, box, frac, d, thickness, track=None, fill=None, stops=None, knob=None, knob_r=None,
            glow=False, live_badge=True):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        pal = d.pal
        track = track or pal["track"]
        t = thickness
        kr = knob_r or 0
        bx0, bx1 = x0 + kr, x1 - kr
        fill_pill(img, bx0, bx1, cy, t, track)
        if frac is None:
            if d.live and live_badge:
                self.live_badge(img, (x0, cy - t * 2.2, x1, cy + t * 2.2), d)
            return None
        fx = bx0 + (bx1 - bx0) * max(0.0, min(1.0, frac))
        if glow and fx - bx0 > t:
            fill_pill(img, bx0 - t * 0.4, fx + t * 0.4, cy, t * 2.4, P.mix(pal["bg"], fill or pal["accent"], 0.28))
        if stops:
            w = int(bx1 - bx0)
            fw = int(fx - bx0)
            if fw >= 1:
                tile = gradient_tile(w, max(1, int(round(t))), stops).crop((0, 0, fw, max(1, int(round(t)))))
                top = int(round(cy - t / 2))
                mask = rrect_mask(w, max(1, int(round(t))), t / 2).crop((0, 0, fw, max(1, int(round(t)))))
                img.paste(tile, (int(bx0), top), mask)
                if fw > t:
                    fill_circle(img, bx0 + fw - t / 2, top + int(round(t)) / 2, t / 2, ramp(stops, fw / max(1, w)))
        else:
            fill_pill(img, bx0, max(bx0 + t, fx), cy, t, fill or pal["accent"])
        if knob:
            self.knob(img, fx, cy, knob_r or t * 1.6, knob, d)
        return fx

    def knob(self, img, cx, cy, r, style, d):
        pal = d.pal
        if d.shadow:
            shadow(img, (cx - r, cy - r, cx + r, cy + r), r, max(1, r * 0.5), 0.5 * d.shadow, offset=(0, r * 0.25),
                   shape="circle")
        if style == "light":
            tile = cached(("knob_l", int(r * 2), pal["knob"]), lambda: _sphere(int(r * 2), P.shade(pal["knob"], 1.1),
                                                                                 P.shade(pal["knob"], 0.82)))
            img.paste(tile, (int(round(cx - tile.width / 2)), int(round(cy - tile.height / 2))),
                      circle_mask(tile.width))
        elif style == "dark":
            face = pal.get("knob_dark", (42, 40, 44))
            tile = cached(("knob_d", int(r * 2), face), lambda: _sphere(int(r * 2), P.shade(face, 1.25),
                                                                       P.shade(face, 0.6)))
            img.paste(tile, (int(round(cx - tile.width / 2)), int(round(cy - tile.height / 2))),
                      circle_mask(tile.width))
            ring(img, cx, cy, r, max(1, r * 0.12), P.shade(face, 0.45))
            fill_circle(img, cx, cy, r * 0.32, P.shade(face, 0.7))
        else:
            fill_circle(img, cx, cy, r, pal["accent"] if style == "accent" else pal["knob"])

    # ------------------------------------------------------------ buttons
    def transport(self, d, toggles=True):
        """[(kind, enabled, active, role)] — role: main | side | toggle."""
        playing = d.status == "Playing"
        caps = d.caps
        main = ("pause" if playing else "play", caps["pause"] if playing else caps["play"], playing, "main")
        prev = (self.prev_glyph, caps["previous"], False, "side")
        nxt = (self.next_glyph, caps["next"], False, "side")
        items = [prev, main, nxt]
        if toggles:
            shuffle, repeat = self.toggle_items(d)
            if shuffle:
                items.insert(0, shuffle)
            if repeat:
                items.append(repeat)
        return items

    prev_glyph = "previous"
    next_glyph = "next"

    def toggle_items(self, d):
        shuffle = repeat = None
        if d.shuffle is not None:
            shuffle = ("shuffle", d.caps["control"], bool(d.shuffle), "toggle")
        if d.loop is not None:
            repeat = ("repeat_one" if d.loop == "Track" else "repeat", d.caps["control"], d.loop != "None", "toggle")
        return shuffle, repeat

    def glyph_color(self, enabled, active, role, d):
        pal = d.pal
        if not enabled:
            return pal["icon_off"]
        if role == "toggle":
            return pal["accent"] if active else pal["icon_off"]
        return pal["icon"]

    def buttons(self, img, box, d):
        """Icon-only transport: big centre key, sides at 70 %, toggles at the ends."""
        x0, y0, x1, y1 = box
        h = y1 - y0
        items = self.transport(d)
        w = x1 - x0
        main = min(h * 0.62, w / 5.2)
        self._icon_row(img, items, box, main, main * 0.72, main * 2.0, d)

    def _icon_row(self, img, items, box, main, side, spacing, d):
        """Centre key, sides at ``spacing``; toggles (when reported) at the ends, kept inside ``box``."""
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        centre = (x0 + x1) / 2
        core = [i for i in items if i[3] != "toggle"]
        toggles = [i for i in items if i[3] == "toggle"]
        half = (x1 - x0) / 2
        if toggles:
            spacing = min(spacing, (half - side * 0.45) / 2)
            main = min(main, spacing * 0.9)
            side = min(side, spacing * 0.8)
        else:
            spacing = min(spacing, half - side * 0.55)
        positions = {0: centre - spacing, 1: centre, 2: centre + spacing}
        for index, (kind, enabled, active, role) in enumerate(core):
            size = main if role == "main" else side
            self.draw_icon(img, kind, positions[index], cy, size, self.glyph_color(enabled, active, role, d), d)
        for kind, enabled, active, role in toggles:
            x = centre - spacing * 2 if kind == "shuffle" else centre + spacing * 2
            self.draw_icon(img, kind, x, cy, side * 0.7, self.glyph_color(enabled, active, role, d), d)

    def draw_icon(self, img, kind, cx, cy, size, color, d):
        icon(img, kind, cx, cy, size, color)

    # ------------------------------------------------------------ volume
    def volume(self, img, box, d):
        self.volume_line(img, box, d)

    def volume_line(self, img, box, d, left="vol_low", right="vol_high", thickness=0.16, knob=None, fill=None,
                    stops=None, percent=None, icon_scale=0.5, icon_color=None):
        x0, y0, x1, y1 = box
        h = y1 - y0
        cy = (y0 + y1) / 2
        pal = d.pal
        muted = bool(d.vol_muted)
        isz = max(8, min(h * icon_scale * 1.6, d.base * 1.25))
        icolor = icon_color or pal["text3"]
        x = x0
        if left:
            icon(img, "mute" if muted else left, x + isz / 2, cy, isz, pal["mute"] if muted else icolor)
            x += isz + d.base * 0.5
        end = x1
        show_pct = d.show_vol_percent if percent is None else percent
        if show_pct:
            ps = max(8, d.base * 0.8)
            label = _("muted") if muted else d.vol_text
            self.text(img, (x1, cy), label, ps, pal["mute"] if muted else pal["text3"], d, anchor="rm")
            end -= P.text_width("100%", ps, False, d.face) + d.base * 0.5
        if right and not show_pct:
            icon(img, right, x1 - isz / 2, cy, isz, icolor)
            end -= isz + d.base * 0.5
        elif right and show_pct and end - x > d.base * 8:
            icon(img, right, end - isz / 2, cy, isz, icolor)
            end -= isz + d.base * 0.5
        t = max(2.0, min(h * thickness * 2, d.base * thickness * 2))
        if end - x < 8 + (t * 3.2 if knob else t):
            return
        frac = None if d.vol_percent is None else min(1.0, d.vol_percent / max(1, d.vol_scale))
        t = max(2.0, min(h * thickness * 2, d.base * thickness * 2))
        kr = t * 1.6 if knob else 0
        colour = pal["track"] if muted else (fill or pal["accent"])
        self.bar(img, (x, y0, end, y1), frac if frac is not None else 0.0, d, t, fill=colour,
                 stops=None if muted else stops, knob=knob, knob_r=kr or None, live_badge=False)

    # ------------------------------------------------------------ visualizer
    def vis(self, img, box, d):
        """Mirrored thin bars (waveform look); ``d.vis_label`` says DECO or FFT."""
        x0, y0, x1, y1 = box
        bands = d.bands
        if not bands:
            return
        pal = d.pal
        w, h = x1 - x0, y1 - y0
        bar_w = max(1.0, d.base * 0.18)
        step = bar_w * 2.4
        n = max(8, int(w / step))
        mid = y0 + h * 0.6
        played = d.fraction if d.fraction is not None else 0.0
        draw = ImageDraw.Draw(img)
        for i in range(n):
            t = i / max(1, n - 1)
            v = _interp(bands, t) * d.shape_at(t)
            x = x0 + i * step + (w - n * step + step - bar_w) / 2
            up = max(1, v * h * 0.58)
            down = max(1, v * h * 0.34)
            colour = ramp(pal["stops"], t) if t <= played else pal["track"]
            draw.rectangle((x, mid - up, x + bar_w - 1, mid - 1), fill=colour)
            draw.rectangle((x, mid + 1, x + bar_w - 1, mid + down), fill=P.mix(pal["bg"], pal["text3"], 0.55))
        self.text(img, (x1, y0 + d.base * 0.4), d.vis_label, max(7, d.base * 0.55), pal["text3"], d, anchor="rm")

    # ------------------------------------------------------------ telemetry
    def tele(self, img, box, d, items, overlay=False, opacity=0.85, slide=0.0):
        x0, y0, x1, y1 = box
        h = y1 - y0
        pal = d.pal
        r = int(h * self.tele_radius)
        if overlay or self.tele_style == "overlay":
            region = img.crop(box).convert("RGBA")
            band = Image.new("RGBA", region.size, (*pal["tele_bg"], int(255 * opacity)))
            region.alpha_composite(band)
            img.paste(region.convert("RGB"), box[:2], rrect_mask(x1 - x0, h, r))
        elif self.tele_style in ("band", "pill", "hud"):
            fill_rrect(img, box, r, pal["tele_bg"])
        self.tele_decor(img, box, d)
        size = max(7, h * 0.56)
        face = "mono" if self.tele_style == "hud" else d.face
        mono = True if face == "mono" else face
        fg, accent = pal["tele_fg"], pal["tele_accent"]
        x = x0 + h * 0.45 + slide
        draw = ImageDraw.Draw(img)
        for index, (ico, label, value, alert) in enumerate(items):
            text = f"{label} {value}" if label else value
            needed = P.text_width(text, size, mono=mono) + (h * 0.8 if ico is not None and d.tele_icons else 0)
            if x + needed + (h * 0.45 if index else 0) > x1 - h * 0.3:
                break
            if index:
                if d.tele_sep == "bar":
                    draw.line((x + h * 0.2, y0 + h * 0.28, x + h * 0.2, y1 - h * 0.28), fill=P.mix(fg, pal["bg"], 0.55))
                    x += h * 0.45
                elif d.tele_sep == "dot":
                    fill_circle(img, x + h * 0.22, (y0 + y1) / 2, max(1.2, h * 0.06), P.mix(fg, pal["bg"], 0.4))
                    x += h * 0.45
                else:
                    x += h * 0.35
            if ico is not None and d.tele_icons:
                tile = ico(int(h * 0.58), (240, 90, 70) if alert else accent)
                if tile is not None:
                    img.paste(tile, (int(x), int(y0 + (h - tile.height) / 2)), tile)
                    x += tile.width + 2
            x += P.put_text(img, (x, (y0 + y1) / 2), text, size, (240, 90, 70) if alert else fg, mono=mono)

    def tele_decor(self, img, box, d):
        pass

    # ------------------------------------------------------------ extras and overlays
    def extras(self, img, L, d):
        """Badge (distribution logo or output), eyebrow, chip: painted after the main areas."""
        if L.extras.get("eyebrow"):
            self.eyebrow(img, L.extras["eyebrow"], d)
        if L.extras.get("chip"):
            self.chip(img, L.extras["chip"], d)
        if L.mode != "micro":
            self.badge_area(img, L, d)

    def eyebrow(self, img, box, d):
        x0, y0, x1, y1 = box
        text = d.app if d.show["source"] else ""
        if not text:
            return
        size = max(8, min(P.height(box) * 0.8, d.base * 0.9))
        align = self.eyebrow_align
        x = x0 if align == "l" else (x0 + x1) / 2
        self.text(img, (x, (y0 + y1) / 2), P.ellipsize(text, size, x1 - x0, False, d.face), size, d.pal["text3"], d,
                  anchor=align + "m")

    def chip(self, img, box, d):
        """Output device (when known and enabled) or the source application, as a pill."""
        x0, y0, x1, y1 = box
        h = min(y1 - y0, d.base * 2.0)
        label, kind = (d.output, "output") if d.output else (d.app, "app")
        if not label:
            return
        size = max(8, h * 0.42)
        tw = min(P.text_width(label, size, False, d.face), (x1 - x0) - h * 1.8)
        w = tw + h * 1.6
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        pill = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        fill_rrect(img, pill, h / 2, d.pal["surface"])
        icon(img, kind, pill[0] + h * 0.58, cy, h * 0.5, d.pal["text2"])
        self.text(img, (pill[0] + h * 1.05, cy), P.ellipsize(label, size, tw + 1, False, d.face), size, d.pal["text"],
                  d)

    badge_corner = "tr"
    eyebrow_align = "l"

    def badge_area(self, img, L, d):
        if self.badge == "none" or d.logo_style == "none" or d.logo is None:
            return
        card = L.extras.get("card") or (0, 0, L.W, L.H)
        size = int(max(10, min(L.font * 1.15, min(L.W, L.H) * 0.07)))
        pad = max(4, round(min(L.W, L.H) * self.pad_frac * 0.6))
        box = L.extras.get("badge")
        if box:
            x1, cy = box[2], (box[1] + box[3]) / 2
        elif self.badge_corner == "tr":
            x1, cy = card[2] - pad, card[1] + pad + size / 2
        else:
            x1, cy = card[2] - pad, card[3] - pad - size / 2
        self.draw_badge(img, x1, cy, size, d, L)

    def draw_badge(self, img, x1, cy, size, d, L):
        x = x1
        if d.distro and d.logo_style in ("name", "logo_name") and badge_width(d.logo_style, d.distro, L.font, L.W) > \
                L.font * 1.6:
            ts = max(8, size * 0.62)
            x -= self.text(img, (x, cy), d.distro, ts, d.pal["text3"], d, anchor="rm") + size * 0.3
        if d.logo_style in ("logo", "logo_name"):
            logo = d.logo_at(size)
            if logo is not None:
                img.paste(logo, (int(x - logo.width), int(cy - logo.height / 2)), logo)

    def overlay(self, img, L, d):
        if d.osd is not None:
            draw_volume_osd(img, L, d, d.pal)
        if d.banner is not None:
            self.track_banner(img, L, d)

    def track_banner(self, img, L, d):
        """New track: title and artist slide in over the bottom of the art for a few seconds."""
        box = L.art or L.info
        if not box or not d.title:
            return
        x0, y0, x1, y1 = box
        h = min(P.height(box) * 0.32, L.font * 3.2)
        t = d.banner
        rise = min(1.0, t / 0.25, (3.0 - t) / 0.3) if t < 3 else 0
        if rise <= 0:
            return
        band = (x0, y1 - h * rise, x1, y1)
        region = img.crop(P.ibox(band)).convert("RGBA")
        region.alpha_composite(Image.new("RGBA", region.size, (*P.shade(d.pal["bg"], 0.5), 205)))
        img.paste(region.convert("RGB"), P.ibox(band)[:2])
        size = max(9, h * 0.34)
        self.text(img, (x0 + h * 0.25, band[1] + h * 0.34), P.ellipsize(d.title, size, P.width(box) - h * 0.5, True,
                                                                         d.face), size, d.pal["text"], d, bold=True)
        sub = d.artist or d.app
        if sub:
            self.text(img, (x0 + h * 0.25, band[1] + h * 0.72), P.ellipsize(sub, size * 0.8, P.width(box) - h * 0.5,
                                                                             False, d.face), size * 0.8,
                      d.pal["text2"], d)

    def live_badge(self, img, box, d, text=None):
        x0, y0, x1, y1 = box
        h = min(y1 - y0, d.base * 1.3)
        text = text or _("LIVE")
        size = max(7, h * 0.6)
        w = P.text_width(text, size, True, d.face) + h * 0.9
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        fill_rrect(img, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), h / 2, (200, 36, 48))
        self.text(img, (cx, cy), text, size, (255, 255, 255), d, bold=True, anchor="mm")


def badge_width(logo_style, distro, base, W):
    """Room reserved for the distribution mark (logo, and its name on wide panels)."""
    if logo_style == "none":
        return 0
    width = base * 1.5 if logo_style in ("logo", "logo_name") else 0
    if distro and logo_style in ("name", "logo_name") and W >= 420:
        width += P.text_width(distro, max(8, base * 0.72)) + base * 0.4
    return width


def ambient_tile(image, w, h, pal):
    """Blurred, toned-down cover filling the card (cached per cover and size)."""
    key = ("amb", id(image), w, h, pal["bg"], bool(pal.get("light")))

    def make():
        small = P.cover_fit(image.convert("RGB"), (max(8, w // 8), max(8, h // 8)))
        small = small.filter(ImageFilter.GaussianBlur(max(1.5, min(w, h) / 80)))
        tile = small.resize((w, h), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(max(2, min(w, h) / 40)))
        arr = np.asarray(tile, dtype=np.float32)
        if pal.get("light"):
            arr = arr * 0.18 + np.array(pal["bg"], dtype=np.float32) * 0.82
        else:
            lum = float((arr @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)).mean()) / 255
            arr = arr * min(1.0, 0.16 / max(0.01, lum)) * 0.85
            arr = arr * 0.7 + np.array(pal["bg"], dtype=np.float32) * 0.3
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return cached(key, make)


def _interp(values, t):
    if not values:
        return 0.0
    pos = t * (len(values) - 1)
    i = int(pos)
    j = min(len(values) - 1, i + 1)
    return values[i] + (values[j] - values[i]) * (pos - i)


def track_shape(seed_text, count=96):
    """A per-track, deterministic envelope for the decorative waveform (not audio data)."""
    seed = zlib.crc32((seed_text or "").encode("utf-8", "replace"))
    rng = np.random.default_rng(seed)
    raw = rng.random(count)
    smooth = np.convolve(raw, np.ones(5) / 5, mode="same")
    env = 0.45 + 0.55 * np.sin(np.linspace(0.2, math.pi - 0.2, count)) ** 0.6
    shape = np.clip(0.35 + 0.65 * smooth * env * 1.5, 0.15, 1.0)
    return [float(v) for v in shape]


def _sphere(d, top, bottom):
    """Small glossy disc (knob face): vertical gradient with a soft highlight."""
    d = max(2, d)
    tile = Image.new("RGB", (d, d))
    P.vgrad(tile, (0, 0, d, d), top, bottom)
    hl = Image.new("L", (d, d), 0)
    ImageDraw.Draw(hl).ellipse((d * 0.2, d * 0.08, d * 0.8, d * 0.5), fill=70)
    hl = hl.filter(ImageFilter.GaussianBlur(max(1, d / 10)))
    return Image.composite(Image.new("RGB", (d, d), (255, 255, 255)), tile, hl)


def _disc_tile(side, base, groove, sheen):
    side = max(8, int(side))
    S = 2
    big = Image.new("RGB", (side * S, side * S), base)
    draw = ImageDraw.Draw(big)
    c = side * S / 2
    step = max(2, int(side * S / 90))
    for k, r in enumerate(range(int(c * 0.38), int(c * 0.97), step)):
        colour = groove if k % 3 else P.mix(base, groove, 0.5)
        draw.ellipse((c - r, c - r, c + r, c + r), outline=colour, width=1)
    draw.ellipse((c - c * 0.97, c - c * 0.97, c + c * 0.97, c + c * 0.97), outline=P.mix(base, groove, 1.6 / 3),
                 width=max(1, S))
    disc = big.resize((side, side), Image.Resampling.LANCZOS)
    # Two soft specular wedges, as a record reflects a ceiling light.
    light = Image.new("L", (side, side), 0)
    ImageDraw.Draw(light).pieslice((0, 0, side - 1, side - 1), 200, 235, fill=60)
    ImageDraw.Draw(light).pieslice((0, 0, side - 1, side - 1), 20, 55, fill=45)
    light = light.filter(ImageFilter.GaussianBlur(max(1, side / 18)))
    return Image.composite(Image.new("RGB", (side, side), sheen), disc, light)


def _label_tile(image, d, angle, accent):
    d = max(4, int(d))
    if image is not None:
        label = P.cover_fit(image.convert("RGB"), (d, d))
    else:
        label = Image.new("RGB", (d, d), accent)
        draw = ImageDraw.Draw(label)
        draw.ellipse((d * 0.12, d * 0.12, d * 0.88, d * 0.88), outline=P.shade(accent, 0.7), width=max(1, d // 20))
    draw = ImageDraw.Draw(label)
    # A printed mark makes the rotation visible even on a uniform cover.
    draw.rectangle((d * 0.47, d * 0.06, d * 0.53, d * 0.24), fill=P.mix(accent, (255, 255, 255), 0.6))
    if angle:
        label = label.rotate(-angle, Image.Resampling.BILINEAR)
    return label


def draw_volume_osd(img, L, d, pal):
    """Temporary enlarged volume after a change (fades out by itself)."""
    W, H = L.W, L.H
    short = min(W, H)
    w, h = min(W * 0.62, short * 1.1), short * 0.3
    cx, cy = W / 2, H / 2
    box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    region = img.crop(P.ibox(box)).convert("RGBA")
    region.alpha_composite(Image.new("RGBA", region.size, (*P.shade(pal["lcd_bg"], 0.55), 225)))
    r = int(h * 0.22)
    img.paste(region.convert("RGB"), P.ibox(box)[:2], rrect_mask(P.width(P.ibox(box)), P.height(P.ibox(box)), r))
    muted = bool(d.vol_muted)
    isz = h * 0.42
    fg = pal["lcd_hi"]
    icon(img, "mute" if muted else "vol_high", box[0] + h * 0.45, cy - h * 0.1, isz,
         pal.get("mute", (235, 80, 70)) if muted else fg)
    face = getattr(d, "face", False)
    size = h * 0.34
    P.put_text(img, (box[2] - h * 0.3, cy - h * 0.1), _("muted") if muted else d.vol_text, size, fg, bold=True,
               mono=face, anchor="rm")
    frac = 0 if (d.vol_percent is None or muted) else min(1.0, d.vol_percent / max(1, d.vol_scale))
    bx0, bx1 = box[0] + h * 0.3, box[2] - h * 0.3
    t = max(3, h * 0.08)
    fill_pill(img, bx0, bx1, cy + h * 0.28, t, P.mix(pal["lcd_bg"], fg, 0.25))
    if frac > 0:
        fill_pill(img, bx0, bx0 + max(t, (bx1 - bx0) * frac), cy + h * 0.28, t, pal.get("fill", fg))


def cover_colors(image):
    """(vibrant, deep) colours of a cover: an accent and a dark background tint."""
    vibrant = P.dominant_color(image)
    small = np.asarray(image.convert("RGB").resize((16, 16), Image.Resampling.BILINEAR), dtype=np.float64)
    avg = small.reshape(-1, 3).mean(axis=0)
    # Keep the hue, cap the saturation, darken to a luminance where white text reads (> 12:1).
    grey = avg.mean()
    avg = grey + (avg - grey) * 0.75
    low, high = 0.0, 1.0
    for _step in range(14):
        k = (low + high) / 2
        if P.luminance(tuple(avg * k)) > 0.028:
            high = k
        else:
            low = k
    deep = tuple(int(max(6, min(255, c * low))) for c in avg)
    return vibrant, deep
