"""Session start through the XDG autostart directory (every desktop reads it).

The entry starts the app with ``--autostart``: tray icon only, no window, and
the app gives up quietly on desktops without a tray host.
"""

import os

# Entries written by the first version of these apps (pull request #11), replaced
# by the new ones: removed only when they start those launchers.
LEGACY = {
    "big-screen-monitor-deepcool": ("deepcool-digital.desktop", ("deepcool-digital",)),
    "big-screen-monitor-tray": ("screen-monitor-tray.desktop", ("screen-monitor-tray",)),
}
NAMES = {
    "big-screen-monitor-deepcool": "DeepCool Digital",
    "big-screen-monitor-tray": "Big Screen Monitor Tray",
}


def directory():
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart")


def path(app_id):
    return os.path.join(directory(), f"{app_id}.desktop")


def command(app_id):
    import shlex
    from .session import command as session_command
    return shlex.join(session_command(app_id))


def is_enabled(app_id):
    return os.path.exists(path(app_id))


def enable(app_id):
    os.makedirs(directory(), exist_ok=True)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={NAMES.get(app_id, app_id)}\n"
        f"Exec={command(app_id)} --autostart\n"
        f"Icon={app_id}\n"
        "Terminal=false\n"
        "NoDisplay=true\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n"
        "X-KDE-StartupNotify=false\n"
    )
    target = path(app_id)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp, target)


def disable(app_id):
    try:
        os.unlink(path(app_id))
    except FileNotFoundError:
        pass


def migrate_legacy(app_id):
    """Replace the autostart entry of the first version by the new one (once)."""
    name, launchers = LEGACY.get(app_id, (None, ()))
    if not name:
        return False
    old = os.path.join(directory(), name)
    try:
        with open(old, encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return False
    exec_lines = [line for line in text.splitlines() if line.startswith("Exec=")]
    if not any(launcher in line for line in exec_lines for launcher in launchers):
        return False                       # someone else's entry with the same name: leave it
    enable(app_id)
    os.unlink(old)
    return True
