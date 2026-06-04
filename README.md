# video-player

Reproductor de video en **Raspberry Pi 5** con **VLC** y control por **GPIO**: loop corto en un tramo del video (toggle) y reinicio rápido al inicio. Pensado para kiosk / instalación con HDMI.

Repositorio: [github.com/sector7gp/video-player](https://github.com/sector7gp/video-player)

## Características

- Reproducción continua de un MP4 (loop nativo VLC con `--input-repeat=-1`).
- **GPIO23**: toggle — pulsar y soltar activa/desactiva un loop entre dos marcas de tiempo; al desactivar vuelve a la posición donde estaba.
- **GPIO24**: reinicio rápido por seek a `RESTART_MS` (sin pantalla negra en reproducción normal).
- **Fin del video**: si VLC entra en estado `Ended`, reinicio automático a `RESTART_MS` (con `stop()` breve solo en ese caso).
- Antirebote hardware (gpiozero) y software en los botones.
- Log en consola y en `control.log` junto al script.
- Servicio **systemd** opcional para arranque al boot (`deploy/`).

## Requisitos

- Raspberry Pi 5 (GPIO vía `lgpio`)
- Raspberry Pi OS con VLC y Python 3
- Video en disco (por defecto `/media/video1.mp4`)
- Botones a **GND** (pull-up interno en los pines)

### Paquetes

```bash
sudo apt update
sudo apt install -y vlc python3-vlc python3-lgpio
```

El usuario que ejecuta el script debe poder usar GPIO y video (p. ej. `video1`):

```bash
sudo usermod -aG video,render,input,gpio video1
```

## Cableado GPIO

| Pin BCM | Función | Conexión |
|---------|---------|----------|
| **23** | Loop corto (toggle) | Un terminal del botón a GPIO23, el otro a **GND** |
| **24** | Reinicio | Igual: GPIO24 ↔ GND |

No hace falta resistencia externa si usás `pull_up=True` en el código.

## Uso manual

```bash
cd /home/video1/video-player
python3 video_control.py
```

### Botones

| Acción | Comportamiento |
|--------|----------------|
| **GPIO23** — pulsar y soltar | Activa loop en el tramo configurado; otro pulso lo desactiva y restaura la posición guardada |
| **GPIO24** — pulsar y soltar | Seek rápido a `RESTART_MS` (por defecto 20 ms desde el inicio) |

### Reinicio y loop del archivo completo

La función `ir_a_tiempo(ms)` hace un **seek directo** mientras el video está reproduciendo (GPIO23/24, loop corto). Si el reproductor está en **`Ended`** o **`Stopped`** (p. ej. al terminar el MP4), primero ejecuta un `stop()` de ~30 ms y luego `set_time` + `play()` para salir del estado congelado.

Además, VLC tiene repetición en dos niveles:

- Instancia: `--input-repeat=-1`
- Medio: `:input-repeat=-1`

Si igual llega a `Ended`, el bucle principal del script reinicia en `RESTART_MS` como respaldo.

## Configuración (`video_control.py`)

| Constante | Default | Descripción |
|-----------|---------|-------------|
| `PATH_VIDEO` | `/media/video1.mp4` | Archivo de video |
| `GPIO_LOOP` | `23` | Pin del loop |
| `GPIO_REINICIO` | `24` | Pin de reinicio |
| `INICIO_LOOP_MS` | `14000` | Inicio del tramo de loop (ms) |
| `FIN_LOOP_MS` | `14500` | Fin del tramo de loop (ms) |
| `RESTART_MS` | `20` | Posición de reinicio (ms) |
| `DEBOUNCE_TOGGLE_S` | `0.40` | Antirebote software entre pulsaciones |
| `PULSO_MINIMO_S` | `0.05` | Duración mínima válida de pulsación |

## Arranque automático (systemd)

1. Cloná el repo en la Pi:

```bash
git clone https://github.com/sector7gp/video-player.git /home/video1/video-player
```

2. Colocá el MP4 en `/media/video1.mp4` (o cambiá `PATH_VIDEO` en `video_control.py`).
3. Instalá el servicio (ajusta el usuario si no es `video1`):

```bash
cd /home/video1/video-player
sudo bash deploy/install-service.sh video1
sudo reboot
```

Comandos útiles:

```bash
sudo systemctl status video-control.service
journalctl -u video-control.service -f
tail -f /home/video1/video-player/control.log
```

El unit en `deploy/` está orientado a arranque **sin escritorio** (`multi-user.target`, espera `/dev/dri/card0`). Si tu instalación usa **X11** y `DISPLAY=:0`, adaptá el `.service` localmente (no incluido por defecto en el repo).

## Archivos del repositorio

| Archivo | Descripción |
|---------|-------------|
| `video_control.py` | Programa principal (GPIO + VLC + logging) |
| `player.py` | Versión mínima de referencia (solo loop manteniendo GPIO18) |
| `deploy/video-control.service` | Unit systemd |
| `deploy/install-service.sh` | Instala y habilita el servicio |

## Notas

- Se recomienda MP4 con **H.265** o **H.264**; 4K en Pi 5 puede requerir buen cooling y alimentación.
- El loop corto usa `set_time()` al llegar a `FIN_LOOP_MS` (mismo criterio que el reinicio rápido).
- Si VLC falla al crear salida de video, evitá forzar `--vout=drm` en Python: la configuración actual usa solo `vlc.Instance('--input-repeat=-1')`, igual que `player.py`.

## Historial de cambios

### 2026-06-04 (rutas)

- Proyecto en `/home/video1/video-player`; video en `/media/video1.mp4`.
- `video-control.service` e `install-service.sh` alineados (sin duplicar ruta en el `sed`).

### 2026-06-04

- **Fix fin de video congelado**: en estado `Ended`, `set_time()` solo no reinicia; `ir_a_tiempo()` hace `stop()` + `play()` solo si el estado es `Ended`/`Stopped`.
- **Repetición VLC**: añadido `:input-repeat=-1` en el objeto `media` además de la instancia.
- **Reintento al terminar**: el bucle principal reintenta cada 0,5 s (antes 1 s) si el video finaliza.
- **GPIO23 / GPIO24**, toggle de loop, reinicio a 20 ms, VLC minimal (sin `vout=drm`), documentación y `deploy/` (commits anteriores en el repo).

## Licencia

Uso libre para el proyecto del autor; sin garantía.
