"""Settings: single source of truth, validation, atomic writes and migration.

Source of truth
---------------
``/etc/big-screen-monitor-display/settings.json`` (world readable, written
only by root through ``bsm-helper``). The system service never reads files in
``/home``; legacy per-user files are migrated once by the helper.

``BSM_CONFIG`` overrides the path (development, tests and manual runs).
"""

import glob
import json
import os
import re
import tempfile
import threading

SYSTEM_CONFIG = "/etc/big-screen-monitor-display/settings.json"
LEGACY_RELATIVE = os.path.join(".config", "big-screen-monitor", "settings.json")
MAX_FILE_SIZE = 512 * 1024      # Kojiro layouts (and per-display copies) need more than the 4.0 limit


def config_path():
    return os.environ.get("BSM_CONFIG") or SYSTEM_CONFIG


def _choice(*values):
    return ("choice", values)


def _int(low, high):
    return ("int", (low, high))


BOOL = ("bool", None)

GK_KEYS = (
    "gk_show_host", "gk_show_date", "gk_show_time", "gk_show_gpu", "gk_show_cpu",
    "gk_show_cores", "gk_show_temp", "gk_show_proc", "gk_show_disk", "gk_show_eth0",
    "gk_show_mem", "gk_show_swap", "gk_show_docker", "gk_show_ppp", "gk_show_vlan",
    "gk_show_sys", "gk_show_hda", "gk_show_inet", "gk_show_devices", "gk_show_media",
    "gk_show_uptime", "gk_show_battery",
)
GK_DEFAULT_OFF = {"gk_show_cores", "gk_show_docker", "gk_show_ppp", "gk_show_vlan",
                  "gk_show_inet", "gk_show_battery"}

THEME_IDS = ("standard", "gkrellm", "planet", "old_computer", "brother_away", "kojiro")
# 3.x themes that are now colour schemes of "standard" (migrated on load).
LEGACY_STANDARD = ("dark", "light", "neon", "cyberpunk")
STD_SCHEMES = ("dark", "light", "neon", "cyberpunk", "nord", "dracula", "solarized", "high_contrast")

ORIENTATIONS = ("horizontal", "vertical", "horizontal_flipped", "vertical_flipped")
# Display families (bsmd.displays.registry; kept here so the root helper
# does not import the drivers). A test checks both lists agree.
PROFILE_IDS = ("ax206", "turing_rev_a", "xuanfang_rev_b", "turing_rev_c", "kipye_rev_d", "weact_a",
               "weact_b", "turing_usb")
LED_COLORS = ("off", "white", "red", "green", "blue", "cyan", "magenta", "yellow", "orange", "purple")

