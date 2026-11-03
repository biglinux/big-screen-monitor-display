"""Hardware collectors.

The module-level names (``SYSTEM_STATS``, ``*_HISTORY``, ``STATS_LOCK``) are
kept from the 3.x code because every legacy theme renderer reads them; they
are mutated in place so ``from bsmd.telemetry import X`` stays valid.

Cadences (seconds): fast metrics 1, swap/processes 5, disk usage 10,
power profile 30. No subprocess is spawned inside the loop any more (the
previous loop ran ``powerprofilesctl`` - a Python program - every 0.4 s,
~89 ms of CPU each time, plus a 36 ms process scan).
"""

import glob
import os
import platform
import re
import socket
import subprocess
import threading
import time

import psutil

STATS_LOCK = threading.Lock()
HISTORY_LEN = 30

SYSTEM_STATS = {
    "cpu_percent": 0.0,
    "cpu_temp": "?°C",
    "cpu_temp_value": None,
    "ram_used_mb": 0,
    "ram_total_mb": 0,
    "ram_percent": 0.0,
    "swap_used_mb": 0,
    "swap_total_mb": 0,
    "swap_percent": 0.0,
    "disk_percent": 0.0,
    "disk_text": "0/0 GB",
    "disk_free_gb": None,
    "disk_used_gb": None,
    "disk_total_gb": None,
    "procs_mem": [],
    "boot_time": None,
    "net_ifaces": {},
    "load_history": [0.0] * HISTORY_LEN,
    "sensors": [],          # [(group, label, value, unit)] real temperatures and fans, every 5 s
    "net_rx_mbps": 0.0,
    "net_tx_mbps": 0.0,
    "gpus": [],
    "cpu_cores_history": [],
    "cpu_cores_percent": [],
    "active_gpu_idx": 0,
    "procs": [],
    "hostname": socket.gethostname(),
    "kernel": platform.release(),
    "kernel_offset": 0,
    "kernel_dir": 1,
    "gpu_marquee_offset": 0,
    "gpu_marquee_dir": 1,
    "power_profile": "",
    "on_battery": False,
    "cpu_user": 0.0,
    "cpu_system": 0.0,
    "load_avg": (0.0, 0.0, 0.0),
    "disk_io_kbs": 0.0,
    "cpu_freq_mhz": None,
    "cpu_model": "",
    "cpu_cores": (None, None),        # (physical, logical)
    "cpu_temp_crit": None,            # hwmon critical limit, when the chip reports one
    "fans": [],                       # [{"id", "label", "rpm", "percent"}] only while a theme wants them
    "disks": {},                      # mountpoint -> usage/io/temperature, only for wanted mounts
    "net_addrs": {},                  # iface -> {"ipv4", "speed_mbps"} (every 30 s, on demand)
    "valid": False,
}

CPU_TEMP_HISTORY = [0] * HISTORY_LEN
CPU_USAGE_HISTORY = [0] * HISTORY_LEN
CPU_USER_HISTORY = [0] * HISTORY_LEN
CPU_SYSTEM_HISTORY = [0] * HISTORY_LEN
RAM_USAGE_HISTORY = [0] * HISTORY_LEN
GPU_USAGE_HISTORY = [0] * HISTORY_LEN
GPU_MEM_HISTORY = [0] * HISTORY_LEN
DISK_IO_HISTORY = [0] * HISTORY_LEN
NET_RX_HISTORY = [0] * HISTORY_LEN
NET_TX_HISTORY = [0] * HISTORY_LEN


def _push(history, value):
    history.append(value)
    del history[0]


def cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return re.sub(r"\s+", " ", line.split(":", 1)[1]).strip()
    except OSError:
        pass
    return platform.processor() or ""


def find_fans(hwmon_glob="/sys/class/hwmon/hwmon*"):
    """Fan inputs with their PWM duty file when the same chip exposes one.

    A percentage is only reported from the PWM duty cycle (0-255): RPM alone
    says nothing about the fan's range.
    """
    fans = []
    for hwmon in sorted(glob.glob(hwmon_glob)):
        try:
            chip = _read(os.path.join(hwmon, "name"))
        except OSError:
            continue
        for path in sorted(glob.glob(os.path.join(hwmon, "fan*_input"))):
            index = os.path.basename(path)[3:-len("_input")]
            try:
                label = _read(os.path.join(hwmon, f"fan{index}_label"))
            except OSError:
                label = f"fan{index}"
            pwm = os.path.join(hwmon, f"pwm{index}")
            fans.append({"id": f"{chip}/{label}", "chip": chip, "label": label, "input": path,
                         "pwm": pwm if os.path.exists(pwm) else None})
    return fans


