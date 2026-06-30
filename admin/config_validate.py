"""Validación de config.json (independiente de video_control.py)."""

import os

CONFIG_DEFAULT = {
    "video": {"path": "/media/video1.mp4"},
    "audio": {
        "salida": "hdmi",
        "alsa_hdmi": "plughw:CARD=vc4hdmi0,DEV=0",
        "alsa_externa": "plughw:CARD=Device,DEV=0",
    },
    "cuepoints": {
        "cue1_ms": 20,
        "cue2_ms": 12000,
        "cue3_ms": 13000,
        "cue4_ms": 14000,
        "cue5_ms": 14500,
        "cue6_ms": 15000,
        "cue7_ms": 16000,
        "cue8_ms": 200000,
        "cue9_ms": 210000,
    },
    "timer_minutos": 5,
    "boton1_largo": {
        "segundos": 5,
        "salir_app_segundos": 10,
        "comando": "systemctl restart video-control",
        "overlay": {
            "texto": "SOLTAR PARA\nREINICIAR",
            "tamano": 42,
            "centrado": True,
            "color_hex": "FFFFFF",
            "opacidad": 255,
            "sombra_roja": True,
        },
    },
}

CUE_KEYS = (
    "cue1_ms",
    "cue2_ms",
    "cue3_ms",
    "cue4_ms",
    "cue5_ms",
    "cue6_ms",
    "cue7_ms",
    "cue8_ms",
    "cue9_ms",
)


def deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_config(data, require_video_file=True):
    """
    Valida un dict de config. Devuelve (cfg_merged, errores).
    Si errores está vacío, cfg_merged es la config normalizada.
    """
    errores = []

    if not isinstance(data, dict):
        return None, ["config.json debe ser un objeto JSON."]

    cfg = deep_merge(CONFIG_DEFAULT, data)

    video_path = cfg.get("video", {}).get("path", "").strip()
    if not video_path:
        errores.append("config.json: video.path no puede estar vacío.")
    elif require_video_file and not os.path.isfile(video_path):
        parent = os.path.dirname(video_path) or "/"
        if not os.path.isdir(parent):
            errores.append(
                f"config.json: el directorio del video no existe: {parent}"
            )
        else:
            errores.append(
                f"config.json: el archivo de video no existe: {video_path}"
            )

    audio = cfg.get("audio")
    if not isinstance(audio, dict):
        errores.append("config.json: audio debe ser un objeto.")
    else:
        salida = str(audio.get("salida", "")).strip().lower()
        if salida not in ("hdmi", "externa"):
            errores.append("config.json: audio.salida debe ser 'hdmi' o 'externa'.")
        for key in ("alsa_hdmi", "alsa_externa"):
            if not str(audio.get(key, "")).strip():
                errores.append(f"config.json: audio.{key} no puede estar vacío.")

    cues = cfg.get("cuepoints")
    if not isinstance(cues, dict):
        errores.append("config.json: cuepoints debe ser un objeto.")
        valores_cue = []
    else:
        valores_cue = []
        for key in CUE_KEYS:
            valor = cues.get(key)
            if not isinstance(valor, (int, float)):
                errores.append(f"config.json: cuepoints.{key} debe ser un número.")
                valores_cue.append(None)
            elif valor < 0:
                errores.append(f"config.json: cuepoints.{key} debe ser >= 0.")
                valores_cue.append(int(valor))
            else:
                valores_cue.append(int(valor))

        if all(v is not None for v in valores_cue):
            for i in range(len(valores_cue) - 1):
                if valores_cue[i] >= valores_cue[i + 1]:
                    errores.append(
                        f"config.json: los cuepoints deben ser estrictamente crecientes "
                        f"({CUE_KEYS[i]}={valores_cue[i]} >= "
                        f"{CUE_KEYS[i + 1]}={valores_cue[i + 1]})."
                    )

    timer_minutos = cfg.get("timer_minutos")
    if not isinstance(timer_minutos, (int, float)) or timer_minutos <= 0:
        errores.append("config.json: timer_minutos debe ser un número > 0.")

    boton1_largo = cfg.get("boton1_largo")
    if not isinstance(boton1_largo, dict):
        errores.append("config.json: boton1_largo debe ser un objeto.")
    else:
        hold_s = boton1_largo.get("segundos")
        if not isinstance(hold_s, (int, float)) or hold_s <= 0:
            errores.append("config.json: boton1_largo.segundos debe ser un número > 0.")
        salir_app_s = boton1_largo.get("salir_app_segundos")
        if not isinstance(salir_app_s, (int, float)) or salir_app_s <= 0:
            errores.append(
                "config.json: boton1_largo.salir_app_segundos debe ser un número > 0."
            )
        elif isinstance(hold_s, (int, float)) and salir_app_s <= hold_s:
            errores.append(
                "config.json: boton1_largo.salir_app_segundos debe ser mayor "
                "que boton1_largo.segundos."
            )
        if not str(boton1_largo.get("comando", "")).strip():
            errores.append("config.json: boton1_largo.comando no puede estar vacío.")
        overlay = boton1_largo.get("overlay")
        if not isinstance(overlay, dict):
            errores.append("config.json: boton1_largo.overlay debe ser un objeto.")
        else:
            if not str(overlay.get("texto", "")).strip():
                errores.append(
                    "config.json: boton1_largo.overlay.texto no puede estar vacío."
                )
            tamano = overlay.get("tamano")
            if not isinstance(tamano, (int, float)) or tamano <= 0:
                errores.append(
                    "config.json: boton1_largo.overlay.tamano debe ser un número > 0."
                )
            if not isinstance(overlay.get("centrado"), bool):
                errores.append(
                    "config.json: boton1_largo.overlay.centrado debe ser true/false."
                )
            opacidad = overlay.get("opacidad")
            if not isinstance(opacidad, (int, float)) or not (0 <= int(opacidad) <= 255):
                errores.append(
                    "config.json: boton1_largo.overlay.opacidad debe estar entre 0 y 255."
                )
            color_hex = str(overlay.get("color_hex", "")).strip().lstrip("#")
            if len(color_hex) != 6:
                errores.append(
                    "config.json: boton1_largo.overlay.color_hex debe tener 6 hex dígitos."
                )
            else:
                try:
                    int(color_hex, 16)
                except ValueError:
                    errores.append(
                        "config.json: boton1_largo.overlay.color_hex es inválido."
                    )
            if not isinstance(overlay.get("sombra_roja"), bool):
                errores.append(
                    "config.json: boton1_largo.overlay.sombra_roja debe ser true/false."
                )

    if errores:
        return None, errores
    return cfg, []
