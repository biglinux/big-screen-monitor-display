"""PyQt6 when available, PyQt5 otherwise, behind one set of names.

Enum members are reached through their scoped names (``Qt.AlignmentFlag.X``),
which PyQt6 requires and PyQt5 (5.11+) also accepts; ``exec_app`` hides the
``exec``/``exec_`` difference.
"""

try:
    from PyQt6 import QtCore, QtGui, QtWidgets
    from PyQt6.QtGui import QAction, QActionGroup
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
    BINDING = "PyQt6"
except ImportError:  # pragma: no cover - depends on the installed binding
    from PyQt5 import QtCore, QtGui, QtWidgets
    from PyQt5.QtNetwork import QLocalServer, QLocalSocket  # noqa: F401 (re-exported)
    from PyQt5.QtWidgets import QAction, QActionGroup  # noqa: F401 (re-exported)
    BINDING = "PyQt5"

Qt = QtCore.Qt
QTimer = QtCore.QTimer
QObject = QtCore.QObject
QThread = QtCore.QThread
QSize = QtCore.QSize
QPoint = QtCore.QPoint
QRect = QtCore.QRect
QRectF = QtCore.QRectF
Signal = QtCore.pyqtSignal

QColor = QtGui.QColor
QFont = QtGui.QFont
QIcon = QtGui.QIcon
QImage = QtGui.QImage
QPainter = QtGui.QPainter
QPainterPath = QtGui.QPainterPath
QPalette = QtGui.QPalette
QPen = QtGui.QPen
QPixmap = QtGui.QPixmap
QKeySequence = QtGui.QKeySequence

QApplication = QtWidgets.QApplication
QButtonGroup = QtWidgets.QButtonGroup
QComboBox = QtWidgets.QComboBox
QFrame = QtWidgets.QFrame
QGridLayout = QtWidgets.QGridLayout
QHBoxLayout = QtWidgets.QHBoxLayout
QLabel = QtWidgets.QLabel
QMenu = QtWidgets.QMenu
QMessageBox = QtWidgets.QMessageBox
QProgressBar = QtWidgets.QProgressBar
QPushButton = QtWidgets.QPushButton
QScrollArea = QtWidgets.QScrollArea
QSizePolicy = QtWidgets.QSizePolicy
QSlider = QtWidgets.QSlider
QSystemTrayIcon = QtWidgets.QSystemTrayIcon
QToolButton = QtWidgets.QToolButton
QVBoxLayout = QtWidgets.QVBoxLayout
QWidget = QtWidgets.QWidget
QColorDialog = QtWidgets.QColorDialog
QShortcut = getattr(QtGui, "QShortcut", None) or QtWidgets.QShortcut   # QtGui in Qt 6, QtWidgets in Qt 5


def exec_app(app):
    return app.exec() if hasattr(app, "exec") else app.exec_()


def exec_menu(menu, pos):
    return menu.exec(pos) if hasattr(menu, "exec") else menu.exec_(pos)


def dark_palette(widget=None):
    """True when the desktop palette is dark (window darker than its text)."""
    palette = (widget.palette() if widget is not None else QApplication.palette())
    window = palette.color(QPalette.ColorRole.Window)
    text = palette.color(QPalette.ColorRole.WindowText)
    return window.lightness() < text.lightness()
