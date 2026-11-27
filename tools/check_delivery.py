#!/usr/bin/env python3
"""Does the BigLinux package repository carry the latest release?

Reads the public pacman databases (biglinux-testing and biglinux-stable), finds
the build date of the package and compares it with the date of the latest
GitHub release. A build older than the release, past a grace period, means the
delivery is stuck (it was, unnoticed, from March to November 2026).

    tools/check_delivery.py                 report; exit 1 when a repository is behind
    tools/check_delivery.py --json          machine-readable report (the workflow uses it)

Grace periods: testing gets the build within TESTING_GRACE of a release; stable
needs a manual promotion by the BigLinux team, so it gets STABLE_GRACE.
"""

import argparse
import datetime
import io
import json
import os
import sys
import tarfile
import urllib.request

PACKAGE = "big-screen-monitor-display"
MIRROR = "https://packages.biglinux.com.br/{repo}/x86_64/{repo}.db"
REPOS = ("biglinux-testing", "biglinux-stable")
RELEASES = "https://api.github.com/repos/{project}/releases?per_page=50"
TESTING_GRACE = datetime.timedelta(days=2)
STABLE_GRACE = datetime.timedelta(days=21)


def read_package(db_bytes, package=PACKAGE):
    """{"version", "builddate"} of ``package`` in a pacman .db (gzip tar), or None."""
    with tarfile.open(fileobj=io.BytesIO(db_bytes), mode="r:*") as db:
        for member in db.getmembers():
            name = member.name.rstrip("/")
            if not name.endswith("/desc"):
                continue
            entry = name[:-len("/desc")]
            # "<name>-<pkgver>-<pkgrel>": the name is everything before the last two dashes
            if entry.rsplit("-", 2)[0] != package:
                continue
            fields, key = {}, None
            for line in db.extractfile(member).read().decode("utf-8", "replace").splitlines():
                if line.startswith("%") and line.endswith("%"):
                    key = line.strip("%")
                elif line and key:
                    fields.setdefault(key, line)
            built = datetime.datetime.fromtimestamp(int(fields["BUILDDATE"]), datetime.timezone.utc)
            return {"version": fields.get("VERSION", "?"), "builddate": built}
    return None


def assess(releases, packages, now):
    """Report per repository: ok / waiting / behind / missing.

    ``releases`` is [(tag, published datetime)], newest first. A repository is behind
    when the oldest release it does not carry yet (published after its build) is
    older than the grace period: the delay counts from the first missed release.
    """
    latest_tag, latest_date = releases[0]
    report = {"release": latest_tag, "release_date": latest_date.isoformat(), "repos": {}, "ok": True}
    for repo in REPOS:
        grace = TESTING_GRACE if repo.endswith("testing") else STABLE_GRACE
        package = packages.get(repo)
        missed = [] if package is None else [(t, d) for t, d in releases if d > package["builddate"]]
        if package is None:
            state, detail = "missing", "package not in the repository"
        elif not missed:
            state, detail = "ok", f"carries {latest_tag}"
        else:
            first_tag, first_date = missed[-1]
            if now - first_date <= grace:
                state, detail = "waiting", f"{first_tag} is younger than the {grace.days}-day grace period"
            else:
                state = "behind"
                detail = (f"built {package['builddate']:%Y-%m-%d}; missing {len(missed)} release(s) "
                          f"since {first_tag} ({first_date:%Y-%m-%d}, {(now - first_date).days} days)")
        report["repos"][repo] = {"state": state, "detail": detail,
                                 "version": package and package["version"],
                                 "builddate": package and package["builddate"].isoformat()}
        # stable missing is expected when only testing gets builds; testing missing is not
        if state == "behind" or (state == "missing" and repo.endswith("testing")):
            report["ok"] = False
    return report


def fetch(url, token=None):
    request = urllib.request.Request(url, headers={"User-Agent": "bsmd-delivery-check"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", default=os.environ.get("GITHUB_REPOSITORY", "ruscher/big-screen-monitor-display"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    listing = json.loads(fetch(RELEASES.format(project=args.project), os.environ.get("GITHUB_TOKEN")))
    releases = sorted(((r["tag_name"], datetime.datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")))
                       for r in listing if not r.get("draft") and not r.get("prerelease") and r.get("published_at")),
                      key=lambda item: item[1], reverse=True)
    packages = {repo: read_package(fetch(MIRROR.format(repo=repo))) for repo in REPOS}
    report = assess(releases, packages, datetime.datetime.now(datetime.timezone.utc))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"latest release: {report['release']} ({report['release_date'][:10]})")
        for repo, item in report["repos"].items():
            print(f"  {repo:18} {item['state']:8} {item['version'] or '-':16} {item['detail']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
