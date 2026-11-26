"""Where the service keeps its runtime files, and the status file it publishes.

Kept apart from ``bsmd.runtime`` (which pulls Pillow, numpy and the themes) so
that light clients, such as the tray apps, can follow the service cheaply.
"""

import json
import os

SYSTEM_STATUS = "/run/big-screen-monitor-display/status.json"


def runtime_dir():
    base = os.environ.get("RUNTIME_DIRECTORY", "").split(":")[0]
    if not base:
        base = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/bsmd-{os.getuid()}",
                            "big-screen-monitor-display")
    return base


def state_dir():
    base = os.environ.get("STATE_DIRECTORY", "").split(":")[0]
    if not base:
        base = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                            "big-screen-monitor-display")
    return base


def status_path():
    return os.path.join(runtime_dir(), "status.json")


def find_status_file():
    """BSM_STATUS when set (development), else the freshest of system service and manual run."""
    if os.environ.get("BSM_STATUS"):
        return os.environ["BSM_STATUS"] if os.path.exists(os.environ["BSM_STATUS"]) else None
    candidates = [SYSTEM_STATUS, status_path()]
    best, best_mtime = None, -1.0
    for path in filter(None, candidates):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = path, mtime
    return best


def read_status(path=None):
    path = path or find_status_file()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None
