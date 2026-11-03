import threading
import time

import numpy as np
from PIL import Image

from bsmd import frames


def reference_rgb565_be(image):
    """The 3.x pure Python AX206 conversion, kept as the reference."""
    data = image.convert("RGB").tobytes()
    out = bytearray(len(data) // 3 * 2)
    for i in range(len(data) // 3):
        r, g, b = data[i * 3], data[i * 3 + 1], data[i * 3 + 2]
        value = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        out[i * 2] = value >> 8
        out[i * 2 + 1] = value & 0xFF
    return bytes(out)


def random_image(w, h, seed=1):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (h, w, 3), dtype=np.uint8), "RGB")


def test_rgb565_big_endian_matches_reference():
    image = random_image(64, 40)
    assert frames.image_to_rgb565(image, ">").tobytes() == reference_rgb565_be(image)


def test_rgb565_little_endian_is_byteswapped():
    image = random_image(16, 8)
    be = frames.image_to_rgb565(image, ">").tobytes()
    le = frames.image_to_rgb565(image, "<").tobytes()
    assert le == b"".join(be[i + 1:i + 2] + be[i:i + 1] for i in range(0, len(be), 2))


def test_known_colours():
    image = Image.new("RGB", (3, 1))
    image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert frames.image_to_rgb565(image, "<").tolist() == [[0xF800, 0x07E0, 0x001F]]


def test_edge_pixels_are_detected_for_non_multiple_sizes():
    # 800x480 with 48x20 tiles: 800/48 is not an integer; 3.x ignored x >= 768.
    prev = np.zeros((480, 800), dtype=np.uint16)
    curr = prev.copy()
    curr[479, 799] = 1
    rects = frames.plan_rects(curr, prev, 48, 20, 48)
    assert rects == [(768, 460, 800, 480)]


def test_rects_merge_horizontally_and_vertically():
    prev = np.zeros((64, 64), dtype=np.uint16)
    curr = prev.copy()
    curr[0:32, 0:32] = 5          # 2x2 tiles of 16
    curr[48, 63] = 1
    rects = frames.plan_rects(curr, prev, 16, 16, 10)
    assert rects == [(0, 0, 32, 32), (48, 48, 64, 64)]


def test_plan_rects_full_and_unchanged():
    a = np.zeros((20, 20), dtype=np.uint16)
    assert frames.plan_rects(a, None, 8, 8, 4) is None
    assert frames.plan_rects(a, a.copy(), 8, 8, 4) == []
    b = a + 1
    assert frames.plan_rects(b, a, 8, 8, 4) is None   # everything changed


def test_too_many_rects_collapse_to_bounding_box():
    prev = np.zeros((64, 64), dtype=np.uint16)
    curr = prev.copy()
    curr[::16, ::16] = 1  # 16 isolated tiles
    rects = frames.plan_rects(curr, prev, 8, 8, 4)
    assert rects == [(0, 0, 56, 56)]


def test_mailbox_coalesces_and_applies_backpressure():
    box = frames.FrameMailbox()
    box.put("a")
    box.put("b")
    assert box.dropped == 1
    assert box.take(0.1) == "b"
    assert box.take(0.01) is None
    box.put("c")
    released = []
    threading.Thread(target=lambda: (time.sleep(0.05), released.append(box.take(1)))).start()
    assert box.wait_consumed(1.0)
    assert released == ["c"]


def test_to_native_rotates_portrait_frames():
    portrait = Image.new("RGB", (320, 480))
    assert frames.to_native(portrait, (480, 320), "vertical").size == (480, 320)
