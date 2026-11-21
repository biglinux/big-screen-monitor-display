# -*- coding: utf-8 -*-
"""Geração de ícones dinâmicos para o system tray (PyQt6/PyQt5)."""

from typing import Optional, Union

try:
    from qt import (
        ALIGN_CENTER, ANTIALIASING, FONT_BOLD, NO_PEN, QBrush, QColor,
        QConicalGradient, QFont, QIcon, QPainter, QPen, QPixmap
    )
except ImportError:
    from .qt import (
        ALIGN_CENTER, ANTIALIASING, FONT_BOLD, NO_PEN, QBrush, QColor,
        QConicalGradient, QFont, QIcon, QPainter, QPen, QPixmap
    )


def create_deepcool_icon(connected: bool = True) -> QIcon:
    """Cria ícone com o símbolo estilizado do DeepCool."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(ANTIALIASING)

    bg = QColor(0, 137, 123) if connected else QColor(120, 120, 120)
    painter.setBrush(bg)
    painter.setPen(NO_PEN)
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)

    painter.setBrush(QColor(255, 255, 255))
    painter.drawRoundedRect(26, 12, 12, 40, 3, 3)
    painter.drawRoundedRect(12, 26, 40, 12, 3, 3)

    painter.end()
    return QIcon(pixmap)


def create_status_icon(
    display_value: Union[int, float],
    unit: str = "°C",
    connected: bool = True,
    temp_celsius: Optional[float] = None
) -> QIcon:
    """
    Cria ícone dinâmico com valor numérico e cor baseada no nível térmico.
    Exibe números nítidos e legíveis na barra de tarefas.
    """
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(ANTIALIASING)

    celsius_ref = temp_celsius if temp_celsius is not None else float(display_value)

    if not connected:
        bg = QColor(100, 100, 100)
    elif celsius_ref >= 80:
        bg = QColor(211, 47, 47)     # Vermelho (crítico)
    elif celsius_ref >= 65:
        bg = QColor(245, 124, 0)     # Laranja (aquecido)
    else:
        bg = QColor(0, 137, 123)     # Teal / verde petróleo (normal)

    painter.setBrush(bg)
    painter.setPen(NO_PEN)
    painter.drawRoundedRect(2, 2, 60, 60, 14, 14)

    val_int = int(round(display_value))
    painter.setPen(QColor(255, 255, 255))
    painter.setFont(QFont("sans-serif", 20 if val_int < 100 else 16, FONT_BOLD))
    painter.drawText(2, 2, 60, 48, ALIGN_CENTER, str(val_int))

    painter.setFont(QFont("sans-serif", 10))
    painter.drawText(2, 38, 60, 22, ALIGN_CENTER, unit)

    painter.end()
    return QIcon(pixmap)


def make_color_icon(
    hex_color: Optional[str] = None,
    size: int = 16,
    is_rainbow: bool = False,
    is_off: bool = False,
) -> QIcon:
    """Cria ícone circular para a seleção de cor no menu."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(ANTIALIASING)

    if is_off:
        painter.setBrush(QBrush(QColor("#333333")))
        painter.setPen(QPen(QColor("#555555"), 1))
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.setPen(QPen(QColor("#888888"), 1.5))
        painter.drawLine(4, 4, size - 4, size - 4)
        painter.drawLine(size - 4, 4, 4, size - 4)
    elif is_rainbow:
        gradient = QConicalGradient(size / 2, size / 2, 0)
        gradient.setColorAt(0.0, QColor("#FF0000"))
        gradient.setColorAt(0.17, QColor("#FF9900"))
        gradient.setColorAt(0.33, QColor("#FFFF00"))
        gradient.setColorAt(0.50, QColor("#00FF00"))
        gradient.setColorAt(0.67, QColor("#0099FF"))
        gradient.setColorAt(0.83, QColor("#6633FF"))
        gradient.setColorAt(1.0, QColor("#FF0000"))
        painter.setBrush(QBrush(gradient))
        painter.setPen(NO_PEN)
        painter.drawEllipse(1, 1, size - 2, size - 2)
    else:
        color = QColor(hex_color or "#00CCCC")
        painter.setBrush(QBrush(color))
        if hex_color and hex_color.upper() in ("#FFFFFF", "#FFF"):
            painter.setPen(QPen(QColor("#AAAAAA"), 1))
        else:
            painter.setPen(NO_PEN)
        painter.drawEllipse(1, 1, size - 2, size - 2)

    painter.end()
    return QIcon(pixmap)
