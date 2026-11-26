#!/usr/bin/env python3
"""Reference BSMD-lite client: connects to the bridge over TCP and draws the
figures as bars in a terminal (a Raspberry Pi with a small screen, an SSH
session). Only the standard library: it is also the parser to port to C.

    lite_client.py 192.168.0.10 7720
    lite_client.py 127.0.0.1 7720 --once      # one frame and exit (tests)
"""

import argparse
import socket
import sys

VERSION = "BSMD1"
BAR = 24


def parse(line):
    """{key: str} for a BSMD1 line, None otherwise; unknown keys are kept (and ignored)."""
    parts = line.rstrip("\r\n").split("|")
    if parts[0] != VERSION:
        return None
    fields = {}
    for part in parts[1:]:
        key, sep, value = part.partition("=")
        if sep and key:
            fields[key] = value
    return fields


def number(fields, key):
    """float, or None when absent or "-" (not measured)."""
    try:
        return float(fields.get(key, "-"))
    except ValueError:
        return None


def bar(percent):
    if percent is None:
        return "·" * BAR + "    —"
    filled = round(max(0.0, min(100.0, percent)) / 100 * BAR)
    return "█" * filled + "░" * (BAR - filled) + f" {percent:3.0f}%"


def temp(fields, key):
    value = number(fields, key)
    return "" if value is None else f"  {value:.0f}°C"


def frame(fields):
    lines = [f"  {fields.get('host', '-')}", ""]
    lines.append(f"  CPU  {bar(number(fields, 'cpu'))}{temp(fields, 'cpu_t')}")
    lines.append(f"  GPU  {bar(number(fields, 'gpu'))}{temp(fields, 'gpu_t')}")
    ram_gb = f"{fields.get('ram_used', '-')}/{fields.get('ram_total', '-')} GB"
    lines.append(f"  RAM  {bar(number(fields, 'ram'))}  {ram_gb}")
    lines.append(f"  DISK {bar(number(fields, 'disk'))}")
    lines.append(f"  NET  ↓ {fields.get('rx', '-')} Mbps  ↑ {fields.get('tx', '-')} Mbps")
    if fields.get("media", "-") != "-":
        lines.append(f"  ♪    {fields['media']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="BSMD-lite terminal client")
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--once", action="store_true", help="draw one frame and exit")
    args = parser.parse_args(argv)
    with socket.create_connection((args.host, args.port), timeout=10) as conn:
        stream = conn.makefile("r", encoding="cp1252", newline="\n")
        for line in stream:
            fields = parse(line)
            if fields is None:
                continue
            if args.once:
                print(frame(fields))
                return 0
            sys.stdout.write("\033[H\033[2J" + frame(fields) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
