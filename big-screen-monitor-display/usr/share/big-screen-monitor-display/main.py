import sys
import time
import struct
import threading
import subprocess
import socket
import platform
import os
import glob
import json
import re
import io
from datetime import datetime, timedelta

import usb.core
import usb.util
import psutil
from PIL import Image, ImageDraw, ImageFont

STATS_LOCK = threading.Lock()

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
        except Exception:
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
        },
        "gkrellm": {
            "bg": (0, 0, 0), "panel_bg": (0, 0, 0), "text_main": (170, 255, 170),
            "text_muted": (85, 170, 85), "text_label": (85, 170, 85), "time": (170, 255, 170),
            "good": (170, 255, 170), "warn": (170, 255, 170), "crit": (170, 255, 170),
            "vram": (170, 255, 170), "swap": (170, 255, 170), "disk": (170, 255, 170),
            "temp_line": (170, 255, 170), "bar_bg": (0, 0, 0), "border": (85, 170, 85),
            "icon_color": (170, 255, 170)
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
    "cpu_cores_history": [],
    "cpu_cores_percent": [],
    "active_gpu_idx": 0,
    "procs": [],
    "hostname": socket.gethostname(),
    "kernel": platform.release(),
    "kernel_offset": 0,
    "kernel_dir": 1,
    "gpu_marquee_offset": 0,
    "gpu_marquee_dir": 1,
    "power_profile": "",
    "cpu_user": 0.0,
    "cpu_system": 0.0,
}

# Historico para linha CPU Temp, CPU Uso e RAM Uso
CPU_TEMP_HISTORY = [0] * 30
CPU_USAGE_HISTORY = [0] * 30
CPU_USER_HISTORY = [0] * 30
CPU_SYSTEM_HISTORY = [0] * 30
RAM_USAGE_HISTORY = [0] * 30
GPU_USAGE_HISTORY = [0] * 30
GPU_MEM_HISTORY = [0] * 30
DISK_IO_HISTORY = [0] * 30
NET_RX_HISTORY = [0] * 30
NET_TX_HISTORY = [0] * 30

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
            "temp": "?°C",
            "usage_history": [0] * 30,
            "mem_history": [0] * 30
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
            except Exception:
                pass
                
        if pci_slot:
            try:
                # Pega o nome dinâmico via lspci
                cmd = f"lspci -s {pci_slot} | sed -n 's/.*\\[\\(.*\\)\\].*/\\1/p'"
                out = subprocess.check_output(cmd, shell=True, text=True).strip()
                if out:
                    gpu_info["name"] = out.split("\n")[0][:20]
            except Exception:
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
            except Exception:
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
            "temp": "?°C",
            "usage_history": [0] * 30,
            "mem_history": [0] * 30
        })
        
    return gpus

