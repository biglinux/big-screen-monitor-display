"""tools/soak.py: the leak verdict (the long run itself is the weekly Soak workflow)."""

import importlib.util
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
spec = importlib.util.spec_from_file_location("soak", os.path.join(ROOT, "tools", "soak.py"))
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


def series(rss, fds=10, threads=11, step=60):
    return [(i * step, value, fds, threads) for i, value in enumerate(rss)]


def test_slope_in_units_per_hour():
    assert soak.slope_per_hour([(0, 100), (1800, 101), (3600, 102)]) == 2.0
    assert soak.slope_per_hour([(0, 5), (60, 5)]) == 0.0


def test_warm_up_then_plateau_passes():
    """The measured shape: fast growth while themes load, then flat (10-minute local run)."""
    rss = [104, 149, 167, 175, 177] + [179.2] * 60 + [179.3] * 55
    report = soak.verdict(series(rss), 5.0, 3, 2)
    assert report["ok"] and report["rss_slope_mb_per_hour"] < 1


def test_steady_growth_fails():
    rss = [150 + i * 0.5 for i in range(120)]              # +30 MB/h, never settles
    report = soak.verdict(series(rss), 5.0, 3, 2)
    assert not report["ok"] and "memory grows" in report["problems"][0]


def test_descriptor_and_thread_growth_fail():
    samples = [(i * 60, 150.0, 10 + i, 11 + i) for i in range(20)]
    problems = soak.verdict(samples, 5.0, 3, 2)["problems"]
    assert any("open files" in p for p in problems) and any("threads" in p for p in problems)
