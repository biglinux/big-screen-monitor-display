#!/usr/bin/env python3
"""docs/images/tour.gif: the themes in one short loop for the top of the README.

Built from the screenshots that tools/make_screenshots.sh renders with the real
themes (nothing is drawn by hand). Run it again after regenerating them.
"""

import os
import sys

from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IMAGES = os.path.join(ROOT, "docs", "images")
FRAMES = ["theme-standard-nord.png", "ba-noon.png", "kojiro-cyberpunk.png", "bmp-modern-flow.png",
          "theme-gkrellm-480.png", "ba-sunset.png", "theme-planet.png", "kojiro-glass.png",
          "theme-old_computer.png", "ba-night.png", "theme-standard-neon.png", "bmp-bigamp.png"]
SIZE = (480, 320)
SECONDS = 1.6


def frame(name):
    with Image.open(os.path.join(IMAGES, name)) as image:
        image = image.convert("RGB")
        image.thumbnail(SIZE)
        canvas = Image.new("RGB", SIZE, (16, 20, 28))
        canvas.paste(image, ((SIZE[0] - image.width) // 2, (SIZE[1] - image.height) // 2))
        return canvas


def main():
    frames = [frame(name).quantize(colors=128, method=Image.Quantize.MEDIANCUT) for name in FRAMES]
    out = os.path.join(IMAGES, "tour.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=int(SECONDS * 1000), loop=0,
                   optimize=True)
    print(f"{out}: {len(frames)} frames, {os.path.getsize(out) // 1024} KiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
