# -*- coding: utf-8 -*-
"""Interface System Tray - menu de contexto e interação com o usuário para DeepCool Digital."""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from typing import Optional

import psutil

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    import autostart
    from colors import (
        COLOR_DEFAULT, COLOR_OFF, COLOR_RAINBOW, PRESET_COLORS,
        apply_color_setting, is_openrgb_available
    )
    from config import (
        ALARM_TEMPS, GITHUB_URL, INTERVAL, SETTINGS_FILE, VENDOR_ID, VERSION
    )
    from i18n import tr
    from icons import create_deepcool_icon, create_status_icon, make_color_icon
    from qt import (
        ANTIALIASING, FONT_BOLD, NO_PEN, QAction, QActionGroup, QApplication,
        QColor, QColorDialog, QFont, QIcon, QMenu, QPainter, QPixmap,
        QSystemTrayIcon, QTimer
    )
    from utils import format_temperature
except ImportError:
    from . import autostart
    from .colors import (
        COLOR_DEFAULT, COLOR_OFF, COLOR_RAINBOW, PRESET_COLORS,
        apply_color_setting, is_openrgb_available
    )
    from .config import (
        ALARM_TEMPS, GITHUB_URL, INTERVAL, SETTINGS_FILE, VENDOR_ID, VERSION
    )
    from .i18n import tr
    from .icons import create_deepcool_icon, create_status_icon, make_color_icon
    from .qt import (
        ANTIALIASING, FONT_BOLD, NO_PEN, QAction, QActionGroup, QApplication,
        QColor, QColorDialog, QFont, QIcon, QMenu, QPainter, QPixmap,
        QSystemTrayIcon, QTimer
    )
    from .utils import format_temperature

logger = logging.getLogger("bsmd.tray.app")

BSM_SETTINGS_PATH = "/etc/big-screen-monitor-display/settings.json"
BSM_STATUS_PATH = "/run/big-screen-monitor-display/status.json"
BSM_HELPER = "/usr/lib/big-screen-monitor-display/bsm-helper"


def _read_cpu_temp(sensor_name: str) -> float:
    """Lê a temperatura atual da CPU via psutil ou sysfs."""
    try:
        temps = psutil.sensors_temperatures()
        if sensor_name in temps and temps[sensor_name]:
            for entry in temps[sensor_name]:
                if entry.current and entry.current > 0:
                    return float(entry.current)
        for name, entries in temps.items():
            if entries and name not in ['acpitz', 'nvme', 'iwlwifi']:
                for entry in entries:
                    if entry.current and entry.current > 0:
                        return float(entry.current)
    except Exception:
        pass
    return 35.0


def _save_bsm_settings(updates: dict) -> bool:
    """Aplica configurações em /etc/big-screen-monitor-display/settings.json."""
    data = {}
    if os.path.exists(BSM_SETTINGS_PATH):
        try:
            with open(BSM_SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Erro ao ler {BSM_SETTINGS_PATH}: {e}")

    data.update(updates)

    # Também atualiza no bloco de cada display DeepCool se existir
    displays = data.get("displays", {})
    for _disp_id, disp_cfg in displays.items():
        if disp_cfg.get("profile") == "deepcool_ak" or "ak" in disp_cfg.get("name", "").lower():
            for k, v in updates.items():
                if k.startswith("dc_") or k == "led_color":
                    disp_cfg[k] = v

    # Se gravável diretamente, salva atômico
    if os.access(os.path.dirname(BSM_SETTINGS_PATH), os.W_OK) and (not os.path.exists(BSM_SETTINGS_PATH) or os.access(BSM_SETTINGS_PATH, os.W_OK)):
        try:
            tmp = BSM_SETTINGS_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, BSM_SETTINGS_PATH)
            logger.info("Configurações salvas diretamente no settings.json")
            return True
        except Exception as e:
            logger.warning(f"Erro ao salvar diretamente: {e}")

    # Fallback: executa via helper polkit (autorizado sem senha pelo bsm-helper)
    if os.path.exists(BSM_HELPER):
        try:
            res = subprocess.run(
                ["pkexec", BSM_HELPER, "apply-settings"],
                input=json.dumps(data), text=True, capture_output=True, timeout=10
            )
            if res.returncode == 0:
                logger.info("Configurações salvas via bsm-helper")
                return True
            logger.warning(f"bsm-helper retornou {res.returncode}: {res.stderr}")
        except Exception as e:
            logger.error(f"Erro ao executar bsm-helper: {e}")

    return False


