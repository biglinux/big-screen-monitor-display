#!/usr/bin/python3
"""DeepCool Digital: tray app of Big Screen Monitor Display."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from traykit.launch import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main("deepcooltray.app", "DeepCoolTray", "DeepCool Digital"))
