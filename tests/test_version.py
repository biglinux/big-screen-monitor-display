"""Uma só versão: o pacote Python, o app Android e o README dizem a mesma coisa.

O ``tools/release.sh`` faz as mesmas conferências antes de criar a tag; este
teste pega a divergência já no PR, antes de alguém tentar publicar.
"""

import os
import re

from bsmd import __version__

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_android_matches():
    gradle = read("android", "app", "build.gradle.kts")
    name = re.search(r'versionName = "([^"]+)"', gradle).group(1)
    code = int(re.search(r"versionCode = (\d+)", gradle).group(1))
    major, minor, patch = (int(x) for x in __version__.split("."))
    assert name == __version__
    assert code == major * 10000 + minor * 100 + patch     # 5.5.2 -> 50502: sempre crescente


def test_readme_badge_matches():
    assert f"vers%C3%A3o-{__version__}-" in read("README.md")


def test_changelog_has_current_version():
    assert f"## [{__version__}]" in read("CHANGELOG.md")
