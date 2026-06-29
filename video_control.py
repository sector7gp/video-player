"""Control de video ffplay + GPIO para Raspberry Pi 5 — v2.2.0"""
__version__ = "2.2.0"

import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
import logging
from gpiozero import Button
from gpiozero.pins.lgpio import LGPIOFactory

# Obtener ruta del directorio del script para el archivo de log
script_dir = os.path.dirname(os.path.abspath(__file__))
log_path = os.path.join(script_dir, "control.log")

# Configurar logging (consola y archivo)
logger = logging.getLogger("video_control")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Manejador de archivo
file_handler = logging.FileHandler(log_path)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Manejador de consola
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

logger.info(f"Iniciando video-player v{__version__}...")

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


def _deep_merge(base, override):
    """Fusiona override sobre base (solo dicts anidados)."""
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _log_resumen_config(cfg):
    cues = cfg["cuepoints"]
    audio = cfg["audio"]
    logger.info(
        f"Config cargada: video={cfg['video']['path']} | "
        f"CUE1={cues['cue1_ms']} CUE2={cues['cue2_ms']} CUE3={cues['cue3_ms']} "
        f"CUE4={cues['cue4_ms']} CUE5={cues['cue5_ms']} CUE6={cues['cue6_ms']} "
        f"CUE7={cues['cue7_ms']} CUE8={cues['cue8_ms']} CUE9={cues['cue9_ms']} ms | "
        f"timer={cfg['timer_minutos']} min | "
        f"audio={audio['salida']} | "
        f"boton1_largo={cfg['boton1_largo']['segundos']}s | "
        f"salir_app={cfg['boton1_largo']['salir_app_segundos']}s"
    )


