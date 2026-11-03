"""Protocol drivers checked against the reference implementation.

Rev. A, B and D byte streams must be identical to turing-smart-screen-python
golden files; for rev. C the image payloads must be identical (the command
headers changed in the reference after its golden files were recorded).
Hashes are stored in tests/data so the check also runs without the
reference repository.
"""

import hashlib
import json
import os
import struct

import pytest

from protocol_support import RecordingTransport, sample_image

from bsmd.displays import base, discovery, registry, turing_usb
from bsmd.displays.base import DisplayError
from bsmd.displays.kipye import KipyeRevD
from bsmd.displays.turing_serial import (LANDSCAPE, PORTRAIT, REVERSE_LANDSCAPE, REVERSE_PORTRAIT, TuringRevA,
                                         TuringRevC)
from bsmd.displays.weact import WeActA, WeActB
from bsmd.displays.xuanfang import XuanFangRevB

HASHES = json.load(open(os.path.join(os.path.dirname(__file__), "data", "reference_protocol_hashes.json")))["hashes"]
ORIENTATIONS = {"portrait": PORTRAIT, "landscape": LANDSCAPE, "reverse_portrait": REVERSE_PORTRAIT,
                "reverse_landscape": REVERSE_LANDSCAPE}


@pytest.fixture(autouse=True)
def no_cooldown(monkeypatch):
    monkeypatch.setattr(XuanFangRevB, "COOLDOWN", 0)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def images(size):
    return {"portrait": sample_image(*size), "landscape": sample_image(size[1], size[0])}


IMAGES = images((320, 480))


@pytest.mark.parametrize("prefix,cls", [("rev_a", TuringRevA), ("rev_b", XuanFangRevB), ("rev_d", KipyeRevD)])
def test_brightness_matches_reference(prefix, cls):
    transport = RecordingTransport()
    cls(transport=transport).set_brightness(25)
    assert sha(transport.stream) == HASHES[f"{prefix}_set_brightness"]


@pytest.mark.parametrize("prefix,cls", [("rev_a", TuringRevA), ("rev_b", XuanFangRevB), ("rev_d", KipyeRevD)])
@pytest.mark.parametrize("orientation", list(ORIENTATIONS))
@pytest.mark.parametrize("patch", [False, True])
def test_bitmaps_match_reference(prefix, cls, orientation, patch):
    transport = RecordingTransport()
    driver = cls(transport=transport)
    driver.set_orientation(ORIENTATIONS[orientation])
    image = IMAGES["portrait" if "portrait" in orientation else "landscape"]
    if patch:
        driver.display_image(image.crop((0, 0, 100, 200)), 10, 20)
    else:
        driver.display_image(image)
    key = f"{prefix}_display_pil_image_{'patch_' if patch else ''}{orientation}"
    assert sha(transport.stream) == HASHES[key]


REV_C_IMAGES = images((480, 800))


def test_rev_c_brightness_matches_reference():
    transport = RecordingTransport()
    TuringRevC(transport=transport).set_brightness(25)
    assert sha(transport.stream) == HASHES["rev_c_set_brightness"]


@pytest.mark.parametrize("orientation", list(ORIENTATIONS))
def test_rev_c_image_payloads_match_reference(orientation):
    image = REV_C_IMAGES["portrait" if "portrait" in orientation else "landscape"]
    transport = RecordingTransport()
    driver = TuringRevC(transport=transport)
    driver.set_orientation(ORIENTATIONS[orientation])
    driver.display_image(image)
    assert sha(transport.writes[4]) == HASHES[f"rev_c_full_image_payload_{orientation}"]
    assert transport.reads == [1024, 1024]
    transport = RecordingTransport()
    driver = TuringRevC(transport=transport)
    driver.rom_version = 87
    driver.set_orientation(ORIENTATIONS[orientation])
    driver.display_image(image.crop((0, 0, 100, 200)), 10, 20)
    assert sha(transport.writes[2]) == HASHES[f"rev_c_patch_pixels_{orientation}"]


def test_rev_c_messages_are_padded_to_250_bytes():
    transport = RecordingTransport()
    driver = TuringRevC(transport=transport)
    driver.set_orientation(LANDSCAPE)
    driver.display_image(REV_C_IMAGES["landscape"])
    assert all(len(write) % 250 == 0 for write in transport.writes)


# ------------------------------------------------------------- handshakes

