import re

path = '/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py'
with open(path, 'r') as f:
    content = f.read()

# Fix bare excepts
content = re.sub(r'except:\n(\s+)pass', r'except Exception:\n\1pass', content)
content = re.sub(r'except:\n(\s+)return False', r'except Exception:\n\1return False', content)
content = re.sub(r'except:\n', r'except Exception:\n', content)

# Remove unused vars from except Exception as e:
content = re.sub(r'except Exception as e:\n(\s+)pass', r'except Exception:\n\1pass', content)

# Fix ANTIALIAS deprecation
content = content.replace('Image.ANTIALIAS if hasattr(Image, "ANTIALIAS") else 1', '1')
content = content.replace('resamp = Image.ANTIALIAS', 'resamp = Image.Resampling.LANCZOS')

# Fix unused font vars in main.py
content = re.sub(r'font_time = font_lg = font_md = font_sm = font_icon = ImageFont.load_default\(\)', r'font_time = font_md = font_sm = ImageFont.load_default()', content)

# Now, the complex psutil.sensors_temperatures() and Lock ()
lock_def = """import psutil
import io
from PIL import Image, ImageDraw, ImageFont

STATS_LOCK = threading.Lock()
"""
content = content.replace("import psutil\nimport io\nfrom PIL import Image, ImageDraw, ImageFont\n", lock_def)

# Find the monitor thread and replace the `sensors` loop
old_sensors = """            try:
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
            except Exception:
                pass"""

new_sensors = """            try:
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
                pass"""

content = content.replace(old_sensors, new_sensors)

# Add locks around other history accesses
content = re.sub(r'(CPU_USAGE_HISTORY\.append\(SYSTEM_STATS\["cpu_percent"\]\)\n\s+CPU_USAGE_HISTORY\.pop\(0\))', r'with STATS_LOCK:\n                \1', content)
content = re.sub(r'(RAM_USAGE_HISTORY\.append\(mem\.percent\)\n\s+RAM_USAGE_HISTORY\.pop\(0\))', r'with STATS_LOCK:\n                \1', content)

with open(path, 'w') as f:
    f.write(content)

print("Fixed main.py")
