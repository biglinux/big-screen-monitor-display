"""GPU telemetry for every vendor: amdgpu sysfs, NVIDIA through NVML, Intel clock,
and "—" (never a fake 0 %) when the driver does not report usage."""

import ctypes

import pytest

from bsmd import compact, dashboard, nvidia, runtime, settings, telemetry, themes


# ------------------------------------------------------------------ NVML (fake library)

class FakeNVML:
    """Stands in for libnvidia-ml: each call writes its result through the byref() argument."""

    def __init__(self, init_code=0, known=("0000:01:00.0",)):
        self.init_code, self.known, self.calls = init_code, set(known), []

    def nvmlInit_v2(self):
        self.calls.append("init")
        return self.init_code

    def nvmlDeviceGetHandleByPciBusId_v2(self, bus, handle):
        if bus.decode() not in self.known:
            return 3                                    # NVML_ERROR_NOT_FOUND
        handle._obj.value = 1234
        return 0

    def nvmlDeviceGetUtilizationRates(self, handle, util):
        util._obj.gpu, util._obj.memory = 87, 40
        return 0

    def nvmlDeviceGetTemperature(self, handle, sensor, temp):
        temp._obj.value = 71
        return 0

    def nvmlDeviceGetMemoryInfo(self, handle, memory):
        memory._obj.total, memory._obj.used = 12 * 1024 ** 3, 3 * 1024 ** 3
        return 0

    def nvmlDeviceGetPowerUsage(self, handle, power):
        power._obj.value = 215500                      # milliwatts
        return 0

    def nvmlDeviceGetClockInfo(self, handle, kind, clock):
        clock._obj.value = 2520
        return 0

    def nvmlDeviceGetEncoderUtilization(self, handle, enc, period):
        return 2                                        # NVML_ERROR_NOT_SUPPORTED: left out


def test_nvml_reads_one_card():
    lib = FakeNVML()
    data = nvidia.NVML(loader=lambda: lib).read("0000:01:00.0")
    assert data == {"percent": 87.0, "temp_value": 71.0, "mem_used_mb": 3072, "mem_total_mb": 12288,
                    "power_w": 215.5, "clock_mhz": 2520}
    assert nvidia.NVML(loader=lambda: lib).read("0000:02:00.0") is None


@pytest.mark.parametrize("loader", [
    lambda: (_ for _ in ()).throw(OSError("libnvidia-ml.so.1: cannot open shared object file")),
    lambda: FakeNVML(init_code=9),                   # NVML_ERROR_DRIVER_NOT_LOADED
])
def test_nvml_missing_is_quiet_and_tried_once(loader):
    calls = []

    def counting():
        calls.append(1)
        return loader()
    session = nvidia.NVML(loader=counting)
    assert session.read("0000:01:00.0") is None
    assert session.read("0000:01:00.0") is None
    assert len(calls) == 1


def test_nvml_real_structures_match_the_c_layout():
    assert ctypes.sizeof(nvidia._Utilization) == 8
    assert ctypes.sizeof(nvidia._Memory) == 24


# ------------------------------------------------------------------ sysfs (fake tree)

def make_card(root, name, vendor_id, slot, files=()):
    card = root / name
    (card / "device").mkdir(parents=True)
    (card / "device" / "uevent").write_text(f"DRIVER=x\nPCI_ID={vendor_id}:1234\nPCI_SLOT_NAME={slot}\n")
    for rel, value in files:
        path = card / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)
    return card


def test_find_gpus_records_vendor_and_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "_lspci_name", lambda slot: "")
    make_card(tmp_path, "card0", "1002", "0000:03:00.0")
    make_card(tmp_path, "card1", "10DE", "0000:01:00.0")
    make_card(tmp_path, "card2", "8086", "0000:00:02.0")
    gpus = telemetry.find_gpus(str(tmp_path / "card[0-9]"))
    assert [(g["name"], g["vendor"], g["pci_slot"]) for g in gpus] == [
        ("AMD Radeon", "amd", "0000:03:00.0"), ("NVIDIA", "nvidia", "0000:01:00.0"),
        ("Intel", "intel", "0000:00:02.0")]
    assert not any(g["usage_known"] for g in gpus)


