"""Big Media session agent (``main.py --media-agent``).

Runs as the logged-in user (XDG autostart), never as root:

    MediaCore     MPRIS watcher + ActivePlayerManager + system volume + art
                  loader + optional spectrum; builds wire snapshots and runs
                  commands. The configuration window embeds the same class
                  for its live preview and controls.
    Publisher     pushes snapshots/art/spectrum to the display service socket.
    Control API   ``br.com.biglinux.BigScreenMonitor.Media`` on the session bus
                  (single instance, commands from the window, keyboard
                  shortcuts through ``main.py --media ACTION``).

The agent exits by itself when no display uses the Big Media Player theme
(the window starts it again when the theme is applied) and when the session
bus goes away (logout).
"""

import collections
import json
import logging
import os
import time

from gi.repository import Gio, GLib

from .. import __version__, settings as settings_mod
from . import artwork, ipc, model, mpris, selection, volume

log = logging.getLogger("bsmd.media")

BUS_NAME = "br.com.biglinux.BigScreenMonitor.Media"
OBJECT_PATH = "/br/com/biglinux/BigScreenMonitor/Media"
INTERFACE = "br.com.biglinux.BigScreenMonitor.Media1"
INTROSPECTION = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="Command">
      <arg type="s" name="action" direction="in"/>
      <arg type="s" name="bus" direction="in"/>
      <arg type="d" name="value" direction="in"/>
      <arg type="b" name="ok" direction="out"/>
      <arg type="s" name="message" direction="out"/>
    </method>
    <method name="GetState">
      <arg type="s" name="json" direction="out"/>
    </method>
    <signal name="Changed"/>
  </interface>
