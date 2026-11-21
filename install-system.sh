#!/usr/bin/env bash
# Big Screen Monitor Display - install from this source tree.
#
# For distributions without a package (openSUSE Tumbleweed/Leap/Slowroll,
# Regata OS, Debian/Ubuntu, Fedora). On Arch, Manjaro and BigLinux prefer the
# package (pkgbuild/PKGBUILD): it is what this script refuses to overwrite.
#
#   sudo ./install-system.sh               dependencies + files + service
#   sudo ./install-system.sh --skip-deps   files + service only
#   ./install-system.sh --print-deps       show the packages for this system
#   ./install-system.sh --destdir DIR      stage the files in DIR (no root,
#                                          no dependency or system changes)
#
# Safe to run again (upgrade): /etc/big-screen-monitor-display/settings.json
# is never replaced (a verified copy is kept before an upgrade), the service
# keeps its enabled/disabled state, and every installed file is listed in
# /usr/lib/big-screen-monitor-display/install-manifest so that
# uninstall-system.sh removes exactly those files.
set -euo pipefail

PKGNAME="big-screen-monitor-display"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="${PKGNAME}.service"
DESTDIR=""
SKIP_DEPS=0
PRINT_DEPS=0
FORCE=0
OS_RELEASE="${BSM_OS_RELEASE:-/etc/os-release}"

usage() { sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --destdir) DESTDIR="${2:?--destdir needs a directory}"; shift ;;
        --destdir=*) DESTDIR="${1#*=}" ;;
        --skip-deps) SKIP_DEPS=1 ;;
        --print-deps) PRINT_DEPS=1 ;;
        --force) FORCE=1 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

say() { printf ':: %s\n' "$*"; }
warn() { printf ':: WARNING: %s\n' "$*" >&2; }
die() { printf ':: ERROR: %s\n' "$*" >&2; exit 1; }

# ------------------------------------------------------------------ distribution
# Same families as bsmd/distro.py (a test checks both lists agree).
os_field() { [ -r "$OS_RELEASE" ] && sed -n "s/^$1=//p" "$OS_RELEASE" | head -n1 | tr -d '"'"'" || true; }

detect_family() {
    local id like token
    id="$(os_field ID | tr '[:upper:]' '[:lower:]')"
    like="$(os_field ID_LIKE | tr '[:upper:]' '[:lower:]')"
    for token in $id $like; do
        case "$token" in
            arch|manjaro|biglinux|bigcommunity|endeavouros|garuda|cachyos|artix) echo arch; return ;;
            opensuse|opensuse-*|regataos|suse|sles|sled) echo suse; return ;;
            debian|ubuntu|linuxmint|pop|elementary|zorin) echo debian; return ;;
            fedora|rhel|centos|rocky|almalinux|nobara) echo fedora; return ;;
        esac
    done
    echo unknown
}

python_suffix() { python3 -c 'import sys; print(f"{sys.version_info[0]}{sys.version_info[1]}")' 2>/dev/null || echo 3; }

# Essential packages (service + configuration window + tray apps).
deps_for() {
    local py
    case "$1" in
        arch)
            echo python python-pillow python-numpy python-psutil python-pyusb libusb python-pyserial pciutils \
                 librsvg fontconfig polkit python-gobject python-cairo glib2 gtk4 libadwaita hicolor-icon-theme \
                 gettext python-pyqt6 ;;
        suse)
            py="python$(python_suffix)"
            echo python3 "$py-Pillow" "$py-numpy" "$py-psutil" "$py-pyusb" "$py-pyserial" "$py-gobject" \
                 "$py-gobject-cairo" "$py-pycairo" "$py-PyQt6" typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 \
                 libusb-1_0-0 pciutils rsvg-convert fontconfig polkit pkexec gettext-tools hicolor-icon-theme ;;
        debian)
            echo python3 python3-pil python3-numpy python3-psutil python3-usb python3-serial python3-gi \
                 python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 libusb-1.0-0 pciutils librsvg2-bin fontconfig \
                 polkitd pkexec gettext hicolor-icon-theme python3-pyqt6 ;;
        fedora)
            echo python3 python3-pillow python3-numpy python3-psutil python3-pyusb python3-pyserial \
                 python3-gobject python3-cairo gtk4 libadwaita libusb1 pciutils librsvg2-tools fontconfig polkit \
                 gettext hicolor-icon-theme python3-pyqt6 ;;
    esac
}

