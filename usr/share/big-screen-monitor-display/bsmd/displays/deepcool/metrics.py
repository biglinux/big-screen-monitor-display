"""CPU metrics for DeepCool coolers: values, presentations and theme adaptation.

Values come from the shared telemetry collector (bsmd.telemetry); nothing
here reads sensors. A value the computer does not provide, or one that has
gone stale, is ``None`` with a reason - never a zero. What reaches a
device is decided by :func:`build_frame`:

* single-field families (AK, AG, LS) choose which metric the field shows;
  an unavailable metric is never shown (the field switches to one that is);
* fixed-layout families (AK PRO, LD, MYSTIQUE) always receive every field
  the firmware draws. They have no "blank" value: an unavailable metric is
  sent as 0 and reported as such in the status and the interface.
"""

import time
from dataclasses import dataclass, field

from ...i18n import N_
from .models import FREQ, GPU_TEMP, POWER, RAM, TEMP, USAGE

AUTO_SWITCH = 5.0          # seconds per metric when a single field alternates (as the vendor software)

# Native DeepCool presentations.
PRESETS = {
    "essentials": (N_("CPU Essentials"), N_("Temperature and usage, alternating on single-field coolers.")),
    "advanced": (N_("CPU Advanced"), N_("Temperature, power, usage and frequency, as many as the cooler shows.")),
    "guardian": (N_("CPU Guardian"), N_("Temperature always on screen; the alarm lamp lights up at the "
                                         "threshold.")),
    "performance": (N_("CPU Performance"), N_("Load first: usage, or power on coolers that show power.")),
    "minimal": (N_("CPU Minimal"), N_("Only the temperature.")),
    "custom": (N_("CPU Custom"), N_("You choose what the configurable field shows.")),
}
PRESET_IDS = ("auto",) + tuple(PRESETS)

# How each existing theme is represented on a numeric cooler (Theme Capability Adapter).
THEME_ADAPTER = {
    "standard": ("essentials", "adapted", N_("Uses the standard CPU fields of the cooler.")),
    "gkrellm": ("performance", "adapted", N_("Shows the supported CPU numbers; GKrellM's charts cannot be drawn "
                                           "on a numeric display.")),
    "planet": ("essentials", "partial", N_("The globe cannot be drawn; the cooler shows the CPU fields instead.")),
    "old_computer": ("essentials", "partial", N_("The window look cannot be drawn; CPU fields are shown.")),
    "kojiro": ("custom", "adapted", N_("Choose which metric the configurable field shows; the wallpaper and "
                                     "widget layout stay on graphic displays.")),
    "brother_away": ("guardian", "unsupported", N_("The island story needs a graphic display; the cooler keeps "
                                                 "monitoring the CPU.")),
    "big_media_player": ("essentials", "unsupported", N_("Album art and playback need a graphic display; the "
                                                       "cooler keeps monitoring the CPU.")),
}
COMPATIBILITY = {"native": N_("Compatible"), "adapted": N_("Compatible with adaptation"),
                 "partial": N_("Partially compatible"), "unsupported": N_("Not compatible"),
                 "untested": N_("Not tested")}


@dataclass
class Values:
    temp: float = None              # °C
    usage: float = None             # %
    power: float = None             # W
    freq: float = None              # MHz
    ram: float = None               # %
    gpu_temp: float = None          # °C
    reasons: dict = field(default_factory=dict)

    def get(self, metric):
        return getattr(self, metric)


def gather(stats, now=None, freq_source="max"):
    """Metric values from a telemetry snapshot (``telemetry.snapshot()``)."""
    from ... import telemetry
    now = time.monotonic() if now is None else now
    values = Values()
    if not stats.get("valid"):
        values.reasons = {m: N_("no data yet") for m in (TEMP, USAGE, POWER, FREQ, RAM, GPU_TEMP)}
        return values
    temp_at = stats.get("cpu_temp_at")
    if stats.get("cpu_temp_value") is None or temp_at is None:
        values.reasons[TEMP] = N_("no CPU temperature sensor (coretemp, k10temp or zenpower)")
    elif now - temp_at > telemetry.FRESH_FOR:
        values.reasons[TEMP] = N_("the temperature sensor stopped answering")
    else:
        values.temp = float(stats["cpu_temp_value"])
    if stats.get("cpu_percent") is not None:
        values.usage = max(0.0, min(100.0, float(stats["cpu_percent"])))
    power, power_at = stats.get("cpu_power_w"), stats.get("cpu_power_at")
    if power is not None and power_at is not None and now - power_at <= telemetry.FRESH_FOR:
        values.power = float(power)
    else:
        values.reasons[POWER] = {
            "permission": N_("no permission to read the CPU energy counter (the package's udev rule grants it "
                             "to the service)"),
            "warming": N_("measuring (needs two samples)"),
            "invalid": N_("the energy counter returned an invalid value"),
        }.get(stats.get("cpu_power_status"), N_("no CPU energy counter (RAPL, zenergy or amd_energy)"))
    freq = stats.get("cpu_freq_max_mhz") if freq_source == "max" else stats.get("cpu_freq_mhz")
    if freq:
        values.freq = float(freq)
    else:
        values.reasons[FREQ] = N_("the CPU frequency is not reported")
    if stats.get("ram_percent") is not None:
        values.ram = float(stats["ram_percent"])
    gpus = [g for g in stats.get("gpus") or [] if g.get("path")]
    gpu_temp = next((g.get("temp_value") for g in gpus if g.get("temp_value") is not None), None)
    if gpu_temp is not None:
        values.gpu_temp = float(gpu_temp)
    else:
        values.reasons[GPU_TEMP] = N_("no GPU temperature sensor")
    return values