@pytest.mark.parametrize("answer,model,size", [
    (b"", "Turing Smart Screen 3.5\"", (480, 320)),
    (bytes([1] * 6), "UsbPCMonitor 3.5\"", (480, 320)),
    (bytes([2] * 6), "UsbPCMonitor 5\"", (800, 480)),
    (bytes([3] * 6), "UsbPCMonitor 7\"", (1024, 600))])
def test_rev_a_hello_sub_revisions(answer, model, size):
    transport = RecordingTransport([answer])
    info = TuringRevA(transport=transport).open()
    assert (info.model, (info.width, info.height)) == (model, size)
    assert transport.writes[0] == bytes([69] * 6)
    # landscape orientation command with the landscape size
    assert transport.writes[1][5:7] == bytes([121, 102])


def rev_b_hello(sub):
    return bytes([0xCA]) + b"HELLO" + bytes([0x0A, sub, 0, 0xCA])


@pytest.mark.parametrize("sub,leds,steps", [(0x01, False, 2), (0x02, True, 2), (0x11, False, 256), (0x12, True, 256)])
def test_rev_b_sub_revisions_drive_capabilities(sub, leds, steps):
    transport = RecordingTransport([rev_b_hello(sub)])
    driver = XuanFangRevB(transport=transport)
    driver.open()
    assert driver.capabilities.leds is leds and driver.capabilities.brightness_steps == steps
    assert driver.set_leds((255, 0, 0)) is leds
    driver.set_brightness(50)
    assert transport.writes[-1] == XuanFangRevB.frame(0xCE, [127 if steps == 256 else 0])


def test_rev_b_rejects_a_device_that_does_not_answer_hello():
    with pytest.raises(DisplayError) as error:
        XuanFangRevB(transport=RecordingTransport([b""])).open()
    assert error.value.kind == base.PROTOCOL


def test_rev_c_hello_parses_rom_and_size(monkeypatch):
    transport = RecordingTransport([b"chs_88inch.dev1_rom1.90\x00"])
    driver = TuringRevC(transport=transport, options={"size": "auto"})
    driver.open()
    assert driver.rom_version == 90 and driver.size_name == "8.8" and driver.native_size == (1920, 480)


def test_rev_c_gives_up_after_bad_answers(monkeypatch):
    monkeypatch.setattr("bsmd.displays.turing_serial.time.sleep", lambda s: None)
    with pytest.raises(DisplayError) as error:
        TuringRevC(transport=RecordingTransport([b"garbage"] * 10)).open()
    assert error.value.kind == base.PROTOCOL


def test_kipye_packets_are_prefixed_and_short():
    transport = RecordingTransport()
    driver = KipyeRevD(transport=transport)
    driver.open()
    driver.display_image(sample_image(64, 32), 0, 0)
    packets = transport.writes[-2]
    assert all(packets[i] == 0x50 for i in range(0, len(packets), 64))
    assert transport.resets >= 3     # input flushed after every write


# ------------------------------------------------------------- WeAct

def test_weact_a_open_sequence_and_sensors():
    version = bytes([0xC2]) + b"V1.0.0.0" + bytes(10)
    transport = RecordingTransport([b"", version])
    driver = WeActA(transport=transport)
    info = driver.open()
    assert info.details["firmware"] == "V1.0.0.0" and driver.native_size == (480, 320)
    assert transport.writes[0] == bytes((0xC2, 0x0A))
    assert transport.writes[1] == bytes((0x02, LANDSCAPE, 0x0A))
    assert transport.writes[2] == bytes((0x06, 0xE8, 0x03, 0x0A))     # report every 1000 ms
    # 55.10 % humidity is 0x1586: the frame contains a second 0x86 byte
    transport.responses = [b"\x01" + bytes((0x86,)) + struct.pack("<Hh", 2345, 5510) + bytes((0x0A,))]
    driver.probe()
    assert (driver.room_temperature, driver.humidity) == (23.45, 55.1)


def test_weact_bitmap_packets():
    transport = RecordingTransport([b"", b""])
    driver = WeActB(transport=transport)
    driver.open()
    assert driver.native_size == (160, 80) and not driver.capabilities.sensors
    driver.display_image(sample_image(16, 8), 4, 2)
    header = transport.writes[-2]
    assert header == bytes((0x05, 4, 0, 2, 0, 19, 0, 9, 0, 0x0A))
    assert len(transport.writes[-1]) == 16 * 8 * 2
    driver.set_brightness(100)
    assert transport.writes[-1] == bytes((0x03, 255, 0xE8, 0x03, 0x0A))


