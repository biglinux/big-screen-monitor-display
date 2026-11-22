"""bsmd.fonts: display pictures never show boxes for a translated text."""

import os

import pytest
from PIL import Image, ImageDraw

from bsmd import fonts, i18n, themes

DEJAVU = os.path.join(themes.FONT_DIR, "DejaVuSans.ttf")


@pytest.fixture(autouse=True)
def _fresh():
    fonts._system_font_for.cache_clear()
    yield
    fonts._system_font_for.cache_clear()


def test_text_the_font_draws_stays_with_it():
    font = fonts.truetype(DEJAVU, 14)
    for text in ("CPU 42%", "Ação", "Память", "Μνήμη", "זיכרון"):
        assert font._resolve(text)[0] is font


def test_missing_glyphs_use_a_system_font_with_all_of_them(monkeypatch):
    asked = []
    monkeypatch.setattr(fonts, "_system_font_for", lambda chars, bold: asked.append(chars) or DEJAVU)
    font = fonts.truetype(DEJAVU, 14)
    chosen, text = font._resolve("CPU 使用率")
    assert chosen is not font and text == "CPU 使用率" and chosen.size == 14
    assert asked == ["".join(sorted(set("CPU使用率")))]
    assert font._resolve("CPU 使用率")[0] is chosen and len(asked) == 1     # cached


def test_without_any_font_the_english_text_is_drawn(monkeypatch):
    monkeypatch.setattr(fonts, "_system_font_for", lambda chars, bold: None)
    monkeypatch.setattr(i18n, "original", lambda text: {"内存": "MEMORY"}.get(text, text))
    font = fonts.truetype(DEJAVU, 14)
    chosen, text = font._resolve("内存")
    assert chosen is font and text == "MEMORY"
    assert font.getlength("内存") == font.getlength("MEMORY")
    image = Image.new("L", (80, 20))
    ImageDraw.Draw(image).text((0, 0), "内存", font=font, fill=255)
    reference = Image.new("L", (80, 20))
    ImageDraw.Draw(reference).text((0, 0), "MEMORY", font=font, fill=255)
    assert image.tobytes() == reference.tobytes()


def test_cjk_is_drawn_with_a_system_font_when_installed():
    path = fonts._system_font_for("使用", False)
    if path is None:
        pytest.skip("no CJK font installed")
    font = fonts.truetype(DEJAVU, 14)
    chosen, _text = font._resolve("使用率")
    assert chosen is not font and not fonts._missing(chosen, "使用率")


def test_original_maps_a_translation_back(monkeypatch):
    class Catalog:
        _catalog = {"": "header", "MEMORY": "ПАМЯТЬ", ("{count} display", 0): "x"}
    monkeypatch.setattr(i18n, "_translation", Catalog())
    assert i18n.original("ПАМЯТЬ") == "MEMORY"
    assert i18n.original("other") == "other"
