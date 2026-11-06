"""Big Stage: cinematic — the picture fills the left side edge to edge and fades into a
near-black stage; big white play disc between shuffle/skip/repeat, and the system volume
with its output in a card at the bottom."""

from PIL import Image

from ...i18n import N_, _
from .. import paint as P
from . import base as B
from .base import Row


class BigStage(B.ModernSkin):
    id = "big_stage"
    name = "Big Stage"
    description = N_("Cinematic layout: the picture fills the left side and fades into a dark stage, big "
                     "white play key, volume card at the bottom.")
    faces = ("Noto Sans", "Lato")
    art_style = "bleed"
    art_fit = "cover"
    art_frac = 0.46
    portrait_art = 0.44
    card_margin = 0.0
    card_round = 0.04
    pad_frac = 0.055
    tint_from_cover = True
    remaining = True
    rows = (Row("header", 1.5, drop=1), Row("meta", 2.9, flex=0.6), Row("progress_times", 2.0),
            Row("controls", 3.5, flex=0.4), Row("chip_volume", 2.4, drop=2))
    meta = (("artist", 0.95, False), ("title", 1.5, True))
    tele_style = "overlay"
    tele_radius = 0.5
    base_pal = {
        "bg": (14, 15, 19), "bg2": (9, 10, 13), "outer": (4, 4, 6), "surface": (30, 32, 39),
        "text": (255, 255, 255), "text2": (200, 202, 208), "text3": (132, 134, 142),
        "accent": (215, 40, 52), "accent2": (140, 20, 30), "track": (62, 64, 72), "fill": (238, 232, 205),
        "icon": (238, 238, 242), "icon_off": (80, 82, 90), "knob": (255, 255, 255),
        "tele_bg": (0, 0, 0), "tele_fg": (226, 226, 232), "tele_accent": (240, 90, 90),
    }

    def palette(self, mode="skin", custom=None, cover=None, tone=None):
        pal = super().palette(mode, custom, cover, tone)
        pal["bar"] = (238, 232, 205) if mode in ("skin", "cover") else pal["accent"]
        return pal

    def card_fill(self, img, card, r, L, d):
        super().card_fill(img, card, r, L, d)
        if not L.art or L.mode == "portrait":
            return
        # A faint wash of the accent where the picture meets the stage: spill light.
        ax1 = L.art[2]
        x0, y0, x1, y1 = card
        w = int(min(x1 - ax1, (x1 - x0) * 0.35))
        if w > 4 and not d.pal.get("contrast"):
            glow = B.gradient_tile(w, y1 - y0, ((0, P.mix(d.pal["bg"], d.pal["accent"], 0.16)), (1, d.pal["bg"])))
            img.paste(glow, (int(ax1), int(y0)))

    def art(self, img, box, tile, d):
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        img.paste(tile[0], (x0, y0), tile[1])
        portrait = h < w
        # Cinematic fade of the picture into the stage colour (right edge; bottom edge in portrait).
        mask = B.cached(("fade", w, h, portrait), lambda: _fade_mask(w, h, portrait))
        img.paste(B.solid((w, h), d.pal["bg"]), (x0, y0), mask)

    def art_radius(self, box, d):
        return 0, "square"

    def header(self, img, box, d):
        x0, y0, x1, y1 = box
        text = d.app if d.show["source"] else ""
        if not text:
            return
        size = max(8, min(P.height(box) * 0.62, d.base * 0.88))
        label = _("Now playing · {source}").format(source=text)
        self.text(img, ((x0 + x1) / 2, (y0 + y1) / 2), P.ellipsize(label, size, x1 - x0, False, d.face), size,
                  d.pal["text2"], d, anchor="mm")

    def extras(self, img, L, d):
        if L.extras.get("header"):
            self.header(img, L.extras["header"], d)
        if L.extras.get("chip_volume"):
            self.volume_card(img, L.extras["chip_volume"], d)
        self.badge_area(img, L, d)

    def progress(self, img, box, d):
        t = max(2, min(P.height(box) * 0.26, d.base * 0.28))
        self.bar(img, box, d.fraction, d, t, fill=d.pal["bar"])

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        cy = (y0 + y1) / 2
        items = self.transport(d, toggles=False)
        shuffle, repeat = self.toggle_items(d)
        R = min(h * 0.44, (x1 - x0) / 8.5)
        span = (x1 - x0) - R * 2
        slots = [x0 + R + span * k / 4 for k in range(5)]
        if shuffle:
            kind, enabled, active, role = shuffle
            B.icon(img, kind, slots[0], cy, R * 0.72, self.glyph_color(enabled, active, role, d))
        for (kind, enabled, active, role), x in zip(items, slots[1:4], strict=True):
            if role == "main":
                if d.shadow:
                    B.shadow(img, (x - R, cy - R, x + R, cy + R), R, max(2, R * 0.35), 0.7 * d.shadow,
                             offset=(0, R * 0.12), shape="circle")
                if d.glow and active and not d.pal.get("contrast"):
                    B.ring(img, x, cy, R * 1.12, max(1.5, R * 0.06), P.mix(d.pal["bg"], d.pal["accent"], 0.7))
                B.fill_circle(img, x, cy, R, d.pal["knob"] if enabled else d.pal["icon_off"])
                B.icon(img, kind, x + (R * 0.06 if kind == "play" else 0), cy, R * 0.72, d.pal["bg"])
            else:
                B.icon(img, kind, x, cy, R * 0.82, self.glyph_color(enabled, active, role, d))
        if repeat:
            kind, enabled, active, role = repeat
            B.icon(img, kind, slots[4], cy, R * 0.72, self.glyph_color(enabled, active, role, d))

    def volume_card(self, img, box, d):
        """In place of the "next track" card of streaming apps (MPRIS has no queue): the real volume."""
        x0, y0, x1, y1 = box
        h = y1 - y0
        inner = (x0 + (x1 - x0) * 0.04, y0, x1 - (x1 - x0) * 0.04, y1)
        B.fill_rrect(img, inner, h * 0.22, d.pal["surface"])
        ix0, iy0, ix1, iy1 = inner
        label = d.output or ""
        x = ix0 + h * 0.3
        if label:
            size = max(8, h * 0.3)
            lw = min(P.text_width(label, size, False, d.face), (ix1 - ix0) * 0.38)
            B.icon(img, "output", x + h * 0.22, (iy0 + iy1) / 2, h * 0.42, d.pal["text2"])
            self.text(img, (x + h * 0.55, (iy0 + iy1) / 2), P.ellipsize(label, size, lw, False, d.face), size,
                      d.pal["text"], d)
            x += h * 0.55 + lw + h * 0.35
        self.volume_line(img, (x, iy0 + h * 0.2, ix1 - h * 0.3, iy1 - h * 0.2), d, left="speaker", right=None,
                         thickness=0.1, fill=d.pal["bar"])

    def volume(self, img, box, d):
        self.volume_line(img, box, d, left="speaker", right=None, thickness=0.1, fill=d.pal["bar"])


def _fade_mask(w, h, portrait):
    if portrait:
        ramp = Image.linear_gradient("L").resize((max(1, w), max(1, h)))
        start = 0.62
    else:
        ramp = Image.linear_gradient("L").rotate(90, expand=True).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        ramp = ramp.resize((max(1, w), max(1, h)))
        start = 0.6
    # Ease: transparent until ``start``, then a smooth rise to opaque at the edge.
    return ramp.point(lambda v: 0 if v / 255 < start else int(255 * ((v / 255 - start) / (1 - start)) ** 1.6))
