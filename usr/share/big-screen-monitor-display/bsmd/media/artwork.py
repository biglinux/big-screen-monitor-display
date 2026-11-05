"""Album art and video thumbnails from ``mpris:artUrl`` (session agent only).

Sources
    file://  local files the user can read (players write covers to caches);
             regular files only, size limited.
    data:    inline base64 images (some browsers).
    http(s): fetched with a timeout, a byte limit and at most 3 redirects;
             every hop must be http(s) and must not resolve to a loopback,
             private, link-local or multicast address (a player cannot make the
             agent probe the local network).
Processing
    Decoded with Pillow under a pixel limit, only common still-image formats,
    reduced to ``MAX_SIDE`` and converted to raw RGB. The service receives
    those pixels, never a file, so it never runs an image decoder on data
    coming from the session.
Cache
    Processed PNGs in ``$XDG_CACHE_HOME/big-screen-monitor-display/art``
    (bounded by count and size) plus a small in-memory LRU.

Loading runs in worker threads; results return through ``GLib.idle_add``.
"""

import base64
import collections
import hashlib
import io
import ipaddress
import logging
import os
import socket
import threading
import stat
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

from . import model

log = logging.getLogger("bsmd.media")

MAX_SIDE = 240
MAX_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 40_000_000
TIMEOUT = 6.0
MAX_REDIRECTS = 3
FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}
DISK_FILES = 300
DISK_BYTES = 40 * 1024 * 1024
MEMORY = 24
USER_AGENT = "BigScreenMonitorDisplay-art/1.0"


class ArtError(Exception):
    pass


def art_id(url):
    return hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:20]


def cache_dir():
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "big-screen-monitor-display", "art")


# ---------------------------------------------------------------- fetching

def _public_host(host):
    """True when every address of ``host`` is a public unicast address."""
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    if not infos:
        return False
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return False
        if (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_reserved or address.is_unspecified):
            return False
    return True


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check_remote_url(url, resolve=_public_host):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ArtError("only http(s) URLs are fetched")
    if parsed.username or parsed.password:
        raise ArtError("credentials in URL")
    if not resolve(parsed.hostname):
        raise ArtError("address not allowed")
    return parsed


