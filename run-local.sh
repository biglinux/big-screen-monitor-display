#!/usr/bin/env bash
# Run Big Screen Monitor Display from this source tree (development), with the
# system Python and its modules - nothing is downloaded or installed.
#
#   ./run-local.sh                 the monitor itself (manual run, as your user)
#   ./run-local.sh config          the configuration window
#   ./run-local.sh tray            the USB screens tray app
#   ./run-local.sh deepcool        the DeepCool tray app
#   ./run-local.sh <main.py args>  anything main.py accepts (--help)
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/usr/share/big-screen-monitor-display"
export PYTHONPATH="${APP_DIR}${PYTHONPATH:+:${PYTHONPATH}}"

if ! python3 -c 'import PIL, numpy, psutil, usb, serial' 2>/dev/null; then
    echo "Missing Python modules. Show the packages for this system with:" >&2
    echo "    ./install-system.sh --print-deps" >&2
    exit 1
fi

case "${1:-}" in
    config) shift; exec python3 "${APP_DIR}/config_gui.py" "$@" ;;
    tray) shift; exec python3 "${APP_DIR}/screentray/main.py" "$@" ;;
    deepcool) shift; exec python3 "${APP_DIR}/deepcooltray/main.py" "$@" ;;
    *) exec python3 "${APP_DIR}/main.py" "$@" ;;
esac
