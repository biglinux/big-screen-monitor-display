"""DeepCool support: packets, metrics, sensors, drivers and runtime integration.

Hardware-free. Packets are checked byte by byte against the layouts documented
by the reference projects (docs/deepcool/03-protocolos.md); the MYSTIQUE
checksum is also checked against a response captured on real hardware by
dinoyoshi/serial-lcd-panel-client. Passing here means "implemented as
documented", not "validated on a physical cooler".
"""

import os
import struct
import types

import pytest

from bsmd import health, runtime, settings, telemetry
from bsmd.displays import discovery, registry
from bsmd.displays.base import DISCONNECTED, PERMISSION, TELEMETRY, DisplayError
from bsmd.displays.deepcool import conflicts, drivers, hid, metrics, models, protocols
from bsmd.displays.discovery import UsbDevice

FAMILY = models.FAMILIES


# ---------------------------------------------------------------- packets: AK / AG / LS

def test_ak_temperature_packet():
    data = protocols.ak_status(protocols.MODE_TEMP_C, 45, 37, False)
    assert len(data) == 64
    assert list(data[:7]) == [16, 19, 4, 0, 4, 5, 0] and not any(data[7:])


def test_ak_usage_fahrenheit_alarm_and_clamping():
    assert list(protocols.ak_status(protocols.MODE_SECOND, 100, 100, True)[:7]) == [16, 76, 10, 1, 0, 0, 1]
    assert list(protocols.ak_status(protocols.MODE_TEMP_F, 2000, 5, False)[:6]) == [16, 35, 1, 9, 9, 9]
    assert protocols.status_bar(14.9) == 1 and protocols.status_bar(15) == 2 and protocols.status_bar(None) == 1


def test_ak_se_variant_drops_the_report_id():
    normal = protocols.ak_status(protocols.MODE_TEMP_C, 61, 50, False)
    se = protocols.ak_status(protocols.MODE_TEMP_C, 61, 50, False, se=True)
    assert len(se) == 63 and se == normal[1:]
    assert protocols.ak_init(True) == protocols.ak_init()[1:] and protocols.ak_init()[:2] == bytes((16, 170))


def test_ag_two_digits_and_alarm_position():
    assert list(protocols.ag_status(protocols.MODE_TEMP_C, 72, True)[:6]) == [16, 19, 0, 7, 2, 1]
    assert list(protocols.ag_status(protocols.MODE_SECOND, 100, False)[:6]) == [16, 76, 0, 9, 9, 0]


# ---------------------------------------------------------------- packets: AK PRO / LD

def test_ak_pro_packet_byte_by_byte():
    data = protocols.structured_status(protocols.HEADER_AK_PRO, 65, 55, False, 30, 4500)
    expected = [16, 104, 1, 4, 13, 1, 2, 8, 0, 65, 0, 66, 92, 0, 0, 30, 17, 148, 39, 22]
    assert list(data[:20]) == expected and not any(data[20:])


def test_ak400_pro_and_ld_have_no_frequency():
    for header in (protocols.HEADER_AK400_PRO, protocols.HEADER_LD):
        data = protocols.structured_status(header, 120.4, 70, True, 99.6, None)
        assert data[1:8] == bytes(header)
        assert struct.unpack(">H", data[8:10])[0] == 120 and data[10] == 1
        assert struct.unpack(">f", data[11:15])[0] == 70.0 and data[15] == 100
        assert data[16] == sum(data[1:16]) % 256 and data[17] == 22 and not any(data[18:])


def test_structured_values_are_clamped():
    data = protocols.structured_status(protocols.HEADER_AK_PRO, 99999, None, False, -5, 70000)
    assert struct.unpack(">H", data[8:10])[0] == 0xFFFF and data[15] == 0
    assert struct.unpack(">H", data[16:18])[0] == 0xFFFF


def test_ld_init_sequence():
    first, second = protocols.ld_init(True)
    assert list(first[:9]) == [16, 104, 1, 1, 2, 3, 1, 112, 22]
    assert list(second[:9]) == [16, 104, 1, 1, 2, 2, 1, 111, 22]
    assert list(protocols.ld_init(False)[1][:9]) == [16, 104, 1, 1, 2, 2, 0, 110, 22]


# ---------------------------------------------------------------- packets: MYSTIQUE

def test_mystique_checksum_matches_a_real_hardware_capture():
    captured = bytes.fromhex("552e" + "00" * 40 + "48494443" + "9b01")
    assert len(captured) == 48
    assert protocols.mystique_checksum(captured) == 0x019B


