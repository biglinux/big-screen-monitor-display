"""Android Open Accessory (AOA): a phone on a USB cable, without USB debugging.

Two steps, on two sides (docs/android/05-conexao-usb.md):

1. **Switch** (user session: the configuration window or the screen tray, which
   reach the phone through ``uaccess``): vendor requests 51 (protocol), 52
   (identification strings) and 53 (start) ask the phone to re-enumerate as an
   accessory (Google ``18d1:2d00``/``2d01``). Android then offers to open the
   app that declared these strings (``android/app/src/main/res/xml/accessory_filter.xml``).
   Only phones the user picks in the window, or phones already paired over USB
   (remembered by a hash of their serial number), are ever asked.
2. **Link** (service): the accessory-mode device belongs to the
   ``big-screen-monitor`` group (udev); :class:`AccessoryWatcher` claims its bulk
   endpoints and bridges them to a socket pair, so the same :class:`~.link.Link`,
   handshake and token authentication as on the network apply (no TLS: the cable
   is the channel).

The service never sends AOA requests itself and never touches a phone that is
not already in accessory mode.
"""

import glob
import hashlib
import logging
import os
import socket
import threading
import time

from ..base import DisplayError, IO

log = logging.getLogger("bsmd")

GOOGLE_VID = 0x18D1
ACCESSORY_PIDS = (0x2D00, 0x2D01)                 # accessory, accessory + adb
GET_PROTOCOL, SEND_STRING, START = 51, 52, 53
STRINGS = ("BigLinux", "BigScreenMonitorDisplay", "Big Screen Monitor Display", "1",
           "https://github.com/ruscher/big-screen-monitor-display", "bsmd")
# Interfaces an Android phone exposes in its usual USB modes.
MTP = ("06", "01", "01")
ADB = ("ff", "42", "01")
PTP = ("06", "01", "01")
SYSFS = os.environ.get("BSM_SYSFS", "/sys/bus/usb/devices")


