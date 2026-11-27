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
    assert report["ok"] and not report["inconclusive"] and report["rss_slope_mb_per_hour"] < 1


def test_steady_growth_fails():
    rss = [150 + i * 0.5 for i in range(120)]              # +30 MB/h, never settles
    report = soak.verdict(series(rss), 5.0, 3, 2)
    assert not report["ok"] and "memory grows" in report["problems"][0]


def test_descriptor_and_thread_growth_fail():
    samples = [(i * 60, 150.0, 10 + i, 11 + i) for i in range(20)]
    problems = soak.verdict(samples, 5.0, 3, 2)["problems"]
    assert any("open files" in p for p in problems) and any("threads" in p for p in problems)


def test_a_run_shorter_than_one_theme_cycle_is_inconclusive():
    """The first CI run (12 min, 5 min per theme) only met 3 of the 7 themes: each
    first load looked like growth. Before a full cycle nothing is judged."""
    rss = [77.5 + i for i in range(48)]                     # new themes still loading
    report = soak.verdict(series(rss, step=15), 5.0, 3, 2, warm_up=7 * 300)
    assert report["inconclusive"] and report["ok"] and not report["problems"]


def test_after_the_warm_up_the_plateau_is_judged():
    warm = [100 + i * 2 for i in range(35)]                 # 35 min loading the themes
    rss = warm + [170.0] * 85                               # then flat for 85 min
    report = soak.verdict(series(rss), 5.0, 3, 2, warm_up=35 * 60)
    assert report["ok"] and not report["inconclusive"] and report["judged_from_s"] >= 35 * 60