def preset_for(settings):
    """(preset id, source theme or None) for a display's effective settings."""
    preset = settings.get("dc_preset", "auto")
    if preset in PRESETS:
        return preset, None
    theme = settings.get("theme", "standard")
    return THEME_ADAPTER.get(theme, ("essentials",))[0], theme


def compatibility(family, theme_id):
    """(state, explanation) of an existing theme on a DeepCool family."""
    if family.display == "lcd":
        # MYSTIQUE in information mode: the firmware draws its own screen.
        if theme_id in ("standard", "gkrellm", "kojiro"):
            return "adapted", N_("The cooler draws its own information screen with these CPU values; the theme's "
                                 "look cannot be sent (no safe live image transfer).")
        return "partial" if theme_id in ("planet", "old_computer") else "unsupported", \
            N_("This theme needs live images, which the cooler cannot receive safely; it keeps its information "
               "screen.")
    state, text = THEME_ADAPTER.get(theme_id, ("essentials", "untested", ""))[1:]
    if family.layout == "fixed" and state == "adapted":
        text = N_("The firmware shows its fixed CPU fields; the theme's choices do not change them.")
    return state, text


def main_metric(family, preset, settings, values, now):
    """Metric of the single configurable field (AK, AG, LS) - never an unavailable one."""
    choices = [m for m in family.main_choices if values.get(m) is not None]
    if not choices:
        return None
    if preset == "custom":
        wanted = settings.get("dc_main", "auto")
    else:
        wanted = {"essentials": "auto", "advanced": "auto", "guardian": TEMP, "minimal": TEMP,
                  "performance": POWER if POWER in family.main_choices else USAGE}.get(preset, "auto")
    if wanted in choices:
        return wanted
    if wanted != "auto" and wanted in family.main_choices:
        return choices[0]           # wanted metric unavailable right now: show what is real
    return choices[int(now // AUTO_SWITCH) % len(choices)]


@dataclass
class Frame:
    """What one update sends: the values per field and what was unavailable."""
    family: str
    fields: dict                    # metric -> value actually sent
    main: str = None                # single-field families: metric on the field
    alarm: bool = False
    fahrenheit: bool = False
    missing: tuple = ()             # fixed fields sent as 0 because the value is unavailable
    preset: str = "essentials"
    source_theme: str = None

    def describe(self):
        return {"family": self.family, "fields": {k: (None if v is None else round(v, 1))
                                                   for k, v in self.fields.items()},
                "main": self.main, "alarm": self.alarm, "fahrenheit": self.fahrenheit,
                "missing": list(self.missing), "preset": self.preset, "source_theme": self.source_theme}


def to_unit(celsius, fahrenheit):
    return celsius * 9 / 5 + 32 if fahrenheit else celsius


def build_frame(family, settings, values, now=None):
    now = time.monotonic() if now is None else now
    preset, theme = preset_for(settings)
    fahrenheit = family.fahrenheit and settings.get("dc_temp_unit", "c") == "f"
    if family.layout == "single":
        main = main_metric(family, preset, settings, values, now)
        fields = {main: values.get(main)} if main else {}
        if family.status_bar:
            fields[USAGE + "_bar"] = values.usage
    else:
        main = None
        fields = {metric: values.get(metric) for metric in family.fields}
    missing = tuple(m for m, v in fields.items() if v is None and not m.endswith("_bar"))
    alarm = False
    if family.software_alarm and values.temp is not None:
        enabled = settings.get("dc_alarm", True) or preset == "guardian"
        alarm = enabled and values.temp >= settings.get("dc_alarm_temp", 90)
    if TEMP in fields and fields[TEMP] is not None:
        fields[TEMP] = to_unit(fields[TEMP], fahrenheit)
    return Frame(family.id, fields, main, alarm, fahrenheit, missing, preset, theme)
