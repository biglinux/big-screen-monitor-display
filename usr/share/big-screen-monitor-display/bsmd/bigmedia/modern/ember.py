"""Big Ember: near-black premium hi-fi panel, a large photographic cover with a record
peeking out, amber progress light, dark round keys and a short amber volume line."""

from PIL import ImageDraw

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row


class BigEmber(B.ModernSkin):
    id = "big_ember"
    name = "Big Ember"
    description = N_("Black premium audio panel: large cover, amber-lit progress bar, dark round keys "
                     "with soft rims.")
    faces = ("Noto Sans", "Lato")
    card_margin = 0.022
    card_round = 0.022
    pad_frac = 0.05
    art_round = 0.0
    art_shape = "square"
    art_frac = 0.4
    disc = 0.16
    rows = (Row("meta", 3.6, flex=1.0), Row("times", 1.2, drop=1), Row("progress", 1.5),
            Row("controls_volume", 3.1))
    meta = (("title", 1.75, False), ("album_dot_artist_caps", 0.92, False))
    tele_radius = 0.18
    base_pal = {
        "bg": (30, 27, 30), "bg2": (16, 15, 18), "outer": (8, 8, 9), "surface": (44, 40, 44),
        "text": (243, 243, 243), "text2": (160, 156, 160), "text3": (138, 134, 140),
        "accent": (241, 138, 39), "accent2": (190, 80, 22), "track": (6, 5, 6),
        "icon": (196, 192, 198), "icon_off": (88, 84, 90), "knob": (60, 56, 60), "knob_dark": (52, 48, 52),
        "tele_bg": (12, 11, 13), "tele_fg": (255, 173, 68), "tele_accent": (241, 138, 39),
        "stops": ((0, (176, 70, 18)), (0.55, (241, 138, 39)), (1, (255, 186, 92))),
    }
    disc_colors = ((16, 15, 17), (34, 31, 34), (70, 64, 70))

    def palette(self, mode="skin", custom=None, cover=None, tone=None):
        pal = super().palette(mode, custom, cover, tone)
        if mode == "skin":
            pal["stops"] = self.base_pal["stops"]
        else:
            a = pal["accent"]
            pal["stops"] = ((0, P.shade(a, 0.7)), (0.55, a), (1, P.mix(a, (255, 255, 255), 0.3)))
        return pal

    def card_fill(self, img, card, r, L, d):
        super().card_fill(img, card, r, L, d)
        x0, y0, x1, y1 = card
        B.apply_texture(img, P.inset(card, 2), d.texture * 5, seed=9, scale=0.7)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=r, outline=(58, 53, 58))
        draw.line((x0 + r, y0 + 1, x1 - r, y0 + 1), fill=(78, 72, 78))

    def times(self, img, box, d):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        size = P.fit_size(f"{d.elapsed_text} / {d.total_text}", min(P.height(box) * 0.75, d.base * 1.0), x1 - x0,
                          False, d.face, minimum=8)
        w = self.text(img, (x1, cy), f" / {d.total_text}", size, d.pal["text2"], d, anchor="rm")
        self.text(img, (x1 - w, cy), d.elapsed_text, size, d.pal["accent"], d, anchor="rm")

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        t = max(4, min(P.height(box) * 0.42, d.base * 0.55))
        cy = (y0 + y1) / 2
        kr = t * 1.45
        # Recessed black channel with a lit lower lip.
        B.fill_pill(img, x0, x1, cy, t + 3, (0, 0, 0))
        B.fill_pill(img, x0 + 1, x1 - 1, cy + 1, t + 1, (52, 48, 52))
        B.fill_pill(img, x0 + 1, x1 - 1, cy, t + 1, (4, 4, 5))
        self.bar(img, (x0 + 1, y0, x1 - 1, y1), d.fraction, d, t, stops=d.pal["stops"], knob="dark", knob_r=kr,
                 glow=d.glow, fill=d.pal["accent"])

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        cy = (y0 + y1) / 2
        items = self.transport(d)
        main = next(i for i in items if i[3] == "main")
        sides = [i for i in items if i[3] == "side"]
        toggles = [i for i in items if i[3] == "toggle"]
        R = min(h * 0.46, (x1 - x0) / 5.4)
        r = R * 0.68
        x = x0 + R
        self.round_key(img, x, cy, R, main, d)
        x += R + r * 1.25
        for item in sides:
            self.round_key(img, x, cy, r, item, d)
            x += r * 2.3
        for kind, enabled, active, role in toggles:
            if x + r * 0.6 > x1:
                break
            B.icon(img, kind, x, cy, r * 0.85, self.glyph_color(enabled, active, role, d))
            x += r * 1.4

    def round_key(self, img, cx, cy, r, item, d):
        kind, enabled, active, role = item
        if d.shadow:
            B.shadow(img, (cx - r, cy - r, cx + r, cy + r), r, max(2, r * 0.35), 0.75 * d.shadow,
                     offset=(0, r * 0.18), shape="circle")
        face = self.key_face(int(r * 2), d)
        img.paste(face, (int(round(cx - face.width / 2)), int(round(cy - face.height / 2))), B.circle_mask(face.width))
        B.ring(img, cx, cy, r, max(1, r * 0.06), (12, 11, 12))
        colour = d.pal["accent"] if (active and role == "main" and d.glow) else self.glyph_color(enabled, active,
                                                                                               role, d)
        B.icon(img, kind, cx + (r * 0.06 if kind == "play" else 0), cy, r * 0.82, colour)

    def key_face(self, size, d):
        def make():
            tile = B.gradient_tile(size, size, ((0, (70, 65, 70)), (0.5, (42, 39, 42)), (1, (24, 22, 24))),
                                   horizontal=False).copy()
            draw = ImageDraw.Draw(tile)
            # Lit rim on the upper half: brushed metal edge catching the room light.
            draw.arc((1, 1, size - 2, size - 2), 200, 340, fill=(120, 112, 120), width=max(1, size // 30))
            draw.ellipse((size * 0.08, size * 0.08, size * 0.92, size * 0.92), outline=(30, 28, 30))
            return tile
        return B.cached(("ember_key", size), make)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        cy = (y0 + y1) / 2
        line_h = min(h, d.base * 1.6)
        self.volume_line(img, (x0, cy - line_h / 2, x1, cy + line_h / 2), d, left="speaker", right=None,
                         thickness=0.13, knob="dark", stops=d.pal["stops"])

    def tele_decor(self, img, box, d):
        x0, y0, x1, y1 = box
        ImageDraw.Draw(img).line((x0 + 4, y0, x1 - 4, y0), fill=P.mix(d.pal["accent"], d.pal["tele_bg"], 0.6))