def test_mystique_framing():
    packet = protocols.mystique_packet(protocols.CMD_DEVICE_INFO)
    assert len(packet) == 48 and packet[:3] == bytes((0xAA, 0x2E, 0x12)) and packet[42:46] == b"HIDC"
    assert packet[46:] == bytes((0x02, 0x02))
    with pytest.raises(ValueError):
        protocols.mystique_packet(0x01, bytes(40))
    assert protocols.mystique_rotation(270)[3:8] == bytes((0x01, 0x00, 0x03, 0x01, 0x24))


def test_mystique_display_packet():
    packet = protocols.mystique_display(34, 7, 4, 36, 5200)
    assert packet[2] == 0x01 and packet[3] == 34 and packet[6] == 7 and packet[9] == 4 and packet[14] == 36
    assert packet[11] == 0x06 and (packet[12], packet[15], packet[17], packet[18], packet[20]) == (3, 5, 6, 12, 7)
    assert packet[21] == 5 and packet[23] == 20
    assert struct.unpack("<H", packet[24:26])[0] == 2000 == struct.unpack("<H", packet[27:29])[0]
    assert protocols.mystique_checksum(packet) == packet[46] | packet[47] << 8
    low = protocols.mystique_display(200, 150, -1, None, 4030)
    assert low[3] == 127 and low[6] == 100 and low[9] == 0 and low[14] == 0 and low[23] == 0x0A


def test_no_image_upload_commands_are_exposed():
    names = dir(protocols)
    assert not any("upload" in name.lower() or "erase" in name.lower() for name in names)
    assert all(command not in (0x0F, 0x14) for command, _p in protocols.MYSTIQUE_INIT)


# ---------------------------------------------------------------- models and detection

def test_models_and_families():
    assert models.family_for(0x0002).id == "deepcool_ak" and models.family_for(0x0012).id == "deepcool_ak_pro"
    assert models.family_for(0x000A).id == "deepcool_ld" and models.family_for(0x0009).id == "deepcool_mystique"
    assert models.family_for(0x0005) is None                   # CH560: identified, not driven
    assert models.model_name(0x0002, "AK620-DIGITAL") == "AK620 DIGITAL"
    assert models.is_se(0x0001, "A400") and not models.is_se(0x0001, "AK400") and not models.is_se(0x0012, "x")
    assert models.model_name(0x0001, "A400") == "AK400 DIGITAL SE"


def test_settings_profile_ids_include_deepcool():
    assert {p.id for p in registry.PROFILES} == set(settings.PROFILE_IDS)


def test_discovery_classifies_by_vid_pid_only():
    ak = UsbDevice("1-2", 0x3633, 0x0002, product="AK620-DIGITAL", hidraws=("/dev/hidraw7",))
    case = UsbDevice("1-3", 0x3633, 0x0005, product="CH560")
    other = UsbDevice("1-4", 0x3634, 0x0002)
    found = discovery.discover([ak, case, other])
    assert [c.id for c in found] == ["usb-1-2"]
    assert found[0].auto_profile().id == "deepcool_ak" and found[0].confidence == "confirmed"


def test_scan_finds_hidraw_nodes(tmp_path):
    dev = tmp_path / "1-2"
    node = dev / "1-2:1.0" / "0003:3633:0002.0007" / "hidraw" / "hidraw7"
    node.mkdir(parents=True)
    for name, value in (("idVendor", "3633"), ("idProduct", "0002"), ("product", "AK620-DIGITAL"),
                        ("busnum", "1"), ("devnum", "5")):
        (dev / name).write_text(value)
    devices = discovery.scan_usb(str(tmp_path))
    assert devices[0].hidraws == ("/dev/hidraw7",) and devices[0].product == "AK620-DIGITAL"


# ---------------------------------------------------------------- telemetry: power, frequency, temperature

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def rapl(tmp_path, energy, limit="262143328850"):
    domain = tmp_path / "intel-rapl:0"
    write(domain / "name", "package-0")
    write(domain / "energy_uj", str(energy))
    write(domain / "max_energy_range_uj", limit)
    write(tmp_path / "intel-rapl:0:0" / "name", "core")
    return domain


def test_power_from_rapl_delta(tmp_path):
    domain = rapl(tmp_path, 1_000_000)
    meter = telemetry.EnergyCounter.find(str(tmp_path), str(tmp_path / "nohwmon*"))
    assert meter.label == "RAPL intel-rapl:0"
    assert meter.sample(10.0) is None and meter.status == "warming"        # never 0 W on the first sample
    (domain / "energy_uj").write_text(str(1_000_000 + 45_000_000))
    assert meter.sample(11.0) == pytest.approx(45.0) and meter.status == "ok"


