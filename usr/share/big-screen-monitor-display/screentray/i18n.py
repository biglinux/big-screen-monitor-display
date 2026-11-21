# -*- coding: utf-8 -*-
"""
Internacionalização (i18n) para o System Tray do Monitor de Tela 3.5".
"""

import locale
import os


def get_system_lang() -> str:
    """Detecta o idioma do sistema operacional."""
    try:
        lang = os.environ.get("LANG", "")
        if not lang:
            loc = locale.getlocale()
            lang = loc[0] or ""
        return "pt" if lang.lower().startswith("pt") else "en"
    except Exception:
        return "pt"


LANG = get_system_lang()

STRINGS = {
    "pt": {
        "app_name": "Monitor de Tela 3.5\"",
        "connected": "Conectado",
        "disconnected": "Desconectado",
        "service_running": "Serviço Ativo",
        "service_stopped": "Serviço Parado",
        "theme": "Tema",
        "themes": "Temas",
        "brightness": "Brilho",
        "orientation": "Orientação",
        "horizontal": "Horizontal / Paisagem (480x320)",
        "vertical": "Vertical / Retrato (320x480)",
        "rotate": "Girar Tela (0° / 90°)",
        "black_screen": "Apagar Tela",
        "wake_screen": "Ligar Tela",
        "apply": "Aplicar no Display",
        "settings": "Painel de Configurações...",
        "restart_service": "Reiniciar Serviço do Display",
        "autostart": "Iniciar com o sistema",
        "quit": "Sair",
        "active": "Ativo",
        "choose_theme": "Escolha o Tema (clique para aplicar):",
        "preview": "Prévia do Display",
    },
    "en": {
        "app_name": "3.5\" Screen Monitor",
        "connected": "Connected",
        "disconnected": "Disconnected",
        "service_running": "Service Active",
        "service_stopped": "Service Stopped",
        "theme": "Theme",
        "themes": "Themes",
        "brightness": "Brightness",
        "orientation": "Orientation",
        "horizontal": "Horizontal / Landscape (480x320)",
        "vertical": "Vertical / Portrait (320x480)",
        "rotate": "Rotate Screen (0° / 90°)",
        "black_screen": "Blank Screen",
        "wake_screen": "Wake Screen",
        "apply": "Apply to Display",
        "settings": "Full Settings...",
        "restart_service": "Restart Display Service",
        "autostart": "Start on system boot",
        "quit": "Quit",
        "active": "Active",
        "choose_theme": "Choose Theme (click to apply):",
        "preview": "Display Preview",
    }
}


def tr(key: str) -> str:
    """Retorna o texto traduzido para o idioma ativo."""
    return STRINGS.get(LANG, STRINGS["pt"]).get(key, key)
