#!/usr/bin/env python3
"""
Solução Final e Absoluta para AX206 AIDA64 Display.
Com design moderno, ícones Emoji, multi-GPU e gráficos responsivos.
"""

import sys
import time
import struct
from datetime import datetime
import threading
import subprocess
import socket
import platform
import os
import glob
import json
import re

import usb.core
import usb.util
import psutil
import io
from PIL import Image, ImageDraw, ImageFont

# Tenta importar pystray apenas se houver um ambiente gráfico, para evitar erro no serviço systemd
pystray = None
if os.environ.get("DISPLAY"):
    try:
        import pystray
        from pystray import MenuItem as item
    except Exception:
        pystray = None
else:
    pystray = None

# Configurações de Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.expanduser("~/.config/big-screen-monitor/settings.json")

def get_settings():
    default_settings = {
        "model": "auto",
        "size": "3.5",
        "orientation": "horizontal",
        "brightness": 70,
        "theme": "dark",
        "network_iface": "auto"
    }
    
    config_path = CONFIG_FILE
    
    # Se rodar como root, tenta encontrar o arquivo de config do usuário
    if os.getuid() == 0 and not os.path.exists(config_path):
        # Tenta pegar do ambiente se o sudo/pkexec passou
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            user_config = os.path.expanduser(f"~{sudo_user}/.config/big-screen-monitor/settings.json")
            if os.path.exists(user_config):
                config_path = user_config
        else:
            # Fallback: procura o primeiro usuário em /home que tenha a config
            for user_home in glob.glob("/home/*"):
                test_path = os.path.join(user_home, ".config/big-screen-monitor/settings.json")
                if os.path.exists(test_path):
                    config_path = test_path
                    break

    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                default_settings.update(json.load(f))
        except:
            pass
    return default_settings

def get_theme_colors(theme_name):
    themes = {
        "dark": {
            "bg": (18, 18, 25), "panel_bg": (30, 30, 40), "text_main": (255, 255, 255),
            "text_muted": (180, 180, 200), "text_label": (200, 200, 220), "time": (77, 217, 255),
            "good": (77, 217, 112), "warn": (249, 217, 35), "crit": (255, 85, 85),
            "vram": (215, 120, 255), "swap": (77, 150, 255), "disk": (200, 200, 200),
            "temp_line": (249, 100, 35), "bar_bg": (40, 40, 50), "border": (60, 60, 80),
            "icon_color": (255, 255, 255)
        },
        "light": {
            "bg": (240, 240, 245), "panel_bg": (255, 255, 255), "text_main": (20, 20, 30),
            "text_muted": (100, 100, 120), "text_label": (80, 80, 100), "time": (0, 120, 215),
            "good": (40, 167, 69), "warn": (255, 193, 7), "crit": (220, 53, 69),
            "vram": (111, 66, 193), "swap": (0, 123, 255), "disk": (108, 117, 125),
            "temp_line": (253, 126, 20), "bar_bg": (230, 230, 235), "border": (200, 200, 210),
            "icon_color": (40, 40, 45)
        },
        "neon": {
            "bg": (10, 5, 20), "panel_bg": (20, 10, 40), "text_main": (255, 255, 255),
            "text_muted": (255, 105, 180), "text_label": (0, 255, 255), "time": (255, 0, 255),
            "good": (57, 255, 20), "warn": (255, 255, 0), "crit": (255, 49, 49),
            "vram": (157, 0, 255), "swap": (0, 255, 255), "disk": (200, 200, 200),
            "temp_line": (255, 165, 0), "bar_bg": (40, 20, 60), "border": (80, 40, 120),
            "icon_color": (255, 255, 255)
        },
        "cyberpunk": {
            "bg": (2, 2, 4), "panel_bg": (10, 10, 15), "text_main": (253, 237, 5),
            "text_muted": (153, 143, 3), "text_label": (255, 99, 146), "time": (0, 240, 255),
            "good": (22, 198, 12), "warn": (253, 237, 5), "crit": (255, 25, 76),
            "vram": (138, 43, 226), "swap": (0, 240, 255), "disk": (200, 200, 200),
            "temp_line": (255, 140, 0), "bar_bg": (20, 20, 30), "border": (253, 237, 5),
            "icon_color": (255, 255, 255)
        }
    }
    # Fallback default para temas customizados ou incompletos
    theme = themes.get(theme_name, themes["dark"])
    if "icon_color" not in theme:
        theme["icon_color"] = (255, 255, 255) if theme_name != "light" else (40, 40, 45)
    return theme

# ================= BACKGROUND MONITOR =================
SYSTEM_STATS = {
    "cpu_percent": 0.0,
    "cpu_temp": "?°C",
    "ram_used_mb": 0,
    "ram_total_mb": 0,
    "ram_percent": 0.0,
    "swap_used_mb": 0,
    "swap_total_mb": 0,
    "swap_percent": 0.0,
    "disk_percent": 0.0,
    "disk_text": "0/0 GB",
    "net_rx_mbps": 0.0,
    "net_tx_mbps": 0.0,
    "gpus": [],
    "active_gpu_idx": 0,
    "procs": [],
    "hostname": socket.gethostname(),
    "kernel": platform.release(),
}

# Historico para linha CPU Temp, CPU Uso e RAM Uso
CPU_TEMP_HISTORY = [0] * 30
CPU_USAGE_HISTORY = [0] * 30
RAM_USAGE_HISTORY = [0] * 30

# Cache Global de Icones SVG 
ICON_CACHE = {}

def get_svg_icon(name, size, color=None):
    cache_key = f"{name}_{size}_{color}"
    if cache_key in ICON_CACHE:
        return ICON_CACHE[cache_key]
        
    path = os.path.join(BASE_DIR, "img", name)
    if os.path.exists(path):
        try:
            if color:
                with open(path, 'r') as f:
                    svg_data = f.read()
                
                # Converte tupla (R, G, B) para Hex
                c_hex = '#{:02x}{:02x}{:02x}'.format(*color) if isinstance(color, tuple) else color
                
                # Substituição robusta usando Regex: 
                # Pega #ffffff, #FFFFFF, #fff, #FFF e variações em stroke ou fill
                svg_data = re.sub(r'(stroke|fill)="#[fF]{3,6}"', r'\1="{}"'.format(c_hex), svg_data)
                # Caso não tenha aspas ou use aspas simples
                svg_data = re.sub(r'#[fF]{3,6}', c_hex, svg_data)
                
                p = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size)], 
                                   input=svg_data.encode('utf-8'),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            else:
                p = subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), path], 
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2)
            
            if p.returncode == 0:
                img = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
                ICON_CACHE[cache_key] = img
                return img
        except Exception:
            pass
    return None

