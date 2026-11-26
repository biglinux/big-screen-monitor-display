"""Tray icons drawn at every size the panel may ask for (crisp on HiDPI).

The screens' icon is a monochrome (symbolic) monitor drawn in the panel's
text colour, with a status dot; the DeepCool badge carries a number. Both
read on light and dark panels alike.
"""

import os

from .qt import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap, QRectF, Qt, QtCore, \
    QtWidgets

QPointF = QtCore.QPointF

SIZES = (16, 22, 24, 32, 48, 64, 128)


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


# Status dot of the symbolic tray icon (screentray.states colours). GNOME palette
# tones bright enough for dark panels; each dot has a darker rim of its own hue
# so yellow and green still read on light panels.
DOT_COLOURS = {"green": "#2ec27e", "yellow": "#f5c211", "red": "#e01b24", "grey": "#9a9996"}
LIGHT_FOREGROUND, DARK_FOREGROUND = "#f6f5f4", "#241f31"


def panel_foreground(app=None, desktop=None):
    """Colour of the symbols on the panel that hosts the tray icon.

    The tray gets a picture, not an icon name (the status dot is drawn into
    it), so the panel cannot recolour it like a "-symbolic" theme icon: the
    monochrome monitor is drawn in the panel's text colour instead. GNOME
    Shell's top bar is dark in both styles; elsewhere the panel follows the
    desktop colour scheme (Qt 6.5+), else the lightness of the palette's text.
    """
    desktop = (desktop if desktop is not None else os.environ.get("XDG_CURRENT_DESKTOP", "")).lower()
    if "gnome" in desktop.split(":"):
        return QColor(LIGHT_FOREGROUND)
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return QColor(DARK_FOREGROUND)
    schemes = getattr(QtCore.Qt, "ColorScheme", None)
    scheme = getattr(app.styleHints(), "colorScheme", None)
    if schemes is not None and scheme is not None:
        value = scheme()
        if value == schemes.Dark:
            return QColor(LIGHT_FOREGROUND)
        if value == schemes.Light:
            return QColor(DARK_FOREGROUND)
    text = app.palette().color(QPalette.ColorRole.WindowText)
    return QColor(LIGHT_FOREGROUND) if text.lightness() > 128 else QColor(DARK_FOREGROUND)


def _stroke(size):
    # 1 px at 16, 2 px at 22-32: whole pixels keep the outline crisp.
    return float(max(1, round(size / 14)))


def draw_monitor(painter, size, foreground):
    """Monochrome monitor: screen outline, neck and foot (same shape as the -symbolic SVG)."""
    width = _stroke(size)
    half = width / 2
    pen = QPen(QColor(foreground), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    unit = size / 16.0
    # 16 px grid: screen x 1..15, y 2..11.5; strokes centred on whole/half pixels.
    left, top = round(1 * unit) + half, round(2 * unit) + half
    right, bottom = round(15 * unit) - half, round(11.5 * unit) - half
    painter.drawRoundedRect(QRectF(left, top, right - left, bottom - top), 1.5 * unit, 1.5 * unit)
    centre = size / 2 if int(width) % 2 == 0 else round(size / 2 - 0.5) + 0.5
    foot = round(14.5 * unit) - half
    painter.drawLine(QPointF(centre, bottom + half), QPointF(centre, foot))
    painter.drawLine(QPointF(round(5 * unit) + half, foot), QPointF(round(11 * unit) - half, foot))


def draw_dot(painter, size, dot):
    """Status dot at the upper right, inside a transparent gap (never merges with the outline);
    the stand stays whole, so the shape still reads as a monitor at 16 px."""
    radius = max(2.5, size * 0.19)
    cx, cy = size - radius - 0.5, radius + 0.5
    gap = radius + max(1.0, size / 16)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0))
    painter.drawEllipse(QRectF(cx - gap, cy - gap, 2 * gap, 2 * gap))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    colour = QColor(DOT_COLOURS.get(dot, DOT_COLOURS["grey"]))
    painter.setBrush(colour)
    painter.setPen(QPen(colour.darker(150), max(1.0, size / 24)))
    painter.drawEllipse(QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius))


def screen_icon(dot="green", foreground=None):
    """Tray icon of the USB screens: symbolic monitor in the panel's text colour + status dot.

    ``dot``: green, yellow, red or grey (screentray.states). A stopped service
    also dims the monitor, so it reads without relying on colour alone."""
    foreground = QColor(foreground) if foreground is not None else panel_foreground()

    def draw(painter, size):
        painter.setOpacity(0.55 if dot == "grey" else 1.0)
        draw_monitor(painter, size, foreground)
        painter.setOpacity(1.0)
        draw_dot(painter, size, dot)
    return _icon(draw)


def dot_icon(dot, size=16):
    """Small coloured dot for menu entries (state of each display)."""
    pixmap, painter = _canvas(size)
    colour = QColor(DOT_COLOURS.get(dot, DOT_COLOURS["grey"]))
    painter.setBrush(colour)
    painter.setPen(QPen(colour.darker(150), 1))
    radius = size * 0.28
    painter.drawEllipse(QRectF(size / 2 - radius, size / 2 - radius, 2 * radius, 2 * radius))
    painter.end()
    return QIcon(pixmap)


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
