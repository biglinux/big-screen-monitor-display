"""System output volume (the default sink), independent of any player.

Backends, first that works wins:
    pulse   ``pactl`` (PipeWire's pipewire-pulse or PulseAudio). Event driven:
            one long-lived ``pactl subscribe`` reports sink/server changes
            (keyboard keys, Plasma/GNOME sliders, default output switched to a
            headset); only then is the state read again. Restarted with backoff
            when PipeWire/PulseAudio restarts.
    wpctl   WirePlumber without pactl. wpctl has no event stream, so it is read
            every ``POLL`` seconds (documented limitation).
    alsa    ``amixer`` Master control, polled.
Values above 100 % (software amplification) are reported as they are; the
controls clamp to the configured safe maximum. All processes run
asynchronously (Gio.Subprocess), never in a render thread.
"""

import json
import logging
import re
import shutil

from gi.repository import Gio, GLib

log = logging.getLogger("bsmd.media")

POLL = 2
DEBOUNCE_MS = 60
RESTART_DELAYS = (1, 2, 5, 10, 30)


# ---------------------------------------------------------------- parsers (pure)

def parse_pactl_sinks(text, default_sink, wanted=None):
    """State from ``pactl --format=json list sinks``; ``wanted`` sink name wins when present."""
    sinks = json.loads(text)
    if not isinstance(sinks, list) or not sinks:
        raise ValueError("no sinks")
    by_name = {sink.get("name"): sink for sink in sinks if isinstance(sink, dict)}
    sink = by_name.get(wanted) or by_name.get(default_sink) or next(iter(by_name.values()))
    percents = []
    for channel in (sink.get("volume") or {}).values():
        value = channel.get("value_percent") if isinstance(channel, dict) else None
        if isinstance(value, str) and value.rstrip("%").strip().isdigit():
            percents.append(int(value.rstrip("%")))
        elif isinstance(channel, dict) and isinstance(channel.get("value"), int):
            percents.append(round(channel["value"] * 100 / 65536))
    if not percents:
        raise ValueError("sink without volume")
    def describe(item):
        description = item.get("description")
        return description if usable_description(description) else ""
    return {"available": True, "percent": max(percents), "muted": bool(sink.get("mute")),
            "output": describe(sink), "sink": sink.get("name") or "",
            "outputs": [(s.get("name"), describe(s)) for s in by_name.values()]}


def parse_pactl_descriptions(text):
    """{sink name: description} from ``LC_ALL=C pactl list sinks`` (UTF-8 safe, unlike the
    JSON output of some pactl builds, which prints "(null)" for non-ASCII descriptions)."""
    result = {}
    name = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Name: "):
            name = line[6:].strip()
        elif line.startswith("Description: ") and name:
            result[name] = line[13:].strip()
            name = None
    return result


def usable_description(text):
    return bool(text) and text.strip() not in ("(null)", "null")


def parse_pactl_text(volume_text, mute_text):
    """Fallback for pactl without --format=json (PulseAudio < 16)."""
    percents = [int(value) for value in re.findall(r"(\d+)%", volume_text)]
    if not percents:
        raise ValueError("no volume")
    return {"available": True, "percent": max(percents), "muted": "yes" in mute_text.lower()}


def parse_wpctl(text):
    match = re.search(r"Volume:\s*([0-9.]+)", text)
    if not match:
        raise ValueError("no volume")
    return {"available": True, "percent": round(float(match.group(1)) * 100), "muted": "[MUTED]" in text}


def parse_wpctl_description(text):
    match = re.search(r'node\.description\s*=\s*"([^"]*)"', text) or re.search(r'node\.nick\s*=\s*"([^"]*)"', text)
    return match.group(1) if match else ""


def parse_amixer(text):
    percents = [int(value) for value in re.findall(r"\[(\d+)%\]", text)]
    if not percents:
        raise ValueError("no Master control")
    states = re.findall(r"\[(on|off)\]", text)
    return {"available": True, "percent": max(percents), "muted": bool(states) and all(s == "off" for s in states)}


# ---------------------------------------------------------------- async process helper

def run(argv, callback, c_locale=False):
    """Run argv; callback(ok, stdout) on the main loop."""
    try:
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        if c_locale:
            launcher.setenv("LC_ALL", "C", True)
        proc = launcher.spawnv(argv)
    except GLib.Error as error:
        callback(False, error.message)
        return

    def done(process, result):
        try:
            _ok, stdout, _stderr = process.communicate_utf8_finish(result)
        except GLib.Error as error:
            callback(False, error.message)
            return
        callback(process.get_successful(), stdout or "")
    proc.communicate_utf8_async(None, None, done)


# ---------------------------------------------------------------- backends

