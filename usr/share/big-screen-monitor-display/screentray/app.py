# -*- coding: utf-8 -*-
"""
Aplicação Principal de System Tray para Monitor de Tela Secundária USB de 3,5".
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

try:
    from .qt import (
        QApplication, QSystemTrayIcon, QMenu, QAction, QActionGroup,
        QTimer, QCursor, QPoint, Qt
    )
    from .config import (
        APP_NAME, APP_ID, BSM_SETTINGS_PATH, BSM_HELPER,
        CONFIG_GUI_CMD, SYSTEMD_SERVICE, BRIGHTNESS_PRESETS,
        THEMES
    )
    from .hardware import detect_screen_device, ScreenStatus
    from .icons import create_screen_tray_icon
    from .gallery import ScreenGalleryWindow
    from .i18n import tr
    from . import autostart
except ImportError:
    from qt import (
        QApplication, QSystemTrayIcon, QMenu, QAction, QActionGroup,
        QTimer, QCursor, QPoint, Qt
    )
    from config import (
        APP_NAME, APP_ID, BSM_SETTINGS_PATH, BSM_HELPER,
        CONFIG_GUI_CMD, SYSTEMD_SERVICE, BRIGHTNESS_PRESETS,
        THEMES
    )
    from hardware import detect_screen_device, ScreenStatus
    from icons import create_screen_tray_icon
    from gallery import ScreenGalleryWindow
    from i18n import tr
    import autostart

logger = logging.getLogger("ScreenTray")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


class ScreenTrayApp:
    """Controlador do System Tray para o monitor de tela de 3.5 polegadas."""

    def __init__(self, app: QApplication):
        self.app = app
        self.status = ScreenStatus()
        self.last_stat_mtime = 0

        # Janela de Galeria Visual (Flyout)
        self.gallery = ScreenGalleryWindow()
        self.gallery.theme_changed.connect(self.on_theme_changed)
        self.gallery.brightness_changed.connect(self.on_brightness_changed)
        self.gallery.rotate_requested.connect(self.on_rotate_requested)
        self.gallery.toggle_black_screen.connect(self.on_toggle_black_screen)
        self.gallery.open_settings_requested.connect(self.open_config_gui)
        self.gallery.restart_requested.connect(self.restart_service)

        # Ícone na bandeja
        self.tray = QSystemTrayIcon()
        self.tray.setIcon(create_screen_tray_icon(connected=True))
        self.tray.activated.connect(self.on_tray_activated)

        # Menu Nativo de Contexto (Botão Direito)
        self.menu = QMenu()
        self.menu.setStyleSheet("""
            QMenu {
                background-color: #1c2128;
                color: #e6edf3;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
            }
            QMenu::item {
                padding: 6px 24px 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1f6feb;
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #30363d;
                margin: 4px 6px;
            }
        """)
        self.tray.setContextMenu(self.menu)

        # Atualização inicial e montagem do menu
        self.refresh_status()
        self.build_menu()

        # Timer periódico para checar hardware e arquivo de configurações (a cada 3s)
        self.timer = QTimer()
        self.timer.timeout.connect(self.periodic_check)
        self.timer.start(3000)

        self.tray.show()
        logger.info("ScreenTrayApp inicializado com sucesso.")

    # -------------------------------------------------------------
    # Leitura e Gravação de Configurações
    # -------------------------------------------------------------
    def load_settings(self) -> dict:
        """Carrega configurações do arquivo do sistema /etc/.../settings.json."""
        try:
            if os.path.exists(BSM_SETTINGS_PATH):
                with open(BSM_SETTINGS_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler {BSM_SETTINGS_PATH}: {e}")
        return {}

    def save_settings(self, updates: dict) -> bool:
        """Salva atualizações diretamente ou via bsm-helper apply-settings."""
        values = self.load_settings()
        values.update(updates)

        # Se tiver permissão direta de escrita
        if os.access(os.path.dirname(BSM_SETTINGS_PATH) or ".", os.W_OK):
            try:
                import tempfile
                tmp_fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=os.path.dirname(BSM_SETTINGS_PATH))
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(values, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                os.replace(tmp_path, BSM_SETTINGS_PATH)
                logger.info("Configurações salvas diretamente.")
                return True
            except Exception as e:
                logger.warning(f"Tentativa de escrita direta falhou: {e}")

        # Caso contrário, utiliza o helper com polkit
        try:
            payload = json.dumps(values)
            res = subprocess.run(
                ["pkexec", BSM_HELPER, "apply-settings"],
                input=payload, text=True, capture_output=True, timeout=10, check=False
            )
            if res.returncode == 0:
                logger.info("Configurações salvas via bsm-helper apply-settings com sucesso.")
                return True
            else:
                logger.error(f"bsm-helper falhou ({res.returncode}): {res.stderr}")
        except Exception as e:
            logger.error(f"Erro ao chamar bsm-helper: {e}")
        return False

    # -------------------------------------------------------------
    # Atualização de Estado e Menu
    # -------------------------------------------------------------
    def refresh_status(self):
        """Atualiza estado de conexão, resolução e tema ativo."""
        self.status = detect_screen_device()

        # Atualiza ícone da bandeja
        self.tray.setIcon(create_screen_tray_icon(connected=self.status.connected))

        # Atualiza Tooltip
        theme_name = self.status.theme.capitalize()
        if self.status.theme == "standard":
            theme_name = f"Standard ({self.status.theme_scheme.capitalize()})"
        status_txt = tr("connected") if self.status.connected else tr("disconnected")
        tooltip = f"{tr('app_name')} - {status_txt}\n{tr('theme')}: {theme_name}\n{tr('brightness')}: {self.status.brightness}%"
        self.tray.setToolTip(tooltip)

        # Sincroniza a janela de galeria
        self.gallery.update_state(
            theme=self.status.theme,
            scheme=self.status.theme_scheme,
            brightness=self.status.brightness,
            orientation=self.status.orientation
        )

    def build_menu(self):
        """Constrói o menu nativo de contexto (QMenu) com submenus hierárquicos."""
        self.menu.clear()

        # 1. Cabeçalho de Status
        status_icon = "🟢" if self.status.connected else "🔴"
        status_desc = tr("connected") if self.status.connected else tr("disconnected")
        header_text = f"🖥  {self.status.name}  •  {status_icon} {status_desc}"
        header_act = self.menu.addAction(header_text)
        header_act.setEnabled(False)

        self.menu.addSeparator()

        # 2. Submenu de Temas (Hierárquico com Títulos e Radio Buttons)
        theme_title = self.status.theme.capitalize()
        if self.status.theme == "standard":
            theme_title = f"Standard ({self.status.theme_scheme.capitalize()})"
        theme_menu = self.menu.addMenu(f"🎨  {tr('theme')}: {theme_title}")

        theme_group = QActionGroup(self.menu)
        theme_group.setExclusive(True)

        for th in THEMES:
            t_id = th["id"]
            t_name = th["name"]

            # Se o tema tiver variantes (esquemas de cores ou presets)
            if "schemes" in th:
                sub_th = theme_menu.addMenu(f"●  {t_name}" if self.status.theme == t_id else f"○  {t_name}")
                sub_group = QActionGroup(self.menu)
                sub_group.setExclusive(True)
                for item in th["schemes"]:
                    s_id, s_name = item[0], item[1]
                    act = sub_th.addAction(s_name)
                    act.setCheckable(True)
                    if self.status.theme == t_id and self.status.theme_scheme == s_id:
                        act.setChecked(True)
                    act.triggered.connect(lambda checked, tid=t_id, sid=s_id: self.on_theme_changed(tid, sid))
                    sub_group.addAction(act)
            elif "presets" in th:
                sub_th = theme_menu.addMenu(f"●  {t_name}" if self.status.theme == t_id else f"○  {t_name}")
                sub_group = QActionGroup(self.menu)
                sub_group.setExclusive(True)
                for p_id, p_name in th["presets"]:
                    act = sub_th.addAction(p_name)
                    act.setCheckable(True)
                    act.triggered.connect(lambda checked, tid=t_id, pid=p_id: self.on_theme_changed(tid, pid))
                    sub_group.addAction(act)
            elif "accents" in th:
                sub_th = theme_menu.addMenu(f"●  {t_name}" if self.status.theme == t_id else f"○  {t_name}")
                sub_group = QActionGroup(self.menu)
                sub_group.setExclusive(True)
                for a_id, a_name in th["accents"]:
                    act = sub_th.addAction(a_name)
                    act.setCheckable(True)
                    act.triggered.connect(lambda checked, tid=t_id, aid=a_id: self.on_theme_changed(tid, aid))
                    sub_group.addAction(act)
            else:
                act = theme_menu.addAction(t_name)
                act.setCheckable(True)
                if self.status.theme == t_id:
                    act.setChecked(True)
                act.triggered.connect(lambda checked, tid=t_id: self.on_theme_changed(tid, ""))
                theme_group.addAction(act)

        # 3. Submenu de Brilho
        bright_menu = self.menu.addMenu(f"☀  {tr('brightness')} ({self.status.brightness}%)")
        bright_group = QActionGroup(self.menu)
        bright_group.setExclusive(True)
        for val in BRIGHTNESS_PRESETS:
            act = bright_menu.addAction(f"{val}%")
            act.setCheckable(True)
            if self.status.brightness == val:
                act.setChecked(True)
            act.triggered.connect(lambda checked, b=val: self.on_brightness_changed(b))
            bright_group.addAction(act)

        # 4. Submenu de Orientação
        orient_name = "Horizontal (480x320)" if self.status.orientation == "horizontal" else "Vertical (320x480)"
        orient_menu = self.menu.addMenu(f"↻  {tr('orientation')}: {orient_name}")
        orient_group = QActionGroup(self.menu)
        orient_group.setExclusive(True)

        h_act = orient_menu.addAction(tr("horizontal"))
        h_act.setCheckable(True)
        h_act.setChecked(self.status.orientation == "horizontal")
        h_act.triggered.connect(lambda: self.on_orientation_changed("horizontal"))
        orient_group.addAction(h_act)

        v_act = orient_menu.addAction(tr("vertical"))
        v_act.setCheckable(True)
        v_act.setChecked(self.status.orientation == "vertical")
        v_act.triggered.connect(lambda: self.on_orientation_changed("vertical"))
        orient_group.addAction(v_act)

        self.menu.addSeparator()

        # 5. Abrir Galeria Visual (Flyout)
        gallery_act = self.menu.addAction("🖼  Galeria Visual de Temas...")
        gallery_act.triggered.connect(self.show_gallery)

        # 6. Configurações Avançadas
        cfg_act = self.menu.addAction(f"⚙  {tr('settings')}")
        cfg_act.triggered.connect(self.open_config_gui)

        # 7. Reiniciar Serviço
        restart_act = self.menu.addAction(f"↻  {tr('restart_service')}")
        restart_act.triggered.connect(self.restart_service)

        # 8. Autostart
        autostart_act = self.menu.addAction(tr("autostart"))
        autostart_act.setCheckable(True)
        autostart_act.setChecked(autostart.is_enabled())
        autostart_act.triggered.connect(self.toggle_autostart)

        self.menu.addSeparator()

        # 9. Sair
        quit_act = self.menu.addAction(f"✕  {tr('quit')}")
        quit_act.triggered.connect(self.app.quit)

    # -------------------------------------------------------------
    # Handlers de Eventos
    # -------------------------------------------------------------
    def on_tray_activated(self, reason):
        """Clique esquerdo abre a Galeria Visual; clique direito abre o menu."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.gallery.isVisible():
                self.gallery.hide()
            else:
                self.show_gallery()

    def show_gallery(self):
        """Posiciona e exibe o Flyout de Galeria Visual próximo ao ícone da bandeja."""
        self.refresh_status()
        geom = self.tray.geometry()
        pos = QCursor.pos()

        # Se geometry do tray for válida, posiciona acima ou abaixo
        if geom.isValid() and geom.x() > 0:
            x = geom.center().x() - (self.gallery.width() // 2)
            y = geom.top() - self.gallery.height() - 8 if geom.top() > self.gallery.height() else geom.bottom() + 8
        else:
            x = pos.x() - (self.gallery.width() // 2)
            y = max(20, pos.y() - self.gallery.height() - 10)

        # Garante que não ultrapasse as bordas da tela
        screen = QApplication.primaryScreen().geometry()
        x = max(10, min(x, screen.width() - self.gallery.width() - 10))
        y = max(10, min(y, screen.height() - self.gallery.height() - 10))

        self.gallery.move(x, y)
        self.gallery.show()
        self.gallery.raise_()
        self.gallery.activateWindow()

    def on_theme_changed(self, theme_id: str, scheme_or_preset: str = ""):
        """Aplica a troca de tema no settings.json."""
        logger.info(f"Alterando tema para: {theme_id} (esquema/preset: {scheme_or_preset})")
        updates = {"theme": theme_id}

        if theme_id == "standard":
            updates["std_scheme"] = scheme_or_preset or "cyberpunk"
        elif theme_id == "planet":
            if scheme_or_preset:
                updates["planet_accent"] = scheme_or_preset
        elif theme_id == "old_computer":
            if scheme_or_preset:
                updates["oc_scheme"] = scheme_or_preset
        elif theme_id == "kojiro":
            # Para kojiro, preserva a chave kojiro e ajusta o preset se fornecido
            current = self.load_settings()
            k_dict = current.get("kojiro", {})
            if isinstance(k_dict, dict) and scheme_or_preset:
                k_dict["preset"] = scheme_or_preset
                updates["kojiro"] = k_dict

        self.save_settings(updates)
        self.refresh_status()
        self.build_menu()

    def on_brightness_changed(self, value: int):
        """Ajusta o nível de brilho da tela (0-100%)."""
        logger.info(f"Ajustando brilho para: {value}%")
        self.save_settings({"brightness": value})
        self.refresh_status()
        self.build_menu()

    def on_orientation_changed(self, orientation: str):
        """Altera a orientação entre horizontal e vertical."""
        logger.info(f"Alterando orientação para: {orientation}")
        self.save_settings({"orientation": orientation})
        self.refresh_status()
        self.build_menu()

    def on_rotate_requested(self):
        """Alterna a rotação atual."""
        new_orient = "vertical" if self.status.orientation == "horizontal" else "horizontal"
        self.on_orientation_changed(new_orient)

    def on_toggle_black_screen(self):
        """Liga ou apaga a tela temporariamente (brilho 0 vs anterior)."""
        if self.status.brightness > 0:
            self._prev_brightness = self.status.brightness
            self.on_brightness_changed(0)
        else:
            prev = getattr(self, "_prev_brightness", 100)
            self.on_brightness_changed(prev if prev > 0 else 100)

    def open_config_gui(self):
        """Abre a janela de configuração GTK4 completa."""
        try:
            logger.info("Abrindo Painel de Configurações Completo...")
            subprocess.Popen(CONFIG_GUI_CMD)
        except Exception as e:
            logger.error(f"Erro ao abrir {CONFIG_GUI_CMD}: {e}")

    def restart_service(self):
        """Reinicia o serviço systemd do display."""
        try:
            logger.info("Reiniciando serviço big-screen-monitor-display...")
            subprocess.run(["pkexec", BSM_HELPER, "service", "restart"], timeout=10, check=False)
            self.refresh_status()
            self.build_menu()
        except Exception as e:
            logger.error(f"Erro ao reiniciar serviço: {e}")

    def toggle_autostart(self, enabled: bool):
        """Alterna inicialização automática."""
        if enabled:
            autostart.enable()
        else:
            autostart.disable()

    def periodic_check(self):
        """Verifica se o arquivo settings.json mudou externamente."""
        try:
            if os.path.exists(BSM_SETTINGS_PATH):
                mtime = os.path.getmtime(BSM_SETTINGS_PATH)
                if self.last_stat_mtime and mtime != self.last_stat_mtime:
                    self.last_stat_mtime = mtime
                    self.refresh_status()
                    self.build_menu()
                elif not self.last_stat_mtime:
                    self.last_stat_mtime = mtime
        except Exception:
            pass
