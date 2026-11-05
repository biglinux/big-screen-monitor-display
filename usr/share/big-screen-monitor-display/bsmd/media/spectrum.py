"""Real audio spectrum (opt-in "Real spectrum" visualizer).

MPRIS carries no audio, so a real spectrum needs the sound itself: the agent
records the *monitor* of the default output (what the speakers play, mixed)
with ``parec`` at 16 kHz mono, 16-bit, and computes a log-spaced band FFT
with NumPy, ~12 times per second. The stream is named "Big Screen Monitor
visualizer" so it is visible in the desktop's sound settings. Capture runs
only while the visualizer is set to the real spectrum *and* something plays;
samples never leave the process — only band levels (0..1) are sent.
"""

import logging
import shutil
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger("bsmd.media")

RATE = 16000
CHUNK = 1024              # 64 ms
BANDS = 24
LOW_HZ, HIGH_HZ = 50.0, 7500.0
FLOOR_DB, CEIL_DB = -72.0, -12.0
SEND_EVERY = 1 / 12


def band_edges(bands=BANDS, rate=RATE, size=CHUNK):
    freqs = np.geomspace(LOW_HZ, HIGH_HZ, bands + 1)
    bins = np.clip(np.round(freqs * size / rate).astype(int), 1, size // 2)
    for index in range(1, len(bins)):          # every band gets at least one FFT bin
        if bins[index] <= bins[index - 1]:
            bins[index] = bins[index - 1] + 1
    return np.minimum(bins, size // 2 + 1)


_WINDOW = np.hanning(CHUNK)
_EDGES = band_edges()


def compute_bands(samples, sensitivity=1.0, edges=_EDGES):
    """Band levels 0..1 from int16 or float samples (one chunk)."""
    data = np.asarray(samples, dtype=np.float64)
    if data.size < CHUNK:
        data = np.pad(data, (0, CHUNK - data.size))
    data = data[:CHUNK]
    if np.issubdtype(np.asarray(samples).dtype, np.integer):
        data = data / 32768.0
    spectrum = np.abs(np.fft.rfft(data * _WINDOW)) / (CHUNK / 4)
    power = spectrum ** 2
    levels = []
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        energy = float(power[low:high].mean()) if high > low else 0.0
        db = 10 * np.log10(energy + 1e-12)
        level = (db - FLOOR_DB) / (CEIL_DB - FLOOR_DB) * sensitivity
        levels.append(min(1.0, max(0.0, level)))
    return levels


class SpectrumCapture:
    def __init__(self, on_bands, sensitivity=1.0):
        self.on_bands = on_bands
        self.sensitivity = sensitivity
        self.proc = None
        self.thread = None
        self.stop_event = threading.Event()
        self.state = "off"
        self.error = ""

    @staticmethod
    def available():
        return shutil.which("parec") is not None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running:
            return True
        if not self.available():
            self.state, self.error = "unavailable", "parec not installed"
            return False
        try:
            self.proc = subprocess.Popen(
                ["parec", "--device=@DEFAULT_MONITOR@", "--format=s16le", f"--rate={RATE}", "--channels=1",
                 "--latency-msec=60", "--raw", "--client-name=Big Screen Monitor visualizer",
                 "--stream-name=Big Screen Monitor visualizer"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
        except OSError as error:
            self.state, self.error = "unavailable", str(error)
            return False
        self.stop_event.clear()
        self.state = "running"
        self.thread = threading.Thread(target=self._read, name="spectrum", daemon=True)
        self.thread.start()
        return True

    def stop(self):
        self.stop_event.set()
        proc, self.proc = self.proc, None
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        if self.state == "running":
            self.state = "off"

    def _read(self):
        proc = self.proc
        smooth = np.zeros(BANDS)
        last_sent = 0.0
        while not self.stop_event.is_set() and proc is not None:
            data = proc.stdout.read(CHUNK * 2)
            if not data or len(data) < CHUNK * 2:
                break
            levels = np.array(compute_bands(np.frombuffer(data, dtype="<i2"), self.sensitivity))
            # Fast attack, slow release, like a hardware analyser.
            smooth = np.where(levels > smooth, levels, smooth * 0.78 + levels * 0.22)
            now = time.monotonic()
            if now - last_sent >= SEND_EVERY:
                last_sent = now
                self.on_bands([round(float(v), 3) for v in smooth], now)
        if not self.stop_event.is_set():
            self.state, self.error = "unavailable", "audio capture ended"
            log.info("spectrum capture ended")
