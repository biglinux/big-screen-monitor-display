"""LED colours through the OpenRGB command line (optional).

The digital DeepCool coolers take no colour over their own USB link: their ARGB
strip is wired to a motherboard (or controller) header that OpenRGB drives.
Rules kept here:

* nothing happens until the user picks one OpenRGB device in the tray; no other
  device is touched (``-d`` is always given; OpenRGB without ``-d`` changes all);
* the device is matched by name before every change (indexes can shift);
* zones are never resized and nothing is written to OpenRGB profiles;
* the CLI is run without ``--noautoconnect``, so when the OpenRGB server is
  running it does the work (two programs probing SMBus at once is avoided);
* the colour lives in the tray's own file, never in the service settings
  (``led_color`` there belongs to the screens' backplate LEDs).
"""

import logging
import re
import shutil
import subprocess

log = logging.getLogger("bsmd.deepcool.openrgb")

PRESETS = (("red", "#FF0000"), ("orange", "#FF6600"), ("yellow", "#FFCC00"), ("green", "#00CC44"),
           ("cyan", "#00CCCC"), ("blue", "#0066FF"), ("purple", "#9933FF"), ("pink", "#FF33AA"),
           ("white", "#FFFFFF"))
RAINBOW = "rainbow"
OFF = "off"
RAINBOW_MODES = ("rainbow", "rainbow wave", "spectrum cycle", "color cycle", "colour cycle", "cycle")
STATIC_MODES = ("static", "direct")
HEX = re.compile(r"^#?[0-9A-Fa-f]{6}$")
TIMEOUT = 30


class Device:
    def __init__(self, index, name, modes=(), kind=""):
        self.index, self.name, self.modes, self.kind = index, name, tuple(modes), kind

    def mode(self, wanted):
        lowered = {m.lower(): m for m in self.modes}
        for name in wanted:
            if name in lowered:
                return lowered[name]
        return None

    def __repr__(self):
        return f"Device({self.index}, {self.name!r})"


def available():
    return shutil.which("openrgb") is not None


def _run(args):
    try:
        result = subprocess.run(["openrgb", *args], capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        return False, "OpenRGB is not installed"
    except subprocess.TimeoutExpired:
        return False, f"OpenRGB did not answer in {TIMEOUT} s"
    except OSError as error:
        return False, str(error)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[-300:]
    return True, result.stdout


def _tokens(text):
    """Mode names: ``[Current]``, ``'Two Words'`` or plain words."""
    return [next(group for group in match if group) for match in re.findall(r"\[([^\]]+)\]|'([^']+)'|(\S+)", text)]


def parse_devices(text):
    """Devices of ``openrgb --list-devices`` output (index, name, modes, type)."""
    devices, current = [], None
    for raw in text.splitlines():
        match = re.match(r"^(\d+):\s+(.+?)\s*$", raw)
        if match:
            current = Device(int(match.group(1)), match.group(2))
            devices.append(current)
            continue
        if current is None:
            continue
        line = raw.strip()
        if line.lower().startswith("modes:"):
            current.modes = tuple(_tokens(line[6:]))
        elif line.lower().startswith("type:"):
            current.kind = line[5:].strip()
    return devices


def list_devices():
    ok, output = _run(["--list-devices"])
    if not ok:
        log.warning("openrgb --list-devices failed: %s", output)
        return []
    return parse_devices(output)


def resolve(name, index=None):
    """The device called ``name`` now (``index`` only breaks ties)."""
    devices = [d for d in list_devices() if d.name == name]
    if not devices:
        return None
    if index is not None:
        for device in devices:
            if device.index == index:
                return device
    return devices[0]


def apply(colour, name, index=None):
    """Apply ``colour`` (``#RRGGBB``, ``"rainbow"`` or ``"off"``) to one device.
    Returns ``(ok, message)``."""
    if not name:
        return False, "no OpenRGB device chosen"
    if colour not in (RAINBOW, OFF) and not HEX.match(colour or ""):
        return False, f"invalid colour {colour!r}"
    device = resolve(name, index)
    if device is None:
        return False, f"OpenRGB device {name!r} not found"
    args = ["--device", str(device.index)]
    if colour == RAINBOW:
        mode = device.mode(RAINBOW_MODES)
        if mode is None:
            return False, "this device has no rainbow effect"
        args += ["--mode", mode]
    else:
        mode = device.mode(STATIC_MODES)
        if mode:
            args += ["--mode", mode]
        args += ["--color", "000000" if colour == OFF else colour.lstrip("#").upper()]
    ok, output = _run(args)
    if ok:
        log.info("OpenRGB: %s -> %s", colour, device.name)
        return True, ""
    return False, output