def sample(gpu):
    collector = telemetry.Collector()
    collector._sample_gpu(gpu, 0)
    return gpu


def test_amd_usage_is_known(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "_lspci_name", lambda slot: "")
    make_card(tmp_path, "card0", "1002", "0000:03:00.0", [("device/gpu_busy_percent", "42\n")])
    gpu = sample(telemetry.find_gpus(str(tmp_path / "card[0-9]"))[0])
    assert gpu["usage_known"] and gpu["percent"] == 42.0
    assert telemetry.gpu_percent_text(gpu) == "42%"


def test_nvidia_uses_nvml(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "_lspci_name", lambda slot: "")
    monkeypatch.setattr(nvidia, "_shared", nvidia.NVML(loader=FakeNVML))
    make_card(tmp_path, "card1", "10de", "0000:01:00.0")
    gpu = sample(telemetry.find_gpus(str(tmp_path / "card[0-9]"))[0])
    assert gpu["usage_known"] and gpu["percent"] == 87.0
    assert gpu["temp_value"] == 71.0 and gpu["temp"] == "71°C"
    assert gpu["mem_total_mb"] == 12288 and gpu["clock_mhz"] == 2520 and gpu["ppt"] == "215.5W"


def test_nvidia_without_nvml_stays_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "_lspci_name", lambda slot: "")
    monkeypatch.setattr(nvidia, "_shared", nvidia.NVML(loader=lambda: FakeNVML(init_code=9)))
    make_card(tmp_path, "card1", "10de", "0000:01:00.0")
    gpu = sample(telemetry.find_gpus(str(tmp_path / "card[0-9]"))[0])
    assert not gpu["usage_known"] and gpu["temp_value"] is None
    assert telemetry.gpu_percent_text(gpu) == "—"


@pytest.mark.parametrize("rel", ["gt/gt0/rps_act_freq_mhz", "device/tile0/gt0/freq0/act_freq"])
def test_intel_clock_i915_and_xe(tmp_path, monkeypatch, rel):
    monkeypatch.setattr(telemetry, "_lspci_name", lambda slot: "")
    make_card(tmp_path, "card0", "8086", "0000:00:02.0", [(rel, "1300\n")])
    gpu = sample(telemetry.find_gpus(str(tmp_path / "card[0-9]"))[0])
    assert gpu["clock_mhz"] == 1300 and not gpu["usage_known"]


# ------------------------------------------------------------------ what the themes show

def gpu(known, percent=63.0):
    entry = telemetry._empty_gpu("/sys/class/drm/card0", "Test GPU")
    entry.update(percent=percent if known else 0.0, usage_known=known, temp_value=55, temp="55°C")
    return entry


@pytest.fixture
def with_gpu(monkeypatch):
    def install(entry):
        monkeypatch.setitem(telemetry.SYSTEM_STATS, "gpus", [entry])
        monkeypatch.setitem(telemetry.SYSTEM_STATS, "active_gpu_idx", 0)
    return install


def test_dashboard_row_dash_when_unknown(with_gpu):
    with_gpu(gpu(False))
    row = next(r for r in dashboard.metric_rows(settings.defaults())[0] if r["key"] == "gpu")
    assert row["value"] == "—" and row["percent"] is None           # no bar drawn
    with_gpu(gpu(True))
    row = next(r for r in dashboard.metric_rows(settings.defaults())[0] if r["key"] == "gpu")
    assert row["value"] == "63%" and row["percent"] == 63.0


def test_compact_metrics(with_gpu):
    assert ("GPU", None, "gpu") in compact._metrics({"gpus": [gpu(False)]})
    assert ("GPU", 63.0, "gpu") in compact._metrics({"gpus": [gpu(True)]})


THEME_IDS = [info.id for info in themes.available()]


@pytest.mark.parametrize("known", [False, True])
@pytest.mark.parametrize("theme", THEME_IDS)
def test_every_theme_renders_with_known_and_unknown_gpu(theme, known, with_gpu):
    with_gpu(gpu(known))
    values = settings.defaults()
    values.update(theme=theme)
    values, problems = settings.validate(values)
    assert not problems
    for size in ((480, 320), (320, 480)):
        image = themes.create(theme, runtime.RenderContext(preview=True)).render(*size, values, None)
        assert image.size == size
