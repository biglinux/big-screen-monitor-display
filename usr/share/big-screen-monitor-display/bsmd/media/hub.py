"""Media state as seen by the renderers.

The service owns one :class:`MediaHub`, fed by :class:`bsmd.media.ipc.Server`;
every display reads the same hub (no D-Bus connection per display or per
frame). The configuration window owns a local hub fed in-process by its own
media core, so the preview shows the real music too.

``view()`` returns a :class:`MediaState`: an immutable-ish snapshot with the
players, the system volume, art lookup and the optional spectrum.
"""

import collections
import os
import threading
import time

from PIL import Image

from . import ipc, model

STALE_AFTER = 20.0          # the agent sends a heartbeat every 5 s
SPECTRUM_STALE = 1.0
ART_CACHE = 16


class MediaState:
    def __init__(self, snapshot=None, arts=None, spectrum=None, connected=False, stale=False, uid=None,
                 demo=False):
        self.snapshot = snapshot
        self._arts = arts or {}
        self.spectrum = spectrum
        self.connected = connected          # an agent has sent fresh data
        self.stale = stale                  # it stopped talking (logout, crash)
        self.uid = uid
        self.demo = demo

    @property
    def players(self):
        return self.snapshot["players"] if self.snapshot and not self.stale else []

    @property
    def volume(self):
        if self.snapshot and not self.stale:
            return self.snapshot["volume"]
        return model.clean_volume({})

    @property
    def agent(self):
        return self.snapshot["agent"] if self.snapshot else model.clean_agent({})

    def art(self, art_id):
        return self._arts.get(art_id) if art_id else None

    def spectrum_bands(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.spectrum or now - self.spectrum["mono"] > SPECTRUM_STALE:
            return None
        return self.spectrum["bands"]


class MediaHub:
    def __init__(self, socket_path=None, on_change=None, clock=time.monotonic):
        self.socket_path = socket_path
        self.on_change = on_change
        self.clock = clock
        self.lock = threading.Lock()
        self.states = {}                # uid -> {"snapshot", "received", "spectrum"}
        self.arts = collections.OrderedDict()   # (uid, id) -> Image
        self.server = None
        self.messages = 0
        self.invalid = 0
        self._seat = (-1e9, None)

    # ------------------------------------------------------------ service socket
    def start(self):
        if not self.socket_path:
            return False
        self.server = ipc.Server(self.socket_path, self.on_message, on_disconnect=self._disconnected)
        return self.server.start()

    def stop(self):
        if self.server:
            self.server.stop()
            self.server = None

    # ------------------------------------------------------------ input
    def on_message(self, uid, message):
        kind = message.get("type")
        now = self.clock()
        if kind == "snapshot":
            snapshot = model.clean_snapshot(message)
            if snapshot is None:
                self.invalid += 1
                return
            with self.lock:
                state = self.states.setdefault(uid, {"snapshot": None, "received": 0.0, "spectrum": None})
                old = state["snapshot"]
                state["snapshot"] = snapshot
                state["received"] = now
                self.messages += 1
            if self.on_change and _significant(old, snapshot):
                self.on_change()
        elif kind == "art":
            art = model.clean_art(message)
            if art is None:
                self.invalid += 1
                return
            art_id, width, height, raw = art
            image = Image.frombytes("RGB", (width, height), raw)
            with self.lock:
                self.arts[(uid, art_id)] = image
                self.arts.move_to_end((uid, art_id))
                while len(self.arts) > ART_CACHE:
                    self.arts.popitem(last=False)
            if self.on_change:
                self.on_change()
        elif kind == "spectrum":
            spectrum = model.clean_spectrum(message)
            if spectrum is None:
                return
            with self.lock:
                state = self.states.setdefault(uid, {"snapshot": None, "received": 0.0, "spectrum": None})
                state["spectrum"] = spectrum
                state["received"] = max(state["received"], now)
        else:
            self.invalid += 1

    def _disconnected(self, uid):
        with self.lock:
            state = self.states.get(uid)
            if state:
                state["received"] = min(state["received"], self.clock() - STALE_AFTER - 1)
        if self.on_change:
            self.on_change()

    # ------------------------------------------------------------ output
    def _pick_uid(self):
        now = self.clock()
        if now - self._seat[0] > 2.0:        # one small sysfs-like read every 2 s, not per frame
            self._seat = (now, ipc.active_seat_uid())
        active = self._seat[1]
        if active is not None and active in self.states:
            return active
        if not self.states:
            return None
        return max(self.states, key=lambda uid: self.states[uid]["received"])

    def view(self):
        with self.lock:
            uid = self._pick_uid()
            if uid is None:
                return MediaState()
            state = self.states[uid]
            stale = self.clock() - state["received"] > STALE_AFTER
            arts = {art_id: image for (owner, art_id), image in self.arts.items() if owner == uid}
            return MediaState(state["snapshot"], arts, state["spectrum"], connected=not stale, stale=stale, uid=uid)

    def status(self):
        view = self.view()
        server = self.server
        return {
            "socket": self.socket_path,
            "listening": bool(server and server.listener),
            "socket_error": server.error if server else None,
            "agents": len(server.clients) if server else 0,
            "rejected": server.rejected if server else 0,
            "connected": view.connected,
            "uid": view.uid,
            "players": [{"bus": p["bus"], "identity": p["identity"], "status": p["status"]} for p in view.players],
            "volume_backend": view.volume.get("backend"),
            "messages": self.messages,
            "invalid": self.invalid,
        }


def _significant(old, new):
    """Changes that deserve an immediate redraw (not the periodic heartbeat)."""
    if old is None:
        return True
    def key(snapshot):
        return ([(p["bus"], p["status"], p["title"], p["artist"], p["art"], p["position_us"] // 1_000_000
                  if p["position_us"] is not None else None, p["length_us"], p["can"]["next"],
                  p["shuffle"], p["loop"]) for p in snapshot["players"]],
                snapshot["active"], snapshot["volume"]["percent"], snapshot["volume"]["muted"],
                snapshot["volume"]["output"])
    return key(old) != key(new)


# ---------------------------------------------------------------- in-process hub (configuration window)

_LOCAL = None


def set_local(hub):
    global _LOCAL
    _LOCAL = hub


def local():
    return _LOCAL


def local_uid():
    return os.getuid()
