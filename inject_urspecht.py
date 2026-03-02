import re

with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "r") as f:
    content = f.read()

# Replace theme colors
gkrellm_theme_old = """        "gkrellm": {
            "bg": (15, 15, 15), "panel_bg": (50, 50, 55), "text_main": (220, 220, 220),
            "text_muted": (150, 150, 150), "text_label": (180, 180, 180), "time": (255, 255, 255),
            "good": (0, 200, 255), "warn": (255, 165, 0), "crit": (255, 50, 50),
            "vram": (150, 150, 200), "swap": (100, 150, 200), "disk": (150, 180, 150),
            "temp_line": (200, 200, 250), "bar_bg": (20, 25, 30), "border": (80, 80, 90),
            "icon_color": (200, 200, 200)
        }"""

urspecht_theme = """        "gkrellm": {
            "bg": (0, 0, 0), "panel_bg": (0, 0, 0), "text_main": (170, 255, 170),
            "text_muted": (85, 170, 85), "text_label": (85, 170, 85), "time": (170, 255, 170),
            "good": (170, 255, 170), "warn": (170, 255, 170), "crit": (170, 255, 170),
            "vram": (170, 255, 170), "swap": (170, 255, 170), "disk": (170, 255, 170),
            "temp_line": (170, 255, 170), "bar_bg": (0, 0, 0), "border": (85, 170, 85),
            "icon_color": (170, 255, 170)
        }"""

content = content.replace(gkrellm_theme_old, urspecht_theme)

# Find the start and end of render_dashboard_gkrellm
start_idx = content.find("def render_dashboard_gkrellm(")
end_idx = content.find("def render_dashboard(", start_idx)

