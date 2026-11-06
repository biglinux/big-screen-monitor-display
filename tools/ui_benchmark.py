#!/usr/bin/env python3
"""Reproducible benchmark of the configuration window (development tool).

    python3 tools/ui_benchmark.py [APP_DIR] [--json]

APP_DIR defaults to this checkout's usr/share/big-screen-monitor-display; pass
an older checkout to compare versions. The window runs inside its own
``dbus-run-session`` with a temporary settings file, memory GSettings and
private XDG directories, so the desktop and /etc are never touched. The
service status file is read as it is (read-only) so a connected display is
measured the way the user sees it.

Measured: time until the window is drawn and idle, idle RSS and CPU, CPU
while an animated preview is visible, page switch time and RSS after
repeated navigation. Works with the 4.x tab window and the 5.x sidebar.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APP = os.path.join(HERE, "..", "usr", "share", "big-screen-monitor-display")

CHILD = r'''
import json, os, sys, time
T0 = time.monotonic()
APP = sys.argv[1]
sys.path.insert(0, APP)
import psutil
import config_gui
from gi.repository import GLib

proc = psutil.Process()
result = {}
context = GLib.MainContext.default()


def pump(seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        context.iteration(False)
        time.sleep(0.002)


def settle():
    start = time.monotonic()
    while context.pending():
        context.iteration(False)
    return time.monotonic() - start


def thread_cpu():
    out = {}
    for t in proc.threads():
        try:
            name = open(f"/proc/self/task/{t.id}/comm").read().strip()
        except OSError:
            name = str(t.id)
        out[name] = out.get(name, 0) + t.user_time + t.system_time
    return out


def cpu_by_thread(seconds):
    before = thread_cpu()
    pump(seconds)
    after = thread_cpu()
    return {k: round((after[k] - before.get(k, 0)) / seconds * 100, 1) for k in after
            if after[k] - before.get(k, 0) > 0.001 * seconds}


def cpu_over(seconds):
    before = proc.cpu_times()
    start = time.monotonic()
    pump(seconds)
    after = proc.cpu_times()
    used = (after.user - before.user) + (after.system - before.system)
    return round(used / (time.monotonic() - start) * 100, 2)


def sections(window):
    if hasattr(window, "section_keys"):
        return list(window.section_keys()), window.show_section
    names = [page.get_name() for page in window.stack.get_pages() if page.get_visible()]
    return names, window.stack.set_visible_child_name


def animated(window, keys):
    for key in ("brother_away", "theme_brother_away"):
        if key in keys:
            return key
    return None


def run(window):
    result["window_drawn_s"] = round(time.monotonic() - T0, 3)
    settle()
    result["usable_s"] = round(time.monotonic() - T0, 3)
    pump(5)
    result["rss_idle_mb"] = round(proc.memory_info().rss / 1048576, 1)
    result["cpu_idle_percent"] = cpu_over(10)
    if os.environ.get("BENCH_THREADS"):
        result["idle_threads"] = cpu_by_thread(5)
    keys, show = sections(window)
    result["sections"] = keys
    switches = {}
    for key in keys:
        start = time.perf_counter()
        show(key)
        settle()
        switches[key] = round((time.perf_counter() - start) * 1000, 1)
        pump(0.6)
    result["switch_ms"] = switches
    result["switch_ms_max"] = max(switches.values()) if switches else None
    anim = animated(window, keys)
    if anim:
        show(anim)
        pump(4)
        if os.environ.get("BENCH_THREADS"):
            result["animated_threads_first"] = cpu_by_thread(5)
        result["cpu_animated_preview_percent"] = cpu_over(10)
        if os.environ.get("BENCH_THREADS"):
            result["animated_threads"] = cpu_by_thread(5)
    for _ in range(int(os.environ.get("BENCH_CYCLES", "4"))):
        for key in keys:
            show(key)
            settle()
            pump(0.15)
    show(keys[0])
    pump(3)
    result["rss_after_navigation_mb"] = round(proc.memory_info().rss / 1048576, 1)
    if os.environ.get("BENCH_LONG"):
        for _ in range(16):
            for key in keys:
                show(key)
                settle()
                pump(0.1)
        show(keys[0])
        pump(3)
        result["rss_after_long_navigation_mb"] = round(proc.memory_info().rss / 1048576, 1)
    result["threads"] = proc.num_threads()
    print("BENCH " + json.dumps(result), flush=True)
    window.close()
    os._exit(0)


original = config_gui.ConfigWindow.__init__


def patched(self, *args, **kwargs):
    original(self, *args, **kwargs)
    self.connect("map", lambda w: GLib.timeout_add(1, lambda: run(w) and False))


config_gui.ConfigWindow.__init__ = patched
config_gui.main([sys.argv[0]])
'''


def measure(app_dir, theme="brother_away"):
    app_dir = os.path.abspath(app_dir)
    tmp = tempfile.mkdtemp(prefix="bsmd-uibench-")
    try:
        sys.path.insert(0, app_dir)
        from bsmd import settings
        values = settings.defaults()
        values["theme"] = theme
        settings.save(values, os.path.join(tmp, "settings.json"))
        script = os.path.join(tmp, "child.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(CHILD)
        env = dict(os.environ, BSM_CONFIG=os.path.join(tmp, "settings.json"), GSETTINGS_BACKEND="memory",
                   XDG_CONFIG_HOME=os.path.join(tmp, "config"), XDG_CACHE_HOME=os.path.join(tmp, "cache"),
                   XDG_STATE_HOME=os.path.join(tmp, "state"), GTK_A11Y="none")
        command = ["dbus-run-session", "--", sys.executable, script, app_dir]
        output = subprocess.run(command, env=env, capture_output=True, text=True, timeout=240).stdout
        line = next((ln for ln in output.splitlines() if ln.startswith("BENCH ")), None)
        if line is None:
            raise RuntimeError("benchmark produced no result:\n" + output[-2000:])
        return json.loads(line[6:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    app = args[0] if args else DEFAULT_APP
    theme = argv[argv.index("--theme") + 1] if "--theme" in argv else "brother_away"
    args = [a for a in args if a != theme]
    app = args[0] if args else DEFAULT_APP
    result = measure(app, theme)
    if "--json" in argv:
        print(json.dumps(result, indent=2))
        return 0
    for key, value in result.items():
        print(f"{key:32} {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