def block_device_of(mountpoint):
    """(partition, whole disk) names backing a mount, e.g. ("nvme0n1p2", "nvme0n1")."""
    try:
        partitions = psutil.disk_partitions(all=False)
    except OSError:
        return None, None
    device = next((p.device for p in partitions if p.mountpoint == mountpoint), None)
    if not device or not device.startswith("/dev/"):
        return None, None
    name = os.path.basename(os.path.realpath(device))
    if os.path.exists(f"/sys/block/{name}"):
        return name, name
    for disk in os.listdir("/sys/block") if os.path.isdir("/sys/block") else ():
        if os.path.exists(f"/sys/block/{disk}/{name}"):
            return name, disk
    return name, None


def disk_temperature_input(disk):
    """Temperature file of a physical disk (NVMe controller or drivetemp), if any."""
    if not disk:
        return None
    for pattern in (f"/sys/block/{disk}/device/hwmon*/temp1_input",
                    f"/sys/block/{disk}/device/hwmon/hwmon*/temp1_input",
                    f"/sys/block/{disk}/device/device/hwmon*/temp1_input"):
        found = sorted(glob.glob(pattern))
        if found:
            return found[0]
    return None


def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().strip()


def link_stats(net_dir="/sys/class/net"):
    """{interface: (is_up, speed_mbps)} read from sysfs.

    psutil.net_if_stats() needs an AF_INET socket for its ioctls, which the
    service's RestrictAddressFamilies forbids (EAFNOSUPPORT on every call).
    """
    result = {}
    try:
        names = os.listdir(net_dir)
    except OSError:
        return result
    for name in names:
        try:
            flags = int(_read(os.path.join(net_dir, name, "flags")), 16)
        except (OSError, ValueError):
            continue
        try:
            speed = max(0, int(_read(os.path.join(net_dir, name, "speed"))))
        except (OSError, ValueError):     # EINVAL while the link is down, absent on wireless
            speed = 0
        result[name] = (bool(flags & 0x1), speed)     # IFF_UP
    return result