class Backend:
    name = "none"

    def __init__(self, on_change, wanted_sink=""):
        self.on_change = on_change
        self.wanted = wanted_sink
        self.state = {"available": False, "percent": None, "muted": None, "output": "", "error": ""}
        self.outputs = []
        self.failed = False

    def snapshot(self):
        return dict(self.state, backend=self.name)

    def _publish(self, state):
        state = dict(self.state, **state, error="")
        if state != self.state:
            self.state = state
            self.on_change()

    def _fail(self, message):
        state = dict(self.state, available=False, error=message)
        if state != self.state:
            self.state = state
            self.on_change()

    def start(self):
        pass

    def stop(self):
        pass

    def set_percent(self, percent, reply=None):
        (reply or (lambda ok, message: None))(False, "no volume backend")

    def set_mute(self, mute, reply=None):
        (reply or (lambda ok, message: None))(False, "no volume backend")


class PulseBackend(Backend):
    name = "pulse"

    def __init__(self, on_change, wanted_sink=""):
        super().__init__(on_change, wanted_sink)
        self.proc = None
        self.stream = None
        self.cancel = None
        self.pending = None
        self.restarts = 0
        self.json_ok = True
        self.target = "@DEFAULT_SINK@"
        self.descriptions = {}
        self.stopped = False

    @staticmethod
    def available():
        return shutil.which("pactl") is not None

    def start(self):
        self.stopped = False
        self._spawn()
        self.refresh()

    def stop(self):
        # Mark first: cancelling the read ends _on_line, which must not respawn pactl.
        self.stopped = True
        if self.pending is not None:
            GLib.source_remove(self.pending)
            self.pending = None
        if self.cancel:
            self.cancel.cancel()
        if self.proc:
            self.proc.force_exit()
            self.proc = None

    def _spawn(self):
        try:
            self.proc = Gio.Subprocess.new(["pactl", "subscribe"],
                                           Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as error:
            self._fail(f"pactl subscribe: {error.message}")
            return
        self.cancel = Gio.Cancellable()
        self.stream = Gio.DataInputStream.new(self.proc.get_stdout_pipe())
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, self.cancel, self._on_line)

    def _on_line(self, stream, result):
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if self.stopped:
            return
        if line is None:
            # pactl ended: PipeWire/PulseAudio restarted or the session is going away.
            self.proc = None
            delay = RESTART_DELAYS[min(self.restarts, len(RESTART_DELAYS) - 1)]
            self.restarts += 1
            self._fail("audio server connection lost, retrying")
            GLib.timeout_add_seconds(delay, self._restart)
            return
        self.restarts = 0
        if " on sink #" in line or " on server" in line or " on card #" in line:
            self.schedule_refresh()
        stream.read_line_async(GLib.PRIORITY_DEFAULT, self.cancel, self._on_line)

    def _restart(self):
        if self.stopped:
            return False
        self._spawn()
        self.refresh()
        return False

    def schedule_refresh(self):
        if self.pending is None:
            self.pending = GLib.timeout_add(DEBOUNCE_MS, self._debounced)

    def _debounced(self):
        self.pending = None
        self.refresh()
        return False

    def refresh(self):
        def got_default(ok, stdout):
            default = stdout.strip() if ok else ""
            if self.json_ok:
                run(["pactl", "--format=json", "list", "sinks"], lambda ok2, out: self._got_sinks(ok2, out, default))
            else:
                self._refresh_text()
        run(["pactl", "get-default-sink"], got_default)

    def _got_sinks(self, ok, stdout, default):
        if not ok:
            self.json_ok = False
            self._refresh_text()
            return
        try:
            state = parse_pactl_sinks(stdout, default, self.wanted)
        except (ValueError, TypeError, AttributeError):
            self.json_ok = False
            self._refresh_text()
            return
        outputs = state.pop("outputs")
        self.target = state.pop("sink") or "@DEFAULT_SINK@"
        missing = [name for name, description in outputs if not description and name not in self.descriptions]
        self.outputs = [(name, description or self.descriptions.get(name) or name) for name, description in outputs]
        if not state["output"]:
            state["output"] = self.descriptions.get(self.target, "")
        self._publish(state)
        if missing:
            run(["pactl", "list", "sinks"], self._got_descriptions, c_locale=True)

    def _got_descriptions(self, ok, stdout):
        if not ok:
            return
        found = parse_pactl_descriptions(stdout)
        # Remember names without a description too, so this runs once per new sink.
        self.descriptions.update({name: found.get(name, "") for name, _d in self.outputs})
        self.descriptions.update(found)
        self.outputs = [(name, self.descriptions.get(name) or name) for name, _d in self.outputs]
        if self.descriptions.get(self.target):
            self._publish({"output": self.descriptions[self.target]})

    def _refresh_text(self):
        def got_volume(ok, volume_text):
            if not ok:
                self.failed = True
                self._fail("pactl cannot reach the audio server")
                return
            run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"], lambda ok2, mute: self._got_text(volume_text, mute))
        run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"], got_volume)

    def _got_text(self, volume_text, mute_text):
        try:
            self._publish(parse_pactl_text(volume_text, mute_text))
        except ValueError as error:
            self._fail(str(error))

    def set_percent(self, percent, reply=None):
        run(["pactl", "set-sink-volume", self.target, f"{int(percent)}%"], lambda ok, _o: self._done(ok, reply))

    def set_mute(self, mute, reply=None):
        value = "toggle" if mute is None else ("1" if mute else "0")
        run(["pactl", "set-sink-mute", self.target, value], lambda ok, _o: self._done(ok, reply))

    def _done(self, ok, reply):
        self.schedule_refresh()       # the subscribe event also arrives; cheap and debounced
        if reply:
            reply(ok, "" if ok else "pactl failed")