def find_gpus():
    gpus = []
    # Vasculha todas as placas DRM em /sys/class/drm/
    for card in sorted(glob.glob("/sys/class/drm/card[0-9]")):
        if not os.path.exists(os.path.join(card, "device")):
            continue
            
        gpu_info = {
            "path": card,
            "name": "GPU Desconhecida",
            "percent": 0.0,
            "mem_used_mb": 0,
            "mem_total_mb": 0,
            "enc_percent": 0.0,
            "temp": "?°C"
        }
        
        uevent_path = os.path.join(card, "device", "uevent")
        pci_slot = ""
        if os.path.exists(uevent_path):
            try:
                with open(uevent_path, "r") as f:
                    for line in f:
                        if line.startswith("PCI_SLOT_NAME="):
                            pci_slot = line.split("=")[1].strip()
                            break
            except:
                pass
                
        if pci_slot:
            try:
                # Pega o nome dinâmico via lspci
                cmd = f"lspci -s {pci_slot} | sed -n 's/.*\\[\\(.*\\)\\].*/\\1/p'"
                out = subprocess.check_output(cmd, shell=True, text=True).strip()
                if out:
                    gpu_info["name"] = out.split("\n")[0][:20]
            except:
                pass

        if gpu_info["name"] == "GPU Desconhecida" and os.path.exists(uevent_path):
            try:
                with open(uevent_path, "r") as f:
                    content = f.read()
                    if "1002:7590" in content:
                        gpu_info["name"] = "RX 580"[:20]
                    elif "1002" in content:
                        gpu_info["name"] = "AMD Radeon"[:20]
                    elif "8086" in content:
                        gpu_info["name"] = "Intel"[:20]
                    elif "10de" in content:
                        gpu_info["name"] = "NVIDIA"[:20]
            except:
                pass
        
        # Garante que só será listada se for uma GPU real (removendo placa dummie sem nome)
        if gpu_info["name"] != "GPU Desconhecida":
            gpus.append(gpu_info)
            
    if not gpus:
        gpus.append({
            "path": None,
            "name": "GPU",
            "percent": 0.0,
            "mem_used_mb": 0,
            "mem_total_mb": 0,
            "enc_percent": 0.0,
            "temp": "?°C"
        })
        
    return gpus

def monitor_thread():
    last_net = psutil.net_io_counters()
    last_time = time.time()
    
    SYSTEM_STATS["gpus"] = find_gpus()
    gpu_switch_counter = 0
    
    while True:
        try:
            SYSTEM_STATS["cpu_percent"] = psutil.cpu_percent(interval=None)
            CPU_USAGE_HISTORY.append(SYSTEM_STATS["cpu_percent"])
            CPU_USAGE_HISTORY.pop(0)
            
            mem = psutil.virtual_memory()
            SYSTEM_STATS["ram_percent"] = mem.percent
            RAM_USAGE_HISTORY.append(mem.percent)
            RAM_USAGE_HISTORY.pop(0)
            
            SYSTEM_STATS["ram_used_mb"] = mem.used // 1048576
            SYSTEM_STATS["ram_total_mb"] = mem.total // 1048576
            
            try:
                swap = psutil.swap_memory()
                SYSTEM_STATS["swap_percent"] = swap.percent
                SYSTEM_STATS["swap_used_mb"] = swap.used // 1048576
                SYSTEM_STATS["swap_total_mb"] = swap.total // 1048576
            except:
                pass
                
            try:
                disk = psutil.disk_usage('/')
                SYSTEM_STATS["disk_percent"] = disk.percent
                SYSTEM_STATS["disk_text"] = f"{disk.used//(1024**3)} / {disk.total//(1024**3)} GB"
            except:
                pass
                
            net = psutil.net_io_counters()
            now = time.time()
            dt = now - last_time
            if dt > 0:
                rx_mbps = ((net.bytes_recv - last_net.bytes_recv) * 8) / (dt * 1e6)
                tx_mbps = ((net.bytes_sent - last_net.bytes_sent) * 8) / (dt * 1e6)
                SYSTEM_STATS["net_rx_mbps"] = rx_mbps
                SYSTEM_STATS["net_tx_mbps"] = tx_mbps
            last_net = net
            last_time = now

            try:
                procs = sorted([p.info for p in psutil.process_iter(['name', 'cpu_percent', 'memory_percent']) if p.info['cpu_percent'] is not None], 
                       key=lambda x: x['cpu_percent'], reverse=True)[:10]
                SYSTEM_STATS["procs"] = procs
            except:
                pass
            
            try:
                out = subprocess.check_output("sensors", shell=True, timeout=0.2, text=True)
                cpu_t_val = 0
                for line in out.splitlines():
                    if ("k10temp" in line or "coretemp" in line or "Tctl" in line or "Package id 0" in line or "Core 0" in line) and "+" in line and "°C" in line:
                        temp_str = line.split("+")[1].split("°C")[0].strip()
                        cpu_t_val = float(temp_str)
                        break
                
                if cpu_t_val > 0:
                    SYSTEM_STATS["cpu_temp"] = f"{cpu_t_val:.0f}°C"
                    CPU_TEMP_HISTORY.append(cpu_t_val)
                    CPU_TEMP_HISTORY.pop(0)
            except:
                pass

            if len(SYSTEM_STATS["gpus"]) > 1:
                gpu_switch_counter += 1
                if gpu_switch_counter >= 3:
                    SYSTEM_STATS["active_gpu_idx"] = (SYSTEM_STATS["active_gpu_idx"] + 1) % len(SYSTEM_STATS["gpus"])
                    gpu_switch_counter = 0

            # GPU Status
            for i, gpu in enumerate(SYSTEM_STATS["gpus"]):
                if not gpu["path"]: continue
                card_dev = os.path.join(gpu["path"], "device")
                try:
                    if os.path.exists(os.path.join(card_dev, "gpu_busy_percent")):
                        with open(os.path.join(card_dev, "gpu_busy_percent")) as f:
                            gpu["percent"] = float(f.read().strip())
                            
                    if os.path.exists(os.path.join(card_dev, "mem_info_vram_used")):
                        with open(os.path.join(card_dev, "mem_info_vram_used")) as f:
                            gpu["mem_used_mb"] = int(f.read().strip()) // 1048576
                        with open(os.path.join(card_dev, "mem_info_vram_total")) as f:
                            gpu["mem_total_mb"] = int(f.read().strip()) // 1048576
                            
                    if os.path.exists(os.path.join(card_dev, "vcn_busy_percent")):
                        with open(os.path.join(card_dev, "vcn_busy_percent")) as f:
                            val = f.read().strip()
                            gpu["enc_percent"] = float(val) if val.isdigit() else 0.0
                            
                    hwmon_path = glob.glob(os.path.join(card_dev, "hwmon", "hwmon*"))
                    if hwmon_path:
                        temp1_input = os.path.join(hwmon_path[0], "temp1_input")
                        if os.path.exists(temp1_input):
                            with open(temp1_input) as f:
                                gpu["temp"] = f"{int(f.read().strip()) // 1000}°C"
                except:
                    pass

        except Exception as e:
            pass
        
        time.sleep(1)

