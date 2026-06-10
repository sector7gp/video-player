"""Control de video VLC + GPIO para Raspberry Pi 5 — v1.3.0"""
__version__ = "1.3.0"

import json
import os
import sys
import vlc
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
    "loop_corto": {"inicio_ms": 14000, "fin_ms": 14500},
    "loop_principal": {
        "inicio_ms": 20,
        "fin_ms": 0,
        "margen_antes_fin_ms": 400,
    },
}


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
    loop_corto = cfg["loop_corto"]
    loop_principal = cfg["loop_principal"]
    if loop_principal["fin_ms"] > 0:
        umbral = f"umbral fin {loop_principal['fin_ms']} ms"
    else:
        umbral = (
            f"umbral fin auto (margen {loop_principal['margen_antes_fin_ms']} ms)"
        )
    logger.info(
        f"Config cargada: video={cfg['video']['path']} | "
        f"loop corto {loop_corto['inicio_ms']}-{loop_corto['fin_ms']} ms | "
        f"reinicio a {loop_principal['inicio_ms']} ms | {umbral}"
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

    loop_corto = cfg["loop_corto"]
    inicio_corto = loop_corto.get("inicio_ms")
    fin_corto = loop_corto.get("fin_ms")
    if not isinstance(inicio_corto, (int, float)) or not isinstance(
        fin_corto, (int, float)
    ):
        logger.error("config.json: loop_corto.inicio_ms y fin_ms deben ser números.")
        sys.exit(1)
    if inicio_corto >= fin_corto:
        logger.error(
            f"config.json: loop_corto.inicio_ms ({inicio_corto}) "
            f"debe ser menor que fin_ms ({fin_corto})."
        )
        sys.exit(1)

    loop_principal = cfg["loop_principal"]
    inicio_principal = loop_principal.get("inicio_ms")
    fin_principal = loop_principal.get("fin_ms")
    margen = loop_principal.get("margen_antes_fin_ms")
    for nombre, valor in (
        ("loop_principal.inicio_ms", inicio_principal),
        ("loop_principal.fin_ms", fin_principal),
        ("loop_principal.margen_antes_fin_ms", margen),
    ):
        if not isinstance(valor, (int, float)):
            logger.error(f"config.json: {nombre} debe ser un número.")
            sys.exit(1)
    if inicio_principal < 0 or fin_principal < 0:
        logger.error("config.json: loop_principal.inicio_ms y fin_ms deben ser >= 0.")
        sys.exit(1)
    if margen <= 0:
        logger.error("config.json: loop_principal.margen_antes_fin_ms debe ser > 0.")
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


def _puntero_struct(puntero):
    """Resuelve POINTER(ctypes.Structure) a su contenido."""
    if puntero is None:
        return None
    return puntero.contents if hasattr(puntero, "contents") else puntero[0]


def registrar_info_video(media, path):
    """Registra duración y especificaciones del video en los logs."""
    logger.info(f"Video: {path}")

    duracion = media.get_duration()
    if duracion > 0:
        logger.info(f"Duración: {duracion} ms ({formatear_duracion(duracion)})")
    else:
        logger.warning("Duración del video no disponible tras el parse.")

    try:
        tracks = media.tracks_get()
    except Exception as e:
        logger.warning(f"No se pudieron leer las pistas del video: {e}")
        return

    if not tracks:
        logger.warning("Sin pistas detectadas en el video.")
        return

    for track in tracks:
        codec = vlc.libvlc_media_get_codec_description(track.type, track.codec)
        if track.type == vlc.TrackType.video:
            vt = _puntero_struct(track.u.video)
            if vt and vt.width and vt.height:
                fps = (
                    vt.frame_rate_num / vt.frame_rate_den
                    if vt.frame_rate_den
                    else 0.0
                )
                logger.info(
                    f"Pista video: {codec} {vt.width}x{vt.height} @ {fps:.2f} fps"
                )
            else:
                logger.info(f"Pista video: {codec}")
        elif track.type == vlc.TrackType.audio:
            at = _puntero_struct(track.u.audio)
            if at and at.rate:
                logger.info(
                    f"Pista audio: {codec} {at.rate} Hz, {at.channels} canales"
                )
            else:
                logger.info(f"Pista audio: {codec}")


config = cargar_config()
PATH_VIDEO = config["video"]["path"]
INICIO_LOOP_MS = int(config["loop_corto"]["inicio_ms"])
FIN_LOOP_MS = int(config["loop_corto"]["fin_ms"])
RESTART_MS = int(config["loop_principal"]["inicio_ms"])
REINICIO_LOOP_MS = int(config["loop_principal"]["fin_ms"])
MARGEN_ANTES_FIN_MS = int(config["loop_principal"]["margen_antes_fin_ms"])

# GPIO (Raspberry Pi 5, chip 0) — pull-up interno, botón a GND
GPIO_LOOP = 23       # toggle loop corto
GPIO_REINICIO = 24   # reinicio rápido al inicio del video

# Configuración específica para Raspberry Pi 5
try:
    factory = LGPIOFactory(chip=0)
    boton_loop = Button(
        GPIO_LOOP, pull_up=True, pin_factory=factory, bounce_time=0.05
    )
    boton_reinicio = Button(
        GPIO_REINICIO, pull_up=True, pin_factory=factory, bounce_time=0.05
    )
    logger.info(
        f"GPIO{GPIO_LOOP} (loop) y GPIO{GPIO_REINICIO} (reinicio) configurados "
        "con pull-up interno y filtro antirrebote."
    )
except Exception as e:
    logger.error(f"Error al configurar GPIO: {e}")
    sys.exit(1)

# Audio: "hdmi" (por defecto) o "externa" (placa USB / HAT). También: variable de entorno AUDIO_SALIDA.
# Dispositivos ALSA: listar con `aplay -l` y probar con `speaker-test -D plughw:1,0 -c2`
AUDIO_SALIDA = os.environ.get("AUDIO_SALIDA", "hdmi").strip().lower()
ALSA_HDMI = os.environ.get("ALSA_HDMI", "plughw:CARD=vc4hdmi0,DEV=0")
ALSA_EXTERNA = os.environ.get("ALSA_EXTERNA", "plughw:1,0")


def opciones_vlc():
    """Opciones de instancia VLC (video + audio ALSA)."""
    opts = ["--input-repeat=-1", "--aout=alsa"]
    if AUDIO_SALIDA == "externa":
        device = ALSA_EXTERNA
        etiqueta = "placa externa"
    elif AUDIO_SALIDA == "hdmi":
        device = ALSA_HDMI
        etiqueta = "HDMI"
    else:
        logger.warning(
            f"AUDIO_SALIDA='{AUDIO_SALIDA}' no válido (use hdmi o externa). Usando HDMI."
        )
        device = ALSA_HDMI
        etiqueta = "HDMI (fallback)"
    opts.append(f"--alsa-audio-device={device}")
    return opts, device, etiqueta


# Inicializar VLC (configuración mínima, sin vout=drm ni opciones extra)
try:
    vlc_args, alsa_device, audio_etiqueta = opciones_vlc()
    instance = vlc.Instance(" ".join(vlc_args))
    player = instance.media_player_new()
    media = instance.media_new(PATH_VIDEO)
    media.add_option(":input-repeat=-1")
    media.add_option(":aout=alsa")
    media.add_option(f":alsa-audio-device={alsa_device}")
    player.set_media(media)

    parse_ok = media.parse_with_options(vlc.MediaParseFlag.local, 10000)
    if parse_ok != 0:
        logger.warning("VLC no pudo parsear el video por completo; metadatos parciales.")
    registrar_info_video(media, PATH_VIDEO)

    logger.info(f"VLC inicializado con el video: {PATH_VIDEO}")
    logger.info(f"Audio: {audio_etiqueta} ({alsa_device})")
except Exception as e:
    logger.error(f"Error al inicializar VLC: {e}")
    sys.exit(1)

TOLERANCIA_MS = 80
# Antirebote software: tiempo mínimo entre toggles y pulso válido
DEBOUNCE_TOGGLE_S = 0.40
PULSO_MINIMO_S = 0.05

estado_loop_corto = False
posicion_guardada_ms = None
esperando_seek = False
ultimo_reintento_fin = 0.0
esperando_seek_principal = False
umbral_reinicio_cache = None
momento_presion_loop = 0.0
ultimo_toggle = 0.0
ultimo_reinicio_gpio = 0.0
momento_presion_reinicio = 0.0

def asegurar_reproduciendo():
    if player.get_state() != vlc.State.Playing:
        player.play()

def ir_a_tiempo(ms):
    """Seek instantáneo; si el video terminó (Ended), stop breve y play."""
    if player.get_state() in (vlc.State.Ended, vlc.State.Stopped):
        player.stop()
        time.sleep(0.03)
    player.set_time(ms)
    player.play()

def obtener_umbral_reinicio():
    """Devuelve el tiempo (ms) en el que el loop principal vuelve a RESTART_MS."""
    global umbral_reinicio_cache
    if umbral_reinicio_cache is not None:
        return umbral_reinicio_cache
    if REINICIO_LOOP_MS > 0:
        umbral_reinicio_cache = REINICIO_LOOP_MS
    else:
        duracion = player.get_length()
        if duracion > 0:
            umbral_reinicio_cache = max(
                RESTART_MS + TOLERANCIA_MS,
                duracion - MARGEN_ANTES_FIN_MS,
            )
            logger.info(
                f"Reinicio automático del loop principal en {umbral_reinicio_cache} ms "
                f"(duración {duracion} ms, margen {MARGEN_ANTES_FIN_MS} ms)."
            )
        else:
            umbral_reinicio_cache = None
    if umbral_reinicio_cache is not None and REINICIO_LOOP_MS > 0:
        logger.info(f"Reinicio del loop principal en {umbral_reinicio_cache} ms.")
    return umbral_reinicio_cache

def iniciar_loop():
    """Toggle ON: guarda posición actual y entra al loop del tramo."""
    global estado_loop_corto, posicion_guardada_ms, esperando_seek
    current = player.get_time()
    posicion_guardada_ms = current if current >= 0 else 0
    estado_loop_corto = True
    esperando_seek = True
    ir_a_tiempo(INICIO_LOOP_MS)
    logger.info(
        f"Loop ACTIVADO ({INICIO_LOOP_MS}-{FIN_LOOP_MS} ms). "
        f"Posición guardada: {posicion_guardada_ms} ms."
    )

def detener_loop():
    """Toggle OFF: sale del loop y vuelve a la posición guardada."""
    global estado_loop_corto, esperando_seek
    estado_loop_corto = False
    esperando_seek = False
    if posicion_guardada_ms is not None:
        ir_a_tiempo(posicion_guardada_ms)
        logger.info(f"Loop DESACTIVADO. Vuelve a {posicion_guardada_ms} ms.")

def registrar_presion_loop():
    global momento_presion_loop
    momento_presion_loop = time.monotonic()

def alternar_loop_al_soltar():
    """GPIO23: press+release alterna loop ON/OFF (antirebote software)."""
    global ultimo_toggle
    ahora = time.monotonic()
    duracion = ahora - momento_presion_loop

    if duracion < PULSO_MINIMO_S:
        logger.info("GPIO23: pulsación ignorada (demasiado corta, rebote).")
        return
    if ahora - ultimo_toggle < DEBOUNCE_TOGGLE_S:
        logger.info("GPIO23: pulsación ignorada (antirebote software).")
        return

    ultimo_toggle = ahora
    if estado_loop_corto:
        detener_loop()
    else:
        iniciar_loop()

def registrar_presion_reinicio():
    global momento_presion_reinicio
    momento_presion_reinicio = time.monotonic()

def reiniciar_video_al_soltar():
    """GPIO24: press+release → seek rápido a RESTART_MS (sin stop)."""
    global ultimo_reinicio_gpio, estado_loop_corto, esperando_seek
    ahora = time.monotonic()
    duracion = ahora - momento_presion_reinicio

    if duracion < PULSO_MINIMO_S:
        logger.info("GPIO24: pulsación ignorada (demasiado corta, rebote).")
        return
    if ahora - ultimo_reinicio_gpio < DEBOUNCE_TOGGLE_S:
        logger.info("GPIO24: pulsación ignorada (antirebote software).")
        return

    ultimo_reinicio_gpio = ahora
    if estado_loop_corto:
        estado_loop_corto = False
        esperando_seek = False
        logger.info("GPIO24: loop corto desactivado por reinicio.")

    logger.info(f"GPIO24: reinicio rápido a {RESTART_MS} ms.")
    ir_a_tiempo(RESTART_MS)

boton_loop.when_pressed = registrar_presion_loop
boton_loop.when_released = alternar_loop_al_soltar
boton_reinicio.when_pressed = registrar_presion_reinicio
boton_reinicio.when_released = reiniciar_video_al_soltar

logger.info("Iniciando reproducción...")
player.play()

try:
    while True:
        state = player.get_state()
        
        # 1. Loop corto mientras el toggle está activo
        if estado_loop_corto:
            current_time = player.get_time()

            if esperando_seek:
                if current_time < 0:
                    pass
                elif current_time <= INICIO_LOOP_MS + TOLERANCIA_MS:
                    esperando_seek = False
                time.sleep(0.02)
                continue

            if current_time < 0:
                time.sleep(0.02)
                continue

            if current_time >= FIN_LOOP_MS:
                esperando_seek = True
                player.set_time(INICIO_LOOP_MS)

        # 2. Loop principal: reinicio anticipado (evita negro al llegar al final real)
        else:
            current_time = player.get_time()
            umbral = obtener_umbral_reinicio()

            if esperando_seek_principal:
                if current_time < 0:
                    pass
                elif current_time <= RESTART_MS + TOLERANCIA_MS:
                    esperando_seek_principal = False
                time.sleep(0.02)
                continue

            if (
                umbral is not None
                and current_time >= 0
                and current_time >= umbral
            ):
                esperando_seek_principal = True
                logger.info(
                    f"Loop principal: reinicio anticipado ({current_time} ms "
                    f"≥ {umbral} ms) → {RESTART_MS} ms."
                )
                player.set_time(RESTART_MS)

            # Respaldo por si igual llega a Ended (p. ej. umbral mal configurado)
            elif state == vlc.State.Ended:
                ahora = time.monotonic()
                if ahora - ultimo_reintento_fin >= 0.5:
                    ultimo_reintento_fin = ahora
                    logger.warning(
                        f"Video en Ended; reinicio de respaldo a {RESTART_MS} ms."
                    )
                    ir_a_tiempo(RESTART_MS)

        time.sleep(0.05)

except KeyboardInterrupt:
    logger.info("Interrupción por teclado detectada. Deteniendo reproducción y saliendo...")
    player.stop()
    logger.info("Programa finalizado.")