def monitor_thread():
    last_net = psutil.net_io_counters()
    last_disk = psutil.disk_io_counters()
    last_time = time.time()
    
    SYSTEM_STATS["gpus"] = find_gpus()
    gpu_switch_counter = 0
    
    while True:
        try:
            SYSTEM_STATS["cpu_percent"] = psutil.cpu_percent(interval=None)
            cpu_times = psutil.cpu_times_percent(interval=None)
            cpu_user = cpu_times.user
            cpu_system = cpu_times.system
            with STATS_LOCK:
                SYSTEM_STATS["cpu_user"] = cpu_user
                SYSTEM_STATS["cpu_system"] = cpu_system
                CPU_USER_HISTORY.append(cpu_user)
                CPU_USER_HISTORY.pop(0)
                CPU_SYSTEM_HISTORY.append(cpu_system)
                CPU_SYSTEM_HISTORY.pop(0)
                CPU_USAGE_HISTORY.append(SYSTEM_STATS["cpu_percent"])
                CPU_USAGE_HISTORY.pop(0)
            
            cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
            with STATS_LOCK:
                SYSTEM_STATS["cpu_cores_percent"] = cpu_cores
                if not SYSTEM_STATS["cpu_cores_history"]:
                    SYSTEM_STATS["cpu_cores_history"] = [[] for _ in cpu_cores]
                for i, c in enumerate(cpu_cores):
                    if i < len(SYSTEM_STATS["cpu_cores_history"]):
                        SYSTEM_STATS["cpu_cores_history"][i].append(c)
                        if len(SYSTEM_STATS["cpu_cores_history"][i]) > 40:
                            SYSTEM_STATS["cpu_cores_history"][i].pop(0)
            
            mem = psutil.virtual_memory()
            SYSTEM_STATS["ram_percent"] = mem.percent
            with STATS_LOCK:
                RAM_USAGE_HISTORY.append(mem.percent)
            RAM_USAGE_HISTORY.pop(0)
            
            SYSTEM_STATS["ram_used_mb"] = mem.used // 1048576
            SYSTEM_STATS["ram_total_mb"] = mem.total // 1048576
            
            try:
                swap = psutil.swap_memory()
                SYSTEM_STATS["swap_percent"] = swap.percent
                SYSTEM_STATS["swap_used_mb"] = swap.used // 1048576
                SYSTEM_STATS["swap_total_mb"] = swap.total // 1048576
            except Exception:
                pass
                
            try:
                disk = psutil.disk_usage('/')
                SYSTEM_STATS["disk_percent"] = disk.percent
                SYSTEM_STATS["disk_text"] = f"{disk.used//(1024**3)} / {disk.total//(1024**3)} GB"
            except Exception:
                pass
                
            net = psutil.net_io_counters()
            now = time.time()
            dt = now - last_time
            if dt > 0:
                rx_mbps = ((net.bytes_recv - last_net.bytes_recv) * 8) / (dt * 1e6)
                tx_mbps = ((net.bytes_sent - last_net.bytes_sent) * 8) / (dt * 1e6)
                SYSTEM_STATS["net_rx_mbps"] = rx_mbps
                SYSTEM_STATS["net_tx_mbps"] = tx_mbps
                with STATS_LOCK:
                    NET_RX_HISTORY.append(rx_mbps)
                    NET_RX_HISTORY.pop(0)
                    NET_TX_HISTORY.append(tx_mbps)
                    NET_TX_HISTORY.pop(0)
            last_net = net
            
            disk_io = psutil.disk_io_counters()
            if dt > 0:
                read_kb = (disk_io.read_bytes - last_disk.read_bytes) / (dt * 1024)
                write_kb = (disk_io.write_bytes - last_disk.write_bytes) / (dt * 1024)
                total_io = read_kb + write_kb
                SYSTEM_STATS["disk_io_kbs"] = total_io
                with STATS_LOCK:
                    DISK_IO_HISTORY.append(total_io)
                    DISK_IO_HISTORY.pop(0)
            last_disk = disk_io
            
            try:
                SYSTEM_STATS["load_avg"] = os.getloadavg()
            except:
                SYSTEM_STATS["load_avg"] = (0.0, 0.0, 0.0)

            last_time = now

            try:
                procs = sorted([p.info for p in psutil.process_iter(['name', 'cpu_percent', 'memory_percent']) if p.info['cpu_percent'] is not None], 
                       key=lambda x: x['cpu_percent'], reverse=True)[:10]
                SYSTEM_STATS["procs"] = procs
            except Exception:
                pass
            
            try:
                cpu_t_val = 0
                if hasattr(psutil, "sensors_temperatures"):
                    temps = psutil.sensors_temperatures()
                    for name, entries in temps.items():
                        if "coretemp" in name or "k10temp" in name or "zenpower" in name:
                            for entry in entries:
                                if "Tctl" in entry.label or "Package id 0" in entry.label or "Tdie" in entry.label or "Core 0" in entry.label or not entry.label:
                                    cpu_t_val = entry.current
                                    break
                            if cpu_t_val > 0: break
                    if cpu_t_val == 0:
                        for entries in temps.values():
                            if entries:
                                cpu_t_val = entries[0].current
                                break
                    if cpu_t_val > 0:
                        with STATS_LOCK:
                            SYSTEM_STATS["cpu_temp"] = f"{cpu_t_val:.0f}°C"
                            CPU_TEMP_HISTORY.append(cpu_t_val)
                            CPU_TEMP_HISTORY.pop(0)
            except Exception:
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
                            
                    # Update individual GPU history
                    with STATS_LOCK:
                        gpu["usage_history"].append(gpu["percent"])
                        gpu["usage_history"].pop(0)
                        m_p = (gpu["mem_used_mb"] / gpu["mem_total_mb"] * 100) if gpu.get("mem_total_mb", 0) > 0 else 0
                        gpu["mem_history"].append(m_p)
                        gpu["mem_history"].pop(0)

                    if i == SYSTEM_STATS.get("active_gpu_idx", 0):
                        with STATS_LOCK:
                            GPU_USAGE_HISTORY.append(gpu["percent"])
                            GPU_USAGE_HISTORY.pop(0)
                            mem_p = (gpu["mem_used_mb"] / gpu["mem_total_mb"] * 100) if gpu.get("mem_total_mb", 0) > 0 else 0
                            GPU_MEM_HISTORY.append(mem_p)
                            GPU_MEM_HISTORY.pop(0)
                            
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
                            
                    # Tenta pegar sensores avançados (edge, junction, ppt) se for AMD
                    for sensor_file in ["temp1_input", "temp2_input", "temp3_input", "power1_average"]:
                        path = os.path.join(hwmon_path[0], sensor_file)
                        if os.path.exists(path):
                            with open(path) as f:
                                val = int(f.read().strip())
                                if "temp" in sensor_file:
                                    label = "edge" if "1" in sensor_file else ("junc" if "2" in sensor_file else "mem")
                                    gpu[label] = f"{val//1000}°C"
                                else:
                                    gpu["ppt"] = f"{val/1000000:.1f}W"
                except Exception:
                    pass
            
            # Perfil de Energia
            try:
                prof_path = "/sys/firmware/acpi/platform_profile"
                if os.path.exists(prof_path):
                    with open(prof_path) as f:
                        SYSTEM_STATS["power_profile"] = f.read().strip()
                else:
                    # Fallback power-profiles-ctl
                    p = subprocess.check_output("powerprofilesctl get 2>/dev/null", shell=True, text=True).strip()
                    if p: SYSTEM_STATS["power_profile"] = p
            except: pass

        except Exception:
            pass
            
        # Marquee offset kernel e GPU
        try:
            # Kernel
            k = SYSTEM_STATS.get('kernel', '')
            k_len = len(k)
            limit_k = 20 # Perfect fit for the column width
            if k_len > limit_k:
                off = SYSTEM_STATS.get('kernel_offset', 0)
                d_dir = SYSTEM_STATS.get('kernel_dir', 1)
                off += d_dir
                if off >= (k_len - limit_k):
                    off = k_len - limit_k
                    d_dir = -1
                elif off <= 0:
                    off = 0
                    d_dir = 1
                SYSTEM_STATS['kernel_offset'] = off
                SYSTEM_STATS['kernel_dir'] = d_dir
            else:
                SYSTEM_STATS['kernel_offset'] = 0
            
            # GPU (Sync all GPUs based on the longest name)
            max_gn_len = 0
            for g in SYSTEM_STATS.get("gpus", []):
                max_gn_len = max(max_gn_len, len(g.get("name", "")))
            
            limit_g = 20
            if max_gn_len > limit_g:
                off_g = SYSTEM_STATS.get('gpu_marquee_offset', 0)
                d_dir_g = SYSTEM_STATS.get('gpu_marquee_dir', 1)
                off_g += d_dir_g
                if off_g >= (max_gn_len - limit_g):
                    off_g = max_gn_len - limit_g
                    d_dir_g = -1
                elif off_g <= 0:
                    off_g = 0
                    d_dir_g = 1
                SYSTEM_STATS['gpu_marquee_offset'] = off_g
                SYSTEM_STATS['gpu_marquee_dir'] = d_dir_g
            else:
                SYSTEM_STATS['gpu_marquee_offset'] = 0
        except Exception:
            pass
        
        time.sleep(0.4)

