import re

with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "r") as f:
    content = f.read()

if "cpu_cores_history" not in content:
    # 1. Add cpu_cores_history
    content = content.replace('"gpus": [],', '"gpus": [],\n    "cpu_cores_history": [],\n    "cpu_cores_percent": [],')

    # 2. Update monitor_thread
    monitor_patch = """            SYSTEM_STATS["cpu_percent"] = psutil.cpu_percent(interval=None)
            cpu_cores = psutil.cpu_percent(interval=None, percpu=True)
            with STATS_LOCK:
                SYSTEM_STATS["cpu_cores_percent"] = cpu_cores
                if not SYSTEM_STATS["cpu_cores_history"]:
                    SYSTEM_STATS["cpu_cores_history"] = [[] for _ in cpu_cores]
                for i, c in enumerate(cpu_cores):
                    if i < len(SYSTEM_STATS["cpu_cores_history"]):
                        SYSTEM_STATS["cpu_cores_history"][i].append(c)
                        if len(SYSTEM_STATS["cpu_cores_history"][i]) > 40:
                            SYSTEM_STATS["cpu_cores_history"][i].pop(0)"""
    content = re.sub(r'SYSTEM_STATS\["cpu_percent"\] = psutil\.cpu_percent\(interval=None\)', monitor_patch, content)

    # 3. Add GKrellM theme dict
    gkrellm_theme = """
        "cyberpunk": {
            "bg": (2, 2, 4), "panel_bg": (10, 10, 15), "text_main": (253, 237, 5),
            "text_muted": (153, 143, 3), "text_label": (255, 99, 146), "time": (0, 240, 255),
            "good": (22, 198, 12), "warn": (253, 237, 5), "crit": (255, 25, 76),
            "vram": (138, 43, 226), "swap": (0, 240, 255), "disk": (200, 200, 200),
            "temp_line": (255, 140, 0), "bar_bg": (20, 20, 30), "border": (253, 237, 5),
            "icon_color": (255, 255, 255)
        },
        "gkrellm": {
            "bg": (15, 15, 15), "panel_bg": (50, 50, 55), "text_main": (220, 220, 220),
            "text_muted": (150, 150, 150), "text_label": (180, 180, 180), "time": (255, 255, 255),
            "good": (0, 200, 255), "warn": (255, 165, 0), "crit": (255, 50, 50),
            "vram": (150, 150, 200), "swap": (100, 150, 200), "disk": (150, 180, 150),
            "temp_line": (200, 200, 250), "bar_bg": (20, 25, 30), "border": (80, 80, 90),
            "icon_color": (200, 200, 200)
        }"""
    content = content.replace('"cyberpunk": {', gkrellm_theme[1:].split('"cyberpunk": {')[1])

    # 4. Inject render_dashboard_gkrellm
    gk_render = """
def render_dashboard_gkrellm(width, height, settings):
    theme_colors = get_theme_colors("gkrellm")
    bg_color = theme_colors["bg"]
    img = Image.new('RGB', (width, height), color=bg_color)
    d = ImageDraw.Draw(img)
    
    font_dir = os.path.join(BASE_DIR, "fonts")
    try:
        font_lg = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans-Bold.ttf"), int(height * 0.035))
        font_md = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.025))
        font_sm = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.020))
        font_tiny = ImageFont.truetype(os.path.join(font_dir, "DejaVuSans.ttf"), int(height * 0.015))
    except (OSError, IOError):
        font_lg = font_md = font_sm = font_tiny = ImageFont.load_default()

    curr_y = 5
    padding = 10
    w_box = width - (padding * 2)
    x_off = padding

    def draw_separator(y, label, val=""):
        h_sep = int(height * 0.03)
        d.rectangle((x_off, y, x_off+w_box, y+h_sep), fill=(70, 70, 75))
        d.line((x_off, y, x_off+w_box, y), fill=(120, 120, 125)) # top
        d.line((x_off, y, x_off, y+h_sep), fill=(120, 120, 125)) # left
        d.line((x_off, y+h_sep, x_off+w_box, y+h_sep), fill=(30, 30, 30)) # bot
        d.line((x_off+w_box, y, x_off+w_box, y+h_sep), fill=(30, 30, 30)) # right
        
        tw = get_text_width(d, label, font_md)
        d.text((width//2 - tw//2, y + 2), label, fill=(230, 230, 230), font=font_md)
        if val:
            vw = get_text_width(d, val, font_md)
            d.text((x_off+w_box - vw - 5, y + 2), val, fill=(0, 200, 255), font=font_md)
        return y + h_sep + 2
        
    def draw_graph(y, data, color, max_v=100, label_left="", label_right="", label_mid=""):
        h_graph = int(height * 0.05)
        gx = x_off + 2
        gw = w_box - 4
        d.rectangle((gx, y, gx+gw, y+h_graph), fill=(0, 0, 10)) 
        
        d.line((gx, y+h_graph//2, gx+gw, y+h_graph//2), fill=(0, 40, 60))
        d.line((gx+gw//2, y, gx+gw//2, y+h_graph), fill=(0, 40, 60))
        
        d.line((gx, y, gx+gw, y), fill=(20, 20, 20))
        d.line((gx, y, gx, y+h_graph), fill=(20, 20, 20))
        d.line((gx, y+h_graph, gx+gw, y+h_graph), fill=(90, 90, 90))
        d.line((gx+gw, y, gx+gw, y+h_graph), fill=(90, 90, 90))

        if data and len(data) > 0:
            step = float(gw) / max(1, len(data) - 1)
            for i in range(len(data)):
                px = gx + i*step
                val = min(data[i], max_v)
                py = y + h_graph - ( (val / max_v) * (h_graph - 2) ) - 1
                if py < y + h_graph - 1:
                    d.line((px, py, px, y+h_graph-2), fill=color, width=max(1, int(step)))
                    
        if label_left:
            d.text((gx + 4, y + 2), label_left, fill=(200, 200, 200), font=font_sm)
        if label_mid:
            tw = get_text_width(d, label_mid, font_sm)
            d.text((width//2 - tw//2, y + 2), label_mid, fill=(255, 255, 255), font=font_sm)
        if label_right:
            tw = get_text_width(d, label_right, font_sm)
            d.text((gx + gw - tw - 4, y + 2), label_right, fill=(0, 200, 255), font=font_sm)
            
        return y + h_graph + 2

    os_info = get_os_release()
    pname = os_info.get("PRETTY_NAME", "Linux OS")
    
    curr_y = draw_separator(curr_y, "gkrellm")
    
    d.text((x_off + 5, curr_y + 2), f"{SYSTEM_STATS['hostname']}", fill=(200, 200, 200), font=font_md)
    curr_y += int(height * 0.035)
    d.text((x_off + 5, curr_y), SYSTEM_STATS['kernel'], fill=(150, 150, 150), font=font_sm)
    
    from datetime import datetime
    now = datetime.now()
    ds = now.strftime("%a %d %b")
    ts = now.strftime("%H:%M:%S")
    dw = get_text_width(d, ds, font_sm)
    tw = get_text_width(d, ts, font_lg)
    
    d.text((x_off + w_box - dw - 5, curr_y - int(height * 0.03)), ds, fill=(200, 200, 200), font=font_sm)
    d.text((x_off + w_box - tw - 5, curr_y + 2), ts, fill=(255, 255, 255), font=font_lg)
    
    curr_y += int(height * 0.045)

    with STATS_LOCK:
        cores_percent = list(SYSTEM_STATS.get("cpu_cores_percent", []))
        cores_hist = [list(c) for c in SYSTEM_STATS.get("cpu_cores_history", [])]
        cpu_hist = list(CPU_USAGE_HISTORY)
        cpu_temp = SYSTEM_STATS.get('cpu_temp', '?°C')
        ram_hist = list(RAM_USAGE_HISTORY)
    
    curr_y = draw_separator(curr_y, "CPU", cpu_temp)
    
    c_count = len(cores_percent) if cores_percent else 1
    
    curr_y = draw_graph(curr_y, cpu_hist, (0, 255, 100), max_v=100, label_left="CPU", label_right=f"{SYSTEM_STATS['cpu_percent']:.0f}%")
    
    if c_count > 0:
        h_avail = height - curr_y - int(height * 0.35) 
        if h_avail > 0:
            h_core = int(h_avail / c_count)
            h_core = max(8, min(h_core, int(height * 0.035)))
            
            def draw_core_graph(y, data, color, l_left, l_right):
                gx = x_off + 2
                gw = w_box - 4
                d.rectangle((gx, y, gx+gw, y+h_core), fill=(0, 0, 10)) 
                d.line((gx, y, gx+gw, y), fill=(20, 20, 20))
                d.line((gx, y+h_core, gx+gw, y+h_core), fill=(90, 90, 90))
                if data:
                    step = float(gw) / max(1, len(data) - 1)
                    for i in range(len(data)):
                        px = gx + i*step
                        val = min(data[i], 100)
                        py = y + h_core - ( (val / 100) * (h_core - 2) ) - 1
                        if py < y + h_core - 1:
                            d.line((px, py, px, y+h_core-2), fill=color, width=max(1, int(step)))
                
                if h_core >= 10:
                    d.text((gx + 2, y), l_left, fill=(180, 180, 180), font=font_tiny)
                    tw = get_text_width(d, l_right, font_tiny)
                    d.text((gx + gw - tw - 2, y), l_right, fill=(0, 200, 255), font=font_tiny)
                return y + h_core + 2

            for i in range(c_count):
                hist = cores_hist[i] if i < len(cores_hist) else []
                curr_y = draw_core_graph(curr_y, hist, (0, 150, 200), f"CPU{i}", f"{cores_percent[i]:.0f}%")

    curr_y += 5
    curr_y = draw_separator(curr_y, "Processos / GPU")
    
    draw_procs = 3
    for i, p in enumerate(SYSTEM_STATS["procs"][:draw_procs]):
        nm = p['name'][:12]
        d.text((x_off + 5, curr_y), nm, fill=(200, 200, 200), font=font_sm)
        vw = get_text_width(d, f"{p['cpu_percent']:.0f}%", font_sm)
        d.text((x_off + w_box - vw - 5, curr_y), f"{p['cpu_percent']:.0f}%", fill=(0, 200, 255), font=font_sm)
        curr_y += int(height * 0.02)
        
    curr_y += 5
    if SYSTEM_STATS["gpus"]:
        gpu = SYSTEM_STATS["gpus"][SYSTEM_STATS["active_gpu_idx"]]
        lbl = gpu.get("name", "GPU")[:14]
        tp = gpu.get("temp", "?°C")
        curr_y = draw_graph(curr_y, [(gpu.get('percent', 0))], (255, 100, 0), max_v=100, label_left=lbl, label_right=f"{gpu.get('percent', 0):.0f}%", label_mid=tp)
    
    curr_y += 3
    curr_y = draw_separator(curr_y, "Memória")
        
    curr_y = draw_graph(curr_y, ram_hist, (0, 255, 0), max_v=100, label_left="RAM", label_right=f"{SYSTEM_STATS['ram_used_mb']}M")
    curr_y = draw_graph(curr_y, [(SYSTEM_STATS['swap_percent'])], (255, 255, 0), max_v=100, label_left="Swap", label_right=f"{SYSTEM_STATS['swap_used_mb']}M")

    curr_y += 3
    curr_y = draw_separator(curr_y, "Disco")
    curr_y = draw_graph(curr_y, [(SYSTEM_STATS['disk_percent'])], (0, 200, 255), max_v=100, label_left="/ root", label_right=SYSTEM_STATS["disk_text"], label_mid=f"{SYSTEM_STATS['disk_percent']}%")

    curr_y += 3
    curr_y = draw_separator(curr_y, "Rede (RX/TX)")
    rx = f"RX: {SYSTEM_STATS['net_rx_mbps']:.1f} M"
    tx = f"TX: {SYSTEM_STATS['net_tx_mbps']:.1f} M"
    curr_y = draw_graph(curr_y, [], (200, 0, 255), max_v=100, label_left=rx, label_right=tx)

    return img

"""
    content = content.replace("def render_dashboard(width, height, settings):", gk_render + "def render_dashboard(width, height, settings):")

    # 5. Route to gkrellm theme
    routing_patch = """def render_dashboard(width, height, settings):
    if settings.get("theme") == "gkrellm":
        return render_dashboard_gkrellm(width, height, settings)
    if settings.get("orientation") == "vertical":"""

    content = content.replace("""def render_dashboard(width, height, settings):
    if settings.get("orientation") == "vertical":""", routing_patch)

    with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "w") as f:
        f.write(content)

    print("Patched main.py with GKrellM theme.")
else:
    print("Already patched.")

