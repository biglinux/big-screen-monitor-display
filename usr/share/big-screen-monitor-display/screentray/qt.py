# -*- coding: utf-8 -*-
"""
Camada de compatibilidade transparente entre PyQt5 e PyQt6 para o System Tray do Monitor 3.5".
"""

try:
    from PyQt6.QtWidgets import (
        QApplication, QMessageBox, QSystemTrayIcon, QMenu, QWidget, QFrame,
        QLabel, QPushButton, QSlider, QComboBox, QVBoxLayout, QHBoxLayout,
        QGridLayout, QScrollArea, QGraphicsDropShadowEffect
    )
    from PyQt6.QtGui import (
        QAction, QActionGroup, QColor, QPixmap, QImage, QIcon, QPainter, QBrush,
        QPen, QFont, QCursor
    )
    from PyQt6.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QSize
    IS_PYQT6 = True
except ImportError:
    from PyQt5.QtWidgets import (
        QApplication, QMessageBox, QSystemTrayIcon, QMenu, QAction,
        QActionGroup, QWidget, QFrame, QLabel, QPushButton, QSlider,
        QComboBox, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
        QGraphicsDropShadowEffect
    )
    from PyQt5.QtGui import (
        QColor, QPixmap, QImage, QIcon, QPainter, QBrush, QPen, QFont, QCursor
    )
    from PyQt5.QtCore import Qt, pyqtSignal, QObject, QTimer, QPoint, QSize
    IS_PYQT6 = False


# Aliases compatíveis para Enums do Qt
if IS_PYQT6:
    ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
    ALIGN_LEFT = Qt.AlignmentFlag.AlignLeft
    ALIGN_RIGHT = Qt.AlignmentFlag.AlignRight
    NO_PEN = Qt.PenStyle.NoPen
    ANTIALIASING = QPainter.RenderHint.Antialiasing
    SMOOTH_PIXMAP = QPainter.RenderHint.SmoothPixmapTransform
    FONT_BOLD = QFont.Weight.Bold
    ORIENT_HORIZ = Qt.Orientation.Horizontal
    ORIENT_VERT = Qt.Orientation.Vertical
    TOOL_FLAG = Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
else:
    ALIGN_CENTER = Qt.AlignCenter
    ALIGN_LEFT = Qt.AlignLeft
    ALIGN_RIGHT = Qt.AlignRight
    NO_PEN = Qt.NoPen
    ANTIALIASING = QPainter.Antialiasing
    SMOOTH_PIXMAP = QPainter.SmoothPixmapTransform
    FONT_BOLD = QFont.Bold
    ORIENT_HORIZ = Qt.Horizontal
    ORIENT_VERT = Qt.Vertical
    TOOL_FLAG = Qt.ToolTip | Qt.FramelessWindowHint
