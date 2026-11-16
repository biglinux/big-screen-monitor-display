#!/usr/bin/env bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo ":: Execute com sudo: sudo $0"
    exit 1
fi

echo "=== Parando e desabilitando o serviço ==="
systemctl disable --now big-screen-monitor-display.service 2>/dev/null || true

echo "=== Removendo arquivos do sistema ==="
rm -f /usr/bin/big-screen-monitor-config.sh /usr/bin/big-screen-monitor-display.sh
rm -rf /usr/share/big-screen-monitor-display
rm -rf /usr/lib/big-screen-monitor-display
rm -f /usr/lib/systemd/system/big-screen-monitor-display.service
rm -f /usr/lib/udev/rules.d/70-big-screen-monitor-display.rules
rm -f /usr/lib/sysusers.d/big-screen-monitor-display.conf
rm -f /usr/share/polkit-1/actions/org.biglinux.big-screen-monitor.policy
rm -f /usr/share/polkit-1/rules.d/49-big-screen-monitor.rules
rm -f /etc/xdg/autostart/big-screen-monitor-media.desktop

echo "=== Recarregando systemd e udev ==="
systemctl daemon-reload
udevadm control --reload-rules 2>/dev/null || true

echo "=== Desinstalação concluída ==="
