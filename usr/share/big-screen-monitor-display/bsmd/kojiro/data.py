"""Telemetry -> widget metrics.

A metric never invents a value: when the hardware or driver does not report
something (fan, video engine, disk temperature, a second GPU...) the metric
is ``available=False`` and the widget shows a dash or hides itself.

Alert thresholds for temperatures come from the chip (``tempN_crit``) when
it reports one; otherwise conservative defaults the user can override.
"""

import math
import time
from dataclasses import dataclass, field

from .. import i18n
from ..i18n import N_, _

DEFAULT_TEMP_CRIT = {"cpu": 95.0, "gpu": 95.0, "disk": 70.0}
USAGE_LIMITS = {"disk": (85.0, 95.0), "battery": None}


@dataclass
class Metric:
    available: bool = True
    fraction: float = 0.0          # 0..1 main indicator
    fraction2: float = None        # secondary ring (temperature)
    big: str = ""                  # main text
    lines: list = field(default_factory=list)      # [(label, text)]
    title: str = ""
    alert_value: float = None
    alert_kind: str = None          # "temp" | "usage"
    warn: float = None
    crit: float = None
    history: list = None
    history_max: float = None
    rpm: float = 0.0                # fan animation speed
    extra: dict = field(default_factory=dict)

    def key(self):
        """What the rendered layer depends on (values rounded to what is visible)."""
        return (self.available, round(self.fraction, 3), None if self.fraction2 is None else round(self.fraction2, 3),
                self.big, tuple(self.lines), self.title,
                tuple(round(v, 2) for v in self.history[-40:]) if self.history else None,
                tuple(sorted((k, str(v)) for k, v in self.extra.items())))


def temperature_text(value, unit="c"):
    if value is None:
        return "—"
    return f"{value * 9 / 5 + 32:.0f}°F" if unit == "f" else f"{value:.0f}°C"


def size_text(mb):
    if mb is None:
        return "—"
    return f"{mb / 1024:.1f} GB" if mb >= 10240 else f"{mb:.0f} MB"


def rate_text(mbps, unit="auto_bytes"):
    """Telemetry rates are megabits per second; bits and bytes are never mixed."""
    if mbps is None:
        return "—"
    if unit == "Mbps":
        return f"{mbps:.1f} Mbps"
    if unit == "Gbps":
        return f"{mbps / 1000:.2f} Gbps"
    kbytes = mbps * 1e6 / 8 / 1024
    if unit == "KB/s" or (unit == "auto_bytes" and kbytes < 1024):
        return f"{kbytes:.0f} KB/s" if kbytes >= 10 or unit == "KB/s" else f"{kbytes:.1f} KB/s"
    return f"{kbytes / 1024:.1f} MB/s"


def uptime_text(boot_time, now=None):
    if not boot_time:
        return "—"
    seconds = int((now or time.time()) - boot_time)
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    return f"{days}d {hours:02d}:{minutes:02d}" if days else f"{hours:02d}:{minutes:02d}"


def _thresholds(widget, kind, auto_crit=None, default_crit=95.0):
    warn, crit = widget.get("warn") or 0, widget.get("crit") or 0
    if kind == "temp":
        crit = crit or auto_crit or default_crit
        warn = warn or crit - 15
    else:
        auto = USAGE_LIMITS.get(widget["type"]) or (80.0, 92.0)
        warn, crit = warn or auto[0], crit or auto[1]
    return min(warn, crit), crit


def _gpu(stats, index):
    """GPU by index; -1 = automatic: the one with most VRAM (the dedicated card on hybrid systems)."""
    gpus = [g for g in (stats.get("gpus") or []) if g.get("path")]
    if not gpus:
        return None
    if index < 0:
        return max(gpus, key=lambda g: g.get("mem_total_mb") or 0)
    all_gpus = stats.get("gpus") or []
    if index < len(all_gpus) and all_gpus[index].get("path"):
        return all_gpus[index]
    return None


def _fan(stats, wanted):
    fans = stats.get("fans") or []
    if wanted and wanted != "auto":
        return next((fan for fan in fans if fan["id"] == wanted), None)
    spinning = [fan for fan in fans if fan.get("rpm")]
    return spinning[0] if spinning else None


