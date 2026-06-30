#!/usr/bin/env python3
"""Portal admin temporal: hotspot WiFi + edición config.json + upload video."""

import hmac
import json
import logging
import os
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from functools import wraps

from flask import (
    Flask,
    jsonify,
    redirect,
    request,
    send_from_directory,
    session,
    url_for,
)

admin_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.dirname(admin_dir)
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)
if admin_dir not in sys.path:
    sys.path.insert(0, admin_dir)

from version import __version__  # noqa: E402
from config_validate import validate_config  # noqa: E402
import hotspot  # noqa: E402

logger = logging.getLogger("video_admin")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

PORTAL_DEFAULT = {
    "hotspot": {
        "ssid": "VIDEO1-Setup",
        "usuario": "admin",
        "clave": "cambiar-clave-min-8",
    },
    "ventana_minutos": 10,
    "puerto": 8080,
    "config_path": os.path.join(project_dir, "config.json"),
    "max_upload_gb": 8,
}

ventana_cerrada = False
ventana_fin_monotonic = 0.0
portal_cfg = {}
wifi_ifname = None

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024


def cargar_portal_config():
    portal_path = os.environ.get(
        "PORTAL_PATH", os.path.join(admin_dir, "portal.json")
    )
    cfg = dict(PORTAL_DEFAULT)
    if os.path.isfile(portal_path):
        with open(portal_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            hs = data.get("hotspot", {})
            if isinstance(hs, dict):
                cfg["hotspot"].update(hs)
            for key in ("ventana_minutos", "puerto", "config_path", "max_upload_gb"):
                if key in data:
                    cfg[key] = data[key]
    else:
        logger.warning("No se encontró %s; usando valores por defecto.", portal_path)

    hs = cfg["hotspot"]
    if not str(hs.get("ssid", "")).strip():
        raise ValueError("portal.json: hotspot.ssid no puede estar vacío.")
    if not str(hs.get("usuario", "")).strip():
        raise ValueError("portal.json: hotspot.usuario no puede estar vacío.")
    if len(str(hs.get("clave", ""))) < 8:
        raise ValueError("portal.json: hotspot.clave debe tener al menos 8 caracteres.")
    if cfg["ventana_minutos"] <= 0:
        raise ValueError("portal.json: ventana_minutos debe ser > 0.")
    if cfg["puerto"] <= 0:
        raise ValueError("portal.json: puerto debe ser > 0.")
    return cfg


def segundos_restantes():
    return max(0, int(ventana_fin_monotonic - time.monotonic()))


def credenciales_validas(usuario, clave):
    esperado_u = portal_cfg["hotspot"]["usuario"]
    esperado_c = portal_cfg["hotspot"]["clave"]
    u_ok = hmac.compare_digest(str(usuario), str(esperado_u))
    c_ok = hmac.compare_digest(str(clave), str(esperado_c))
    return u_ok and c_ok


def requiere_login(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if ventana_cerrada:
            return jsonify({"error": "Ventana de administración cerrada."}), 503
        if not session.get("autenticado"):
            return jsonify({"error": "No autenticado."}), 401
        return fn(*args, **kwargs)

    return wrapper


def reiniciar_reproductor():
    subprocess.run(
        ["systemctl", "restart", "video-control.service"],
        check=False,
        capture_output=True,
        text=True,
    )
    logger.info("Reproductor reiniciado (video-control.service).")


def leer_config_raw():
    path = portal_cfg["config_path"]
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _chown_video_user(path):
    video_user = os.environ.get("VIDEO_USER", "video1")
    try:
        import pwd

        pw = pwd.getpwnam(video_user)
        os.chown(path, pw.pw_uid, pw.pw_gid)
    except (ImportError, KeyError, OSError):
        pass


def guardar_config(data):
    path = portal_cfg["config_path"]
    cfg, errores = validate_config(data, require_video_file=True)
    if errores:
        return None, errores

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.isfile(path):
        shutil.copy2(path, path + ".bak")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.chmod(path, 0o644)
    _chown_video_user(path)
    return cfg, []


def validar_video_ffprobe(path):
    if not shutil.which("ffprobe"):
        logger.warning("ffprobe no disponible; omitiendo validación de video.")
        return True, None
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or "ffprobe falló").strip()
    if "video" not in (proc.stdout or ""):
        return False, "El archivo no contiene pista de video."
    return True, None


@app.before_request
def verificar_ventana():
    if ventana_cerrada and request.endpoint not in (None,):
        if request.path.startswith("/api/") or request.path == "/login":
            return jsonify({"error": "Ventana de administración cerrada."}), 503


@app.route("/")
def index():
    if ventana_cerrada:
        return (
            "<h1>Ventana cerrada</h1><p>El portal admin ya no está disponible.</p>",
            503,
        )
    if not session.get("autenticado"):
        return redirect(url_for("login_page"))
    return send_from_directory(app.static_folder, "index.html")


@app.route("/login", methods=["GET"])
def login_page():
    if ventana_cerrada:
        return (
            "<h1>Ventana cerrada</h1><p>El portal admin ya no está disponible.</p>",
            503,
        )
    if session.get("autenticado"):
        return redirect(url_for("index"))
    return send_from_directory(app.static_folder, "login.html")


@app.route("/login", methods=["POST"])
def login_post():
    if ventana_cerrada:
        return jsonify({"error": "Ventana de administración cerrada."}), 503
    body = request.get_json(silent=True) or request.form
    usuario = body.get("usuario", "")
    clave = body.get("clave", "")
    if credenciales_validas(usuario, clave):
        session["autenticado"] = True
        session.permanent = False
        logger.info("Login exitoso desde %s", request.remote_addr)
        return jsonify({"ok": True})
    logger.warning("Login fallido desde %s", request.remote_addr)
    return jsonify({"error": "Usuario o clave incorrectos."}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    video_path = None
    try:
        raw = leer_config_raw()
        if isinstance(raw, dict):
            video_path = raw.get("video", {}).get("path")
    except (json.JSONDecodeError, OSError):
        pass
    return jsonify(
        {
            "version": __version__,
            "ventana_abierta": not ventana_cerrada,
            "segundos_restantes": segundos_restantes(),
            "video_path": video_path,
            "autenticado": bool(session.get("autenticado")),
            "ssid": portal_cfg["hotspot"]["ssid"],
        }
    )


@app.route("/api/config", methods=["GET"])
@requiere_login
def api_get_config():
    try:
        data = leer_config_raw()
    except json.JSONDecodeError as e:
        return jsonify({"error": f"JSON inválido en config: {e}"}), 500
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    if data is None:
        return jsonify({"error": "config.json no encontrado."}), 404
    return jsonify(data)


@app.route("/api/config", methods=["PUT"])
@requiere_login
def api_put_config():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Se esperaba un objeto JSON."}), 400
    cfg, errores = guardar_config(data)
    if errores:
        return jsonify({"error": "Validación fallida.", "detalles": errores}), 400
    reiniciar_reproductor()
    return jsonify({"ok": True, "video_path": cfg["video"]["path"]})


@app.route("/api/video", methods=["POST"])
@requiere_login
def api_upload_video():
    if "video" not in request.files:
        return jsonify({"error": "Campo 'video' requerido."}), 400
    archivo = request.files["video"]
    if not archivo or not archivo.filename:
        return jsonify({"error": "No se recibió archivo."}), 400

    try:
        raw = leer_config_raw()
    except (json.JSONDecodeError, OSError) as e:
        return jsonify({"error": str(e)}), 500
    if not isinstance(raw, dict):
        return jsonify({"error": "config.json no encontrado o inválido."}), 400

    destino = raw.get("video", {}).get("path", "").strip()
    if not destino:
        return jsonify({"error": "config.json: video.path vacío."}), 400

    dest_dir = os.path.dirname(destino) or "/"
    os.makedirs(dest_dir, exist_ok=True)
    tmp_path = destino + ".upload.tmp"

    try:
        archivo.save(tmp_path)
        ok, err = validar_video_ffprobe(tmp_path)
        if not ok:
            os.remove(tmp_path)
            return jsonify({"error": f"Video inválido: {err}"}), 400
        if os.path.isfile(destino):
            shutil.copy2(destino, destino + ".bak")
        os.replace(tmp_path, destino)
        os.chmod(destino, 0o644)
        _chown_video_user(destino)
    except OSError as e:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
        return jsonify({"error": f"Error guardando video: {e}"}), 500

    reiniciar_reproductor()
    logger.info("Video actualizado: %s", destino)
    return jsonify({"ok": True, "path": destino})


def cerrar_ventana():
    global ventana_cerrada
    ventana_cerrada = True
    shutdown_event.set()
    logger.info(
        "Ventana de administración cerrada (%s min).",
        portal_cfg.get("ventana_minutos", "?"),
    )


def timer_ventana():
    restante = segundos_restantes()
    if restante > 0:
        time.sleep(restante)
    cerrar_ventana()


shutdown_event = threading.Event()


def main():
    global portal_cfg, ventana_fin_monotonic, wifi_ifname, ventana_cerrada

    logger.info("Iniciando video-admin v%s...", __version__)

    try:
        portal_cfg = cargar_portal_config()
    except (ValueError, json.JSONDecodeError, OSError) as e:
        logger.error("Error cargando portal.json: %s", e)
        sys.exit(1)

    max_gb = portal_cfg.get("max_upload_gb", 8)
    app.config["MAX_CONTENT_LENGTH"] = int(max_gb * 1024 * 1024 * 1024)
    app.secret_key = os.environ.get(
        "PORTAL_SECRET", secrets.token_hex(32)
    )

    ventana_fin_monotonic = time.monotonic() + portal_cfg["ventana_minutos"] * 60

    def sig_handler(signum, frame):
        logger.info("Señal %s recibida; cerrando portal.", signum)
        shutdown_event.set()

    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    try:
        wifi_ifname = hotspot.setup_hotspot(
            portal_cfg["hotspot"]["ssid"],
            portal_cfg["hotspot"]["clave"],
        )
        gw = hotspot.hotspot_gateway_ip(wifi_ifname)
        puerto = portal_cfg["puerto"]
        logger.info(
            "Portal disponible ~%s min: http://%s:%s (SSID=%s)",
            portal_cfg["ventana_minutos"],
            gw,
            puerto,
            portal_cfg["hotspot"]["ssid"],
        )
    except (RuntimeError, ValueError) as e:
        logger.error("No se pudo activar hotspot: %s", e)
        sys.exit(1)

    timer_thread = threading.Thread(target=timer_ventana, daemon=True)
    timer_thread.start()

    try:
        from werkzeug.serving import make_server

        server = make_server("0.0.0.0", portal_cfg["puerto"], app, threaded=True)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        while not shutdown_event.is_set():
            time.sleep(0.2)
        server.shutdown()
    finally:
        hotspot.teardown_hotspot()
        logger.info("video-admin finalizado.")


if __name__ == "__main__":
    main()