def cargar_config():
    """Carga config.json; valida y devuelve dict con tiempos y ruta del video."""
    config_path = os.environ.get(
        "CONFIG_PATH", os.path.join(script_dir, "config.json")
    )
    cfg = dict(CONFIG_DEFAULT)

    if not os.path.isfile(config_path):
        logger.warning(
            f"No se encontró {config_path}; usando valores por defecto."
        )
        _log_resumen_config(cfg)
        return cfg

    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido en {config_path}: {e}")
        sys.exit(1)

    if not isinstance(data, dict):
        logger.error(f"config.json debe ser un objeto JSON en {config_path}.")
        sys.exit(1)

    cfg = _deep_merge(CONFIG_DEFAULT, data)

    video_path = cfg.get("video", {}).get("path", "").strip()
    if not video_path:
        logger.error("config.json: video.path no puede estar vacío.")
        sys.exit(1)
    if not os.path.isfile(video_path):
        logger.error(f"config.json: el archivo de video no existe: {video_path}")
        sys.exit(1)

    audio = cfg.get("audio")
    if not isinstance(audio, dict):
        logger.error("config.json: audio debe ser un objeto.")
        sys.exit(1)
    salida = str(audio.get("salida", "")).strip().lower()
    if salida not in ("hdmi", "externa"):
        logger.error("config.json: audio.salida debe ser 'hdmi' o 'externa'.")
        sys.exit(1)
    for key in ("alsa_hdmi", "alsa_externa"):
        value = str(audio.get(key, "")).strip()
        if not value:
            logger.error(f"config.json: audio.{key} no puede estar vacío.")
            sys.exit(1)

    cues = cfg["cuepoints"]
    valores_cue = []
    for key in CUE_KEYS:
        valor = cues.get(key)
        if not isinstance(valor, (int, float)):
            logger.error(f"config.json: cuepoints.{key} debe ser un número.")
            sys.exit(1)
        if valor < 0:
            logger.error(f"config.json: cuepoints.{key} debe ser >= 0.")
            sys.exit(1)
        valores_cue.append(int(valor))

    for i in range(len(valores_cue) - 1):
        if valores_cue[i] >= valores_cue[i + 1]:
            logger.error(
                f"config.json: los cuepoints deben ser estrictamente crecientes "
                f"({CUE_KEYS[i]}={valores_cue[i]} >= {CUE_KEYS[i + 1]}={valores_cue[i + 1]})."
            )
            sys.exit(1)

    timer_minutos = cfg.get("timer_minutos")
    if not isinstance(timer_minutos, (int, float)) or timer_minutos <= 0:
        logger.error("config.json: timer_minutos debe ser un número > 0.")
        sys.exit(1)

    boton1_largo = cfg.get("boton1_largo")
    if not isinstance(boton1_largo, dict):
        logger.error("config.json: boton1_largo debe ser un objeto.")
        sys.exit(1)
    hold_s = boton1_largo.get("segundos")
    if not isinstance(hold_s, (int, float)) or hold_s <= 0:
        logger.error("config.json: boton1_largo.segundos debe ser un número > 0.")
        sys.exit(1)
    salir_app_s = boton1_largo.get("salir_app_segundos")
    if not isinstance(salir_app_s, (int, float)) or salir_app_s <= 0:
        logger.error(
            "config.json: boton1_largo.salir_app_segundos debe ser un número > 0."
        )
        sys.exit(1)
    if salir_app_s <= hold_s:
        logger.error(
            "config.json: boton1_largo.salir_app_segundos debe ser mayor que boton1_largo.segundos."
        )
        sys.exit(1)
    comando = str(boton1_largo.get("comando", "")).strip()
    if not comando:
        logger.error("config.json: boton1_largo.comando no puede estar vacío.")
        sys.exit(1)
    overlay = boton1_largo.get("overlay")
    if not isinstance(overlay, dict):
        logger.error("config.json: boton1_largo.overlay debe ser un objeto.")
        sys.exit(1)
    texto = str(overlay.get("texto", "")).strip()
    if not texto:
        logger.error("config.json: boton1_largo.overlay.texto no puede estar vacío.")
        sys.exit(1)
    tamano = overlay.get("tamano")
    if not isinstance(tamano, (int, float)) or tamano <= 0:
        logger.error("config.json: boton1_largo.overlay.tamano debe ser un número > 0.")
        sys.exit(1)
    if not isinstance(overlay.get("centrado"), bool):
        logger.error("config.json: boton1_largo.overlay.centrado debe ser true/false.")
        sys.exit(1)
    opacidad = overlay.get("opacidad")
    if not isinstance(opacidad, (int, float)) or not (0 <= int(opacidad) <= 255):
        logger.error("config.json: boton1_largo.overlay.opacidad debe estar entre 0 y 255.")
        sys.exit(1)
    color_hex = str(overlay.get("color_hex", "")).strip().lstrip("#")
    if len(color_hex) != 6:
        logger.error("config.json: boton1_largo.overlay.color_hex debe tener 6 hex dígitos.")
        sys.exit(1)
    try:
        int(color_hex, 16)
    except ValueError:
        logger.error("config.json: boton1_largo.overlay.color_hex es inválido.")
        sys.exit(1)
    if not isinstance(overlay.get("sombra_roja"), bool):
        logger.error("config.json: boton1_largo.overlay.sombra_roja debe ser true/false.")
        sys.exit(1)

    _log_resumen_config(cfg)
    return cfg


