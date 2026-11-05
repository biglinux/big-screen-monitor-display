"""Responsive layout shared by the seven skins.

Areas (every skin, every size):
    A title      skin name, distro logo, source application
    B art        album art / video thumbnail / original placeholder
    C info       title, artist, album, description, source (+ big LCD time
                 readout ``readout`` and the visualizer ``vis`` when they fit)
    D progress   elapsed, bar, total (``times`` + ``progress``)
    E controls   transport ``buttons`` and the ``volume`` meter
    F tele       optional telemetry strip (top, bottom or over the art)

Families by shape: ``micro`` (short side < 128 px: alternating pages, no
chrome), ``portrait``, ``landscape`` and ``ultrawide`` (aspect >= 2.6).
Nothing shrinks below a readable minimum; areas are dropped in a fixed
priority order instead (visualizer, readout, album line, buttons...).
"""

from dataclasses import dataclass, field

MICRO_SIDE = 128
MICRO_AREA = 36000
ULTRAWIDE = 2.6
TEXT_SCALE = {"small": 0.86, "normal": 1.0, "large": 1.18}
ART_SCALE = {"small": 0.8, "normal": 1.0, "large": 1.2}


@dataclass
class Layout:
    W: int
    H: int
    mode: str
    unit: float
    font: float                      # base text size in px
    title: tuple = None
    tele: tuple = None
    tele_overlay: bool = False
    art: tuple = None
    info: tuple = None
    readout: tuple = None
    vis: tuple = None
    times: tuple = None
    progress: tuple = None
    buttons: tuple = None
    volume: tuple = None
    body: tuple = None               # area inside the window chrome
    lines: int = 4                   # metadata lines that fit in ``info``
    extras: dict = field(default_factory=dict)

    def key(self):
        return (self.W, self.H, self.mode, self.title, self.tele, self.tele_overlay, self.art, self.info,
                self.readout, self.vis, self.times, self.progress, self.buttons, self.volume, self.body)


def is_micro(width, height):
    return min(width, height) < MICRO_SIDE or width * height < MICRO_AREA


def _r(box):
    return tuple(int(round(v)) for v in box) if box else None


def compute(width, height, skin, opts):
    """``opts``: title_bar, tele ('top'|'bottom'|'overlay'|None), vis, controls,
    volume, variant ('full'|'compact'|'party'|'info'), text_size, art_size."""
    W, H = width, height
    unit = min(W, H) / 320
    text_scale = TEXT_SCALE.get(opts.get("text_size"), 1.0)
    variant = opts.get("variant", "full")
    if is_micro(W, H):
        return _micro(W, H, skin, opts, text_scale)
    aspect = W / H
    mode = "ultrawide" if aspect >= ULTRAWIDE else ("portrait" if H > W * 1.15 else "landscape")
    base = max(10.0, min(28.0, (H if mode != "portrait" else W) / (300 / 13) * text_scale))
    if mode == "ultrawide":
        base = max(10.0, min(26.0, H / 13 * text_scale))
    pad = max(3, round(skin.pad * unit))
    frame = max(2, round(skin.frame * unit))
    L = Layout(W, H, mode, unit, base)
    x0, y0, x1, y1 = frame, frame, W - frame, H - frame
    if opts.get("title_bar", True) and variant != "compact":
        th = max(12, round(skin.title_h * unit * (0.85 if mode == "ultrawide" else 1.0)))
        L.title = _r((0, 0, W, th + frame))
        y0 = th + frame
    tele = opts.get("tele")
    tele_h = max(13, round(base * 1.45))
    if tele in ("top", "bottom"):
        if tele == "top":
            L.tele = _r((x0, y0, x1, y0 + tele_h))
            y0 += tele_h + pad // 2
        else:
            L.tele = _r((x0, y1 - tele_h, x1, y1))
            y1 -= tele_h + pad // 2
    L.body = _r((x0, y0, x1, y1))
    x0, y0, x1, y1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad
    gutter = pad
    art_scale = ART_SCALE.get(opts.get("art_size"), 1.0) * (1.25 if variant == "party" else 1.0)
    controls = opts.get("controls", True)
    volume = opts.get("volume", True)
    row = max(16, round(base * 1.9))              # control row height
    prog_h = max(12, round(base * 1.35))

    if mode == "landscape":
        rows = prog_h + gutter + ((row + gutter) if (controls or volume) else 0)
        top_h = (y1 - y0) - rows
        side = min(top_h, (x1 - x0) * 0.42 * art_scale, (x1 - x0) * 0.55)
        if variant == "info":
            side *= 0.8
        L.art = _r((x0, y0, x0 + side, y0 + side))
        info = (x0 + side + gutter, y0, x1, y0 + top_h)
        # A centred art when the info column is taller than the art.
        if top_h > side:
            L.art = _r((x0, y0 + (top_h - side) / 2, x0 + side, y0 + (top_h - side) / 2 + side))
        L.info = _r(info)
        y = y0 + top_h + gutter
        L.times, L.progress = _progress_row(x0, y, x1, prog_h, base, skin)
        y += prog_h + gutter
        _controls_row(L, x0, y, x1, row, controls, volume, base)
    elif mode == "portrait":
        rows = prog_h + gutter + ((row + gutter) if controls else 0) + ((row + gutter) if volume else 0)
        info_min = base * 1.3 * (4 if variant == "info" else 3) + gutter
        avail = (y1 - y0) - rows - info_min
        side = max(40, min((x1 - x0) * 0.86 * min(1.0, art_scale), avail, (y1 - y0) * 0.5 * art_scale))
        L.art = _r(((W - side) / 2, y0, (W + side) / 2, y0 + side))
        y = y0 + side + gutter
        L.info = _r((x0, y, x1, y1 - rows))
        y = y1 - rows + gutter * 0
        L.times, L.progress = _progress_row(x0, y, x1, prog_h, base, skin)
        y += prog_h + gutter
        if controls:
            L.buttons = _r((x0, y, x1, y + row))
            y += row + gutter
        if volume:
            L.volume = _r((x0, y, x1, y + row * 0.8))
    else:  # ultrawide
        side = y1 - y0
        L.art = _r((x0, y0, x0 + side, y1))
        right_w = max(160, (x1 - x0) * 0.30)
        L.info = _r((x0 + side + gutter, y0, x1 - right_w - gutter, y1))
        rx0 = x1 - right_w
        L.times, L.progress = _progress_row(rx0, y0, x1, prog_h, base, skin)
        y = y0 + prog_h + gutter
        row = max(row, min(base * 3.2, (y1 - y) / 2.3))
        _controls_row(L, rx0, y, x1, min(row, (y1 - y) - 2), controls, volume, base, stacked=(y1 - y) > row * 2.1)

    _split_info(L, skin, opts, variant)
    if not skin.time_inline and L.readout is None and L.progress and not L.times:
        # No room for the big LCD time: fall back to times beside the bar.
        x0_, y0_, x1_, y1_ = L.progress
        tw = base * 3.3
        L.times = L.progress
        L.progress = _r((x0_ + tw, y0_, x1_ - tw, y1_))
    if tele == "overlay" and L.art:
        ax0, ay0, ax1, ay1 = L.art
        L.tele = _r((ax0, ay1 - tele_h, ax1, ay1))
        L.tele_overlay = True
    return L


