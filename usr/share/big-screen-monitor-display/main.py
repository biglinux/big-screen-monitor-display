#!/usr/bin/env python3
"""Big Screen Monitor Display - entry point.

    main.py [--service]              run the monitor (systemd uses --service)
    main.py --simulate 480x320       run against an in-memory panel
    main.py --render THEME --size 480x320 --out frame.png [--orientation vertical]
    main.py --diagnose               human readable health report
    main.py --status                 print the service status JSON
    main.py --media-agent            Big Media Player session agent (XDG autostart)
    main.py --media ACTION [--value N]   control the player shown on the display
                                     (play_pause, next, previous, volume_up, mute...)
"""

import argparse
import io
import json
import logging
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    # ``python3 -I`` (used by the unit) does not add the script directory.
    sys.path.insert(0, BASE_DIR)



def _media_entry(argv):
    """Session-side media commands start without the display pipeline (drivers, NumPy,
    renderers): the agent lives all session long and should stay small."""
    if not argv or argv[0] not in ("--media-agent", "--media"):
        return None
    import argparse as _argparse
    parser = _argparse.ArgumentParser(prog="main.py")
    parser.add_argument("--media-agent", action="store_true")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--media", metavar="ACTION")
    parser.add_argument("--value", type=float, default=0.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s")
    from bsmd.media import agent
    if args.media_agent:
        return agent.run_agent(keep=args.keep)
    return agent.run_command(args.media, args.value)


if __name__ == "__main__":
    _code = _media_entry(sys.argv[1:])
    if _code is not None:
        sys.exit(_code)

from bsmd import __version__, drivers, i18n, runtime, settings, telemetry, themes  # noqa: E402
from bsmd.sdnotify import Notifier  # noqa: E402

# Compatibility with scripts that imported the 3.x module.
from bsmd.legacy_themes import get_theme_colors  # noqa: E402,F401
from bsmd.telemetry import SYSTEM_STATS  # noqa: E402,F401

log = logging.getLogger("bsmd")


class JournalFormatter(logging.Formatter):
    """Prefix lines with <priority> so journald keeps the log level."""

    PRIORITY = {logging.DEBUG: 7, logging.INFO: 6, logging.WARNING: 4, logging.ERROR: 3,
                logging.CRITICAL: 2}

    def format(self, record):
        return f"<{self.PRIORITY.get(record.levelno, 6)}>{super().format(record)}"


def setup_logging(verbose=False):
    handler = logging.StreamHandler(sys.stderr)
    if os.environ.get("JOURNAL_STREAM"):
        handler.setFormatter(JournalFormatter("%(threadName)s: %(message)s"))
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def get_settings():
    """3.x compatible helper."""
    return settings.load()


def render_dashboard(width, height, settings_):
    """3.x compatible helper: render one frame of the configured theme."""
    theme = themes.create(settings_.get("theme"), runtime.RenderContext(preview=True))
    return theme.render(width, height, settings_, runtime.RenderContext(preview=True))


def parse_size(text):
    width, height = (int(part) for part in text.lower().split("x"))
    return width, height


def parse_simulate(text, latency_ms=0.0, throughput=None):
    """``320x240``, ``480x320,80x160`` or ``480x480:round`` -> simulated panels."""
    panels = []
    for item in text.split(","):
        size, _, shape = item.strip().partition(":")
        panels.append(drivers.SimulatedDisplay(parse_size(size), shape=shape or "rect", latency=latency_ms / 1000,
                                               throughput=throughput,
                                               model=f"Simulated panel {size}" + (f" ({shape})" if shape else "")))
    return panels


def run_tray_icon():
    """Optional tray icon for manual runs inside a desktop session (returned so it can be stopped)."""
    if os.getuid() == 0 or not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return None
    try:
        import pystray
        from PIL import Image
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    try:
        icon_path = "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg"
        icon_img = Image.new("RGB", (64, 64), (0, 120, 215))
        if os.path.exists(icon_path):
            result = subprocess.run(["rsvg-convert", "-w", "64", "-h", "64", icon_path],
                                    capture_output=True, timeout=5, check=False)
            if result.returncode == 0:
                icon_img = Image.open(io.BytesIO(result.stdout))

        def open_config(_icon, _item):
            subprocess.Popen([sys.executable, os.path.join(BASE_DIR, "config_gui.py")])

        def exit_app(icon, _item):
            icon.stop()
            os.kill(os.getpid(), 15)

        menu = pystray.Menu(pystray.MenuItem(i18n._("Settings"), open_config),
                            pystray.MenuItem(i18n._("Quit"), exit_app))
        icon = pystray.Icon("BigScreenMonitor", icon_img, "Big Screen Monitor", menu)
        icon.run_detached()
        return icon
    except Exception:  # noqa: BLE001
        log.debug("tray icon unavailable", exc_info=True)
        return None


def cmd_render(args):
    current = settings.load()
    current["theme"] = args.render
    if args.orientation:
        current["orientation"] = args.orientation
    for item in args.set or []:
        key, _, value = item.partition("=")
        current[key] = json.loads(value) if value[:1] in "0123456789tf[{\"-" else value
    current, problems = settings.validate(current)
    for problem in problems:
        print(f"warning: {problem}", file=sys.stderr)
    width, height = parse_size(args.size)
    if str(current["orientation"]).startswith("vertical") and width > height:
        width, height = height, width
    collector = telemetry.Collector()
    collector.prime()
    collector._sample_processes()        # per-process CPU needs two samples
    time.sleep(0.5)
    collector.sample_once()
    collector._sample_processes()
    collector._sample_sensor_list()
    ctx = runtime.RenderContext(preview=True)
    theme = themes.create(current["theme"], ctx)
    if args.at is not None and hasattr(theme, "debug_seek"):
        theme.debug_seek(args.at, args.scene, args.hour, args.weather, args.speech)
    image = None
    frame_count = max(1, args.frames or 1)
    for _ in range(frame_count):
        image = theme.render(width, height, current, ctx)
        if frame_count > 1:
            time.sleep(theme.frame_interval(current, ctx))
    image.save(args.out)
    print(args.out)
    return 0


def cmd_status(_args):
    status = runtime.read_status()
    if status is None:
        print(i18n._("No status file found: the service is not running."), file=sys.stderr)
        return 1
    print(json.dumps(status, indent=2, ensure_ascii=False))
    return 0


def cmd_list_displays(args):
    from bsmd.displays import discovery
    devices = discovery.scan_usb()
    found = discovery.discover(devices) + discovery.unknown_serial_devices(devices)
    if args.json:
        print(json.dumps([candidate.describe() for candidate in found], indent=2, ensure_ascii=False))
        return 0
    if not found:
        print(i18n._("No display or serial USB device found."))
        return 1
    for candidate in found:
        info = candidate.describe()
        best = candidate.best
        family = best.profile.name if best else i18n._("unknown serial device")
        print(f"{info['id']:<18} {info['ids']}  {info['confidence']:<10} {family}")
        details = [f"serial={info['serial']}" if info["serial"] else "", f"port={info['port']}" if info["port"] else "",
                   info["product"] or "", "asleep" if info["asleep"] else ""]
        print(" " * 19 + "  ".join(filter(None, details)))
        for match in info["matches"][1:]:
            print(" " * 19 + i18n._("also possible: {name} ({confidence})").format(**match))
    return 0


def cmd_benchmark(args):
    from bsmd import benchmark
    report = benchmark.run(sizes=args.bench_sizes, themes_=args.bench_themes, frames=args.frames or 6)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(benchmark.format_report(report))
    return 0


def cmd_diagnose(_args):
    from bsmd import diagnostics
    report = diagnostics.run_checks()
    print(diagnostics.format_report(report))
    return 0 if all(check["ok"] for check in report["checks"] if check["severity"] != "info") else 1


def cmd_run(args):
    setup_logging(args.verbose)
    store = settings.SettingsStore()
    current = store.get()
    i18n.set_language(current.get("language"))
    for problem in store.problems:
        log.warning("settings: %s", problem)
    simulate = None
    if args.simulate:
        simulate = parse_simulate(args.simulate, args.simulate_latency, args.simulate_throughput)
    log.info("Big Screen Monitor Display %s starting (theme=%s orientation=%s model=%s config=%s)",
             __version__, current["theme"], current["orientation"], current["model"], store.path)
    notifier = Notifier()
    app = runtime.Runtime(store, notifier=notifier, simulate=simulate, service=args.service)
    app.install_signal_handlers()
    tray = None if args.service else run_tray_icon()
    if simulate is not None and args.snapshot:
        import threading

        def snapshot_path(index):
            if index == 0:
                return args.snapshot
            root, ext = os.path.splitext(args.snapshot)
            return f"{root}-{index}{ext or '.png'}"

        def snapshot_loop():
            while not app.stop_event.wait(1.0):
                for index, panel in enumerate(simulate):
                    if panel.last_image is not None:
                        panel.last_image.save(snapshot_path(index))
        threading.Thread(target=snapshot_loop, daemon=True).start()
    code = app.run()
    log.info("stopped (exit code %d)", code)
    if tray is not None:
        # pystray's backend threads are not daemons (and stop() waits on
        # them): without this a manual run kept running after SIGTERM/Ctrl+C.
        logging.shutdown()
        os._exit(code)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description="Big Screen Monitor Display")
    parser.add_argument("--service", action="store_true", help="running under systemd")
    parser.add_argument("--simulate", metavar="WxH[,WxH...]",
                        help="use in-memory panels (WxH:round for a round one)")
    parser.add_argument("--simulate-latency", type=float, default=0.0, metavar="MS",
                        help="with --simulate: latency of every transfer")
    parser.add_argument("--simulate-throughput", type=float, default=None, metavar="BYTES_PER_S",
                        help="with --simulate: link throughput (e.g. 1000000 for a serial panel)")
    parser.add_argument("--snapshot", metavar="PNG", help="with --simulate: save the last frame")
    parser.add_argument("--render", metavar="THEME", help="render one frame to --out and exit")
    parser.add_argument("--size", default="480x320")
    parser.add_argument("--orientation", choices=settings.ORIENTATIONS)
    parser.add_argument("--out", default="frame.png")
    parser.add_argument("--frames", type=int, default=None, help="with --render/--benchmark: frames to render")
    parser.add_argument("--at", type=float, help="with --render: seconds into the scene (Brother Away)")
    parser.add_argument("--scene", help="with --render: story id to preview (Brother Away)")
    parser.add_argument("--speech", help="with --render: advance until the character says this text")
    parser.add_argument("--hour", type=float, help="with --render: fixed hour of day (Brother Away)")
    parser.add_argument("--weather", help="with --render: clear, windy, rain, storm, fog, rainbow")
    parser.add_argument("--set", action="append", metavar="KEY=VALUE", help="with --render: override a setting")
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--list-displays", action="store_true", help="show detected panels (read-only)")
    parser.add_argument("--benchmark", action="store_true", help="measure rendering and encoding costs")
    parser.add_argument("--bench-sizes", nargs="*", metavar="WxH", help="with --benchmark: resolutions")
    parser.add_argument("--bench-themes", nargs="*", metavar="THEME", help="with --benchmark: themes")
    parser.add_argument("--json", action="store_true", help="with --list-displays/--benchmark: JSON output")
    parser.add_argument("--sound-agent", action="store_true", help="play optional sounds in the user session")
    parser.add_argument("--media-agent", action="store_true",
                        help="Big Media Player agent for the desktop session (MPRIS, volume, album art)")
    parser.add_argument("--keep", action="store_true", help="with --media-agent: run even if the theme is unused")
    parser.add_argument("--media", metavar="ACTION", help="control media: play_pause, next, previous, stop, "
                        "volume_up, volume_down, mute, volume_set, seek_by, shuffle, loop")
    parser.add_argument("--value", type=float, default=0.0, help="with --media: percent or microseconds")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if args.render:
        return cmd_render(args)
    if args.status:
        return cmd_status(args)
    if args.diagnose:
        return cmd_diagnose(args)
    if args.list_displays:
        return cmd_list_displays(args)
    if args.benchmark:
        return cmd_benchmark(args)
    if args.media_agent:
        setup_logging(args.verbose)
        from bsmd.media import agent
        return agent.run_agent(keep=args.keep)
    if args.media:
        from bsmd.media import agent
        return agent.run_command(args.media, args.value)
    if args.sound_agent:
        from bsmd import sound
        return sound.run_agent()
    return cmd_run(args)


if __name__ == "__main__":
    sys.exit(main())
