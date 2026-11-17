# -*- coding: utf-8 -*-
"""
Detecção do monitor de tela 3.5" USB (Turing / UsbPCMonitor / ACM) e status do serviço.
"""

import os
import sys
import subprocess
from dataclasses import dataclass
from typing import Optional

# Garantir que o bsmd esteja no sys.path
BSMD_DIR = "/usr/share/big-screen-monitor-display"
if BSMD_DIR not in sys.path:
    sys.path.insert(0, BSMD_DIR)

REPO_BSMD = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_BSMD not in sys.path:
    sys.path.insert(0, REPO_BSMD)


@dataclass
class ScreenStatus:
    connected: bool = False
    name: str = "Turing 3.5\" USB Screen"
    model: str = "3.5\""
    resolution: str = "480x320"
    device_node: Optional[str] = None
    tty: Optional[str] = None
    service_active: bool = False
    brightness: int = 100
    orientation: str = "horizontal"
    theme: str = "standard"
    theme_scheme: str = "cyberpunk"


def is_service_running() -> bool:
    """Verifica se o serviço systemd do monitor está ativo."""
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "big-screen-monitor-display"],
            capture_output=True, text=True, timeout=2, check=False
        )
        return res.stdout.strip() == "active"
    except Exception:
        return False


def detect_screen_device() -> ScreenStatus:
    """Detecta o display de 3.5 polegadas conectado via USB/Serial."""
    status = ScreenStatus()
    status.service_active = is_service_running()

    try:
        from bsmd import diagnostics
        devices = diagnostics.find_usb_devices()
        for dev in devices:
            # Procura especificamente telas (Turing, UsbPCMonitor, etc.) e ignora cooler deepcool
            if dev.get("profile") != "deepcool_ak" and ("3.5" in dev.get("name", "") or dev.get("tty") or "turing" in dev.get("profile", "")):
                status.connected = True
                status.name = dev.get("name", "Turing 3.5\" / UsbPCMonitor")
                status.tty = dev.get("tty")
                status.device_node = dev.get("node")
                break
    except Exception:
        # Fallback via detecção direta de ttyACM / ttyUSB
        for port in ["/dev/ttyACM0", "/dev/ttyACM1", "/dev/ttyUSB0"]:
            if os.path.exists(port):
                status.connected = True
                status.tty = port
                break

    # Carrega preferências atuais do settings.json
    try:
        from bsmd import settings
        val = settings.load()
        status.brightness = int(val.get("brightness", 100))
        status.orientation = val.get("orientation", "horizontal")
        status.theme = val.get("theme", "standard")
        status.theme_scheme = val.get("std_scheme", "cyberpunk")
    except Exception:
        pass

    return status
