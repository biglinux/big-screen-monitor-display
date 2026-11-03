import json
import os

from bsmd import settings


def test_defaults_are_valid():
    values, problems = settings.validate(settings.defaults())
    assert problems == []
    assert values["theme"] == "standard" and values["performance_profile"] == "auto"


def test_invalid_values_fall_back_and_are_reported():
    values, problems = settings.validate({"theme": "nope", "brightness": "high", "unknown": 1,
                                          "overlay_opacity": 250, "ba_animation": "yes"})
    assert values["theme"] == "standard"
    assert values["brightness"] == 70
    assert values["overlay_opacity"] == 100
    assert values["ba_animation"] is True
    assert "unknown" not in values
    assert len(problems) == 4


def test_legacy_values_are_migrated():
    values, problems = settings.validate({"model": "other", "brightness": 7})
    assert values["model"] == "auto"
    assert values["brightness"] == 100
    assert problems == []
    assert settings.validate({"brightness": 1})[0]["brightness"] == 10


def test_legacy_themes_become_standard_schemes():
    for old in ("dark", "light", "neon", "cyberpunk"):
        values, problems = settings.validate({"theme": old})
        assert values["theme"] == "standard" and values["std_scheme"] == old and not problems
    # An explicit scheme wins over the legacy id.
    assert settings.validate({"theme": "neon", "std_scheme": "nord"})[0]["std_scheme"] == "nord"


def test_corrupted_file_gives_defaults(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    values, problems = settings.read_file(str(path))
    assert values == settings.defaults() and problems


def test_atomic_save_roundtrip(tmp_path):
    path = str(tmp_path / "etc" / "settings.json")
    settings.save({"theme": "planet", "brightness": 40}, path)
    assert settings.read_file(path)[0]["theme"] == "planet"
    assert oct(os.stat(path).st_mode & 0o777) == "0o644"
    assert not [p for p in os.listdir(os.path.dirname(path)) if p.startswith(".tmp-")]


def test_migrate_picks_newest_legacy_file(tmp_path):
    homes = tmp_path / "home"
    for index, (user, theme) in enumerate((("ana", "neon"), ("bia", "planet"))):
        cfg = homes / user / ".config" / "big-screen-monitor"
        cfg.mkdir(parents=True)
        (cfg / "settings.json").write_text(json.dumps({"theme": theme}))
        os.utime(cfg / "settings.json", (1000 + index * 100, 1000 + index * 100))
    target = str(tmp_path / "etc" / "settings.json")
    source = settings.migrate_legacy(target, home_glob=str(homes / "*"), root_home=str(tmp_path / "root"))
    assert source.endswith("bia/.config/big-screen-monitor/settings.json")
    assert settings.read_file(target)[0]["theme"] == "planet"
    # Never overwrites an existing system file.
    assert settings.migrate_legacy(target, home_glob=str(homes / "*")) is None


def test_store_detects_changes(tmp_path):
    path = str(tmp_path / "s.json")
    settings.save({"brightness": 50}, path)
    store = settings.SettingsStore(path)
    assert store.refresh() == set()
    settings.save({"brightness": 60, "theme": "planet"}, path)
    assert store.refresh() == {"brightness", "theme"}
    assert store.get()["brightness"] == 60