def serial_hash(serial):
    """What is remembered of a phone's USB serial number (never the number itself)."""
    return hashlib.sha256(("bsmd-usb:" + (serial or "")).encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ session side: find and switch

def _read(path, name):
    try:
        with open(os.path.join(path, name), encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def android_phones(sysfs=None):
    """USB devices that look like Android phones in their usual mode (MTP/PTP or adb
    interface), never displays or accessories already switched. Read-only sysfs."""
    sysfs = sysfs or SYSFS
    phones = []
    for path in sorted(glob.glob(os.path.join(sysfs, "[0-9]*-[0-9]*"))):
        name = os.path.basename(path)
        if ":" in name:
            continue
        vid, pid = _read(path, "idVendor"), _read(path, "idProduct")
        if not vid or (vid == f"{GOOGLE_VID:04x}" and int(pid or "0", 16) in ACCESSORY_PIDS):
            continue
        interfaces = set()
        for iface in glob.glob(os.path.join(path, f"{name}:*")):
            interfaces.add((_read(iface, "bInterfaceClass"), _read(iface, "bInterfaceSubClass"),
                            _read(iface, "bInterfaceProtocol")))
            if _read(iface, "interface") == "MTP":
                interfaces.add(MTP)
        if not interfaces & {MTP, ADB, PTP}:
            continue
        phones.append({"path": name, "vid": int(vid, 16), "pid": int(pid, 16),
                       "bus": int(_read(path, "busnum") or 0), "address": int(_read(path, "devnum") or 0),
                       "serial": _read(path, "serial"), "manufacturer": _read(path, "manufacturer"),
                       "product": _read(path, "product")})
    return phones


def switch_to_accessory(phone, usb_core=None, strings=STRINGS):
    """Ask ``phone`` (from :func:`android_phones`) to become our accessory.
    Returns the AOA protocol version; raises DisplayError when it cannot."""
    if usb_core is None:
        import usb.core as usb_core
    device = usb_core.find(idVendor=phone["vid"], idProduct=phone["pid"],
                           custom_match=lambda d: (d.bus, d.address) == (phone["bus"], phone["address"]))
    if device is None:
        raise DisplayError("not_found", "the phone is no longer connected")
    try:
        data = device.ctrl_transfer(0xC0, GET_PROTOCOL, 0, 0, 2, timeout=1000)
        version = int(data[0]) | int(data[1]) << 8 if len(data) >= 2 else 0
        if version < 1:
            raise DisplayError(IO, "this device does not support USB accessories")
        for index, text in enumerate(strings):
            device.ctrl_transfer(0x40, SEND_STRING, 0, index, text.encode("utf-8") + b"\0", timeout=1000)
        device.ctrl_transfer(0x40, START, 0, 0, None, timeout=1000)
    except DisplayError:
        raise
    except Exception as error:  # noqa: BLE001 - USBError, permission, stalls
        raise DisplayError(IO, f"the phone refused the accessory mode: {error}", error) from error
    finally:
        try:
            usb_core.util.dispose_resources(device)
        except Exception:  # noqa: BLE001
            pass
    log.info("android: %s %s asked to open the app (AOA %d)", phone.get("manufacturer"), phone.get("product"),
             version)
    return version


class AutoSwitcher:
    """Session side (screen tray): phones already paired over USB become displays
    again when plugged in, without opening the window. One attempt per plug."""

    def __init__(self, sysfs=None, switch=switch_to_accessory, clock=time.monotonic):
        self.sysfs = sysfs
        self.switch = switch
        self.clock = clock
        self.tried = {}

    def step(self, android_status, enabled=True):
        if not enabled or not android_status:
            return []
        known = {entry.get("usb") for entry in android_status.get("paired") or [] if entry.get("usb")}
        if not known:
            return []
        switched = []
        now = self.clock()
        for phone in android_phones(self.sysfs):
            key = (phone["path"], phone["serial"])
            if serial_hash(phone["serial"]) not in known or now - self.tried.get(key, -1e9) < 60.0:
                continue
            self.tried[key] = now
            try:
                self.switch(phone)
                switched.append(phone)
            except DisplayError as error:
                log.info("android: %s: %s", phone.get("product"), error)
        return switched


# ------------------------------------------------------------------ service side: accessory links

class AccessoryBridge:
    """Bulk endpoints of an accessory-mode phone <-> one end of a socket pair."""

    READ_SIZE = 16384

    def __init__(self, device, usb_core, usb_util, interface=0):
        self.device = device
        self.core = usb_core
        self.util = usb_util
        self.interface = interface
        self.ours, self.theirs = socket.socketpair()
        self.running = False
        self.threads = []
        self.ep_in = self.ep_out = None

    def open(self):
        device = self.device
        try:
            if device.is_kernel_driver_active(self.interface):
                device.detach_kernel_driver(self.interface)
        except Exception:  # noqa: BLE001 - not supported everywhere
            pass
        device.set_configuration()
        config = device.get_active_configuration()
        intf = config[(self.interface, 0)]
        self.util.claim_interface(device, self.interface)
        direction = self.util.endpoint_direction
        self.ep_in = self.util.find_descriptor(intf, custom_match=lambda e: direction(e.bEndpointAddress) ==
                                               self.util.ENDPOINT_IN)
        self.ep_out = self.util.find_descriptor(intf, custom_match=lambda e: direction(e.bEndpointAddress) ==
                                                self.util.ENDPOINT_OUT)
        if self.ep_in is None or self.ep_out is None:
            raise DisplayError(IO, "accessory without bulk endpoints")
        self.running = True
        for target, name in ((self._usb_to_socket, "aoa-in"), (self._socket_to_usb, "aoa-out")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self.ours

    def _usb_to_socket(self):
        timeout_error = getattr(self.core, "USBTimeoutError", ())
        while self.running:
            try:
                data = self.ep_in.read(self.READ_SIZE, timeout=500)
            except timeout_error:
                continue
            except Exception:  # noqa: BLE001 - unplugged
                break
            if data:
                try:
                    self.theirs.sendall(bytes(data))
                except OSError:
                    break
        self.close()

    def _socket_to_usb(self):
        self.theirs.settimeout(0.5)
        while self.running:
            try:
                data = self.theirs.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                break
            try:
                for start in range(0, len(data), self.READ_SIZE):
                    self.ep_out.write(data[start:start + self.READ_SIZE], timeout=3000)
            except Exception:  # noqa: BLE001
                break
        self.close()

    def close(self):
        if not self.running and not self.threads:
            return
        self.running = False
        for sock in (self.theirs,):
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        try:
            self.util.release_interface(self.device, self.interface)
            self.util.dispose_resources(self.device)
        except Exception:  # noqa: BLE001
            pass
        self.threads = []


class AccessoryWatcher:
    """Service side: adopts phones that switched to accessory mode (hot-plug scan)."""

    EVERY = 1.0

    def __init__(self, hub, scan=None, usb_core=None, usb_util=None, clock=time.monotonic):
        self.hub = hub
        self.scan = scan
        self.usb_core = usb_core
        self.usb_util = usb_util
        self.clock = clock
        self.bridges = {}            # usb path -> AccessoryBridge
        self.last = -1e9
        self.error = None

    def step(self, settings):
        now = self.clock()
        if now - self.last < self.EVERY:
            return
        self.last = now
        for path, bridge in list(self.bridges.items()):
            if not bridge.running:
                del self.bridges[path]
        if not settings.get("android_usb", True):
            return
        devices = (self.scan or _scan_usb)()
        for device in devices:
            if device.vid != GOOGLE_VID or device.pid not in ACCESSORY_PIDS or device.path in self.bridges:
                continue
            self._adopt(device)

    def _adopt(self, info):
        from .link import Link
        try:
            core = self.usb_core
            util = self.usb_util
            if core is None or util is None:
                import usb.core as core
                import usb.util as util
            device = core.find(idVendor=info.vid, idProduct=info.pid,
                               custom_match=lambda d: (d.bus, d.address) == (info.bus, info.address))
            if device is None:
                return
            bridge = AccessoryBridge(device, core, util)
            sock = bridge.open()
        except Exception as error:  # noqa: BLE001 - permission, busy, unplugged
            message = f"USB accessory {info.path}: {error}"
            if message != self.error:
                self.error = message
                log.warning("android: %s", message)
            return
        self.error = None
        self.bridges[info.path] = bridge
        link = Link(sock, transport="usb-accessory", address=f"usb:{info.path}", tls=False, clock=self.clock)
        link.usb_hash = serial_hash(info.serial)
        link.start()
        log.info("android: phone on USB %s in accessory mode", info.path)
        self.hub.adopt(link)

    def stop(self):
        for bridge in self.bridges.values():
            bridge.close()
        self.bridges.clear()


def _scan_usb():
    from ..discovery import scan_usb
    return scan_usb()
