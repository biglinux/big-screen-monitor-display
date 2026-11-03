"""'Diagnose my display': checks that need no privileges, with safe fixes.

Each check is a dict: ``id``, ``title``, ``ok``, ``severity`` (info, warning,
error), ``detail`` and an optional ``fix`` naming a helper action
(``restart``, ``recover``, ``enable``, ``migrate``).
"""

import grp
import os
import stat
import subprocess
import time

from . import SERVICE_NAME, runtime, settings
from .displays import discovery
from .i18n import _

UDEV_RULE = "/usr/lib/udev/rules.d/70-big-screen-monitor-display.rules"
HELPER = "/usr/lib/big-screen-monitor-display/bsm-helper"
SERVICE_GROUP = "big-screen-monitor"


def systemctl_query(*args):
    try:
        result = subprocess.run(["systemctl", *args, SERVICE_NAME], capture_output=True,
                                text=True, timeout=5, check=False)
        return result.stdout.strip() or result.stderr.strip()
    except (OSError, subprocess.SubprocessError) as error:
        return f"error: {error}"


def find_usb_devices(sysfs=discovery.SYSFS):
    """Panels recognised by universal discovery (read-only sysfs scan)."""
    found = []
    for candidate in discovery.discover(discovery.scan_usb(sysfs)):
        device = candidate.device
        best = candidate.best
        found.append({"name": best.profile.name, "profile": best.profile.id, "id": device.ids,
                      "display_id": candidate.id, "confidence": candidate.confidence,
                      "sysfs": os.path.join(sysfs, device.path),
                      "node": f"/dev/bus/usb/{device.bus:03d}/{device.address:03d}" if device.bus else None,
                      "tty": candidate.port, "asleep": candidate.asleep})
    return found


def _node_access(node):
    try:
        info = os.stat(node)
    except OSError as error:
        return None, str(error)
    try:
        group = grp.getgrgid(info.st_gid).gr_name
    except KeyError:
        group = str(info.st_gid)
    return (stat.S_IMODE(info.st_mode), group), None


def _check(id_, title, ok, detail, severity="error", fix=None):
    return {"id": id_, "title": title, "ok": bool(ok), "detail": detail,
            "severity": "info" if ok else severity, "fix": None if ok else fix}


