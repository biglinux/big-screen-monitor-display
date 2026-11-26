#!/usr/bin/env python3
"""
Bridge de telemetria entre o Big Screen Monitor Display (bsmd) e o Palm Zire 72
via Bluetooth Serial Port Profile (SPP - UUID 00001101-0000-1000-8000-00805f9b34fb).

Dois modos:
  * cliente (padrão): o ZireMon fica escutando no Palm e a bridge conecta nele.
    O MAC vem de --target ou é detectado entre os dispositivos pareados.
  * --target listen: a bridge registra um perfil SPP no BlueZ e o Palm conecta
    (Menu -> Connection -> Connect BT).

O pacote enviado é uma linha ASCII/cp1252:
  M|cpu%|cpuT|mhz|gpu%|gpuT|ram%|ramU|ramT|disk%|rx|tx|host|media\\n
O Palm responde com linhas "CMD|<ação>\\n" (controle de mídia e volume).
"""

import argparse
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time

SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/org/bsmd/palm/spp"
MEDIA_MAX = 48          # bytes; o campo no Palm tem 52
HOST_MAX = 20           # bytes; o campo no Palm tem 24


def _app_dir_candidates():
    here = os.path.dirname(os.path.abspath(__file__))
    repo = os.path.abspath(os.path.join(here, "..", "..", "..", "usr", "share", "big-screen-monitor-display"))
    return (repo, "/usr/share/big-screen-monitor-display")


# O bsmd do repositório (quando a bridge roda de dentro dele) vence o instalado.
for _path in _app_dir_candidates():
    if os.path.isdir(os.path.join(_path, "bsmd")):
        if _path in sys.path:
            sys.path.remove(_path)
        sys.path.insert(0, _path)
        break

from bsmd import lite, telemetry  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from palm_bt import resolve_palm  # noqa: E402


# --- Pacote -------------------------------------------------------------------

def _clean_text(text, limit):
    """Texto seguro para um campo do pacote: sem '|' nem controles, cabe em ``limit`` bytes cp1252."""
    return lite.clean_text(text, limit)


def media_text(players_cmd=None, timeout=1.0):
    """'Artista - Título' do player MPRIS ativo (playerctl), ou '-'."""
    return _clean_text(lite.media_text(players_cmd, timeout) or "", MEDIA_MAX) or "-"


pick_gpu = lite.pick_gpu


def _int(value):
    return "-" if value is None else f"{value:.0f}"


def _one(value):
    return "-" if value is None else f"{value:.1f}"


def build_packet(snap, media="-", gpu_index=None):
    """Pacote do ZireMon (formato fixo do app C). Os números vêm de ``bsmd.lite.metrics``,
    a mesma leitura da telemetria usada pelos outros clientes; '-' = não medido."""
    m = lite.metrics(snap, gpu_index)
    host = _clean_text(m["host"] or socket.gethostname() or "linux", HOST_MAX) or "linux"
    media = _clean_text(media, MEDIA_MAX) or "-"
    return (
        f"M|{_int(m['cpu'])}|{_int(m['cpu_t'])}|{_int(m['cpu_mhz'])}|"
        f"{_int(m['gpu'])}|{_int(m['gpu_t'])}|"
        f"{_int(m['ram'])}|{_one(m['ram_used'])}|{_one(m['ram_total'])}|"
        f"{_int(m['disk'])}|{_one(m['rx'])}|{_one(m['tx'])}|"
        f"{host}|{media}\n"
    )


def encode_packet(line):
    return line.encode("cp1252", errors="replace")


class Sampler:
    """Coleta telemetria e mídia num só thread; os clientes só leem o último pacote."""

    def __init__(self, interval, gpu_index=None):
        self.interval = interval
        self.gpu_index = gpu_index
        self.collector = telemetry.Collector()
        self.collector.want_processes = False     # a lista de processos não vai para o Palm
        self.collector.prime()
        self._media = "-"
        self._lock = threading.Lock()

    def sample(self):
        try:
            self.collector.sample_once()
        except Exception as exc:  # um sensor quebrado não pode derrubar a bridge
            print(f"[TELEMETRY] erro: {exc}", file=sys.stderr)
        media = media_text()
        with self._lock:
            self._media = media

    def packet(self):
        with self._lock:
            media = self._media
        return build_packet(telemetry.snapshot(), media, self.gpu_index)

    def run(self, stop_ev):
        while not stop_ev.is_set():
            self.sample()
            stop_ev.wait(self.interval)


# --- Comandos vindos do Palm ----------------------------------------------------

COMMANDS = lite.COMMANDS


def handle_palm_command(cmd, run=subprocess.run):
    """Executa uma linha 'CMD|AÇÃO' (só as de ``bsmd.lite.COMMANDS``). Devolve a ação ou None."""
    return lite.handle_command(cmd, run=run)


def rx_loop(sock, stop_ev):
    buf = b""
    while not stop_ev.is_set():
        try:
            chunk = sock.recv(128)
        except (socket.timeout, TimeoutError):
            continue
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            handle_palm_command(line.decode("ascii", errors="ignore"))
        if len(buf) > 512:      # lixo sem fim de linha
            buf = b""


def serve_socket(sock, sampler, stop_ev, label):
    """Envia telemetria por um socket RFCOMM conectado até cair; lê comandos em paralelo."""
    conn_ev = threading.Event()

    def _rx():
        rx_loop(sock, stop_ev)
        conn_ev.set()

    threading.Thread(target=_rx, daemon=True).start()
    try:
        while not (stop_ev.is_set() or conn_ev.is_set()):
            sock.sendall(encode_packet(sampler.packet()))
            stop_ev.wait(sampler.interval)
    except OSError as exc:
        print(f"[SPP] Cliente desconectado ({label}): {exc}")
    finally:
        conn_ev.set()
        try:
            sock.close()
        except OSError:
            pass
    print(f"[SPP] Conexão encerrada ({label})")


