"""MPRIS2 client on the session bus (Gio, asynchronous, signal driven).

Discovery
    ListNames once, then NameOwnerChanged for players that appear, restart
    (new unique name) or quit. Support is decided by the presence of an
    ``org.mpris.MediaPlayer2.*`` name, never by the application name.
State
    GetAll on both interfaces when a player appears; afterwards only
    PropertiesChanged and Seeked. ``Position`` is not signalled by MPRIS, so it
    is read on play/pause, track change, seek, and every ``RESYNC`` seconds
    for players that are playing; the themes interpolate in between.
Commands
    PlayPause, Play, Pause, Next, Previous, Stop, Seek, SetPosition and the
    Volume/Shuffle/LoopStatus properties; each one is refused locally when the
    player does not announce the capability, and errors are reported back.

All calls have a timeout, so a frozen player cannot block the agent's loop.
``playerctld`` is skipped: it mirrors other players and would duplicate them.
"""

import logging
import time

from gi.repository import Gio, GLib

log = logging.getLogger("bsmd.media")

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
CALL_TIMEOUT_MS = 2500
RESYNC = 5.0
SKIP = ("org.mpris.MediaPlayer2.playerctld",)
COMMANDS = {"play_pause": ("PlayPause", ("play", "pause")), "play": ("Play", ("play",)),
            "pause": ("Pause", ("pause",)), "next": ("Next", ("next",)), "previous": ("Previous", ("previous",)),
            "stop": ("Stop", ("control",))}


def _first(value):
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value if item)
    return value if isinstance(value, str) else ""


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value == value:
        return int(value)
    return None


def parse_metadata(metadata):
    """Plain dict from an MPRIS Metadata a{sv} (already unpacked)."""
    metadata = metadata if isinstance(metadata, dict) else {}
    comment = metadata.get("xesam:comment")
    length = _int(metadata.get("mpris:length"))
    return {
        "track_id": str(metadata.get("mpris:trackid") or ""),
        "title": _first(metadata.get("xesam:title")),
        "artist": _first(metadata.get("xesam:artist")) or _first(metadata.get("xesam:albumArtist")),
        "album": _first(metadata.get("xesam:album")),
        "description": _first(comment) if comment else "",
        "url": _first(metadata.get("xesam:url")),
        "art_url": _first(metadata.get("mpris:artUrl")),
        "length_us": length if length and length > 0 else None,
    }


class Player:
    def __init__(self, bus, owner, clock):
        self.bus = bus
        self.owner = owner
        self.clock = clock
        self.identity = ""
        self.desktop = ""
        self.status = "Stopped"
        self.meta = parse_metadata({})
        self.position_us = None
        self.position_mono = clock()
        self.rate = 1.0
        self.can = {"control": False, "play": False, "pause": False, "next": False, "previous": False,
                    "seek": False, "stop": False}
        self.volume = None
        self.loop = None
        self.shuffle = None
        self.last_active = clock()
        self.playing_since = None
        self.errors = 0
        self.ready = False

    def update(self, props):
        """Apply a dict of Player/root properties. Returns the set of changed areas."""
        changed = set()
        now = self.clock()
        if "Identity" in props:
            self.identity = str(props["Identity"] or "")
        if "DesktopEntry" in props:
            self.desktop = str(props["DesktopEntry"] or "")
        if "PlaybackStatus" in props and props["PlaybackStatus"] in ("Playing", "Paused", "Stopped"):
            status = props["PlaybackStatus"]
            if status != self.status:
                # Freeze the interpolated position at the transition.
                self.position_us = self.position_now(now)
                self.position_mono = now
                self.status = status
                changed.add("status")
                if status == "Playing":
                    self.playing_since = now
                else:
                    self.playing_since = None
                self.last_active = now
        if "Metadata" in props:
            meta = parse_metadata(props["Metadata"])
            if meta != self.meta:
                track_changed = (meta["track_id"], meta["title"], meta["url"]) != \
                    (self.meta["track_id"], self.meta["title"], self.meta["url"])
                self.meta = meta
                changed.add("metadata")
                if track_changed:
                    changed.add("track")
                    self.position_us = 0 if self.position_us is not None else None
                    self.position_mono = now
                    if self.status == "Playing":
                        self.last_active = now
        if "Position" in props:
            position = _int(props["Position"])
            self.position_us = max(0, position) if position is not None else None
            self.position_mono = now
            changed.add("position")
        if "Rate" in props:
            try:
                rate = float(props["Rate"])
            except (TypeError, ValueError):
                rate = 1.0
            if rate != self.rate:
                self.position_us = self.position_now(now)
                self.position_mono = now
                self.rate = rate
                changed.add("position")
        for prop, key in (("CanControl", "control"), ("CanPlay", "play"), ("CanPause", "pause"),
                          ("CanGoNext", "next"), ("CanGoPrevious", "previous"), ("CanSeek", "seek")):
            if prop in props:
                value = bool(props[prop])
                if self.can[key] != value:
                    self.can[key] = value
                    changed.add("caps")
        self.can["stop"] = self.can["control"]
        if "Volume" in props:
            try:
                self.volume = max(0.0, float(props["Volume"]))
            except (TypeError, ValueError):
                self.volume = None
            changed.add("volume")
        if "LoopStatus" in props:
            self.loop = props["LoopStatus"] if props["LoopStatus"] in ("None", "Track", "Playlist") else None
            changed.add("loop")
        if "Shuffle" in props:
            self.shuffle = bool(props["Shuffle"])
            changed.add("shuffle")
        return changed

    def position_now(self, now=None):
        if self.position_us is None:
            return None
        if self.status != "Playing":
            return self.position_us
        now = self.clock() if now is None else now
        position = self.position_us + int(max(0.0, now - self.position_mono) * self.rate * 1e6)
        length = self.meta["length_us"]
        return min(position, length) if length else position

    def to_wire(self, art_id=None, art_state="none"):
        return {
            "bus": self.bus, "identity": self.identity, "desktop": self.desktop, "status": self.status,
            "title": self.meta["title"], "artist": self.meta["artist"], "album": self.meta["album"],
            "description": self.meta["description"], "url": self.meta["url"], "track_id": self.meta["track_id"],
            "art": art_id, "art_state": art_state, "length_us": self.meta["length_us"],
            "position_us": self.position_us, "position_mono": self.position_mono, "rate": self.rate,
            "can": dict(self.can), "volume": self.volume, "loop": self.loop, "shuffle": self.shuffle,
            "last_active_mono": self.last_active, "playing_since_mono": self.playing_since,
        }


