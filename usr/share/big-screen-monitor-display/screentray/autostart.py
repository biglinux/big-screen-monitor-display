# -*- coding: utf-8 -*-
"""
Gerencia a inicialização automática no KDE Plasma / Ambientes Desktop via arquivo .desktop.
"""

import os
import sys
from pathlib import Path

AUTOSTART_DIR = Path.home() / ".config" / "autostart"
AUTOSTART_FILE = AUTOSTART_DIR / "screen-monitor-tray.desktop"
APP_DISPLAY_NAME = "Screen Monitor Display Tray"


def get_exec_command() -> str:
    """Retorna o comando executável do tray."""
    bin_path = "/usr/bin/screen-monitor-tray.sh"
    if os.path.exists(bin_path):
        return bin_path
    user_bin = os.path.expanduser("~/.local/bin/screen-monitor-tray")
    if os.path.exists(user_bin):
        return user_bin
    tray_main = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
    return f"{sys.executable} {tray_main}"


def is_enabled() -> bool:
    """Verifica se autostart está ativo."""
    return AUTOSTART_FILE.exists()


def enable():
    """Habilita o início automático no KDE Plasma / desktop."""
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    cmd = get_exec_command()

    content = f"""[Desktop Entry]
Type=Application
Name={APP_DISPLAY_NAME}
Comment=System Tray controller for USB secondary screen monitor
Exec={cmd}
Icon=screen-monitor-tray
Terminal=false
Categories=System;Monitor;
StartupNotify=false
X-KDE-autostart-after=panel
"""
    AUTOSTART_FILE.write_text(content, encoding="utf-8")


def disable():
    """Desabilita o início automático."""
    if AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()