threading.Thread(target=monitor_thread, daemon=True).start()

# ================= COMUNICAÇÃO DISPLAY =================

class AX206_DPF:
    def __init__(self, vid=0x1908, pid=0x0102):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            sys.exit(1)
        
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except Exception:
            pass
            
        try:
            self.dev.set_configuration()
            # Pequeno delay para estabilização após handshake USB
            time.sleep(0.1)
        except Exception:
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
        else:
            pass

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
    except Exception:
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



def render_dashboard_gkrellm(width, height, settings):
    # Tela inteira (800x480)
    bg_color = (0, 0, 0)
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    try:
        font_mono = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf", 20)
        font_mono_lg = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaMono-Bold.ttf", 26)
        font_mono_sm = ImageFont.truetype("/usr/share/fonts/Adwaita/AdwaitaMono-Regular.ttf", 16)
    except:
        font_mono = font_mono_lg = font_mono_sm = ImageFont.load_default()

    gk_theme = settings.get("gk_theme_color", "urlicht")
    
    if gk_theme == "urlicht":
        font_main  = (220, 220, 230)
        font_blue  = (80, 130, 255)
        font_dim   = (120, 120, 130)
        line_top   = (80, 80, 90)
        line_bot   = (30, 30, 40)
        bar_fill   = (80, 130, 255)
    elif gk_theme == "cyber_red":
        font_main  = (255, 180, 180)  
        font_blue  = (255, 50, 50)   
        font_dim   = (150, 100, 100) 
        line_top   = (120, 50, 50)    
        line_bot   = (50, 20, 20)    
        bar_fill   = (255, 50, 50)
    else: # classic
        font_main  = (170, 255, 170)
        font_blue  = (85, 170, 85)
        font_dim   = (85, 170, 85)
        line_top   = (85, 170, 85)
        line_bot   = (40, 80, 40)
        bar_fill   = (170, 255, 170)

    is_vertical = settings.get("orientation", "horizontal") == "vertical" or height > width
    num_cols = 2 if is_vertical else 4
    col_w = width // num_cols
    
    # Dividers
    for i in range(1, num_cols):
        d.line((col_w*i, 0, col_w*i, height), fill=line_bot, width=2)
        d.line((col_w*i-2, 0, col_w*i-2, height), fill=line_top, width=2)

    def draw_sep(x, y, w, title="", is_net=False):
        d.line((x, y, x+w, y), fill=line_top, width=2)
        d.line((x, y+2, x+w, y+2), fill=line_bot, width=2)
        if title:
            d.rectangle((x, y+4, x+w, y+26), fill=(line_bot[0]//2, line_bot[1]//2, line_bot[2]//2))
            tw = get_text_width(d, title, font_mono)
            d.text((x + (w-tw)//2, y + 2), title, fill=font_main, font=font_mono)
            
            if is_net:
                sec = int(time.time() * 2)
                # Blink LED for RX and TX
                rx_color = font_blue if sec % 2 == 0 else (40, 40, 50)
                tx_color = font_blue if (sec+1) % 2 == 0 else (40, 40, 50)
                # Draw right aligned LEDs
                d.rectangle((x+w-25, y+10, x+w-15, y+18), fill=rx_color, outline=line_top)
                d.rectangle((x+w-12, y+10, x+w-2, y+18), fill=tx_color, outline=line_top)

            d.line((x, y+28, x+w, y+28), fill=line_top, width=2)
            d.line((x, y+30, x+w, y+30), fill=line_bot, width=2)
            return y + 32
        return y + 6
        
    def format_bytes(b):
        if b < 1024: return f"{b}"
        elif b < 1024*1024: return f"{b/1024:.1f}K"
        else: return f"{b/(1024*1024):.1f}M"

    pad = 8
    graph_h = 45

    def draw_graph(x, y, w, h, data, max_val=100, style="line", color=font_blue, fill_color=(10,30,80), current_val=0, data2=None, color2=(255,100,100)):
        # Background gradient effect
        for i in range(h):
            ratio = i / h
            bg_c = (int(0 * ratio), int(0 * ratio), int(40 * (1-ratio)))
            d.line((x, y+i, x+w, y+i), fill=bg_c)
        
        d.line((x, y, x+w, y), fill=line_bot) # top border
        
        if data:
            actual_max = max(max_val, max(data) if data else 1)
            if data2:
                actual_max = max(actual_max, max(data2) if data2 else 1)
            step = w / max(1, len(data)-1)
            pts = []
            pts2 = []
            for i, val in enumerate(data):
                px = x + int(i*step)
                py = y + h - int((val / actual_max) * h)
                pts.append((px, py))
                if py < y + h:
                    if style == "line" or style == "mixed":
                        if style == "mixed":
                            d.line((px, py, px, y+h), fill=(color[0]//3, color[1]//3, color[2]//3))
                        d.line((px, py, px, py+1), fill=color) # The bright top line 
                    elif style == "bar":
                        d.rectangle((px, py, px+2, y+h), fill=(color[0]//2, color[1]//2, color[2]//2))
                        d.rectangle((px, py, px+2, py+1), fill=(min(255, color[0]+80), min(255, color[1]+80), min(255, color[2]+80)))
                if data2 and i < len(data2):
                    val2 = data2[i]
                    py2 = y + h - int((val2 / actual_max) * h)
                    pts2.append((px, py2))
            
            if len(pts) > 1 and style in ["bar", "mixed"]:
                d.line(pts, fill=(min(255, color[0]+50), min(255, color[1]+50), min(255, color[2]+50)), width=1)
            if pts2 and len(pts2) > 1 and style in ["line", "mixed"]:
                d.line(pts2, fill=color2, width=1)

        # Bottom tick horizontal bar
        d.line((x, y+h, x+w, y+h), fill=line_top) # bottom border
        d.rectangle((x, y+h+1, x+w, y+h+4), fill=(20, 20, 25))
        
        tick_w = int(w * (current_val / actual_max if 'actual_max' in locals() and actual_max > 0 else 0))
        tick_w = min(max(tick_w, 0), w)
        d.rectangle((x, y+h+1, x+tick_w, y+h+4), fill=color)

        return y + h + 6

    # Dynamic placement algorithm
    col = 0
    cx = 0; cy = 2; cw = col_w
    def request_space(h_req):
        nonlocal cy, col, cx
        if cy + h_req > height:
            col += 1
            cy = 0
            cx = col * cw
        if col >= num_cols:
            return False
        return True

    def draw_temp_row(label, val_str, default_val=40, custom_cy=None):
        nonlocal cy
        used_cy = custom_cy if custom_cy else cy
        try:
            val = float(str(val_str).replace('°C', ''))
        except:
            val = default_val
        ratio = max(0.0, min(1.0, (val - 30) / 60.0)) # 30 to 90
        r_c = int(font_blue[0] * (1-ratio) + 255*ratio)
        g_c = int(font_blue[1] * (1-ratio) + 50*ratio)
        b_c = int(font_blue[2] * (1-ratio) + 50*ratio)
        t_color = (r_c, g_c, b_c)
        
        d.text((cx+pad, used_cy), label, fill=font_blue, font=font_mono_sm)
        vw = get_text_width(d, f"{val:.1f}°C", font_mono_sm)
        d.text((cx+cw-vw-pad, used_cy), f"{val:.1f}°C", fill=t_color, font=font_mono_sm)
        
        b_y = used_cy + 18
        bar_len = int((cw-pad*2) * ratio)
        for i in range(bar_len):
            r_i = i/(cw-pad*2)
            cur_c = (int(font_blue[0] * (1-r_i) + 255*r_i), int(font_blue[1] * (1-r_i) + 50*r_i), int(font_blue[2] * (1-r_i) + 50*r_i))
            d.line((cx+pad+i, b_y, cx+pad+i, b_y+2), fill=cur_c)
            
        if custom_cy is None:
            cy += 25

    # Logo / Host
    if settings.get('gk_show_host', True):
        if request_space(80):
            os_info = get_os_release()
            logo_name = os_info.get("LOGO", "")
            logo_path = f"/usr/share/pixmaps/{logo_name}.png"
            hn = SYSTEM_STATS.get('hostname', 'URSPECHT')
            krn = SYSTEM_STATS.get('kernel', 'Linux')
            tw = get_text_width(d, hn, font_mono_lg)
            kw = get_text_width(d, krn, font_mono_sm)
            
            if os.path.exists(logo_path):
                try:
                    logo = Image.open(logo_path).convert("RGBA")
                    logo.thumbnail((45, 45), Image.Resampling.LANCZOS)
                    img.paste(logo, (cx + (cw - logo.width)//2, cy), mask=logo)
                    cy += logo.height + 5
                except: pass
                
            d.text((cx + (cw - tw)//2, cy), hn, fill=font_dim, font=font_mono_lg)
            cy += 30
            
            # Scroll Kernel
            k_text = krn
            limit_k = 20
            if len(krn) > limit_k:
                off_k = SYSTEM_STATS.get('kernel_offset', 0)
                k_text = krn[off_k : off_k + limit_k]
            
            kw = get_text_width(d, k_text, font_mono_sm)
            kx = cx + (cw - kw)//2 if len(krn) <= limit_k else cx + pad
            d.text((kx, cy), k_text, fill=font_main, font=font_mono_sm)
            cy += 20

    now = datetime.now()

    # DATE
    if settings.get('gk_show_date', True):
        if request_space(25):
            ds1 = now.strftime("%a ")
            ds2 = now.strftime("%d")
            ds3 = now.strftime(" %b")
            d.text((cx + pad + 20, cy), ds1, fill=font_main, font=font_mono)
            w1 = get_text_width(d, ds1, font_mono)
            d.text((cx + pad + 20 + w1, cy), ds2, fill=font_blue, font=font_mono)
            w2 = get_text_width(d, ds2, font_mono)
            d.text((cx + pad + 20 + w1 + w2, cy), ds3, fill=font_main, font=font_mono)
            cy += 25

    # TIME
    if settings.get('gk_show_time', True):
        if request_space(35):
            ts1 = now.strftime("%H:%M")
            ts2 = now.strftime(" %S")
            d.text((cx + pad + 20, cy), ts1, fill=font_main, font=font_mono_lg)
            w1 = get_text_width(d, ts1, font_mono_lg)
            d.text((cx + pad + 20 + w1, cy+4), ts2, fill=font_blue, font=font_mono)
            cy += 35

    # UPTIME
    if settings.get('gk_show_uptime', True):
        try:
            with open('/proc/uptime', 'r') as f:
                uptime_seconds = float(f.readline().split()[0])
            uptime_str = str(timedelta(seconds=int(uptime_seconds)))
        except:
            uptime_str = "0:00:00"
        if request_space(25):
            up_str = f"up: {uptime_str}"
            tw = get_text_width(d, up_str, font_mono_sm)
            d.text((cx + (cw - tw)//2, cy), up_str, fill=font_main, font=font_mono_sm)
            cy += 25

    # CPU MONITOR (ADVANCED DUAL-LAYER)
    if settings.get('gk_show_cpu', True):
        # space for title + graph + text
        if request_space(110):
            cy = draw_sep(cx, cy, cw, "CPU")
            
            # CPU STATS
            cpu_p = SYSTEM_STATS.get('cpu_percent', 0)
            cpu_u = SYSTEM_STATS.get('cpu_user', 0)
            cpu_s = SYSTEM_STATS.get('cpu_system', 0)
            cpu_t = SYSTEM_STATS.get('cpu_temp', '0°C')
            
            # Colors for CPUS - System (Darker/Reddish) and User (Lighter/Greenish)
            c_user = (100, 255, 100) if gk_theme != "classic" else (170, 255, 170)
            c_sys  = (255, 100, 100) if gk_theme != "classic" else (255, 80, 80)
            
            # --- Draw the specialized CPU Graph ---
            # Moves Right to Left (History is append-only, so we show it directly or reversed)
            # data is [0...30], current is at index 29 (right)
            gx, gy, gw, gh = cx + pad, cy, cw - pad*2, graph_h
            
            # Background with grid lines every 20%
            for i in range(gh):
                ratio = i / gh
                bg_c = (int(0 * ratio), int(0 * ratio), int(40 * (1-ratio)))
                d.line((gx, gy+i, gx+gw, gy+i), fill=bg_c)
            
            # Grid lines
            for perc in [20, 40, 60, 80]:
                grid_y = gy + gh - int((perc / 100) * gh)
                d.line((gx, grid_y, gx+gw, grid_y), fill=(50, 50, 60), width=1)
                
            # Border
            d.rectangle((gx, gy, gx+gw, gy+gh), outline=line_bot)
            
            # Draw layers (User + System = Total)
            # We draw them as stacked areas
            # System is "top" relative to user, but visual order: User on bottom, System added on top
            step = gw / max(1, len(CPU_USER_HISTORY)-1)
            
            pts_user = []
            pts_system = []
            
            for i in range(len(CPU_USER_HISTORY)):
                px = gx + i * step
                u_val = CPU_USER_HISTORY[i]
                s_val = CPU_SYSTEM_HISTORY[i]
                
                # User Layer (Bottom)
                uy = gy + gh - int((u_val / 100) * gh)
                pts_user.append((px, uy))
                
                # System Layer (Stacked on top of User)
                sy = gy + gh - int(((u_val + s_val) / 100) * gh)
                pts_system.append((px, sy))
                
                # Fill vertical bars for area effect
                if uy < gy + gh:
                    d.line((px, uy, px, gy+gh), fill=(c_user[0]//3, c_user[1]//3, c_user[2]//3))
                if sy < uy:
                    d.line((px, sy, px, uy), fill=(c_sys[0]//3, c_sys[1]//3, c_sys[2]//3))
            
            # Draw top lines for the layers
            if len(pts_user) > 1:
                d.line(pts_user, fill=c_user, width=1)
                d.line(pts_system, fill=c_sys, width=1)
            
            cy += gh + 5
            
            # Numerical Values: u% s% Temp
            # Text align: Left-center-right/distributed
            txt_u = f"u: {cpu_u:.1f}%"
            txt_s = f"s: {cpu_s:.1f}%"
            
            d.text((cx + pad, cy), txt_u, fill=font_main, font=font_mono_sm)
            
            sw = get_text_width(d, txt_s, font_mono_sm)
            d.text((cx + (cw - sw)//2, cy), txt_s, fill=font_dim, font=font_mono_sm)
            
            tw = get_text_width(d, cpu_t, font_mono_sm)
            d.text((cx + cw - tw - pad, cy), cpu_t, fill=font_blue, font=font_mono_sm)
            
            cy += 20
            cy += 5

    # GPU (Iterate all detected GPUs)
    if settings.get('gk_show_gpu', True):
        for i, gpu in enumerate(SYSTEM_STATS.get("gpus", [])):
            if request_space(120):
                cy = draw_sep(cx, cy, cw, f"GPU {i}")
                gn = gpu.get("name", "GPU")
                limit_g = 20
                msg_gpu = gn
                if len(gn) > limit_g:
                    off_g = SYSTEM_STATS.get('gpu_marquee_offset', 0)
                    current_off = min(off_g, len(gn) - limit_g)
                    msg_gpu = gn[current_off : current_off + limit_g]
                
                gw_text = get_text_width(d, msg_gpu, font_mono_sm)
                gx_text = cx + (cw - gw_text)//2 if len(gn) <= limit_g else cx + pad
                d.text((gx_text, cy), msg_gpu, fill=font_main, font=font_mono_sm)
                cy += 20
                
                gpu_temp = gpu.get("temp", "43°C")
                gpu_perc = gpu.get("percent", 0)
                mem_tot = gpu.get("mem_total_mb", 1)
                mem_used = gpu.get("mem_used_mb", 0)
                gpu_mem_p = (mem_used / mem_tot * 100) if mem_tot > 0 else 0
                
                # Use individual history per GPU
                cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, list(gpu["usage_history"]), 100, "mixed", color=font_blue, current_val=gpu_perc, data2=list(gpu["mem_history"]), color2=(255,150,50))
                
                draw_temp_row("Temp", gpu_temp)
                
                # Align values text
                txt_vals = f"GPU {gpu_perc:.0f}% MEM {gpu_mem_p:.0f}%"
                vw_vals = get_text_width(d, txt_vals, font_mono_sm)
                d.text((cx + (cw-vw_vals)//2, cy), txt_vals, fill=font_main, font=font_mono_sm)
                cy += 20
                cy += 5

    # INDIVIDUAL CORES
    if settings.get('gk_show_cores', True):
        cores = SYSTEM_STATS.get('cpu_cores_percent', [])
        history = SYSTEM_STATS.get('cpu_cores_history', [])
        for i, val in enumerate(cores):
            if request_space(18):
                d.text((cx+pad, cy), f"CPU{i}", fill=font_main, font=font_mono_sm)
                pct_str = f"{val:.0f}%"
                vw = get_text_width(d, pct_str, font_mono_sm)
                d.text((cx+pad+90-vw, cy), pct_str, fill=font_main, font=font_mono_sm)
                fill_w = int((cw - pad*3 - 95) * (val/100.0))
                fill_w = max(0, fill_w)
                d.rectangle((cx+pad+95, cy+4, cx+pad+95+fill_w, cy+14), fill=font_blue)
                cy += 18

    # PROCESSES & LOAD
    if settings.get('gk_show_proc', True):
        if request_space(95):
            procs = sum(1 for p in SYSTEM_STATS.get('procs', []))
            if procs == 0: procs = 133
            load1, load5, load15 = SYSTEM_STATS.get('load_avg', (0,0,0))
            cy = draw_sep(cx, cy, cw, "Proc")
            d.text((cx+pad, cy), f"{procs} procs", fill=font_main, font=font_mono_sm)
            load_txt = f"{load1:.2f} {load5:.2f}"
            lw = get_text_width(d, load_txt, font_mono_sm)
            d.text((cx+cw-pad-lw, cy), load_txt, fill=font_dim, font=font_mono_sm)
            cy += 20
            cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, [min(100, x*1.2) for x in list(CPU_USAGE_HISTORY)[::-1]], 100, "mixed", color=font_blue, current_val=min(100, len(SYSTEM_STATS.get('procs', []))))
            cy += 5

    if settings.get('gk_show_temp', True):
        draw_temp_row("CPU", SYSTEM_STATS.get('cpu_temp', '16.0°C'))
    
    if settings.get('gk_show_temp', True):
        draw_temp_row("chipset", "45.0°C")

    # ETH0
    if settings.get('gk_show_eth0', True):
        if request_space(95):
            cy = draw_sep(cx, cy, cw, "eth0", is_net=True)
            rx_mbps = SYSTEM_STATS.get('net_rx_mbps', 0)
            tx_mbps = SYSTEM_STATS.get('net_tx_mbps', 0)
            txt_rx = f"RX: {rx_mbps:.1f}M"
            txt_tx = f"TX: {tx_mbps:.1f}M"
            d.text((cx+pad, cy), txt_rx, fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, txt_tx, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), txt_tx, fill=font_main, font=font_mono_sm)
            cy += 20
            
            c2_tx = (255, 120, 100) # Laranja/Vermelho para TX
            cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, list(NET_RX_HISTORY), 10, "mixed", color=font_blue, current_val=rx_mbps, data2=list(NET_TX_HISTORY), color2=c2_tx) 
            cy += 5

    # RAM
    if settings.get('gk_show_mem', True):
        if request_space(45):
            cy = draw_sep(cx, cy, cw, "Mem")
            mem_p = SYSTEM_STATS.get('ram_percent', 0)
            mem_tot = format_bytes(SYSTEM_STATS.get('ram_total_mb', 0)*1024*1024)
            d.text((cx+pad, cy), f"{mem_p:.0f}%", fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, mem_tot, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), mem_tot, fill=font_dim, font=font_mono_sm)
            cy += 20
            d.rectangle((cx+pad, cy, cx+cw-pad, cy+18), fill=(20, 20, 25))
            fw = int((cw-pad*2) * (mem_p/100.0))
            d.rectangle((cx+pad, cy, cx+pad+fw, cy+18), fill=bar_fill) 
            cy += 25

    # SWAP
    if settings.get('gk_show_swap', True):
        if request_space(45):
            cy = draw_sep(cx, cy, cw, "Swap")
            swap_p = SYSTEM_STATS.get('swap_percent', 0)
            sw_tot = format_bytes(SYSTEM_STATS.get('swap_total_mb', 0)*1024*1024)
            d.text((cx+pad, cy), f"{swap_p:.0f}%", fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, sw_tot, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), sw_tot, fill=font_dim, font=font_mono_sm)
            cy += 20
            d.rectangle((cx+pad, cy, cx+cw-pad, cy+18), fill=(20, 20, 25))
            sw = int((cw-pad*2) * (swap_p/100.0))
            d.rectangle((cx+pad, cy, cx+pad+sw, cy+18), fill=bar_fill)
            cy += 25

    # DISKS (NVME, etc)
    if settings.get('gk_show_disk', True):
        disks = []
        try:
            for part in psutil.disk_partitions(all=False):
                if 'loop' not in part.device:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append((part.device.split('/')[-1], usage.percent))
        except:
            disks = [("hda", SYSTEM_STATS.get('disk_percent', 0))]

        for name, percent in disks:
            if request_space(45):
                cy = draw_sep(cx, cy, cw, name)
                d.text((cx+pad, cy), f"{percent}%", fill=font_main, font=font_mono_sm)
                d.rectangle((cx+pad+45, cy+2, cx+cw-pad, cy+16), fill=(20, 20, 25))
                dw = int((cw-pad*2 - 45) * (percent/100.0))
                d.rectangle((cx+pad+45, cy+2, cx+pad+45+dw, cy+16), fill=bar_fill)
                cy += 25

    # DOCKER
    if settings.get('gk_show_docker', False):
        if request_space(35):
            try:
                dk = len(subprocess.check_output(['docker', 'ps', '-q']).splitlines())
            except:
                dk = 0
            cy = draw_sep(cx, cy, cw, "docker")
            d.text((cx+pad, cy), f"{dk} containers", fill=font_main, font=font_mono_sm)
            cy += 25
            
    # DEVICES
    if settings.get('gk_show_devices', True):
        if request_space(110):
            cy = draw_sep(cx, cy, cw)
            items = [("cdrom", "/dev/sr0"), ("keydrive", "/dev/sdb1"), ("cardread", "/dev/mmcblk0"), ("fwdrive", "/dev/sdc1")]
            
            # Tenta detectar montagens reais
            partitions = psutil.disk_partitions(all=True)
            mounted_devs = [p.device for p in partitions]
            
            for it, dev in items:
                cy += 5
                is_active = any(dev in m for m in mounted_devs) or os.path.exists(dev)
                d.rectangle((cx+pad, cy+8, cx+pad+4, cy+12), fill=(0,255,0) if is_active else (50, 50, 50))
                d.text((cx+pad+10, cy), it, fill=font_main, font=font_mono_sm)
                by = cy + 4
                d.rectangle((cx+cw-30, by, cx+cw-10, by+10), fill=line_top, outline=line_bot)
                if is_active:
                    d.rectangle((cx+cw-20, by+2, cx+cw-12, by+8), fill=(100, 255, 100))
                else:
                    d.rectangle((cx+cw-20, by+2, cx+cw-12, by+8), fill=(40, 45, 50))
                cy += 25

    # MEDIA
    if settings.get('gk_show_media', True):
        if request_space(130):
            vol = "4/4"
            play_st = "( )"
            track = "Idle"
            try:
                # Tentativa de pegar info media real dbus do KDE/GNOME
                pmt = subprocess.check_output("playerctl status 2>/dev/null", shell=True, text=True).strip()
                if "Playing" in pmt:
                    play_st = "(>)"
                    tr = subprocess.check_output("playerctl metadata title 2>/dev/null", shell=True, text=True).strip()
                    track = tr[:12] if tr else "Track 1"
                elif "Paused" in pmt:
                    play_st = "(II)"
                
                v = subprocess.check_output("amixer sget Master 2>/dev/null | grep 'Right:' | awk -F'[][]' '{ print $2 }'", shell=True, text=True).strip()
                if v: vol = v
            except: pass
                
            cy += 10
            d.text((cx + cw//2 - 25, cy+10), play_st, fill=font_blue, font=font_mono_lg)
            d.text((cx + cw//2 + 15, cy + 14), vol, fill=font_main, font=font_mono)
            cy += 45
            d.text((cx+pad, cy), "Pcm", fill=font_main, font=font_mono_sm)
            d.line((cx+40, cy+10, cx+cw-30, cy+10), fill=line_top, width=2)
            if play_st == "(>)":
                d.ellipse((cx+cw-25, cy+4, cx+cw-10, cy+19), fill=(0,255,0))
            else:
                d.ellipse((cx+cw-25, cy+4, cx+cw-10, cy+19), fill=font_blue)
            cy += 25
            d.text((cx+pad, cy), "CD", fill=font_main, font=font_mono_sm)
            d.line((cx+40, cy+10, cx+cw-30, cy+10), fill=line_top, width=2)
            d.ellipse((cx+40, cy+4, cx+55, cy+19), fill=font_blue)
            cy += 20
            tw = get_text_width(d, track, font_mono)
            d.text((cx + (cw-tw)//2, cy), track, fill=font_dim, font=font_mono)
            cy += 25

    # PPP
    if settings.get('gk_show_ppp', False):
        ppps = ["ppp0", "ppp1", "ppp2"]
        for p in ppps:
            if request_space(80):
                cy = draw_sep(cx, cy, cw, p, is_net=True)
                d.text((cx+pad, cy), "0", fill=font_main, font=font_mono_sm)
                cy += 20
                cy = draw_graph(cx+pad, cy, cw-pad*2, 30, [max(0, x-5) for x in list(CPU_USAGE_HISTORY)], 100, "mixed", color=font_blue, current_val=0)

    # VLAN
    if settings.get('gk_show_vlan', False):
        if request_space(45):
            cy = draw_sep(cx, cy, cw, "vlan1", is_net=True)
            d.text((cx+pad, cy), "0", fill=font_main, font=font_mono_sm)
            cy += 25

    # SYS (TENSÕES)
    if settings.get('gk_show_sys', True):
        sensors_sys = []
        try:
            temps = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
            fans = psutil.sensors_fans() if hasattr(psutil, "sensors_fans") else {}
            # get some random actual sys values for hardware feeling
            for name, entries in temps.items():
                if "nvme" in name or "acpi" in name or "k10temp" in name:
                    for e in entries[:2]:
                        lbl = e.label if e.label else name
                        sensors_sys.append((lbl[:6], f"{e.current}°C"))
            for name, entries in fans.items():
                for e in entries[:2]:
                    lbl = e.label if e.label else name
                    sensors_sys.append((lbl[:6], f"{e.current}R"))
        except: pass
        
        if not sensors_sys: # Fallback dummy
            sensors_sys = [
                ("Vcore", "1.79V"),
                ("+3.3V", "3.29V"),
                ("+5V", "5.00V"),
                ("Fan0", "3770")
            ]
        
        sensors_sys = sensors_sys[:6] # Limite para não explodir layout
        if request_space(35 + len(sensors_sys)*20):
            cy = draw_sep(cx, cy, cw, "sys")
            
            # Adiciona sensores avançados solicitados se existirem na GPU ativa
            gpu = SYSTEM_STATS["gpus"][0] if SYSTEM_STATS["gpus"] else {}
            for label in ["ppt", "edge", "junc", "mem", "vddgfx", "vddnb", "power"]:
                if label in gpu:
                    sensors_sys.append((label, gpu[label]))
            
            for k, v in sensors_sys[:10]: # Aumentado limite
                d.text((cx+pad, cy), k, fill=font_main, font=font_mono_sm)
                tw = get_text_width(d, v, font_mono_sm)
                d.text((cx+cw-tw-pad, cy), v, fill=font_main, font=font_mono_sm)
                cy += 20
            cy += 10

    # HDA (I/O)
    if settings.get('gk_show_hda', True):
        if request_space(100):
            disk_u = SYSTEM_STATS.get('disk_percent', 0)
            io_kb = SYSTEM_STATS.get('disk_io_kbs', 0)
            io_str = f"{io_kb/1024:.1f}M" if io_kb > 1024 else f"{io_kb:.1f}K"
            
            cy = draw_sep(cx, cy, cw, "hda")
            cy = draw_graph(cx+pad, cy, cw-pad*2, graph_h, list(DISK_IO_HISTORY), 500, "mixed", color=font_blue, current_val=min(500, io_kb))
            d.text((cx+pad, cy), f"{disk_u}%", fill=font_main, font=font_mono_sm)
            vw = get_text_width(d, io_str, font_mono_sm)
            d.text((cx+cw-vw-pad, cy), io_str, fill=font_dim, font=font_mono_sm)
            cy += 20
            cy += 5

    # INET0
    if settings.get('gk_show_inet', False):
        if request_space(80):
            cy = draw_sep(cx, cy, cw, "inet0", is_net=True)
            d.text((cx+pad, cy), "0", fill=font_main, font=font_mono_sm)
            cy += 20
            cy = draw_graph(cx+pad, cy, cw-pad*2, 30, [max(0, x-5) for x in list(CPU_USAGE_HISTORY)], 100, "mixed", color=font_blue, current_val=0)

    # BATTERY
    if settings.get('gk_show_battery', False):
        if request_space(50):
            try:
                bat = psutil.sensors_battery()
                b_pct = bat.percent if bat else 100
                plt = "AC" if bat and bat.power_plugged else "BAT"
                prof = SYSTEM_STATS.get("power_profile", "")
                bat_str = f"{b_pct}% {plt}"
                if prof: bat_str += f" [{prof}]"
            except:
                bat_str = "100% AC"
            cy = draw_sep(cx, cy, cw, "bat0")
            d.text((cx+pad, cy), bat_str, fill=font_main, font=font_mono_sm)
            cy += 25
    
    # Preenchimentos
    d.line((0, height-2, width, height-2), fill=line_bot, width=2)
    return img
def render_dashboard(width, height, settings):
    if settings.get("theme") == "gkrellm":
        return render_dashboard_gkrellm(width, height, settings)
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
    except Exception:
        font_time = font_md = font_sm = ImageFont.load_default()

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
                resamp = 1
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
    except Exception:
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
    except Exception:
        font_time = font_md = font_sm = ImageFont.load_default()

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
                resamp = 1
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
    except Exception:
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
                resamp = 1
                
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
        
    for i in range(1, frames_in + 1):
        progress = i / frames_in
        ease_out = 1 - (1 - progress) * (1 - progress)
        blend_and_generate(0.5 + 0.5 * ease_out, int(255 * progress))
        
    hold_frame_data = pre_rendered_frames[-1]
        
    for i in range(frames_out, -1, -1):
        progress = i / frames_out
        blend_and_generate(1.0, int(255 * progress))
        
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
            time.sleep(0.5)
    except KeyboardInterrupt:
        lcd.set_backlight(0)

if __name__ == '__main__':
    main()