def formatear_duracion(ms):
    """Convierte milisegundos a mm:ss."""
    if ms < 0:
        return "desconocida"
    total_s = int(ms // 1000)
    minutos, segundos = divmod(total_s, 60)
    return f"{minutos}:{segundos:02d}"


def _fps_desde_ffprobe(valor):
    if not valor or "/" not in valor:
        return 0.0
    num, den = valor.split("/", 1)
    try:
        num_i = int(num)
        den_i = int(den)
        return num_i / den_i if den_i else 0.0
    except ValueError:
        return 0.0


def _ffprobe_json(path):
    """Lee metadata JSON con ffprobe. Devuelve dict o None."""
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", path,
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _log_ffprobe(path):
    """Loguea metadata via ffprobe. Devuelve duración en ms o -1."""
    data = _ffprobe_json(path)
    if not data:
        return -1

    duracion_ms = -1
    fmt = data.get("format", {})
    duracion_s = float(fmt.get("duration", 0) or 0)
    if duracion_s > 0:
        duracion_ms = int(duracion_s * 1000)
        logger.info(
            f"Duración: {duracion_ms} ms ({formatear_duracion(duracion_ms)}) [ffprobe]"
        )

    for stream in data.get("streams", []):
        tipo = stream.get("codec_type")
        codec = (stream.get("codec_name") or "?").upper()
        if tipo == "video":
            ancho = stream.get("width")
            alto = stream.get("height")
            fps = _fps_desde_ffprobe(stream.get("r_frame_rate"))
            logger.info(
                f"Pista video: {codec} {ancho}x{alto} @ {fps:.2f} fps [ffprobe]"
            )
        elif tipo == "audio":
            rate = stream.get("sample_rate", "?")
            canales = stream.get("channels", "?")
            logger.info(
                f"Pista audio: {codec} {rate} Hz, {canales} canales [ffprobe]"
            )
    return duracion_ms


def _recolectar_y_loguear_metadatos(path):
    """Registra metadatos del video para troubleshooting."""
    global video_duracion_ms
    logger.info(f"Video: {path}")
    duracion = _log_ffprobe(path)
    if duracion > 0:
        video_duracion_ms = duracion
    else:
        logger.warning(
            "Especificaciones de pistas no disponibles. "
            "Instalá ffmpeg para logs completos: sudo apt install -y ffmpeg"
        )


def iniciar_log_metadatos_en_background(path):
    """Lanza la lectura de metadatos en un hilo aparte para no frenar play()."""

    def trabajo():
        try:
            _recolectar_y_loguear_metadatos(path)
        except Exception as e:
            logger.warning(f"Error al leer metadatos del video: {e}")

    threading.Thread(
        target=trabajo, daemon=True, name="metadatos-video"
    ).start()


config = cargar_config()
PATH_VIDEO = config["video"]["path"]
CUE1 = int(config["cuepoints"]["cue1_ms"])
CUE2 = int(config["cuepoints"]["cue2_ms"])
CUE3 = int(config["cuepoints"]["cue3_ms"])
CUE4 = int(config["cuepoints"]["cue4_ms"])
CUE5 = int(config["cuepoints"]["cue5_ms"])
CUE6 = int(config["cuepoints"]["cue6_ms"])
CUE7 = int(config["cuepoints"]["cue7_ms"])
CUE8 = int(config["cuepoints"]["cue8_ms"])
CUE9 = int(config["cuepoints"]["cue9_ms"])
TIMER_MINUTOS = float(config["timer_minutos"])
TIMER_SEGUNDOS = TIMER_MINUTOS * 60.0
BOTON1_LARGO_SEGUNDOS = float(config["boton1_largo"]["segundos"])
BOTON1_SALIR_APP_SEGUNDOS = float(config["boton1_largo"]["salir_app_segundos"])
BOTON1_LARGO_COMANDO = str(config["boton1_largo"]["comando"]).strip()
BOTON1_LARGO_OVERLAY_TEXTO = str(config["boton1_largo"]["overlay"]["texto"])
BOTON1_LARGO_OVERLAY_TAMANO = int(config["boton1_largo"]["overlay"]["tamano"])
BOTON1_LARGO_OVERLAY_CENTRADO = bool(config["boton1_largo"]["overlay"]["centrado"])
BOTON1_LARGO_OVERLAY_COLOR = int(
    str(config["boton1_largo"]["overlay"]["color_hex"]).strip().lstrip("#"),
    16,
)
BOTON1_LARGO_OVERLAY_OPACIDAD = int(config["boton1_largo"]["overlay"]["opacidad"])
BOTON1_LARGO_OVERLAY_SOMBRA_ROJA = bool(
    config["boton1_largo"]["overlay"]["sombra_roja"]
)

# GPIO (Raspberry Pi 5, chip 0) — pull-up interno, botón a GND
GPIO_BOTON1 = 23
GPIO_BOTON2 = 24

# Configuración específica para Raspberry Pi 5
try:
    factory = LGPIOFactory(chip=0)
    boton1 = Button(
        GPIO_BOTON1, pull_up=True, pin_factory=factory, bounce_time=0.05
    )
    boton2 = Button(
        GPIO_BOTON2, pull_up=True, pin_factory=factory, bounce_time=0.05
    )
    logger.info(
        f"GPIO{GPIO_BOTON1} (botón1) y GPIO{GPIO_BOTON2} (botón2) configurados "
        "con pull-up interno y filtro antirrebote."
    )
except Exception as e:
    logger.error(f"Error al configurar GPIO: {e}")
    sys.exit(1)

# Audio centralizado en config.json con override opcional por variables de entorno.
def _resolver_audio(config):
    cfg_audio = config["audio"]
    salida_cfg = str(cfg_audio.get("salida", "hdmi")).strip().lower()
    alsa_hdmi_cfg = str(cfg_audio.get("alsa_hdmi", "")).strip()
    alsa_externa_cfg = str(cfg_audio.get("alsa_externa", "")).strip()

    salida = os.environ.get("AUDIO_SALIDA", salida_cfg).strip().lower()
    alsa_hdmi = os.environ.get("ALSA_HDMI", alsa_hdmi_cfg).strip()
    alsa_externa = os.environ.get("ALSA_EXTERNA", alsa_externa_cfg).strip()
    return salida, alsa_hdmi, alsa_externa


AUDIO_SALIDA, ALSA_HDMI, ALSA_EXTERNA = _resolver_audio(config)


def _normalizar_alsa_para_sdl(device):
    """Convierte plughw:CARD=xxx,DEV=y a plughw:xxx,y para AUDIODEV."""
    raw = (device or "").strip()
    if "CARD=" in raw and "DEV=" in raw:
        try:
            prefijo, resto = raw.split(":", 1)
            partes = [p.strip() for p in resto.split(",") if p.strip()]
            kv = {}
            for parte in partes:
                k, v = parte.split("=", 1)
                kv[k.strip().upper()] = v.strip()
            card = kv.get("CARD")
            dev = kv.get("DEV")
            if card and dev:
                return f"{prefijo}:{card},{dev}"
        except Exception:
            return raw
    return raw


def opciones_ffplay():
    """Resuelve device de audio y etiqueta para ffplay/SDL."""
    if AUDIO_SALIDA == "externa":
        device = _normalizar_alsa_para_sdl(ALSA_EXTERNA)
        etiqueta = "placa externa"
    elif AUDIO_SALIDA == "hdmi":
        device = _normalizar_alsa_para_sdl(ALSA_HDMI)
        etiqueta = "HDMI"
    else:
        logger.warning(
            f"AUDIO_SALIDA='{AUDIO_SALIDA}' no válido (use hdmi o externa). Usando HDMI."
        )
        device = _normalizar_alsa_para_sdl(ALSA_HDMI)
        etiqueta = "HDMI (fallback)"
    return device, etiqueta

TOLERANCIA_MS = 80
DEBOUNCE_BOTON_S = 0.40
PULSO_MINIMO_S = 0.05

MODO_PRESENTACION = "presentacion"
MODO_OUTRO = "outro_presentacion"
MODO_SESION_A = "sesion_a"
MODO_SESION_B = "sesion_b"
MODO_FINALE = "finale"

modo = MODO_PRESENTACION
timer_fin = None
posicion_guardada_ms = None
esperando_seek = False
ultimo_reintento_fin = 0.0
momento_presion_boton1 = 0.0
momento_presion_boton2 = 0.0
ultimo_boton1 = 0.0
ultimo_boton2 = 0.0
boton1_hold_token = 0
boton1_overlay_visible = False
salir_solicitado = threading.Event()

FFPLAY_BIN = os.environ.get("FFPLAY_BIN", "ffplay").strip() or "ffplay"
FFPLAY_LOGLEVEL = os.environ.get("FFPLAY_LOGLEVEL", "warning").strip() or "warning"
FFPLAY_EXTRA_ARGS = shlex.split(os.environ.get("FFPLAY_EXTRA_ARGS", "").strip())

alsa_device, audio_etiqueta = opciones_ffplay()
ffplay_env = dict(os.environ)
ffplay_env["SDL_AUDIODRIVER"] = "alsa"
ffplay_env["AUDIODEV"] = alsa_device

player_process = None
player_lock = threading.Lock()
player_esperado_activo = False
player_anchor_ms = 0
player_anchor_monotonic = None

video_duracion_ms = -1

PLAYER_STATE_PLAYING = "playing"
PLAYER_STATE_ENDED = "ended"
PLAYER_STATE_STOPPED = "stopped"


def _ffplay_disponible():
    if "/" in FFPLAY_BIN:
        return os.path.isfile(FFPLAY_BIN) and os.access(FFPLAY_BIN, os.X_OK)
    return shutil.which(FFPLAY_BIN) is not None


def _comando_ffplay(start_ms):
    return [
        FFPLAY_BIN,
        "-hide_banner",
        "-loglevel",
        FFPLAY_LOGLEVEL,
        "-nostats",
        "-autoexit",
        "-fs",
        "-sync",
        "audio",
        "-ss",
        f"{max(0, int(start_ms)) / 1000:.3f}",
        *FFPLAY_EXTRA_ARGS,
        PATH_VIDEO,
    ]


def _detener_ffplay_locked():
    global player_process
    if player_process is None:
        return
    if player_process.poll() is None:
        player_process.terminate()
        try:
            player_process.wait(timeout=1.5)
        except subprocess.TimeoutExpired:
            player_process.kill()
            try:
                player_process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                pass
    player_process = None


def stop_player():
    """Detiene el proceso ffplay actual."""
    global player_esperado_activo, player_anchor_monotonic
    with player_lock:
        player_esperado_activo = False
        player_anchor_monotonic = None
        _detener_ffplay_locked()


def play_from(ms):
    """Reinicia ffplay desde un offset en ms."""
    global player_process, player_esperado_activo, player_anchor_ms, player_anchor_monotonic
    cmd = _comando_ffplay(ms)
    with player_lock:
        _detener_ffplay_locked()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=ffplay_env,
                start_new_session=True,
            )
        except Exception as e:
            logger.error(f"No se pudo lanzar ffplay: {e}")
            raise
        player_esperado_activo = True
        player_anchor_ms = max(0, int(ms))
        player_anchor_monotonic = time.monotonic()
        player_process = proc


