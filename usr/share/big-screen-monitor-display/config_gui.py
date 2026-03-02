import sys
import json
import os
import threading

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
        "network_iface": "auto",
        "gk_show_host": True,
        "gk_show_date": True,
        "gk_show_time": True,
        "gk_show_cpu": True,
        "gk_show_cores": False,
        "gk_show_proc": True,
        "gk_show_temp": True,
        "gk_show_disk": True,
        "gk_show_eth0": True,
        "gk_show_mem": True,
        "gk_show_swap": True,
        "gk_show_docker": False,
        "gk_show_ppp": False,
        "gk_show_vlan": False,
        "gk_show_sys": True,
        "gk_show_hda": True,
        "gk_show_inet": False,
        "gk_show_devices": True,
        "gk_show_media": True,
        "gk_show_uptime": True,
        "gk_show_battery": False,
        "gk_theme_color": "urlicht"
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                settings = json.load(f)
                default_settings.update(settings)
        except Exception:
            pass
            
    return default_settings

def save_settings(settings):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f, indent=4)
        return True
    except Exception:
        return False

class BigScreenConfigWindow(Adw.ApplicationWindow):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.set_title("Configurações do Monitor")
        self.set_default_size(600, 700)
        
        self.settings = load_settings()

        # Layout principal (REMOVIDO ToastOverlay conforme recomendacao UX)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(box)

        # HeaderBar
        header = Adw.HeaderBar()
        box.append(header)

        # Logo no canto superior esquerdo
        logo_img = Gtk.Image.new_from_icon_name("big-screen-monitor-display")
        logo_img.set_pixel_size(24)
        logo_img.set_margin_start(10)
        logo_img.set_tooltip_text("Logo Big Screen Monitor")
        # Orca properties
        logo_img.update_property([Gtk.AccessibleProperty.LABEL], ["Logo Big Screen Monitor"])
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
        self.combo_model = Adw.ComboRow(title="Modelo do Display", subtitle="Padrão: Auto", model=model_model)
        
        if self.settings["model"] == "auto":
            self.combo_model.set_selected(0)
        elif self.settings["model"] == "ax206":
            self.combo_model.set_selected(1)
        else:
            self.combo_model.set_selected(2)
        group_display.add(self.combo_model)

        # Tamanho
        size_model = Gtk.StringList.new(["3.5\"", "5\"", "8.8\"", "2.1\" / 2.8\""])
        self.combo_size = Adw.ComboRow(title="Tamanho do Display", subtitle="Padrão: 3.5\"", model=size_model)
        size_map = {"3.5": 0, "5": 1, "8.8": 2, "2.1": 3}
        self.combo_size.set_selected(size_map.get(self.settings["size"], 0))
        group_display.add(self.combo_size)

        # Orientação
        orientation_model = Gtk.StringList.new(["Horizontal (Landscape)", "Vertical (Portrait)"])
        self.combo_orientation = Adw.ComboRow(title="Orientação", subtitle="Rotação 90 graus", model=orientation_model)
        self.combo_orientation.set_selected(0 if self.settings["orientation"] == "horizontal" else 1)
        group_display.add(self.combo_orientation)

        # Brilho de 10 a 100
        self.scale_brightness = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 10)
        self.scale_brightness.set_value(self.settings["brightness"])
        self.scale_brightness.set_hexpand(True)
        self.scale_brightness.set_valign(Gtk.Align.CENTER)
        self.scale_brightness.set_draw_value(True)
        self.scale_brightness.set_value_pos(Gtk.PositionType.RIGHT)
        self.scale_brightness.set_tooltip_text("Ajustar Nível de Brilho")
        self.scale_brightness.update_property([Gtk.AccessibleProperty.LABEL], ["Deslizante de Brilho do Monitor"])
        
        row_brightness = Adw.ActionRow(title="Brilho")
        row_brightness.add_suffix(self.scale_brightness)
        group_display.add(row_brightness)


        # ================= CONFIGURAÇÕES DO MONITOR DO SISTEMA =================
        group_system = Adw.PreferencesGroup()
        group_system.set_title("Monitor do Sistema")
        group_system.set_description("Personalize os relatórios e estatísticas do painel.")
        page.add(group_system)

        # Tema
        theme_model = Gtk.StringList.new(["Escuro (Dark)", "Claro (Light)", "Neon", "Cyberpunk", "GKrellM"])
        self.combo_theme = Adw.ComboRow(title="Tema de Interface", subtitle="Cores da Tela", model=theme_model)
        theme_map = {"dark": 0, "light": 1, "neon": 2, "cyberpunk": 3, "gkrellm": 4}
        self.combo_theme.set_selected(theme_map.get(self.settings.get("theme", "dark"), 0))
        group_system.add(self.combo_theme)

        # ====== Expansão de configurações exclusivas do Gkrellm ======
        self.gkrellm_expander = Adw.ExpanderRow(title="Personalizar GKrellM")
        self.gkrellm_expander.set_subtitle("Escolha quais módulos, temas e sensores visíveis")
        self.gkrellm_expander.set_expanded(False)
        self.gkrellm_expander.set_visible(self.combo_theme.get_selected() == 4)
        
        self.combo_theme.connect("notify::selected", self.on_theme_changed)
        
        # Sub-temas e fontes
        gk_theme_model = Gtk.StringList.new(["Urlicht (Blue Neon)", "Classic (Fósforo Verde)", "Cyber-Red"])
        self.combo_gk_theme = Adw.ComboRow(title="Estilo Visual", model=gk_theme_model)
        val = self.settings.get("gk_theme_color", "urlicht")
        gk_tk_map = {"urlicht": 0, "classic": 1, "cyber_red": 2}
        self.combo_gk_theme.set_selected(gk_tk_map.get(val, 0))
        self.gkrellm_expander.add_row(self.combo_gk_theme)

        # Switches
        self.gk_switches = {}
        gk_options = [
            ("gk_show_host", "Nome do Host"),
            ("gk_show_date", "Data"),
            ("gk_show_time", "Hora"),
            ("gk_show_gpu", "GPU (Mem, Enc, Temp)"),
            ("gk_show_cpu", "Uso de CPU (Geral)"),
            ("gk_show_cores", "Selecionar CPUs Individualmente"),
            ("gk_show_temp", "Sensores / Temperaturas"),
            ("gk_show_proc", "Processos"),
            ("gk_show_disk", "Disco (Partições e NVMe)"),
            ("gk_show_eth0", "Trafégo de Rede (eth0)"),
            ("gk_show_mem", "Memória RAM"),
            ("gk_show_swap", "Memória SWAP"),
            ("gk_show_docker", "Containers Docker"),
            ("gk_show_ppp", "Conexões PPP"),
            ("gk_show_vlan", "Redes VLAN"),
            ("gk_show_sys", "Tensões do Sistema (sys)"),
            ("gk_show_hda", "I/O de Disco Físico (hda)"),
            ("gk_show_inet", "Monitoramento Inet0"),
            ("gk_show_devices", "Dispositivos (CD/Pendrive/Cards)"),
            ("gk_show_media", "Mídia Atual (PCM / CD)"),
            ("gk_show_uptime", "Tempo de Serviço (Uptime)"),
            ("gk_show_battery", "Status da Bateria")
        ]
        
        for key, title in gk_options:
            switch = Adw.SwitchRow(title=title)
            switch.set_active(self.settings.get(key, True))
            self.gk_switches[key] = switch
            self.gkrellm_expander.add_row(switch)
        
        group_system.add(self.gkrellm_expander)

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
        self.switch_startup.set_active(self.check_service_status())
        self.switch_startup.connect("notify::active", self.on_startup_toggled)
        group_startup.add(self.switch_startup)

        # Area de Mensagens Inline
        self.feedback_label = Gtk.Label(label="", wrap=True)
        self.feedback_label.add_css_class("dim-label")
        self.feedback_label.set_margin_top(10)
        self.feedback_label.set_margin_bottom(5)
        self.feedback_label.set_margin_start(20)
        self.feedback_label.set_margin_end(20)
        box.append(self.feedback_label)

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
        btn_restore.set_tooltip_text("Voltar para as configurações de fábrica")
        btn_restore.connect("clicked", self.on_restore_clicked)
        action_box.append(btn_restore)

        # Aplicar e Reiniciar
        self.btn_apply_restart = Gtk.Button(label="Salvar e Reiniciar")
        self.btn_apply_restart.set_size_request(160, -1)
        self.btn_apply_restart.add_css_class("suggested-action")
        self.btn_apply_restart.connect("clicked", self.on_restart_clicked)
        action_box.append(self.btn_apply_restart)

        # Sair
        btn_exit = Gtk.Button(label="Sair")
        btn_exit.set_size_request(120, -1)
        btn_exit.set_tooltip_text("Fechar a janela de configuração")
        btn_exit.connect("clicked", self.on_cancel_clicked)
        action_box.append(btn_exit)

    def _create_menu_button(self):
        menu = Gio.Menu.new()
        section = Gio.Menu.new()
        section.append("Sobre", "app.about")
        section.append("Sair", "app.quit")
        menu.append_section(None, section)
        
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_menu_model(menu)
        menu_button.set_tooltip_text("Menu principal")
        menu_button.update_property([Gtk.AccessibleProperty.LABEL], ["Menu de Opções Principais"])
        menu_button.set_css_classes(["flat"])
        return menu_button

    def _get_current_settings(self):
        model_map = {0: "auto", 1: "ax206", 2: "other"}
        size_map = {0: "3.5", 1: "5", 2: "8.8", 3: "2.1"}
        theme_map = {0: "dark", 1: "light", 2: "neon", 3: "cyberpunk", 4: "gkrellm"}
        net_map = {0: "auto", 1: "eth", 2: "wifi"}

        res = {
            "model": model_map[self.combo_model.get_selected()],
            "size": size_map[self.combo_size.get_selected()],
            "orientation": "horizontal" if self.combo_orientation.get_selected() == 0 else "vertical",
            "brightness": int(self.scale_brightness.get_value()),
            "theme": theme_map[self.combo_theme.get_selected()],
            "network_iface": net_map[self.combo_net.get_selected()]
        }
        
        gk_tk_map_rev = {0: "urlicht", 1: "classic", 2: "cyber_red"}
        res["gk_theme_color"] = gk_tk_map_rev[self.combo_gk_theme.get_selected()]
        for k, switch in self.gk_switches.items():
            res[k] = switch.get_active()
            
        return res

    def on_theme_changed(self, combo, pspec):
        self.gkrellm_expander.set_visible(combo.get_selected() == 4)

    def on_cancel_clicked(self, button):
        self.close()

    def show_feedback(self, message):
        """Visual feedback mechanism avoiding ToastOverlay anti-pattern"""
        self.feedback_label.set_label(f"<b>Informação:</b> {message}")
        self.feedback_label.set_use_markup(True)
        GLib.timeout_add(5000, lambda: self.feedback_label.set_label(""))

    def on_apply_clicked(self):
        new_settings = self._get_current_settings()
        if save_settings(new_settings):
            self.show_feedback("Configurações salvas no disco local.")
            return True
        return False

    def on_restore_clicked(self, button):
        # UX: Confirm before destructive action
        dialog = Adw.MessageDialog(heading="Restaurar Padrões?",
                                   body="Isso vai apagar todas as configurações e voltar ao padrão de fábrica. Tem certeza?",
                                   transient_for=self)
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("restore", "Limpar e Restaurar")
        dialog.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        
        def on_response(dlg, response):
            if response == "restore":
                self._do_restore()
                
        dialog.connect("response", on_response)
        dialog.present()

    def _do_restore(self):
        default_settings = {
            "model": "auto",
            "size": "3.5",
            "orientation": "horizontal",
            "brightness": 70,
            "theme": "dark",
            "network_iface": "auto",
        "gk_show_host": True,
        "gk_show_date": True,
        "gk_show_time": True,
        "gk_show_cpu": True,
        "gk_show_cores": False,
        "gk_show_proc": True,
        "gk_show_temp": True,
        "gk_show_disk": True,
        "gk_show_eth0": True,
        "gk_show_mem": True,
        "gk_show_swap": True,
        "gk_show_docker": False,
        "gk_show_ppp": False,
        "gk_show_vlan": False,
        "gk_show_sys": True,
        "gk_show_hda": True,
        "gk_show_inet": False,
        "gk_show_devices": True,
        "gk_show_media": True,
        "gk_show_uptime": True,
        "gk_show_battery": False,
        "gk_theme_color": "urlicht"
        }
        self.settings = default_settings
        self.combo_model.set_selected(0)
        self.combo_size.set_selected(0)
        self.combo_orientation.set_selected(0)
        self.scale_brightness.set_value(70)
        self.combo_theme.set_selected(0)
        self.combo_net.set_selected(0)
        
        self.show_feedback("Padrões aplicados. Clique em Salvar e Reiniciar para efetivar.")

    def _async_service_cmd(self, action, use_pkexec, cb):
        def worker():
            try:
                if use_pkexec:
                    subprocess.Popen(["pkexec", "systemctl", action, "big-screen-monitor-display.service"])
                    GLib.idle_add(cb, True, "Prompt de autorização enviado.")
                else:
                    res = subprocess.run(["systemctl", action, "big-screen-monitor-display.service"], capture_output=True, text=True, timeout=10)
                    success = res.returncode == 0
                    msg = "Sucesso" if success else f"Falha: {res.stderr}"
                    GLib.idle_add(cb, success, msg)
            except Exception as e:
                GLib.idle_add(cb, False, f"Erro: {str(e)}")
        threading.Thread(target=worker, daemon=True).start()

    def on_restart_clicked(self, button):
        if not self.on_apply_clicked():
            self.show_feedback("Erro ao salvar! O Serviço não será reiniciado.")
            return
            
        self.btn_apply_restart.set_sensitive(False)
        self.show_feedback("Salvando configurações e reiniciando serviço de background...")
        
        def on_result(success, msg):
            self.btn_apply_restart.set_sensitive(True)
            if success and "autorização" not in msg:
                self.show_feedback("✔ Reiniciado com sucesso!")
                self.btn_apply_restart.set_label("✔ Salvo!")
                GLib.timeout_add(3000, lambda: self.btn_apply_restart.set_label("Salvar e Reiniciar"))
            elif not success:
                # Tenta pkexec como fallback se systemctl restart falhou
                self._async_service_cmd("restart", True, lambda s, m: self.show_feedback(m))
        
        self._async_service_cmd("restart", False, on_result)

    def check_service_status(self):
        try:
            res = subprocess.run(["systemctl", "is-enabled", "big-screen-monitor-display.service"], 
                                 capture_output=True, text=True, timeout=2)
            return res.stdout.strip() == "enabled"
        except Exception:
            return False

    def on_startup_toggled(self, row, pspec):
        is_active = self.switch_startup.get_active()
        cmd = "enable" if is_active else "disable"
        
        self.show_feedback(f"Aplicando configuração de inicialização ({cmd})...")
        self.switch_startup.set_sensitive(False)
        
        def on_result(success, msg):
            self.switch_startup.set_sensitive(True)
            if success and "autorização" not in msg:
                self.show_feedback(f"Serviço de inicialização: {cmd} aplicado com sucesso.")
            elif not success:
                self._async_service_cmd(cmd, True, lambda s, m: self.show_feedback(m))
                
        self._async_service_cmd(cmd, False, on_result)

