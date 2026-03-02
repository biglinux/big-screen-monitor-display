import re

with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "r") as f:
    content = f.read()

# Start of the function
start_pattern = """def render_dashboard_gkrellm(width, height, settings):
    theme_colors = get_theme_colors("gkrellm")
    bg_color = (0, 0, 0)
    img = Image.new('RGB', (width, height), color=(0, 0, 5)) # Fundo preto bem proximo do azul escuro
    d = ImageDraw.Draw(img)"""

replacement = """def render_dashboard_gkrellm(width, height, settings):
    theme_colors = get_theme_colors("gkrellm")
    
    orig_w, orig_h = width, height
    
    # Define a dynamically fitting resolution limit for retro UI
    # Best layout is around 400x240 for this font/spacing.
    # We will scale it proportionally.
    scale = max(1, orig_h // 240) 
    
    width = orig_w // scale
    height = orig_h // scale

    bg_color = (0, 0, 0)
    img = Image.new('RGB', (width, height), color=(0, 0, 5))
    d = ImageDraw.Draw(img)"""

content = content.replace(start_pattern, replacement)

end_pattern = """    # Final little gkrellm info
    cy = draw_sep(cx, cy, cw, "linux")
    
    return img"""

end_replacement = """    # Final little gkrellm info
    cy = draw_sep(cx, cy, cw, "linux")
    
    try:
        resamp = Image.Resampling.NEAREST
    except AttributeError:
        resamp = Image.NEAREST
        
    img = img.resize((orig_w, orig_h), resamp)
    return img"""

content = content.replace(end_pattern, end_replacement)

with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "w") as f:
    f.write(content)