new_func = """def render_dashboard_gkrellm(width, height, settings):
    theme_colors = get_theme_colors("gkrellm")
    bg_color = (0, 0, 0)
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    font_px = ImageFont.load_default()
    
    font_main = (170, 255, 170) # Verde claro fosforescente
    font_dim  = (85, 170, 85)   # Verde escuro
    border_cl = (85, 170, 85)
    
    col_w = width // 4
    pad = 4

    def draw_sep(x, y, w, title=""):
        d.line((x, y, x+w, y), fill=border_cl)
        if title:
            d.rectangle((x, y+1, x+w, y+13), fill=(20, 40, 20))
            tw = get_text_width(d, title, font_px)
            d.text((x + (w-tw)//2, y+1), title, fill=font_main, font=font_px)
            d.line((x, y+14, x+w, y+14), fill=border_cl)
            return y + 16
        return y + 2
        
    def format_bytes(b):
        if b < 1024: return f"{b}"
        elif b < 1024*1024: return f"{b/1024:.1f}K"
        else: return f"{b/(1024*1024):.1f}M"

    # ================= COL 1 =================
    cx = 0
    cy = 2
    cw = col_w - 2
    
    # Bloco 1: URSPECHT
    tw = get_text_width(d, "URSPECHT", font_px)
    d.text((cx + (cw-tw)//2, cy), "URSPECHT", fill=font_main, font=font_px)
    cy += 14
    
    from datetime import datetime
    now = datetime.now()
    ds = now.strftime("%a %d %b")
    tw = get_text_width(d, ds, font_px)
    d.text((cx + (cw-tw)//2, cy), ds, fill=font_main, font=font_px)
    cy += 14
    
    ts = now.strftime("%H:%M:%S")
    tw = get_text_width(d, ts, font_px)
    d.text((cx + (cw-tw)//2, cy), ts, fill=font_main, font=font_px)
    cy += 18
    
    # Bloco 2: CPU
    cy = draw_sep(cx, cy, cw, "CPU")
    cpu_p = SYSTEM_STATS.get('cpu_percent', 0)
    d.text((cx+2, cy), f"{cpu_p:.0f}%", fill=font_main, font=font_px)
    cy += 14
    
    # Historico (grafico barras)
    hist = list(CPU_USAGE_HISTORY)
    h_graph = 25
    d.rectangle((cx+2, cy, cx+cw-2, cy+h_graph), fill=(0,0,0), outline=font_dim)
    if hist:
        step = (cw-4) / max(1, len(hist)-1)
        for i, val in enumerate(hist):
            px = cx + 2 + int(i*step)
            py = cy + h_graph - int((min(val, 100)/100.0)* (h_graph-2)) - 1
            if py < cy + h_graph - 1:
                d.line((px, py, px, cy+h_graph-2), fill=(50,150,50))
                d.line((px, py, px, py), fill=font_main) # Top dot
    cy += h_graph + 4
    
    d.text((cx+2, cy), "CPU", fill=font_main, font=font_px)
    tw = get_text_width(d, SYSTEM_STATS['cpu_temp'], font_px)
    d.text((cx+cw-tw-2, cy), SYSTEM_STATS['cpu_temp'], fill=font_main, font=font_px)
    cy += 12
    d.text((cx+2, cy), "chipset", fill=font_dim, font=font_px)
    d.text((cx+cw-tw-2, cy), "45.0°C", fill=font_main, font=font_px) # Fake chipset se não houver
    cy += 16
    
    cy = draw_sep(cx, cy, cw, "eth0")
    tx = SYSTEM_STATS.get('net_tx_mbps', 0) * 1024 # emulate KB
    d.text((cx+2, cy), format_bytes(tx), fill=font_main, font=font_px)
    cy += 14
    # Historico eth0 (mock or line)
    d.rectangle((cx+2, cy, cx+cw-2, cy+20), fill=(0,0,0), outline=font_dim)
    
    # ================= COL 2 =================
    cx = col_w * 1
    cy = 2
    cw = col_w - 2
    
    # Proc
    cy = draw_sep(cx, cy, cw, "Proc")
    procs = sum(1 for p in SYSTEM_STATS.get('procs', []))
    if procs == 0: procs = 133
    d.text((cx+2, cy), f"{procs} procs", fill=font_main, font=font_px)
    cy += 12
    d.text((cx+2, cy), "3 users", fill=font_main, font=font_px)
    cy += 16
    
    d.rectangle((cx+2, cy, cx+cw-2, cy+25), fill=(0,0,0), outline=font_dim)
    cy += 25 + 4
    
    # Memoria
    cy = draw_sep(cx, cy, cw, "Mem")
    mem_p = SYSTEM_STATS.get('ram_percent', 0)
    d.rectangle((cx+2, cy, cx+cw-2, cy+10), fill=(0,0,0), outline=font_dim)
    fill_w = int((cw-4) * (mem_p/100.0))
    if fill_w > 0:
        d.rectangle((cx+2, cy, cx+2+fill_w, cy+10), fill=font_main)
    cy += 14
    
    # Swap
    cy = draw_sep(cx, cy, cw, "Swap")
    swap_p = SYSTEM_STATS.get('swap_percent', 0)
    d.rectangle((cx+2, cy, cx+cw-2, cy+10), fill=(0,0,0), outline=font_dim)
    fill_w = int((cw-4) * (swap_p/100.0))
    if fill_w > 0:
        d.rectangle((cx+2, cy, cx+2+fill_w, cy+10), fill=font_main)
    cy += 14
    
    cy = draw_sep(cx, cy, cw)
    d.text((cx+2, cy), "> cdrom", fill=font_main, font=font_px)
    d.rectangle((cx+cw-12, cy+2, cx+cw-2, cy+8), fill=(80,80,80), outline=(150,150,150))
    cy += 14
    d.text((cx+2, cy), "> keydrive", fill=font_main, font=font_px)
    d.rectangle((cx+cw-12, cy+2, cx+cw-2, cy+8), fill=(80,80,80), outline=(150,150,150))
    cy += 14
    d.text((cx+2, cy), "> cardread", fill=font_main, font=font_px)
    d.rectangle((cx+cw-12, cy+2, cx+cw-2, cy+8), fill=(80,80,80), outline=(150,150,150))
    cy += 14
    d.text((cx+2, cy), "> fwdrive", fill=font_main, font=font_px)
    d.rectangle((cx+cw-12, cy+2, cx+cw-2, cy+8), fill=(80,80,80), outline=(150,150,150))
    
    # ================= COL 3 =================
    cx = col_w * 2
    cy = 2
    cw = col_w - 2
    
    # Audio
    # Centered Logo
    d.text((cx + cw//2 - 10, cy+10), "( )", fill=(0, 200, 255), font=font_px)
    d.text((cx + cw//2 + 10, cy+10), "4/4", fill=font_main, font=font_px)
    cy += 35
    
    d.text((cx+2, cy), "Pcm", fill=font_main, font=font_px)
    d.line((cx+30, cy+6, cx+cw-10, cy+6), fill=font_dim)
    d.ellipse((cx+cw-15, cy+3, cx+cw-5, cy+9), fill=font_main)
    cy += 14
    
    d.text((cx+2, cy), "CD", fill=font_main, font=font_px)
    d.line((cx+30, cy+6, cx+cw-10, cy+6), fill=font_dim)
    d.ellipse((cx+40, cy+3, cx+50, cy+9), fill=font_main)
    cy += 14
    
    time_str = "15d 2:00"
    tw = get_text_width(d, time_str, font_px)
    d.text((cx + (cw-tw)//2, cy), time_str, fill=font_dim, font=font_px)
    cy += 14
    tw = get_text_width(d, "nexus", font_px)
    d.text((cx + (cw-tw)//2, cy), "nexus", fill=font_dim, font=font_px)
    cy += 18
    
    d.rectangle((cx+2, cy, cx+cw-2, cy+30), fill=(0,0,0), outline=font_dim)
    # fake audio bars
    for i in range(15):
        h_a = (i*13 % 20) + 2
        d.rectangle((cx+4+i*4, cy+30-h_a, cx+6+i*4, cy+30), fill=font_main)
    cy += 30+4
    
    cy = draw_sep(cx, cy, cw, "CPU")
    d.text((cx+2, cy), f"{SYSTEM_STATS.get('cpu_cores_percent', [0])[0]:.0f}", fill=font_main, font=font_px)
    cy += 12
    d.rectangle((cx+2, cy, cx+cw-2, cy+25), fill=(0,0,0), outline=font_dim)
    cy += 25+4
    
    cy = draw_sep(cx, cy, cw, "Wan")
    rx_k = SYSTEM_STATS.get('net_rx_mbps', 0) * 1024
    d.text((cx+2, cy), f"{format_bytes(rx_k)}", fill=font_main, font=font_px)
    cy += 12
    d.rectangle((cx+2, cy, cx+cw-2, cy+25), fill=(0,0,0), outline=font_dim)
    cy += 25+4
    
    
    # ================= COL 4 =================
    cx = col_w * 3
    cy = 2
    cw = width - cx - 5
    
    # SYSTEM SENSORS
    cy = draw_sep(cx, cy, cw, "sys")
    
    # Some hardcoded values per user request + some real
    sensors = [
        ("Vcore", "1.79V"),
        ("+3.3V", "3.29V"),
        ("+5V", "5.00V"),
        ("+12V", "11.7V"),
        ("fan 0", "3770"),
        ("fan 1", "3750")
    ]
    
    for k, v in sensors:
        d.text((cx+2, cy), k, fill=font_main, font=font_px)
        vw = get_text_width(d, v, font_px)
        d.text((cx+cw-vw-2, cy), v, fill=font_main, font=font_px)
        cy += 12
        
    cy += 8
    disk_u = SYSTEM_STATS.get('disk_percent', 0)
    cy = draw_sep(cx, cy, cw, "hda")
    d.text((cx+2, cy), f"{disk_u}%", fill=font_main, font=font_px)
    vw = get_text_width(d, "1.4M", font_px)
    d.text((cx+cw-vw-2, cy), "1.4M", fill=font_dim, font=font_px)
    cy += 12
    d.rectangle((cx+2, cy, cx+cw-2, cy+25), fill=(0,0,0), outline=font_dim)
    cy += 25+4
    
    cy = draw_sep(cx, cy, cw, "inet0")
    tx_k = SYSTEM_STATS.get('net_tx_mbps', 0) * 1024
    d.text((cx+2, cy), f"t {format_bytes(tx_k)}", fill=font_main, font=font_px)
    cy += 12
    d.text((cx+2, cy), f"r {format_bytes(rx_k)}", fill=font_main, font=font_px)
    cy += 12
    d.rectangle((cx+2, cy, cx+cw-2, cy+25), fill=(0,0,0), outline=font_dim)
    cy += 25+4
    
    # Final little gkrellm info
    cy = draw_sep(cx, cy, cw, "linux")
    
    return img

"""

content = content[:start_idx] + new_func + content[end_idx:]

with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "w") as f:
    f.write(content)
