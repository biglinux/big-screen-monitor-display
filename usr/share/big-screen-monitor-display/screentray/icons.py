# -*- coding: utf-8 -*-
"""
Geração dinâmica e carregamento de ícones da bandeja do sistema (Systray).
"""

import os
from pathlib import Path
try:
    from .qt import (
        QPixmap, QIcon, QPainter, QColor, QPen, QBrush,
        ANTIALIASING, NO_PEN
    )
except ImportError:
    from qt import (
        QPixmap, QIcon, QPainter, QColor, QPen, QBrush,
        ANTIALIASING, NO_PEN
    )


def create_screen_tray_icon(connected: bool = True, size: int = 64) -> QIcon:
    """Cria dinamicamente um ícone vetorial de monitor de tela com badge de status."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(0, 0, 0, 0))

    painter = QPainter(pixmap)
    painter.setRenderHint(ANTIALIASING, True)

    scale = size / 64.0

    # Moldura do Monitor (Bezel externo)
    # [x, y, w, h, rx, ry]
    outer_x = 4 * scale
    outer_y = 8 * scale
    outer_w = 56 * scale
    outer_h = 40 * scale
    radius = 5 * scale

    bezel_color = QColor(33, 38, 45) if connected else QColor(40, 44, 52)
    border_pen = QPen(QColor(88, 166, 255) if connected else QColor(110, 118, 129), 2 * scale)
    painter.setPen(border_pen)
    painter.setBrush(QBrush(bezel_color))
    painter.drawRoundedRect(int(outer_x), int(outer_y), int(outer_w), int(outer_h), int(radius), int(radius))

    # Área da Tela (Display LCD interno)
    inner_x = 8 * scale
    inner_y = 12 * scale
    inner_w = 48 * scale
    inner_h = 32 * scale
    screen_color = QColor(13, 17, 23) if connected else QColor(22, 27, 34)
    painter.setPen(NO_PEN)
    painter.setBrush(QBrush(screen_color))
    painter.drawRect(int(inner_x), int(inner_y), int(inner_w), int(inner_h))

    # Conteúdo da tela (linhas de telemetria / gráfico estilizado)
    if connected:
        # Gráfico ciano e barra verde
        painter.setPen(QPen(QColor(66, 232, 255), 1.5 * scale))
        painter.drawLine(int(12 * scale), int(32 * scale), int(22 * scale), int(24 * scale))
        painter.drawLine(int(22 * scale), int(24 * scale), int(32 * scale), int(28 * scale))
        painter.drawLine(int(32 * scale), int(28 * scale), int(42 * scale), int(18 * scale))
        painter.drawLine(int(42 * scale), int(18 * scale), int(52 * scale), int(22 * scale))

        # Barra de telemetria inferior
        painter.setPen(NO_PEN)
        painter.setBrush(QBrush(QColor(63, 185, 80)))
        painter.drawRoundedRect(int(12 * scale), int(36 * scale), int(24 * scale), int(3 * scale), 1, 1)

        painter.setBrush(QBrush(QColor(240, 68, 219)))
        painter.drawRoundedRect(int(38 * scale), int(36 * scale), int(14 * scale), int(3 * scale), 1, 1)

    # Base / Suporte do Monitor
    stand_w = 16 * scale
    stand_h = 6 * scale
    stand_x = (size - stand_w) / 2
    stand_y = outer_y + outer_h
    painter.setPen(NO_PEN)
    painter.setBrush(QBrush(QColor(88, 166, 255) if connected else QColor(110, 118, 129)))
    painter.drawRect(int(stand_x), int(stand_y), int(stand_w), int(stand_h))

    # Pé do Suporte
    foot_w = 28 * scale
    foot_h = 3 * scale
    foot_x = (size - foot_w) / 2
    foot_y = stand_y + stand_h
    painter.drawRoundedRect(int(foot_x), int(foot_y), int(foot_w), int(foot_h), 1, 1)

    # Badge de Status (Canto inferior direito: Verde para conectado, Vermelho para desconectado)
    badge_radius = 6 * scale
    badge_cx = 54 * scale
    badge_cy = 50 * scale
    badge_color = QColor(63, 185, 80) if connected else QColor(248, 81, 73)

    painter.setPen(QPen(QColor(13, 17, 23), 2 * scale))
    painter.setBrush(QBrush(badge_color))
    painter.drawEllipse(int(badge_cx - badge_radius), int(badge_cy - badge_radius),
                        int(badge_radius * 2), int(badge_radius * 2))

    painter.end()
    return QIcon(pixmap)
