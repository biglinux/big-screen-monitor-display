"""Every theme at every panel size the supported families use."""

import pytest
from PIL import Image

from bsmd import compact, settings, telemetry, themes
from bsmd.brother_away import overlay
from bsmd.runtime import RenderContext

# Landscape native sizes of the families in bsmd.displays.registry (+ extremes).
SIZES = [(160, 80), (480, 320), (480, 480), (800, 480), (1024, 600), (1920, 480), (1280, 720), (1920, 462),
         (1280, 800), (1920, 720)]


@pytest.fixture(scope="module", autouse=True)
def stats():
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()


@pytest.mark.parametrize("theme_id", settings.THEME_IDS)
@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("portrait", [False, True])
def test_theme_renders_at_panel_size(theme_id, size, portrait):
    width, height = (size[1], size[0]) if portrait else size
    ctx = RenderContext(preview=True)
    theme = themes.create(theme_id, ctx)
    image = themes.render_for_panel(theme, width, height, dict(settings.defaults(), theme=theme_id), ctx)
    assert image.size == (width, height)
    assert len(image.resize((32, 32)).getcolors(1024)) > 3          # not a blank frame


@pytest.mark.parametrize("theme_id", settings.THEME_IDS)
def test_round_panel_keeps_content_in_the_safe_area(theme_id):
    ctx = RenderContext(preview=True)
    ctx.shape = "round"
    theme = themes.create(theme_id, ctx)
    image = themes.render_for_panel(theme, 480, 480, dict(settings.defaults(), theme=theme_id), ctx)
    corner = image.getpixel((0, 0))
    # Everything outside the inscribed square is plain background.
    margin = (480 - int(480 * themes.ROUND_SAFE)) // 2
    strip = image.crop((0, 0, 480, margin - 1))
    assert [color for _count, color in strip.getcolors(1 << 16)] == [corner]


def test_tiny_panels_use_the_compact_layout():
    assert compact.needed(160, 80) and compact.needed(80, 160)
    assert not compact.needed(320, 240) and not compact.needed(480, 320)
    for theme_id in ("standard", "gkrellm", "planet", "old_computer"):
        image = compact.render(80, 160, dict(settings.defaults(), theme=theme_id), theme_id)
        assert image.size == (80, 160)


def test_speech_bubble_fits_narrow_panels():
    image = Image.new("RGB", (80, 160))
    rect = overlay.draw_bubble(image, "Bom dia, ilha! Os mesmos problemas de ontem?", (40, 120))
    assert rect is None or (rect[0] >= 0 and rect[2] <= 80)


def test_hud_fits_narrow_panels():
    stats = telemetry.snapshot()
    rect = overlay.hud_rect(80, 160, settings.defaults(), stats)
    assert rect[0] >= 0 and rect[2] <= 80
