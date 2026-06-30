"""Hotspot WiFi vía NetworkManager (nmcli)."""

import logging
import re
import shutil
import subprocess

logger = logging.getLogger("video_admin.hotspot")

HOTSPOT_CONN_NAME = "video-admin-hotspot"


def _run(cmd, check=True):
    logger.debug("Ejecutando: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Comando falló ({result.returncode}): {' '.join(cmd)}\n{err}")
    return result


def detect_wifi_interface():
    """Devuelve la primera interfaz WiFi disponible (ej. wlan0)."""
    if not shutil.which("nmcli"):
        raise RuntimeError("nmcli no encontrado; instale network-manager.")

    result = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"], check=True)
    candidatos = []
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        device, dev_type, state = parts[0], parts[1], parts[2]
        if dev_type == "wifi" and device:
            candidatos.append((device, state))

    if not candidatos:
        raise RuntimeError("No se encontró interfaz WiFi.")

    for device, state in candidatos:
        if state != "unavailable":
            return device
    return candidatos[0][0]


def setup_hotspot(ssid, password, ifname=None):
    """Activa hotspot WPA2. Devuelve nombre de interfaz usada."""
    if len(password) < 8:
        raise ValueError("La clave WPA del hotspot debe tener al menos 8 caracteres.")

    if ifname is None:
        ifname = detect_wifi_interface()

    teardown_hotspot()

    _run(
        [
            "nmcli",
            "device",
            "wifi",
            "hotspot",
            "ifname",
            ifname,
            "ssid",
            ssid,
            "password",
            password,
            "con-name",
            HOTSPOT_CONN_NAME,
        ]
    )
    logger.info("Hotspot activo: SSID=%s ifname=%s", ssid, ifname)
    return ifname


def teardown_hotspot():
    """Baja el hotspot creado por este módulo."""
    if not shutil.which("nmcli"):
        return

    _run(["nmcli", "connection", "down", HOTSPOT_CONN_NAME], check=False)
    _run(["nmcli", "connection", "delete", HOTSPOT_CONN_NAME], check=False)
    logger.info("Hotspot desactivado.")


def hotspot_gateway_ip(ifname=None):
    """Intenta obtener la IP del AP para mostrar en logs."""
    if ifname is None:
        try:
            ifname = detect_wifi_interface()
        except RuntimeError:
            return None
    result = _run(
        ["nmcli", "-t", "-f", "IP4.ADDRESS", "device", "show", ifname],
        check=False,
    )
    for line in result.stdout.splitlines():
        m = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
        if m:
            return m.group(1)
    return "192.168.4.1"
