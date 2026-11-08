"""Compiled theme (``img.dat``) of the SmartMonitor HID panel.

Layout::

    [ 64 slots x 64 bytes = 4096 bytes ][ resources ]

* slot 0: little-endian slot count (150), *not* a record;
* slots 1..63: one widget record each (type byte first, multi-byte fields
  big-endian);
* resources (pixels, glyph atlases) from offset 4096, referenced by absolute
  offset. Pixels are RGB565 little-endian, row major; glyphs are 8-bit
  coverage that the panel blends in the widget colour.

Only the record types this project needs are written, with the field layout
measured on hardware by the reference projects (see :mod:`.protocol`):

* ``0x81`` background image (full canvas);
* ``0x92`` number widget: the value of a channel, drawn digit by digit from a
  12-cell atlas (``0123456789.-``). The cells may hold any picture: a value
  of 1 draws cell 1, which is how a channel can select a *word*;
* ``0x8B`` progress bar bound to a channel (0..100);
* ``0x96`` rotation (in a regular slot: at offset 0 the panel ignores it).

Firmware budget measured on hardware (Starfleet project): at most 40
widgets, 28 number widgets and 26 distinct channels; past it the panel
silently drops widgets or shows only "boot". :func:`compile_theme` refuses
themes beyond it.
"""

from dataclasses import dataclass, field

SLOT = 64
SLOTS = 64
HEADER_SLOT_COUNT = 150
RESOURCE_START = SLOT * SLOTS
GLYPHS = "0123456789.-"

BACKGROUND = 0x81
PROGRESS = 0x8B
NUMBER = 0x92
ROTATE = 0x96

MAX_WIDGETS = 40
MAX_NUMBERS = 28
MAX_CHANNELS = 26
ROTATIONS = {0: 0, 90: 1, 180: 2, 270: 3}


def rgb565(color):
    red, green, blue = color[:3]
    return ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)


def rgb565_bytes(image):
    """Little-endian RGB565 pixels of a PIL image."""
    import numpy as np
    pixels = np.asarray(image.convert("RGB"), dtype=np.uint16)
    value = ((pixels[..., 0] >> 3) << 11) | ((pixels[..., 1] >> 2) << 5) | (pixels[..., 2] >> 3)
    return value.astype("<u2").tobytes()


@dataclass
class Atlas:
    """Twelve glyph cells of 8-bit coverage, all ``height`` tall."""
    widths: tuple
    height: int
    data: bytes

    def __post_init__(self):
        if len(self.widths) != len(GLYPHS):
            raise ValueError("an atlas has 12 cells")
        if sum(self.widths) * self.height != len(self.data):
            raise ValueError("atlas size does not match its cells")


@dataclass
class Number:
    channel: int
    box: tuple                   # x, y, width, height
    color: tuple
    atlas: Atlas
    align: int = 0               # 0 = left (proven on hardware)


@dataclass
class Bar:
    channel: int
    box: tuple
    fg: tuple
    bg: tuple
    frame: tuple
    style: int = 1               # 1 = horizontal fill (vendor themes)


@dataclass
class Theme:
    size: tuple
    background: object           # PIL image of ``size``
    numbers: list = field(default_factory=list)
    bars: list = field(default_factory=list)
    rotation: int = 0

    def check(self):
        widgets = len(self.numbers) + len(self.bars)
        channels = {n.channel for n in self.numbers} | {b.channel for b in self.bars}
        problems = []
        if widgets > MAX_WIDGETS:
            problems.append(f"{widgets} widgets (the panel serves {MAX_WIDGETS})")
        if len(self.numbers) > MAX_NUMBERS:
            problems.append(f"{len(self.numbers)} number widgets (the panel serves {MAX_NUMBERS})")
        if len(channels) > MAX_CHANNELS:
            problems.append(f"{len(channels)} channels (the panel serves {MAX_CHANNELS})")
        if any(not 0 < c <= 255 for c in channels):
            problems.append("channel out of range")
        if self.background.size != tuple(self.size):
            problems.append("background size does not match the canvas")
        width, height = self.size
        for widget in list(self.numbers) + list(self.bars):
            x, y, w, h = widget.box
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                problems.append(f"widget on channel {widget.channel} outside the canvas: {widget.box}")
        if self.rotation not in ROTATIONS:
            problems.append(f"rotation {self.rotation}")
        return problems


def _put16(buf, offset, value):
    buf[offset:offset + 2] = (int(value) & 0xFFFF).to_bytes(2, "big")


def _put32(buf, offset, value):
    buf[offset:offset + 4] = (int(value) & 0xFFFFFFFF).to_bytes(4, "big")


def _box(buf, box):
    x, y, w, h = box
    _put16(buf, 3, x)
    _put16(buf, 5, y)
    _put16(buf, 7, w)
    _put16(buf, 9, h)


