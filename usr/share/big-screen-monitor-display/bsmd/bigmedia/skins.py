"""The Big Media Player skins: seven classic homages here, eight modern ones in :mod:`.modern`.

Each skin is an original homage to the look of a period media player (see
docs/big-media-player-skins.md): materials, colours, geometry and type are
recreated procedurally; no logo, bitmap, sprite or name of the original
programs is used. All skins show the same information (areas A..F of
:mod:`bsmd.bigmedia.layout`); only the presentation changes.

A skin paints in two passes:
    chrome(img, L, d)   static: body, frames, wells, title, logo (cached by the engine)
    dynamic painters    title_info, art, info, readout, vis, progress, times,
                        buttons, volume, tele - called every frame
"""

import math

from PIL import Image, ImageDraw

from ..i18n import N_, _
from . import paint as P

CLASSIC_IDS = ("bigamp", "bigmatch", "bigative", "bigalplayer", "bigmediaplayer", "bigxmms2", "bigx")
MODERN_IDS = ("big_vinyl", "big_pure", "big_ember", "big_groove", "big_lounge", "big_wave", "big_flow", "big_stage")
SKIN_IDS = CLASSIC_IDS + MODERN_IDS
COLLECTIONS = {"classic": CLASSIC_IDS, "modern": MODERN_IDS}


