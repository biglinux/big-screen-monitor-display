#!/usr/bin/env python3
"""
Bridge de telemetria entre o Big Screen Monitor Display (bsmd) e o Palm Zire 72
via Bluetooth Serial Port Profile (SPP - UUID 00001101-0000-1000-8000-00805f9b34fb).
"""

import argparse
import json
import os
import re
import signal
import socket
import struct
import sys
import threading
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

BSMD_PATH = "/usr/share/big-screen-monitor-display"
STATUS_JSON = "/run/big-screen-monitor-display/status.json"
SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/org/bsmd/palm/spp"

if os.path.isdir(BSMD_PATH) and BSMD_PATH not in sys.path:
    sys.path.insert(0, BSMD_PATH)

from bsmd import telemetry  # noqa: E402


def _safe_int(val, default=0):
    try:
        if val is None:
            return default
        if isinstance(val, str):
            digits = "".join(c for c in val if c.isdigit() or c == "." or c == "-")
            return int(float(digits)) if digits else default
        return int(round(float(val)))
    except Exception:
        return default


def _safe_float(val, default=0.0):
    try:
        return float(val) if val is not None else default
    except Exception:
        return default


def _read_media():
    try:
        with open(STATUS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        media = data.get("media")
        if isinstance(media, dict):
            title = (media.get("title") or "").strip()
            artist = (media.get("artist") or "").strip()
            if artist and title:
                text = f"{artist} - {title}"
            else:
                text = title or artist
            return text.replace("|", "/").replace("\n", " ")[:48]
    except Exception:
        pass
    return "-"


def build_packet(snap):
    cpu_pct = _safe_int(snap.get("cpu_percent"))
    cpu_temp = _safe_int(snap.get("cpu_temp_value") or snap.get("cpu_temp"))
    cpu_mhz = _safe_int(snap.get("cpu_freq_mhz"))

    gpus = snap.get("gpus") or []
    gpu0 = gpus[0] if gpus and isinstance(gpus[0], dict) else {}
    gpu_pct = _safe_int(gpu0.get("usage") or gpu0.get("gpu_percent"))
    gpu_temp = _safe_int(gpu0.get("temp") or gpu0.get("temperature"))

    ram_pct = _safe_int(snap.get("ram_percent"))
    ram_used_gb = _safe_float(snap.get("ram_used_mb")) / 1024.0
    ram_tot_gb = _safe_float(snap.get("ram_total_mb")) / 1024.0

    disk_pct = _safe_int(snap.get("disk_percent"))
    rx_mbps = _safe_float(snap.get("net_rx_mbps"))
    tx_mbps = _safe_float(snap.get("net_tx_mbps"))

    host = (snap.get("hostname") or socket.gethostname() or "linux").replace("|", "-")[:20]
    media = _read_media()

    return (
        f"M|{cpu_pct}|{cpu_temp}|{cpu_mhz}|"
        f"{gpu_pct}|{gpu_temp}|"
        f"{ram_pct}|{ram_used_gb:.1f}|{ram_tot_gb:.1f}|"
        f"{disk_pct}|{rx_mbps:.1f}|{tx_mbps:.1f}|"
        f"{host}|{media}\n"
    )


class PalmSPPProfile(dbus.service.Object):
    def __init__(self, bus, path, interval=1.0):
        super().__init__(bus, path)
        self.interval = interval
        self.clients = set()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()

    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        print("[SPP] Profile released")
        self.stop_event.set()

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, device, fd, properties):
        raw_fd = fd.take()
        print(f"[SPP] Conectado: {device} (fd={raw_fd})")
        t = threading.Thread(
            target=self._client_loop,
            args=(str(device), raw_fd),
            daemon=True,
        )
        t.start()

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, device):
        print(f"[SPP] Desconexão solicitada: {device}")

    def _client_loop(self, device, raw_fd):
        sock = socket.fromfd(raw_fd, socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        os.close(raw_fd)
        sock.settimeout(2.0)
        try:
            while not self.stop_event.is_set():
                snap = telemetry.snapshot()
                line = build_packet(snap)
                sock.sendall(line.encode("ascii", errors="replace"))
                time.sleep(self.interval)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
            print(f"[SPP] Cliente desconectado ({device}): {exc}")
        finally:
            try:
                sock.close()
            except Exception:
                pass


def discover_spp_channel(mac, timeout=8.0):
    """Consulta SDP L2CAP PSM 1 pelo UUID 0x1101 e retorna o canal RFCOMM."""
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_L2CAP)
    s.settimeout(timeout)
    try:
        s.connect((mac, 1))
        pdu_body = bytes.fromhex("3503191101ffff35050a0000ffff00")
        pkt = struct.pack(">BHH", 0x06, 0x0002, len(pdu_body)) + pdu_body
        s.sendall(pkt)
        resp = s.recv(4096)
    finally:
        s.close()
    m = re.search(rb"\x19\x00\x03\x08(.)", resp, re.DOTALL)
    return m.group(1)[0] if m else None


