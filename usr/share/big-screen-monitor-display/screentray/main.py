#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Screen Monitor Display Tray - System Tray para telas secundárias USB de 3,5".
Permite alternar temas com 1 clique (Flyout com miniaturas visuais) ou pelo menu nativo.
"""

import fcntl
import logging
import os
import sys
from pathlib import Path
from typing import Optional, TextIO

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# Inclui diretório raiz do big-screen-monitor-display
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

try:
    from app import ScreenTrayApp
    from config import APP_NAME, CONFIG_DIR
    from qt import QApplication
except ImportError:
    from .app import ScreenTrayApp
    from .config import APP_NAME, CONFIG_DIR
    from .qt import QApplication

LOCK_FILE = CONFIG_DIR / "app.lock"
LOG_FILE = CONFIG_DIR / "screentray.log"


def setup_logging() -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                RotatingFileHandler(str(LOG_FILE), maxBytes=2 * 1024 * 1024, backupCount=2, encoding="utf-8"),
                logging.StreamHandler()
            ]
        )
    except Exception as e:
        print(f"Aviso: logging em arquivo indisponível: {e}")


def acquire_lock() -> TextIO:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except IOError:
        raise RuntimeError(f"{APP_NAME} já está em execução.")


def release_lock(lock_file: Optional[TextIO]) -> None:
    if lock_file is not None:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()
        except Exception:
            pass


def main() -> None:
    setup_logging()
    logger = logging.getLogger("ScreenTray.Main")
    logger.info(f"Iniciando {APP_NAME}...")

    lock_file = None
    try:
        lock_file = acquire_lock()
    except RuntimeError as e:
        logger.warning(str(e))
        print(str(e))
        sys.exit(0)

    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        app.setApplicationName(APP_NAME)

        tray_app = ScreenTrayApp(app)

        exit_code = app.exec() if hasattr(app, "exec") else app.exec_()
        logger.info(f"Aplicação encerrada com código {exit_code}")
        sys.exit(exit_code)
    except Exception as e:
        logger.critical(f"Erro fatal: {e}", exc_info=True)
        sys.exit(1)
    finally:
        release_lock(lock_file)


if __name__ == "__main__":
    main()
