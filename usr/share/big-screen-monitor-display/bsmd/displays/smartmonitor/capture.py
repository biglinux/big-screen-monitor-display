"""Turn any theme into a SmartMonitor dashboard by watching it draw.

The panel cannot show frames, only a flashed picture plus numbers and bars.
Instead of re-drawing every theme by hand, the theme's own renderer is run
with its ``ImageDraw`` calls intercepted:

1. render with fixed telemetry and a frozen clock -> the list of calls;
2. render again with one field changed (CPU usage, RAM used...) or with the
   clock moved; calls whose text or geometry changed depend on it;
3. render a last time with those calls rewritten: a value inside a text is
   cut out (the static words around it are still drawn by the theme, at the
   same place, font and colour), a moving bar is left out. That picture is the
   background;
4. every value becomes a number widget built from the *same font, size,
   colour and alignment* the theme used, and every bar a panel bar; a
   *binding* (:mod:`.fields`) says how to compute it from the live telemetry
   (the scale is measured: "11.3" for 11571 MB is x 1/1024).

Everything here changes process-wide state (telemetry, the clock, PIL), so it
runs in a separate process (:mod:`.worker`), never inside the service.
"""

import datetime
import difflib
import json
import math
import os
import random
import re
import sys
import time

from PIL import Image, ImageColor, ImageDraw, ImageFont

from . import fields, imgdat

SIZE = (480, 320)
DRAW_METHODS = ("text", "rectangle", "rounded_rectangle", "line", "ellipse", "pieslice", "arc", "polygon",
                "point", "chord", "regular_polygon")
RECTS = ("rectangle", "rounded_rectangle")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")      # "Quarta-feira" is one word
NICE_SCALES = (1.0, 1e3, 1e-3, 1024.0, 1 / 1024, 1 / 1048576, 8.0, 0.125, 125.0, 1 / 125, 1e6 / 8 / 1024, 100.0,
               0.01, 1 / 60, 1 / 3600, 1 / 86400, 1e-6, 1e6)
MAX_NUMBERS = 26          # firmware limits minus a margin (imgdat.MAX_*)
MAX_WIDGETS = 38
MAX_CHANNELS = 25

# How a theme is best adapted: settings it is captured with, animation frames.
THEME_OPTIONS = {
    "standard": {"settings": {"std_side_panel": "none"}},
    "gkrellm": {"settings": {}},
    "planet": {"settings": {}},
    "old_computer": {"settings": {}},
    # The scene keeps its art; what moves (the castaway, the palm) becomes looping
    # sprites of 24 frames, 4 per second. Speech is text: no bubbles on the panel.
    "brother_away": {"settings": {"ba_catchphrases": False, "ba_subtitles": False, "ba_dialogue_frequency": "low"},
                     "bars": False,         # the castaway reacts to the load: that is art, not a gauge
                     "calm": "_castaway_home",
                     "sprites": {"frames": 24, "dt": 0.25, "max_area": 20000, "budget": 1_000_000}},
    "kojiro": {"settings": {}},
    # Without media (the panel cannot show titles or covers live) the player's own
    # full-screen telemetry mode, in the chosen skin.
    # While a song plays: the player itself (time, progress, volume live). Without
    # media: the player's own full-screen telemetry mode, in the chosen skin.
    "big_media_player": {"settings": {"bmp_idle_mode": "telemetry", "bmp_idle_after": 600,
                                      "bmp_preview_demo": False}},
}


class CaptureError(Exception):
    pass


# ---------------------------------------------------------------- recording

class Call:
    __slots__ = ("args", "font", "index", "kwargs", "method", "paint", "size", "target", "tf")

    def __init__(self, index, method, size, args, kwargs, font, target=None):
        self.index, self.method, self.size = index, method, size
        self.args, self.kwargs, self.font = args, kwargs, font
        self.target = target          # id() of the image drawn on
        self.tf = None                # (sx, sy, ox, oy): that image's pixels on the final frame
        self.paint = None             # colour of a text drawn into a mask, then pasted in colour

    def key(self):
        """What a call *is* regardless of the values it draws (used to match renders)."""
        font = getattr(self.font, "path", None)     # not the size: themes shrink text to fit
        if self.method == "text":
            # The shape of the string (letters -> a, digits -> #) and its row keep a
            # label, its value and its unit apart even when they share a font.
            text = self.text if isinstance(self.text, str) else ""
            skeleton = re.sub(r"\d+(?:[.,]\d+)?", "#", WORD.sub("a", text))
            try:
                row = round(float(self.xy[1]) / 3)
            except (TypeError, ValueError, IndexError):
                row = None
            # Only the image height: text drawn on a tile of its own size changes width.
            return ("text", self.size[1], font, self.kwargs.get("anchor"), skeleton, row)
        # Colours are content, not identity: alert colours change with the value.
        return (self.method, self.size)

    def content(self):
        def plain(value):
            if isinstance(value, ImageFont.FreeTypeFont):
                return ("font", value.path, value.size)
            if isinstance(value, Image.Image):
                return ("image", value.size, value.mode)
            return repr(value)
        return (tuple(plain(v) for v in self.args), tuple(sorted((k, plain(v)) for k, v in self.kwargs.items())))

    @property
    def text(self):
        return self.args[1] if self.method == "text" and len(self.args) > 1 else self.kwargs.get("text", "")

    @property
    def xy(self):
        return self.args[0] if self.args else self.kwargs.get("xy")


class SegmentFont:
    """Stands for a theme's seven-segment "font" (Kojiro's ``seven_segment``, the Big
    Media Player's ``seven_seg``), so a segment readout is captured like a text and
    its digits come from the theme's own drawing."""

    path = None

    def __init__(self, size, draw, width=0.52, thick=0.11, thick_min=2.0, gap=0.16, narrow=":.;"):
        self.size = size
        self._draw = draw           # draw(image, xy, text, size, colour, anchor)
        self.width, self.thick, self.thick_min, self.gap, self.narrow = width, thick, thick_min, gap, narrow

    def _advance(self, ch, size=None):
        size = size or self.size
        if ch in self.narrow:
            return max(self.thick_min, size * self.thick) * 2.2
        return size * self.width + size * self.gap

    def getlength(self, text):
        return sum(self._advance(ch) for ch in text)

    def anchor_origin(self, xy, text, anchor):
        """Top-left of the drawing (the segment functions anchor on their own box)."""
        total = self.getlength(text) - (self.size * self.gap if text and text[-1] not in self.narrow else 0)
        x, y = xy
        anchor = anchor or "la"
        if anchor[0] == "m":
            x -= total / 2
        elif anchor[0] == "r":
            x -= total
        if anchor[1] == "m":
            y -= self.size / 2
        elif anchor[1] in ("b", "d"):
            y -= self.size
        return x, y

    def atlas(self, size):
        import numpy as np
        cells, widths = bytearray(), []
        for glyph in imgdat.GLYPHS:
            width = max(1, math.ceil(self._advance(glyph, size)))
            tile = Image.new("RGBA", (width, size + 1), (0, 0, 0, 0))
            self._draw(tile, (0, 0), glyph, size, (255, 255, 255, 255), "la")
            rgba = np.asarray(tile, dtype=np.float32)
            # Coverage = alpha x brightness: lit segments 255, unlit "ghost" ones faint.
            coverage = rgba[..., 3] * rgba[..., :3].max(axis=2) / 255
            cells += np.clip(coverage, 0, 255).astype(np.uint8).tobytes()
            widths.append(width)
        return imgdat.Atlas(tuple(widths), size + 1, bytes(cells))


