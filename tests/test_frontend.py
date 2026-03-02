import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../big-screen-monitor-display/usr/share/big-screen-monitor-display')))

import config_gui

def test_config_gui_defaults():
    settings = config_gui.load_settings()
    assert 'theme' in settings

@patch('config_gui.save_settings')
def test_config_save(mock_save):
    mock_save.return_value = True
    res = config_gui.save_settings({"theme": "light"})
    assert res is True
