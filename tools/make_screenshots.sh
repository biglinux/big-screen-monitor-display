#!/bin/bash
# Regenerate the documentation screenshots (docs/images) from the real renderers.
set -e
cd "$(dirname "$0")/.."
OUT=docs/images
APP=usr/share/big-screen-monitor-display/main.py
mkdir -p "$OUT"
export LANGUAGE=${LANGUAGE:-pt}
for scheme in dark light neon cyberpunk nord dracula solarized high_contrast; do
    python3 "$APP" --render standard --size 480x320 --set std_scheme=$scheme --out "$OUT/theme-standard-$scheme.png" >/dev/null
done
python3 "$APP" --render standard --size 480x320 --set std_scheme=nord --set std_side_panel=graphs \
    --set std_bar_style=segmented --out "$OUT/theme-standard-graphs.png" >/dev/null
python3 "$APP" --render standard --size 320x480 --set std_scheme=dracula --out "$OUT/theme-standard-portrait.png" >/dev/null
python3 "$APP" --render gkrellm --size 800x480 --set gk_show_cores=true --out "$OUT/theme-gkrellm.png" >/dev/null
python3 "$APP" --render gkrellm --size 320x480 --set gk_theme_color=classic --out "$OUT/theme-gkrellm-portrait.png" >/dev/null
python3 "$APP" --render gkrellm --size 480x320 --set 'gk_disk_count="4"' --set gk_show_inet=false --set gk_show_cores=false --out "$OUT/theme-gkrellm-480.png" >/dev/null
python3 "$APP" --render planet --size 480x320 --out "$OUT/theme-planet.png" >/dev/null
python3 "$APP" --render planet --size 480x320 --set planet_accent=amber --out "$OUT/theme-planet-amber.png" >/dev/null
python3 "$APP" --render old_computer --size 480x320 --out "$OUT/theme-old_computer.png" >/dev/null
python3 "$APP" --render old_computer --size 800x480 --set oc_scheme=slate --set oc_show_storage=true \
    --out "$OUT/theme-old_computer-slate.png" >/dev/null
r() { python3 "$APP" --render brother_away --size "${5:-480x320}" --out "$OUT/ba-$1.png" --at "$2" --hour "$3" ${4:+--scene $4} ${6:+--weather $6} >/dev/null; }
r morning 2 8.0
r noon 2 12.5
r sunset 2 18.3
r night 2 23.0
r portrait 2 16.0 "" 320x480
r rain 3 13.0 rain_complaint 480x320 rain
python3 "$APP" --render brother_away --size 480x320 --out "$OUT/ba-coconut-away.png" --scene coconut_tree --hour 14 --at 0.8 --speech AWAAAAAY >/dev/null
r shark 16 11.0 shark
r ufo 13 2.0 ufo
python3 "$APP" --render brother_away --size 480x320 --out "$OUT/ba-raft-perplexed.png" --scene raft --hour 9 --at 0.6 --speech perplect >/dev/null
r philosopher 15 16.5 philosopher
r crab 13 10.0 crab_glasses
r big-800x480 2 17.0 "" 800x480
# Big Media Player: every skin with the labelled demonstration data of the preview.
for skin in bigamp bigmatch bigative bigalplayer bigmediaplayer bigxmms2 bigx; do
    python3 "$APP" --render big_media_player --size 480x320 --set bmp_skin=$skin --out "$OUT/bmp-$skin.png" >/dev/null
done
python3 "$APP" --render big_media_player --size 800x480 --set bmp_skin=bigamp --set bmp_vis_style=led --out "$OUT/bmp-bigamp-800.png" >/dev/null
python3 "$APP" --render big_media_player --size 320x480 --set bmp_skin=bigmatch --out "$OUT/bmp-portrait.png" >/dev/null
python3 "$APP" --render big_media_player --size 160x80 --set bmp_skin=bigx --out "$OUT/bmp-micro.png" >/dev/null
python3 "$APP" --render big_media_player --size 1920x480 --set bmp_skin=bigative --out "$OUT/bmp-ultrawide.png" >/dev/null
python3 "$APP" --render big_media_player --size 480x320 --set bmp_skin=bigmediaplayer --set bmp_vinyl=true \
    --set bmp_tele_position=overlay --set bmp_tele_mode=always --out "$OUT/bmp-vinyl-overlay.png" >/dev/null
python3 "$APP" --render big_media_player --size 480x320 --set bmp_skin=bigxmms2 --set bmp_preview_demo=false \
    --out "$OUT/bmp-idle.png" >/dev/null
python3 "$APP" --render big_media_player --size 480x320 --set bmp_skin=bigx --set bmp_preview_demo=false \
    --set bmp_idle_mode=clock --out "$OUT/bmp-idle-clock.png" >/dev/null
# Big Media Player — Modern Collection (default settings, not this machine's).
M="env BSM_CONFIG=/nonexistent/settings.json python3 $APP --render big_media_player"
for skin in vinyl pure ember groove lounge wave flow stage; do
    $M --size 480x320 --set bmp_skin=big_$skin --set bmp_show_output=true --out "$OUT/bmp-modern-$skin.png" >/dev/null
done
$M --size 320x480 --set bmp_skin=big_flow --out "$OUT/bmp-modern-portrait.png" >/dev/null
$M --size 1920x480 --set bmp_skin=big_stage --out "$OUT/bmp-modern-ultrawide.png" >/dev/null
$M --size 160x80 --set bmp_skin=big_wave --set bmp_tele_mode=hidden --out "$OUT/bmp-modern-micro.png" >/dev/null
$M --size 800x480 --set bmp_skin=big_groove --out "$OUT/bmp-modern-groove-800.png" >/dev/null
$M --size 480x320 --set bmp_skin=big_pure --set bmp_pure_tone=graphite --out "$OUT/bmp-modern-pure-graphite.png" >/dev/null
$M --size 480x320 --set bmp_skin=big_lounge --set bmp_palette=contrast --out "$OUT/bmp-modern-contrast.png" >/dev/null
python3 tools/make_bmp_gallery.py "$OUT/bmp-modern-gallery.png" modern 480x320 >/dev/null
