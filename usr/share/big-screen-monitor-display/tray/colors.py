# -*- coding: utf-8 -*-
"""
Controle de cores da borda LED ARGB via OpenRGB.

As fitas LED ARGB do display do cooler DeepCool são conectadas ao
header ARGB 3-pin da placa-mãe e controladas pelo OpenRGB CLI.
"""

import logging
import re
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("bsmd.tray.colors")

# Cores predefinidas (chave_i18n, hex)
PRESET_COLORS: List[Tuple[str, str]] = [
    ("color_red",    "#FF0000"),
    ("color_blue",   "#0066FF"),
    ("color_green",  "#00CC44"),
    ("color_purple", "#9933FF"),
    ("color_cyan",   "#00CCCC"),
    ("color_yellow", "#FFCC00"),
    ("color_orange", "#FF6600"),
    ("color_white",  "#FFFFFF"),
    ("color_pink",   "#FF33AA"),
]

COLOR_RAINBOW: str = "__rainbow__"
COLOR_OFF: str = "__off__"
COLOR_DEFAULT: str = "#00CCCC"

_cached_argb_device_id: Optional[int] = None


def is_openrgb_available() -> bool:
    """Verifica se o OpenRGB está instalado no sistema."""
    return shutil.which("openrgb") is not None


def _run_openrgb(*args: str, timeout: int = 10) -> Optional[str]:
    """Executa comando OpenRGB e retorna stdout."""
    cmd = ["openrgb"] + list(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            logger.warning(f"OpenRGB code {result.returncode}: {result.stderr.strip()}")
            return None
        return result.stdout
    except subprocess.TimeoutExpired:
        logger.error(f"OpenRGB timeout após {timeout}s")
        return None
    except FileNotFoundError:
        logger.error("OpenRGB não encontrado no PATH")
        return None
    except Exception as e:
        logger.error(f"Erro ao executar OpenRGB: {e}")
        return None


def list_devices() -> List[Dict]:
    """Lista dispositivos RGB detectados pelo OpenRGB."""
    output = _run_openrgb("--noautoconnect", "--list-devices", timeout=15)
    if not output:
        return []

    devices: List[Dict] = []
    for line in output.splitlines():
        match = re.match(r"^(\d+):\s+(.+)$", line.strip())
        if match:
            devices.append({"id": int(match.group(1)), "name": match.group(2).strip()})
    return devices


def find_motherboard_argb_device() -> Optional[int]:
    """Encontra o dispositivo da placa-mãe que controla o header ARGB."""
    global _cached_argb_device_id
    if _cached_argb_device_id is not None:
        return _cached_argb_device_id

    devices = list_devices()
    if not devices:
        return None

    # Procura placa-mãe conhecida
    keywords = ["motherboard", "b660", "b550", "x570", "z690", "z790", "gigabyte", "asus", "msi", "asrock"]
    for dev in devices:
        name_lower = dev["name"].lower()
        if any(kw in name_lower for kw in keywords):
            _cached_argb_device_id = dev["id"]
            return _cached_argb_device_id

    _cached_argb_device_id = devices[0]["id"]
    return _cached_argb_device_id


def set_color(hex_color: str, device_id: Optional[int] = None, zone_id: Optional[int] = None, led_count: Optional[int] = None) -> bool:
    """Define uma cor estática nas LEDs ARGB."""
    if not is_openrgb_available():
        return False

    color = hex_color.lstrip("#").upper()
    if len(color) != 6 or not all(c in "0123456789ABCDEF" for c in color):
        logger.error(f"Cor hex inválida: {hex_color}")
        return False

    if device_id is None:
        device_id = find_motherboard_argb_device()
    if device_id is None:
        return False

    args = ["--noautoconnect", "-d", str(device_id)]
    if zone_id is not None:
        args += ["-z", str(zone_id)]
        if led_count is not None:
            args += ["-sz", str(led_count)]
        args += ["-c", color]
    else:
        # Aplica explicitamente nas zonas ARGB digitais (D_LED1 = 0, D_LED2 = 1) e global
        args += [
            "-z", "0", "-sz", "30", "-c", color,
            "-z", "1", "-sz", "30", "-c", color,
            "-c", color,
        ]

    output = _run_openrgb(*args)
    return output is not None


def set_rainbow(device_id: Optional[int] = None, zone_id: Optional[int] = None, led_count: Optional[int] = None) -> bool:
    """Define modo arco-íris / ciclo de cores nas LEDs ARGB."""
    if not is_openrgb_available():
        return False

    if device_id is None:
        device_id = find_motherboard_argb_device()
    if device_id is None:
        return False

    for mode in ["Color Cycle", "Spectrum Cycle", "Rainbow", "Rainbow Wave", "Breathing"]:
        args = ["--noautoconnect", "-d", str(device_id)]
        if zone_id is not None:
            args += ["-z", str(zone_id)]
        if led_count is not None:
            args += ["-sz", str(led_count)]
        args += ["-m", mode]
        output = _run_openrgb(*args)
        if output is not None:
            return True

    return False


def set_off(device_id: Optional[int] = None, zone_id: Optional[int] = None, led_count: Optional[int] = None) -> bool:
    """Desliga as LEDs ARGB."""
    return set_color("#000000", device_id, zone_id, led_count)


def apply_color_setting(color_value: str, device_id: Optional[int] = None, zone_id: Optional[int] = None, led_count: Optional[int] = None) -> bool:
    """Aplica uma configuração de cor (hex, arco-íris ou desligado)."""
    if color_value == COLOR_RAINBOW:
        return set_rainbow(device_id, zone_id, led_count)
    if color_value in (COLOR_OFF, "off"):
        return set_off(device_id, zone_id, led_count)
    return set_color(color_value, device_id, zone_id, led_count)
