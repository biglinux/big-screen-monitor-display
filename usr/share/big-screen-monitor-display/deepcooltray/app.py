"""Tray app for the DeepCool digital coolers (AK, AG, LS, AK PRO, LD, MYSTIQUE).

The service drives the coolers; this app shows the CPU temperature and usage in
the tray (read here from one sysfs file and psutil, never invented), what the
cooler shows right now (from the service status), and edits the cooler's own
settings (``dc_*`` keys of that display, like the configuration window).
Options appear only for what the cooler's family really has.
"""

import json
import logging
import os
import time

import psutil

from bsmd import control, telemetry
from bsmd.displays.deepcool import models
from bsmd.displays.deepcool.metrics import PRESETS
from bsmd.i18n import N_, _

from traykit import autostart
from traykit.base import TrayApp
from traykit.icons import heat_colour, swatch_icon, value_icon
from traykit.qt import (QAction, QActionGroup, QButtonGroup, QColor, QColorDialog, QComboBox, QGridLayout,
                        QHBoxLayout, QLabel, QMenu, QPushButton, QIcon, QWidget, QtWidgets)
from traykit.window import PanelWindow, muted_label, section_label

from . import openrgb

log = logging.getLogger("bsmd.deepcooltray")
STATE_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                          "big-screen-monitor-display", "deepcool-tray.json")
LEGACY_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                           "deepcool-digital", "settings.json")
ALARM_CHOICES = (60, 65, 70, 75, 80, 85, 90, 95, 100)
METRICS_FRESH_FOR = 6.0
STATE_TEXT = {
    "healthy": ("ok", N_("Connected")),
    "degraded": ("warning", N_("Unstable connection")),
    "starting": ("warning", N_("Starting…")),
    "recovering": ("warning", N_("Reconnecting…")),
    "retrying": ("warning", N_("Reconnecting…")),
    "disconnected": ("error", N_("Disconnected")),
    "failed": ("error", N_("Not responding")),
}
COLOUR_NAMES = {"red": N_("Red"), "orange": N_("Orange"), "yellow": N_("Yellow"), "green": N_("Green"),
                "cyan": N_("Cyan"), "blue": N_("Blue"), "purple": N_("Purple"), "pink": N_("Pink"),
                "white": N_("White")}
CHIP_STYLE = """
QPushButton {
    border: 1px solid palette(mid);
    border-radius: 12px;
    padding: 3px 12px;
    background: palette(button);
}
QPushButton:hover { border-color: palette(highlight); }
QPushButton:checked { border: 2px solid palette(highlight); background: palette(alternate-base); font-weight: 600; }
QPushButton:disabled { color: palette(placeholder-text); }
"""


def to_unit(celsius, fahrenheit):
    return celsius * 9 / 5 + 32 if fahrenheit else celsius


def temperature_text(celsius, fahrenheit):
    if celsius is None:
        return "—"
    return f"{to_unit(celsius, fahrenheit):.0f} {'°F' if fahrenheit else '°C'}"


class CpuReader:
    """CPU temperature and usage, the way the service reads them (one sysfs file,
    psutil as fallback). ``None`` means not measured: never a made-up number."""

    def __init__(self):
        self.path = telemetry.find_cpu_temp_input()
        self.source = self.path or "psutil"
        psutil.cpu_percent(interval=None)                 # baseline for the next delta

    def temperature(self):
        if self.path:
            try:
                with open(self.path, encoding="ascii") as handle:
                    return int(handle.read().strip()) / 1000
            except (OSError, ValueError):
                self.path = None                           # sensor gone (driver reload): psutil from now on
        if hasattr(psutil, "sensors_temperatures"):
            try:
                return telemetry._cpu_temperature(psutil.sensors_temperatures())
            except (OSError, RuntimeError):
                return None
        return None

    @staticmethod
    def usage():
        try:
            return float(psutil.cpu_percent(interval=None))
        except (OSError, RuntimeError):
            return None