class Skin:
    id = "base"
    name = "Skin"
    description = ""
    collection = "classic"
    modern = False
    # metrics in px for a 320 px short side
    pad = 6
    frame = 3
    title_h = 18
    time_inline = True          # elapsed/total beside the progress bar
    has_readout = False         # big LCD time in the info area
    vis_beside_readout = False
    art_shape = "square"
    marquee_loop = False
    pixel_text = False
    mono = False
    caps_title = False
    pal = {}

    # ------------------------------------------------------------ colours
    def c(self, key, d=None):
        if d is not None and d.accent and key in ("accent", "fill"):
            return d.accent
        return self.pal[key]

    # ------------------------------------------------------------ chrome (static)
    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, L.W, L.H), fill=self.pal["body"])
        if L.title:
            self.title_bar(img, L, d)
        for box in (L.info,):
            if box:
                P.lcd_well(img, P.inset(box, -2), self.pal["lcd_bg"])
        if L.art:
            self.art_well(img, L.art)
        if L.tele and not L.tele_overlay:
            P.lcd_well(img, L.tele, self.pal["tele_bg"])

    def title_bar(self, img, L, d):
        x0, y0, x1, y1 = L.title
        draw = ImageDraw.Draw(img)
        draw.rectangle(L.title, fill=self.pal["title_bg"])
        self.title_text(img, L.title, d, self.pal["title_fg"])

    def title_text(self, img, box, d, color, x=None, bold=True, size=None):
        x0, y0, x1, y1 = box
        h = y1 - y0
        size = size or max(8, h * 0.58)
        x = x0 + max(4, h * 0.3) if x is None else x
        if d.logo is not None and d.logo_style in ("logo", "logo_name"):
            logo = d.logo_at(int(h * 0.72))
            if logo is not None:
                img.paste(logo, (int(x), int(y0 + (h - logo.height) / 2)), logo)
                x += logo.width + max(3, h * 0.25)
        name = self.name.upper() if self.caps_title else self.name
        x += P.put_text(img, (x, (y0 + y1) / 2), name, size, color, bold=bold, mono=self.mono)
        if d.distro and d.logo_style in ("name", "logo_name") and (x1 - x0) >= 400:
            x += h * 0.4 + P.put_text(img, (x + h * 0.4, (y0 + y1) / 2), f"· {d.distro}", size * 0.8,
                                      P.mix(color, self.pal["title_bg"], 0.35), mono=self.mono)
        return x

    def title_info(self, img, L, d):
        """Source application at the right of the title bar (dynamic)."""
        if not L.title or not d.source:
            return
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        size = max(7, h * 0.48)
        text = P.ellipsize(d.source, size, (x1 - x0) * 0.32, mono=self.mono)
        P.put_text(img, (x1 - max(5, h * 0.35), (y0 + y1) / 2), text, size,
                   P.mix(self.pal["title_fg"], self.pal["title_bg"], 0.25), anchor="rm", mono=self.mono)

    def art_well(self, img, box):
        ImageDraw.Draw(img).rectangle(P.inset(box, -2), fill=P.shade(self.pal["body"], 0.6))

    # ------------------------------------------------------------ art
    def art_radius(self, box, d):
        shape = d.art_shape if d.art_shape != "skin" else self.art_shape
        side = min(P.width(box), P.height(box))
        return {"square": 0, "rounded": max(3, side // 9), "circle": side // 2}.get(shape, 0), shape

    def art(self, img, box, tile, d):
        """Paste the prepared art tile (already shaped/masked by the engine) and frame it."""
        radius, shape = self.art_radius(box, d)
        x0, y0, x1, y1 = box
        if d.art_glow:
            d.halo(img, box, radius, shape, self.c("accent", d), 7, filled=True)
        img.paste(tile[0], (x0, y0), tile[1])
        self._art_frame(img, box, radius, shape, d)

    def _art_frame(self, img, box, radius, shape, d):
        frame = d.art_frame if d.art_frame != "skin" else self.default_frame
        draw = ImageDraw.Draw(img)
        if frame == "metal":
            for i, color in enumerate(((235, 238, 244), (150, 156, 168), (90, 94, 104))):
                self._shape_outline(draw, P.inset(box, -1 - i), radius + 1 + i, shape, color)
        elif frame == "neon":
            d.halo(img, P.inset(box, -2), radius + 2, shape, self.c("accent", d), 4, filled=False)
            self._shape_outline(draw, P.inset(box, -2), radius + 2, shape, P.shade(self.c("accent", d), 1.3), width=2)
        elif frame == "bevel":
            P.bevel(draw, P.inset(box, -2), self.pal.get("bevel_lo", (40, 40, 40)), self.pal.get("bevel_hi",
                                                                                                    (220, 220, 220)),
                    depth=2)
        elif frame == "line":
            self._shape_outline(draw, P.inset(box, -1), radius, shape, self.pal["accent"])

    default_frame = "line"

    @staticmethod
    def _shape_outline(draw, box, radius, shape, color, width=1):
        if shape == "circle":
            draw.ellipse(box, outline=color, width=width)
        elif radius:
            draw.rounded_rectangle(box, radius=radius, outline=color, width=width)
        else:
            draw.rectangle(box, outline=color, width=width)

    # ------------------------------------------------------------ info text
    def info_lines(self, d, n):
        """[(text, role)] in display order; role: title, line, dim, source, badge."""
        lines = []
        if d.show["title"]:
            lines.append((d.title or _("Unknown title"), "title"))
        if d.show["artist"] and d.artist:
            lines.append((d.artist, "line"))
        if d.show["album"] and d.album:
            lines.append((d.album, "dim"))
        if d.show["description"] and d.description and d.description not in (d.artist, d.album):
            lines.append((d.description, "dim"))
        if d.show["source"] and d.source:
            lines.append((d.source, "source"))
        if len(lines) > n:
            # Keep the title and the most informative lines.
            order = {"title": 0, "line": 1, "source": 2, "dim": 3}
            keep = sorted(range(len(lines)), key=lambda i: (order[lines[i][1]], i))[:n]
            lines = [lines[i] for i in sorted(keep)]
        return lines

    def role_style(self, role, d):
        """(colour, size factor, bold)."""
        if role == "title":
            return self.c("lcd_hi", d) if not d.accent else d.accent, 1.18, True
        if role == "line":
            return self.pal["lcd_fg"], 1.0, False
        if role == "source":
            return self.pal["lcd_dim2"], 0.86, False
        return self.pal["lcd_dim2"], 0.9, False

    def info(self, img, L, d):
        box = L.extras.get("text") or L.info
        if not box:
            return
        x0, y0, x1, y1 = P.inset(box, max(3, L.font * 0.35), 1)
        lines = self.info_lines(d, max(1, L.lines))
        if not lines:
            return
        sizes = [L.font * self.role_style(role, d)[1] for _t, role in lines]
        total = sum(s * 1.3 for s in sizes)
        y = y0 + max(0, ((y1 - y0) - total) / 2) if L.mode != "portrait" else y0 + 2
        align = "m" if L.mode == "portrait" and not self.mono else "l"
        for (text, role), size in zip(lines, sizes, strict=True):
            color, _f, bold = self.role_style(role, d)
            line_box = (x0, y, x1, y + size * 1.3)
            if role == "source":
                text = self.source_prefix + text
            if role == "title" and d.marquee:
                P.marquee(img, line_box, text, size, color, d.scroll(text, size, x1 - x0, bold, self.mono,
                                                                    self.pixel_text, self.marquee_loop),
                          bold=bold, mono=self.mono, pixel=self.pixel_text and size < 26, loop=self.marquee_loop,
                          align=align)
            else:
                shown = P.ellipsize(text, size, x1 - x0, bold, self.mono)
                anchor = "lm" if align == "l" else "mm"
                x = x0 if align == "l" else (x0 + x1) / 2
                P.put_text(img, (x, y + size * 0.65), shown, size, color, bold=bold, mono=self.mono, anchor=anchor)
            y += size * 1.3

    source_prefix = "♪ "

    # ------------------------------------------------------------ time
    def readout(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        P.lcd_well(img, box, self.pal["lcd_bg"])
        text = d.readout_text
        size = h * 0.66
        while P.seven_seg_width(text, size) > (x1 - x0) * 0.86 and size > 8:
            size -= 1
        color = self.c("lcd_hi", d)
        P.seven_seg(img, (x1 - h * 0.18, (y0 + y1) / 2), text, size, color, anchor="rm", bg=self.pal["lcd_bg"])
        self.state_glyph(img, (x0 + h * 0.12, y0 + h * 0.18, x0 + h * 0.42, y0 + h * 0.48), d, color)

    def state_glyph(self, img, box, d, color):
        draw = ImageDraw.Draw(img)
        kind = {"Playing": "play", "Paused": "pause"}.get(d.status, "stop")
        P.glyph(draw, kind, box, color)

    def times(self, img, box, d):
        """Elapsed at the left, total/remaining at the right of the progress row."""
        x0, y0, x1, y1 = box
        size = max(8, (y1 - y0) * 0.72)
        color = self.pal["time_fg"]
        P.put_text(img, (x0, (y0 + y1) / 2), d.elapsed_text, size, color, mono=True)
        P.put_text(img, (x1, (y0 + y1) / 2), d.total_text, size, color, mono=True, anchor="rm")

    # ------------------------------------------------------------ progress
    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        draw = ImageDraw.Draw(img)
        h = y1 - y0
        track = (x0, y0 + h * 0.3, x1, y1 - h * 0.3)
        draw.rounded_rectangle(track, radius=h * 0.2, fill=self.pal["track"])
        if d.fraction is not None:
            fx = x0 + (x1 - x0) * d.fraction
            draw.rounded_rectangle((x0, track[1], max(x0 + 2, fx), track[3]), radius=h * 0.2,
                                   fill=self.c("fill", d))
        elif d.live:
            self.live_badge(img, box, d)

    def live_badge(self, img, box, d, text=None):
        x0, y0, x1, y1 = box
        h = y1 - y0
        text = text or _("LIVE")
        size = max(7, h * 0.62)
        w = P.text_width(text, size, True) + h * 0.6
        cx = (x0 + x1) / 2
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((cx - w / 2, y0, cx + w / 2, y1), radius=h * 0.3, fill=(190, 30, 40))
        P.put_text(img, (cx, (y0 + y1) / 2), text, size, (255, 255, 255), bold=True, anchor="mm")

    # ------------------------------------------------------------ buttons
    def button_set(self, d):
        """[(kind, enabled, active)] for the transport row."""
        playing = d.status == "Playing"
        caps = d.caps
        items = [("previous", caps["previous"], False),
                 ("pause" if playing else "play", caps["pause"] if playing else caps["play"], playing),
                 ("stop", caps["stop"], False),
                 ("next", caps["next"], False)]
        return items

    def toggles(self, d):
        result = []
        if d.shuffle is not None:
            result.append(("shuffle", True, d.shuffle))
        if d.loop is not None:
            result.append(("repeat_one" if d.loop == "Track" else "repeat", True, d.loop != "None"))
        return result

    def buttons(self, img, box, d):
        items = self.button_set(d)
        extra = self.toggles(d)
        x0, y0, x1, y1 = box
        h = y1 - y0
        size = min(h, (x1 - x0) / (len(items) + len(extra) * 0.8 + 0.6))
        gap = size * 0.18
        x = x0
        for kind, enabled, active in items:
            self.button(img, (x, y0 + (h - size) / 2, x + size, y0 + (h + size) / 2), kind, enabled, active, d)
            x += size + gap
        x += gap
        small = size * 0.72
        for kind, _enabled, active in extra:
            self.toggle(img, (x, y0 + (h - small) / 2, x + small, y0 + (h + small) / 2), kind, active, d)
            x += small + gap * 0.6

    def button(self, img, box, kind, enabled, active, d):
        draw = ImageDraw.Draw(img)
        P.win_bevel(draw, box, self.pal["btn_face"])
        color = self.pal["btn_glyph"] if enabled else self.pal["btn_off"]
        P.glyph(draw, kind, P.inset(box, P.width(box) * 0.28), color)

    def toggle(self, img, box, kind, active, d):
        draw = ImageDraw.Draw(img)
        color = self.c("accent", d) if active else self.pal["btn_off"]
        P.glyph(draw, kind, P.inset(box, P.width(box) * 0.18), color)

    # ------------------------------------------------------------ volume
    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        draw = ImageDraw.Draw(img)
        h = y1 - y0
        icon = (x0, y0 + h * 0.2, x0 + h * 0.6, y1 - h * 0.2)
        muted = d.vol_muted
        P.glyph(draw, "mute" if muted else "speaker", icon, self.pal["btn_glyph"] if not muted else (220, 60, 60))
        label_w = P.text_width("100%", max(8, h * 0.5), mono=True) + 6 if d.show_vol_percent else 0
        bar = (x0 + h * 0.85, y0 + h * 0.36, x1 - label_w, y1 - h * 0.36)
        draw.rounded_rectangle(bar, radius=2, fill=self.pal["track"])
        if d.vol_percent is not None:
            frac = min(1.0, d.vol_percent / d.vol_scale)
            draw.rounded_rectangle((bar[0], bar[1], bar[0] + max(2, (bar[2] - bar[0]) * frac), bar[3]), radius=2,
                                   fill=self.pal["btn_off"] if muted else self.c("fill", d))
        if d.show_vol_percent:
            P.put_text(img, (x1, (y0 + y1) / 2), d.vol_text, max(8, h * 0.5), self.pal["time_fg"], mono=True,
                       anchor="rm")

    # ------------------------------------------------------------ visualizer
    def vis(self, img, box, d):
        x0, y0, x1, y1 = box
        P.lcd_well(img, box, self.pal["vis_bg"])
        inner = P.inset(box, 2)
        style = d.vis_style
        bands = d.bands
        if not bands:
            return
        colors = self.pal["vis"]
        draw = ImageDraw.Draw(img)
        ix0, iy0, ix1, iy1 = inner
        w, h = ix1 - ix0, iy1 - iy0
        if style == "scope":
            pts = [(ix0 + w * i / (len(bands) - 1), iy1 - h * (0.12 + 0.76 * v)) for i, v in enumerate(bands)]
            draw.line(pts, fill=colors[1], width=max(1, int(h / 18)))
        elif style == "vu":
            level = min(1.0, (sum(v * v for v in bands) / len(bands)) ** 0.5 * 1.25)
            self._vu(img, inner, level, colors)
        else:
            n = len(bands)
            bw = w / n
            seg = max(2, h / 12) if style == "led" else 0
            for i, v in enumerate(bands):
                bx0 = ix0 + i * bw + max(1, bw * 0.15)
                bx1 = ix0 + (i + 1) * bw - max(1, bw * 0.15)
                top = iy1 - h * v
                if style == "led":
                    y = iy1
                    while y - seg >= top - 0.5 and y - seg >= iy0:
                        t = (iy1 - y) / max(1, h)
                        draw.rectangle((bx0, y - seg + 1, bx1, y - 1), fill=_ramp(colors, t))
                        y -= seg
                else:
                    steps = max(1, int(h * v))
                    for k in range(0, steps, max(1, int(h / 24))):
                        t = k / max(1, h)
                        yy = iy1 - k
                        draw.rectangle((bx0, max(top, yy - max(1, int(h / 24))), bx1, yy), fill=_ramp(colors, t))
        P.put_text(img, (ix1 - 1, iy0 + 1), d.vis_label, max(6, min(9, h * 0.2)), self.pal["lcd_dim2"],
                   mono=True, anchor="rt")

    @staticmethod
    def _vu(img, box, level, colors):
        x0, y0, x1, y1 = box
        draw = ImageDraw.Draw(img)
        w, h = x1 - x0, y1 - y0
        segments = 20
        sw = w / segments
        for i in range(segments):
            t = i / segments
            lit = t < level
            color = _ramp(colors, t) if lit else P.shade(_ramp(colors, t), 0.22)
            draw.rectangle((x0 + i * sw + 1, y0 + h * 0.25, x0 + (i + 1) * sw - 1, y1 - h * 0.25), fill=color)

    # ------------------------------------------------------------ telemetry strip
    def tele(self, img, box, d, items, overlay=False, opacity=0.85, slide=0.0):
        x0, y0, x1, y1 = box
        h = y1 - y0
        if overlay:
            band = Image.new("RGBA", (x1 - x0, h), (*self.pal["tele_bg"], int(255 * opacity)))
            base = img.crop(box).convert("RGBA")
            base.alpha_composite(band)
            img.paste(base.convert("RGB"), (x0, y0))
        else:
            ImageDraw.Draw(img).rectangle(box, fill=self.pal["tele_bg"])
        size = max(7, h * 0.58)
        sep = d.tele_sep
        x = x0 + h * 0.3 + slide
        draw = ImageDraw.Draw(img)
        fg, accent = self.pal["tele_fg"], self.pal["tele_accent"]
        for index, (icon, label, value, alert) in enumerate(items):
            if index:
                if sep == "bar":
                    draw.line((x + h * 0.2, y0 + h * 0.22, x + h * 0.2, y1 - h * 0.22),
                              fill=P.mix(fg, self.pal["tele_bg"], 0.5))
                    x += h * 0.45
                elif sep == "dot":
                    draw.ellipse((x + h * 0.15, (y0 + y1) / 2 - 1.5, x + h * 0.15 + 3, (y0 + y1) / 2 + 1.5),
                                 fill=P.mix(fg, self.pal["tele_bg"], 0.4))
                    x += h * 0.5
                else:
                    x += h * 0.35
            text = f"{label} {value}" if label else value
            needed = P.text_width(text, size, mono=self.mono) + (h * 0.8 if icon is not None and d.tele_icons else 0)
            if x + needed > x1 - 2:
                break
            if icon is not None and d.tele_icons:
                tile = icon(int(h * 0.62), alert and (230, 70, 60) or accent)
                if tile is not None:
                    img.paste(tile, (int(x), int(y0 + (h - tile.height) / 2)), tile)
                    x += tile.width + 2
            x += P.put_text(img, (x, (y0 + y1) / 2), text, size, (240, 90, 70) if alert else fg, mono=self.mono)


def _ramp(colors, t):
    """Colour along a 3-stop ramp (low, mid, high)."""
    t = max(0.0, min(1.0, t))
    if t < 0.6:
        return P.mix(colors[0], colors[1], t / 0.6)
    return P.mix(colors[1], colors[2], (t - 0.6) / 0.4)


# ================================================================ BIGAMP

class Bigamp(Skin):
    id = "bigamp"
    name = "Bigamp"
    description = N_("Compact dark console with a green LCD, big digits, spectrum bars and square transport keys.")
    pad = 5
    frame = 4
    title_h = 15
    has_readout = True
    vis_beside_readout = True
    time_inline = False
    marquee_loop = True
    pixel_text = True
    caps_title = True
    default_frame = "bevel"
    source_prefix = "SRC "
    pal = {
        "body": (40, 40, 56), "body2": (24, 24, 34), "title_bg": (20, 20, 30), "title_fg": (222, 186, 84),
        "lcd_bg": (0, 0, 0), "lcd_fg": (0, 226, 0), "lcd_hi": (0, 255, 64), "lcd_dim2": (0, 150, 40),
        "time_fg": (0, 226, 0), "track": (22, 22, 30), "fill": (218, 180, 80), "accent": (0, 230, 60),
        "btn_face": (92, 90, 120), "btn_glyph": (16, 16, 24), "btn_off": (70, 70, 90),
        "bevel_hi": (150, 146, 190), "bevel_lo": (14, 14, 22), "vis_bg": (0, 0, 0),
        "vis": ((0, 200, 40), (230, 220, 0), (255, 50, 20)), "tele_bg": (0, 0, 0), "tele_fg": (0, 220, 0),
        "tele_accent": (222, 186, 84), "gold": (222, 186, 84), "purple": (120, 90, 200),
    }

    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        P.vgrad(img, (0, 0, L.W, L.H), None, None, [(0, (58, 58, 80)), (0.5, (38, 38, 54)), (1, (26, 26, 38))])
        # Fine horizontal ribs, like a moulded plastic case.
        for y in range(0, L.H, 3):
            draw.line((0, y, L.W, y), fill=(34, 34, 48))
        P.bevel(draw, (0, 0, L.W, L.H), (110, 106, 150), (8, 8, 14), depth=2)
        if L.title:
            self.title_bar(img, L, d)
        if L.body:
            P.bevel(draw, P.inset(L.body, 1), (16, 16, 24), (96, 92, 128))
        for box in (L.info, L.readout):
            if box:
                P.lcd_well(img, P.inset(box, -2), (0, 0, 0), rim_hi=(110, 106, 150), rim_lo=(8, 8, 12))
        if L.info and d.lcd_effect:
            P.dither_dots(img, P.inset(L.info, -2), (24, 24, 24), 0.35, 2)
        if L.art:
            P.lcd_well(img, P.inset(L.art, -3), (0, 0, 0), rim_hi=(110, 106, 150), rim_lo=(8, 8, 12))
        if L.vis:
            P.lcd_well(img, L.vis, (0, 0, 0), rim_hi=(110, 106, 150), rim_lo=(8, 8, 12))
        if L.tele and not L.tele_overlay:
            P.lcd_well(img, L.tele, (0, 0, 0), rim_hi=(110, 106, 150), rim_lo=(8, 8, 12))

    def title_bar(self, img, L, d):
        x0, y0, x1, y1 = L.title
        draw = ImageDraw.Draw(img)
        P.vgrad(img, L.title, None, None, [(0, (34, 34, 50)), (1, (18, 18, 28))])
        h = y1 - y0
        end = self.title_text(img, L.title, d, self.pal["gold"], size=max(8, h * 0.56))
        # Gold grooves fill the bar, with a purple keyline: the classic "title stripe".
        gx0 = end + h * 0.5
        gx1 = x1 - h * 0.4 - (P.text_width(d.source, max(7, h * 0.48)) + h if d.source else 0)
        for k in range(3):
            yy = y0 + h * (0.34 + k * 0.16)
            if gx1 > gx0 + 8:
                draw.line((gx0, yy, gx1, yy), fill=(160, 130, 60) if k != 1 else (90, 70, 30))
        draw.line((0, y1 - 1, L.W, y1 - 1), fill=self.pal["purple"])

    def role_style(self, role, d):
        if role == "title":
            return (d.accent or self.pal["lcd_hi"]), 1.12, False
        if role == "line":
            return self.pal["lcd_fg"], 0.95, False
        return self.pal["lcd_dim2"], 0.86, False

    def button(self, img, box, kind, enabled, active, d):
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = P.ibox(box)
        P.vgrad(img, (x0, y0, x1, y1), None, None,
                [(0, (128, 124, 160)), (0.5, (96, 92, 126)), (1, (70, 66, 96))] if not active else
                [(0, (90, 86, 120)), (1, (120, 116, 150))])
        P.bevel(draw, (x0, y0, x1, y1), (176, 172, 210), (20, 20, 30), inset_=active)
        color = (12, 12, 20) if enabled else (78, 76, 100)
        P.glyph(draw, kind, P.inset((x0, y0, x1, y1), (x1 - x0) * 0.27), color)

    def toggle(self, img, box, kind, active, d):
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = P.ibox(box)
        draw.rectangle((x0, y0, x1, y1), fill=(30, 30, 42))
        P.bevel(draw, (x0, y0, x1, y1), (120, 116, 150), (10, 10, 16))
        P.led(draw, (x0 + (x1 - x0) * 0.22, y0 + (y1 - y0) * 0.25), max(1.5, (y1 - y0) * 0.1), (0, 255, 60), active)
        P.glyph(draw, kind, P.inset((x0, y0, x1, y1), (x1 - x0) * 0.26), (200, 200, 220) if active else (90, 90, 110))

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        draw = ImageDraw.Draw(img)
        h = y1 - y0
        groove = (x0, y0 + h * 0.32, x1, y1 - h * 0.32)
        draw.rectangle(groove, fill=(14, 14, 22))
        P.bevel(draw, groove, (8, 8, 12), (90, 86, 120))
        if d.fraction is not None:
            tw = max(10, h * 1.6)
            tx = x0 + (x1 - x0 - tw) * d.fraction
            P.vgrad(img, (tx, y0 + h * 0.12, tx + tw, y1 - h * 0.12), None, None,
                    [(0, (250, 220, 120)), (0.5, (214, 170, 70)), (1, (150, 110, 40))])
            P.bevel(draw, (tx, y0 + h * 0.12, tx + tw, y1 - h * 0.12), (255, 240, 170), (90, 60, 20))
        elif d.live:
            self.live_badge(img, box, d)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        draw = ImageDraw.Draw(img)
        h = y1 - y0
        label_size = max(7, h * 0.42)
        label = "MUTE" if d.vol_muted else d.vol_label
        lw = P.text_width("MUTE", label_size, True, True) + 4
        P.put_text(img, (x0, (y0 + y1) / 2), label, label_size, (240, 70, 60) if d.vol_muted else self.pal["gold"],
                   bold=True, mono=True)
        pw = (P.text_width("150%", label_size, mono=True) + 6) if d.show_vol_percent else 0
        groove = (x0 + lw + 2, y0 + h * 0.3, x1 - pw, y1 - h * 0.3)
        # Green -> yellow -> red ramp under a dark mask: the volume slider of the era.
        gw = int(groove[2] - groove[0])
        if gw > 4:
            P.hgrad(img, groove, (0, 160, 0), (230, 40, 0))
            frac = 0 if d.vol_percent is None else min(1.0, d.vol_percent / d.vol_scale)
            if d.vol_muted:
                frac = 0
            draw.rectangle((groove[0] + gw * frac, groove[1], groove[2], groove[3]), fill=(18, 18, 26))
            P.bevel(draw, groove, (8, 8, 12), (90, 86, 120))
            tx = groove[0] + gw * frac
            P.vgrad(img, (tx - 3, y0 + h * 0.15, tx + 3, y1 - h * 0.15), (240, 236, 250), (120, 116, 150))
        if d.show_vol_percent:
            P.put_text(img, (x1, (y0 + y1) / 2), d.vol_text, label_size, self.pal["lcd_fg"], mono=True, anchor="rm")

    def times(self, img, box, d):
        pass        # the big LCD readout carries the time


# ================================================================ BIGMATCH

class Bigmatch(Skin):
    id = "bigmatch"
    name = "Bigmatch"
    description = N_("Silver-blue chrome jukebox with rounded panels, round glossy keys and an electric-blue display.")
    pad = 8
    frame = 6
    title_h = 22
    art_shape = "rounded"
    default_frame = "metal"
    pal = {
        "body": (176, 188, 206), "title_bg": (120, 136, 162), "title_fg": (14, 30, 60),
        "lcd_bg": (8, 22, 48), "lcd_fg": (150, 214, 255), "lcd_hi": (110, 220, 255), "lcd_dim2": (90, 140, 190),
        "time_fg": (14, 36, 70), "track": (70, 82, 102), "fill": (40, 160, 255), "accent": (40, 170, 255),
        "btn_face": (210, 218, 230), "btn_glyph": (16, 70, 150), "btn_off": (140, 150, 168),
        "vis_bg": (6, 18, 40), "vis": ((30, 110, 255), (60, 200, 255), (190, 245, 255)),
        "tele_bg": (8, 22, 48), "tele_fg": (160, 214, 255), "tele_accent": (60, 190, 255),
    }
    CHROME = [(0, (232, 238, 246)), (0.18, (196, 206, 222)), (0.55, (150, 164, 188)), (0.8, (176, 188, 208)),
              (1, (120, 134, 160))]

    def chrome(self, img, L, d):
        P.vgrad(img, (0, 0, L.W, L.H), None, None, [(0, (60, 72, 96)), (1, (30, 38, 56))])
        radius = max(8, int(L.unit * 18))
        P.chrome_panel(img, (1, 1, L.W - 1, L.H - 1), radius, self.CHROME, outline=(70, 84, 110), gloss=0.25,
                       brushed_strength=4)
        if L.title:
            self.title_bar(img, L, d)
        draw = ImageDraw.Draw(img)
        if L.info:
            box = P.inset(L.info, -3)
            r = max(6, int(L.unit * 12))
            draw.rounded_rectangle(P.inset(box, -2), radius=r + 2, fill=(110, 124, 150))
            draw.rounded_rectangle(box, radius=r, fill=self.pal["lcd_bg"])
            P.vgrad(img, (box[0] + r, box[1] + 2, box[2] - r, box[1] + max(3, P.height(box) // 3)), (26, 52, 92),
                    self.pal["lcd_bg"])
        if L.art:
            side = P.width(L.art)
            draw.rounded_rectangle(P.inset(L.art, -6), radius=side // 9 + 6, fill=(126, 140, 166))
        if L.vis:
            draw.rounded_rectangle(L.vis, radius=6, fill=self.pal["vis_bg"])
        if L.tele and not L.tele_overlay:
            draw.rounded_rectangle(L.tele, radius=max(4, P.height(L.tele) // 2), fill=self.pal["tele_bg"])

    def title_bar(self, img, L, d):
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        cap = (x0 + h * 0.5, y0 + h * 0.18, x1 - h * 0.5, y1 - h * 0.05)
        P.chrome_panel(img, cap, int(P.height(cap) / 2), [(0, (250, 252, 255)), (0.5, (190, 202, 222)),
                                                          (1, (140, 156, 184))], outline=(90, 106, 134), gloss=0.45)
        self.title_text(img, cap, d, (18, 38, 80), x=cap[0] + P.height(cap) * 0.5, size=P.height(cap) * 0.62)

    def title_info(self, img, L, d):
        if not L.title or not d.source:
            return
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        size = max(7, h * 0.42)
        P.put_text(img, (x1 - h * 1.2, (y0 + y1) / 2 + h * 0.06), P.ellipsize(d.source, size, (x1 - x0) * 0.3),
                   size, (30, 60, 120), anchor="rm", bold=True)

    def button(self, img, box, kind, enabled, active, d):
        x0, y0, x1, y1 = P.ibox(box)
        side = min(x1 - x0, y1 - y0)
        tile = Image.new("RGB", (side, side))
        stops = [(0, (255, 255, 255)), (0.45, (206, 216, 232)), (0.55, (168, 182, 206)), (1, (226, 234, 246))]
        if active:
            stops = [(0, (170, 220, 255)), (0.5, (60, 160, 250)), (1, (150, 210, 255))]
        P.vgrad(tile, (0, 0, side, side), None, None, stops)
        mask = P.circle_mask(side)
        img.paste(tile, (x0, y0), mask)
        draw = ImageDraw.Draw(img)
        draw.ellipse((x0, y0, x0 + side - 1, y0 + side - 1), outline=(80, 96, 126))
        draw.arc((x0 + 2, y0 + 2, x0 + side - 3, y0 + side - 3), 200, 340, fill=(255, 255, 255))
        color = ((255, 255, 255) if active else self.pal["btn_glyph"]) if enabled else self.pal["btn_off"]
        P.glyph(draw, kind, P.inset((x0, y0, x0 + side, y0 + side), side * 0.3), color)

    def button_set(self, d):
        return [item for item in super().button_set(d) if item[0] != "stop"] if d.compact_buttons else \
            super().button_set(d)

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        tube = (x0, y0 + h * 0.28, x1, y1 - h * 0.28)
        P.chrome_panel(img, tube, int(P.height(tube) / 2), [(0, (90, 104, 130)), (0.5, (40, 52, 74)),
                                                            (1, (110, 124, 150))], gloss=0)
        if d.fraction is not None:
            fx = tube[0] + (tube[2] - tube[0]) * d.fraction
            if fx - tube[0] > 4:
                fill = self.c("fill", d)
                P.chrome_panel(img, (tube[0], tube[1], fx, tube[3]), int(P.height(tube) / 2),
                               [(0, P.shade(fill, 1.5)), (0.5, fill), (1, P.shade(fill, 0.7))], gloss=0.3)
            r = h * 0.42
            knob = (fx - r, (y0 + y1) / 2 - r, fx + r, (y0 + y1) / 2 + r)
            P.chrome_panel(img, knob, int(r), [(0, (255, 255, 255)), (1, (150, 164, 190))], outline=(70, 84, 110),
                           gloss=0.4)
        elif d.live:
            self.live_badge(img, box, d)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        # Small arc meter (real system volume) followed by a chrome slider.
        r = h * 0.48
        cx, cy = x0 + r, (y0 + y1) / 2 + r * 0.35
        draw.pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=(14, 30, 60))
        frac = 0 if d.vol_percent is None else min(1.0, d.vol_percent / d.vol_scale)
        angle = math.radians(180 + 180 * frac)
        draw.arc((cx - r, cy - r, cx + r, cy + r), 180, 180 + 180 * frac, fill=self.c("accent", d),
                 width=max(2, int(r * 0.22)))
        draw.line((cx, cy, cx + math.cos(angle) * r * 0.8, cy + math.sin(angle) * r * 0.8),
                  fill=(240, 80, 60) if d.vol_muted else (255, 255, 255), width=max(1, int(r * 0.12)))
        sub = (x0 + r * 2 + 6, y0, x1, y1)
        super().volume(img, sub, d)


# ================================================================ BIGATIVE

class Bigative(Skin):
    id = "bigative"
    name = "Bigative"
    description = N_("Stacked gunmetal hi-fi modules with screws, a blue backlit LCD, LED indicators "
                     "and labelled keys.")
    pad = 7
    frame = 5
    title_h = 20
    has_readout = True
    time_inline = False
    caps_title = True
    default_frame = "bevel"
    pal = {
        "body": (58, 62, 70), "title_bg": (34, 37, 43), "title_fg": (200, 206, 216),
        "lcd_bg": (16, 46, 104), "lcd_fg": (190, 226, 255), "lcd_hi": (230, 246, 255), "lcd_dim2": (120, 170, 230),
        "time_fg": (190, 226, 255), "track": (10, 30, 70), "fill": (170, 220, 255), "accent": (120, 200, 255),
        "btn_face": (88, 94, 104), "btn_glyph": (226, 232, 240), "btn_off": (110, 116, 126),
        "bevel_hi": (140, 146, 158), "bevel_lo": (18, 20, 24), "vis_bg": (16, 46, 104),
        "vis": ((120, 190, 255), (190, 230, 255), (255, 255, 255)), "tele_bg": (16, 46, 104),
        "tele_fg": (200, 230, 255), "tele_accent": (140, 210, 255),
    }

    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, L.W, L.H), fill=(26, 28, 32))
        # Stacked modules: the body is split into slabs separated by dark seams.
        rows = []
        if L.title:
            rows.append(L.title)
        top = L.title[3] if L.title else 0
        if L.mode in ("landscape", "ultrawide") and L.progress:
            cut = min(b[1] for b in (L.progress, L.buttons, L.volume) if b) - 4
            rows += [(0, top, L.W, cut), (0, cut, L.W, L.H)]
        else:
            rows.append((0, top, L.W, L.H))
        for k, box in enumerate(rows):
            slab = P.inset(box, 2, 1)
            P.vgrad(img, slab, None, None, [(0, (96, 102, 112)), (0.08, (74, 79, 88)), (0.92, (54, 58, 66)),
                                            (1, (36, 39, 45))])
            P.brushed(img, slab, 6, seed=11 + k)
            P.bevel(draw, slab, (150, 156, 168), (20, 22, 26))
            r = max(2, P.height(slab) * 0.05) if P.height(slab) < 60 else 3 * L.unit + 1
            if P.height(slab) > 16 and P.width(slab) > 60:
                for cx in (slab[0] + r * 2.4, slab[2] - r * 2.4):
                    for cy in ((slab[1] + slab[3]) / 2,) if P.height(slab) < 40 else (slab[1] + r * 2.4,
                                                                                         slab[3] - r * 2.4):
                        P.screw(draw, (cx, cy), r, (150, 156, 166))
        if L.title:
            self.title_text(img, L.title, d, (210, 216, 226), x=L.title[0] + P.height(L.title) * 0.9,
                            size=P.height(L.title) * 0.5)
        for box in (L.info, L.readout, L.vis):
            if box:
                P.lcd_well(img, P.inset(box, -3), (12, 14, 18))
                P.vgrad(img, P.inset(box, -1), None, None, [(0, (34, 80, 160)), (0.5, (16, 48, 108)),
                                                            (1, (10, 34, 82))])
        if L.info and d.lcd_effect:
            P.dither_dots(img, P.inset(L.info, -1), (0, 10, 40), 0.25, 3)
        if L.art:
            P.lcd_well(img, P.inset(L.art, -4), (12, 14, 18))
        if L.tele and not L.tele_overlay:
            P.lcd_well(img, P.inset(L.tele, -2), (12, 14, 18))
            P.vgrad(img, L.tele, (24, 66, 140), (12, 38, 90))

    def title_info(self, img, L, d):
        if not L.title:
            return
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        # Indicator LEDs with engraved labels: PLAY (green), MUTE (red).
        x = x1 - h * 1.1
        for label, color, lit in (("MUTE", (255, 60, 50), bool(d.vol_muted)),
                                  ("PLAY", (60, 255, 90), d.status == "Playing")):
            P.led(draw, (x, (y0 + y1) / 2), max(2, h * 0.16), color, lit)
            x -= P.put_text(img, (x - h * 0.3, (y0 + y1) / 2), label, max(6, h * 0.36), (170, 176, 186), bold=True,
                            anchor="rm") + h * 0.9
        if d.source:
            P.put_text(img, (x - h * 0.2, (y0 + y1) / 2), P.ellipsize(d.source.upper(), h * 0.38, (x1 - x0) * 0.2),
                       max(6, h * 0.38), (150, 156, 166), anchor="rm")

    def button(self, img, box, kind, enabled, active, d):
        x0, y0, x1, y1 = P.ibox(box)
        w = x1 - x0
        # Rectangular metal key, wider than tall, with an engraved label under the glyph.
        key = (x0 - w * 0.12, y0 + (y1 - y0) * 0.08, x1 + w * 0.12, y1 - (y1 - y0) * 0.08)
        P.vgrad(img, key, None, None, [(0, (150, 156, 166)), (0.5, (104, 110, 120)), (1, (70, 74, 82))] if not active
                else [(0, (70, 76, 86)), (1, (120, 126, 136))])
        draw = ImageDraw.Draw(img)
        P.bevel(draw, key, (196, 202, 212), (24, 26, 30), inset_=active)
        color = (240, 244, 250) if enabled else (120, 124, 132)
        if active:
            color = (130, 220, 255)
        P.glyph(draw, kind, (key[0] + w * 0.3, key[1] + P.height(key) * 0.18, key[2] - w * 0.3,
                             key[1] + P.height(key) * 0.58), color)
        label = {"previous": "PREV", "play": "PLAY", "pause": "PAUSE", "stop": "STOP", "next": "NEXT"}.get(kind, "")
        if P.height(key) > 22:
            P.put_text(img, ((key[0] + key[2]) / 2, key[3] - P.height(key) * 0.2), label,
                       max(6, P.height(key) * 0.2), (30, 32, 36) if not active else (180, 220, 255), bold=True,
                       anchor="mm")

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        P.lcd_well(img, (x0, y0, x1, y1), (12, 14, 18))
        P.vgrad(img, P.inset(box, 1), (24, 66, 140), (12, 38, 90))
        if d.fraction is None:
            if d.live:
                self.live_badge(img, P.inset(box, 2), d)
            return
        # Segmented LCD bar.
        n = max(10, int((x1 - x0) / max(5, h * 0.55)))
        sw = (x1 - x0 - 4) / n
        lit = round(n * d.fraction)
        for i in range(n):
            color = self.c("fill", d) if i < lit else (30, 70, 140)
            draw.rectangle((x0 + 2 + i * sw + 1, y0 + h * 0.25, x0 + 2 + (i + 1) * sw - 1, y1 - h * 0.25), fill=color)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        P.put_text(img, (x0, (y0 + y1) / 2), "VOL", max(7, h * 0.36), (200, 206, 216), bold=True)
        lx = x0 + P.text_width("VOL", max(7, h * 0.36), True) + 4
        pw = P.text_width("150%", max(7, h * 0.4), mono=True) + 6 if d.show_vol_percent else 0
        n = 16
        sw = (x1 - pw - lx) / n
        frac = 0 if (d.vol_percent is None or d.vol_muted) else min(1.0, d.vol_percent / d.vol_scale)
        for i in range(n):
            t = i / n
            lit = t < frac
            color = (60, 220, 90) if t < 0.65 else ((240, 200, 40) if t < 0.85 else (250, 70, 50))
            bh = (y1 - y0) * (0.3 + 0.5 * t)
            draw.rectangle((lx + i * sw + 1, y1 - h * 0.12 - bh, lx + (i + 1) * sw - 1, y1 - h * 0.12),
                           fill=color if lit else P.shade(color, 0.25))
        if d.show_vol_percent:
            P.put_text(img, (x1, (y0 + y1) / 2), "MUTE" if d.vol_muted else d.vol_text, max(7, h * 0.4),
                       (255, 90, 70) if d.vol_muted else (200, 230, 255), mono=True, anchor="rm")

    def times(self, img, box, d):
        pass


# ================================================================ BIGALPLAYER

class Bigalplayer(Skin):
    id = "bigalplayer"
    name = "Bigalplayer"
    description = N_("Classic silver desktop application window with a black viewer, oval keys and a blue seek bar.")
    pad = 6
    frame = 4
    title_h = 20
    art_shape = "square"
    default_frame = "none"
    pal = {
        "body": (214, 218, 226), "title_bg": (40, 70, 150), "title_fg": (255, 255, 255),
        "lcd_bg": (6, 8, 14), "lcd_fg": (230, 236, 246), "lcd_hi": (255, 255, 255), "lcd_dim2": (150, 160, 180),
        "time_fg": (20, 30, 60), "track": (160, 166, 178), "fill": (30, 100, 220), "accent": (250, 140, 30),
        "btn_face": (226, 230, 238), "btn_glyph": (20, 70, 170), "btn_off": (160, 166, 178),
        "vis_bg": (6, 8, 14), "vis": ((30, 100, 220), (100, 180, 255), (250, 160, 40)),
        "tele_bg": (234, 236, 242), "tele_fg": (30, 40, 70), "tele_accent": (30, 100, 220),
    }

    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        P.vgrad(img, (0, 0, L.W, L.H), None, None, [(0, (238, 240, 246)), (0.5, (214, 218, 226)), (1, (186, 192, 204))])
        P.bevel(draw, (0, 0, L.W, L.H), (255, 255, 255), (110, 116, 130), depth=2)
        if L.title:
            self.title_bar(img, L, d)
        for box in (L.info,):
            if box:
                outer = P.inset(box, -3)
                P.bevel(draw, outer, (120, 126, 140), (255, 255, 255))
                draw.rectangle(P.inset(outer, 1), fill=self.pal["lcd_bg"])
        if L.art:
            outer = P.inset(L.art, -3)
            P.bevel(draw, outer, (120, 126, 140), (255, 255, 255))
            draw.rectangle(P.inset(outer, 1), fill=(0, 0, 0))
        if L.vis:
            draw.rectangle(L.vis, fill=self.pal["vis_bg"])
        if L.tele and not L.tele_overlay:
            P.bevel(draw, L.tele, (150, 156, 170), (255, 255, 255))
            draw.rectangle(P.inset(L.tele, 1), fill=self.pal["tele_bg"])

    def title_bar(self, img, L, d):
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        P.vgrad(img, (x0 + 2, y0 + 2, x1 - 2, y1 - 1), None, None,
                [(0, (90, 130, 210)), (0.5, (40, 80, 170)), (1, (24, 50, 120))])
        draw = ImageDraw.Draw(img)
        draw.line((x0 + 2, y0 + 2, x1 - 2, y0 + 2), fill=(170, 200, 250))
        self.title_text(img, L.title, d, (255, 255, 255), size=h * 0.55)
        # Little coloured jewels: the accent dots of the era (purely ornamental, not buttons).
        for k, color in enumerate(((250, 150, 40), (90, 200, 90), (240, 220, 60))):
            cx = x1 - h * (0.6 + k * 0.45)
            draw.ellipse((cx - h * 0.13, (y0 + y1) / 2 - h * 0.13, cx + h * 0.13, (y0 + y1) / 2 + h * 0.13),
                         fill=color, outline=(20, 30, 60))

    def title_info(self, img, L, d):
        if not L.title or not d.source:
            return
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        P.put_text(img, (x1 - h * 1.9, (y0 + y1) / 2), P.ellipsize(d.source, h * 0.45, (x1 - x0) * 0.28),
                   max(7, h * 0.45), (220, 230, 255), anchor="rm")

    def button(self, img, box, kind, enabled, active, d):
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        big = kind in ("play", "pause")
        oval = (x0 - (w * 0.25 if big else 0), y0 + h * (0.06 if big else 0.18), x1 + (w * 0.25 if big else 0),
                y1 - h * (0.06 if big else 0.18))
        ow, oh = int(P.width(oval)), int(P.height(oval))
        tile = Image.new("RGB", (max(1, ow), max(1, oh)))
        P.vgrad(tile, (0, 0, ow, oh), None, None,
                [(0, (255, 255, 255)), (0.5, (214, 220, 232)), (1, (170, 178, 194))] if not active else
                [(0, (190, 214, 255)), (0.5, (110, 160, 240)), (1, (60, 110, 210))])
        mask = Image.new("L", tile.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, ow - 1, oh - 1), fill=255)
        img.paste(tile, (int(oval[0]), int(oval[1])), mask)
        draw = ImageDraw.Draw(img)
        draw.ellipse(oval, outline=(100, 110, 130))
        color = ((255, 255, 255) if active else self.pal["btn_glyph"]) if enabled else self.pal["btn_off"]
        gs = min(ow, oh) * 0.5
        cx, cy = (oval[0] + oval[2]) / 2, (oval[1] + oval[3]) / 2
        P.glyph(draw, kind, (cx - gs / 2, cy - gs / 2, cx + gs / 2, cy + gs / 2), color)

    def buttons(self, img, box, d):
        x0, y0, x1, y1 = box
        super().buttons(img, (x0 + (y1 - y0) * 0.3, y0, x1, y1), d)

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        track = (x0, y0 + h * 0.38, x1, y1 - h * 0.38)
        draw.rectangle(track, fill=(150, 156, 170))
        P.bevel(draw, track, (110, 116, 130), (255, 255, 255))
        if d.fraction is not None:
            fx = x0 + (x1 - x0) * d.fraction
            P.vgrad(img, (x0 + 1, track[1] + 1, max(x0 + 2, fx), track[3] - 1), (80, 150, 250), (20, 70, 180))
            tw, th = max(8, h * 0.9), h * 0.86
            thumb = (fx - tw / 2, (y0 + y1) / 2 - th / 2, fx + tw / 2, (y0 + y1) / 2 + th / 2)
            P.chrome_panel(img, thumb, int(tw / 2), [(0, (255, 255, 255)), (1, (170, 178, 194))],
                           outline=(90, 100, 120), gloss=0.2)
        elif d.live:
            self.live_badge(img, box, d)


# ================================================================ BIG MEDIA PLAYER

class BigMediaPlayer(Skin):
    id = "bigmediaplayer"
    name = "Big Media Player"
    description = N_("Light-grey 3D desktop window of the late 90s: menu strip, black viewer, square keys, trackbars.")
    pad = 5
    frame = 3
    title_h = 18
    default_frame = "none"
    art_shape = "square"
    pal = {
        "body": (192, 192, 192), "title_bg": (0, 0, 128), "title_fg": (255, 255, 255),
        "lcd_bg": (0, 0, 0), "lcd_fg": (220, 220, 220), "lcd_hi": (255, 255, 255), "lcd_dim2": (150, 150, 150),
        "time_fg": (0, 0, 0), "track": (128, 128, 128), "fill": (0, 0, 128), "accent": (0, 0, 160),
        "btn_face": (192, 192, 192), "btn_glyph": (0, 0, 0), "btn_off": (128, 128, 128),
        "vis_bg": (0, 0, 0), "vis": ((0, 160, 0), (220, 220, 0), (240, 0, 0)),
        "tele_bg": (192, 192, 192), "tele_fg": (0, 0, 0), "tele_accent": (0, 0, 128),
    }

    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        P.win_bevel(draw, (0, 0, L.W, L.H), (192, 192, 192))
        if L.title:
            self.title_bar(img, L, d)
        if L.info:
            # The black "viewer" holds the text like the video area of the period player.
            P.win_bevel(draw, P.inset(L.info, -3), None, sunken=True)
            draw.rectangle(P.inset(L.info, -1), fill=(0, 0, 0))
        if L.art:
            P.win_bevel(draw, P.inset(L.art, -3), None, sunken=True)
            draw.rectangle(P.inset(L.art, -1), fill=(0, 0, 0))
        if L.vis:
            draw.rectangle(L.vis, fill=(0, 0, 0))
        if L.tele and not L.tele_overlay:
            P.win_bevel(draw, L.tele, (192, 192, 192), sunken=True)

    def title_bar(self, img, L, d):
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        P.hgrad(img, (x0 + 3, y0 + 3, x1 - 3, y1 - 1), (0, 0, 128), (16, 132, 208))
        self.title_text(img, L.title, d, (255, 255, 255), x=x0 + 6, size=h * 0.52)

    def title_info(self, img, L, d):
        if not L.title or not d.source:
            return
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        P.put_text(img, (x1 - 8, (y0 + y1) / 2), P.ellipsize(d.source, h * 0.48, (x1 - x0) * 0.3), max(7, h * 0.48),
                   (255, 255, 255), anchor="rm")

    def role_style(self, role, d):
        if role == "title":
            return (d.accent and P.ensure_contrast(d.accent, (0, 0, 0))) or (255, 255, 255), 1.12, True
        if role == "line":
            return (200, 200, 200), 0.98, False
        return (140, 140, 140), 0.88, False

    def button(self, img, box, kind, enabled, active, d):
        draw = ImageDraw.Draw(img)
        P.win_bevel(draw, box, (192, 192, 192), sunken=active)
        color = (0, 0, 0) if enabled else (128, 128, 128)
        inner = P.inset(box, P.width(box) * 0.3)
        if not enabled:
            P.glyph(draw, kind, (inner[0] + 1, inner[1] + 1, inner[2] + 1, inner[3] + 1), (255, 255, 255))
        P.glyph(draw, kind, inner if not active else (inner[0] + 1, inner[1] + 1, inner[2] + 1, inner[3] + 1), color)

    def toggle(self, img, box, kind, active, d):
        draw = ImageDraw.Draw(img)
        P.win_bevel(draw, box, (192, 192, 192), sunken=active)
        P.glyph(draw, kind, P.inset(box, P.width(box) * 0.24), (0, 0, 128) if active else (96, 96, 96))

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        groove = (x0, (y0 + y1) / 2 - 2, x1, (y0 + y1) / 2 + 2)
        P.win_bevel(draw, groove, (192, 192, 192), sunken=True)
        if d.fraction is not None:
            tw = max(8, h * 0.6)
            tx = x0 + (x1 - x0 - tw) * d.fraction
            # Trackbar thumb with a pointed bottom.
            draw.polygon([(tx, y0 + 1), (tx + tw, y0 + 1), (tx + tw, y1 - h * 0.3), (tx + tw / 2, y1 - 1),
                          (tx, y1 - h * 0.3)], fill=(192, 192, 192))
            draw.line((tx, y1 - h * 0.3, tx, y0 + 1, tx + tw, y0 + 1), fill=(255, 255, 255))
            draw.line((tx + tw, y0 + 1, tx + tw, y1 - h * 0.3, tx + tw / 2, y1 - 1), fill=(64, 64, 64))
        elif d.live:
            self.live_badge(img, box, d)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        P.glyph(draw, "mute" if d.vol_muted else "speaker", (x0, y0 + h * 0.22, x0 + h * 0.56, y1 - h * 0.22),
                (160, 0, 0) if d.vol_muted else (0, 0, 0))
        pw = P.text_width("150%", max(8, h * 0.46)) + 6 if d.show_vol_percent else 0
        bx0, bx1 = x0 + h * 0.8, x1 - pw
        # Wedge-shaped volume trackbar.
        draw.polygon([(bx0, y1 - h * 0.25), (bx1, y1 - h * 0.25), (bx1, y0 + h * 0.25)], fill=(255, 255, 255),
                     outline=(128, 128, 128))
        frac = 0 if d.vol_percent is None else min(1.0, d.vol_percent / d.vol_scale)
        tx = bx0 + (bx1 - bx0) * frac
        tw = max(5, h * 0.3)
        P.win_bevel(draw, (tx - tw / 2, y0 + h * 0.12, tx + tw / 2, y1 - h * 0.12), (192, 192, 192))
        if d.show_vol_percent:
            P.put_text(img, (x1, (y0 + y1) / 2), _("Mute") if d.vol_muted else d.vol_text, max(8, h * 0.46),
                       (0, 0, 0), anchor="rm")

    def tele(self, img, box, d, items, overlay=False, opacity=0.85, slide=0.0):
        if overlay:
            return super().tele(img, box, d, items, overlay, opacity, slide)
        # Status bar with sunken panes.
        draw = ImageDraw.Draw(img)
        x0, y0, x1, y1 = box
        h = y1 - y0
        size = max(7, h * 0.58)
        x = x0 + 2
        for _icon, label, value, alert in items:
            text = f"{label} {value}" if label else value
            w = P.text_width(text, size) + h * 0.6
            if x + w > x1 - 2:
                break
            P.win_bevel(draw, (x, y0 + 1, x + w, y1 - 1), (192, 192, 192), sunken=True)
            P.put_text(img, (x + h * 0.3, (y0 + y1) / 2), text, size, (160, 0, 0) if alert else (0, 0, 0))
            x += w + 2


# ================================================================ BIGXMMS2

class BigXMMS2(Skin):
    id = "bigxmms2"
    name = "BigXMMS2"
    description = N_("Black terminal-style client: thin cyan rules, monospaced text, segmented bars "
                     "and a small thumbnail.")
    pad = 5
    frame = 2
    title_h = 16
    mono = True
    default_frame = "line"
    art_shape = "square"
    source_prefix = ""
    pal = {
        "body": (0, 0, 0), "title_bg": (0, 0, 0), "title_fg": (0, 215, 215),
        "lcd_bg": (0, 0, 0), "lcd_fg": (200, 210, 210), "lcd_hi": (95, 255, 95), "lcd_dim2": (0, 160, 160),
        "time_fg": (95, 255, 95), "track": (0, 60, 60), "fill": (0, 215, 215), "accent": (95, 255, 95),
        "btn_face": (0, 0, 0), "btn_glyph": (0, 215, 215), "btn_off": (0, 80, 80),
        "vis_bg": (0, 0, 0), "vis": ((0, 140, 140), (0, 215, 215), (95, 255, 95)),
        "tele_bg": (0, 0, 0), "tele_fg": (0, 200, 200), "tele_accent": (95, 255, 95), "rule": (0, 150, 150),
    }

    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, L.W, L.H), fill=(0, 0, 0))
        draw.rectangle((0, 0, L.W - 1, L.H - 1), outline=self.pal["rule"])
        if L.title:
            x0, y0, x1, y1 = L.title
            draw.line((0, y1 - 1, L.W, y1 - 1), fill=self.pal["rule"])
            h = y1 - y0
            prompt = "bigxmms2>"
            x = x0 + 5 + P.put_text(img, (x0 + 5, (y0 + y1) / 2), prompt, h * 0.6, (95, 255, 95), mono=True)
            if d.logo is not None and d.logo_style in ("logo", "logo_name"):
                logo = d.logo_at(int(h * 0.7))
                if logo is not None:
                    img.paste(logo, (int(x + 4), int(y0 + (h - logo.height) / 2)), logo)
                    x += logo.width + 6
            if d.distro and d.logo_style in ("name", "logo_name"):
                P.put_text(img, (x + 4, (y0 + y1) / 2), d.distro.lower(), h * 0.55, self.pal["lcd_dim2"], mono=True)
        for box in (L.info, L.vis):
            if box:
                draw.rectangle(P.inset(box, -2), outline=self.pal["rule"])
        if L.tele and not L.tele_overlay:
            draw.line((L.tele[0], L.tele[1] - 1, L.tele[2], L.tele[1] - 1), fill=self.pal["rule"])

    def title_info(self, img, L, d):
        if not L.title:
            return
        x0, y0, x1, y1 = L.title
        h = y1 - y0
        state = {"Playing": "playing", "Paused": "paused"}.get(d.status, "stopped")
        text = f"[{state}] {d.source.lower()}" if d.source else f"[{state}]"
        P.put_text(img, (x1 - 5, (y0 + y1) / 2), P.ellipsize(text, h * 0.55, (x1 - x0) * 0.45, mono=True),
                   h * 0.55, self.pal["lcd_dim2"], mono=True, anchor="rm")

    def info_lines(self, d, n):
        width = 7
        lines = []
        for key, label, role in (("title", "title", "title"), ("artist", "artist", "line"),
                                 ("album", "album", "dim"), ("description", "info", "dim"),
                                 ("source", "player", "source")):
            if not d.show[key]:
                continue
            value = getattr(d, key) or ("?" if key == "title" else "")
            if not value or (key == "description" and value in (d.artist, d.album)):
                continue
            lines.append((f"{label:<{width}}: {value}", role))
        return lines[:max(1, n)]

    def role_style(self, role, d):
        if role == "title":
            return (d.accent or self.pal["lcd_hi"]), 1.0, True
        if role == "line":
            return self.pal["lcd_fg"], 0.96, False
        return self.pal["lcd_dim2"], 0.92, False

    def art_well(self, img, box):
        pass

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        draw.text((x0, (y0 + y1) / 2), "[", font=P.font(h * 0.8, mono=True), fill=self.pal["rule"], anchor="lm")
        draw.text((x1, (y0 + y1) / 2), "]", font=P.font(h * 0.8, mono=True), fill=self.pal["rule"], anchor="rm")
        bx0, bx1 = x0 + h * 0.6, x1 - h * 0.6
        if d.fraction is None:
            text = _("live stream") if d.live else "--"
            P.put_text(img, ((bx0 + bx1) / 2, (y0 + y1) / 2), text, h * 0.6, self.pal["lcd_dim2"], mono=True,
                       anchor="mm")
            return
        n = max(8, int((bx1 - bx0) / max(4, h * 0.42)))
        sw = (bx1 - bx0) / n
        lit = round(n * d.fraction)
        for i in range(n):
            color = self.c("fill", d) if i < lit else self.pal["track"]
            draw.rectangle((bx0 + i * sw + 1, y0 + h * 0.3, bx0 + (i + 1) * sw - 1, y1 - h * 0.3), fill=color)

    def times(self, img, box, d):
        x0, y0, x1, y1 = box
        size = max(8, (y1 - y0) * 0.7)
        P.put_text(img, (x0, (y0 + y1) / 2), d.elapsed_text, size, self.pal["time_fg"], mono=True)
        P.put_text(img, (x1, (y0 + y1) / 2), d.total_text, size, self.pal["lcd_dim2"], mono=True, anchor="rm")

    def button(self, img, box, kind, enabled, active, d):
        draw = ImageDraw.Draw(img)
        color = (self.pal["lcd_hi"] if active else self.pal["btn_glyph"]) if enabled else self.pal["btn_off"]
        draw.rectangle(box, outline=color)
        P.glyph(draw, kind, P.inset(box, P.width(box) * 0.3), color)

    def toggle(self, img, box, kind, active, d):
        draw = ImageDraw.Draw(img)
        color = self.pal["lcd_hi"] if active else self.pal["btn_off"]
        P.glyph(draw, kind, P.inset(box, P.width(box) * 0.2), color)

    def volume(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        size = max(8, h * 0.55)
        label = "mute" if d.vol_muted else d.vol_label.lower()
        x = x0 + P.put_text(img, (x0, (y0 + y1) / 2), f"{label:<4}", size, (240, 90, 80) if d.vol_muted else
                            self.pal["lcd_dim2"], mono=True) + 4
        pw = P.text_width(" 150%", size, mono=True) if d.show_vol_percent else 0
        n = 14
        sw = (x1 - pw - x) / n
        frac = 0 if (d.vol_percent is None or d.vol_muted) else min(1.0, d.vol_percent / d.vol_scale)
        draw = ImageDraw.Draw(img)
        for i in range(n):
            lit = i / n < frac
            draw.rectangle((x + i * sw + 1, y0 + h * 0.3, x + (i + 1) * sw - 1, y1 - h * 0.3),
                           fill=self.c("fill", d) if lit else self.pal["track"])
        if d.show_vol_percent:
            P.put_text(img, (x1, (y0 + y1) / 2), d.vol_text, size, self.pal["lcd_fg"], mono=True, anchor="rm")

    def vis(self, img, box, d):
        x0, y0, x1, y1 = box
        ImageDraw.Draw(img).rectangle(box, fill=(0, 0, 0))
        super().vis(img, box, d)


# ================================================================ BIGX MULTIMEDIA SYSTEM

class BigX(Skin):
    id = "bigx"
    name = "BIGX Multimedia System"
    description = N_("Dark metallic Linux audio player of the 90s: glowing blue LCDs, state lamps, graphic EQ display.")
    pad = 5
    frame = 4
    title_h = 14
    has_readout = True
    vis_beside_readout = True
    time_inline = False
    marquee_loop = True
    caps_title = True
    default_frame = "bevel"
    source_prefix = ""
    pal = {
        "body": (44, 50, 64), "title_bg": (28, 32, 42), "title_fg": (170, 190, 220),
        "lcd_bg": (4, 8, 18), "lcd_fg": (92, 200, 255), "lcd_hi": (150, 225, 255), "lcd_dim2": (40, 110, 170),
        "time_fg": (92, 200, 255), "track": (14, 20, 34), "fill": (92, 200, 255), "accent": (92, 200, 255),
        "btn_face": (74, 82, 100), "btn_glyph": (210, 220, 236), "btn_off": (90, 98, 116),
        "bevel_hi": (130, 140, 162), "bevel_lo": (14, 16, 22), "vis_bg": (4, 8, 18),
        "vis": ((30, 90, 200), (70, 170, 255), (190, 240, 255)), "tele_bg": (4, 8, 18), "tele_fg": (92, 200, 255),
        "tele_accent": (150, 225, 255),
    }

    def chrome(self, img, L, d):
        draw = ImageDraw.Draw(img)
        P.vgrad(img, (0, 0, L.W, L.H), None, None, [(0, (70, 78, 96)), (0.5, (46, 52, 66)), (1, (32, 36, 48))])
        P.brushed(img, (0, 0, L.W, L.H), 3, seed=5)
        P.bevel(draw, (0, 0, L.W, L.H), (140, 150, 172), (10, 12, 16), depth=2)
        if L.title:
            x0, y0, x1, y1 = L.title
            h = y1 - y0
            P.vgrad(img, (2, 2, L.W - 2, y1), (60, 68, 86), (30, 34, 46))
            end = self.title_text(img, L.title, d, (178, 196, 226), size=h * 0.56)
            for k in range(2):
                yy = y0 + h * (0.42 + k * 0.2)
                draw.line((end + h * 0.6, yy, x1 - h * 0.6 - (h * 6 if d.source else 0), yy), fill=(100, 110, 132))
        for box in (L.info, L.readout, L.vis):
            if box:
                P.lcd_well(img, P.inset(box, -2), self.pal["lcd_bg"], rim_hi=(130, 140, 162), rim_lo=(10, 12, 16))
        if L.info and d.lcd_effect:
            P.dither_dots(img, P.inset(L.info, -2), (14, 24, 40), 0.5, 2)
        if L.art:
            P.lcd_well(img, P.inset(L.art, -3), (0, 0, 0), rim_hi=(130, 140, 162), rim_lo=(10, 12, 16))
        if L.tele and not L.tele_overlay:
            P.lcd_well(img, L.tele, self.pal["tele_bg"], rim_hi=(130, 140, 162), rim_lo=(10, 12, 16))

    def readout(self, img, box, d):
        super().readout(img, box, d)
        # State lamps in the LCD: they light only for states the player really reports.
        x0, y0, x1, y1 = box
        h = y1 - y0
        lamps = [("MUTE", bool(d.vol_muted))]
        if d.shuffle is not None:
            lamps.append(("SHUF", d.shuffle))
        if d.loop is not None:
            lamps.append(("REP", d.loop != "None"))
        size = max(6, h * 0.17)
        x = x0 + h * 0.1
        for label, lit in lamps:
            color = self.pal["lcd_hi"] if lit else P.mix(self.pal["lcd_bg"], self.pal["lcd_fg"], 0.18)
            x += P.put_text(img, (x, y1 - h * 0.17), label, size, color, bold=True, mono=True) + size * 0.6

    def role_style(self, role, d):
        if role == "title":
            return (d.accent or self.pal["lcd_hi"]), 1.08, False
        if role == "line":
            return self.pal["lcd_fg"], 0.95, False
        return self.pal["lcd_dim2"], 0.86, False

    def button(self, img, box, kind, enabled, active, d):
        x0, y0, x1, y1 = P.ibox(box)
        h = y1 - y0
        key = (x0 - (x1 - x0) * 0.1, y0 + h * 0.15, x1 + (x1 - x0) * 0.1, y1 - h * 0.15)
        P.vgrad(img, key, None, None, [(0, (110, 120, 140)), (1, (60, 66, 82))] if not active else
                [(0, (50, 56, 70)), (1, (90, 100, 120))])
        draw = ImageDraw.Draw(img)
        P.bevel(draw, key, (170, 180, 200), (12, 14, 18), inset_=active)
        color = ((150, 225, 255) if active else (220, 228, 240)) if enabled else (100, 108, 126)
        P.glyph(draw, kind, P.inset(key, P.height(key) * 0.24), color)

    def progress(self, img, box, d):
        x0, y0, x1, y1 = box
        h = y1 - y0
        draw = ImageDraw.Draw(img)
        P.lcd_well(img, (x0, y0 + h * 0.2, x1, y1 - h * 0.2), self.pal["lcd_bg"], rim_hi=(130, 140, 162),
                   rim_lo=(10, 12, 16))
        if d.fraction is not None:
            fx = x0 + 2 + (x1 - x0 - 4) * d.fraction
            P.hgrad(img, (x0 + 2, y0 + h * 0.3, max(x0 + 3, fx), y1 - h * 0.3), (20, 70, 160), self.c("fill", d))
            draw.rectangle((fx - 2, y0 + h * 0.1, fx + 2, y1 - h * 0.1), fill=(200, 236, 255))
        elif d.live:
            self.live_badge(img, box, d)

    def times(self, img, box, d):
        pass


SKINS = {cls.id: cls() for cls in (Bigamp, Bigmatch, Bigative, Bigalplayer, BigMediaPlayer, BigXMMS2, BigX)}

# The Modern Collection lives in its own package (bsmd.bigmedia.modern); it subclasses Skin above.
from .modern import MODERN_SKINS  # noqa: E402

SKINS.update((cls.id, cls()) for cls in MODERN_SKINS)


def get(skin_id):
    return SKINS.get(skin_id) or SKINS["bigamp"]
