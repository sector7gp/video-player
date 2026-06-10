# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Reference

**What this is**: A Raspberry Pi 5 video kiosk player — runs MP4 files in a continuous loop with GPIO button controls and configurable audio output.

**Key files**:
- `video_control.py` — Main event loop and control logic (276 lines)
- `deploy/video-control.service` — systemd unit for auto-start
- `deploy/install-service.sh` — Installation script

## Architecture & Control Flow

### Main Loop (video_control.py:242–300)

The script runs a single infinite event loop that monitors VLC playback state and manages two concurrent control patterns:

1. **Short Loop Mode** (GPIO23 toggle): When `estado_loop_corto=True`, repeatedly seek between `INICIO_LOOP_MS` (14s) and `FIN_LOOP_MS` (14.5s). The loop saves the playback position before entering and restores it on exit.

2. **Main Loop Mode** (default): Anticipatory restart — when playback reaches `umbral_reinicio()` (calculated as video duration minus `MARGEN_ANTES_FIN_MS`), seek to `RESTART_MS` *before* the file ends. This avoids VLC's buffer black-screen artifact. Fallback: if VLC still reaches `Ended` state, force restart via `ir_a_tiempo()`.

### State Management

Key global variables track:
- `estado_loop_corto` — Is short loop active?
- `posicion_guardada_ms` — Playback position to restore after short loop
- `esperando_seek` / `esperando_seek_principal` — Debounce flags during seeks (wait for playback to catch up before checking position)
- `umbral_reinicio_cache` — Cached restart threshold (computed once from video duration)

### Button Debouncing

Two-layer approach:
1. **Hardware**: 50ms bounce time on gpiozero `Button` objects
2. **Software**: 400ms `DEBOUNCE_TOGGLE_S` between successive presses + 50ms `PULSO_MINIMO_S` minimum pulse duration

GPIO23 callback chain: `when_pressed` → `registrar_presion_loop()` (record timestamp) → `when_released` → `alternar_loop_al_soltar()` (validate timing, toggle state).

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

Current: **v1.2.0** (configurable audio output via ALSA)

- **v1.1.0**: Anticipatory main loop restart
- **v1.0.0**: Initial stable release (GPIO + loop)

See `README.md` for full changelog and Spanish documentation.
