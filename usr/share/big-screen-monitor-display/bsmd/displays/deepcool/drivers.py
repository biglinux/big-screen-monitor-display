"""DeepCool drivers on the shared display contract (output = telemetry).

* :class:`DeepCoolHid` - AK, AG, LS, AK PRO, AK400 PRO and LD families over
  hidraw (output reports, report id 16).
* :class:`DeepCoolMystique` - MYSTIQUE 240/360 over its vendor bulk interface
  (pyusb), in the firmware's Machine Info mode.

Both are opened, recovered and supervised by the runtime like any panel.
They only send the documented packets of their own family; nothing is sent
to a device whose identifiers do not match a family in models.py.
"""

import errno
import time

from ..base import BUSY, DISCONNECTED, IO, NOT_FOUND, PERMISSION, PROTOCOL, TIMEOUT, DeviceInfo, DisplayError, \
    TelemetryDriver, Transfer
from . import conflicts, models, protocols
from .hid import Hidraw
from .models import POWER, TEMP, USAGE


class DeepCoolBase(TelemetryDriver):
    def __init__(self, family, pid, product="", usb_path="", options=None):
        super().__init__()
        self.family = family
        self.pid = pid
        self.product = product
        self.usb_path = usb_path
        self.options = dict(options or {})
        self.DRIVER = family.id
        self.min_interval = family.min_interval
        caps = self.capabilities
        caps.transport = family.transport
        caps.metrics = family.fields
        caps.display = family.display
        caps.notes = family.notes
        self.last_frame = None

    def _info(self, extra=None):
        details = {"family": self.family.name, "protocol": self.family.protocol, "pid": f"{self.pid:04x}",
                   "product": self.product}
        found = conflicts.find_conflicts()
        if found:
            details["conflicts"] = ", ".join(c["name"] for c in found)
        details.update(extra or {})
        return DeviceInfo(self.family.id, models.model_name(self.pid, self.product), 0, 0,
                          f"usb {self.usb_path}", details)


class DeepCoolHid(DeepCoolBase):
    def __init__(self, family, pid, hidraw, product="", usb_path="", options=None):
        super().__init__(family, pid, product, usb_path, options)
        self.se = models.is_se(pid, product)
        self.hid = Hidraw(hidraw, models.VENDOR, pid)

    def open(self):
        self.hid.open()
        try:
            if self.family.id in ("deepcool_ak", "deepcool_ls"):
                self.hid.write(protocols.ak_init(self.se))
            elif self.family.id == "deepcool_ld":
                for packet in protocols.ld_init(self.options.get("dc_lead_zeros", True)):
                    self.hid.write(packet)
        except DisplayError:
            self.hid.close()
            raise
        self.info = self._info({"hidraw": self.hid.path, "se_variant": self.se})
        return self.info

    def packet(self, frame):
        family = self.family.id
        if family in ("deepcool_ak", "deepcool_ls", "deepcool_ag"):
            if frame.main is None:
                return None
            value = frame.fields[frame.main]
            if frame.main == TEMP:
                mode = protocols.MODE_TEMP_F if frame.fahrenheit else protocols.MODE_TEMP_C
            else:
                mode = protocols.MODE_SECOND      # usage (AK/AG) or power (LS)
            if family == "deepcool_ag":
                return protocols.ag_status(mode, value, frame.alarm)
            bar = frame.fields.get(USAGE + "_bar")
            if family == "deepcool_ls":
                return protocols.ls_status(mode, value, bar, frame.alarm)
            return protocols.ak_status(mode, value, bar, frame.alarm, self.se)
        fields = frame.fields
        header = {"deepcool_ak_pro": protocols.HEADER_AK_PRO, "deepcool_ak400_pro": protocols.HEADER_AK400_PRO,
                  "deepcool_ld": protocols.HEADER_LD}[family]
        freq = (fields.get(models.FREQ) or 0) if family == "deepcool_ak_pro" else None
        return protocols.structured_status(header, fields.get(POWER), fields.get(TEMP), frame.fahrenheit,
                                           fields.get(USAGE), freq)

    def present(self, frame):
        start = time.monotonic()
        data = self.packet(frame)
        if data is None:
            return Transfer(duration=0.0)
        sent = self.hid.write(data)
        self.last_frame = frame
        return Transfer(sent, 1, True, time.monotonic() - start)

    def probe(self):
        if not self.hid.alive():
            raise DisplayError(DISCONNECTED, "HID node vanished")
        return True

    def close(self):
        self.hid.close()