def run_checks(status_file=None):
    checks = []
    active = systemctl_query("is-active")
    enabled = systemctl_query("is-enabled")
    checks.append(_check("service_active", _("Background service running"), active == "active",
                         _("State: {state}").format(state=active), fix="restart"))
    checks.append(_check("service_enabled", _("Service starts with the computer"), enabled == "enabled",
                         _("State: {state}").format(state=enabled), severity="warning", fix="enable"))

    devices = find_usb_devices()
    names = ", ".join(f"{d['name']} ({d['id']}, {d['confidence']})" for d in devices)
    checks.append(_check("device_present", _("Display connected over USB"), bool(devices),
                         names or _("No supported display found. Check the cable and try another USB port."),
                         fix=None))
    for device in devices:
        node = device["tty"] or device["node"]
        if not node:
            continue
        access, error = _node_access(node)
        if access is None:
            checks.append(_check("device_node", _("Device node"), False, error))
            continue
        mode, group = access
        world_writable = bool(mode & 0o002)
        ok = group == SERVICE_GROUP and mode & 0o060 == 0o060
        detail = _("{node}: mode {mode:o}, group {group}").format(node=node, mode=mode, group=group)
        if world_writable:
            detail += " — " + _("world writable (old udev rule); reinstall the package or reconnect the display")
        checks.append(_check("device_permissions", _("Display permissions"), ok and not world_writable,
                             detail, severity="warning"))

    fragment = systemctl_query("show", "-p", "FragmentPath", "--value")
    if fragment.startswith("/etc/"):
        checks.append(_check("unit_override", _("Service definition"), False,
                             _("{path} overrides the packaged service; remove it to get the watchdog and "
                               "the sandbox of this version.").format(path=fragment), severity="warning"))
    checks.append(_check("udev_rule", _("udev rule installed"), os.path.exists(UDEV_RULE), UDEV_RULE,
                         severity="warning"))
    checks.append(_check("helper", _("Administrative helper installed"), os.path.exists(HELPER), HELPER,
                         severity="warning"))

    path = settings.config_path()
    _values, problems = settings.read_file(path)
    exists = os.path.exists(path)
    legacy = settings.find_legacy_files(home_glob=os.path.expanduser("~"), root_home="/nonexistent")
    if not exists and legacy:
        checks.append(_check("settings", _("Settings file"), False,
                             _("Old per-user settings found in {path}; they can be imported.").format(path=legacy[0]),
                             severity="warning", fix="migrate"))
    else:
        checks.append(_check("settings", _("Settings file"), not problems,
                             "; ".join(problems) or (path if exists else _("Using defaults (no file yet)")),
                             severity="warning"))

    status = runtime.read_status(status_file)
    if status is None:
        checks.append(_check("status", _("Service health report"), False,
                             _("The service has not published a health report."), fix="restart"))
    else:
        age = time.time() - os.path.getmtime(status_file or runtime.find_status_file())
        fresh = age < 15
        checks.append(_check("status", _("Service health report"), fresh,
                             _("Updated {age:.0f}s ago, state: {state}").format(age=age, state=status.get("state")),
                             fix="restart"))
        state = status.get("state")
        checks.append(_check("link", _("Communication with the display"), state in ("healthy",),
                             describe_state(status), severity="warning" if state == "degraded" else "error",
                             fix="recover" if state in ("degraded", "failed", "retrying") else None))
        checks.append(_check("pipeline", _("Rendering and transfer pipeline"), not status.get("stalled"),
                             _("A pipeline thread stopped making progress.") if status.get("stalled")
                             else _("All threads are progressing."), fix="restart"))
        for display in status.get("displays") or []:
            device = display.get("device") or {}
            title = _("Display {name}").format(name=display.get("name") or display.get("id"))
            checks.append(_check(f"display:{display.get('id')}", title, display.get("state") == "healthy",
                                 describe_state(display), severity="warning", fix="recover"
                                 if display.get("state") in ("degraded", "failed", "retrying") else None))
        for pending in status.get("pending") or []:
            checks.append(_check(f"pending:{pending.get('id')}", _("Display waiting for a model choice"), False,
                                 _("{ids} at {port}: choose its model in My Displays.").format(
                                     ids=pending.get("ids"), port=pending.get("port") or pending.get("usb_path")),
                                 severity="warning"))
        recent = [i for i in status.get("incidents", []) if i.get("severity") in ("error", "critical")]
        checks.append(_check("incidents", _("Recent errors"), not recent,
                             _("{count} recent error(s); last: {message}").format(
                                 count=len(recent), message=recent[-1]["message"]) if recent
                             else _("No recent errors."), severity="warning"))
    return {"checks": checks, "status": status, "devices": devices}


def describe_state(status):
    state = status.get("state")
    device = status.get("device") or {}
    texts = {
        "healthy": _("Working normally ({model} {w}x{h})."),
        "degraded": _("Transient errors; retrying automatically."),
        "recovering": _("Reconnecting to the display..."),
        "disconnected": _("Display not found; waiting for it to be connected."),
        "retrying": _("Connection failed; retrying with increasing intervals."),
        "failed": _("The display does not respond. The service will be restarted automatically."),
        "starting": _("Starting..."),
        "stopped": _("Service stopped."),
    }
    return texts.get(state, state).format(model=device.get("model", "?"), w=device.get("width", "?"),
                                          h=device.get("height", "?"))


def format_report(report):
    lines = []
    for check in report["checks"]:
        mark = "OK " if check["ok"] else ("!! " if check["severity"] == "error" else "?  ")
        lines.append(f"{mark}{check['title']}: {check['detail']}")
        if check.get("fix"):
            lines.append(f"     -> {_('suggested action')}: {check['fix']}")
    status = report.get("status")
    if status:
        stats = status.get("stats", {})
        proc = status.get("process", {})
        lines.append("")
        lines.append(f"state={status.get('state')} uptime={status.get('uptime_s')}s "
                     f"recoveries={status.get('recoveries')} frames={stats.get('frames_sent')} "
                     f"fps={stats.get('fps', 0):.1f} cpu={proc.get('cpu_percent')}% rss={proc.get('rss_mb')}MB")
        lines.append(_("Note: the panels do not report what they display; a successful transfer means "
                       "the device accepted the data."))
    return "\n".join(lines)
