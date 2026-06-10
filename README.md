# video-player v1.3

Reproductor de video para **Raspberry Pi 5**: VLC en loop continuo, control por GPIO (tramo corto y reinicio), arranque automático con systemd. Pensado para kiosk con HDMI.

**Repositorio:** [github.com/sector7gp/video-player](https://github.com/sector7gp/video-player)

## Versión 1.3 — Resumen

| Elemento | Valor |
|----------|--------|
| Plataforma | Raspberry Pi 5, `lgpio` (chip 0) |
| Proyecto en la Pi | `/home/video1/video-player` |
| Video | `/media/video1.mp4` |
| Loop corto | 14,0 s → 14,5 s (toggle GPIO23) |
| Reinicio GPIO24 | Seek a 20 ms |
| Loop principal | Reinicio anticipado en `loop_principal.fin_ms` (sin esperar al final) |
| Configuración | `config.json` (ruta del video + tiempos de loop) |
| Audio | `hdmi` (default) o `externa` (`AUDIO_SALIDA`) |
| Servicio | `video-control.service` → `multi-user.target` |

## Características

- Reproducción en bucle del MP4 (`--input-repeat=-1` en instancia y medio).
- **GPIO23** — pulsar y soltar: activa/desactiva loop en el tramo; al desactivar restaura la posición guardada.
- **GPIO24** — pulsar y soltar: reinicio rápido a `RESTART_MS` (20 ms).
- Loop principal: al llegar a `REINICIO_LOOP_MS` vuelve a `RESTART_MS` antes del final (evita pantalla negra del buffer).
- Antirebote hardware (50 ms) y software (400 ms entre pulsaciones).
- Log en `control.log` dentro del directorio del proyecto.
- Al arrancar, registra duración y especificaciones del video (codec, resolución, fps, audio).
- **Audio:** salida por **HDMI** o **placa externa** (USB/HAT) vía ALSA, configurable.

## Requisitos

- Raspberry Pi 5
- Raspberry Pi OS con VLC y Python 3
- HDMI conectado; MP4 en `/media/video1.mp4`
- Dos botones entre GPIO y **GND** (pull-up interno en firmware)

```bash
sudo apt update
sudo apt install -y vlc python3-vlc python3-lgpio git
sudo usermod -aG video,render,input,gpio video1
```

(Reiniciar sesión o la Pi tras `usermod`.)

## Instalación rápida

```bash
git clone https://github.com/sector7gp/video-player.git /home/video1/video-player
# Copiar o enlazar el video:
# sudo cp /ruta/origen.mp4 /media/video1.mp4

cd /home/video1/video-player
sudo bash deploy/install-service.sh video1
sudo reboot
```

## Cableado

| GPIO | Función |
|------|---------|
| **23** | Toggle loop 14 s – 14,5 s |
| **24** | Reinicio al inicio (20 ms) |

Conexión: un lado del botón al GPIO, el otro a **GND**.

## Uso

### Manual

```bash
cd /home/video1/video-player
python3 video_control.py
```

### Botones

| Botón | Acción |
|-------|--------|
| GPIO23 | Pulsar y soltar → entra/sale del loop corto |
| GPIO24 | Pulsar y soltar → vuelve a 20 ms del video |

### Servicio systemd

```bash
sudo systemctl status video-control.service
journalctl -u video-control.service -f
tail -f /home/video1/video-player/control.log
```

El unit (`deploy/video-control.service`) arranca sin escritorio: espera `/dev/dri/card0`, `WorkingDirectory` y script en `video-player/`.

## Configuración

### `config.json`

Editar `config.json` en el directorio del proyecto:

```json
{
  "video": {
    "path": "/media/video1.mp4"
  },
  "loop_corto": {
    "inicio_ms": 14000,
    "fin_ms": 14500
  },
  "loop_principal": {
    "inicio_ms": 20,
    "fin_ms": 0,
    "margen_antes_fin_ms": 400
  }
}
```

| Campo | Default | Descripción |
|-------|---------|-------------|
| `video.path` | `/media/video1.mp4` | Archivo de video |
| `loop_corto.inicio_ms` | `14000` | Inicio del tramo GPIO23 (ms) |
| `loop_corto.fin_ms` | `14500` | Fin del tramo GPIO23 (ms) |
| `loop_principal.inicio_ms` | `20` | Posición de reinicio (GPIO24 y loop principal) |
| `loop_principal.fin_ms` | `0` | Umbral de reinicio anticipado; `0` = duración − margen |
| `loop_principal.margen_antes_fin_ms` | `400` | Margen antes del final si `fin_ms` es `0` |

Ruta alternativa del archivo: variable de entorno `CONFIG_PATH`.

Tras cambios en `config.json`: `sudo systemctl restart video-control.service`.

### Logs al arranque

Al iniciar el servicio, `control.log` y journalctl muestran la config cargada y las especificaciones del video:

```
INFO - Config cargada: video=/media/video1.mp4 | loop corto 14000-14500 ms | reinicio a 20 ms | umbral fin auto (margen 400 ms)
INFO - Video: /media/video1.mp4
INFO - Duración: 180432 ms (3:00)
INFO - Pista video: HEVC 3840x2160 @ 30.00 fps
INFO - Pista audio: MPEG AAC 48000 Hz, 2 canales
INFO - VLC inicializado con el video: /media/video1.mp4
```

### Audio y GPIO (en `video_control.py` o variables de entorno)

| Constante / variable | Default | Descripción |
|----------------------|---------|-------------|
| `GPIO_LOOP` | `23` | Pin loop |
| `GPIO_REINICIO` | `24` | Pin reinicio |
| `AUDIO_SALIDA` | `hdmi` | `hdmi` o `externa` |
| `ALSA_HDMI` | `plughw:CARD=vc4hdmi0,DEV=0` | Dispositivo ALSA para HDMI |
| `ALSA_EXTERNA` | `plughw:1,0` | Dispositivo ALSA para placa externa |
| `DEBOUNCE_TOGGLE_S` | `0.40` | Antirebote software (s) |
| `PULSO_MINIMO_S` | `0.05` | Pulso mínimo válido (s) |

Tras cambios en el script: `sudo systemctl restart video-control.service`.

## Audio (HDMI o placa externa)

Por defecto el sonido sale por **HDMI** (`AUDIO_SALIDA = "hdmi"`).

### Usar placa de audio externa

1. Conectá la placa (USB o HAT) y listá dispositivos:

```bash
aplay -l
```

2. Probá el dispositivo (ej. tarjeta 1):

```bash
speaker-test -D plughw:1,0 -c2 -t wav
```

3. En `video_control.py`:

```python
AUDIO_SALIDA = "externa"
ALSA_EXTERNA = "plughw:1,0"   # ajustar según aplay -l
```

O con variables de entorno (sin editar el script), en el servicio systemd:

```ini
Environment=AUDIO_SALIDA=externa
Environment=ALSA_EXTERNA=plughw:1,0
```

4. Reiniciá el servicio:

```bash
sudo systemctl restart video-control.service
```

En `control.log` debe aparecer: `Audio: placa externa (plughw:1,0)`.

Si HDMI no suena en Pi 5, probá otro nombre de tarjeta, p. ej. `plughw:CARD=vc4hdmi1,DEV=0` en `ALSA_HDMI`.

## Cómo funciona el reinicio

- **Loop principal:** cuando `get_time() >= loop_principal.fin_ms`, hace `set_time(loop_principal.inicio_ms)` sin esperar al final del MP4 (evita el negro del buffer).
- Con `loop_principal.fin_ms = 0`, el umbral se calcula solo: `duración del video − margen_antes_fin_ms`.
- **GPIO24 / seek manual:** `ir_a_tiempo(ms)` — seek rápido; si VLC está `Ended`, `stop()` breve y `play()`.
- **Respaldo:** si igual llega a `Ended`, reinicio con `ir_a_tiempo(loop_principal.inicio_ms)`.

VLC se inicializa de forma mínima (`vlc.Instance('--input-repeat=-1')`).

## Estructura del repositorio

```
video-player/
├── video_control.py      # Programa principal (v1.3)
├── config.json           # Ruta del video y tiempos de loop
├── VERSION               # 1.3.0
├── README.md
└── deploy/
    ├── video-control.service
    └── install-service.sh
```

## Notas

- MP4 **H.264** o **H.265**; 4K exige buena refrigeración y alimentación en Pi 5.
- Si usás **X11** (`DISPLAY=:0`), adaptá el `.service` localmente; la v1.0 por defecto es headless/DRM.

## Changelog

### v1.3.0 (2026-06-09)

- Configuración en `config.json`: ruta del video, loop corto y loop principal.
- Al arrancar, log de duración y especificaciones del video (codec, resolución, fps, audio).
- Variable de entorno `CONFIG_PATH` para ruta alternativa del JSON.

### v1.2.0 (2026-06-04)

- Audio configurable: `AUDIO_SALIDA` = `hdmi` o `externa` (ALSA en VLC).
- Variables `ALSA_HDMI` / `ALSA_EXTERNA` y ejemplos en el servicio systemd.

### v1.1.0 (2026-06-04)

- Eliminado `player.py` (referencia obsoleta; solo `video_control.py`).
- **Loop principal anticipado:** `REINICIO_LOOP_MS` reinicia en `RESTART_MS` antes del final del MP4 (evita pantalla negra del buffer).
- Modo automático: `REINICIO_LOOP_MS = 0` usa `duración − MARGEN_ANTES_FIN_MS`.
- Respaldo si VLC llega igual a `Ended` (umbral mal configurado).

### v1.0.0 (2026-06-04)

Primera versión estable.

- GPIO23: loop corto por toggle con posición guardada.
- GPIO24: reinicio rápido a 20 ms.
- Reinicio automático al fin del video (estado `Ended`).
- Rutas: proyecto en `/home/video1/video-player`, video en `/media/video1.mp4`.
- Servicio systemd e instalador `deploy/install-service.sh`.
- Logging a `control.log`.

## Licencia

Uso libre para el proyecto del autor; sin garantía.
