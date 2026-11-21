"""FOSTON FS-707DC with BigFoston OS: FSP over TCP (USB network).

The device side is the Python model of the client (EmulatedDevice) behind a
real TCP socket, so TcpTransport and FostonLinuxDisplay run exactly as with
the navigator; the shell's C client is checked on the device itself."""

import socket
import threading
import time

import numpy as np
from PIL import Image, ImageDraw

from bsmd import frames
from bsmd.displays import discovery, registry
from bsmd.displays.base import DisplayError, NOT_FOUND
from bsmd.displays.foston import protocol as fsp
from bsmd.displays.foston.driver import LINUX_MODEL, FostonLinuxDisplay
from bsmd.displays.foston.emulator import EmulatedDevice
from bsmd.displays.transport import TcpTransport


class TcpDevice:
    """EmulatedDevice served on 127.0.0.1:<port>, one connection at a time."""

    def __init__(self, **kwargs):
        self.device = EmulatedDevice(client="bigfoston-shell 0.1.0 (emulated)", **kwargs)
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.conn = None
        self._stop = False
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while not self._stop:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.conn = conn
            threading.Thread(target=self._pump_out, args=(conn,), daemon=True).start()
            try:
                while True:
                    data = conn.recv(65536)
                    if not data:
                        break
                    self.device.write(data)
            except OSError:
                pass

    def _pump_out(self, conn):
        try:
            while True:
                data = self.device.read(65536)
                if data:
                    conn.sendall(data)
        except Exception:  # noqa: BLE001 - the connection went away
            pass

    def close(self):
        self._stop = True
        self.server.close()
        if self.conn is not None:
            self.conn.close()


def busy_image():
    image = Image.new("RGB", (800, 480), (10, 20, 30))
    draw = ImageDraw.Draw(image)
    for i in range(0, 800, 40):
        draw.rectangle((i, (i * 3) % 400, i + 30, (i * 3) % 400 + 60), fill=(i % 255, 120, 200 - i % 200))
    return image


def test_tcp_driver_handshake_frames_touch_and_brightness():
    server = TcpDevice()
    try:
        panel = FostonLinuxDisplay(host="127.0.0.1", tcp_port=server.port, host_name="biglinux")
        info = panel.open()
        assert info.model == LINUX_MODEL and (info.width, info.height) == (800, 480)
        assert info.location == f"tcp://127.0.0.1:{server.port}"
        assert "linux" in info.details and "windows_ce" not in info.details
        assert panel.capabilities.transport == "network" and panel.capabilities.touch == "single"
        image = busy_image()
        assert panel.present(image).full
        assert np.array_equal(server.device.fb, frames.image_to_rgb565(image, "<"))
        ImageDraw.Draw(image).rectangle((100, 100, 160, 140), fill=(255, 0, 0))
        transfer = panel.present(image)
        assert not transfer.full and transfer.rects >= 1
        assert np.array_equal(server.device.fb, frames.image_to_rgb565(image, "<"))
        got = []
        panel.on_input = got.append
        server.device.tap(400, 240)
        deadline = time.monotonic() + 3
        while len(got) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert [e.kind for e in got[:2]] == [fsp.TOUCH_DOWN, fsp.TOUCH_UP]
        assert (got[0].x, got[0].y) == (400, 240)
        panel.set_brightness(40)
        panel.probe()
        panel.close()
    finally:
        server.close()


def test_tcp_transport_reports_missing_app():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()                              # nothing listens there any more
    try:
        TcpTransport("127.0.0.1", port, connect_timeout=1.0).open()
    except DisplayError as error:
        assert error.kind == NOT_FOUND
    else:
        raise AssertionError("connecting to a closed port must fail")


def test_bigfoston_gadget_is_recognised_only_by_its_serial():
    gadget = discovery.UsbDevice("5-1.4.3", 0x0525, 0xA4AA, "BIGFOSTON-FS707DC", "Linux 6.12.117-bigfoston",
                                 "CDC Composite Gadget", 5, 7, ("/dev/ttyACM0",), ())
    other = discovery.UsbDevice("5-1.2", 0x0525, 0xA4AA, "", "Linux", "CDC Composite Gadget", 5, 8,
                                ("/dev/ttyACM1",), ())
    candidate = discovery.classify(gadget)
    assert candidate.auto_profile().id == "foston_bigfoston"
    assert not discovery.classify(other).matches              # any other Linux gadget is left alone
    driver = registry.get("foston_bigfoston").create(candidate, {})
    assert isinstance(driver, FostonLinuxDisplay) and driver.port == "tcp://192.168.7.2:7707"
