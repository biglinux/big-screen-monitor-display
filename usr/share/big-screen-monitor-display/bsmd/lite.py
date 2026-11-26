"""BSMD-lite: telemetry for small home-made clients (ESP32, Arduino, Raspberry Pi,
old handhelds) as one text line per sample.

    BSMD1|cpu=12|cpu_t=61|cpu_mhz=4120|gpu=77|gpu_t=66|ram=33|ram_used=15.5|...\\n

* ``BSMD1`` is the protocol version; a client rejects lines with another prefix.
* Fields are ``key=value`` in any order; a client ignores keys it does not know,
  so new keys never break old clients.
* ``-`` means "not measured" (a GPU without usage reporting, no sensor), never 0.
* Text values (``host``, ``media``) have no ``|``, ``=`` or control characters and
  are cut to a byte limit; the line is cp1252 (Latin-1 compatible) and at most
  255 bytes, so an 8-bit microcontroller can parse it in place.

The client answers with ``CMD|<action>`` lines from :data:`COMMANDS`; anything
else is ignored. Device bridges (``device-clients/``) share :func:`metrics`, so
the reading of the telemetry snapshot lives in one place.
"""

import re
import shutil
import subprocess


VERSION = "BSMD1"
MAX_LINE = 255
TEXT_LIMITS = {"host": 20, "media": 48}
UNKNOWN = "-"


def _number(value):
    """A float from a number or a text such as "61°C"; None when there is none."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def clean_text(text, limit):
    """No separators or control characters, at most ``limit`` cp1252 bytes."""
    text = "".join(ch if ch.isprintable() else " " for ch in str(text or ""))
    text = " ".join(text.replace("|", "/").replace("=", "-").split())
    return text.encode("cp1252", errors="replace")[:limit].decode("cp1252")


def pick_gpu(gpus, index=None):
    """``index`` when valid, else the GPU with most VRAM (the discrete one).

    The service rotates ``active_gpu_idx`` every 3 s for its own themes; a small
    client that only says "GPU" would mix both cards in one history.
    """
    gpus = [g for g in (gpus or []) if isinstance(g, dict)]
    if not gpus:
        return {}
    if index is not None and 0 <= index < len(gpus):
        return gpus[index]
    return max(gpus, key=lambda g: _number(g.get("mem_total_mb")) or 0)


def metrics(snap, gpu_index=None):
    """Normalised figures from a :func:`bsmd.telemetry.snapshot`; None = not measured."""
    gpu = pick_gpu(snap.get("gpus"), gpu_index)
    ram_used, ram_total = _number(snap.get("ram_used_mb")), _number(snap.get("ram_total_mb"))
    cpu_t = _number(snap.get("cpu_temp_value"))
    if cpu_t is None:
        cpu_t = _number(snap.get("cpu_temp"))
    gpu_t = _number(gpu.get("temp_value"))
    if gpu_t is None:
        gpu_t = _number(gpu.get("temp"))
    return {
        "cpu": _number(snap.get("cpu_percent")),
        "cpu_t": cpu_t,
        "cpu_mhz": _number(snap.get("cpu_freq_mhz")),
        "gpu": _number(gpu.get("percent")) if gpu.get("usage_known") else None,
        "gpu_t": gpu_t,
        "gpu_mhz": _number(gpu.get("clock_mhz")),
        "ram": _number(snap.get("ram_percent")),
        "ram_used": None if ram_used is None else ram_used / 1024,
        "ram_total": None if ram_total is None else ram_total / 1024,
        "disk": _number(snap.get("disk_percent")),
        "rx": _number(snap.get("net_rx_mbps")),
        "tx": _number(snap.get("net_tx_mbps")),
        "host": snap.get("hostname") or "",
    }


DECIMALS = {"ram_used": 1, "ram_total": 1, "rx": 1, "tx": 1}


def _field(key, value):
    if key in TEXT_LIMITS:
        return clean_text(value, TEXT_LIMITS[key]) or UNKNOWN
    if value is None:
        return UNKNOWN
    return f"{value:.{DECIMALS.get(key, 0)}f}"


def encode(values, media=None):
    """One BSMD-lite line (str, ends with \\n) from :func:`metrics` plus the media text."""
    fields = dict(values)
    if media is not None:
        fields["media"] = media
    line = VERSION + "".join(f"|{key}={_field(key, value)}" for key, value in fields.items())
    raw = line.encode("cp1252", errors="replace")
    if len(raw) > MAX_LINE - 1:                       # keep whole fields only
        raw = raw[:MAX_LINE - 1]
        raw = raw[:raw.rfind(b"|")]
    return raw.decode("cp1252") + "\n"


def decode(line):
    """{key: str} from a BSMD-lite line, or None when it is not one (reference parser for clients)."""
    line = line.rstrip("\r\n")
    parts = line.split("|")
    if parts[0] != VERSION:
        return None
    out = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if sep and key:
            out[key] = value
    return out


# --- commands from the client -------------------------------------------------------

def _volume(delta):
    if shutil.which("pactl"):
        return ["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{delta:+d}%"]
    if shutil.which("wpctl"):
        return ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{abs(delta)}%{'+' if delta > 0 else '-'}"]
    return None


COMMANDS = {
    "PLAY_PAUSE": lambda: ["playerctl", "play-pause"],
    "NEXT": lambda: ["playerctl", "next"],
    "PREV": lambda: ["playerctl", "previous"],
    "VOL_UP": lambda: _volume(+5),
    "VOL_DOWN": lambda: _volume(-5),
}


def handle_command(line, run=subprocess.run, log=print):
    """Run one ``CMD|ACTION`` line from a client; only :data:`COMMANDS` exist.
    Returns the action, or None for anything else."""
    line = line.strip()
    if not line.startswith("CMD|"):
        return None
    action = line[4:]
    factory = COMMANDS.get(action)
    if factory is None:
        log(f"[CMD] unknown action {action!r}")
        return None
    argv = factory()
    log(f"[CMD] {action}")
    if not argv:
        log("[CMD] neither pactl nor wpctl found for the volume")
        return action
    try:
        run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
    except FileNotFoundError as error:
        log(f"[CMD] tool not found: {error}")
    except subprocess.TimeoutExpired:
        log(f"[CMD] {argv[0]} did not answer")
    return action


def media_text(playerctl=None, timeout=1.0):
    """'Artist - Title' of the active MPRIS player (playerctl), or None."""
    exe = playerctl or shutil.which("playerctl")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "metadata", "--format", "{{artist}}\t{{title}}"],
                             capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    artist, _, title = out.stdout.strip().partition("\t")
    artist, title = artist.strip(), title.strip()
    text = f"{artist} - {title}" if artist and title else (title or artist)
    return text or None