# --- Bluetooth ----------------------------------------------------------------------

def parse_sdp_rfcomm_channel(resp):
    """Canal RFCOMM numa resposta SDP: UUID16 0x0003 (RFCOMM) seguido de uint8."""
    m = re.search(rb"\x19\x00\x03\x08(.)", resp, re.DOTALL)
    return m.group(1)[0] if m else None


def discover_spp_channel(mac, timeout=8.0):
    """Consulta SDP (L2CAP PSM 1) pelo UUID 0x1101 e retorna o canal RFCOMM."""
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
    return parse_sdp_rfcomm_channel(resp)


def run_rfcomm_client(mac, sampler, stop_ev):
    """Conecta ativamente via RFCOMM no Palm (descobrindo canal via SDP 0x1101)."""
    while not stop_ev.is_set():
        try:
            ch = discover_spp_channel(mac)
            if ch is None:
                print(f"[SPP] Serviço ZireMon (0x1101) ainda não anunciado em {mac}")
                stop_ev.wait(2.5)
                continue
            print(f"[SPP] Conectando a {mac} canal {ch}...")
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            try:
                sock.settimeout(10.0)
                sock.connect((mac, ch))
            except OSError:
                sock.close()
                raise
            sock.settimeout(1.5)
            print(f"[SPP] Conectado ao ZireMon ({mac} canal {ch})! Enviando telemetria...")
            serve_socket(sock, sampler, stop_ev, mac)
        except OSError as exc:
            print(f"[SPP] Aguardando Palm ({mac}): {exc}")
        stop_ev.wait(2.5)


def run_listen(sampler, stop_ev, channel):
    import dbus
    import dbus.mainloop.glib
    import dbus.service
    from gi.repository import GLib

    class PalmSPPProfile(dbus.service.Object):
        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            print("[SPP] Perfil liberado pelo BlueZ")

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
        def NewConnection(self, device, fd, properties):
            raw_fd = fd.take()
            sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM, fileno=raw_fd)
            if not _is_paired(bus, device):     # só o Palm pareado manda comandos de mídia/volume
                print(f"[SPP] Recusado (não pareado): {device}")
                sock.close()
                return
            print(f"[SPP] Conectado: {device}")
            sock.settimeout(2.0)
            threading.Thread(target=serve_socket, args=(sock, sampler, stop_ev, str(device)), daemon=True).start()

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, device):
            print(f"[SPP] Desconexão solicitada: {device}")

    def _is_paired(bus, device):
        try:
            props = dbus.Interface(bus.get_object("org.bluez", device), "org.freedesktop.DBus.Properties")
            return bool(props.Get("org.bluez.Device1", "Paired"))
        except dbus.DBusException:
            return False

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
    PalmSPPProfile(bus, PROFILE_PATH)

    opts = {
        "Name": "ZireMon Telemetry",
        "Role": "server",
        # link autenticado (exige pareamento); a autorização por conexão fica com o
        # teste de Paired em NewConnection, que dispensa um agente BlueZ perguntando a cada vez
        "RequireAuthentication": True,
        "RequireAuthorization": False,
    }
    if channel > 0:
        opts["Channel"] = dbus.UInt16(channel)
    manager.RegisterProfile(PROFILE_PATH, SPP_UUID, opts)
    print(f"[SPP] Serviço 'ZireMon Telemetry' registrado (UUID={SPP_UUID})")
    print("[SPP] Aguardando conexão Bluetooth do Palm...")

    loop = GLib.MainLoop()
    GLib.timeout_add(250, lambda: (loop.quit() if stop_ev.is_set() else True))
    try:
        loop.run()
    finally:
        try:
            manager.UnregisterProfile(PROFILE_PATH)
        except Exception:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bridge bsmd -> Palm (ZireMon) via Bluetooth SPP")
    parser.add_argument("--interval", type=float, default=1.0, help="Intervalo de envio em segundos (padrão: 1.0)")
    parser.add_argument("--channel", type=int, default=0, help="Canal RFCOMM no modo listen (0 = automático)")
    parser.add_argument("--target", default="",
                        help="MAC do Palm para conectar (padrão: detecta o Palm pareado) "
                             "ou 'listen' para modo servidor")
    parser.add_argument("--gpu", type=int, default=None,
                        help="Índice da GPU mostrada (padrão: a de mais VRAM)")
    parser.add_argument("--stdout", action="store_true", help="Apenas imprime pacotes no terminal (modo teste)")
    args = parser.parse_args(argv)
    args.interval = max(0.2, args.interval)

    stop_ev = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_ev.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_ev.set())

    target = None if args.stdout or args.target == "listen" else resolve_palm(args.target)

    sampler = Sampler(args.interval, args.gpu)
    time.sleep(0.25)

    if args.stdout:
        try:
            while not stop_ev.is_set():
                sampler.sample()
                sys.stdout.write(sampler.packet())
                sys.stdout.flush()
                stop_ev.wait(args.interval)
        except BrokenPipeError:
            pass
        return

    threading.Thread(target=sampler.run, args=(stop_ev,), daemon=True).start()
    if target:
        run_rfcomm_client(target, sampler, stop_ev)
    else:
        run_listen(sampler, stop_ev, args.channel)


if __name__ == "__main__":
    main()
