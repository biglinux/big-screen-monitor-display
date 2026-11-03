"""Managed storage: imported wallpapers, user presets and shareable packages.

Wallpapers
    The configuration window decodes the user's image *as the user*
    (``normalize_image``: format sniffing, pixel limits, first frame, EXIF
    orientation, metadata stripped, re-encoded as PNG). The privileged helper
    only checks the PNG structure (``check_png``, no decoding as root) and
    stores it as ``<sha256>.png`` next to the settings, where the sandboxed
    service can read it. The original file is never modified or referenced.

Presets and packages
    User presets are plain JSON files in ``$XDG_DATA_HOME``; packages
    (``.kojiro.zip``) carry a configuration, metadata, a thumbnail and - only
    if the user asks - the wallpaper. Imports are validated entry by entry.
"""

import hashlib
import io
import json
import os
import re
import struct
import zipfile
import zlib

from .. import settings as settings_mod
from . import model

MAX_SOURCE_BYTES = 64 * 1024 * 1024        # file chosen by the user
MAX_SOURCE_PIXELS = 50_000_000
MAX_LONG_SIDE = 2560
MAX_WALLPAPER_BYTES = 8 * 1024 * 1024       # normalised PNG
MAX_WALLPAPERS = 64
MAX_PRESET_BYTES = 512 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PACKAGE_ENTRIES = {"config.json": MAX_PRESET_BYTES, "metadata.json": 16 * 1024, "thumbnail.png": 1024 * 1024,
                   "wallpaper.png": MAX_WALLPAPER_BYTES}
PACKAGE_FORMAT = "kojiro-package"


class StoreError(Exception):
    pass


# ---------------------------------------------------------------- wallpapers

def wallpapers_dir(config_path=None):
    return os.path.join(os.path.dirname(config_path or settings_mod.config_path()), "wallpapers")


def wallpaper_path(wallpaper_id, directory=None):
    if not model.WALLPAPER_ID.match(wallpaper_id or ""):
        return None
    path = os.path.join(directory or wallpapers_dir(), f"{wallpaper_id}.png")
    return path if os.path.isfile(path) and not os.path.islink(path) else None


def list_wallpapers(directory=None):
    """[(id, path, mtime)] newest first."""
    directory = directory or wallpapers_dir()
    found = []
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    for name in names:
        stem, ext = os.path.splitext(name)
        path = os.path.join(directory, name)
        if ext == ".png" and model.WALLPAPER_ID.match(stem) and os.path.isfile(path) and not os.path.islink(path):
            found.append((stem, path, os.path.getmtime(path)))
    return sorted(found, key=lambda item: -item[2])


def check_png(data):
    """Structural validation without decoding: signature, IHDR, chunk CRCs, IEND.

    Returns (width, height). Raises StoreError.
    """
    if len(data) > MAX_WALLPAPER_BYTES:
        raise StoreError("image too large")
    if not data.startswith(PNG_SIGNATURE):
        raise StoreError("not a PNG file")
    offset = len(PNG_SIGNATURE)
    width = height = None
    seen_end = False
    while offset + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[offset:offset + 8])
        if length > len(data):
            raise StoreError("broken PNG chunk")
        chunk = data[offset + 8:offset + 8 + length]
        crc = data[offset + 8 + length:offset + 12 + length]
        if len(chunk) != length or len(crc) != 4 or zlib.crc32(kind + chunk) & 0xFFFFFFFF != struct.unpack(">I", crc)[0]:
            raise StoreError("PNG checksum mismatch")
        if width is None:
            if kind != b"IHDR" or length != 13:
                raise StoreError("PNG without IHDR")
            width, height = struct.unpack(">II", chunk[:8])
        if kind == b"IEND":
            seen_end = True
            break
        offset += 12 + length
    if not seen_end or width is None:
        raise StoreError("truncated PNG")
    if not (16 <= width <= 4096 and 16 <= height <= 4096):
        raise StoreError(f"unsupported image size {width}x{height}")
    return width, height


def wallpaper_id(data):
    return hashlib.sha256(data).hexdigest()[:32]


