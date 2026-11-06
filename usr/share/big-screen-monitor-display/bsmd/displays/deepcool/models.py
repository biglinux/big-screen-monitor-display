"""DeepCool digital devices: identifiers, protocol family and what each one can show.

One table drives detection, the drivers, the configuration window and the
compatibility matrix. Product IDs come from the community device lists
(Nortank12/deepcool-digital-linux ``device-list``, qt-deepcool udev rules);
``community`` records what *those* projects report, ``validation`` what
this project has verified (B = implemented and checked against the
documented byte streams with automated tests; A would need our own test on
real hardware, which none of these has had yet).
"""

from dataclasses import dataclass

from ...i18n import N_

VENDOR = 0x3633

TEMP, USAGE, POWER, FREQ, RAM, GPU_TEMP = "temp", "usage", "power", "freq", "ram", "gpu_temp"
METRIC_LABELS = {TEMP: N_("CPU temperature"), USAGE: N_("CPU usage"), POWER: N_("CPU power"),
                 FREQ: N_("CPU frequency"), RAM: N_("Memory usage"), GPU_TEMP: N_("GPU temperature")}
METRIC_UNITS = {TEMP: "°C", USAGE: "%", POWER: "W", FREQ: "MHz", RAM: "%", GPU_TEMP: "°C"}


@dataclass(frozen=True)
class Family:
    id: str
    name: str
    protocol: str
    transport: str             # hid (hidraw) or usb (vendor bulk)
    layout: str                # single: one switchable field; fixed: firmware shows every field
    fields: tuple              # metrics the firmware can show, in physical order
    main_choices: tuple = ()   # single-field families: what the main field may show
    digits: int = 3
    fahrenheit: bool = True
    status_bar: bool = False   # 10-step CPU usage bar
    software_alarm: bool = False   # alarm lamp driven by us (threshold is ours)
    firmware_alarm: str = ""   # fixed thresholds of the firmware, for the interface
    min_interval: float = 0.5
    display: str = "segment"   # segment (numeric) or lcd (graphic panel in information mode)
    notes: tuple = ()


AK = Family("deepcool_ak", "AK DIGITAL", "HID report 16: mode, bar, 3 BCD digits, alarm", "hid", "single",
            (TEMP, USAGE), (TEMP, USAGE), 3, True, True, True,
            notes=(N_("One three-digit field (temperature or usage), a 10-step usage bar and an alarm lamp."),
                   N_("SE variants send the same data without the HID report id; detected from the product name.")))
AG = Family("deepcool_ag", "AG DIGITAL", "HID report 16: mode, 2 BCD digits, alarm", "hid", "single",
            (TEMP, USAGE), (TEMP, USAGE), 2, False, False, True,
            notes=(N_("Two digits only (99 is the highest value shown); Celsius only; no usage bar."),))
LS = Family("deepcool_ls", "LS SE DIGITAL", "HID report 16: mode, bar, 3 BCD digits, alarm", "hid", "single",
            (TEMP, POWER), (TEMP, POWER), 3, True, True, True,
            notes=(N_("One field that shows temperature or power, plus a 10-step usage bar."),))
AK_PRO = Family("deepcool_ak_pro", "AK500/AK620 DIGITAL PRO", "HID structured: u16 power, f32 temp, usage, "
                "u16 MHz, checksum", "hid", "fixed", (POWER, TEMP, USAGE, FREQ), (), 3, True, False, False,
                N_("warning at 80 °C, limit at 90 °C (fixed by the firmware)"),
                notes=(N_("The firmware shows power, temperature, usage and frequency; their layout cannot be "
                          "changed."),))
AK400_PRO = Family("deepcool_ak400_pro", "AK400 DIGITAL PRO", "HID structured: u16 power, f32 temp, usage, "
                   "checksum", "hid", "fixed", (POWER, TEMP, USAGE), (), 3, True, False, False,
                   N_("warning at 80 °C, limit at 90 °C (fixed by the firmware)"),
                   notes=(N_("The firmware shows power, temperature and usage; no frequency field."),))
LD = Family("deepcool_ld", "LD240/LD360", "HID structured: u16 power, f32 temp, usage, checksum", "hid", "fixed",
            (POWER, TEMP, USAGE), (), 3, True, False, False, N_("limit at 85 °C (fixed by the firmware)"),
            notes=(N_("The firmware shows power, temperature and usage; leading zeros can be shown or hidden."),))
MYSTIQUE = Family("deepcool_mystique", "MYSTIQUE 240/360", "USB vendor bulk, 48-byte AA 2E frames, Machine Info "
                  "mode", "usb", "fixed", (TEMP, USAGE, RAM, GPU_TEMP, FREQ), (), 3, False, False, False,
                  N_("ring colour follows the CPU temperature (thresholds in the firmware)"), min_interval=1.0,
                  display="lcd",
                  notes=(N_("2.8\" LCD (480×640) in its native information mode: CPU temperature, usage and "
                            "clock, memory usage and GPU temperature; rotation in 90° steps."),
                         N_("Custom images and GIFs are not sent: the transfer writes to the cooler's permanent "
                            "memory and is known to leave it unable to return to the information mode.")))
