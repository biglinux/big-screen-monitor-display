"""Descoberta do Palm pareado no BlueZ, compartilhada pela bridge e pelo send_prc."""

import re

PALM_NAME = re.compile(r"palm|zire|tungsten|treo|centro|lifedrive", re.IGNORECASE)


def paired_devices():
    """[(mac, nome)] pareados no BlueZ; vazio se o D-Bus/BlueZ não estiver disponível."""
    try:
        import dbus
        bus = dbus.SystemBus()
        objects = dbus.Interface(bus.get_object("org.bluez", "/"),
                                 "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
    except Exception:
        return []
    found = []
    for ifaces in objects.values():
        dev = ifaces.get("org.bluez.Device1")
        if dev and dev.get("Paired"):
            found.append((str(dev.get("Address", "")), str(dev.get("Alias") or dev.get("Name") or "")))
    return found


def pick_palm(devices):
    """MAC do único Palm pareado (pelo nome), ou None se nenhum ou mais de um."""
    palms = sorted({mac for mac, name in devices if PALM_NAME.search(name)})
    return palms[0] if len(palms) == 1 else None


def resolve_palm(mac=None, devices=None):
    """``mac`` quando informado; senão o Palm pareado. SystemExit com a lista se não der."""
    if mac:
        return mac
    devices = paired_devices() if devices is None else devices
    found = pick_palm(devices)
    if found:
        print(f"[BT] Palm pareado detectado: {found}")
        return found
    names = ", ".join(f"{name or '?'} ({addr})" for addr, name in devices) or "nenhum"
    raise SystemExit("Não achei um único Palm pareado. Pareie o Palm no Bluetooth do sistema "
                     "ou informe o MAC (AA:BB:CC:DD:EE:FF).\nPareados: " + names)
