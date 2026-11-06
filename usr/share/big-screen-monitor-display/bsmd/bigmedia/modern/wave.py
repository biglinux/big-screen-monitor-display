"""Big Wave: minimal black panel, a rounded cover with the title under it, a thin
waveform that fills in blue as the track plays, line icons and a big ring play key."""

from PIL import ImageDraw

from ...i18n import N_
from .. import paint as P
from . import base as B
from .base import Row


class BigWave(B.ModernSkin):
    id = "big_wave"
    name = "Big Wave"
    description = N_("Minimal black panel with a waveform that fills in blue as the track plays, centred "
                     "caption under the cover and a ring play key.")
    faces = ("Montserrat", "Noto Sans", "Lato")
    card_margin = 0.0
    card_round = 0.03
    pad_frac = 0.06
    art_round = 0.09
    art_frac = 0.34
    caption = True
    rows = (Row("vis", 3.2, flex=1.0, drop=3), Row("progress_times", 2.1), Row("controls", 3.1),
            Row("volume", 1.25, drop=2))
    portrait_rows = (Row("meta", 2.9), Row("vis", 2.6, flex=1.0, drop=3), Row("progress_times", 2.1),
                     Row("controls", 3.1), Row("volume", 1.25, drop=2))
    meta = (("title", 1.4, True), ("artist", 1.0, False))
    tele_style = "hud"
    tele_radius = 0.15
    base_pal = {
        "bg": (19, 20, 23), "bg2": (16, 17, 20), "outer": (10, 10, 12), "surface": (34, 36, 41),
        "text": (245, 245, 245), "text2": (196, 198, 204), "text3": (130, 132, 138),
        "accent": (95, 169, 255), "accent2": (125, 216, 245), "track": (52, 54, 60),
        "icon": (245, 245, 245), "icon_off": (78, 80, 86), "knob": (95, 169, 255),
        "tele_bg": (14, 15, 18), "tele_fg": (125, 216, 245), "tele_accent": (95, 169, 255),
        "stops": ((0, (125, 216, 245)), (1, (95, 169, 255))),
    }

    def palette(self, mode="skin", custom=None, cover=None, tone=None):
        pal = super().palette(mode, custom, cover, tone)
        if mode == "skin":
            pal["stops"] = self.base_pal["stops"]
        pal["knob"] = pal["accent"]
        return pal

    def progress(self, img, box, d):
        t = max(2, min(P.height(box) * 0.2, d.base * 0.22))
        self.bar(img, box, d.fraction, d, t, stops=d.pal["stops"], knob="accent", knob_r=max(3, t * 2.4))

    def times(self, img, box, d):
        x0, y0, x1, y1 = box
        size = max(8, min(P.height(box) * 0.8, d.base * 0.95))
        cy = (y0 + y1) / 2
        self.text(img, (x0, cy), d.elapsed_text, size, d.pal["text2"], d)
        self.text(img, (x1, cy), d.total_text, size, d.pal["text2"], d, anchor="rm")

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        cy = (y0 + y1) / 2
        items = self.transport(d, toggles=False)
        shuffle, repeat = self.toggle_items(d)
        R = min(h * 0.46, (x1 - x0) / 9)
        span = (x1 - x0) - R * 2
        slots = [x0 + R + span * k / 4 for k in range(5)]
        if repeat:
            kind, enabled, active, role = repeat
            B.icon(img, kind, slots[0], cy, R * 0.85, self.glyph_color(enabled, active, role, d))
        for (kind, enabled, active, role), x in zip(items, slots[1:4], strict=True):
            colour = self.glyph_color(enabled, active, role, d)
            if role == "main":
                B.ring(img, x, cy, R, max(1.5, R * 0.07), colour)
                B.icon(img, kind, x + (R * 0.06 if kind == "play" else 0), cy, R * 0.8, colour)
            else:
                B.icon(img, kind, x, cy, R * 0.8, colour)
        if shuffle:
            kind, enabled, active, role = shuffle
            B.icon(img, kind, slots[4], cy, R * 0.85, self.glyph_color(enabled, active, role, d))

    def volume(self, img, box, d):
        self.volume_line(img, box, d, left="speaker", right=None, thickness=0.09)

    def tele_decor(self, img, box, d):
        x0, y0, x1, y1 = box
        ImageDraw.Draw(img).rounded_rectangle((x0, y0, x1 - 1, y1 - 1), radius=max(1, int((y1 - y0) * 0.15)),
                                              outline=P.mix(d.pal["accent"], d.pal["bg"], 0.65))