class Recorder:
    """Intercepts ImageDraw calls (``plan`` maps a call index to an action) and
    follows where every image ends up (pasted, composited, cropped, resized), so a
    call drawn on a layer can be placed on the final frame."""

    def __init__(self):
        self.calls = []
        self.plan = {}
        self.original = {}
        self.links = {}           # id(child) -> [(id(parent), sx, sy, ox, oy)]
        self.keep = []            # images alive for the whole render (stable ids)
        self.mask_colors = {}     # id(mask) -> colour it was pasted with
        self.seen = {}            # call identity -> occurrences so far in this render
        self.muted = False        # drawing pieces of a planned call: not recorded

    def __enter__(self):
        for name in DRAW_METHODS:
            method = getattr(ImageDraw.ImageDraw, name, None)
            if method is None:
                continue
            self.original[name] = method
            setattr(ImageDraw.ImageDraw, name, self._wrap(name, method))
        self._patch_images()
        self._patch_segments()
        return self

    def __exit__(self, *exc):
        for name, method in self.original.items():
            if name.startswith("segment."):
                module, attr, real = method
                setattr(module, attr, real)
            elif name.startswith("Image."):
                setattr(Image.Image, name[6:], method)
            elif name.startswith("module."):
                setattr(Image, name[7:], method)
            else:
                setattr(ImageDraw.ImageDraw, name, method)

    def _patch_segments(self):
        hooks = []
        try:
            from ...kojiro import draw as kojiro_draw
            hooks.append((kojiro_draw, "seven_segment",
                          lambda real: (lambda img, xy, text, size, colour, anchor="la": real(img, xy, text, size,
                                                                                           colour, anchor)),
                          lambda args, kwargs: (args[0], args[1], args[2], args[3], args[4],
                                                args[5] if len(args) > 5 else kwargs.get("anchor", "la")),
                          {"width": 0.52, "thick": 0.11, "thick_min": 2.0, "gap": 0.16, "narrow": ":.;"}))
        except ImportError:
            pass
        try:
            from ...bigmedia import paint as bmp_paint
            hooks.append((bmp_paint, "seven_seg",
                          lambda real: (lambda img, xy, text, size, colour, anchor="la": real(
                              img, xy, text, size, colour, anchor=anchor, bg=(0, 0, 0))),
                          lambda args, kwargs: (args[0], args[1], args[2], args[3], args[4],
                                                args[6] if len(args) > 6 else kwargs.get("anchor", "la")),
                          {"width": 0.52, "thick": 0.12, "thick_min": 1.5, "gap": 0.18, "narrow": ":."}))
        except ImportError:
            pass
        for module, name, glyphs, unpack, metrics in hooks:
            self._hook_segment(module, name, glyphs, unpack, metrics)

    def _hook_segment(self, module, name, glyphs, unpack, metrics):
        real = getattr(module, name)
        self.original["segment." + module.__name__ + "." + name] = (module, name, real)
        recorder = self
        draw_glyphs = glyphs(real)

        def segment(*args, **kwargs):
            if recorder.muted:
                return real(*args, **kwargs)
            layer, xy, text, size, colour, anchor = unpack(args, kwargs)
            font = SegmentFont(size, draw_glyphs, **metrics)
            call = Call(len(recorder.calls), "text", layer.size, (xy, text), {"fill": colour, "anchor": anchor},
                        font, id(layer))
            recorder.keep.append(layer)
            recorder.calls.append(call)
            key = call.key()
            occurrence = recorder.seen.get(key, 0)
            recorder.seen[key] = occurrence + 1
            action = recorder.plan.get((key, occurrence))
            if action is None:
                return real(*args, **kwargs)
            # Same bookkeeping as for real text: the inner polygons are recorded on a scratch layer.
            scratch = Image.new("RGBA", layer.size, (0, 0, 0, 0))
            total = real(scratch, *args[1:], **kwargs)
            if action != "skip":
                recorder.muted = True
                try:
                    for piece, x, y in action[1]:
                        piece_args = list(args)
                        piece_args[1], piece_args[2] = (x, y), piece
                        piece_kwargs = dict(kwargs)
                        if "anchor" in piece_kwargs or len(piece_args) <= 5:
                            piece_kwargs["anchor"] = "la"
                        real(*piece_args, **piece_kwargs)
                finally:
                    recorder.muted = False
            return total
        setattr(module, name, segment)

    def reset(self, plan=None):
        self.calls, self.links, self.keep, self.mask_colors, self.seen = [], {}, [], {}, {}
        self.plan = plan or {}

    # ------------------------------------------------------------ provenance
    def _link(self, child, parent, sx=1.0, sy=1.0, ox=0.0, oy=0.0):
        if not isinstance(child, Image.Image) or not isinstance(parent, Image.Image) or child is parent:
            return
        self.keep.extend((child, parent))
        self.links.setdefault(id(child), []).append((id(parent), sx, sy, ox, oy))

    def _patch_images(self):
        recorder = self
        original = self.original

        def method(name, linker):
            real = getattr(Image.Image, name)
            original["Image." + name] = real

            def wrapper(image, *args, **kwargs):
                result = real(image, *args, **kwargs)
                try:
                    linker(image, result, args, kwargs)
                except Exception:  # noqa: BLE001, S110 - bookkeeping must never break a theme
                    pass
                return result
            setattr(Image.Image, name, wrapper)

        def paste(image, result, args, kwargs):
            source = args[0] if args else kwargs.get("im")
            box = args[1] if len(args) > 1 else kwargs.get("box")
            mask = args[2] if len(args) > 2 else kwargs.get("mask")
            if isinstance(box, Image.Image):
                box, mask = None, box
            x, y = (box[0], box[1]) if box else (0, 0)
            recorder._link(source, image, 1.0, 1.0, x, y)
            recorder._link(mask, image, 1.0, 1.0, x, y)      # paste(colour, box, text_mask)
            if isinstance(mask, Image.Image) and source is not None:
                colour = source
                if isinstance(source, Image.Image):
                    # A solid image pasted through a mask is the same as a colour.
                    extrema = source.convert("RGB").getextrema()
                    colour = tuple(low for low, high in extrema) if all(low == high for low, high in extrema) \
                        else None
                if colour is not None:
                    recorder.mask_colors[id(mask)] = colour   # the colour a text mask is painted with

        def composite(image, result, args, kwargs):
            source = args[0] if args else kwargs.get("im")
            dest = args[1] if len(args) > 1 else kwargs.get("dest", (0, 0))
            src = args[2] if len(args) > 2 else kwargs.get("source", (0, 0))
            recorder._link(source, image, 1.0, 1.0, dest[0] - src[0], dest[1] - src[1])

        def same(image, result, args, kwargs):
            recorder._link(image, result)

        def crop(image, result, args, kwargs):
            box = args[0] if args else kwargs.get("box") or (0, 0, 0, 0)
            recorder._link(image, result, 1.0, 1.0, -box[0], -box[1])

        def resize(image, result, args, kwargs):
            if isinstance(result, Image.Image) and image.size[0] and image.size[1]:
                recorder._link(image, result, result.size[0] / image.size[0], result.size[1] / image.size[1])

        method("paste", paste)
        method("alpha_composite", composite)
        for name in ("copy", "convert", "filter", "point"):
            method(name, same)
        method("crop", crop)
        method("resize", resize)

        def function(name):
            real = getattr(Image, name)
            original["module." + name] = real

            def wrapper(*args, **kwargs):
                result = real(*args, **kwargs)
                for source in args[:2]:
                    recorder._link(source, result)
                return result
            setattr(Image, name, wrapper)
        for name in ("alpha_composite", "composite", "blend"):
            function(name)

    def resolve(self, root):
        """Fill ``call.tf`` for every call whose image reaches ``root``."""
        cache = {id(root): (1.0, 1.0, 0.0, 0.0)}

        def find(node, depth=0, seen=()):
            if node in cache:
                return cache[node]
            if depth > 12 or node in seen:
                return None
            for parent, sx, sy, ox, oy in self.links.get(node, ()):
                upper = find(parent, depth + 1, seen + (node,))
                if upper is not None:
                    psx, psy, pox, poy = upper
                    cache[node] = (sx * psx, sy * psy, ox * psx + pox, oy * psy + poy)
                    return cache[node]
            return None
        for call in self.calls:
            call.tf = find(call.target)
            if call.target in self.mask_colors:
                call.paint = self.mask_colors[call.target]

    # ------------------------------------------------------------ drawing
    def _wrap(self, name, method):
        recorder = self

        def wrapper(draw, *args, **kwargs):
            if recorder.muted:
                return method(draw, *args, **kwargs)
            font = kwargs.get("font")
            if name == "text" and font is None and len(args) > 3:
                font = args[3]
            target = getattr(draw, "_image", None)
            if target is not None:
                recorder.keep.append(target)
            call = Call(len(recorder.calls), name, draw.im.size, args, kwargs, font, id(target))
            recorder.calls.append(call)
            # Plans are addressed by (identity, occurrence): the n-th call that looks
            # like this one. Stable even when a theme adds a call somewhere else.
            key = call.key()
            occurrence = recorder.seen.get(key, 0)
            recorder.seen[key] = occurrence + 1
            action = recorder.plan.get((key, occurrence))
            if action is not None and action != "skip" and name != "text":
                action = None
            if action is None:
                return method(draw, *args, **kwargs)
            # Still run the call on a scratch image: calls made inside it (multiline
            # text) are recorded too, so the indices of later calls do not shift.
            scratch = ImageDraw.Draw(Image.new(draw.im.mode if draw.im.mode in ("1", "L", "RGB", "RGBA") else "RGBA",
                                               draw.im.size))
            try:
                method(scratch, *args, **kwargs)
            except Exception:  # noqa: BLE001, S110 - the scratch copy is only for bookkeeping
                pass
            if action == "skip":
                return None
            # ("pieces", [(text, x, y)]): draw only the static parts of a text.
            for text, x, y in action[1]:
                piece_kwargs = dict(kwargs, anchor="la")
                method(draw, (x, y), text, *args[2:], **piece_kwargs)
            return None
        return wrapper