def test_power_counter_wraparound_and_reset(tmp_path):
    domain = rapl(tmp_path, 990, limit="1000")
    meter = telemetry.EnergyCounter.find(str(tmp_path), str(tmp_path / "x*"))
    meter.sample(0.0)
    (domain / "energy_uj").write_text("10")                      # wrapped: 10 + 1000 - 990 = 20 µJ
    assert meter.sample(1.0) == pytest.approx(20 / 1_000_000)
    hw = tmp_path / "hwmon5"
    write(hw / "name", "zenergy")
    write(hw / "energy1_label", "Ecore000")
    write(hw / "energy17_label", "Esocket0")
    write(hw / "energy17_input", "500000000")
    zen = telemetry.EnergyCounter.find(str(tmp_path / "none"), str(tmp_path / "hwmon*"))
    assert zen.label == "zenergy Esocket" and zen.sample(0.0) is None
    (hw / "energy17_input").write_text("100")                   # unbounded counter went back: sensor reset
    assert zen.sample(1.0) is None and zen.status == "invalid"


def test_power_rejects_absurd_values_and_handles_permission(tmp_path):
    domain = rapl(tmp_path, 0)
    meter = telemetry.EnergyCounter.find(str(tmp_path), str(tmp_path / "x*"))
    meter.sample(0.0)
    (domain / "energy_uj").write_text(str(10 ** 13))
    assert meter.sample(1.0) is None and meter.status == "invalid"
    if os.geteuid() != 0:
        (domain / "energy_uj").chmod(0)
        assert meter.sample(2.0) is None and meter.status == "permission"
    assert telemetry.EnergyCounter.find(str(tmp_path / "no"), str(tmp_path / "no*")).status == "unavailable"


def test_highest_core_frequency(tmp_path):
    for index, khz in enumerate((1_800_000, 4_525_000, 3_100_000)):
        write(tmp_path / f"cpu{index}" / "cpufreq" / "scaling_cur_freq", str(khz))
    assert telemetry.highest_core_mhz(str(tmp_path / "cpu[0-9]*" / "cpufreq" / "scaling_cur_freq")) == 4525
    cpuinfo = tmp_path / "cpuinfo"
    cpuinfo.write_text("cpu MHz\t\t: 3400.000\ncpu MHz\t\t: 4100.5\n")
    assert telemetry.highest_core_mhz(str(tmp_path / "none*"), str(cpuinfo)) == 4100.5
    assert telemetry.highest_core_mhz(str(tmp_path / "none*"), str(tmp_path / "missing")) is None


def test_cpu_temperature_prefers_tdie_over_tctl(tmp_path):
    hw = tmp_path / "hwmon3"
    write(hw / "name", "k10temp")
    for index, label in ((1, "Tctl"), (2, "Tdie"), (3, "Tccd1")):
        write(hw / f"temp{index}_label", label)
        write(hw / f"temp{index}_input", str(60000 + index))
    assert telemetry.find_cpu_temp_input(str(tmp_path / "hwmon*")).endswith("temp2_input")
    (hw / "temp2_label").unlink()
    assert telemetry.find_cpu_temp_input(str(tmp_path / "hwmon*")).endswith("temp1_input")


# ---------------------------------------------------------------- metrics and presentation

def stats(now, **over):
    base = {"valid": True, "cpu_temp_value": 61.4, "cpu_temp_at": now, "cpu_percent": 42.0, "cpu_power_w": 88.6,
            "cpu_power_at": now, "cpu_power_status": "ok", "cpu_freq_max_mhz": 4525.0, "cpu_freq_mhz": 3900.0,
            "ram_percent": 30.0, "gpus": [{"path": "/x", "temp_value": 50.0}]}
    base.update(over)
    return base


def test_gather_never_invents_values():
    now = 100.0
    values = metrics.gather(stats(now, cpu_power_w=None, cpu_power_status="permission", cpu_temp_at=now - 30,
                                  cpu_freq_max_mhz=None, gpus=[]), now)
    assert values.temp is None and values.power is None and values.freq is None and values.gpu_temp is None
    assert set(values.reasons) == {"temp", "power", "freq", "gpu_temp"}
    assert "permission" in values.reasons["power"] and values.usage == 42.0
    assert metrics.gather({"valid": False}, now).usage is None
    assert metrics.gather(stats(now), now, "average").freq == 3900.0


def test_single_field_auto_alternates_and_skips_missing():
    values = metrics.gather(stats(0.0), 0.0)
    shown = {metrics.build_frame(FAMILY["deepcool_ak"], {}, values, t).main for t in (0.0, 5.0, 10.0)}
    assert shown == {"temp", "usage"}
    no_temp = metrics.gather(stats(0.0, cpu_temp_value=None), 0.0)
    frames = [metrics.build_frame(FAMILY["deepcool_ak"], {}, no_temp, t) for t in (0.0, 5.0)]
    assert {f.main for f in frames} == {"usage"} and all(not f.missing for f in frames)