def test_partial_updates_send_only_changes():
    transport = RecordingTransport([b""])
    driver = TuringRevA(transport=transport)
    driver.open()
    frame = sample_image(480, 320)
    first = driver.present(frame)
    assert first.full
    assert driver.present(frame).bytes == 0
    frame.putpixel((479, 319), (1, 2, 255))
    second = driver.present(frame)
    assert not second.full and second.bytes == 2          # one pixel: rectangles are trimmed


# ------------------------------------------------------------- Turing USB

class FakeEndpoint:
    def __init__(self, address, store):
        self.bEndpointAddress = address
        self.store = store

    def write(self, data, timeout):
        self.store.setdefault("writes", []).append(bytes(data))
        if self.store.get("fail"):
            raise self.store.pop("fail")
        return len(data)

    def read(self, size, timeout):
        if timeout >= 1000 and self.store.get("answers"):   # short reads only flush the endpoint
            return self.store["answers"].pop(0)
        raise TimeoutError("timed out")


class FakeUsbDevice:
    idVendor, bus, address = 0x1CBE, 3, 7

    def __init__(self, pid, store):
        self.idProduct = pid
        out, inp = FakeEndpoint(0x01, store), FakeEndpoint(0x81, store)
        self.interface = [out, inp]

    def is_kernel_driver_active(self, number):
        return False

    def set_configuration(self):
        pass

    def get_active_configuration(self):
        return {(0, 0): self.interface}


def fake_usb(device):
    import types

    class USBError(OSError):
        pass

    def find_descriptor(interface, custom_match):
        return next((e for e in interface if custom_match(e)), None)

    core = types.SimpleNamespace(find=lambda custom_match: device if device and custom_match(device) else None,
                                 USBError=USBError)
    util = types.SimpleNamespace(find_descriptor=find_descriptor, ENDPOINT_OUT=0, ENDPOINT_IN=0x80,
                                 endpoint_direction=lambda address: address & 0x80, claim_interface=lambda *a: None,
                                 release_interface=lambda *a: None, dispose_resources=lambda *a: None)
    return types.SimpleNamespace(core=core, util=util)


def ok_answer():
    return bytes([0, 0xC8]) + bytes(510)


def test_turing_usb_header_layout():
    header = turing_usb.command_header(14, now=1_700_000_000.0)
    assert header[0] == 14 and header[2:4] == b"\x1a\x6d" and len(header) == 500
    packet = turing_usb.encrypt_header(header)
    assert len(packet) == 512 and packet[510:] == bytes((161, 26))
    from bsmd.displays import des
    assert packet[:504] == des.encrypt_cbc(b"slv3tuzx", b"slv3tuzx", bytes(header))


@pytest.mark.parametrize("pid,size,shape", [(0x0088, (1920, 480), "rect"), (0x0028, (480, 480), "round"),
                                            (0x0046, (960, 320), "rect")])
def test_turing_usb_open_and_frame(pid, size, shape):
    store = {"answers": [ok_answer(), ok_answer()]}
    driver = turing_usb.TuringUSB(usb_module=fake_usb(FakeUsbDevice(pid, store)))
    info = driver.open()
    assert driver.native_size == size and driver.capabilities.shape == shape and info.details["sync_ok"]
    transfer = driver.present(sample_image(*size))
    assert transfer.full
    frame = store["writes"][-1]
    assert frame[512:520] == b"\x89PNG\r\n\x1a\n"
    assert driver.present(sample_image(*size)).bytes == 0     # unchanged frames are not re-sent


def test_turing_usb_jpeg_fallback(monkeypatch):
    monkeypatch.setattr(turing_usb, "MAX_PAYLOAD", 20_000)
    cmd, data = turing_usb.encode_frame(sample_image(480, 480), max_bytes=20_000)
    assert cmd == turing_usb.CMD_UPLOAD_JPEG and len(data) <= 20_000 and data[:2] == b"\xff\xd8"


def test_turing_usb_disconnect_is_classified():
    store = {"answers": [ok_answer()]}
    driver = turing_usb.TuringUSB(usb_module=fake_usb(FakeUsbDevice(0x0088, store)))
    driver.open()
    error = OSError(19, "No such device")
    error.errno = 19
    store["fail"] = error
    with pytest.raises(DisplayError) as raised:
        driver.present(sample_image(1920, 480))
    assert raised.value.kind == base.DISCONNECTED


