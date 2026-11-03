import json
import random

import pytest

from bsmd import runtime, settings, themes
from bsmd.brother_away import BrotherAwayTheme, Reactions, pick_scale, stories
from bsmd.brother_away.dialogue import LINES, Dialogue
from bsmd.brother_away.narrative import (EVENT, IDLE, PREPARATION, REACTION, RESOLUTION, Memory)

SIZES = [(320, 240), (480, 320), (800, 480), (320, 480), (240, 320)]


class Ctx:
    def __init__(self, state_dir=None, preview=True, stats=None):
        self.state_dir = state_dir
        self.preview = preview
        self.target_fps = 8.0
        self.stats = stats or {"valid": True, "cpu_percent": 12.0, "cpu_temp_value": 46.0,
                               "ram_used_mb": 5300, "ram_total_mb": 16000, "ram_percent": 33.0,
                               "disk_percent": 38.0, "gpus": [{"path": "/x", "percent": 8.0, "temp_value": 42.0}],
                               "active_gpu_idx": 0}

    def telemetry(self):
        return self.stats


def make_theme(**kwargs):
    return BrotherAwayTheme(themes.REGISTRY["brother_away"], Ctx(**kwargs))


def ba_settings(**overrides):
    values = settings.defaults()
    values.update(theme="brother_away", **overrides)
    return values


@pytest.mark.parametrize("size", SIZES)
def test_renders_every_supported_size(size):
    theme = make_theme()
    image = theme.render(*size, ba_settings(), theme.ctx)
    assert image.size == size and image.mode == "RGB"


def test_integer_pixel_scale():
    assert pick_scale(320, 240) == 2
    assert pick_scale(480, 320) == 2
    assert pick_scale(800, 480) == 3
    assert pick_scale(1024, 600) == 4


@pytest.mark.parametrize("story_id", [s.id for s in stories.build_registry()[0]])
def test_every_story_completes_without_errors(story_id):
    theme = make_theme()
    values = ba_settings()
    theme.render(480, 320, values, theme.ctx)
    theme.world.hour_override = 2.0 if story_id in ("ufo", "stars_night") else 12.0
    engine = theme.engine
    engine.interrupt()
    item = next(s for s in engine.stories if s.id == story_id)
    engine.start(item)
    seen = set()
    for _ in range(3000):                 # 300 s of simulated time
        theme._advance(0.1, values, theme.world.when)
        seen.add(engine.state)
        if engine.current is None:
            break
    assert engine.current is None, f"{story_id} did not finish"
    assert {PREPARATION, EVENT, REACTION, RESOLUTION} <= seen
    assert engine.memory.data["stories"].get(story_id) == 1


def test_main_stories_exist():
    ids = {s.id for s in stories.build_registry()[0]}
    assert set(stories.MAIN_STORIES) <= ids
    assert len(ids) >= 5


def test_interrupting_a_story_restores_the_world():
    theme = make_theme()
    values = ba_settings()
    theme.render(480, 320, values, theme.ctx)
    engine = theme.engine
    engine.interrupt()
    engine.start(next(s for s in engine.stories if s.id == "philosopher"))
    for _ in range(200):
        theme._advance(0.1, values, theme.world.when)
    engine.interrupt()
    assert theme.world.palm_lean == 0.0
    assert engine.state == IDLE and engine.current is None


def test_selection_avoids_immediate_repetition():
    theme = make_theme()
    values = ba_settings(ba_event_frequency="high")
    theme.render(480, 320, values, theme.ctx)
    engine = theme.engine
    engine.rng = random.Random(3)
    picks = []
    for _ in range(400):
        engine.time += 400
        engine.last_story_end = -1e9
        item = engine.choose()
        picks.append(item.id)
        engine.last_run[item.id] = engine.time
        engine.history = (engine.history + [item.id])[-10:]
    repeats = sum(1 for a, b in zip(picks, picks[1:]) if a == b)
    assert repeats < len(picks) * 0.1
    assert len(set(picks)) >= 8


def test_long_simulation_is_stable_and_bounded():
    """One simulated day at 2 fps: no exceptions, bounded actors and history."""
    theme = make_theme()
    values = ba_settings(ba_event_frequency="high")
    theme.render(320, 240, values, theme.ctx)
    for step in range(24 * 60 * 2):
        theme.world.hour_override = (step / 120.0) % 24
        theme._advance(0.5, values, theme.world.when)
        assert len(theme.world.actors) < 60
        assert len(theme.world.floaters) < 30
    assert len(theme.engine.history) <= 10
    assert len(theme.dialogue.recent) <= 12
    assert sum(theme.engine.memory.data["stories"].values()) > 5


