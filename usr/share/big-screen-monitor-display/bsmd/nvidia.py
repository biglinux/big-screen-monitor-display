"""NVIDIA GPUs through NVML (``libnvidia-ml.so.1``, shipped with the driver).

The proprietary driver exposes neither ``gpu_busy_percent`` nor a hwmon node,
so without NVML an NVIDIA card shows no usage and no temperature. NVML is read
in-process with ctypes: microseconds per call, no ``nvidia-smi`` process every
second and no new dependency. Everything degrades to "not available": no
library, no driver loaded or a sandbox without ``/dev/nvidia*`` leave the card
as it was.
"""

import ctypes
import logging
import threading

log = logging.getLogger("bsmd.nvidia")

LIBRARY = "libnvidia-ml.so.1"
SUCCESS = 0
TEMPERATURE_GPU = 0
CLOCK_GRAPHICS = 0


class _Utilization(ctypes.Structure):
    _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]


class _Memory(ctypes.Structure):
    _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]


class NVML:
    """One NVML session; ``read(pci_slot)`` returns the numbers of that card or None."""

    def __init__(self, loader=None):
        self._loader = loader or (lambda: ctypes.CDLL(LIBRARY))
        self._lib = None
        self._failed = False
        self._handles = {}
        self._lock = threading.Lock()

    def _ensure(self):
        if self._lib is not None or self._failed:
            return self._lib
        try:
            lib = self._loader()
            init = getattr(lib, "nvmlInit_v2", None) or lib.nvmlInit
            code = init()
        except (OSError, AttributeError) as error:
            log.debug("NVML not available: %s", error)
            self._failed = True
            return None
        if code != SUCCESS:
            log.info("NVML could not start (code %s): NVIDIA usage and temperature unavailable", code)
            self._failed = True
            return None
        self._lib = lib
        return lib

    def _handle(self, lib, pci_slot):
        if pci_slot in self._handles:
            return self._handles[pci_slot]
        handle = ctypes.c_void_p()
        by_bus = getattr(lib, "nvmlDeviceGetHandleByPciBusId_v2", None) or lib.nvmlDeviceGetHandleByPciBusId
        code = by_bus(pci_slot.encode("ascii"), ctypes.byref(handle))
        self._handles[pci_slot] = handle if code == SUCCESS else None
        return self._handles[pci_slot]

    def read(self, pci_slot):
        """{"percent", "mem_percent", "temp_value", "mem_used_mb", "mem_total_mb", "power_w",
        "clock_mhz", "enc_percent"} for the card at ``pci_slot`` ("0000:01:00.0"); missing
        figures are left out. None when NVML or the card is not available."""
        with self._lock:
            lib = self._ensure()
            if lib is None or not pci_slot:
                return None
            handle = self._handle(lib, pci_slot)
            if handle is None:
                return None
            out = {}
            util = _Utilization()
            if lib.nvmlDeviceGetUtilizationRates(handle, ctypes.byref(util)) == SUCCESS:
                out["percent"] = float(util.gpu)
            temp = ctypes.c_uint()
            if lib.nvmlDeviceGetTemperature(handle, TEMPERATURE_GPU, ctypes.byref(temp)) == SUCCESS:
                out["temp_value"] = float(temp.value)
            memory = _Memory()
            if lib.nvmlDeviceGetMemoryInfo(handle, ctypes.byref(memory)) == SUCCESS and memory.total:
                out["mem_used_mb"] = int(memory.used // 1048576)
                out["mem_total_mb"] = int(memory.total // 1048576)
            power = ctypes.c_uint()
            if lib.nvmlDeviceGetPowerUsage(handle, ctypes.byref(power)) == SUCCESS:
                out["power_w"] = power.value / 1000
            clock = ctypes.c_uint()
            if lib.nvmlDeviceGetClockInfo(handle, CLOCK_GRAPHICS, ctypes.byref(clock)) == SUCCESS:
                out["clock_mhz"] = int(clock.value)
            enc, period = ctypes.c_uint(), ctypes.c_uint()
            if lib.nvmlDeviceGetEncoderUtilization(handle, ctypes.byref(enc), ctypes.byref(period)) == SUCCESS:
                out["enc_percent"] = float(enc.value)
            return out or None


_shared = None


def shared():
    """Process-wide session (NVML is initialised once)."""
    global _shared
    if _shared is None:
        _shared = NVML()
    return _shared