def test_presets_and_custom_field():
    values = metrics.gather(stats(0.0), 0.0)
    ak = FAMILY["deepcool_ak"]
    assert metrics.build_frame(ak, {"dc_preset": "minimal"}, values, 7.0).main == "temp"
    assert metrics.build_frame(ak, {"dc_preset": "performance"}, values, 0.0).main == "usage"
    assert metrics.build_frame(FAMILY["deepcool_ls"], {"dc_preset": "performance"}, values, 0.0).main == "power"
    custom = metrics.build_frame(ak, {"dc_preset": "custom", "dc_main": "usage"}, values, 0.0)
    assert custom.main == "usage" and custom.fields["usage"] == 42.0
    no_power = metrics.gather(stats(0.0, cpu_power_w=None), 0.0)
    ls = metrics.build_frame(FAMILY["deepcool_ls"], {"dc_preset": "custom", "dc_main": "power"}, no_power, 0.0)
    assert ls.main == "temp"                                    # power unavailable: never "0 W"


def test_theme_adapter_follows_the_display_theme():
    values = metrics.gather(stats(0.0), 0.0)
    frame = metrics.build_frame(FAMILY["deepcool_ak"], {"theme": "brother_away"}, values, 0.0)
    assert frame.preset == "guardian" and frame.source_theme == "brother_away" and frame.main == "temp"
    assert metrics.compatibility(FAMILY["deepcool_ak"], "big_media_player")[0] == "unsupported"
    assert metrics.compatibility(FAMILY["deepcool_ak"], "standard")[0] == "adapted"
    assert metrics.compatibility(FAMILY["deepcool_mystique"], "brother_away")[0] == "unsupported"
    for family in FAMILY.values():
        for theme_id in ("standard", "gkrellm", "planet", "old_computer", "brother_away", "kojiro",
                         "big_media_player"):
            state, text = metrics.compatibility(family, theme_id)
            assert state in metrics.COMPATIBILITY and text


def test_fixed_layout_reports_missing_fields_and_units():
    values = metrics.gather(stats(0.0, cpu_power_w=None), 0.0)
    frame = metrics.build_frame(FAMILY["deepcool_ak_pro"], {"dc_temp_unit": "f"}, values, 0.0)
    assert frame.missing == ("power",) and frame.fahrenheit
    assert frame.fields["temp"] == pytest.approx(61.4 * 9 / 5 + 32)
    ag = metrics.build_frame(FAMILY["deepcool_ag"], {"dc_temp_unit": "f", "dc_preset": "minimal"}, values, 0.0)
    assert not ag.fahrenheit and ag.fields["temp"] == pytest.approx(61.4)      # AG: Celsius only


def test_alarm_threshold_and_guardian():
    hot = metrics.gather(stats(0.0, cpu_temp_value=91.0), 0.0)
    warm = metrics.gather(stats(0.0, cpu_temp_value=80.0), 0.0)
    ak = FAMILY["deepcool_ak"]
    assert metrics.build_frame(ak, {}, hot, 0.0).alarm
    assert not metrics.build_frame(ak, {"dc_alarm": False}, hot, 0.0).alarm
    assert metrics.build_frame(ak, {"dc_alarm": False, "dc_preset": "guardian"}, hot, 0.0).alarm
    assert metrics.build_frame(ak, {"dc_alarm_temp": 75}, warm, 0.0).alarm
    assert not metrics.build_frame(FAMILY["deepcool_ak_pro"], {}, hot, 0.0).alarm    # firmware-driven


# ---------------------------------------------------------------- HID driver

@pytest.fixture
def fake_hidraw(tmp_path, monkeypatch):
    node = types.SimpleNamespace(path=tmp_path / "hidraw7", pid=0x0012)
    node.path.write_bytes(b"")
    monkeypatch.setattr(hid, "hidraw_identity", lambda fd: (0x3633, node.pid))
    monkeypatch.setattr(conflicts, "find_conflicts", lambda: [])
    return node


def packets(path, size=64):
    data = path.read_bytes()
    return [data[i:i + size] for i in range(0, len(data), size)]


def test_hid_driver_ak_pro_end_to_end(fake_hidraw):
    driver = drivers.DeepCoolHid(FAMILY["deepcool_ak_pro"], 0x0012, str(fake_hidraw.path), "AK620-DIGITAL-PRO", "1-2")
    info = driver.open()
    assert info.model == "AK620 DIGITAL PRO" and driver.capabilities.output == TELEMETRY
    assert fake_hidraw.path.read_bytes() == b""                       # AK PRO needs no init packet
    values = metrics.gather(stats(0.0), 0.0)
    transfer = driver.present(metrics.build_frame(driver.family, {}, values, 0.0))
    sent = packets(fake_hidraw.path)[0]
    assert transfer.bytes == 64 and sent[:8] == bytes((16, 104, 1, 4, 13, 1, 2, 8))
    assert struct.unpack(">H", sent[8:10])[0] == 89 and struct.unpack(">H", sent[16:18])[0] == 4525
    driver.close()
    assert driver.hid.fd is None