FAMILIES = {family.id: family for family in (AK, AG, LS, AK_PRO, AK400_PRO, LD, MYSTIQUE)}


@dataclass(frozen=True)
class Model:
    pid: int
    names: tuple
    family: str                # family id, or "" when this project does not drive it
    community: str             # what the reference projects report
    note: str = ""


# Status in the reference projects: "supported" (reported working by its users),
# "partial", "hardware-confirmed" (byte-level protocol checked on a real unit),
# "investigation" (identifiers known, protocol not implemented here).
MODELS = (
    Model(0x0001, ("AK400 DIGITAL", "AK400 DIGITAL SE"), "deepcool_ak", "supported"),
    Model(0x0002, ("AK620 DIGITAL", "AK620 DIGITAL SE"), "deepcool_ak", "supported"),
    Model(0x0003, ("AK500 DIGITAL",), "deepcool_ak", "supported"),
    Model(0x0004, ("AK500S DIGITAL", "AK500S DIGITAL SE"), "deepcool_ak", "supported"),
    Model(0x0005, ("CH560 DIGITAL",), "", "supported", N_("Case display: protocol not implemented here yet.")),
    Model(0x0006, ("LS520 SE DIGITAL", "LS720 SE DIGITAL"), "deepcool_ls", "supported"),
    Model(0x0007, ("MORPHEUS",), "", "supported", N_("Case display: protocol not implemented here yet.")),
    Model(0x0008, ("AG400 DIGITAL", "AG620 DIGITAL", "AG300 DIGITAL", "AG500 DIGITAL"), "deepcool_ag", "supported"),
    Model(0x0009, ("MYSTIQUE 240", "MYSTIQUE 360"), "deepcool_mystique", "hardware-confirmed",
          N_("Information mode and rotation confirmed on a MYSTIQUE 240 by the reference project.")),
    Model(0x000A, ("LD240", "LD360"), "deepcool_ld", "supported"),
    Model(0x000C, ("LP240", "LP360"), "", "partial", N_("Pixel-matrix protocol not implemented here yet.")),
    Model(0x000D, ("LQ240", "LQ360"), "", "supported", N_("Protocol not implemented here yet.")),
    Model(0x000F, ("ASSASSIN IV VC VISION",), "", "supported", N_("Protocol not implemented here yet.")),
    Model(0x0010, ("AK400 DIGITAL PRO",), "deepcool_ak400_pro", "supported"),
    Model(0x0011, ("AK500 DIGITAL PRO",), "deepcool_ak_pro", "supported"),
    Model(0x0012, ("AK620 DIGITAL PRO",), "deepcool_ak_pro", "supported"),
    Model(0x0013, ("CH170 DIGITAL",), "", "partial", N_("Case display: protocol not implemented here yet.")),
    Model(0x0015, ("CH360 DIGITAL",), "", "supported", N_("Case display: protocol not implemented here yet.")),
    Model(0x0016, ("CH270 DIGITAL",), "", "partial", N_("Case display: protocol not implemented here yet.")),
    Model(0x001B, ("CH690 DIGITAL",), "", "partial", N_("Case display: protocol not implemented here yet.")),
    Model(0x001F, ("ASSASSIN IV VC VISION",), "", "supported", N_("Protocol not implemented here yet.")),
    Model(0x0029, ("AK620 G2 DIGITAL NYX",), "", "supported", N_("Protocol not implemented here yet.")),
    Model(0x002A, ("AK700 DIGITAL NYX",), "", "supported", N_("Protocol not implemented here yet.")),
    Model(0x002B, ("AK400 G2 DIGITAL NYX",), "", "supported", N_("Protocol not implemented here yet.")),
    Model(0x002C, ("AK500 G2 DIGITAL NYX",), "", "supported", N_("Protocol not implemented here yet.")),
)
BY_PID = {model.pid: model for model in MODELS}
SUPPORTED_PIDS = {family_id: tuple(m.pid for m in MODELS if m.family == family_id) for family_id in FAMILIES}


def model_for(pid):
    return BY_PID.get(pid)


def family_for(pid):
    model = BY_PID.get(pid)
    return FAMILIES.get(model.family) if model and model.family else None


def model_name(pid, product=""):
    """Best human name: the variant named in the USB product string, else the PID's first name."""
    model = BY_PID.get(pid)
    if model is None:
        return f"DeepCool {pid:04x}"
    text = (product or "").upper().replace("-", " ").replace("_", " ")
    for name in model.names:
        if name.replace("-", " ") in text:
            return name
    if pid in (0x0001, 0x0002, 0x0004) and product and not product.upper().startswith("AK"):
        return model.names[-1]                    # "A400" style product names are the SE variants
    return model.names[0]


def is_se(pid, product):
    """AK DIGITAL SE units report e.g. "A400" instead of "AK400" and omit the HID report id."""
    return pid in SUPPORTED_PIDS["deepcool_ak"] and bool(product) and not product.upper().startswith("AK")
