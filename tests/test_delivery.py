"""tools/check_delivery.py: is the BigLinux package repository behind the releases?"""

import datetime
import importlib.util
import io
import os
import tarfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
spec = importlib.util.spec_from_file_location("check_delivery", os.path.join(ROOT, "tools", "check_delivery.py"))
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

UTC = datetime.timezone.utc


def day(text):
    return datetime.datetime.fromisoformat(text).replace(tzinfo=UTC)


def db(*packages):
    """A pacman .db (gzip tar) with one <name>-<ver>-<rel>/desc per package."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, version, built in packages:
            desc = f"%NAME%\n{name}\n\n%VERSION%\n{version}\n\n%BUILDDATE%\n{int(built.timestamp())}\n".encode()
            info = tarfile.TarInfo(f"{name}-{version}/desc")
            info.size = len(desc)
            tar.addfile(info, io.BytesIO(desc))
    return buffer.getvalue()


def test_reads_the_package_and_ignores_similar_names():
    data = db(("big-screen-monitor-display-git", "5.6.1.r3-1", day("2026-11-20")),
              ("big-screen-monitor-display", "26.03.28-1921", day("2026-03-28")))
    package = check.read_package(data)
    assert package == {"version": "26.03.28-1921", "builddate": day("2026-03-28")}
    assert check.read_package(db(("other", "1-1", day("2026-01-01")))) is None


RELEASES = [("v5.6.0", day("2026-11-26")), ("v5.5.2", day("2026-11-26")), ("v5.5.1", day("2026-11-22"))]


def test_behind_counts_from_the_first_missed_release():
    old = {"version": "26.03.28-1921", "builddate": day("2026-03-28")}
    report = check.assess(RELEASES, {"biglinux-testing": old, "biglinux-stable": old}, day("2026-12-30"))
    assert report["repos"]["biglinux-testing"]["state"] == "behind"
    assert "since v5.5.1" in report["repos"]["biglinux-stable"]["detail"] and not report["ok"]


def test_grace_periods_and_up_to_date():
    fresh = {"version": "26.11.27-0900", "builddate": day("2026-11-27")}
    old = {"version": "26.03.28-1921", "builddate": day("2026-03-28")}
    report = check.assess(RELEASES, {"biglinux-testing": fresh, "biglinux-stable": old}, day("2026-11-28"))
    assert report["repos"]["biglinux-testing"]["state"] == "ok"
    assert report["repos"]["biglinux-stable"]["state"] == "waiting"      # promotion to stable takes time
    assert report["ok"]


def test_missing_from_testing_is_an_alarm():
    report = check.assess(RELEASES, {"biglinux-testing": None, "biglinux-stable": None}, day("2026-11-27"))
    assert report["repos"]["biglinux-testing"]["state"] == "missing" and not report["ok"]
