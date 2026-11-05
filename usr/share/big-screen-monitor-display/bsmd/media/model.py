"""Media snapshot contract shared by the session agent, the service and the themes.

Wire messages (JSON objects, one per IPC frame):

    {"type": "snapshot", "v": 1, "players": [...], "active": bus|None,
     "volume": {...}, "agent": {...}, "sent_mono": float}
    {"type": "art", "id": hex, "w": int, "h": int, "rgb": base64}   raw RGB, never a file format
    {"type": "spectrum", "bands": [0..1, ...], "mono": float}        real FFT of the output (opt-in)

Everything that comes from another process goes through ``clean_*`` here:
strings are truncated, numbers clamped, unknown keys dropped. Nothing is ever
invented: a value that the player does not report stays ``None`` and the
themes leave it out instead of drawing a placeholder number.

Times are microseconds (MPRIS), positions carry the CLOCK_MONOTONIC instant
they were read at (system wide on Linux, so the agent and the service agree)
and are interpolated with the playback rate while the player is playing.
"""

import base64
import binascii
import time

PROTOCOL = 1
STATUSES = ("Playing", "Paused", "Stopped")
LOOPS = ("None", "Track", "Playlist")
MAX_PLAYERS = 12
MAX_TEXT = 300
MAX_ART_SIDE = 320
SPECTRUM_BANDS = 24
CAPS = ("control", "play", "pause", "next", "previous", "seek", "stop")
MAX_LENGTH_US = 400 * 24 * 3600 * 10 ** 6     # longer than any real media: treat as unknown
VOLUME_BACKENDS = ("pulse", "wpctl", "alsa", "none")


def _text(value, limit=MAX_TEXT):
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(item) for item in value if isinstance(item, str) and item.strip())
    if not isinstance(value, str):
        return ""
    value = " ".join("".join(ch if ch.isprintable() else " " for ch in value).split())
    return value[:limit]


def _number(value, low, high, default=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if value != value:       # NaN
        return default
    return max(low, min(high, value))


def _length(value):
    """Track length in µs; 0, negative or absurd values mean 'unknown'."""
    number = _number(value, 0, MAX_LENGTH_US + 1)
    if number is None or number <= 0 or number > MAX_LENGTH_US:
        return None
    return int(number)


def clean_player(data):
    if not isinstance(data, dict):
        return None
    bus = _text(data.get("bus"), 255)
    if not bus.startswith("org.mpris.MediaPlayer2."):
        return None
    status = data.get("status") if data.get("status") in STATUSES else "Stopped"
    can = data.get("can") if isinstance(data.get("can"), dict) else {}
    position = _number(data.get("position_us"), 0, MAX_LENGTH_US)
    art = data.get("art")
    player = {
        "bus": bus,
        "identity": _text(data.get("identity"), 80) or bus.rsplit(".", 1)[-1],
        "desktop": _text(data.get("desktop"), 80),
        "status": status,
        "title": _text(data.get("title")),
        "artist": _text(data.get("artist")),
        "album": _text(data.get("album")),
        "description": _text(data.get("description")),
        "url": _text(data.get("url"), 500),
        "track_id": _text(data.get("track_id"), 255),
        "art": art if isinstance(art, str) and len(art) <= 64 and art.isalnum() else None,
        "art_state": data.get("art_state") if data.get("art_state") in ("none", "loading", "ok", "error") else "none",
        "length_us": _length(data.get("length_us")),
        "position_us": None if position is None else int(position),
        "position_mono": _number(data.get("position_mono"), 0, 1e12, 0.0),
        "rate": _number(data.get("rate"), 0.0, 16.0, 1.0),
        "can": {key: bool(can.get(key)) for key in CAPS},
        "volume": _number(data.get("volume"), 0.0, 4.0),
        "loop": data.get("loop") if data.get("loop") in LOOPS else None,
        "shuffle": data.get("shuffle") if isinstance(data.get("shuffle"), bool) else None,
        "last_active_mono": _number(data.get("last_active_mono"), 0, 1e12, 0.0),
        "playing_since_mono": _number(data.get("playing_since_mono"), 0, 1e12),
    }
    if status != "Playing":
        player["playing_since_mono"] = None
    return player


def clean_volume(data):
    data = data if isinstance(data, dict) else {}
    percent = _number(data.get("percent"), 0, 200)
    available = bool(data.get("available")) and percent is not None
    return {
        "available": available,
        "percent": int(round(percent)) if available else None,
        "muted": bool(data.get("muted")) if available else None,
        "output": _text(data.get("output"), 120),
        "backend": data.get("backend") if data.get("backend") in VOLUME_BACKENDS else "none",
        "error": _text(data.get("error"), 200),
    }


def clean_agent(data):
    data = data if isinstance(data, dict) else {}
    errors = data.get("errors") if isinstance(data.get("errors"), list) else []
    return {
        "version": _text(data.get("version"), 20),
        "dbus": _text(data.get("dbus"), 120) or "unknown",
        "spectrum": data.get("spectrum") if data.get("spectrum") in ("off", "running", "unavailable") else "off",
        "errors": [_text(item, 200) for item in errors[:8]],
    }


def clean_snapshot(data):
    """Validated snapshot or None (wrong type/version)."""
    if not isinstance(data, dict) or data.get("type") != "snapshot" or data.get("v") != PROTOCOL:
        return None
    raw_players = data.get("players") if isinstance(data.get("players"), list) else []
    players = []
    seen = set()
    for item in raw_players[:MAX_PLAYERS]:
        player = clean_player(item)
        if player and player["bus"] not in seen:
            seen.add(player["bus"])
            players.append(player)
    active = data.get("active") if data.get("active") in seen else None
    return {"players": players, "active": active, "volume": clean_volume(data.get("volume")),
            "agent": clean_agent(data.get("agent")),
            "sent_mono": _number(data.get("sent_mono"), 0, 1e12, 0.0)}


def clean_art(data):
    """(id, width, height, rgb bytes) or None."""
    if not isinstance(data, dict) or data.get("type") != "art":
        return None
    art_id, width, height = data.get("id"), data.get("w"), data.get("h")
    if not (isinstance(art_id, str) and 0 < len(art_id) <= 64 and art_id.isalnum()):
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_ART_SIDE for v in (width, height)):
        return None
    try:
        raw = base64.b64decode(data.get("rgb", ""), validate=True)
    except (binascii.Error, ValueError, TypeError):
        return None
    if len(raw) != width * height * 3:
        return None
    return art_id, width, height, raw


