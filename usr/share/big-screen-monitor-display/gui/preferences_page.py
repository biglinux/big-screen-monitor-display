"""Preferences section: startup, window appearance, language, feedback,
restore defaults and about.

The window style (follow the desktop / light / dark) is a preference of
this window only, kept in ``$XDG_CONFIG_HOME/big-screen-monitor-display/gui.json``
(user-writable, no password); everything else lives in the system settings.
"""

import json
import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from bsmd import __version__  # noqa: E402
from bsmd.i18n import _  # noqa: E402

from . import components as ui  # noqa: E402

STYLES = (("system", Adw.ColorScheme.DEFAULT), ("light", Adw.ColorScheme.FORCE_LIGHT),
          ("dark", Adw.ColorScheme.FORCE_DARK))


def gui_settings_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "big-screen-monitor-display", "gui.json")


def load_gui_settings():
    try:
        with open(gui_settings_path(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_gui_settings(data):
    path = gui_settings_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def apply_style(style):
    scheme = dict(STYLES).get(style, Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)


class PreferencesPage:
    def __init__(self, window):
        self.window = window
        w = window

        startup = Adw.PreferencesGroup(title=_("Startup"))
        startup.add(w.startup_row)
        page_items = [startup]

        look = Adw.PreferencesGroup(title=_("Appearance"),
                                    description=_("Only this window. The display themes have their own colours."))
        self.style_row = Adw.ComboRow(title=_("Style"),
                                      model=Gtk.StringList.new([_("Follow the system"), _("Light"), _("Dark")]))
        current = load_gui_settings().get("style", "system")
        keys = [key for key, _scheme in STYLES]
        self.style_row.set_selected(keys.index(current) if current in keys else 0)
        self.style_row.connect("notify::selected", self._on_style)
        look.add(self.style_row)
        look.add(w._combo("language", _("Language"), [("auto", _("As the system")), ("pt", "Português (Brasil)"),
                                                      ("en", "English")],
                          _("Used by the display themes; the window follows the system after a restart.")))
        page_items.append(look)

        feedback = Adw.PreferencesGroup(title=_("Feedback"))
        feedback.add(w._switch("ui_sound_feedback", _("Sound after applying"),
                               _("Plays a short system sound when settings are applied.")))
        page_items.append(feedback)

        keys_group = Adw.PreferencesGroup(title=_("Keyboard shortcuts"))
        for accel, text in (("Ctrl+S", _("Apply the changes")), ("Ctrl+F", _("Search the theme gallery")),
                            ("Ctrl+1 … Ctrl+9", _("Go to a section")), ("Alt+←", _("Back")),
                            ("Ctrl+Q", _("Quit"))):
            row = Adw.ActionRow(title=text)
            shortcut = Gtk.Label(label=accel, valign=Gtk.Align.CENTER)
            shortcut.add_css_class("dim-label")
            shortcut.add_css_class("numeric")
            row.add_suffix(shortcut)
            keys_group.add(row)
        page_items.append(keys_group)

        reset = Adw.PreferencesGroup(title=_("Reset"))
        restore = Adw.ActionRow(title=_("Restore defaults"),
                                subtitle=_("Every theme, display and performance option goes back to its original "
                                           "value. Nothing changes on the displays until you press Apply."),
                                activatable=True)
        button = Gtk.Button(label=_("Restore…"), valign=Gtk.Align.CENTER)
        button.add_css_class("destructive-action")
        button.connect("clicked", lambda _b: w._confirm_restore())
        restore.add_suffix(button)
        restore.set_activatable_widget(button)
        reset.add(restore)
        page_items.append(reset)

        about = Adw.PreferencesGroup(title=_("About"))
        version = Adw.ActionRow(title=_("Big Screen Monitor Display"), subtitle=_("Version {version}").format(
            version=__version__))
        details = Gtk.Button(label=_("About…"), valign=Gtk.Align.CENTER)
        details.connect("clicked", lambda _b: w.get_application().activate_action("about", None))
        version.add_suffix(details)
        about.add(version)
        page_items.append(about)

        content = ui.page_layout(*page_items, maximum=760)
        self.page = ui.navigation_page(_("Preferences"), content, tag="preferences")

    def _on_style(self, row, _pspec):
        style = STYLES[row.get_selected()][0]
        apply_style(style)
        data = load_gui_settings()
        data["style"] = style
        save_gui_settings(data)
