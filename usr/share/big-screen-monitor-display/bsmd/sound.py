"""Optional retro sound effects, played by the host computer.

The panels have no speaker and the system service cannot reach the user's
audio session, so a tiny agent runs inside the session (autostarted only
when the user enables sound). It watches the service status for story
events and plays short, original, procedurally synthesised effects.
Silent by default.
"""

import io
import os
import shutil
import subprocess
import time
import wave

import numpy as np

from . import runtime, settings

RATE = 22050
PLAYERS = (["pw-play", "--volume={volume}"], ["paplay", "--volume={pa_volume}"], ["aplay", "-q"])
EVENT_SOUNDS = {
    "awaaay": "awaaay", "shark_run": "alarm", "coconut_hit": "bonk", "raft_broken": "splash",
    "ufo_wake": "ufo", "ufo_win": "fanfare", "raft_done": "fanfare", "treasure": "fanfare",
    "laugh": "laugh", "fish_caught": "blip_up", "gull": "squawk",
}
SPEECH_CHANCE = {"low": 0.15, "normal": 0.4, "high": 0.8}
MIN_GAP = 1.5


def _square(freqs, duty=0.5):
    phase = np.cumsum(freqs / RATE) % 1.0
    return np.where(phase < duty, 1.0, -1.0)


def _envelope(n, attack=0.01, release=0.08):
    env = np.ones(n)
    a, r = int(RATE * attack), int(RATE * release)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if r and r < n:
        env[-r:] = np.linspace(1, 0, r)
    return env


def synth(kind):
    """Return a mono float signal in -1..1 for ``kind``."""
    rng = np.random.default_rng(len(kind))

    def sweep(f0, f1, seconds, duty=0.5):
        n = int(RATE * seconds)
        return _square(np.linspace(f0, f1, n), duty) * _envelope(n)

    if kind == "awaaay":
        n = int(RATE * 1.1)
        vibrato = 1 + 0.03 * np.sin(np.linspace(0, 40, n))
        return _square(np.linspace(520, 260, n) * vibrato, 0.35) * _envelope(n, 0.02, 0.3)
    if kind == "alarm":
        return np.concatenate([sweep(880, 660, 0.12), sweep(880, 660, 0.12), sweep(880, 660, 0.12)])
    if kind == "bonk":
        n = int(RATE * 0.18)
        return (_square(np.linspace(180, 90, n)) * 0.7 + rng.uniform(-0.3, 0.3, n)) * _envelope(n, 0.001, 0.15)
    if kind == "splash":
        n = int(RATE * 0.6)
        noise = rng.uniform(-1, 1, n)
        smooth = np.convolve(noise, np.ones(6) / 6, mode="same")
        return smooth * _envelope(n, 0.005, 0.5)
    if kind == "ufo":
        n = int(RATE * 1.2)
        return _square(600 + 220 * np.sin(np.linspace(0, 30, n)), 0.5) * _envelope(n, 0.1, 0.3) * 0.6
    if kind == "fanfare":
        return np.concatenate([sweep(f, f, 0.11) for f in (523, 659, 784, 1046)] + [sweep(1046, 1046, 0.25)])
    if kind == "laugh":
        return np.concatenate([np.concatenate([sweep(420, 380, 0.07), np.zeros(int(RATE * 0.05))])
                               for _ in range(4)])
    if kind == "squawk":
        return sweep(1400, 900, 0.18, 0.25) * 0.7
    if kind == "blip_up":
        return sweep(500, 900, 0.09)
    # Speech "blips": a few random syllables, like classic adventure games.
    return np.concatenate([sweep(f, f * 0.9, 0.045, 0.4) for f in rng.uniform(220, 330, 5)]) * 0.6


def to_wav(signal, volume=1.0):
    data = np.clip(signal * 0.6 * volume, -1, 1)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes((data * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


class Player:
    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp",
                                                   "big-screen-monitor-sounds")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.command = next((cmd for cmd in PLAYERS if shutil.which(cmd[0])), None)
        self.last = 0.0

    def play(self, kind, volume_percent):
        if not self.command or time.monotonic() - self.last < MIN_GAP:
            return False
        path = os.path.join(self.cache_dir, f"{kind}.wav")
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(to_wav(synth(kind)))
        volume = max(0, min(100, volume_percent)) / 100
        args = [part.format(volume=f"{volume:.2f}", pa_volume=int(volume * 65536)) for part in self.command]
        try:
            subprocess.Popen(args + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        self.last = time.monotonic()
        return True


def sound_for(event, frequency, rng):
    """Effect for a theme event ("say:<context>" or "fx:<name>"), or None."""
    source, _sep, name = event.partition(":")
    kind = EVENT_SOUNDS.get(name)
    if kind:
        return kind
    if source == "say" and rng.random() < SPEECH_CHANCE.get(frequency, 0.4):
        return "speech"
    return None


def run_agent(poll=1.0):
    """Session agent: exits by itself when sound is disabled."""
    import random
    rng = random.Random()
    player = Player()
    store = settings.SettingsStore()
    last_seq = None
    while True:
        store.refresh()
        values = store.get()
        if not values.get("sound_enabled"):
            return 0
        status = runtime.read_status() or {}
        events = status.get("sound_events") or []
        if last_seq is None:
            last_seq = max((seq for seq, _event in events), default=0)
        for seq, event in events:
            if seq > last_seq:
                last_seq = seq
                kind = sound_for(event, values.get("ba_dialogue_frequency", "normal"), rng)
                if kind:
                    player.play(kind, values.get("sound_volume", 40))
        time.sleep(poll)


AUTOSTART_NAME = "big-screen-monitor-sound.desktop"


def autostart_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "autostart", AUTOSTART_NAME)


def set_autostart(enabled, main_py):
    path = autostart_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("[Desktop Entry]\nType=Application\nName=Big Screen Monitor sounds\n"
                         f"Exec=python3 {main_py} --sound-agent\nNoDisplay=true\n"
                         "X-GNOME-Autostart-enabled=true\n")
    elif os.path.exists(path):
        os.unlink(path)
