# -*- coding: utf-8 -*-
"""Internacionalização - detecção de idioma e traduções."""

import os

TRANSLATIONS = {
    "pt": {
        "display_switch": "Exibir",
        "temperature": "Temperatura",
        "utilization": "Uso de CPU",
        "automatic": "Automático",
        "temp_display": "Mostrador de temperatura",
        "alarm_control": "Controle de alarme",
        "alarm_off": "Desligado",
        "launch_startup": "Executar na inicialização",
        "support": "Suporte",
        "website": "Website",
        "version": "Versão",
        "restart": "Reiniciar",
        "exit": "Sair",
        "connected": "Conectado",
        "disconnected": "Desconectado",
        "connecting": "Conectando...",
        "already_running": "já está em execução.",

        # Cores da borda LED
        "color_menu_title": "Cor da borda",
        "color_menu_disabled": "Cor da borda (instale OpenRGB)",
        "color_customize": "Personalizar...",
        "color_rainbow": "Arco-íris",
        "color_off": "Desligado",
        "color_dialog_title": "Personalizar cor da borda",
        "color_red": "Vermelho",
        "color_blue": "Azul",
        "color_green": "Verde",
        "color_purple": "Roxo",
        "color_cyan": "Ciano",
        "color_yellow": "Amarelo",
        "color_orange": "Laranja",
        "color_white": "Branco",
        "color_pink": "Rosa",
    },
    "en": {
        "display_switch": "Display Switch",
        "temperature": "Temperature",
        "utilization": "Utilization",
        "automatic": "Automatic",
        "temp_display": "Temperature Display",
        "alarm_control": "Alarm Control",
        "alarm_off": "Off",
        "launch_startup": "Launch at startup",
        "support": "Support",
        "website": "Website",
        "version": "Version",
        "restart": "Restart",
        "exit": "Exit",
        "connected": "Connected",
        "disconnected": "Disconnected",
        "connecting": "Connecting...",
        "already_running": "is already running.",

        # Border LED colors
        "color_menu_title": "Border color",
        "color_menu_disabled": "Border color (install OpenRGB)",
        "color_customize": "Customize...",
        "color_rainbow": "Rainbow",
        "color_off": "Off",
        "color_dialog_title": "Customize border color",
        "color_red": "Red",
        "color_blue": "Blue",
        "color_green": "Green",
        "color_purple": "Purple",
        "color_cyan": "Cyan",
        "color_yellow": "Yellow",
        "color_orange": "Orange",
        "color_white": "White",
        "color_pink": "Pink",
    },
}

_current_lang = None


def detect_language():
    """Detecta idioma do sistema sem usar getdefaultlocale."""
    global _current_lang
    if _current_lang:
        return _current_lang

    for var in ('LC_ALL', 'LC_MESSAGES', 'LANG', 'LANGUAGE'):
        lang = os.environ.get(var, '')
        if lang.startswith('pt'):
            _current_lang = 'pt'
            return 'pt'

    _current_lang = 'en'
    return 'en'


def tr(key: str) -> str:
    """Traduz uma chave para o idioma detectado."""
    lang = detect_language()
    return TRANSLATIONS.get(lang, {}).get(key, TRANSLATIONS["en"].get(key, key))
