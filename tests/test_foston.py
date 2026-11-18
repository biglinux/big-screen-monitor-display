"""FOSTON FS-707DC: FSP protocol, C client core, driver, touch layer, runtime.

Everything here runs against models (the Python emulator and the client's
portable C core built with the host compiler). Physical validation is
recorded separately in docs/foston-fs707dc/10-testes-hardware.md.
"""

import os
import shutil
import struct
import subprocess
import threading
import time
import zlib

import numpy as np
import pytest
from PIL import Image, ImageDraw

from bsmd import frames, health, settings, touch
from bsmd.displays import discovery, registry
from bsmd.displays.base import PROTOCOL, TIMEOUT, DisplayError
from bsmd.displays.discovery import UsbDevice
from bsmd.displays.foston import protocol as fsp
from bsmd.displays.foston.driver import MODEL, FostonDisplay
from bsmd.displays.foston.emulator import EmulatedDevice, decode_rect

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CLIENT = os.path.join(ROOT, "device-clients", "wince")


def busy_image(seed=1, size=(800, 480)):
    rng = np.random.default_rng(seed)
    image = Image.new("RGB", size, (16, 20, 28))
    draw = ImageDraw.Draw(image)
    for _ in range(40):
        x, y = int(rng.integers(0, size[0] - 80)), int(rng.integers(0, size[1] - 60))
        draw.rectangle((x, y, x + int(rng.integers(5, 80)), y + int(rng.integers(5, 60))),
                       fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    draw.text((20, 20), "Big Screen Monitor 12:34", fill=(255, 255, 255))
    return image


# ------------------------------------------------------------------ protocol

def test_header_layout_and_crc():
    data = fsp.message(fsp.PING, b"\x01\x02\x03\x04", seq=0x1234)
    assert len(data) == fsp.HEADER_SIZE + 4
    magic, version, kind, seq, flags, length, pcrc, hcrc = fsp.HEADER.unpack_from(data)
    assert (magic, version, kind, seq, flags, length) == (b"FS", 1, fsp.PING, 0x1234, 0, 4)
    assert pcrc == fsp.crc16(b"\x01\x02\x03\x04")
    assert hcrc == fsp.crc16(data[:14])
    # CRC-16/CCITT-FALSE check value
    assert fsp.crc16(b"123456789") == 0x29B1


def test_parser_resynchronises_and_rejects_bad_crc():
    good = fsp.message(fsp.PONG, b"abcd" + b"\0" * 4, 1)
    bad = bytearray(fsp.message(fsp.PONG, b"zzzz" + b"\0" * 4, 2))
    bad[-1] ^= 0x55
    parser = fsp.Parser()
    stream = b"\x00garbage F" + good + bytes(bad) + b"FS\x01" + good
    out = []
    for i in range(0, len(stream), 3):            # tiny chunks like a slow serial port
        out += parser.feed(stream[i:i + 3])
    assert [m.payload[:4] for m in out] == [b"abcd", b"abcd"]
    assert parser.crc_errors == 1 and parser.dropped > 0


def test_oversized_payload_refused():
    with pytest.raises(ValueError):
        fsp.message(fsp.RECT, b"\0" * (fsp.MAX_PAYLOAD + 1))


@pytest.mark.parametrize("encoding", ["raw", "rle", "deflate", "auto"])
def test_encodings_roundtrip(encoding):
    rng = np.random.default_rng(3)
    pixels = rng.integers(0, 4, (37, 53), dtype=np.uint16) * 0x0841
    pixels[5:20, :] = 0xF800
    encoded = fsp.encode_rect(pixels, 7, 9, encoding)
    fb = np.zeros((100, 100), dtype=np.uint16)
    assert decode_rect(fb, encoded.kind, encoded.payload) == (7, 9, 53, 37)
    assert np.array_equal(fb[9:46, 7:60], pixels)


def test_uniform_area_becomes_fill_and_noise_stays_raw():
    flat = np.full((40, 40), 0x1234, dtype=np.uint16)
    assert fsp.encode_rect(flat, 0, 0).encoding == "fill"
    noise = np.random.default_rng(0).integers(0, 65535, (40, 40), dtype=np.uint16)
    assert fsp.encode_rect(noise, 0, 0).encoding == "raw"


def test_rle_long_runs_split_at_32768():
    data = fsp.rle_encode(np.full((1, 70000), 7, dtype=np.uint16))
    tokens = [struct.unpack_from("<HH", data, offset) for offset in range(0, len(data), 4)]
    assert tokens == [(0xFFFF, 7), (0xFFFF, 7), (0x8000 | (70000 - 65536 - 1), 7)]


def test_hello_ack_parse():
    payload = struct.pack("<HHHHIIIII", 1, 800, 480, 16, 5, 0, 1400, 61440, 30000) + bytes([1, 80, 1, 1]) + \
        b"bsmd-ce 1.0.0\0MT3351\0FOSTON\0COM9:\0Mass_Storage_Class\0"
    ack = fsp.HelloAck.parse(payload)
    assert (ack.width, ack.height, ack.bpp, ack.os_version) == (800, 480, 16, (5, 0, 1400))
    assert ack.touch and ack.usb_switched and ack.brightness == 1
    assert ack.strings["port"] == "COM9:" and ack.strings["usb_previous"] == "Mass_Storage_Class"


# ------------------------------------------------------- C core of the client

@pytest.fixture(scope="module")
def host_decoder(tmp_path_factory):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        pytest.skip("no host C compiler")
    out = tmp_path_factory.mktemp("fsp") / "host_decode"
    subprocess.run([compiler, "-O2", "-Wall", "-Wextra", "-Werror", "-std=c99", "-o", str(out),
                    os.path.join(CLIENT, "tests", "host_decode.c"), os.path.join(CLIENT, "src", "fsp.c")],
                   check=True)
    return str(out)


def run_decoder(decoder, tmp_path, stream, size, bottom_up=False):
    src, dst = tmp_path / "stream.bin", tmp_path / "fb.bin"
    src.write_bytes(stream)
    args = [decoder, str(size[0]), str(size[1]), str(src), str(dst)] + (["bottom-up"] if bottom_up else [])
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    fb = np.fromfile(dst, dtype="<u2").reshape(size[1], size[0])
    stats = dict(item.split("=") for item in result.stdout.split())
    return (fb[::-1] if bottom_up else fb), {k: int(v) for k, v in stats.items()}


@pytest.mark.parametrize("bottom_up", [False, True])
def test_c_core_decodes_driver_stream_byte_exact(host_decoder, tmp_path, bottom_up):
    """The C core of bsmd-ce and the Python driver agree on every byte."""
    device = EmulatedDevice()
    driver = FostonDisplay("/dev/fake", transport=device, host_name="test")
    driver.open()
    image = busy_image(1)
    driver.present(image)
    draw = ImageDraw.Draw(image)
    for step in range(5):
        draw.text((100 + step * 40, 200), str(step), fill=(255, 200, 0))
        driver.present(image)
    stream = bytearray()
    recorder = []
    # Re-encode the same session with every encoding to cover the C paths.
    for encoding in ("raw", "rle", "deflate", "auto"):
        pixels = frames.image_to_rgb565(image, "<")
        for band in range(0, 480, 96):
            rect = fsp.encode_rect(pixels[band:band + 96], 0, band, encoding)
            stream += fsp.message(rect.kind, rect.payload, len(recorder))
            recorder.append(rect.encoding)
        stream += fsp.message(fsp.PRESENT, fsp.present(len(recorder)))
    stream += b"\x00\x13garbageFS\x01" + fsp.message(fsp.PING, b"1234")
    fb, stats = run_decoder(host_decoder, tmp_path, bytes(stream), (800, 480), bottom_up)
    assert np.array_equal(fb, frames.image_to_rgb565(image, "<"))
    assert np.array_equal(device.fb, frames.image_to_rgb565(image, "<"))
    assert stats["presents"] == 4 and stats["naks"] == 0 and stats["dropped"] > 0
    driver.close()


def test_c_core_rejects_corrupt_and_hostile_input(host_decoder, tmp_path):
    rng = np.random.default_rng(5)
    stream = bytearray()
    good = fsp.encode_rect(np.full((10, 10), 0xFFFF, dtype=np.uint16), 0, 0, "raw")
    corrupt = bytearray(fsp.message(good.kind, good.payload, 1))
    corrupt[40] ^= 0xFF                                   # payload CRC mismatch
    stream += corrupt
    # rectangle outside the panel, truncated RLE, bogus zlib: all refused, no crash
    stream += fsp.message(fsp.FILL, struct.pack("<HHHHH", 790, 470, 20, 20, 1))
    stream += fsp.message(fsp.RECT, struct.pack("<HHHHBBHH", 0, 0, 4, 4, fsp.ENC_RLE, 0, 0, 0) + b"\x05\x00\x01")
    stream += fsp.message(fsp.RECT, struct.pack("<HHHHBBHH", 0, 0, 4, 4, fsp.ENC_DEFLATE, 0, 0, 0) +
                          bytes(rng.integers(0, 255, 40, dtype=np.uint8)))
    stream += fsp.message(fsp.RECT, struct.pack("<HHHHBBHH", 0, 0, 4, 4, fsp.ENC_DEFLATE, 0, 0, 0) +
                          zlib.compress(b"\0" * 10))       # inflates to the wrong size
    stream += fsp.message(fsp.FILL, struct.pack("<HHHHH", 0, 0, 2, 2, 0x1234))
    fb, stats = run_decoder(host_decoder, tmp_path, bytes(stream), (800, 480))
    assert stats["crc_errors"] == 1
    assert stats["naks"] == 1 + 4                         # CRC + four refused rectangles
    assert fb[0, 0] == 0x1234 and fb[5, 5] == 0          # the valid FILL still landed


# ------------------------------------------------------------------- driver

class EmulatedPanel(FostonDisplay):
    """Driver bound to an emulated device; reconnects keep the same device."""

    def __init__(self, device=None, **kwargs):
        self.device = device or EmulatedDevice()
        super().__init__("/dev/ttyUSB-emulated", transport=self.device, host_name="biglinux", **kwargs)
        self.connected = True

    def close(self):
        super().close()
        self.transport = self.device


def test_driver_handshake_frames_and_controls():
    panel = EmulatedPanel()
    info = panel.open()
    assert info.model == MODEL and (info.width, info.height) == (800, 480)
    assert panel.capabilities.touch == "single" and panel.capabilities.brightness
    assert info.details["usb_previous_client"] == "Mass_Storage_Class"
    image = busy_image(2)
    transfer = panel.present(image)
    assert transfer.full and transfer.rects == 1
    assert np.array_equal(panel.device.fb, frames.image_to_rgb565(image, "<"))
    assert panel.present(image).rects == 0               # nothing changed: nothing sent
    ImageDraw.Draw(image).rectangle((300, 300, 340, 320), fill=(255, 0, 0))
    transfer = panel.present(image)
    assert not transfer.full and transfer.bytes < 2000
    assert np.array_equal(panel.device.fb, frames.image_to_rgb565(image, "<"))
    panel.set_brightness(35)
    panel.probe()
    panel.calibrate()
    assert wait(lambda: panel.device.brightness == 35 and panel.device.calibrations == 1)
    panel.close()


def test_driver_without_client_reports_timeout():
    panel = EmulatedPanel(EmulatedDevice(silent=True))
    panel.HELLO_TIMEOUT = 0.3
    with pytest.raises(DisplayError) as error:
        panel.open()
    assert error.value.kind == TIMEOUT and "bsmd-ce" in str(error.value)


def test_driver_detects_hung_device_and_nak():
    panel = EmulatedPanel()
    panel.open()
    panel.PRESENT_TIMEOUT = 0.3
    image = busy_image(3)
    panel.present(image)
    panel.device.nak_next = True
    ImageDraw.Draw(image).text((10, 400), "nak", fill=(255, 255, 255))
    panel.present(image)                                  # repaired in place: re-handshake + full frame
    assert panel.stats["resyncs"] == 1
    assert np.array_equal(panel.device.fb, frames.image_to_rgb565(image, "<"))
    panel.device.drop_present = True
    ImageDraw.Draw(image).text((10, 440), "hung", fill=(255, 255, 255))
    with pytest.raises(DisplayError) as error:
        panel.present(image)                              # timeout, resync, timeout again: give up
    assert error.value.kind == TIMEOUT and panel.stats["resyncs"] == 2
    panel.close()


def test_driver_refuses_unknown_client():
    device = EmulatedDevice(width=480, height=800)        # portrait-native: not supported yet
    panel = EmulatedPanel(device)
    with pytest.raises(DisplayError) as error:
        panel.open()
    assert error.value.kind == PROTOCOL


def test_unplug_is_reported_as_disconnected():
    panel = EmulatedPanel()
    panel.open()
    panel.device.unplug()
    with pytest.raises(DisplayError) as error:
        panel.present(busy_image(4))
    assert error.value.kind in ("disconnected", "timeout")
    panel.close()


def test_touch_events_reach_callback_in_order():
    panel = EmulatedPanel()
    panel.open()
    events = []
    panel.on_input = events.append
    panel.device.touch(fsp.TOUCH_DOWN, 10, 20)
    panel.device.touch(fsp.TOUCH_MOVE, 30, 20)
    panel.device.touch(fsp.TOUCH_UP, 40, 20)
    assert wait(lambda: len(events) == 3)
    assert [(e.kind, e.x, e.y) for e in events] == [(1, 10, 20), (2, 30, 20), (3, 40, 20)]
    panel.close()


# ---------------------------------------------------------------- discovery

def test_registry_and_discovery_match_wince_serial():
    profile = registry.get("foston_fs707dc")
    assert profile is not None and profile.name == "FOSTON FS-707DC Touch Display"
    assert "foston_fs707dc" in settings.PROFILE_IDS
    device = UsbDevice("5-1.4.1", 0x045E, 0x00CE, "", "Generic Manufacturer", "Generic Serial", 5, 6,
                       ("/dev/ttyUSB0",), ())
    candidate = discovery.classify(device)
    assert candidate.auto_profile().id == "foston_fs707dc"
    driver = profile.create(candidate)
    assert isinstance(driver, FostonDisplay) and driver.port == "/dev/ttyUSB0"
    # the same navigator in mass-storage mode is not a display
    storage = UsbDevice("5-1.4.1", 0x045E, 0xFFFF, "A4E7EDDA-E575-4252-9D6B-4195D48BB863", "", "", 5, 7, (), ())
    assert not discovery.classify(storage).matches


def test_udev_rule_is_pinned_to_the_wince_serial_function():
    rules = open(os.path.join(ROOT, "usr", "lib", "udev", "rules.d", "70-big-screen-monitor-display.rules"),
                 encoding="utf-8").read()
    logical = rules.replace("\\\n", " ")
    line = next(line for line in logical.splitlines() if "045e" in line and "00ce" in line and
                not line.startswith("#"))
    assert 'SUBSYSTEM=="tty"' in line and "MODE=\"0666\"" not in line and 'GROUP="big-screen-monitor"' in line


# -------------------------------------------------------------------- touch

@pytest.mark.parametrize("orientation", settings.ORIENTATIONS)
def test_native_to_render_inverts_the_frame_rotation(orientation):
    native = (800, 480)
    size = frames.render_size(native, orientation)
    for point in ((0, 0), (10, 20), (size[0] - 1, size[1] - 1), (123, 45)):
        image = Image.new("L", size, 0)
        image.putpixel(point, 255)
        rotated = np.asarray(frames.to_native(image, native, orientation))
        y, x = map(int, np.argwhere(rotated == 255)[0])
        assert touch.native_to_render(x, y, native, orientation) == point


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_gestures():
    r, clock = touch.GestureRecognizer(), Clock()

    def names(seq):
        out = []
        for kind, x, y, dt in seq:
            clock.now += dt
            out += [g[0] for g in r.feed(kind, x, y, clock.now) + r.tick(clock.now)]
        return [n for n in out if n not in ("press", "release", "drag")]
    assert names([(1, 100, 100, 0), (3, 104, 102, 0.1)]) == ["tap"]
    assert names([(1, 100, 100, 0), (2, 101, 100, 0.8), (3, 101, 100, 0.1)]) == ["long_press"]
    assert names([(1, 400, 200, 0), (2, 300, 205, 0.1), (3, 200, 210, 0.1)]) == ["swipe_left"]
    assert names([(1, 200, 200, 0), (3, 400, 190, 0.2)]) == ["swipe_right"]
    assert names([(1, 400, 400, 0), (3, 405, 200, 0.2)]) == ["swipe_up"]
    assert names([(1, 100, 100, 0), (2, 300, 300, 0.5), (3, 310, 300, 2.0)]) == []    # slow drag
    assert names([(3, 1, 1, 0)]) == []                                                # stray release


class Host:
    def __init__(self, settings_value=None):
        self.values = dict(settings_value or {"theme": "standard", "brightness": 70})
        self.requests = []
        self.wakes = 0

    def base_settings(self):
        return dict(self.values)

    def request(self, *args):
        self.requests.append(args)

    def wake(self):
        self.wakes += 1

    def name(self):
        return "FOSTON"

    def state(self):
        return "healthy"


def tap(ui, clock, x, y):
    ui.handle(touch.DOWN, x, y)
    clock.now += 0.08
    ui.handle(touch.UP, x, y)
    clock.now += 0.05


def test_touch_ui_bar_buttons_theme_and_brightness(tmp_path):
    host, clock = Host(), Clock()
    ui = touch.TouchUI(host, str(tmp_path / "touch.json"), clock=clock)
    frame = Image.new("RGB", (800, 480), (0, 0, 0))
    tap(ui, clock, 400, 200)                        # first tap opens the bar
    assert ui.page == "bar"
    decorated = ui.decorate(frame, ui.apply(host.base_settings()))
    assert decorated.size == frame.size and decorated.getpixel((400, 470)) != (0, 0, 0)
    buttons = {action: box for box, action, arg in ui.buttons if action != "brightness"}
    brighter = next(box for box, action, arg in ui.buttons if action == "brightness" and arg > 0)
    box = buttons["theme_next"]
    tap(ui, clock, (box[0] + box[2]) // 2, (box[1] + box[3]) // 2)
    assert ui.apply(host.base_settings())["theme"] == settings.THEME_IDS[1]
    tap(ui, clock, (brighter[0] + brighter[2]) // 2, (brighter[1] + brighter[3]) // 2)
    assert ("brightness", 80) in host.requests and ui.apply(host.base_settings())["brightness"] == 80
    # persisted: a new UI (service restart) keeps the panel's choices
    again = touch.TouchUI(host, str(tmp_path / "touch.json"), clock=clock)
    assert again.apply(host.base_settings())["theme"] == settings.THEME_IDS[1]
    # the configuration window wins: changing the theme there drops the override
    host.values["theme"] = "planet"
    assert again.apply(host.base_settings())["theme"] == "planet"
    assert "theme" not in again.overrides.values


def test_touch_ui_menu_gallery_test_and_timeout(tmp_path):
    host, clock = Host(), Clock()
    ui = touch.TouchUI(host, None, clock=clock)
    ui.handle(touch.DOWN, 300, 300)
    clock.now += 0.9
    ui.tick()                                       # long press fires while still held
    ui.handle(touch.UP, 300, 300)
    assert ui.page == "menu"
    ui.decorate(Image.new("RGB", (800, 480)), host.base_settings())
    kojiro = next(box for box, action, arg in ui.buttons if action == "theme" and arg == "kojiro")
    tap(ui, clock, (kojiro[0] + kojiro[2]) // 2, (kojiro[1] + kojiro[3]) // 2)
    assert ui.page is None and ui.apply(host.base_settings())["theme"] == "kojiro"
    ui.start_test()
    for x in range(100, 300, 20):
        ui.handle(touch.MOVE if x > 100 else touch.DOWN, x, 200)
    ui.handle(touch.UP, 300, 200)
    image = ui.decorate(Image.new("RGB", (800, 480)), host.base_settings())
    assert ui.page == "test" and len(ui.trail) >= 5 and image.getpixel((200, 200)) != (0, 0, 0)
    clock.now += touch.TEST_SECONDS + 1
    ui.tick()
    assert ui.page is None
    # swipes cycle themes without opening anything
    ui.handle(touch.DOWN, 600, 240)
    clock.now += 0.2
    ui.handle(touch.UP, 300, 240)
    assert ui.page is None and ("invalidate",) in host.requests


def test_touch_ui_portrait_layout_has_reachable_buttons():
    host, clock = Host(), Clock()
    ui = touch.TouchUI(host, None, clock=clock)
    tap(ui, clock, 10, 10)
    ui.decorate(Image.new("RGB", (480, 800)), host.base_settings())
    assert ui.buttons and all(box[2] <= 480 and box[3] <= 800 and box[2] - box[0] >= 40 for box, _a, _b in
                              ui.buttons)


# ------------------------------------------------------------------ runtime

def wait(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def foston_runtime(tmp_path):
    from test_runtime import FakeNotifier, FastRuntime
    config = tmp_path / "settings.json"
    apps = []

    def start(panels, data=None):
        settings.save(data or {"theme": "standard", "brightness": 60}, str(config))
        app = FastRuntime(settings.SettingsStore(str(config)), notifier=FakeNotifier(), simulate=panels,
                          status_file=str(tmp_path / "run" / "status.json"),
                          state_directory=str(tmp_path / "state"))
        app.backoff = health.Backoff(base=0.05, cap=0.2, jitter=0)
        thread = threading.Thread(target=app.run, daemon=True)
        thread.start()
        apps.append((app, thread))
        return app
    yield start
    for app, thread in apps:
        app.stop()
        thread.join(5)


def test_runtime_end_to_end_with_touch(foston_runtime):
    panel = EmulatedPanel()
    app = foston_runtime([panel])
    assert wait(lambda: len(panel.device.presented) >= 2)
    session = app.sessions["simulated"]
    assert session.touch is not None and panel.device.brightness == 60
    assert panel.device.fb.any()
    # a swipe on the panel changes this display's theme, nothing else
    panel.device.touch(fsp.TOUCH_DOWN, 600, 240)
    panel.device.touch(fsp.TOUCH_UP, 300, 240, tick=200)
    assert wait(lambda: session.theme is not None and session.theme.info.id == settings.THEME_IDS[1])
    # a tap shows the control bar on the panel itself
    before = len(panel.device.presented)
    panel.device.tap(400, 100)
    ok = wait(lambda: session.touch.page == "bar" and len(panel.device.presented) > before)
    assert ok, (session.touch.page, session.touch.events, len(panel.device.presented), before, session.link.state)
    status = session.status()
    assert status["touch"]["events"] >= 4 and status["stats"]["touch_events"] >= 4


def test_runtime_recovers_after_unplug_and_keeps_other_panels(foston_runtime):
    from bsmd.displays.simulated import SimulatedDisplay
    panel, other = EmulatedPanel(), SimulatedDisplay((480, 320))
    app = foston_runtime([panel, other])
    assert wait(lambda: len(panel.device.presented) >= 1 and other.frames >= 1)
    panel.device.unplug()
    frames_other = other.frames
    assert wait(lambda: app.sessions["simulated"].link.state != health.HEALTHY)
    assert wait(lambda: other.frames > frames_other + 2)            # the other panel keeps going
    panel.device.closed = False                                       # plugged back
    count = len(panel.device.presented)
    assert wait(lambda: len(panel.device.presented) > count, timeout=12)
    assert app.sessions["simulated"].recoveries >= 1


# ------------------------------------------------------------ flow control

def test_old_client_without_credits_is_refused():
    device = EmulatedDevice(client="bsmd-ce 1.0.2")
    device.credits = False
    panel = EmulatedPanel(device)
    with pytest.raises(DisplayError) as error:
        panel.open()
    assert error.value.kind == PROTOCOL and "too old" in str(error.value)


def test_credit_window_limits_bytes_in_flight():
    """The FS-707DC serial driver drops data beyond ~1 KB when unread (measured):
    the host must never run further ahead than the client confirmed."""
    panel = EmulatedPanel()
    panel.open()
    panel.WINDOW = 4096
    panel.PRESENT_TIMEOUT = 0.4
    panel.device.withhold_credit = True
    noise = Image.fromarray(np.random.default_rng(9).integers(0, 255, (480, 800, 3), dtype=np.uint8), "RGB")
    with pytest.raises(DisplayError) as error:
        panel.present(noise)              # first message goes out alone, the next one must wait
    assert error.value.kind == TIMEOUT
    assert panel._sent - panel._credited <= max(panel.WINDOW, 800 * 480 * 2 + 64)
    panel.close()


def test_credits_let_large_frames_through():
    panel = EmulatedPanel()
    panel.open()
    panel.WINDOW = 8192                   # far smaller than a raw frame: many round trips
    panel.options["encoding"] = "raw"
    image = busy_image(7)
    panel.present(image)
    assert np.array_equal(panel.device.fb, frames.image_to_rgb565(image, "<"))
    assert panel._credited == panel._sent
    panel.close()


def test_bar_hides_brightness_when_the_panel_has_no_backlight_control():
    host, clock = Host(), Clock()
    host.brightness_supported = lambda: False
    ui = touch.TouchUI(host, None, clock=clock)
    tap(ui, clock, 400, 200)
    ui.decorate(Image.new("RGB", (800, 480)), host.base_settings())
    assert ui.buttons and not [b for b in ui.buttons if b[1] == "brightness"]


def test_client_installer_finds_only_the_navigator_and_verifies_the_copy(tmp_path):
    from bsmd.displays.foston import install
    sysfs = tmp_path / "sys"
    for block, ids in (("sdf", ("045e", "ffff")), ("sde", ("0781", "55bb"))):
        usb = sysfs / "devices" / f"usb-{block}"
        (usb / "host" / "target").mkdir(parents=True)
        (usb / "idVendor").write_text(ids[0])
        (usb / "idProduct").write_text(ids[1])
        (sysfs / "block" / block).mkdir(parents=True)
        os.symlink(usb / "host" / "target", sysfs / "block" / block / "device")
    mounts = tmp_path / "mounts"
    nav, ssd = tmp_path / "nav vol", tmp_path / "ssd"
    nav.mkdir()
    ssd.mkdir()
    mounts.write_text(f"/dev/sdf1 {str(nav).replace(' ', chr(92) + '040')} vfat rw 0 0\n"
                      f"/dev/sde1 {ssd} ntfs rw 0 0\n/dev/sdd2 / btrfs rw 0 0\n")
    assert install.find_volumes(str(sysfs), str(mounts)) == [str(nav)]
    client = tmp_path / "bsmd-ce.exe"
    client.write_bytes(b"MZ" + bytes(range(256)) * 10)
    target = install.install(str(nav), str(client))
    assert target == str(nav / "BigScreen" / "bsmd-ce.exe")
    assert open(target, "rb").read() == client.read_bytes()
    assert not os.path.exists(target + ".new")


def test_packaged_client_matches_its_checksum():
    from bsmd.displays.foston import install
    expected = open(install.PACKAGED_CLIENT + ".sha256").read().split()[0]
    assert install.sha256(install.PACKAGED_CLIENT) == expected
    assert open(install.PACKAGED_CLIENT, "rb").read(2) == b"MZ"


def test_exit_to_device_menu_needs_a_confirming_tap():
    host, clock = Host(), Clock()
    host.can_quit = lambda: True
    ui = touch.TouchUI(host, None, clock=clock)
    ui._open("menu", clock())
    ui.decorate(Image.new("RGB", (800, 480)), host.base_settings())
    quit_box = next(box for box, action, _arg in ui.buttons if action == "quit")
    center = ((quit_box[0] + quit_box[2]) // 2, (quit_box[1] + quit_box[3]) // 2)
    tap(ui, clock, *center)
    assert ("quit_client",) not in host.requests and ui.page == "menu"   # armed only
    clock.now += touch.QUIT_CONFIRM_SECONDS + 1
    tap(ui, clock, *center)
    assert ("quit_client",) not in host.requests                        # expired: armed again
    tap(ui, clock, *center)
    assert ("quit_client",) in host.requests and ui.page is None


def test_menu_has_no_exit_for_panels_without_a_client():
    host, clock = Host(), Clock()
    ui = touch.TouchUI(host, None, clock=clock)
    ui._open("menu", clock())
    ui.decorate(Image.new("RGB", (800, 480)), host.base_settings())
    assert not [b for b in ui.buttons if b[1] == "quit"]


def test_runtime_quit_client_reaches_the_device(foston_runtime):
    panel = EmulatedPanel()
    app = foston_runtime([panel])
    assert wait(lambda: len(panel.device.presented) >= 1)
    app.sessions["simulated"].request("quit_client")
    assert wait(lambda: panel.device.quit)