def save_wallpaper(data, directory=None):
    """Store a checked PNG; returns its id. Same content -> same id (no duplicates)."""
    check_png(data)
    directory = directory or wallpapers_dir()
    os.makedirs(directory, mode=0o755, exist_ok=True)
    if os.path.islink(directory):
        raise StoreError("wallpaper directory is a symbolic link")
    image_id = wallpaper_id(data)
    target = os.path.join(directory, f"{image_id}.png")
    if os.path.exists(target):
        return image_id
    if len(list_wallpapers(directory)) >= MAX_WALLPAPERS:
        raise StoreError(f"too many wallpapers (limit {MAX_WALLPAPERS}); remove some first")
    tmp = os.path.join(directory, f".{image_id}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return image_id


def delete_wallpaper(image_id, directory=None):
    path = wallpaper_path(image_id, directory)
    if path is None:
        raise StoreError("unknown wallpaper")
    os.unlink(path)


def normalize_image(path):
    """Decode a user image (as the user) and return clean PNG bytes."""
    from PIL import Image, ImageOps
    try:
        size = os.path.getsize(path)
    except OSError as error:
        raise StoreError(str(error))
    if size > MAX_SOURCE_BYTES:
        raise StoreError("file too large")
    with open(path, "rb") as handle:
        head = handle.read(512)
    if head.lstrip().startswith((b"<?xml", b"<svg")) or b"<svg" in head:
        return _rasterize_svg(path)
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    try:
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF"):
                raise StoreError(f"unsupported format {image.format}")
            image.verify()
        with Image.open(path) as image:
            image.seek(0)                       # animated GIF/WebP: first frame
            image = ImageOps.exif_transpose(image)
            image.load()
    except StoreError:
        raise
    except Exception as error:  # noqa: BLE001 - every decoder error is just "invalid image"
        raise StoreError(f"invalid image: {error}")
    return _encode(image)


def _rasterize_svg(path):
    import subprocess
    try:
        result = subprocess.run(["rsvg-convert", "-w", "1920", "--keep-aspect-ratio", path], capture_output=True,
                                timeout=20, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise StoreError(f"cannot convert SVG: {error}")
    if result.returncode != 0 or not result.stdout:
        raise StoreError("cannot convert SVG")
    from PIL import Image
    image = Image.open(io.BytesIO(result.stdout))
    image.load()
    return _encode(image)


def _encode(image):
    from PIL import Image
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (0, 0, 0))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")
    long_side = MAX_LONG_SIDE
    while True:
        copy = image.copy()
        copy.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
        if min(copy.size) < 16:
            raise StoreError("image too small")
        buffer = io.BytesIO()
        copy.save(buffer, format="PNG", optimize=False, compress_level=7)
        data = buffer.getvalue()
        if len(data) <= MAX_WALLPAPER_BYTES or long_side <= 640:
            check_png(data)
            return data
        long_side = int(long_side * 0.75)


# ---------------------------------------------------------------- presets

def presets_dir():
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "big-screen-monitor-display", "kojiro", "presets")


def _slug(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]
    return slug or "preset"


def save_user_preset(name, config, directory=None):
    directory = directory or presets_dir()
    os.makedirs(directory, exist_ok=True)
    clean, _problems = model.validate(config)
    clean["preset"] = name[:40]
    path = os.path.join(directory, f"{_slug(name)}.json")
    settings_mod.atomic_write_json(path, {"format": "kojiro-preset", "name": name[:40], "config": clean}, 0o600)
    return path


def list_user_presets(directory=None):
    directory = directory or presets_dir()
    result = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    for name in names:
        if name.endswith(".json"):
            try:
                result.append((load_preset_file(os.path.join(directory, name))[0], os.path.join(directory, name)))
            except StoreError:
                continue
    return result


def delete_user_preset(path, directory=None):
    directory = os.path.realpath(directory or presets_dir())
    if os.path.dirname(os.path.realpath(path)) != directory:
        raise StoreError("not a user preset")
    os.unlink(path)


