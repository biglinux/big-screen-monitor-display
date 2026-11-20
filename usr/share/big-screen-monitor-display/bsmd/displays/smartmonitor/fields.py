"""Live quantities a captured theme can show on the SmartMonitor panel.

A *field* is something a theme draws from the telemetry (CPU usage, RAM used,
the clock...). For the capture (:mod:`.capture`) each field knows how to
change the telemetry so that only it changes on screen (``vary``), and which
quantities a number drawn for it may be (``candidates``): "11.3" next to RAM is
``ram_used_mb`` x 1/1024, "07" in a clock is the minute.

At run time a *binding* (channel, field, candidate, scale, part) turns the
current telemetry into the integer the panel draws: see :func:`binding_value`.
"""

import datetime
import math
import time

# The clock is frozen at T0 for every capture render and moved to T1 to find
# what depends on it. No two components share a value (14, 29, 35, 8, 11, 2026,
# Sunday), so a number found on screen tells which component it is.
T0 = datetime.datetime(2026, 11, 8, 14, 29, 35)
T1 = datetime.datetime(2027, 3, 17, 9, 47, 57)     # odd seconds like T0: a blinking colon stays the same
BOOT0 = 4380.0          # seconds of uptime at T0 -> 01:13
BOOT1 = 49320.0         # -> 13:42: the same day, so "up 01:13" keeps its format ("1d 13:42" would not)


def set_date(day):
    """Capture at ``day`` (a date): the date is drawn into the picture (renewed daily,
    see layout.spec) and only the time of day moves between T0 and T1."""
    global T0, T1
    T0 = T0.replace(year=day.year, month=day.month, day=day.day)
    T1 = T1.replace(year=day.year, month=day.month, day=day.day)


def _gpu(stats):
    gpus = [g for g in stats.get("gpus") or [] if g.get("path")] or list(stats.get("gpus") or [])
    if not gpus:
        return {}
    index = stats.get("active_gpu_idx", 0)
    return gpus[index] if 0 <= index < len(gpus) else gpus[0]


def _uptime(stats, now):
    boot = stats.get("boot_time")
    return max(0.0, now - boot) if boot else 0.0


def _media(stats):
    media = stats.get("media")
    return media if isinstance(media, dict) and media.get("present") else {}


def _elapsed(stats, t):
    """Seconds into the track now (interpolated while playing, as the player does)."""
    media = _media(stats)
    position = media.get("position_us")
    if position is None:
        return 0.0
    seconds = position / 1e6
    if media.get("status") == "Playing" and media.get("position_mono") is not None:
        seconds += max(0.0, time.monotonic() - media["position_mono"]) * (media.get("rate") or 1.0)
    length = media.get("length_us")
    return min(seconds, length / 1e6) if length else seconds


def _length(stats):
    length = _media(stats).get("length_us")
    return length / 1e6 if length else 0.0


def _load(stats, index):
    load = stats.get("load_avg") or (0.0, 0.0, 0.0)
    return load[index] if len(load) > index else 0.0


