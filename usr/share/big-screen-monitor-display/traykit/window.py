"""Control window shared by the tray apps.

An ordinary top-level window (title bar, keyboard focus, closes with Esc):
Wayland compositors do not let a client place a frameless popup next to the
tray icon, so it is only positioned on X11, when the icon geometry is known.
Colours come from the desktop palette, so light and dark themes keep contrast.
"""

from bsmd.i18n import _

from .qt import (QApplication, QFrame, QHBoxLayout, QIcon, QKeySequence, QLabel, QProgressBar, QPushButton,
                 QScrollArea, QShortcut, QSizePolicy, QTimer, QVBoxLayout, QWidget, Qt)

STYLE = """
QFrame#note, QFrame#message {
    background: palette(alternate-base);
    border: 1px solid palette(mid);
    border-radius: 8px;
}
QFrame#message[error="true"] { border-color: #c62828; }
QLabel#title { font-size: 15px; font-weight: 600; }
QLabel#section { font-weight: 600; padding-top: 6px; }
QLabel#muted { color: palette(placeholder-text); }
QLabel#pill {
    border-radius: 9px;
    padding: 2px 10px;
    border: 1px solid palette(mid);
}
QProgressBar#busy { max-height: 3px; border: 0; background: transparent; }
QProgressBar#busy::chunk { background: palette(highlight); }
"""

# state -> (dot colour, label); colours readable on light and dark backgrounds
STATES = {
    "ok": ("#2e7d32", ""),
    "warning": ("#ef6c00", ""),
    "error": ("#c62828", ""),
    "off": ("#757575", ""),
}


def section_label(text):
    label = QLabel(text)
    label.setObjectName("section")
    return label


def muted_label(text="", wrap=True):
    label = QLabel(text)
    label.setObjectName("muted")
    label.setWordWrap(wrap)
    return label


class PanelWindow(QWidget):
    def __init__(self, title, icon_name, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("panel")
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon.fromTheme(icon_name))
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(380)
        self.resize(460, 640)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.busy = QProgressBar()
        self.busy.setObjectName("busy")
        self.busy.setRange(0, 0)
        self.busy.setTextVisible(False)
        self.busy.setVisible(False)
        outer.addWidget(self.busy)

        header = QHBoxLayout()
        header.setContentsMargins(18, 16, 18, 8)
        header.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(QIcon.fromTheme(icon_name).pixmap(40, 40))
        icon.setAccessibleName(title)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("title")
        self.subtitle = muted_label()
        names.addWidget(self.title)
        names.addWidget(self.subtitle)
        header.addLayout(names, 1)
        self.pill = QLabel()
        self.pill.setObjectName("pill")
        self.pill.setAccessibleDescription(_("Connection state"))
        header.addWidget(self.pill, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        self.body = QVBoxLayout(body)
        self.body.setContentsMargins(18, 4, 18, 12)
        self.body.setSpacing(10)
        self.host_note = self._note_frame("note")
        self.message = self._note_frame("message")
        self.body.addWidget(self.host_note)
        self.body.addWidget(self.message)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(18, 8, 18, 14)
        self.footer.setSpacing(8)
        outer.addLayout(self.footer)

        self._message_timer = QTimer(self)
        self._message_timer.setSingleShot(True)
        self._message_timer.timeout.connect(lambda: self.message.setVisible(False))
        QShortcut(QKeySequence(QKeySequence.StandardKey.Close), self, activated=self.close)
        QShortcut(QKeySequence("Esc"), self, activated=self.close)

    # ------------------------------------------------------------ building blocks
    def _note_frame(self, name):
        frame = QFrame()
        frame.setObjectName(name)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 10, 12, 10)
        label = QLabel()
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(label, 1)
        frame.label = label
        frame.setVisible(False)
        return frame

    def add_footer_button(self, text, callback, tooltip=""):
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.clicked.connect(callback)
        self.footer.addWidget(button)
        return button

    def add_footer_stretch(self):
        self.footer.addStretch(1)

    def add_session_option(self, text, checked, callback):
        """Check box at the end of the window body (keeps the footer short on narrow windows)."""
        from .qt import QtWidgets
        box = QtWidgets.QCheckBox(text)
        box.setChecked(checked)
        box.toggled.connect(callback)
        self.body.addWidget(box)
        return box

    # ------------------------------------------------------------ state
    def set_state(self, kind, text, subtitle=None):
        colour = STATES.get(kind, STATES["off"])[0]
        self.pill.setText(f"<span style='color:{colour}'>●</span> {text}")
        self.pill.setToolTip(text)
        self.pill.setAccessibleName(text)
        if subtitle is not None:
            self.subtitle.setText(subtitle)
            self.subtitle.setVisible(bool(subtitle))

    def set_host_note(self, text):
        self.host_note.label.setText(text)
        self.host_note.setVisible(bool(text))

    def show_message(self, text, error=False, timeout_ms=8000):
        self.message.setProperty("error", "true" if error else "false")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.label.setText(text)
        self.message.setVisible(bool(text))
        if text and timeout_ms:
            self._message_timer.start(timeout_ms)

    def set_busy(self, busy):
        self.busy.setVisible(busy)

    # ------------------------------------------------------------ showing
    def present_near(self, tray_geometry=None):
        """Show, raise and focus (user-requested), next to the icon on X11 when known."""
        if QApplication.platformName() == "xcb" and tray_geometry is not None and tray_geometry.isValid() \
                and not self.isVisible():
            screen = QApplication.screenAt(tray_geometry.center()) or QApplication.primaryScreen()
            area = screen.availableGeometry()
            size = self.sizeHint().expandedTo(self.size())
            x = min(max(area.left(), tray_geometry.center().x() - size.width() // 2), area.right() - size.width())
            if tray_geometry.center().y() > area.center().y():
                y = max(area.top(), tray_geometry.top() - size.height() - 8)
            else:
                y = min(tray_geometry.bottom() + 8, area.bottom() - size.height())
            self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # With a tray icon the window only hides; without one, closing quits
        # (nothing would be left to reach the app).
        if getattr(self.owner, "tray", None) is not None:
            event.ignore()
            self.hide()
        else:
            event.accept()
            self.owner.quit()


def expanding():
    widget = QWidget()
    widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return widget