def test_turing_usb_brightness_scale():
    store = {"answers": [ok_answer(), ok_answer()]}
    driver = turing_usb.TuringUSB(usb_module=fake_usb(FakeUsbDevice(0x0088, store)))
    driver.open()
    driver.set_brightness(100)
    from bsmd.displays import des   # noqa: F401 - decrypt via cryptography if present
    pytest.importorskip("cryptography")
    try:
        from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    except ImportError:
        from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES
    from cryptography.hazmat.primitives.ciphers import Cipher, modes
    decryptor = Cipher(TripleDES(b"slv3tuzx" * 3), modes.CBC(b"slv3tuzx")).decryptor()
    plain = decryptor.update(store["writes"][-1][:504]) + decryptor.finalize()
    assert plain[0] == 14 and plain[8] == 102


# ------------------------------------------------------------- discovery

def device(vid, pid, serial="", path="1-1", ttys=("/dev/ttyACM0",)):
    return discovery.UsbDevice(path, vid, pid, serial, ttys=ttys)


@pytest.mark.parametrize("dev,profile,confidence", [
    (device(0x1908, 0x0102, ttys=()), "ax206", "confirmed"),
    (device(0x1A86, 0x5722, "USB35INCHIPSV2"), "turing_rev_a", "confirmed"),
    (device(0x1A86, 0x5722, "2017-2-25"), "xuanfang_rev_b", "confirmed"),
    (device(0x1A86, 0x5722, "whatever"), "turing_rev_a", "probable"),
    (device(0x1A86, 0xFE0C, "AB1234"), "weact_a", "confirmed"),
    (device(0x1A86, 0xFE0C, "AD99"), "weact_b", "confirmed"),
    (device(0x454D, 0x4E41), "kipye_rev_d", "probable"),
    (device(0x1CBE, 0x0088, ttys=()), "turing_usb", "probable"),
    (device(0x0525, 0xA4A7, "20080411"), "turing_rev_c", "probable"),
    (device(0x1234, 0x5678, "CT88INCH"), "turing_rev_c", "confirmed"),
])
def test_identification(dev, profile, confidence):
    candidate = discovery.classify(dev)
    assert candidate.best.profile.id == profile
    assert candidate.confidence == confidence
    assert candidate.auto_profile().id == profile


def test_ambiguous_weact_needs_a_choice():
    candidate = discovery.classify(device(0x1A86, 0xFE0C, "XX"))
    assert candidate.confidence == "ambiguous" and candidate.auto_profile() is None
    assert discovery.choose_profile(candidate, "weact_b").id == "weact_b"


def test_shared_ids_keep_the_alternative_visible():
    candidate = discovery.classify(device(0x1A86, 0x5722))
    assert [m.profile.id for m in candidate.matches] == ["turing_rev_a", "xuanfang_rev_b"]


def test_generic_gadget_without_turing_serial_is_not_claimed():
    assert not discovery.classify(device(0x0525, 0xA4A7, "pi-zero")).matches
    assert not discovery.classify(device(0x1CBE, 0x00FD, ttys=())).matches   # TI debug probe, same vendor


def test_sleeping_rev_c_carries_the_size_hint():
    candidate = discovery.classify(device(0x1A86, 0xCA21, "CT21INCH"))
    assert candidate.asleep and candidate.hint == "2.1"


def test_sysfs_scan(tmp_path):
    root = tmp_path / "devices"
    for name, values in (("3-2", {"idVendor": "1a86", "idProduct": "5722", "serial": "USB35INCHIPSV2",
                                  "busnum": "3", "devnum": "9"}),
                         ("3-2:1.0", {}), ("usb3", {"idVendor": "1d6b", "idProduct": "0002"}),
                         ("4-1", {"idVendor": "046d", "idProduct": "c52b"})):
        folder = root / name
        folder.mkdir(parents=True)
        for key, value in values.items():
            (folder / key).write_text(value + "\n")
    (root / "3-2" / "3-2:1.0" / "tty" / "ttyACM3").mkdir(parents=True)
    candidates = discovery.discover(discovery.scan_usb(str(root)))
    assert [(c.id, c.port, c.best.profile.id) for c in candidates] == [("usb-3-2", "/dev/ttyACM3", "turing_rev_a")]


def test_every_profile_has_a_driver():
    for profile in registry.PROFILES:
        candidate = discovery.Candidate(device(0x1, 0x2), [discovery.Match(profile, "confirmed", profile.rules[0])])
        assert profile.create(candidate) is not None