def _temp_sensor(stats, wanted):
    for group, label, value, unit in stats.get("sensors") or []:
        if unit == "°C" and f"{group}/{label}" == wanted:
            return value
    return None


def _iface(stats, wanted):
    ifaces = stats.get("net_ifaces") or {}
    if wanted and wanted != "auto":
        return ifaces.get(wanted)
    return None


def metric(widget, stats, now=None):
    """Metric for one widget from a telemetry snapshot."""
    kind = widget["type"]
    opts = widget.get("opts", {})
    default_title = TITLES.get(kind, kind.upper())
    title = widget.get("label") or (_(default_title) if default_title else "")   # _("") is the PO header
    builder = BUILDERS.get(kind)
    if builder is None:
        return Metric(title=title)
    result = builder(widget, opts, stats, now or time.time())
    result.title = title
    return result


TITLES = {"cpu": "CPU", "gpu": "GPU", "ram": "RAM", "swap": "SWAP", "vram": "VRAM", "fan": "FAN",
          "encdec": "ENC/DEC", "disk": "HDD", "net_down": "DN", "net_up": "UP", "clock": "", "distro": "",
          "cores": "CORES", "uptime": "UPTIME", "hostname": "HOST", "kernel": "KERNEL", "ip": "IP",
          "battery": "BAT", "power": "POWER", "processes": "TOP", "text": "", "separator": "", "frame": ""}


def _cpu(widget, opts, stats, now):
    usage = stats.get("cpu_percent") or 0.0
    unit = widget.get("unit") or "c"
    temp = stats.get("cpu_temp_value")
    if opts.get("temp_sensor", "auto") != "auto":
        temp = _temp_sensor(stats, opts["temp_sensor"])
    warn, crit = _thresholds(widget, "temp", stats.get("cpu_temp_crit"), DEFAULT_TEMP_CRIT["cpu"])
    lines = []
    if opts.get("show_temp", True):
        lines.append(("temp", temperature_text(temp, unit)))
    freq = stats.get("cpu_freq_mhz")
    if opts.get("show_freq", True):
        lines.append(("freq", f"{freq / 1000:.1f} GHz" if freq else "—"))
    if opts.get("show_model"):
        lines.append(("model", stats.get("cpu_model") or "—"))
    return Metric(fraction=usage / 100, fraction2=None if temp is None else temp / crit,
                  big=f"{usage:.{widget.get('decimals', 0)}f}%", lines=lines,
                  alert_value=temp if temp is not None else usage, alert_kind="temp" if temp is not None else "usage",
                  warn=warn if temp is not None else 85, crit=crit if temp is not None else 97,
                  history=list(stats.get("cpu_history") or []), history_max=100.0)


def _gpu_metric(widget, opts, stats, now):
    gpu = _gpu(stats, opts.get("index", 0))
    if gpu is None:
        return Metric(available=False, big="—")
    unit = widget.get("unit") or "c"
    temp = gpu.get("temp_value")
    warn, crit = _thresholds(widget, "temp", gpu.get("temp_crit"), DEFAULT_TEMP_CRIT["gpu"])
    lines = []
    if opts.get("show_temp", True):
        lines.append(("temp", temperature_text(temp, unit)))
    if opts.get("show_clock", True):
        clock = gpu.get("clock_mhz")
        lines.append(("clock", f"{clock} MHz" if clock else "—"))
    if opts.get("show_vram") and gpu.get("mem_total_mb"):
        lines.append(("vram", f"{size_text(gpu['mem_used_mb'])} / {size_text(gpu['mem_total_mb'])}"))
    if opts.get("show_power") and gpu.get("power_w") is not None:
        lines.append(("power", f"{gpu['power_w']:.0f} W"))
    if opts.get("show_name"):
        lines.append(("name", gpu.get("name", "GPU")))
    usage = gpu.get("percent") or 0.0
    return Metric(fraction=usage / 100, fraction2=None if temp is None else temp / crit,
                  big=f"{usage:.{widget.get('decimals', 0)}f}%", lines=lines,
                  alert_value=temp if temp is not None else usage, alert_kind="temp" if temp is not None else "usage",
                  warn=warn if temp is not None else 85, crit=crit if temp is not None else 97,
                  history=list(gpu.get("usage_history") or []), history_max=100.0,
                  extra={"name": gpu.get("name", "GPU")})