def test_hid_driver_ak_se_and_ld_init(fake_hidraw):
    fake_hidraw.pid = 0x0001
    driver = drivers.DeepCoolHid(FAMILY["deepcool_ak"], 0x0001, str(fake_hidraw.path), "A400", "1-2")
    driver.open()
    driver.present(metrics.build_frame(driver.family, {"dc_preset": "minimal"}, metrics.gather(stats(0.0), 0.0),
                                       0.0))
    data = fake_hidraw.path.read_bytes()
    assert data[:63] == protocols.ak_init(se=True) and data[63:126][0] == 19     # no report id
    driver.close()
    fake_hidraw.path.write_bytes(b"")
    fake_hidraw.pid = 0x000A
    ld = drivers.DeepCoolHid(FAMILY["deepcool_ld"], 0x000A, str(fake_hidraw.path), "LD360", "1-2",
                             {"dc_lead_zeros": False})
    ld.open()
    assert packets(fake_hidraw.path) == list(protocols.ld_init(False))
    ld.close()


def test_hid_driver_refuses_wrong_identity_and_reports_errors(fake_hidraw, monkeypatch, tmp_path):
    driver = drivers.DeepCoolHid(FAMILY["deepcool_ak_pro"], 0x0012, str(fake_hidraw.path), "", "1-2")
    monkeypatch.setattr(hid, "hidraw_identity", lambda fd: (0x046D, 0xC52B))      # node reused by a mouse
    with pytest.raises(DisplayError) as error:
        driver.open()
    assert error.value.kind == "not_found" and fake_hidraw.path.read_bytes() == b""
    missing = drivers.DeepCoolHid(FAMILY["deepcool_ak_pro"], 0x0012, str(tmp_path / "gone"), "", "1-2")
    with pytest.raises(DisplayError) as error:
        missing.open()
    assert error.value.kind == "not_found"
    if os.geteuid() != 0:
        fake_hidraw.path.chmod(0)
        with pytest.raises(DisplayError) as error:
            driver.open()
        assert error.value.kind == PERMISSION


def test_two_copies_cannot_drive_the_same_cooler(fake_hidraw):
    first = drivers.DeepCoolHid(FAMILY["deepcool_ak_pro"], 0x0012, str(fake_hidraw.path), "", "1-2")
    second = drivers.DeepCoolHid(FAMILY["deepcool_ak_pro"], 0x0012, str(fake_hidraw.path), "", "1-2")
    first.open()
    with pytest.raises(DisplayError) as error:
        second.open()
    assert error.value.kind == "busy"
    first.close()
    second.open()
    second.close()


def test_hid_write_errors_map_to_recovery_kinds(fake_hidraw, monkeypatch):
    driver = drivers.DeepCoolHid(FAMILY["deepcool_ak_pro"], 0x0012, str(fake_hidraw.path), "", "1-2")
    driver.open()
    import errno

    def fail(fd, data):
        raise OSError(errno.ENODEV, "No such device")
    monkeypatch.setattr(hid.os, "write", fail)
    with pytest.raises(DisplayError) as error:
        driver.present(metrics.build_frame(driver.family, {}, metrics.gather(stats(0.0), 0.0), 0.0))
    assert error.value.kind == DISCONNECTED
    driver.close()


# ---------------------------------------------------------------- MYSTIQUE driver (fake pyusb)

class FakeEndpoint:
    def __init__(self, address):
        self.bEndpointAddress = address


class FakeInterface(list):
    bInterfaceClass = 0xFF
    bInterfaceNumber = 0


class FakeMystique:
    idVendor, idProduct, bus, address = 0x3633, 0x0009, 3, 9

    def __init__(self):
        self.writes = []
        self.claimed = False
        self.fail_next = None

    def get_active_configuration(self):
        return [FakeInterface(FakeEndpoint(a) for a in (0x01, 0x81, 0x02, 0x82))]

    def is_kernel_driver_active(self, _number):
        return False

    def write(self, endpoint, data, timeout=None):
        if self.fail_next:
            error, self.fail_next = self.fail_next, None
            raise error
        self.writes.append((endpoint, bytes(data)))
        return len(data)

    def read(self, endpoint, size, timeout=None):
        return bytes((0x55, 0x2E)) + bytes(46)