def load_local():
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    data = {}
    try:                                                   # first version (pull request #11): keep the colour
        with open(LEGACY_FILE, encoding="utf-8") as handle:
            legacy = json.load(handle)
        colour = legacy.get("led_color")
        if colour == "__rainbow__":
            colour = openrgb.RAINBOW
        elif colour in ("__off__", "off"):
            colour = openrgb.OFF
        if colour in (openrgb.RAINBOW, openrgb.OFF) or openrgb.HEX.match(str(colour or "")):
            data["openrgb"] = {"colour": colour}
    except (OSError, ValueError, AttributeError):
        pass
    return data


def save_local(data):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError as error:
        log.warning("could not save %s: %s", STATE_FILE, error)


def cooler_name(entry):
    device = entry.get("device") or {}
    return (entry.get("settings") or {}).get("name") or device.get("model") or entry.get("name") or "DeepCool"


class DeepCoolWindow(PanelWindow):
    def __init__(self, owner):
        super().__init__(_("DeepCool Digital"), owner.icon_name, owner)
        body = self.body
        self.target_row = QWidget()
        row = QHBoxLayout(self.target_row)
        row.setContentsMargins(0, 0, 0, 0)
        label = QLabel(_("Cooler"))
        self.target = QComboBox()
        self.target.setAccessibleName(_("Cooler that receives the changes"))
        label.setBuddy(self.target)
        row.addWidget(label)
        row.addWidget(self.target, 1)
        body.addWidget(self.target_row)
        self.empty = muted_label()
        body.addWidget(self.empty)

        # Now.
        body.addWidget(section_label(_("CPU now")))
        now = QHBoxLayout()
        self.temp = QLabel("—")
        self.usage = QLabel("—")
        for widget, name in ((self.temp, _("CPU temperature")), (self.usage, _("CPU usage"))):
            font = widget.font()
            font.setPointSizeF(font.pointSizeF() * 2.0)
            font.setBold(True)
            widget.setFont(font)
            widget.setAccessibleName(name)
            box = QtWidgets.QVBoxLayout()
            box.addWidget(widget)
            box.addWidget(muted_label(name))
            now.addLayout(box, 1)
        body.addLayout(now)
        self.on_cooler = muted_label()
        body.addWidget(self.on_cooler)

        # What the cooler shows.
        body.addWidget(section_label(_("The cooler shows")))
        self.mode_host = QWidget()
        self.mode_host.setStyleSheet(CHIP_STYLE)
        self.mode_grid = QGridLayout(self.mode_host)
        self.mode_grid.setContentsMargins(0, 0, 0, 0)
        self.mode_grid.setSpacing(6)
        body.addWidget(self.mode_host)
        self.mode_group = QButtonGroup(self)
        self.mode_buttons = {}
        self.mode_note = muted_label()
        body.addWidget(self.mode_note)

        # Unit.
        self.unit_title = section_label(_("Temperature unit"))
        body.addWidget(self.unit_title)
        self.unit_host = QWidget()
        self.unit_host.setStyleSheet(CHIP_STYLE)
        units = QHBoxLayout(self.unit_host)
        units.setContentsMargins(0, 0, 0, 0)
        self.unit_group = QButtonGroup(self)
        self.unit_buttons = {}
        for key, name in (("c", _("Celsius (°C)")), ("f", _("Fahrenheit (°F)"))):
            button = QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, k=key: owner.set_unit(k))
            self.unit_group.addButton(button)
            self.unit_buttons[key] = button
            units.addWidget(button)
        units.addStretch(1)
        body.addWidget(self.unit_host)
        self.unit_note = muted_label()
        body.addWidget(self.unit_note)

        # Alarm.
        body.addWidget(section_label(_("Temperature alarm")))
        alarm = QHBoxLayout()
        self.alarm = QComboBox()
        self.alarm.setAccessibleName(_("Temperature alarm"))
        self.alarm.addItem(_("Off"), 0)
        for value in ALARM_CHOICES:
            self.alarm.addItem(f"{value} °C", value)
        self.alarm.activated.connect(lambda index: owner.set_alarm(self.alarm.itemData(index)))
        alarm.addWidget(self.alarm)
        alarm.addStretch(1)
        body.addLayout(alarm)
        self.alarm_note = muted_label()
        body.addWidget(self.alarm_note)
        self.notify_alarm = QtWidgets.QCheckBox(_("Also warn on the desktop when the alarm lights up"))
        self.notify_alarm.toggled.connect(owner.set_notify_alarm)
        body.addWidget(self.notify_alarm)

        # LEDs (OpenRGB).
        body.addWidget(section_label(_("LED colour (OpenRGB)")))
        rgb = QHBoxLayout()
        self.rgb_device = QComboBox()
        self.rgb_device.setAccessibleName(_("OpenRGB device of the cooler's LEDs"))
        self.rgb_device.activated.connect(owner.rgb_device_chosen)
        self.rgb_find = QPushButton(_("Find Devices"))
        self.rgb_find.clicked.connect(owner.find_rgb_devices)
        rgb.addWidget(self.rgb_device, 1)
        rgb.addWidget(self.rgb_find)
        body.addLayout(rgb)
        self.rgb_host = QWidget()
        self.rgb_host.setStyleSheet(CHIP_STYLE)
        colours = QGridLayout(self.rgb_host)
        colours.setContentsMargins(0, 0, 0, 0)
        colours.setSpacing(6)
        self.rgb_group = QButtonGroup(self)
        self.rgb_buttons = {}
        items = [(hex_value, _(COLOUR_NAMES[name]), swatch_icon(hex_value)) for name, hex_value in openrgb.PRESETS]
        items += [(openrgb.RAINBOW, _("Rainbow"), swatch_icon(rainbow=True)),
                  (openrgb.OFF, _("Off"), swatch_icon(off=True))]
        for index, (value, name, icon) in enumerate(items):
            button = QPushButton(icon, name)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, v=value: owner.set_colour(v))
            self.rgb_group.addButton(button)
            self.rgb_buttons[value] = button
            colours.addWidget(button, index // 4, index % 4)
        custom = QPushButton(_("Other…"))
        custom.clicked.connect(owner.custom_colour)
        self.rgb_custom = custom
        colours.addWidget(custom, len(items) // 4, len(items) % 4)
        body.addWidget(self.rgb_host)
        self.rgb_note = muted_label()
        body.addWidget(self.rgb_note)
        body.addStretch(1)

        self.add_footer_button(_("Configuration…"), owner.open_configuration,
                               _("Open the complete configuration window"))
        self.reconnect_button = self.add_footer_button(_("Reconnect"), owner.reconnect_cooler,
                                                       _("Close and reopen this cooler only"))
        self.service_button = self.add_footer_button(_("Restart Service"), owner.service_action)
        self.add_footer_stretch()
        self.autostart = self.add_session_option(_("Start with the session"),
                                                 autostart.is_enabled(owner.app_id), owner.set_autostart)

    def set_modes(self, choices, current, owner):
        """Radio chips of what a single-field cooler shows (rebuilt only when they change)."""
        keys = [key for key, _label in choices]
        if keys != list(self.mode_buttons):
            for button in self.mode_buttons.values():
                self.mode_group.removeButton(button)
                button.deleteLater()
            self.mode_buttons = {}
            for index, (key, label) in enumerate(choices):
                button = QPushButton(label)
                button.setCheckable(True)
                button.clicked.connect(lambda _c=False, k=key: owner.set_mode(k))
                self.mode_group.addButton(button)
                self.mode_buttons[key] = button
                self.mode_grid.addWidget(button, index // 2, index % 2)
        self.mode_group.setExclusive(False)
        for key, button in self.mode_buttons.items():
            button.setChecked(key == current)
        self.mode_group.setExclusive(True)
        self.mode_host.setVisible(bool(choices))


class DeepCoolTray(TrayApp):
    app_id = "big-screen-monitor-deepcool"
    icon_name = "big-screen-monitor-deepcool"

    def __init__(self, app, autostarted=False):
        super().__init__(app, autostarted)
        self.cpu = CpuReader()
        self.temp_c = None
        self.usage = None
        self.target_id = ""
        self.local = load_local()
        self.local.setdefault("notify_alarm", True)
        self._alarm_lit = {}
        self._menu_signature = None
        self.rgb_devices = []
        self.menu = QMenu()

    # ------------------------------------------------------------ build
    def build(self):
        autostart.migrate_legacy(self.app_id)
        self.window = DeepCoolWindow(self)
        self.window.target.currentIndexChanged.connect(self._target_changed)
        self.window.notify_alarm.setChecked(bool(self.local.get("notify_alarm", True)))
        self._fill_rgb_combo()
        chosen = self.local.get("openrgb") or {}
        if chosen.get("device") and chosen.get("colour") and openrgb.available():
            # The LEDs forget their colour at power off: restore the user's choice, on that device only.
            self.run_async(lambda: openrgb.apply(chosen["colour"], chosen["device"], chosen.get("index")),
                           self._rgb_done)

    def tray_menu(self):
        return self.menu

    def tray_icon(self):
        return self._icon()

    # ------------------------------------------------------------ model
    def coolers(self):
        return [entry for entry in self.status.displays if control.is_deepcool(entry)]

    def target(self):
        coolers = self.coolers()
        for entry in coolers:
            if entry.get("id") == self.target_id:
                return entry
        return coolers[0] if coolers else None

    def family(self, entry=None):
        entry = entry or self.target()
        return models.FAMILIES.get(control.profile_of(entry)) if entry else None

    def own(self, entry=None):
        entry = entry or self.target()
        if not entry:
            return {}
        return dict((self.values.get("displays") or {}).get(entry.get("id")) or {})

    def effective(self, entry=None):
        entry = entry or self.target()
        return control.effective(self.values, entry.get("id")) if entry else dict(self.values)

    def fahrenheit(self):
        family = self.family()
        return bool(family and family.fahrenheit and self.effective().get("dc_temp_unit", "c") == "f")

    def alarm_threshold(self):
        family, values = self.family(), self.effective()
        if family and family.software_alarm and values.get("dc_alarm", True):
            return int(values.get("dc_alarm_temp", 90))
        return None

    def connection(self):
        """(pill kind, text) of the target cooler."""
        if self.status.state == "missing":
            return "off", _("Service not running")
        if self.status.state == "stale":
            return "error", _("Service stopped")
        entry = self.target()
        if entry is None:
            return "off", _("No cooler connected")
        kind, label = STATE_TEXT.get(entry.get("state"), ("warning", entry.get("state", "?")))
        return kind, _(label)

    def mode_choices(self, family):
        if not family or family.layout != "single":
            return []
        labels = {models.TEMP: _("Temperature"), models.USAGE: _("Usage"), models.POWER: _("Power")}
        choices = [("theme", _("Follow the theme"))]
        choices += [(metric, labels.get(metric, _(models.METRIC_LABELS[metric]))) for metric in family.main_choices]
        choices.append(("auto", _("Alternate")))
        return choices

    def current_mode(self):
        own = self.own()
        preset = own.get("dc_preset")
        if not preset:
            return "theme"
        if preset == "custom":
            return own.get("dc_main", "auto")
        return ""                           # another presentation, chosen in the configuration window

    # ------------------------------------------------------------ polling
    def poll(self, force=False):
        super().poll(force)
        self.temp_c = self.cpu.temperature()
        self.usage = self.cpu.usage()
        self.refresh_values()

    def on_status(self, status):
        coolers = self.coolers()
        ids = [entry.get("id") for entry in coolers]
        if self.target_id not in ids:
            self.target_id = ids[0] if ids else ""
        if self.window is not None:
            combo = self.window.target
            wanted = [(entry.get("id"), cooler_name(entry)) for entry in coolers]
            current = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
            if current != wanted:
                combo.blockSignals(True)
                combo.clear()
                for value, text in wanted:
                    combo.addItem(text, value)
                combo.setCurrentIndex(max(0, combo.findData(self.target_id)))
                combo.blockSignals(False)
            self.window.target_row.setVisible(len(coolers) > 1)
        self._watch_alarm(coolers)
        self.sync()

    def on_settings(self, values):
        self.sync()

    def _target_changed(self, index):
        self.target_id = self.window.target.itemData(index) or ""
        self.sync()

    def _watch_alarm(self, coolers):
        """Desktop warning when a cooler's alarm lamp lights up (the service's own decision)."""
        for entry in coolers:
            metrics = entry.get("metrics") or {}
            lit = bool(metrics.get("alarm")) and time.time() - (metrics.get("updated") or 0) < METRICS_FRESH_FOR
            was = self._alarm_lit.get(entry.get("id"), False)
            self._alarm_lit[entry.get("id")] = lit
            if lit and not was and self.local.get("notify_alarm", True):
                temp = (metrics.get("fields") or {}).get(models.TEMP)
                unit = "°F" if metrics.get("fahrenheit") else "°C"
                text = _("CPU at {value}: the alarm threshold of {name} was reached.").format(
                    value=f"{temp:.0f} {unit}" if temp is not None else "—", name=cooler_name(entry))
                self.notify(_("CPU temperature alarm"), text, error=True)

    # ------------------------------------------------------------ view
    def _icon(self):
        fahrenheit = self.fahrenheit()
        text = f"{to_unit(self.temp_c, fahrenheit):.0f}" if self.temp_c is not None else "--"
        kind, _text = self.connection()
        return value_icon(text, heat_colour(self.temp_c, self.alarm_threshold()),
                          connected=kind not in {"off", "error"})

    def refresh_values(self):
        """Numbers that change every poll: icon, tooltip and the 'now' labels."""
        fahrenheit = self.fahrenheit()
        temp = temperature_text(self.temp_c, fahrenheit)
        usage = f"{self.usage:.0f} %" if self.usage is not None else "—"
        kind, text = self.connection()
        entry = self.target()
        if self.tray is not None:
            self.tray.setIcon(self._icon())
            lines = [cooler_name(entry) if entry else _("DeepCool Digital"), text,
                     _("CPU: {temp} · {usage}").format(temp=temp, usage=usage)]
            if self.temp_c is None:
                lines.append(_("No CPU temperature sensor found"))
            self.tray.setToolTip("\n".join(lines))
        if self.window is not None:
            window = self.window
            window.temp.setText(temp)
            window.usage.setText(usage)
            window.temp.setToolTip(_("No CPU temperature sensor found (k10temp, coretemp or zenpower).")
                                   if self.temp_c is None else _("Read from {source}").format(source=self.cpu.source))
            window.on_cooler.setText(self._cooler_line(entry))
        if self._menu_values is not None:
            self._menu_values.setText(_("CPU: {temp} · {usage}").format(temp=temp, usage=usage))

    _menu_values = None

    def _cooler_line(self, entry):
        if entry is None:
            return ""
        metrics = entry.get("metrics") or {}
        if not metrics or time.time() - (metrics.get("updated") or 0) > METRICS_FRESH_FOR:
            return _("Waiting for the cooler's first update…") if entry.get("state") == "healthy" else ""
        unit = {models.TEMP: "°F" if metrics.get("fahrenheit") else "°C", models.GPU_TEMP: "°C"}
        parts = []
        for metric, value in (metrics.get("fields") or {}).items():
            label = _(models.METRIC_LABELS.get(metric, metric))
            if value is None:
                reason = (metrics.get("reasons") or {}).get(metric)
                parts.append(f"{label}: — ({_(reason)})" if reason else f"{label}: —")
            else:
                parts.append(f"{label}: {value:g} {unit.get(metric, models.METRIC_UNITS.get(metric, ''))}".strip())
        line = _("On the cooler: {values}").format(values=" · ".join(parts)) if parts else ""
        if metrics.get("alarm"):
            line += "\n" + _("The alarm lamp is lit.")
        return line

    def sync(self):
        entry = self.target()
        family = self.family(entry)
        values = self.effective(entry)
        kind, text = self.connection()
        if self.window is not None:
            window = self.window
            window.set_state(kind, text, cooler_name(entry) if entry else "")
            if self.status.state != "running":
                window.empty.setText(_("The monitor service is not running, so nothing reaches the cooler. Start "
                                       "it below (administrator authorization)."))
            elif entry is None:
                window.empty.setText(_("Connect a DeepCool digital cooler (its USB cable goes to an internal USB "
                                       "header). It appears here a moment after the service finds it."))
            else:
                window.empty.setText("")
            window.empty.setVisible(bool(window.empty.text()))
            enabled = entry is not None
            choices = self.mode_choices(family)
            window.set_modes(choices, self.current_mode(), self)
            window.mode_host.setEnabled(enabled)
            if family and family.layout != "single":
                window.mode_note.setText(_("This cooler always shows {fields}; its firmware decides the layout.")
                                         .format(fields=", ".join(_(models.METRIC_LABELS[m]) for m in family.fields)))
            elif family and not self.current_mode():
                preset = self.own(entry).get("dc_preset")
                window.mode_note.setText(_("Presentation chosen in the configuration window: {name}.").format(
                    name=_(PRESETS[preset][0]) if preset in PRESETS else preset))
            elif family:
                window.mode_note.setText(_("“Follow the theme” lets the screen theme choose what fits."))
            else:
                window.mode_note.setText("")
            window.mode_note.setVisible(bool(window.mode_note.text()))
            unit_ok = bool(family and family.fahrenheit)
            window.unit_host.setVisible(unit_ok or family is None)
            window.unit_host.setEnabled(enabled and unit_ok)
            for key, button in window.unit_buttons.items():
                button.setChecked(values.get("dc_temp_unit", "c") == key)
            window.unit_note.setText(_("This cooler shows Celsius only.") if family and not family.fahrenheit else "")
            window.unit_note.setVisible(bool(window.unit_note.text()))
            software = bool(family and family.software_alarm)
            window.alarm.setEnabled(enabled and software)
            threshold = self.alarm_threshold()
            window.alarm.setCurrentIndex(max(0, window.alarm.findData(threshold or 0)))
            if family and family.firmware_alarm:
                window.alarm_note.setText(_("Built into the cooler: {limits}. It stays active and is never changed "
                                            "by this program.").format(limits=_(family.firmware_alarm)))
            elif family and not software:
                window.alarm_note.setText(_("This cooler has no alarm indicator."))
            else:
                window.alarm_note.setText("")
            window.alarm_note.setVisible(bool(window.alarm_note.text()))
            window.reconnect_button.setEnabled(enabled and self.status.running)
            window.service_button.setText(_("Start Service") if self.status.state != "running"
                                          else _("Restart Service"))
            self._sync_rgb()
        self.refresh_values()
        self._rebuild_menu(entry, family, values, kind, text)

    # ------------------------------------------------------------ menu
    def _rebuild_menu(self, entry, family, values, kind, text):
        rgb = self.local.get("openrgb") or {}
        signature = (entry.get("id") if entry else None, kind, text, family.id if family else None,
                     self.current_mode(), values.get("dc_temp_unit"), self.alarm_threshold(),
                     rgb.get("device"), rgb.get("colour"), self.status.state, autostart.is_enabled(self.app_id))
        if signature == self._menu_signature:
            return                       # rebuilding an open menu would close it
        self._menu_signature = signature
        menu = self.menu
        menu.clear()
        header = menu.addAction(f"{cooler_name(entry)} · {text}" if entry else text)
        header.setEnabled(False)
        self._menu_values = menu.addAction("")
        self._menu_values.setEnabled(False)
        menu.addSeparator()
        choices = self.mode_choices(family)
        if choices:
            sub = menu.addMenu(_("The cooler shows"))
            group = QActionGroup(sub)
            for key, label in choices:
                action = QAction(label, sub, checkable=True)
                action.setChecked(key == self.current_mode())
                action.triggered.connect(lambda _c=False, k=key: self.set_mode(k))
                group.addAction(action)
                sub.addAction(action)
        if family and family.fahrenheit:
            sub = menu.addMenu(_("Temperature unit"))
            group = QActionGroup(sub)
            for key, label in (("c", _("Celsius (°C)")), ("f", _("Fahrenheit (°F)"))):
                action = QAction(label, sub, checkable=True)
                action.setChecked(values.get("dc_temp_unit", "c") == key)
                action.triggered.connect(lambda _c=False, k=key: self.set_unit(k))
                group.addAction(action)
                sub.addAction(action)
        if family and family.software_alarm:
            sub = menu.addMenu(_("Temperature alarm"))
            group = QActionGroup(sub)
            threshold = self.alarm_threshold()
            for value in (0, *ALARM_CHOICES):
                action = QAction(_("Off") if not value else f"{value} °C", sub, checkable=True)
                action.setChecked((threshold or 0) == value)
                action.triggered.connect(lambda _c=False, v=value: self.set_alarm(v))
                group.addAction(action)
                sub.addAction(action)
        if rgb.get("device") and openrgb.available():
            sub = menu.addMenu(_("LED colour"))
            group = QActionGroup(sub)
            entries = [(v, _(COLOUR_NAMES[n]), swatch_icon(v)) for n, v in openrgb.PRESETS]
            entries += [(openrgb.RAINBOW, _("Rainbow"), swatch_icon(rainbow=True)),
                        (openrgb.OFF, _("Off"), swatch_icon(off=True))]
            for value, label, icon in entries:
                action = QAction(icon, label, sub, checkable=True)
                action.setChecked(str(rgb.get("colour", "")).upper() == value.upper())
                action.triggered.connect(lambda _c=False, v=value: self.set_colour(v))
                group.addAction(action)
                sub.addAction(action)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("preferences-other-symbolic"), _("Controls…"), self.show_window)
        menu.addAction(QIcon.fromTheme("preferences-system-symbolic"), _("Configuration…"), self.open_configuration)
        if entry is not None and self.status.running:
            menu.addAction(QIcon.fromTheme("view-refresh-symbolic"), _("Reconnect the Cooler"), self.reconnect_cooler)
        menu.addAction(_("Start Service") if self.status.state != "running" else _("Restart Service"),
                       self.service_action)
        start = QAction(_("Start with the session"), menu, checkable=True)
        start.setChecked(autostart.is_enabled(self.app_id))
        start.toggled.connect(self.set_autostart)
        menu.addAction(start)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("application-exit-symbolic"), _("Quit"), self.quit)
        self.refresh_values()

    # ------------------------------------------------------------ changes (dc_* of the target cooler)
    def _apply(self, updates):
        entry = self.target()
        if entry is None:
            return
        values = self.values
        for key, value in updates.items():
            values = control.set_display(values, entry.get("id"), key, value)
        log.info("apply %s to %s", updates, entry.get("id"))
        self.save(values)
        self.sync()

    def set_mode(self, mode):
        if mode == "theme":
            self._apply({"dc_preset": None, "dc_main": None})
        elif mode == "auto":
            self._apply({"dc_preset": "custom", "dc_main": None})
        else:
            self._apply({"dc_preset": "custom", "dc_main": mode})

    def set_unit(self, unit):
        self._apply({"dc_temp_unit": None if unit == "c" else unit})

    def set_alarm(self, value):
        if not value:
            self._apply({"dc_alarm": False})
        else:
            self._apply({"dc_alarm": None, "dc_alarm_temp": None if int(value) == 90 else int(value)})

    def set_notify_alarm(self, enabled):
        self.local["notify_alarm"] = bool(enabled)
        save_local(self.local)

    def set_autostart(self, enabled):
        super().set_autostart(enabled)
        if self.window is not None:
            self.window.autostart.blockSignals(True)
            self.window.autostart.setChecked(autostart.is_enabled(self.app_id))
            self.window.autostart.blockSignals(False)
        self._menu_signature = None
        self.sync()

    def reconnect_cooler(self):
        entry = self.target()
        if entry is not None:
            self.reconnect(entry.get("id"))

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

    # ------------------------------------------------------------ OpenRGB
    def _fill_rgb_combo(self):
        combo = self.window.rgb_device
        chosen = (self.local.get("openrgb") or {}).get("device")
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_("No device (LEDs untouched)"), None)
        names = [device.name for device in self.rgb_devices]
        if chosen and chosen not in names:
            names.insert(0, chosen)
        for name in names:
            combo.addItem(name, name)
        combo.setCurrentIndex(max(0, combo.findData(chosen)) if chosen else 0)
        combo.blockSignals(False)

    def _sync_rgb(self):
        window = self.window
        present = openrgb.available()
        rgb = self.local.get("openrgb") or {}
        for widget in (window.rgb_device, window.rgb_find):
            widget.setEnabled(present)
        window.rgb_host.setEnabled(present and bool(rgb.get("device")))
        colour = str(rgb.get("colour", ""))
        window.rgb_group.setExclusive(False)
        for value, button in window.rgb_buttons.items():
            button.setChecked(colour.upper() == value.upper())
        window.rgb_group.setExclusive(True)
        if not present:
            from bsmd import distro
            hint = distro.install_hint("openrgb")
            window.rgb_note.setText(_("The cooler's LED strip is wired to the motherboard and is controlled with "
                                      "OpenRGB, which is not installed.") + (f" ({hint})" if hint else ""))
        elif not rgb.get("device"):
            window.rgb_note.setText(_("Choose the OpenRGB device the cooler's LED cable is connected to (usually "
                                      "the motherboard). No other device is ever changed."))
        else:
            window.rgb_note.setText("")
        window.rgb_note.setVisible(bool(window.rgb_note.text()))

    def find_rgb_devices(self):
        self.window.rgb_find.setEnabled(False)

        def finished(result, error):
            self.window.rgb_find.setEnabled(True)
            self.rgb_devices = result or []
            self._fill_rgb_combo()
            if not self.rgb_devices:
                self.notify(_("No OpenRGB device found"),
                            _("Check that OpenRGB sees your motherboard (it may need its i2c/SMBus setup)."),
                            error=True)

        self.run_async(openrgb.list_devices, finished)

    def rgb_device_chosen(self, index):
        name = self.window.rgb_device.itemData(index)
        rgb = dict(self.local.get("openrgb") or {})
        if name:
            match = [d for d in self.rgb_devices if d.name == name]
            rgb.update(device=name, index=match[0].index if match else rgb.get("index"))
        else:
            rgb.pop("device", None)
            rgb.pop("index", None)
        self.local["openrgb"] = rgb
        save_local(self.local)
        self._menu_signature = None
        self.sync()

    def set_colour(self, colour):
        rgb = dict(self.local.get("openrgb") or {})
        if not rgb.get("device"):
            return
        rgb["colour"] = colour
        self.local["openrgb"] = rgb
        save_local(self.local)
        self.run_async(lambda: openrgb.apply(colour, rgb["device"], rgb.get("index")), self._rgb_done)
        self._menu_signature = None
        self.sync()

    def custom_colour(self):
        current = str((self.local.get("openrgb") or {}).get("colour", "#00CCCC"))
        colour = QColorDialog.getColor(QColor(current if openrgb.HEX.match(current) else "#00CCCC"), self.window,
                                       _("LED colour"))
        if colour.isValid():
            self.set_colour(colour.name().upper())

    def _rgb_done(self, result, error):
        ok, message = result if error is None and result else (False, str(error or ""))
        if not ok:
            self.notify(_("Could not change the LED colour"), message, error=True)

