"""Generated documentation stays in sync with the code."""

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_compatibility_page_matches_the_registry():
    """docs/compatibilidade.md is generated from bsmd/displays/registry.py:
    run tools/make_compat.py after adding or promoting a driver."""
    result = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_compat.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_aur_package_matches_the_biglinux_one():
    """pkgbuild/aur/ is generated from pkgbuild/PKGBUILD: run tools/make_aur.py after changing it."""
    result = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "make_aur.py"), "--check"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_aur_package_installs_to_the_real_paths():
    with open(os.path.join(ROOT, "pkgbuild", "aur", "PKGBUILD"), encoding="utf-8") as fh:
        text = fh.read()
    package = text[text.index("package() {"):]
    assert "${pkgname}" not in package and "$pkgname" not in package     # would be ...-git
    assert "pkgname=big-screen-monitor-display-git" in text and "conflicts=" in text


def test_documentation_index_links_exist():
    import re
    index = os.path.join(ROOT, "docs", "README.md")
    with open(index, encoding="utf-8") as fh:
        links = re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", fh.read())
    missing = [link for link in links if not link.startswith("http")
               and not os.path.exists(os.path.normpath(os.path.join(ROOT, "docs", link)))]
    assert not missing, missing
