"""Tray apps seen from outside, without Qt (the GTK configuration window uses it).

* each tray app listens on ``$XDG_RUNTIME_DIR/<app id>.sock`` (one instance per
  user); ``show`` raises its window and ``quit`` ends it;
* whether the desktop has a status notifier host (the tray), and what to tell
  the user when it has not.
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile

from bsmd.i18n import N_, _

from . import autostart

SCREEN = "big-screen-monitor-tray"
DEEPCOOL = "big-screen-monitor-deepcool"
APPS = {
    SCREEN: (N_("USB displays"), N_("Theme gallery, brightness and orientation from an icon in the panel."),
             "screentray"),
    DEEPCOOL: (N_("DeepCool coolers"), N_("CPU temperature in the panel and the cooler's display options."),
               "deepcooltray"),
}
WATCHER = "org.kde.StatusNotifierWatcher"


def runtime_dir():
    path = os.environ.get("XDG_RUNTIME_DIR")
    if path and os.path.isdir(path):
        return path
    return tempfile.gettempdir()


def socket_path(app_id):
    return os.path.join(runtime_dir(), f"{app_id}-{os.getuid()}.sock")


def send(app_id, command, timeout=0.5):
    """Send ``show`` or ``quit`` to the running instance. True when one answered."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(timeout)
            client.connect(socket_path(app_id))
            client.sendall(command.encode() + b"\n")
        return True
    except OSError:
        return False


def running(app_id):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            client.connect(socket_path(app_id))
        return True
    except OSError:
        return False


def command(app_id):
    """Command line that starts a tray app (installed launcher, else the source tree)."""
    installed = shutil.which(app_id)
    if installed:
        return [installed]
    package = APPS[app_id][2]
    main = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), package, "main.py")
    return [sys.executable, main]


def start(app_id):
    """Start the tray app in the background (tray icon only: ``--autostart``)."""
    try:
        subprocess.Popen(command(app_id) + ["--autostart"], start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def qt_available():
    import importlib.util
    return any(importlib.util.find_spec(name) is not None for name in ("PyQt6", "PyQt5"))


def tray_host_available():
    """True when a status notifier host (system tray) is registered on the session bus,
    False when there is none, None when that cannot be told (no session bus)."""
    try:
        result = subprocess.run(["busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                                 "org.freedesktop.DBus", "NameHasOwner", "s", WATCHER],
                                capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip().endswith("true")


def desktop_name():
    return (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()


def host_hint(in_window=True):
    """Why there is no tray icon on this desktop, and what to do (translated)."""
    desktop = desktop_name()
    if "gnome" in desktop or "ubuntu" in desktop:
        return _("GNOME shows tray icons only with the “AppIndicator and KStatusNotifierItem Support” "
                 "extension. Install it from your distribution (gnome-shell-extension-appindicator) or from "
                 "extensions.gnome.org and enable it in Extensions; the icon then appears the next time you "
                 "open this app.")
    if "windowmaker" in desktop or "wlmaker" in desktop:
        return _("Window Maker has no notification area: open the controls from the applications menu or a Dock "
                 "icon whenever you need them; the display keeps working without it.")
    if in_window:
        return _("This desktop has no notification area (system tray) running, so the controls are shown in this "
                 "window. Add a system tray to your panel to get the icon.")
    return _("This desktop has no notification area (system tray) running. Add a system tray to your panel to "
             "get the icon; meanwhile the controls open in a window from the applications menu.")


# ------------------------------------------------------------------ window open

OFFER_KEY = "tray_offer_done"


def kinds_present(status):
    """Tray apps that match the displays the service reports."""
    from bsmd import control
    present = set()
    for entry in (status or {}).get("displays") or []:
        if not isinstance(entry, dict):
            continue
        if control.is_deepcool(entry):
            present.add(DEEPCOOL)
        elif control.is_screen(entry):
            present.add(SCREEN)
    return present


def ensure_trays(status, load_settings, save_settings, notify):
    """When the configuration window opens: start the tray apps that are switched
    on but not running and, once, switch on the tray of the connected devices on a
    desktop that has a tray. ``BSM_NO_TRAY_START`` disables it (tests)."""
    if os.environ.get("BSM_NO_TRAY_START") or not qt_available():
        return []
    host = tray_host_available()
    if host is False:
        return []                          # nothing to show them in; Preferences explains why
    switched_on = []
    present = kinds_present(status)
    data = load_settings()
    if host and present and not data.get(OFFER_KEY):
        for app_id in sorted(present):
            if not autostart.is_enabled(app_id):
                try:
                    autostart.enable(app_id)
                    switched_on.append(app_id)
                except OSError:
                    pass
        data[OFFER_KEY] = True
        save_settings(data)
    for app_id in APPS:
        if autostart.is_enabled(app_id) and not running(app_id):
            start(app_id)
    if switched_on:
        notify(_("Tray icon turned on. You can switch it off in Preferences."))
    return switched_on
