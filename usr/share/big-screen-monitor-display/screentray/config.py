# -*- coding: utf-8 -*-
"""
Configurações, caminhos e definições de temas para o System Tray do Monitor de Tela 3.5".
"""

from pathlib import Path
import os

APP_NAME = "Screen Monitor Display Tray"
APP_ID = "screen-monitor-tray"
VERSION = "1.0.0"

# Caminhos do sistema
BSM_SETTINGS_PATH = "/etc/big-screen-monitor-display/settings.json"
BSM_HELPER = "/usr/lib/big-screen-monitor-display/bsm-helper"
CONFIG_GUI_CMD = ["/usr/bin/big-screen-monitor-config.sh"]
SYSTEMD_SERVICE = "big-screen-monitor-display.service"

# Diretório de configuração do usuário
CONFIG_DIR: Path = Path.home() / ".config" / "screen-monitor-tray"
SETTINGS_FILE: Path = CONFIG_DIR / "settings.json"

# Diretório base do screentray e miniaturas
MODULE_DIR = Path(__file__).resolve().parent
THUMBNAILS_DIR = MODULE_DIR / "thumbnails"

# Definições dos temas disponíveis
THEMES = [
    {
        "id": "standard",
        "name": "Standard",
        "desc": "Dashboard limpo com telemetria (CPU, GPU, RAM, Disco, Rede e Processos)",
        "thumb": "theme-standard-cyberpunk.png",
        "schemes": [
            ("dark", "Dark (Preto Clássico)", "theme-standard-dark.png"),
            ("cyberpunk", "Cyberpunk (Neon Amarelo/Ciano)", "theme-standard-cyberpunk.png"),
            ("neon", "Neon (Ciano & Roxo)", "theme-standard-neon.png"),
            ("dracula", "Dracula (Roxo & Rosa)", "theme-standard-dracula.png"),
            ("nord", "Nord (Azul Ártico)", "theme-standard-nord.png"),
            ("solarized", "Solarized Dark", "theme-standard-dark.png"),
            ("light", "Light (Claro)", "theme-standard-dark.png"),
        ]
    },
    {
        "id": "kojiro",
        "name": "Kojiro",
        "desc": "Wallpaper customizável com widgets livres (anéis, barras e gráficos)",
        "thumb": "kojiro-cyberpunk.png",
        "presets": [
            ("cyberpunk", "Cyberpunk"),
            ("gamer", "Gamer"),
            ("glass", "Glass"),
            ("matrix", "Matrix"),
            ("minimal", "Minimal"),
            ("retro", "Retro"),
        ]
    },
    {
        "id": "planet",
        "name": "Planet",
        "desc": "Vista orbital da Terra com posições em tempo real do Sol e da Lua",
        "thumb": "theme-planet.png",
        "accents": [
            ("blue", "Azul Oceânico"),
            ("amber", "Âmbar Dourado"),
        ]
    },
    {
        "id": "brother_away",
        "name": "Brother Away",
        "desc": "Ilha tropical animada em pixel art com clima e ciclo dia/noite",
        "thumb": "ba-coconut-away.png",
    },
    {
        "id": "old_computer",
        "name": "Old Computer",
        "desc": "Visual retrô nostálgico de janela de sistema estilo Windows 95",
        "thumb": "theme-old_computer.png",
        "schemes": [
            ("classic", "Classic 95"),
            ("slate", "Slate"),
        ]
    },
    {
        "id": "gkrellm",
        "name": "GKrellM",
        "desc": "Tributo ao clássico monitor modular GKrellM do Linux",
        "thumb": "theme-gkrellm.png",
    },
    {
        "id": "big_media_player",
        "name": "Big Media Player",
        "desc": "Player de mídia retrô (estilo Winamp) sincronizado com a música do PC",
        "thumb": "bmp-bigamp.png",
    },
]

# Níveis de brilho para atalhos
BRIGHTNESS_PRESETS = [25, 50, 75, 100]

# Modos de orientação
ORIENTATIONS = [
    ("horizontal", "Horizontal / Paisagem (480x320)"),
    ("vertical", "Vertical / Retrato (320x480)")
]