def load_preset_file(path):
    """(name, clean config, problems) from a .json preset/export."""
    try:
        if os.path.getsize(path) > MAX_PRESET_BYTES:
            raise StoreError("file too large")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as error:
        raise StoreError(f"cannot read {os.path.basename(path)}: {error}")
    return parse_preset(data)


def parse_preset(data):
    if not isinstance(data, dict):
        raise StoreError("not a Kojiro file")
    config = data.get("config", data.get("kojiro") if "kojiro" in data else None)
    if config is None and "layouts" in data:
        config = data
    if not isinstance(config, dict):
        raise StoreError("no Kojiro configuration in the file")
    clean, problems = model.validate(config)
    name = data.get("name") if isinstance(data.get("name"), str) else clean.get("preset", "custom")
    return name[:40], clean, problems


def export_json(config, path, name="Kojiro"):
    clean, _problems = model.validate(config)
    if model.uses_user_wallpaper(clean):
        # A plain JSON export references an image the receiver does not have.
        clean["wallpaper"]["source"] = "builtin:cyberpunk"
    settings_mod.atomic_write_json(path, {"format": "kojiro-preset", "version": model.VERSION, "name": name[:40],
                                          "config": clean})


def export_package(config, path, name="Kojiro", thumbnail_png=None, include_wallpaper=False, store_dir=None):
    """Zip with config, metadata, thumbnail and (optionally) the imported wallpaper."""
    clean, _problems = model.validate(config)
    wallpaper = model.uses_user_wallpaper(clean)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if wallpaper and include_wallpaper:
            source = wallpaper_path(wallpaper, store_dir)
            if source:
                with open(source, "rb") as handle:
                    archive.writestr("wallpaper.png", handle.read())
                clean["wallpaper"]["source"] = "package:wallpaper"
        elif wallpaper:
            clean["wallpaper"]["source"] = "builtin:cyberpunk"
        archive.writestr("config.json", json.dumps(clean, indent=2, ensure_ascii=False))
        archive.writestr("metadata.json", json.dumps({"format": PACKAGE_FORMAT, "version": model.VERSION,
                                                      "name": name[:40], "widgets": len(clean["layouts"]["landscape"])},
                                                     ensure_ascii=False))
        if thumbnail_png:
            archive.writestr("thumbnail.png", thumbnail_png)


def read_package(path):
    """Validated contents: {"name", "config", "problems", "wallpaper": bytes|None, "thumbnail": bytes|None}."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise StoreError(f"not a Kojiro package: {error}")
    with archive:
        entries = {}
        total = 0
        for info in archive.infolist():
            if info.filename not in PACKAGE_ENTRIES or info.is_dir():
                raise StoreError(f"unexpected entry {info.filename!r}")
            if info.file_size > PACKAGE_ENTRIES[info.filename]:
                raise StoreError(f"{info.filename} too large")
            if info.compress_size and info.file_size / info.compress_size > 200:
                raise StoreError(f"{info.filename}: suspicious compression ratio")
            total += info.file_size
            if total > 12 * 1024 * 1024:
                raise StoreError("package too large")
            entries[info.filename] = archive.read(info)
    try:
        metadata = json.loads(entries.get("metadata.json", b"{}").decode("utf-8"))
        config = json.loads(entries["config.json"].decode("utf-8"))
    except (KeyError, UnicodeDecodeError, ValueError) as error:
        raise StoreError(f"invalid package: {error}")
    if not isinstance(metadata, dict) or metadata.get("format", PACKAGE_FORMAT) != PACKAGE_FORMAT:
        raise StoreError("not a Kojiro package")
    wallpaper = entries.get("wallpaper.png")
    if wallpaper is not None:
        check_png(wallpaper)
    if isinstance(config, dict) and isinstance(config.get("wallpaper"), dict) and \
            config["wallpaper"].get("source") == "package:wallpaper":
        config["wallpaper"]["source"] = "builtin:cyberpunk"      # replaced after the import
    clean, problems = model.validate(config)
    name = metadata.get("name") if isinstance(metadata.get("name"), str) else "Kojiro"
    return {"name": name[:40], "config": clean, "problems": problems, "wallpaper": wallpaper,
            "thumbnail": entries.get("thumbnail.png")}
