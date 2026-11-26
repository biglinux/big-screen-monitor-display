"""gettext setup shared by the service, the helper and the GUI."""

import gettext
import os
import re

DOMAIN = "big-screen-monitor-display"
_HERE = os.path.dirname(os.path.abspath(__file__))
# Development checkouts compile catalogs into <repository>/locale-build.
_LOCAL_LOCALEDIR = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", "locale-build"))
LOCALEDIR = _LOCAL_LOCALEDIR if os.path.isdir(_LOCAL_LOCALEDIR) else "/usr/share/locale"

# Catalogs shipped in locale/ (code, name in that language), for the language choice.
LANGUAGES = (
    ("pt", "Português (Brasil)"), ("en", "English"), ("bg", "Български"), ("cs", "Čeština"),
    ("da", "Dansk"), ("de", "Deutsch"), ("el", "Ελληνικά"), ("es", "Español"), ("et", "Eesti"),
    ("fi", "Suomi"), ("fr", "Français"), ("he", "עברית"), ("hr", "Hrvatski"), ("hu", "Magyar"),
    ("is", "Íslenska"), ("it", "Italiano"), ("ja", "日本語"), ("ko", "한국어"), ("nb", "Norsk bokmål"),
    ("nl", "Nederlands"), ("pl", "Polski"), ("ro", "Română"), ("ru", "Русский"), ("sk", "Slovenčina"),
    ("sv", "Svenska"), ("tr", "Türkçe"), ("uk", "Українська"), ("zh", "中文（简体）"),
)

_translation = gettext.translation(DOMAIN, LOCALEDIR, fallback=True)
_language = None


def set_language(language):
    """Switch the active catalog. ``auto`` follows LANG/LC_* variables."""
    global _translation, _language
    languages = None if not language or language == "auto" else [language]
    _language = None if languages is None else language
    _translation = gettext.translation(DOMAIN, LOCALEDIR, languages=languages, fallback=True)


def current_language():
    """Language in use: the configured one, or the one taken from the environment."""
    if _language:
        return _language
    info = _translation.info() if hasattr(_translation, "info") else {}
    language = info.get("language") if isinstance(info, dict) else None
    if language:
        return language
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(variable)
        if value:
            return value.split(":")[0].split(".")[0]
    return "en"


_originals = (None, {}, [])
_FIELD = re.compile(r"\{([^{}]*)\}")
_SEPARATORS = ("  ·  ", " · ")


def _index(translation):
    """Exact and formatted (regex) lookups from translations back to the English source."""
    catalog = getattr(translation, "_catalog", None) or {}
    exact, patterns = {}, []
    for key, value in catalog.items():
        source = key[0] if isinstance(key, tuple) else key          # plural: (msgid, index)
        if not source or not isinstance(value, str) or not value:
            continue
        exact.setdefault(value, source)
        names = _FIELD.findall(value)
        if names and sorted(names) == sorted(_FIELD.findall(source)):
            parts = _FIELD.split(value)
            regex = "".join(re.escape(part) if i % 2 == 0 else f"(?P<f{i // 2}>.+?)"
                            for i, part in enumerate(parts))
            patterns.append((re.compile(f"^{regex}$", re.S), names, source))
    return exact, patterns


def original(text):
    """The source (English) text ``text`` was translated from, or ``text``.

    Also undoes a formatted message ("{count} …" with the values filled in) and
    texts joined with " · ", so a display whose font lacks the script can draw
    the English instead (bsmd.fonts)."""
    global _originals
    translation = _translation
    if _originals[0] is not translation:
        _originals = (translation, *_index(translation))
    _, exact, patterns = _originals
    if text in exact:
        return exact[text]
    for regex, names, source in patterns:
        match = regex.match(text)
        if match and not any(sep.strip() in value for value in match.groups() for sep in _SEPARATORS):
            values = {name: match.group(f"f{i}") for i, name in enumerate(names)}
            return _FIELD.sub(lambda m: values.get(m.group(1), m.group(0)), source)  # noqa: B023 - used at once
    for separator in _SEPARATORS:
        if separator in text:
            parts = text.split(separator)
            back = [original(part) for part in parts]
            if back != parts:
                return separator.join(back)
    return text


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, n):
    return _translation.ngettext(singular, plural, n)


def N_(message):
    """Mark a string for extraction without translating it immediately."""
    return message