def current_time_ms():
    """Tiempo de reproducción estimado usando reloj monotónico."""
    with player_lock:
        if not player_esperado_activo or player_anchor_monotonic is None:
            return -1
        estimado = int(
            player_anchor_ms + (time.monotonic() - player_anchor_monotonic) * 1000
        )
    if video_duracion_ms > 0:
        return min(estimado, video_duracion_ms)
    return estimado


def is_running():
    """Indica si ffplay sigue activo."""
    with player_lock:
        return player_process is not None and player_process.poll() is None


def player_state():
    if not is_running():
        if player_esperado_activo:
            return PLAYER_STATE_ENDED
        return PLAYER_STATE_STOPPED
    return PLAYER_STATE_PLAYING


def ir_a_tiempo(ms):
    """Seek por relanzamiento de ffplay desde el tiempo solicitado."""
    global esperando_seek
    play_from(ms)
    esperando_seek = True


def _timer_activo():
    return timer_fin is not None and time.monotonic() < timer_fin


def _iniciar_timer():
    global timer_fin
    timer_fin = time.monotonic() + TIMER_SEGUNDOS
    logger.info(f"Timer iniciado: {TIMER_MINUTOS} min (expira en {TIMER_SEGUNDOS:.0f} s).")


def _cancelar_timer():
    global timer_fin
    if timer_fin is not None:
        logger.info("Timer cancelado.")
    timer_fin = None


