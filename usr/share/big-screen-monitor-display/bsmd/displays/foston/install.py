"""Copy the bsmd-ce client to a FOSTON mounted as USB storage (045e:ffff).

Runs as the desktop user (the volume is mounted by udisks for that user);
never writes outside ``<volume>/BigScreen``. The navigator caches its file
system while it is exported over USB, so after copying the device must be
restarted (reset) before the new client is started from its menu.
"""

import glob
import hashlib
import os
import shutil

CLIENT_NAME = "bsmd-ce.exe"
TARGET_DIR = "BigScreen"
STORAGE_IDS = {("045e", "ffff")}          # Windows CE USB mass storage function
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PACKAGED_CLIENT = os.path.join(APP_DIR, "device-clients", "wince", CLIENT_NAME)


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _usb_ids(block, sysfs):
    """(vid, pid) of the USB device behind /sys/block/<block>, or None."""
    path = os.path.realpath(os.path.join(sysfs, "block", block, "device"))
    while path and path != "/":
        vid, pid = _read(os.path.join(path, "idVendor")), _read(os.path.join(path, "idProduct"))
        if vid and pid:
            return vid.lower(), pid.lower()
        path = os.path.dirname(path)
    return None


def _unescape(field):
    return field.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def find_volumes(sysfs="/sys", mounts="/proc/mounts"):
    """Mount points of FOSTON storage volumes currently mounted."""
    blocks = {}
    for entry in glob.glob(os.path.join(sysfs, "block", "sd*")):
        block = os.path.basename(entry)
        if _usb_ids(block, sysfs) in STORAGE_IDS:
            blocks[block] = True
    result = []
    for line in _read(mounts).splitlines():
        fields = line.split()
        if len(fields) < 2 or not fields[0].startswith("/dev/"):
            continue
        name = os.path.basename(fields[0])
        parent = name.rstrip("0123456789")
        if parent in blocks:
            result.append(_unescape(fields[1]))
    return result


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install(volume, client=PACKAGED_CLIENT):
    """Copy the client to ``volume``/BigScreen; returns the installed path (verified)."""
    if not os.path.isfile(client):
        raise FileNotFoundError(client)
    target_dir = os.path.join(volume, TARGET_DIR)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, CLIENT_NAME)
    temporary = target + ".new"
    shutil.copyfile(client, temporary)
    with open(temporary, "rb") as handle:
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    if sha256(target) != sha256(client):
        raise OSError(f"verification failed for {target}")
    return target