@pytest.fixture
def fake_usb(monkeypatch):
    import sys

    from fakes import USBError, USBTimeoutError
    device = FakeMystique()
    core = types.SimpleNamespace(find=lambda **kw: device if kw.get("idProduct") == 0x0009 else None,
                                 USBError=USBError, USBTimeoutError=USBTimeoutError)
    util = types.SimpleNamespace(claim_interface=lambda dev, n: setattr(dev, "claimed", True),
                                 release_interface=lambda dev, n: setattr(dev, "claimed", False),
                                 dispose_resources=lambda dev: None)
    module = types.SimpleNamespace(core=core, util=util)
    monkeypatch.setitem(sys.modules, "usb", module)
    monkeypatch.setitem(sys.modules, "usb.core", core)
    monkeypatch.setitem(sys.modules, "usb.util", util)
    monkeypatch.setattr(conflicts, "find_conflicts", lambda: [])
    monkeypatch.setattr(drivers.time, "sleep", lambda s: None)
    return device


def test_mystique_init_rotation_and_update(fake_usb):
    driver = drivers.DeepCoolMystique(FAMILY["deepcool_mystique"], 0x0009, 3, 9, "MYSTIQUE", "3-2",
                                      {"dc_rotation": 90})
    driver.open()
    init = [data for endpoint, data in fake_usb.writes if endpoint == 0x01]
    assert [p[2] for p in init[:13]] == [command for command, _payload in protocols.MYSTIQUE_INIT]
    assert init[-1] == protocols.mystique_rotation(90) and fake_usb.claimed
    fake_usb.writes.clear()
    frame = metrics.build_frame(driver.family, {}, metrics.gather(stats(0.0), 0.0), 0.0)
    driver.present(frame)
    status, update = (data for _e, data in fake_usb.writes)
    assert {e for e, _d in fake_usb.writes} == {0x02} and status[2] == 0x10 and update[2] == 0x01
    assert update[3] == 61 and update[6] == 42 and update[9] == 30 and update[14] == 50 and update[21] == 4
    assert all(data[2] not in (0x0F, 0x14) for _e, data in fake_usb.writes)
    driver.close()
    assert not fake_usb.claimed


def test_mystique_errors(fake_usb):
    import errno

    from fakes import USBError
    driver = drivers.DeepCoolMystique(FAMILY["deepcool_mystique"], 0x0009, 3, 9)
    fake_usb.fail_next = USBError("Access denied", errno_=errno.EACCES)
    with pytest.raises(DisplayError) as error:
        driver.open()
    assert error.value.kind == PERMISSION
    driver.open()
    fake_usb.fail_next = USBError("No such device", errno_=errno.ENODEV)
    with pytest.raises(DisplayError) as error:
        driver.present(metrics.build_frame(driver.family, {}, metrics.gather(stats(0.0), 0.0), 0.0))
    assert error.value.kind == DISCONNECTED


# ---------------------------------------------------------------- conflicts

def test_conflicting_programs_and_units(tmp_path, monkeypatch):
    class Proc:
        def __init__(self, pid, name, cmdline):
            self.info = {"pid": pid, "name": name, "cmdline": cmdline}
    monkeypatch.setattr(conflicts.psutil, "process_iter", lambda attrs: [
        Proc(1, "python3", ["/usr/bin/python3", "/usr/local/bin/deepcool-digital-info.py", "-j", "x"]),
        Proc(2, "deepcool-digital-linux", ["deepcool-digital-linux"]), Proc(3, "bash", ["bash"])])
    names = {c["name"] for c in conflicts.running_programs()}
    assert names == {"deepcool-digital-info.py", "deepcool-digital-linux"}
    (tmp_path / "deepcool-temp.service").write_text("[Unit]\n")
    assert [u["name"] for u in conflicts.installed_units((str(tmp_path),))] == ["deepcool-temp.service"]


# ---------------------------------------------------------------- runtime integration