def _lspci_name(pci_slot):
    """Marketing name between brackets in ``lspci -s`` output (run once)."""
    try:
        output = subprocess.run(["lspci", "-s", pci_slot], capture_output=True, text=True,
                                timeout=3, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(r"\[([^\[\]]+)\][^\[]*$", output.splitlines()[0]) if output else None
    if not match:
        return ""
    # "Radeon Vega Series / Radeon Vega Mobile Series" -> first marketing name
    return match.group(1).split(" / ")[0].strip()


def _empty_gpu(path=None, name="GPU"):
    return {"path": path, "name": name, "percent": 0.0, "mem_used_mb": 0, "mem_total_mb": 0,
            "enc_percent": 0.0, "temp": "?°C", "temp_value": None,
            "usage_history": [0] * HISTORY_LEN, "mem_history": [0] * HISTORY_LEN}


def find_gpus(drm_glob="/sys/class/drm/card[0-9]"):
    gpus = []
    for card in sorted(glob.glob(drm_glob)):
        uevent_path = os.path.join(card, "device", "uevent")
        if not os.path.exists(uevent_path):
            continue
        try:
            uevent = _read(uevent_path)
        except OSError:
            continue
        pci_slot = ""
        for line in uevent.splitlines():
            if line.startswith("PCI_SLOT_NAME="):
                pci_slot = line.split("=", 1)[1].strip()
        name = _lspci_name(pci_slot) if pci_slot else ""
        if not name:
            if "1002:7590" in uevent:
                name = "RX 580"
            elif "1002" in uevent:
                name = "AMD Radeon"
            elif "8086" in uevent:
                name = "Intel"
            elif "10de" in uevent:
                name = "NVIDIA"
        if name:
            gpu = _empty_gpu(card, name[:28])
            hwmon = glob.glob(os.path.join(card, "device", "hwmon", "hwmon*"))
            gpu["hwmon"] = hwmon[0] if hwmon else None
            gpus.append(gpu)
    return gpus or [_empty_gpu()]


def read_power_profile():
    for path, parse in (("/sys/firmware/acpi/platform_profile", lambda text: text),
                        ("/var/lib/power-profiles-daemon/state.ini", _ppd_profile)):
        try:
            value = parse(_read(path))
        except OSError:
            continue
        if value:
            return value
    return ""


def _ppd_profile(text):
    match = re.search(r"^Profile=(\S+)", text, re.MULTILINE)
    return match.group(1) if match else ""


def _cpu_temperature(temps):
    for name, entries in temps.items():
        if any(key in name for key in ("coretemp", "k10temp", "zenpower")):
            for entry in entries:
                label = entry.label or ""
                if not label or any(key in label for key in ("Tctl", "Package id 0", "Tdie", "Core 0")):
                    if entry.current:
                        return entry.current
    for entries in temps.values():
        if entries and entries[0].current:
            return entries[0].current
    return None


def find_cpu_temp_input(hwmon_glob="/sys/class/hwmon/hwmon*"):
    """Path of the CPU package temperature file, found once.

    Reading one sysfs file per second costs ~0.05 ms, while
    psutil.sensors_temperatures() reads every sensor of every device (~6 ms).
    """
    preferred = ("Tctl", "Tdie", "Package id 0")
    for hwmon in sorted(glob.glob(hwmon_glob)):
        try:
            name = _read(os.path.join(hwmon, "name"))
        except OSError:
            continue
        if name not in ("coretemp", "k10temp", "zenpower"):
            continue
        fallback = None
        for label_path in sorted(glob.glob(os.path.join(hwmon, "temp*_label"))):
            try:
                label = _read(label_path)
            except OSError:
                continue
            input_path = label_path[:-len("_label")] + "_input"
            if label in preferred and os.path.exists(input_path):
                return input_path
            if fallback is None and label.startswith("Core 0") and os.path.exists(input_path):
                fallback = input_path
        first = os.path.join(hwmon, "temp1_input")
        return fallback or (first if os.path.exists(first) else None)
    return None


def critical_for(input_path):
    """``tempN_crit`` (or ``_max``) next to a ``tempN_input``, in °C."""
    if not input_path:
        return None
    for suffix in ("_crit", "_max"):
        try:
            value = int(_read(input_path[:-len("_input")] + suffix)) / 1000
        except (OSError, ValueError):
            continue
        if 40 <= value <= 150:
            return value
    return None


def _advance_marquee(text_len, offset_key, dir_key, limit=20):
    if text_len > limit:
        offset = SYSTEM_STATS.get(offset_key, 0) + SYSTEM_STATS.get(dir_key, 1)
        direction = SYSTEM_STATS.get(dir_key, 1)
        if offset >= text_len - limit:
            offset, direction = text_len - limit, -1
        elif offset <= 0:
            offset, direction = 0, 1
        SYSTEM_STATS[offset_key] = offset
        SYSTEM_STATS[dir_key] = direction
    else:
        SYSTEM_STATS[offset_key] = 0


class Collector:
    """Background sampler. ``heartbeat`` is a bsmd.health.Heartbeat or None."""

    INTERVAL = 1.0

    def __init__(self, heartbeat=None, interval=None):
        self.heartbeat = heartbeat
        self.interval = interval or self.INTERVAL
        self.sensor_errors = {}
        self._stop = threading.Event()
        self._thread = None
        self._last = {}
        self.want_processes = True     # the runtime turns it off for themes without a process list
        self.want_sensors = False      # full sensor list (GKrellM); costs ~6 ms, sampled every 5 s
        self.want_fans = False         # fan RPM/PWM (Kojiro), every 2 s
        self.want_disks = set()        # extra mountpoints whose usage/io/temperature a theme shows
        self.want_addrs = False        # local IP addresses and link speeds, every 30 s
        self._cpu_temp_path = None
        self._fans = None
        self._disk_paths = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self.run, name="telemetry", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _due(self, key, period, now):
        if now - self._last.get(key, -1e9) >= period:
            self._last[key] = now
            return True
        return False

    def _guard(self, name, func):
        """Run one collector; failures are counted, never hidden or fatal."""
        try:
            func()
            self.sensor_errors.pop(name, None)
        except Exception as error:  # noqa: BLE001 - one bad sensor must not stop the loop
            self.sensor_errors[name] = f"{type(error).__name__}: {error}"[:200]

    def prime(self):
        """Discover GPUs and take the baseline samples deltas are computed from."""
        SYSTEM_STATS["gpus"] = find_gpus()
        self._net = psutil.net_io_counters()
        self._disk = psutil.disk_io_counters()
        self._time = time.monotonic()
        psutil.cpu_percent(interval=None)
        psutil.cpu_times_percent(interval=None)
        psutil.cpu_percent(interval=None, percpu=True)
        self._gpu_switch = 0
        self._cpu_temp_path = find_cpu_temp_input()
        SYSTEM_STATS["cpu_temp_crit"] = critical_for(self._cpu_temp_path)
        SYSTEM_STATS["cpu_model"] = cpu_model()
        try:
            SYSTEM_STATS["cpu_cores"] = (psutil.cpu_count(logical=False), psutil.cpu_count(logical=True))
        except Exception:  # noqa: BLE001
            SYSTEM_STATS["cpu_cores"] = (None, None)
        self._perdisk = psutil.disk_io_counters(perdisk=True) or {}
        self._nics = psutil.net_io_counters(pernic=True)
        try:
            SYSTEM_STATS["boot_time"] = psutil.boot_time()
        except OSError:
            SYSTEM_STATS["boot_time"] = None

    def run(self):
        self.prime()
        while not self._stop.is_set():
            started = time.monotonic()
            if self.heartbeat:
                self.heartbeat.begin("sample")
            self.sample_once(started)
            if self.heartbeat:
                self.heartbeat.end(ok=not self.sensor_errors,
                                   error="; ".join(f"{k}: {v}" for k, v in self.sensor_errors.items()))
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.1, self.interval - elapsed))

    def sample_once(self, now=None):
        now = time.monotonic() if now is None else now
        self._guard("cpu", self._sample_cpu)
        self._guard("memory", self._sample_memory)
        self._guard("io", lambda: self._sample_io(now))
        self._guard("temperature", self._sample_temperature)
        self._guard("gpu", self._sample_gpus)
        if self._due("slow", 5, now):
            self._guard("swap", self._sample_swap)
            if self.want_processes:
                self._guard("processes", self._sample_processes)
            self._guard("battery", self._sample_battery)
            if self.want_sensors:
                self._guard("sensors", self._sample_sensor_list)
        if self._due("disk", 10, now):
            self._guard("disk", self._sample_disk)
        if self.want_disks and self._due("disks", 2, now):
            self._guard("disks", lambda: self._sample_disks(now))
        if self.want_fans and self._due("fans", 2, now):
            self._guard("fans", self._sample_fans)
        if self.want_addrs and self._due("addrs", 30, now):
            self._guard("addrs", self._sample_addrs)
        if self._due("power", 30, now):
            SYSTEM_STATS["power_profile"] = read_power_profile()
        _advance_marquee(len(SYSTEM_STATS.get("kernel", "")), "kernel_offset", "kernel_dir")
        longest = max((len(g.get("name", "")) for g in SYSTEM_STATS.get("gpus", [])), default=0)
        _advance_marquee(longest, "gpu_marquee_offset", "gpu_marquee_dir")
        SYSTEM_STATS["valid"] = True
        SYSTEM_STATS["sampled_at"] = time.time()

    def _sample_cpu(self):
        total = psutil.cpu_percent(interval=None)
        times = psutil.cpu_times_percent(interval=None)
        cores = psutil.cpu_percent(interval=None, percpu=True)
        with STATS_LOCK:
            SYSTEM_STATS["cpu_percent"] = total
            SYSTEM_STATS["cpu_user"] = times.user
            SYSTEM_STATS["cpu_system"] = times.system
            _push(CPU_USER_HISTORY, times.user)
            _push(CPU_SYSTEM_HISTORY, times.system)
            _push(CPU_USAGE_HISTORY, total)
            SYSTEM_STATS["cpu_cores_percent"] = cores
            history = SYSTEM_STATS["cpu_cores_history"]
            if len(history) != len(cores):
                history[:] = [[] for _ in cores]
            for core_history, value in zip(history, cores):
                core_history.append(value)
                if len(core_history) > 40:
                    del core_history[0]
        try:
            freq = psutil.cpu_freq()
            SYSTEM_STATS["cpu_freq_mhz"] = freq.current if freq and freq.current else None
        except Exception:  # noqa: BLE001 - not every platform reports a frequency
            SYSTEM_STATS["cpu_freq_mhz"] = None
        try:
            SYSTEM_STATS["load_avg"] = os.getloadavg()
        except OSError:
            SYSTEM_STATS["load_avg"] = (0.0, 0.0, 0.0)
        with STATS_LOCK:
            _push(SYSTEM_STATS["load_history"], SYSTEM_STATS["load_avg"][0])

    def _sample_memory(self):
        mem = psutil.virtual_memory()
        with STATS_LOCK:
            SYSTEM_STATS["ram_percent"] = mem.percent
            SYSTEM_STATS["ram_used_mb"] = mem.used // 1048576
            SYSTEM_STATS["ram_total_mb"] = mem.total // 1048576
            _push(RAM_USAGE_HISTORY, mem.percent)

    def _sample_swap(self):
        swap = psutil.swap_memory()
        SYSTEM_STATS["swap_percent"] = swap.percent
        SYSTEM_STATS["swap_used_mb"] = swap.used // 1048576
        SYSTEM_STATS["swap_total_mb"] = swap.total // 1048576

    def _sample_disk(self):
        disk = psutil.disk_usage("/")
        SYSTEM_STATS["disk_percent"] = disk.percent
        SYSTEM_STATS["disk_text"] = f"{disk.used // (1024 ** 3)} / {disk.total // (1024 ** 3)} GB"
        SYSTEM_STATS["disk_free_gb"] = disk.free / (1024 ** 3)
        SYSTEM_STATS["disk_used_gb"] = disk.used / (1024 ** 3)
        SYSTEM_STATS["disk_total_gb"] = disk.total / (1024 ** 3)

    def _sample_io(self, now):
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()
        dt = now - self._time
        if dt > 0:
            rx = max(0.0, (net.bytes_recv - self._net.bytes_recv) * 8 / (dt * 1e6))
            tx = max(0.0, (net.bytes_sent - self._net.bytes_sent) * 8 / (dt * 1e6))
            with STATS_LOCK:
                SYSTEM_STATS["net_rx_mbps"] = rx
                SYSTEM_STATS["net_tx_mbps"] = tx
                _push(NET_RX_HISTORY, rx)
                _push(NET_TX_HISTORY, tx)
                if disk is not None and self._disk is not None:
                    total = max(0.0, ((disk.read_bytes - self._disk.read_bytes) +
                                      (disk.write_bytes - self._disk.write_bytes)) / (dt * 1024))
                    SYSTEM_STATS["disk_io_kbs"] = total
                    _push(DISK_IO_HISTORY, total)
        # Move the baseline first: a failing interface list must not turn the
        # rates above into averages since start-up.
        self._net, self._disk, self._time = net, disk, now
        self._sample_interfaces(dt)

    IGNORED_NICS = ("lo", "veth", "docker", "br-", "virbr", "vnet")

    def _sample_interfaces(self, dt):
        """Per-interface rates for themes that list interfaces (GKrellM).

        Virtual container interfaces are skipped and vanished interfaces are
        dropped, so the dictionary never grows without bound.
        """
        nics = psutil.net_io_counters(pernic=True)
        links = link_stats()
        current = SYSTEM_STATS["net_ifaces"]
        seen = set()
        for name, counters in nics.items():
            if name.startswith(self.IGNORED_NICS) or not links.get(name, (False, 0))[0]:
                continue
            previous = self._nics.get(name)
            if previous is None or dt <= 0:
                continue
            seen.add(name)
            rx = max(0.0, (counters.bytes_recv - previous.bytes_recv) * 8 / (dt * 1e6))
            tx = max(0.0, (counters.bytes_sent - previous.bytes_sent) * 8 / (dt * 1e6))
            entry = current.setdefault(name, {"rx_history": [0] * HISTORY_LEN, "tx_history": [0] * HISTORY_LEN})
            entry["rx"], entry["tx"] = rx, tx
            entry["rx_total"], entry["tx_total"] = counters.bytes_recv, counters.bytes_sent
            _push(entry["rx_history"], rx)
            _push(entry["tx_history"], tx)
        for name in list(current):
            if name not in seen:
                del current[name]
        self._nics = nics

    def _sample_temperature(self):
        value = None
        if self._cpu_temp_path:
            try:
                value = int(_read(self._cpu_temp_path)) / 1000
            except (OSError, ValueError):
                self._cpu_temp_path = None
        if value is None and hasattr(psutil, "sensors_temperatures"):
            value = _cpu_temperature(psutil.sensors_temperatures())
        if value:
            with STATS_LOCK:
                SYSTEM_STATS["cpu_temp"] = f"{value:.0f}°C"
                SYSTEM_STATS["cpu_temp_value"] = value
                _push(CPU_TEMP_HISTORY, value)

    def _sample_sensor_list(self):
        found = []
        if hasattr(psutil, "sensors_temperatures"):
            for group, entries in psutil.sensors_temperatures().items():
                for entry in entries[:4]:
                    if entry.current:
                        found.append((group, entry.label or group, entry.current, "°C"))
        if hasattr(psutil, "sensors_fans"):
            for group, entries in psutil.sensors_fans().items():
                for entry in entries[:4]:
                    found.append((group, entry.label or group, entry.current, "RPM"))
        SYSTEM_STATS["sensors"] = found[:24]

    def _sample_fans(self):
        if self._fans is None:
            self._fans = find_fans()
        found = []
        for fan in self._fans:
            try:
                rpm = int(_read(fan["input"]))
            except (OSError, ValueError):
                continue
            percent = None
            if fan["pwm"]:
                try:
                    percent = int(_read(fan["pwm"])) * 100 / 255
                except (OSError, ValueError):
                    percent = None
            found.append({"id": fan["id"], "label": fan["label"], "chip": fan["chip"], "rpm": rpm,
                          "percent": percent})
        SYSTEM_STATS["fans"] = found

    def _sample_disks(self, now):
        perdisk = psutil.disk_io_counters(perdisk=True) or {}
        dt = now - self._last.get("disks_prev", now)
        self._last["disks_prev"] = now
        result = {}
        for mount in sorted(self.want_disks)[:8]:
            try:
                usage = psutil.disk_usage(mount)
            except OSError:
                result[mount] = {"available": False}
                continue
            if mount not in self._disk_paths:
                part, disk = block_device_of(mount)
                path = disk_temperature_input(disk)
                self._disk_paths[mount] = (part, disk, path, critical_for(path))
            part, disk, temp_path, temp_crit = self._disk_paths[mount]
            entry = {"available": True, "percent": usage.percent, "used_gb": usage.used / 1024 ** 3,
                     "total_gb": usage.total / 1024 ** 3, "device": part, "disk": disk,
                     "temp": None, "temp_crit": temp_crit, "read_kbs": None, "write_kbs": None}
            if temp_path:
                try:
                    entry["temp"] = int(_read(temp_path)) / 1000
                except (OSError, ValueError):
                    pass
            # I/O belongs to the physical disk (or the partition when it is listed).
            key = part if part in perdisk else disk
            if key in perdisk and key in self._perdisk and dt > 0:
                entry["read_kbs"] = max(0.0, (perdisk[key].read_bytes - self._perdisk[key].read_bytes) / dt / 1024)
                entry["write_kbs"] = max(0.0, (perdisk[key].write_bytes - self._perdisk[key].write_bytes)
                                         / dt / 1024)
            result[mount] = entry
        self._perdisk = perdisk
        SYSTEM_STATS["disks"] = result

    def _sample_addrs(self):
        links = link_stats()
        result = {}
        for name, addrs in psutil.net_if_addrs().items():
            if name.startswith(self.IGNORED_NICS):
                continue
            ipv4 = next((a.address for a in addrs if a.family == socket.AF_INET), None)
            if ipv4:
                speed = links.get(name, (False, 0))[1] or None
                result[name] = {"ipv4": ipv4, "speed_mbps": speed}
        SYSTEM_STATS["net_addrs"] = result

    def _sample_battery(self):
        battery = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        SYSTEM_STATS["on_battery"] = bool(battery is not None and not battery.power_plugged)
        SYSTEM_STATS["battery"] = None if battery is None else {
            "percent": battery.percent, "plugged": bool(battery.power_plugged)}

    def _sample_processes(self):
        procs = [p.info for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"])
                 if p.info["cpu_percent"] is not None]
        by_memory = sorted(procs, key=lambda info: info.get("memory_percent") or 0, reverse=True)
        procs.sort(key=lambda info: info["cpu_percent"], reverse=True)
        SYSTEM_STATS["procs"] = procs[:12]
        SYSTEM_STATS["procs_mem"] = by_memory[:12]
        SYSTEM_STATS["proc_count"] = len(procs)

    def _sample_gpus(self):
        gpus = SYSTEM_STATS["gpus"]
        if len(gpus) > 1:
            self._gpu_switch += 1
            if self._gpu_switch >= 3:
                SYSTEM_STATS["active_gpu_idx"] = (SYSTEM_STATS["active_gpu_idx"] + 1) % len(gpus)
                self._gpu_switch = 0
        for index, gpu in enumerate(gpus):
            if gpu["path"]:
                self._guard(f"gpu{index}", lambda gpu=gpu, index=index: self._sample_gpu(gpu, index))

    def _sample_gpu(self, gpu, index):
        device = os.path.join(gpu["path"], "device")
        busy = os.path.join(device, "gpu_busy_percent")
        if os.path.exists(busy):
            gpu["percent"] = float(_read(busy))
        used = os.path.join(device, "mem_info_vram_used")
        if os.path.exists(used):
            gpu["mem_used_mb"] = int(_read(used)) // 1048576
            gpu["mem_total_mb"] = int(_read(os.path.join(device, "mem_info_vram_total"))) // 1048576
        mem_percent = gpu["mem_used_mb"] / gpu["mem_total_mb"] * 100 if gpu["mem_total_mb"] else 0
        with STATS_LOCK:
            _push(gpu["usage_history"], gpu["percent"])
            _push(gpu["mem_history"], mem_percent)
            if index == SYSTEM_STATS.get("active_gpu_idx", 0):
                _push(GPU_USAGE_HISTORY, gpu["percent"])
                _push(GPU_MEM_HISTORY, mem_percent)
        sclk = os.path.join(device, "pp_dpm_sclk")
        if os.path.exists(sclk):
            current = [line for line in _read(sclk).splitlines() if line.rstrip().endswith("*")]
            match = re.search(r"(\d+)\s*Mhz", current[0], re.IGNORECASE) if current else None
            gpu["clock_mhz"] = int(match.group(1)) if match else None
        vcn = os.path.join(device, "vcn_busy_percent")
        if os.path.exists(vcn):
            value = _read(vcn)
            gpu["enc_percent"] = float(value) if value.isdigit() else 0.0
            gpu["video_engine"] = "VCN"        # AMD: one figure for encode + decode
        hwmon = gpu.get("hwmon")
        if hwmon:
            for sensor, label in (("temp1_input", "edge"), ("temp2_input", "junc"), ("temp3_input", "mem")):
                path = os.path.join(hwmon, sensor)
                if os.path.exists(path):
                    gpu[label] = f"{int(_read(path)) // 1000}°C"
                    if sensor == "temp1_input":
                        gpu["temp_value"] = int(_read(path)) / 1000
                        gpu["temp"] = gpu[label]
                        if "temp_crit" not in gpu:
                            gpu["temp_crit"] = critical_for(path)
            power = os.path.join(hwmon, "power1_average")
            if not os.path.exists(power):
                power = os.path.join(hwmon, "power1_input")
            if os.path.exists(power):
                gpu["power_w"] = int(_read(power)) / 1000000
                gpu["ppt"] = f"{gpu['power_w']:.1f}W"


def snapshot():
    """Consistent shallow copy for consumers that need several fields at once."""
    with STATS_LOCK:
        data = dict(SYSTEM_STATS)
        data["gpus"] = [dict(gpu) for gpu in SYSTEM_STATS.get("gpus", [])]
        data["cpu_history"] = list(CPU_USAGE_HISTORY)
        data["ram_history"] = list(RAM_USAGE_HISTORY)
        data["net_rx_history"] = list(NET_RX_HISTORY)
        data["net_tx_history"] = list(NET_TX_HISTORY)
        data["disks"] = {k: dict(v) for k, v in SYSTEM_STATS.get("disks", {}).items()}
        data["fans"] = [dict(f) for f in SYSTEM_STATS.get("fans", [])]
    return data