</node>
"""
THEME_ID = "big_media_player"
HEARTBEAT = 5
PUBLISH_DEBOUNCE_MS = 80
SETTINGS_EVERY = 3
IDLE_EXIT_AFTER = 60.0
ACTIONS = ("play_pause", "play", "pause", "next", "previous", "stop", "seek_to", "seek_by", "shuffle", "loop",
           "volume_set", "volume_up", "volume_down", "mute", "player_volume", "select", "retry_art")


def theme_in_use(values):
    if values.get("theme") == THEME_ID:
        return True
    return any(isinstance(entry, dict) and entry.get("theme") == THEME_ID and entry.get("enabled", True)
               for entry in (values.get("displays") or {}).values())


def wants_spectrum(values):
    if values.get("bmp_visualizer") == "spectrum":
        return True
    return any(isinstance(entry, dict) and entry.get("bmp_visualizer") == "spectrum"
               for entry in (values.get("displays") or {}).values())


class MediaCore:
    def __init__(self, connection, values, sink=None, on_state=None, clock=time.monotonic):
        self.conn = connection
        self.values = dict(values)
        self.sink = sink or (lambda message, coalesce=None: None)
        self.on_state = on_state or (lambda: None)
        self.clock = clock
        self.errors = collections.deque(maxlen=12)
        self.manager = selection.ActivePlayerManager.from_settings(self.values)
        self.manual = None            # player chosen at runtime from the window ("follow this one")
        self.art = {}                 # bus -> (url, id, state)
        self.images = {}              # art id -> PIL image (latest per player)
        self.sent_art = set()
        self._publish_source = None
        self._takeover_source = None
        self.dbus_state = "connected"
        self.watcher = mpris.MprisWatcher(connection, self._on_player, self._error, clock)
        self.volume = volume.SystemVolume(self._on_volume, self.values.get("bmp_volume_sink", ""),
                                          self.values.get("bmp_volume_max", 100))
        self.loader = artwork.ArtLoader(self._on_art)
        self.spectrum = None          # created on first use: NumPy is only loaded for the real spectrum
        self._heartbeat = None
        connection.connect("closed", self._on_closed)

    # ------------------------------------------------------------ lifecycle
    def start(self):
        self.watcher.start()
        self._heartbeat = GLib.timeout_add_seconds(HEARTBEAT, self._tick)
        self.schedule_publish()

    def stop(self):
        self.watcher.stop()
        self.volume.stop()
        if self.spectrum is not None:
            self.spectrum.stop()
        if self._heartbeat:
            GLib.source_remove(self._heartbeat)
            self._heartbeat = None

    def apply_settings(self, values):
        self.values = dict(values)
        self.manager.apply_settings(self.values)
        self.volume.max_percent = self.values.get("bmp_volume_max", 100)
        self.volume.set_wanted(self.values.get("bmp_volume_sink", ""))
        if self.spectrum is not None:
            self.spectrum.sensitivity = self.values.get("bmp_vis_sensitivity", 100) / 100
        self._update_spectrum()
        self.schedule_publish()

    def _on_closed(self, _conn, _remote_vanished, _error):
        self.dbus_state = "session bus closed"
        self._error("session D-Bus connection closed")
        self.schedule_publish()

    # ------------------------------------------------------------ events
    def _error(self, message):
        log.info("media: %s", message)
        self.errors.append(f"{time.strftime('%H:%M:%S')} {message}")

    def _on_player(self, bus, areas):
        player = self.watcher.players.get(bus)
        if "removed" in areas:
            self.art.pop(bus, None)
            if self.manual == bus:
                self.manual = None
        elif player is not None:
            self._update_art(bus, player)
        self._update_spectrum()
        self.schedule_publish()

    def _on_volume(self):
        self.schedule_publish()

    def _update_art(self, bus, player):
        url = player.meta["art_url"]
        old = self.art.get(bus)
        if old and old[0] == url:
            return
        if not url:
            self.art[bus] = ("", None, "none")
            return
        identifier = artwork.art_id(url)
        state = "ok" if identifier in self.images else "loading"
        self.art[bus] = (url, identifier, state)
        if state == "loading":
            self.loader.request(url)

    def _on_art(self, identifier, image, error):
        for bus, (url, art_id, _state) in list(self.art.items()):
            if art_id == identifier:
                self.art[bus] = (url, art_id, "ok" if image is not None else "error")
        if image is not None:
            self.images[identifier] = image
            used = {art_id for _url, art_id, _s in self.art.values()}
            for stale in [key for key in self.images if key not in used]:
                del self.images[stale]
            self._send_art(identifier)
        elif error:
            self._error(f"album art: {error}")
        self.schedule_publish()

    def _send_art(self, identifier):
        image = self.images.get(identifier)
        if image is None or identifier in self.sent_art:
            return
        self.sent_art.add(identifier)
        self.sink(artwork.to_message(identifier, image))

    def resend_all(self):
        """A service (re)connected: it has nothing yet."""
        self.sent_art.clear()
        for identifier in list(self.images):
            self._send_art(identifier)
        self.schedule_publish()

    def _on_bands(self, bands, mono):
        self.sink({"type": "spectrum", "bands": bands, "mono": mono}, coalesce="spectrum")

    def _update_spectrum(self):
        active = self.active_player()
        need = wants_spectrum(self.values) and active is not None and active.status == "Playing"
        if need and self.spectrum is None:
            from .spectrum import SpectrumCapture
            self.spectrum = SpectrumCapture(self._on_bands, self.values.get("bmp_vis_sensitivity", 100) / 100)
        if self.spectrum is None:
            return
        if need and not self.spectrum.running:
            if self.spectrum.state != "unavailable":
                self.spectrum.start()
        elif not need and self.spectrum.running:
            self.spectrum.stop()

    def _tick(self):
        self._update_spectrum()
        self.publish()
        return True

    # ------------------------------------------------------------ snapshot
    def active_player(self):
        if self.manual in self.watcher.players:
            return self.watcher.players[self.manual]
        wire = [model.clean_player(p.to_wire()) for p in self.watcher.players.values() if p.ready]
        bus = self.manager.choose([p for p in wire if p], self.clock())
        return self.watcher.players.get(bus)

    def snapshot(self):
        players = []
        for bus, player in self.watcher.players.items():
            if not player.ready:
                continue
            _url, art_id, art_state = self.art.get(bus, ("", None, "none"))
            players.append(player.to_wire(art_id if art_state == "ok" else None, art_state))
        active = self.active_player()
        return {"type": "snapshot", "v": model.PROTOCOL, "players": players,
                "active": active.bus if active else None, "volume": self.volume.snapshot(),
                "agent": {"version": __version__, "dbus": self.dbus_state,
                          "spectrum": self.spectrum.state if self.spectrum else "off",
                          "errors": list(self.errors)[-8:]},
                "sent_mono": self.clock()}

    def schedule_publish(self):
        if self._publish_source is None:
            self._publish_source = GLib.timeout_add(PUBLISH_DEBOUNCE_MS, self._debounced)

    def _debounced(self):
        self._publish_source = None
        self.publish()
        return False

    def publish(self):
        snapshot = self.snapshot()
        self.sink(snapshot, coalesce="snapshot")
        self.on_state()
        self._schedule_takeover(snapshot)

    def _schedule_takeover(self, snapshot):
        """Re-evaluate exactly when a waiting player becomes eligible to take over
        (instead of waiting for the next heartbeat)."""
        active = next((p for p in snapshot["players"] if p["bus"] == snapshot["active"]), None)
        if active is not None and active["status"] == "Playing":
            return
        now = self.clock()
        waits = [p["playing_since_mono"] + selection.STEAL_AFTER - now for p in snapshot["players"]
                 if p["status"] == "Playing" and p["bus"] != snapshot["active"] and p.get("playing_since_mono")]
        waits = [w for w in waits if w > 0]
        if waits and self._takeover_source is None:
            def fire():
                self._takeover_source = None
                self.schedule_publish()
                return False
            self._takeover_source = GLib.timeout_add(int(min(waits) * 1000) + 50, fire)

    # ------------------------------------------------------------ commands
    def command(self, action, bus="", value=0.0, reply=None):
        """Run ``action`` on ``bus`` (empty = the active player). ``reply(ok, message)``."""
        reply = reply or (lambda ok, message: None)
        if action not in ACTIONS:
            reply(False, f"unknown action {action}")
            return
        if action in ("volume_set", "volume_up", "volume_down", "mute"):
            step = int(self.values.get("bmp_volume_step", 5))
            if action == "volume_set":
                self.volume.set_percent(value, reply)
            elif action == "volume_up":
                self.volume.change(step, reply)
            elif action == "volume_down":
                self.volume.change(-step, reply)
            else:
                self.volume.set_mute(None, reply)
            return
        if action == "retry_art":
            self.loader.retry_failed()
            for key in list(self.art):
                self.art.pop(key)
            for name, player in self.watcher.players.items():
                self._update_art(name, player)
            reply(True, "")
            return
        if action == "select":
            if bus and bus in self.watcher.players:
                self.manual = bus
            else:
                self.manual = None
            self.schedule_publish()
            reply(True, "")
            return
        player = self.watcher.players.get(bus) if bus else self.active_player()
        if player is None:
            reply(False, "no media player")
            return
        name = player.bus
        if action in mpris.COMMANDS:
            self.watcher.command(name, action, reply)
        elif action == "seek_to":
            self.watcher.seek_to(name, value, reply)
        elif action == "seek_by":
            self.watcher.seek_by(name, value, reply)
        elif action == "shuffle":
            if player.shuffle is None:
                reply(False, "shuffle is not supported by this player")
                return
            self.watcher.set_property(name, "Shuffle", GLib.Variant("b", not player.shuffle), reply)
        elif action == "loop":
            if player.loop is None:
                reply(False, "repeat is not supported by this player")
                return
            following = {"None": "Playlist", "Playlist": "Track", "Track": "None"}[player.loop]
            self.watcher.set_property(name, "LoopStatus", GLib.Variant("s", following), reply)
        elif action == "player_volume":
            if player.volume is None:
                reply(False, "this player has no own volume")
                return
            self.watcher.set_property(name, "Volume", GLib.Variant("d", max(0.0, min(1.0, value))), reply)

    def state_json(self, extra=None):
        snapshot = self.snapshot()
        snapshot["outputs"] = self.volume.outputs
        snapshot["manual"] = self.manual
        snapshot.update(extra or {})
        return json.dumps(snapshot, ensure_ascii=False)


# ---------------------------------------------------------------- agent process

class Agent:
    def __init__(self, keep=False):
        self.keep = keep
        self.loop = GLib.MainLoop()
        self.store = settings_mod.SettingsStore()
        self.publisher = ipc.Publisher()
        self.core = None
        self.conn = None
        self.registration = None
        self.unused_since = None
        self.exit_code = 0

    def run(self):
        try:
            self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as error:
            log.error("no session bus: %s", error.message)
            return 1
        values = self.store.get()
        if not self.keep and not theme_in_use(values):
            log.info("Big Media Player is not in use; media agent not needed")
            return 0
        if agent_running(self.conn):
            log.info("media agent already running")
            return 0
        self.core = MediaCore(self.conn, values, sink=self.publisher.publish, on_state=self._emit_changed)
        self.publisher.on_connect = lambda path: GLib.idle_add(lambda: self.core.resend_all() and False)
        # Export the object first, then take the name: a client never sees the name without it.
        node = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION)
        self.registration = self.conn.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, None, None)
        reply = self.conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                    "RequestName", GLib.Variant("(su)", (BUS_NAME, 4)),     # DO_NOT_QUEUE
                                    GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 3000, None)
        if reply.unpack()[0] not in (1, 4):      # PRIMARY_OWNER / ALREADY_OWNER
            log.info("media agent already running")
            self.conn.unregister_object(self.registration)
            return 0
        self.conn.connect("closed", lambda *_: self.loop.quit())
        self.publisher.start()
        self.core.start()
        GLib.timeout_add_seconds(SETTINGS_EVERY, self._check_settings)
        for signum in (2, 15):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._quit)
        log.info("media agent %s running (sockets: %s)", __version__, ", ".join(self.publisher.paths))
        self.loop.run()
        self.core.stop()
        self.publisher.stop()
        return self.exit_code

    def _quit(self):
        self.loop.quit()
        return False

    def _check_settings(self):
        if self.store.refresh():
            self.core.apply_settings(self.store.get())
        if not self.keep and not theme_in_use(self.store.get()):
            now = time.monotonic()
            self.unused_since = self.unused_since or now
            if now - self.unused_since > IDLE_EXIT_AFTER:
                log.info("Big Media Player no longer in use; media agent exiting")
                self.loop.quit()
                return False
        else:
            self.unused_since = None
        return True

    def _emit_changed(self):
        try:
            self.conn.emit_signal(None, OBJECT_PATH, INTERFACE, "Changed", None)
        except GLib.Error:
            pass

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetState":
            extra = {"sockets": sorted(self.publisher.connected), "pid": os.getpid()}
            invocation.return_value(GLib.Variant("(s)", (self.core.state_json(extra),)))
            return
        if method == "Command":
            action, bus, value = params.unpack()

            def reply(ok, message):
                invocation.return_value(GLib.Variant("(bs)", (bool(ok), str(message or ""))))
            self.core.command(action, bus, value, reply)
            return
        invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)


def run_agent(keep=False):
    return Agent(keep).run()


# ---------------------------------------------------------------- one-shot commands (keyboard shortcuts)

def agent_running(conn):
    try:
        reply = conn.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                               "NameHasOwner", GLib.Variant("(s)", (BUS_NAME,)), GLib.VariantType("(b)"),
                               Gio.DBusCallFlags.NONE, 2000, None)
        return reply.unpack()[0]
    except GLib.Error:
        return False


def call_agent(conn, action, bus="", value=0.0, timeout_ms=4000):
    reply = conn.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, "Command", GLib.Variant("(ssd)", (action, bus, value)),
                           GLib.VariantType("(bs)"), Gio.DBusCallFlags.NONE, timeout_ms, None)
    return reply.unpack()


def agent_state(conn, timeout_ms=2000):
    reply = conn.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, "GetState", None, GLib.VariantType("(s)"),
                           Gio.DBusCallFlags.NONE, timeout_ms, None)
    return json.loads(reply.unpack()[0])


def run_command(action, value=0.0):
    """``main.py --media ACTION [VALUE]``: through the agent, or a short-lived core."""
    if action not in ACTIONS:
        print(f"unknown action; use one of: {', '.join(ACTIONS)}")
        return 2
    conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    if agent_running(conn):
        ok, message = call_agent(conn, action, "", value)
    else:
        loop = GLib.MainLoop()
        core = MediaCore(conn, settings_mod.load())
        core.start()
        result = {}

        def go():
            core.command(action, "", value, lambda ok, message: (result.update(ok=ok, message=message), loop.quit()))
            return False
        GLib.timeout_add(700, go)              # let discovery and the volume backend answer
        GLib.timeout_add_seconds(6, loop.quit)
        loop.run()
        core.stop()
        ok, message = result.get("ok", False), result.get("message", "timeout")
    if not ok:
        print(message)
    return 0 if ok else 1