def _cambiar_modo(nuevo_modo, ms_destino, motivo):
    global modo, esperando_seek
    modo = nuevo_modo
    logger.info(f"Modo → {nuevo_modo} ({motivo}). Seek a {ms_destino} ms.")
    ir_a_tiempo(ms_destino)


def ir_a_presentacion(motivo):
    global posicion_guardada_ms
    posicion_guardada_ms = None
    _cancelar_timer()
    _cambiar_modo(MODO_PRESENTACION, CUE1, motivo)


def _loop_del_modo():
    if modo == MODO_PRESENTACION:
        return CUE1, CUE2
    if modo == MODO_OUTRO:
        return None, None
    if modo == MODO_SESION_A and _timer_activo():
        return CUE4, CUE5
    if modo == MODO_SESION_B and _timer_activo():
        return CUE6, CUE7
    return None, None


def _seek_completado(current_time, inicio, fin):
    """True si el seek terminó (cerca del inicio o dentro del tramo del loop)."""
    if current_time < 0:
        return False
    if current_time <= inicio + TOLERANCIA_MS:
        return True
    return inicio <= current_time <= fin


def _verificar_timer_vencido():
    global modo
    if modo not in (MODO_OUTRO, MODO_SESION_A, MODO_SESION_B):
        return
    if timer_fin is None or time.monotonic() < timer_fin:
        return
    _cancelar_timer()
    _cambiar_modo(MODO_FINALE, CUE8, "timer completado")


def _verificar_transicion_outro(current_time):
    global modo
    if modo != MODO_OUTRO:
        return
    if current_time >= 0 and current_time >= CUE4:
        modo = MODO_SESION_A
        logger.info("Outro finalizado (CUE3→CUE4). Modo → sesion_a (loop CUE4-CUE5).")


