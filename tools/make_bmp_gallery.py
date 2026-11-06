#!/usr/bin/env python3
"""Comparison sheet of the Big Media Player skins, rendered by the real theme (docs aid).

    tools/make_bmp_gallery.py OUT.png [modern|classic|all] [WIDTHxHEIGHT]

Uses the default settings (not the machine's) and the labelled demonstration data of the preview.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "usr", "share",
                                "big-screen-monitor-display"))
os.environ.setdefault("BSM_CONFIG", "/nonexistent/big-screen-monitor-display/settings.json")

from PIL import Image  # noqa: E402

from bsmd import runtime, settings, telemetry, themes  # noqa: E402
from bsmd.bigmedia import paint as P, skins  # noqa: E402


def main(argv):
    out = argv[1]
    which = argv[2] if len(argv) > 2 else "modern"
    w, h = (int(v) for v in (argv[3] if len(argv) > 3 else "480x320").split("x"))
    ids = {"modern": skins.MODERN_IDS, "classic": skins.CLASSIC_IDS}.get(which, skins.SKIN_IDS)
    collector = telemetry.Collector()
    collector.prime()
    collector.sample_once()
    cols = 4 if len(ids) > 8 else 2 if w > 600 else 4
    rows = (len(ids) + cols - 1) // cols
    gap, label = 18, 30
    sheet = Image.new("RGB", (cols * (w + gap) + gap, rows * (h + gap + label) + gap), (32, 34, 40))
    for index, skin_id in enumerate(ids):
        ctx = runtime.RenderContext(preview=True)
        theme = themes.create("big_media_player", ctx)
        values = dict(settings.defaults(), theme="big_media_player", bmp_skin=skin_id, bmp_show_output=True)
        image = themes.render_for_panel(theme, w, h, values, ctx)
        x = gap + (index % cols) * (w + gap)
        y = gap + (index // cols) * (h + gap + label)
        sheet.paste(image, (x, y))
        P.put_text(sheet, (x, y + h + label / 2 + 2), skins.SKINS[skin_id].name, 16, (230, 232, 238), bold=True)
    sheet.save(out, optimize=True)
    print(out)


if __name__ == "__main__":
    main(sys.argv)
