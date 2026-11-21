"""Tray app for the USB screens (Turing/UsbPCMonitor 3.5", AX206, WeAct, Kipye...).

The screens come from the service status (the service follows USB hot-plug
through udev and reconnects by itself); this app never opens a device. Changes
go through ``bsmd.control`` (validated, atomic, polkit helper) with the same
global / per-display meaning as the configuration window.
"""

import hashlib
import json
import logging
import os
import sys

from bsmd import __version__, control
from bsmd.i18n import N_, _

from traykit import autostart
from traykit.base import TrayApp
from traykit.icons import screen_icon
from traykit.qt import (QAction, QActionGroup, QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QIcon, QLabel,
                        QMenu, QPixmap, QPushButton, QSize, QSlider, QTimer, QToolButton, QWidget, Qt,
                        QtCore)
from traykit.window import FlowLayout, PanelWindow, muted_label, section_label

from . import catalog

log = logging.getLogger("bsmd.screentray")
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THUMB_DIR = os.path.join(APP_DIR, "screentray", "thumbnails")
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "big-screen-monitor-display", "tray-thumbnails")
STATE_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                          "big-screen-monitor-display", "screen-tray.json")
CARD_SIZE = QSize(168, 112)
ALL = ""

# status display state -> (pill kind, label)
STATE_TEXT = {
    "healthy": ("ok", N_("Connected")),
    "degraded": ("warning", N_("Unstable connection")),
    "starting": ("warning", N_("Starting…")),
    "recovering": ("warning", N_("Reconnecting…")),
    "retrying": ("warning", N_("Reconnecting…")),
    "disconnected": ("error", N_("Disconnected")),
    "failed": ("error", N_("Not responding")),
}


def display_name(entry):
    settings_name = (entry.get("settings") or {}).get("name")
    device = entry.get("device") or {}
    return settings_name or entry.get("name") or device.get("model") or entry.get("id", "?")


def display_size(entry, orientation):
    device = entry.get("device") or {}
    width, height = device.get("width") or 480, device.get("height") or 320
    if width < height:
        width, height = height, width
    if str(orientation).startswith("vertical"):
        width, height = height, width
    return int(width), int(height)


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError as error:
        log.warning("could not save %s: %s", STATE_FILE, error)


class ThemeCard(QToolButton):
    """Focusable, checkable card: thumbnail, name; the summary is the tooltip."""

    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self.setCheckable(True)
        self.setAutoRaise(False)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setIconSize(CARD_SIZE)
        self.setText(_(theme.name))
        self.setToolTip(_(theme.summary))
        self.setAccessibleName(_(theme.name))
        self.setAccessibleDescription(_(theme.summary))
        self.setMinimumSize(CARD_SIZE + QSize(16, 34))
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_picture(self, path):
        pixmap = QPixmap(path) if path and os.path.exists(path) else QPixmap()
        if pixmap.isNull():
            pixmap = QPixmap(CARD_SIZE)
            pixmap.fill(Qt.GlobalColor.darkGray)
        self.setIcon(QIcon(pixmap.scaled(CARD_SIZE, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)))


CARD_STYLE = """
QToolButton {
    border: 1px solid palette(mid);
    border-radius: 10px;
    padding: 6px;
    background: palette(base);
}
QToolButton:hover { border-color: palette(highlight); }
QToolButton:focus { border: 2px solid palette(highlight); }
QToolButton:checked {
    border: 2px solid palette(highlight);
    background: palette(alternate-base);
    font-weight: 600;
}
QToolButton:disabled { color: palette(placeholder-text); }
"""
CHIP_STYLE = """
QPushButton {
    border: 1px solid palette(mid);
    border-radius: 12px;
    padding: 3px 12px;
    background: palette(button);
}
QPushButton:hover { border-color: palette(highlight); }
QPushButton:checked { border: 2px solid palette(highlight); background: palette(alternate-base); font-weight: 600; }
"""


