#!/usr/bin/env bash
# Big Screen Monitor Display - remove what install-system.sh installed.
#
#   sudo ./uninstall-system.sh            files and service; settings are kept
#   sudo ./uninstall-system.sh --purge    also /etc/big-screen-monitor-display
#                                         (a copy is left in /var/backups first)
#   ./uninstall-system.sh --destdir DIR   remove a staged install from DIR
#
# Files are taken from the install manifest, so nothing else is touched.
# Personal files are never deleted: autostart entries the tray apps created in
# home folders are only listed.
set -euo pipefail

PKGNAME="big-screen-monitor-display"
SERVICE="${PKGNAME}.service"
DESTDIR=""
PURGE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --destdir) DESTDIR="${2:?--destdir needs a directory}"; shift ;;
        --destdir=*) DESTDIR="${1#*=}" ;;
        --purge) PURGE=1 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf ':: %s\n' "$*"; }
die() { printf ':: ERROR: %s\n' "$*" >&2; exit 1; }

if [ -n "$DESTDIR" ]; then
    ROOT="$(cd "$DESTDIR" && pwd)"
else
    ROOT=""
    [ "$(id -u)" -eq 0 ] || die "run as root: sudo $0"
    if command -v pacman >/dev/null 2>&1 && pacman -Qq "$PKGNAME" >/dev/null 2>&1; then
        die "these files belong to the ${PKGNAME} package: remove it with pacman -R ${PKGNAME}"
    fi
fi

MANIFEST="${ROOT}/usr/lib/${PKGNAME}/install-manifest"

if [ -z "$DESTDIR" ]; then
    say "Stopping the service"
    systemctl disable --now "$SERVICE" 2>/dev/null || true
    "/usr/lib/${PKGNAME}/bsm-usb-guard" unpark 2>/dev/null || true
fi

say "Removing files"
removed=0
if [ -f "$MANIFEST" ]; then
    while IFS= read -r file; do
        case "$file" in
            /usr/*|/etc/xdg/autostart/*) ;;
            *) continue ;;            # never anything outside what the installer writes
        esac
        if [ -e "${ROOT}${file}" ] || [ -L "${ROOT}${file}" ]; then
            rm -f "${ROOT}${file}"
            removed=$((removed + 1))
        fi
    done < "$MANIFEST"
fi
# Installs made before the manifest existed, and the first tray apps (pull request #11).
for file in usr/bin/big-screen-monitor-config.sh usr/bin/big-screen-monitor-display.sh \
            usr/bin/big-screen-monitor-tray usr/bin/big-screen-monitor-deepcool \
            usr/bin/deepcool-digital usr/bin/deepcool-digital.sh usr/bin/screen-monitor-tray usr/bin/screen-monitor-tray.sh \
            usr/lib/systemd/system/${PKGNAME}.service usr/lib/systemd/system/${PKGNAME}-sleep.service \
            usr/lib/systemd/system/sleep.target.wants/${PKGNAME}-sleep.service \
            usr/lib/udev/rules.d/70-${PKGNAME}.rules usr/lib/sysusers.d/${PKGNAME}.conf \
            usr/share/polkit-1/actions/org.biglinux.big-screen-monitor.policy \
            usr/share/applications/${PKGNAME}.desktop usr/share/applications/big-screen-monitor-tray.desktop \
            usr/share/applications/big-screen-monitor-deepcool.desktop \
            usr/share/applications/deepcool-digital.desktop usr/share/applications/screen-monitor-tray.desktop \
            usr/share/icons/hicolor/scalable/apps/${PKGNAME}.svg \
            usr/share/icons/hicolor/scalable/apps/big-screen-monitor-tray.svg \
            usr/share/icons/hicolor/scalable/apps/big-screen-monitor-deepcool.svg \
            usr/share/icons/hicolor/scalable/apps/deepcool-digital.svg \
            usr/share/icons/hicolor/scalable/apps/screen-monitor-tray.svg \
            etc/xdg/autostart/big-screen-monitor-media.desktop; do
    case "$file" in
        usr/bin/deepcool-digital*|usr/bin/screen-monitor-tray*|usr/share/applications/deepcool-digital.desktop|\
        usr/share/applications/screen-monitor-tray.desktop)
            # Old names: only when they start this program.
            grep -qs "/usr/share/${PKGNAME}/" "${ROOT}/${file}" || [ -L "${ROOT}/${file}" ] || continue ;;
    esac
    if [ -e "${ROOT}/${file}" ] || [ -L "${ROOT}/${file}" ]; then
        rm -f "${ROOT}/${file}"
        removed=$((removed + 1))
    fi
done
for file in "${ROOT}"/usr/share/locale/*/LC_MESSAGES/"${PKGNAME}".mo; do
    [ -e "$file" ] && rm -f "$file" && removed=$((removed + 1))
done
rm -rf "${ROOT}/usr/share/${PKGNAME:?}" "${ROOT}/usr/lib/${PKGNAME:?}"
say "Removed ${removed} files"

if [ "$PURGE" = 1 ] && [ -d "${ROOT}/etc/${PKGNAME}" ]; then
    backup="${ROOT}/var/backups/${PKGNAME}-$(date +%Y%m%d-%H%M%S).tar.gz"
    mkdir -p "${backup%/*}"
    tar -C "${ROOT}/etc" -czf "$backup" "$PKGNAME"
    tar -tzf "$backup" >/dev/null || die "could not verify the backup $backup; settings kept"
    rm -rf "${ROOT}/etc/${PKGNAME:?}"
    say "Settings removed (copy: ${backup#"$ROOT"})"
else
    [ -d "${ROOT}/etc/${PKGNAME}" ] && say "Settings kept in /etc/${PKGNAME} (use --purge to remove them)"
fi

if [ -z "$DESTDIR" ]; then
    systemctl daemon-reload
    udevadm control --reload-rules 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
    shown=0
    for file in /home/*/.config/autostart/big-screen-monitor-*.desktop /root/.config/autostart/big-screen-monitor-*.desktop; do
        [ -e "$file" ] || continue
        [ "$shown" = 1 ] || say "Personal autostart entries left untouched (remove them if you wish):"
        shown=1
        printf '   %s\n' "$file"
    done
fi
say "Done."