def compile_theme(theme):
    """``img.dat`` bytes. Raises ValueError for a theme the panel cannot serve."""
    problems = theme.check()
    if problems:
        raise ValueError("; ".join(problems))
    resources = bytearray()
    offsets = {}

    def place(payload):
        payload = bytes(payload)
        if payload not in offsets:
            offsets[payload] = RESOURCE_START + len(resources)
            resources.extend(payload)
        return offsets[payload]

    records = []
    width, height = theme.size
    record = bytearray(SLOT)
    record[0] = BACKGROUND
    _box(record, (0, 0, width, height))
    record[11] = 0                               # image, not a flat colour
    _put32(record, 14, place(rgb565_bytes(theme.background)))
    record[18] = 1                               # frames
    records.append(record)
    widget_id = 1
    for number in theme.numbers:
        record = bytearray(SLOT)
        record[0] = NUMBER
        record[1] = widget_id
        record[2] = number.channel
        _box(record, number.box)
        record[11] = number.align
        _put16(record, 12, rgb565(number.color))
        record[14] = 0
        record[15] = 0xFF                        # opaque
        _put32(record, 16, place(number.atlas.data))
        _put16(record, 20, number.atlas.height)
        for index, cell in enumerate(number.atlas.widths):
            _put16(record, 22 + index * 2, cell)
        records.append(record)
        widget_id += 1
    for bar in theme.bars:
        record = bytearray(SLOT)
        record[0] = PROGRESS
        record[1] = widget_id
        record[2] = bar.channel
        _box(record, bar.box)
        record[11] = bar.style
        _put16(record, 12, rgb565(bar.bg))
        _put16(record, 14, rgb565(bar.fg))
        _put16(record, 16, rgb565(bar.frame))
        records.append(record)
        widget_id += 1
    if theme.rotation:
        record = bytearray(SLOT)
        record[0] = ROTATE
        record[1] = ROTATIONS[theme.rotation]
        records.append(record)
    if len(records) > SLOTS - 1:
        raise ValueError(f"{len(records)} records do not fit {SLOTS - 1} slots")
    out = bytearray(RESOURCE_START + len(resources))
    out[0:4] = HEADER_SLOT_COUNT.to_bytes(4, "little")
    for index, record in enumerate(records, start=1):
        out[index * SLOT:(index + 1) * SLOT] = record
    out[RESOURCE_START:] = resources
    return bytes(out)


# ---------------------------------------------------------------- decoding (previews, tests)

def parse(data):
    """Records of an ``img.dat`` as dicts (the subset written above)."""
    records = []
    for index in range(1, SLOTS):
        raw = data[index * SLOT:(index + 1) * SLOT]
        if len(raw) < SLOT or not any(raw):
            continue
        kind = raw[0]
        item = {"slot": index, "type": kind, "id": raw[1],
                "box": tuple(int.from_bytes(raw[o:o + 2], "big") for o in (3, 5, 7, 9))}
        if kind == BACKGROUND:
            item["offset"] = int.from_bytes(raw[14:18], "big")
        elif kind == NUMBER:
            item.update(channel=raw[2], align=raw[11], color=int.from_bytes(raw[12:14], "big"), alpha=raw[15],
                        offset=int.from_bytes(raw[16:20], "big"), height=int.from_bytes(raw[20:22], "big"),
                        widths=tuple(int.from_bytes(raw[22 + 2 * k:24 + 2 * k], "big") for k in range(12)))
        elif kind == PROGRESS:
            item.update(channel=raw[2], style=raw[11], bg=int.from_bytes(raw[12:14], "big"),
                        fg=int.from_bytes(raw[14:16], "big"), frame=int.from_bytes(raw[16:18], "big"))
        elif kind == ROTATE:
            item["rotation"] = raw[1]
        records.append(item)
    return records


def _from565(value):
    return (((value >> 11) & 0x1F) * 255 // 31, ((value >> 5) & 0x3F) * 255 // 63, (value & 0x1F) * 255 // 31)


def render(data, values=None):
    """What the panel draws for ``values`` ({channel: int}): a PIL image decoded
    back out of the compiled bytes (so a correct preview proves the offsets)."""
    import numpy as np
    from PIL import Image
    values = values or {}
    records = parse(data)
    background = next(r for r in records if r["type"] == BACKGROUND)
    width, height = background["box"][2:]
    raw = np.frombuffer(data, dtype="<u2", count=width * height, offset=background["offset"])
    raw = raw.reshape(height, width)
    rgb = np.stack([((raw >> 11) & 0x1F) * 255 // 31, ((raw >> 5) & 0x3F) * 255 // 63, (raw & 0x1F) * 255 // 31],
                   axis=-1).astype("uint8")
    image = Image.fromarray(rgb, "RGB")
    for record in records:
        x, y, w, h = record["box"]
        if record["type"] == PROGRESS:
            value = max(0, min(100, int(values.get(record["channel"], 0))))
            image.paste(_from565(record["bg"]), (x, y, x + w, y + h))
            fill = round(w * value / 100)
            if fill:
                image.paste(_from565(record["fg"]), (x, y, x + fill, y + h))
        elif record["type"] == NUMBER and record["channel"] in values:
            cells = []
            offset = record["offset"]
            for cell_w in record["widths"]:
                size = cell_w * record["height"]
                cells.append(Image.frombytes("L", (cell_w, record["height"]), data[offset:offset + size]) if size
                             else None)
                offset += size
            cursor = x
            for char in str(int(values[record["channel"]])):
                cell = cells[GLYPHS.index(char)]
                if cell is None:
                    continue
                if cursor + cell.width <= x + w:
                    mask = cell.crop((0, 0, cell.width, min(cell.height, h)))
                    image.paste(_from565(record["color"]), (cursor, y, cursor + mask.width, y + mask.height), mask)
                cursor += cell.width
    return image
