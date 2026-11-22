"""Fonts for the pictures sent to the displays, with a fallback for missing glyphs.

Themes draw with Pillow and the bundled fonts (DejaVu, theme pixel fonts), which
have no Chinese, Japanese or Korean glyphs and, for some theme fonts, no Cyrillic
or Greek either. Pillow has no font fallback: a translated caption would be
drawn as boxes. :func:`truetype` returns a font that, for a text with a glyph it
lacks, measures and draws the whole text with a system font that has them all
(``fc-match``); when the system has none, the untranslated (English) text is
drawn instead, never boxes.
"""

import functools
import logging
import os
import subprocess
import threading

from PIL import ImageFont

from . import i18n

log = logging.getLogger("bsmd")

_ORIGINAL_TRUETYPE = ImageFont.truetype
_NOTDEF = "\U0010FFFD"                    # a private-use code point no font draws
_LOCK = threading.Lock()


def _mask_key(font, text):
    mask = font.getmask(text)
    return mask.size, bytes(mask)


@functools.lru_cache(maxsize=64)
def _system_font_for(chars, bold):
    """A system font file that draws every character of ``chars`` (a sorted str)."""
    charset = " ".join(f"{ord(char):x}" for char in chars[:64])
    pattern = f"sans-serif:charset={charset}" + (":weight=bold" if bold else "")
    try:
        result = subprocess.run(["fc-match", "-s", "-f", "%{file}\n", pattern], capture_output=True, text=True,
                                timeout=2, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    for path in result.stdout.splitlines()[:8]:
        path = path.strip()
        if not path.lower().endswith((".ttf", ".otf", ".ttc")) or not os.path.exists(path):
            continue
        try:
            probe = _ORIGINAL_TRUETYPE(path, 16)
        except OSError:
            continue
        if not _missing(probe, chars):
            return path
    return None


def _missing(font, chars):
    notdef = _mask_key(font, _NOTDEF)
    return [char for char in chars if _mask_key(font, char) == notdef]


class FallbackFont(ImageFont.FreeTypeFont):
    """A FreeTypeFont that hands texts it cannot draw to another font."""

    MAX_CACHE = 512

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drawable = {}               # char -> bool
        self._choice = {}                 # text -> (font, text)
        self._fallbacks = {}              # path -> FreeTypeFont
        self._plain = None                # same face without the overrides, to probe glyphs

    def _resolve(self, text):
        if not isinstance(text, str) or text.isascii():
            return self, text
        with _LOCK:
            choice = self._choice.get(text)
        if choice is not None:
            return choice
        chars = sorted(set(text) - set(" \n\t"))
        unknown = [char for char in chars if char not in self._drawable]
        if unknown:
            if self._plain is None:
                self._plain = ImageFont.FreeTypeFont(self.path, self.size, self.index, self.encoding)
            missing = set(_missing(self._plain, "".join(unknown)))
            for char in unknown:
                self._drawable[char] = char not in missing
        choice = (self, text)
        absent = "".join(char for char in chars if not self._drawable[char])
        if absent:
            path = _system_font_for("".join(chars), "bold" in (self.font.style or "").lower())
            if path:
                fallback = self._fallbacks.get(path)
                if fallback is None:
                    fallback = self._fallbacks[path] = _ORIGINAL_TRUETYPE(path, self.size)
                choice = (fallback, text)
            else:
                original = i18n.original(text)
                if original != text:
                    choice = self._resolve(original)
                else:
                    log.debug("fonts: no font draws %r", absent)
        with _LOCK:
            if len(self._choice) >= self.MAX_CACHE:
                self._choice.clear()
            self._choice[text] = choice
        return choice

    def getmetrics(self):
        """Ascent and descent covering this face and every fallback it has used."""
        ascent, descent = super().getmetrics()
        for fallback in list(self._fallbacks.values()):
            other = fallback.getmetrics()
            ascent, descent = max(ascent, other[0]), max(descent, other[1])
        return ascent, descent

    # Pillow measures and draws through these; each one asks the font that
    # will really draw the text.
    def getmask(self, text, *args, **kwargs):
        font, text = self._resolve(text)
        return super().getmask(text, *args, **kwargs) if font is self else font.getmask(text, *args, **kwargs)

    def getmask2(self, text, *args, **kwargs):
        font, text = self._resolve(text)
        return super().getmask2(text, *args, **kwargs) if font is self else font.getmask2(text, *args, **kwargs)

    def getbbox(self, text, *args, **kwargs):
        font, text = self._resolve(text)
        return super().getbbox(text, *args, **kwargs) if font is self else font.getbbox(text, *args, **kwargs)

    def getlength(self, text, *args, **kwargs):
        font, text = self._resolve(text)
        return super().getlength(text, *args, **kwargs) if font is self else font.getlength(text, *args, **kwargs)


def truetype(path, size, **kwargs):
    """``ImageFont.truetype`` for the display pictures (see the module docstring)."""
    return FallbackFont(path, size, **kwargs)
