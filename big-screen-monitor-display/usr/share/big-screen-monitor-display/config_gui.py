import sys
import json
import os

# Suprime os avisos relacionados a Vulkan não suportado no GTK4
os.environ["GSK_RENDERER"] = "cairo"

import gi
import subprocess

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, GLib

CONFIG_FILE = os.path.expanduser("~/.config/big-screen-monitor/settings.json")

def load_settings():
    default_settings = {
        "model": "auto",
        "size": "3.5",
        "orientation": "horizontal",
        "brightness": 70,
        "theme": "dark",
        "network_iface": "auto"
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                settings = json.load(f)
                default_settings.update(settings)
        except Exception as e:
            print(f"Erro ao carregar configurações: {e}")
            
    return default_settings

def save_settings(settings):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception as e:
        print(f"Erro ao salvar configurações: {e}")
        return False

class BigScreenConfigWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Configurações do Monitor")
        self.set_default_size(600, 700)
        
        self.settings = load_settings()

        # Layout principal
        self.toast_overlay = Adw.ToastOverlay.new()
        self.set_content(self.toast_overlay)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.toast_overlay.set_child(box)

        # HeaderBar
        header = Adw.HeaderBar()
        box.append(header)

        # Logo no canto superior esquerdo
        logo_img = Gtk.Image.new_from_icon_name("big-screen-monitor-display")
        logo_img.set_pixel_size(24)
        logo_img.set_margin_start(10)
        header.pack_start(logo_img)

        # Menu Button (Pack End)
        menu_btn = self._create_menu_button()
        header.pack_end(menu_btn)

        # Scrollable preferences
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        box.append(scrolled)

        page = Adw.PreferencesPage()
        scrolled.set_child(page)

        # ================= CONFIGURAÇÕES DO DISPLAY =================
        group_display = Adw.PreferencesGroup()
        group_display.set_title("Configurações do Display")
        group_display.set_description("Ajuste as opções de hardware do seu monitor.")
        page.add(group_display)

        # Modelos
        model_model = Gtk.StringList.new(["Detectar Automaticamente", "AX206 (Turing Smart Screen)", "Outro (Genérico)"])
        self.combo_model = Adw.ComboRow(title="Modelo do Display", model=model_model)
        
        if self.settings["model"] == "auto":
            self.combo_model.set_selected(0)
        elif self.settings["model"] == "ax206":
            self.combo_model.set_selected(1)
        else:
            self.combo_model.set_selected(2)
        group_display.add(self.combo_model)

        # Tamanho
        size_model = Gtk.StringList.new(["3.5\"", "5\"", "8.8\"", "2.1\" / 2.8\""])
        self.combo_size = Adw.ComboRow(title="Tamanho do Display", model=size_model)
        size_map = {"3.5": 0, "5": 1, "8.8": 2, "2.1": 3}
        self.combo_size.set_selected(size_map.get(self.settings["size"], 0))
        group_display.add(self.combo_size)

        # Orientação
        orientation_model = Gtk.StringList.new(["Horizontal (Landscape)", "Vertical (Portrait)"])
        self.combo_orientation = Adw.ComboRow(title="Orientação", model=orientation_model)
        self.combo_orientation.set_selected(0 if self.settings["orientation"] == "horizontal" else 1)
        group_display.add(self.combo_orientation)

        # Brilho de 10 a 100 (evitando 0 para não apagar a tela)
        self.scale_brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 10)
        self.scale_brightness.set_value(self.settings["brightness"])
        self.scale_brightness.set_hexpand(True)
        self.scale_brightness.set_valign(Gtk.Align.CENTER)
        self.scale_brightness.set_draw_value(True)
        self.scale_brightness.set_value_pos(Gtk.PositionType.RIGHT)
        
        row_brightness = Adw.ActionRow(title="Brilho")
        row_brightness.add_suffix(self.scale_brightness)
        group_display.add(row_brightness)


        # ================= CONFIGURAÇÕES DO MONITOR DO SISTEMA =================
        group_system = Adw.PreferencesGroup()
        group_system.set_title("Monitor do Sistema")
        group_system.set_description("Personalize os relatórios e estatísticas do painel.")
        page.add(group_system)

        # Tema
        theme_model = Gtk.StringList.new(["Escuro (Dark)", "Claro (Light)", "Neon", "Cyberpunk"])
        self.combo_theme = Adw.ComboRow(title="Tema de Interface", model=theme_model)
        theme_map = {"dark": 0, "light": 1, "neon": 2, "cyberpunk": 3}
        self.combo_theme.set_selected(theme_map.get(self.settings["theme"], 0))
        group_system.add(self.combo_theme)

        # Interface de Rede Principal
        net_model = Gtk.StringList.new(["Detectar Automaticamente", "Ethernet (Cabo)", "Wi-Fi"])
        self.combo_net = Adw.ComboRow(title="Conexão Principal", model=net_model)
        net_map = {"auto": 0, "eth": 1, "wifi": 2}
        self.combo_net.set_selected(net_map.get(self.settings["network_iface"], 0))
        group_system.add(self.combo_net)

        # ================= INICIALIZAÇÃO DO SISTEMA =================
        group_startup = Adw.PreferencesGroup()
        group_startup.set_title("Inicialização")
        group_startup.set_description("Gerencie como o monitor inicia com o seu computador.")
        page.add(group_startup)

        self.switch_startup = Adw.SwitchRow(title="Iniciar com o sistema", 
                                            subtitle="Ativa o serviço no boot do computador")
        # Verifica se o serviço está habilitado para definir o estado inicial
        self.switch_startup.set_active(self.check_service_status())
        self.switch_startup.connect("notify::active", self.on_startup_toggled)
        group_startup.add(self.switch_startup)


        # ================= FOOTER / BOTÕES DE AÇÃO =================
        footer_bin = Adw.Bin()
        footer_bin.add_css_class("footer")
        box.append(footer_bin)

        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        action_box.set_margin_top(14)
        action_box.set_margin_bottom(14)
        action_box.set_margin_start(14)
        action_box.set_margin_end(14)
        action_box.set_halign(Gtk.Align.CENTER)
        footer_bin.set_child(action_box)

        # Restaurar
        btn_restore = Gtk.Button(label="Restaurar Padrões")
        btn_restore.set_size_request(160, -1)
        btn_restore.connect("clicked", self.on_restore_clicked)
        action_box.append(btn_restore)

        # Aplicar e Reiniciar
        btn_apply_restart = Gtk.Button(label="Salvar e Reiniciar")
        btn_apply_restart.set_size_request(160, -1)
        btn_apply_restart.add_css_class("suggested-action")
        btn_apply_restart.connect("clicked", self.on_restart_clicked)
        action_box.append(btn_apply_restart)

        # Sair
        btn_exit = Gtk.Button(label="Sair")
        btn_exit.set_size_request(120, -1)
        btn_exit.add_css_class("destructive-action")
        btn_exit.connect("clicked", self.on_cancel_clicked)
        action_box.append(btn_exit)

    def _create_menu_button(self):
        menu = Gio.Menu.new()
        section = Gio.Menu.new()
        section.append("Sobre", "app.about")
        section.append("Restaurar Padrões", "app.restore")
        section.append("Sair", "app.quit")
        menu.append_section(None, section)
        
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text("Menu principal")
        menu_button.set_css_classes(["flat"])
        return menu_button

    def _get_current_settings(self):
        # Mapeamento reverso
        model_map = {0: "auto", 1: "ax206", 2: "other"}
        size_map = {0: "3.5", 1: "5", 2: "8.8", 3: "2.1"}
        theme_map = {0: "dark", 1: "light", 2: "neon", 3: "cyberpunk"}
        net_map = {0: "auto", 1: "eth", 2: "wifi"}

        return {
            "model": model_map[self.combo_model.get_selected()],
            "size": size_map[self.combo_size.get_selected()],
            "orientation": "horizontal" if self.combo_orientation.get_selected() == 0 else "vertical",
            "brightness": int(self.scale_brightness.get_value()),
            "theme": theme_map[self.combo_theme.get_selected()],
            "network_iface": net_map[self.combo_net.get_selected()]
        }

    def on_cancel_clicked(self, button):
        self.close()

    def on_apply_clicked(self, button):
        new_settings = self._get_current_settings()
        if save_settings(new_settings):
            print("Configurações salvas!")
            self.show_toast("Configurações salvas com sucesso.")

    def on_restore_clicked(self, button):
        default_settings = {
            "model": "auto",
            "size": "3.5",
            "orientation": "horizontal",
            "brightness": 70,
            "theme": "dark",
            "network_iface": "auto"
        }
        self.settings = default_settings
        
        # Atualiza UI
        self.combo_model.set_selected(0)
        self.combo_size.set_selected(0)
        self.combo_orientation.set_selected(0)
        self.scale_brightness.set_value(70)
        self.combo_theme.set_selected(0)
        self.combo_net.set_selected(0)
        
        self.show_toast("Padrões restaurados. Clique em Salvar para aplicar.")

    def on_restart_clicked(self, button):
        self.on_apply_clicked(button)
        self.show_toast("Configurações salvas. Reiniciando serviço...")
        
        # O serviço está em /usr/lib/systemd/system/, então é um serviço de sistema.
        # Tentamos reiniciar via systemctl (pode pedir senha via polkit se o ambiente permitir)
        try:
            # Tenta reiniciar o serviço de sistema
            # Em distros como BigLinux, o polkit pode permitir isso sem senha se configurado,
            # ou abrirá um prompt gráfico de senha.
            res = subprocess.run(["systemctl", "restart", "big-screen-monitor-display.service"], 
                                 capture_output=True, text=True)
            
            if res.returncode != 0:
                # Se falhar, tenta com pkexec para garantir prompt de senha gráfico
                subprocess.Popen(["pkexec", "systemctl", "restart", "big-screen-monitor-display.service"])
                self.show_toast("Solicitando autorização para reiniciar...")
            else:
                self.show_toast("Serviço reiniciado com sucesso!")
        except Exception as e:
            print(f"Erro ao reiniciar: {e}")
            self.show_toast("Erro ao reiniciar serviço.")

    def check_service_status(self):
        """Verifica se o serviço está habilitado no systemd."""
        try:
            res = subprocess.run(["systemctl", "is-enabled", "big-screen-monitor-display.service"], 
                                 capture_output=True, text=True)
            return res.stdout.strip() == "enabled"
        except:
            return False

    def on_startup_toggled(self, row, pspec):
        """Ativa ou desativa o serviço no boot."""
        is_active = self.switch_startup.get_active()
        cmd = "enable" if is_active else "disable"
        
        try:
            # Tenta sem pkexec primeiro (pode estar no polkit do BigLinux)
            res = subprocess.run(["systemctl", cmd, "big-screen-monitor-display.service"], 
                                 capture_output=True, text=True)
            
            if res.returncode != 0:
                # Se falhar, usa pkexec para prompt de senha
                subprocess.Popen(["pkexec", "systemctl", cmd, "big-screen-monitor-display.service"])
                self.show_toast(f"Solicitando autorização para {'ativar' if is_active else 'desativar'}...")
            else:
                self.show_toast(f"Serviço {'ativado' if is_active else 'desativado'} com sucesso.")
        except Exception as e:
            print(f"Erro ao mudar estado: {e}")
            self.show_toast("Erro ao configurar inicialização.")
                
    def show_toast(self, message):
        toast = Adw.Toast.new(message)
        self.toast_overlay.add_toast(toast)
        print(f"TOAST: {message}")

class BigScreenConfigApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.github.ruscher.BigScreenConfig',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        
        win = self.props.active_window
        if not win:
            win = BigScreenConfigWindow(application=self)
            
            # Setup Actions (About, Restore, Quit)
            self._setup_actions(win)
            
        win.present()

    def _setup_actions(self, win):
        # About
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about_clicked)
        self.add_action(about_action)
        
        # Restore
        restore_action = Gio.SimpleAction.new("restore", None)
        restore_action.connect("activate", lambda *_: win.on_restore_clicked(None))
        self.add_action(restore_action)
        
        # Quit
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: win.close())
        self.add_action(quit_action)

    def _on_about_clicked(self, action, param):
        win = self.props.active_window
        about = Adw.AboutDialog(
            application_name="Big Screen Monitor Configuration",
            application_icon="big-screen-monitor-display",
            developer_name="BigLinux Team",
            version="2.0.0",
            comments="Configure seu monitor AX206 e dashboard do sistema.",
            website="https://github.com/biglinux/big-screen-monitor-display",
            issue_url="https://github.com/biglinux/big-screen-monitor-display/issues",
            license_type=Gtk.License.GPL_3_0,
            copyright="© 2026 BigLinux Team",
        )
        about.present(win)

if __name__ == '__main__':
    app = BigScreenConfigApp()
    app.run(sys.argv)
