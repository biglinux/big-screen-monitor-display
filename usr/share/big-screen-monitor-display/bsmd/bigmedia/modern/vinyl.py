"""Big Vinyl: graphite panel, the cover on a record that slides out and turns while playing,
joined grey transport keys, red volume and a full-width red progress bar."""

from PIL import ImageDraw

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row


class BigVinyl(B.ModernSkin):
    id = "big_vinyl"
    name = "Big Vinyl"
    description = N_("Graphite panel with the cover on a turning record, joined grey keys and a deep red "
                     "progress bar.")
    faces = ("Lato", "Noto Sans")
    card_margin = 0.018
    card_round = 0.045
    art_round = 0.0
    art_shape = "square"
    art_frac = 0.4
    disc = 0.36
    rows = (Row("meta", 2.9, flex=1.0), Row("controls", 2.5), Row("volume", 1.7, drop=2))
    footer = (Row("progress_inline", 1.7),)
    portrait_rows = (Row("meta", 2.9, flex=0.5), Row("controls", 2.5), Row("volume", 1.7, drop=2),
                     Row("progress_inline", 1.7))
    meta = (("title", 1.45, True), ("artist", 1.05, True))
    base_pal = {
        "bg": (62, 62, 64), "bg2": (42, 42, 44), "outer": (22, 22, 24), "surface": (72, 72, 74),
        "text": (244, 244, 244), "text2": (172, 172, 174), "text3": (142, 142, 144),
        "accent": (179, 39, 41), "accent2": (128, 22, 24), "track": (16, 16, 17),
        "icon": (236, 236, 236), "icon_off": (112, 112, 114), "knob": (232, 232, 232),
        "tele_bg": (36, 36, 38), "tele_fg": (226, 226, 226), "tele_accent": (225, 80, 80),
    }

    def card_fill(self, img, card, r, L, d):
        super().card_fill(img, card, r, L, d)
        x0, y0, x1, y1 = card
        draw = ImageDraw.Draw(img)
        # A light keyline along the top edge and a dark one at the bottom: a moulded panel.
        draw.line((x0 + r, y0 + 1, x1 - r, y0 + 1), fill=P.mix(d.pal["bg"], (255, 255, 255), 0.18))
        draw.line((x0 + r, y1 - 2, x1 - r, y1 - 2), fill=P.shade(d.pal["bg2"], 0.6))
        B.apply_texture(img, B.P.inset(card, 2), d.texture * 4, seed=3, scale=0.8)

    def art(self, img, box, tile, d):
        super().art(img, box, tile, d)
        # Thin bright rim: a printed sleeve catching the light.
        x0, y0, x1, y1 = box
        ImageDraw.Draw(img).rectangle((x0, y0, x1 - 1, y1 - 1), outline=P.mix(d.pal["accent"], (255, 255, 255),
                                                                                0.25) if d.glow else
                                      P.shade(d.pal["bg"], 1.4))

    # ------------------------------------------------------------ keys
    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        items = self.transport(d)
        core = [i for i in items if i[3] != "toggle"]
        toggles = [i for i in items if i[3] == "toggle"]
        key_h = min(h * 0.86, d.base * 2.4)
        key_w = min((x1 - x0) / (3 + len(toggles) * 0.75), key_h * 1.75)
        top = y0 + (h - key_h) / 2
        r = max(2, int(key_h * 0.16))
        group = (x0, top, x0 + key_w * 3, top + key_h)
        if d.shadow:
            B.shadow(img, group, r, max(2, key_h * 0.12), 0.6 * d.shadow, offset=(0, key_h * 0.06))
        B.fill_rrect(img, B.P.inset(group, -1), r + 1, (20, 20, 21))
        for index, (kind, enabled, active, role) in enumerate(core):
            kx0 = group[0] + index * key_w
            key = (kx0, top, kx0 + key_w, top + key_h)
            stops = ((0, (112, 112, 114)), (0.5, (82, 82, 84)), (1, (58, 58, 60))) if not active else \
                ((0, (52, 52, 54)), (1, (78, 78, 80)))
            tile = B.gradient_tile(B.P.width(key), B.P.height(key), stops, horizontal=False)
            mask = B.rrect_mask(B.P.width(key), B.P.height(key), r)
            if index == 1:
                mask = B.rrect_mask(B.P.width(key), B.P.height(key), 0)
            elif index == 0:
                mask = _half_round(B.P.width(key), B.P.height(key), r, left=True)
            else:
                mask = _half_round(B.P.width(key), B.P.height(key), r, left=False)
            img.paste(tile, B.P.ibox(key)[:2], mask)
            draw = ImageDraw.Draw(img)
            draw.line((key[0] + 2, key[1] + 1, key[2] - 3, key[1] + 1), fill=(150, 150, 152) if not active else
                      (60, 60, 62))
            if index:
                draw.line((key[0], key[1] + 2, key[0], key[3] - 2), fill=(26, 26, 27))
            B.icon(img, kind, (key[0] + key[2]) / 2, (key[1] + key[3]) / 2, key_h * (0.46 if role == "main" else 0.4),
                   self.glyph_color(enabled, active, role, d) if role != "main" or enabled else d.pal["icon_off"])
        x = group[2] + key_h * 0.5
        for kind, enabled, active, role in toggles:
            if x + key_h * 0.7 > x1:
                break
            B.icon(img, kind, x + key_h * 0.32, top + key_h / 2, key_h * 0.52,
                   self.glyph_color(enabled, active, role, d))
            x += key_h * 0.8

    def glyph_color(self, enabled, active, role, d):
        if role == "main" and active:
            return (255, 255, 255)
        return super().glyph_color(enabled, active, role, d)

    # ------------------------------------------------------------ bars
    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        t = max(4, min(P.height(box) * 0.5, d.base * 0.62))
        cy = (y0 + y1) / 2
        B.fill_pill(img, x0, x1, cy, t + 2, (10, 10, 11))
        self.bar(img, (x0 + 1, y0, x1 - 1, y1), d.fraction, d, t, glow=False)
        ImageDraw.Draw(img).line((x0 + t / 2, cy + t / 2, x1 - t / 2, cy + t / 2),
                                 fill=P.mix(d.pal["bg"], (255, 255, 255), 0.12))

    def times(self, img, box, d):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        total = f" / {d.total_text}"
        size = P.fit_size(d.elapsed_text + total, min(P.height(box) * 0.62, d.base * 0.92), x1 - x0, False, d.face,
                          minimum=8)
        w = self.text(img, (x1, cy), total, size, d.pal["text3"], d, anchor="rm")
        self.text(img, (x1 - w, cy), d.elapsed_text, size, d.pal["text"], d, bold=True, anchor="rm")

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        self.volume_line(img, (x0, y0, x1, y1), d, left="speaker", right=None, thickness=0.12, knob="light")


def _half_round(w, h, r, left):
    """Mask rounded only on one side (first/last key of a joined group)."""
    w, h, r = int(w), int(h), int(r)

    def make():
        full = B.P.rounded_mask((w + r * 2, h), r)
        return full.crop((0, 0, w, h)) if left else full.crop((r * 2, 0, w + r * 2, h))
    return B.cached(("half", w, h, r, left), make)
