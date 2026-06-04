#!/bin/bash
# Instala arranque automático con systemd (Pi sin escritorio / Lite).
set -euo pipefail

USER_NAME="${1:-video1}"
HOME_DIR="/home/${USER_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/deploy/video-control.service"
SERVICE_DST="/etc/systemd/system/video-control.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Ejecutá con sudo: sudo bash deploy/install-service.sh [usuario]"
  exit 1
fi

if [[ ! -f "${HOME_DIR}/video_control.py" ]]; then
  echo "No existe ${HOME_DIR}/video_control.py"
  exit 1
fi

sed "s|/home/video1|${HOME_DIR}|g; s|User=video1|User=${USER_NAME}|g; s|Group=video1|Group=${USER_NAME}|g" \
  "${SERVICE_SRC}" > "${SERVICE_DST}"

# Quitar autostart de escritorio si existía (no aplica sin GUI)
rm -f "${HOME_DIR}/.config/autostart/video-control.desktop"

systemctl daemon-reload
systemctl enable video-control.service
systemctl restart video-control.service

echo "OK: servicio habilitado para arranque en multi-user (sin GUI)."
echo "Estado: systemctl status video-control.service"
echo "Log:    journalctl -u video-control.service -f"
echo "Reiniciá para probar boot: sudo reboot"