# ---------------------------------------------------------------- frozen world

class _Frozen:
    def __init__(self):
        self.now = fields.T0
        self.saved = {}

    def install(self):
        frozen = self
        real_datetime, real_date = datetime.datetime, datetime.date

        class FrozenDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                value = frozen.now
                return value if tz is None else value.replace(tzinfo=tz)

            @classmethod
            def today(cls):
                return frozen.now

            @classmethod
            def utcnow(cls):
                return frozen.now - datetime.timedelta(seconds=time.localtime().tm_gmtoff)

        class FrozenDate(real_date):
            @classmethod
            def today(cls):
                return frozen.now.date()

        self.saved = {"datetime": real_datetime, "date": real_date, "time": time.time,
                      "monotonic": time.monotonic, "localtime": time.localtime, "strftime": time.strftime,
                      "gmtime": time.gmtime}
        datetime.datetime, datetime.date = FrozenDateTime, FrozenDate
        time.time = lambda: frozen.now.timestamp()
        time.monotonic = lambda: 1000.0 + (frozen.now - fields.T0).total_seconds()
        localtime, gmtime, strftime = time.localtime, time.gmtime, time.strftime
        time.localtime = lambda secs=None: localtime(frozen.now.timestamp() if secs is None else secs)
        time.gmtime = lambda secs=None: gmtime(frozen.now.timestamp() if secs is None else secs)
        time.strftime = lambda fmt, t=None: strftime(fmt, time.localtime() if t is None else t)
        for name, module in list(sys.modules.items()):
            if not name.startswith("bsmd") or module is None:
                continue
            for attr, value in list(vars(module).items()):
                if value is real_datetime:
                    setattr(module, attr, FrozenDateTime)
                elif value is real_date:
                    setattr(module, attr, FrozenDate)


# ---------------------------------------------------------------- rendering

def _calm(theme_id, settings):
    """Settings with alert colours off: a bar photographed full must keep its normal colour."""
    calm = dict(settings, std_alert_colors=False, bmp_tele_alert_cpu=100, bmp_tele_alert_temp=110)
    kojiro = settings.get("kojiro")
    if isinstance(kojiro, dict):
        kojiro = json.loads(json.dumps(kojiro))
        for layout_ in (kojiro.get("layouts") or {}).values():
            for widget in layout_ or []:
                if isinstance(widget, dict):
                    widget["alerts"] = False
        calm["kojiro"] = kojiro
    return calm


class Scene:
    def __init__(self, theme_id, settings, stats):
        from ... import runtime, telemetry, themes
        self.theme_id = theme_id
        options = THEME_OPTIONS.get(theme_id, {})
        self.settings = dict(settings, theme=theme_id, **options.get("settings", {}))
        self.base = fields.base_stats(stats)
        self.telemetry, self.themes, self.runtime = telemetry, themes, runtime
        self.clock = _Frozen()
        self.clock.install()
        self.seed = 1234
        self.last_theme = None
        self.art = None               # the current cover (PIL) when the panel follows songs

    def _state_copy(self):
        """A private copy of the themes' saved progress (Brother Away's story), fresh for
        every render: the capture shows the user's story but never changes it."""
        import shutil
        import tempfile
        if getattr(self, "_state_tmp", None) is None:
            self._state_tmp = tempfile.mkdtemp(prefix="bsmd-capture-")
        source = self.runtime.state_dir()
        for name in ("brother_away.json",):
            target = os.path.join(self._state_tmp, name)
            try:
                shutil.copyfile(os.path.join(source, name), target)
            except OSError:
                try:
                    os.unlink(target)
                except OSError:
                    pass
        return self._state_tmp

    def render(self, recorder, changes=None, when=None, plan=None, settings=None):
        stats = dict(self.base)
        stats.update(changes or {})
        self.clock.now = when or fields.T0
        tele = self.telemetry
        tele.SYSTEM_STATS.clear()
        tele.SYSTEM_STATS.update(stats)
        for name in ("CPU_TEMP_HISTORY", "CPU_USAGE_HISTORY", "CPU_USER_HISTORY", "CPU_SYSTEM_HISTORY",
                     "RAM_USAGE_HISTORY", "GPU_USAGE_HISTORY", "GPU_MEM_HISTORY", "DISK_IO_HISTORY",
                     "NET_RX_HISTORY", "NET_TX_HISTORY"):
            history = getattr(tele, name, None)
            if history is not None:
                history[:] = [20] * len(history)
        random.seed(self.seed)
        _clear_theme_caches()
        recorder.reset(plan)
        ctx = self.runtime.RenderContext(preview=False)
        ctx.state_dir = self._state_copy()    # the user's saved progress, read only
        ctx.media = lambda stats=stats: _media_state(stats, self.art)
        theme = self.themes.create(self.theme_id, ctx)
        try:
            image = self.themes.render_for_panel(theme, SIZE[0], SIZE[1], dict(settings or self.settings), ctx)
        finally:
            closer = getattr(theme, "close", None)
            if closer:
                closer()
        recorder.resolve(image)
        calls = list(recorder.calls)
        recorder.keep = []
        self.last_theme = theme
        return image.convert("RGB"), calls

    def choose_seed(self, recorder):
        """A random seed giving a representative moment (Brother Away: the castaway at
        home on the island, not away on the raft)."""
        check = THEME_OPTIONS.get(self.theme_id, {}).get("calm")
        if not check:
            return
        for seed in range(1234, 1274):
            self.seed = seed
            self.render(recorder)
            if globals()[check](self.last_theme):
                return
        self.seed = 1234


