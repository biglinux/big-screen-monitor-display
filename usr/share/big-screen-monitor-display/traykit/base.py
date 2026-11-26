"""Common machinery of the tray apps (DeepCool and USB screens).

* one instance per user: launching again shows the running instance's window;
* the status notifier icon when the desktop has a tray host (KDE Plasma, XFCE,
  Cinnamon, GNOME with the AppIndicator extension...), and otherwise the same
  controls in an ordinary window that says why there is no icon, so the app is
  never running without a way to reach it;
* the service and the settings followed by a cheap ``stat()`` every two seconds
  (the service itself watches USB hot-plug through udev and rewrites its
  status, so the tray never opens the devices and never competes with it);
* slow work (pkexec, OpenRGB) off the GUI thread.
"""

import functools
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from bsmd import control, i18n, settings
from bsmd.i18n import _

from . import autostart
from .session import desktop_name, host_hint, socket_path
from .qt import (QApplication, QIcon, QLocalServer, QLocalSocket, QObject, QSystemTrayIcon, QTimer, Signal,
                 exec_app)

POLL_MS = 2000
# Autostart: give the panel this long to bring its tray host up before giving up.
HOST_WAIT_S = 45
log = logging.getLogger("bsmd.tray")


def setup_logging(name):
    """Log to stderr (the session journal) and to a small rotating file."""
    handlers = [logging.StreamHandler()]
    try:
        directory = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                                 "big-screen-monitor-display")
        os.makedirs(directory, exist_ok=True)
        handlers.append(RotatingFileHandler(os.path.join(directory, f"{name}.log"), maxBytes=256 * 1024,
                                            backupCount=1, encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s",
                        handlers=handlers)


class _Bridge(QObject):
    done = Signal(object, object, object)   # callback, result, error


class TrayApp(QObject):
    """Base class: subclasses build ``self.window`` and the menu, and react to
    ``on_status`` / ``on_settings``."""

    app_id = "big-screen-monitor-tray"         # desktop file id, instance name, log name
    icon_name = "big-screen-monitor-tray"

    def __init__(self, app, autostarted=False):
        super().__init__()
        self.app = app
        self.autostarted = autostarted
        self.window = None
        self.tray = None
        self.status = control.ServiceStatus(None, None)
        self.values = control.load_settings()
        i18n.set_language(self.values.get("language", "auto"))
        self._status_mtime = None
        self._settings_mtime = self._mtime(settings.config_path())
        self._bridge = _Bridge()
        self._bridge.done.connect(self._deliver)
        self._busy = 0
        self._saving = False
        self._save_pending = None
        self._host_deadline = time.monotonic() + (HOST_WAIT_S if autostarted else 0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self.build()
        self.poll(force=True)
        self.timer.start(POLL_MS)
        self._ensure_presence()

    def build(self):
        raise NotImplementedError

    def tray_menu(self):
        raise NotImplementedError

    def tray_icon(self):
        return QIcon.fromTheme(self.icon_name)

    def _ensure_presence(self):
        """Tray icon when there is a host; else the window (never invisible)."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._make_tray()
            return
        if self.autostarted and time.monotonic() < self._host_deadline:
            QTimer.singleShot(3000, self._ensure_presence)      # the panel may still be starting
            return
        if self.autostarted:
            # Started with the session on a desktop without a tray host: do not
            # pop a window at every login, and do not stay running unreachable.
            log.info("no system tray host on %r: autostart instance exits", desktop_name())
            self.app.quit()
            return
        log.info("no system tray host on %r: showing the window", desktop_name())
        self.show_window(no_tray=True)

    def _make_tray(self):
        if self.tray is not None:
            return
        self.tray = QSystemTrayIcon(self.tray_icon(), self)
        self.tray.setContextMenu(self.tray_menu())
        self.tray.activated.connect(self._activated)
        self.refresh_tray()
        self.tray.show()

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self.window is not None and self.window.isVisible() and self.window.isActiveWindow():
                self.window.hide()
            else:
                self.show_window()

    def show_window(self, no_tray=False):
        if self.window is None:
            return
        self.window.set_host_note(host_hint() if (no_tray or self.tray is None) else "")
        self.window.present_near(self.tray.geometry() if self.tray is not None else None)

    def refresh_tray(self):
        """Subclasses update icon and tooltip here."""

    def shutdown(self):
        """Stop timers and child processes (subclasses add theirs)."""
        self.timer.stop()

    def quit(self):
        self.shutdown()
        if self.tray is not None:
            self.tray.hide()
        self.app.quit()

    # ------------------------------------------------------------ polling
    @staticmethod
    def _mtime(path):
        try:
            return os.path.getmtime(path)
        except (OSError, TypeError):
            return None

    def poll(self, force=False):
        """Follow status.json and settings.json (two stat() calls when nothing changed)."""
        mtime = control.status_mtime()
        status_changed = force or mtime != self._status_mtime
        if not status_changed and self.status.state == "running" and mtime is not None \
                and time.time() - mtime > control.STATUS_STALE_AFTER:
            status_changed = True                                  # the service stopped refreshing it
        if status_changed:
            self._status_mtime = mtime
            self.status = control.read_status()
            self.on_status(self.status)
        settings_mtime = self._mtime(settings.config_path())
        if (force or settings_mtime != self._settings_mtime) and not self._saving:
            self._settings_mtime = settings_mtime
            self.values = control.load_settings()
            self.on_settings(self.values)

    def on_status(self, status):
        """Service status changed (devices plugged, unplugged, states)."""

    def on_settings(self, values):
        """settings.json changed (this app, the configuration window, or by hand)."""

    # ------------------------------------------------------------ settings
    def save(self, values, done=None):
        """Write settings off the GUI thread; ``done(ok, message)`` on the GUI thread.

        One write at a time: changes made while a write runs are merged into the
        next one (always the newest values), so an older write can never land
        after a newer one. Until then the values in memory are the truth."""
        self.values = values
        if self._saving:
            self._save_pending = (values, done)
            return
        self._saving = True

        def finished(result, error):
            ok, message = result if error is None else (False, str(error))
            if not ok:
                log.warning("saving settings failed: %s", message)
                self.notify(_("Could not save the settings"), message, error=True)
            self._saving = False
            if not ok and self._save_pending is None:
                # Show what is really saved, not the choice that could not be written.
                self.values = control.load_settings()
                self.on_settings(self.values)
            if self._save_pending is not None:
                (next_values, next_done), self._save_pending = self._save_pending, None
                self.save(next_values, next_done)
            else:
                self._settings_mtime = None                      # reread what was really written
                self.poll()
            if done:
                done(ok, message)

        self.run_async(lambda: control.save_settings(values), finished)

    # ------------------------------------------------------------ async work
    def run_async(self, func, callback=None):
        self._busy += 1
        self.busy_changed(True)

        def target():
            result, error = None, None
            try:
                result = func()
            except Exception as exc:          # reported on the GUI thread, never lost
                log.exception("background task failed")
                error = exc
            self._bridge.done.emit(callback, result, error)

        threading.Thread(target=target, name=f"{self.app_id}-task", daemon=True).start()

    def _deliver(self, callback, result, error):
        self._busy = max(0, self._busy - 1)
        self.busy_changed(self._busy > 0)
        if callback is not None:
            callback(result, error)

    def busy_changed(self, busy):
        if self.window is not None:
            self.window.set_busy(busy)

    def notify(self, title, message, error=False):
        if self.tray is not None and self.tray.supportsMessages():
            icon = QSystemTrayIcon.MessageIcon.Warning if error else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage(title, message, icon, 6000)
        elif self.window is not None:
            self.window.show_message(f"{title}: {message}" if message else title, error=error)

    # ------------------------------------------------------------ actions shared by both apps
    def open_configuration(self):
        import subprocess
        try:
            subprocess.Popen(["big-screen-monitor-config.sh"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config_gui.py")
            subprocess.Popen([sys.executable, script], start_new_session=True)

    def restart_service(self):
        """Restart through the helper (administrator authorization, then the service
        reopens every display); progress and result are shown, nothing blocks."""
        def finished(result, error):
            ok, message = result if error is None else (False, str(error))
            if ok:
                self.notify(_("Service restarted"), _("The displays reconnect in a few seconds."))
            else:
                self.notify(_("Could not restart the service"), message, error=True)
            self.poll(force=True)

        self.run_async(lambda: control.service("restart"), finished)

    def reconnect(self, display_id):
        def finished(result, error):
            ok, message = result if error is None else (False, str(error))
            if not ok:
                self.notify(_("Could not reconnect"), message, error=True)

        self.run_async(lambda: control.display_command(display_id, "reconnect"), finished)

    def set_autostart(self, enabled):
        try:
            if enabled:
                autostart.enable(self.app_id)
            else:
                autostart.disable(self.app_id)
        except OSError as error:
            self.notify(_("Could not change the session start"), str(error), error=True)


# ------------------------------------------------------------ single instance


def activate_running(app_id):
    """True when another instance runs (it was asked to show its window)."""
    socket = QLocalSocket()
    socket.connectToServer(socket_path(app_id))
    if not socket.waitForConnected(500):
        return False
    socket.write(b"show\n")
    socket.flush()
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


class CommandServer(QLocalServer):
    """Single-instance socket: ``show`` raises the window, ``quit`` ends the app
    (the configuration window's switch). Slots never let an exception out (PyQt6
    aborts the process on one) and never touch a socket Qt already destroyed."""

    def __init__(self, on_show, on_quit):
        super().__init__()
        self.on_show, self.on_quit = on_show, on_quit
        self._partial = {}       # connection -> end of a command not yet complete
        self.newConnection.connect(self._accept)

    def _accept(self):
        try:
            while self.hasPendingConnections():
                connection = self.nextPendingConnection()
                connection.readyRead.connect(functools.partial(self._read, connection))
                # A short client (connect, write, close): the command may already be
                # buffered (Qt does not signal it again) or come with the hang-up, so
                # what is left is read before the connection is dropped.
                connection.disconnected.connect(functools.partial(self._gone, connection))
                if connection.bytesAvailable() or connection.waitForReadyRead(0):
                    self._read(connection)
        except Exception:      # noqa: BLE001 - never into PyQt (it aborts)
            log.exception("single-instance socket")

    def _gone(self, connection):
        self._read(connection)
        self._run(self._partial.pop(connection, "").split())    # the hang-up ends the last word
        try:
            connection.deleteLater()
        except RuntimeError:
            pass

    def _read(self, connection):
        try:
            if not connection.isOpen() or not connection.bytesAvailable():
                return
            data = bytes(connection.readAll())
        except (RuntimeError, AttributeError):   # already destroyed by Qt
            return
        # A command may arrive split across reads ("qu" + "it\n"): only words that a
        # separator (or the hang-up) ended are run; the rest waits for the next read.
        text = self._partial.pop(connection, "") + data.decode("ascii", "replace")
        words = text.split()
        if words and not text[-1].isspace():
            self._partial[connection] = words.pop()
        self._run(words)

    def _run(self, words):
        try:
            for word in words:
                if word == "quit":
                    log.info("asked to quit (configuration window)")
                    self.on_quit()
                elif word == "show":
                    self.on_show()
        except Exception:      # noqa: BLE001 - never into PyQt (it aborts)
            log.exception("single-instance command")


def listen(app_id, on_show, on_quit):
    server = CommandServer(on_show, on_quit)
    QLocalServer.removeServer(socket_path(app_id))       # stale socket of a crashed instance
    if not server.listen(socket_path(app_id)):
        log.warning("single-instance socket unavailable: %s", server.errorString())
    return server


def run(app_cls, argv=None):
    """Entry point shared by both launchers."""
    argv = list(sys.argv if argv is None else argv)
    autostarted = "--autostart" in argv
    show = "--show" in argv          # explicit request (also the default when not autostarted)
    setup_logging(app_cls.app_id)
    app = QApplication([argv[0]])
    app.setApplicationName(app_cls.app_id)
    app.setDesktopFileName(app_cls.app_id)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon.fromTheme(app_cls.icon_name))
    if activate_running(app_cls.app_id):
        if not autostarted:
            log.info("already running: asked the running instance to show its window")
        return 0
    tray_app = app_cls(app, autostarted=autostarted)
    server = listen(app_cls.app_id, tray_app.show_window, tray_app.quit)
    app.aboutToQuit.connect(tray_app.shutdown)          # also on logout (session manager)
    tray_app.start()
    if (show or not autostarted) and tray_app.tray is not None:
        tray_app.show_window()      # opened from the menu: show the controls at once
    code = exec_app(app)
    server.close()
    return code
