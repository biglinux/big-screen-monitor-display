"""Helpers to compare driver byte streams with turing-smart-screen-python goldens.

``sample_image`` reproduces the image generator of the reference test-suite
(turing-smart-screen-python, Copyright (C) 2021 Matthieu Houdebine,
GPL-3.0-or-later) so the bitmaps match its golden files. Only SHA-256
hashes of those files are stored here (tests/data); the reference
repository is read, never modified.
"""

import hashlib
import os

from PIL import Image

REFERENCE_GOLDEN = os.environ.get("TSSP_GOLDEN") or os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "turing-smart-screen-python", "tests", "library", "lcd", "golden"))


class RecordingTransport:
    """In-memory transport: records writes/reads, replays scripted answers."""

    def __init__(self, responses=None):
        self.writes = []
        self.reads = []
        self.responses = list(responses or [])
        self.resets = 0

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def read(self, size):
        self.reads.append(size)
        return self.responses.pop(0) if self.responses else b""

    def reset_input(self):
        self.resets += 1

    def drain_input(self):
        return self.responses.pop(0) if self.responses else b""

    def alive(self):
        pass

    def close(self):
        pass

    @property
    def stream(self):
        return b"".join(self.writes)


def sample_image(width, height):
    """Same generator as the reference tests (red/green/blue/black corners)."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for x in range(width):
        for y in range(height):
            wx, wy = x / (width - 1), y / (height - 1)
            pixels[x, y] = (int((1 - wx) * (1 - wy) * 255), int(wx * (1 - wy) * 255), int(wy * (1 - wx) * 255))
    return image


def golden(name):
    """(sha256 of the written stream, list of read sizes) or None if unavailable."""
    path = os.path.join(REFERENCE_GOLDEN, name + ".txt")
    if not os.path.exists(path):
        return None
    digest = hashlib.sha256()
    reads = []
    with open(path, encoding="ascii") as handle:
        for line in handle:
            parts = line.split()
            if len(parts) != 2:
                continue
            if parts[0] == "write":
                digest.update(bytes.fromhex(parts[1]))
            elif parts[0] == "read":
                reads.append(int(parts[1]))
    return digest.hexdigest(), reads


def fingerprint(transport):
    return hashlib.sha256(transport.stream).hexdigest(), list(transport.reads)
