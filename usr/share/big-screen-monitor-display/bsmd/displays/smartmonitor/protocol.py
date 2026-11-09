"""Wire format of the 3.5" "SmartMonitor" HID panel (llhmi.com / llTechCo, 0483:0065).

The panel is a full-speed HID device with one vendor collection (usage page
0xFF00, 64-byte reports, no report ids). It has no framebuffer: it stores a
compiled theme (``img.dat``, see :mod:`.imgdat`) in flash and draws it
itself, while the host pushes numbers on numbered channels.

Reports written to ``/dev/hidrawN`` carry a leading report-id byte (0)
followed by the 64-byte payload, whose first byte is the report type:

======  ========  ==========================================================
0x01    command   ``0x01 "reset\\0"`` (leave the running theme, before YMODEM)
0x02    sensor    ``[0x02][n]`` + n x ``[channel][u16 BE value]``, n <= 20
0x03    datetime  ``[03][01][15][yy][mm][dd][hh][mi][ss][bl_timeout][bright]``
======  ========  ==========================================================

``bl_timeout`` is in 1/8 s (below 8 disables blanking); ``bright`` is 1..100
and is the one field that works whatever theme is loaded.

Theme upload is YMODEM over the same reports: ``reset``, ``"ymodem\\0"``
(ACK ``06 43``), block 0 with ``"img.dat\\0<size>\\0"`` (ACK ``06 43``), 1 KiB
STX blocks padded with 0x1A (ACK ``06 43``, the last one ``06 00``), EOT
(ACK ``06 43``) and an empty block 0 (ACK ``06 00``). Each block is
``[type][seq][~seq] + data + CRC16-XMODEM`` cut into 64-byte reports.

Protocol references: James Buren's ``hidss`` (MIT,
gitlab.com/braewoods/usb-smart-screen), the Starfleet project's panel driver
(MIT, github.com/pauloesterwitz/Starfleet) and smartmonitor_hid_lib /
turing-smart-screen-python-HIDdev2 (GPL-3.0, github.com/Agentry433).
"""

VENDOR = 0x0483
PRODUCT = 0x0065
REPORT = 64
MAX_PAIRS = 20

CMD = 0x01
SENSOR = 0x02
DATETIME = 0x03
RESET = b"\x01reset\x00"
YMODEM = b"ymodem\x00"

SOH, STX, EOT, ACK, NAK = 0x01, 0x02, 0x04, 0x06, 0x15
ACK_MORE = 0x43          # "C": send the next block
ACK_DONE = 0x00          # last data block / end of session
BLOCK = 1024
THEME_MIN, THEME_MAX = 4096, 4 * 1024 * 1024


def report(payload):
    """One hidraw write: report id 0 + the payload padded to 64 bytes."""
    payload = bytes(payload)
    if len(payload) > REPORT:
        raise ValueError(f"payload of {len(payload)} bytes does not fit one report")
    return b"\x00" + payload.ljust(REPORT, b"\x00")


def clamp_value(value):
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(0xFFFF, number))


def sensor_reports(values):
    """Reports for ``{channel: value}`` (any number of channels, 20 per report)."""
    pairs = sorted((int(channel), clamp_value(value)) for channel, value in values.items()
                   if 0 < int(channel) <= 0xFF)
    reports = []
    for start in range(0, len(pairs), MAX_PAIRS):
        chunk = pairs[start:start + MAX_PAIRS]
        payload = bytearray([SENSOR, len(chunk)])
        for channel, value in chunk:
            payload += bytes([channel]) + value.to_bytes(2, "big")
        reports.append(report(payload))
    return reports


def datetime_report(when, brightness=100, timeout=0):
    """Clock and backlight. ``brightness`` 0..100 (the panel's minimum is 1)."""
    payload = bytes([DATETIME, 0x01, 0x15, max(0, min(255, when.year - 2000)), when.month, when.day, when.hour,
                     when.minute, when.second, max(0, min(255, int(timeout))),
                     max(1, min(100, round(brightness)))])
    return report(payload)


def crc16_xmodem(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def ymodem_block(block_type, seq, data, size):
    """Reports carrying one YMODEM block (``size`` = 128 for SOH, 1024 for STX)."""
    body = bytes(data)[:size].ljust(size, b"\x00" if block_type == SOH else b"\x1a")
    block = bytes([block_type, seq & 0xFF, (~seq) & 0xFF]) + body + crc16_xmodem(body).to_bytes(2, "big")
    return [report(block[offset:offset + REPORT]) for offset in range(0, len(block), REPORT)]


def metadata_block(name, size):
    payload = name.encode("ascii") + b"\x00"
    if size > 0:
        payload += str(size).encode("ascii") + b"\x00"
    return ymodem_block(SOH, 0, payload, 128)


def data_blocks(data):
    """``(reports, expected_ack)`` for every 1 KiB block of ``data``."""
    total = max(1, (len(data) + BLOCK - 1) // BLOCK)
    for index in range(total):
        chunk = data[index * BLOCK:(index + 1) * BLOCK]
        yield ymodem_block(STX, index + 1, chunk, BLOCK), (ACK_DONE if index == total - 1 else ACK_MORE)


def parse_ack(data):
    """``(kind, value)`` of an input report: kind is "ack", "nak" or None."""
    if not data:
        return None, None
    if data[0] == ACK:
        return "ack", data[1] if len(data) > 1 else None
    if data[0] == NAK:
        return "nak", None
    return None, None