def _memory(used_mb, total_mb, widget, opts):
    if not total_mb:
        return None
    percent = used_mb / total_mb * 100
    warn, crit = _thresholds(widget, "usage")
    lines = []
    if opts.get("show_values", True):
        lines.append(("values", f"{size_text(used_mb)} / {size_text(total_mb)}"))
    return Metric(fraction=percent / 100, big=f"{percent:.{widget.get('decimals', 0)}f}%"
                  if opts.get("show_percent", True) else "", lines=lines,
                  alert_value=percent, alert_kind="usage", warn=warn, crit=crit)


def _ram(widget, opts, stats, now):
    # psutil "used" = total - free - buffers - cache: memory the system cannot reclaim easily.
    result = _memory(stats.get("ram_used_mb", 0), stats.get("ram_total_mb", 0), widget, opts)
    if result is None:
        return Metric(available=False, big="—")
    result.history, result.history_max = list(stats.get("ram_history") or []), 100.0
    return result


def _swap(widget, opts, stats, now):
    total = stats.get("swap_total_mb", 0)
    if not total:
        return Metric(available=False, big=_("no swap"), extra={"no_swap": True})
    return _memory(stats.get("swap_used_mb", 0), total, widget, opts)


def _vram(widget, opts, stats, now):
    gpu = _gpu(stats, opts.get("index", 0))
    if gpu is None or not gpu.get("mem_total_mb"):
        return Metric(available=False, big="—")
    result = _memory(gpu.get("mem_used_mb", 0), gpu["mem_total_mb"], widget, {"show_values": True,
                                                                              "show_percent": True})
    return result


def _fan_metric(widget, opts, stats, now):
    fan = _fan(stats, opts.get("fan", "auto"))
    if fan is None:
        return Metric(available=False, big="—")
    lines = []
    if opts.get("show_rpm", True):
        lines.append(("rpm", f"{fan['rpm']} RPM"))
    percent = fan.get("percent")
    big = f"{percent:.0f}%" if percent is not None else f"{fan['rpm']}"
    return Metric(fraction=(percent or 0) / 100, big=big, lines=lines, rpm=fan["rpm"],
                  extra={"label": fan["label"], "pwm": percent is not None})


def _encdec(widget, opts, stats, now):
    gpu = _gpu(stats, opts.get("index", 0))
    if gpu is None or not gpu.get("video_engine"):
        return Metric(available=False, big="—")
    value = gpu.get("enc_percent") or 0.0
    return Metric(fraction=value / 100, big=f"{value:.0f}%", lines=[("engine", f"{gpu['video_engine']} enc+dec")],
                  extra={"engine": gpu["video_engine"]})


def _disk(widget, opts, stats, now):
    mount = opts.get("mount", "/")
    entry = (stats.get("disks") or {}).get(mount)
    if entry is None and mount == "/" and stats.get("disk_total_gb"):
        entry = {"available": True, "percent": stats.get("disk_percent", 0), "used_gb": stats.get("disk_used_gb"),
                 "total_gb": stats.get("disk_total_gb"), "temp": None, "temp_crit": None}
    if not entry or not entry.get("available"):
        return Metric(available=False, big="—")
    unit = widget.get("unit") or "c"
    warn, crit = _thresholds(widget, "usage")
    lines = []
    if opts.get("show_space", True):
        lines.append(("space", f"{entry['used_gb']:.0f} / {entry['total_gb']:.0f} GB"))
    if opts.get("show_temp", True) and entry.get("temp") is not None:
        lines.append(("temp", temperature_text(entry["temp"], unit)))
    if opts.get("show_io") and entry.get("read_kbs") is not None:
        lines.append(("io", f"R {entry['read_kbs']:.0f} · W {entry['write_kbs']:.0f} KB/s"))
    return Metric(fraction=entry["percent"] / 100, big=f"{entry['percent']:.0f}%", lines=lines,
                  alert_value=entry["percent"], alert_kind="usage", warn=warn, crit=crit,
                  extra={"mount": mount})