# candidate name -> f(stats, now_epoch, now_datetime)
CANDIDATES = {
    "cpu_percent": lambda s, t, d: s.get("cpu_percent") or 0.0,
    "cpu_user": lambda s, t, d: s.get("cpu_user") or 0.0,
    "cpu_system": lambda s, t, d: s.get("cpu_system") or 0.0,
    "cpu_temp": lambda s, t, d: s.get("cpu_temp_value") or 0.0,
    "cpu_temp_f": lambda s, t, d: (s.get("cpu_temp_value") or 0.0) * 9 / 5 + 32,
    "cpu_mhz": lambda s, t, d: s.get("cpu_freq_mhz") or 0.0,
    "cpu_power": lambda s, t, d: s.get("cpu_power_w") or 0.0,
    "ram_percent": lambda s, t, d: s.get("ram_percent") or 0.0,
    "ram_used_mb": lambda s, t, d: s.get("ram_used_mb") or 0.0,
    "ram_used_pct": lambda s, t, d: (100.0 * (s.get("ram_used_mb") or 0) / s["ram_total_mb"]
                                     if s.get("ram_total_mb") else 0.0),
    "swap_used_pct": lambda s, t, d: (100.0 * (s.get("swap_used_mb") or 0) / s["swap_total_mb"]
                                      if s.get("swap_total_mb") else 0.0),
    "disk_used_pct": lambda s, t, d: (100.0 * (s.get("disk_used_gb") or 0) / s["disk_total_gb"]
                                      if s.get("disk_total_gb") else 0.0),
    "swap_percent": lambda s, t, d: s.get("swap_percent") or 0.0,
    "swap_used_mb": lambda s, t, d: s.get("swap_used_mb") or 0.0,
    "disk_percent": lambda s, t, d: s.get("disk_percent") or 0.0,
    "disk_used_gb": lambda s, t, d: s.get("disk_used_gb") or 0.0,
    "disk_io_kbs": lambda s, t, d: s.get("disk_io_kbs") or 0.0,
    "net_rx_mbps": lambda s, t, d: s.get("net_rx_mbps") or 0.0,
    "net_tx_mbps": lambda s, t, d: s.get("net_tx_mbps") or 0.0,
    "gpu_percent": lambda s, t, d: _gpu(s).get("percent") or 0.0,
    "gpu_temp": lambda s, t, d: _gpu(s).get("temp_value") or 0.0,
    "gpu_temp_f": lambda s, t, d: (_gpu(s).get("temp_value") or 0.0) * 9 / 5 + 32,
    "gpu_mem_used_mb": lambda s, t, d: _gpu(s).get("mem_used_mb") or 0.0,
    "gpu_mem_percent": lambda s, t, d: (100.0 * (_gpu(s).get("mem_used_mb") or 0) / _gpu(s)["mem_total_mb"]
                                        if _gpu(s).get("mem_total_mb") else 0.0),
    "gpu_enc": lambda s, t, d: _gpu(s).get("enc_percent") or 0.0,
    "gpu_mem_total_mb": lambda s, t, d: _gpu(s).get("mem_total_mb") or 0.0,
    "gpu_clock": lambda s, t, d: _gpu(s).get("clock_mhz") or 0.0,
    "gpu_power": lambda s, t, d: _gpu(s).get("power_w") or 0.0,
    "load1": lambda s, t, d: _load(s, 0),
    "load5": lambda s, t, d: _load(s, 1),
    "load15": lambda s, t, d: _load(s, 2),
    "procs": lambda s, t, d: s.get("proc_count") or len(s.get("procs") or ()),
    "uptime_hours": lambda s, t, d: _uptime(s, t) // 3600,
    "uptime_hours_mod": lambda s, t, d: (_uptime(s, t) // 3600) % 24,
    "uptime_minutes": lambda s, t, d: (_uptime(s, t) // 60) % 60,
    "uptime_days": lambda s, t, d: _uptime(s, t) // 86400,
    "media_min": lambda s, t, d: _elapsed(s, t) // 60,
    "media_sec": lambda s, t, d: _elapsed(s, t) % 60,
    "media_left_min": lambda s, t, d: max(0.0, _length(s) - _elapsed(s, t)) // 60,
    "media_left_sec": lambda s, t, d: max(0.0, _length(s) - _elapsed(s, t)) % 60,
    "media_pct": lambda s, t, d: 100.0 * _elapsed(s, t) / _length(s) if _length(s) else 0.0,
    "media_volume": lambda s, t, d: _media(s).get("volume") or 0.0,
    "media_muted": lambda s, t, d: 1.0 if _media(s).get("muted") else 0.0,
    "media_paused": lambda s, t, d: 0.0 if _media(s).get("status") == "Playing" else 1.0,
    "media_len_min": lambda s, t, d: _length(s) // 60,
    "media_len_sec": lambda s, t, d: _length(s) % 60,
    "hour": lambda s, t, d: d.hour,
    "hour12": lambda s, t, d: (d.hour % 12) or 12,
    "minute": lambda s, t, d: d.minute,
    "second": lambda s, t, d: d.second,
    "day": lambda s, t, d: d.day,
    "month": lambda s, t, d: d.month,
    "year": lambda s, t, d: d.year,
    "year2": lambda s, t, d: d.year % 100,
    "weekday": lambda s, t, d: d.weekday(),          # word atlases: Monday = 0
    "month0": lambda s, t, d: d.month - 1,           # word atlases: January = 0
}


def _with_gpu(stats, **changes):
    gpus = [dict(g) for g in stats.get("gpus") or [{}]]
    if not gpus:
        gpus = [{}]
    index = stats.get("active_gpu_idx", 0)
    index = index if 0 <= index < len(gpus) else 0
    gpus[index].update(changes)
    return {"gpus": gpus}


def _temp_text(value):
    return f"{value:.0f}°C"


# field -> (priority, (delta A, delta B), candidates). A delta is a function of
# the base stats returning the keys to change. Lower priority numbers are kept
# first when a theme has more live values than the panel can serve.
FIELDS = {
    # Two digits in both variants: the "%" after it is drawn into the picture, so the
    # value captured sets where it sits (with "7%" a later "13%" covered the sign).
    "cpu_percent": (10, (lambda s: {"cpu_percent": 17.0}, lambda s: {"cpu_percent": 36.0}), ("cpu_percent",)),
    "cpu_temp": (12, (lambda s: {"cpu_temp_value": 53.0, "cpu_temp": _temp_text(53)},
                      lambda s: {"cpu_temp_value": 61.0, "cpu_temp": _temp_text(61)}), ("cpu_temp", "cpu_temp_f")),
    "ram_percent": (14, (lambda s: {"ram_percent": 24.0}, lambda s: {"ram_percent": 47.0}), ("ram_percent",)),
    "ram_used": (15, (lambda s: {"ram_used_mb": 11571}, lambda s: {"ram_used_mb": 20700}),
                 ("ram_used_mb", "ram_used_pct")),
    "gpu_percent": (20, (lambda s: _with_gpu(s, percent=12.0), lambda s: _with_gpu(s, percent=41.0)),
                    ("gpu_percent",)),
    "gpu_temp": (21, (lambda s: _with_gpu(s, temp_value=54.0, temp=_temp_text(54)),
                      lambda s: _with_gpu(s, temp_value=63.0, temp=_temp_text(63))), ("gpu_temp", "gpu_temp_f")),
    "gpu_mem": (24, (lambda s: _with_gpu(s, mem_used_mb=1741), lambda s: _with_gpu(s, mem_used_mb=9216)),
                ("gpu_mem_used_mb", "gpu_mem_percent")),
    "disk_percent": (30, (lambda s: {"disk_percent": 59.0}, lambda s: {"disk_percent": 71.0}), ("disk_percent",)),
    "disk_used": (32, (lambda s: _disk(s, 262.4), lambda s: _disk(s, 371.8)), ("disk_used_gb", "disk_used_pct")),
    "net_rx": (34, (lambda s: {"net_rx_mbps": 2.9}, lambda s: {"net_rx_mbps": 6.3}), ("net_rx_mbps",)),
    "net_tx": (35, (lambda s: {"net_tx_mbps": 0.87}, lambda s: {"net_tx_mbps": 0.31}), ("net_tx_mbps",)),
    "cpu_split": (41, (lambda s: {"cpu_user": 15.0, "cpu_system": 12.0}, lambda s: {"cpu_user": 31.0, "cpu_system": 19.0}),
                  ("cpu_user", "cpu_system")),
    "cpu_freq": (40, (lambda s: {"cpu_freq_mhz": 3774.0}, lambda s: {"cpu_freq_mhz": 2210.0}), ("cpu_mhz",)),
    "swap_percent": (42, (lambda s: {"swap_percent": 3.0}, lambda s: {"swap_percent": 27.0}), ("swap_percent",)),
    "swap_used": (43, (lambda s: {"swap_used_mb": 612}, lambda s: {"swap_used_mb": 9420}),
                  ("swap_used_mb", "swap_used_pct")),
    "gpu_enc": (45, (lambda s: _with_gpu(s, enc_percent=9.0), lambda s: _with_gpu(s, enc_percent=33.0)),
                ("gpu_enc",)),
    "gpu_clock": (46, (lambda s: _with_gpu(s, clock_mhz=1768.0), lambda s: _with_gpu(s, clock_mhz=914.0)),
                  ("gpu_clock",)),
    "gpu_power": (47, (lambda s: _with_gpu(s, power_w=27.0), lambda s: _with_gpu(s, power_w=64.0)), ("gpu_power",)),
    "disk_io": (50, (lambda s: {"disk_io_kbs": 2048.0}, lambda s: {"disk_io_kbs": 9300.0}), ("disk_io_kbs",)),
    "cpu_power": (52, (lambda s: {"cpu_power_w": 26.0}, lambda s: {"cpu_power_w": 61.0}), ("cpu_power",)),
    "media_position": (5, (lambda s: _with_media(s, position_us=83_000_000),
                           lambda s: _with_media(s, position_us=197_000_000)),
                       ("media_min", "media_sec", "media_left_min", "media_left_sec", "media_pct")),
    "media_volume": (6, (lambda s: _with_media(s, volume=35), lambda s: _with_media(s, volume=72)),
                     ("media_volume",)),
    "media_length": (7, (lambda s: _with_media(s, length_us=236_000_000),
                         lambda s: _with_media(s, length_us=312_000_000)),
                     ("media_len_min", "media_len_sec", "media_left_min", "media_left_sec")),
    "uptime": (60, (lambda s: {"boot_time": T0.timestamp() - BOOT0}, lambda s: {"boot_time": T0.timestamp() - BOOT1}),
               ("uptime_hours", "uptime_hours_mod", "uptime_minutes", "uptime_days")),
    "load": (70, (lambda s: {"load_avg": (3.78, 3.96, 3.79)}, lambda s: {"load_avg": (1.21, 2.54, 6.07)}),
             ("load1", "load5", "load15")),
    "procs": (80, (lambda s: {"proc_count": 497}, lambda s: {"proc_count": 1208}), ("procs",)),
}
CLOCK_PRIORITY = 0

# Key of a capture variant setting the level of every history graph (see capture.render).
HISTORY_LEVEL = "_history_level"

# Fans: one live value per fan (RPM and PWM duty), found by its id ("nct6793/fan2"),
# so a theme showing a chosen fan keeps showing that one. Each fan gets its own
# values in the capture variants, so a number drawn for a fan tells which fan it is.
# Fans standing still keep 0 RPM in every variant: "auto" picks the same fan the
# themes pick at run time (the first one spinning).
FAN_PRIORITY = 38
FAN_RPM, FAN_PCT = "fan_rpm:", "fan_pct:"


def _fan_changes(stats, variant):
    fans = []
    for index, fan in enumerate(stats.get("fans") or []):
        fan = dict(fan)
        if fan.get("rpm"):
            fan["rpm"] = (1137 if variant == 0 else 2351) + 97 * index
        if fan.get("percent") is not None or fan.get("rpm"):
            fan["percent"] = float((23 if variant == 0 else 58) + 3 * index)
        fans.append(fan)
    return {"fans": fans}


def _fan_percent(stats, pct):
    return {"fans": [dict(fan, percent=float(pct)) for fan in stats.get("fans") or []]}


def _fan_value(stats, name):
    kind, wanted = (FAN_RPM, name[len(FAN_RPM):]) if name.startswith(FAN_RPM) else (FAN_PCT, name[len(FAN_PCT):])
    fan = next((f for f in stats.get("fans") or [] if f.get("id") == wanted), None)
    if fan is None:
        return 0.0
    return float((fan.get("rpm") if kind == FAN_RPM else fan.get("percent")) or 0.0)


IFACE_PRIORITY = 36
IFACE_RX, IFACE_TX = "iface_rx:", "iface_tx:"
NESTED_HISTORIES = (("gpus", ("usage_history", "mem_history")), ("net_ifaces", ("rx_history", "tx_history")))


def _iface_changes(stats, variant):
    ifaces = {}
    for index, (name, data) in enumerate(sorted((stats.get("net_ifaces") or {}).items())):
        data = dict(data)
        data["rx"] = (2.9 if variant == 0 else 6.3) + 0.4 * index      # Mb/s, above 1: "2.9M"
        data["tx"] = (1.3 if variant == 0 else 4.7) + 0.4 * index
        ifaces[name] = data
    return {"net_ifaces": ifaces}


def _iface_value(stats, name):
    key, wanted = ("rx", name[len(IFACE_RX):]) if name.startswith(IFACE_RX) else ("tx", name[len(IFACE_TX):])
    data = (stats.get("net_ifaces") or {}).get(wanted) or {}
    return float(data.get(key) or 0.0)


def set_ifaces(ifaces):
    """Make each network interface's traffic a live value of the next capture."""
    names = sorted(ifaces or {})
    if not names:
        FIELDS.pop("iface", None)
        return
    FIELDS["iface"] = (IFACE_PRIORITY, (lambda s: _iface_changes(s, 0), lambda s: _iface_changes(s, 1)),
                       tuple(IFACE_RX + n for n in names) + tuple(IFACE_TX + n for n in names))


def set_fans(fans):
    """Make the fans of this computer live values of the next capture."""
    fans = [f for f in fans or [] if f.get("id")]
    if not fans:
        FIELDS.pop("fan", None)
        PERCENT.pop("fan", None)
        return
    names = tuple(FAN_RPM + f["id"] for f in fans) + tuple(FAN_PCT + f["id"] for f in fans)
    FIELDS["fan"] = (FAN_PRIORITY, (lambda s: _fan_changes(s, 0), lambda s: _fan_changes(s, 1)), names)
    spinning = [f for f in fans if f.get("rpm")]
    from ...kojiro.data import _fan as pick
    auto = pick({"fans": spinning}, "auto") if spinning else None
    if auto is not None:
        PERCENT["fan"] = (_fan_percent, FAN_PCT + auto["id"])
    else:
        PERCENT.pop("fan", None)

# How to put a field at a given percentage (0..100) of its bar, and the candidate
# that bar follows. Used to find bars and photograph them empty and full.
PERCENT = {
    "cpu_percent": (lambda s, p: {"cpu_percent": float(p)}, "cpu_percent"),
    # Themes compute some bars from used/total: keep both views consistent.
    "ram_percent": (lambda s, p: {"ram_percent": float(p), "ram_used_mb": (s.get("ram_total_mb") or 16384) * p / 100},
                    "ram_percent"),
    "swap_percent": (lambda s, p: {"swap_percent": float(p),
                                   "swap_used_mb": (s.get("swap_total_mb") or 8192) * p / 100}, "swap_percent"),
    "disk_percent": (lambda s, p: dict(_disk(s, (s.get("disk_total_gb") or 447.0) * p / 100), disk_percent=float(p)),
                     "disk_percent"),
    "gpu_percent": (lambda s, p: _with_gpu(s, percent=float(p)), "gpu_percent"),
    "gpu_mem": (lambda s, p: _with_gpu(s, mem_used_mb=(_gpu(s).get("mem_total_mb") or 8192) * p / 100),
                "gpu_mem_percent"),
    "cpu_temp": (lambda s, p: {"cpu_temp_value": float(p), "cpu_temp": _temp_text(p)}, "cpu_temp"),
    "gpu_temp": (lambda s, p: _with_gpu(s, temp_value=float(p), temp=_temp_text(p)), "gpu_temp"),
    "media_position": (lambda s, p: _with_media(s, position_us=int(236_000_000 * p / 100)), "media_pct"),
    "media_volume": (lambda s, p: _with_media(s, volume=float(p)), "media_volume"),
}
# Things with a few states drawn as icons (mute, play/pause): photographed in each
# state and shown by one widget whose glyph cell k is state k.
STATES = {
    "media_mute": (lambda s, k: _with_media(s, muted=bool(k)), 2, "media_muted"),
    "media_play": (lambda s, k: _with_media(s, status="Paused" if k else "Playing"), 2, "media_paused"),
}

# The player's spectrum visualizer: the capture draws it with SPECTRUM bands, each a
# gauge of its own (the agent sends 24; they are grouped for the panel). The count
# shrinks when the panel has no room left for twelve (see set_spectrum).
SPECTRUM = 12
SPECTRUM_MAX = 12


def _band_setter(index):
    def setter(stats, pct):
        bands = list((stats.get("media") or {}).get("bands") or [0.3] * SPECTRUM)
        bands[index] = pct / 100
        return _with_media(stats, bands=bands)
    return setter


def set_spectrum(count):
    """Draw the visualizer with ``count`` bands in the next capture (0: none)."""
    global SPECTRUM
    SPECTRUM = count
    for index in range(SPECTRUM_MAX):
        PERCENT.pop(f"band{index}", None)
    for index in range(count):
        CANDIDATES[f"band{index}"] = (lambda i: lambda s, t, d: 100.0 * ((_media(s).get("bands") or [])
                                                                           + [0.0] * SPECTRUM_MAX)[i])(index)
        PERCENT[f"band{index}"] = (_band_setter(index), f"band{index}")


set_spectrum(SPECTRUM_MAX)


def regroup(bands, count):
    """``bands`` (any number) as ``count`` bands, each the loudest of its group."""
    if not bands or count <= 0:
        return []
    step = len(bands) / count
    return [max(bands[int(i * step):max(int(i * step) + 1, int((i + 1) * step))]) for i in range(count)]


def panel_bands(bands):
    """The agent's spectrum (any number of bands) as the most the panel can show."""
    return regroup(bands, SPECTRUM_MAX) or None


CLOCK_CANDIDATES = ("hour", "hour12", "minute", "second", "day", "month", "year", "year2", "weekday", "month0")


MEDIA_SAMPLE = {"present": True, "status": "Playing", "title": "Sample Title", "artist": "Sample Artist",
                "album": "Sample Album", "identity": "Player", "length_us": 236_000_000, "position_us": 83_000_000,
                "position_mono": None, "rate": 0.0, "art": None, "volume": 35, "muted": False}


def _with_media(stats, **changes):
    media = dict(stats.get("media") or MEDIA_SAMPLE)
    media.update(changes)
    return {"media": media}


def track_noise(stats):
    """Another song: title, artist, album and cover change (left out unless the panel is
    flashed again on every song)."""
    return _with_media(stats, title="Other Song Name", artist="Different Band", album="Another Record",
                       art=None, identity="Player")


def noise(stats):
    """Everything a theme may show that no field covers (other GPUs, sensor lists,
    fans, per-core loads, disks, battery, processes), changed at once: what moves
    with it cannot be kept live, so the capture leaves it out instead of freezing it."""
    changes = {}
    gpus = [dict(g) for g in stats.get("gpus") or []]
    active = stats.get("active_gpu_idx", 0)
    for index, gpu in enumerate(gpus):
        # The active GPU's clock, power and encoder are live fields: only the other
        # GPUs' are noise (left out when a theme shows them).
        for key in ("clock_mhz", "power_w", "enc_percent"):
            if index != active:
                gpu[key] = (gpu.get(key) or 0) * 1.37 + 11
        for key in ("edge", "junc", "mem"):             # hwmon temperature strings ("54.0°C")
            if gpu.get(key):
                try:
                    gpu[key] = f"{float(str(gpu[key]).replace('°C', '')) + 9:.1f}°C"
                except ValueError:
                    pass
        if index != active:
            gpu["percent"] = (gpu.get("percent") or 0) + 23
            gpu["mem_used_mb"] = (gpu.get("mem_used_mb") or 0) + 733
            gpu["temp_value"] = (gpu.get("temp_value") or 40) + 9
            gpu["temp"] = f"{gpu['temp_value']:.0f}°C"
    if gpus:
        changes["gpus"] = gpus
    changes[HISTORY_LEVEL] = 70
    for key, names in NESTED_HISTORIES:
        items = changes.get(key, stats.get(key))
        if not items:
            continue
        moved = [dict(i) for i in items] if isinstance(items, list) else {n: dict(d) for n, d in items.items()}
        for item in (moved if isinstance(moved, list) else moved.values()):
            for name in names:
                if item.get(name):
                    item[name] = [70] * len(item[name])
        changes[key] = moved
    changes["sensors"] = [(group, label, (value or 0) + 7.3 if isinstance(value, (int, float)) else value, unit)
                          for group, label, value, unit in (tuple(item) for item in stats.get("sensors") or [])]
    if "fan" not in FIELDS:
        changes["fans"] = [dict(fan, rpm=(fan.get("rpm") or 0) + 111, percent=(fan.get("percent") or 0) + 17)
                           for fan in stats.get("fans") or []]
    changes["cpu_cores_percent"] = [(value or 0) + 13 for value in stats.get("cpu_cores_percent") or []]
    changes["disks"] = {mount: {k: (v * 1.3 + 3 if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                                for k, v in info.items()} for mount, info in (stats.get("disks") or {}).items()}
    changes["procs"] = [dict(p, name=(p.get("name") or "")[::-1] + "x", cpu_percent=(p.get("cpu_percent") or 0) + 9)
                        for p in stats.get("procs") or []]
    changes["procs_mem"] = [dict(p, name=(p.get("name") or "")[::-1] + "x") for p in stats.get("procs_mem") or []]
    battery = stats.get("battery")
    if isinstance(battery, dict):
        changes["battery"] = dict(battery, percent=(battery.get("percent") or 0) + 17)
    changes["power_profile"] = (stats.get("power_profile") or "") + "x"
    return changes


def _disk(stats, used):
    total = stats.get("disk_total_gb") or 447.0
    return {"disk_used_gb": used, "disk_percent": stats.get("disk_percent", 59.0),
            "disk_text": f"{used:.0f}/{total:.0f} GB", "disk_total_gb": total}


def base_stats(stats):
    """The telemetry every capture render starts from (realistic, fixed)."""
    base = dict(stats)
    set_fans(stats.get("fans"))
    set_ifaces(stats.get("net_ifaces"))
    base.update({"valid": True, "boot_time": T0.timestamp() - BOOT0, "proc_count": 497,
                 "load_avg": (3.78, 3.96, 3.79), "cpu_freq_mhz": 3774.0, "cpu_power_w": 26.0,
                 "cpu_power_status": "ok", "disk_io_kbs": 2048.0, "cpu_temp_at": T0.timestamp()})
    media = stats.get("media") if isinstance(stats.get("media"), dict) else {}
    if media.get("present"):
        # The real track as the player shows it, frozen (rate 0) for the capture.
        track = dict(MEDIA_SAMPLE)
        track.update({k: v for k, v in media.items() if k != "art_image"})
        # A player that reports no length (some browsers, streams) keeps none: the
        # theme shows what it shows then, instead of a total of 0:00.
        known = bool(media.get("length_us"))
        track.update(rate=0.0, position_mono=None, position_us=83_000_000,
                     length_us=236_000_000 if known else None,
                     status="Playing", volume=35, muted=False, bands=[0.3] * SPECTRUM)
        base["media"] = track
    else:
        base["media"] = {"present": False}
    for name, field in FIELDS.items():
        if name.startswith("media_") and not media.get("present"):
            continue
        base.update(field[1][0](base))
    if not base.get("ram_total_mb"):
        base["ram_total_mb"] = 47513
    return base


def candidate_value(name, stats, now=None):
    if name.startswith((FAN_RPM, FAN_PCT)):
        return _fan_value(stats, name)
    if name.startswith((IFACE_RX, IFACE_TX)):
        return _iface_value(stats, name)
    now = now or time.time()
    return float(CANDIDATES[name](stats, now, datetime.datetime.fromtimestamp(now)))


def binding_value(binding, stats, now=None):
    """Integer for one channel. ``binding`` keys: cand, scale, part ("int", "frac",
    "tens", "ones", "word", "pct", "whole"), decimals, digits."""
    if binding["cand"].startswith("band") and binding.get("of"):
        # A visualizer captured with fewer bands: regroup the live spectrum the same way.
        bands = regroup((_media(stats).get("bands") or []), binding["of"])
        index = int(binding["cand"][4:])
        value = 100.0 * (bands[index] if index < len(bands) else 0.0)
    else:
        value = candidate_value(binding["cand"], stats, now) * binding.get("scale", 1.0)
    part = binding.get("part", "whole")
    decimals = binding.get("decimals", 0)
    if part == "state":
        return max(0, min(9, int(round(value))))
    if part == "level":
        # A gauge drawn from ten photographed levels: cell k shows level k.
        return max(0, min(9, round(max(0.0, min(100.0, value)) / 100 * 9)))
    if part == "word_chunk":
        # Words first..first+8 live in cells 0..8 of this widget; cell 9 is blank.
        first = binding.get("first", 0)
        result = value - first if first <= value < first + 9 else 9
    elif part in ("word", "pct"):
        result = value
    elif part == "frac":
        scaled = round(abs(value) * 10 ** decimals)
        result = scaled % (10 ** decimals)
    elif part == "frac_digit":
        scaled = round(abs(value) * 10 ** decimals) % (10 ** decimals)
        result = (scaled // 10 ** (decimals - 1 - binding.get("digit", 0))) % 10
    elif part == "int":
        result = math.floor(round(abs(value), decimals))
    elif part == "tens":
        result = (round(abs(value)) // 10) % 10
    elif part == "ones":
        result = round(abs(value)) % 10
    else:
        result = abs(value)
    if part == "pct":
        result = max(0.0, min(100.0, result))
        curve = binding.get("curve")
        if curve:
            # The theme's fill is not linear in the width (a gauge arc): follow its curve.
            step = min(3, int(result // 25))
            low, high = curve[step], curve[step + 1]
            result = low + (high - low) * (result - step * 25) / 25
    return max(0, min(0xFFFF, round(result)))
