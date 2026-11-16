#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepCool Digital - System Tray App
Para Regata OS / openSUSE (KDE Plasma)

Parte do screen-monitor-display (branch developer)
https://github.com/marquimRcc/screen-monitor-display
"""

import fcntl
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional, TextIO

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from app import DeepCoolTray
    from config import APP_DISPLAY_NAME, LOCK_FILE, LOG_FILE
    from hardware import detect_model, detect_product_id, detect_sensor
    from i18n import tr
    from qt import QApplication, QMessageBox
except ImportError:
    from .app import DeepCoolTray
    from .config import APP_DISPLAY_NAME, LOCK_FILE, LOG_FILE
    from .hardware import detect_model, detect_product_id, detect_sensor
    from .i18n import tr
    from .qt import QApplication, QMessageBox


def setup_logging() -> None:
    """Configura o sistema de logging com rotação de arquivos."""
    try:
        log_dir: Path = Path(LOG_FILE).parent
        log_dir.mkdir(parents=True, exist_ok=True)

        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                RotatingFileHandler(
                    LOG_FILE,
                    maxBytes=5 * 1024 * 1024,
                    backupCount=2,
                    encoding='utf-8'
                ),
                logging.StreamHandler()
            ]
        )
    except Exception as e:
        print(f"Aviso: não foi possível configurar logging em arquivo: {e}")


def acquire_lock() -> TextIO:
    """Adquire lock de instância única."""
    try:
        Path(LOCK_FILE).parent.mkdir(parents=True, exist_ok=True)
        lock_file: TextIO = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except IOError as e:
        raise RuntimeError(f"{APP_DISPLAY_NAME} {tr('already_running')}") from e
    except Exception as e:
        raise RuntimeError(f"Erro ao criar arquivo de lock: {e}") from e


def release_lock(lock_file: Optional[TextIO]) -> None:
    """Libera o lock de instância única."""
    if lock_file is not None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        except Exception:
            pass


def main() -> None:
    """Função principal da aplicação."""
    setup_logging()
    logger = logging.getLogger("bsmd.tray.main")
    logger.info(f"Iniciando {APP_DISPLAY_NAME} Tray...")

    lock_file: Optional[TextIO] = None
    exit_code: int = 0

    try:
        # Prevenir múltiplas instâncias
        lock_file = acquire_lock()

        # Qt App
        app: QApplication = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(APP_DISPLAY_NAME)

        # Detectar hardware
        logger.info("Detectando hardware...")
        product_id: int = detect_product_id()
        model: str = detect_model(product_id)
        sensor: str = detect_sensor()

        logger.info(f"Hardware detectado: {model} (0x{product_id:04x}), Sensor: {sensor}")

        # Tray
        tray = DeepCoolTray(app, product_id, model, sensor)
        tray.start()

        logger.info("Aplicação de bandeja iniciada com sucesso")
        exit_code = app.exec() if hasattr(app, "exec") else app.exec_()

    except RuntimeError as e:
        logger.warning(str(e))
        print(str(e))
        exit_code = 1

    except Exception as e:
        error_msg = f"Erro inesperado ao iniciar aplicação da bandeja: {e}"
        logger.critical(error_msg, exc_info=True)
        if not os.environ.get("HEADLESS"):
            try:
                QMessageBox.critical(None, "Erro Fatal", error_msg)
            except Exception:
                pass
        exit_code = 3

    finally:
        release_lock(lock_file)

    logger.info(f"Aplicação encerrada com código {exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