def test_runtime_drives_a_cooler_next_to_a_raster_panel(tmp_path, monkeypatch, fake_hidraw):
    from test_multi_display import FakeBus
    from test_runtime import FakeNotifier, FastRuntime, wait_for

    from bsmd.displays.simulated import SimulatedDisplay
    panel = SimulatedDisplay((480, 320), model="ax206")
    original = runtime.UsbSource.create

    def create(self, settings_):
        if self.display_id == "usb-5-1":
            return panel
        return original(self, settings_)
    monkeypatch.setattr(runtime.UsbSource, "create", create)
    telemetry.SYSTEM_STATS.update(stats(0.0, cpu_temp_at=1e12, cpu_power_at=1e12))
    bus = FakeBus(UsbDevice("5-1", 0x1908, 0x0102, bus=5, address=2),
                  UsbDevice("1-2", 0x3633, 0x0012, product="AK620-DIGITAL-PRO", hidraws=(str(fake_hidraw.path),)))
    config = tmp_path / "settings.json"
    settings.save({"theme": "standard", "displays": {"usb-1-2": {"dc_interval": "0.5"}}}, str(config))
    app = FastRuntime(settings.SettingsStore(str(config)), notifier=FakeNotifier(),
                      status_file=str(tmp_path / "run" / "status.json"), state_directory=str(tmp_path / "s"),
                      scan=bus)
    app.DISCOVERY_EVERY = 0.1
    app.backoff = health.Backoff(base=0.05, cap=0.2, jitter=0)
    import threading
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    try:
        assert wait_for(lambda: len(packets(fake_hidraw.path)) >= 2 and panel.frames >= 1, timeout=10)
        cooler = app.sessions["usb-1-2"]
        assert cooler.theme is None and cooler.link.state == health.HEALTHY
        status = cooler.status()
        assert status["metrics"]["family"] == "deepcool_ak_pro" and status["capabilities"]["output"] == TELEMETRY
        assert all(len(p) == 64 and p[:2] == bytes((16, 104)) for p in packets(fake_hidraw.path))
        assert app.sessions["usb-5-1"].theme is not None                     # the raster panel keeps its theme
    finally:
        app.stop()
        thread.join(5)
        telemetry.SYSTEM_STATS.update({"cpu_temp_at": None, "cpu_power_w": None})


def test_runtime_recovers_a_cooler_that_vanished(tmp_path, monkeypatch, fake_hidraw):
    import errno
    import threading

    from test_multi_display import FakeBus
    from test_runtime import FakeNotifier, FastRuntime, kinds, wait_for
    telemetry.SYSTEM_STATS.update(stats(0.0, cpu_temp_at=1e12, cpu_power_at=1e12))
    fake_hidraw.pid = 0x000A
    bus = FakeBus(UsbDevice("1-2", 0x3633, 0x000A, product="LD360", hidraws=(str(fake_hidraw.path),)))
    config = tmp_path / "settings.json"
    settings.save({"displays": {"usb-1-2": {"dc_interval": "0.5"}}}, str(config))
    app = FastRuntime(settings.SettingsStore(str(config)), notifier=FakeNotifier(),
                      status_file=str(tmp_path / "run" / "status.json"), state_directory=str(tmp_path / "s"),
                      scan=bus)
    app.DISCOVERY_EVERY = 0.1
    app.backoff = health.Backoff(base=0.05, cap=0.2, jitter=0)
    real_write = os.write
    failures = {"left": 0}
    written = []          # a regular file is reopened at offset 0, so record the writes themselves

    def flaky(fd, data):
        if failures["left"]:
            failures["left"] -= 1
            raise OSError(errno.ENODEV, "No such device")
        written.append(bytes(data))
        return real_write(fd, data)
    monkeypatch.setattr(hid.os, "write", flaky)
    thread = threading.Thread(target=app.run, daemon=True)
    thread.start()
    try:
        assert wait_for(lambda: len(written) >= 3, timeout=10)                       # init x2 + data
        failures["left"] = 1
        session = app.sessions["usb-1-2"]
        assert wait_for(lambda: session.recoveries >= 1 and session.link.state == health.HEALTHY, timeout=10)
        before = len(written)
        assert wait_for(lambda: len(written) > before + 2, timeout=10)
        assert "recovered" in kinds(app)
        assert sum(1 for p in written if p[4:6] == bytes((2, 3))) == 2                # LD init again on reopen
    finally:
        app.stop()
        thread.join(5)
        telemetry.SYSTEM_STATS.update({"cpu_temp_at": None, "cpu_power_w": None})


def test_udev_rules_match_the_supported_models_only():
    import re
    path = os.path.join(os.path.dirname(__file__), "..", "usr", "lib", "udev", "rules.d",
                        "70-big-screen-monitor-display.rules")
    text = open(path, encoding="utf-8").read().replace("\\\n", " ")
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "0666" not in text
    hid_rules = [line for line in text.splitlines() if 'SUBSYSTEM=="hidraw"' in line]
    # Exactly two hidraw grants: the DeepCool coolers and the SmartMonitor panel, each by product id.
    assert len(hid_rules) == 2
    deepcool = next(line for line in hid_rules if 'ATTRS{idVendor}=="3633"' in line)
    granted = set(re.search(r'ATTRS\{idProduct\}=="([^"]+)"', deepcool).group(1).split("|"))
    expected = {f"{m.pid:04x}" for m in models.MODELS if m.family and models.FAMILIES[m.family].transport == "hid"}
    assert granted == expected
    panel = next(line for line in hid_rules if 'ATTRS{idVendor}=="0483"' in line)
    assert 'ATTRS{idProduct}=="0065"' in panel and "|" not in panel
    for rule in hid_rules:
        assert 'GROUP="big-screen-monitor"' in rule and 'MODE="0660"' in rule
    mystique = [line for line in text.splitlines() if 'ATTR{idProduct}=="0009"' in line and "MODE=" in line]
    assert len(mystique) == 1 and 'MODE="0660"' in mystique[0]
    rapl_rule = next(line for line in text.splitlines() if 'SUBSYSTEM=="powercap"' in line)
    assert "chmod 0440" in rapl_rule and "chgrp big-screen-monitor" in rapl_rule and "444" not in rapl_rule