def _gestionar_loop(current_time, state):
    global esperando_seek, modo, ultimo_reintento_fin

    _verificar_timer_vencido()
    _verificar_transicion_outro(current_time)

    if modo == MODO_FINALE:
        if current_time >= 0 and current_time >= CUE9:
            ahora = time.monotonic()
            if ahora - ultimo_reintento_fin >= 0.5:
                ultimo_reintento_fin = ahora
                ir_a_presentacion(f"timer: CUE9 ({CUE9} ms) → reinicio en CUE1")
        elif state == PLAYER_STATE_ENDED:
            ahora = time.monotonic()
            if ahora - ultimo_reintento_fin >= 0.5:
                ultimo_reintento_fin = ahora
                logger.warning("Video en Ended durante finale; reinicio en CUE1.")
                ir_a_presentacion("fin de video en finale")
        return

    inicio, fin = _loop_del_modo()
    if inicio is None:
        return

    if esperando_seek:
        if _seek_completado(current_time, inicio, fin):
            esperando_seek = False
        return

    if current_time < 0:
        return

    if current_time >= fin:
        esperando_seek = True
        logger.info(f"Loop {modo}: {current_time} ms ≥ {fin} ms → {inicio} ms.")
        ir_a_tiempo(inicio)


def _pulso_valido(duracion, ultimo, nombre):
    if duracion < PULSO_MINIMO_S:
        logger.info(f"{nombre}: pulsación ignorada (demasiado corta, rebote).")
        return False
    if time.monotonic() - ultimo < DEBOUNCE_BOTON_S:
        logger.info(f"{nombre}: pulsación ignorada (antirebote software).")
        return False
    return True


def registrar_presion_boton1():
    global momento_presion_boton1, boton1_hold_token
    momento_presion_boton1 = time.monotonic()
    boton1_hold_token += 1
    token = boton1_hold_token
    threading.Thread(
        target=_monitor_pulsacion_larga_boton1,
        args=(token, momento_presion_boton1),
        daemon=True,
        name="boton1-largo-monitor",
    ).start()


def _set_marquee_visible(show, text=BOTON1_LARGO_OVERLAY_TEXTO):
    """Compatibilidad de interfaz: ffplay no soporta marquee dinámico."""
    if show:
        logger.info(
            "Overlay omitido en backend ffplay: no hay soporte marquee en esta fase."
        )
    return False


def _mostrar_overlay_boton1_largo():
    global boton1_overlay_visible
    if boton1_overlay_visible:
        return
    _set_marquee_visible(True)
    boton1_overlay_visible = True


def _ocultar_overlay_boton1_largo():
    global boton1_overlay_visible
    if not boton1_overlay_visible:
        return
    _set_marquee_visible(False)
    boton1_overlay_visible = False


def _monitor_pulsacion_larga_boton1(token, inicio):
    """Si sigue presionado al cumplir el umbral, muestra overlay."""
    deadline = inicio + BOTON1_LARGO_SEGUNDOS
    while time.monotonic() < deadline:
        if token != boton1_hold_token or not boton1.is_pressed:
            return
        time.sleep(0.05)
    if token == boton1_hold_token and boton1.is_pressed:
        _mostrar_overlay_boton1_largo()


