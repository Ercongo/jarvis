#!/bin/bash
# Preferencias del navegador del asistente:
#  - siempre: que YouTube y TikTok suenen solos cuando el asistente los abre;
#  - solo si la gráfica lo necesita (AMD antiguas con el controlador «radeon», como la ARUBA del primer portátil, que
#    se cuelgan cuando Firefox dibuja con ellas): dibujar con el procesador. Lo detecta core-orchestrator/equipo.py.
J="${JARVIS_INSTALACION:-$HOME/jarvis}"
M="${JARVIS_MOTOR:-$J/core-orchestrator}"
PY="$J/venv/bin/python"; [ -x "$PY" ] || PY=python3
SIN_ACELERACION="${JARVIS_SIN_ACELERACION:-}"
[ -z "$SIN_ACELERACION" ] && eval "$(cd "$M" && "$PY" equipo.py --shell 2>/dev/null)"
PREFS='user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);'
if [ "$SIN_ACELERACION" = "1" ]; then
PREFS="$PREFS"'
user_pref("gfx.webrender.software", true);
user_pref("gfx.webrender.all", false);
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.canvas.accelerated", false);
user_pref("webgl.disabled", true);
user_pref("media.hardware-video-decoding.enabled", false);
user_pref("media.ffmpeg.vaapi.enabled", false);'
fi
for perfil in "$HOME/snap/firefox/common/jarvis-perfil" "$HOME"/snap/firefox/common/.mozilla/firefox/*.default* \
              "$HOME"/.mozilla/firefox/*.default*; do
    [ -d "$perfil" ] || continue
    printf '%s\n' "$PREFS" > "$perfil/user.js"
done
