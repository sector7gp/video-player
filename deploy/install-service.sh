#!/bin/bash
# Instala arranque automático con systemd (Pi sin escritorio / Lite).
set -euo pipefail

USER_NAME="${1:-video1}"
PROJECT_DIR="/home/${USER_NAME}/video-player"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/deploy/video-control.service"
SERVICE_DST="/etc/systemd/system/video-control.service"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Ejecutá con sudo: sudo bash deploy/install-service.sh [usuario]"
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/video_control.py" ]]; then
  echo "No existe ${PROJECT_DIR}/video_control.py"
  echo "Cloná el repo: git clone https://github.com/sector7gp/video-player.git ${PROJECT_DIR}"
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/config.json" ]]; then
  if [[ -f "${PROJECT_DIR}/config.json.example" ]]; then
    cp "${PROJECT_DIR}/config.json.example" "${PROJECT_DIR}/config.json"
    chown "${USER_NAME}:${USER_NAME}" "${PROJECT_DIR}/config.json"
    echo "Creado ${PROJECT_DIR}/config.json desde config.json.example"
  else
    echo "AVISO: no existe config.json ni config.json.example en ${PROJECT_DIR}"
  fi
fi

sed "s|/home/video1/video-player|${PROJECT_DIR}|g; s|User=video1|User=${USER_NAME}|g; s|Group=video1|Group=${USER_NAME}|g" \
  "${SERVICE_SRC}" > "${SERVICE_DST}"

# Quitar autostart de escritorio si existía (no aplica sin GUI)
rm -f "/home/${USER_NAME}/.config/autostart/video-control.desktop"

systemctl daemon-reload
systemctl enable video-control.service
systemctl restart video-control.service

echo "OK: servicio habilitado para arranque en multi-user (sin GUI)."
echo "Estado: systemctl status video-control.service"
echo "Log:    journalctl -u video-control.service -f"
echo "Reiniciá para probar boot: sudo reboot"
