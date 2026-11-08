"""The SmartMonitor HID panel in the configuration window.

The panel shows a flashed adaptation of the selected theme (see
bsmd.displays.smartmonitor.capture), so its card and live preview show that
adaptation, decoded from the same compiled picture the service sends, with
the service's last values when it is running.
"""

from bsmd import settings
from bsmd.displays.smartmonitor import layout

PROFILE = "smartmonitor_hid"
PREVIEW_SIZE = layout.SIZE


def _status(window, display_id):
    return next((d for d in (window.status or {}).get("displays") or [] if d.get("id") == display_id), None)


def is_panel(status=None, own=None, candidate=None):
    ids = [((status or {}).get("source") or {}).get("profile"), (own or {}).get("profile")]
    if candidate is not None and getattr(candidate, "best", None):
        ids.append(candidate.best.profile.id)
    return PROFILE in ids


def metrics_of(status):
    status = status or {}
    if status.get("state") not in ("healthy", "degraded"):
        return {}
    return status.get("metrics") or {}


def face_renderer(window, display_id):
    """Preview callable for a SmartMonitor display, or None for other displays."""
    status = _status(window, display_id)
    if not is_panel(status):
        return None

    def draw():
        current = _status(window, display_id) or status
        return layout.preview(settings.merged(window.values, display_id), metrics_of(current))
    return draw


def thumbnail_work(effective, status):
    snapshot, metrics = dict(effective), metrics_of(status)
    return lambda: layout.preview(snapshot, metrics)
