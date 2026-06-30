# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

**What this is**: A Raspberry Pi 5 video kiosk player — runs MP4 files in a continuous loop with GPIO button controls and configurable audio output.

**Key files**:
- `video_control.py` — Main event loop, VLC + GPIO state machine (~930 lines)
- `deploy/video-control.service` — systemd unit for auto-start
- `deploy/install-service.sh` — Installation script

## Architecture & Control Flow

### State machine (v2.2.5)

The script runs a single infinite event loop (`video_control.py`) that monitors VLC playback and GPIO. Modes (`modo`):

| Mode | Behavior |
|------|----------|
| `presentacion` | On boot or after finale: play `CUE1 → CUE2`, pause at `CUE2` (`presentacion_en_reposo`) |
| `outro_presentacion` | Botón1 from idle: timer starts, unpause + seek `CUE3`, free play until `CUE4` |
| `sesion_a` | Loop `CUE4 → CUE5` while timer active |
| `sesion_b` | Loop `CUE6 → CUE7` while timer active (botón1 from sesión A) |
| `finale` | Timer expired: seek `CUE8`, play to `CUE9`, return to presentation |

Configuration: `config.json` (`cuepoints.cue1_ms` … `cue9_ms`, `timer_minutos`).

### Presentation pause (CUE1 → CUE2)

`ir_a_presentacion_pausada()` seeks to `CUE1`, plays forward, and `_verificar_seek_pausa()` pauses when `current_time >= CUE2`. Do **not** seek directly to `CUE2` on Pi/VLC — causes black screen.

Leaving presentation: botón1 calls `ir_a_tiempo(CUE3)` after `set_pause(0)` — VLC on Pi does not seek reliably while Paused.

### Session loops

`_loop_del_modo()` returns loop bounds per mode. `_gestionar_loop()` seeks back to loop start when `current_time >= fin`.

### Button debouncing

Two-layer approach:
1. **Hardware**: 50ms bounce time on gpiozero `Button` objects
2. **Software**: 400ms between successive presses + 50ms minimum pulse duration

GPIO23 only: `when_pressed` → `registrar_presion_boton1()` → `when_released` → `boton1_al_soltar()`.

Long press: `boton1_largo.segundos` runs shell command; `salir_app_segundos` exits app cleanly.

### Audio Configuration

The `opciones_vlc()` function builds VLC instance arguments:
- ALSA output via `--alsa-audio-device`
- Defaults to HDMI (`plughw:CARD=vc4hdmi0,DEV=0`)
- Override via environment variables (`AUDIO_SALIDA`, `ALSA_HDMI`, `ALSA_EXTERNA`) or Python constants

## Common Tasks

### Manual Testing on Pi

```bash
# Run the player directly (without systemd)
cd /home/video1/video-player
python3 video_control.py

# Watch live logs
tail -f /home/video1/video-player/control.log

# Or via journalctl (systemd)
journalctl -u video-control.service -f
```

### Modify Configuration

Edit constants at the top of `video_control.py` (lines 34–113). Restart the service:

```bash
sudo systemctl restart video-control.service
```

Or pass environment variables in the systemd unit:

```ini
[Service]
Environment=AUDIO_SALIDA=externa
Environment=ALSA_EXTERNA=plughw:1,0
```

### Install/Update on Pi

```bash
# One-time installation (creates systemd service and enables auto-start)
sudo bash deploy/install-service.sh video1

# After editing video_control.py
sudo systemctl restart video-control.service
```

### Troubleshooting

- **Video doesn't play**: Check `/dev/dri/card0` exists; systemd waits up to 30s for it.
- **Audio missing**: Run `aplay -l` to list ALSA devices; verify `ALSA_HDMI`/`ALSA_EXTERNA`.
- **Button not responding**: Check GPIO number, GND wiring, and antirebote timings.
- **Loop threshold wrong**: Set `REINICIO_LOOP_MS` explicitly or check `MARGEN_ANTES_FIN_MS` (auto-mode uses duration − margin).

## Key Design Decisions

### Why Anticipatory Restart?

VLC can freeze with a black screen if playback reaches end-of-file. Seeking 400ms before the end (or at a fixed threshold) avoids this. The backup `Ended` state handler catches misconfigured thresholds.

### Why No X11?

Headless operation reduces boot time and resource use. Video routes via DRM (`/dev/dri/card0`) → HDMI, not through X11 compositing.

### Why Two Debounce Layers?

GPIO bounce is electrical noise (≤10ms). 50ms hardware filter catches this. Software debounce (400ms) filters accidental double-presses from user interaction.

### Why Cache Restart Threshold?

Computing video duration (`player.get_length()`) blocks briefly. Caching avoids repeated I/O in the main loop.

## Environment & Dependencies

- **OS**: Raspberry Pi OS (Lite or Full)
- **Python**: 3.9+
- **Packages**: `vlc` (media server), `python3-vlc` (bindings), `python3-lgpio` (GPIO)
- **User**: Runs as unprivileged `video1` user with supplementary groups `video`, `render`, `input`, `gpio` (for GPIO access without `sudo`)
- **Service**: systemd unit `video-control.service` → `multi-user.target`

## Version & Release Notes

Current: **v2.2.5** (presentation idle at CUE2, single botón1, stable on Pi/VLC)

- **v2.2.x**: Presentation plays CUE1→CUE2 and pauses; botón2 removed; finale returns to idle presentation; VLC/Pi pause/seek fixes
- **v2.1.x**: CUE3 outro, independent session A/B cuepoints (CUE4–CUE7), timer CUE8/CUE9
- **v2.0.x**: config.json cuepoints, timer, long-press botón1, overlay
- **v1.x**: Legacy GPIO loop player (superseded)

See `README.md` for full changelog and Spanish documentation.