# Optional features, never installed silently (named at the end).
optional_for() {
    case "$1" in
        arch) echo "lm_sensors openrgb playerctl libpulse alsa-utils" ;;
        suse) echo "sensors OpenRGB playerctl pulseaudio-utils alsa-utils" ;;
        debian) echo "lm-sensors openrgb playerctl pulseaudio-utils alsa-utils" ;;
        fedora) echo "lm_sensors openrgb playerctl pulseaudio-utils alsa-utils" ;;
    esac
}

install_deps() {
    local family="$1" packages
    read -r -a packages <<< "$(deps_for "$family")"
    say "Installing dependencies for ${family} ($(os_field PRETTY_NAME)): ${packages[*]}"
    case "$family" in
        # --needed: nothing reinstalled. No -Sy: a partial upgrade breaks Arch systems.
        arch) pacman -S --needed --noconfirm "${packages[@]}" ||
                  die "pacman could not install the packages; update the system (pacman -Syu) and run again." ;;
        suse) zypper --non-interactive install --no-recommends "${packages[@]}" ;;
        # update refreshes the package lists only (no upgrade); a fresh system has none.
        debian) apt-get update && apt-get install -y --no-install-recommends "${packages[@]}" ;;
        fedora) dnf install -y "${packages[@]}" ;;
        *) die "Unknown distribution: install the dependencies listed in README.md and use --skip-deps." ;;
    esac
}

check_python() {
    # Every change made in the windows reaches /etc through pkexec (openSUSE and
    # Debian ship it apart from polkit).
    command -v pkexec >/dev/null 2>&1 || die "pkexec is missing: settings could not be saved (install pkexec/polkit)"
    say "Checking the Python modules"
    python3 - <<'EOF' || die "a required Python module is missing (see above)"
import importlib, sys
missing = []
for module in ("PIL", "numpy", "psutil", "usb", "serial", "gi"):
    try:
        importlib.import_module(module)
    except ImportError:
        missing.append(module)
try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
except (ImportError, ValueError) as error:
    missing.append(f"GTK 4 / libadwaita ({error})")
if missing:
    print("   missing:", ", ".join(missing), file=sys.stderr)
    sys.exit(1)
try:
    import PyQt6  # noqa: F401
except ImportError:
    try:
        import PyQt5  # noqa: F401
    except ImportError:
        print("   note: PyQt6/PyQt5 missing: the tray apps will explain how to install it", file=sys.stderr)
EOF
}

# ------------------------------------------------------------------ files
MANIFEST_REL="usr/lib/${PKGNAME}/install-manifest"
declare -a INSTALLED=()

put() {       # put MODE SOURCE TARGET_RELATIVE
    install -D -m "$1" "$2" "${ROOT}/$3"
    INSTALLED+=("/$3")
}

put_conffile() {      # shipped file under /etc: never overwrite a changed copy
    local target="${ROOT}/$2"
    if [ -e "$target" ] && ! cmp -s "$1" "$target"; then
        install -D -m 644 "$1" "${target}.new"
        warn "kept your $2 (the new version is $2.new)"
    else
        install -D -m 644 "$1" "$target"
    fi
    INSTALLED+=("/$2")
}