# ---------------------------------------------------------------- previews and the interface

def test_preview_draws_every_family():
    from bsmd.displays.deepcool import preview
    values = metrics.Values(temp=54.0, usage=23.0, power=None, freq=4525.0, ram=41.0, gpu_temp=None)
    for family in models.FAMILIES.values():
        frame = metrics.build_frame(family, {"dc_preset": "essentials"}, values, now=0)
        image = preview.render(family, frame, (480, 300), demo=True)
        assert image.size == (480, 300) and image.getbbox() is not None


def test_preview_marks_missing_fixed_fields_dim():
    from bsmd.displays.deepcool import preview
    family = models.FAMILIES["deepcool_ld"]
    full = metrics.Values(temp=50.0, usage=20.0, power=88.0)
    lacking = metrics.Values(temp=50.0, usage=20.0, power=None)
    a = preview.render(family, metrics.build_frame(family, {}, full, 0), (480, 300))
    b = preview.render(family, metrics.build_frame(family, {}, lacking, 0), (480, 300))
    assert a.tobytes() != b.tobytes()           # power drawn lit vs. dimmed with a red caption


@pytest.fixture
def gui_page():
    gi = pytest.importorskip("gi")
    try:
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
    except ValueError:
        pytest.skip("GTK4/libadwaita not installed")
    import sys
    app = os.path.join(os.path.dirname(__file__), "..", "usr", "share", "big-screen-monitor-display")
    if app not in sys.path:
        sys.path.insert(0, app)
    from bsmd import i18n
    from gui import deepcool_page
    i18n.set_language("en")
    yield deepcool_page
    i18n.set_language("auto")


def test_gui_family_and_frame_source(gui_page):
    page = gui_page
    entry = types.SimpleNamespace(id="usb-1-2", candidate=None, status={
        "state": "healthy", "source": {"profile": "deepcool_ak"},
        "metrics": {"family": "deepcool_ak", "fields": {"temp": 70.0, "usage_bar": 40.0}, "main": "temp",
                    "alarm": True, "fahrenheit": False, "missing": [], "preset": "guardian"}})
    family = page.family_of(entry, {})
    assert family.id == "deepcool_ak"
    frame, demo = page.frame_for(family, {}, entry)
    assert not demo and frame.alarm and frame.fields["temp"] == 70.0
    entry.status["state"] = "disconnected"
    frame, demo = page.frame_for(family, {}, entry)
    assert demo                                    # never shows stale numbers as live
    other = types.SimpleNamespace(id="x", candidate=None, status={"source": {"profile": "simulated"}})
    assert page.family_of(other, {}) is None


def test_gui_lists_unsupported_deepcool_devices(gui_page):
    page = gui_page
    from bsmd.displays.discovery import UsbDevice
    rows = page.unsupported_rows([UsbDevice("1-1", 0x3633, 0x0029, product="AK620 G2"),
                                  UsbDevice("1-2", 0x3633, 0x0002, product="AK620"),
                                  UsbDevice("1-3", 0x1234, 0x0029)])
    assert len(rows) == 1
    title, subtitle = rows[0]
    assert title == "AK620 G2 DIGITAL NYX" and "3633:0029" in subtitle and "Nothing is sent" in subtitle


def test_gui_node_access_reports_group(gui_page, tmp_path):
    page = gui_page
    node = tmp_path / "hidraw7"
    node.write_bytes(b"")
    text = page.node_access(str(node))
    assert str(node) in text and "-rw" in text
    assert page.node_access(str(tmp_path / "missing")).startswith(str(tmp_path / "missing") + ":")
    assert page.node_access("") == "No HID node found for this cooler."


def test_compatibility_matrix_covers_every_theme_and_family():
    from bsmd import themes
    for info in themes.available():
        assert info.id in metrics.THEME_ADAPTER, info.id
        for family in models.FAMILIES.values():
            state, text = metrics.compatibility(family, info.id)
            assert state in metrics.COMPATIBILITY and state != "untested" and text, (info.id, family.id)