def clean_spectrum(data):
    if not isinstance(data, dict) or data.get("type") != "spectrum":
        return None
    bands = data.get("bands")
    if not isinstance(bands, list) or not 4 <= len(bands) <= 64:
        return None
    values = [_number(value, 0.0, 1.0, 0.0) for value in bands]
    return {"bands": values, "mono": _number(data.get("mono"), 0, 1e12, 0.0)}


# ---------------------------------------------------------------- helpers for the themes

def position_now(player, now=None):
    """Interpolated position in µs, or None when the player does not report one."""
    if not player or player.get("position_us") is None:
        return None
    position = player["position_us"]
    if player.get("status") == "Playing":
        now = time.monotonic() if now is None else now
        elapsed = max(0.0, now - (player.get("position_mono") or now))
        position += int(elapsed * (player.get("rate") or 1.0) * 1e6)
    length = player.get("length_us")
    if length:
        position = min(position, length)
    return max(0, position)


def fmt_time(us, force_hours=False):
    """"3:56", "1:02:03"; "--:--" when unknown."""
    if us is None:
        return "--:--"
    seconds = int(us // 1_000_000)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours or force_hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def secondary_line(player):
    """Description fallback chain: description → artist → album → source application."""
    for key in ("description", "artist", "album", "identity"):
        value = (player or {}).get(key)
        if value:
            return value
    return ""


def is_live(player):
    """A stream or live video: playing/paused but without a known length."""
    return bool(player) and player.get("length_us") is None and bool(player.get("title"))


def app_key(player):
    """Short, stable name of the application: 'spotify', 'firefox', 'vlc'..."""
    if not player:
        return ""
    return player["bus"][len("org.mpris.MediaPlayer2."):].split(".")[0].lower()


def matches(player, pattern):
    """Case-insensitive match of a user pattern against bus suffix, identity or desktop id."""
    pattern = (pattern or "").strip().lower()
    if not pattern or not player:
        return False
    fields = (player["bus"][len("org.mpris.MediaPlayer2."):], player.get("identity", ""), player.get("desktop", ""))
    return any(pattern in (field or "").lower() for field in fields)


def split_patterns(text):
    return [part.strip().lower() for part in (text or "").replace(";", ",").split(",") if part.strip()]


# ---------------------------------------------------------------- demonstration data

DEMO_BUS = "org.mpris.MediaPlayer2.bsmd_demo"


def demo_snapshot(now=None, playing=True):
    """Clearly labelled demonstration data for previews without any MPRIS player."""
    now = time.monotonic() if now is None else now
    length = 236_000_000
    position = int(((now * 1_000_000) % length) if playing else 84_000_000)
    player = clean_player({
        "bus": DEMO_BUS, "identity": "DEMO", "desktop": "", "status": "Playing" if playing else "Paused",
        "title": "Neon Horizon (demo track)", "artist": "The Retro Signal Ensemble", "album": "Preview Sessions",
        "description": "", "url": "", "track_id": "/demo/1", "art": "demo", "art_state": "ok",
        "length_us": length, "position_us": position, "position_mono": now, "rate": 1.0,
        "can": {key: True for key in CAPS}, "volume": None, "loop": "None", "shuffle": False,
        "last_active_mono": now,
    })
    return {"players": [player], "active": DEMO_BUS,
            "volume": clean_volume({"available": True, "percent": 65, "muted": False, "output": "DEMO",
                                    "backend": "none"}),
            "agent": clean_agent({"dbus": "demo"}), "sent_mono": now}