def test_static_mode_keeps_monitoring():
    theme = make_theme()
    values = ba_settings(ba_animation=False)
    first = theme.render(480, 320, values, theme.ctx)
    assert theme.engine.current is None
    assert 0 < theme.frame_interval(values, theme.ctx) <= 1.01
    assert first.size == (480, 320)


def test_memory_persists_atomically_and_tolerates_garbage(tmp_path):
    path = tmp_path / "brother_away.json"
    memory = Memory(str(path))
    memory.data["raft"] = 4
    memory.data["items"] = ["bottle"]
    memory.mark()
    memory.maybe_save()            # rate limited: not yet
    assert not path.exists()
    memory.maybe_save(force=True)
    assert json.loads(path.read_text())["raft"] == 4
    path.write_text('{"raft": "lots", "items": 7, "stories": {"x": "y"}}')
    reloaded = Memory(str(path))
    assert reloaded.data["raft"] == 0 and reloaded.data["items"] == []


def test_preview_does_not_persist(tmp_path):
    theme = make_theme(state_dir=str(tmp_path), preview=True)
    assert theme.memory.path is None
    service = make_theme(state_dir=str(tmp_path), preview=False)
    assert service.memory.path.endswith("brother_away.json")


def test_reactions_use_hysteresis_and_cooldown():
    reactions = Reactions()
    stats = {"cpu_percent": 95, "cpu_temp_value": 50, "ram_percent": 30, "disk_percent": 40, "gpus": []}
    assert reactions.update(0, stats) is None          # must hold above the threshold
    assert reactions.update(10, stats) == "react_heat"
    stats["cpu_percent"] = 75                           # between exit and enter: stays active
    assert reactions.update(20, stats) is None and reactions.active["heat"]
    stats["cpu_percent"] = 50
    reactions.update(30, stats)
    assert not reactions.active["heat"]
    stats["cpu_percent"] = 95
    reactions.update(40, stats)
    assert reactions.update(60, stats) is None          # cooldown


def test_dialogue_respects_humour_and_catchphrases():
    dialogue = Dialogue(random.Random(1))
    assert dialogue.line("awaaay", {"ba_catchphrases": False}) is None
    assert dialogue.line("awaaay", {"ba_catchphrases": True}) == "AWAAAAAY!"
    family = {dialogue.line("coconut_hit", {"ba_humor": "family"}) for _ in range(40)}
    adult_only = {text for text, level, _ in LINES["coconut_hit"] if level == "A"}
    assert not family & adult_only
    ask = dialogue.line("philosophy_ask", {"ba_catchphrases": False})
    assert ask and "morô" not in ask


def test_overlay_handles_missing_telemetry():
    theme = make_theme(stats={"valid": False, "gpus": []})
    image = theme.render(480, 320, ba_settings(), theme.ctx)
    assert image.size == (480, 320)


def test_overlay_can_be_hidden_and_moved():
    for position in ("top_left", "top_right", "bottom_left", "bottom_right"):
        theme = make_theme()
        theme.render(480, 320, ba_settings(overlay_position=position, overlay_size="compact"), theme.ctx)
    theme = make_theme()
    theme.render(480, 320, ba_settings(overlay_enabled=False), theme.ctx)


def test_registered_and_selectable():
    assert "brother_away" in settings.THEME_IDS
    theme = themes.create("brother_away", runtime.RenderContext(preview=True))
    assert isinstance(theme, BrotherAwayTheme)
    assert theme.info.animated


def test_mermaid_draws_while_rising_and_sinking():
    # regression: with 1-3 px above the water the body rectangle was inverted
    # and Pillow raised "y1 must be greater than or equal to y0"
    from PIL import Image, ImageDraw

    from bsmd.brother_away.world import Mermaid
    img = Image.new("RGBA", (64, 64))
    d = ImageDraw.Draw(img)
    mermaid = Mermaid(30, 40)
    for rise in [i / 18 for i in range(19)]:
        mermaid.rise = rise
        mermaid.draw(d, img, None)