def _match(base, other):
    """Pairs (base index, other index) of calls that are the same drawing operation.

    A block that differs (a bar drawn with more segments, a longer list) is matched
    again on its own, and a call whose identity is unique on both sides of what is
    left is paired too, so a value next to a growing bar is still recognised."""
    base_keys, other_keys = [c.key() for c in base], [c.key() for c in other]
    pairs, unmatched = [], set()

    def walk(i1, i2, j1, j2, depth):
        matcher = difflib.SequenceMatcher(None, base_keys[i1:i2], other_keys[j1:j2], autojunk=False)
        for tag, a1, a2, b1, b2 in matcher.get_opcodes():
            a1, a2, b1, b2 = a1 + i1, a2 + i1, b1 + j1, b2 + j1
            if tag == "equal":
                pairs.extend(zip(range(a1, a2), range(b1, b2)))
            elif tag == "replace" and depth < 3 and (a2 - a1, b2 - b1) != (i2 - i1, j2 - j1):
                walk(a1, a2, b1, b2, depth + 1)
            else:
                left = {}
                for b in range(b1, b2):
                    left.setdefault(other_keys[b], []).append(b)
                counts = {}
                for a in range(a1, a2):
                    counts[base_keys[a]] = counts.get(base_keys[a], 0) + 1
                for a in range(a1, a2):
                    candidates = left.get(base_keys[a], [])
                    if counts[base_keys[a]] == 1 and len(candidates) == 1:
                        pairs.append((a, candidates[0]))
                    else:
                        unmatched.add(a)
    walk(0, len(base), 0, len(other), 0)
    return pairs, unmatched


def _color(fill):
    if fill is None:
        return (255, 255, 255)
    if isinstance(fill, str):
        return ImageColor.getrgb(fill)[:3]
    if isinstance(fill, int):
        return (fill & 0xFF, (fill >> 8) & 0xFF, (fill >> 16) & 0xFF)
    return tuple(int(v) for v in fill[:3])


def _fill_of(call):
    if call.paint is not None:
        return _color(call.paint)
    fill = call.kwargs.get("fill")
    if fill is None and call.method == "text" and len(call.args) > 2:
        fill = call.args[2]
    return _color(fill)


def _as_float(token):
    return float(token.replace(",", "."))


def _decimals(token):
    match = re.search(r"[.,](\d+)$", token)
    return len(match.group(1)) if match else 0


# ---------------------------------------------------------------- analysis

