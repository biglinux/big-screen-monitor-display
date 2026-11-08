"""Big Pure: a matte white object floating on a pale ground; soft shadows, thin lines,
large light-grey symbols and quiet typography (white, beige, grey or graphite)."""

from PIL import ImageDraw

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row

TONES = {
    "white": {"bg": (249, 249, 247), "bg2": (236, 236, 234), "outer": (226, 223, 218)},
    "beige": {"bg": (248, 243, 235), "bg2": (235, 228, 216), "outer": (220, 211, 196)},
    "grey": {"bg": (242, 243, 245), "bg2": (226, 228, 232), "outer": (204, 207, 213)},
    "graphite": {"bg": (54, 55, 59), "bg2": (40, 41, 45), "outer": (24, 25, 27), "light": False,
                 "text": (238, 238, 240), "text2": (172, 172, 178), "text3": (140, 140, 147),
                 "accent": (196, 196, 202), "accent2": (150, 150, 156), "track": (30, 30, 33),
                 "icon": (206, 206, 212), "icon_off": (92, 92, 98), "knob": (226, 226, 230),
                 "surface": (64, 65, 70), "tele_fg": (180, 180, 186), "tele_accent": (206, 206, 212),
                 "emboss": (30, 30, 33)},
}


class BigPure(B.ModernSkin):
    id = "big_pure"
    name = "Big Pure"
    description = N_("Minimal matte white panel with soft relief, thin progress line and large light-grey "
                     "symbols. White, beige, grey or graphite.")
    faces = ("Lato", "Cantarell", "Noto Sans")
    card_margin = 0.05
    card_round = 0.085
    pad_frac = 0.06
    art_round = 0.05
    art_frac = 0.36
    rows = (Row("meta", 3.4, flex=1.0), Row("progress_times", 2.0), Row("controls", 2.8),
            Row("volume", 1.3, drop=2))
    meta = (("artist", 1.1, False), ("title", 1.85, False), ("album", 0.9, False))
    tele_style = "text"
    light = True
    base_pal = {
        "light": True, "bg": (249, 249, 247), "bg2": (236, 236, 234), "outer": (226, 223, 218),
        "surface": (238, 238, 236), "text": (98, 98, 98), "text2": (140, 140, 140), "text3": (150, 150, 148),
        "accent": (176, 176, 174), "accent2": (150, 150, 148), "track": (222, 222, 220),
        "icon": (150, 150, 148), "icon_off": (212, 212, 210), "knob": (255, 255, 255),
        "tele_bg": (240, 240, 238), "tele_fg": (130, 130, 128), "tele_accent": (165, 165, 163),
        "emboss": (255, 255, 255), "mute": (200, 90, 80),
    }

    def base_palette(self, tone=None):
        pal = dict(self.base_pal)
        pal.update(TONES.get(tone or "white", TONES["white"]))
        return pal

    def card_fill(self, img, card, r, L, d):
        super().card_fill(img, card, r, L, d)
        x0, y0, x1, y1 = card
        draw = ImageDraw.Draw(img)
        # Raised matte surface: bright top edge, faint darker lower edge.
        edge = P.mix(d.pal["bg"], (255, 255, 255), 0.8 if d.pal.get("light") else 0.1)
        draw.line((x0 + r, y0, x1 - r, y0), fill=edge)
        draw.line((x0 + r, y1 - 1, x1 - r, y1 - 1), fill=P.shade(d.pal["bg2"], 0.93))

    def art(self, img, box, tile, d):
        radius, shape = self.art_radius(box, d)
        side = min(P.width(box), P.height(box))
        if d.shadow:
            B.shadow(img, box, radius, max(2, side * 0.08), 0.32 * d.shadow, offset=(0, side * 0.04),
                     shape="circle" if shape == "circle" else "rect")
        img.paste(tile[0], box[:2], tile[1])

    def _emboss_icon(self, img, kind, cx, cy, size, color, d):
        B.icon(img, kind, cx, cy + max(1, size * 0.04), size, d.pal["emboss"])
        B.icon(img, kind, cx, cy, size, color)

    def draw_icon(self, img, kind, cx, cy, size, color, d):
        self._emboss_icon(img, kind, cx, cy, size, color, d)

    prev_glyph = "rewind"
    next_glyph = "forward"

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        main = min(h * 0.5, (x1 - x0) / 7)
        self._icon_row(img, self.transport(d), box, main, main * 1.05, min((x1 - x0) / 4.2, main * 2.6), d)

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        t = max(3, min(P.height(box) * 0.32, d.base * 0.34))
        cy = (y0 + y1) / 2
        kr = t * 1.55
        # Recessed groove: darker upper edge, light lower edge.
        B.fill_pill(img, x0 + kr, x1 - kr, cy - 0.6, t, P.shade(d.pal["track"], 0.9))
        self.bar(img, box, d.fraction, d, t, knob="light", knob_r=kr)

    def volume(self, img, box, d):
        self.volume_line(img, box, d, left="speaker", right=None, thickness=0.1)