def _progress_row(x0, y, x1, h, base, skin):
    time_w = base * (3.3 if skin.time_inline else 0)
    if skin.time_inline:
        return _r((x0, y, x1, y + h)), _r((x0 + time_w, y, x1 - time_w, y + h))
    return None, _r((x0, y, x1, y + h))


def _controls_row(L, x0, y, x1, row, controls, volume, base, stacked=False):
    if controls and volume:
        if stacked:
            L.buttons = _r((x0, y, x1, y + row))
            L.volume = _r((x0, y + row + 4, x1, y + row * 1.8 + 4))
            return
        split = x0 + (x1 - x0) * 0.6
        L.buttons = _r((x0, y, split - 4, y + row))
        L.volume = _r((split + 4, y, x1, y + row))
    elif controls:
        L.buttons = _r((x0, y, x1, y + row))
    elif volume:
        L.volume = _r((x0, y, x1, y + row))


def _split_info(L, skin, opts, variant):
    """Place the big time readout and the visualizer inside the info area."""
    x0, y0, x1, y1 = L.info
    w, h = x1 - x0, y1 - y0
    line_h = L.font * 1.3
    want_vis = opts.get("vis") and variant != "info"
    want_readout = skin.has_readout and variant != "compact"
    if want_readout and L.mode != "portrait" and w > L.font * 14 and h > line_h * 3.4:
        rh = max(L.font * 1.6, min(h * 0.34, L.font * 2.6))
        rw = min(w * 0.42, rh * 3.3)
        L.readout = _r((x0, y0, x0 + rw, y0 + rh))
        if want_vis and h > rh + line_h * 3.6 and L.mode == "landscape" and skin.vis_beside_readout:
            L.vis = _r((x0 + rw + 6, y0, x1, y0 + rh))
            want_vis = False
        y0 = y0 + rh + max(3, L.font * 0.35)
    if want_vis:
        vh = min(h * (0.42 if variant == "party" else 0.3), L.font * (4.2 if variant == "party" else 3))
        if (y1 - y0) - vh >= line_h * 2.2 and vh >= 12:
            L.vis = _r((x0, y1 - vh, x1, y1))
            y1 -= vh + 3
    L.extras["text"] = _r((x0, y0, x1, y1))
    L.lines = max(1, int((y1 - y0) // line_h))


def _micro(W, H, skin, opts, text_scale):
    portrait = H > W
    unit = min(W, H) / 80
    base = max(8.0, min(14.0, min(W, H) / 7.2 * text_scale))
    L = Layout(W, H, "micro", unit, base)
    pad = 2
    if portrait:
        side = W - pad * 2
        L.art = _r((pad, pad, pad + side, pad + side))
        y = pad + side + 2
        L.info = _r((pad, y, W - pad, H - base * 2.2))
        L.progress = _r((pad, H - base * 2.1, W - pad, H - base * 1.6))
        L.times = _r((pad, H - base * 1.55, W - pad, H - 1))
    else:
        side = H - pad * 2
        L.art = _r((pad, pad, pad + side, pad + side))
        x = pad + side + 3
        L.info = _r((x, pad, W - pad, H - base * 2.1))
        L.progress = _r((x, H - base * 2.0, W - pad, H - base * 1.5))
        L.times = _r((x, H - base * 1.45, W - pad, H - 1))
    L.body = (0, 0, W, H)
    L.extras["text"] = L.info
    L.lines = max(1, int((L.info[3] - L.info[1]) // (base * 1.25)))
    return L
