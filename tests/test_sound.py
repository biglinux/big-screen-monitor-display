import io
import random
import wave

from bsmd import sound
from bsmd.brother_away import BrotherAwayTheme

from test_brother_away import Ctx, ba_settings
from bsmd import themes


def test_every_effect_is_a_short_valid_wav():
    for kind in ("awaaay", "alarm", "bonk", "splash", "ufo", "fanfare", "laugh", "squawk", "blip_up", "speech"):
        data = sound.to_wav(sound.synth(kind), volume=0.5)
        with wave.open(io.BytesIO(data)) as handle:
            assert handle.getframerate() == sound.RATE and handle.getnchannels() == 1
            assert 0.05 < handle.getnframes() / sound.RATE < 2.0


def test_event_mapping_and_speech_frequency():
    rng = random.Random(1)
    assert sound.sound_for("say:awaaay", "low", rng) == "awaaay"
    assert sound.sound_for("fx:laugh", "low", rng) == "laugh"
    assert sound.sound_for("fx:unknown", "high", rng) is None
    hits = sum(sound.sound_for("say:idle", "low", rng) == "speech" for _ in range(1000))
    assert 80 < hits < 250


def test_theme_publishes_bounded_sound_events():
    theme = BrotherAwayTheme(themes.REGISTRY["brother_away"], Ctx())
    values = ba_settings()
    theme.render(480, 320, values, theme.ctx)
    theme.engine.interrupt()
    theme.engine.start(next(s for s in theme.engine.stories if s.id == "coconut_tree"))
    for _ in range(600):
        theme._advance(0.1, values, theme.world.when)
    events = [event for _seq, event in theme.sound_events]
    assert "say:awaaay" in events and "say:coconut_hit" in events
    assert len(theme.sound_events) <= 20 and theme.engine.events == []


def test_autostart_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    sound.set_autostart(True, "/usr/share/big-screen-monitor-display/main.py")
    text = (tmp_path / "autostart" / sound.AUTOSTART_NAME).read_text()
    assert "--sound-agent" in text
    sound.set_autostart(False, "x")
    assert not (tmp_path / "autostart" / sound.AUTOSTART_NAME).exists()
