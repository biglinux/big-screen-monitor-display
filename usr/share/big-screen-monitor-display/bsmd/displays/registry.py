"""Display families: identifiers, drivers, capabilities and validation status.

Each profile lists match rules on USB identifiers only. Identification never
writes to a device; a family handshake runs later, in ``open()``, and only
for the family the identifiers point to.

Validation classes (docs/11-compatibilidade-hardware.md):
A - validated on real hardware, B - driver implemented and verified against
reference byte streams/mocks, real hardware pending, C - protocol known,
implementation in progress, D - under investigation, E - not supported.
"""

from dataclasses import dataclass, field

from ..i18n import N_

CONFIRMED, PROBABLE, AMBIGUOUS, UNKNOWN = "confirmed", "probable", "ambiguous", "unknown"
CONFIDENCE_ORDER = {CONFIRMED: 3, PROBABLE: 2, AMBIGUOUS: 1, UNKNOWN: 0}


@dataclass(frozen=True)
class Rule:
    vid: int
    pids: tuple
    confidence: str
    serial: tuple = ()           # exact serial numbers
    serial_prefix: tuple = ()
    asleep: bool = False         # rev. C panels sleep until their port is opened
    hint: str = ""               # e.g. panel size implied by the identifiers

    def matches(self, device):
        if (self.vid is not None and device.vid != self.vid) or (self.pids and device.pid not in self.pids):
            return False
        if self.serial and device.serial not in self.serial:
            return False
        if self.serial_prefix and not (device.serial or "").startswith(self.serial_prefix):
            return False
        return True


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    vendor: str
    models: tuple
    resolutions: str
    protocol: str
    transport: str              # serial or usb
    rules: tuple
    validation: str
    reference: str
    options: tuple = ()         # per-display options this family needs
    notes: tuple = field(default_factory=tuple)

    def create(self, candidate, options=None):
        """Build an unopened driver for ``candidate``."""
        options = dict(options or {})
        if self.id == "ax206":
            from .ax206 import AX206
            device = candidate.device
            return AX206(bus=device.bus or None, address=device.address or None)
        if self.id == "turing_usb":
            from .turing_usb import TuringUSB
            device = candidate.device
            return TuringUSB(pid=device.pid, bus=device.bus, address=device.address, options=options)
        port = candidate.port
        if self.id == "turing_rev_a":
            from .turing_serial import TuringRevA
            return TuringRevA(port, options=options)
        if self.id == "xuanfang_rev_b":
            from .xuanfang import XuanFangRevB
            return XuanFangRevB(port, options=options)
        if self.id == "turing_rev_c":
            from .turing_serial import TuringRevC
            if options.get("size", "auto") == "auto" and candidate.hint:
                options["size"] = candidate.hint
            return TuringRevC(port, options=dict(options, size=options.get("size") or "auto"))
        if self.id == "kipye_rev_d":
            from .kipye import KipyeRevD
            return KipyeRevD(port, options=options)
        if self.id == "weact_a":
            from .weact import WeActA
            return WeActA(port, options=options)
        if self.id == "weact_b":
            from .weact import WeActB
            return WeActB(port, options=options)
        if self.id.startswith("deepcool_"):
            from .deepcool import drivers as deepcool_drivers
            return deepcool_drivers.create(self.id, candidate.device, options)
        raise ValueError(f"no driver for {self.id}")


REF = "https://github.com/mathoudebine/turing-smart-screen-python"
QINHENG = 0x1A86
LINUX_GADGET = (0x0525, 0x1D6B)

