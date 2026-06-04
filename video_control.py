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

logger.info("Iniciando programa de control de video...")

# GPIO (Raspberry Pi 5, chip 0) — pull-up interno, botón a GND
GPIO_LOOP = 23       # toggle loop corto 14s–14.5s
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

# Ruta de tu video 4K (Se recomienda formato .mp4 con codec H.265)
PATH_VIDEO = "/media/video1.mp4"

# Reinicio rápido (seek, sin stop/set_media — evita pantalla negra)
RESTART_MS = 20

# Inicializar VLC — igual que player.py (sin vout=drm ni opciones extra)
try:
    instance = vlc.Instance('--input-repeat=-1')
    player = instance.media_player_new()
    media = instance.media_new(PATH_VIDEO)
    media.add_option(':input-repeat=-1')
    player.set_media(media)
    logger.info(f"VLC inicializado con el video: {PATH_VIDEO}")
except Exception as e:
    logger.error(f"Error al inicializar VLC: {e}")
    sys.exit(1)

# Loop corto por toggle del botón (configurable)
INICIO_LOOP_MS = 14000   # inicio del tramo (14 s)
FIN_LOOP_MS = 14500      # fin del tramo (14.5 s) → 500 ms de loop
TOLERANCIA_MS = 80
# Antirebote software: tiempo mínimo entre toggles y pulso válido
DEBOUNCE_TOGGLE_S = 0.40
PULSO_MINIMO_S = 0.05

estado_loop_corto = False
posicion_guardada_ms = None
esperando_seek = False
ultimo_reintento_fin = 0.0
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

        # 2. Si el video termina, VLC queda en Ended: hace falta stop+play
        elif state == vlc.State.Ended:
            ahora = time.monotonic()
            if ahora - ultimo_reintento_fin >= 0.5:
                ultimo_reintento_fin = ahora
                logger.info(
                    f"Video finalizado. Reiniciando en {RESTART_MS} ms (loop principal)..."
                )
                ir_a_tiempo(RESTART_MS)

        time.sleep(0.05)

except KeyboardInterrupt:
    logger.info("Interrupción por teclado detectada. Deteniendo reproducción y saliendo...")
    player.stop()
    logger.info("Programa finalizado.")
