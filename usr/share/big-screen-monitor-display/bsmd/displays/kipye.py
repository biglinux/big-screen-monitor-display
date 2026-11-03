"""Kipye Qiye Smart Display 3.5" (revision D).

Protocol as implemented by turing-smart-screen-python (Copyright (C) 2021
Matthieu Houdebine, GPL-3.0-or-later): ASCII-like commands, RGB565
big-endian bitmaps sent in 63-byte packets prefixed with 0x50. The panel only
has portrait orientations; landscape is done in software.
"""

from .. import frames
from .base import Capabilities, percent
from .turing_serial import LANDSCAPE, PORTRAIT, REVERSE_LANDSCAPE, REVERSE_PORTRAIT, SerialDisplay

SETORG = bytes((67, 72, 0, 0))      # portrait
SET180 = bytes((67, 71, 0, 0))      # reverse portrait
SETBL = bytes((67, 67))             # brightness
DISPCOLOR = bytes((67, 66))         # fill with an RGB565 colour
BLOCKWRITE = bytes((67, 65))        # bitmap rectangle
INTOPICMODE = bytes((68, 0, 0, 0))
OUTPICMODE = bytes((65, 0, 0, 0))


class KipyeRevD(SerialDisplay):
    DRIVER = "kipye_rev_d"
    TILE = (40, 20)
    MAX_RECTS = 12

    def __init__(self, port=None, transport=None, options=None):
        super().__init__(port, transport, options)
        self.capabilities = Capabilities(encoding="rgb565be", transport="serial",
                                         notes=("landscape rotated in software",))

    def write(self, data):
        self.transport.write(data)
        self.transport.reset_input()      # the panel echoes data nobody reads

    def set_orientation(self, orientation):
        self.orientation = orientation
        self.write(SET180 if orientation in (REVERSE_LANDSCAPE, REVERSE_PORTRAIT) else SETORG)

    def set_brightness(self, level):
        value = (percent(level) * 5).to_bytes(2, "big")
        self.write(SETBL + value)
        self.write(SETBL + value)

    def clear(self):
        self.write(DISPCOLOR + (0x0000).to_bytes(2, "big"))

    def display_image(self, image, x=0, y=0):
        width, height = self.get_width(), self.get_height()
        image_width = min(image.width, width - x)
        image_height = min(image.height, height - y)
        if (image_width, image_height) != image.size:
            image = image.crop((0, 0, image_width, image_height))
        if self.orientation in (PORTRAIT, REVERSE_PORTRAIT):
            x0, y0, x1, y1 = x, y, x + image_width - 1, y + image_height - 1
        else:
            image = image.rotate(270, expand=True)
            x0, y0 = self.display_width - y - image_height, x
            x1, y1 = self.display_width - y - 1, x + image_width - 1
        header = x0.to_bytes(2, "big") + x1.to_bytes(2, "big") + y0.to_bytes(2, "big") + y1.to_bytes(2, "big")
        self.write(BLOCKWRITE + header)
        self.write(INTOPICMODE)
        payload = frames.image_to_rgb565(image, ">").tobytes()
        # Packets of 0x50 + 63 bytes, sent in large writes (same byte stream).
        packets = b"".join(b"\x50" + chunk for chunk in frames.chunked(payload, 63))
        self.write(packets)
        self.write(OUTPICMODE)
        return len(payload)

    def open(self):
        self._connect()
        self.orientation = LANDSCAPE      # SETORG + software rotation
        self.write(SETORG)
        return self._ready("Kipye Qiye Smart Display 3.5\"")

    def _blit(self, image, rect):
        return self.display_image(image.crop(rect), rect[0], rect[1])
