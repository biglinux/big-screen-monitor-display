"""Other programs that drive DeepCool coolers.

Two programs writing to the same cooler interleave their packets (flickering
or wrong values). Nothing here stops or changes them: they are listed with a
hint, and the user decides. Reads only process names and unit files.
"""

import os

import psutil

from ...i18n import N_

# executable / script name -> project
PROGRAMS = {
    "deepcool-digital-linux": "Nortank12/deepcool-digital-linux",
    "deepcool-digital-info.py": "Algorithm0/deepcool-digital-info",
    "deepcool-ak-series-digital.py": "raghulkrishna/deepcool-ak620-digital-linux",
    "deepcool-cli": "mymymy1303/qt-deepcool",
    "deepcool-qt": "mymymy1303/qt-deepcool",
}
UNITS = ("deepcool-temp.service", "deepcool-ak-series-digital.service", "deepcool-cli.service",
         "deepcool-digital.service", "deepcool-digital-linux.service")
UNIT_DIRS = ("/etc/systemd/system", "/usr/lib/systemd/system", "/lib/systemd/system", "/usr/local/lib/systemd/system")
HINT = N_("Stop and disable it before using the cooler here, for example: sudo systemctl disable --now {unit}")


def running_programs():
    found = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            names = [proc.info.get("name") or ""] + [os.path.basename(part) for part in
                                                    (proc.info.get("cmdline") or [])[:3]]
        except (psutil.Error, TypeError):
            continue
        for name in names:
            if name in PROGRAMS:
                found.append({"kind": "process", "name": name, "pid": proc.info["pid"], "project": PROGRAMS[name]})
                break
    return found


def installed_units(dirs=UNIT_DIRS):
    found = []
    for directory in dirs:
        for unit in UNITS:
            path = os.path.join(directory, unit)
            if os.path.exists(path):
                enabled = any(os.path.exists(os.path.join("/etc/systemd/system", target, unit))
                              for target in ("multi-user.target.wants", "graphical.target.wants"))
                found.append({"kind": "unit", "name": unit, "path": path, "enabled": enabled})
    return found


def find_conflicts():
    """Programs running now plus installed services known to drive DeepCool coolers."""
    try:
        programs = running_programs()
    except Exception:  # noqa: BLE001 - diagnostics only
        programs = []
    return programs + installed_units()
