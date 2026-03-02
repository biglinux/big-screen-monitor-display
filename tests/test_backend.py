import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../big-screen-monitor-display/usr/share/big-screen-monitor-display')))

import main

def test_get_theme_colors():
    dark_theme = main.get_theme_colors('dark')
    assert 'bg' in dark_theme
    assert dark_theme['bg'] == (18, 18, 25)

def test_config_load_fallback():
    settings = main.get_settings()
    assert isinstance(settings, dict)
    assert 'model' in settings
