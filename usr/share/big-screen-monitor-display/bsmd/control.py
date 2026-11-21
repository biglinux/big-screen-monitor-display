"""Settings, service and display control shared by the windows and the tray apps.

No GUI toolkit here: the GTK configuration window and the Qt tray apps use the
same functions, so every program writes the settings the same way (validated,
atomic, through the polkit helper) and reads the same service status.

Global and per-display values follow the configuration window:

* ``set_global(values, key, value)`` changes the global value and removes the
  per-display overrides of that key, so the choice reaches every display (the
  theme gallery does the same);
* ``set_display(values, display_id, key, value)`` changes one display only;
  ``None`` removes the override and the display follows the global value again.
"""

import copy
import json
import os
import subprocess
import time

from . import settings, statusfile
from .i18n import _

HELPER = "/usr/lib/big-screen-monitor-display/bsm-helper"
SERVICE_VERBS = ("start", "stop", "restart", "enable", "disable")
# The service rewrites status.json every second; older than this means stopped or stalled.
STATUS_STALE_AFTER = 10.0


def run_helper(args, payload=None, timeout=120, helper=None):
    """Run the privileged helper through pkexec. Returns ``(ok, message)``."""
    helper = helper or HELPER
    if not os.path.exists(helper):
        return False, _("The administrative helper is not installed ({path}).").format(path=helper)
    binary = isinstance(payload, bytes)
    try:
        result = subprocess.run(["pkexec", helper, *args], input=payload, capture_output=True,
                                text=not binary, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if binary:
        result.stdout = result.stdout.decode("utf-8", "replace")
        result.stderr = result.stderr.decode("utf-8", "replace")
    if result.returncode in (126, 127):
        return False, _("Authorization was cancelled or denied.")
    try:
        reply = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        reply = {"ok": result.returncode == 0, "error": result.stderr.strip()}
    if reply.get("ok"):
        if "id" in reply:
            return True, reply["id"]
        return True, "; ".join(reply.get("problems") or [])
    return False, reply.get("error") or result.stderr.strip() or _("Unknown error")


def save_settings(values, helper=None):
    """Persist settings: directly when the directory is writable (development,
    ``BSM_CONFIG``), else through the helper. Returns ``(ok, message)``."""
    path = settings.config_path()
    directory = os.path.dirname(path)
    if os.environ.get("BSM_CONFIG") or (os.path.isdir(directory) and os.access(directory, os.W_OK)):
        try:
            _clean, problems = settings.save(values, path)
            return True, "; ".join(problems)
        except OSError as error:
            return False, str(error)
    return run_helper(["apply-settings"], json.dumps(values), helper=helper)


def load_settings():
    """Current settings, validated (defaults when the file is missing)."""
    return settings.load()


def service(verb, helper=None):
    if verb not in SERVICE_VERBS:
        raise ValueError(verb)
    return run_helper(["service", verb], helper=helper, timeout=60)


def recover(helper=None):
    """Ask the running service to reconnect its displays (no restart)."""
    return run_helper(["recover"], helper=helper, timeout=30)


def display_command(display_id, action, helper=None, **extra):
    command = settings.validate_command(dict(extra, display=display_id, action=action))
    if command is None:
        return False, _("Invalid command.")
    return run_helper(["display-command"], json.dumps(command), helper=helper, timeout=30)


# ------------------------------------------------------------------ editing


def set_global(values, key, value, clear_overrides=True):
    """Return a copy of ``values`` with the global ``key`` set (and, by default,
    the per-display overrides of ``key`` removed so the choice applies everywhere)."""
    result = copy.deepcopy(values)
    result[key] = value
    if clear_overrides:
        displays = result.get("displays") or {}
        for display_id in list(displays):
            entry = displays[display_id]
            if isinstance(entry, dict) and key in entry:
                entry.pop(key)
                if not entry:
                    displays.pop(display_id)
    return result


def set_display(values, display_id, key, value):
    """Return a copy of ``values`` with ``key`` overridden on one display
    (``None`` removes the override)."""
    result = copy.deepcopy(values)
    displays = result.setdefault("displays", {})
    entry = displays.setdefault(display_id, {})
    if value is None:
        entry.pop(key, None)
    else:
        entry[key] = value
    if not entry:
        displays.pop(display_id, None)
    return result


def effective(values, display_id):
    """Settings one display uses (global values + its overrides)."""
    return settings.merged(values, display_id) if display_id else dict(values)


# ------------------------------------------------------------------ status


class ServiceStatus:
    """What the running service reports (``status.json``), read cheaply.

    ``state`` is one of ``"running"``, ``"stale"`` (file not refreshed: service
    stopped, frozen or restarting) and ``"missing"`` (never started)."""

    def __init__(self, data, age):
        self.data = data or {}
        self.age = age
        if data is None:
            self.state = "missing"
        elif age is not None and age > STATUS_STALE_AFTER:
            self.state = "stale"
        else:
            self.state = "running"

    @property
    def running(self):
        return self.state == "running"

    @property
    def displays(self):
        return [entry for entry in self.data.get("displays") or [] if isinstance(entry, dict)]

    def display(self, display_id):
        for entry in self.displays:
            if entry.get("id") == display_id:
                return entry
        return None


def _status_candidates():
    if os.environ.get("BSM_STATUS"):
        return [os.environ["BSM_STATUS"]]
    return [statusfile.SYSTEM_STATUS, statusfile.status_path()]


def read_status(path=None):
    """``ServiceStatus`` of the system service or of a manual run.

    When both are running (both files fresh), the one that drives displays
    wins: picking only the newest file would flip between them every second."""
    if path:
        candidates = [path]
    else:
        candidates = _status_candidates()
    best = None
    now = time.time()
    for candidate in candidates:
        try:
            age = max(0.0, now - os.path.getmtime(candidate))
        except OSError:
            continue
        status = ServiceStatus(statusfile.read_status(candidate), age)
        if best is None:
            best = status
            continue
        rank = (status.state == "running", bool(status.displays), -age)
        best_rank = (best.state == "running", bool(best.displays), -best.age)
        if rank > best_rank:
            best = status
    return best or ServiceStatus(None, None)


def status_mtime(path=None):
    """Newest modification time of the status files, or ``None`` (cheap change detection)."""
    times = []
    for candidate in [path] if path else _status_candidates():
        try:
            times.append(os.path.getmtime(candidate))
        except (OSError, TypeError):
            continue
    return max(times) if times else None


def profile_of(entry):
    """Driver family of a status display entry (``"turing_rev_a"``, ``"deepcool_ak"``...)."""
    source = entry.get("source") or {}
    profile = source.get("profile") or (entry.get("settings") or {}).get("profile") or ""
    return profile if profile != "auto" else ""


def is_deepcool(entry):
    return profile_of(entry).startswith("deepcool_")


def is_screen(entry):
    """Raster displays (pictures), as opposed to the numeric DeepCool coolers."""
    capabilities = entry.get("capabilities") or {}
    if is_deepcool(entry):
        return False
    return capabilities.get("output", "raster") == "raster"
