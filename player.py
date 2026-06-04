import vlc
import time
from gpiozero import Button
from gpiozero.pins.lgpio import LGPIOFactory

# Configuración específica para Raspberry Pi 5
# Usamos el chip 0 que es donde residen los GPIO de usuario en la Pi 5
factory = LGPIOFactory(chip=0)
# pull_up=True: el pin está en HIGH por defecto.
# bounce_time=0.05: filtra el ruido de los contactos mecánicos (antirrebote)
boton = Button(18, pull_up=True, pin_factory=factory, bounce_time=0.05)

# Ruta de tu video 4K (Se recomienda formato .mp4 con codec H.265)
PATH_VIDEO = "/media/video1.mp4"

# Inicializar VLC
instance = vlc.Instance('--input-repeat=0')
player = instance.media_player_new()
media = instance.media_new(PATH_VIDEO)
player.set_media(media)

# Variables de control para el loop corto (segundo 15 al 17)
estado_loop_corto = False
INICIO_LOOP_MS = 15000  # 15 segundos
FIN_LOOP_MS = 15300     # 17 segundos (2 segundos de duración)

def iniciar_loop():
    global estado_loop_corto
    print("GPIO18 conectado a GND. Yendo al segundo 15 y activando bucle de 2 segundos...")
    estado_loop_corto = True
    player.set_time(INICIO_LOOP_MS)

def detener_loop():
    global estado_loop_corto
    print("GPIO18 en HIGH. Desactivando bucle y continuando reproducción normal...")
    estado_loop_corto = False

# Al conectar a GND (LOW) -> Se activa el loop corto
boton.when_pressed = iniciar_loop

# Al volver a HIGH (desconectado de GND) -> Vuelve a reproducción normal
boton.when_released = detener_loop

print("Iniciando reproducción...")
player.play()

try:
    while True:
        if estado_loop_corto:
            current_time = player.get_time()
            # Si el tiempo actual supera el límite del bucle (17s), volvemos al segundo 15
            if current_time >= FIN_LOOP_MS:
                player.set_time(INICIO_LOOP_MS)
                # Pequeña pausa para permitir que el reproductor procese el seek antes de la siguiente lectura
                time.sleep(0.1)
        
        # Frecuencia de muestreo rápida (50ms) para detectar el límite del loop con precisión sin consumir CPU
        time.sleep(0.05)

except KeyboardInterrupt:
    player.stop()
    print("Programa finalizado.")