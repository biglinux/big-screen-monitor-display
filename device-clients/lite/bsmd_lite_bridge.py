#!/usr/bin/env python3
"""BSMD-lite bridge: sends the computer's telemetry, one line per interval, to a
home-made client over a serial port (ESP32/Arduino on USB), TCP (Raspberry Pi,
another computer) or the terminal. The client may answer with CMD| lines
(media and volume). Protocol: docs/25-protocolo-bsmd-lite.md.

    bsmd_lite_bridge.py --stdout
    bsmd_lite_bridge.py --serial /dev/ttyUSB0 [--baud 115200]
    bsmd_lite_bridge.py --tcp 7720 [--bind 0.0.0.0]     # loopback only by default
"""

import argparse
import os
import signal
import socket
import sys
import threading


def _use_app_package():
    """The bsmd of this repository when run from it, else the installed one."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.abspath(os.path.join(here, "..", "..", "usr", "share", "big-screen-monitor-display")),
                 "/usr/share/big-screen-monitor-display"):
        if os.path.isdir(os.path.join(path, "bsmd")):
            if path in sys.path:
                sys.path.remove(path)
            sys.path.insert(0, path)
            return


_use_app_package()
from bsmd import lite, telemetry  # noqa: E402


class Sampler:
    """Telemetry and media in one thread; senders only read the last line."""

    def __init__(self, interval, gpu_index=None, media=True):
        self.interval = interval
        self.gpu_index = gpu_index
        self.media = media
        self.collector = telemetry.Collector()
        self.collector.want_processes = False
        self.collector.prime()
        self._line = lite.encode(lite.metrics(telemetry.snapshot(), gpu_index))
        self._lock = threading.Lock()

    def sample(self):
        try:
            self.collector.sample_once()
        except Exception as error:  # noqa: BLE001 - a broken sensor must not stop the bridge
            print(f"[telemetry] {error}", file=sys.stderr)
        media = lite.media_text() if self.media else None
        line = lite.encode(lite.metrics(telemetry.snapshot(), self.gpu_index), media)
        with self._lock:
            self._line = line

    def line(self):
        with self._lock:
            return self._line

    def run(self, stop):
        while not stop.is_set():
            self.sample()
            stop.wait(self.interval)


class LineReader:
    """Splits received bytes into lines and runs the CMD| ones (bounded buffer)."""

    def __init__(self, handle=lite.handle_command):
        self.buffer = b""
        self.handle = handle

    def feed(self, data):
        self.buffer += data
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            self.handle(line.decode("ascii", errors="ignore"))
        if len(self.buffer) > 512:          # garbage without a line end
            self.buffer = b""


def serve_stream(read, write, sampler, stop, label):
    """Send lines with ``write`` and read commands with ``read`` until either fails."""
    done = threading.Event()

    def reader():
        lines = LineReader()
        while not (stop.is_set() or done.is_set()):
            try:
                data = read()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            if data is None:            # serial read timeout
                continue
            if not data:
                break
            lines.feed(data)
        done.set()

    threading.Thread(target=reader, daemon=True).start()
    try:
        while not (stop.is_set() or done.is_set()):
            write(sampler.line().encode("cp1252", errors="replace"))
            stop.wait(sampler.interval)
    except OSError as error:
        print(f"[{label}] disconnected: {error}")
    finally:
        done.set()


def run_tcp(sampler, stop, port, bind):
    server = socket.create_server((bind, port), reuse_port=False)
    server.settimeout(0.5)
    print(f"[tcp] listening on {bind}:{port}")
    try:
        while not stop.is_set():
            try:
                conn, addr = server.accept()
            except (socket.timeout, TimeoutError):
                continue
            conn.settimeout(1.0)
            label = f"{addr[0]}:{addr[1]}"
            print(f"[tcp] client {label}")

            def client(conn=conn, label=label):
                with conn:
                    serve_stream(lambda: conn.recv(128), conn.sendall, sampler, stop, label)
            threading.Thread(target=client, daemon=True).start()
    finally:
        server.close()


def run_serial(sampler, stop, port, baud):
    import serial
    while not stop.is_set():
        try:
            with serial.Serial(port, baud, timeout=1.0, write_timeout=2.0) as link:
                print(f"[serial] {port} at {baud} baud")
                serve_stream(lambda: link.read(128) or None, link.write, sampler, stop, port)
        except (OSError, serial.SerialException) as error:
            print(f"[serial] waiting for {port}: {error}")
        stop.wait(2.0)


def main(argv=None):
    parser = argparse.ArgumentParser(description="BSMD-lite bridge (telemetry for home-made displays)")
    out = parser.add_mutually_exclusive_group(required=True)
    out.add_argument("--stdout", action="store_true", help="print the lines (no client)")
    out.add_argument("--serial", metavar="PORT", help="serial port, e.g. /dev/ttyUSB0")
    out.add_argument("--tcp", metavar="PORT", type=int, help="listen for TCP clients on this port")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--bind", default="127.0.0.1",
                        help="TCP address (default loopback; 0.0.0.0 exposes it to the network)")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between lines")
    parser.add_argument("--gpu", type=int, default=None, help="GPU index (default: the one with most VRAM)")
    parser.add_argument("--no-media", action="store_true", help="do not send the playing track")
    parser.add_argument("--count", type=int, default=0, help="with --stdout: stop after N lines")
    args = parser.parse_args(argv)
    interval = max(0.2, args.interval)

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    sampler = Sampler(interval, args.gpu, media=not args.no_media)

    if args.stdout:
        sent = 0
        while not stop.is_set():
            sampler.sample()
            sys.stdout.write(sampler.line())
            sys.stdout.flush()
            sent += 1
            if args.count and sent >= args.count:
                break
            stop.wait(interval)
        return 0
    threading.Thread(target=sampler.run, args=(stop,), daemon=True).start()
    if args.tcp:
        run_tcp(sampler, stop, args.tcp, args.bind)
    else:
        run_serial(sampler, stop, args.serial, args.baud)
    return 0


if __name__ == "__main__":
    sys.exit(main())
