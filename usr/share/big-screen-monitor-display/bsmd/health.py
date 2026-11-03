"""Display Health Monitor: heartbeats, link state machine, backoff, incidents.

The watchdog never looks at pixels: a static theme legitimately sends no
data. Each subsystem reports *progress* (a loop iteration that completed,
even if it decided nothing had to be sent) and *in-flight* operations, so a
thread blocked inside a call is detected even though the image is static.
"""

import collections
import json
import os
import random
import threading
import time

# Link states
STARTING = "starting"
HEALTHY = "healthy"
DEGRADED = "degraded"
RECOVERING = "recovering"
DISCONNECTED = "disconnected"
RETRYING = "retrying"
FAILED = "failed"
STOPPED = "stopped"

TRANSITIONS = {
    STARTING: {RECOVERING, DISCONNECTED, STOPPED},
    HEALTHY: {DEGRADED, RECOVERING, STOPPED},
    DEGRADED: {HEALTHY, RECOVERING, STOPPED},
    RECOVERING: {HEALTHY, DISCONNECTED, RETRYING, STOPPED},
    DISCONNECTED: {RETRYING, STOPPED},
    RETRYING: {RECOVERING, DISCONNECTED, FAILED, STOPPED},
    FAILED: {RECOVERING, STOPPED},
    STOPPED: set(),
}


class InvalidTransition(RuntimeError):
    pass


class LinkStateMachine:
    def __init__(self, clock=time.monotonic, on_change=None):
        self.state = STARTING
        self.since = clock()
        self.history = collections.deque(maxlen=64)
        self._clock = clock
        self._on_change = on_change
        self._lock = threading.Lock()

    def to(self, new_state, reason=""):
        with self._lock:
            old = self.state
            if new_state == old:
                return False
            if new_state not in TRANSITIONS[old]:
                raise InvalidTransition(f"{old} -> {new_state}")
            self.state = new_state
            self.since = self._clock()
            self.history.append((time.time(), old, new_state, reason))
        if self._on_change:
            self._on_change(old, new_state, reason)
        return True


class Backoff:
    """Exponential backoff with jitter and a cap."""

    def __init__(self, base=1.0, factor=2.0, cap=30.0, jitter=0.2, rng=None):
        self.base, self.factor, self.cap, self.jitter = base, factor, cap, jitter
        self.attempt = 0
        self._rng = rng or random.Random()

    def next_delay(self):
        delay = min(self.cap, self.base * (self.factor ** self.attempt))
        self.attempt += 1
        if self.jitter:
            delay *= 1 + self._rng.uniform(-self.jitter, self.jitter)
        return max(0.0, delay)

    def reset(self):
        self.attempt = 0


class Heartbeat:
    """Progress tracker for one subsystem (thread safe enough under the GIL)."""

    def __init__(self, name, clock=time.monotonic):
        self.name = name
        self._clock = clock
        self.last_progress = clock()
        self.last_success = None
        self.op_name = None
        self.op_started = None
        self.iterations = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.last_error = ""
        self.last_duration = 0.0
        self.avg_duration = 0.0
        self.max_duration = 0.0

    def begin(self, op):
        self.op_name = op
        self.op_started = self._clock()

    def end(self, ok=True, error=""):
        now = self._clock()
        if self.op_started is not None:
            duration = now - self.op_started
            self.last_duration = duration
            self.max_duration = max(self.max_duration, duration)
            self.avg_duration = duration if not self.iterations else self.avg_duration * 0.9 + duration * 0.1
        self.op_name = None
        self.op_started = None
        self.progress(ok, error)

    def progress(self, ok=True, error=""):
        now = self._clock()
        self.last_progress = now
        self.iterations += 1
        if ok:
            self.last_success = now
            self.consecutive_errors = 0
        else:
            self.errors += 1
            self.consecutive_errors += 1
            self.last_error = str(error)[:300]

    def stalled(self, progress_timeout, op_timeout):
        """Return a reason string if the subsystem looks stuck, else None."""
        now = self._clock()
        if self.op_started is not None and now - self.op_started > op_timeout:
            return f"{self.name}: '{self.op_name}' running for {now - self.op_started:.1f}s"
        if now - self.last_progress > progress_timeout:
            return f"{self.name}: no progress for {now - self.last_progress:.1f}s"
        return None

    def snapshot(self):
        now = self._clock()
        return {
            "age_s": round(now - self.last_progress, 2),
            "last_success_age_s": None if self.last_success is None else round(now - self.last_success, 2),
            "in_flight": self.op_name,
            "in_flight_s": None if self.op_started is None else round(now - self.op_started, 2),
            "iterations": self.iterations,
            "errors": self.errors,
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error,
            "last_ms": round(self.last_duration * 1000, 2),
            "avg_ms": round(self.avg_duration * 1000, 2),
            "max_ms": round(self.max_duration * 1000, 2),
        }


SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR, SEVERITY_CRITICAL = "info", "warning", "error", "critical"


class IncidentLog:
    """Bounded in-memory incident history, optionally appended to a JSONL file."""

    def __init__(self, path=None, maxlen=100, max_file_lines=500, logger=None):
        self.items = collections.deque(maxlen=maxlen)
        self.path = path
        self.max_file_lines = max_file_lines
        self.logger = logger
        self._lock = threading.Lock()
        self._file_lines = None
        if path:
            self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                lines = handle.readlines()
        except OSError:
            self._file_lines = 0
            return
        self._file_lines = len(lines)
        for line in lines[-self.items.maxlen:]:
            try:
                self.items.append(json.loads(line))
            except ValueError:
                continue

    def record(self, kind, severity, message, **fields):
        entry = {"time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": kind,
                 "severity": severity, "message": message}
        entry.update({key: value for key, value in fields.items() if value is not None})
        with self._lock:
            self.items.append(entry)
            self._append_file(entry)
        if self.logger:
            level = {"info": 20, "warning": 30, "error": 40, "critical": 50}[severity]
            extra = " ".join(f"{key}={value}" for key, value in fields.items() if value is not None)
            self.logger.log(level, "incident kind=%s %s %s", kind, message, extra)
        return entry

    def _append_file(self, entry):
        if not self.path:
            return
        try:
            if self._file_lines is not None and self._file_lines >= self.max_file_lines:
                keep = list(self.items)[-self.max_file_lines // 2:]
                tmp = self.path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as handle:
                    handle.writelines(json.dumps(item, ensure_ascii=False) + "\n" for item in keep)
                os.replace(tmp, self.path)
                self._file_lines = len(keep)
            else:
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
                self._file_lines = (self._file_lines or 0) + 1
        except OSError:
            self.path = None  # read-only state dir: keep the in-memory history

    def recent(self, count=50):
        with self._lock:
            return list(self.items)[-count:]
