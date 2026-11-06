"""Universal display discovery: USB identifiers -> candidate families.

Reads only sysfs (no device is opened, nothing is written), so it is safe to
run every couple of seconds for hot-plug detection and from the GUI as an
ordinary user.

A candidate's id is its USB port path (``usb-5-1.4.4``): identical panels
share serial numbers, and rev. C panels change VID/PID when they wake up,
but the physical port stays the same.
"""

import glob
import os
from dataclasses import dataclass, field

from .registry import AMBIGUOUS, CONFIDENCE_ORDER, PROFILES, UNKNOWN, get

SYSFS = "/sys/bus/usb/devices"


@dataclass
class UsbDevice:
    path: str
    vid: int
    pid: int
    serial: str = ""
    manufacturer: str = ""
    product: str = ""
    bus: int = 0
    address: int = 0
    ttys: tuple = ()
    hidraws: tuple = ()          # /dev/hidrawN of the device's HID interfaces (DeepCool coolers)

    @property
    def ids(self):
        return f"{self.vid:04x}:{self.pid:04x}"


@dataclass
class Match:
    profile: object
    confidence: str
    rule: object


@dataclass
class Candidate:
    device: UsbDevice
    matches: list = field(default_factory=list)

    @property
    def id(self):
        return f"usb-{self.device.path}"

    @property
    def port(self):
        return self.device.ttys[0] if self.device.ttys else None

    @property
    def best(self):
        return self.matches[0] if self.matches else None

    @property
    def confidence(self):
        """Overall confidence; two top matches at the same level are ambiguous."""
        if not self.matches:
            return UNKNOWN
        top = self.matches[0].confidence
        if len(self.matches) > 1 and self.matches[1].confidence == top:
            return AMBIGUOUS
        return top

    @property
    def asleep(self):
        return bool(self.best and self.best.rule.asleep)

    @property
    def hint(self):
        return self.best.rule.hint if self.best else ""

    def auto_profile(self):
        """Profile to start automatically, or None when a choice is needed."""
        if self.confidence in ("confirmed", "probable"):
            return self.best.profile
        return None

    def describe(self):
        device = self.device
        return {
            "id": self.id, "ids": device.ids, "serial": device.serial, "manufacturer": device.manufacturer,
            "product": device.product, "port": self.port, "usb_path": device.path,
            "confidence": self.confidence, "asleep": self.asleep,
            "matches": [{"profile": m.profile.id, "name": m.profile.name, "confidence": m.confidence}
                        for m in self.matches],
        }


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def scan_usb(sysfs=SYSFS):
    devices = []
    for entry in sorted(glob.glob(os.path.join(sysfs, "*"))):
        name = os.path.basename(entry)
        if ":" in name or name.startswith("usb"):
            continue
        vid, pid = _read(os.path.join(entry, "idVendor")), _read(os.path.join(entry, "idProduct"))
        if not vid or not pid or _read(os.path.join(entry, "authorized")) == "0":
            continue
        ttys = sorted("/dev/" + os.path.basename(t) for t in glob.glob(os.path.join(entry, "*:*", "tty", "tty*")))
        ttys += sorted("/dev/" + os.path.basename(t) for t in glob.glob(os.path.join(entry, "*:*", "tty*"))
                       if os.path.basename(t).startswith("ttyUSB"))
        hidraws = sorted("/dev/" + os.path.basename(h) for h in glob.glob(os.path.join(entry, "*:*", "*", "hidraw",
                                                                                     "hidraw*")))
        try:
            bus = int(_read(os.path.join(entry, "busnum")) or 0)
            address = int(_read(os.path.join(entry, "devnum")) or 0)
        except ValueError:
            bus = address = 0
        devices.append(UsbDevice(name, int(vid, 16), int(pid, 16), _read(os.path.join(entry, "serial")),
                                 _read(os.path.join(entry, "manufacturer")), _read(os.path.join(entry, "product")),
                                 bus, address, tuple(dict.fromkeys(ttys)), tuple(hidraws)))
    return devices


def classify(device):
    matches = []
    for profile in PROFILES:
        for rule in profile.rules:
            if rule.matches(device):
                matches.append(Match(profile, rule.confidence, rule))
                break     # first (most specific) rule of each profile
    matches.sort(key=lambda m: -CONFIDENCE_ORDER[m.confidence])
    return Candidate(device, matches)


def discover(devices=None, assigned=()):
    """Candidates for every USB device matching a family.

    Serial devices without a match are included only when the user assigned
    a family to them (``assigned`` holds their ids).
    """
    devices = scan_usb() if devices is None else devices
    result = []
    for candidate in map(classify, devices):
        if candidate.matches or (candidate.id in assigned and candidate.port):
            result.append(candidate)
    return result


def unknown_serial_devices(devices=None):
    """Serial USB devices no family recognises (for the manual assistant)."""
    devices = scan_usb() if devices is None else devices
    return [candidate for candidate in map(classify, devices) if not candidate.matches and candidate.port]


def find(candidate_id, devices=None, assigned=()):
    for candidate in discover(devices, assigned):
        if candidate.id == candidate_id:
            return candidate
    return None


def choose_profile(candidate, override="auto"):
    """Profile for a candidate, honouring a manual choice from the settings."""
    if override and override != "auto":
        profile = get(override)
        if profile is not None and (profile.transport != "serial" or candidate.port or candidate.asleep):
            return profile
    return candidate.auto_profile()


def driver_options(settings):
    """Driver options from a display's effective settings."""
    return {"size": settings.get("rev_c_size", "auto"), "led_color": settings.get("led_color", "off"),
            "sensors": True, "dc_lead_zeros": settings.get("dc_lead_zeros", True),
            "dc_rotation": int(settings.get("dc_rotation", "0") or 0)}
