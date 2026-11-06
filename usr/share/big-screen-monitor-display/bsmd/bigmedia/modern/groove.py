"""Big Groove: pebbled dark leather, the cover in front of a record, a coloured corner tab,
letterpress titles and a magenta-to-amber progress gradient on matte round keys."""

from PIL import ImageDraw

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row

GRADIENT = ((0, (217, 34, 145)), (0.4, (234, 68, 85)), (0.8, (247, 161, 59)), (1, (250, 205, 90)))


class BigGroove(B.ModernSkin):
    id = "big_groove"
    name = "Big Groove"
    description = N_("Dark leather texture, cover over a record with a coloured corner tab and a vivid "
                     "magenta-to-amber progress bar.")
    faces = ("Roboto", "Noto Sans", "Lato")
    card_margin = 0.03
    card_round = 0.035
    art_round = 0.0
    art_shape = "square"
    art_frac = 0.38
    disc = 0.3
    rows = (Row("meta", 3.6, flex=1.0), Row("progress", 1.6), Row("times", 1.15, drop=1),
            Row("controls_volume", 3.0))
    meta = (("title", 1.65, True), ("artist_dot_album", 1.02, True))
    badge = "none"                 # the distribution logo lives in the corner tab of the cover
    tele_radius = 0.2
    base_pal = {
        "bg": (36, 36, 40), "bg2": (24, 24, 27), "outer": (14, 14, 16), "surface": (48, 48, 53),
        "text": (150, 150, 158), "text2": (122, 122, 130), "text3": (112, 112, 120),
        "accent": (234, 68, 85), "accent2": (217, 34, 145), "track": (10, 10, 12),
        "icon": (150, 150, 158), "icon_off": (70, 70, 76), "knob": (60, 60, 66), "knob_dark": (56, 56, 62),
        "tele_bg": (20, 20, 23), "tele_fg": (170, 170, 178), "tele_accent": (240, 110, 80),
        "stops": GRADIENT, "time_hi": (240, 106, 58),
    }
    disc_colors = ((12, 12, 13), (28, 28, 31), (64, 64, 70))

    def palette(self, mode="skin", custom=None, cover=None, tone=None):
        pal = super().palette(mode, custom, cover, tone)
        if mode == "skin":
            pal["stops"] = GRADIENT
        elif mode != "contrast":
            a = pal["accent"]
            pal["stops"] = ((0, P.shade(a, 0.6)), (0.6, a), (1, P.mix(a, (255, 230, 140), 0.45)))
        pal["time_hi"] = pal["accent"] if mode != "skin" else pal["time_hi"]
        return pal

    def chrome(self, img, L, d):
        super().chrome(img, L, d)
        card = L.extras.get("card") or (0, 0, L.W, L.H)
        # Leather outside the card too: the panel sits in a textured case.
        strength = d.texture * 22
        if strength > 0.5:
            x0, y0, x1, y1 = card
            for box in ((0, 0, L.W, y0), (0, y1, L.W, L.H), (0, y0, x0, y1), (x1, y0, L.W, y1)):
                if P.width(box) > 1 and P.height(box) > 1:
                    B.apply_texture(img, box, strength * 0.7, seed=21, scale=1.1)

    def card_fill(self, img, card, r, L, d):
        super().card_fill(img, card, r, L, d)
        x0, y0, x1, y1 = card
        B.apply_texture(img, P.inset(card, 1), d.texture * 22, seed=17, scale=1.2)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=r, outline=(70, 70, 76))
        draw.rounded_rectangle((x0 + 1, y0 + 1, x1 - 2, y1 - 2), radius=max(0, r - 1), outline=(8, 8, 9))

    def role_color(self, role, d):
        return d.pal["text"] if role == "title" else d.pal["text2"]

    def draw_lines(self, img, box, lines, base, d, align="l", valign=0.5, cut=None):
        # Letterpress: every line is drawn once in shadow (1 px up) and once lit (1 px down) under the ink.
        x0, y0, x1, y1 = box
        if d.pal.get("contrast"):
            return super().draw_lines(img, box, lines, base, d, align, valign, cut)
        saved = d.pal
        try:
            d.pal = dict(saved, text=(8, 8, 9), text2=(8, 8, 9))
            super().draw_lines(img, (x0, y0 - 1, x1, y1 - 1), lines, base, d, align, valign, cut)
            d.pal = dict(saved, text=(70, 70, 76), text2=(62, 62, 68))
            super().draw_lines(img, (x0, y0 + 1, x1, y1 + 1), lines, base, d, align, valign, cut)
        finally:
            d.pal = saved
        super().draw_lines(img, box, lines, base, d, align, valign, cut)

    def art(self, img, box, tile, d):
        super().art(img, box, tile, d)
        x0, y0, x1, y1 = box
        side = min(x1 - x0, y1 - y0)
        tab = side * 0.26
        mask = B.cached(("tab", int(tab)), lambda: _corner_mask(int(tab)))
        grad = B.gradient_tile(int(tab), int(tab), d.pal["stops"][:2] if not d.pal.get("contrast") else
                               ((0, d.pal["accent"]), (1, d.pal["accent"])), horizontal=True)
        img.paste(grad, (x0, y0), mask)
        if d.logo is not None and d.logo_style != "none":
            logo = d.logo_at(int(tab * 0.42))
            if logo is not None:
                img.paste(logo, (int(x0 + tab * 0.1), int(y0 + tab * 0.1)), logo)

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        t = max(4, min(P.height(box) * 0.42, d.base * 0.6))
        cy = (y0 + y1) / 2
        kr = t * 1.5
        B.fill_pill(img, x0, x1, cy, t + 3, (4, 4, 5))
        B.fill_pill(img, x0 + 1, x1 - 1, cy + 1, t + 1, (54, 54, 60))
        B.fill_pill(img, x0 + 1, x1 - 1, cy, t + 1, d.pal["track"])
        self.bar(img, (x0 + 1, y0, x1 - 1, y1), d.fraction, d, t, stops=d.pal["stops"], knob="dark", knob_r=kr,
                 glow=False)

    def times(self, img, box, d):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        size = P.fit_size(f"{d.elapsed_text} · {d.total_text}", min(P.height(box) * 0.78, d.base * 0.95), x1 - x0,
                          True, d.face, minimum=8)
        w = self.text(img, (x1, cy), f" · {d.total_text}", size, d.pal["text3"], d, bold=True, anchor="rm")
        self.text(img, (x1 - w, cy), d.elapsed_text, size, d.pal["time_hi"], d, bold=True, anchor="rm")

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        cy = (y0 + y1) / 2
        items = self.transport(d)
        main = next(i for i in items if i[3] == "main")
        sides = [i for i in items if i[3] == "side"]
        toggles = [i for i in items if i[3] == "toggle"]
        R = min(h * 0.47, (x1 - x0) / 5.6)
        r = R * 0.72
        x = x0 + R
        self.rubber_key(img, x, cy, R, main, d)
        x += R + r * 1.3
        for item in sides:
            self.rubber_key(img, x, cy, r, item, d)
            x += r * 2.25
        for kind, enabled, active, role in toggles:
            if x + r * 0.5 > x1:
                break
            B.icon(img, kind, x, cy, r * 0.8, self.glyph_color(enabled, active, role, d))
            x += r * 1.35

    def rubber_key(self, img, cx, cy, r, item, d):
        kind, enabled, active, role = item
        if d.shadow:
            B.shadow(img, (cx - r, cy - r, cx + r, cy + r), r, max(2, r * 0.4), 0.85 * d.shadow,
                     offset=(0, r * 0.2), shape="circle")
        size = int(r * 2)

        def make():
            tile = B.gradient_tile(size, size, ((0, (64, 64, 70)), (1, (32, 32, 36))), horizontal=False).copy()
            draw = ImageDraw.Draw(tile)
            draw.ellipse((size * 0.07, size * 0.07, size * 0.93, size * 0.93), fill=(44, 44, 49))
            draw.arc((size * 0.07, size * 0.07, size * 0.93, size * 0.93), 200, 340, fill=(30, 30, 34),
                     width=max(1, size // 28))
            return tile
        face = B.cached(("groove_key", size), make)
        img.paste(face, (int(round(cx - size / 2)), int(round(cy - size / 2))), B.circle_mask(size))
        colour = self.glyph_color(enabled, active, role, d)
        B.icon(img, kind, cx + (r * 0.06 if kind == "play" else 0), cy, r * 0.74, colour)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        line_h = min(y1 - y0, d.base * 1.5)
        self.volume_line(img, (x0, cy - line_h / 2, x1, cy + line_h / 2), d, left="speaker", right=None,
                         thickness=0.12, knob="dark", stops=d.pal["stops"][:2], icon_color=d.pal["accent"])

    def tele_decor(self, img, box, d):
        x0, y0, x1, y1 = box
        w = max(1, int(x1 - x0 - 8))
        img.paste(B.gradient_tile(w, 2, d.pal["stops"]), (int(x0 + 4), int(y0)))


def _corner_mask(size):
    S = size * 4
    from PIL import Image
    big = Image.new("L", (S, S), 0)
    ImageDraw.Draw(big).polygon([(0, 0), (S, 0), (0, S)], fill=255)
    return big.resize((size, size), Image.Resampling.LANCZOS)
