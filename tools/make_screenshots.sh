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
