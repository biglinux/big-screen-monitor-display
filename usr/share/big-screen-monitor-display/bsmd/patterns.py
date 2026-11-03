"""Test patterns shown on a panel for a few seconds (identify, colours, geometry).

They are rendered like a theme frame (in the display's orientation) so they
also check rotation, colour order, byte order and partial updates; the
runtime restores the theme with a full frame afterwards.
"""

from PIL import Image, ImageDraw

from . import themes
from .i18n import N_, _
from .settings import PATTERN_NAMES

NAMES = PATTERN_NAMES
LABELS = {
    "identify": N_("Identify"),
    "bars": N_("Colour bars"),
    "grid": N_("Geometry grid"),
    "gradient": N_("Gradients"),
    "orientation": N_("Orientation"),
    "white": N_("White (backlight)"),
    "black": N_("Black (contrast)"),
}
BARS = ((255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255),
        (0, 0, 0))


def _centered(draw, text, font, y, width, fill):
    text_width = draw.textlength(text, font=font)
    draw.text(((width - text_width) / 2, y), text, font=font, fill=fill)


def _fit_font(draw, text, width, size, bold=True):
    while size > 8:
        font = themes.ui_font(size, bold=bold)
        if draw.textlength(text, font=font) <= width:
            return font
        size -= 2
    return themes.ui_font(8, bold=bold)


def _identify(image, draw, width, height, label, display_id):
    draw.rectangle((0, 0, width - 1, height - 1), outline=(80, 170, 255), width=max(2, min(width, height) // 40))
    big = _fit_font(draw, label, width * 0.86, max(10, height // 6))
    small = _fit_font(draw, display_id, width * 0.9, max(8, height // 14), bold=False)
    _centered(draw, label, big, height * 0.36, width, (235, 242, 255))
    _centered(draw, display_id, small, height * 0.36 + big.size * 1.3, width, (140, 170, 210))
    _centered(draw, f"{width}x{height}", small, height * 0.36 + big.size * 1.3 + small.size * 1.4, width,
              (110, 130, 160))


def _bars(image, draw, width, height):
    band = height * 3 // 4
    for index, color in enumerate(BARS):
        draw.rectangle((index * width // 8, 0, (index + 1) * width // 8 - 1, band), fill=color)
    for x in range(width):     # grey ramp: banding shows the colour depth
        level = x * 255 // max(1, width - 1)
        draw.line((x, band + 1, x, height - 1), fill=(level, level, level))


def _grid(image, draw, width, height):
    step = max(8, min(width, height) // 8)
    for x in range(0, width, step):
        draw.line((x, 0, x, height - 1), fill=(70, 80, 100))
    for y in range(0, height, step):
        draw.line((0, y, width - 1, y), fill=(70, 80, 100))
    draw.rectangle((0, 0, width - 1, height - 1), outline=(255, 255, 255))
    draw.line((0, 0, width - 1, height - 1), fill=(255, 80, 80))
    draw.line((0, height - 1, width - 1, 0), fill=(80, 255, 120))
    radius = min(width, height) // 2 - 2
    draw.ellipse((width // 2 - radius, height // 2 - radius, width // 2 + radius, height // 2 + radius),
                 outline=(90, 170, 255), width=2)
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        draw.rectangle((x - 3, y - 3, x + 3, y + 3), fill=(255, 220, 0))


def _gradient(image, draw, width, height):
    rows = ((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255))
    band = max(1, height // len(rows))
    for row, (r, g, b) in enumerate(rows):
        for x in range(width):
            k = x / max(1, width - 1)
            draw.line((x, row * band, x, (row + 1) * band - 1), fill=(int(r * k), int(g * k), int(b * k)))


def _orientation(image, draw, width, height):
    size = min(width, height)
    cx = width // 2
    head = size // 3
    draw.polygon(((cx, size // 10), (cx - head // 2, size // 10 + head), (cx + head // 2, size // 10 + head)),
                 fill=(80, 200, 120))
    draw.rectangle((cx - head // 6, size // 10 + head, cx + head // 6, size // 10 + head * 2), fill=(80, 200, 120))
    font = _fit_font(draw, _("TOP"), width * 0.5, max(9, size // 9))
    _centered(draw, _("TOP"), font, size // 10 + head * 2 + 4, width, (235, 240, 255))
    corner = themes.ui_font(max(8, size // 16), bold=True)
    for text, xy in (("1", (4, 2)), ("2", (width - corner.size, 2)), ("3", (4, height - corner.size - 4)),
                     ("4", (width - corner.size, height - corner.size - 4))):
        draw.text(xy, text, font=corner, fill=(255, 220, 0))


def render(name, width, height, label="", display_id="", shape="rect"):
    """One test pattern frame of ``width`` x ``height``."""
    background = {"white": (255, 255, 255)}.get(name, (0, 0, 0) if name == "black" else (12, 14, 20))
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    if name == "identify":
        _identify(image, draw, width, height, label or display_id, display_id)
    elif name == "bars":
        _bars(image, draw, width, height)
    elif name == "grid":
        _grid(image, draw, width, height)
    elif name == "gradient":
        _gradient(image, draw, width, height)
    elif name == "orientation":
        _orientation(image, draw, width, height)
    if shape == "round" and name not in ("white", "black"):
        radius = min(width, height) // 2 - 1
        draw.ellipse((width // 2 - radius, height // 2 - radius, width // 2 + radius, height // 2 + radius),
                     outline=(255, 120, 0), width=2)
    return image
