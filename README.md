# video-player v1.1

Reproductor de video para **Raspberry Pi 5**: VLC en loop continuo, control por GPIO (tramo corto y reinicio), arranque automático con systemd. Pensado para kiosk con HDMI.

**Repositorio:** [github.com/sector7gp/video-player](https://github.com/sector7gp/video-player)

## Versión 1.1 — Resumen

| Elemento | Valor |
|----------|--------|
| Plataforma | Raspberry Pi 5, `lgpio` (chip 0) |
| Proyecto en la Pi | `/home/video1/video-player` |
| Video | `/media/video1.mp4` |
| Loop corto | 14,0 s → 14,5 s (toggle GPIO23) |
| Reinicio GPIO24 | Seek a 20 ms |
| Loop principal | Reinicio anticipado en `REINICIO_LOOP_MS` (sin esperar al final) |
| Servicio | `video-control.service` → `multi-user.target` |

## Características

- Reproducción en bucle del MP4 (`--input-repeat=-1` en instancia y medio).
- **GPIO23** — pulsar y soltar: activa/desactiva loop en el tramo; al desactivar restaura la posición guardada.
- **GPIO24** — pulsar y soltar: reinicio rápido a `RESTART_MS` (20 ms).
- Loop principal: al llegar a `REINICIO_LOOP_MS` vuelve a `RESTART_MS` antes del final (evita pantalla negra del buffer).
- Antirebote hardware (50 ms) y software (400 ms entre pulsaciones).
- Log en `control.log` dentro del directorio del proyecto.

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

Editar constantes al inicio de `video_control.py`:

| Constante | Default | Descripción |
|-----------|---------|-------------|
| `PATH_VIDEO` | `/media/video1.mp4` | Archivo de video |
| `GPIO_LOOP` | `23` | Pin loop |
| `GPIO_REINICIO` | `24` | Pin reinicio |
| `INICIO_LOOP_MS` | `14000` | Inicio del tramo (ms) |
| `FIN_LOOP_MS` | `14500` | Fin del tramo (ms) |
| `RESTART_MS` | `20` | Posición de reinicio (ms) |
| `REINICIO_LOOP_MS` | `0` | Tiempo (ms) para reiniciar el loop principal; `0` = fin del archivo − margen |
| `MARGEN_ANTES_FIN_MS` | `400` | Margen antes del final si `REINICIO_LOOP_MS = 0` |
| `DEBOUNCE_TOGGLE_S` | `0.40` | Antirebote software (s) |
| `PULSO_MINIMO_S` | `0.05` | Pulso mínimo válido (s) |

Tras cambios en el script: `sudo systemctl restart video-control.service`.

## Cómo funciona el reinicio

- **Loop principal:** cuando `get_time() >= REINICIO_LOOP_MS`, hace `set_time(RESTART_MS)` sin esperar al final del MP4 (evita el negro del buffer).
- Con `REINICIO_LOOP_MS = 0`, el umbral se calcula solo: `duración del video − MARGEN_ANTES_FIN_MS`.
- **GPIO24 / seek manual:** `ir_a_tiempo(ms)` — seek rápido; si VLC está `Ended`, `stop()` breve y `play()`.
- **Respaldo:** si igual llega a `Ended`, reinicio con `ir_a_tiempo(RESTART_MS)`.

VLC se inicializa de forma mínima (`vlc.Instance('--input-repeat=-1')`), compatible con la referencia `player.py`.

## Estructura del repositorio

```
video-player/
├── video_control.py      # Programa principal (v1.1)
├── player.py             # Referencia mínima (desarrollo)
├── VERSION               # 1.1.0
├── README.md
└── deploy/
    ├── video-control.service
    └── install-service.sh
```

## Notas

- MP4 **H.264** o **H.265**; 4K exige buena refrigeración y alimentación en Pi 5.
- Si usás **X11** (`DISPLAY=:0`), adaptá el `.service` localmente; la v1.0 por defecto es headless/DRM.

## Changelog

### v1.1.0 (2026-06-04)

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