class MprisWatcher:
    """Tracks every MPRIS player on ``connection``; calls ``on_change(bus, areas)``."""

    def __init__(self, connection, on_change, on_error=None, clock=time.monotonic):
        self.conn = connection
        self.on_change = on_change
        self.on_error = on_error or (lambda message: None)
        self.clock = clock
        self.players = {}         # well-known name -> Player
        self.owners = {}          # unique name -> well-known name
        self._subscriptions = []
        self._resync_source = None

    # ------------------------------------------------------------ lifecycle
    def start(self):
        conn = self.conn
        self._subscriptions = [
            conn.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                  "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._on_owner, None),
            conn.signal_subscribe(None, PROPS_IFACE, "PropertiesChanged", PATH, None,
                                  Gio.DBusSignalFlags.NONE, self._on_properties, None),
            conn.signal_subscribe(None, PLAYER_IFACE, "Seeked", PATH, None,
                                  Gio.DBusSignalFlags.NONE, self._on_seeked, None),
        ]
        conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames", None,
                  GLib.VariantType("(as)"), Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None, self._on_names)
        self._resync_source = GLib.timeout_add_seconds(int(RESYNC), self._resync)

    def stop(self):
        for subscription in self._subscriptions:
            self.conn.signal_unsubscribe(subscription)
        self._subscriptions = []
        if self._resync_source:
            GLib.source_remove(self._resync_source)
            self._resync_source = None

    # ------------------------------------------------------------ discovery
    def _on_names(self, conn, result):
        try:
            names = conn.call_finish(result).unpack()[0]
        except GLib.Error as error:
            self.on_error(f"ListNames failed: {error.message}")
            return
        for name in names:
            if name.startswith(PREFIX) and name not in SKIP:
                self._resolve_owner(name)

    def _resolve_owner(self, name):
        def done(conn, result):
            try:
                owner = conn.call_finish(result).unpack()[0]
            except GLib.Error:
                return
            self._add(name, owner)
        self.conn.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "GetNameOwner",
                       GLib.Variant("(s)", (name,)), GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE,
                       CALL_TIMEOUT_MS, None, done)

    def _on_owner(self, _conn, _sender, _path, _iface, _signal, params, _data):
        name, old, new = params.unpack()
        if not name.startswith(PREFIX) or name in SKIP:
            return
        if old and name in self.players:
            self._remove(name)
        if new:
            self._add(name, new)

    def _add(self, name, owner):
        if name in self.players and self.players[name].owner == owner:
            return
        player = Player(name, owner, self.clock)
        self.players[name] = player
        self.owners[owner] = name
        for iface in (ROOT_IFACE, PLAYER_IFACE):
            self.conn.call(name, PATH, PROPS_IFACE, "GetAll", GLib.Variant("(s)", (iface,)),
                           GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None,
                           self._on_getall, (name, owner, iface))

    def _on_getall(self, conn, result, data):
        name, owner, iface = data
        player = self.players.get(name)
        if player is None or player.owner != owner:
            return
        try:
            props = conn.call_finish(result).unpack()[0]
        except GLib.Error as error:
            player.errors += 1
            self.on_error(f"{name}: {error.message}")
            return
        areas = player.update(props)
        if iface == PLAYER_IFACE:
            player.ready = True
            # GetAll may or may not include Position (some players omit it).
            if "Position" not in props:
                self.refresh_position(name)
            areas.add("added")
        self.on_change(name, areas)

    def _remove(self, name):
        player = self.players.pop(name, None)
        if player:
            self.owners.pop(player.owner, None)
            self.on_change(name, {"removed"})

    # ------------------------------------------------------------ signals
    def _on_properties(self, _conn, sender, _path, _iface, _signal, params, _data):
        name = self.owners.get(sender)
        player = self.players.get(name)
        if player is None:
            return
        iface, changed, invalidated = params.unpack()
        if iface not in (PLAYER_IFACE, ROOT_IFACE):
            return
        areas = player.update(changed)
        if invalidated:
            # Some players (Chromium) invalidate instead of sending values: fetch them again.
            self.conn.call(name, PATH, PROPS_IFACE, "GetAll", GLib.Variant("(s)", (iface,)),
                           GLib.VariantType("(a{sv})"), Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None,
                           self._on_getall, (name, player.owner, iface))
        if areas & {"status", "track"}:
            self.refresh_position(name)
        if areas:
            self.on_change(name, areas)

    def _on_seeked(self, _conn, sender, _path, _iface, _signal, params, _data):
        name = self.owners.get(sender)
        player = self.players.get(name)
        if player is None:
            return
        player.update({"Position": params.unpack()[0]})
        self.on_change(name, {"position"})

    # ------------------------------------------------------------ position
    def refresh_position(self, name):
        player = self.players.get(name)
        if player is None:
            return

        def done(conn, result):
            current = self.players.get(name)
            if current is not player:
                return
            try:
                value = conn.call_finish(result).unpack()[0]
            except GLib.Error:
                # Position not supported (some streams/browsers): stay unknown, never invent it.
                if player.position_us is not None and player.meta["length_us"] is None:
                    player.position_us = None
                    self.on_change(name, {"position"})
                return
            before = player.position_now()
            player.update({"Position": value})
            if before is None or abs((player.position_us or 0) - before) > 1_500_000:
                self.on_change(name, {"position"})
        self.conn.call(name, PATH, PROPS_IFACE, "Get", GLib.Variant("(ss)", (PLAYER_IFACE, "Position")),
                       GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None, done)

    def _resync(self):
        for name, player in list(self.players.items()):
            if player.status == "Playing":
                self.refresh_position(name)
        return True

    # ------------------------------------------------------------ commands
    def command(self, name, action, reply=None):
        """Run a transport command. ``reply(ok, message)`` is called later."""
        reply = reply or (lambda ok, message: None)
        player = self.players.get(name)
        if player is None:
            reply(False, "player not found")
            return False
        method, needs = COMMANDS[action]
        if not player.can["control"] or not any(player.can[need] for need in needs):
            reply(False, "not supported by this player")
            return False
        self._call(name, method, None, reply)
        return True

    def seek_to(self, name, position_us, reply=None):
        reply = reply or (lambda ok, message: None)
        player = self.players.get(name)
        if player is None or not player.can["seek"]:
            reply(False, "seeking is not supported")
            return False
        length = player.meta["length_us"]
        position = max(0, int(position_us))
        if length:
            position = min(position, length - 1)
        track = player.meta["track_id"]
        if track and track.startswith("/") and track != "/org/mpris/MediaPlayer2/TrackList/NoTrack":
            self._call(name, "SetPosition", GLib.Variant("(ox)", (track, position)), reply)
        else:
            offset = position - (player.position_now() or 0)
            self._call(name, "Seek", GLib.Variant("(x)", (offset,)), reply)
        return True

    def seek_by(self, name, offset_us, reply=None):
        player = self.players.get(name)
        if player is None or not player.can["seek"]:
            (reply or (lambda ok, message: None))(False, "seeking is not supported")
            return False
        self._call(name, "Seek", GLib.Variant("(x)", (int(offset_us),)), reply)
        return True

    def set_property(self, name, prop, variant, reply=None):
        reply = reply or (lambda ok, message: None)
        player = self.players.get(name)
        if player is None or not player.can["control"]:
            reply(False, "not supported by this player")
            return False

        def done(conn, result):
            try:
                conn.call_finish(result)
            except GLib.Error as error:
                reply(False, error.message)
                return
            reply(True, "")
        self.conn.call(name, PATH, PROPS_IFACE, "Set", GLib.Variant("(ssv)", (PLAYER_IFACE, prop, variant)),
                       None, Gio.DBusCallFlags.NONE, CALL_TIMEOUT_MS, None, done)
        return True

    def _call(self, name, method, params, reply):
        def done(conn, result):
            try:
                conn.call_finish(result)
            except GLib.Error as error:
                player = self.players.get(name)
                if player:
                    player.errors += 1
                self.on_error(f"{name}.{method}: {error.message}")
                if reply:
                    reply(False, error.message)
                return
            if reply:
                reply(True, "")
            self.refresh_position(name)
        self.conn.call(name, PATH, PLAYER_IFACE, method, params, None, Gio.DBusCallFlags.NONE,
                       CALL_TIMEOUT_MS, None, done)