# key -> (kind, constraint, default)
SCHEMA = {
    # Device
    "model": (*_choice("auto", "ax206", "turing"), "auto"),
    "size": (*_choice("3.5", "5", "8.8", "2.1"), "3.5"),
    "orientation": (*_choice(*ORIENTATIONS), "horizontal"),
    "brightness": (*_int(0, 100), 70),
    # Application
    "theme": (*_choice(*THEME_IDS, *LEGACY_STANDARD), "standard"),
    "network_iface": (*_choice("auto", "eth", "wifi"), "auto"),
    "language": (*_choice("auto", "pt", "en"), "auto"),
    "performance_profile": (*_choice("auto", "economy", "balanced", "fluid"), "auto"),
    "gk_theme_color": (*_choice("urlicht", "classic", "cyber_red"), "urlicht"),
    # Standard dashboard ("Padrão")
    "std_scheme": (*_choice(*STD_SCHEMES), "dark"),
    "std_side_panel": (*_choice("processes", "graphs", "none"), "processes"),
    "std_header": (*BOOL, True),
    "std_logo": (*BOOL, True),
    "std_host_line": (*BOOL, True),
    "std_date": (*BOOL, True),
    "std_clock_24h": (*BOOL, True),
    "std_seconds": (*BOOL, False),
    "std_show_cpu": (*BOOL, True),
    "std_show_ram": (*BOOL, True),
    "std_show_swap": (*BOOL, True),
    "std_show_disk": (*BOOL, True),
    "std_show_gpu": (*BOOL, True),
    "std_gpu_details": (*BOOL, True),
    "std_network": (*BOOL, True),
    "std_history": (*BOOL, True),
    "std_bar_style": (*_choice("rounded", "flat", "segmented"), "rounded"),
    "std_values": (*_choice("absolute", "percent"), "absolute"),
    "std_alert_colors": (*BOOL, True),
    "std_colored_labels": (*BOOL, True),
    "std_temp_unit": (*_choice("c", "f"), "c"),
    "std_process_count": (*_choice("5", "8", "10", "12"), "8"),
    "std_process_sort": (*_choice("cpu", "memory"), "cpu"),
    "std_footer": (*BOOL, True),
    "std_text_size": (*_choice("small", "normal", "large"), "normal"),
    # GKrellM layout
    "gk_columns": (*_choice("auto", "1", "2", "3", "4"), "auto"),
    "gk_text_size": (*_choice("small", "normal", "large"), "normal"),
    "gk_chart_height": (*_choice("small", "normal", "large"), "normal"),
    "gk_disk_count": (*_choice("1", "2", "3", "4"), "2"),
    # Planet
    "planet_accent": (*_choice("blue", "green", "amber", "violet", "red"), "blue"),
    "planet_show_paths": (*BOOL, True),
    "planet_show_moon": (*BOOL, True),
    "planet_city_lights": (*BOOL, True),
    "planet_night": (*BOOL, True),
    "planet_seconds": (*BOOL, True),
    # Old Computer
    "oc_scheme": (*_choice("classic", "slate", "amber", "plum"), "classic"),
    "oc_show_gpu": (*BOOL, True),
    "oc_show_storage": (*BOOL, False),
    "oc_titlebar": (*BOOL, True),
    "oc_statusbar": (*BOOL, True),
    "oc_seconds": (*BOOL, False),
    # Brother Away
    "ba_animation": (*BOOL, True),
    "ba_event_frequency": (*_choice("low", "normal", "high"), "normal"),
    "ba_humor": (*_choice("family", "classic", "adult"), "classic"),
    "ba_catchphrases": (*BOOL, True),
    "ba_day_night": (*BOOL, True),
    "ba_story_continuity": (*BOOL, True),
    "ba_telemetry_reactions": (*BOOL, True),
    "ba_subtitles": (*BOOL, True),
    "ba_dialogue_frequency": (*_choice("low", "normal", "high"), "normal"),
    "ba_weather": (*BOOL, True),
    # Telemetry overlay (Brother Away)
    "overlay_enabled": (*BOOL, True),
    "overlay_size": (*_choice("compact", "expanded"), "expanded"),
    "overlay_opacity": (*_int(0, 100), 72),
    "overlay_position": (*_choice("top_left", "top_right", "bottom_left", "bottom_right"), "top_left"),
    "overlay_show_clock": (*BOOL, True),
    "overlay_show_cpu": (*BOOL, True),
    "overlay_show_ram": (*BOOL, True),
    "overlay_show_disk": (*BOOL, True),
    "overlay_show_gpu": (*BOOL, True),
    "overlay_auto_dim": (*BOOL, True),
    # Host side sound (optional, off by default)
    "sound_enabled": (*BOOL, False),
    "sound_volume": (*_int(0, 100), 40),
    "ui_sound_feedback": (*BOOL, False),
}
for _key in GK_KEYS:
    SCHEMA[_key] = (*BOOL, _key not in GK_DEFAULT_OFF)

# Keys whose change needs the driver to be reopened (no process restart).
DEVICE_KEYS = ("model",)

# Per-display entries ("displays": {"usb-5-1.4.4": {...}}): these keys plus
# any SCHEMA key a display may override (theme, orientation, brightness,
# theme options...). Global-only keys cannot be overridden.
DISPLAY_SCHEMA = {
    "enabled": (*BOOL, True),
    "name": ("text", 40, ""),
    "profile": (*_choice("auto", *PROFILE_IDS), "auto"),
    "rev_c_size": (*_choice("auto", "2.1", "2.8", "5", "8.8"), "auto"),
    "led_color": (*_choice(*LED_COLORS), "off"),
}
GLOBAL_ONLY = {"model", "size", "language", "sound_enabled", "sound_volume", "ui_sound_feedback"}
MAX_DISPLAYS = 16
# Per-display commands accepted from the configuration window (command spool).
SPOOL_ACTIONS = ("reconnect", "pattern", "identify", "clear_pattern")
PATTERN_NAMES = ("identify", "bars", "grid", "gradient", "orientation", "white", "black")
DISPLAY_ID = re.compile(r"^(usb-[0-9][0-9.-]{0,30}|simulated(-[0-9]{1,2})?)$")