backup_settings() {
    local settings="${ROOT}/etc/${PKGNAME}/settings.json" copy
    [ -f "$settings" ] || return 0
    copy="${settings}.pre-install-$(date +%Y%m%d-%H%M%S)"
    cp -p "$settings" "$copy"
    cmp -s "$settings" "$copy" || die "could not verify the settings backup $copy"
    say "Settings kept; verified copy: ${copy#"$ROOT"}"
    # Keep the three newest copies (the service keeps its own settings.json.bak too).
    local old
    while IFS= read -r old; do rm -f "$old"; done < <(find "${settings%/*}" -maxdepth 1 \
        -name "${settings##*/}.pre-install-*" -printf '%T@ %p\n' | sort -rn | tail -n +4 | cut -d' ' -f2-)
}

remove_legacy() {
    # Files of the first version of the tray apps (pull request #11 installer).
    local file
    for file in usr/bin/deepcool-digital usr/bin/deepcool-digital.sh usr/bin/screen-monitor-tray \
                usr/bin/screen-monitor-tray.sh usr/share/applications/deepcool-digital.desktop \
                usr/share/applications/screen-monitor-tray.desktop; do
        [ -e "${ROOT}/${file}" ] || [ -L "${ROOT}/${file}" ] || continue
        if grep -qs "/usr/share/${PKGNAME}/" "${ROOT}/${file}" || \
                [ "$(readlink "${ROOT}/${file}" 2>/dev/null)" = "/usr/bin/${file##*/}.sh" ]; then
            rm -f "${ROOT}/${file}"
            say "removed old ${file}"
        fi
    done
    # Their icons: the same pictures as ours under the old names, removed only when identical.
    local old new
    for old in deepcool-digital:big-screen-monitor-deepcool screen-monitor-tray:big-screen-monitor-tray; do
        new="${SCRIPT_DIR}/usr/share/icons/hicolor/scalable/apps/${old#*:}.svg"
        file="${ROOT}/usr/share/icons/hicolor/scalable/apps/${old%%:*}.svg"
        if [ -f "$file" ] && cmp -s "$file" "$new"; then rm -f "$file"; fi
    done
}