class BigScreenConfigApp(Adw.Application):
    def __init__(self):
        # ID válido para o D-Bus (requer ponto). O Wayland usará o prgname abaixo para o ícone.
        super().__init__(application_id='br.com.biglinux.BigScreenMonitorDisplay',
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        # O prgname deve coincidir com o nome do arquivo .desktop para o ícone aparecer no Wayland
        GLib.set_prgname('big-screen-monitor-display')
        GLib.set_application_name('Big Screen Monitor Display')

    def do_activate(self):
        # Configura o esquema de cores via Adw.StyleManager (forma correta no GTK4/Adwaita)
        style_manager = Adw.StyleManager.get_default()
        style_manager.set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        
        # Tenta desativar a propriedade antiga do GTK que gera alertas no Adwaita
        settings = Gtk.Settings.get_default()
        if settings:
            settings.set_property("gtk-application-prefer-dark-theme", False)
        
        win = self.props.active_window
        if not win:
            win = BigScreenConfigWindow(application=self)
            self._setup_actions(win)
        win.present()

    def _setup_actions(self, win):
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about_clicked)
        self.add_action(about_action)
        
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: win.close())
        self.add_action(quit_action)

    def _on_about_clicked(self, action, param):
        win = self.props.active_window
        
        history = (
            "Rafael Ruscher queria um mini display para compor seu gabinete com informações de hardware "
            "até que encontrou uma telinha pequena e simples, mas não se atentou que só funcionava no "
            "Windows e ainda precisava de software proprietário (AIDA64). Como ele não usava Windows e "
            "não tinha achado nada que funcionasse, deixou o dispositivo guardado por alguns anos.\n\n"
            "Um belo dia, organizando seu setup, encontrou novamente a tela e a vontade de fazê-la "
            "funcionar despertou. Juntando conhecimento técnico com o apoio de Inteligência Artificial, "
            "desenvolveu sua própria solução: agora como Software Livre, onde qualquer usuário Linux "
            "pode usar, modificar e distribuir. Excelente para quem não sai do htop ou gkrellm!"
        )

        about = Adw.AboutWindow(
            transient_for=win,
            application_name="Big Screen Monitor Display",
            application_icon="big-screen-monitor-display",
            version="3.0.0",
            developers=["Rafael Ruscher", "BigLinux Team"],
            copyright="© 2026 BigLinux Team",
            license_type=Gtk.License.GPL_3_0,
            comments=history,
            website="https://github.com/biglinux/big-screen-monitor-display",
            issue_url="https://github.com/biglinux/big-screen-monitor-display/issues",
            debug_info="Dependências do Sistema:\n"
                       "• python (>= 3.10)\n"
                       "• python-pillow\n"
                       "• python-psutil\n"
                       "• python-pyusb\n"
                       "• librsvg\n"
                       "• lm_sensors\n"
                       "• python-pystray"
        )
        about.present()

if __name__ == '__main__':
    app = BigScreenConfigApp()
    app.run(sys.argv)