class DeepCoolTray:
    """Gerencia o ícone na bandeja e o menu de contexto exclusivo para o DeepCool."""

    def __init__(self, app: QApplication, product_id: int, model: str, sensor: str):
        self.app: QApplication = app
        self.product_id: int = product_id
        self.model: str = model
        self.sensor: str = sensor

        # Estado inicial
        self.connected: bool = True
        self.current_temp: float = 0.0
        self.current_cpu: int = 0

        # Configurações padrão
        self.display_mode: str = "auto"   # "temp", "util", "auto"
        self.temp_unit: str = "C"         # "C", "F"
        self.alarm_enabled: bool = True
        self.alarm_temp: int = 90
        self._led_color: str = COLOR_DEFAULT
        self._openrgb_device_id: Optional[int] = None

        # Carregar configurações salvas
        self._load_settings()

        # Aplicar cor salva em background
        self._apply_led_color_async()

        # System Tray Icon
        self.tray: QSystemTrayIcon = QSystemTrayIcon()
        self.tray.setIcon(create_deepcool_icon(False))
        self.tray.setToolTip(f"DeepCool Digital - {tr('connecting')}")

        # Menu
        self.menu: QMenu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)

        # Timer de atualização periódica
        self.timer: QTimer = QTimer()
        self.timer.timeout.connect(self._poll_status)
        self.timer.start(INTERVAL * 1000)

        logger.info("Interface system tray inicializada com sucesso")

    def _load_settings(self) -> None:
        """Carrega configurações do settings.json do BSM e do arquivo local."""
        # 1. Carrega do settings.json global se existir
        if os.path.exists(BSM_SETTINGS_PATH):
            try:
                with open(BSM_SETTINGS_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                dc_main = data.get("dc_main", "auto")
                if dc_main == "temp":
                    self.display_mode = "temp"
                elif dc_main == "usage":
                    self.display_mode = "util"
                else:
                    self.display_mode = "auto"

                unit = data.get("dc_temp_unit", "c")
                self.temp_unit = "F" if unit.lower() == "f" else "C"
                self.alarm_enabled = bool(data.get("dc_alarm", True))
                self.alarm_temp = int(data.get("dc_alarm_temp", 90))
                if data.get("led_color"):
                    self._led_color = data["led_color"]
            except Exception as e:
                logger.warning(f"Erro ao carregar settings do BSM: {e}")

        # 2. Carrega preferências locais se existirem
        if SETTINGS_FILE.exists():
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    local_saved = json.load(f)
                if "led_color" in local_saved:
                    self._led_color = local_saved["led_color"]
                if "openrgb_device_id" in local_saved:
                    self._openrgb_device_id = local_saved["openrgb_device_id"]
            except Exception:
                pass

    def _save_settings(self) -> None:
        """Salva configurações tanto no settings.json do sistema quanto no local."""
        # Mapeamento para o formato do screen-monitor-display
        dc_main = "temp" if self.display_mode == "temp" else ("usage" if self.display_mode == "util" else "auto")
        dc_preset = "custom" if self.display_mode == "temp" else ("performance" if self.display_mode == "util" else "essentials")

        updates = {
            "dc_main": dc_main,
            "dc_preset": dc_preset,
            "dc_temp_unit": self.temp_unit.lower(),
            "dc_alarm": self.alarm_enabled,
            "dc_alarm_temp": self.alarm_temp,
            "led_color": self._led_color,
        }
        _save_bsm_settings(updates)

        # Salva localmente em ~/.config/deepcool-digital/settings.json
        try:
            SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
            local_data = {
                "display_mode": self.display_mode,
                "temp_unit": self.temp_unit,
                "alarm_enabled": self.alarm_enabled,
                "alarm_temp": self.alarm_temp,
                "led_color": self._led_color,
                "openrgb_device_id": self._openrgb_device_id,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(local_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Erro ao salvar localmente: {e}")

    def _apply_led_color_async(self) -> None:
        """Aplica a cor LED salva em background."""
        def _apply():
            if is_openrgb_available():
                success = apply_color_setting(self._led_color, self._openrgb_device_id)
                if success:
                    logger.info(f"Cor LED aplicada: {self._led_color}")
                else:
                    logger.warning(f"Falha ao aplicar cor LED: {self._led_color}")

        thread = threading.Thread(target=_apply, daemon=True)
        thread.start()

    def start(self) -> None:
        """Exibe o ícone e realiza a primeira leitura."""
        self.tray.show()
        self._poll_status()
        logger.info("System tray exibido")

    def _build_menu(self) -> None:
        """Constrói o menu de contexto completo exatamente como no projeto original."""
        self.menu.clear()

        self.menu.setStyleSheet("""
            QMenu {
                background-color: palette(window);
                border: 1px solid palette(mid);
                padding: 5px 0px;
            }
            QMenu::item {
                padding: 7px 35px 7px 20px;
                font-size: 13px;
            }
            QMenu::item:selected {
                background-color: palette(highlight);
                color: palette(highlighted-text);
            }
            QMenu::item:disabled {
                color: palette(dark);
            }
            QMenu::separator {
                height: 1px;
                background: palette(mid);
                margin: 5px 12px;
            }
        """)

        # ── Dispositivo ──
        device_menu: QMenu = self.menu.addMenu(f"  {self.model}")
        self._add_disabled(device_menu, f"Vendor: 0x{VENDOR_ID:04X}")
        self._add_disabled(device_menu, f"Product: 0x{self.product_id:04X}")
        self._add_disabled(device_menu, f"Sensor: {self.sensor}")

        self.menu.addSeparator()

        # ── Status (atualiza em tempo real) ──
        self.status_action: QAction = self._add_disabled(
            self.menu, "  🌡️ --°C │ 📊 --%"
        )
        self.connection_action: QAction = self._add_disabled(
            self.menu, f"  ⏳ {tr('connecting')}"
        )

        self.menu.addSeparator()

        # ── Display Switch (Exibir) ──
        display_menu: QMenu = self.menu.addMenu(f"  {tr('display_switch')}")
        self.display_group: QActionGroup = QActionGroup(self.menu)
        self.display_group.setExclusive(True)

        for mode, key in [("temp", "temperature"), ("util", "utilization"), ("auto", "automatic")]:
            action: QAction = QAction(tr(key), self.menu, checkable=True)
            action.setData(mode)
            action.setChecked(mode == self.display_mode)
            action.triggered.connect(lambda _, m=mode: self._set_display_mode(m))
            self.display_group.addAction(action)
            display_menu.addAction(action)

        # ── Temperature Display (Mostrador de temperatura) ──
        temp_menu: QMenu = self.menu.addMenu(f"  {tr('temp_display')}")
        self.temp_group: QActionGroup = QActionGroup(self.menu)
        self.temp_group.setExclusive(True)

        for unit, label in [("C", "Celsius (°C)"), ("F", "Fahrenheit (°F)")]:
            action = QAction(label, self.menu, checkable=True)
            action.setChecked(unit == self.temp_unit)
            action.triggered.connect(lambda _, u=unit: self._set_temp_unit(u))
            self.temp_group.addAction(action)
            temp_menu.addAction(action)

        # ── Alarm Control (Controle de alarme) ──
        alarm_menu: QMenu = self.menu.addMenu(f"  {tr('alarm_control')}")
        self.alarm_group: QActionGroup = QActionGroup(self.menu)
        self.alarm_group.setExclusive(True)

        alarm_off: QAction = QAction(tr("alarm_off"), self.menu, checkable=True)
        alarm_off.setChecked(not self.alarm_enabled)
        alarm_off.triggered.connect(lambda: self._set_alarm(False, 0))
        self.alarm_group.addAction(alarm_off)
        alarm_menu.addAction(alarm_off)

        alarm_menu.addSeparator()

        for temp_val in ALARM_TEMPS:
            temp_display, unit = format_temperature(float(temp_val), self.temp_unit)
            label: str = f"{temp_display}{unit}"
            if self.temp_unit == 'F':
                label += f" ({temp_val}°C)"

            action = QAction(label, self.menu, checkable=True)
            action.setChecked(self.alarm_enabled and self.alarm_temp == temp_val)
            action.triggered.connect(lambda _, t=temp_val: self._set_alarm(True, t))
            self.alarm_group.addAction(action)
            alarm_menu.addAction(action)

        self.menu.addSeparator()

        # ── Cor da borda LED (OpenRGB) ──
        self._build_color_menu()

        self.menu.addSeparator()

        # ── Launch at startup ──
        self.autostart_action: QAction = QAction(
            f"  {tr('launch_startup')}", self.menu, checkable=True
        )
        self.autostart_action.setChecked(autostart.is_enabled())
        self.autostart_action.triggered.connect(self._toggle_autostart)
        self.menu.addAction(self.autostart_action)

        # ── Support ──
        support_menu: QMenu = self.menu.addMenu(f"  {tr('support')}")
        website: QAction = QAction(tr("website"), self.menu)
        website.triggered.connect(self._open_website)
        support_menu.addAction(website)
        self._add_disabled(support_menu, f"{tr('version')}: {VERSION}")

        self.menu.addSeparator()

        # ── Restart ──
        restart_action: QAction = QAction(f"  {tr('restart')}", self.menu)
        restart_action.triggered.connect(self._restart_service)
        self.menu.addAction(restart_action)

        # ── Exit ──
        quit_action: QAction = QAction(f"  {tr('exit')}", self.menu)
        quit_action.triggered.connect(self._quit)
        self.menu.addAction(quit_action)

    def _build_color_menu(self) -> None:
        """Constrói o submenu 'Cor da borda' com cores predefinidas, arco-íris, desligado e personalizar."""
        openrgb_ok = is_openrgb_available()
        is_rainbow = self._led_color == COLOR_RAINBOW
        is_off = self._led_color in (COLOR_OFF, "off")

        if not openrgb_ok:
            disabled_menu: QMenu = self.menu.addMenu(f"  🎨 {tr('color_menu_disabled')}")
            disabled_menu.setEnabled(False)
            return

        color_menu: QMenu = QMenu(f"  🎨 {tr('color_menu_title')}", self.menu)
        color_menu.setIcon(make_color_icon(
            self._led_color if not is_rainbow and not is_off else None,
            is_rainbow=is_rainbow,
            is_off=is_off,
        ))
        self.menu.addMenu(color_menu)

        color_group = QActionGroup(color_menu)
        color_group.setExclusive(True)

        for i18n_key, hex_color in PRESET_COLORS:
            action = QAction(tr(i18n_key), color_menu, checkable=True)
            action.setIcon(make_color_icon(hex_color))
            action.setChecked(not is_rainbow and not is_off and self._led_color.upper() == hex_color.upper())
            action.triggered.connect(lambda _, c=hex_color: self._on_color_selected(c))
            color_group.addAction(action)
            color_menu.addAction(action)

        rainbow_action = QAction(tr("color_rainbow"), color_menu, checkable=True)
        rainbow_action.setIcon(make_color_icon(is_rainbow=True))
        rainbow_action.setChecked(is_rainbow)
        rainbow_action.triggered.connect(lambda: self._on_color_selected(COLOR_RAINBOW))
        color_group.addAction(rainbow_action)
        color_menu.addAction(rainbow_action)

        off_action = QAction(tr("color_off"), color_menu, checkable=True)
        off_action.setIcon(make_color_icon(is_off=True))
        off_action.setChecked(is_off)
        off_action.triggered.connect(lambda: self._on_color_selected(COLOR_OFF))
        color_group.addAction(off_action)
        color_menu.addAction(off_action)

        color_menu.addSeparator()

        custom_action = QAction(f"🎨 {tr('color_customize')}", color_menu)
        custom_action.triggered.connect(self._on_custom_color)
        color_menu.addAction(custom_action)

    def _on_color_selected(self, color_value: str) -> None:
        """Callback quando uma cor é selecionada."""
        self._led_color = color_value

        def _apply():
            apply_color_setting(color_value, self._openrgb_device_id)

        threading.Thread(target=_apply, daemon=True).start()
        self._save_settings()
        self._build_menu()

    def _on_custom_color(self) -> None:
        """Abre QColorDialog para cor personalizada."""
        if self._led_color in (COLOR_RAINBOW, COLOR_OFF, "off"):
            initial = QColor(COLOR_DEFAULT)
        else:
            initial = QColor(self._led_color)

        color = QColorDialog.getColor(initial, None, tr('color_dialog_title'))
        if color.isValid():
            hex_color = color.name().upper()
            self._on_color_selected(hex_color)

    @staticmethod
    def _add_disabled(menu: QMenu, text: str) -> QAction:
        action = QAction(text, menu)
        action.setEnabled(False)
        menu.addAction(action)
        return action

    def _set_display_mode(self, mode: str) -> None:
        self.display_mode = mode
        self._save_settings()
        logger.info(f"Modo de exibição alterado para: {mode}")

    def _set_temp_unit(self, unit: str) -> None:
        self.temp_unit = unit
        self._save_settings()
        self._build_menu()
        logger.info(f"Unidade de temperatura alterada para: {unit}")

    def _set_alarm(self, enabled: bool, temp: int) -> None:
        self.alarm_enabled = enabled
        self.alarm_temp = temp
        self._save_settings()
        logger.info(f"Alarme configurado: enabled={enabled}, temp={temp}°C")

    def _toggle_autostart(self) -> None:
        if self.autostart_action.isChecked():
            autostart.enable()
            logger.info("Autostart habilitado")
        else:
            autostart.disable()
            logger.info("Autostart desabilitado")

    def _open_website(self) -> None:
        try:
            subprocess.Popen(['xdg-open', GITHUB_URL])
        except Exception as e:
            logger.error(f"Erro ao abrir website: {e}")

    def _restart_service(self) -> None:
        logger.info("Reiniciando serviço do monitor...")
        subprocess.Popen(["systemctl", "--user", "restart", "big-screen-monitor-display.service"])
        # Se for serviço de sistema:
        if os.path.exists(BSM_HELPER):
            subprocess.Popen(["pkexec", "systemctl", "restart", "big-screen-monitor-display.service"])

    def _quit(self) -> None:
        logger.info("Encerrando aplicativo da bandeja...")
        self._save_settings()
        self.timer.stop()
        self.tray.hide()
        self.app.quit()

    def _poll_status(self) -> None:
        """Consulta o hardware e atualiza o ícone e menu da bandeja."""
        temp_c = _read_cpu_temp(self.sensor)
        try:
            cpu_percent = int(round(psutil.cpu_percent(interval=None)))
        except Exception:
            cpu_percent = 0

        # Verifica conectividade via status.json do backend se existir
        is_connected = True
        if os.path.exists(BSM_STATUS_PATH):
            try:
                with open(BSM_STATUS_PATH, "r", encoding="utf-8") as f:
                    st = json.load(f)
                # Procura o display DeepCool
                found_dc = False
                for disp in st.get("displays", []):
                    if disp.get("settings", {}).get("profile") == "deepcool_ak" or "ak" in disp.get("name", "").lower():
                        found_dc = True
                        if disp.get("state") not in ("healthy", "degraded"):
                            is_connected = False
                        break
                if found_dc is False and st.get("displays"):
                    # Se há displays mas o DeepCool não está presente
                    is_connected = False
            except Exception:
                pass

        self.connected = is_connected
        self.current_temp = temp_c
        self.current_cpu = cpu_percent

        temp_display, unit = format_temperature(temp_c, self.temp_unit)

        self.status_action.setText(f"  🌡️ {temp_display}{unit} │ 📊 {cpu_percent}%")
        if self.connected:
            self.connection_action.setText(f"  ✅ {tr('connected')}")
            self.tray.setToolTip(f"DeepCool {self.model}\n{temp_display}{unit} │ CPU: {cpu_percent}%")
            self.tray.setIcon(create_status_icon(temp_display, unit, True, temp_celsius=temp_c))
        else:
            self.connection_action.setText(f"  ❌ {tr('disconnected')}")
            self.tray.setToolTip(f"DeepCool {self.model}\n{tr('disconnected')}")
            self.tray.setIcon(create_deepcool_icon(False))