install_files() {
    local src="${SCRIPT_DIR}" rel file po lang
    [ -d "${src}/usr/share/${PKGNAME}" ] || die "run this script from the source tree"
    # Application directory: entirely ours, replaced (removed modules must not linger).
    rm -rf "${ROOT}/usr/share/${PKGNAME:?}"
    while IFS= read -r -d '' file; do
        rel="${file#"${src}/"}"
        case "$rel" in */__pycache__/*|*.pyc) continue ;; esac
        if [ -x "$file" ]; then put 755 "$file" "$rel"; else put 644 "$file" "$rel"; fi
    done < <(find "${src}/usr" -type f -print0 | sort -z)
    for file in "${src}"/etc/xdg/autostart/*.desktop; do
        [ -e "$file" ] && put_conffile "$file" "etc/xdg/autostart/${file##*/}"
    done
    chmod 755 "${ROOT}"/usr/bin/big-screen-monitor-* "${ROOT}/usr/lib/${PKGNAME}/bsm-helper" \
        "${ROOT}/usr/lib/${PKGNAME}/bsm-usb-guard" "${ROOT}/usr/share/${PKGNAME}/main.py" \
        "${ROOT}/usr/share/${PKGNAME}/config_gui.py"
    # Sleep hook of the SmartMonitor HID panels (does nothing without one).
    install -d "${ROOT}/usr/lib/systemd/system/sleep.target.wants"
    ln -sfn "../${PKGNAME}-sleep.service" "${ROOT}/usr/lib/systemd/system/sleep.target.wants/${PKGNAME}-sleep.service"
    INSTALLED+=("/usr/lib/systemd/system/sleep.target.wants/${PKGNAME}-sleep.service")
    # Translations (an invalid machine translation is skipped, never fatal).
    if command -v msgfmt >/dev/null 2>&1; then
        for po in "${src}"/locale/*.po; do
            [ -s "$po" ] || continue
            lang="$(basename "$po" .po)"
            rel="usr/share/locale/${lang}/LC_MESSAGES/${PKGNAME}.mo"
            install -d "${ROOT}/${rel%/*}"
            if msgfmt -o "${ROOT}/${rel}" "$po" 2>/dev/null; then INSTALLED+=("/${rel}"); else
                rm -f "${ROOT}/${rel}"; warn "skipped invalid catalog ${lang}.po"; fi
        done
    else
        warn "msgfmt not found: the interface stays in English (install gettext)"
    fi
    find "${ROOT}/usr/share/${PKGNAME}" -name __pycache__ -type d -prune -exec rm -rf {} +
    install -d "${ROOT}/usr/lib/${PKGNAME}"
    printf '%s\n' "${INSTALLED[@]}" "/${MANIFEST_REL}" | sort -u > "${ROOT}/${MANIFEST_REL}"
    say "Installed $(wc -l < "${ROOT}/${MANIFEST_REL}") files (list: /${MANIFEST_REL})"
}

# ------------------------------------------------------------------ system
refresh_system() {
    # Same steps as the package scriptlet (pkgbuild/pkgbuild.install).
    systemd-sysusers "${PKGNAME}.conf" 2>/dev/null || true
    udevadm control --reload-rules 2>/dev/null || true
    local vendor
    for vendor in 1908 1cbe 1a86 454d 3633 0483; do
        udevadm trigger --action=add --subsystem-match=usb --attr-match=idVendor="${vendor}" 2>/dev/null || true
    done
    udevadm trigger --action=add --subsystem-match=tty 2>/dev/null || true
    udevadm trigger --action=change --subsystem-match=hidraw 2>/dev/null || true
    udevadm trigger --action=change --subsystem-match=powercap 2>/dev/null || true
    "/usr/lib/${PKGNAME}/bsm-helper" migrate >/dev/null 2>&1 || true
    systemctl daemon-reload
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
}

# ------------------------------------------------------------------ main
FAMILY="$(detect_family)"

if [ "$PRINT_DEPS" = 1 ]; then
    echo "family: ${FAMILY}"
    echo "essential: $(deps_for "$FAMILY")"
    echo "optional: $(optional_for "$FAMILY")"
    exit 0
fi

if [ -n "$DESTDIR" ]; then
    ROOT="$(mkdir -p "$DESTDIR" && cd "$DESTDIR" && pwd)"
    SKIP_DEPS=1
else
    ROOT=""
    [ "$(id -u)" -eq 0 ] || die "run as root: sudo $0"
    if [ "$FORCE" != 1 ]; then
        if command -v pacman >/dev/null 2>&1 && pacman -Qq "$PKGNAME" >/dev/null 2>&1; then
            die "the ${PKGNAME} package is installed; update it with pacman instead (or remove it first)."
        fi
        if command -v rpm >/dev/null 2>&1 && rpm -q "$PKGNAME" >/dev/null 2>&1; then
            die "the ${PKGNAME} RPM is installed; update it with your package manager instead."
        fi
    fi
fi

UPGRADE=0
if [ -e "${ROOT}/${MANIFEST_REL}" ] || [ -d "${ROOT}/usr/share/${PKGNAME}" ]; then UPGRADE=1; fi

[ "$SKIP_DEPS" = 1 ] || install_deps "$FAMILY"
[ -n "$DESTDIR" ] || check_python
backup_settings
remove_legacy
install_files

if [ -z "$DESTDIR" ]; then
    refresh_system
    if [ "$UPGRADE" = 0 ]; then
        systemctl enable --now "$SERVICE"
    else
        # Respect the user's choice: never re-enable a disabled service on upgrade.
        systemctl try-restart "$SERVICE" 2>/dev/null || true
    fi
    say "Service: $(systemctl is-active "$SERVICE" 2>/dev/null || true) ($(systemctl is-enabled "$SERVICE" 2>/dev/null || true))"
    say "Optional extras for ${FAMILY}: $(optional_for "$FAMILY")"
fi
say "Done. Open \"Big Screen Monitor Display\" from the applications menu."