def _net(direction):
    def build(widget, opts, stats, now):
        iface = _iface(stats, opts.get("iface", "auto"))
        if opts.get("iface", "auto") != "auto" and iface is None:
            return Metric(available=False, big="—")
        if iface is not None:
            value = iface["rx" if direction == "down" else "tx"]
            history = list(iface["rx_history" if direction == "down" else "tx_history"])
        else:
            value = stats.get("net_rx_mbps" if direction == "down" else "net_tx_mbps", 0.0)
            history = list(stats.get("net_rx_history" if direction == "down" else "net_tx_history") or [])
        peak = max(history + [value, 1.0])
        return Metric(fraction=min(1.0, value / peak), big=rate_text(value, widget.get("unit") or "auto_bytes"),
                      history=history, history_max=None, extra={"direction": direction,
                                                                "intensity": round(min(1.0, value / 100), 2)})
    return build


def _clock(widget, opts, stats, now):
    local = time.localtime(now)
    if opts.get("h24", True):
        text = time.strftime("%H:%M:%S" if opts.get("seconds") else "%H:%M", local)
    else:
        text = time.strftime("%I:%M:%S" if opts.get("seconds") else "%I:%M", local).lstrip("0") or "12"
        text += " " + time.strftime("%p", local)
    parts = []
    if opts.get("weekday", True):
        parts.append(_(WEEKDAYS[local.tm_wday]))
    if opts.get("date", True):
        parts.append(time.strftime(DATE_FORMATS.get(opts.get("date_format", "auto"), _auto_date_format()), local))
    colon = not opts.get("blink", True) or opts.get("seconds") or local.tm_sec % 2 == 0
    return Metric(big=text, lines=[("date", " · ".join(parts))] if parts else [], extra={"colon": colon})


WEEKDAYS = (N_("Monday"), N_("Tuesday"), N_("Wednesday"), N_("Thursday"), N_("Friday"), N_("Saturday"),
            N_("Sunday"))
DATE_FORMATS = {"dmy": "%d/%m/%Y", "mdy": "%m/%d/%Y", "ymd": "%Y-%m-%d"}


def _auto_date_format():
    """Day first for Portuguese, ISO otherwise (unambiguous in any locale)."""
    return DATE_FORMATS["dmy"] if (i18n.current_language() or "").startswith("pt") else DATE_FORMATS["ymd"]


def _distro(widget, opts, stats, now):
    from .assets import distro_info
    info = distro_info()
    name = opts.get("name") or info["name"]
    return Metric(big=name, extra={"logo": info["logo"]})


def _cores(widget, opts, stats, now):
    cores = list(stats.get("cpu_cores_percent") or [])[:opts.get("max", 16)]
    if not cores:
        return Metric(available=False, big="—")
    return Metric(fraction=sum(cores) / len(cores) / 100, big=f"{len(cores)}",
                  extra={"cores": tuple(round(c) for c in cores)})


def _simple(text_fn):
    def build(widget, opts, stats, now):
        text = text_fn(stats, opts, now)
        return Metric(available=text not in (None, "", "—"), big=text or "—")
    return build


def _ip(stats, opts, now):
    addrs = stats.get("net_addrs") or {}
    wanted = opts.get("iface", "auto")
    if wanted != "auto":
        return (addrs.get(wanted) or {}).get("ipv4")
    for name in sorted(addrs, key=lambda n: (not n.startswith(("en", "eth", "wl")), n)):
        return addrs[name]["ipv4"]
    return None


def _battery(widget, opts, stats, now):
    battery = stats.get("battery")
    if not battery:
        return Metric(available=False, big="—")
    percent = battery["percent"]
    return Metric(fraction=percent / 100, big=f"{percent:.0f}%",
                  lines=[("state", _("charging") if battery["plugged"] else _("on battery"))])


def _processes(widget, opts, stats, now):
    key = "procs_mem" if opts.get("sort") == "memory" else "procs"
    procs = (stats.get(key) or [])[:opts.get("count", 4)]
    field_name = "memory_percent" if opts.get("sort") == "memory" else "cpu_percent"
    rows = tuple((str(p.get("name", "?"))[:18], f"{(p.get(field_name) or 0):.0f}%") for p in procs)
    return Metric(available=bool(rows), big="", extra={"rows": rows})


def _text(widget, opts, stats, now):
    return Metric(big=opts.get("text", ""))


