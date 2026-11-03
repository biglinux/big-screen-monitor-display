"""Compatibility layer for the 3.x/4.0 single-display driver API.

The drivers now live in :mod:`bsmd.displays` (one module per protocol
family, see docs/13-arquitetura-drivers.md). This module keeps the names
older code and scripts imported: error kinds, :class:`DisplayError`,
:class:`Transfer`, :class:`DeviceInfo`, the AX206 and simulated panels, the
Turing 3.5" driver and ``make_driver``/``device_present``, which now go
through universal discovery.
"""

from .displays import discovery, registry
from .displays.ax206 import AX206, brightness_to_ax206
from .displays.base import (BUSY, DISCONNECTED, EXTERNAL_KINDS, FATAL_KINDS, IO, NOT_FOUND, PERMISSION, PROTOCOL,
                            TIMEOUT, Capabilities, DeviceInfo, DisplayError, Transfer)
from .displays.simulated import SimulatedDisplay
from .displays.turing_serial import TuringRevA as TuringSmartScreen

__all__ = ("AX206", "BUSY", "Capabilities", "DISCONNECTED", "DeviceInfo", "DisplayError", "EXTERNAL_KINDS",
           "FATAL_KINDS", "IO", "NOT_FOUND", "PERMISSION", "PROTOCOL", "SimulatedDisplay", "TIMEOUT",
           "Transfer", "TuringSmartScreen", "brightness_to_ax206", "brightness_to_turing", "device_present",
           "make_driver")


def brightness_to_turing(percent):
    """Map 0..100 % to the Turing scale 255..0 (0 = brightest)."""
    percent = max(0, min(100, int(percent)))
    return int(255 - percent * 255 / 100)


def _first_candidate(settings, devices=None):
    model = settings.get("model", "auto")
    for candidate in discovery.discover(devices):
        profile = discovery.choose_profile(candidate, model)
        if profile is not None and (model == "auto" or profile.id == registry.get(model).id):
            return candidate, profile
    return None, None


def make_driver(settings, simulate=None, devices=None):
    """Unopened driver for the first display matching ``settings['model']``."""
    if simulate is not None:
        return simulate
    candidate, profile = _first_candidate(settings, devices)
    if candidate is None:
        raise DisplayError(NOT_FOUND, "no supported display connected")
    return profile.create(candidate, discovery.driver_options(settings))


def device_present(settings, simulate=None, devices=None):
    if simulate is not None:
        return simulate.connected
    return _first_candidate(settings, devices)[0] is not None
