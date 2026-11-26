#!/usr/bin/env python3
"""Android display benchmark on this computer: the real runtime, hub and TLS, with the
reference client of the tests standing in for the phone (loopback).

    python3 tools/android-bench.py [seconds per theme] [WxH] [quality]

Prints, per theme: frames shown, fps, kB per frame, transfer ms, process CPU % and RSS.
"""
import os
import resource
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tests"), os.path.join(ROOT, "usr", "share", "big-screen-monitor-display")]

import psutil  # noqa: E402

from android_client import Client, free_port_pair  # noqa: E402
from bsmd import health, runtime, settings  # noqa: E402
from bsmd.displays.android import protocol as bsdp  # noqa: E402
from bsmd.displays.android.hub import AndroidHub  # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 15
VIEW = tuple(int(v) for v in (sys.argv[2] if len(sys.argv) > 2 else "1600x720").split("x"))
QUALITY = sys.argv[3] if len(sys.argv) > 3 else "auto"
THEMES = ("standard", "gkrellm", "planet", "old_computer", "brother_away", "kojiro", "big_media_player")


def main():
    tmp = tempfile.mkdtemp(prefix="bsmd-bench-")
    hub = AndroidHub(os.path.join(tmp, "state"), host_name="Bench", usb=False)
    port = free_port_pair()
    hub.listen(port, host="127.0.0.1")
    config = os.path.join(tmp, "settings.json")
    settings.save({"theme": "standard", "android_port": port,
                   "performance_profile": os.environ.get("BENCH_PROFILE", "fluid")}, config)
    app = runtime.Runtime(settings.SettingsStore(config), status_file=os.path.join(tmp, "run", "status.json"),
                          state_directory=os.path.join(tmp, "state"), scan=lambda: [], android=hub)
    threading.Thread(target=app.run, daemon=True).start()
    import secrets
    ticket, secret = secrets.token_hex(8), bsdp.b64e(secrets.token_bytes(16))
    hub.open_pairing(ticket, secret, 60)
    client = Client(port, view=VIEW)
    assert client.login(ticket, secret), client.reject
    display = client.welcome["display_id"]
    deadline = time.time() + 20
    while display not in app.sessions or app.sessions[display].driver is None:
        if time.time() > deadline:
            raise SystemExit("session did not start")
        time.sleep(0.1)
    session = app.sessions[display]
    proc = psutil.Process()
    print(f"view {VIEW[0]}x{VIEW[1]} -> drawing {session.driver.native_size[0]}x{session.driver.native_size[1]}, "
          f"quality {QUALITY}, profile {os.environ.get('BENCH_PROFILE', 'fluid')}, "
          f"{SECONDS:.0f} s per theme (loopback, TLS)")
    print(f"{'theme':18} {'frames':>6} {'fps':>5} {'kB/frame':>9} {'kB/s':>7} {'xfer ms':>8} {'cpu %':>6} "
          f"{'rss MB':>7} formats")
    for theme in THEMES:
        data = settings.read_file(config)[0]
        data.update(theme=theme, displays={display: {"android_quality": QUALITY}} if QUALITY != "auto" else {})
        settings.save(data, config)
        time.sleep(3)                                  # theme switch and first frames
        frames0, bytes0 = client.frames, session.stats["bytes_sent"]
        session.driver.stats["formats"].clear()
        cpu0 = proc.cpu_times()
        t0 = time.time()
        time.sleep(SECONDS)
        elapsed = time.time() - t0
        cpu1 = proc.cpu_times()
        frames = client.frames - frames0
        sent = session.stats["bytes_sent"] - bytes0
        cpu = ((cpu1.user - cpu0.user) + (cpu1.system - cpu0.system)) / elapsed * 100
        formats = ", ".join(f"{k} {v}" for k, v in session.driver.stats["formats"].most_common())
        print(f"{theme:18} {frames:6d} {frames / elapsed:5.1f} {sent / max(frames, 1) / 1024:9.1f} "
              f"{sent / elapsed / 1024:7.1f} {session.stats['transfer_ms']:8.1f} {cpu:6.1f} "
              f"{proc.memory_info().rss / 1048576:7.1f} {formats}")
    assert session.link.state == health.HEALTHY
    client.close()
    app.stop()
    print(f"peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024:.0f} MB "
          "(includes the reference client in the same process)")


if __name__ == "__main__":
    main()
