# -*- coding: utf-8 -*-
"""Gerencia o autostart no KDE Plasma via .desktop file."""

import os
import sys
from pathlib import Path

try:
    from config import APP_DISPLAY_NAME, APP_NAME, AUTOSTART_DIR, AUTOSTART_FILE
except ImportError:
    from .config import APP_DISPLAY_NAME, APP_NAME, AUTOSTART_DIR, AUTOSTART_FILE


def get_exec_command():
    """Retorna comando para executar o tray."""
    bin_path = "/usr/bin/deepcool-digital.sh"
    if os.path.exists(bin_path):
        return bin_path
    user_bin = os.path.expanduser("~/.local/bin/deepcool-digital")
    if os.path.exists(user_bin):
        return user_bin
    tray_main = os.path.abspath(os.path.join(os.path.dirname(__file__), 'main.py'))
    return f"{sys.executable} {tray_main}"


def is_enabled():
    """Verifica se autostart está habilitado."""
    return AUTOSTART_FILE.exists()


def enable():
    """Cria arquivo .desktop para iniciar automaticamente no KDE Plasma."""
    AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
    cmd = get_exec_command()

    content = f"""[Desktop Entry]
Type=Application
Name={APP_DISPLAY_NAME}
Comment=DeepCool Digital cooler system tray controller
Exec={cmd}
Icon=deepcool-digital
Terminal=false
Categories=System;Monitor;
StartupNotify=false
X-KDE-autostart-after=panel
"""
    AUTOSTART_FILE.write_text(content, encoding='utf-8')


def disable():
    """Remove arquivo .desktop do autostart."""
    if AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()
