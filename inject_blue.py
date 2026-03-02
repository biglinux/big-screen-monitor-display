import re

with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "r") as f:
    content = f.read()

# Make sure we are replacing the URSPECHT vars
old_vars = """    bg_color = (0, 0, 0)
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
        return y + 2"""

new_vars = """    bg_color = (0, 0, 0)
    img = Image.new('RGB', (width, height), color=(0, 0, 5)) # Fundo preto bem proximo do azul escuro
    d = ImageDraw.Draw(img)
    
    font_px = ImageFont.load_default()
    
    # URLICHT Blue Neon Theme
    font_main  = (230, 230, 240)    # Cinza claro / Branco suave para textos princ
    font_dim   = (70, 110, 255)     # Azul neonzinho para titulos (CPU, Proc)
    font_blue  = (40, 80, 240)      # Azul escuro pra detalhes
    border_cl  = (120, 120, 130)    # Borda cinza clara bevel cima
    border_dk  = (40, 40, 50)       # Borda cinza escuro bevel baixo
    bar_color  = (0, 140, 255)      # Cor das barras de progresso (azul meio cyan)
    bar_bg     = (0, 15, 40)        # Fundo do grafico simulando LED
    
    col_w = width // 4
    pad = 4

    def draw_sep(x, y, w, title=""):
        # Bevel line
        d.line((x, y, x+w, y), fill=border_dk)
        if title:
            # gradient-like box
            d.rectangle((x, y+1, x+w, y+13), fill=(45, 45, 50))
            tw = get_text_width(d, title, font_px)
            d.text((x + (w-tw)//2, y+1), title, fill=font_main, font=font_px) # "CPU" text in white bg grey
            d.line((x, y+14, x+w, y+14), fill=border_dk)
            return y + 16
        return y + 2"""

content = content.replace(old_vars, new_vars)

# Top URSPECHT Title becomes 'urlicht'
content = content.replace('d.text((cx + (cw-tw)//2, cy), "URSPECHT", fill=font_main, font=font_px)', 'd.text((cx + (cw-tw)//2, cy), "urlicht", fill=border_cl, font=font_px)')
content = content.replace('tw = get_text_width(d, "URSPECHT", font_px)', 'tw = get_text_width(d, "urlicht", font_px)')

# Replacing colors globally in the rendering block
content = content.replace('fill=(0,0,0)', 'fill=bar_bg')
content = content.replace('fill=(50,150,50)', 'fill=font_blue')
content = content.replace('d.line((px, py, px, py), fill=font_main)', 'd.line((px, py, px, py), fill=(100, 200, 255))') # dot
content = content.replace('d.text((cx+2, cy), "CPU", fill=font_main', 'd.text((cx+2, cy), "CPU", fill=font_dim')
content = content.replace('d.text((cx+2, cy), "chipset", fill=font_dim, font=font_px)', 'd.text((cx+2, cy), "chipset", fill=font_dim, font=font_px)')

# Process text
content = content.replace('d.text((cx+2, cy), "CPU", fill=font_main, font=font_px)', 'd.text((cx+2, cy), "CPU", fill=font_dim, font=font_px)')

# Memory and Swap Bars
content = content.replace('d.rectangle((cx+2, cy, cx+2+fill_w, cy+10), fill=font_main)', 'd.rectangle((cx+2, cy, cx+2+fill_w, cy+10), fill=bar_color)')

def replace_fill_font_main_for_labels(src, labels):
    new_src = src
    for lbl in labels:
        new_src = new_src.replace(f'd.text((cx+2, cy), "{lbl}"', f'd.text((cx+2, cy), "{lbl}"')
    return new_src

content = content.replace('fill=(80,80,80), outline=(150,150,150)', 'fill=(70,70,80), outline=border_cl')

# Replace exact occurrences that need font_dim
content = content.replace('d.text((cx+2, cy), "CPU", fill=font_main', 'd.text((cx+2, cy), "CPU", fill=font_dim')
content = content.replace('d.text((cx+2, cy), "Pcm", fill=font_main, font=font_px)', 'd.text((cx+2, cy), "Pcm", fill=font_main, font=font_px)')

# Small adjustments
content = content.replace('fill=font_main)', 'fill=bar_color)') 
content = content.replace('fill=font_main, font=font_px)', 'fill=font_main, font=font_px)')
content = content.replace('fill=border_cl, font=font_px)', 'fill=border_cl, font=font_px)')

# Fix bar_color where it used to be fill=(170, 255, 170)
content = content.replace('fill=bar_color, font=font_px)', 'fill=font_main, font=font_px)')

# Audio ellipses
content = content.replace('d.ellipse((cx+cw-15, cy+3, cx+cw-5, cy+9), fill=bar_color)', 'd.ellipse((cx+cw-15, cy+3, cx+cw-5, cy+9), fill=(50,100,200))')
content = content.replace('d.ellipse((cx+40, cy+3, cx+50, cy+9), fill=bar_color)', 'd.ellipse((cx+40, cy+3, cx+50, cy+9), fill=(50,100,200))')


with open("/home/ruscher/Documentos/Git/github-biglinux/big-screen-monitor-display/big-screen-monitor-display/usr/share/big-screen-monitor-display/main.py", "w") as f:
    f.write(content)