def defaults():
    result = {key: spec[2] for key, spec in SCHEMA.items()}
    result["displays"] = {}
    result["kojiro"] = kojiro_defaults()
    return result


def kojiro_defaults():
    from .kojiro import model
    return model.defaults()


def _validate_kojiro(value, problems, prefix="kojiro"):
    from .kojiro import model
    clean, found = model.validate(value)
    problems.extend(f"{prefix}: {problem}" for problem in found[:20])
    return clean


def display_defaults():
    return {key: spec[2] for key, spec in DISPLAY_SCHEMA.items()}


def _validate_display(display_id, entry, problems):
    clean = {}
    if not isinstance(entry, dict):
        problems.append(f"displays.{display_id} is not an object")
        return clean
    for key, value in entry.items():
        if key in DISPLAY_SCHEMA:
            kind, constraint, default = DISPLAY_SCHEMA[key]
            if kind == "text":
                ok = isinstance(value, str) and value.isprintable() and len(value) <= constraint
                clean[key] = value.strip() if ok else default
            else:
                clean[key], ok = _coerce_spec(key, value, DISPLAY_SCHEMA[key])
        elif key == "kojiro":
            clean[key], ok = _validate_kojiro(value, problems, f"displays.{display_id}.kojiro"), True
        elif key in SCHEMA and key not in GLOBAL_ONLY:
            clean[key], ok = _coerce(key, value)
        else:
            continue
        if not ok:
            problems.append(f"displays.{display_id}.{key}={value!r} invalid, using {clean[key]!r}")
    if clean.get("theme") in LEGACY_STANDARD:
        clean.setdefault("std_scheme", clean["theme"])
        clean["theme"] = "standard"
    return clean


def validate_command(command):
    """A spool command, cleaned; None when it is not acceptable."""
    if not isinstance(command, dict):
        return None
    action, display = command.get("action"), command.get("display", "*")
    if action not in SPOOL_ACTIONS or not isinstance(display, str) or not (display == "*" or DISPLAY_ID.match(display)):
        return None
    clean = {"action": action, "display": display}
    if action == "pattern":
        if command.get("pattern") not in PATTERN_NAMES:
            return None
        seconds = command.get("seconds", 10)
        clean["pattern"] = command["pattern"]
        clean["seconds"] = max(2, min(60, int(seconds))) if isinstance(seconds, (int, float)) else 10
    return clean


def merged(settings, display_id):
    """Effective settings of one display: global values + its overrides."""
    entry = (settings.get("displays") or {}).get(display_id) or {}
    result = {key: value for key, value in settings.items() if key != "displays"}
    result.update(display_defaults())
    result.update(entry)
    result["display_id"] = display_id
    return result


def _coerce(key, value):
    """Return (valid_value, ok). Invalid values fall back to the default."""
    return _coerce_spec(key, value, SCHEMA[key])


def _coerce_spec(key, value, spec):
    kind, constraint, default = spec
    if kind == "bool":
        if isinstance(value, bool):
            return value, True
        return default, False
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default, False
        low, high = constraint
        number = int(value)
        if key == "brightness" and 0 < number <= 7 and isinstance(value, int):
            # Legacy AX206 1..7 scale -> percent.
            number = int(10 + (number - 1) * 90 / 6)
        return max(low, min(high, number)), low <= number <= high
    if kind == "choice":
        if key == "model" and value == "other":
            return "auto", True  # legacy "Outro (Genérico)"
        if isinstance(value, str) and value in constraint:
            return value, True
        return default, False
    return default, False


def validate(data):
    """Validate a mapping. Returns (settings, problems).

    Unknown keys are dropped, wrong values are replaced by defaults and
    reported, so a damaged file can never stop the service.
    """
    result = defaults()
    problems = []
    if not isinstance(data, dict):
        return result, ["root is not an object"]
    for key, value in data.items():
        if key == "displays":
            result["displays"] = _validate_displays(value, problems)
            continue
        if key == "kojiro":
            result["kojiro"] = _validate_kojiro(value, problems)
            continue
        if key not in SCHEMA:
            continue
        coerced, ok = _coerce(key, value)
        result[key] = coerced
        if not ok:
            problems.append(f"{key}={value!r} invalid, using {coerced!r}")
    if result["theme"] in LEGACY_STANDARD:
        # 3.x Dark/Light/Neon/Cyberpunk -> Standard with that colour scheme.
        if "std_scheme" not in data:
            result["std_scheme"] = result["theme"]
        result["theme"] = "standard"
    return result, problems


