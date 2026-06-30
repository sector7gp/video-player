#!/bin/bash
# Instala portal admin temporal (hotspot + web) con systemd.
set -euo pipefail

USER_NAME="${1:-video1}"
PROJECT_DIR="/home/${USER_NAME}/video-player"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_SRC="${SCRIPT_DIR}/deploy/video-admin.service"
SERVICE_DST="/etc/systemd/system/video-admin.service"
PORTAL_EXAMPLE="${PROJECT_DIR}/admin/portal.json.example"
PORTAL_JSON="${PROJECT_DIR}/admin/portal.json"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Ejecutá con sudo: sudo bash deploy/install-admin.sh [usuario]"
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/admin/portal_main.py" ]]; then
  echo "No existe ${PROJECT_DIR}/admin/portal_main.py"
  echo "Cloná o actualizá el repo en ${PROJECT_DIR}"
  exit 1
fi

echo "Instalando dependencias..."
apt-get update -qq
apt-get install -y network-manager python3-flask ffmpeg

if [[ ! -f "${PORTAL_JSON}" ]]; then
  if [[ -f "${PORTAL_EXAMPLE}" ]]; then
    cp "${PORTAL_EXAMPLE}" "${PORTAL_JSON}"
    sed -i "s|/home/video1|/home/${USER_NAME}|g" "${PORTAL_JSON}"
    chown "${USER_NAME}:${USER_NAME}" "${PORTAL_JSON}"
    echo "Creado ${PORTAL_JSON} desde portal.json.example"
    echo "IMPORTANTE: editá hotspot.clave antes de usar en producción."
  else
    echo "AVISO: no existe portal.json.example"
  fi
fi

mkdir -p /media
chmod 755 /media

sed "s|/home/video1/video-player|${PROJECT_DIR}|g; s|VIDEO_USER=video1|VIDEO_USER=${USER_NAME}|g" \
  "${SERVICE_SRC}" > "${SERVICE_DST}"

systemctl daemon-reload
systemctl enable video-admin.service

REPO_VERSION="$(tr -d '[:space:]' < "${PROJECT_DIR}/VERSION" 2>/dev/null || echo unknown)"
echo "OK: video-admin v${REPO_VERSION} habilitado (ventana temporal en cada boot)."
echo "Editar credenciales: nano ${PORTAL_JSON}"
echo "Estado:  systemctl status video-admin.service"
echo "Log:     journalctl -u video-admin.service -f"
echo "Reiniciá para probar: sudo reboot"