BUILDERS = {
    "cpu": _cpu, "gpu": _gpu_metric, "ram": _ram, "swap": _swap, "vram": _vram, "fan": _fan_metric,
    "encdec": _encdec, "disk": _disk, "net_down": _net("down"), "net_up": _net("up"), "clock": _clock,
    "distro": _distro, "cores": _cores, "battery": _battery, "processes": _processes, "text": _text,
    "uptime": _simple(lambda s, o, now: uptime_text(s.get("boot_time"), now)),
    "hostname": _simple(lambda s, o, now: s.get("hostname")),
    "kernel": _simple(lambda s, o, now: s.get("kernel")),
    "ip": _simple(_ip),
    "power": _simple(lambda s, o, now: s.get("power_profile") or None),
    "separator": lambda w, o, s, now: Metric(), "frame": lambda w, o, s, now: Metric(),
}


# ---------------------------------------------------------------- telemetry needs

def needs(widgets):
    """What the collector must sample for these widgets."""
    result = {"fans": False, "disks": set(), "processes": False, "sensors": False, "addrs": False}
    for widget in widgets:
        if not widget.get("visible", True):
            continue
        kind, opts = widget["type"], widget.get("opts", {})
        if kind == "fan":
            result["fans"] = True
        elif kind == "disk":
            result["disks"].add(opts.get("mount", "/"))
        elif kind == "processes":
            result["processes"] = True
        elif kind == "ip":
            result["addrs"] = True
        elif kind == "cpu" and opts.get("temp_sensor", "auto") != "auto":
            result["sensors"] = True
    return result


# ---------------------------------------------------------------- demo data

def demo_stats(now=None):
    """Plausible moving values for the editor when no real data is wanted."""
    t = now or time.time()

    def wave(period, low, high, phase=0.0):
        return low + (high - low) * (0.5 + 0.5 * math.sin(t * 2 * math.pi / period + phase))
    history = [wave(9, 10, 70, i * 0.4) for i in range(30)]
    gpu = {"path": "demo", "name": "Demo GPU", "percent": wave(7, 20, 85), "temp_value": wave(23, 48, 71),
           "temp_crit": 100.0, "clock_mhz": int(wave(5, 600, 2400)), "mem_used_mb": 3200, "mem_total_mb": 8192,
           "power_w": wave(6, 30, 160), "video_engine": "VCN", "enc_percent": wave(11, 0, 40),
           "usage_history": history}
    return {
        "cpu_percent": wave(5, 8, 64), "cpu_temp_value": wave(19, 45, 78), "cpu_temp_crit": None,
        "cpu_freq_mhz": wave(4, 2200, 4600), "cpu_model": "Demo CPU 8-Core", "cpu_history": history,
        "cpu_cores_percent": [wave(3 + i % 5, 0, 100, i) for i in range(8)],
        "ram_used_mb": 7340, "ram_total_mb": 16384, "ram_history": [45] * 30,
        "swap_used_mb": 820, "swap_total_mb": 8192,
        "gpus": [gpu], "fans": [{"id": "demo/fan1", "label": "CPU fan", "chip": "demo", "rpm": int(wave(13, 900, 1800)),
                                 "percent": wave(13, 35, 70)}],
        "disks": {"/": {"available": True, "percent": 63.0, "used_gb": 588, "total_gb": 931, "temp": 38.0,
                        "temp_crit": 84.0, "read_kbs": wave(3, 0, 900), "write_kbs": wave(4, 0, 400)}},
        "disk_percent": 63.0, "disk_used_gb": 588, "disk_total_gb": 931,
        "net_rx_mbps": wave(6, 0.5, 80), "net_tx_mbps": wave(8, 0.1, 12),
        "net_rx_history": [wave(6, 0.5, 80, i * 0.3) for i in range(30)],
        "net_tx_history": [wave(8, 0.1, 12, i * 0.3) for i in range(30)], "net_ifaces": {},
        "boot_time": t - 3 * 3600 - 1260, "hostname": "kojiro", "kernel": "6.18.0-demo",
        "net_addrs": {"enp7s0": {"ipv4": "192.168.0.42", "speed_mbps": 1000}},
        "battery": {"percent": 76.0, "plugged": True}, "power_profile": "balanced",
        "procs": [{"name": "firefox", "cpu_percent": 12.0}, {"name": "kwin_wayland", "cpu_percent": 4.0},
                  {"name": "python3", "cpu_percent": 2.0}, {"name": "pipewire", "cpu_percent": 1.0}],
        "procs_mem": [], "sensors": [],
    }