PROFILES = (
    Profile("ax206", "AX206 DPF (AIDA64 / USB-Display)", "Appotech AX206 based frames",
            ("AX206 3.5\"", "AX206 5\"", "USB-Display"), N_("reported by the device (320x240, 480x320, 800x480...)"),
            "dpf-ax SCSI over bulk", "usb",
            (Rule(0x1908, (0x0102,), CONFIRMED),),
            "A", "https://github.com/dreamlayers/dpf-ax",
            notes=(N_("Partial updates; validated on real hardware."),)),
    Profile("turing_rev_a", "Turing Smart Screen 3.5\" / UsbPCMonitor", "Turing / TURZX, UsbPCMonitor",
            ("Turing 3.5\" (rev. A)", "UsbPCMonitor 3.5\"", "UsbPCMonitor 5\"", "UsbPCMonitor 7\""),
            "320x480, 480x800, 600x1024", "rev. A serial, RGB565 LE", "serial",
            (Rule(QINHENG, (0x5722,), CONFIRMED, serial=("USB35INCHIPSV2",)),
             Rule(QINHENG, (0x5722,), PROBABLE)),
            "B", REF, notes=(N_("Shares 1a86:5722 with XuanFang rev. B; the serial number tells them apart."),)),
    Profile("xuanfang_rev_b", "XuanFang 3.5\" rev. B / flagship", "XuanFang",
            ("XuanFang 3.5\" rev. B", "XuanFang 3.5\" flagship (RGB LEDs)"), "320x480",
            "rev. B serial, RGB565 BE", "serial",
            (Rule(QINHENG, (0x5722,), CONFIRMED, serial=("2017-2-25",)),
             Rule(QINHENG, (0x5722,), AMBIGUOUS)),
            "B", REF, options=("led_color",),
            notes=(N_("Backplate LEDs and fine brightness depend on the sub-revision reported by the panel."),)),
    Profile("turing_rev_c", "Turing Smart Screen 2.1\"/2.8\"/5\"/8.8\" (rev. C)", "Turing / TURZX",
            ("Turing 2.1\"", "Turing 2.8\"", "Turing 5\"", "Turing 8.8\" (rev. C)"),
            "480x480, 480x800, 480x1920", "rev. C serial, BGRA", "serial",
            (Rule(None, (), CONFIRMED, serial=("CT21INCH",), asleep=True, hint="2.1"),
             Rule(None, (), CONFIRMED, serial=("CT88INCH",), asleep=True, hint="8.8"),
             Rule(None, (), CONFIRMED, serial=("USB7INCH",), asleep=True, hint="5"),
             Rule(QINHENG, (0xCA21,), PROBABLE, asleep=True),
             Rule(LINUX_GADGET[0], (0xA4A7,), PROBABLE, serial=("20080411",)),
             Rule(LINUX_GADGET[1], (0x0121, 0x0106), PROBABLE, serial=("20080411",))),
            "B", REF, options=("size",),
            notes=(N_("Sleeps until opened and then reappears as a generic USB gadget; the size may need to be chosen."),)),
    Profile("kipye_rev_d", "Kipye Qiye Smart Display 3.5\"", "Kipye / Qiye",
            ("Kipye Qiye Smart Display 3.5\"",), "320x480", "rev. D serial, RGB565 BE", "serial",
            (Rule(0x454D, (0x4E41,), PROBABLE),),
            "B", REF, notes=(N_("The protocol has no handshake: identification relies on the USB IDs."),)),
    Profile("weact_a", "WeAct Studio Display FS V1 3.5\"", "WeAct Studio",
            ("WeAct Display FS V1 3.5\"",), "320x480", "WeAct serial, RGB565 LE", "serial",
            (Rule(QINHENG, (0xFE0C,), CONFIRMED, serial_prefix=("AB",)),
             Rule(QINHENG, (0xFE0C,), PROBABLE)),
            "B", REF, notes=(N_("Also reports room temperature and humidity."),)),
    Profile("weact_b", "WeAct Studio Display FS V1 0.96\"", "WeAct Studio",
            ("WeAct Display FS V1 0.96\"",), "80x160", "WeAct serial, RGB565 LE", "serial",
            (Rule(QINHENG, (0xFE0C,), CONFIRMED, serial_prefix=("AD",)),
             Rule(QINHENG, (0xFE0C,), PROBABLE)),
            "B", REF, notes=(N_("Tiny panel: themes switch to a compact layout."),)),
    Profile("turing_usb", "Turing Smart Screen USB (2.8\" round, 4.6\", 5.2\", 8\", 8.8\", 9.2\", 12.3\")",
            "Turing / TURZX", ("Turing 2.8\" round", "Turing 4.6\"", "Turing 5.2\"", "Turing 8.0\"",
                               "Turing 8.8\" (USB)", "Turing 9.2\"", "Turing 12.3\""),
            "480x480, 320x960, 720x1280, 800x1280, 480x1920, 462x1920, 720x1920",
            "native USB, DES header + PNG/JPEG", "usb",
            (Rule(0x1CBE, (0x0028, 0x0046, 0x0050, 0x0080, 0x0088, 0x0092, 0x0123), PROBABLE),),
            "B", REF, notes=(N_("Whole frames only (PNG, JPEG when larger than 1 MB); no video or storage functions."),)),
)


def _deepcool_profiles():
    from .deepcool import models
    result = []
    for family in models.FAMILIES.values():
        names = tuple(name for m in models.MODELS if m.family == family.id for name in m.names)
        transport = "usb" if family.transport == "usb" else "hid"
        result.append(Profile(family.id, f"DeepCool {family.name}", "DeepCool", names,
                              N_("numeric CPU display") if family.display == "segment" else
                              N_("2.8\" LCD, information mode"), family.protocol, transport,
                              (Rule(models.VENDOR, models.SUPPORTED_PIDS[family.id], CONFIRMED),), "B",
                              "https://github.com/Nortank12/deepcool-digital-linux" if transport == "hid" else
                              "https://github.com/dinoyoshi/serial-lcd-panel-client",
                              options=("dc_lead_zeros",) if family.id == "deepcool_ld" else
                              (("dc_rotation",) if transport == "usb" else ()),
                              notes=family.notes))
    return tuple(result)


PROFILES = PROFILES + _deepcool_profiles()
BY_ID = {profile.id: profile for profile in PROFILES}
LEGACY_MODELS = {"turing": "turing_rev_a"}


def get(profile_id):
    return BY_ID.get(LEGACY_MODELS.get(profile_id, profile_id))
