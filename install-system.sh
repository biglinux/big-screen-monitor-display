#!/usr/bin/env bash
set -e

if [ "$EUID" -ne 0 ]; then
    echo ":: Este script precisa de privilégios de root para instalar no sistema."
    echo ":: Execute com: sudo $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKGNAME="big-screen-monitor-display"

echo "=== 1. Instalando dependências do sistema ==="
if command -v zypper >/dev/null 2>&1; then
    echo ":: Instalando via zypper para Python 3.13 e GTK4..."
    zypper --non-interactive install --no-recommends \
        typelib-1_0-Gtk-4_0 \
        typelib-1_0-Adw-1 \
        python313-Pillow \
        python313-pyusb \
        python313-pyserial
elif command -v apt-get >/dev/null 2>&1; then
    echo ":: Detectado gerenciador apt"
    apt-get update -y
    apt-get install -y \
        gir1.2-gtk-4.0 gir1.2-adw-1 \
        python3-pil python3-numpy python3-psutil \
        python3-usb python3-serial libusb-1.0-0 \
        pciutils librsvg2-bin fontconfig polkitd gettext
fi

echo "=== 2. Copiando arquivos para o sistema (/usr e /etc) ==="
cp -r "${SCRIPT_DIR}/usr"/* /usr/
if [ -d "${SCRIPT_DIR}/etc" ]; then
    cp -r "${SCRIPT_DIR}/etc"/* /etc/
fi

echo "=== 3. Aplicando configurações para DeepCool AK500S e Tela USB (Tema Brother Away) ==="
mkdir -p /etc/big-screen-monitor-display
if [ -f "${SCRIPT_DIR}/settings.json" ]; then
    cp "${SCRIPT_DIR}/settings.json" /etc/big-screen-monitor-display/settings.json
fi
chmod 644 /etc/big-screen-monitor-display/settings.json 2>/dev/null || true

echo "=== 4. Compilando arquivos de tradução (locales) ==="
for po in "${SCRIPT_DIR}/locale/"*.po; do
    [ -s "$po" ] || continue
    lang=$(basename "$po" .po)
    install -d "/usr/share/locale/${lang}/LC_MESSAGES"
    msgfmt -o "/usr/share/locale/${lang}/LC_MESSAGES/${PKGNAME}.mo" "$po" 2>/dev/null || {
        echo ":: Aviso: pulando catálogo ${lang}.po"
    }
done

echo "=== 5. Ajustando permissões de executáveis e serviços ==="
chmod 755 /usr/bin/big-screen-monitor-config.sh /usr/bin/big-screen-monitor-display.sh /usr/bin/deepcool-digital.sh 2>/dev/null || true
ln -sf /usr/bin/deepcool-digital.sh /usr/bin/deepcool-digital 2>/dev/null || true
chmod 755 /usr/share/${PKGNAME}/main.py /usr/share/${PKGNAME}/config_gui.py /usr/share/${PKGNAME}/tray/main.py 2>/dev/null || true
chmod 755 /usr/lib/${PKGNAME}/bsm-helper
chmod 644 /usr/lib/systemd/system/big-screen-monitor-display.service
chmod 644 /usr/lib/udev/rules.d/70-big-screen-monitor-display.rules
chmod 644 /usr/lib/sysusers.d/big-screen-monitor-display.conf
if [ -f "/usr/share/polkit-1/actions/org.biglinux.big-screen-monitor.policy" ]; then
    chmod 644 /usr/share/polkit-1/actions/org.biglinux.big-screen-monitor.policy
fi
if [ -f "/usr/share/polkit-1/rules.d/49-big-screen-monitor.rules" ]; then
    chmod 644 /usr/share/polkit-1/rules.d/49-big-screen-monitor.rules
fi
if [ -f "/etc/xdg/autostart/big-screen-monitor-media.desktop" ]; then
    chmod 644 /etc/xdg/autostart/big-screen-monitor-media.desktop
fi

echo "=== 6. Configurando grupo e permissões de udev ==="
systemd-sysusers /usr/lib/sysusers.d/big-screen-monitor-display.conf 2>/dev/null || groupadd -r big-screen-monitor 2>/dev/null || true

# Adicionar o usuário atual aos grupos necessários
TARGET_USER="${SUDO_USER:-marcos}"
if id "$TARGET_USER" >/dev/null 2>&1; then
    usermod -aG dialout,big-screen-monitor "$TARGET_USER" 2>/dev/null || true
    echo ":: Usuário $TARGET_USER adicionado aos grupos dialout e big-screen-monitor"
fi

udevadm control --reload-rules 2>/dev/null || true

# Gatilhos udev para aplicar as permissões imediatamente aos displays conectados
for vendor in 1908 1cbe 1a86 454d 3633 0483; do
    udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor=${vendor} 2>/dev/null || true
done
udevadm trigger --action=add --subsystem-match=tty 2>/dev/null || true
udevadm trigger --action=change --subsystem-match=hidraw 2>/dev/null || true
udevadm trigger --action=change --subsystem-match=powercap 2>/dev/null || true

echo "=== 7. Ativando e iniciando o serviço systemd ==="
systemctl daemon-reload
systemctl enable big-screen-monitor-display.service
systemctl restart big-screen-monitor-display.service

echo ""
echo "=========================================================="
echo "    INSTALAÇÃO CONCLUÍDA COM SUCESSO!"
echo "=========================================================="
echo "  - DeepCool AK500S configurado (monitoramento CPU)"
echo "  - Turing Smart Screen 3.5\" configurado com tema Brother Away"
echo "  - Status do serviço:"
systemctl status big-screen-monitor-display.service --no-pager || true
echo "=========================================================="
