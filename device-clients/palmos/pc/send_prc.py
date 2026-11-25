#!/usr/bin/env python3
"""
Envia um arquivo (.prc / .pdb) para o Palm Zire 72 via Bluetooth OBEX Object Push
usando o obexd da sessão (org.bluez.obex).
"""

import argparse
import os
import sys

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

DEFAULT_MAC = "00:07:E0:47:3B:EC"


def send_file(mac, filepath):
    filepath = os.path.abspath(filepath)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Arquivo não encontrado: {filepath}")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    client = dbus.Interface(
        bus.get_object("org.bluez.obex", "/org/bluez/obex"),
        "org.bluez.obex.Client1",
    )

    print(f"[OBEX] Criando sessão OPP com {mac}...")
    session_path = client.CreateSession(mac, {"Target": "opp"})
    opp = dbus.Interface(
        bus.get_object("org.bluez.obex", session_path),
        "org.bluez.obex.ObjectPush1",
    )

    loop = GLib.MainLoop()
    result = {"status": "unknown", "error": None}

    transfer_path, props = opp.SendFile(filepath)
    print(f"[OBEX] Enviando {os.path.basename(filepath)} ({props.get('Size', '?')} bytes)...")
    print("[OBEX] Confirme 'Yes' na tela do Palm Zire 72 se aparecer o aviso de recebimento.")

    def on_props_changed(interface, changed, invalidated, path=None):
        if path != transfer_path:
            return
        if "Status" in changed:
            st = str(changed["Status"])
            print(f"[OBEX] Status: {st}")
            if st in ("complete", "error"):
                result["status"] = st
                loop.quit()

    bus.add_signal_receiver(
        on_props_changed,
        dbus_interface="org.freedesktop.DBus.Properties",
        signal_name="PropertiesChanged",
        path_keyword="path",
    )

    GLib.timeout_add_seconds(60, loop.quit)
    loop.run()

    try:
        client.RemoveSession(session_path)
    except Exception:
        pass

    if result["status"] != "complete":
        raise RuntimeError(f"Transferência OBEX não completou (status={result['status']})")
    print("[OBEX] Enviado com sucesso!")


def main():
    parser = argparse.ArgumentParser(description="Envia .prc/.pdb para o Palm Zire 72 via Bluetooth OBEX")
    parser.add_argument("file", help="Caminho do arquivo .prc ou .pdb")
    parser.add_argument("--mac", default=DEFAULT_MAC, help=f"Endereço MAC Bluetooth do Palm (padrão: {DEFAULT_MAC})")
    args = parser.parse_args()

    try:
        send_file(args.mac, args.file)
    except Exception as exc:
        print(f"[OBEX] Erro: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