def fetch_remote(url, resolve=_public_host, opener=None):
    opener = opener or urllib.request.build_opener(_NoRedirect)
    for _hop in range(MAX_REDIRECTS + 1):
        check_remote_url(url, resolve)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        try:
            response = opener.open(request, timeout=TIMEOUT)
        except urllib.error.HTTPError as error:
            if error.code in (301, 302, 303, 307, 308) and error.headers.get("Location"):
                url = urllib.parse.urljoin(url, error.headers["Location"])
                continue
            raise ArtError(f"HTTP {error.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ArtError(f"download failed: {error}") from None
        with response:
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > MAX_BYTES:
                raise ArtError("image too large")
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ArtError("image too large")
        return data
    raise ArtError("too many redirects")


def read_local(url):
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
    if not os.path.isabs(path):
        raise ArtError("relative path")
    try:
        info = os.stat(path)
    except OSError as error:
        raise ArtError(f"cannot read {path}: {error.strerror}") from None
    if not stat.S_ISREG(info.st_mode):
        raise ArtError("not a regular file")
    if info.st_size > MAX_BYTES:
        raise ArtError("image too large")
    with open(path, "rb") as handle:
        return handle.read(MAX_BYTES + 1)


def read_data_url(url):
    header, _, payload = url.partition(",")
    if ";base64" not in header or not header.startswith("data:image/"):
        raise ArtError("unsupported data URL")
    if len(payload) > MAX_BYTES * 4 // 3 + 4:
        raise ArtError("image too large")
    try:
        return base64.b64decode(payload, validate=False)
    except ValueError:
        raise ArtError("bad base64") from None


def fetch(url, resolve=_public_host):
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme == "file":
        return read_local(url)
    if scheme == "data":
        return read_data_url(url)
    if scheme in ("http", "https"):
        return fetch_remote(url, resolve)
    raise ArtError(f"unsupported scheme {scheme!r}")


def normalize(data, max_side=MAX_SIDE):
    """Validated, reduced RGB image from encoded bytes."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in FORMATS:
                raise ArtError(f"format {image.format} not accepted")
            if image.width * image.height > MAX_PIXELS:
                raise ArtError("image too large")
            image.draft("RGB", (max_side * 2, max_side * 2))
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, (0, 0, 0, 255))
            image = Image.alpha_composite(background, image).convert("RGB")
            image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            return image
    except ArtError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, SyntaxError) as error:
        raise ArtError(f"invalid image: {error}") from None


def to_message(identifier, image):
    image = image.convert("RGB")
    if max(image.size) > model.MAX_ART_SIDE:
        image.thumbnail((model.MAX_ART_SIDE, model.MAX_ART_SIDE))
    return {"type": "art", "id": identifier, "w": image.width, "h": image.height,
            "rgb": base64.b64encode(image.tobytes()).decode("ascii")}


# ---------------------------------------------------------------- cache + loader

class ArtCache:
    def __init__(self, directory=None):
        self.directory = directory or cache_dir()
        self.memory = collections.OrderedDict()
        self.lock = threading.Lock()

    def get(self, identifier):
        with self.lock:
            image = self.memory.get(identifier)
            if image is not None:
                self.memory.move_to_end(identifier)
                return image
        path = os.path.join(self.directory, f"{identifier}.png")
        try:
            with Image.open(path) as cached:
                image = cached.convert("RGB")
            os.utime(path)
        except (OSError, ValueError):
            return None
        self._remember(identifier, image)
        return image

    def put(self, identifier, image):
        self._remember(identifier, image)
        try:
            os.makedirs(self.directory, mode=0o700, exist_ok=True)
            tmp = os.path.join(self.directory, f".{identifier}.tmp")
            image.save(tmp, "PNG", optimize=False)
            os.replace(tmp, os.path.join(self.directory, f"{identifier}.png"))
            self.prune()
        except OSError as error:
            log.debug("art cache write failed: %s", error)

    def _remember(self, identifier, image):
        with self.lock:
            self.memory[identifier] = image
            self.memory.move_to_end(identifier)
            while len(self.memory) > MEMORY:
                self.memory.popitem(last=False)

    def prune(self):
        try:
            entries = [(entry.stat().st_mtime, entry.stat().st_size, entry.path)
                       for entry in os.scandir(self.directory) if entry.name.endswith(".png")]
        except OSError:
            return
        entries.sort()
        total = sum(size for _m, size, _p in entries)
        while entries and (len(entries) > DISK_FILES or total > DISK_BYTES):
            _mtime, size, path = entries.pop(0)
            total -= size
            try:
                os.unlink(path)
            except OSError:
                pass

    def usage(self):
        try:
            entries = [entry.stat().st_size for entry in os.scandir(self.directory) if entry.name.endswith(".png")]
        except OSError:
            return 0, 0
        return len(entries), sum(entries)

    def clear(self):
        with self.lock:
            self.memory.clear()
        try:
            for entry in os.scandir(self.directory):
                if entry.name.endswith(".png"):
                    os.unlink(entry.path)
        except OSError:
            pass


class ArtLoader:
    """Loads URLs in background threads (at most ``WORKERS`` at once, newest first).

    ``on_done(identifier, image_or_None, error)`` is called on the GLib main loop.
    """

    WORKERS = 2

    def __init__(self, on_done, cache=None, schedule=None):
        self.on_done = on_done
        self.cache = cache or ArtCache()
        self.schedule = schedule
        self.pending = collections.OrderedDict()
        self.running = set()
        self.failed = {}
        self.lock = threading.Lock()

    def _post(self, *args):
        if self.schedule:
            self.schedule(self.on_done, *args)
        else:
            from gi.repository import GLib
            GLib.idle_add(lambda: self.on_done(*args) and False)

    def request(self, url):
        """Identifier for ``url``; the image arrives through ``on_done`` (maybe at once)."""
        identifier = art_id(url)
        image = self.cache.get(identifier)
        if image is not None:
            self._post(identifier, image, "")
            return identifier
        with self.lock:
            if identifier in self.running or identifier in self.pending:
                return identifier
            if identifier in self.failed:
                return identifier
            self.pending[identifier] = url
            self.pending.move_to_end(identifier, last=False)
            self._start_workers()
        return identifier

    def _start_workers(self):
        while self.pending and len(self.running) < self.WORKERS:
            identifier, url = self.pending.popitem(last=False)
            self.running.add(identifier)
            threading.Thread(target=self._work, args=(identifier, url), name="art", daemon=True).start()

    def _work(self, identifier, url):
        image, error = None, ""
        try:
            image = normalize(fetch(url))
            self.cache.put(identifier, image)
        except ArtError as problem:
            error = str(problem)
        except Exception as problem:  # noqa: BLE001 - a broken image must not kill the agent
            error = repr(problem)
        with self.lock:
            self.running.discard(identifier)
            if error:
                self.failed[identifier] = error
                if len(self.failed) > 200:
                    self.failed.clear()
            self._start_workers()
        if error:
            log.info("album art unavailable (%s): %s", url[:120], error)
        self._post(identifier, image, error)

    def retry_failed(self):
        with self.lock:
            self.failed.clear()