class PolledBackend(Backend):
    def start(self):
        self.refresh()
        self.source = GLib.timeout_add_seconds(POLL, self._tick)

    def stop(self):
        if getattr(self, "source", None):
            GLib.source_remove(self.source)
            self.source = None

    def _tick(self):
        self.refresh()
        return True

    def _done(self, ok, reply):
        self.refresh()
        if reply:
            reply(ok, "" if ok else f"{self.name} failed")


class WpctlBackend(PolledBackend):
    name = "wpctl"
    TARGET = "@DEFAULT_AUDIO_SINK@"

    @staticmethod
    def available():
        return shutil.which("wpctl") is not None

    def refresh(self):
        def got(ok, stdout):
            if not ok:
                self._fail("wpctl cannot read the default output")
                return
            try:
                state = parse_wpctl(stdout)
            except ValueError as error:
                self._fail(str(error))
                return
            if not self.state.get("output"):
                run(["wpctl", "inspect", self.TARGET],
                    lambda ok2, text: ok2 and self._publish({"output": parse_wpctl_description(text)}))
            self._publish(state)
        run(["wpctl", "get-volume", self.TARGET], got)

    def set_percent(self, percent, reply=None):
        run(["wpctl", "set-volume", "-l", "2.0", self.TARGET, f"{percent / 100:.2f}"],
            lambda ok, _o: self._done(ok, reply))

    def set_mute(self, mute, reply=None):
        value = "toggle" if mute is None else ("1" if mute else "0")
        run(["wpctl", "set-mute", self.TARGET, value], lambda ok, _o: self._done(ok, reply))


class AlsaBackend(PolledBackend):
    name = "alsa"

    @staticmethod
    def available():
        return shutil.which("amixer") is not None

    def refresh(self):
        def got(ok, stdout):
            if not ok:
                self._fail("amixer: no Master control")
                return
            try:
                self._publish(dict(parse_amixer(stdout), output="ALSA Master"))
            except ValueError as error:
                self._fail(str(error))
        run(["amixer", "-M", "get", "Master"], got)

    def set_percent(self, percent, reply=None):
        run(["amixer", "-M", "-q", "set", "Master", f"{min(100, int(percent))}%"],
            lambda ok, _o: self._done(ok, reply))

    def set_mute(self, mute, reply=None):
        value = "toggle" if mute is None else ("mute" if mute else "unmute")
        run(["amixer", "-q", "set", "Master", value], lambda ok, _o: self._done(ok, reply))


BACKENDS = (PulseBackend, WpctlBackend, AlsaBackend)


class SystemVolume:
    """Picks a backend and falls back to the next one when it cannot work."""

    def __init__(self, on_change, wanted_sink="", max_percent=100):
        self.on_change = on_change
        self.wanted = wanted_sink
        self.max_percent = max_percent
        self.candidates = [cls for cls in BACKENDS if cls.available()]
        self.backend = None
        self._next()

    def _next(self):
        if self.backend:
            self.backend.stop()
        self.backend = None
        while self.candidates:
            cls = self.candidates.pop(0)
            self.backend = cls(self._changed, self.wanted)
            self.backend.start()
            return
        self.on_change()

    def _changed(self):
        backend = self.backend
        if backend and backend.failed and not backend.state["available"] and self.candidates:
            log.info("volume backend %s unusable (%s); trying the next one", backend.name, backend.state["error"])
            GLib.idle_add(lambda: self._next() and False)
        self.on_change()

    def stop(self):
        if self.backend:
            self.backend.stop()

    def set_wanted(self, sink):
        if sink != self.wanted:
            self.wanted = sink
            if self.backend:
                self.backend.wanted = sink
                if hasattr(self.backend, "refresh"):
                    self.backend.refresh()

    def snapshot(self):
        if self.backend is None:
            return {"available": False, "percent": None, "muted": None, "output": "", "backend": "none",
                    "error": "no audio control found (pactl, wpctl or amixer)"}
        return self.backend.snapshot()

    @property
    def outputs(self):
        return list(self.backend.outputs) if self.backend else []

    def set_percent(self, percent, reply=None):
        percent = max(0, min(self.max_percent, int(round(percent))))
        if self.backend:
            self.backend.set_percent(percent, reply)
        elif reply:
            reply(False, "no volume backend")

    def change(self, delta, reply=None):
        current = self.snapshot().get("percent")
        if current is None:
            if reply:
                reply(False, "volume unknown")
            return
        # Never push an already amplified value further up past the safe maximum.
        target = current + delta
        if delta > 0 and current >= self.max_percent:
            target = current
        self.set_percent(target, reply)

    def set_mute(self, mute=None, reply=None):
        if self.backend:
            self.backend.set_mute(mute, reply)
        elif reply:
            reply(False, "no volume backend")