class Capture:
    def __init__(self, theme_id, settings, stats):
        self.scene = Scene(theme_id, settings, stats)
        self.recorder = Recorder()
        self.deps = {}            # base call index -> {source: other call}
        self._without_decimals = {}   # call index -> plan when its decimals are left out
        self.base_image = None
        self.base_calls = []

    def run(self):
        with self.recorder:
            self.scene.render(self.recorder)          # warm up: themes fill caches on their first frame
            self.scene.choose_seed(self.recorder)
            self.base_image, self.base_calls = self.scene.render(self.recorder)
            media = self.scene.base.get("media") or {}
            sources = {name: (spec[1][1](self.scene.base), None) for name, spec in fields.FIELDS.items()
                       if media.get("present") or not name.startswith("media_")}
            sources["clock"] = ({"boot_time": fields.T1.timestamp() - fields.BOOT0}, fields.T1)
            sources["noise"] = (fields.noise(self.scene.base), None)
            if media.get("present") and not self.scene.settings.get("sm_bmp_track_refresh"):
                # Title, artist and cover cannot follow the songs live: left out.
                sources["noise_track"] = (fields.track_noise(self.scene.base), None)
            self.variants = {}
            for name, (changes, when) in sources.items():
                stats_b = dict(self.scene.base)
                stats_b.update(changes)
                _image, calls = self.scene.render(self.recorder, changes, when)
                pairs, unmatched = _match(self.base_calls, calls)
                for i, j in pairs:
                    if self.base_calls[i].content() != calls[j].content():
                        self.deps.setdefault(i, {})[name] = calls[j]
                for i in unmatched:
                    self.deps.setdefault(i, {})[name] = None
                self.variants[name] = (stats_b, when or fields.T0)
            candidates, plan = self._widgets()
            candidates.extend(self._photo_bars(plan))
            kept, bindings, dropped = self._select(candidates)
            self._close_gaps(kept, bindings)
            # A text whose every value was left out goes away whole (no "ENC  %").
            with_values = {c[3] for c in candidates if c[1] is not None}
            for index in with_values - {c[3] for c in kept}:
                plan[index] = "skip"
            with_decimals = {c[3] for c in kept if c[2].get("part") == "frac"}
            for index, action in self._without_decimals.items():
                if index not in with_decimals and plan.get(index) != "skip":
                    plan[index] = action
            background = self._render_planned(plan)
            self._photo_bars(plan, (background, [c[1] for c in kept if isinstance(c[1], imgdat.Bar)], plan))
            frames = self._frames(plan)
            sprites = self._sprites(plan, [c[1].box for c in kept if isinstance(c[1], imgdat.Number)])
        theme = self._theme(background, frames, candidates, kept, bindings, dropped)
        theme[0].sprites = sprites
        problems = theme[0].check()
        if problems:
            raise CaptureError("; ".join(problems))
        return theme

    # ------------------------------------------------------------ widgets
    @staticmethod
    def _frame_point(tf, x, y):
        sx, sy, ox, oy = tf
        return x * sx + ox, y * sy + oy

    def _widgets(self):
        """Candidate widgets (with priority) and the background plan."""
        plan, candidates = {}, []
        for index, sources in sorted(self.deps.items()):
            call = self.base_calls[index]
            dynamic = {name: other for name, other in sources.items()}
            options = THEME_OPTIONS.get(self.scene.theme_id, {})
            animated = options.get("frames", 1) > 1 or bool(options.get("sprites"))
            if call.method != "text" and animated:
                continue                  # an animated scene's art (moves with time, reacts to load): keep it
            if any(name.startswith("noise") for name in dynamic):
                plan[index] = "skip"      # shows data no field covers: never frozen, left out
                continue
            if call.method == "text":
                action, found = self._text(call, dynamic)
                plan[index] = action
                candidates.extend((*item, index) for item in found)
            elif call.method in RECTS:
                plan[index] = "skip"      # bars are found by photographing them (see _photo_bars)
            else:
                plan[index] = "skip"      # graphs, rings: no panel equivalent
        return candidates, plan

    def _text(self, call, dynamic):
        """Rewrite one dynamic text: keep its static words, extract its numbers."""
        text = call.text if isinstance(call.text, str) else ""
        font = call.font
        if not text or not isinstance(font, (ImageFont.FreeTypeFont, SegmentFont)) or "\n" in text or \
                call.tf is None:
            return "skip", []
        tokens = list(NUMBER.finditer(text))
        words = list(WORD.finditer(text))
        found, cut, full_cut = [], [], []
        for source, other in dynamic.items():
            other_text = other.text if other is not None else None
            if not isinstance(other_text, str):
                return "skip", []
            other_tokens = list(NUMBER.finditer(other_text))
            if len(other_tokens) != len(tokens):
                return "skip", []
            for position, (token, token_b) in enumerate(zip(tokens, other_tokens)):
                if token.group() == token_b.group():
                    continue
                binding = self._bind_number(source, token.group(), token_b.group())
                if binding is None:
                    return "skip", []
                found.append((source, token, binding, other, token_b))
                full_cut.append(token.span())
                separator = re.search(r"[.,]", token.group())
                if separator:
                    # The decimal separator stays part of the theme's own text (static).
                    split = token.start() + separator.start()
                    cut.extend(((token.start(), split), (split + 1, token.end())))
                else:
                    cut.append(token.span())
            if source == "clock":
                other_words = list(WORD.finditer(other_text))
                if len(other_words) != len(words):
                    return "skip", []
                for position, (word, word_b) in enumerate(zip(words, other_words)):
                    if word.group() != word_b.group():
                        binding = self._bind_word(word.group(), call.index, position)
                        if binding is None:
                            return "skip", []
                        found.append((source, word, binding, other, word_b))
                        cut.append(word.span())
                        full_cut.append(word.span())
        if not found:
            return "skip", []
        layout = self._layout(call)
        if layout is None:
            return "skip", []
        la_x, la_y, _tf = layout

        def pieces_for(spans):
            pieces, start = [], 0
            for begin, end in sorted(set(spans)):
                if begin > start and text[start:begin].strip():
                    pieces.append((text[start:begin], la_x + font.getlength(text[:start]), la_y))
                start = max(start, end)
            if text[start:].strip():
                pieces.append((text[start:], la_x + font.getlength(text[:start]), la_y))
            return pieces
        pieces = pieces_for(cut)
        if sorted(set(cut)) != sorted(set(full_cut)):
            # Without room for its decimals the number takes the whole token: no lone separator.
            self._without_decimals[call.index] = ("pieces", pieces_for(full_cut))
        widgets = []
        for source, token, binding, other, token_b in found:
            widgets.extend(self._number_widgets(call, layout, token, binding, other, token_b, source))
        return ("pieces", pieces), widgets

    def _layout(self, call):
        """Left/ascender origin of a text call, in its canvas coordinates."""
        probe = ImageDraw.Draw(Image.new("L", (1, 1)))
        font, text = call.font, call.text
        anchor = call.kwargs.get("anchor") or "la"
        if isinstance(font, SegmentFont):
            x, y = font.anchor_origin(call.xy, text, anchor)
            return x, y, call.tf
        try:
            box = ImageDraw.ImageDraw.textbbox(probe, call.xy, text, font=font, anchor=anchor)
            zero = ImageDraw.ImageDraw.textbbox(probe, (0, 0), text, font=font, anchor="la")
        except (ValueError, TypeError):
            return None
        return box[0] - zero[0], box[1] - zero[1], call.tf

    def _alignment(self, call, other, token, token_b):
        """How the theme places this number when its width changes: 0 left, 1 centre, 2 right
        (measured on the final frame: a text drawn on its own tile moves with the tile)."""
        if other is None or call.tf is None or other.tf is None:
            return 2
        mine, theirs = self._layout(call), self._layout(other)
        if mine is None or theirs is None:
            return 2
        sx_a, _sy, ox_a, _oy = call.tf
        sx_b, _sy_b, ox_b, _oy_b = other.tf
        start_a = (mine[0] + call.font.getlength(call.text[:token.start()])) * sx_a + ox_a
        start_b = (theirs[0] + other.font.getlength(other.text[:token_b.start()])) * sx_b + ox_b
        end_a = start_a + call.font.getlength(token.group()) * sx_a
        end_b = start_b + other.font.getlength(token_b.group()) * sx_b
        if abs(start_a - start_b) < 1.5:
            return 0
        if abs(end_a - end_b) < 1.5:
            return 2
        return 1

    def _bind_number(self, source, token_a, token_b):
        value_a, value_b = _as_float(token_a), _as_float(token_b)
        stats_a, when_a = self.scene.base, fields.T0
        stats_b, when_b = self.variants_for(source)
        names = fields.CLOCK_CANDIDATES if source == "clock" else fields.FIELDS[source][2]
        if source == "clock":
            names = tuple(names) + ("uptime_hours", "uptime_minutes")
        decimals = _decimals(token_a)
        tolerance = 0.51 * 10 ** -decimals + 1e-9
        for name in names:
            cand_a = fields.candidate_value(name, stats_a, when_a.timestamp())
            cand_b = fields.candidate_value(name, stats_b, when_b.timestamp())
            if cand_a == 0:
                if value_a == 0 and abs(cand_b - value_b) <= tolerance:
                    return {"cand": name, "scale": 1.0, "decimals": decimals}
                continue
            # The scale from the larger value: "3" for 2.66 % would look like x1.13.
            ratio = value_b / cand_b if cand_b and abs(cand_b) > abs(cand_a) else value_a / cand_a
            for scale in NICE_SCALES:
                if ratio and abs(ratio / scale - 1) > 0.06:
                    continue
                if abs(cand_a * scale - value_a) <= tolerance and abs(cand_b * scale - value_b) <= tolerance:
                    integer_a = token_a.split(".")[0].split(",")[0]
                    padded = len(integer_a) > len(str(int(cand_a * scale))) or \
                        len(token_b.split(".")[0].split(",")[0]) > len(str(int(cand_b * scale)))
                    # Minutes and seconds in two digits are always zero-padded ("09:05").
                    padded = padded or (name in ("minute", "second", "uptime_minutes") and len(integer_a) == 2)
                    return {"cand": name, "scale": scale, "decimals": decimals, "padded": padded}
        return None

    def variants_for(self, source):
        return self.variants.get(source, (self.scene.base, fields.T0))

    def _bind_word(self, word, call_index, position):
        """A weekday or month name: read the word at the same place for every day of
        the week / every month (the theme's own spelling, case and language)."""
        cache = self.__dict__.setdefault("_word_cache", {})
        for cand, dates, order in (
                ("weekday", [fields.T0 + datetime.timedelta(days=d) for d in range(7)], lambda d: d.weekday()),
                ("month0", [fields.T0.replace(month=m, day=8) for m in range(1, 13)], lambda d: d.month - 1)):
            key = (call_index, position, cand)
            if key not in cache:
                cache[key] = self._words_at(call_index, position, dates)
            names = cache[key]
            if not names or names[0 if cand == "weekday" else fields.T0.month - 1] != word or \
                    len(set(names)) != len(names):
                continue
            words = [None] * len(dates)
            for when, name in zip(dates, names):
                words[order(when)] = name
            return {"cand": cand, "scale": 1.0, "part": "word", "words": words}
        return None

    def _words_at(self, call_index, position, dates):
        names = []
        for when in dates:
            _image, calls = self.scene.render(self.recorder, when=when)
            pairs, _unmatched = _match(self.base_calls, calls)
            other = next((calls[j] for i, j in pairs if i == call_index), None)
            words = WORD.findall(other.text) if other is not None and isinstance(other.text, str) else []
            if len(words) <= position:
                return []
            names.append(words[position])
        return names

    def _number_widgets(self, call, layout, token, binding, other, token_b, source):
        la_x, la_y, tf = layout
        font = call.font
        sx, sy = tf[0], tf[1]
        size = max(6, round(font.size * sy))
        color = _fill_of(call)
        priority = fields.CLOCK_PRIORITY if source == "clock" else fields.FIELDS[source][0]
        start = la_x + font.getlength(call.text[:token.start()])
        x0, y0 = self._frame_point(tf, start, la_y)
        if binding.get("part") == "word":
            words = binding["words"]
            if len(words) <= 10:
                atlas = _word_atlas(font.path, size, words)
                box = (round(x0), round(y0), atlas.widths[0], atlas.height)
                return [(priority, imgdat.Number(0, box, color, atlas, 0), dict(binding))]
            # A number widget reaches cells 0..9 only: split the list in chunks of
            # nine words plus a blank cell 9, drawn in overlapping widgets (the
            # panel composites them, a blank one does not erase the other).
            result = []
            width = max(math.ceil(font.getlength(w)) for w in words) + 1
            for first in range(0, len(words), 9):
                chunk = words[first:first + 9] + [""] * (10 - len(words[first:first + 9]))
                atlas = _word_atlas(font.path, size, chunk, width=round(width * sx) + 1)
                box = (round(x0), round(y0), atlas.widths[0], atlas.height)
                result.append((priority, imgdat.Number(0, box, color, atlas, 0),
                               dict(binding, part="word_chunk", first=first, words=None)))
            return result
        atlas = font.atlas(size) if isinstance(font, SegmentFont) else _digit_atlas(font.path, size)
        digit_w = atlas.widths[0]
        text = token.group()
        decimals = binding.get("decimals", 0)
        integer = re.split(r"[.,]", text)[0]
        longest = max(len(integer), len(re.split(r"[.,]", token_b.group())[0]))
        end_int = x0 + font.getlength(integer) * sx
        result = []
        if binding.get("padded") and len(integer) == 2:
            for offset, part in ((0, "tens"), (1, "ones")):
                box = (round(x0 + offset * digit_w), round(y0), digit_w, atlas.height)
                result.append((priority, imgdat.Number(0, box, color, atlas, 0), dict(binding, part=part)))
        else:
            align = self._alignment(call, other, token, token_b) if not decimals else 2
            if align == 1:
                # A centred text keeps its words where they were (static pieces): the number
                # leans on the word after it ("8 %") or, at the end, on the one before.
                align = 2 if call.text[token.end():].strip() else 0
            digits = max(longest, len(integer)) + (1 if align != 0 else 0)
            width = digit_w * digits
            if align == 2:
                left = end_int - width
            elif align == 1:
                left = (x0 + end_int) / 2 - width / 2
            else:
                left = x0
            left = max(0, left)
            box = (round(left), round(y0), min(round(width), SIZE[0] - round(left)), atlas.height)
            number = imgdat.Number(0, box, color, atlas, align)
            if decimals:
                # Where the integer ends if its decimals are left out (the whole token).
                number.shift = round((x0 + font.getlength(text) * sx) - end_int)
            result.append((priority, number, dict(binding, part="int" if decimals else "whole")))
        if decimals:
            separator = text[len(integer)]
            sep_x = end_int
            frac_x = sep_x + font.getlength(separator) * sx
            box = (round(frac_x), round(y0), digit_w * decimals, atlas.height)
            # Decimals are the first thing left out when the panel runs short.
            result.append((priority + 100, imgdat.Number(0, box, color, atlas, 0), dict(binding, part="frac")))
        return result

    def _bar(self, call, dynamic):
        """A rectangle whose width follows a field: a panel bar on its track."""
        found = []
        for source, other in dynamic.items():
            if other is None or source == "clock":
                continue
            box_a, box_b = _rect(call.xy), _rect(other.xy)
            if box_a is None or box_b is None:
                continue
            if abs(box_a[1] - box_b[1]) > 1 or abs(box_a[3] - box_b[3]) > 1 or abs(box_a[0] - box_b[0]) > 1:
                continue                       # not a left-anchored horizontal bar
            track = self._track(call, box_a)
            if track is None:
                continue
            if call.tf is None:
                continue
            width = track[2] - track[0]
            if width <= 0:
                continue
            pct_a = 100 * (box_a[2] - box_a[0]) / width
            pct_b = 100 * (box_b[2] - box_b[0]) / width
            binding = None
            stats_b, when_b = self.variants_for(source)
            for name in fields.FIELDS[source][2]:
                cand_a = fields.candidate_value(name, self.scene.base, fields.T0.timestamp())
                cand_b = fields.candidate_value(name, stats_b, when_b.timestamp())
                if not cand_a or not cand_b:
                    continue
                scale = pct_a / cand_a
                if abs(cand_b * scale - pct_b) <= max(2.5, 0.05 * pct_b):
                    binding = {"cand": name, "scale": scale, "part": "pct"}
                    break
            if binding is None:
                continue
            left, top = self._frame_point(call.tf, track[0], track[1])
            box = (round(left), round(top), max(1, round((track[2] - track[0]) * call.tf[0])),
                   max(1, round((track[3] - track[1]) * call.tf[1])))
            fg = _fill_of(call)
            bg = track[4]
            priority = fields.FIELDS[source][0] + 0.5
            found.append((priority, imgdat.Bar(0, box, fg, bg, bg), binding))
            break
        return found

    def _track(self, call, box):
        """The static rectangle drawn under a bar (same row, containing it)."""
        for previous in reversed(self.base_calls[:call.index]):
            if previous.method not in RECTS or previous.index in self.deps or previous.size != call.size:
                continue
            other = _rect(previous.xy)
            if other is None:
                continue
            if abs(other[1] - box[1]) <= 2 and abs(other[3] - box[3]) <= 2 and other[0] <= box[0] + 2 and \
                    other[2] >= box[2] - 2 and other[2] - other[0] > 4:
                return (*other, _fill_of(previous))
        return None

    # ------------------------------------------------------------ frames
    def _photo_bars(self, plan, refresh=None):
        """Bars, found and drawn by the theme itself: each percentage field is set to
        0, 50 and 100 % (values cut out, alert colours off); what changes is a bar if
        it fills from the left. The panel then shows the theme's own empty and full
        bar pictures (image bars, measured on hardware), so segmented, gradient and
        rounded bars look exactly as on a graphic display."""
        import numpy as np
        found = []
        if THEME_OPTIONS.get(self.scene.theme_id, {}).get("bars", True) is False:
            return found
        calm = _calm(self.scene.theme_id, self.scene.settings)
        # No text at all (a text on a tile sized by its value would move and look like a
        # bar); every shape left in place (fills are drawn with rectangles, lines, arcs;
        # a gauge's needle photographed at each level moves with it).
        plan = {call.index: "skip" for call in self.base_calls if call.method == "text"}
        if refresh is not None:
            # The final background's words (where the theme leaves them) are copied onto
            # both pictures of a bar they sit on, so "26% 12.3/46.4G" stays on its bar.
            background, plain, final_plan = refresh
            final = np.asarray(background, dtype=np.int16)
            # Only the words: the final background against the same plan without any text.
            no_text = dict(final_plan)
            no_text.update({call.index: "skip" for call in self.base_calls if call.method == "text"})
            words = np.abs(final - np.asarray(self._render_planned(no_text), dtype=np.int16)).sum(axis=2) > 30
            for bar in plain:
                x, y, w, h = bar.box
                for attr in ("bg_image", "fg_image"):
                    picture = np.asarray(getattr(bar, attr), dtype=np.int16).copy()
                    region = words[y:y + h, x:x + w]
                    picture[region] = final[y:y + h, x:x + w][region]
                    setattr(bar, attr, Image.fromarray(picture.astype("uint8"), "RGB"))
            return []
        media_present = (self.scene.base.get("media") or {}).get("present")
        # Nothing that moves at all (no text, no dynamic shape): what a gauge is drawn on.
        empty_plan = dict(plan)
        empty_plan.update({i: "skip" for i in self.deps if self.base_calls[i].method != "text"})
        self._empty = None

        def empty():
            if self._empty is None:
                self._empty = np.asarray(self._render_planned(empty_plan, settings=calm), dtype=np.int16)
            return self._empty
        self._empty_shot = empty
        for name, (setter, cand) in fields.PERCENT.items():
            if name.startswith("media_") and not media_present:
                continue
            shots = {pct: np.asarray(self._render_planned(plan, changes=setter(self.scene.base, pct), settings=calm),
                                     dtype=np.int16) for pct in (0, 25, 50, 75, 98, 100)}
            changed = np.abs(shots[100] - shots[0]).sum(axis=2) > 24
            boxes = _boxes(changed)
            boxes = [b for b in boxes if not any(o != b and o[0] <= b[0] and o[1] <= b[1] and o[2] >= b[2] and
                                                 o[3] >= b[3] for o in boxes)]
            for x0, y0, x1, y1 in boxes:
                w, h = x1 - x0, y1 - y0
                if w < 12 or h < 2:
                    continue
                # Bars, and semicircle gauges: revealed left to right, an arc fills almost
                # exactly like the theme draws it (the test below keeps only those).
                # How far the fill reaches (fraction of the width) at 25/50/75 %: a straight
                # bar gives 0.25/0.5/0.75, a gauge arc another curve the panel follows.
                reach = [0.0]
                for pct in (25, 50, 75):
                    cols = np.nonzero((np.abs(shots[pct] - shots[0]).sum(axis=2)[y0:y1, x0:x1] > 24).any(axis=0))[0]
                    reach.append(float((cols[-1] + 1) / w) if len(cols) else 0.0)
                reach.append(1.0)
                gauge = self._level_gauge(name, cand, plan, calm, (x0, y0, x1, y1), shots, reach)
                if gauge is not None:
                    found.append(gauge)
                    continue
                if any(b < a - 0.02 for a, b in zip(reach, reach[1:])):
                    continue                # does not grow left to right
                # At 50 % the theme must look like "full up to the reach, empty after it".
                cut = max(1, round(reach[2] * w))
                composite = shots[0][y0:y1, x0:x1].copy()
                composite[:, :cut] = shots[100][y0:y1, x0:x1][:, :cut]
                half = shots[50][y0:y1, x0:x1]
                changed_px = (np.abs(shots[100] - shots[0]).sum(axis=2)[y0:y1, x0:x1] > 24).sum()
                wrong_px = (np.abs(half - composite).sum(axis=2) > 48).sum()
                if not changed_px or wrong_px > 0.25 * changed_px:
                    continue                # not something that fills from the left
                # Full picture at 98 %: some themes still turn a bar red at 100 %.
                full = Image.fromarray(shots[98][y0:y1, x0:x1].astype("uint8"), "RGB")
                empty = Image.fromarray(shots[0][y0:y1, x0:x1].astype("uint8"), "RGB")
                fg = tuple(int(v) for v in np.asarray(full).reshape(-1, 3).mean(axis=0))
                bg = tuple(int(v) for v in np.asarray(empty).reshape(-1, 3).mean(axis=0))
                bar = imgdat.Bar(0, (int(x0), int(y0), int(w), int(h)), fg, bg, bg, 1, fg_image=full, bg_image=empty)
                bar.field = name
                binding = {"cand": cand, "scale": 1.0, "part": "pct"}
                if any(abs(r - i / 4) > 0.05 for i, r in enumerate(reach)):
                    binding["curve"] = [round(r * 100, 1) for r in reach]      # value 0/25/50/75/100 -> reveal %
                found.append((fields.FIELDS[name][0] + 0.5, bar, binding, -1))
        return found

    LEVELS = tuple(round(k * 100 / 9) for k in range(10))      # 0, 11, 22 ... 100

    def _level_gauge(self, name, cand, plan, calm, box, shots, reach):
        """A gauge, ring or vertical bar (anything that does not fill left to right like a
        bar): drawn by one number widget whose ten glyph cells are the theme's own
        fill photographed at ten levels (cell k = level k), in the fill colour."""
        import numpy as np
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        linear = all(abs(r - i / 4) <= 0.06 for i, r in enumerate(reach))
        if linear or w * h * 10 > 420_000:
            return None
        setter = fields.PERCENT[name][0]
        base = self._empty_shot()[y0:y1, x0:x1]      # no fill, no needle: no ghost of the 0 % needle
        cells, colours, lit_counts = bytearray(), [], []
        for level in self.LEVELS:
            shot = shots.get(level)
            if shot is None:
                shot = np.asarray(self._render_planned(plan, changes=setter(self.scene.base, level), settings=calm),
                                  dtype=np.int16)
            crop = shot[y0:y1, x0:x1]
            lit = np.abs(crop - base).sum(axis=2) > 24
            lit_counts.append(int(lit.sum()))
            cells += (lit.astype(np.uint8) * 255).tobytes()
            if lit.any():
                colours.append(crop[lit].reshape(-1, 3))
        # A gauge only ever grows with its value (a figure reacting to the load does not).
        if not colours or any(b < a * 0.97 for a, b in zip(lit_counts, lit_counts[1:])) or lit_counts[-1] < 20:
            return None
        colour = tuple(int(v) for v in np.median(np.concatenate(colours), axis=0))
        atlas = imgdat.Atlas((w,) * 10 + (1, 1), h, bytes(cells) + bytes(2 * h))
        number = imgdat.Number(0, (int(x0), int(y0), int(w), int(h)), colour, atlas, 0)
        return (fields.FIELDS[name][0] + 0.5, number, {"cand": cand, "scale": 1.0, "part": "level"}, -1)

    def _render_planned(self, plan, when=None, changes=None, settings=None):
        """Render with ``plan`` (base call index -> action) addressed by identity and
        occurrence, so a theme whose call list varies cannot misplace it."""
        occurrences, keyed = {}, {}
        for call in self.base_calls:
            key = call.key()
            occurrence = occurrences.get(key, 0)
            occurrences[key] = occurrence + 1
            if call.index in plan:
                keyed[(key, occurrence)] = plan[call.index]
        image, _calls = self.scene.render(self.recorder, changes=changes, when=when, plan=keyed, settings=settings)
        return image

    def _sprites(self, plan, avoid):
        """Looping sprites for the parts of an animated scene that move."""
        import numpy as np
        options = THEME_OPTIONS.get(self.scene.theme_id, {}).get("sprites")
        if not options:
            return []
        count, dt = options["frames"], options["dt"]
        shots = [self._render_planned(plan, when=fields.T0 + datetime.timedelta(seconds=k * dt)) for k in range(count)]
        arrays = [np.asarray(shot, dtype=np.int16) for shot in shots]
        mask = np.zeros(arrays[0].shape[:2], bool)
        for array in arrays[1:]:
            mask |= np.abs(array - arrays[0]).sum(axis=2) > 30
        boxes = []
        for x0, y0, x1, y1 in _boxes(mask, join=4):
            x0, y0 = max(0, int(x0) - 2), max(0, int(y0) - 2)
            x1, y1 = min(SIZE[0], int(x1) + 2), min(SIZE[1], int(y1) + 2)
            if (x1 - x0) * (y1 - y0) >= 30:
                boxes.append([x0, y0, x1, y1])
        merged = True
        while merged:                           # overlapping regions become one sprite
            merged = False
            for a in range(len(boxes)):
                for b in range(a + 1, len(boxes)):
                    p, q = boxes[a], boxes[b]
                    if p[0] <= q[2] and q[0] <= p[2] and p[1] <= q[3] and q[1] <= p[3]:
                        boxes[a] = [min(p[0], q[0]), min(p[1], q[1]), max(p[2], q[2]), max(p[3], q[3])]
                        del boxes[b]
                        merged = True
                        break
                if merged:
                    break

        def overlaps(box):
            return any(box[0] < x + w and x < box[2] and box[1] < y + h and y < box[3] for x, y, w, h in avoid)
        sprites, spent = [], 0
        for x0, y0, x1, y1 in sorted(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])):
            area = (x1 - x0) * (y1 - y0)
            cost = area * 2 * count
            if area > options["max_area"] or overlaps((x0, y0, x1, y1)) or spent + cost > options["budget"]:
                continue                        # the sky, the HUD: stay as in the first frame
            sprites.append(imgdat.Sprite((x0, y0, x1 - x0, y1 - y0), [s.crop((x0, y0, x1, y1)) for s in shots],
                                         round(dt * 1000)))
            spent += cost
        return sprites

    def _frames(self, plan):
        options = THEME_OPTIONS.get(self.scene.theme_id, {})
        count = options.get("frames", 1)
        frames = []
        for step in range(1, count):
            when = fields.T0 + datetime.timedelta(seconds=step * options.get("frame_dt", 0.5))
            frames.append(self._render_planned(plan, when))
        return frames

    # ------------------------------------------------------------ assembly
    def _select(self, candidates):
        """Widgets that fit the firmware budget, most important first, and their channels.

        The values of one text go in together or not at all (a text with a value
        missing would show "%  /46.4G"); its decimals are the first thing dropped."""
        channels, kept, bindings = {}, [], {}
        counts = {"numbers": 0, "bars": 0}
        dropped = 0
        groups = {}
        for item in (c for c in candidates if c[1] is not None):
            group = item[3] if item[3] >= 0 else ("bar", id(item[1]))
            groups.setdefault(group, []).append(item)

        def fits(items):
            numbers = sum(isinstance(i[1], imgdat.Number) for i in items)
            bars = len(items) - numbers
            new = {_channel_key(i[2]) for i in items} - set(channels)
            return (counts["numbers"] + numbers <= MAX_NUMBERS and
                    counts["numbers"] + counts["bars"] + numbers + bars <= MAX_WIDGETS and
                    len(channels) + len(new) <= MAX_CHANNELS)

        for _group, items in sorted(groups.items(), key=lambda g: min(i[0] for i in g[1])):
            chosen = items if fits(items) else [i for i in items if i[2].get("part") != "frac"]
            if not chosen or not fits(chosen):
                dropped += len(items)
                continue
            dropped += len(items) - len(chosen)
            for item in chosen:
                _priority, widget, binding, _index = item
                key = _channel_key(binding)
                if key not in channels:
                    channels[key] = len(channels) + 1
                    bindings[channels[key]] = binding
                widget.channel = channels[key]
                counts["numbers" if isinstance(widget, imgdat.Number) else "bars"] += 1
                kept.append(item)
        return kept, bindings, dropped

    @staticmethod
    def _close_gaps(kept, bindings):
        """An integer whose decimals did not fit takes the whole token's place, rounded."""
        with_decimals = {c[3] for c in kept if c[2].get("part") == "frac"}
        for _priority, widget, binding, index in kept:
            if binding.get("part") != "int" or index in with_decimals:
                continue
            x, y, w, h = widget.box
            widget.box = (min(x + getattr(widget, "shift", 0), SIZE[0] - w), y, w, h)
            binding["part"] = "whole"
            bindings[widget.channel] = binding

    def _theme(self, background, frames, candidates, kept, bindings, dropped):
        # Gauges (level widgets) first: the numbers printed on them are drawn on top.
        numbers = [c[1] for c in kept if isinstance(c[1], imgdat.Number) and c[2].get("part") == "level"] + \
                  [c[1] for c in kept if isinstance(c[1], imgdat.Number) and c[2].get("part") != "level"]
        bars = [c[1] for c in kept if isinstance(c[1], imgdat.Bar)]
        theme = imgdat.Theme(SIZE, background, numbers, bars, frames=frames,
                             frame_delay_ms=THEME_OPTIONS.get(self.scene.theme_id, {}).get("frame_delay_ms", 0))
        problems = theme.check()
        if problems:
            raise CaptureError("; ".join(problems))
        return theme, {str(k): v for k, v in bindings.items()}, dropped