threading.Thread(target=monitor_thread, daemon=True).start()

# ================= COMUNICAÇÃO DISPLAY =================

class AX206_DPF:
    def __init__(self, vid=0x1908, pid=0x0102):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            print(f"❌ Display USB {hex(vid)}:{hex(pid)} não encontrado!")
            sys.exit(1)
            
        print(f"✅ Display Encontrado: {self.dev.manufacturer} {self.dev.product}")
        
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
                print("   ✓ Driver nativo desativado")
        except Exception:
            pass
            
        try:
            self.dev.set_configuration()
            # Pequeno delay para estabilização após handshake USB
            time.sleep(0.1)
        except:
            pass
            
        self.ep_out = 0x01
        self.ep_in = 0x81
        
        # Tenta detectar a resolução com retentativas
        self.width, self.height = 0, 0
        for _ in range(3):
            self.width, self.height = self.get_dimensions()
            if self.width > 0 and self.height > 0:
                break
            time.sleep(0.2)

        if self.width == 0 or self.height == 0:
            # Fallback seguro para o modelo mais comum
            self.width = 800
            self.height = 480
            print("⚠️ Nota: Resolução detectada como 800x480 (padrão)")
        else:
            print(f"📐 Resolução detectada: {self.width}x{self.height}")

    def scsi_wrap(self, cmd, dir_out=True, data=None):
        block_len = len(data) if data else 0
        cmd_padded = cmd.ljust(16, b'\x00')
        cbw_flags = 0x00 if dir_out else 0x80
        cbw = struct.pack("<4sIIBBb16s", b"USBC", 0xdeadbeef, block_len, cbw_flags, 0x00, len(cmd), cmd_padded)
                          
        try:
            self.dev.write(self.ep_out, cbw, timeout=1000)
        except Exception:
            return -1

        resp_data = None
        if block_len > 0:
            if dir_out:
                try:
                    self.dev.write(self.ep_out, data, timeout=3000)
                except Exception:
                    return -1
            else:
                try:
                    resp_data = self.dev.read(self.ep_in, block_len, timeout=4000)
                except Exception:
                    return -1

        try:
            csw = self.dev.read(self.ep_in, 13, timeout=5000)
            if len(csw) == 13 and csw[:4] == b"USBS":
                return resp_data if not dir_out else csw[12]
            else:
                return resp_data if not dir_out else 0
        except Exception:
            return resp_data if not dir_out else 0

    def get_dimensions(self):
        cmd = bytearray([0xcd, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
        res = self.scsi_wrap(cmd, dir_out=False, data=bytearray(5))
        if res != -1 and res is not None and len(res) == 5:
            w = res[0] | (res[1] << 8)
            h = res[2] | (res[3] << 8)
            return w, h
        return 0, 0

    def set_backlight(self, b):
        # Mapeia o valor de 10-100 (vindo do novo slider) para o hardware 1-7
        # Se b <= 7, assumimos que é uma versão antiga das configs e forçamos o mapeamento
        if b <= 7:
            # Legado: se for 0, vira 1 (mínimo ligado)
            hardware_b = max(1, int(b))
        else:
            # Novo: mapeia 10-100 para 1-7
            # 10% -> 1 (mínimo), 100% -> 7 (máximo)
            hardware_b = int(1 + (b - 10) * (7 - 1) / (100 - 10))
            # Garante limites
            hardware_b = max(1, min(7, hardware_b))
            
        cmd = bytearray([0xcd, 0, 0, 0, 0, 6, 0x01, 0x01, 0x00, hardware_b, 0x00, 0, 0, 0, 0, 0])
        self.scsi_wrap(cmd, dir_out=True, data=None)

    def draw(self, image, settings=None):
        # Handle orientation/rotation
        if settings and settings.get("orientation") == "vertical":
            # Rotate 90 degrees if vertical is desired on a landscape hardware
            # We assume internal rendering was done in (h, w) format
            image = image.rotate(90, expand=True)
            
        width, height = image.size
        # Fast RGB565 conversion - avoids DeprecationWarning
        img_bytes = image.convert("RGB").tobytes()
        
        rgb565 = bytearray(width * height * 2)
        for i in range(width * height):
            r = img_bytes[i*3]
            g = img_bytes[i*3+1]
            b = img_bytes[i*3+2]
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            rgb565[i*2] = (val >> 8) & 0xFF
            rgb565[i*2+1] = val & 0xFF

        self._draw_rgb565(rgb565, width, height)

    def _draw_rgb565(self, rgb565, width, height):
        x1 = width - 1
        y1 = height - 1
        cmd = bytearray([
            0xcd, 0x00, 0x00, 0x00, 0x00, 0x06, 0x12, 
            0x00, 0x00, 0x00, 0x00,
            x1 & 0xFF, (x1 >> 8) & 0xFF,
            y1 & 0xFF, (y1 >> 8) & 0xFF,
            0x00
        ])
        
        self.scsi_wrap(cmd, dir_out=True, data=rgb565)

# ================= RENDERIZACAO DA TELA =================

def get_os_release():
    info = {"PRETTY_NAME": "Linux", "LOGO": ""}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    info[k] = v.strip('"')
    except:
        pass
    return info

def get_text_width(d, text, font):
    try:
        return int(d.textlength(text, font=font))
    except AttributeError:
        try:
            return int(d.textbbox((0, 0), text, font=font)[2])
        except AttributeError:
            return int(font.getsize(text)[0])


def render_dashboard(width, height, settings):
    if settings.get("orientation") == "vertical":
        return render_dashboard_portrait(width, height, settings)
    return render_dashboard_landscape(width, height, settings)

def render_dashboard_portrait(width, height, settings):
    theme_colors = get_theme_colors(settings.get("theme", "dark"))
    bg_color = theme_colors["bg"]
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    # === FONTS ===
    try:
        font_dir = os.path.join(BASE_DIR, "fonts")
        font_time = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.04)) 
        font_lg = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.032))  
        font_md = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.024))  
        font_sm = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.022))       
        font_icon = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.015))     
    except:
        font_time = font_lg = font_md = font_sm = font_icon = ImageFont.load_default()

    os_info = get_os_release()
    pretty_name = os_info.get("PRETTY_NAME", "Linux")
    logo_name = os_info.get("LOGO", "")
    
    # === 1. HEADER PORTRAIT ===
    header_h = int(height * 0.12)
    d.rounded_rectangle((10, 10, width-10, header_h), radius=10, fill=theme_colors["panel_bg"])
    
    # Logo
    logo_path = f"/usr/share/pixmaps/{logo_name}.png"
    logo_offset = 20
    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            l_h = header_h - 30
            try:
                resamp = Image.Resampling.LANCZOS
            except AttributeError:
                resamp = Image.ANTIALIAS if hasattr(Image, "ANTIALIAS") else 1
            logo.thumbnail((l_h, l_h), resamp)
            img.paste(logo, (20, 15), mask=logo)
            logo_offset = logo.width + 30
        except Exception:
            pass

    # Simple clock in header
    now = datetime.now().strftime("%H:%M")
    time_w = get_text_width(d, now, font_time)
    d.text((width - time_w - 20, 20), now, fill=theme_colors["time"], font=font_time)
    
    # OS Name (font reduced) + Host + Kernel (Split lines)
    d.text((logo_offset, 18), pretty_name[:20], fill=theme_colors["text_main"], font=font_md)
    d.text((logo_offset, 48), f"{SYSTEM_STATS['hostname']}", fill=theme_colors["text_muted"], font=font_sm)
    d.text((logo_offset, 74), f"{SYSTEM_STATS['kernel']}", fill=theme_colors["text_muted"], font=font_sm)

    # Rede RX / TX below clock
    net_rx_icon = get_svg_icon("rx-symbolic.svg", int(height*0.022), theme_colors["icon_color"])
    net_tx_icon = get_svg_icon("tx-symbolic.svg", int(height*0.022), theme_colors["icon_color"])
    net_rx_t = f"{SYSTEM_STATS['net_rx_mbps']:.1f}"
    net_tx_t = f"{SYSTEM_STATS['net_tx_mbps']:.1f}"
    
    rx_w = get_text_width(d, net_rx_t, font_sm)
    tx_w = get_text_width(d, net_tx_t, font_sm)
    icon_sz = int(height*0.022)
    
    # Position TX first (rightmost)
    tx_x = width - tx_w - 20
    d.text((tx_x, 55), net_tx_t, fill=theme_colors["good"], font=font_sm)
    if net_tx_icon:
        img.paste(net_tx_icon, (tx_x - icon_sz - 4, 57), net_tx_icon)
        
    # Position RX to the left of TX
    rx_x = tx_x - icon_sz - 15 - rx_w
    d.text((rx_x, 55), net_rx_t, fill=theme_colors["good"], font=font_sm)
    if net_rx_icon:
        img.paste(net_rx_icon, (rx_x - icon_sz - 4, 57), net_rx_icon)

    # === PROGRESS BAR HELPER ===
    def draw_bar(x, y, w, h, percent, label, text_val, color, icon_name=""):
        icon_offset = 0
        if icon_name:
            icon_img = get_svg_icon(icon_name, int(height*0.025), theme_colors["icon_color"])
            if icon_img:
                img.paste(icon_img, (x, y-2), icon_img)
                icon_offset = icon_img.width + 8
            
        d.text((x + icon_offset, y), label, fill=theme_colors["text_label"], font=font_md)
        val_w = get_text_width(d, text_val, font=font_md)
        d.text((x + w - val_w, y), text_val, fill=theme_colors["text_main"], font=font_md)
        
        by = y + int(height * 0.035)
        d.rounded_rectangle((x, by, x + w, by + h), radius=h//2, fill=theme_colors["bar_bg"])
        fill_w = int(w * (percent / 100))
        if fill_w > h:
            d.rounded_rectangle((x, by, x + fill_w, by + h), radius=h//2, fill=color)

    # === VERTICAL STACK ===
    curr_y = header_h + 20
    row_w = width - 40
    row_h = int(height * 0.015)
    spacing = int(height * 0.08)

    # CPU section (Manual draw to match landscape style with colored temp)
    cpu_w = int(row_w * 0.55)
    cpu_temp = SYSTEM_STATS['cpu_temp']
    current_temp = CPU_TEMP_HISTORY[-1] if CPU_TEMP_HISTORY else 40
    temp_color = theme_colors["crit"] if current_temp > 85 else (theme_colors["warn"] if current_temp >= 50 else theme_colors["good"])
    
    # Icon
    icon_img = get_svg_icon("cpu-symbolic.svg", int(height*0.025), theme_colors["icon_color"])
    icon_w = 0
    if icon_img:
        img.paste(icon_img, (20, curr_y-2), icon_img)
        icon_w = icon_img.width + 8

    # Label "CPU " + "Temp"
    d.text((20 + icon_w, curr_y), "CPU ", fill=theme_colors["text_label"], font=font_md)
    off_cpu = get_text_width(d, "CPU ", font_md)
    d.text((20 + icon_w + off_cpu, curr_y), f"{cpu_temp}", fill=temp_color, font=font_md)

    # Value %
    val_txt = f"{SYSTEM_STATS['cpu_percent']:.0f}%"
    val_w = get_text_width(d, val_txt, font_md)
    d.text((20 + cpu_w - val_w, curr_y), val_txt, fill=theme_colors["text_main"], font=font_md)

    # Bar
    by = curr_y + int(height * 0.035)
    d.rounded_rectangle((20, by, 20 + cpu_w, by + row_h), radius=row_h//2, fill=theme_colors["bar_bg"])
    fill_w = int(cpu_w * (SYSTEM_STATS["cpu_percent"] / 100))
    if fill_w > row_h:
        d.rounded_rectangle((20, by, 20 + fill_w, by + row_h), radius=row_h//2, fill=theme_colors["warn"])
             
    # Graph on the right of CPU
    gx = 20 + cpu_w + 10
    gw = width - gx - 20
    gh = int(height * 0.05)
    d.rectangle((gx, curr_y, gx + gw, curr_y + gh), fill=theme_colors["panel_bg"], outline=theme_colors["border"])
    if len(CPU_USAGE_HISTORY) > 1:
        max_t = max(80, max(CPU_TEMP_HISTORY))
        min_t = 30
        step = gw / (len(CPU_USAGE_HISTORY) - 1)
        pts_cpu = []
        pts_ram = []
        pts_temp = []
        for i in range(len(CPU_USAGE_HISTORY)):
            px = gx + i*step
            pts_cpu.append((px, curr_y + gh - (CPU_USAGE_HISTORY[i]/100*gh)))
            pts_ram.append((px, curr_y + gh - (RAM_USAGE_HISTORY[i]/100*gh)))
            tv = max(min_t, min(CPU_TEMP_HISTORY[i], max_t))
            pts_temp.append((px, curr_y + gh - (((tv - min_t) / max(1, max_t - min_t)) * gh)))
        d.line(pts_temp, fill=theme_colors["temp_line"], width=2)
        d.line(pts_cpu, fill=theme_colors["warn"], width=2)
        d.line(pts_ram, fill=theme_colors["good"], width=2)

    curr_y += spacing
    
    # RAM
    draw_bar(20, curr_y, row_w, row_h, SYSTEM_STATS["ram_percent"], 
             "RAM", f"{SYSTEM_STATS['ram_used_mb']}MB", theme_colors["good"], "ram-symbolic.svg")
    curr_y += spacing
    
    # SWAP
    draw_bar(20, curr_y, row_w, row_h, SYSTEM_STATS["swap_percent"], 
             "SWAP", f"{SYSTEM_STATS['swap_used_mb']}MB", theme_colors["swap"], "swap-symbolic.svg")
    curr_y += spacing
    
    # DISK
    draw_bar(20, curr_y, row_w, row_h, SYSTEM_STATS["disk_percent"], 
             "DISK", f"{SYSTEM_STATS['disk_percent']:.0f}%", theme_colors["disk"], "disk-symbolic.svg")
    curr_y += spacing
    
    # GPU Box
    gpu_box_h = int(height * 0.16)
    d.rounded_rectangle((10, curr_y, width-10, curr_y + gpu_box_h), radius=10, fill=theme_colors["panel_bg"])
    
    active_gpu = SYSTEM_STATS["gpus"][SYSTEM_STATS["active_gpu_idx"]] if SYSTEM_STATS["gpus"] else {}
    gpu_badge = f" [GPU {SYSTEM_STATS['active_gpu_idx']+1}/{len(SYSTEM_STATS['gpus'])}]" if len(SYSTEM_STATS['gpus']) > 1 else ""
    gpu_title = f"{active_gpu.get('name', 'GPU')[:17]}{gpu_badge}"
    
    # GPU Icon + Title (Landscape style)
    gpu_icon = get_svg_icon("gpu-symbolic.svg", int(height*0.025), theme_colors["icon_color"])
    icon_off = 20
    if gpu_icon:
        img.paste(gpu_icon, (20, curr_y + 8), gpu_icon)
        icon_off = 20 + gpu_icon.width + 8
        
    d.text((icon_off, curr_y + 8), gpu_title, fill=theme_colors["text_label"], font=font_md)
    
    # Dynamic Temp Color
    gpu_t = active_gpu.get("temp", "?°C")
    try:
        gpu_t_val = int(gpu_t.replace("°C", ""))
    except:
        gpu_t_val = 40
    
    gpu_c = theme_colors["crit"] if gpu_t_val > 85 else (theme_colors["warn"] if gpu_t_val >= 50 else theme_colors["good"])
    
    t_w = get_text_width(d, gpu_t, font_md)
    d.text((width - t_w - 20, curr_y + 8), gpu_t, fill=gpu_c, font=font_md)
    
    # GPU Load Bar inside GPU Box
    draw_bar(20, curr_y + int(height * 0.045), row_w, row_h, active_gpu.get("percent", 0), 
             "CORE", f"{active_gpu.get('percent', 0):.0f}%", theme_colors["crit"])
    
    current_gpu_mem_p = (active_gpu.get("mem_used_mb", 0) / max(1, active_gpu.get("mem_total_mb", 1))) * 100
    draw_bar(20, curr_y + int(height * 0.1), row_w, row_h, current_gpu_mem_p, 
             "VRAM", f"{active_gpu.get('mem_used_mb', 0)}MB", theme_colors["vram"])
             
    curr_y += gpu_box_h + 15
    
    # TOP PROCESSES (Same style as landscape)
    proc_icon = get_svg_icon("process-symbolic.svg", int(height*0.03), theme_colors["icon_color"])
    if proc_icon:
        img.paste(proc_icon, (20, curr_y-2), proc_icon)
        d.text((20 + proc_icon.width + 8, curr_y), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_md)
    else:
        d.text((20, curr_y), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_md)
        
    d.line((20, curr_y + 25, width - 20, curr_y + 25), fill=theme_colors["border"], width=1)
    curr_y += 35
    
    proc_step = int(height * 0.03)
    for i, p in enumerate(SYSTEM_STATS["procs"][:10]):
        py = curr_y + (i * proc_step)
        if py + proc_step > height - 5: break
        
        # Color logic from landscape
        color = theme_colors["crit"] if i < 2 else (theme_colors["warn"] if i < 5 else (theme_colors["text_label"] if i < 8 else theme_colors["good"]))
        
        d.text((20, py), f"{i+1}. {p['name'][:10]}", fill=color, font=font_sm)
        # Align CPU and MEM to the right
        cpu_txt = f"{p['cpu_percent']:.1f}%"
        cpu_w = get_text_width(d, cpu_txt, font_sm)
        d.text((width - 95 - cpu_w, py), cpu_txt, fill=color, font=font_sm)
        
        mem_txt = f"{p.get('memory_percent') or 0:.0f}%"
        mem_w = get_text_width(d, mem_txt, font_sm)
        d.text((width - 25 - mem_w, py), mem_txt, fill=theme_colors["text_muted"] if i >= 2 else color, font=font_sm)

    return img

def render_dashboard_landscape(width, height, settings):
    theme_colors = get_theme_colors(settings.get("theme", "dark"))
    bg_color = theme_colors["bg"]
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    # === FONTS ===
    try:
        font_dir = os.path.join(BASE_DIR, "fonts")
        font_time = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.07)) 
        font_lg = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.050))  
        font_md = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.038))  
        font_sm = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.035))       
        font_icon = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.022))     
    except:
        font_time = font_lg = font_md = font_sm = font_icon = ImageFont.load_default()

    os_info = get_os_release()
    pretty_name = os_info.get("PRETTY_NAME", "Linux OS")
    logo_name = os_info.get("LOGO", "")
    
    # === 1. HEADER BANNER ===
    header_h = int(height * 0.18)
    try:
        d.rounded_rectangle((10, 10, width-10, header_h), radius=10, fill=theme_colors["panel_bg"])
    except AttributeError:
        d.rectangle((10, 10, width-10, header_h), fill=theme_colors["panel_bg"])
    
    # Logo
    logo_path = f"/usr/share/pixmaps/{logo_name}.png"
    if os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            try:
                resamp = Image.Resampling.LANCZOS
            except AttributeError:
                resamp = Image.ANTIALIAS if hasattr(Image, "ANTIALIAS") else 1
            logo.thumbnail((header_h - 20, header_h - 20), resamp)
            img.paste(logo, (20, 15), mask=logo)
        except Exception:
            pass

    # Info OS + Hostname + Kernel
    d.text((100, 15), f"{pretty_name}", fill=theme_colors["text_main"], font=font_lg)
    # Mostrando kernel junto 
    d.text((100, 50), f"Host: {SYSTEM_STATS['hostname']} | Kernel: {SYSTEM_STATS['kernel']}", fill=theme_colors["text_muted"], font=font_sm)

    # Relógio MENOR
    now = datetime.now().strftime("%H:%M")
    time_w = get_text_width(d, now, font_time)
    d.text((width - time_w - 20, 15), now, fill=theme_colors["time"], font=font_time)
    
    # Rede RX / TX
    net_rx_icon = get_svg_icon("rx-symbolic.svg", int(height*0.04), theme_colors["icon_color"])
    net_tx_icon = get_svg_icon("tx-symbolic.svg", int(height*0.04), theme_colors["icon_color"])
    
    net_str = f"  {SYSTEM_STATS['net_rx_mbps']:.1f} Mbps      {SYSTEM_STATS['net_tx_mbps']:.1f} Mbps"
    net_w = get_text_width(d, net_str, font_sm)
    d.text((width - net_w - 20, 55), net_str, fill=theme_colors["good"], font=font_sm)
    
    if net_rx_icon:
        img.paste(net_rx_icon, (int(width - net_w - 30), 55), net_rx_icon)
    if net_tx_icon:
        middle_offset = get_text_width(d, f"  {SYSTEM_STATS['net_rx_mbps']:.1f} Mbps    ", font_sm)
        img.paste(net_tx_icon, (int(width - net_w - 30 + middle_offset), 55), net_tx_icon)

    # === FUNCAO PROGRESS BAR ===
    def draw_bar(x, y, w, h, percent, label, text_val, color, icon_name=""):
        icon_offset = 0
        if icon_name:
            icon_img = get_svg_icon(icon_name, int(height*0.045), theme_colors["icon_color"])
            if icon_img:
                img.paste(icon_img, (x, y-2), icon_img)
                icon_offset = icon_img.width + 10
            
        d.text((x + icon_offset, y), label, fill=theme_colors["text_label"], font=font_md)
        val_w = get_text_width(d, text_val, font=font_md)
        d.text((x + w - val_w, y), text_val, fill=theme_colors["text_main"], font=font_md)
        
        by = y + 27
        try:
            d.rounded_rectangle((x, by, x + w, by + h), radius=h//2, fill=theme_colors["bar_bg"])
            fill_w = int(w * (percent / 100))
            if fill_w > h:
                d.rounded_rectangle((x, by, x + fill_w, by + h), radius=h//2, fill=color)
        except AttributeError:
            d.rectangle((x, by, x + w, by + h), fill=theme_colors["bar_bg"])
            fill_w = int(w * (percent / 100))
            if fill_w > h:
                d.rectangle((x, by, x + fill_w, by + h), fill=color)

    # === 2. LEFT COLUMN (HARDWARE) ===
    col1_x, col1_w = 20, int(width * 0.45)
    bar_y = header_h + 15
    col1_spacing = int(height * 0.12)

    #  ----- CPU (Split: Barra esq | Gráfico Temp dir) -----
    cpu_label = f"CPU ({SYSTEM_STATS['cpu_temp']})"
    icon_img = get_svg_icon("cpu-symbolic.svg", int(height*0.05), theme_colors["icon_color"])
    icon_w = 0
    if icon_img:
        img.paste(icon_img, (col1_x, bar_y-2), icon_img)
        icon_w = icon_img.width + 8
    
    current_temp = CPU_TEMP_HISTORY[-1] if CPU_TEMP_HISTORY else 40
    if current_temp > 85:
        temp_color = theme_colors["crit"] # Vermelho (Sobrecarga)
    elif current_temp >= 50:
        temp_color = theme_colors["warn"] # Amarelo (Carga)
    else:
        temp_color = theme_colors["good"] # Verde (Normal 30-50°C)

    d.text((col1_x + icon_w, bar_y), "CPU ", fill=theme_colors["text_label"], font=font_md)
    offset_cpu = get_text_width(d, "CPU ", font=font_md)
    d.text((col1_x + icon_w + offset_cpu, bar_y), f"{SYSTEM_STATS['cpu_temp']}", fill=temp_color, font=font_md)
    offset_cpu += get_text_width(d, f"{SYSTEM_STATS['cpu_temp']}", font=font_md)
    d.text((col1_x + icon_w + offset_cpu, bar_y), " ", fill=theme_colors["text_label"], font=font_md)
    
    val_w = get_text_width(d, f"{SYSTEM_STATS['cpu_percent']:.1f}%", font=font_md)
    # Metade da tela na barra:
    half_w = int(col1_w * 0.6)
    d.text((col1_x + half_w - val_w, bar_y), f"{SYSTEM_STATS['cpu_percent']:.1f}%", fill=theme_colors["text_main"], font=font_md)
    
    # Barra CPU
    by = bar_y + 27
    h_bar = int(height * 0.025)
    try:
        d.rounded_rectangle((col1_x, by, col1_x + half_w, by + h_bar), radius=h_bar//2, fill=theme_colors["bar_bg"])
        fcpu = int(half_w * (SYSTEM_STATS["cpu_percent"] / 100))
        if fcpu > h_bar:
            d.rounded_rectangle((col1_x, by, col1_x + fcpu, by + h_bar), radius=h_bar//2, fill=theme_colors["warn"])
    except AttributeError:
        pass
        
    # Gráfico Temperatura, CPU e MEM na direita
    gx = col1_x + half_w + 15
    # Limites
    max_t = max(80, max(CPU_TEMP_HISTORY))
    min_t = 30
    gw = (col1_x + col1_w) - gx
    gh = (by + h_bar + 5) - bar_y
    step = gw / max(1, len(CPU_TEMP_HISTORY) - 1)
    
    # Bg do Grafico
    d.rectangle((gx, bar_y, gx + gw, bar_y + gh), fill=theme_colors["panel_bg"], outline=theme_colors["border"])
    
    pts_temp = []
    pts_cpu = []
    pts_ram = []
    for i in range(len(CPU_TEMP_HISTORY)):
        px = gx + (i * step)
        
        # Temp (Laranja)
        tv = max(min_t, min(CPU_TEMP_HISTORY[i], max_t))
        py_temp = bar_y + gh - (((tv - min_t) / max(1, max_t - min_t)) * gh)
        pts_temp.append((px, py_temp))
        
        # CPU (Amarelo)
        vcpu = max(0, min(CPU_USAGE_HISTORY[i], 100))
        py_cpu = bar_y + gh - ((vcpu / 100) * gh)
        pts_cpu.append((px, py_cpu))
        
        # RAM (Verde)
        vram = max(0, min(RAM_USAGE_HISTORY[i], 100))
        py_ram = bar_y + gh - ((vram / 100) * gh)
        pts_ram.append((px, py_ram))

    if len(pts_temp) > 1:
        d.line(pts_temp, fill=theme_colors["temp_line"], width=2)
        d.line(pts_cpu, fill=theme_colors["warn"], width=2)
        d.line(pts_ram, fill=theme_colors["good"], width=2)
        
    # ------ RAM ------
    bar_y += col1_spacing
    draw_bar(col1_x, bar_y, col1_w, h_bar, SYSTEM_STATS["ram_percent"], 
             "RAM", f"{SYSTEM_STATS['ram_used_mb']} / {SYSTEM_STATS['ram_total_mb']} MB", theme_colors["good"], icon_name="ram-symbolic.svg") 
             
    # ------ SWAP ------
    bar_y += col1_spacing
    draw_bar(col1_x, bar_y, col1_w, h_bar, SYSTEM_STATS["swap_percent"], 
             "SWAP", f"{SYSTEM_STATS['swap_used_mb']} / {SYSTEM_STATS['swap_total_mb']} MB", theme_colors["swap"], icon_name="swap-symbolic.svg") 
             
    # ------ DISK ------
    bar_y += col1_spacing
    draw_bar(col1_x, bar_y, col1_w, h_bar, SYSTEM_STATS["disk_percent"], 
             "DISK /", SYSTEM_STATS["disk_text"], theme_colors["disk"], icon_name="disk-symbolic.svg")

    # === NVTOP GPU SECTION === #
    bar_y += col1_spacing + 5
    box_h = height - bar_y - 10
    
    # Caixa background GPU
    try:
        d.rounded_rectangle((10, bar_y-5, col1_x + col1_w + 10, height - 10), radius=10, fill=theme_colors["panel_bg"])
    except AttributeError:
        d.rectangle((10, bar_y-5, col1_x + col1_w + 10, height - 10), fill=theme_colors["panel_bg"])
        
    active_gpu = SYSTEM_STATS["gpus"][SYSTEM_STATS["active_gpu_idx"]] if SYSTEM_STATS["gpus"] else {}
    gpu_badge = f" [GPU {SYSTEM_STATS['active_gpu_idx']+1}/{len(SYSTEM_STATS['gpus'])}]" if len(SYSTEM_STATS['gpus']) > 1 else ""
    gpu_title = f"{active_gpu.get('name', 'N/A')[:15]}{gpu_badge}"
    
    # Titulo e Temp GPU 
    gpu_icon = get_svg_icon("gpu-symbolic.svg", int(height*0.05), theme_colors["icon_color"])
    icon_gpu_w = 0
    if gpu_icon:
        img.paste(gpu_icon, (col1_x, bar_y+2), gpu_icon)
        icon_gpu_w = gpu_icon.width + 5
    
    d.text((col1_x + icon_gpu_w, bar_y+3), gpu_title, fill=theme_colors["text_label"], font=font_md)
    
    gpu_t = active_gpu.get("temp", "?°C")
    try:
        gpu_t_val = int(gpu_t.replace("°C", ""))
    except:
        gpu_t_val = 40
        
    if gpu_t_val > 85:
        gpu_c = theme_colors["crit"]
    elif gpu_t_val >= 50:
        gpu_c = theme_colors["warn"]
    else:
        gpu_c = theme_colors["good"]
        
    gpu_t_w = get_text_width(d, f"{gpu_t}", font=font_md)
    d.text((col1_x + col1_w - gpu_t_w, bar_y+3), f"{gpu_t}", fill=gpu_c, font=font_md)
    
    # Barras lado a lado ou em sequencia (espaco vertical)
    bar_y += int(height * 0.08)
    h_gpu = int(height * 0.02)
    # Processamento Core GPU
    draw_bar(col1_x, bar_y-7, col1_w, h_gpu, active_gpu.get("percent", 0), 
             "CORE", f"{active_gpu.get('percent', 0):.1f}%", theme_colors["crit"]) 
    
    bar_y += int(height * 0.08)
    # VRAM
    gpu_mem_p = (active_gpu.get("mem_used_mb", 0) / max(1, active_gpu.get("mem_total_mb", 1))) * 100
    draw_bar(col1_x, bar_y-4, col1_w, h_gpu, gpu_mem_p, 
             "VRAM", f"{active_gpu.get('mem_used_mb', 0)}/{active_gpu.get('mem_total_mb', 0)} MB", theme_colors["vram"]) 
             
    bar_y += int(height * 0.08)
    # Encode / Decode
    enc = active_gpu.get("enc_percent", 0.0)
    enc_icon = get_svg_icon("encdec-symbolic.svg", int(height*0.04), theme_colors["icon_color"])
    if enc_icon:
        img.paste(enc_icon, (col1_x, bar_y+2), enc_icon)
        d.text((col1_x + enc_icon.width + 5, bar_y+2), f"ENC / DEC: {enc:.1f}%", fill=theme_colors["text_muted"], font=font_sm)
    else:
        d.text((col1_x, bar_y-5), f"ENC / DEC: {enc:.1f}%", fill=theme_colors["text_muted"], font=font_sm)


# === 3. RIGHT COLUMN (PROCESSES TOP 10) ===
    col2_x = int(width * 0.5) + 5
    col2_w = width - col2_x - 10
    
    try:
        d.rounded_rectangle((col2_x, header_h + 10, width - 10, height - 10), radius=15, fill=theme_colors["panel_bg"])
    except AttributeError:
        d.rectangle((col2_x, header_h + 10, width - 10, height - 10), fill=theme_colors["panel_bg"])
        
    proc_icon = get_svg_icon("process-symbolic.svg", int(height*0.045), theme_colors["icon_color"])
    if proc_icon:
        img.paste(proc_icon, (col2_x + 15, header_h + 18), proc_icon)
        d.text((col2_x + 15 + proc_icon.width + 8, header_h + 20), "TOP 10 PROCESSOS | CPU | MEM", fill=theme_colors["text_muted"], font=font_md)
    else:
        d.text((col2_x + 15, header_h + 20), "TOP 10 PROCESSOS | CPU | MEM)", fill=theme_colors["text_muted"], font=font_md)
    d.line((col2_x + 15, header_h + 50, width - 25, header_h + 50), fill=theme_colors["border"], width=2)
    
    py = header_h + 60
    # Processos: vamos mostrar exatamente 10 
    proc_limit = 10
    available_h = height - py - 20
    step_y = available_h // max(1, proc_limit)
    
    for i, p in enumerate(SYSTEM_STATS["procs"][:proc_limit]):
        # trinca string conforme espaço
        p_name = p['name'][:12] if width > 500 else p['name'][:8]
        p_cpu = f"{p['cpu_percent']:.1f}%"
        p_mem = f"{p.get('memory_percent') or 0:.1f}%"
        
        # Coloracao Top
        color = theme_colors["crit"] if i < 2 else (theme_colors["warn"] if i < 5 else (theme_colors["text_label"] if i < 8 else theme_colors["good"]))
        
        # Numeração
        d.text((col2_x + 15, py), f"{i+1}.", fill=theme_colors["text_muted"], font=font_sm)
        # Nome
        d.text((col2_x + 45, py), p_name, fill=color, font=font_sm)
        
        # CPU alinhado à direita (penúltima coluna)
        cpu_w = get_text_width(d, p_cpu, font=font_sm)
        d.text((width - 95 - cpu_w, py), f"{p_cpu}", fill=color, font=font_sm)
        
        # MEM alinhado à direita (última coluna)
        mem_w = get_text_width(d, p_mem, font=font_sm)
        d.text((width - 25 - mem_w, py), f"{p_mem}", fill=color, font=font_sm)
        
        py += step_y

    return img


def animate_intro(lcd, settings):
    # Determine orientation dimensions
    is_vertical = settings.get("orientation") == "vertical"
    if is_vertical:
        width, height = lcd.height, lcd.width
    else:
        width, height = lcd.width, lcd.height
    theme_colors = get_theme_colors(settings.get("theme", "dark"))
    bg_color = theme_colors["bg"]
    
    possible_paths = [
        os.path.abspath(os.path.join(BASE_DIR, "..", "icons", "hicolor", "scalable", "apps", "big-screen-monitor-display.svg")),
        "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg"
    ]
    
    logo_path = None
    for p in possible_paths:
        if os.path.exists(p):
            logo_path = p
            break
            
    if not logo_path:
        return
        
    # Scale logo proportionally: 50% of height in landscape, 30% in portrait
    max_h = int(height * 0.3) if is_vertical else int(height * 0.5)
    try:
        p = subprocess.run(["rsvg-convert", "-h", str(max_h), logo_path], 
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode != 0:
            return
        base_logo = Image.open(io.BytesIO(p.stdout)).convert("RGBA")
    except Exception:
        return
    frames_in = 8
    frames_hold = 8
    frames_out = 6
    
    pre_rendered_frames = []
    
    def blend_and_generate(scale, alpha):
        img = Image.new('RGB', (width, height), color=bg_color)
        cw, ch = base_logo.size
        nw, nh = int(cw * scale), int(ch * scale)
        if nw > 0 and nh > 0:
            try:
                resamp = Image.Resampling.LANCZOS
            except AttributeError:
                resamp = Image.ANTIALIAS if hasattr(Image, "ANTIALIAS") else 1
                
            scaled = base_logo.resize((nw, nh), resamp)
            
            r, g, b, a = scaled.split()
            a = a.point(lambda p: int(p * (alpha / 255.0)))
            scaled.putalpha(a)
            
            x = (width - nw) // 2
            y = (height - nh) // 2
            img.paste(scaled, (x, y), scaled)
            
        # Hardware-bound rotation
        if is_vertical:
            final_img = img.rotate(90, expand=True)
        else:
            final_img = img
            
        dw, dh = final_img.size
        img_bytes = final_img.convert("RGB").tobytes()
        rgb565 = bytearray(dw * dh * 2)
        for i in range(dw * dh):
            r, g, b = img_bytes[i*3:i*3+3]
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            rgb565[i*2] = (val >> 8) & 0xFF
            rgb565[i*2+1] = val & 0xFF
            
        pre_rendered_frames.append((rgb565, dw, dh))
        
    print("⏳ Pré-carregando animação na memória...")
    for i in range(1, frames_in + 1):
        progress = i / frames_in
        ease_out = 1 - (1 - progress) * (1 - progress)
        blend_and_generate(0.5 + 0.5 * ease_out, int(255 * progress))
        
    hold_frame_data = pre_rendered_frames[-1]
        
    for i in range(frames_out, -1, -1):
        progress = i / frames_out
        blend_and_generate(1.0, int(255 * progress))
        
    print("🎬 Rodando animação de abertura!")
    
    for frame_data in pre_rendered_frames[:frames_in]:
        lcd._draw_rgb565(frame_data[0], frame_data[1], frame_data[2])
        
    for _ in range(frames_hold):
        lcd._draw_rgb565(hold_frame_data[0], hold_frame_data[1], hold_frame_data[2])
        
    for frame_data in pre_rendered_frames[frames_in:]:
        lcd._draw_rgb565(frame_data[0], frame_data[1], frame_data[2])
    
    # Final bg fill for cleanup
    bg_img = Image.new('RGB', (width, height), color=bg_color)
    if is_vertical:
        bg_img = bg_img.rotate(90, expand=True)
    dw, dh = bg_img.size
    bg_bytes = bg_img.convert("RGB").tobytes()
    bg_565 = bytearray(dw * dh * 2)
    for i in range(dw * dh):
        r, g, b = bg_bytes[i*3:i*3+3]
        val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        bg_565[i*2] = (val >> 8) & 0xFF
        bg_565[i*2+1] = val & 0xFF
    lcd._draw_rgb565(bg_565, dw, dh)

def run_tray_icon():
    if pystray is None or os.getuid() == 0 or not os.environ.get("DISPLAY"):
        return

    try:
        def open_config(icon, item):
            subprocess.Popen(["python3", os.path.join(BASE_DIR, "config_gui.py")])

        def exit_app(icon, item):
            icon.stop()
            os._exit(0)

        # Busca o ícone
        possible_paths = [
            "/usr/share/icons/hicolor/scalable/apps/big-screen-monitor-display.svg",
            os.path.abspath(os.path.join(BASE_DIR, "..", "icons", "hicolor", "scalable", "apps", "big-screen-monitor-display.svg")),
            os.path.join(BASE_DIR, "img", "gpu-symbolic.svg") # Extremo fallback
        ]
        
        icon_path = next((p for p in possible_paths if os.path.exists(p)), None)
        
        if icon_path:
            p = subprocess.run(["rsvg-convert", "-w", "64", "-h", "64", icon_path], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if p.returncode == 0:
                icon_img = Image.open(io.BytesIO(p.stdout))
            else:
                icon_img = Image.new('RGB', (64, 64), color=(0, 120, 215))
        else:
            icon_img = Image.new('RGB', (64, 64), color=(0, 120, 215))

        menu = pystray.Menu(item('Configurações', open_config), item('Sair', exit_app))
        icon = pystray.Icon("BigScreenMonitor", icon_img, "Big Screen Monitor", menu)
        icon.run_detached()
    except Exception:
        pass


def main():
    lcd = AX206_DPF()
    
    # Refresh dinamico
    settings = get_settings()
    lcd.set_backlight(settings.get("brightness", 7))
    
    animate_intro(lcd, settings)
    run_tray_icon()
    
    print("🚀 Loop UI NVTOP-Style rodando =).")
    try:
        last_check = 0
        while True:
            # Check for settings update every 5 seconds without blocking
            now = time.time()
            if now - last_check > 5:
                # reload settings dynamically
                new_settings = get_settings()
                if new_settings.get("brightness") != settings.get("brightness"):
                    lcd.set_backlight(new_settings.get("brightness", 7))
                
                # Dispara a intro se a orientação mudar dinamicamente
                if new_settings.get("orientation") != settings.get("orientation"):
                    animate_intro(lcd, new_settings)
                    
                settings = new_settings
                last_check = now
            
            # Use swapped dimensions if vertical
            if settings.get("orientation") == "vertical":
                render_w, render_height = lcd.height, lcd.width
            else:
                render_w, render_height = lcd.width, lcd.height
                
            img = render_dashboard(render_w, render_height, settings)
            lcd.draw(img, settings)
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n👋 Saindo...")
        lcd.set_backlight(0)

if __name__ == '__main__':
    main()
