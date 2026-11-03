import pytest
from PIL import Image

import fakes
from bsmd import drivers


def make_ax206(width=480, height=320):
    device = fakes.FakeAX206Device(width, height)
    driver = drivers.AX206(usb_module=fakes.fake_usb(device))
    return driver, device


def test_ax206_open_detects_resolution():
    driver, _device = make_ax206(800, 480)
    info = driver.open()
    assert (info.width, info.height) == (800, 480)
    assert driver.native_size == (800, 480)


def test_ax206_absent_raises_not_found():
    module = fakes.fake_usb(None)
    with pytest.raises(drivers.DisplayError) as error:
        drivers.AX206(usb_module=module).open()
    assert error.value.kind == drivers.NOT_FOUND


def test_ax206_full_then_partial_blit():
    driver, device = make_ax206()
    driver.open()
    image = Image.new("RGB", (480, 320), (10, 20, 30))
    first = driver.present(image)
    assert first.full and device.blits[-1][:4] == (0, 0, 480, 320)
    image.putpixel((479, 319), (255, 255, 255))
    second = driver.present(image)
    assert not second.full and device.blits[-1][:4] == (448, 304, 480, 320)
    assert second.bytes == 32 * 16 * 2
    assert driver.present(image).bytes == 0  # unchanged: nothing is sent


def test_ax206_disconnect_is_reported_not_swallowed():
    driver, device = make_ax206()
    driver.open()
    driver.present(Image.new("RGB", (480, 320)))
    device.faults = [fakes.ENODEV]
    with pytest.raises(drivers.DisplayError) as error:
        driver.present(Image.new("RGB", (480, 320), (100, 100, 100)))
    assert error.value.kind == drivers.DISCONNECTED
    assert driver._prev is None  # next frame is sent in full


@pytest.mark.parametrize("fault,kind", [(fakes.ETIMEDOUT, drivers.TIMEOUT), (fakes.EIO, drivers.IO)])
def test_ax206_error_classification(fault, kind):
    driver, device = make_ax206()
    driver.open()
    device.faults = [fault]
    with pytest.raises(drivers.DisplayError) as error:
        driver.set_brightness(50)
    assert error.value.kind == kind


def test_ax206_brightness_mapping():
    assert [drivers.brightness_to_ax206(p) for p in (0, 10, 50, 70, 100)] == [0, 1, 3, 5, 7]
    driver, device = make_ax206()
    driver.open()
    driver.set_brightness(100)
    assert device.brightness == 7


def test_ax206_bad_csw_is_protocol_error():
    driver, device = make_ax206()
    driver.open()
    device.read = lambda *a, **k: b"XXXX" + bytes(9)
    with pytest.raises(drivers.DisplayError) as error:
        driver.set_brightness(10)
    assert error.value.kind == drivers.PROTOCOL


def make_turing():
    from bsmd.displays.transport import SerialTransport
    fakes.FakeSerial.instances.clear()
    transport = SerialTransport("/dev/null", serial_module=fakes.fake_serial_module()).open()
    return drivers.TuringSmartScreen("/dev/null", transport=transport)


def test_turing_uses_write_timeout_and_exclusive_port():
    driver = make_turing()
    info = driver.open()
    port = fakes.FakeSerial.instances[-1]
    assert port.write_timeout and port.write_timeout > 0
    assert port.exclusive and port.rtscts
    assert (info.width, info.height) == (480, 320)


def test_turing_write_timeout_becomes_display_error():
    driver = make_turing()
    driver.open()
    driver.transport.ser.faults = [fakes.SerialTimeoutException("Write timeout")]
    with pytest.raises(drivers.DisplayError) as error:
        driver.present(Image.new("RGB", (480, 320)))
    assert error.value.kind == drivers.TIMEOUT


def test_turing_partial_update_covers_edges():
    driver = make_turing()
    driver.open()
    driver.display_width, driver.display_height = 480, 800   # 5" model: 800 is not a multiple of 48
    driver.set_orientation(2)
    driver._ready("UsbPCMonitor 5\"")
    image = Image.new("RGB", (800, 480))
    driver.present(image)
    image.putpixel((799, 0), (255, 0, 0))
    transfer = driver.present(image)
    assert transfer.rects == 1 and transfer.bytes == 32 * 20 * 2


def reference_command(cmd, x, y, ex, ey):
    """3.x TuringSmartScreen._send_command encoding."""
    buf = bytearray(6)
    buf[0] = (x >> 2)
    buf[1] = (((x & 3) << 6) + (y >> 4))
    buf[2] = (((y & 15) << 4) + (ex >> 6))
    buf[3] = (((ex & 63) << 2) + (ey >> 8))
    buf[4] = (ey & 255)
    buf[5] = cmd
    return bytes(buf)


@pytest.mark.parametrize("args", [(197, 0, 0, 479, 319), (197, 48, 20, 95, 39), (110, 128, 0, 0, 0)])
def test_turing_command_encoding(args):
    assert drivers.TuringSmartScreen.command(*args) == reference_command(*args)


def test_brightness_turing_scale():
    assert drivers.brightness_to_turing(100) == 0 and drivers.brightness_to_turing(0) == 255


def test_turing_absent():
    driver = drivers.TuringSmartScreen(None)
    with pytest.raises(drivers.DisplayError) as error:
        driver.open()
    assert error.value.kind == drivers.NOT_FOUND


def test_presence_detection_uses_discovery():
    from bsmd.displays.discovery import UsbDevice
    ax206 = UsbDevice("5-1.4.4", 0x1908, 0x0102, bus=5, address=13)
    turing = UsbDevice("3-2", 0x1A86, 0x5722, serial="USB35INCHIPSV2", ttys=("/dev/ttyACM0",))
    keyboard = UsbDevice("1-1", 0x046D, 0xC31C)
    assert drivers.device_present({"model": "ax206"}, devices=[keyboard]) is False
    assert drivers.device_present({"model": "auto"}, devices=[]) is False
    assert drivers.device_present({"model": "turing"}, devices=[ax206]) is False
    assert drivers.device_present({"model": "auto"}, devices=[ax206]) is True
    with pytest.raises(drivers.DisplayError):
        drivers.make_driver({"model": "auto"}, devices=[keyboard])
    driver = drivers.make_driver({"model": "turing"}, devices=[ax206, turing])
    assert isinstance(driver, drivers.TuringSmartScreen) and driver.port == "/dev/ttyACM0"
    driver = drivers.make_driver({"model": "auto"}, devices=[ax206])
    assert isinstance(driver, drivers.AX206) and (driver.bus, driver.address) == (5, 13)


def test_ax206_busy_device_is_classified():
    import errno as errno_
    driver, device = make_ax206()
    driver.open()
    device.faults = [fakes.USBError("Resource busy", -6, errno_.EBUSY)]
    with pytest.raises(drivers.DisplayError) as error:
        driver.set_brightness(10)
    assert error.value.kind == drivers.BUSY
    assert drivers.BUSY in drivers.EXTERNAL_KINDS
