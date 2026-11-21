"""System tray switches of the Preferences section, and the tray start when the
window opens.

A switch on = the tray app starts now and with every session (XDG autostart
entry, the same one the tray's own "Start with the session" writes); off = the
running tray app ends and the entry is removed. Nothing here imports Qt.

When the window opens, a tray app that is switched on but not running is
started; the first time, on a desktop that has a tray, the tray matching the
connected devices is switched on and the user is told where to change it.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from bsmd import distro  # noqa: E402
from bsmd.i18n import _  # noqa: E402
from traykit import autostart, session  # noqa: E402


def ensure_running(window, load_gui_settings, save_gui_settings):
    """On window open (GLib timeout): start the switched-on tray apps; offer them once."""
    session.ensure_trays(window.status, load_gui_settings, save_gui_settings, window.toast)
    # The Preferences page may already be built (opened with --page preferences, or
    # visited in the first seconds): show what was just switched on and started.
    page = getattr(window, "preferences_page", None)
    if page is not None:
        page.trays.refresh()
        for delay in (1500, 4000):
            GLib.timeout_add(delay, page.trays.refresh)
    return False


class TrayGroup:
    """Preferences group: one switch per tray app, with its state and the reason
    when it cannot work on this desktop."""

    def __init__(self, window):
        self.window = window
        self.group = Adw.PreferencesGroup(
            title=_("System tray"),
            description=_("Quick controls from an icon in the panel. A tray that is on also starts with the "
                          "session."))
        self.note = Adw.ActionRow()
        self.note.add_css_class("property")
        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        self.note.add_prefix(icon)
        self.note.set_subtitle_lines(0)
        self.group.add(self.note)
        self.rows = {}         # app id -> Gtk.Switch
        self.lines = {}        # app id -> Adw.ActionRow
        self.states = {}
        for app_id, (title, subtitle, _package) in session.APPS.items():
            # The state label goes before the switch, so the switches stay aligned.
            row = Adw.ActionRow(title=_(title), subtitle=_(subtitle))
            state = Gtk.Label(valign=Gtk.Align.CENTER)
            state.add_css_class("dim-label")
            row.add_suffix(state)
            switch = Gtk.Switch(valign=Gtk.Align.CENTER, active=autostart.is_enabled(app_id))
            switch.update_property([Gtk.AccessibleProperty.LABEL], [_(title)])
            row.add_suffix(switch)
            row.set_activatable_widget(switch)
            switch.connect("notify::active", self._toggled, app_id)
            self.group.add(row)
            self.lines[app_id] = row
            self.rows[app_id] = switch
            self.states[app_id] = state
        self._updating = False
        self.refresh()

    def refresh(self):
        qt = session.qt_available()
        host = session.tray_host_available() if qt else None
        if not qt:
            hint = distro.install_hint("pyqt")
            self.note.set_title(_("The tray apps need the Qt bindings for Python (PyQt6 or PyQt5)."))
            self.note.set_subtitle(_("Install them with: {command}").format(command=hint) if hint else "PyQt6")
        elif host is False:
            self.note.set_title(_("This desktop shows no tray icons right now"))
            self.note.set_subtitle(session.host_hint(in_window=False))
        self.note.set_visible(not qt or host is False)
        self._updating = True
        for app_id, row in self.rows.items():
            self.lines[app_id].set_sensitive(qt)
            row.set_active(autostart.is_enabled(app_id))
            alive = session.running(app_id)
            self.states[app_id].set_label(_("Running") if alive else "")
        self._updating = False
        return False

    def _toggled(self, row, _pspec, app_id):
        if self._updating:
            return
        try:
            if row.get_active():
                autostart.enable(app_id)
                if not session.running(app_id):
                    session.start(app_id)
                if session.tray_host_available() is False:
                    self.window.toast(_("Switched on; this desktop has no tray to show the icon."))
            else:
                autostart.disable(app_id)
                session.send(app_id, "quit")
        except OSError as error:
            self.window.toast(str(error))
        # The app needs a moment to start (or to end) before its state is right.
        for delay in (1500, 4000):
            GLib.timeout_add(delay, self.refresh)
