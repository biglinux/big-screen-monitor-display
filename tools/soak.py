#!/usr/bin/env python3
"""Long-run test: does the service leak memory, file descriptors or threads?

Runs the real service (main.py --simulate) against simulated panels, switches
the theme through the settings file every ``--per-theme`` seconds (live
reload, as the window does), samples /proc every ``--every`` seconds and fits a
line through the second half of each measurement (the first half is warm-up:
caches, fonts, theme assets).

    tools/soak.py --minutes 120                       # the weekly CI run
    tools/soak.py --minutes 3 --per-theme 30          # quick local check

Exit 1 when memory grows faster than --max-mb-per-hour, or descriptors or
threads keep growing. A JSON report is written to --report.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
APP = os.path.join(ROOT, "usr", "share", "big-screen-monitor-display")
THEMES = ["standard", "gkrellm", "planet", "old_computer", "brother_away", "kojiro", "big_media_player"]


def proc_sample(pid):
    """(rss MB, open fds, threads) of a running process, from /proc."""
    with open(f"/proc/{pid}/status", encoding="utf-8") as fh:
        status = dict(line.split(":", 1) for line in fh if ":" in line)
    rss = int(status["VmRSS"].split()[0]) / 1024
    threads = int(status["Threads"])
    fds = len(os.listdir(f"/proc/{pid}/fd"))
    return rss, fds, threads


def slope_per_hour(points):
    """Least-squares slope of [(seconds, value)] in units per hour (0 with < 3 points)."""
    if len(points) < 3:
        return 0.0
    n = len(points)
    mean_t = sum(t for t, _ in points) / n
    mean_v = sum(v for _, v in points) / n
    var = sum((t - mean_t) ** 2 for t, _ in points)
    if not var:
        return 0.0
    return sum((t - mean_t) * (v - mean_v) for t, v in points) / var * 3600


def verdict(samples, max_mb_per_hour, max_fd_growth, max_thread_growth):
    """Report from [(seconds, rss, fds, threads)]; the second half is judged."""
    half = samples[len(samples) // 2:]
    rss_slope = slope_per_hour([(t, r) for t, r, _f, _th in half])
    fd_growth = half[-1][2] - half[0][2] if half else 0
    thread_growth = half[-1][3] - half[0][3] if half else 0
    problems = []
    if rss_slope > max_mb_per_hour:
        problems.append(f"memory grows {rss_slope:.1f} MB/h (limit {max_mb_per_hour})")
    if fd_growth > max_fd_growth:
        problems.append(f"open files grew by {fd_growth} (limit {max_fd_growth})")
    if thread_growth > max_thread_growth:
        problems.append(f"threads grew by {thread_growth} (limit {max_thread_growth})")
    return {"samples": len(samples), "rss_start_mb": round(samples[0][1], 1) if samples else None,
            "rss_end_mb": round(samples[-1][1], 1) if samples else None,
            "rss_peak_mb": round(max(s[1] for s in samples), 1) if samples else None,
            "rss_slope_mb_per_hour": round(rss_slope, 2), "fd_growth": fd_growth,
            "thread_growth": thread_growth, "problems": problems, "ok": not problems}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--minutes", type=float, default=120)
    parser.add_argument("--per-theme", type=float, default=300, help="seconds on each theme")
    parser.add_argument("--every", type=float, default=10, help="seconds between samples")
    parser.add_argument("--panels", default="800x480,480x320")
    parser.add_argument("--max-mb-per-hour", type=float, default=5.0)
    parser.add_argument("--max-fd-growth", type=int, default=3)
    parser.add_argument("--max-thread-growth", type=int, default=2)
    parser.add_argument("--report", default="soak-report.json")
    args = parser.parse_args(argv)

    sys.path.insert(0, APP)
    from bsmd import settings

    work = tempfile.mkdtemp(prefix="bsmd-soak-")
    config = os.path.join(work, "settings.json")
    settings.save(dict(settings.defaults(), theme=THEMES[0]), config)
    env = dict(os.environ, BSM_CONFIG=config, BSM_STATUS=os.path.join(work, "status.json"),
               XDG_RUNTIME_DIR=work, XDG_STATE_HOME=os.path.join(work, "state"), PYTHONUNBUFFERED="1")
    env.pop("NOTIFY_SOCKET", None)
    log = open(os.path.join(work, "service.log"), "w", encoding="utf-8")
    service = subprocess.Popen([sys.executable, os.path.join(APP, "main.py"), "--simulate", args.panels],
                               env=env, stdout=log, stderr=subprocess.STDOUT)
    samples, start, theme_at, index, exited_early = [], time.monotonic(), time.monotonic(), 0, None
    try:
        while time.monotonic() - start < args.minutes * 60:
            time.sleep(args.every)
            if service.poll() is not None:
                exited_early = service.returncode
                break
            now = time.monotonic()
            if now - theme_at >= args.per_theme:
                index = (index + 1) % len(THEMES)
                settings.save(dict(settings.defaults(), theme=THEMES[index]), config)
                theme_at = now
            samples.append((now - start, *proc_sample(service.pid)))
    finally:
        service.send_signal(signal.SIGTERM)
        try:
            service.wait(timeout=20)
        except subprocess.TimeoutExpired:
            service.kill()
        log.close()

    report = verdict(samples, args.max_mb_per_hour, args.max_fd_growth, args.max_thread_growth)
    if exited_early is not None:
        report["problems"].append(f"the service exited early with code {exited_early}")
        report["ok"] = False
    report.update(minutes=args.minutes, themes=THEMES, panels=args.panels, log=os.path.join(work, "service.log"))
    with open(args.report, "w", encoding="utf-8") as fh:
        json.dump({**report, "series": [[round(t), round(r, 1), f, th] for t, r, f, th in samples]}, fh, indent=1)
    print(json.dumps({k: v for k, v in report.items() if k != "series"}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
