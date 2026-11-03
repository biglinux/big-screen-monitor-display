"""Frame helpers: RGB565 conversion, dirty rectangles and a latest-wins mailbox."""

import threading

import numpy as np
from PIL import Image


def image_to_rgb565(image, byteorder="<"):
    """Return a (h, w) uint16 array with RGB565 pixels in ``byteorder``.

    Vectorised with numpy (the previous AX206 path used a Python loop that
    took ~110 ms per 800x480 frame).
    """
    if image.mode != "RGB":
        image = image.convert("RGB")
    rgb = np.asarray(image, dtype=np.uint8)
    r = rgb[..., 0].astype(np.uint16)
    g = rgb[..., 1].astype(np.uint16)
    b = rgb[..., 2].astype(np.uint16)
    pixels = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return pixels.astype(byteorder + "u2", copy=False)


def image_key(image):
    """(h, w) uint32 array of packed RGB888 pixels, used to detect changes."""
    if image.mode != "RGB":
        image = image.convert("RGB")
    rgb = np.asarray(image, dtype=np.uint8).astype(np.uint32)
    return (rgb[..., 0] << 16) | (rgb[..., 1] << 8) | rgb[..., 2]


def image_to_bgr(image):
    if image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGB")
    return np.ascontiguousarray(np.asarray(image)[..., (2, 1, 0)]).tobytes()


def image_to_bgra(image):
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    return np.ascontiguousarray(np.asarray(image)[..., (2, 1, 0, 3)]).tobytes()


def chunked(data, size):
    for offset in range(0, len(data), size):
        yield data[offset:offset + size]


def dirty_tiles(curr, prev, tile_w, tile_h):
    """Boolean (rows, cols) grid telling which tiles differ.

    The grid uses ceiling division, so right/bottom edge pixels of
    resolutions that are not multiples of the tile size are also compared.
    """
    height, width = curr.shape
    rows = -(-height // tile_h)
    cols = -(-width // tile_w)
    diff = curr != prev
    pad_h = rows * tile_h - height
    pad_w = cols * tile_w - width
    if pad_h or pad_w:
        diff = np.pad(diff, ((0, pad_h), (0, pad_w)))
    return diff.reshape(rows, tile_h, cols, tile_w).any(axis=(1, 3))


def tiles_to_rects(tiles, tile_w, tile_h, width, height):
    """Merge dirty tiles into rectangles ``(x0, y0, x1, y1)`` (exclusive ends).

    Runs of dirty tiles in a row are merged horizontally, then identical runs
    on consecutive rows are merged vertically. Rectangles are clipped to the
    frame size.
    """
    rows, cols = tiles.shape
    open_runs = {}   # (c0, c1) -> [x0, y0, x1, y1]
    finished = []
    for ty in range(rows):
        row = tiles[ty]
        runs = []
        tx = 0
        while tx < cols:
            if not row[tx]:
                tx += 1
                continue
            start = tx
            while tx < cols and row[tx]:
                tx += 1
            runs.append((start, tx))
        next_open = {}
        for run in runs:
            rect = open_runs.pop(run, None)
            if rect is None:
                rect = [run[0] * tile_w, ty * tile_h, min(width, run[1] * tile_w), 0]
            rect[3] = min(height, (ty + 1) * tile_h)
            next_open[run] = rect
        finished.extend(open_runs.values())
        open_runs = next_open
    finished.extend(open_runs.values())
    return [tuple(rect) for rect in sorted(finished, key=lambda r: (r[1], r[0]))]


def bounding_rect(rects):
    return (min(r[0] for r in rects), min(r[1] for r in rects),
            max(r[2] for r in rects), max(r[3] for r in rects))


def rect_area(rect):
    return (rect[2] - rect[0]) * (rect[3] - rect[1])


def tighten(rect, diff):
    """``rect`` shrunk to the bounding box of the pixels that changed in it."""
    x0, y0, x1, y1 = rect
    region = diff[y0:y1, x0:x1]
    rows = np.flatnonzero(region.any(axis=1))
    cols = np.flatnonzero(region.any(axis=0))
    if not rows.size:
        return None
    return (x0 + int(cols[0]), y0 + int(rows[0]), x0 + int(cols[-1]) + 1, y0 + int(rows[-1]) + 1)


def plan_rects(curr, prev, tile_w, tile_h, max_rects, tight=False):
    """Rectangles to send for ``curr`` given the previously sent ``prev``.

    Returns ``None`` for a full frame, ``[]`` when nothing changed.
    When too many small rectangles would be produced (command overhead), they
    collapse into their bounding box. ``tight`` trims every rectangle to the
    pixels that really changed (a clock digit instead of whole tiles), for
    panels on slow links that accept any rectangle.
    """
    if prev is None or prev.shape != curr.shape:
        return None
    height, width = curr.shape
    tiles = dirty_tiles(curr, prev, tile_w, tile_h)
    if not tiles.any():
        return []
    rects = tiles_to_rects(tiles, tile_w, tile_h, width, height)
    if len(rects) > max_rects:
        rects = [bounding_rect(rects)]
    if tight:
        diff = curr != prev
        rects = [r for r in (tighten(rect, diff) for rect in rects) if r]
    if len(rects) == 1 and rect_area(rects[0]) == width * height:
        return None
    return rects


class FrameMailbox:
    """Single-slot, latest-wins frame hand-off between render and transport.

    Coalescing: a frame that was not consumed yet is replaced by the newer
    one (counted in ``dropped``), so a slow transport never builds a queue.
    """

    def __init__(self):
        self._cond = threading.Condition()
        self._frame = None
        self.dropped = 0
        self.posted = 0

    def put(self, frame):
        with self._cond:
            if self._frame is not None:
                self.dropped += 1
            self._frame = frame
            self.posted += 1
            self._cond.notify_all()

    def take(self, timeout):
        with self._cond:
            if not self._cond.wait_for(lambda: self._frame is not None, timeout):
                return None
            frame, self._frame = self._frame, None
            self._cond.notify_all()
            return frame

    def wait_consumed(self, timeout):
        """Backpressure: block the producer until the slot is free."""
        with self._cond:
            return self._cond.wait_for(lambda: self._frame is None, timeout)

    def clear(self):
        with self._cond:
            self._frame = None
            self._cond.notify_all()


ROTATIONS = {"vertical": Image.Transpose.ROTATE_90, "vertical_flipped": Image.Transpose.ROTATE_270,
             "horizontal_flipped": Image.Transpose.ROTATE_180}


def is_portrait(orientation):
    return str(orientation).startswith("vertical")


def render_size(native_size, orientation):
    """Size themes draw at for a landscape panel mounted in ``orientation``."""
    width, height = native_size
    return (height, width) if is_portrait(orientation) else (width, height)


def to_native(image, native_size, orientation):
    """Rotate a frame rendered for ``orientation`` to the panel's native landscape size."""
    rotation = ROTATIONS.get(orientation)
    if rotation is not None and image.size == render_size(native_size, orientation):
        image = image.transpose(rotation)
    if image.size != native_size:
        image = image.resize(native_size, Image.Resampling.NEAREST)
    return image
