"""gettext setup shared by the service, the helper and the GUI."""

import gettext
import os

DOMAIN = "big-screen-monitor-display"
_HERE = os.path.dirname(os.path.abspath(__file__))
# Development checkouts compile catalogs into <repository>/locale-build.
_LOCAL_LOCALEDIR = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", "locale-build"))
LOCALEDIR = _LOCAL_LOCALEDIR if os.path.isdir(_LOCAL_LOCALEDIR) else "/usr/share/locale"

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


def _(message):
    return _translation.gettext(message)


def ngettext(singular, plural, n):
    return _translation.ngettext(singular, plural, n)


def N_(message):
    """Mark a string for extraction without translating it immediately."""
    return message
