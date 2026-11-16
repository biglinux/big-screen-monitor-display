#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/usr/share/big-screen-monitor-display:${PYTHONPATH}"

if [ ! -d "${SCRIPT_DIR}/.venv" ]; then
    echo "Ambiente virtual não encontrado em ${SCRIPT_DIR}/.venv. Criando..."
    python3 -m venv "${SCRIPT_DIR}/.venv" --system-site-packages
    "${SCRIPT_DIR}/.venv/bin/pip" install Pillow pyusb pyserial
fi

exec "${SCRIPT_DIR}/.venv/bin/python3" "${SCRIPT_DIR}/usr/share/big-screen-monitor-display/main.py" "$@"