class ScreenWindow(PanelWindow):
    def __init__(self, owner):
        super().__init__(_("Big Screen Monitor"), owner.icon_name, owner)
        body = self.body

        # Target display (only with more than one screen).
        self.target_row = QWidget()
        row = QHBoxLayout(self.target_row)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(_("Apply to"))
        self.target = QComboBox()
        self.target.setAccessibleName(_("Display that receives the changes"))
        self.target.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(10)
        label.setBuddy(self.target)
        row.addWidget(label)
        row.addWidget(self.target, 1)
        body.addWidget(self.target_row)

        self.empty = muted_label()
        body.addWidget(self.empty)

        # Gallery.
        body.addWidget(section_label(_("Theme")))
        grid_host = QWidget()
        self.grid = QGridLayout(grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        grid_host.setStyleSheet(CARD_STYLE)
        self.cards = {}
        self.card_group = QButtonGroup(self)
        self.card_group.setExclusive(True)
        for theme in catalog.THEMES:
            card = ThemeCard(theme)
            card.set_picture(os.path.join(THUMB_DIR, catalog.placeholder(theme.id) or ""))
            card.clicked.connect(lambda _checked=False, t=theme.id: owner.choose_theme(t))
            self.card_group.addButton(card)
            self.cards[theme.id] = card
        self._columns = 0
        self._reflow(2)
        body.addWidget(grid_host)

        self.variant_title = section_label("")
        body.addWidget(self.variant_title)
        self.variant_host = QWidget()
        self.variant_host.setStyleSheet(CHIP_STYLE)
        self.variant_grid = FlowLayout(self.variant_host)
        body.addWidget(self.variant_host)
        self.variant_group = QButtonGroup(self)
        self.variant_buttons = []
        self.more_note = muted_label()
        body.addWidget(self.more_note)

        # Brightness.
        body.addWidget(section_label(_("Brightness")))
        bright = QHBoxLayout()
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(catalog.BRIGHTNESS_MIN, 100)
        self.slider.setSingleStep(5)
        self.slider.setPageStep(10)
        self.slider.setAccessibleName(_("Brightness"))
        self.bright_value = QLabel("—")
        self.bright_value.setMinimumWidth(44)
        self.bright_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bright.addWidget(self.slider, 1)
        bright.addWidget(self.bright_value)
        body.addLayout(bright)
        presets_host = QWidget()
        presets = FlowLayout(presets_host)
        self.preset_buttons = []
        for value in catalog.BRIGHTNESS_PRESETS:
            button = QPushButton(f"{value}%")
            button.setAccessibleName(_("Brightness {value}%").format(value=value))
            button.clicked.connect(lambda _c=False, v=value: owner.set_brightness(v))
            presets.addWidget(button)
            self.preset_buttons.append(button)
        self.power = QPushButton()
        self.power.clicked.connect(owner.toggle_power)
        presets.addWidget(self.power)
        body.addWidget(presets_host)
        self.bright_note = muted_label()
        body.addWidget(self.bright_note)
        self._slider_timer = QTimer(self)
        self._slider_timer.setSingleShot(True)
        self._slider_timer.setInterval(450)
        self._slider_timer.timeout.connect(lambda: owner.set_brightness(self.slider.value()))
        self.slider.valueChanged.connect(self._slider_moved)

        # Orientation.
        body.addWidget(section_label(_("Orientation")))
        orient_host = QWidget()
        orient_host.setStyleSheet(CHIP_STYLE)
        orient = FlowLayout(orient_host)
        self.orient_group = QButtonGroup(self)
        self.orient_buttons = {}
        for key, name in catalog.ORIENTATIONS:
            button = QPushButton(_(name))
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, k=key: owner.set_orientation(k))
            self.orient_group.addButton(button)
            self.orient_buttons[key] = button
            orient.addWidget(button)
        body.addWidget(orient_host)
        body.addStretch(1)

        self.settings_button = self.add_footer_button(_("Configuration…"), owner.open_configuration,
                                                      _("Open the complete configuration window"))
        self.service_button = self.add_footer_button(_("Restart Service"), owner.service_action)
        self.add_footer_stretch()
        self.autostart = self.add_session_option(_("Start with the session"),
                                                 autostart.is_enabled(owner.app_id), owner.set_autostart)
        self._syncing = False

    def _reflow(self, columns):
        """As many cards per row as fit the visible width (never clipped)."""
        if columns == self._columns:
            return
        self._columns = columns
        for index, theme in enumerate(catalog.THEMES):
            card = self.cards[theme.id]
            self.grid.removeWidget(card)
            self.grid.addWidget(card, index // columns, index % columns)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        card = next(iter(self.cards.values()))
        spacing = self.grid.spacing()
        margins = self.body.contentsMargins()
        width = self.scroll.viewport().width() - margins.left() - margins.right()
        self._reflow(max(1, min(4, (width + spacing) // (card.sizeHint().width() + spacing))))

    def _slider_moved(self, value):
        self.bright_value.setText(f"{value}%")
        if not self._syncing:
            self._slider_timer.start()

    def set_variants(self, theme, current, owner):
        for button in self.variant_buttons:
            self.variant_group.removeButton(button)
            button.deleteLater()
        self.variant_buttons = []
        has = bool(theme and theme.variants)
        self.variant_title.setVisible(has)
        self.variant_host.setVisible(has)
        if not has:
            return
        self.variant_title.setText(_("Colour scheme") if theme.key != "planet_accent" else _("Accent colour"))
        for variant in theme.variants:
            button = QPushButton(_(variant.name))
            button.setCheckable(True)
            button.setChecked(variant.id == current)
            button.clicked.connect(lambda _c=False, t=theme.id, v=variant.id: owner.choose_theme(t, v))
            self.variant_group.addButton(button)
            self.variant_buttons.append(button)
            self.variant_grid.addWidget(button)


class ScreenTray(TrayApp):
    app_id = "big-screen-monitor-tray"
    icon_name = "big-screen-monitor-tray"

    def __init__(self, app, autostarted=False):
        super().__init__(app, autostarted)
        self.target_id = ALL
        self.local = _load_state()
        self._menu_signature = None
        self._thumbs = None
        self._thumbs_pending = None
        self._thumb_keys = {}
        self.menu = QMenu()

    # ------------------------------------------------------------ build
    def build(self):
        autostart.migrate_legacy(self.app_id)
        self.window = ScreenWindow(self)
        self.window.target.currentIndexChanged.connect(self._target_changed)

    def tray_menu(self):
        return self.menu

    def tray_icon(self):
        return screen_icon(self._icon_state())

    # ------------------------------------------------------------ model
    def screens(self):
        return [entry for entry in self.status.displays if control.is_screen(entry)]

    def target_entries(self):
        screens = self.screens()
        if self.target_id:
            return [entry for entry in screens if entry.get("id") == self.target_id]
        return screens

    def effective(self):
        """Values the target uses: one display's merged settings, or the global ones."""
        if self.target_id:
            return control.effective(self.values, self.target_id)
        screens = self.screens()
        if len(screens) == 1:
            return control.effective(self.values, screens[0].get("id"))
        return dict(self.values)

    def _icon_state(self):
        if not self.status.running:
            return "error" if self.status.state == "stale" else "off"
        entries = self.target_entries()
        if not entries:
            return "off"
        kinds = [STATE_TEXT.get(entry.get("state"), ("warning", ""))[0] for entry in entries]
        return "error" if "error" in kinds else "warning" if "warning" in kinds else "ok"

    def _state_text(self):
        if self.status.state == "missing":
            return "off", _("Service not running")
        if self.status.state == "stale":
            return "error", _("Service stopped")
        entries = self.target_entries()
        if not entries:
            return "off", _("No display connected")
        if len(entries) == 1:
            kind, label = STATE_TEXT.get(entries[0].get("state"), ("warning", entries[0].get("state", "?")))
            return kind, _(label)
        kind = self._icon_state()
        return kind, _("{count} displays").format(count=len(entries))

    def brightness_supported(self):
        return any((entry.get("capabilities") or {}).get("brightness") for entry in self.target_entries())

    # ------------------------------------------------------------ status / settings
    def on_status(self, status):
        screens = self.screens()
        ids = [entry.get("id") for entry in screens]
        if self.target_id and self.target_id not in ids:
            self.target_id = ALL                      # unplugged: back to all displays
        if self.window is not None:
            combo = self.window.target
            wanted = [(ALL, _("All displays"))] + [(entry.get("id"), display_name(entry)) for entry in screens]
            current = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
            if current != wanted:
                combo.blockSignals(True)
                combo.clear()
                for value, text in wanted:
                    combo.addItem(text, value)
                combo.setCurrentIndex(max(0, combo.findData(self.target_id)))
                combo.blockSignals(False)
            self.window.target_row.setVisible(len(screens) > 1)
        self.sync()

    def on_settings(self, values):
        self.sync()

    def _target_changed(self, index):
        self.target_id = self.window.target.itemData(index) or ALL
        self.sync()

    def sync(self):
        """Window, menu, icon and tooltip from the status and the settings."""
        values = self.effective()
        kind, text = self._state_text()
        entries = self.target_entries()
        if self.window is not None:
            window = self.window
            window._syncing = True
            subtitle = display_name(entries[0]) if len(entries) == 1 else ""
            window.set_state(kind, text, subtitle)
            has_screen = bool(entries)
            if self.status.state != "running":
                window.empty.setText(_("The monitor service is not running, so nothing reaches the displays. "
                                       "Start it below (administrator authorization)."))
            elif not self.screens():
                window.empty.setText(_("Connect a USB display. It appears here a moment after it is plugged in; "
                                       "your choices below are kept and used when it connects."))
            else:
                window.empty.setText("")
            window.empty.setVisible(bool(window.empty.text()))
            theme_id = values.get("theme", "standard")
            for tid, card in window.cards.items():
                card.setChecked(tid == theme_id)
            theme = catalog.BY_ID.get(theme_id)
            window.set_variants(theme, theme.current_variant(values) if theme else "", self)
            window.more_note.setText(_("More options for this theme are in the configuration window.")
                                     if theme_id in ("kojiro", "big_media_player", "brother_away") else "")
            window.more_note.setVisible(bool(window.more_note.text()))
            brightness = int(values.get("brightness", 70))
            supported = self.brightness_supported() or not has_screen
            window.slider.setValue(max(catalog.BRIGHTNESS_MIN, brightness))
            window.bright_value.setText(f"{brightness}%" if brightness else _("Off"))
            for widget in [window.slider, window.power, *window.preset_buttons]:
                widget.setEnabled(supported)
            window.power.setText(_("Turn On") if brightness == 0 else _("Turn Off"))
            window.power.setToolTip(_("Switch the backlight off and on again; the theme keeps running."))
            window.bright_note.setText("" if supported else
                                       _("This display has no adjustable backlight (its firmware does not offer "
                                         "it)."))
            window.bright_note.setVisible(not supported)
            orientation = values.get("orientation", "horizontal")
            for key, button in window.orient_buttons.items():
                button.setChecked(key == orientation)
            window.service_button.setText(_("Start Service") if self.status.state != "running"
                                          else _("Restart Service"))
            window._syncing = False
            if window.isVisible():
                self.request_thumbnails()
        self.refresh_tray()
        self._rebuild_menu(values, kind, text)

    def refresh_tray(self):
        if self.tray is None:
            return
        self.tray.setIcon(screen_icon(self._icon_state()))
        values = self.effective()
        kind, text = self._state_text()
        theme = catalog.BY_ID.get(values.get("theme", "standard"))
        lines = [_("Big Screen Monitor"), text]
        if theme is not None:
            lines.append(_("Theme: {name}").format(name=_(theme.name)))
        if self.brightness_supported():
            lines.append(_("Brightness: {value}%").format(value=values.get("brightness", 70)))
        self.tray.setToolTip("\n".join(lines))

    # ------------------------------------------------------------ menu
    def _rebuild_menu(self, values, kind, text):
        theme_id = values.get("theme", "standard")
        signature = (kind, text, theme_id, tuple(values.get(t.key, "") for t in catalog.THEMES if t.key),
                     values.get("brightness"), values.get("orientation"), self.brightness_supported(),
                     self.status.state, autostart.is_enabled(self.app_id))
        if signature == self._menu_signature:
            return                       # rebuilding an open menu would close it
        self._menu_signature = signature
        menu = self.menu
        menu.clear()
        header = menu.addAction(text)
        header.setEnabled(False)
        menu.addSeparator()
        themes_menu = menu.addMenu(QIcon.fromTheme("preferences-desktop-theme"), _("Theme"))
        group = QActionGroup(themes_menu)
        for theme in catalog.THEMES:
            if theme.variants:
                sub = themes_menu.addMenu(_(theme.name))
                sub_group = QActionGroup(sub)
                current = theme.current_variant(values) if theme.id == theme_id else None
                for variant in theme.variants:
                    action = QAction(_(variant.name), sub, checkable=True)
                    action.setChecked(variant.id == current)
                    action.triggered.connect(lambda _c=False, t=theme.id, v=variant.id: self.choose_theme(t, v))
                    sub_group.addAction(action)
                    sub.addAction(action)
                if theme.id == theme_id:
                    sub.setIcon(QIcon.fromTheme("object-select-symbolic"))
            else:
                action = QAction(_(theme.name), themes_menu, checkable=True)
                action.setChecked(theme.id == theme_id)
                action.triggered.connect(lambda _c=False, t=theme.id: self.choose_theme(t))
                group.addAction(action)
                themes_menu.addAction(action)
        bright_menu = menu.addMenu(QIcon.fromTheme("display-brightness-symbolic"), _("Brightness"))
        bright_menu.setEnabled(self.brightness_supported())
        bright_group = QActionGroup(bright_menu)
        for value in catalog.BRIGHTNESS_PRESETS:
            action = QAction(f"{value}%", bright_menu, checkable=True)
            action.setChecked(values.get("brightness") == value)
            action.triggered.connect(lambda _c=False, v=value: self.set_brightness(v))
            bright_group.addAction(action)
            bright_menu.addAction(action)
        bright_menu.addSeparator()
        power = bright_menu.addAction(_("Turn On") if values.get("brightness") == 0 else _("Turn Off"))
        power.triggered.connect(self.toggle_power)
        orient_menu = menu.addMenu(QIcon.fromTheme("object-rotate-right-symbolic"), _("Orientation"))
        orient_group = QActionGroup(orient_menu)
        for key, name in catalog.ORIENTATIONS:
            action = QAction(_(name), orient_menu, checkable=True)
            action.setChecked(values.get("orientation") == key)
            action.triggered.connect(lambda _c=False, k=key: self.set_orientation(k))
            orient_group.addAction(action)
            orient_menu.addAction(action)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("view-grid-symbolic"), _("Theme Gallery…"), self.show_window)
        menu.addAction(QIcon.fromTheme("preferences-system-symbolic"), _("Configuration…"), self.open_configuration)
        menu.addAction(QIcon.fromTheme("view-refresh-symbolic"),
                       _("Start Service") if self.status.state != "running" else _("Restart Service"),
                       self.service_action)
        start = QAction(_("Start with the session"), menu, checkable=True)
        start.setChecked(autostart.is_enabled(self.app_id))
        start.toggled.connect(self.set_autostart)
        menu.addAction(start)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("application-exit-symbolic"), _("Quit"), self.quit)

    def set_autostart(self, enabled):
        super().set_autostart(enabled)
        if self.window is not None:
            self.window.autostart.blockSignals(True)
            self.window.autostart.setChecked(autostart.is_enabled(self.app_id))
            self.window.autostart.blockSignals(False)
        self._menu_signature = None
        self.sync()

    # ------------------------------------------------------------ changes
    def apply(self, updates):
        """Write ``updates`` for the target: one display, or every display."""
        values = self.values
        single = self.screens()[0].get("id") if not self.target_id and len(self.screens()) == 1 else None
        for key, value in updates.items():
            if self.target_id:
                values = control.set_display(values, self.target_id, key, value)
            else:
                values = control.set_global(values, key, value, clear_overrides=True)
        log.info("apply %s to %s", updates, self.target_id or single or "all displays")
        self.save(values, lambda ok, message: self.window and ok and message and
                  self.window.show_message(message))
        self.sync()

    def choose_theme(self, theme_id, variant_id=""):
        if not variant_id:
            theme = catalog.BY_ID[theme_id]
            current = self.effective()
            # Clicking the card of another theme keeps that theme's own variant.
            variant_id = theme.current_variant(current) if theme.variants else ""
        self.apply(catalog.theme_values(theme_id, variant_id))

    def set_brightness(self, value):
        value = int(value)
        if value and value < catalog.BRIGHTNESS_MIN:
            value = catalog.BRIGHTNESS_MIN
        if value == self.effective().get("brightness"):
            return
        self.apply({"brightness": value})

    def toggle_power(self):
        key = self.target_id or "all"
        current = int(self.effective().get("brightness", 70))
        restore = self.local.setdefault("restore_brightness", {})
        if current > 0:
            restore[key] = current
            _save_state(self.local)
            self.apply({"brightness": 0})
        else:
            self.apply({"brightness": int(restore.get(key) or 70)})

    def set_orientation(self, orientation):
        if orientation != self.effective().get("orientation"):
            self.apply({"orientation": orientation})

    def service_action(self):
        if self.status.state == "running":
            self.restart_service()
            return

        def finished(result, error):
            ok, message = result if error is None else (False, str(error))
            if not ok:
                self.notify(_("Could not start the service"), message, error=True)
            self.poll(force=True)

        self.run_async(lambda: control.service("enable"), finished)

    # ------------------------------------------------------------ thumbnails
    def show_window(self, no_tray=False):
        super().show_window(no_tray)
        self.request_thumbnails()

    def _thumb_jobs(self):
        values = self.effective()
        entries = self.target_entries()
        size = display_size(entries[0], values.get("orientation", "horizontal")) if entries else (480, 320)
        theme_id = values.get("theme", "standard")
        jobs = []
        for theme in catalog.THEMES:
            variant = theme.current_variant(values) if theme.variants else ""
            jobs.append((theme.id, "", catalog.theme_values(theme.id, variant)))
        return size, jobs, theme_id

    def _key(self, theme_id, overrides, size):
        theme = catalog.BY_ID[theme_id]
        import fnmatch
        relevant = {k: v for k, v in dict(self.effective(), **overrides).items()
                    if k in ("language", "orientation") or any(fnmatch.fnmatch(k, p) for p in theme.preferences)}
        blob = json.dumps([__version__, theme_id, size, relevant], sort_keys=True, default=str)
        return hashlib.sha1(blob.encode()).hexdigest()[:16]

    def request_thumbnails(self):
        if self.window is None:
            return
        size, jobs, _theme = self._thumb_jobs()
        items = []
        for theme_id, _variant, overrides in jobs:
            key = self._key(theme_id, overrides, size)
            self._thumb_keys[key] = theme_id
            path = os.path.join(CACHE_DIR, f"{key}.png")
            if os.path.exists(path):
                self.window.cards[theme_id].set_picture(path)
            else:
                items.append({"key": key, "theme": theme_id, "values": overrides})
        if not items:
            return
        job = {"size": list(size), "out": CACHE_DIR, "items": items}
        if self._thumbs is not None:
            self._thumbs_pending = job                 # one renderer at a time; keep the latest request
            return
        self._start_thumbs(job)

    def _start_thumbs(self, job):
        process = QtCore.QProcess(self)
        environment = QtCore.QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONPATH", APP_DIR + os.pathsep + environment.value("PYTHONPATH", ""))
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(APP_DIR)
        process.readyReadStandardOutput.connect(lambda p=process: self._thumbs_output(p))
        process.finished.connect(lambda *_a, p=process: self._thumbs_finished(p))
        self._thumbs = process
        process.start(sys.executable, ["-m", "traykit.thumbs"])
        process.write(json.dumps(job).encode())
        process.closeWriteChannel()

    def _thumbs_output(self, process):
        while process.canReadLine():
            line = bytes(process.readLine()).decode("utf-8", "replace").strip()
            word, _sep, rest = line.partition(" ")
            key = rest.split(" ")[0]
            theme_id = self._thumb_keys.get(key)
            if word == "done" and theme_id and self.window is not None:
                self.window.cards[theme_id].set_picture(os.path.join(CACHE_DIR, f"{key}.png"))
            elif word == "fail":
                log.warning("thumbnail failed: %s", rest)

    def shutdown(self):
        super().shutdown()
        self._thumbs_pending = None
        process, self._thumbs = self._thumbs, None
        if process is not None:
            process.blockSignals(True)            # no callback on a half-destroyed app
            process.kill()
            process.waitForFinished(2000)
            process.deleteLater()

    def _thumbs_finished(self, process):
        self._thumbs_output(process)
        process.deleteLater()
        self._thumbs = None
        if self._thumbs_pending is not None:
            job, self._thumbs_pending = self._thumbs_pending, None
            self._start_thumbs(job)