def _ejecutar_comando_boton1_largo():
    """Ejecuta comando de recuperación para pulsación larga de botón1."""
    logger.warning(
        f"GPIO23: pulsación larga detectada (>= {BOTON1_LARGO_SEGUNDOS}s). "
        f"Ejecutando comando: {BOTON1_LARGO_COMANDO}"
    )
    try:
        result = subprocess.run(
            BOTON1_LARGO_COMANDO,
            shell=True,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode == 0:
            logger.info("Comando de pulsación larga ejecutado correctamente.")
        else:
            salida = (result.stderr or result.stdout or "").strip()
            logger.error(
                f"Comando de pulsación larga falló (exit {result.returncode}): {salida}"
            )
    except Exception as e:
        logger.error(f"Error ejecutando comando de pulsación larga: {e}")


def _solicitar_salida_app():
    """Solicita terminar la app de forma limpia desde el loop principal."""
    logger.warning(
        f"GPIO23: pulsación muy larga detectada (>= {BOTON1_SALIR_APP_SEGUNDOS}s). "
        "Cerrando aplicación..."
    )
    salir_solicitado.set()


def boton1_al_soltar():
    """Botón1: sesión / entra o sale del loop CUE6-CUE7 (toggle con posición guardada)."""
    global ultimo_boton1, modo, posicion_guardada_ms, boton1_hold_token
    boton1_hold_token += 1  # invalida monitor de pulsación larga en curso
    duracion = time.monotonic() - momento_presion_boton1
    _ocultar_overlay_boton1_largo()
    if duracion >= BOTON1_SALIR_APP_SEGUNDOS:
        if time.monotonic() - ultimo_boton1 < DEBOUNCE_BOTON_S:
            logger.info("GPIO23: pulsación muy larga ignorada (antirebote software).")
            return
        ultimo_boton1 = time.monotonic()
        _solicitar_salida_app()
        return
    if duracion >= BOTON1_LARGO_SEGUNDOS:
        if time.monotonic() - ultimo_boton1 < DEBOUNCE_BOTON_S:
            logger.info("GPIO23: pulsación larga ignorada (antirebote software).")
            return
        ultimo_boton1 = time.monotonic()
        threading.Thread(
            target=_ejecutar_comando_boton1_largo,
            daemon=True,
            name="boton1-largo",
        ).start()
        return

    if not _pulso_valido(duracion, ultimo_boton1, "GPIO23"):
        return
    ultimo_boton1 = time.monotonic()

    if modo == MODO_PRESENTACION:
        posicion_guardada_ms = None
        _iniciar_timer()
        _cambiar_modo(MODO_OUTRO, CUE3, "botón1 en presentación (outro)")
        return

    if modo == MODO_SESION_A and _timer_activo():
        current = current_time_ms()
        posicion_guardada_ms = current if current >= 0 else 0
        _cambiar_modo(MODO_SESION_B, CUE6, "botón1 dentro del timer (CUE6-CUE7)")
        logger.info(f"Posición guardada: {posicion_guardada_ms} ms.")
        return

    if modo == MODO_SESION_B and _timer_activo():
        modo = MODO_SESION_A
        if posicion_guardada_ms is not None:
            logger.info(
                f"Loop CUE6-CUE7 DESACTIVADO. Vuelve a {posicion_guardada_ms} ms."
            )
            ir_a_tiempo(posicion_guardada_ms)
        else:
            logger.info("Loop CUE6-CUE7 DESACTIVADO (sin posición guardada).")
        posicion_guardada_ms = None
        return

    logger.info(f"GPIO23: pulsación ignorada en modo {modo}.")


def registrar_presion_boton2():
    global momento_presion_boton2
    momento_presion_boton2 = time.monotonic()


def boton2_al_soltar():
    """Botón2: en cualquier momento vuelve a CUE1 (presentación)."""
    global ultimo_boton2
    duracion = time.monotonic() - momento_presion_boton2
    if not _pulso_valido(duracion, ultimo_boton2, "GPIO24"):
        return
    ultimo_boton2 = time.monotonic()
    ir_a_presentacion("botón2")


boton1.when_pressed = registrar_presion_boton1
boton1.when_released = boton1_al_soltar
boton2.when_pressed = registrar_presion_boton2
boton2.when_released = boton2_al_soltar

if not _ffplay_disponible():
    logger.error(
        f"No se encontró ejecutable ffplay ('{FFPLAY_BIN}'). "
        "Instalá ffmpeg: sudo apt install -y ffmpeg"
    )
    sys.exit(1)

logger.info(f"Backend de reproducción: ffplay ({FFPLAY_BIN})")
logger.info(f"Audio: {audio_etiqueta} ({alsa_device})")
logger.info("Iniciando reproducción (presentación CUE1-CUE2)...")
ir_a_tiempo(CUE1)
iniciar_log_metadatos_en_background(PATH_VIDEO)

try:
    while True:
        if salir_solicitado.is_set():
            logger.info("Salida solicitada por botón1 (pulsación > umbral).")
            break
        state = player_state()
        current_time = current_time_ms()
        _gestionar_loop(current_time, state)
        time.sleep(0.05)

except KeyboardInterrupt:
    logger.info("Interrupción por teclado detectada. Saliendo de la aplicación...")
finally:
    stop_player()
    logger.info("Programa finalizado.")
