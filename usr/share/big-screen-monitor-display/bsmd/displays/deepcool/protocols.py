"""DeepCool wire formats: pure packet builders (no I/O).

Byte layouts re-implemented from the community reverse-engineering work
(see docs/deepcool/03-protocolos.md for the sources and what each one
confirmed on real hardware):

* Nortank12/deepcool-digital-linux (GPL-3.0) - AK, AG, LS, AK PRO, LD
* raghulkrishna/deepcool-ak620-digital-linux, Algorithm0/deepcool-digital-info (MIT) - AK
* mymymy1303/qt-deepcool, dinoyoshi/serial-lcd-panel-client (MIT) - MYSTIQUE

HID packets are returned exactly as written to the hidraw node: byte 0 is
the report id (16), except for the AK "SE" variants, which send the same
bytes without it.
"""

import struct

REPORT_ID = 16
HID_PACKET = 64

# --------------------------------------------------------------- AK / AG / LS (digit protocol)

MODE_TEMP_C = 19
MODE_TEMP_F = 35
MODE_SECOND = 76          # "usage" on AK/AG, "power" on LS (same byte, firmware labels the field)
MODE_BAR_ANIMATION = 170  # init: status-bar animation


def _digits(value, count):
    """Clamp to ``count`` decimal digits and split them (most significant first)."""
    value = max(0, min(10 ** count - 1, int(round(value))))
    return [value // 10 ** i % 10 for i in reversed(range(count))]


def status_bar(usage):
    """AK/LS ten-segment bar: 1..10 from the CPU usage (never 0: the bar stays visible)."""
    usage = max(0.0, min(100.0, usage or 0.0))
    return 1 if usage < 15 else max(1, min(10, int(usage / 10 + 0.5)))


def ak_init(se=False):
    data = bytearray(HID_PACKET)
    data[0], data[1] = REPORT_ID, MODE_BAR_ANIMATION
    return _se(data, se)


def ak_status(mode, value, usage, alarm, se=False):
    """AK400/500/500S/620 DIGITAL (and SE): one 3-digit field + 10-step bar + alarm.

    ``mode``: MODE_TEMP_C, MODE_TEMP_F or MODE_SECOND (usage %)."""
    data = bytearray(HID_PACKET)
    data[0], data[1] = REPORT_ID, mode
    data[2] = status_bar(usage)
    data[3:6] = bytes(_digits(value, 3))
    data[6] = 1 if alarm else 0
    return _se(data, se)


def ls_status(mode, value, usage, alarm):
    """LS520/LS720 SE DIGITAL: same layout as AK; MODE_SECOND shows power (W)."""
    return ak_status(mode, value, usage, alarm)


def ag_status(mode, value, alarm):
    """AG300/400/500/620 DIGITAL: one 2-digit field (99 when above), alarm at byte 5, no bar."""
    data = bytearray(HID_PACKET)
    data[0], data[1] = REPORT_ID, mode
    data[3:5] = bytes(_digits(min(value, 99), 2))
    data[5] = 1 if alarm else 0
    return bytes(data)


def _se(data, se):
    # "SE" units do not send the report id: every byte moves one position left.
    return bytes(data[1:]) if se else bytes(data)


# --------------------------------------------------------------- AK PRO / LD (structured protocol)

HEADER_AK_PRO = (104, 1, 4, 13, 1, 2, 8)       # AK500 / AK620 DIGITAL PRO: power, temp, usage, frequency
HEADER_AK400_PRO = (104, 1, 2, 11, 1, 2, 5)    # AK400 DIGITAL PRO: power, temp, usage
HEADER_LD = (104, 1, 1, 11, 1, 2, 5)           # LD240 / LD360: power, temp, usage
TERMINATOR = 22


def u16(value):
    return max(0, min(0xFFFF, int(round(value))))


def structured_status(header, power_w, temp, fahrenheit, usage, freq_mhz=None):
    """Fixed header, power u16 BE, unit, temperature f32 BE, usage, [frequency u16 BE],
    checksum (sum of bytes 1.. mod 256) and terminator 22."""
    data = bytearray(HID_PACKET)
    data[0] = REPORT_ID
    data[1:8] = bytes(header)
    data[8:10] = struct.pack(">H", u16(power_w or 0))
    data[10] = 1 if fahrenheit else 0
    data[11:15] = struct.pack(">f", float(round(temp or 0)))
    data[15] = max(0, min(100, int(round(usage or 0))))
    end = 16
    if freq_mhz is not None:
        data[16:18] = struct.pack(">H", u16(freq_mhz))
        end = 18
    data[end] = sum(data[1:end]) % 256
    data[end + 1] = TERMINATOR
    return bytes(data)


def ld_init(leading_zeros=True):
    """LD240/LD360 start-up: two packets (enable, then the leading-zeros display format)."""
    base = bytearray(HID_PACKET)
    base[0:4] = bytes((REPORT_ID, 104, 1, 1))
    first = bytearray(base)
    first[4:9] = bytes((2, 3, 1, 112, 22))
    second = bytearray(first)
    second[5] = 2
    if leading_zeros:
        second[7] = 111
    else:
        second[6], second[7] = 0, 110
    return bytes(first), bytes(second)


# --------------------------------------------------------------- MYSTIQUE (vendor bulk protocol)

MYSTIQUE_PACKET = 48
MYSTIQUE_FOOTER = b"HIDC"
EP_INIT_OUT, EP_INIT_IN = 0x01, 0x81
EP_DATA_OUT, EP_DATA_IN = 0x02, 0x82
CMD_UPDATE = 0x01
CMD_CONFIG = 0x02
CMD_MODE_SWITCH = 0x0A
CMD_STATUS = 0x10
CMD_DEVICE_INFO = 0x12
MACHINE_INFO_MODE = (0xEA, 0x07, 0x02, 0x02, 0x02, 0x27, 0x21, 0x00)
ROTATIONS = {0: 0x00, 90: 0x01, 180: 0x02, 270: 0x03}
# Machine Info init, sent once on endpoint 0x01 (confirmed end-to-end on a MYSTIQUE 240
# by dinoyoshi/serial-lcd-panel-client; individual steps are opaque but required).
MYSTIQUE_INIT = (
    (CMD_DEVICE_INFO, ()),
    (CMD_CONFIG, (0x01, 0x00, 0x00, 0x01, 0x24)),
    (0x03, (0x01,)),
    (0x04, (0x05, 0x00, 0x00, 0x01)),
    (0x07, (0x00, 0x02)),
    (0x08, (0x00, 0x04)),
    (0x05, (0x01, 0x01)),
    (0x0B, ()),
    (0x06, (0x01,)),
    (0x15, (0x2D, 0x2D)),
    (0x16, (0x2D, 0x2D)),
    (0x17, (0x2D, 0x2D)),
    (CMD_MODE_SWITCH, MACHINE_INFO_MODE),
)
# Image upload (0x0F, 0x14, "DCLd" frames) is deliberately absent: it writes to the
# device's persistent memory and, as documented on real hardware, leaves the cooler
# unable to return to Machine Info mode.


def mystique_checksum(packet):
    return sum(packet[:46]) & 0xFFFF


def mystique_packet(command, payload=()):
    payload = bytes(payload)
    if len(payload) > 39:
        raise ValueError("payload too long")
    data = bytearray(MYSTIQUE_PACKET)
    data[0], data[1], data[2] = 0xAA, 0x2E, command
    data[3:3 + len(payload)] = payload
    data[42:46] = MYSTIQUE_FOOTER
    checksum = mystique_checksum(data)
    data[46], data[47] = checksum & 0xFF, checksum >> 8
    return bytes(data)


def mystique_rotation(degrees):
    return mystique_packet(CMD_CONFIG, (0x01, 0x00, ROTATIONS.get(int(degrees), 0x00), 0x01, 0x24))


def mystique_display(cpu_temp, cpu_usage, ram_usage, gpu_temp, cpu_mhz):
    """Machine Info update (endpoint 0x02). Flag bytes are ported verbatim; the
    clock is split as integer GHz, hundredths and two u16 LE copies."""
    def byte(value, high):
        return max(0, min(high, int(round(value or 0))))
    cpu_temp, gpu_temp = byte(cpu_temp, 127), byte(gpu_temp, 127)
    mhz = max(0, int(round(cpu_mhz or 0)))
    whole = mhz // 1000
    hundredths = (mhz % 1000) // 10
    decimal = (hundredths * 100) & 0xFFFF
    byte23 = hundredths if hundredths >= 10 else 0x0A
    payload = bytearray(39)

    def put(offset, value):
        payload[offset - 3] = value & 0xFF
    put(3, cpu_temp)
    put(6, byte(cpu_usage, 100))
    put(9, byte(ram_usage, 100))
    put(11, 0x05 if gpu_temp < 35 else 0x06 if gpu_temp < 38 else 0x09)
    put(12, 0x03)
    put(14, gpu_temp)
    put(15, 0x05)
    put(17, 0x06)
    put(18, 0x0C)
    put(20, 0x07)
    put(21, whole & 0xFF)
    put(23, byte23)
    payload[24 - 3:26 - 3] = struct.pack("<H", decimal)
    payload[27 - 3:29 - 3] = struct.pack("<H", decimal)
    return mystique_packet(CMD_UPDATE, payload)


def is_mystique_response(data):
    return len(data) >= 3 and data[0] == 0x55 and data[1] == 0x2E
