"""Big Lounge: warm dark glass over a blurred copy of the cover, a big picture, generous
spacing, large frameless symbols, a long volume line and the real output device as a chip."""

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row


class BigLounge(B.ModernSkin):
    id = "big_lounge"
    name = "Big Lounge"
    description = N_("Warm dark glass over the blurred cover, a large picture, wide frameless controls, long "
                     "volume line and the audio output as a chip.")
    faces = ("Lato", "Noto Sans")
    card_margin = 0.0
    card_round = 0.075
    pad_frac = 0.06
    art_round = 0.035
    art_frac = 0.46
    ambient = True
    tint_from_cover = True
    remaining = True
    rows = (Row("meta", 2.9, flex=0.6), Row("progress_times", 2.1), Row("controls", 3.2, flex=0.4),
            Row("volume", 1.6, drop=2), Row("chip", 2.0, drop=1))
    meta = (("title", 1.22, True), ("artist", 1.18, False))
    tele_style = "text"
    prev_glyph = "rewind"
    next_glyph = "forward"
    base_pal = {
        "bg": (34, 28, 24), "bg2": (18, 15, 13), "outer": (6, 5, 5), "surface": (62, 56, 52),
        "text": (250, 248, 245), "text2": (168, 160, 152), "text3": (150, 143, 136),
        "accent": (222, 218, 212), "accent2": (200, 196, 190), "track": (78, 72, 68),
        "icon": (250, 248, 245), "icon_off": (100, 94, 90), "knob": (240, 238, 235),
        "tele_bg": (24, 20, 18), "tele_fg": (200, 194, 188), "tele_accent": (222, 218, 212),
    }

    def palette(self, mode="skin", custom=None, cover=None, tone=None):
        pal = super().palette(mode, custom, cover, tone)
        if mode == "skin":
            pal["stops"] = ((0, pal["accent"]), (1, pal["accent"]))
        return pal

    def progress(self, img, box, d):
        t = max(3, min(P.height(box) * 0.34, d.base * 0.36))
        self.bar(img, box, d.fraction, d, t)

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        main = min(h * 0.62, (x1 - x0) / 5.5)
        self._icon_row(img, self.transport(d), box, main, main * 1.12, min((x1 - x0) / 4.0, main * 2.3), d)

    def volume(self, img, box, d):
        self.volume_line(img, box, d, left="vol_low", right="vol_high", thickness=0.14)