def _validate_displays(value, problems):
    if not isinstance(value, dict):
        problems.append("displays is not an object")
        return {}
    result = {}
    for display_id, entry in value.items():
        if not isinstance(display_id, str) or not DISPLAY_ID.match(display_id):
            problems.append(f"displays: invalid id {display_id!r}")
            continue
        if len(result) >= MAX_DISPLAYS:
            problems.append(f"displays: more than {MAX_DISPLAYS} entries, extra ignored")
            break
        result[display_id] = _validate_display(display_id, entry, problems)
    return result


def read_file(path):
    """Read and validate a settings file. Missing file -> defaults."""
    settings, problems, _readable = read_file_checked(path)
    return settings, problems


def read_file_checked(path):
    """(settings, problems, readable). ``readable`` is False when the file exists
    but could not be parsed at all (truncated, not JSON, too large)."""
    try:
        if os.path.getsize(path) > MAX_FILE_SIZE:
            return defaults(), [f"{path} too large"], False
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return defaults(), [], True
    except (OSError, ValueError) as error:
        return defaults(), [f"{path}: {error}"], False
    settings, problems = validate(data)
    return settings, problems, True


def backup_path(path):
    return path + ".bak"


def load():
    return read_file(config_path())[0]


def atomic_write_json(path, data, mode=0o644):
    """Write JSON atomically (temp file + fsync + rename)."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(settings, path=None):
    """Validate and write atomically; the previous valid file is kept as ``.bak``."""
    clean, problems = validate(settings)
    path = path or config_path()
    _backup(path)
    atomic_write_json(path, clean)
    return clean, problems


def _backup(path):
    """Copy the current file to ``.bak`` when it is readable (never overwrite a good
    backup with a broken file)."""
    try:
        if not os.path.exists(path) or os.path.getsize(path) > MAX_FILE_SIZE:
            return
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return
    try:
        atomic_write_json(backup_path(path), data)
    except OSError:
        pass


def restore_backup(path=None):
    """Put the last valid settings back (used by the configuration window)."""
    path = path or config_path()
    settings, problems, readable = read_file_checked(backup_path(path))
    if not readable or not os.path.exists(backup_path(path)):
        return None
    return settings


def find_legacy_files(home_glob="/home/*", root_home="/root"):
    """Legacy per-user files, most recently modified first."""
    candidates = [os.path.join(root_home, LEGACY_RELATIVE)]
    candidates += [os.path.join(home, LEGACY_RELATIVE) for home in glob.glob(home_glob)]
    found = []
    for path in candidates:
        try:
            found.append((os.path.getmtime(path), path))
        except OSError:
            continue
    return [path for _mtime, path in sorted(found, reverse=True)]


def migrate_legacy(target=None, home_glob="/home/*", root_home="/root"):
    """Create the system file from the newest legacy file, once.

    Returns the source path used, or None when nothing was migrated.
    The newest file wins (instead of the first directory in /home) because it
    reflects the last choice made in the old configuration window.
    """
    target = target or config_path()
    if os.path.exists(target):
        return None
    for source in find_legacy_files(home_glob, root_home):
        settings, _problems = read_file(source)
        save(settings, target)
        return source
    return None


class SettingsStore:
    """Thread-safe cached view of the settings file with cheap change checks."""

    def __init__(self, path=None):
        self.path = path or config_path()
        self._lock = threading.Lock()
        self._signature = None
        self.problems = []
        self._settings = defaults()
        self.refresh(force=True)

    def _stat_signature(self):
        try:
            info = os.stat(self.path)
            return (info.st_mtime_ns, info.st_size, info.st_ino)
        except OSError:
            return None

    def refresh(self, force=False):
        """Reload when the file changed. Returns the set of changed keys."""
        signature = self._stat_signature()
        if not force and signature == self._signature:
            return set()
        settings, problems, readable = read_file_checked(self.path)
        if not readable and self._signature is not None:
            # A damaged file (half-written by hand, disk full...) must not wipe
            # the running configuration: keep the last valid settings.
            with self._lock:
                self._signature = signature
                self.problems = problems + ["kept the last valid settings"]
            return set()
        with self._lock:
            old = self._settings
            self._settings = settings
            self._signature = signature
            self.problems = problems
        return {key for key in settings if old.get(key) != settings[key]} if not force else set(settings)

    def get(self):
        with self._lock:
            return dict(self._settings)
