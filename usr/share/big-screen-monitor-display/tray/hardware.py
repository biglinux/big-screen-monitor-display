# -*- coding: utf-8 -*-
"""Detecção de hardware: sensor, device USB e modelo DeepCool."""

import glob
import logging
import os
import subprocess
from typing import Optional

import psutil

try:
    from config import KNOWN_MODELS, VENDOR_ID
except ImportError:
    from .config import KNOWN_MODELS, VENDOR_ID

logger = logging.getLogger("bsmd.tray.hardware")


def detect_sensor() -> str:
    """Detecta o sensor de temperatura da CPU."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception as e:
        logger.error(f"Erro ao acessar sensores de temperatura: {e}")
        temps = {}

    for name in ['coretemp', 'k10temp', 'zenpower']:
        if name in temps and temps[name]:
            logger.info(f"Sensor detectado: {name}")
            return name

    for name, entries in temps.items():
        if entries and name not in ['acpitz', 'nvme', 'iwlwifi']:
            logger.info(f"Sensor detectado (fallback): {name}")
            return name

    return 'coretemp'


def detect_product_id() -> int:
    """Detecta o Product ID do dispositivo DeepCool via sysfs ou lsusb."""
    # Primeiro tenta via sysfs direto (mais rápido e sem subprocess)
    for dev_path in glob.glob("/sys/bus/usb/devices/*"):
        id_vendor = os.path.join(dev_path, "idVendor")
        id_product = os.path.join(dev_path, "idProduct")
        if os.path.isfile(id_vendor) and os.path.isfile(id_product):
            try:
                with open(id_vendor, "r") as f:
                    v = f.read().strip()
                if v == f"{VENDOR_ID:04x}":
                    with open(id_product, "r") as f:
                        p = f.read().strip()
                    pid = int(p, 16)
                    logger.info(f"DeepCool USB detectado via sysfs: 0x{pid:04x}")
                    return pid
            except (OSError, ValueError):
                continue

    # Fallback para lsusb
    try:
        result = subprocess.run(['lsusb'], capture_output=True, text=True, timeout=5, check=True)
        vendor_id_str = f"{VENDOR_ID:04x}"
        for line in result.stdout.split('\n'):
            if vendor_id_str in line.lower():
                id_part = line.split('ID ')[1].split(' ')[0]
                _vendor, product = id_part.split(':')
                pid = int(product, 16)
                logger.info(f"DeepCool USB detectado via lsusb: 0x{pid:04x}")
                return pid
    except Exception as e:
        logger.warning(f"Erro ao executar lsusb: {e}")

    # Fallback padrão: AK500S / AK620 Digital
    return 0x0004


def detect_model(product_id: int) -> str:
    """Retorna o nome do modelo a partir do Product ID."""
    return KNOWN_MODELS.get(product_id, f"Digital (0x{product_id:04x})")
