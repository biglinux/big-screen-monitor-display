"""A small but real MPRIS2 player for integration tests (Gio D-Bus server).

It owns ``org.mpris.MediaPlayer2.<name>`` on a private bus, answers
Get/GetAll/Set, implements the transport methods and emits PropertiesChanged
and Seeked like a real application. It is a test double for the *player*;
the client under test (bsmd.media.mpris) is the production code.

    python3 tests/mpris_fake.py NAME   # standalone, on the session bus
"""

import sys

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

XML = """
<node>
  <interface name="org.mpris.MediaPlayer2">
    <method name="Raise"/><method name="Quit"/>
    <property name="Identity" type="s" access="read"/>
    <property name="DesktopEntry" type="s" access="read"/>
    <property name="CanQuit" type="b" access="read"/>
    <property name="CanRaise" type="b" access="read"/>
  </interface>
  <interface name="org.mpris.MediaPlayer2.Player">
    <method name="Next"/><method name="Previous"/><method name="Pause"/><method name="PlayPause"/>
    <method name="Stop"/><method name="Play"/>
    <method name="Seek"><arg type="x" direction="in"/></method>
    <method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
    <signal name="Seeked"><arg type="x"/></signal>
    <property name="PlaybackStatus" type="s" access="read"/>
    <property name="LoopStatus" type="s" access="readwrite"/>
    <property name="Rate" type="d" access="readwrite"/>
    <property name="Shuffle" type="b" access="readwrite"/>
    <property name="Metadata" type="a{sv}" access="read"/>
    <property name="Volume" type="d" access="readwrite"/>
    <property name="Position" type="x" access="read"/>
    <property name="CanGoNext" type="b" access="read"/>
    <property name="CanGoPrevious" type="b" access="read"/>
    <property name="CanPlay" type="b" access="read"/>
    <property name="CanPause" type="b" access="read"/>
    <property name="CanSeek" type="b" access="read"/>
    <property name="CanControl" type="b" access="read"/>
  </interface>
</node>
"""
TRACKS = [
    {"title": "First Light", "artist": ["Test Band"], "album": "Integration", "length": 180_000_000},
    {"title": "Second Wind", "artist": ["Test Band", "Guest"], "album": "Integration", "length": 240_000_000},
]
TYPES = {"PlaybackStatus": "s", "LoopStatus": "s", "Rate": "d", "Shuffle": "b", "Volume": "d", "Position": "x",
         "CanGoNext": "b", "CanGoPrevious": "b", "CanPlay": "b", "CanPause": "b", "CanSeek": "b", "CanControl": "b",
         "Identity": "s", "DesktopEntry": "s", "CanQuit": "b", "CanRaise": "b"}


class FakePlayer:
    def __init__(self, conn, name, identity="Test Player", can_next=True, length=True, art_url="", tracks=None):
        self.conn = conn
        self.name = f"org.mpris.MediaPlayer2.{name}"
        self.tracks = tracks or TRACKS
        self.index = 0
        self.length = length
        self.art_url = art_url
        self.calls = []
        self.props = {"PlaybackStatus": "Stopped", "LoopStatus": "None", "Rate": 1.0, "Shuffle": False,
                      "Volume": 0.8, "Position": 0, "CanGoNext": can_next, "CanGoPrevious": True, "CanPlay": True,
                      "CanPause": True, "CanSeek": True, "CanControl": True}
        self.root = {"Identity": identity, "DesktopEntry": name, "CanQuit": False, "CanRaise": False}
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        self.ids = [conn.register_object("/org/mpris/MediaPlayer2", iface, self._call, self._get, self._set)
                    for iface in node.interfaces]
        self.owner = Gio.bus_own_name_on_connection(conn, self.name, Gio.BusNameOwnerFlags.NONE, None, None)

    def close(self):
        Gio.bus_unown_name(self.owner)
        for registration in self.ids:
            self.conn.unregister_object(registration)

    # ------------------------------------------------------------ data
    def metadata(self):
        track = self.tracks[self.index]
        data = {"mpris:trackid": GLib.Variant("o", f"/test/track/{self.index}"),
                "xesam:title": GLib.Variant("s", track["title"]),
                "xesam:artist": GLib.Variant("as", track["artist"]),
                "xesam:album": GLib.Variant("s", track["album"])}
        if self.length:
            data["mpris:length"] = GLib.Variant("x", track["length"])
        if self.art_url:
            data["mpris:artUrl"] = GLib.Variant("s", self.art_url)
        return data

    def variant(self, name):
        if name == "Metadata":
            return GLib.Variant("a{sv}", self.metadata())
        if name in self.root:
            return GLib.Variant(TYPES[name], self.root[name])
        return GLib.Variant(TYPES[name], self.props[name])

    def changed(self, *names):
        values = {name: self.variant(name) for name in names}
        self.conn.emit_signal(None, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties",
                              "PropertiesChanged",
                              GLib.Variant("(sa{sv}as)", ("org.mpris.MediaPlayer2.Player", values, [])))

    def set_status(self, status):
        self.props["PlaybackStatus"] = status
        self.changed("PlaybackStatus")

    def set_track(self, index):
        self.index = index % len(self.tracks)
        self.props["Position"] = 0
        self.changed("Metadata")

    def set_caps(self, **caps):
        self.props.update(caps)
        self.changed(*caps)

    def seek_to(self, position):
        self.props["Position"] = position
        self.conn.emit_signal(None, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Seeked",
                              GLib.Variant("(x)", (position,)))

    # ------------------------------------------------------------ D-Bus
    def _get(self, _conn, _sender, _path, _iface, name):
        return self.variant(name)

    def _set(self, _conn, _sender, _path, _iface, name, value):
        self.props[name] = value.unpack()
        self.calls.append(("Set", name, self.props[name]))
        self.changed(name)
        return True

    def _call(self, _conn, _sender, _path, _iface, method, params, invocation):
        self.calls.append((method, params.unpack() if params is not None else ()))
        status = self.props["PlaybackStatus"]
        if method == "PlayPause":
            self.set_status("Paused" if status == "Playing" else "Playing")
        elif method == "Play":
            self.set_status("Playing")
        elif method == "Pause":
            self.set_status("Paused")
        elif method == "Stop":
            self.set_status("Stopped")
        elif method == "Next":
            if not self.props["CanGoNext"]:
                invocation.return_dbus_error("org.mpris.MediaPlayer2.Error", "cannot go next")
                return
            self.set_track(self.index + 1)
        elif method == "Previous":
            self.set_track(self.index - 1)
        elif method == "Seek":
            self.seek_to(max(0, self.props["Position"] + params.unpack()[0]))
        elif method == "SetPosition":
            self.seek_to(params.unpack()[1])
        invocation.return_value(None)


if __name__ == "__main__":
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    player = FakePlayer(connection, sys.argv[1] if len(sys.argv) > 1 else "bsmdtest")
    player.set_status("Playing")
    GLib.MainLoop().run()
