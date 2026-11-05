# Big Media Player — configurações

As opções ficam em `/etc/big-screen-monitor-display/settings.json` (prefixo
`bmp_`), validadas por `bsmd/settings.py` como as dos outros temas, e podem ser
sobrescritas por display (exceto as globais). Na janela, a aba **Big Media
Player** aparece quando o tema está aplicado.

## Aba Big Media Player

| Grupo | Conteúdo |
| --- | --- |
| Prévia | renderização ao vivo com a música real (ou `DEMO` sem players) |
| Tocando agora | estado; escolha do player (Automático/detectados); anterior, play/pause, stop, próximo, aleatório, repetir; posição com busca; volume do sistema (slider, −, +, mudo, saída). Atalhos: Ctrl+Espaço, Ctrl+←/→, Ctrl+↑/↓, Ctrl+M |
| Skins | galeria das 7 com miniatura renderizada no tamanho do display, descrição, inspiração e compatibilidade com a resolução |
| Aparência | layout, texto, tamanho/forma/moldura da capa, brilho, capa desfocada atrás do texto, modo vinil, cores da capa, textura LCD, transição |
| Metadados | campos visíveis, rolagem e velocidade, logo (automática/personalizada/oculta), estilo da logo, importar logo |
| Reprodução | modo do player, player fixo, aplicativos ignorados, troca automática, teclas, tempo total/restante, porcentagem, dados de demonstração |
| Volume | mostrar, origem (sistema/aplicativo), porcentagem, nome da saída, passo, máximo seguro, saída acompanhada |
| Telemetria | modo, posição, intervalos, limites de alerta, itens, ícones, separador, opacidade, animação |
| Visualizador | desligado / decorativo / espectro real, estilo, sensibilidade |
| Sem reprodução | tela de espera, após quanto tempo, outro tema, escurecer, modo noturno, skin noturna, skin por aplicativo |
| Diagnóstico | agente (pid, sockets), socket do serviço, players MPRIS e capacidades, sistema de áudio, cache de capas (limpar), erros recentes, recarregar sessão |

Todas as opções listadas têm efeito real; nenhuma é só visual.

## Chaves

| Chave | Valores (padrão em **negrito**) |
| --- | --- |
| `bmp_skin` | **bigamp**, bigmatch, bigative, bigalplayer, bigmediaplayer, bigxmms2, bigx |
| `bmp_layout` | **auto**, full, compact, party, info, low_power |
| `bmp_text_size`, `bmp_art_size` | small, **normal**, large |
| `bmp_art_shape` | **skin**, square, rounded, circle |
| `bmp_art_frame` | **skin**, metal, neon, none |
| `bmp_art_glow`, `bmp_art_background`, `bmp_vinyl`, `bmp_adaptive_colors` | **false** |
| `bmp_lcd_effect`, `bmp_glow`, `bmp_transitions` | **true** |
| `bmp_show_title/artist/album/description/source` | **true** |
| `bmp_marquee` / `bmp_marquee_speed` | **true** / slow, **normal**, fast |
| `bmp_logo` / `bmp_logo_style` / `bmp_logo_custom` | **auto**, custom, none / logo, **logo_name**, name / id da imagem importada |
| `bmp_player_mode` | **auto**, last, fixed |
| `bmp_player_fixed`, `bmp_player_ignore` | texto (≤ 80 / ≤ 200) |
| `bmp_auto_switch`, `bmp_show_controls` | **true** |
| `bmp_time_mode` / `bmp_show_percent` | **total**, remaining / **false** |
| `bmp_show_volume`, `bmp_volume_percent` | **true** |
| `bmp_volume_source` | **system**, player |
| `bmp_show_output` | **false** |
| `bmp_volume_step` / `bmp_volume_max` | 1–20 (**5**) / 100–150 (**100**) |
| `bmp_volume_sink` | vazio = saída padrão |
| `bmp_visualizer` / `bmp_vis_style` / `bmp_vis_sensitivity` | off, **decorative**, spectrum / **bars**, led, vu, scope / 50–200 (**100**) |
| `bmp_tele_*` | ver [telemetria](big-media-player-telemetry.md) |
| `bmp_idle_mode` | **screen**, last_art, clock, telemetry, rest, theme |
| `bmp_idle_after` / `bmp_idle_dim` / `bmp_idle_theme` | 5–3600 s (**120**) / **false** / **standard** e demais temas |
| `bmp_preview_demo` | **true** (só a prévia da janela) |
| `bmp_night`, `bmp_night_start`, `bmp_night_end`, `bmp_night_skin` | **false**, **22**, **7**, **same** |
| `bmp_app_skins` | ex.: `spotify=bigamp, firefox=bigmatch` |

## Comportamentos especiais

- **Sem reprodução** (`bmp_idle_mode`): tela de espera com logo da distro e
  relógio (`screen`); última faixa esmaecida (`last_art`); relógio grande de 7
  segmentos (`clock`); telemetria ampliada (`telemetry`); modo descanso escuro
  com relógio pequeno que muda de lugar a cada minuto (`rest`, contra
  marcação da tela); outro tema (`theme`) — a preferência salva não muda e o
  player volta assim que algo tocar.
- **Modo noturno**: escurece o quadro e pode trocar a skin no horário.
- **Skin por aplicativo**: a skin muda conforme o player mostrado.
- **Prévia**: sem player, dados `DEMO` claramente marcados; no display, nunca.
