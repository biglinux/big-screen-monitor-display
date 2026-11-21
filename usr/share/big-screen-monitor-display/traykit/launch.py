"""Start a tray app, or explain clearly why it cannot start.

Imported before any Qt module: when neither PyQt6 nor PyQt5 is installed the
user gets a window (GTK 4 is always present, it runs the configuration window)
naming the package for this distribution, instead of a silent failure.
"""

import os
import sys


def _missing_qt(title):
    from bsmd import distro
    from bsmd.i18n import _
    hint = distro.install_hint("pyqt") or "PyQt6"
    message = _("{title} needs the Qt bindings for Python (PyQt6 or PyQt5).").format(title=title) + "\n\n" + \
        _("Install them with:") + f"\n{hint}"
    print(message, file=sys.stderr)
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk
        if not Gtk.init_check():
            return
        loop = GLib.MainLoop()
        dialog = Gtk.AlertDialog(message=title, detail=message, buttons=[_("Close")])
        dialog.choose(None, None, lambda *_a: loop.quit())
        loop.run()
    except Exception:  # noqa: BLE001 - no usable GTK: the terminal message above is enough
        pass


def main(module, class_name, title):
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)
    try:
        from traykit import qt  # noqa: F401
    except ImportError:
        _missing_qt(title)
        return 2
    import importlib
    from traykit.base import run
    return run(getattr(importlib.import_module(module), class_name))
