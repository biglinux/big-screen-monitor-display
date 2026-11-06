"""Big Flow: a streaming "now playing" card on deep navy — big rounded cover, source line,
title and artist — album, thin white progress, large white symbols and a volume slider
with a big knob."""

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row


class BigFlow(B.ModernSkin):
    id = "big_flow"
    name = "Big Flow"
    description = N_("Streaming-style card on deep navy: big rounded cover, source line, thin white progress, "
                     "large white symbols and a volume slider.")
    faces = ("Noto Sans", "Lato")
    card_margin = 0.0
    card_round = 0.085
    pad_frac = 0.06
    art_round = 0.055
    art_frac = 0.46
    tint_from_cover = True
    rows = (Row("eyebrow", 1.2, drop=1), Row("meta", 2.9, flex=0.5), Row("progress_times", 2.0),
            Row("controls", 3.3, flex=0.5), Row("volume", 1.9, drop=2))
    meta = (("title", 1.38, True), ("artist_album", 1.18, False))
    badge = "eyebrow"
    tele_style = "pill"
    prev_glyph = "rewind"
    next_glyph = "forward"
    base_pal = {
        "bg": (27, 31, 44), "bg2": (16, 18, 27), "outer": (9, 10, 15), "surface": (40, 45, 62),
        "text": (255, 255, 255), "text2": (206, 208, 216), "text3": (124, 128, 140),
        "accent": (255, 255, 255), "accent2": (220, 222, 230), "track": (62, 66, 80),
        "icon": (255, 255, 255), "icon_off": (84, 88, 102), "knob": (255, 255, 255),
        "tele_bg": (14, 16, 24), "tele_fg": (200, 204, 214), "tele_accent": (150, 180, 255),
    }

    def progress(self, img, box, d):
        t = max(3, min(P.height(box) * 0.3, d.base * 0.34))
        self.bar(img, box, d.fraction, d, t, knob="flat", knob_r=t * 1.7)

    def knob(self, img, cx, cy, r, style, d):
        if style == "flat":
            if d.shadow:
                B.shadow(img, (cx - r, cy - r, cx + r, cy + r), r, max(1, r * 0.6), 0.5 * d.shadow,
                         offset=(0, r * 0.2), shape="circle")
            B.fill_circle(img, cx, cy, r, d.pal["knob"])
            return
        super().knob(img, cx, cy, r, style, d)

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        main = min(h * 0.6, (x1 - x0) / 5.2)
        self._icon_row(img, self.transport(d), box, main, main * 1.1, min((x1 - x0) / 4.0, main * 2.2), d)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        self.volume_line(img, box, d, left="vol_low", right="vol_high", thickness=0.17, knob="flat")

    def badge_area(self, img, L, d):
        """Output device (when shown) or the distribution mark at the right of the source line."""
        box = L.extras.get("badge") or L.extras.get("eyebrow")
        if box is None:
            return super().badge_area(img, L, d)
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        size = max(10, min(P.height(box) * 1.0, d.base * 1.2))
        if d.output:
            B.icon(img, "output", x1 - size / 2, cy, size, d.pal["text2"])
            return
        if self.badge != "none" and d.logo_style != "none" and d.logo is not None:
            self.draw_badge(img, x1, cy, int(size), d, L)
