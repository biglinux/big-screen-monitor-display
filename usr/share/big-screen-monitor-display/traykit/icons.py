"""Tray icons drawn at every size the panel may ask for (crisp on HiDPI).

Each icon has a dark outline and a light inner mark, so it reads on light and
dark panels alike. The state colours match the window's status pill.
"""

from .qt import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRectF, Qt

SIZES = (16, 22, 24, 32, 48, 64, 128)
STATE_COLOURS = {"ok": "#2e7d32", "warning": "#ef6c00", "error": "#c62828", "off": "#757575"}


def heat_colour(celsius, alarm=None):
    """Green, amber or red for a CPU temperature (``None``: grey, nothing measured)."""
    if celsius is None:
        return QColor("#616161")
    hot = alarm if alarm else 85
    if celsius >= hot:
        return QColor("#c62828")
    if celsius >= min(70, hot - 10):
        return QColor("#ef6c00")
    return QColor("#2e7d32")


def _canvas(size):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    return pixmap, painter


def _icon(draw):
    icon = QIcon()
    for size in SIZES:
        pixmap, painter = _canvas(size)
        draw(painter, size)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


def screen_icon(state="ok"):
    """A small monitor with a status dot (connected, warning, error, off)."""
    def draw(painter, size):
        s = size / 32.0
        outline = QPen(QColor("#1b1f24"), max(1.0, 1.6 * s))
        painter.setPen(outline)
        painter.setBrush(QColor("#1565c0") if state != "off" else QColor("#78909c"))
        painter.drawRoundedRect(QRectF(2 * s, 4 * s, 28 * s, 19 * s), 3 * s, 3 * s)
        painter.setBrush(QColor("#e3f2fd") if state != "off" else QColor("#cfd8dc"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRect(QRectF(5 * s, 7 * s, 22 * s, 13 * s))
        painter.setPen(outline)
        painter.setBrush(QColor("#455a64"))
        painter.drawRect(QRectF(13 * s, 23 * s, 6 * s, 4 * s))
        painter.drawRoundedRect(QRectF(8 * s, 26.5 * s, 16 * s, 3 * s), 1.5 * s, 1.5 * s)
        if state != "ok":
            painter.setBrush(QColor(STATE_COLOURS.get(state, STATE_COLOURS["off"])))
            painter.setPen(QPen(QColor("#ffffff"), max(1.0, 1.4 * s)))
            painter.drawEllipse(QRectF(19 * s, 15 * s, 12 * s, 12 * s))
    return _icon(draw)


def value_icon(text, colour, connected=True):
    """A rounded badge with a number (CPU temperature or usage) in it."""
    def draw(painter, size):
        rect = QRectF(0.5, 0.5, size - 1, size - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, size * 0.22, size * 0.22)
        painter.fillPath(path, colour if connected else QColor("#616161"))
        painter.setPen(QPen(QColor(0, 0, 0, 110), max(1.0, size / 32)))
        painter.drawPath(path)
        font = QFont()
        font.setBold(True)
        label = text if text else "--"
        font.setPixelSize(max(6, int(size * (0.62 if len(label) <= 2 else 0.46))))
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), label)
        if not connected:
            painter.setPen(QPen(QColor("#ffffff"), max(1.2, size / 14)))
            painter.drawLine(int(size * 0.18), int(size * 0.82), int(size * 0.82), int(size * 0.18))
    return _icon(draw)


def swatch_icon(colour=None, rainbow=False, off=False, size=16):
    """Colour sample for menus (OpenRGB colours)."""
    pixmap, painter = _canvas(size)
    rect = QRectF(1, 1, size - 2, size - 2)
    if rainbow:
        from .qt import QtGui
        gradient = QtGui.QConicalGradient(rect.center(), 0)
        for stop, value in ((0, "#ff0000"), (0.17, "#ffff00"), (0.33, "#00ff00"), (0.5, "#00ffff"),
                            (0.67, "#0000ff"), (0.83, "#ff00ff"), (1, "#ff0000")):
            gradient.setColorAt(stop, QColor(value))
        painter.setBrush(gradient)
    elif off:
        painter.setBrush(QColor("#212121"))
    else:
        painter.setBrush(QColor(colour or "#000000"))
    painter.setPen(QPen(QColor("#757575"), 1))
    painter.drawEllipse(rect)
    if off:
        painter.setPen(QPen(QColor("#bdbdbd"), 1.5))
        painter.drawLine(4, size - 4, size - 4, 4)
    painter.end()
    return QIcon(pixmap)