PERCENT_CANDIDATES = {"cpu_percent", "ram_percent", "swap_percent", "disk_percent", "gpu_percent", "gpu_mem_percent"}


def _channel_key(binding):
    """Bindings that always give the same integer share one channel: a percentage
    printed as text and the bar drawn for it (the panel has 26 channels)."""
    if binding.get("cand") in PERCENT_CANDIDATES and binding.get("part", "whole") in ("whole", "pct") and \
            abs(binding.get("scale", 1.0) - 1.0) < 0.02 and not binding.get("decimals"):
        return ("percent", binding["cand"])
    return repr(sorted((k, repr(v)) for k, v in binding.items()))


def _boxes(mask, join=6):
    """Bounding boxes of the regions of a boolean mask (gaps up to ``join`` px bridged,
    so a segmented bar is one region)."""
    import numpy as np
    height, width = mask.shape
    grown = mask.copy()
    for shift in range(1, join + 1):
        grown[:, shift:] |= mask[:, :-shift]
        grown[:, :-shift] |= mask[:, shift:]
    seen = np.zeros_like(grown)
    boxes = []
    for y, x in zip(*np.nonzero(grown)):
        if seen[y, x]:
            continue
        stack, x0, y0, x1, y1 = [(y, x)], x, y, x, y
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop()
            x0, y0, x1, y1 = min(x0, cx), min(y0, cy), max(x1, cx), max(y1, cy)
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < height and 0 <= nx < width and grown[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        # Shrink back to the real pixels (the bridging widened the region sideways).
        region = mask[y0:y1 + 1, x0:x1 + 1]
        cols = np.nonzero(region.any(axis=0))[0]
        rows = np.nonzero(region.any(axis=1))[0]
        if len(cols) and len(rows):
            boxes.append((x0 + cols[0], y0 + rows[0], x0 + cols[-1] + 1, y0 + rows[-1] + 1))
    return boxes


def _media_state(stats, art=None):
    """What the Big Media Player sees during a capture: one player with the track in
    ``stats["media"]`` (no player at all when nothing plays)."""
    from ...media import hub, model
    media = stats.get("media") if isinstance(stats.get("media"), dict) else {}
    if not media.get("present"):
        return hub.MediaState(None, connected=False)
    now = time.monotonic()
    art_id = "capture-art" if art is not None and media.get("art") else None
    player = model.clean_player({
        "bus": "org.mpris.MediaPlayer2.capture", "identity": media.get("identity") or "Player", "desktop": "",
        "status": media.get("status") or "Playing", "title": media.get("title") or "", "artist": media.get("artist")
        or "", "album": media.get("album") or "", "description": "", "url": "", "track_id": "/capture/1",
        "art": art_id, "art_state": "ok" if art_id else "none", "length_us": media.get("length_us"),
        "position_us": media.get("position_us"), "position_mono": now, "rate": 0.0,
        "can": {key: True for key in model.CAPS}, "volume": None, "loop": "None", "shuffle": False,
        "last_active_mono": now})
    snapshot = {"players": [player], "active": player["bus"],
                "volume": model.clean_volume({"available": True, "percent": media.get("volume") or 0,
                                              "muted": bool(media.get("muted")), "output": "", "backend": "pulse"}),
                "agent": model.clean_agent({}), "sent_mono": now}
    return hub.MediaState(snapshot, {art_id: art} if art_id else {}, connected=True)


def _castaway_home(theme):
    """Brother Away: the castaway standing on the island."""
    hero = getattr(theme, "hero", None)
    world = getattr(theme, "world", None)
    if hero is None or world is None:
        return True
    lay = world.layout
    x = getattr(hero, "x", None)
    return x is not None and lay.walk_min <= x <= lay.walk_max and not getattr(hero, "hidden", False)


def _clear_theme_caches():
    """Themes cache rendered text and layers; a cache hit draws nothing, which the
    recorder cannot see. Every capture render starts from empty caches."""
    import collections
    import functools
    for name, module in list(sys.modules.items()):
        if not name.startswith("bsmd.") or name.startswith("bsmd.displays.smartmonitor") or module is None:
            continue
        for attr, value in list(vars(module).items()):
            if isinstance(value, (dict, collections.OrderedDict)) and "CACHE" in attr.upper():
                value.clear()
            elif isinstance(value, functools._lru_cache_wrapper):
                value.cache_clear()


def _rect(xy):
    try:
        if len(xy) == 4 and not isinstance(xy[0], (list, tuple)):
            x0, y0, x1, y1 = xy
        else:
            (x0, y0), (x1, y1) = xy
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    except (TypeError, ValueError):
        return None


_ATLASES = {}


def _digit_atlas(path, size):
    key = ("digits", path, size)
    if key not in _ATLASES:
        font = ImageFont.truetype(path, size)
        ascent, descent = font.getmetrics()
        height = ascent + descent
        widths = [max(1, math.ceil(font.getlength(g))) for g in imgdat.GLYPHS]
        width = max(widths[:10])
        widths = [width] * 10 + widths[10:]
        data = bytearray()
        for glyph, cell_w in zip(imgdat.GLYPHS, widths):
            cell = Image.new("L", (cell_w, height), 0)
            offset = (cell_w - font.getlength(glyph)) / 2 if glyph.isdigit() else 0
            ImageDraw.Draw(cell).text((offset, 0), glyph, font=font, fill=255, anchor="la")
            data += cell.tobytes()
        _ATLASES[key] = imgdat.Atlas(tuple(widths), height, bytes(data))
    return _ATLASES[key]


def _word_atlas(path, size, words, width=None):
    key = ("words", path, size, tuple(words), width)
    if key not in _ATLASES:
        font = ImageFont.truetype(path, size)
        ascent, descent = font.getmetrics()
        height = ascent + descent
        width = width or max(math.ceil(font.getlength(w)) for w in words if w) + 1
        data = bytearray()
        for index in range(len(imgdat.GLYPHS)):
            cell = Image.new("L", (width, height), 0)
            if index < len(words):
                ImageDraw.Draw(cell).text((0, 0), words[index], font=font, fill=255, anchor="la")
            data += cell.tobytes()
        _ATLASES[key] = imgdat.Atlas((width,) * len(imgdat.GLYPHS), height, bytes(data))
    return _ATLASES[key]


def capture(theme_id, settings, stats, art=None):
    """``(imgdat.Theme, bindings, dropped)`` for ``theme_id`` with ``settings``
    (``art``: the current cover, when the panel is flashed on every song)."""
    if theme_id not in THEME_OPTIONS:
        raise CaptureError(f"no adaptation for theme {theme_id}")
    job = Capture(theme_id, settings, stats)
    job.scene.art = art
    return job.run()
