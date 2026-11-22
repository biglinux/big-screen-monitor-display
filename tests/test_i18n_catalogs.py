"""The translation catalogs (locale/) match the code and are complete."""

import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCALE = os.path.join(ROOT, "locale")
POT = os.path.join(LOCALE, "big-screen-monitor-display.pot")
CATALOGS = sorted(name for name in os.listdir(LOCALE) if name.endswith(".po"))

needs_gettext = pytest.mark.skipif(not shutil.which("xgettext") or not shutil.which("msgfmt"),
                                   reason="gettext tools not installed")


def _msgids(path):
    """Message ids of a .po/.pot file (multi-line strings joined)."""
    text = subprocess.run(["msgcat", "--no-wrap", "--no-location", path], capture_output=True, text=True,
                          check=True).stdout
    return set(re.findall(r'^msgid "(.+)"$', text, re.M))


@needs_gettext
def test_template_matches_the_code(tmp_path):
    """A string marked in the code but missing from the .pot is never translated:
    run tools/update-pot.sh after changing user-visible text."""
    files = sorted(os.path.relpath(os.path.join(base, name), ROOT)
                   for base, _dirs, names in os.walk(os.path.join(ROOT, "usr")) for name in names
                   if name.endswith(".py"))
    fresh = tmp_path / "fresh.pot"
    subprocess.run(["xgettext", "--from-code=UTF-8", "-L", "Python", "-k_", "-kN_", "-kngettext:1,2",
                    "-o", str(fresh), *files], cwd=ROOT, check=True, capture_output=True)
    subprocess.run(["sed", "-i", "s/charset=CHARSET/charset=UTF-8/", str(fresh)], check=True)
    current = _msgids(POT)
    expected = _msgids(str(fresh))
    assert not expected - current, "missing from the .pot; run tools/update-pot.sh"
    assert not current - expected, "no longer in the code; run tools/update-pot.sh"


@needs_gettext
@pytest.mark.parametrize("name", CATALOGS)
def test_catalog_is_valid_and_complete(name):
    path = os.path.join(LOCALE, name)
    result = subprocess.run(["msgfmt", "--check", "--statistics", "-o", os.devnull, path],
                            capture_output=True, text=True, env=dict(os.environ, LC_ALL="C"))
    assert result.returncode == 0, result.stderr
    assert "fuzzy" not in result.stderr and "untranslated" not in result.stderr, result.stderr
    with open(path, encoding="utf-8") as handle:
        header = handle.read(4000)
    assert f'"Language: {name[:-3]}\\n"' in header
    assert re.search(r'"Plural-Forms: nplurals=\d+; plural=[^"]+;\\n"', header)


def test_language_choice_lists_every_catalog():
    from bsmd import i18n, settings
    codes = [code for code, _name in i18n.LANGUAGES]
    assert sorted(codes) == sorted(name[:-3] for name in CATALOGS)
    assert len(set(codes)) == len(codes)
    for code in codes:
        values, problems = settings.validate({"language": code})
        assert values["language"] == code and not problems