class DeepCoolMystique(DeepCoolBase):
    TIMEOUT_MS = 1000
    READ_MS = 200

    def __init__(self, family, pid, bus=None, address=None, product="", usb_path="", options=None):
        super().__init__(family, pid, product, usb_path, options)
        self.bus, self.address = bus, address
        self.dev = None
        self.interface = None

    @staticmethod
    def _error(error, what):
        code = getattr(error, "errno", None)
        if code in (errno.EACCES, errno.EPERM):
            return DisplayError(PERMISSION, f"{what}: no permission for the USB device", error)
        if code == errno.EBUSY:
            return DisplayError(BUSY, f"{what}: interface claimed by another program", error)
        if code in (errno.ENODEV, errno.ENOENT, errno.ESHUTDOWN):
            return DisplayError(DISCONNECTED, f"{what}: device gone", error)
        if code == errno.ETIMEDOUT:
            return DisplayError(TIMEOUT, f"{what}: timeout", error)
        return DisplayError(IO, f"{what}: {error}", error)

    def open(self):
        try:
            import usb.core
            import usb.util
        except ImportError as error:
            raise DisplayError(NOT_FOUND, "pyusb is not installed", error) from None
        self._usb = usb
        match = {}
        if self.bus is not None:
            match["custom_match"] = lambda d: (d.bus, d.address) == (self.bus, self.address)
        try:
            dev = usb.core.find(idVendor=models.VENDOR, idProduct=self.pid, **match)
        except usb.core.USBError as error:
            raise self._error(error, "find") from None
        if dev is None:
            raise DisplayError(NOT_FOUND, "MYSTIQUE not found")
        try:
            config = dev.get_active_configuration()
        except usb.core.USBError as error:
            raise self._error(error, "configuration") from None
        interface = next((i for i in config if i.bInterfaceClass == 0xFF and
                          {e.bEndpointAddress for e in i} >= {protocols.EP_INIT_OUT, protocols.EP_INIT_IN,
                                                               protocols.EP_DATA_OUT, protocols.EP_DATA_IN}), None)
        if interface is None:
            raise DisplayError(PROTOCOL, "no vendor interface with endpoints 0x01/0x81/0x02/0x82")
        number = interface.bInterfaceNumber
        try:
            if dev.is_kernel_driver_active(number):
                dev.detach_kernel_driver(number)
            usb.util.claim_interface(dev, number)
        except usb.core.USBError as error:
            raise self._error(error, "claim") from None
        self.dev, self.interface = dev, number
        try:
            for command, payload in protocols.MYSTIQUE_INIT:
                self._exchange(protocols.EP_INIT_OUT, protocols.EP_INIT_IN, protocols.mystique_packet(command, payload))
                time.sleep(0.01)
            time.sleep(0.09)
            rotation = int(self.options.get("dc_rotation", 0) or 0)
            if rotation:
                self._exchange(protocols.EP_INIT_OUT, protocols.EP_INIT_IN, protocols.mystique_rotation(rotation))
        except DisplayError:
            self.close()
            raise
        self.info = self._info({"interface": number, "rotation": rotation, "mode": "machine info"})
        return self.info

    def _exchange(self, out_ep, in_ep, packet):
        try:
            written = self.dev.write(out_ep, packet, self.TIMEOUT_MS)
        except self._usb.core.USBError as error:
            raise self._error(error, "write") from None
        if written != len(packet):
            raise DisplayError(IO, f"short write ({written}/{len(packet)})")
        try:
            self.dev.read(in_ep, 64, self.READ_MS)        # responses are not interpreted (see docs)
        except self._usb.core.USBTimeoutError:
            pass
        except self._usb.core.USBError as error:
            if getattr(error, "errno", None) != errno.ETIMEDOUT:
                raise self._error(error, "read") from None
        return written

    def present(self, frame):
        start = time.monotonic()
        fields = frame.fields
        sent = self._exchange(protocols.EP_DATA_OUT, protocols.EP_DATA_IN,
                              protocols.mystique_packet(protocols.CMD_STATUS))
        sent += self._exchange(protocols.EP_DATA_OUT, protocols.EP_DATA_IN, protocols.mystique_display(
            fields.get(TEMP), fields.get(USAGE), fields.get(models.RAM), fields.get(models.GPU_TEMP),
            fields.get(models.FREQ)))
        self.last_frame = frame
        return Transfer(sent, 1, True, time.monotonic() - start)

    def probe(self):
        if self.dev is None:
            raise DisplayError(DISCONNECTED, "not open")
        return True

    def close(self):
        dev, self.dev = self.dev, None
        if dev is None:
            return
        try:
            self._usb.util.release_interface(dev, self.interface)
            self._usb.util.dispose_resources(dev)
        except Exception:  # noqa: BLE001 - best effort on close
            pass


def create(family_id, device, options=None):
    """Driver for a discovered USB device (bsmd.displays.discovery.UsbDevice)."""
    family = models.FAMILIES[family_id]
    if family.transport == "usb":
        return DeepCoolMystique(family, device.pid, device.bus or None, device.address or None, device.product,
                                device.path, options)
    hidraw = device.hidraws[0] if getattr(device, "hidraws", ()) else ""
    return DeepCoolHid(family, device.pid, hidraw, device.product, device.path, options)
