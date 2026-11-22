"""State of each display and of the tray icon's status dot (no Qt: unit-tested).

Two levels are kept apart (docs/windowmaker/symbolic-tray.md):

* the **service** - not running (no status file) or stopped refreshing it
  (stale): the dot is GREY and every display reads "service stopped". A
  stopped service is never shown as a disconnected display, because the
  displays may be perfectly fine and only the service is missing;
* each **display** - one :class:`DisplayState` per display the tray knows
  (the ones in the service status, plus a remembered selection that is gone).

Colours of the dot (and of each display in the menu):

======  ==============================================================
GREEN   connected and working
YELLOW  problem detected, unstable link or reconnecting
RED     switched off, disconnected, not responding or unavailable
GREY    service stopped (overrides everything)
======  ==============================================================

With several displays the dot shows the most relevant problem of the
displays that receive the tray's commands (the selected one, or all):
red > yellow > green. A selected display that disappeared is red
("unavailable"), never silently replaced by another one.
"""

from dataclasses import dataclass

from bsmd.i18n import N_

GREEN, YELLOW, RED, GREY = "green", "yellow", "red", "grey"
SEVERITY = {GREEN: 0, YELLOW: 1, RED: 2, GREY: 3}

# Machine state of a display.
CONNECTED, SWITCHED_OFF, RECONNECTING, PROBLEM, DISCONNECTED, UNAVAILABLE, SERVICE_STOPPED = (
    "connected", "switched_off", "reconnecting", "problem", "disconnected", "unavailable", "service_stopped")

COLOUR = {CONNECTED: GREEN, RECONNECTING: YELLOW, PROBLEM: YELLOW, SWITCHED_OFF: RED, DISCONNECTED: RED,
          UNAVAILABLE: RED, SERVICE_STOPPED: GREY}

LABEL = {
    CONNECTED: N_("Connected"),
    SWITCHED_OFF: N_("Switched off"),
    RECONNECTING: N_("Reconnecting…"),
    PROBLEM: N_("Unstable connection"),
    DISCONNECTED: N_("Disconnected"),
    UNAVAILABLE: N_("Unavailable"),
    SERVICE_STOPPED: N_("Service stopped"),
}

# runtime link states (bsmd.health) -> display state
LINK = {"healthy": CONNECTED, "degraded": PROBLEM, "starting": RECONNECTING, "recovering": RECONNECTING,
        "retrying": RECONNECTING, "disconnected": DISCONNECTED, "failed": DISCONNECTED, "stopped": DISCONNECTED}

DETAIL = {
    "failed": N_("The display is connected but does not answer."),
    "replug": N_("Unplug the display's cable and plug it in again."),
    "disconnected": N_("The display is not connected."),
    "unavailable": N_("This display is not connected now. Choose another one or plug it in."),
    "switched_off": N_("The backlight is off; the theme keeps running."),
    "disabled": N_("Turned off in the configuration window."),
    "degraded": N_("Transfers are failing now and then; the service keeps retrying."),
    "reconnecting": N_("The service is reconnecting to the display."),
    "service": N_("The monitor service is not running."),
}


@dataclass(frozen=True)
class DisplayState:
    id: str
    name: str
    state: str
    detail: str = ""          # short untranslated (N_) explanation, "" when all is well

    @property
    def colour(self):
        return COLOUR[self.state]

    @property
    def label(self):
        return LABEL[self.state]


def classify(entry, values=None, service_running=True):
    """State of one status entry (``values``: that display's effective settings)."""
    entry = entry or {}
    display_id = entry.get("id", "")
    name = entry.get("_name") or entry.get("name") or display_id or "?"
    if not service_running:
        return DisplayState(display_id, name, SERVICE_STOPPED, DETAIL["service"])
    if entry.get("_absent"):
        return DisplayState(display_id, name, UNAVAILABLE, DETAIL["unavailable"])
    values = values or {}
    if entry.get("enabled") is False or values.get("enabled") is False:
        return DisplayState(display_id, name, SWITCHED_OFF, DETAIL["disabled"])
    link = entry.get("state", "")
    state = LINK.get(link, PROBLEM)
    if entry.get("attention") == "replug":
        return DisplayState(display_id, name, DISCONNECTED, DETAIL["replug"])
    if state == CONNECTED:
        capabilities = entry.get("capabilities") or {}
        try:
            brightness = int(values.get("brightness", 70))
        except (TypeError, ValueError):
            brightness = 70
        if brightness == 0 and capabilities.get("brightness"):
            return DisplayState(display_id, name, SWITCHED_OFF, DETAIL["switched_off"])
        return DisplayState(display_id, name, CONNECTED)
    detail = {"failed": DETAIL["failed"], "disconnected": DETAIL["disconnected"], "degraded": DETAIL["degraded"]
              }.get(link, DETAIL["reconnecting"] if state == RECONNECTING else "")
    return DisplayState(display_id, name, state, detail)


def aggregate(states, service_running=True):
    """Colour of the tray dot for the displays that receive the commands."""
    if not service_running:
        return GREY
    if not states:
        return RED                       # service running, but no display to show anything on
    return max((s.colour for s in states), key=SEVERITY.__getitem__)


def summary(states, service_running=True):
    """(colour, untranslated label, count) for the menu header and tooltip."""
    if not service_running:
        return GREY, N_("Service stopped"), 0
    if not states:
        return RED, N_("No display connected"), 0
    colour = aggregate(states)
    if len(states) == 1:
        return colour, states[0].label, 1
    if colour == GREEN:
        return colour, N_("All displays working"), len(states)
    return colour, N_("Attention needed on a display"), len(states)