def run_rfcomm_client(mac, interval, stop_ev):
    """Conecta ativamente via RFCOMM no Palm (descobrindo canal via SDP 0x1101)."""
    while not stop_ev.is_set():
        ch = None
        try:
            ch = discover_spp_channel(mac)
            if ch is None:
                print(f"[SPP] Serviço ZireMon (0x1101) ainda não anunciado em {mac}")
                stop_ev.wait(2.5)
                continue

            print(f"[SPP] Conectando a {mac} canal {ch}...")
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            sock.settimeout(10.0)
            sock.connect((mac, ch))
            sock.settimeout(3.0)
            print(f"[SPP] Conectado ao ZireMon ({mac} canal {ch})! Enviando telemetria...")
            try:
                while not stop_ev.is_set():
                    line = build_packet(telemetry.snapshot())
                    sock.sendall(line.encode("ascii", errors="replace"))
                    stop_ev.wait(interval)
            finally:
                try:
                    sock.close()
                except Exception:
                    pass
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError) as exc:
            print(f"[SPP] Aguardando Palm ({mac}): {exc}")
            stop_ev.wait(2.5)


def main():
    parser = argparse.ArgumentParser(description="Bridge bsmd -> Palm Zire 72 via Bluetooth SPP")
    parser.add_argument("--interval", type=float, default=1.0, help="Intervalo de envio em segundos (padrão: 1.0)")
    parser.add_argument("--channel", type=int, default=0, help="Canal RFCOMM no modo listen (0 = automático)")
    parser.add_argument("--target", default="00:07:E0:47:3B:EC", help="MAC do Palm para conectar ativamente (ou 'listen' para modo servidor)")
    parser.add_argument("--stdout", action="store_true", help="Apenas imprime pacotes no terminal (modo teste)")
    args = parser.parse_args()

    collector = telemetry.Collector()
    collector.prime()
    time.sleep(0.25)

    def _collector_loop(stop_ev):
        while not stop_ev.is_set():
            try:
                collector.sample_once()
            except Exception as exc:
                print(f"[TELEMETRY] erro: {exc}", file=sys.stderr)
            stop_ev.wait(args.interval)

    if args.stdout:
        stop_ev = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop_ev.set())
        try:
            while not stop_ev.is_set():
                collector.sample_once()
                print(build_packet(telemetry.snapshot()), end="", flush=True)
                stop_ev.wait(args.interval)
        except BrokenPipeError:
            pass
        return

    if args.target != "listen":
        stop_ev = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop_ev.set())
        signal.signal(signal.SIGTERM, lambda *_: stop_ev.set())
        threading.Thread(target=_collector_loop, args=(stop_ev,), daemon=True).start()
        run_rfcomm_client(args.target, args.interval, stop_ev)
        return

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    manager = dbus.Interface(
        bus.get_object("org.bluez", "/org/bluez"),
        "org.bluez.ProfileManager1",
    )

    profile = PalmSPPProfile(bus, PROFILE_PATH, interval=args.interval)

    opts = {
        "Name": "ZireMon Telemetry",
        "Role": "client" if args.target != "listen" else "server",
        "RequireAuthentication": False,
        "RequireAuthorization": False,
        "AutoConnect": True,
    }
    if args.channel > 0:
        opts["Channel"] = dbus.UInt16(args.channel)
    manager.RegisterProfile(PROFILE_PATH, SPP_UUID, opts)
    print(f"[SPP] Serviço 'ZireMon Telemetry' registrado (UUID={SPP_UUID}, role={opts['Role']})")

    t_col = threading.Thread(target=_collector_loop, args=(profile.stop_event,), daemon=True)
    t_col.start()

    if args.target != "listen":
        dev_path = "/org/bluez/hci0/dev_" + args.target.replace(":", "_").upper()

        def _connect_loop():
            dev = dbus.Interface(bus.get_object("org.bluez", dev_path), "org.bluez.Device1")
            while not profile.stop_event.is_set():
                try:
                    print(f"[SPP] Tentando conectar ao Palm ({args.target})...")
                    dev.ConnectProfile(SPP_UUID)
                    print("[SPP] ConnectProfile aceito!")
                    while not profile.stop_event.is_set():
                        profile.stop_event.wait(3.0)
                except dbus.DBusException as exc:
                    msg = str(exc)
                    if "AlreadyConnected" in msg:
                        profile.stop_event.wait(3.0)
                    else:
                        print(f"[SPP] Aguardando ZireMon abrir no Palm ({msg.splitlines()[-1]})")
                        profile.stop_event.wait(2.5)

        threading.Thread(target=_connect_loop, daemon=True).start()
    else:
        print("[SPP] Aguardando conexão Bluetooth do Palm Zire 72...")

    loop = GLib.MainLoop()

    def _shutdown(*_):
        profile.stop_event.set()
        loop.quit()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run()
    finally:
        try:
            manager.UnregisterProfile(PROFILE_PATH)
        except Exception:
            pass


if __name__ == "__main__":
    main()
